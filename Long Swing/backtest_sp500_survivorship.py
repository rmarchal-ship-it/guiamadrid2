#!/usr/bin/env python3
"""
Long Swing — Survivorship-bias-free backtest using historical SP500 constituents.

Uses Wikipedia's SP500 changes table to reconstruct who was in the index at each
point in time. Then runs the standard Long Swing strategy on that point-in-time
universe instead of the fixed 76-ticker universe.

This is the "prueba de fuego" — if the strategy works on historical constituents
(including companies that were later removed/delisted), it's robust.
"""
import sys
import io
import json
import time
import requests
import warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import pandas_ta as ta

from long_swing.data import download_eodhd
from long_swing.config import (
    TUNED_RSI, BEST_EMA, MAX_POS, RESERVE_PCT, COST_BPS, INITIAL,
    PYR_THRESHOLD, PYR_SIZE, EMA_EXIT_FAST, EMA_EXIT_SLOW, GRACE_BARS,
    MACRO_FILTER, VIX_MAX,
)
from trading.signals import rsi_reversal_macd_entry, ema_cross_entry

CACHE_DIR = Path(__file__).resolve().parent / "data_cache"
SP500_CACHE = Path(__file__).resolve().parent / "sp500_constituents.json"


# ── SP500 Historical Constituents ────────────────────────────────────────

def fetch_sp500_changes():
    """Fetch SP500 addition/removal history from Wikipedia."""
    headers = {"User-Agent": "Mozilla/5.0 (research bot)"}
    r = requests.get(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        headers=headers, timeout=30,
    )
    tables = pd.read_html(io.StringIO(r.text))

    # Current components
    current = sorted(tables[0]["Symbol"].tolist())

    # Changes history
    changes = tables[1]
    changes.columns = ["date", "added_ticker", "added_name",
                       "removed_ticker", "removed_name", "reason"]
    changes["date"] = pd.to_datetime(changes["date"], format="mixed")
    changes = changes.sort_values("date").reset_index(drop=True)

    return current, changes


def build_point_in_time_universe(current, changes, start_date):
    """
    Reconstruct SP500 membership at start_date by reversing changes.

    Starting from current members, walk backwards through changes:
    - If a ticker was ADDED after start_date → remove it (wasn't there yet)
    - If a ticker was REMOVED after start_date → add it back (was still there)
    """
    members = set(current)

    # Process changes in reverse chronological order
    for _, row in changes.sort_values("date", ascending=False).iterrows():
        change_date = row["date"]
        if pd.isna(change_date) or change_date <= pd.Timestamp(start_date):
            break

        added = str(row["added_ticker"]).strip()
        removed = str(row["removed_ticker"]).strip()

        # Reverse the addition
        if added and added != "nan":
            members.discard(added)

        # Reverse the removal (add back)
        if removed and removed != "nan":
            members.add(removed)

    return sorted(members)


def get_universe_at_date(current, changes, target_date):
    """Get SP500 constituents at a specific date."""
    return build_point_in_time_universe(current, changes, target_date)


# ── Backtest Engine (simplified from strategy.py) ────────────────────────

_rsi_fn = rsi_reversal_macd_entry(TUNED_RSI)
_ema_fn = ema_cross_entry(BEST_EMA)


def compute_signals_for_ticker(sym, df):
    """Compute RSI+MACD and EMA cross signals for a single ticker.

    Pre-entry filter: skip signals where EMA21 < EMA50 at signal time.
    This eliminates trades that would never have EMA21 cross above EMA50,
    avoiding the grace_exit trap (-8,655€ in 18 trades with 6% WR).
    """
    signals = []

    rsi_mask = _rsi_fn(df)
    ema_mask = _ema_fn(df)

    close = df["Close"].astype(float)
    adx_series = ta.adx(df["High"].astype(float), df["Low"].astype(float), close, length=14)
    adx_col = adx_series["ADX_14"] if adx_series is not None and "ADX_14" in adx_series.columns else pd.Series(20, index=df.index)

    # EMA21/50 for pre-entry filter
    ema21 = ta.ema(close, length=EMA_EXIT_FAST)
    ema50 = ta.ema(close, length=EMA_EXIT_SLOW)

    def _ema_ok(loc):
        """Return True if EMA21 >= EMA50 at this bar (trend is up)."""
        if ema21 is None or ema50 is None:
            return True  # no data = no filter
        if loc >= len(ema21) or loc >= len(ema50):
            return True
        e21 = float(ema21.iloc[loc])
        e50 = float(ema50.iloc[loc])
        if not (np.isfinite(e21) and np.isfinite(e50)):
            return True
        return e21 >= e50

    for idx in df.index[rsi_mask == 1]:
        loc = df.index.get_loc(idx)
        if loc + 1 < len(df) and _ema_ok(loc):
            entry_idx = loc + 1
            entry_ts = df.index[entry_idx]
            entry_px = float(df["Open"].iloc[entry_idx])
            adx_val = float(adx_col.iloc[loc]) if loc < len(adx_col) else 20
            signals.append({
                "symbol": sym, "signal": "rsi_macd",
                "entry_ts": entry_ts, "entry_px": entry_px,
                "adx": adx_val, "score": adx_val,
            })

    for idx in df.index[ema_mask == 1]:
        loc = df.index.get_loc(idx)
        if loc + 1 < len(df) and _ema_ok(loc):
            entry_idx = loc + 1
            entry_ts = df.index[entry_idx]
            entry_px = float(df["Open"].iloc[entry_idx])
            adx_val = float(adx_col.iloc[loc]) if loc < len(adx_col) else 20
            signals.append({
                "symbol": sym, "signal": "ema_cross",
                "entry_ts": entry_ts, "entry_px": entry_px,
                "adx": adx_val, "score": adx_val,
            })

    return signals


def compute_exit(df, entry_idx):
    """Compute exit using EMA21<EMA50 cross with grace period.

    Exit signal detected at Close of day j → exit at Open of day j+1.
    This avoids look-ahead: we can't know EMA cross until Close,
    so the earliest executable exit is next Open.
    Returns (exit_bar_idx, reason) where exit_bar uses Open price.
    """
    close = df["Close"].astype(float)
    ema21 = ta.ema(close, length=EMA_EXIT_FAST)
    ema50 = ta.ema(close, length=EMA_EXIT_SLOW)

    ema_was_above = False
    for j in range(entry_idx, len(df)):
        bars = j - entry_idx
        if ema21 is not None and ema50 is not None:
            e21 = float(ema21.iloc[j]) if j < len(ema21) else np.nan
            e50 = float(ema50.iloc[j]) if j < len(ema50) else np.nan
            if np.isfinite(e21) and np.isfinite(e50):
                if e21 >= e50:
                    ema_was_above = True
                elif ema_was_above and e21 < e50:
                    # Signal at Close day j → exit at Open day j+1
                    exit_bar = j + 1 if j + 1 < len(df) else j
                    return exit_bar, "ema_cross"
                elif not ema_was_above and bars >= GRACE_BARS:
                    exit_bar = j + 1 if j + 1 < len(df) else j
                    return exit_bar, "grace_exit"

    return len(df) - 1, "end_of_data"


def run_backtest(lookback_months, verbose=True):
    """Run survivorship-bias-free backtest."""
    lookback_days = int(lookback_months * 30.44)

    print(f"\n{'='*80}")
    print(f"  LONG SWING — SP500 Survivorship-Free Backtest | {lookback_months}m")
    print(f"{'='*80}")

    # 1. Get SP500 historical data
    print("\n  Fetching SP500 constituent history...")
    current, changes = fetch_sp500_changes()

    start_date = datetime.now() - timedelta(days=lookback_days)
    universe_start = get_universe_at_date(current, changes, start_date)
    universe_end = current

    # Union of all tickers that were ever in SP500 during the period
    all_tickers_in_period = set(universe_start)
    for _, row in changes.iterrows():
        if pd.isna(row["date"]):
            continue
        if row["date"] >= pd.Timestamp(start_date):
            added = str(row["added_ticker"]).strip()
            removed = str(row["removed_ticker"]).strip()
            if added and added != "nan":
                all_tickers_in_period.add(added)
            if removed and removed != "nan":
                all_tickers_in_period.add(removed)

    # ETFs with liquid futures — no survivorship bias, always included & always tradeable
    ETFS_WITH_FUTURES = {"SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "USO", "TLT", "IEF", "BTC-USD"}
    always_include = {"SPY"}  # SPY for macro context only — ETFs proven to dilute alpha
    all_tickers = sorted(all_tickers_in_period | always_include)

    print(f"  SP500 at start ({start_date.date()}): {len(universe_start)} members")
    print(f"  SP500 at end (today): {len(universe_end)} members")
    print(f"  ETFs with futures (always tradeable): {len(ETFS_WITH_FUTURES)}")
    print(f"  Total tickers to scan: {len(all_tickers)}")

    # 2. Download data for all tickers (with parquet cache)
    sp500_cache_dir = CACHE_DIR / "sp500"
    sp500_cache_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n  Downloading {len(all_tickers)} tickers from EODHD (cache: {sp500_cache_dir})...")
    all_data = {}
    failed = []
    cached_count = downloaded_count = 0

    for i, sym in enumerate(all_tickers, 1):
        sym_safe = sym.replace('.', '_')
        cache_path = sp500_cache_dir / f"{sym_safe}_{lookback_days}d.parquet"

        # Try exact cache first
        if cache_path.exists():
            try:
                df = pd.read_parquet(cache_path)
                if len(df) >= 100:
                    all_data[sym] = df
                    cached_count += 1
                    continue
            except Exception:
                pass

        # Try longer cache and trim (reuse 120m/240m cache for shorter periods)
        found_longer = False
        for longer_file in sorted(sp500_cache_dir.glob(f"{sym_safe}_*d.parquet"), reverse=True):
            try:
                df = pd.read_parquet(longer_file)
                if len(df) >= 100:
                    # Trim to requested period
                    cutoff = pd.Timestamp.now(tz=df.index.tz) - pd.Timedelta(days=lookback_days + 60)
                    df = df[df.index >= cutoff]
                    if len(df) >= 100:
                        all_data[sym] = df
                        cached_count += 1
                        found_longer = True
                        break
            except Exception:
                pass
        if found_longer:
            continue

        # Download
        df = download_eodhd(sym, lookback_days + 60)
        if df is not None and len(df) >= 100:
            all_data[sym] = df
            downloaded_count += 1
            try:
                df.to_parquet(cache_path)
            except Exception:
                pass
        else:
            failed.append(sym)

        if verbose and (downloaded_count + len(failed)) % 50 == 0:
            print(f"    [{i}/{len(all_tickers)}] downloaded...", flush=True)

    print(f"  Data: {cached_count} cached + {downloaded_count} downloaded + {len(failed)} failed = {len(all_data)} tickers")
    if failed and verbose:
        print(f"  Failed: {failed[:20]}{'...' if len(failed) > 20 else ''}")

    # 2b. Liquidity filter: POINT-IN-TIME rolling 252-day dollar volume per ticker
    #     Instead of pre-filtering, we compute the series and check at signal time.
    MIN_DOLLAR_VOL = 1_000_000_000  # $1 billion daily dollar volume
    dollar_vol_series = {}  # sym → pd.Series of rolling avg dollar vol
    liquid_ever = set()
    for sym, df in all_data.items():
        try:
            close = df["Close"].astype(float)
            volume = df["Volume"].astype(float)
            dv = (close * volume).rolling(252, min_periods=50).mean()
            dollar_vol_series[sym] = dv
            if dv.max() >= MIN_DOLLAR_VOL:
                liquid_ever.add(sym)
        except Exception:
            pass

    # Always keep SPY for macro context
    liquid_ever |= {"SPY"}
    print(f"  Liquidity filter (point-in-time >${MIN_DOLLAR_VOL/1e9:.0f}B dollar vol): {len(liquid_ever)} tickers ever qualify")

    # 3. Build change timeline for point-in-time filtering
    change_dates = []
    for _, row in changes.iterrows():
        if pd.isna(row["date"]):
            continue
        dt = row["date"]
        if dt >= pd.Timestamp(start_date):
            change_dates.append({
                "date": dt,
                "added": str(row["added_ticker"]).strip(),
                "removed": str(row["removed_ticker"]).strip(),
            })
    change_dates.sort(key=lambda x: x["date"])

    # 4. Compute macro context (SPY + VIX)
    print("  Computing macro context...")
    spy_df = all_data.get("SPY")
    spy_context = {}
    if spy_df is not None:
        close = spy_df["Close"].astype(float)
        sma200 = ta.sma(close, length=200)
        high_52w = close.rolling(252, min_periods=50).max()
        pct_from_high = ((close - high_52w) / high_52w * 100)
        for dt in spy_df.index:
            spy_context[dt.date() if hasattr(dt, 'date') else dt] = {
                "spy_above_sma200": 1 if (sma200 is not None and dt in sma200.index
                                          and close[dt] > sma200[dt]) else 0,
                "spy_pct_from_high": float(pct_from_high.get(dt, 0)),
            }

    vix_df = download_eodhd("^VIX", lookback_days + 60)
    vix_map = {}
    if vix_df is not None:
        for dt in vix_df.index:
            vix_map[dt.date() if hasattr(dt, 'date') else dt] = float(vix_df.loc[dt, "Close"])

    # 5. Compute ALL trades for ALL tickers
    print("  Computing signals and trades...")
    all_trades = []
    liq_filtered_count = 0
    for sym, df in all_data.items():
        if sym not in liquid_ever:
            continue  # Skip tickers that NEVER had $1B — saves compute
        # Only generate signals for tickers that were ever in SP500 (not ETFs/SPY)
        if sym not in all_tickers_in_period:
            continue

        dv_series = dollar_vol_series.get(sym)
        signals = compute_signals_for_ticker(sym, df)
        for sig in signals:
            entry_ts = sig["entry_ts"]
            # Find entry index
            try:
                entry_date = entry_ts.date() if hasattr(entry_ts, 'date') else entry_ts
                mask = df.index >= pd.Timestamp(entry_ts)
                if not mask.any():
                    continue
                entry_idx = df.index.get_loc(df.index[mask][0])
            except Exception:
                continue

            # Point-in-time liquidity check: must have >$1B at signal time
            if dv_series is not None:
                # Signal fires day before entry → check liquidity at signal bar
                sig_idx = max(0, entry_idx - 1)
                sig_ts = df.index[sig_idx]
                if sig_ts in dv_series.index:
                    dv_val = dv_series[sig_ts]
                    if pd.notna(dv_val) and dv_val < MIN_DOLLAR_VOL:
                        liq_filtered_count += 1
                        continue

            exit_idx, exit_reason = compute_exit(df, entry_idx)
            exit_ts = df.index[exit_idx]
            # Exit at Open (signal was at prior Close, so next Open is executable)
            exit_px = float(df["Open"].iloc[exit_idx])
            entry_px = sig["entry_px"]
            ret = (exit_px / entry_px - 1.0) if entry_px > 0 else 0

            all_trades.append({
                "symbol": sym,
                "signal": sig["signal"],
                "entry_ts": entry_ts,
                "entry_px": entry_px,
                "exit_ts": exit_ts,
                "exit_px": exit_px,
                "exit_reason": exit_reason,
                "ret": ret,
                "adx": sig["adx"],
                "bars": exit_idx - entry_idx,
            })

    trades_df = pd.DataFrame(all_trades)
    if trades_df.empty:
        print("  No trades generated!")
        return

    trades_df = trades_df.sort_values("entry_ts").reset_index(drop=True)
    trades_df["entry_date"] = trades_df["entry_ts"].apply(
        lambda x: x.date() if hasattr(x, 'date') else x
    )
    print(f"  Total raw trades: {len(trades_df)} (filtered by point-in-time liquidity: {liq_filtered_count})")

    # 6. Select 1 signal per day (RSI priority, ADX rank) — proven optimal
    selected = []
    for date, group in trades_df.groupby("entry_date"):
        rsi = group[group["signal"] == "rsi_macd"]
        ema = group[group["signal"] == "ema_cross"]
        if not rsi.empty:
            selected.append(rsi.sort_values("adx", ascending=False).iloc[0])
        elif not ema.empty:
            selected.append(ema.sort_values("adx", ascending=False).iloc[0])

    signals_df = pd.DataFrame(selected).sort_values("entry_ts").reset_index(drop=True)
    print(f"  Selected signals (1/day): {len(signals_df)}")

    # 7. Apply macro filter
    filtered = []
    for _, sig in signals_df.iterrows():
        entry_date = sig["entry_date"]
        ctx = spy_context.get(entry_date, {})
        vix = vix_map.get(entry_date, 20)
        above_sma200 = ctx.get("spy_above_sma200", 1)

        if above_sma200 and vix < VIX_MAX:
            filtered.append(sig)

    filtered_df = pd.DataFrame(filtered)
    print(f"  After macro filter: {len(filtered_df)} signals")

    # 8. Apply point-in-time SP500 membership filter
    active_members = set(universe_start)
    change_idx = 0

    pit_filtered = []
    for _, sig in filtered_df.iterrows():
        entry_date = sig["entry_date"]
        sig_ts = pd.Timestamp(entry_date)

        # Update membership up to this date
        while change_idx < len(change_dates) and change_dates[change_idx]["date"] <= sig_ts:
            c = change_dates[change_idx]
            if c["added"] and c["added"] != "nan":
                active_members.add(c["added"])
            if c["removed"] and c["removed"] != "nan":
                active_members.discard(c["removed"])
            change_idx += 1

        # Only trade tickers that are in SP500 at this point in time, or are always_include
        if sig["symbol"] in active_members or sig["symbol"] in always_include:
            pit_filtered.append(sig)

    pit_df = pd.DataFrame(pit_filtered)
    print(f"  After point-in-time filter: {len(pit_df)} signals")

    # 9. Portfolio simulation with pyramiding (same logic as strategy.py simulate())
    print("\n  Running portfolio simulation (with pyramiding)...")
    cash = INITIAL
    positions = []
    log = []
    still_open = []
    n_pyr = 0

    for _, sig in pit_df.iterrows():
        entry_ts = sig["entry_ts"]

        # Close expired positions first
        new_positions = []
        for pos in positions:
            if entry_ts >= pos["exit_ts"]:
                total_shares = pos["shares"] + pos.get("pyr_shares", 0)
                proceeds = total_shares * pos["exit_px"]
                cost = proceeds * COST_BPS / 10000
                total_invested = pos["alloc"] + pos.get("pyr_alloc", 0)
                cash += proceeds - cost
                pnl = proceeds - total_invested - cost
                log.append({**pos, "total_shares": total_shares,
                           "total_invested": total_invested, "pnl": pnl, "closed": True})
            else:
                new_positions.append(pos)
        positions = new_positions

        # Check pyramid triggers: current price vs entry for each open position
        for pos in positions:
            if pos.get("pyramided"):
                continue
            # Use the signal's entry_px as proxy for current market price at this date
            # Better: look up actual price from data
            sym_df = all_data.get(pos["symbol"])
            if sym_df is None:
                continue
            mask = sym_df.index <= entry_ts
            if not mask.any():
                continue
            current_px = float(sym_df.loc[mask, "Close"].iloc[-1])
            pct_gain = current_px / pos["entry_px"] - 1.0

            if pct_gain >= PYR_THRESHOLD:
                pyr_alloc = pos["alloc"] * PYR_SIZE
                if pyr_alloc > cash:
                    pyr_alloc = cash
                if pyr_alloc > 50:
                    pyr_shares = pyr_alloc / current_px
                    pyr_cost = pyr_alloc * COST_BPS / 10000
                    cash -= pyr_alloc + pyr_cost
                    pos["pyramided"] = True
                    pos["pyr_shares"] = pyr_shares
                    pos["pyr_alloc"] = pyr_alloc
                    pos["pyr_px"] = current_px
                    n_pyr += 1

        # Open new position if slots available
        if len(positions) < MAX_POS:
            held_syms = {p["symbol"] for p in positions}
            if sig["symbol"] not in held_syms:
                free_slots = MAX_POS - len(positions)
                alloc = cash * (1 - RESERVE_PCT) / free_slots
                if alloc > 50:
                    shares = alloc / sig["entry_px"]
                    cost = alloc * COST_BPS / 10000
                    cash -= alloc + cost

                    positions.append({
                        "symbol": sig["symbol"],
                        "signal": sig["signal"],
                        "entry_ts": sig["entry_ts"],
                        "entry_px": sig["entry_px"],
                        "exit_ts": sig["exit_ts"],
                        "exit_px": sig["exit_px"],
                        "exit_reason": sig["exit_reason"],
                        "shares": shares,
                        "alloc": alloc,
                        "pyramided": False,
                        "pyr_shares": 0,
                        "pyr_alloc": 0,
                    })

    # Close remaining positions
    for pos in positions:
        total_shares = pos["shares"] + pos.get("pyr_shares", 0)
        proceeds = total_shares * pos["exit_px"]
        cost = proceeds * COST_BPS / 10000
        total_invested = pos["alloc"] + pos.get("pyr_alloc", 0)
        cash += proceeds - cost
        pnl = proceeds - total_invested - cost
        is_open = pos["exit_reason"] == "end_of_data"
        if is_open:
            still_open.append({**pos, "total_shares": total_shares,
                              "total_invested": total_invested, "pnl": pnl, "closed": False})
        else:
            log.append({**pos, "total_shares": total_shares,
                       "total_invested": total_invested, "pnl": pnl, "closed": True})

    print(f"  Pyramids executed: {n_pyr}")

    # 10. Results
    # All positions (including still_open) were already liquidated into cash above
    equity = cash
    fixed_years = lookback_days / 365.25
    cagr = (equity / INITIAL) ** (1 / fixed_years) - 1 if fixed_years > 0 else 0

    wins = [t for t in log if t["pnl"] > 0]
    losses = [t for t in log if t["pnl"] <= 0]
    pf = sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in losses)) if losses else 999

    # Drawdown calculation
    equity_curve = [INITIAL]
    running = INITIAL
    for t in sorted(log, key=lambda x: x["exit_ts"]):
        running += t["pnl"]
        equity_curve.append(running)
    peak = INITIAL
    max_dd = 0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (eq - peak) / peak
        if dd < max_dd:
            max_dd = dd

    # Benchmark: SPY buy & hold
    spy_start_px = float(spy_df["Close"].iloc[0]) if spy_df is not None else 1
    spy_end_px = float(spy_df["Close"].iloc[-1]) if spy_df is not None else 1
    spy_ret = (spy_end_px / spy_start_px) ** (1 / fixed_years) - 1

    print(f"\n{'='*80}")
    print(f"  RESULTADOS — SP500 Survivorship-Free | {lookback_months}m ({fixed_years:.1f} years)")
    print(f"{'='*80}")
    print(f"  Universe: SP500 point-in-time ({len(universe_start)} at start → {len(universe_end)} at end)")
    print(f"  Tickers downloaded: {len(all_data)} | Failed: {len(failed)}")
    print(f"  Capital: {INITIAL:,.0f}€ → {equity:,.0f}€")
    print(f"  CAGR: {cagr*100:+.1f}%")
    print(f"  Max DD: {max_dd*100:.1f}%")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Trades: {len(log)} ({len(wins)}W / {len(losses)}L) | WR: {len(wins)/len(log)*100:.0f}%")
    print(f"  Still open: {len(still_open)}")
    print(f"  SPY Buy&Hold CAGR: {spy_ret*100:+.1f}%")
    print(f"  Alpha vs SPY: {(cagr - spy_ret)*100:+.1f}pp")
    print(f"{'='*80}")

    # Top winners & losers
    log_sorted = sorted(log, key=lambda x: x["pnl"], reverse=True)
    print(f"\n  TOP 5 WINNERS:")
    for t in log_sorted[:5]:
        print(f"    {t['symbol']:>8s} {str(t['entry_ts'])[:10]} → {str(t['exit_ts'])[:10]} "
              f"PnL: {t['pnl']:+.0f}€  Ret: {(t['exit_px']/t['entry_px']-1)*100:+.1f}%")

    print(f"\n  TOP 5 LOSERS:")
    for t in log_sorted[-5:]:
        print(f"    {t['symbol']:>8s} {str(t['entry_ts'])[:10]} → {str(t['exit_ts'])[:10]} "
              f"PnL: {t['pnl']:+.0f}€  Ret: {(t['exit_px']/t['entry_px']-1)*100:+.1f}%")

    # Save trades to CSV — includes open trades, running equity, and return %
    results_dir = Path(__file__).resolve().parent
    trades_csv = results_dir / f"sp500_trades_{lookback_months}m.csv"
    all_log = log + still_open  # closed + open
    all_log.sort(key=lambda t: str(t.get("exit_ts", t.get("entry_ts", ""))))

    # Compute return % and cumulative PnL
    cum_pnl = 0
    for t in all_log:
        t["return_pct"] = round((t["exit_px"] / t["entry_px"] - 1) * 100, 2) if t["entry_px"] > 0 else 0
        cum_pnl += t["pnl"]
        t["cum_pnl"] = round(cum_pnl, 2)

    log_df = pd.DataFrame(all_log)
    # Reorder columns for clarity
    col_order = ["symbol", "signal", "entry_ts", "entry_px", "exit_ts", "exit_px",
                 "exit_reason", "return_pct", "shares", "alloc", "pyramided",
                 "pyr_shares", "pyr_alloc", "pyr_px", "total_shares", "total_invested",
                 "pnl", "cum_pnl", "closed"]
    col_order = [c for c in col_order if c in log_df.columns]
    log_df = log_df[col_order]
    for col in ["entry_ts", "exit_ts"]:
        if col in log_df.columns:
            log_df[col] = log_df[col].astype(str).str[:10]
    log_df.to_csv(trades_csv, index=False)
    print(f"\n  Trades saved: {trades_csv} ({len(log)} closed + {len(still_open)} open)")

    # Save summary to JSON
    results = {
        "lookback_months": lookback_months,
        "run_date": str(datetime.now().date()),
        "equity": round(equity, 2),
        "cagr": round(cagr * 100, 2),
        "max_dd": round(max_dd * 100, 2),
        "pf": round(pf, 2),
        "trades": len(log),
        "wins": len(wins),
        "losses": len(losses),
        "wr": round(len(wins) / len(log) * 100, 1),
        "spy_cagr": round(spy_ret * 100, 2),
        "alpha": round((cagr - spy_ret) * 100, 2),
        "universe_start": len(universe_start),
        "universe_end": len(universe_end),
        "tickers_downloaded": len(all_data),
        "tickers_failed": len(failed),
        "failed_tickers": failed,
    }
    summary_path = results_dir / f"sp500_results_{lookback_months}m.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Summary saved: {summary_path}")

    return results


if __name__ == "__main__":
    months = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    run_backtest(months)

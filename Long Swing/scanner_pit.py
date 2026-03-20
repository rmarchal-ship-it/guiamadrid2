"""
Long Swing — Scanner PIT (Point-In-Time SP500 universe).

Same logic as scanner.py but uses current SP500 members + $1B liquidity filter
instead of the fixed 76-ticker baseline. This is the scanner for paper trading.

Usage: uv run python -m long_swing.scanner_pit [--refresh]
"""
import sys
import io
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import pandas_ta as ta
import requests

from long_swing.data import download_eodhd
from long_swing.config import (
    TUNED_RSI, BEST_EMA, MAX_POS, RESERVE_PCT, COST_BPS,
    PYR_THRESHOLD, EMA_EXIT_FAST, EMA_EXIT_SLOW, MACRO_FILTER, VIX_MAX,
)
from trading.signals import rsi_reversal_macd_entry, ema_cross_entry

CACHE_DIR = Path(__file__).resolve().parent / "data_cache" / "sp500"
MIN_DOLLAR_VOL = 1_000_000_000  # $1B daily dollar vol

_rsi_fn = rsi_reversal_macd_entry(TUNED_RSI)
_ema_fn = ema_cross_entry(BEST_EMA)


# ── SP500 current members ────────────────────────────────────────────────

def get_current_sp500():
    """Fetch current SP500 tickers from Wikipedia."""
    headers = {"User-Agent": "Mozilla/5.0 (research bot)"}
    r = requests.get(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        headers=headers, timeout=30,
    )
    tables = pd.read_html(io.StringIO(r.text))
    return sorted(tables[0]["Symbol"].tolist())


# ── Data loading (reuses 120m parquet cache) ─────────────────────────────

def load_data(tickers, refresh=False):
    """Load price data, reusing longest available cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    all_data = {}
    failed = []
    cached = downloaded = 0

    for sym in tickers:
        sym_safe = sym.replace('.', '_')

        # Try longest cache first (reuse 120m/240m data)
        found = False
        for f in sorted(CACHE_DIR.glob(f"{sym_safe}_*d.parquet"), reverse=True):
            try:
                df = pd.read_parquet(f)
                if len(df) >= 100:
                    all_data[sym] = df
                    cached += 1
                    found = True
                    break
            except Exception:
                pass
        if found and not refresh:
            continue

        # Download 300 days (enough for EMAs + signals)
        df = download_eodhd(sym, 400)
        if df is not None and len(df) >= 100:
            all_data[sym] = df
            downloaded += 1
        else:
            failed.append(sym)

    return all_data, cached, downloaded, failed


# ── Liquidity filter ─────────────────────────────────────────────────────

def get_liquid_tickers(all_data):
    """Filter tickers by $1B rolling 252d dollar volume (today's value)."""
    liquid = set()
    for sym, df in all_data.items():
        try:
            close = df["Close"].astype(float)
            vol = df["Volume"].astype(float)
            dvol = (close * vol).rolling(252).mean()
            if len(dvol) > 0 and dvol.iloc[-1] >= MIN_DOLLAR_VOL:
                liquid.add(sym)
        except Exception:
            pass
    return liquid


# ── Signal computation ───────────────────────────────────────────────────

def compute_signals(sym, df):
    """Compute signals with EMA pre-entry filter."""
    signals = []
    rsi_mask = _rsi_fn(df)
    ema_mask = _ema_fn(df)

    close = df["Close"].astype(float)
    adx_series = ta.adx(df["High"].astype(float), df["Low"].astype(float), close, length=14)
    adx_col = adx_series["ADX_14"] if adx_series is not None and "ADX_14" in adx_series.columns else pd.Series(20, index=df.index)

    ema21 = ta.ema(close, length=EMA_EXIT_FAST)
    ema50 = ta.ema(close, length=EMA_EXIT_SLOW)

    def _ema_ok(loc):
        if ema21 is None or ema50 is None:
            return True
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


# ── HV Rank for LEAPS decision ───────────────────────────────────────────

def compute_hv_rank(df, window=20, lookback=252):
    """HV Rank: where current 20d HV sits in its 252d range (0-100)."""
    try:
        close = df["Close"].astype(float)
        log_ret = np.log(close / close.shift(1))
        hv = log_ret.rolling(window).std() * np.sqrt(252)
        current = hv.iloc[-1]
        hv_range = hv.tail(lookback)
        lo, hi = hv_range.min(), hv_range.max()
        if hi - lo < 0.001:
            return 50.0
        return float((current - lo) / (hi - lo) * 100)
    except Exception:
        return 50.0


# ── Main scanner ─────────────────────────────────────────────────────────

def scan_to_text(refresh=False):
    """Run PIT scanner and return result as string."""
    lines = []
    w = lines.append

    w("=" * 80)
    w(f"  LONG SWING PIT — Scanner SP500 | Macro: {MACRO_FILTER} | Max {MAX_POS} pos")
    w("=" * 80)

    # 1. Get current SP500 + SPY
    w("\n  Fetching SP500 current members...")
    try:
        sp500 = get_current_sp500()
        w(f"  SP500 members: {len(sp500)}")
    except Exception as e:
        w(f"  ERROR fetching SP500: {e}")
        w("  Falling back to cached data...")
        sp500 = []

    tickers = sorted(set(sp500) | {"SPY"})

    # 2. Load data
    all_data, cached, downloaded, failed = load_data(tickers, refresh)
    w(f"  Data: {cached} cached + {downloaded} downloaded + {len(failed)} failed = {len(all_data)} tickers")

    # 3. Liquidity filter
    liquid = get_liquid_tickers(all_data)
    w(f"  Liquid ($1B+ dvol): {len(liquid)} tickers")

    # 4. Macro context
    spy_data = all_data.get("SPY")
    if spy_data is not None:
        last_close = float(spy_data["Close"].iloc[-1])
        sma200 = float(spy_data["Close"].rolling(200).mean().iloc[-1])
        spy_status = "BULL" if last_close > sma200 else "BEAR"
        w(f"  SPY: {last_close:.2f} | SMA200: {sma200:.2f} | Regime: {spy_status}")

        # VIX (from EODHD if available)
        vix_data = all_data.get("VIX.INDX")
        vix_val = None
        if vix_data is not None and len(vix_data) > 0:
            vix_val = float(vix_data["Close"].iloc[-1])
            w(f"  VIX: {vix_val:.1f}")

        macro_ok = (last_close > sma200) and (vix_val is None or vix_val < VIX_MAX)
    else:
        w("  WARNING: No SPY data — macro filter disabled")
        spy_status = "UNKNOWN"
        macro_ok = True

    # 5. Generate signals for liquid SP500 tickers
    all_signals = []
    for sym in sorted(liquid):
        if sym == "SPY":
            continue  # SPY for macro only, not trading
        df = all_data.get(sym)
        if df is None or len(df) < 60:
            continue
        try:
            sigs = compute_signals(sym, df)
            all_signals.extend(sigs)
        except Exception:
            pass

    if not all_signals:
        w("\n  No hay senales generadas.")
        w(f"\n{'='*80}")
        return "\n".join(lines)

    signals_df = pd.DataFrame(all_signals)

    # 6. Show recent signals (last 7 days)
    today = pd.Timestamp.now(tz="UTC").normalize()
    if signals_df["entry_ts"].dt.tz is None:
        signals_df["entry_ts"] = signals_df["entry_ts"].dt.tz_localize("UTC")

    last_7d = signals_df[signals_df["entry_ts"] >= today - pd.Timedelta(days=7)]
    # Select best per day (RSI priority, then ADX rank) — max 1 signal/day
    last_7d = last_7d.copy()
    last_7d["date"] = last_7d["entry_ts"].dt.date
    last_7d["sig_priority"] = last_7d["signal"].map({"rsi_macd": 0, "ema_cross": 1})
    last_7d = last_7d.sort_values(["date", "sig_priority", "score"], ascending=[True, True, False])
    selected = last_7d.groupby("date").first().reset_index()

    if not selected.empty:
        w(f"\n  SEÑALES RECIENTES (últimos 7 días) — 1 señal/día, RSI priority")
        w(f"  {'Sym':>8s} {'Signal':>8s} {'Entry':>12s} {'ADX':>5s} {'HVR':>5s} {'Macro':>8s} {'LEAPS?':>8s}")
        w("  " + "-" * 68)

        for _, s in selected.iterrows():
            sym = s["symbol"]
            df = all_data.get(sym)
            hvr = compute_hv_rank(df) if df is not None else 50
            leaps_tag = "LEAPS" if hvr < 30 else "stock"
            macro_tag = "  OK" if macro_ok else " BLOCK"
            entry_date = str(s["entry_ts"])[:10]
            w(f"  {sym:>8s} {s['signal']:>8s} {entry_date:>12s} "
              f"{s['adx']:>5.1f} {hvr:>4.0f}% {macro_tag:>8s} {leaps_tag:>8s}")

        # Action for tomorrow
        last_trading_day = last_7d["date"].max()
        actionable = selected[selected["date"] == last_trading_day]
        if not actionable.empty and macro_ok:
            w(f"\n  >>> ACCIÓN MAÑANA: COMPRAR a la apertura:")
            for _, s in actionable.iterrows():
                sym = s["symbol"]
                df = all_data.get(sym)
                hvr = compute_hv_rank(df) if df is not None else 50
                leaps_tag = " → LEAPS (HVR {:.0f}%)".format(hvr) if hvr < 30 else " → Stock (HVR {:.0f}%)".format(hvr)
                w(f"      {sym} ({s['signal']}){leaps_tag}")
        elif not macro_ok:
            w(f"\n  >>> MACRO BLOCK ({spy_status}). No abrir posiciones nuevas.")
        else:
            w(f"\n  >>> No hay señales del último día de trading. Sin acción mañana.")
    else:
        w("\n  No hay señales en los últimos 7 días.")

    # 7. EMA status for OPEN POSITIONS ONLY (from paper_trading.json)
    paper_file = Path(__file__).resolve().parent / "paper_trading_state.json"
    open_positions = []
    if paper_file.exists():
        import json as _json
        try:
            state = _json.loads(paper_file.read_text())
            open_positions = state.get("positions", [])
        except Exception:
            pass

    if open_positions:
        w(f"\n  POSICIONES ABIERTAS — EMA {EMA_EXIT_FAST}/{EMA_EXIT_SLOW}")
        w(f"  {'Sym':>8s} {'Close':>8s} {'Entry':>8s} {'EMA21':>8s} {'EMA50':>8s} {'Status':>12s} {'P&L':>8s}")
        w("  " + "-" * 68)

        for pos in open_positions:
            sym = pos.get("symbol", "")
            entry_px = pos.get("entry_px", 0)
            df = all_data.get(sym)
            if df is None or len(df) < 60:
                continue
            close = df["Close"].astype(float)
            ema21 = float(ta.ema(close, length=EMA_EXIT_FAST).iloc[-1])
            ema50 = float(ta.ema(close, length=EMA_EXIT_SLOW).iloc[-1])
            last_close = float(close.iloc[-1])
            status = "EMA21>50" if ema21 > ema50 else "!!EXIT!!"
            pnl_pct = (last_close / entry_px - 1.0) * 100 if entry_px > 0 else 0
            pyr_tag = f" [PYR +{PYR_THRESHOLD*100:.0f}%]" if pnl_pct >= PYR_THRESHOLD * 100 else ""
            w(f"  {sym:>8s} {last_close:>8.2f} {entry_px:>8.2f} {ema21:>8.2f} {ema50:>8.2f} {status:>12s} {pnl_pct:>+7.1f}%{pyr_tag}")
    else:
        w(f"\n  POSICIONES ABIERTAS: ninguna")

    w(f"\n{'='*80}")
    return "\n".join(lines)


def main():
    text = scan_to_text(refresh="--refresh" in sys.argv)
    print(text)


if __name__ == "__main__":
    main()

"""
Long Swing — LEAPS Simulation over SP500 PIT trades (realistic).

Uses the same trade signals from the stock backtest. First N slots use LEAPS calls
(5% ITM, 365 DTE), remaining slots use plain stock. Tests 1-4 LEAPS slots.

Pricing:
  - Oct 2023+: Real IV from EODHD options API
  - Before Oct 2023: BS with IV = HV × 1.21 (measured IV/HV premium)

Exit pricing FIX (18-mar-2026): queries EODHD with actual LEAPS expiry date,
not "2020-01-01" which returned short-dated options instead.

Usage:
    uv run python -m long_swing.backtest_leaps
"""

import csv
import math
import sys
import time
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import norm
import urllib.request
import json

# ── Black-Scholes ──────────────────────────────────────────────────────────
def bs_call(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0 or S <= 0:
        return max(S - K, 0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)


def bs_delta(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0 or S <= 0:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    return norm.cdf(d1)


# ── Config ──────────────────────────────────────────────────────────────────
ITM_PCT = 0.05
MIN_DTE = 365
RISK_FREE = 0.04
IV_HV_PREMIUM = 1.21
INITIAL = 12_000.0
MAX_POS = 4
RESERVE_PCT = 0.20
COST_BPS = 10           # options cost
STOCK_COST_BPS = 4      # stock cost (same as main backtest)
PYR_THRESHOLD = 0.15
PYR_SIZE = 1.00
EODHD_API_KEY = "69ba6290ce4722.64310546"
EODHD_DATA_START = "2023-10-01"


def _eodhd_options_query(sym, strike, trade_date, exp_date_from):
    """Query EODHD options API for a specific LEAPS call."""
    strike_rounded = round(strike / 5) * 5
    url = ('https://eodhd.com/api/mp/unicornbay/options/eod?'
           f'filter%5Bunderlying_symbol%5D={sym}'
           '&filter%5Btype%5D=call'
           f'&filter%5Bstrike_eq%5D={strike_rounded}'
           f'&filter%5Btradetime_eq%5D={trade_date}'
           f'&filter%5Bexp_date_from%5D={exp_date_from}'
           f'&api_token={EODHD_API_KEY}&fmt=json'
           '&page%5Blimit%5D=5&sort=exp_date')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            if data.get('data'):
                a = data['data'][0]['attributes']
                return {
                    'contract': a['contract'],
                    'iv': a['volatility'],
                    'delta': a['delta'],
                    'mid': a['midpoint'],
                    'last': a['last'],
                    'bid': a['bid'],
                    'ask': a['ask'],
                    'dte': a['dte'],
                    'exp_date': a['exp_date'],
                    'strike': a['strike'],
                }
    except Exception:
        pass
    return None


def compute_hist_vol(df, entry_ts, lookback=60):
    if df.index.tz is not None and entry_ts.tzinfo is None:
        entry_ts = entry_ts.tz_localize("UTC")
    elif df.index.tz is None and hasattr(entry_ts, 'tzinfo') and entry_ts.tzinfo is not None:
        entry_ts = entry_ts.tz_localize(None)
    mask = df.index < entry_ts
    if mask.sum() < lookback:
        lookback = max(mask.sum() - 1, 10)
    recent = df.loc[mask].tail(lookback)
    if len(recent) < 10:
        return 0.30
    returns = np.log(recent["Close"] / recent["Close"].shift(1)).dropna()
    if len(returns) < 5:
        return 0.30
    vol = float(returns.std()) * math.sqrt(252)
    return max(vol, 0.10)


def compute_hv_rank(df, entry_ts, hv_lookback=60, rank_window=252):
    """HV Rank: percentile of current HV vs its own 52-week range.
    Returns 0-100. Low = IV cheap (good for LEAPS), High = IV expensive."""
    if df.index.tz is not None and entry_ts.tzinfo is None:
        entry_ts = entry_ts.tz_localize("UTC")
    elif df.index.tz is None and hasattr(entry_ts, 'tzinfo') and entry_ts.tzinfo is not None:
        entry_ts = entry_ts.tz_localize(None)
    mask = df.index < entry_ts
    if mask.sum() < rank_window:
        return 50  # default: neutral
    hist = df.loc[mask].tail(rank_window + hv_lookback)
    if len(hist) < rank_window:
        return 50
    # Compute rolling HV over the last year
    returns = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
    rolling_hv = returns.rolling(hv_lookback).std() * math.sqrt(252)
    rolling_hv = rolling_hv.dropna()
    if len(rolling_hv) < 60:
        return 50
    current_hv = float(rolling_hv.iloc[-1])
    hv_min = float(rolling_hv.min())
    hv_max = float(rolling_hv.max())
    if hv_max <= hv_min:
        return 50
    rank = (current_hv - hv_min) / (hv_max - hv_min) * 100
    return round(rank, 1)


def price_leaps_entry(sym, entry_px, entry_ts, sym_df):
    """Price a LEAPS call at entry."""
    K = entry_px * (1 - ITM_PCT)
    T = MIN_DTE / 365.25
    entry_date = str(entry_ts)[:10]
    iv_source = "bs_hv"

    if entry_date >= EODHD_DATA_START:
        exp_year = int(entry_date[:4]) + 1
        real_data = _eodhd_options_query(sym, K, entry_date, f"{exp_year}-01-01")
        if real_data and real_data['iv'] and real_data['iv'] > 0:
            iv = real_data['iv']
            premium = real_data['mid'] if real_data['mid'] and real_data['mid'] > 0 else real_data['last']
            if premium and premium > 0:
                delta = real_data['delta'] if real_data['delta'] else bs_delta(entry_px, K, T, RISK_FREE, iv)
                return {
                    'premium': premium, 'delta': delta, 'iv': iv,
                    'strike': real_data['strike'], 'iv_source': "eodhd_real",
                    'dte': real_data['dte'] if real_data['dte'] else MIN_DTE,
                    'exp_date': real_data['exp_date'],
                    'contract': real_data['contract'],
                }

    # Fallback: BS with HV × premium
    hv = compute_hist_vol(sym_df, entry_ts) if sym_df is not None else 0.30
    iv = hv * IV_HV_PREMIUM
    premium = bs_call(entry_px, K, T, RISK_FREE, iv)
    delta = bs_delta(entry_px, K, T, RISK_FREE, iv)
    exp_date = str(entry_ts + pd.Timedelta(days=MIN_DTE))[:10]
    return {
        'premium': premium, 'delta': delta, 'iv': iv,
        'strike': K, 'iv_source': "bs_hv",
        'dte': MIN_DTE, 'exp_date': exp_date, 'contract': None,
    }


def price_leaps_exit(exit_px, K, T_remaining, iv, iv_source, sym, exit_date, leap_exp_date):
    """Price a LEAPS call at exit. Uses EODHD real if available, else BS."""
    if T_remaining <= 0:
        return max(exit_px - K, 0)

    # For real IV trades, try to get exit price from EODHD
    # FIX: use leap_exp_date minus 30d as exp_date_from to find the SAME LEAPS contract
    if iv_source == "eodhd_real" and exit_date >= EODHD_DATA_START:
        # Filter for expiry near the actual LEAPS expiry (within 30 days before)
        exp_from = str(pd.Timestamp(leap_exp_date) - pd.Timedelta(days=30))[:10]
        exit_data = _eodhd_options_query(sym, K, exit_date, exp_from)
        if exit_data and exit_data['mid'] and exit_data['mid'] > 0:
            return exit_data['mid']
        # Try last price
        if exit_data and exit_data['last'] and exit_data['last'] > 0:
            return exit_data['last']

    # BS pricing with same IV
    return bs_call(exit_px, K, T_remaining, RISK_FREE, iv)


def _close_position(pos, exit_px_override=None):
    """Close a position (LEAPS or stock), return dict with pnl info."""
    exit_px = exit_px_override or pos["exit_px"]

    if pos["is_leaps"]:
        # LEAPS exit
        T_remaining = max((pos["leap_expiry"] - pos["exit_ts"]).days / 365.25, 0.001)
        exit_date = str(pos["exit_ts"])[:10]
        exit_premium = price_leaps_exit(
            exit_px, pos["strike"], T_remaining,
            pos["iv"], pos["iv_source"], pos["symbol"],
            exit_date, pos["leap_exp_date"]
        )
        proceeds = pos["contracts"] * 100 * exit_premium
        cost = proceeds * COST_BPS / 10000

        # Pyramid LEAPS
        pyr_proceeds = 0
        if pos.get("pyr_contracts", 0) > 0:
            T_pyr_rem = max((pos["pyr_expiry"] - pos["exit_ts"]).days / 365.25, 0.001)
            pyr_exit_prem = price_leaps_exit(
                exit_px, pos["pyr_strike"], T_pyr_rem,
                pos["iv"], pos["iv_source"], pos["symbol"],
                exit_date, pos.get("pyr_exp_date", pos["leap_exp_date"])
            )
            pyr_proceeds = pos["pyr_contracts"] * 100 * pyr_exit_prem
            cost += pyr_proceeds * COST_BPS / 10000

        total_proceeds = proceeds + pyr_proceeds
        total_invested = pos["alloc"] + pos.get("pyr_alloc", 0)
        pnl = total_proceeds - total_invested - cost
        return {
            "proceeds": total_proceeds, "cost": cost, "pnl": pnl,
            "exit_premium": round(exit_premium, 2),
            "entry_premium": round(pos["entry_premium"], 2),
        }
    else:
        # Stock exit
        shares = pos["shares"]
        proceeds = shares * exit_px
        cost = proceeds * STOCK_COST_BPS / 10000

        pyr_proceeds = 0
        if pos.get("pyr_shares", 0) > 0:
            pyr_proceeds = pos["pyr_shares"] * exit_px
            cost += pyr_proceeds * STOCK_COST_BPS / 10000

        total_proceeds = proceeds + pyr_proceeds
        total_invested = pos["alloc"] + pos.get("pyr_alloc", 0)
        pnl = total_proceeds - total_invested - cost
        return {
            "proceeds": total_proceeds, "cost": cost, "pnl": pnl,
            "exit_premium": 0, "entry_premium": 0,
        }


def run_simulation(leaps_slots, raw_trades, all_data, trading_dates, quiet=False,
                   iv_rank_mode=False, iv_rank_threshold=30):
    """Run mixed LEAPS/stock simulation. Date-driven to match pyramid timing.

    If iv_rank_mode=True, ignores leaps_slots and instead uses HV Rank to decide:
      - HV Rank < iv_rank_threshold → LEAPS
      - HV Rank >= iv_rank_threshold → stock
    """
    cash = INITIAL
    positions = []
    log = []
    still_open = []
    n_pyr = 0
    n_real_iv = 0
    n_bs_iv = 0
    api_calls = 0

    # Index trades by entry date for quick lookup
    trades_by_date = {}
    for t in raw_trades:
        dt = pd.Timestamp(t["entry_ts"]).normalize()
        trades_by_date.setdefault(dt, []).append(t)

    def _log_close(pos, result):
        log.append({
            "symbol": pos["symbol"], "signal": pos["signal"],
            "entry_ts": pos["entry_ts"], "entry_px": pos["entry_px"],
            "exit_ts": pos["exit_ts"], "exit_px": pos["exit_px"],
            "exit_reason": pos["exit_reason"],
            "is_leaps": pos["is_leaps"],
            "hv_rank": pos.get("hv_rank"),
            "strike": round(pos.get("strike", 0), 2),
            "iv": round(pos.get("iv", 0), 3),
            "iv_source": pos.get("iv_source", "n/a"),
            "entry_premium": result["entry_premium"],
            "exit_premium": result["exit_premium"],
            "delta_entry": round(pos.get("delta_entry", 0), 3),
            "leverage": round(pos.get("leverage", 1.0), 1),
            "alloc": round(pos["alloc"], 2),
            "pyr_alloc": round(pos.get("pyr_alloc", 0), 2),
            "pyramided": pos.get("pyr_contracts", 0) > 0 or pos.get("pyr_shares", 0) > 0,
            "pnl": round(result["pnl"], 2),
            "closed": True,
        })

    for today in trading_dates:
        # 1. Close expired positions
        new_positions = []
        for pos in positions:
            if today >= pos["exit_ts"]:
                result = _close_position(pos)
                cash += result["proceeds"] - result["cost"]
                _log_close(pos, result)
            else:
                new_positions.append(pos)
        positions = new_positions

        # 2. Pyramid checks on EVERY trading day (matches original BT)
        for pos in positions:
            already_pyr = pos.get("pyr_contracts", 0) > 0 or pos.get("pyr_shares", 0) > 0
            if already_pyr:
                continue
            sym_df = all_data.get(pos["symbol"])
            if sym_df is None:
                continue
            _ets = today.tz_localize("UTC") if sym_df.index.tz is not None and today.tzinfo is None else today
            mask = sym_df.index <= _ets
            if not mask.any():
                continue
            current_px = float(sym_df.loc[mask, "Close"].iloc[-1])
            pct_gain = current_px / pos["entry_px"] - 1.0

            if pct_gain >= PYR_THRESHOLD:
                pyr_alloc = pos["alloc"] * PYR_SIZE
                if pyr_alloc > cash:
                    pyr_alloc = cash
                if pyr_alloc <= 50:
                    continue

                if pos["is_leaps"]:
                    K_pyr = current_px * (1 - ITM_PCT)
                    T_pyr = MIN_DTE / 365.25
                    pyr_premium = bs_call(current_px, K_pyr, T_pyr, RISK_FREE, pos["iv"])
                    if pyr_premium > 0:
                        pyr_contracts = pyr_alloc / (pyr_premium * 100)
                        pyr_cost = pyr_alloc * COST_BPS / 10000
                        cash -= pyr_alloc + pyr_cost
                        pos["pyr_contracts"] = pyr_contracts
                        pos["pyr_alloc"] = pyr_alloc
                        pos["pyr_strike"] = K_pyr
                        pos["pyr_expiry"] = today + pd.Timedelta(days=MIN_DTE)
                        pos["pyr_exp_date"] = str(pos["pyr_expiry"])[:10]
                        n_pyr += 1
                else:
                    pyr_shares = pyr_alloc / current_px
                    pyr_cost = pyr_alloc * STOCK_COST_BPS / 10000
                    cash -= pyr_alloc + pyr_cost
                    pos["pyr_shares"] = pyr_shares
                    pos["pyr_alloc"] = pyr_alloc
                    n_pyr += 1

        # 3. Open new positions if trade entry on this date
        day_trades = trades_by_date.get(today.normalize(), [])
        for t in day_trades:
            entry_ts = pd.Timestamp(t["entry_ts"])
            exit_ts = pd.Timestamp(t["exit_ts"])
            entry_px = float(t["entry_px"])
            exit_px = float(t["exit_px"])
            sym = t["symbol"]

            if len(positions) >= MAX_POS:
                break
            held_syms = {p["symbol"] for p in positions}
            if sym in held_syms:
                continue
            free_slots = MAX_POS - len(positions)
            alloc = cash * (1 - RESERVE_PCT) / free_slots
            if alloc <= 50:
                continue

            # Decide LEAPS or stock
            if iv_rank_mode:
                sym_df = all_data.get(sym)
                hv_rank = compute_hv_rank(sym_df, entry_ts) if sym_df is not None else 50
                use_leaps = hv_rank < iv_rank_threshold
            else:
                leaps_count = sum(1 for p in positions if p["is_leaps"])
                use_leaps = leaps_count < leaps_slots
                hv_rank = None

            if use_leaps:
                sym_df = all_data.get(sym)
                pricing = price_leaps_entry(sym, entry_px, entry_ts, sym_df)
                api_calls += 1 if pricing['iv_source'] == 'eodhd_real' else 0
                n_real_iv += 1 if pricing['iv_source'] == 'eodhd_real' else 0
                n_bs_iv += 1 if pricing['iv_source'] == 'bs_hv' else 0

                premium = pricing['premium']
                if premium and premium > 0:
                    contracts = alloc / (premium * 100)
                    notional = contracts * 100 * entry_px
                    leverage = notional / alloc

                    cost = alloc * COST_BPS / 10000
                    cash -= alloc + cost

                    positions.append({
                        "symbol": sym, "signal": t["signal"],
                        "entry_ts": entry_ts, "entry_px": entry_px,
                        "exit_ts": exit_ts, "exit_px": exit_px,
                        "exit_reason": t.get("exit_reason", "ema_cross"),
                        "is_leaps": True, "hv_rank": hv_rank,
                        "strike": pricing['strike'], "iv": pricing['iv'],
                        "iv_source": pricing['iv_source'],
                        "entry_premium": premium,
                        "delta_entry": pricing['delta'],
                        "contracts": contracts, "leverage": leverage,
                        "alloc": alloc,
                        "leap_expiry": entry_ts + pd.Timedelta(days=int(pricing['dte'])),
                        "leap_exp_date": pricing['exp_date'],
                        "pyr_contracts": 0, "pyr_alloc": 0,
                    })

                    if pricing['iv_source'] == 'eodhd_real':
                        time.sleep(0.1)
            else:
                # Stock position
                if not iv_rank_mode:
                    sym_df = all_data.get(sym)
                    hv_rank = compute_hv_rank(sym_df, entry_ts) if sym_df is not None else 50
                shares = alloc / entry_px
                cost = alloc * STOCK_COST_BPS / 10000
                cash -= alloc + cost

                positions.append({
                    "symbol": sym, "signal": t["signal"],
                    "entry_ts": entry_ts, "entry_px": entry_px,
                    "exit_ts": exit_ts, "exit_px": exit_px,
                    "exit_reason": t.get("exit_reason", "ema_cross"),
                    "is_leaps": False, "hv_rank": hv_rank,
                    "shares": shares, "leverage": 1.0,
                    "alloc": alloc,
                    "pyr_shares": 0, "pyr_alloc": 0,
                })

    # Close remaining
    for pos in positions:
        result = _close_position(pos)
        cash += result["proceeds"] - result["cost"]
        is_open = pos["exit_reason"] == "end_of_data"
        entry = {
            "symbol": pos["symbol"], "signal": pos["signal"],
            "entry_ts": pos["entry_ts"], "entry_px": pos["entry_px"],
            "exit_ts": pos["exit_ts"], "exit_px": pos["exit_px"],
            "exit_reason": pos["exit_reason"],
            "is_leaps": pos["is_leaps"],
            "strike": round(pos.get("strike", 0), 2),
            "iv": round(pos.get("iv", 0), 3),
            "iv_source": pos.get("iv_source", "n/a"),
            "entry_premium": result["entry_premium"],
            "exit_premium": result["exit_premium"],
            "delta_entry": round(pos.get("delta_entry", 0), 3),
            "leverage": round(pos.get("leverage", 1.0), 1),
            "alloc": round(pos["alloc"], 2),
            "pyr_alloc": round(pos.get("pyr_alloc", 0), 2),
            "pyramided": pos.get("pyr_contracts", 0) > 0 or pos.get("pyr_shares", 0) > 0,
            "pnl": round(result["pnl"], 2),
            "closed": not is_open,
        }
        if is_open:
            still_open.append(entry)
        else:
            log.append(entry)

    # ── Calculate metrics ──────────────────────────────────────────────────
    equity = cash
    fixed_years = 10.0
    cagr = (equity / INITIAL) ** (1 / fixed_years) - 1

    wins = [t for t in log if t["pnl"] > 0]
    losses = [t for t in log if t["pnl"] <= 0]
    pf = sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in losses)) if losses else 999

    # Drawdown
    equity_curve = [INITIAL]
    running = INITIAL
    for t in sorted(log, key=lambda x: str(x["exit_ts"])):
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

    all_trades = log + still_open
    leaps_trades = [t for t in all_trades if t["is_leaps"]]
    stock_trades = [t for t in all_trades if not t["is_leaps"]]
    leverages = [t["leverage"] for t in leaps_trades] if leaps_trades else [1.0]

    results = {
        "leaps_slots": leaps_slots,
        "equity": round(equity, 2),
        "cagr": round(cagr * 100, 1),
        "max_dd": round(max_dd * 100, 2),
        "pf": round(pf, 2),
        "trades": len(log),
        "wins": len(wins),
        "losses": len(losses),
        "wr": round(len(wins)/len(log)*100, 1) if log else 0,
        "leverage_mean": round(np.mean(leverages), 1),
        "leverage_min": round(min(leverages), 1),
        "leverage_max": round(max(leverages), 1),
        "n_leaps": len(leaps_trades),
        "n_stock": len(stock_trades),
        "n_real_iv": n_real_iv,
        "n_bs_iv": n_bs_iv,
        "n_pyr": n_pyr,
        "api_calls": api_calls,
        "still_open": len(still_open),
        "log": log,
        "still_open_list": still_open,
    }

    if not quiet:
        print(f"\n{'='*80}")
        print(f"  LEAPS slots: {leaps_slots}/{MAX_POS} — Results")
        print(f"{'='*80}")
        print(f"  Capital: {INITIAL:,.0f}€ → {equity:,.0f}€")
        print(f"  CAGR: {cagr*100:+.1f}%")
        print(f"  Max DD: {max_dd*100:.1f}%")
        print(f"  Profit Factor: {pf:.2f}")
        print(f"  Trades: {len(log)} ({len(wins)}W / {len(losses)}L) | WR: {len(wins)/len(log)*100:.0f}%")
        print(f"  LEAPS trades: {len(leaps_trades)} | Stock trades: {len(stock_trades)}")
        print(f"  Leverage medio LEAPS: {np.mean(leverages):.1f}x")
        print(f"  IV sources: {n_real_iv} real + {n_bs_iv} BS×{IV_HV_PREMIUM}")
        print(f"  Pyramids: {n_pyr} | Open: {len(still_open)}")

        # Top/bottom trades
        log_sorted = sorted(log, key=lambda x: x["pnl"], reverse=True)
        print(f"\n  TOP 3 WINNERS:")
        for t in log_sorted[:3]:
            typ = "LEAP" if t["is_leaps"] else "STCK"
            print(f"    [{typ}] {t['symbol']:>6s} {str(t['entry_ts'])[:10]} → {str(t['exit_ts'])[:10]} "
                  f"PnL: {t['pnl']:+,.0f}€  Lev: {t['leverage']:.1f}x")
        print(f"  TOP 3 LOSERS:")
        for t in log_sorted[-3:]:
            typ = "LEAP" if t["is_leaps"] else "STCK"
            print(f"    [{typ}] {t['symbol']:>6s} {str(t['entry_ts'])[:10]} → {str(t['exit_ts'])[:10]} "
                  f"PnL: {t['pnl']:+,.0f}€  Lev: {t['leverage']:.1f}x")

    return results


def main():
    results_dir = Path(__file__).resolve().parent
    trades_csv = results_dir / "sp500_trades_120m.csv"

    if not trades_csv.exists():
        print("ERROR: Run backtest_sp500_survivorship.py first to generate trades.")
        return

    with open(trades_csv) as f:
        raw_trades = list(csv.DictReader(f))

    # Load price data
    cache_dir = results_dir / "data_cache" / "sp500"
    all_data = {}
    syms_needed = set(t["symbol"] for t in raw_trades)
    for sym in syms_needed:
        matches = list(cache_dir.glob(f"{sym}_*.parquet"))
        if matches:
            df = pd.read_parquet(matches[0])
            df.index = pd.to_datetime(df.index)
            all_data[sym] = df

    # Build trading calendar from SPY data (or any available ticker)
    spy_df = all_data.get("SPY")
    if spy_df is None:
        # Use any available ticker for dates
        spy_df = next(iter(all_data.values()))
    # Get all trading dates that span the trade period
    first_entry = min(pd.Timestamp(t["entry_ts"]) for t in raw_trades)
    last_exit = max(pd.Timestamp(t["exit_ts"]) for t in raw_trades)
    # Normalize tz for comparison
    idx = spy_df.index
    if idx.tz is not None:
        first_entry = first_entry.tz_localize("UTC") if first_entry.tzinfo is None else first_entry
        last_exit = last_exit.tz_localize("UTC") if last_exit.tzinfo is None else last_exit
    trading_dates = sorted(idx[(idx >= first_entry) & (idx <= last_exit)])
    # Convert all to tz-naive for uniform comparison
    trading_dates = [d.tz_localize(None) if hasattr(d, 'tz_localize') and d.tzinfo else d for d in trading_dates]

    print("=" * 80)
    print("  LONG SWING — LEAPS con filtro HV Rank")
    print("=" * 80)
    print(f"  Trades: {len(raw_trades)} | Price data: {len(all_data)} tickers")
    print(f"  Trading days: {len(trading_dates)} ({str(trading_dates[0])[:10]} → {str(trading_dates[-1])[:10]})")
    print(f"  Config: {ITM_PCT:.0%} ITM, {MIN_DTE} DTE, {MAX_POS} slots")
    print(f"  Regla: HV Rank < umbral → LEAPS, si no → acciones")

    # First: baseline stock-only
    print(f"\n{'─'*80}")
    print(f"  Running baseline: 100% acciones...")
    baseline = run_simulation(0, raw_trades, all_data, trading_dates, quiet=True)

    # First: all-LEAPS
    print(f"  Running: 100% LEAPS...")
    all_leaps = run_simulation(4, raw_trades, all_data, trading_dates, quiet=True)

    # IV Rank thresholds to test
    thresholds = [20, 30, 40, 50, 60, 70]
    iv_results = {}

    for thr in thresholds:
        print(f"  Running: HV Rank < {thr} → LEAPS...")
        res = run_simulation(0, raw_trades, all_data, trading_dates,
                            quiet=True, iv_rank_mode=True, iv_rank_threshold=thr)
        iv_results[thr] = res

    # ── Comparison table ───────────────────────────────────────────────────
    print(f"\n\n{'='*80}")
    print(f"  COMPARACIÓN — HV Rank filter (LEAPS si rank < umbral)")
    print(f"{'='*80}")
    header = f"  {'Config':>15s} {'Equity':>10s} {'CAGR':>8s} {'MaxDD':>8s} {'PF':>6s} {'WR':>5s} {'Efic':>6s} {'#LEAP':>6s} {'#Stk':>5s}"
    print(header)
    print(f"  {'─'*len(header)}")

    # Baseline
    r = baseline
    eff = r['cagr'] / abs(r['max_dd']) if r['max_dd'] != 0 else 0
    print(f"  {'100% Stock':>15s} {r['equity']:>9,.0f}€ {r['cagr']:>+7.1f}% {r['max_dd']:>7.1f}% "
          f"{r['pf']:>5.2f} {r['wr']:>4.0f}% {eff:>5.2f} {r['n_leaps']:>5d} {r['n_stock']:>5d}")

    for thr in thresholds:
        r = iv_results[thr]
        eff = r['cagr'] / abs(r['max_dd']) if r['max_dd'] != 0 else 0
        label = f"IVR<{thr}"
        print(f"  {label:>15s} {r['equity']:>9,.0f}€ {r['cagr']:>+7.1f}% {r['max_dd']:>7.1f}% "
              f"{r['pf']:>5.2f} {r['wr']:>4.0f}% {eff:>5.2f} {r['n_leaps']:>5d} {r['n_stock']:>5d}")

    r = all_leaps
    eff = r['cagr'] / abs(r['max_dd']) if r['max_dd'] != 0 else 0
    print(f"  {'100% LEAPS':>15s} {r['equity']:>9,.0f}€ {r['cagr']:>+7.1f}% {r['max_dd']:>7.1f}% "
          f"{r['pf']:>5.2f} {r['wr']:>4.0f}% {eff:>5.2f} {r['n_leaps']:>5d} {r['n_stock']:>5d}")

    # Detail for best IV rank threshold
    print(f"\n  EFICIENCIA (CAGR / |DD|):")
    all_configs = [("100% Stock", baseline)] + [(f"IVR<{t}", iv_results[t]) for t in thresholds] + [("100% LEAPS", all_leaps)]
    for label, r in all_configs:
        eff = r['cagr'] / abs(r['max_dd']) if r['max_dd'] != 0 else 0
        bar = "█" * int(eff * 10)
        print(f"  {label:>15s}  {eff:.2f}  {bar}")

    # Show trade-level detail for IVR<30
    print(f"\n{'='*80}")
    print(f"  DETALLE — HV Rank < 30 (cada trade)")
    print(f"{'='*80}")
    r30 = iv_results[30]
    all_log = sorted(r30["log"] + r30["still_open_list"], key=lambda t: str(t["entry_ts"]))
    print(f"  {'sym':>6} {'entry':>10} {'HVR':>5} {'tipo':>5} {'lev':>5} {'iv':>5} {'pnl':>10}")
    print(f"  {'─'*58}")
    for t in all_log:
        hvr = t.get("hv_rank")
        hvr_s = f"{hvr:.0f}" if hvr is not None else "?"
        typ = "LEAP" if t["is_leaps"] else "STCK"
        print(f"  {t['symbol']:>6} {str(t['entry_ts'])[:10]} {hvr_s:>5} {typ:>5} "
              f"{t['leverage']:>5.1f}x {t['iv']:.0%} {t['pnl']:>+10,.0f}€")

    # Save summary
    summary = {"baseline_stock": {k: v for k, v in baseline.items() if k not in ("log", "still_open_list")},
               "all_leaps": {k: v for k, v in all_leaps.items() if k not in ("log", "still_open_list")}}
    for thr in thresholds:
        r = iv_results[thr]
        summary[f"ivr_lt_{thr}"] = {k: v for k, v in r.items() if k not in ("log", "still_open_list")}
    summary_path = results_dir / "leaps_ivrank_results_120m.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n  Summary saved: {summary_path}")


if __name__ == "__main__":
    main()

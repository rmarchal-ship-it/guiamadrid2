#!/usr/bin/env python3
"""
BACKTEST v12g PIT — Momentum Breakout v12g Survivorship-Bias-Free (Point-in-Time)

Version: v12g PIT (19 Mar 2026)
Base: backtest_v12_eu_options.py (v12 semidefinitiva)

Objetivo:
  Eliminar survivorship bias usando universo point-in-time:
  - US stocks: solo si estaban en SP500 en la fecha de la señal
  - EU/Asia stocks: solo si dollar volume 252d > $500M en fecha de señal
  - ETFs: solo desde su fecha de inception real
  - Gold overlay 30% post-hoc

Diferencia vs v12g baseline:
  UNICA modificación: filtro PIT en find_candidates() antes de rank_candidates().
  Todo lo demás idéntico: señales, opciones (2US+2EU), macro filter, trailing stops.

Uso:
  python3 backtest_v12g_pit.py --months 120
  python3 backtest_v12g_pit.py --months 120 --gold --gold-pct 0.30
  python3 backtest_v12g_pit.py --multi-period --gold --gold-pct 0.30
  python3 backtest_v12g_pit.py --months 120 --verbose --export-csv
"""

import sys, os, io, json, time, warnings, requests
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Set
from pathlib import Path
from collections import defaultdict

warnings.filterwarnings("ignore")

# Importar desde backtest base
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_experimental import (
    CONFIG, BASE_TICKERS, LEVERAGE_FACTORS, OPTIONS_ELIGIBLE,
    MACRO_EXEMPT, MACRO_EXEMPT_NEG,
    black_scholes_call, historical_volatility, monthly_expiration_dte, iv_rank,
    download_data, generate_all_signals, build_macro_filter,
    rank_candidates, find_candidates,
    Trade, EquityTracker,
    calculate_atr,
)
from momentum_breakout import MomentumEngine, ASSETS

# Importar desde v12 EU options
from backtest_v12_eu_options import (
    OPTIONS_ELIGIBLE_EU, OPTIONS_ALL, US_SPREAD_PCT, EU_SPREAD_PCT,
    OptionTradeV2EU, get_option_spread,
    simulate_gold_overlay, compute_sharpe, print_comparison,
)

# Importar EODHD
from data_eodhd import download_data_eodhd


# =============================================================================
# CACHE
# =============================================================================
CACHE_DIR = Path(__file__).resolve().parent / "data_cache" / "pit"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Long Swing cache (reuse if available)
LONG_SWING_CACHE = Path(__file__).resolve().parent.parent / "Long Swing" / "data_cache" / "sp500"


# =============================================================================
# 1. SP500 POINT-IN-TIME UNIVERSE (copied from Long Swing)
# =============================================================================

def fetch_sp500_changes():
    """Fetch SP500 addition/removal history from Wikipedia."""
    headers = {"User-Agent": "Mozilla/5.0 (research bot)"}
    r = requests.get(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        headers=headers, timeout=30,
    )
    tables = pd.read_html(io.StringIO(r.text))
    current = sorted(tables[0]["Symbol"].tolist())
    changes = tables[1]
    changes.columns = ["date", "added_ticker", "added_name",
                       "removed_ticker", "removed_name", "reason"]
    changes["date"] = pd.to_datetime(changes["date"], format="mixed")
    changes = changes.sort_values("date").reset_index(drop=True)
    return current, changes


def build_point_in_time_universe(current, changes, start_date):
    """Reconstruct SP500 membership at start_date by reversing changes."""
    members = set(current)
    for _, row in changes.sort_values("date", ascending=False).iterrows():
        change_date = row["date"]
        if pd.isna(change_date) or change_date <= pd.Timestamp(start_date):
            break
        added = str(row["added_ticker"]).strip()
        removed = str(row["removed_ticker"]).strip()
        if added and added != "nan":
            members.discard(added)
        if removed and removed != "nan":
            members.add(removed)
    return members


def build_pit_membership_series(sp500_current, sp500_changes, start_date, end_date):
    """Pre-build dict[Timestamp -> frozenset] of SP500 membership for O(1) lookups."""
    members = set(build_point_in_time_universe(sp500_current, sp500_changes, start_date))

    changes_in_range = sp500_changes[
        (sp500_changes['date'] >= pd.Timestamp(start_date)) &
        (sp500_changes['date'] <= pd.Timestamp(end_date))
    ].sort_values('date')

    # Build a list of (date, members_snapshot) at each change point
    change_points = [(pd.Timestamp(start_date), frozenset(members))]

    for _, row in changes_in_range.iterrows():
        added = str(row['added_ticker']).strip()
        removed = str(row['removed_ticker']).strip()
        if added and added != 'nan':
            members.add(added)
        if removed and removed != 'nan':
            members.discard(removed)
        change_points.append((row['date'], frozenset(members)))

    return change_points


def get_sp500_members_at(change_points, target_date):
    """O(log n) lookup of SP500 members at target_date using pre-built change points."""
    ts = pd.Timestamp(target_date)
    # Binary search: find last change_point <= target_date
    lo, hi = 0, len(change_points) - 1
    result = change_points[0][1]
    while lo <= hi:
        mid = (lo + hi) // 2
        if change_points[mid][0] <= ts:
            result = change_points[mid][1]
            lo = mid + 1
        else:
            hi = mid - 1
    return result


# =============================================================================
# 2. ETF INCEPTION DATES
# =============================================================================

ETF_INCEPTION = {
    # Classic US index
    'SPY': '1993-01-29', 'QQQ': '1999-03-10', 'IWM': '2000-05-22',
    'DIA': '1998-01-14',
    # Leveraged — CRITICAL for survivorship
    'TQQQ': '2010-02-09', 'SPXL': '2008-11-05', 'TNA': '2008-11-05',
    # Crypto
    'BITO': '2021-10-19',
    # Precious metals
    'GLD': '2004-11-18', 'SLV': '2006-04-28', 'PPLT': '2010-01-06',
    'GDX': '2006-05-22', 'GDXJ': '2009-11-10',
    # Energy commodities
    'USO': '2006-04-10', 'BNO': '2010-06-02', 'UNG': '2007-04-18',
    'XLE': '1998-12-16', 'XOP': '2006-06-19',
    # Industrial / Ag commodities
    'CPER': '2011-11-15', 'DBB': '2007-01-05', 'PICK': '2010-03-19',
    'DBA': '2007-01-05', 'WEAT': '2011-09-19', 'CORN': '2010-06-09',
    'SOYB': '2011-09-19',
    # Sector ETFs
    'SMH': '2000-05-05', 'XBI': '2006-01-31',
    'XLU': '1998-12-16', 'XLI': '1998-12-16', 'XLF': '1998-12-16', 'XLV': '1998-12-16',
    # International ETFs
    'EEM': '2003-04-07', 'VWO': '2005-03-04', 'EFA': '2001-08-14',
    'FXI': '2004-10-05', 'EWJ': '1996-03-12', 'EWG': '1996-03-12',
    'EWU': '1996-03-18', 'INDA': '2012-02-02', 'EWZ': '2000-07-10',
    'EWT': '2000-06-20',
    # Fixed income
    'TLT': '2002-07-22', 'IEF': '2002-07-22', 'SHY': '2002-07-22',
    'TIP': '2003-12-04', 'AGG': '2003-09-22', 'LQD': '2002-07-22',
    'HYG': '2007-04-04', 'EMB': '2007-12-17',
}


# =============================================================================
# 3. TICKER CLASSIFICATION
# =============================================================================

# EU suffixes
EU_SUFFIXES = ('.DE', '.PA', '.L', '.AS', '.BR', '.MI', '.MC', '.SW', '.ST', '.HE', '.CO')
ASIA_SUFFIXES = ('.T', '.AX', '.HK')

# Categories from ASSETS that are ETFs (not individual stocks)
ETF_CATEGORIES = {
    'COMMODITY_AGRICULTURE', 'COMMODITY_ENERGY', 'COMMODITY_INDUSTRIAL',
    'COMMODITY_PRECIOUS', 'ETF_INTL', 'ETF_SECTOR',
    'US_INDEX', 'US_INDEX_LEV', 'FIXED_INCOME',
}

# Some EU tickers trade without suffix (NOK, ASML, SAP, SHEL, HSBC, BP, RIO, GSK, CRH)
# These are either: US-listed ADRs of EU companies, or dual-listed
# For PIT purposes: if category starts with EU_, treat as EU stock
EU_CATEGORY_PREFIXES = ('EU_',)


def classify_ticker(ticker):
    """Classify ticker as 'us_stock', 'eu_stock', 'asia_stock', or 'etf'."""
    meta = ASSETS.get(ticker, {})
    category = meta.get('category', '')

    # ETFs first (by category)
    if category in ETF_CATEGORIES:
        return 'etf'

    # EU by suffix
    if ticker.endswith(EU_SUFFIXES):
        return 'eu_stock'

    # Asia by suffix
    if ticker.endswith(ASIA_SUFFIXES):
        return 'asia_stock'

    # EU by category (handles SAP, ASML, SHEL, HSBC, BP, RIO, GSK, NOK, CRH)
    if any(category.startswith(p) for p in EU_CATEGORY_PREFIXES):
        return 'eu_stock'

    # Asia by category
    if category.startswith('ASIA_'):
        # China ADRs (BABA, JD, PDD, BIDU) - these ARE US-listed
        # They were added to SP500 or major indices — treat as us_stock for PIT
        if category == 'ASIA_CHINA' and not ticker.endswith(ASIA_SUFFIXES):
            return 'us_stock'  # US-listed ADR, use SP500 membership
        return 'asia_stock'

    # Default: US stock
    return 'us_stock'


def build_ticker_classification():
    """Build classification dict for all ASSETS tickers."""
    classification = {}
    for ticker in ASSETS:
        classification[ticker] = classify_ticker(ticker)
    return classification


# =============================================================================
# 4. DOLLAR VOLUME COMPUTATION
# =============================================================================

MIN_DOLLAR_VOL = 500_000_000  # $500M rolling 252-day

def compute_dollar_volume_series(all_data):
    """Pre-compute rolling 252-day dollar volume for each ticker."""
    dv_cache = {}
    for ticker, df in all_data.items():
        close = df['Close']
        volume = df['Volume']
        if isinstance(close, pd.DataFrame):
            close = close.squeeze()
        if isinstance(volume, pd.DataFrame):
            volume = volume.squeeze()
        dv = (close * volume).rolling(252, min_periods=50).mean()
        dv_cache[ticker] = dv
    return dv_cache


# =============================================================================
# 5. PIT ELIGIBILITY FUNCTION
# =============================================================================

def build_pit_eligible_fn(ticker_class, sp500_change_points, dv_cache):
    """Build a closure that checks PIT eligibility for a ticker on a date.

    Returns: callable(ticker, date) -> bool
    """
    def pit_eligible(ticker, current_date):
        cls = ticker_class.get(ticker)
        if cls is None:
            return True  # Unknown ticker → allow (conservative)

        if cls == 'etf':
            inception = ETF_INCEPTION.get(ticker)
            if inception and pd.Timestamp(current_date) < pd.Timestamp(inception):
                return False
            return True

        if cls == 'us_stock':
            # Must be in SP500 at this date
            if sp500_change_points is None:
                return True  # No SP500 data → allow
            members = get_sp500_members_at(sp500_change_points, current_date)
            # Normalize: some SP500 tickers use . vs - (BRK.B vs BRK-B)
            ticker_variants = {ticker, ticker.replace('-', '.'), ticker.replace('.', '-')}
            return bool(ticker_variants & members)

        if cls in ('eu_stock', 'asia_stock'):
            # EU/Asia are stable blue chips — no survivorship bias filter needed
            # PIT only applies to US stocks (SP500) and ETFs (inception)
            return True

        return True

    return pit_eligible


# =============================================================================
# 6. DATA DOWNLOAD — EXPANDED UNIVERSE
# =============================================================================

def get_all_sp500_tickers_ever(sp500_current, sp500_changes):
    """Get all tickers that were EVER in SP500 during changes history."""
    all_tickers = set(sp500_current)
    for _, row in sp500_changes.iterrows():
        added = str(row['added_ticker']).strip()
        removed = str(row['removed_ticker']).strip()
        if added and added != 'nan':
            all_tickers.add(added)
        if removed and removed != 'nan':
            all_tickers.add(removed)
    return all_tickers


def load_from_cache(ticker, months):
    """Try to load ticker data from parquet cache.

    Searches both PIT cache and Long Swing SP500 cache.
    Tries multiple filename conventions (safe_name and raw ticker).
    Accepts any cache with >= 80% of requested lookback days.
    """
    lookback_days = months * 30 + 60
    # Multiple name variants to match different cache conventions
    safe_name = ticker.replace('.', '_').replace('-', '_')
    raw_name = ticker  # Long Swing uses raw ticker names

    for cache_dir in [CACHE_DIR, LONG_SWING_CACHE]:
        if cache_dir is None or not cache_dir.exists():
            continue

        # Try all name variants
        for name in [safe_name, raw_name]:
            # Try exact lookback match
            path = cache_dir / f"{name}_{lookback_days}d.parquet"
            if path.exists():
                try:
                    df = pd.read_parquet(path)
                    if len(df) >= 50:
                        return df
                except Exception:
                    pass
            # Try any cached file with enough data
            for f in cache_dir.glob(f"{name}_*d.parquet"):
                try:
                    cached_days = int(f.stem.split('_')[-1].replace('d', ''))
                    if cached_days >= lookback_days * 0.5:  # Accept 50%+ of requested
                        df = pd.read_parquet(f)
                        if len(df) >= 50:
                            return df
                except (ValueError, Exception):
                    pass
    return None


def save_to_cache(ticker, df, months):
    """Save ticker data to parquet cache."""
    safe_name = ticker.replace('.', '_').replace('-', '_')
    lookback_days = months * 30 + 60
    path = CACHE_DIR / f"{safe_name}_{lookback_days}d.parquet"
    try:
        df.to_parquet(path)
    except Exception:
        pass


def download_expanded_universe(base_tickers, sp500_ever, months, verbose=False):
    """Download data for expanded universe (base + historical SP500 members).

    Strategy:
    1. Load ALL from cache first (fast, no network)
    2. Download missing BASE tickers via EODHD then Yahoo (these are critical)
    3. Download missing SP500-only tickers via EODHD only (skip Yahoo for delisted)
    """
    all_tickers_needed = set(base_tickers) | sp500_ever
    all_tickers_needed = {t for t in all_tickers_needed
                         if t and t != 'nan' and len(t) <= 10}

    all_data = {}
    failed = []
    cached = 0
    downloaded = 0
    skipped_delisted = 0
    total = len(all_tickers_needed)
    base_set = set(base_tickers)

    print(f"  Universo expandido: {total} tickers ({len(base_tickers)} base + "
          f"{len(sp500_ever)} SP500 historico)")

    # Pass 1: Load everything from cache (instant)
    print("  Pass 1: Loading from cache...")
    need_download = []
    for ticker in sorted(all_tickers_needed):
        df = load_from_cache(ticker, months)
        if df is not None:
            cached += 1
            if 'ATR' not in df.columns:
                df['ATR'] = calculate_atr(df['High'], df['Low'], df['Close'], 14)
            if 'HVOL' not in df.columns:
                df['HVOL'] = historical_volatility(df['Close'], CONFIG['hvol_window'])
            all_data[ticker] = df
        else:
            need_download.append(ticker)
    print(f"  Cache hits: {cached}/{total} | Need download: {len(need_download)}")

    # Pass 2: Download missing (EODHD for all, Yahoo fallback only for base tickers)
    if need_download:
        print(f"  Pass 2: Downloading {len(need_download)} missing tickers...")
        for i, ticker in enumerate(need_download):
            is_base = ticker in base_set

            # EODHD only (has delisted data, faster, no Yahoo noise)
            df = download_data_eodhd(ticker, months)

            if df is not None:
                save_to_cache(ticker, df, months)
                downloaded += 1
                if 'ATR' not in df.columns:
                    df['ATR'] = calculate_atr(df['High'], df['Low'], df['Close'], 14)
                if 'HVOL' not in df.columns:
                    df['HVOL'] = historical_volatility(df['Close'], CONFIG['hvol_window'])
                all_data[ticker] = df
            else:
                if not is_base:
                    skipped_delisted += 1
                failed.append(ticker)

            if (i + 1) % 50 == 0 or i == len(need_download) - 1:
                print(f"\r  Descargados: {downloaded}, fallidos: {len(failed)} "
                      f"(delisted: {skipped_delisted})", end='')
        print()

    print(f"  Total con datos: {len(all_data)} | Cache: {cached} | Descargados: {downloaded} | "
          f"Fallidos: {len(failed)} (delisted: {skipped_delisted})")
    if failed and verbose:
        print(f"  Fallidos (primeros 20): {', '.join(sorted(failed)[:20])}")

    return all_data, failed


# =============================================================================
# 7. RUN BACKTEST PIT — Copy of run_backtest_eu with PIT filter
# =============================================================================

def run_backtest_pit(months, tickers, label, use_leverage_scaling=False,
                     use_options=False, options_eligible_set=None,
                     max_us_options=2, max_eu_options=0,
                     macro_exempt_set=None, verbose=False,
                     preloaded_data=None, download_fn=None,
                     pit_eligible_fn=None):
    """
    Backtest v12 con filtro PIT point-in-time.

    Idéntico a run_backtest_eu() EXCEPTO:
    - pit_eligible_fn: callable(ticker, date) -> bool
      Si se pasa, filtra candidatos antes de ranking.
      Si None, comportamiento baseline (sin filtro PIT).
    """
    if options_eligible_set is None:
        options_eligible_set = set(OPTIONS_ELIGIBLE)
    else:
        options_eligible_set = set(options_eligible_set)

    n_tickers = len(tickers)
    pit_label = " [PIT]" if pit_eligible_fn else " [BASELINE]"
    print(f"\n{'='*70}")
    print(f"  {label}{pit_label} -- {months} MESES -- {n_tickers} tickers")
    if use_options:
        n_us = len([t for t in options_eligible_set if t in OPTIONS_ELIGIBLE])
        n_eu = len([t for t in options_eligible_set if t in OPTIONS_ELIGIBLE_EU])
        print(f"  Options eligible: {len(options_eligible_set)} ({n_us} US @ {US_SPREAD_PCT}% + {n_eu} EU @ {EU_SPREAD_PCT}%)")
        print(f"  Slots: US max {max_us_options} + EU max {max_eu_options} = {max_us_options + max_eu_options} total")
    print(f"{'='*70}")

    # --- DATA LOADING ---
    if preloaded_data is not None:
        all_data = {}
        for ticker in tickers:
            if ticker in preloaded_data:
                df = preloaded_data[ticker].copy()
                if 'ATR' not in df.columns:
                    df['ATR'] = calculate_atr(df['High'], df['Low'], df['Close'], 14)
                if 'HVOL' not in df.columns:
                    df['HVOL'] = historical_volatility(df['Close'], CONFIG['hvol_window'])
                all_data[ticker] = df
        print(f"  Datos precargados: {len(all_data)}/{n_tickers} tickers")
    else:
        if download_fn is None:
            download_fn = download_data
        print("  Descargando datos...")
        all_data = {}
        failed = []
        for i, ticker in enumerate(tickers):
            df = download_fn(ticker, months)
            if df is not None:
                df['ATR'] = calculate_atr(df['High'], df['Low'], df['Close'], 14)
                df['HVOL'] = historical_volatility(df['Close'], CONFIG['hvol_window'])
                all_data[ticker] = df
            else:
                failed.append(ticker)
            if (i + 1) % 20 == 0 or i == n_tickers - 1:
                print(f"\r  Descargados: {len(all_data)}/{n_tickers} OK, {len(failed)} fallidos", end='')
        print(f"\n  Tickers con datos: {len(all_data)}")
        if failed:
            print(f"  Fallidos: {', '.join(failed[:10])}{'...' if len(failed) > 10 else ''}")

    if not all_data:
        return {'error': 'No data'}

    # --- ENGINE + SIGNALS ---
    engine = MomentumEngine(
        ker_threshold=CONFIG['ker_threshold'],
        volume_threshold=CONFIG['volume_threshold'],
        rsi_threshold=CONFIG['rsi_threshold'],
        rsi_max=CONFIG['rsi_max'],
        breakout_period=CONFIG['breakout_period'],
        longs_only=CONFIG['longs_only']
    )
    signals_data, total_signals = generate_all_signals(all_data, engine)
    print(f"  Senales LONG totales: {total_signals}")

    # --- MACRO FILTER ---
    macro_bullish = build_macro_filter(all_data)

    # --- TIMELINE ---
    all_dates = sorted(set(d for sd in signals_data.values() for d in sd['df'].index.tolist()))

    tracker = EquityTracker(CONFIG['initial_capital'])
    active_trades = {}
    active_options = {}
    all_trades = []
    all_option_trades = []

    option_opens_us = 0
    option_opens_eu = 0
    open_options_us = 0
    open_options_eu = 0

    # PIT stats
    pit_filtered_count = 0
    pit_passed_count = 0

    # =================================================================
    # MAIN LOOP
    # =================================================================
    for current_date in all_dates:

        # 1. MANAGE ACTIVE STOCK TRADES
        trades_to_close = []
        for ticker, trade in active_trades.items():
            if ticker not in signals_data:
                continue
            df = signals_data[ticker]['df']
            if current_date not in df.index:
                continue
            idx = df.index.get_loc(current_date)
            bar = df.iloc[idx]
            result = trade.update(bar['High'], bar['Low'], bar['Close'], df['ATR'].iloc[idx])
            if result and result['type'] == 'full_exit':
                trade.exit_date = current_date
                trades_to_close.append(ticker)
                tracker.update_equity(trade.pnl_euros, current_date)

        for ticker in trades_to_close:
            trade = active_trades.pop(ticker)
            tracker.open_positions -= 1
            all_trades.append(trade)
            if verbose:
                pnl_pct = (trade.pnl_euros / trade.position_euros * 100) if trade.position_euros else 0
                pnl_sign = '+' if trade.pnl_euros >= 0 else ''
                print(f"  {current_date.strftime('%Y-%m-%d')} | CLOSE {ticker:8} | "
                      f"{trade.exit_reason:<15} | P&L EUR {pnl_sign}{trade.pnl_euros:.0f} ({pnl_sign}{pnl_pct:.1f}%) | "
                      f"Pos: {tracker.open_positions}/10 | Equity: EUR {tracker.equity:,.0f}")

        # 2. MANAGE ACTIVE OPTIONS
        options_to_close = []
        for ticker, opt in active_options.items():
            if ticker not in signals_data:
                continue
            df = signals_data[ticker]['df']
            if current_date not in df.index:
                continue
            idx = df.index.get_loc(current_date)
            bar = df.iloc[idx]
            days_elapsed = (current_date - opt.entry_date).days
            iv = df['HVOL'].iloc[idx]
            if pd.isna(iv) or iv <= 0:
                iv = opt.entry_iv
            result = opt.update(bar['Close'], iv, days_elapsed)
            if result and result['type'] == 'full_exit':
                opt.exit_date = current_date
                options_to_close.append(ticker)
                tracker.update_equity(opt.pnl_euros, current_date)

        for ticker in options_to_close:
            opt = active_options.pop(ticker)
            tracker.open_positions -= 1
            tracker.open_options -= 1
            if ticker in OPTIONS_ELIGIBLE_EU:
                open_options_eu -= 1
            else:
                open_options_us -= 1
            all_option_trades.append(opt)
            if verbose:
                pnl_pct = (opt.pnl_euros / opt.position_euros * 100) if opt.position_euros else 0
                pnl_sign = '+' if opt.pnl_euros >= 0 else ''
                region = "EU" if opt.ticker in OPTIONS_ELIGIBLE_EU else "US"
                print(f"  {current_date.strftime('%Y-%m-%d')} | CLOSE OPT {ticker:8} [{region}] | "
                      f"{opt.exit_reason:<15} | P&L EUR {pnl_sign}{opt.pnl_euros:.0f} ({pnl_sign}{pnl_pct:.1f}%) | "
                      f"Pos: {tracker.open_positions}/10 | Equity: EUR {tracker.equity:,.0f}")

        # 3. FIND NEW SIGNALS
        if CONFIG['use_macro_filter']:
            prev_dates = [d for d in macro_bullish if d < current_date]
            if len(prev_dates) >= 2:
                is_macro_ok = macro_bullish[prev_dates[-2]]
            elif prev_dates:
                is_macro_ok = macro_bullish[prev_dates[-1]]
            else:
                is_macro_ok = True
        else:
            is_macro_ok = True
        total_open = tracker.open_positions

        if total_open < CONFIG['max_positions'] and (is_macro_ok or macro_exempt_set):
            candidates = find_candidates(signals_data, {**active_trades, **active_options},
                                        current_date, is_macro_ok, macro_exempt_set)

            # ═══════════════════════════════════════════════════════════
            # PIT FILTER — the ONLY difference vs baseline
            # ═══════════════════════════════════════════════════════════
            if pit_eligible_fn is not None:
                pre_filter = len(candidates)
                candidates = [(t, idx, atr) for t, idx, atr in candidates
                              if pit_eligible_fn(t, current_date)]
                filtered_out = pre_filter - len(candidates)
                pit_filtered_count += filtered_out
                pit_passed_count += len(candidates)

            ranked = rank_candidates(candidates, signals_data)

            for ticker, idx, prev_atr, composite_score in ranked:
                if tracker.open_positions >= CONFIG['max_positions']:
                    break

                df = signals_data[ticker]['df']
                bar = df.iloc[idx]

                # Decide: option or stock
                open_as_option = False
                current_ivr = None
                is_eu_ticker = ticker in OPTIONS_ELIGIBLE_EU
                if use_options and ticker in options_eligible_set:
                    has_slot = False
                    if is_eu_ticker and open_options_eu < max_eu_options:
                        has_slot = True
                    elif not is_eu_ticker and open_options_us < max_us_options:
                        has_slot = True

                    if has_slot:
                        hvol_series = df['HVOL']
                        current_ivr = iv_rank(hvol_series, idx, CONFIG.get('option_ivr_window', 252))
                        max_ivr = CONFIG.get('option_max_ivr', 40)
                        if current_ivr < max_ivr:
                            open_as_option = True

                if open_as_option:
                    stock_price = bar['Open']
                    strike = stock_price * (1 - CONFIG['option_itm_pct'])
                    actual_dte = monthly_expiration_dte(current_date, CONFIG['option_dte'])
                    T = actual_dte / 365.0
                    iv = df['HVOL'].iloc[idx]
                    if pd.isna(iv) or iv <= 0:
                        iv = 0.30
                    bs = black_scholes_call(stock_price, strike, T, CONFIG['risk_free_rate'], iv)
                    option_price = bs['price']
                    ticker_spread = get_option_spread(ticker)
                    option_price *= (1 + ticker_spread / 100 / 2)
                    size = tracker.get_option_size(option_price)
                    if size['premium'] < 50:
                        continue

                    opt = OptionTradeV2EU(
                        ticker=ticker, entry_date=current_date,
                        entry_stock_price=stock_price, strike=strike,
                        dte_at_entry=actual_dte, entry_option_price=option_price,
                        entry_iv=iv, num_contracts=size['contracts'],
                        position_euros=size['premium'], spread_pct=ticker_spread,
                    )
                    active_options[ticker] = opt
                    tracker.open_positions += 1
                    tracker.open_options += 1

                    if is_eu_ticker:
                        open_options_eu += 1
                        option_opens_eu += 1
                    else:
                        open_options_us += 1
                        option_opens_us += 1

                    if verbose:
                        region = "EU" if ticker in OPTIONS_ELIGIBLE_EU else "US"
                        print(f"  {current_date.strftime('%Y-%m-%d')} | OPEN OPT {ticker:8} [{region} {ticker_spread}%] | "
                              f"K=${strike:.2f} IV={iv:.0%} IVR={current_ivr:.0f} "
                              f"{actual_dte}DTE Prem=${option_price:.2f} x{size['contracts']:.2f}c = EUR {size['premium']:.0f}")
                else:
                    use_lev = use_leverage_scaling
                    size_info = tracker.get_position_size(ticker, prev_atr, bar['Open'], use_lev)
                    entry_price = bar['Open'] * (1 + CONFIG['slippage_pct'] / 100)
                    position_euros = size_info['notional']
                    position_units = size_info['units']

                    max_per_position = tracker.equity / CONFIG['max_positions']
                    if position_euros > max_per_position:
                        position_euros = max_per_position
                        position_units = position_euros / entry_price

                    if position_euros < 100:
                        continue

                    trade = Trade(
                        ticker=ticker, entry_price=entry_price,
                        entry_date=current_date, entry_atr=prev_atr,
                        position_euros=position_euros, position_units=position_units,
                    )
                    active_trades[ticker] = trade
                    tracker.open_positions += 1

                    if verbose:
                        lev = LEVERAGE_FACTORS.get(ticker, 1.0)
                        lev_str = f" [{lev:.0f}x]" if lev > 1 else ""
                        print(f"  {current_date.strftime('%Y-%m-%d')} | OPEN  {ticker:8}{lev_str} | "
                              f"EUR {position_euros:.0f} ({position_units:.2f}u) @ ${entry_price:.2f}")

    # Close open trades at end
    for ticker, trade in active_trades.items():
        if ticker in signals_data:
            df = signals_data[ticker]['df']
            trade._close(df['Close'].iloc[-1], 'end_of_data')
            trade.exit_date = df.index[-1]
            tracker.update_equity(trade.pnl_euros, df.index[-1])
            all_trades.append(trade)

    for ticker, opt in active_options.items():
        if ticker in signals_data:
            df = signals_data[ticker]['df']
            stock_price = df['Close'].iloc[-1]
            intrinsic = max(stock_price - opt.strike, 0)
            opt._close(intrinsic, 'end_of_data')
            opt.exit_date = df.index[-1]
            tracker.update_equity(opt.pnl_euros, df.index[-1])
            all_option_trades.append(opt)

    # =================================================================
    # METRICS
    # =================================================================
    combined_trades = all_trades + all_option_trades
    if not combined_trades:
        return {'error': 'No trades'}

    total_count = len(combined_trades)
    winners = [t for t in combined_trades if (hasattr(t, 'pnl_euros') and t.pnl_euros > 0)]
    losers = [t for t in combined_trades if (hasattr(t, 'pnl_euros') and t.pnl_euros <= 0)]

    total_pnl = sum(t.pnl_euros for t in combined_trades)
    win_rate = len(winners) / total_count * 100 if total_count > 0 else 0

    gross_profit = sum(t.pnl_euros for t in winners) if winners else 0
    gross_loss = abs(sum(t.pnl_euros for t in losers)) if losers else 0.01
    profit_factor = gross_profit / gross_loss

    max_dd = tracker.get_max_drawdown()
    total_return_pct = (tracker.equity / CONFIG['initial_capital'] - 1) * 100
    annualized = ((1 + total_return_pct / 100) ** (12 / months) - 1) * 100 if months > 0 else 0

    avg_win_pct = np.mean([t.pnl_pct for t in winners]) if winners else 0
    avg_loss_pct = np.mean([t.pnl_pct for t in losers]) if losers else 0

    stock_gt_3r = sum(1 for t in all_trades if t.max_r_mult >= 3.0)
    opt_home_runs = sum(1 for t in all_option_trades if t.pnl_pct >= 100)

    best_trade = max(combined_trades, key=lambda t: t.pnl_pct)
    worst_trade = min(combined_trades, key=lambda t: t.pnl_pct)

    opt_us = [t for t in all_option_trades if t.ticker not in OPTIONS_ELIGIBLE_EU]
    opt_eu = [t for t in all_option_trades if t.ticker in OPTIONS_ELIGIBLE_EU]
    pnl_opt_us = sum(t.pnl_euros for t in opt_us) if opt_us else 0
    pnl_opt_eu = sum(t.pnl_euros for t in opt_eu) if opt_eu else 0

    # PIT stats
    pit_info = ""
    if pit_eligible_fn is not None:
        pit_info = f"\n  PIT FILTER:\n     Candidatos filtrados: {pit_filtered_count}\n     Candidatos pasaron:   {pit_passed_count}"

    print(f"""
{'='*70}
  RESULTADOS {label}{pit_label} -- {months} MESES
{'='*70}

  CAPITAL:
     Inicial:        EUR {CONFIG['initial_capital']:,.2f}
     Final:          EUR {tracker.equity:,.2f}
     P&L Total:      EUR {total_pnl:+,.2f} ({total_return_pct:+.1f}%)
     Annualizado:    {annualized:+.1f}%
     Max Drawdown:   -{max_dd:.1f}%

  TRADES:
     Total:          {total_count} (stocks: {len(all_trades)}, opciones: {len(all_option_trades)})
     Ganadores:      {len(winners)} ({win_rate:.1f}%)
     Perdedores:     {len(losers)}
     Profit Factor:  {profit_factor:.2f}

  FAT TAILS:
     Stocks >= +3R:  {stock_gt_3r}
     Options >= +100%: {opt_home_runs}
     Avg Win:        {avg_win_pct:+.1f}%
     Avg Loss:       {avg_loss_pct:.1f}%
     Best:           {best_trade.ticker} {best_trade.pnl_pct:+.1f}%
     Worst:          {worst_trade.ticker} {worst_trade.pnl_pct:+.1f}%

  OPCIONES DESGLOSE:
     US trades:      {len(opt_us)} opens ({option_opens_us} total) | P&L EUR {pnl_opt_us:+,.0f}
     EU trades:      {len(opt_eu)} opens ({option_opens_eu} total) | P&L EUR {pnl_opt_eu:+,.0f}
{pit_info}
""")

    # Exit reasons
    exit_reasons = {}
    for t in combined_trades:
        reason = t.exit_reason or 'unknown'
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
    print("  RAZONES DE SALIDA:")
    for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
        print(f"     {reason:20} {count:3} ({count/total_count*100:.1f}%)")

    return {
        'label': label,
        'total_trades': total_count,
        'stock_trades': len(all_trades),
        'option_trades': len(all_option_trades),
        'option_trades_us': len(opt_us),
        'option_trades_eu': len(opt_eu),
        'option_pnl_us': pnl_opt_us,
        'option_pnl_eu': pnl_opt_eu,
        'winners': len(winners),
        'losers': len(losers),
        'win_rate': win_rate,
        'total_pnl_euros': total_pnl,
        'total_return_pct': total_return_pct,
        'annualized_return_pct': annualized,
        'profit_factor': profit_factor,
        'max_drawdown': max_dd,
        'avg_win_pct': avg_win_pct,
        'avg_loss_pct': avg_loss_pct,
        'best_ticker': best_trade.ticker,
        'best_pnl_pct': best_trade.pnl_pct,
        'stock_gt_3r': stock_gt_3r,
        'opt_home_runs': opt_home_runs,
        'final_equity': tracker.equity,
        'equity_curve': tracker.equity_curve,
        'all_trades': all_trades,
        'all_option_trades': all_option_trades,
        'combined_trades': combined_trades,
        'pit_filtered_count': pit_filtered_count,
        'pit_passed_count': pit_passed_count,
    }


# =============================================================================
# 8. COMPARISON PRINTER
# =============================================================================

def print_pit_comparison(r_baseline, r_pit, gold_baseline=None, gold_pit=None):
    """Print side-by-side comparison of baseline vs PIT results."""
    print(f"""
{'='*80}
  COMPARATIVA: BASELINE (225 fijos) vs PIT (point-in-time)
{'='*80}

  {'Metrica':<22} {'Baseline':>12} {'PIT':>12} {'Delta':>12}
  {'-'*60}""")

    metrics = [
        ('CAGR', 'annualized_return_pct', '%', '+'),
        ('Max Drawdown', 'max_drawdown', '%', ''),
        ('Profit Factor', 'profit_factor', '', ''),
        ('Trades', 'total_trades', '', ''),
        ('Win Rate', 'win_rate', '%', ''),
        ('Stock Trades', 'stock_trades', '', ''),
        ('Option Trades', 'option_trades', '', ''),
        ('Equity Final', 'final_equity', 'EUR', ''),
    ]

    for name, key, unit, sign in metrics:
        b = r_baseline.get(key, 0)
        p = r_pit.get(key, 0)
        d = p - b

        if unit == 'EUR':
            print(f"  {name:<22} EUR {b:>9,.0f} EUR {p:>9,.0f} EUR {d:>+9,.0f}")
        elif unit == '%':
            print(f"  {name:<22} {b:>+10.1f}% {p:>+10.1f}% {d:>+10.1f}pp")
        else:
            print(f"  {name:<22} {b:>12.2f} {p:>12.2f} {d:>+12.2f}")

    # PIT filtering stats
    if r_pit.get('pit_filtered_count'):
        total_cand = r_pit['pit_filtered_count'] + r_pit['pit_passed_count']
        filt_pct = r_pit['pit_filtered_count'] / total_cand * 100 if total_cand > 0 else 0
        print(f"\n  PIT: {r_pit['pit_filtered_count']} candidatos filtrados de {total_cand} ({filt_pct:.1f}%)")

    # Gold overlay comparison
    if gold_baseline and gold_pit:
        print(f"""
  {'Metrica':<22} {'Base+Gold':>12} {'PIT+Gold':>12} {'Delta':>12}
  {'-'*60}
  {'CAGR + Gold':<22} {gold_baseline['ann_gold']:>+10.1f}% {gold_pit['ann_gold']:>+10.1f}% {gold_pit['ann_gold'] - gold_baseline['ann_gold']:>+10.1f}pp
  {'MaxDD + Gold':<22} {gold_baseline['maxdd_gold']:>10.1f}% {gold_pit['maxdd_gold']:>10.1f}% {gold_pit['maxdd_gold'] - gold_baseline['maxdd_gold']:>+10.1f}pp
  {'Equity + Gold':<22} EUR {gold_baseline['equity_gold']:>9,.0f} EUR {gold_pit['equity_gold']:>9,.0f} EUR {gold_pit['equity_gold'] - gold_baseline['equity_gold']:>+9,.0f}
""")

    print()


# =============================================================================
# 9. CSV/JSON EXPORT
# =============================================================================

def export_trades_csv(result, ticker_class, dv_cache, sp500_change_points, filename):
    """Export all trades to CSV with PIT metadata."""
    rows = []
    for trade in result.get('combined_trades', []):
        ticker = trade.ticker
        cls = ticker_class.get(ticker, 'unknown')

        # Dollar volume at entry
        dv_at_entry = None
        if ticker in dv_cache and trade.entry_date:
            dv = dv_cache[ticker]
            ts = pd.Timestamp(trade.entry_date)
            valid = dv[dv.index <= ts]
            if not valid.empty:
                dv_at_entry = valid.iloc[-1]

        # SP500 membership at entry
        sp500_member = None
        if cls == 'us_stock' and sp500_change_points and trade.entry_date:
            members = get_sp500_members_at(sp500_change_points, trade.entry_date)
            ticker_variants = {ticker, ticker.replace('-', '.'), ticker.replace('.', '-')}
            sp500_member = bool(ticker_variants & members)

        # PIT rule applied
        if cls == 'etf':
            pit_rule = 'etf_inception'
        elif cls == 'us_stock':
            pit_rule = 'sp500'
        else:
            pit_rule = 'dollar_vol'

        is_option = isinstance(trade, OptionTradeV2EU)

        row = {
            'ticker': ticker,
            'type': 'option' if is_option else 'stock',
            'entry_date': trade.entry_date.strftime('%Y-%m-%d') if trade.entry_date else '',
            'exit_date': trade.exit_date.strftime('%Y-%m-%d') if trade.exit_date else '',
            'exit_reason': trade.exit_reason or '',
            'pnl_eur': round(trade.pnl_euros, 2),
            'pnl_pct': round(trade.pnl_pct, 2),
            'bars_held': trade.bars_held,
            'ticker_class': cls,
            'pit_rule': pit_rule,
            'sp500_member': sp500_member,
            'dollar_vol_at_entry': round(dv_at_entry, 0) if dv_at_entry and not pd.isna(dv_at_entry) else None,
        }

        if is_option:
            row['strike'] = round(trade.strike, 2)
            row['entry_option_price'] = round(trade.entry_option_price, 2)
            row['spread_pct'] = trade.spread_pct
        else:
            row['entry_price'] = round(trade.entry_price, 2)
            row['position_eur'] = round(trade.position_euros, 2)
            row['max_r_mult'] = round(trade.max_r_mult, 2)

        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv(filename, index=False)
    print(f"  Trades exportados a: {filename}")
    return df


def export_results_json(result, gold_result, filename, extra=None):
    """Export results to JSON."""
    data = {
        'run_date': datetime.now().strftime('%Y-%m-%d'),
        'months': result.get('label', ''),
        'cagr': round(result['annualized_return_pct'], 2),
        'max_dd': round(result['max_drawdown'], 2),
        'profit_factor': round(result['profit_factor'], 2),
        'total_trades': result['total_trades'],
        'stock_trades': result['stock_trades'],
        'option_trades': result['option_trades'],
        'win_rate': round(result['win_rate'], 1),
        'final_equity': round(result['final_equity'], 2),
        'pit_filtered': result.get('pit_filtered_count', 0),
        'pit_passed': result.get('pit_passed_count', 0),
    }
    if gold_result:
        data['gold_cagr'] = round(gold_result['ann_gold'], 2)
        data['gold_max_dd'] = round(gold_result['maxdd_gold'], 2)
        data['gold_equity'] = round(gold_result['equity_gold'], 2)
    if extra:
        data.update(extra)

    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"  Resultados exportados a: {filename}")


# =============================================================================
# 10. MAIN
# =============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Backtest v12g PIT — Survivorship-bias-free')
    parser.add_argument('--months', type=int, default=120, help='Meses de historico (default: 120)')
    parser.add_argument('--verbose', action='store_true', help='Detalle de trades')
    parser.add_argument('--multi-period', action='store_true', help='Test a 24, 60, 120m')
    parser.add_argument('--gold', action='store_true', help='Aplicar Gold 30%% overlay')
    parser.add_argument('--gold-pct', type=float, default=0.30, help='Fraccion en oro (default: 0.30)')
    parser.add_argument('--export-csv', action='store_true', help='Exportar trades a CSV')
    parser.add_argument('--baseline-only', action='store_true', help='Solo baseline (sin PIT)')
    args = parser.parse_args()

    print(f"""
======================================================================
  BACKTEST v12g PIT — SURVIVORSHIP-BIAS-FREE
======================================================================
  Periodo:    {args.months} meses
  Gold:       {'SI (' + str(args.gold_pct*100) + '%)' if args.gold else 'NO'}
  Multi:      {'SI' if args.multi_period else 'NO'}
  Fuente:     EODHD + Yahoo fallback
======================================================================
    """)

    # ── Step 1: Fetch SP500 history ──
    print("  [1/6] Fetching SP500 historical changes from Wikipedia...")
    sp500_current, sp500_changes = fetch_sp500_changes()
    sp500_ever = get_all_sp500_tickers_ever(sp500_current, sp500_changes)
    print(f"  SP500: {len(sp500_current)} current members, {len(sp500_changes)} historical changes, "
          f"{len(sp500_ever)} tickers ever in index")

    # ── Step 2: Classify tickers ──
    print("  [2/6] Classifying tickers...")
    ticker_class = build_ticker_classification()
    counts = defaultdict(int)
    for cls in ticker_class.values():
        counts[cls] += 1
    print(f"  Classification: {dict(counts)}")

    # ── Step 3: Build PIT membership series ──
    max_months = max([24, 60, 120] if args.multi_period else [args.months])
    start_date = datetime.now() - timedelta(days=max_months * 30 + 60)
    end_date = datetime.now()

    print("  [3/6] Building SP500 PIT membership series...")
    sp500_change_points = build_pit_membership_series(
        sp500_current, sp500_changes, start_date, end_date
    )
    members_start = get_sp500_members_at(sp500_change_points, start_date)
    members_end = get_sp500_members_at(sp500_change_points, end_date)
    print(f"  SP500 members: {len(members_start)} at start -> {len(members_end)} at end")

    # ── Step 4: Download data ──
    # Determine which tickers to download
    if max_months >= 120:
        # For long periods: expand universe with historical SP500 members
        tickers_to_download = sorted(set(BASE_TICKERS) | sp500_ever)
        tickers_to_download = [t for t in tickers_to_download
                               if t and t != 'nan' and len(t) <= 10]
        print(f"  [4/6] Downloading expanded universe: {len(tickers_to_download)} tickers ({max_months}m)...")
    else:
        # For short periods: base 225 only (delisted tickers won't have recent data)
        tickers_to_download = list(BASE_TICKERS)
        print(f"  [4/6] Downloading {len(tickers_to_download)} base tickers ({max_months}m)...")

    all_data = {}
    failed_tickers = []
    for i, ticker in enumerate(tickers_to_download):
        df = download_data_eodhd(ticker, max_months)
        if df is not None:
            if 'ATR' not in df.columns:
                df['ATR'] = calculate_atr(df['High'], df['Low'], df['Close'], 14)
            if 'HVOL' not in df.columns:
                df['HVOL'] = historical_volatility(df['Close'], CONFIG['hvol_window'])
            all_data[ticker] = df
        else:
            failed_tickers.append(ticker)
        if (i + 1) % 50 == 0 or i == len(tickers_to_download) - 1:
            print(f"\r  Progreso: {i+1}/{len(tickers_to_download)} OK={len(all_data)} fail={len(failed_tickers)}", end='')
    print(f"\n  Tickers con datos: {len(all_data)}/{len(tickers_to_download)} | "
          f"Fallidos: {len(failed_tickers)}")

    # ── Step 5: Compute dollar volume ──
    print("  [5/6] Computing dollar volume PIT series...")
    dv_cache = compute_dollar_volume_series(all_data)
    # Stats: how many EU/Asia pass $500M
    eu_asia_tickers = [t for t, c in ticker_class.items() if c in ('eu_stock', 'asia_stock')]
    dv_pass = sum(1 for t in eu_asia_tickers if t in dv_cache and dv_cache[t].max() >= MIN_DOLLAR_VOL)
    print(f"  EU/Asia: {dv_pass}/{len(eu_asia_tickers)} pass $500M dollar volume threshold")

    # ── Step 6: Build PIT eligible function ──
    print("  [6/6] Building PIT eligibility function...")
    pit_fn = build_pit_eligible_fn(ticker_class, sp500_change_points, dv_cache)

    # ── Download GLD for gold overlay ──
    gld_data = None
    if args.gold:
        if 'GLD' in all_data:
            gld_data = all_data['GLD']
        else:
            gld_data = download_data_eodhd('GLD', max_months + 6)
            if gld_data is None:
                gld_data = download_data('GLD', max_months + 6)
        if gld_data is None:
            print("  WARNING: No GLD data, gold overlay disabled")
            args.gold = False

    # ── RUN BACKTESTS ──
    periods = [24, 60, 120] if args.multi_period else [args.months]
    all_tickers_list = sorted(all_data.keys())

    for m in periods:
        print(f"\n{'#'*70}")
        print(f"  PERÍODO: {m} MESES ({m/12:.0f} años)")
        print(f"{'#'*70}")

        # BASELINE (original 225 tickers, no PIT filter)
        r_baseline = run_backtest_pit(
            m, BASE_TICKERS, f"v12g Baseline ({m}m)",
            use_options=True,
            options_eligible_set=OPTIONS_ALL,
            max_us_options=2, max_eu_options=2,
            macro_exempt_set=MACRO_EXEMPT,
            preloaded_data=all_data,
            pit_eligible_fn=None,  # NO PIT
            verbose=args.verbose,
        )

        if args.baseline_only:
            if args.gold and gld_data is not None and 'error' not in r_baseline:
                g = simulate_gold_overlay(r_baseline, gld_data, args.gold_pct)
                if g:
                    print(f"  + Gold {args.gold_pct*100:.0f}%: CAGR {g['ann_gold']:+.1f}%, "
                          f"MaxDD -{g['maxdd_gold']:.1f}%, Equity EUR {g['equity_gold']:,.0f}")
            continue

        # PIT (expanded universe, PIT filter active)
        r_pit = run_backtest_pit(
            m, all_tickers_list, f"v12g PIT ({m}m)",
            use_options=True,
            options_eligible_set=OPTIONS_ALL,
            max_us_options=2, max_eu_options=2,
            macro_exempt_set=MACRO_EXEMPT,
            preloaded_data=all_data,
            pit_eligible_fn=pit_fn,  # PIT ACTIVE
            verbose=args.verbose,
        )

        # Gold overlay
        g_baseline = None
        g_pit = None
        if args.gold and gld_data is not None:
            if 'error' not in r_baseline:
                g_baseline = simulate_gold_overlay(r_baseline, gld_data, args.gold_pct)
            if 'error' not in r_pit:
                g_pit = simulate_gold_overlay(r_pit, gld_data, args.gold_pct)

        # Comparison
        if 'error' not in r_baseline and 'error' not in r_pit:
            print_pit_comparison(r_baseline, r_pit, g_baseline, g_pit)

        # Export
        if args.export_csv and 'error' not in r_pit:
            csv_file = f"mb_v12g_pit_trades_{m}m.csv"
            export_trades_csv(r_pit, ticker_class, dv_cache, sp500_change_points, csv_file)

            json_file = f"mb_v12g_pit_results_{m}m.json"
            export_results_json(r_pit, g_pit, json_file, extra={
                'baseline_cagr': r_baseline.get('annualized_return_pct', 0),
                'baseline_pf': r_baseline.get('profit_factor', 0),
                'baseline_dd': r_baseline.get('max_drawdown', 0),
            })

    # ── Validation checks ──
    print(f"\n{'='*70}")
    print("  VALIDATION CHECKS")
    print(f"{'='*70}")

    # Check TQQQ not traded before 2010
    for period_result in [r_pit] if not args.multi_period else []:
        if 'combined_trades' in period_result:
            for t in period_result['combined_trades']:
                if t.ticker == 'TQQQ' and t.entry_date and t.entry_date < pd.Timestamp('2010-02-09'):
                    print(f"  ❌ TQQQ traded before inception: {t.entry_date}")
                if t.ticker == 'BITO' and t.entry_date and t.entry_date < pd.Timestamp('2021-10-19'):
                    print(f"  ❌ BITO traded before inception: {t.entry_date}")

    print("  ✓ Validation complete")
    print()


if __name__ == '__main__':
    main()

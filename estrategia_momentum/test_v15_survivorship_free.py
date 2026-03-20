#!/usr/bin/env python3
"""
Test v15: Backtest Survivorship-Free con Universo Rotativo
==========================================================
Fecha: 17 Mar 2026
Objetivo: Eliminar survivorship bias usando universos históricos reales.

Metodología:
  - Universo rotativo cada 5 años: usa los top 10 por sector del S&P 500
    TAL COMO ERAN EN CADA MOMENTO, no los de hoy.
  - 2006 snapshot → usado para barras de 2006-2010
  - 2011 snapshot → usado para barras de 2011-2015
  - 2016 snapshot → usado para barras de 2016-2020
  - 2021 snapshot → usado para barras de 2021-2026
  - ETFs: universo fijo (GLD, TLT, etc.) — sin survivorship bias

Comparación:
  - v12 original (225 tickers fijos) vs v15 rotativo (97 por período + ETFs)
  - Stock-only Y con opciones US (2 slots)

Tickers delisted se mapean a sucesor si existe, o se excluyen.
Esto es MÁS CONSERVADOR que la realidad (subestimamos rendimiento de
tickers que desaparecieron por adquisición premium, ej. Celgene +62%).
"""

import sys
import os
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime

warnings.filterwarnings('ignore')

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

from backtest_experimental import (
    download_data, calculate_atr, historical_volatility,
    generate_all_signals, build_macro_filter,
    find_candidates, rank_candidates,
    Trade, EquityTracker,
    CONFIG, OPTIONS_ELIGIBLE,
)
from backtest_v12_eu_options import (
    run_backtest_eu, OPTIONS_ELIGIBLE_EU,
    OptionTradeV2EU, get_option_spread,
    black_scholes_call, monthly_expiration_dte, iv_rank,
)
from momentum_breakout import MomentumEngine, ASSETS
from sp500_historical_universe import (
    SP500_HISTORICAL, TICKER_MAP_CURRENT, get_all_unique_tickers,
)
from data_eodhd import download_data_eodhd

# =============================================================================
# ETFs FIJOS (sin survivorship bias)
# =============================================================================
ETF_UNIVERSE = [
    # Commodities
    'GLD', 'SLV', 'GDX', 'GDXJ', 'USO', 'UNG', 'DBA',
    # Sector
    'XLE', 'XLF', 'XLK', 'XLV', 'XLI', 'XLU', 'SMH', 'XBI',
    # International
    'EEM', 'VWO', 'EWJ', 'EWZ', 'FXI',
    # Fixed income
    'TLT', 'IEF', 'HYG', 'LQD', 'AGG',
    # Broad/Size
    'QQQ', 'IWM', 'SPY',
]

# =============================================================================
# EU + ASIA FIJOS (blue chips históricas, misma lógica que SP500 top-10)
# No cambian por periodo — son las más grandes por país, sin cherry-picking.
# =============================================================================
EU_UNIVERSE = [
    # Alemania
    'SAP', 'SIE.DE', 'ALV.DE', 'DTE.DE', 'MUV2.DE', 'BAS.DE', 'BMW.DE', 'MBG.DE', 'ADS.DE', 'IFX.DE',
    # Francia
    'OR.PA', 'MC.PA', 'SAN.PA', 'AI.PA', 'BNP.PA', 'SU.PA', 'AIR.PA', 'CS.PA', 'DG.PA', 'RI.PA',
    # Holanda
    'ASML', 'INGA.AS', 'PHIA.AS', 'AD.AS',
    # España
    'IBE.MC', 'SAN.MC', 'TEF.MC', 'ITX.MC',
    # Italia
    'ENEL.MI', 'ISP.MI', 'UCG.MI', 'ENI.MI',
    # Bélgica
    'KBC.BR', 'ABI.BR',
    # Nórdicos
    'NOK', 'NOVO-B.CO', 'ERIC-B.ST', 'VOLV-B.ST', 'SAND.ST', 'NESTE.HE',
    # UK (ADRs en US o .L)
    'SHEL', 'HSBC', 'BP', 'RIO', 'GSK', 'ULVR.L', 'LSEG.L', 'BATS.L', 'DGE.L',
    # Suiza
    'NESN.SW', 'ROG.SW', 'NOVN.SW', 'UBSG.SW', 'ZURN.SW', 'ABBN.SW',
    # Irlanda
    'CRH',
]

ASIA_UNIVERSE = [
    # Japón
    '7203.T', '6758.T', '6861.T', '8306.T', '9984.T', '6501.T', '7267.T', '8035.T', '4063.T', '9432.T',
    # Australia
    'BHP.AX', 'CBA.AX', 'CSL.AX', 'NAB.AX', 'WBC.AX', 'FMG.AX', 'WDS.AX', 'RIO.AX',
    # China (ADRs)
    'BABA', 'JD', 'PDD', 'BIDU', '0700.HK',
]


def resolve_ticker(ticker):
    """Mapea ticker histórico a su equivalente descargable actual."""
    if ticker in TICKER_MAP_CURRENT:
        return TICKER_MAP_CURRENT[ticker]  # None si delisted
    return ticker


def get_universe_for_date(current_date):
    """Devuelve la lista de tickers del universo vigente para una fecha dada."""
    year = current_date.year

    if year <= 2010:
        snapshot = SP500_HISTORICAL[2006]
    elif year <= 2015:
        snapshot = SP500_HISTORICAL[2011]
    elif year <= 2020:
        snapshot = SP500_HISTORICAL[2016]
    else:
        snapshot = SP500_HISTORICAL[2021]

    tickers = []
    for sector_tickers in snapshot.values():
        for t in sector_tickers:
            resolved = resolve_ticker(t)
            if resolved is not None and resolved not in tickers:
                tickers.append(resolved)

    # Add ETFs + EU + Asia (fijos, blue chips históricas)
    for universe in [ETF_UNIVERSE, EU_UNIVERSE, ASIA_UNIVERSE]:
        for t in universe:
            if t not in tickers:
                tickers.append(t)

    return tickers


def run_backtest_rotating(months, label, use_options=False, preloaded_data=None,
                          options_eligible_override=None, max_us_options=2,
                          max_eu_options=0, verbose=False):
    """
    Backtest con universo rotativo cada 5 años.
    Soporta opciones US (2 slots) + EU (2 slots) con spreads diferenciados.

    La lógica es: en cada barra del loop, solo se consideran candidatos
    que estén en el universo vigente para esa fecha.
    """
    print(f"\n{'='*70}")
    print(f"  {label} -- {months} MESES -- Universo ROTATIVO")
    if use_options:
        print(f"  Opciones: US max {max_us_options} slots @ 3% + EU max {max_eu_options} slots @ 10%")
    print(f"{'='*70}")

    # Necesitamos TODOS los datos de TODOS los tickers posibles
    all_possible = set()
    for year_data in SP500_HISTORICAL.values():
        for sector_tickers in year_data.values():
            for t in sector_tickers:
                resolved = resolve_ticker(t)
                if resolved:
                    all_possible.add(resolved)
    for universe in [ETF_UNIVERSE, EU_UNIVERSE, ASIA_UNIVERSE]:
        for t in universe:
            all_possible.add(t)

    all_possible = sorted(all_possible)

    # Cargar datos
    if preloaded_data is not None:
        all_data = {}
        for ticker in all_possible:
            if ticker in preloaded_data:
                df = preloaded_data[ticker].copy()
                if 'ATR' not in df.columns:
                    df['ATR'] = calculate_atr(df['High'], df['Low'], df['Close'], 14)
                if 'HVOL' not in df.columns:
                    df['HVOL'] = historical_volatility(df['Close'], CONFIG['hvol_window'])
                all_data[ticker] = df
        print(f"  Datos precargados: {len(all_data)}/{len(all_possible)} tickers")
    else:
        print(f"  Descargando {len(all_possible)} tickers...")
        all_data = {}
        failed = []
        for ticker in all_possible:
            df = download_data_eodhd(ticker, months)
            if df is None:
                df = download_data(ticker, months)
            if df is not None:
                df['ATR'] = calculate_atr(df['High'], df['Low'], df['Close'], 14)
                df['HVOL'] = historical_volatility(df['Close'], CONFIG['hvol_window'])
                all_data[ticker] = df
            else:
                failed.append(ticker)
        print(f"  OK: {len(all_data)} | Fallidos: {len(failed)}")
        if failed:
            print(f"  Fallidos: {failed}")

    if not all_data:
        return {'error': 'No data'}

    # Engine + señales para TODO el superset
    engine = MomentumEngine(
        ker_threshold=CONFIG['ker_threshold'],
        volume_threshold=CONFIG['volume_threshold'],
        rsi_threshold=CONFIG['rsi_threshold'],
        rsi_max=CONFIG['rsi_max'],
        breakout_period=CONFIG['breakout_period'],
        longs_only=CONFIG['longs_only']
    )
    signals_data, total_signals = generate_all_signals(all_data, engine)
    print(f"  Señales LONG totales (superset): {total_signals}")

    # Filtro macro
    macro_bullish = build_macro_filter(all_data)

    # Timeline
    all_dates = sorted(set(d for sd in signals_data.values() for d in sd['df'].index.tolist()))

    tracker = EquityTracker(CONFIG['initial_capital'])
    active_trades = {}
    active_options = {}
    all_trades = []
    all_option_trades = []

    open_options_us = 0
    open_options_eu = 0

    # Options eligible sets
    eu_options_set = set(OPTIONS_ELIGIBLE_EU)  # EU tickers con opciones (spread 10%)
    if options_eligible_override is not None:
        us_options_set = set(options_eligible_override) - eu_options_set
    else:
        # US: All SP500 + ETFs in OPTIONS_ELIGIBLE
        us_options_set = set(all_possible) - set(ETF_UNIVERSE) - set(EU_UNIVERSE) - set(ASIA_UNIVERSE)
        us_options_set |= (set(OPTIONS_ELIGIBLE) & set(ETF_UNIVERSE))
    options_eligible_set = us_options_set | eu_options_set

    signals_filtered_by_universe = 0

    # =================================================================
    # LOOP PRINCIPAL
    # =================================================================
    for current_date in all_dates:

        # Determinar universo vigente para esta fecha
        current_universe = set(get_universe_for_date(current_date))

        # 1. GESTIONAR TRADES ACTIVOS (no afectados por rotación — se cierran normalmente)
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

        # 2. GESTIONAR OPCIONES ACTIVAS
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
            if ticker in eu_options_set:
                open_options_eu -= 1
            else:
                open_options_us -= 1
            all_option_trades.append(opt)

        # 3. BUSCAR NUEVAS SEÑALES (SOLO del universo vigente)
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

        if tracker.open_positions < CONFIG['max_positions'] and is_macro_ok:
            candidates = find_candidates(signals_data, {**active_trades, **active_options},
                                         current_date, is_macro_ok, None)
            ranked = rank_candidates(candidates, signals_data)

            for ticker, idx, prev_atr, composite_score in ranked:
                if tracker.open_positions >= CONFIG['max_positions']:
                    break

                # FILTRO CLAVE: solo tickers del universo vigente
                if ticker not in current_universe:
                    signals_filtered_by_universe += 1
                    continue

                df = signals_data[ticker]['df']
                bar = df.iloc[idx]

                # Decidir opción o acción
                # SLOTS SEPARADOS: US (max_us_options) y EU (max_eu_options)
                open_as_option = False
                is_eu_opt = ticker in eu_options_set
                if use_options and ticker in options_eligible_set:
                    has_slot = False
                    if is_eu_opt and open_options_eu < max_eu_options:
                        has_slot = True
                    elif not is_eu_opt and open_options_us < max_us_options:
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

                    # SPREAD DIFERENCIADO: US 3% vs EU 10%
                    ticker_spread = 10.0 if is_eu_opt else 3.0
                    option_price *= (1 + ticker_spread / 100 / 2)

                    size = tracker.get_option_size(option_price)
                    if size['premium'] < 50:
                        continue

                    opt = OptionTradeV2EU(
                        ticker=ticker,
                        entry_date=current_date,
                        entry_stock_price=stock_price,
                        strike=strike,
                        dte_at_entry=actual_dte,
                        entry_option_price=option_price,
                        entry_iv=iv,
                        num_contracts=size['contracts'],
                        position_euros=size['premium'],
                        spread_pct=ticker_spread,
                    )
                    active_options[ticker] = opt
                    tracker.open_positions += 1
                    tracker.open_options += 1
                    if is_eu_opt:
                        open_options_eu += 1
                    else:
                        open_options_us += 1

                else:
                    # Acción — sizing idéntico a v12
                    entry_price = bar['Open'] * (1 + CONFIG['slippage_pct'] / 100)
                    size_info = tracker.get_position_size(ticker, prev_atr, bar['Open'], False)
                    position_euros = size_info['notional']
                    position_units = size_info['units']

                    max_per_position = tracker.equity / CONFIG['max_positions']
                    if position_euros > max_per_position:
                        position_euros = max_per_position
                        position_units = position_euros / entry_price

                    if position_euros < 100:
                        continue

                    trade = Trade(
                        ticker=ticker,
                        entry_price=entry_price,
                        entry_date=current_date,
                        entry_atr=prev_atr,
                        position_euros=position_euros,
                        position_units=position_units,
                    )
                    active_trades[ticker] = trade
                    tracker.open_positions += 1

    # Cerrar posiciones abiertas
    for ticker, trade in list(active_trades.items()):
        df = signals_data[ticker]['df']
        last_bar = df.iloc[-1]
        trade.pnl_euros = (last_bar['Close'] - trade.entry_price) * trade.position_units
        trade.pnl_pct = ((last_bar['Close'] / trade.entry_price) - 1) * 100
        trade.exit_reason = 'end_of_data'
        trade.exit_date = df.index[-1]
        tracker.update_equity(trade.pnl_euros, df.index[-1])
        all_trades.append(trade)

    for ticker, opt in list(active_options.items()):
        df = signals_data[ticker]['df']
        last_bar = df.iloc[-1]
        days_elapsed = (df.index[-1] - opt.entry_date).days
        iv = df['HVOL'].iloc[-1]
        if pd.isna(iv) or iv <= 0:
            iv = opt.entry_iv
        remaining_dte = max(opt.dte_at_entry - days_elapsed, 1)
        T = remaining_dte / 365.0
        bs = black_scholes_call(last_bar['Close'], opt.strike, T, CONFIG['risk_free_rate'], iv)
        close_spread = 10.0 if ticker in eu_options_set else 3.0
        close_price = bs['price'] * (1 - close_spread / 100 / 2)
        opt._close(close_price, 'end_of_data')
        opt.exit_date = df.index[-1]
        tracker.update_equity(opt.pnl_euros, df.index[-1])
        all_option_trades.append(opt)

    # =================================================================
    # RESULTADOS
    # =================================================================
    combined = all_trades + all_option_trades
    if not combined:
        return {'error': 'No trades'}

    total_count = len(combined)
    winners = [t for t in combined if t.pnl_euros > 0]
    losers = [t for t in combined if t.pnl_euros <= 0]

    total_pnl = sum(t.pnl_euros for t in combined)
    win_rate = len(winners) / total_count * 100
    gross_profit = sum(t.pnl_euros for t in winners) if winners else 0
    gross_loss = abs(sum(t.pnl_euros for t in losers)) if losers else 0.01
    pf = gross_profit / gross_loss
    max_dd = tracker.get_max_drawdown()
    total_ret = (tracker.equity / CONFIG['initial_capital'] - 1) * 100
    cagr = ((1 + total_ret / 100) ** (12 / months) - 1) * 100

    opt_us = [t for t in all_option_trades if t.ticker not in eu_options_set]
    opt_eu = [t for t in all_option_trades if t.ticker in eu_options_set]
    pnl_opt_us = sum(t.pnl_euros for t in opt_us) if opt_us else 0
    pnl_opt_eu = sum(t.pnl_euros for t in opt_eu) if opt_eu else 0

    print(f"\n  RESULTADOS {label}")
    print(f"  {'='*50}")
    print(f"  Capital: EUR {CONFIG['initial_capital']:,.0f} → EUR {tracker.equity:,.0f}")
    print(f"  CAGR: {cagr:+.1f}% | MaxDD: {max_dd:.1f}% | PF: {pf:.2f}")
    print(f"  Trades: {len(all_trades)} stock + {len(all_option_trades)} opciones ({len(opt_us)} US + {len(opt_eu)} EU) = {total_count}")
    print(f"  WR: {win_rate:.1f}% | PnL: EUR {total_pnl:+,.0f}")
    print(f"  Señales filtradas por universo: {signals_filtered_by_universe}")
    if all_option_trades:
        print(f"  PnL opciones US: EUR {pnl_opt_us:+,.0f} | EU: EUR {pnl_opt_eu:+,.0f}")

    return {
        'label': label,
        'stock_trades': len(all_trades),
        'option_trades': len(all_option_trades),
        'option_trades_us': len(opt_us),
        'option_trades_eu': len(opt_eu),
        'total_trades': total_count,
        'win_rate': win_rate,
        'profit_factor': pf,
        'annualized_return_pct': cagr,
        'max_drawdown': max_dd,
        'total_pnl_euros': total_pnl,
        'option_pnl_us': pnl_opt_us,
        'option_pnl_eu': pnl_opt_eu,
        'final_equity': tracker.equity,
        'equity_curve': tracker.equity_curve,
        'signals_filtered': signals_filtered_by_universe,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--months', type=int, default=24)
    args = parser.parse_args()
    months = args.months

    print(f"\n{'#'*70}")
    print(f"  TEST v15: SURVIVORSHIP-FREE con Universo Rotativo")
    print(f"  Periodo: {months} meses | Fecha: {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'#'*70}")

    # Cargar cache v14
    cache_dir = os.path.join(PROJECT_DIR, 'data_cache', f'v15_{months}m')
    all_data = {}

    if os.path.exists(cache_dir):
        print(f"  Cargando cache: {cache_dir}")
        for f in os.listdir(cache_dir):
            if not f.endswith('.csv.gz'):
                continue
            ticker = f.replace('.csv.gz', '').replace('_', '.')
            df = pd.read_csv(os.path.join(cache_dir, f), compression='gzip')
            date_col = None
            for col in ['Date', 'date', 'Datetime']:
                if col in df.columns:
                    date_col = col
                    break
            if date_col:
                df[date_col] = pd.to_datetime(df[date_col])
                df = df.set_index(date_col)
            df.index.name = None
            if len(df) >= 50:
                df['ATR'] = calculate_atr(df['High'], df['Low'], df['Close'], 14)
                df['HVOL'] = historical_volatility(df['Close'], CONFIG['hvol_window'])
                all_data[ticker] = df
        print(f"  Cache: {len(all_data)} tickers")

    # Descargar tickers faltantes: v15 completo (US+EU+Asia+ETF) + v12 (para referencia justa)
    all_needed = set()
    # v15 rotativo US
    for year_data in SP500_HISTORICAL.values():
        for tickers in year_data.values():
            for t in tickers:
                resolved = resolve_ticker(t)
                if resolved:
                    all_needed.add(resolved)
    # ETFs + EU + Asia
    for universe in [ETF_UNIVERSE, EU_UNIVERSE, ASIA_UNIVERSE]:
        for t in universe:
            all_needed.add(t)
    # v12 completo (225 tickers) para referencia justa
    v12_tickers = list(ASSETS.keys())
    for t in v12_tickers:
        all_needed.add(t)

    missing = [t for t in all_needed if t not in all_data]
    if missing:
        os.makedirs(cache_dir, exist_ok=True)
        print(f"  Descargando {len(missing)} tickers faltantes...")
        for i, ticker in enumerate(missing):
            df = download_data_eodhd(ticker, months)
            if df is None:
                df = download_data(ticker, months)
            if df is not None and len(df) >= 50:
                df['ATR'] = calculate_atr(df['High'], df['Low'], df['Close'], 14)
                df['HVOL'] = historical_volatility(df['Close'], CONFIG['hvol_window'])
                all_data[ticker] = df
                # Save to cache
                safe = ticker.replace('.', '_')
                df[['Open', 'High', 'Low', 'Close', 'Volume']].to_csv(
                    os.path.join(cache_dir, f'{safe}.csv.gz'), compression='gzip')
            else:
                print(f"    FAILED: {ticker}")
            if (i + 1) % 20 == 0 or i == len(missing) - 1:
                print(f"\r  Descargados: {len([t for t in missing[:i+1] if t in all_data])}/{len(missing)}", end='')
        print()

    # v12 tickers para referencia
    v12_tickers = list(ASSETS.keys())

    # =================================================================
    # TESTS
    # =================================================================
    results = []

    tests = [
        # Stock-only
        ("v12 stock-only", False, 'v12', 0, 0),
        ("v15 stock-only", False, 'v15', 0, 0),

        # v12 COMPLETO: US + EU (2+2 slots)
        ("v12 US+EU (2+2)", True, 'v12', 2, 2),

        # v15 COMPLETO: US + EU (2+2 slots)
        ("v15 US+EU (2+2)", True, 'v15', 2, 2),
    ]

    for label, use_opts, mode, us_slots, eu_slots in tests:
        t0 = time.time()

        if mode == 'v12':
            if eu_slots > 0:
                opt_set = set(OPTIONS_ELIGIBLE) | set(OPTIONS_ELIGIBLE_EU)
            elif use_opts:
                opt_set = set(OPTIONS_ELIGIBLE)
            else:
                opt_set = None

            r = run_backtest_eu(
                months=months,
                tickers=v12_tickers,
                label=label,
                use_options=use_opts,
                options_eligible_set=opt_set,
                max_us_options=us_slots,
                max_eu_options=eu_slots,
                preloaded_data=all_data,
            )
            if isinstance(r, dict) and 'error' not in r:
                r['signals_filtered'] = 0
                results.append(r)
        else:
            r = run_backtest_rotating(
                months=months,
                label=label,
                use_options=use_opts,
                preloaded_data=all_data,
                max_us_options=us_slots,
                max_eu_options=eu_slots,
            )
            if isinstance(r, dict) and 'error' not in r:
                results.append(r)

        elapsed = time.time() - t0
        print(f"  [{elapsed:.1f}s]")

    # =================================================================
    # TABLA COMPARATIVA
    # =================================================================
    print(f"\n\n{'='*120}")
    print(f"  COMPARATIVA v15 SURVIVORSHIP-FREE vs v12 — {months} MESES")
    print(f"{'='*120}")
    print(f"{'Universo':<30s} {'Stock':>6s} {'OpUS':>5s} {'OpEU':>5s} {'Total':>6s} {'WR':>6s} {'PF':>6s} {'CAGR':>8s} {'MaxDD':>8s} {'PnL EUR':>10s} {'OptUS':>10s} {'OptEU':>10s}")
    print('-' * 130)

    for r in results:
        cagr = r.get('annualized_return_pct', 0) / 100
        dd = r.get('max_drawdown', 0) / 100
        opt_us_n = r.get('option_trades_us', r.get('option_trades', 0))
        opt_eu_n = r.get('option_trades_eu', 0)
        opt_eu_pnl = r.get('option_pnl_eu', 0)
        print(f"{r['label']:<30s} {r.get('stock_trades', 0):>6d} {opt_us_n:>5d} {opt_eu_n:>5d} "
              f"{r.get('total_trades', 0):>6d} {r.get('win_rate', 0):>5.1f}% {r.get('profit_factor', 0):>6.2f} "
              f"{cagr:>7.1%} {dd:>7.1%} "
              f"{r.get('total_pnl_euros', 0):>+10,.0f} {r.get('option_pnl_us', 0):>+10,.0f} "
              f"{opt_eu_pnl:>+10,.0f}")

    # =================================================================
    # GOLD OVERLAY 30%
    # =================================================================
    gld_data = all_data.get('GLD')
    if gld_data is not None:
        print(f"\n\n{'='*120}")
        print(f"  GOLD OVERLAY 30% — {months} MESES")
        print(f"{'='*120}")
        print(f"{'Universo':<30s} {'CAGR sin Gold':>14s} {'CAGR con Gold':>14s} {'DD sin Gold':>12s} {'DD con Gold':>12s}")
        print('-' * 90)

        for r in results:
            if r.get('equity_curve') and use_opts_label_check(r['label']):
                gold_r = simulate_gold_overlay(r, gld_data, gold_reserve_pct=0.30)
                if gold_r:
                    cagr_no = r.get('annualized_return_pct', 0)
                    cagr_g = gold_r.get('ann_gold', 0)
                    dd_no = r.get('max_drawdown', 0)
                    dd_g = gold_r.get('maxdd_gold', 0)
                    print(f"{r['label']:<30s} {cagr_no:>+13.1f}% {cagr_g:>+13.1f}% {dd_no:>11.1f}% {dd_g:>11.1f}%")


def use_opts_label_check(label):
    """Solo aplicar gold a variantes con opciones."""
    return 'US+EU' in label or 'COMPLETO' in label


if __name__ == '__main__':
    main()

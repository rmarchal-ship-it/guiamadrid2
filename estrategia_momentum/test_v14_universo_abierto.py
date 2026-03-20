#!/usr/bin/env python3
"""
Test v14: Universo Abierto con Filtro de Volatilidad
=====================================================
Fecha: 17 Mar 2026
Objetivo: Probar si el motor momentum v8 funciona en universos "sin sesgo"
          (S&P 500, Nasdaq 100, ETFs) usando un filtro de volatilidad ex-ante
          para seleccionar señales de calidad.

Hipótesis: El motor momentum breakout funciona en cualquier universo líquido,
           siempre que se filtre por volatilidad anualizada > 25% (60d pre-señal).

Universos:
  A) S&P 500 (503 tickers) — amplio, sin cherry-picking
  B) Nasdaq 100 (101 tickers) — growth/tech puro
  C) ETFs del universo actual (41 tickers) — diversificación geográfica/sectorial
  D) v12 original (225 tickers) — referencia para comparación
  E) Combinado S&P500+NDX100+ETFs deduplicado

Cada universo se prueba:
  1. SIN filtro de volatilidad (baseline)
  2. CON filtro vol > 25% (solo se toman señales con vol anualizada 60d > 25%)
"""

import sys
import os
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

warnings.filterwarnings('ignore')

# Add project to path
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

from momentum_breakout import MomentumEngine, ASSETS
from backtest_experimental import (
    download_data, calculate_atr, historical_volatility,
    generate_all_signals, build_macro_filter,
    find_candidates, rank_candidates,
    Trade, OptionTradeV2, EquityTracker,
    CONFIG
)
from data_eodhd import download_data_eodhd

# =============================================================================
# UNIVERSOS
# =============================================================================

# S&P 500 (actual a Mar 2026, de Wikipedia)
SP500_TICKERS = [
    'MMM','AOS','ABT','ABBV','ACN','ADBE','AMD','AES','AFL','A','APD','ABNB','AKAM','ALB','ARE',
    'ALGN','ALLE','LNT','ALL','GOOGL','GOOG','MO','AMZN','AMCR','AEE','AAL','AEP','AXP','AIG',
    'AMT','AWK','AMP','AME','AMGN','APH','ADI','ANSS','AON','APA','AAPL','AMAT','APTV','ACGL',
    'ADM','ANET','AJG','AIZ','T','ATO','ADSK','ADP','AZO','AVB','AVY','AXON','BKR','BALL','BAC',
    'BK','BBWI','BAX','BDX','BRK-B','BBY','BIO','TECH','BIIB','BLK','BX','BA','BKNG','BWA',
    'BSX','BMY','AVGO','BR','BRO','BF-B','BLDR','BG','CDNS','CZR','CPT','CPB','COF','CAH','KMX',
    'CCL','CARR','CTLT','CAT','CBOE','CBRE','CDW','CE','COR','CNC','CNP','CF','CHRW','CRL',
    'SCHW','CHTR','CVX','CMG','CB','CHD','CI','CINF','CTAS','CSCO','C','CFG','CLX','CME','CMS',
    'KO','CTSH','CL','CMCSA','CAG','COP','ED','STZ','CEG','COO','CPRT','GLW','CPAY','CTVA',
    'CSGP','COST','CTRA','CRWD','CCI','CSX','CMI','CVS','DHR','DRI','DVA','DAY','DECK','DE',
    'DAL','DVN','DXCM','FANG','DLR','DFS','DG','DLTR','D','DPZ','DOV','DOW','DHI','DTE','DUK',
    'DD','EMN','ETN','EBAY','ECL','EIX','EW','EA','ELV','LLY','EMR','ENPH','ETR','EOG','EPAM',
    'EQT','EFX','EQIX','EQR','ERIE','ESS','EL','ETSY','EG','EVRG','ES','EXC','EXPE','EXPD',
    'EXR','XOM','FFIV','FDS','FICO','FAST','FRT','FDX','FIS','FITB','FSLR','FE','FI','FMC',
    'F','FTNT','FTV','FOXA','FOX','BEN','FCX','GRMN','IT','GE','GEHC','GEV','GEN','GNRC','GD',
    'GIS','GM','GPC','GILD','GPN','GL','GDDY','GS','HAL','HIG','HAS','HCA','DOC','HSIC','HSY',
    'HES','HPE','HLT','HOLX','HD','HON','HRL','HST','HWM','HPQ','HUBB','HUM','HBAN','HII',
    'IBM','IEX','IDXX','ITW','INCY','IR','PODD','INTC','ICE','IFF','IP','IPG','INTU','ISRG',
    'IVZ','INVH','IQV','IRM','JBHT','JBL','JKHY','J','JNJ','JCI','JPM','JNPR','K','KVUE',
    'KDP','KEY','KEYS','KMB','KIM','KMI','KKR','KLAC','KHC','KR','LHX','LH','LRCX','LW',
    'LVS','LDOS','LEN','LIN','LYV','LKQ','LMT','L','LOW','LULU','LYB','MTB','MRO','MPC',
    'MKTX','MAR','MMC','MLM','MAS','MA','MTCH','MKC','MCD','MCK','MDT','MRK','META','MCHP',
    'MU','MSFT','MAA','MRNA','MHK','MOH','TAP','MDLZ','MPWR','MNST','MCO','MS','MOS','MSI',
    'MSCI','NDAQ','NTAP','NFLX','NEM','NWSA','NWS','NEE','NKE','NI','NDSN','NSC','NTRS','NOC',
    'NCLH','NRG','NUE','NVDA','NVR','NXPI','ORLY','OXY','ODFL','OMC','ON','OKE','ORCL','OTIS',
    'PCAR','PKG','PANW','PARA','PH','PAYX','PAYC','PYPL','PNR','PEP','PFE','PCG','PM','PSX',
    'PNW','PXD','PNC','POOL','PPG','PPL','PFG','PG','PGR','PLD','PRU','PEG','PTC','PSA',
    'PHM','QRVO','PWR','QCOM','DGX','RL','RJF','RTX','O','REG','REGN','RF','RSG','RMD',
    'RVTY','RHI','ROK','ROL','ROP','ROST','RCL','SPGI','CRM','SBAC','SLB','STX','SRE','NOW',
    'SHW','SPG','SWKS','SJM','SW','SNA','SOLV','SO','LUV','SWK','SBUX','STT','STLD','STE',
    'SYK','SMCI','SYF','SNPS','SYY','TMUS','TROW','TTWO','TPR','TRGP','TGT','TEL','TDY',
    'TFX','TER','TSLA','TXN','TXT','TMO','TJX','TSCO','TT','TDG','TRV','TRMB','TFC','TYL',
    'TSN','USB','UBER','UDR','ULTA','UNP','UAL','UPS','URI','UNH','UHS','VLO','VTR','VLTO',
    'VRSN','VRSK','VZ','VRTX','VTRS','VICI','V','VMC','WRB','GWW','WAB','WBA','WMT','DIS',
    'WBD','WM','WAT','WEC','WFC','WELL','WST','WDC','WY','WMB','WTW','WYNN','XEL','XYL',
    'YUM','ZBRA','ZBH','ZTS',
]

# Nasdaq 100 (actual a Mar 2026)
NDX100_TICKERS = [
    'AAPL','ABNB','ADBE','ADI','ADP','ADSK','AEP','AMAT','AMGN','AMZN',
    'ANSS','ARM','ASML','AVGO','AZN','BIIB','BKNG','BKR','CDNS','CDW',
    'CEG','CHTR','CMCSA','COST','CPRT','CRWD','CSCO','CSGP','CTAS','CTSH',
    'DASH','DDOG','DLTR','DXCM','EA','EXC','FANG','FAST','FTNT','GEHC',
    'GFS','GILD','GOOG','GOOGL','HON','IDXX','ILMN','INTC','INTU','ISRG',
    'KDP','KHC','KLAC','LIN','LRCX','LULU','MAR','MCHP','MDB','MDLZ',
    'MELI','META','MNST','MRNA','MRVL','MSFT','MU','NFLX','NVDA','NXPI',
    'ODFL','ON','ORLY','PANW','PAYX','PCAR','PDD','PEP','PYPL','QCOM',
    'REGN','ROP','ROST','SBUX','SMCI','SNPS','TEAM','TMUS','TSLA','TTD',
    'TTWO','TXN','VRSK','VRTX','WBD','WDAY','XEL','ZS',
]

# ETFs del universo actual (commodities + ETFs sectoriales/intl + fixed income)
ETF_TICKERS = [
    'DBA','WEAT','CORN','SOYB','USO','BNO','UNG','XLE','XOP',
    'CPER','DBB','PICK','GLD','SLV','PPLT','GDX','GDXJ',
    'EEM','VWO','EFA','FXI','EWJ','EWG','EWU','INDA','EWZ','EWT',
    'SMH','XBI','XLU','XLI','XLF','XLV',
    'TLT','IEF','SHY','TIP','AGG','LQD','HYG','EMB',
]

# v12 original (referencia)
V12_TICKERS = [t for t in ASSETS.keys()]

# =============================================================================
# VOLATILITY FILTER
# =============================================================================

def compute_pre_signal_volatility(all_data, lookback=60):
    """Pre-computa volatilidad anualizada a 60d para cada ticker en cada fecha.

    Returns dict: ticker -> Series(date -> vol_ann)
    """
    vol_data = {}
    for ticker, df in all_data.items():
        returns = df['Close'].pct_change()
        # Rolling vol anualizada
        vol = returns.rolling(lookback).std() * np.sqrt(252)
        vol_data[ticker] = vol
    return vol_data


# =============================================================================
# BACKTEST CON FILTRO DE VOLATILIDAD (modificado de run_backtest)
# =============================================================================

def run_backtest_vol(months, tickers, label, vol_filter=None, preloaded_data=None, verbose=False):
    """Motor de backtest stock-only con filtro de volatilidad opcional.

    Args:
        vol_filter: float or None. Si no None, solo tomar señales donde
                    la volatilidad anualizada 60d pre-señal > vol_filter.
    """
    n_tickers = len(tickers)
    vol_label = f" [vol>{vol_filter:.0%}]" if vol_filter else " [sin filtro vol]"
    print(f"\n{'='*70}")
    print(f"  {label}{vol_label} -- {months}m -- {n_tickers} tickers")
    print(f"{'='*70}")

    # Descargar datos
    if preloaded_data:
        all_data = {t: preloaded_data[t] for t in tickers if t in preloaded_data}
        failed = [t for t in tickers if t not in preloaded_data]
    else:
        print("  Descargando datos...")
        all_data = {}
        failed = []
        for i, ticker in enumerate(tickers):
            df = download_data(ticker, months)
            if df is not None:
                df['ATR'] = calculate_atr(df['High'], df['Low'], df['Close'], 14)
                df['HVOL'] = historical_volatility(df['Close'], CONFIG['hvol_window'])
                all_data[ticker] = df
            else:
                failed.append(ticker)
            if (i + 1) % 50 == 0 or i == n_tickers - 1:
                print(f"\r  Descargados: {len(all_data)}/{n_tickers} OK, {len(failed)} fallidos", end='')
        print()

    print(f"  Tickers con datos: {len(all_data)}")
    if failed and len(failed) <= 20:
        print(f"  Fallidos: {', '.join(failed)}")
    elif failed:
        print(f"  Fallidos: {len(failed)} tickers")

    if not all_data:
        return {'error': 'No data'}

    # Pre-computar volatilidad si hay filtro
    vol_data = None
    if vol_filter:
        vol_data = compute_pre_signal_volatility(all_data)

    # Engine + señales
    engine = MomentumEngine(
        ker_threshold=CONFIG['ker_threshold'],
        volume_threshold=CONFIG['volume_threshold'],
        rsi_threshold=CONFIG['rsi_threshold'],
        rsi_max=CONFIG['rsi_max'],
        breakout_period=CONFIG['breakout_period'],
        longs_only=CONFIG['longs_only']
    )
    signals_data, total_signals = generate_all_signals(all_data, engine)
    print(f"  Señales LONG totales: {total_signals}")

    # Filtro macro
    macro_bullish = build_macro_filter(all_data)

    # Timeline
    all_dates = sorted(set(d for sd in signals_data.values() for d in sd['df'].index.tolist()))

    tracker = EquityTracker(CONFIG['initial_capital'])
    active_trades = {}
    all_trades = []
    signals_taken = 0
    signals_filtered = 0

    # LOOP PRINCIPAL
    for current_date in all_dates:
        # 1. Gestionar trades activos
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

        # 2. Nuevas entradas (stock only, sin opciones)
        if tracker.open_positions >= CONFIG['max_positions']:
            continue

        is_macro_ok = macro_bullish.get(current_date, None)
        if is_macro_ok is None:
            # Buscar último valor conocido
            for d in sorted(macro_bullish.keys(), reverse=True):
                if d <= current_date:
                    is_macro_ok = macro_bullish[d]
                    break
            if is_macro_ok is None:
                is_macro_ok = True

        if not is_macro_ok:
            continue

        candidates = find_candidates(signals_data, active_trades, current_date, is_macro_ok)
        if not candidates:
            continue

        # Aplicar filtro de volatilidad
        if vol_filter and vol_data:
            filtered_candidates = []
            for ticker, idx, prev_atr in candidates:
                vol_series = vol_data.get(ticker)
                if vol_series is not None:
                    df = signals_data[ticker]['df']
                    if current_date in df.index:
                        loc = df.index.get_loc(current_date)
                        if loc > 0:
                            vol_val = vol_series.iloc[loc - 1]  # día anterior
                            if not pd.isna(vol_val) and vol_val > vol_filter:
                                filtered_candidates.append((ticker, idx, prev_atr))
                            else:
                                signals_filtered += 1
                                continue
                filtered_candidates.append((ticker, idx, prev_atr))
            candidates = filtered_candidates

        if not candidates:
            continue

        ranked = rank_candidates(candidates, signals_data)
        slots = CONFIG['max_positions'] - tracker.open_positions

        for ticker, idx, prev_atr, _score in ranked[:slots]:
            df = signals_data[ticker]['df']
            bar = df.iloc[idx]
            entry_price = bar['Open'] * (1 + CONFIG['slippage_pct'] / 100)

            # Position sizing: inverse volatility
            r_per_share = 2 * prev_atr
            if r_per_share <= 0:
                continue
            risk_budget = tracker.equity * (CONFIG['target_risk_per_trade_pct'] / 100)
            units = max(1, int(risk_budget / r_per_share))
            position_eur = units * entry_price
            max_pos = tracker.equity / CONFIG['max_positions']
            if position_eur > max_pos * 2:
                units = max(1, int(max_pos * 2 / entry_price))
                position_eur = units * entry_price

            trade = Trade(
                ticker=ticker,
                entry_price=entry_price,
                position_units=units,
                entry_atr=prev_atr,
                position_euros=position_eur,
                entry_date=current_date
            )
            active_trades[ticker] = trade
            tracker.open_positions += 1
            signals_taken += 1

            if tracker.open_positions >= CONFIG['max_positions']:
                break

    # Cerrar trades abiertos al final
    last_date = all_dates[-1] if all_dates else None
    for ticker, trade in active_trades.items():
        if ticker in signals_data:
            df = signals_data[ticker]['df']
            if last_date and last_date in df.index:
                bar = df.loc[last_date]
                trade.exit_date = last_date
                trade.exit_reason = 'end_of_data'
                pnl = (bar['Close'] - trade.entry_price) * trade.position_units
                trade.pnl_euros = pnl
                tracker.update_equity(pnl, last_date)
                all_trades.append(trade)

    # Estadísticas
    if not all_trades:
        print("  SIN TRADES")
        return {'label': label, 'error': 'No trades'}

    winners = [t for t in all_trades if t.pnl_euros > 0]
    losers = [t for t in all_trades if t.pnl_euros <= 0]
    total_pnl = sum(t.pnl_euros for t in all_trades)
    gross_wins = sum(t.pnl_euros for t in winners)
    gross_loss = abs(sum(t.pnl_euros for t in losers))
    pf = gross_wins / gross_loss if gross_loss > 0 else 999
    wr = len(winners) / len(all_trades) * 100

    # CAGR
    years = months / 12
    final_equity = CONFIG['initial_capital'] + total_pnl
    if final_equity > 0:
        cagr = (final_equity / CONFIG['initial_capital']) ** (1 / years) - 1
    else:
        cagr = -1.0

    # MaxDD
    equity_curve = [CONFIG['initial_capital']]
    for t in sorted(all_trades, key=lambda x: x.exit_date if x.exit_date else datetime.now()):
        equity_curve.append(equity_curve[-1] + t.pnl_euros)
    peak = equity_curve[0]
    max_dd = 0
    for e in equity_curve:
        if e > peak:
            peak = e
        dd = (e - peak) / peak
        if dd < max_dd:
            max_dd = dd

    # Avg win/loss
    avg_win = np.mean([t.pnl_euros for t in winners]) if winners else 0
    avg_loss = np.mean([t.pnl_euros for t in losers]) if losers else 0

    result = {
        'label': label,
        'vol_filter': vol_filter,
        'n_tickers': len(all_data),
        'n_trades': len(all_trades),
        'n_winners': len(winners),
        'n_losers': len(losers),
        'wr': wr,
        'pf': pf,
        'total_pnl': total_pnl,
        'final_equity': final_equity,
        'cagr': cagr,
        'max_dd': max_dd,
        'signals_filtered': signals_filtered,
        'avg_win_eur': avg_win,
        'avg_loss_eur': avg_loss,
    }

    print(f"\n  Trades: {len(all_trades)} ({len(winners)}W / {len(losers)}L)")
    print(f"  Win Rate: {wr:.1f}%")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  CAGR: {cagr:.1%}")
    print(f"  MaxDD: {max_dd:.1%}")
    print(f"  Final equity: EUR {final_equity:,.0f}")
    if vol_filter:
        print(f"  Señales filtradas por vol: {signals_filtered}")

    return result


# =============================================================================
# MAIN
# =============================================================================

def main():
    months = 24
    print(f"\n{'#'*70}")
    print(f"  TEST v14: UNIVERSO ABIERTO CON FILTRO DE VOLATILIDAD")
    print(f"  Periodo: {months} meses | Fecha: {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'#'*70}")

    # Definir universos
    universes = {
        'S&P 500': SP500_TICKERS,
        'Nasdaq 100': NDX100_TICKERS,
        'ETFs': ETF_TICKERS,
        'v12 original': V12_TICKERS,
    }

    # Combinado deduplicado: SP500 + NDX100 + ETFs
    combined = list(dict.fromkeys(SP500_TICKERS + NDX100_TICKERS + ETF_TICKERS))
    universes['SP500+NDX+ETFs'] = combined

    # Descargar TODOS los datos una sola vez (superset)
    all_tickers = list(dict.fromkeys(
        SP500_TICKERS + NDX100_TICKERS + ETF_TICKERS + V12_TICKERS
    ))
    print(f"\n  Descargando superset: {len(all_tickers)} tickers únicos...")

    # Intentar cargar cache v14 primero
    cache_dir = os.path.join(PROJECT_DIR, 'data_cache', f'v14_{months}m')
    all_data = {}
    failed = []
    fallback_yahoo = []

    if os.path.exists(cache_dir) and len(os.listdir(cache_dir)) > 100:
        print(f"  Cargando desde cache: {cache_dir}")
        for f in os.listdir(cache_dir):
            if not f.endswith('.csv.gz'):
                continue
            ticker = f.replace('.csv.gz', '').replace('_', '.')
            df = pd.read_csv(os.path.join(cache_dir, f), parse_dates=['Date'], index_col='Date')
            if len(df) >= 50:
                df['ATR'] = calculate_atr(df['High'], df['Low'], df['Close'], 14)
                df['HVOL'] = historical_volatility(df['Close'], CONFIG['hvol_window'])
                all_data[ticker] = df
        failed = [t for t in all_tickers if t not in all_data]
        print(f"  Cache: {len(all_data)} tickers cargados, {len(failed)} no encontrados")
    else:
        t0 = time.time()
        for i, ticker in enumerate(all_tickers):
            # EODHD primero, fallback a Yahoo si falla
            df = download_data_eodhd(ticker, months)
            if df is None:
                df = download_data(ticker, months)
                if df is not None:
                    fallback_yahoo.append(ticker)
            if df is not None:
                df['ATR'] = calculate_atr(df['High'], df['Low'], df['Close'], 14)
                df['HVOL'] = historical_volatility(df['Close'], CONFIG['hvol_window'])
                all_data[ticker] = df
            else:
                failed.append(ticker)
            if (i + 1) % 50 == 0 or i == len(all_tickers) - 1:
                elapsed = time.time() - t0
                print(f"\r  {len(all_data)}/{len(all_tickers)} OK, {len(failed)} fallidos [{elapsed:.0f}s]", end='')
        print(f"\n  Total con datos: {len(all_data)} | Fallidos: {len(failed)} | Fallback Yahoo: {len(fallback_yahoo)}")

        # Guardar cache
        try:
            os.makedirs(cache_dir, exist_ok=True)
            for ticker, df in all_data.items():
                safe = ticker.replace('.', '_')
                df[['Open','High','Low','Close','Volume']].to_csv(os.path.join(cache_dir, f'{safe}.csv.gz'), compression='gzip')
            print(f"  Cache guardado en {cache_dir}")
        except Exception as e:
            print(f"  Warning: no se pudo guardar cache: {e}")

    if failed and len(failed) <= 30:
        print(f"  Fallidos: {', '.join(failed)}")
    if fallback_yahoo and len(fallback_yahoo) <= 30:
        print(f"  Yahoo fallback: {', '.join(fallback_yahoo)}")

    # Correr cada universo con y sin filtro de volatilidad
    vol_thresholds = [None, 0.25]  # sin filtro, >25%
    results = []

    for univ_name, tickers in universes.items():
        for vf in vol_thresholds:
            r = run_backtest_vol(
                months=months,
                tickers=tickers,
                label=univ_name,
                vol_filter=vf,
                preloaded_data=all_data,
                verbose=False
            )
            if 'error' not in r:
                results.append(r)

    # Tabla comparativa
    print(f"\n\n{'='*90}")
    print(f"  COMPARATIVA FINAL — {months} MESES")
    print(f"{'='*90}")
    print(f"{'Universo':<20s} {'Filtro':<12s} {'Tickers':>7s} {'Trades':>7s} {'WR':>6s} {'PF':>6s} {'CAGR':>8s} {'MaxDD':>8s} {'Final EUR':>10s}")
    print('-' * 90)

    for r in results:
        vf_str = f">25%" if r['vol_filter'] else "Ninguno"
        print(f"{r['label']:<20s} {vf_str:<12s} {r['n_tickers']:>7d} {r['n_trades']:>7d} "
              f"{r['wr']:>5.1f}% {r['pf']:>6.2f} {r['cagr']:>7.1%} {r['max_dd']:>7.1%} {r['final_equity']:>10,.0f}")

    # Resumen del impacto del filtro
    print(f"\n\n{'='*70}")
    print(f"  IMPACTO DEL FILTRO DE VOLATILIDAD (>25%)")
    print(f"{'='*70}")

    for univ_name in universes.keys():
        base = [r for r in results if r['label'] == univ_name and r['vol_filter'] is None]
        filt = [r for r in results if r['label'] == univ_name and r['vol_filter'] == 0.25]
        if base and filt:
            b, f = base[0], filt[0]
            dpf = f['pf'] - b['pf']
            dcagr = f['cagr'] - b['cagr']
            ddd = f['max_dd'] - b['max_dd']
            print(f"\n  {univ_name}:")
            print(f"    PF:   {b['pf']:.2f} → {f['pf']:.2f} ({dpf:+.2f})")
            print(f"    CAGR: {b['cagr']:.1%} → {f['cagr']:.1%} ({dcagr:+.1%})")
            print(f"    DD:   {b['max_dd']:.1%} → {f['max_dd']:.1%} ({ddd:+.1%})")
            print(f"    Trades: {b['n_trades']} → {f['n_trades']} (filtradas: {f['signals_filtered']})")


if __name__ == '__main__':
    main()

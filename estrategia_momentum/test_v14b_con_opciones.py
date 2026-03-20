#!/usr/bin/env python3
"""
Test v14b: Universo Abierto CON OPCIONES US (2 slots)
=====================================================
Fecha: 17 Mar 2026
Objetivo: Verificar si el edge de opciones se mantiene en universos sin sesgo.

Usa el motor v12 (run_backtest_eu) con opciones US, datos cacheados de v14_24m.

Universos:
  A) S&P 500 — options eligible: TODOS (500 tickers, all US = spread 3%)
  B) Nasdaq 100 — options eligible: TODOS (100 tickers)
  C) ETFs — options eligible: los que ya están en OPTIONS_ELIGIBLE del v12
  D) v12 original — referencia con sus 104 tickers options-eligible US
  E) SP500+NDX+ETFs combinado

IMPORTANTE: Solo opciones US (2 slots). Sin EU. Sin gold overlay.
Esto es un test de sesgo, no de rentabilidad máxima.
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
    CONFIG, OPTIONS_ELIGIBLE,
)
from backtest_v12_eu_options import (
    run_backtest_eu, OPTIONS_ELIGIBLE_EU, simulate_gold_overlay,
)

# =============================================================================
# UNIVERSOS (mismos que v14)
# =============================================================================

SP500_TICKERS = [
    'MMM','AOS','ABT','ABBV','ACN','ADBE','AMD','AES','AFL','A','APD','ABNB','AKAM','ALB','ARE',
    'ALGN','ALLE','LNT','ALL','GOOGL','GOOG','MO','AMZN','AMCR','AEE','AAL','AEP','AXP','AIG',
    'AMT','AWK','AMP','AME','AMGN','APH','ADI','ANSS','AON','APA','AAPL','AMAT','APTV','ACGL',
    'ADM','ANET','AJG','AIZ','T','ATO','ADSK','ADP','AZO','AVB','AVY','AXON','BKR','BALL','BAC',
    'BK','BBWI','BAX','BDX','BRK-B','BBY','BIO','TECH','BIIB','BLK','BX','BA','BKNG','BWA',
    'BSX','BMY','AVGO','BR','BRO','BF-B','BLDR','BG','CDNS','CZR','CPT','CPB','COF','CAH','KMX',
    'CCL','CARR','CTLT','CAT','CBOE','CBRE','CDW','CE','COR','CNC','CNP','CF','CHRW','CRL',
    'SCHW','CHTR','CVX','CMG','CB','CHD','CI','CINF','CTAS','CSCO','C','CFG','CLX','CME',
    'CMS','KO','CTSH','CL','CMCSA','CMA','CAG','COP','ED','STZ','CEG','COO','CPRT','GLW',
    'CTVA','CSGP','COST','CTRA','CCI','CSX','CMI','CVS','DHI','DHR','DRI','DVA','DAY','DECK',
    'DE','DAL','XRAY','DVN','DXCM','FANG','DLR','DFS','DG','DLTR','D','DPZ','DOV','DOW','DHI',
    'DTE','DUK','DD','EMN','ETN','EBAY','ECL','EIX','EW','EA','ELV','LLY','EMR','ENPH','ETR',
    'EOG','EPAM','EQT','EFX','EQIX','EQR','ESS','EL','ETSY','EG','EVRG','ES','EXC','EXPE',
    'EXPD','EXR','XOM','FFIV','FDS','FICO','FAST','FRT','FDX','FIS','FITB','FSLR','FE','FI',
    'FMC','F','FTNT','FTV','FOXA','FOX','BEN','FCX','GENZ','GRMN','IT','GEHC','GEN','GNRC',
    'GD','GE','GIS','GM','GPC','GILD','GPN','GL','GDDY','GS','HAL','HIG','HAS','HCA','PEAK',
    'HSIC','HSY','HES','HPE','HLT','HOLX','HD','HON','HRL','HST','HWM','HPQ','HUBB','HUM',
    'HBAN','HII','IBM','IEX','IDXX','ITW','ILMN','INCY','IR','PODD','INTC','ICE','IFF','IP',
    'IPG','INTU','ISRG','IVZ','INVH','IQV','IRM','JBHT','JBL','JKHY','J','JNJ','JCI','JPM',
    'JNPR','K','KVUE','KDP','KEY','KEYS','KMB','KIM','KMI','KLAC','KHC','KR','LHX','LH',
    'LRCX','LW','LVS','LDOS','LEN','LIN','LYV','LKQ','LMT','L','LOW','LULU','LYB','MTB',
    'MRO','MPC','MKTX','MAR','MMC','MLM','MAS','MA','MTCH','MKC','MCD','MCK','MDT','MRK',
    'META','MCHP','MU','MSFT','MAA','MRNA','MHK','MOH','TAP','MDLZ','MPWR','MNST','MCO','MS',
    'MOS','MSI','MSCI','NDAQ','NTAP','NFLX','NEM','NWSA','NWS','NEE','NKE','NI','NDSN','NSC',
    'NTRS','NOC','NCLH','NRG','NUE','NVDA','NVR','NXPI','ORLY','OXY','ODFL','OMC','ON','OKE',
    'ORCL','OGN','OTIS','PCAR','PKG','PANW','PARA','PH','PAYX','PAYC','PYPL','PNR','PEP',
    'PFE','PCG','PM','PSX','PNW','PXD','PTC','PVH','QRVO','QCOM','PWR','DGX','RL','RJF',
    'RTX','O','REG','REGN','RF','RSG','RMD','RVTY','RHI','ROK','ROL','ROP','ROST','RCL',
    'SPGI','CRM','SBAC','SLB','STX','SRE','NOW','SHW','SPG','SWKS','SJM','SNA','SOLV','SO',
    'LUV','SWK','SBUX','STT','STLD','STE','SYK','SMCI','SYF','SNPS','SYY','TMUS','TROW',
    'TTWO','TPR','TRGP','TGT','TEL','TDY','TFX','TER','TSLA','TXN','TXT','TMO','TJX','TSCO',
    'TT','TDG','TRV','TRMB','TFC','TYL','TSN','USB','UBER','UDR','ULTA','UNP','UAL','UPS',
    'URI','UNH','UHS','VLO','VTR','VLTO','VRSN','VRSK','VZ','VRTX','VIAV','V','VMC','WRB',
    'GWW','WAB','WBA','WMT','DIS','WBD','WM','WAT','WEC','WFC','WELL','WST','WDC','WRK',
    'WY','WMB','WTW','WYNN','XEL','XYL','YUM','ZBRA','ZBH','ZION','ZTS',
]

NDX100_TICKERS = [
    'AAPL','ABNB','ADBE','ADI','ADP','ADSK','AEP','AMAT','AMGN','AMZN',
    'ANSS','ARM','ASML','AVGO','AZN','BIIB','BKNG','BKR','CCEP','CDNS',
    'CDW','CEG','CHTR','CMCSA','COST','CPRT','CRWD','CSCO','CSGP','CSX',
    'CTAS','CTSH','DASH','DDOG','DLTR','DXCM','EA','EXC','FANG','FAST',
    'FTNT','GEHC','GFS','GILD','GOOG','GOOGL','HON','IDXX','ILMN','INTC',
    'INTU','ISRG','KDP','KHC','KLAC','LIN','LRCX','LULU','MAR','MCHP',
    'MDB','MDLZ','MELI','META','MNST','MRNA','MRVL','MSFT','MU','NFLX',
    'NVDA','NXPI','ODFL','ON','ORLY','PANW','PAYX','PCAR','PDD','PEP',
    'PYPL','QCOM','REGN','ROP','ROST','SBUX','SMCI','SNPS','SPLK','TEAM',
    'TMUS','TSLA','TTD','TTWO','TXN','VRSK','VRTX','WBD','WDAY','XEL','ZS',
]

ETF_TICKERS = [
    # Commodities
    'GLD','SLV','GDX','GDXJ','PPLT','PALL','DBA','USO','UNG','COPX',
    # Sector
    'XLE','XLF','XLK','XLV','XLI','XLU','XLP','XLY','XLB','XLRE',
    'SMH','IBB','ITA','XBI','ARKK','ARKG',
    # International/EM
    'EWJ','EWZ','EWW','EEM','VWO','FXI',
    # Fixed income / Hedge
    'TLT','HYG','LQD',
    # Broad / Size
    'QQQ','IWM',
]

# v12 original
from momentum_breakout import ASSETS
V12_TICKERS = list(ASSETS.keys())

# =============================================================================
# CARGAR CACHE
# =============================================================================

def load_cache(months):
    """Carga datos cacheados de v14."""
    cache_dir = os.path.join(PROJECT_DIR, 'data_cache', f'v14_{months}m')
    if not os.path.exists(cache_dir):
        print(f"  ERROR: Cache no encontrado: {cache_dir}")
        return {}

    all_data = {}
    for f in os.listdir(cache_dir):
        if not f.endswith('.csv.gz'):
            continue
        ticker = f.replace('.csv.gz', '').replace('_', '.')
        fpath = os.path.join(cache_dir, f)
        df = pd.read_csv(fpath, compression='gzip')
        # Detect date column (could be 'Date' or 'date' or first unnamed)
        date_col = None
        for col in ['Date', 'date', 'Datetime']:
            if col in df.columns:
                date_col = col
                break
        if date_col is None and 'Unnamed: 0' in df.columns:
            date_col = 'Unnamed: 0'
        if date_col:
            df[date_col] = pd.to_datetime(df[date_col])
            df = df.set_index(date_col)
        df.index.name = None
        if len(df) >= 50:
            df['ATR'] = calculate_atr(df['High'], df['Low'], df['Close'], 14)
            df['HVOL'] = historical_volatility(df['Close'], CONFIG['hvol_window'])
            all_data[ticker] = df

    print(f"  Cache cargado: {len(all_data)} tickers de {cache_dir}")
    return all_data


# =============================================================================
# MAIN
# =============================================================================

def main():
    months = 24

    print(f"\n{'#'*70}")
    print(f"  TEST v14b: UNIVERSO ABIERTO CON OPCIONES US (2 slots)")
    print(f"  Periodo: {months} meses | Fecha: {datetime.now().strftime('%Y-%m-%d')}")
    print(f"  Solo opciones US @ 3% spread | Sin EU | Sin Gold")
    print(f"{'#'*70}")

    # Cargar cache
    all_data = load_cache(months)
    if not all_data:
        print("ERROR: No hay datos cacheados. Corre primero test_v14_universo_abierto.py")
        sys.exit(1)

    # Definir tests
    # Para cada universo: (nombre, tickers, options_eligible_set)
    #
    # REGLA ANTI-BIAS: Todos los tickers US del S&P 500 / NDX tienen opciones listadas.
    # Usamos spread 3% (US standard). La liquidez se autopenaliza via el modelo BS + spread.

    tests = [
        # 1) v12 REFERENCIA — stock only (sin opciones) para baseline
        ("v12 stock-only", V12_TICKERS, None, False),

        # 2) v12 REFERENCIA — con opciones US (como siempre)
        ("v12 + opts US", V12_TICKERS, set(OPTIONS_ELIGIBLE), True),

        # 3) S&P 500 — stock only
        ("SP500 stock-only", SP500_TICKERS, None, False),

        # 4) S&P 500 — con opciones US (ALL tickers eligible @ 3%)
        ("SP500 + opts US", SP500_TICKERS, set(SP500_TICKERS), True),

        # 5) NDX100 — stock only
        ("NDX100 stock-only", NDX100_TICKERS, None, False),

        # 6) NDX100 — con opciones US (ALL tickers eligible @ 3%)
        ("NDX100 + opts US", NDX100_TICKERS, set(NDX100_TICKERS), True),

        # 7) ETFs — stock only
        ("ETFs stock-only", ETF_TICKERS, None, False),

        # 8) ETFs — con opciones US (solo los que están en OPTIONS_ELIGIBLE original)
        ("ETFs + opts US", ETF_TICKERS, set(OPTIONS_ELIGIBLE) & set(ETF_TICKERS), True),

        # 9) Combinado SP500+NDX+ETFs — stock only
        ("ALL stock-only", list(dict.fromkeys(SP500_TICKERS + NDX100_TICKERS + ETF_TICKERS)), None, False),

        # 10) Combinado — con opciones US (SP500+NDX are all eligible, ETFs only if in OPTIONS_ELIGIBLE)
        ("ALL + opts US",
         list(dict.fromkeys(SP500_TICKERS + NDX100_TICKERS + ETF_TICKERS)),
         set(SP500_TICKERS) | set(NDX100_TICKERS) | (set(OPTIONS_ELIGIBLE) & set(ETF_TICKERS)),
         True),
    ]

    results = []

    for label, tickers, opt_eligible, use_opts in tests:
        t0 = time.time()
        r = run_backtest_eu(
            months=months,
            tickers=tickers,
            label=label,
            use_leverage_scaling=False,
            use_options=use_opts,
            options_eligible_set=opt_eligible,
            max_us_options=2,
            max_eu_options=0,  # solo US
            macro_exempt_set=None,
            verbose=False,
            preloaded_data=all_data,
        )
        elapsed = time.time() - t0

        if isinstance(r, dict) and 'error' not in r:
            r['label'] = label
            r['elapsed'] = elapsed
            results.append(r)
            print(f"  [{elapsed:.1f}s]")

    # =================================================================
    # TABLA COMPARATIVA
    # =================================================================
    print(f"\n\n{'='*120}")
    print(f"  COMPARATIVA v14b — {months} MESES — CON OPCIONES US")
    print(f"{'='*120}")
    print(f"{'Universo':<22s} {'Stock':>6s} {'Opts':>5s} {'Total':>6s} {'WR':>6s} {'PF':>6s} {'CAGR':>8s} {'MaxDD':>8s} {'PnL EUR':>10s} {'OptPnL':>10s} {'Final EUR':>10s}")
    print('-' * 120)

    for r in results:
        cagr = r.get('annualized_return_pct', 0) / 100
        dd = r.get('max_drawdown', 0) / 100
        print(f"{r['label']:<22s} {r.get('stock_trades', 0):>6d} {r.get('option_trades', 0):>5d} "
              f"{r.get('total_trades', 0):>6d} {r.get('win_rate', 0):>5.1f}% {r.get('profit_factor', 0):>6.2f} "
              f"{cagr:>7.1%} {dd:>7.1%} "
              f"{r.get('total_pnl_euros', 0):>+10,.0f} {r.get('option_pnl_us', 0):>+10,.0f} "
              f"{r.get('final_equity', 0):>10,.0f}")

    # =================================================================
    # DELTA: Impacto de opciones por universo
    # =================================================================
    print(f"\n\n{'='*80}")
    print(f"  IMPACTO DE OPCIONES US (stock-only vs con opciones)")
    print(f"{'='*80}")

    pairs = [
        ("v12", "v12 stock-only", "v12 + opts US"),
        ("SP500", "SP500 stock-only", "SP500 + opts US"),
        ("NDX100", "NDX100 stock-only", "NDX100 + opts US"),
        ("ETFs", "ETFs stock-only", "ETFs + opts US"),
        ("ALL", "ALL stock-only", "ALL + opts US"),
    ]

    for name, stock_label, opt_label in pairs:
        stock = [r for r in results if r['label'] == stock_label]
        opts = [r for r in results if r['label'] == opt_label]
        if stock and opts:
            s, o = stock[0], opts[0]
            s_cagr = s.get('annualized_return_pct', 0)
            o_cagr = o.get('annualized_return_pct', 0)
            s_pf = s.get('profit_factor', 0)
            o_pf = o.get('profit_factor', 0)
            s_dd = s.get('max_drawdown', 0)
            o_dd = o.get('max_drawdown', 0)
            print(f"\n  {name}:")
            print(f"    CAGR:   {s_cagr:>+7.1f}% → {o_cagr:>+7.1f}%  ({o_cagr-s_cagr:>+.1f}pp)")
            print(f"    PF:     {s_pf:>7.2f} → {o_pf:>7.2f}  ({o_pf-s_pf:>+.2f})")
            print(f"    MaxDD:  {s_dd:>7.1f}% → {o_dd:>7.1f}%  ({o_dd-s_dd:>+.1f}pp)")
            print(f"    Trades: {s.get('stock_trades',0)} stock → {o.get('stock_trades',0)} stock + {o.get('option_trades',0)} options")
            print(f"    PnL opciones US: EUR {o.get('option_pnl_us', 0):>+,.0f}")


if __name__ == '__main__':
    main()

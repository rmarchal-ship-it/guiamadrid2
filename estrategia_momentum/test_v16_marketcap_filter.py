#!/usr/bin/env python3
"""
Test v16: Filtro Dinámico por Market Cap Proxy (Dollar Volume)
==============================================================
Fecha: 17 Mar 2026
Objetivo: Eliminar survivorship bias usando un filtro 100% sistemático y ex-ante.

Metodología:
  - Universo base: S&P 500 completo (~500 tickers) + EU blue chips + Asia + ETFs
  - Filtro dinámico: en cada barra, solo considerar señales de tickers cuyo
    dollar_volume_20d (precio × volumen medio 20d) esté en el TOP 25% del universo.
  - Esto da ~125 mega-caps DINÁMICAS, recalculadas cada día.
  - 100% ex-ante: solo usa datos disponibles hasta la barra actual.
  - Opciones: US (2 slots @ 3%) + EU (2 slots @ 10%)
  - Gold overlay 30%

Comparación directa con v12 (225 tickers fijos).
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
    simulate_gold_overlay,
)
from momentum_breakout import MomentumEngine, ASSETS
from data_eodhd import download_data_eodhd
import requests
from datetime import timedelta

EODHD_OPTIONS_KEY = os.environ.get('EODHD_OPTIONS_KEY', '69ba6290ce4722.64310546')
EODHD_OPTIONS_URL = 'https://eodhd.com/api/mp/unicornbay/options/contracts'

# Cache local para queries de opciones EODHD (evita descargas repetidas)
import json
import hashlib

OPTIONS_CACHE_DIR = os.path.join(PROJECT_DIR, 'options_cache')


def _options_cache_path(ticker, trade_date, target_strike):
    """Genera path de cache único para cada query de opciones."""
    key = f"{ticker}_{trade_date.strftime('%Y%m%d')}_{target_strike:.2f}"
    h = hashlib.md5(key.encode()).hexdigest()[:12]
    return os.path.join(OPTIONS_CACHE_DIR, f"{ticker}_{trade_date.strftime('%Y%m%d')}_{h}.json")


def _load_options_cache(cache_path):
    """Carga resultado cacheado o None."""
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            data = json.load(f)
        return data  # puede ser None (guardamos "no encontrado" también)
    return '__MISS__'


def _save_options_cache(cache_path, result):
    """Guarda resultado en cache (incluyendo None para 'no encontrado')."""
    os.makedirs(OPTIONS_CACHE_DIR, exist_ok=True)
    with open(cache_path, 'w') as f:
        json.dump(result, f)


# =============================================================================
# VALIDACIÓN CON PRECIOS REALES DE OPCIONES (EODHD)
# =============================================================================

def fetch_real_option(ticker, trade_date, target_strike, target_exp_date, api_key=None):
    """
    Busca en EODHD el contrato de opción CALL más cercano a nuestros parámetros.
    Devuelve dict con bid/ask/last/IV/greeks o None si no encuentra.
    Cachea resultados en options_cache/ para no repetir queries.
    """
    if api_key is None:
        api_key = EODHD_OPTIONS_KEY

    # Los tickers EU/Asia no están en EODHD options (solo US)
    if any(ticker.endswith(s) for s in ['.DE', '.PA', '.SW', '.L', '.AS', '.MC', '.MI',
                                         '.BR', '.ST', '.CO', '.HE', '.T', '.AX', '.HK']):
        return None

    # Comprobar cache
    cache_path = _options_cache_path(ticker, trade_date, target_strike)
    cached = _load_options_cache(cache_path)
    if cached != '__MISS__':
        return cached  # puede ser None (= "no encontrado" cacheado)

    # Rango de búsqueda: strike ±10% (enteros), tradetime ±3 días
    # NO usamos exp_date filters — causan 422 en EODHD para contratos expirados
    strike_lo = int(target_strike * 0.90)
    strike_hi = int(target_strike * 1.10) + 1
    trade_from = (trade_date - timedelta(days=3)).strftime('%Y-%m-%d')
    trade_to = (trade_date + timedelta(days=3)).strftime('%Y-%m-%d')

    params = {
        'filter[underlying_symbol]': ticker,
        'filter[type]': 'call',
        'filter[strike_from]': str(strike_lo),
        'filter[strike_to]': str(strike_hi),
        'filter[tradetime_from]': trade_from,
        'filter[tradetime_to]': trade_to,
        'page[limit]': 50,
        'api_token': api_key,
    }

    try:
        resp = requests.get(EODHD_OPTIONS_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        time.sleep(0.1)  # rate limit

        contracts = data.get('data', [])
        if not contracts:
            _save_options_cache(cache_path, None)
            return None

        # Post-filtrar por exp_date ±15 días (no lo hacemos en la API porque da 422)
        filtered = []
        for c in contracts:
            a = c['attributes']
            try:
                exp = datetime.strptime(a['exp_date'], '%Y-%m-%d')
                if abs((exp - target_exp_date).days) <= 15:
                    filtered.append(a)
            except (ValueError, KeyError):
                continue

        if not filtered:
            _save_options_cache(cache_path, None)
            return None

        # Encontrar el contrato más cercano: priorizar strike, luego exp, preferir con volumen
        best = None
        best_dist = float('inf')
        for a in filtered:
            strike_dist = abs(a['strike'] - target_strike)
            exp_dist = abs((datetime.strptime(a['exp_date'], '%Y-%m-%d') - target_exp_date).days)
            # Penalizar contratos sin volumen/OI
            vol_penalty = 0 if (a.get('volume', 0) or 0) > 0 or (a.get('open_interest', 0) or 0) > 0 else 0.1
            dist = strike_dist / target_strike + exp_dist / 15 + vol_penalty
            if dist < best_dist:
                best_dist = dist
                best = a

        _save_options_cache(cache_path, best)
        return best

    except Exception as e:
        print(f"    EODHD options error for {ticker}: {e}")
        _save_options_cache(cache_path, None)
        return None


def validate_options_real_vs_bs(option_trades, api_key=None):
    """
    Para cada trade de opciones, busca el precio real en EODHD y compara con BS.
    CLAVE: Recalcula BS con los parámetros del contrato real matcheado para que
    la comparación sea justa (mismo strike y DTE).
    Devuelve lista de dicts con comparación.
    """
    print(f"\n{'='*100}")
    print(f"  VALIDACIÓN: PRECIOS REALES (EODHD) vs BLACK-SCHOLES")
    print(f"  Método: Recalcular BS con strike/DTE del contrato real matcheado")
    print(f"{'='*100}")

    comparisons = []
    for opt in sorted(option_trades, key=lambda o: o.entry_date):
        # Calcular fecha expiración esperada
        exp_date = opt.entry_date + timedelta(days=opt.dte_at_entry)

        # Buscar precio real al ENTRY
        entry_real = fetch_real_option(opt.ticker, opt.entry_date, opt.strike, exp_date, api_key)

        # Buscar precio real al EXIT (mismo contrato)
        exit_real = None
        if opt.exit_date and entry_real:
            real_exp = datetime.strptime(entry_real['exp_date'], '%Y-%m-%d')
            exit_real = fetch_real_option(
                opt.ticker, opt.exit_date, entry_real['strike'], real_exp, api_key)

        comp = {
            'ticker': opt.ticker,
            'entry_date': opt.entry_date,
            'exit_date': opt.exit_date,
            'stock_price': opt.entry_stock_price,
            'strike_bs': opt.strike,
            'dte_bs': opt.dte_at_entry,
            'contracts': opt.num_contracts,
            'bs_entry_price': opt.entry_option_price,
            'bs_pnl': opt.pnl_euros,
            'bs_iv': opt.entry_iv,
        }

        if entry_real:
            real_strike = entry_real['strike']
            real_exp_dt = datetime.strptime(entry_real['exp_date'], '%Y-%m-%d')
            real_dte = (real_exp_dt - opt.entry_date).days
            real_ask = entry_real.get('ask') or 0
            real_bid = entry_real.get('bid') or 0
            real_mid = entry_real.get('midpoint') or 0
            real_iv = entry_real.get('volatility') or 0

            comp['real_strike'] = real_strike
            comp['real_dte'] = real_dte
            comp['real_exp'] = entry_real['exp_date']
            comp['real_ask_entry'] = real_ask
            comp['real_bid_entry'] = real_bid
            comp['real_mid_entry'] = real_mid
            comp['real_iv_entry'] = real_iv
            comp['real_volume'] = entry_real.get('volume', 0) or 0
            comp['real_oi'] = entry_real.get('open_interest', 0) or 0

            # *** CLAVE: Recalcular BS con los parámetros del contrato REAL ***
            real_T = max(real_dte / 365.0, 0.01)
            bs_matched = black_scholes_call(
                opt.entry_stock_price, real_strike, real_T,
                CONFIG['risk_free_rate'], opt.entry_iv
            )
            comp['bs_matched_price'] = bs_matched['price']

            # IV premium ratio: cuánto más cuesta el contrato real vs BS
            # Usamos midpoint para comparación más justa (ask incluye spread)
            price_for_ratio = real_mid if real_mid > 0 else real_ask
            if bs_matched['price'] > 0.5 and price_for_ratio > 0:
                comp['iv_premium_ratio'] = price_for_ratio / bs_matched['price']
            else:
                comp['iv_premium_ratio'] = None

            # Strike mismatch warning
            strike_pct_diff = abs(real_strike - opt.strike) / opt.strike
            comp['strike_mismatch_pct'] = strike_pct_diff

        if exit_real:
            comp['real_ask_exit'] = exit_real.get('ask') or 0
            comp['real_bid_exit'] = exit_real.get('bid') or 0
            comp['real_mid_exit'] = exit_real.get('midpoint') or 0
            comp['real_iv_exit'] = exit_real.get('volatility') or 0

            # PnL real: compramos al ask, vendemos al bid
            real_entry_px = entry_real.get('ask') or entry_real.get('midpoint') or 0
            real_exit_px = exit_real.get('bid') or exit_real.get('midpoint') or 0
            if real_entry_px > 0 and real_exit_px > 0 and opt.num_contracts > 0:
                comp['real_pnl'] = (real_exit_px - real_entry_px) * opt.num_contracts * 100
            else:
                comp['real_pnl'] = None
        else:
            comp['real_pnl'] = None

        comparisons.append(comp)

    # === TABLA 1: Comparación de precios (contrato matcheado) ===
    print(f"\n  {'Ticker':<8s} {'Entry':<12s} {'K_BS':>7s} {'K_Real':>7s} {'DTE_BS':>6s} {'DTE_R':>5s} "
          f"{'BS_orig':>8s} {'BS_adj':>8s} {'Real_Mid':>8s} {'IV_Ratio':>8s} {'BS_IV':>6s} {'Mkt_IV':>6s} {'Note':<12s}")
    print('  ' + '-' * 120)

    iv_ratios = []
    for c in comparisons:
        note = ''
        if 'real_strike' not in c:
            note = 'NO MATCH'
            print(f"  {c['ticker']:<8s} {c['entry_date'].strftime('%Y-%m-%d'):<12s} "
                  f"${c['strike_bs']:>6.0f} {'—':>7s} {c['dte_bs']:>6d} {'—':>5s} "
                  f"${c['bs_entry_price']:>7.2f} {'—':>8s} {'—':>8s} {'—':>8s} "
                  f"{c['bs_iv']:.0%}  {'—':>6s} {note:<12s}")
            continue

        smm = c.get('strike_mismatch_pct', 0)
        if smm > 0.05:
            note = f'K diff {smm:.0%}'
        elif c.get('real_volume', 0) == 0 and c.get('real_oi', 0) == 0:
            note = 'no vol/OI'

        ratio = c.get('iv_premium_ratio')
        ratio_str = f"{ratio:.2f}x" if ratio else '—'
        real_iv = c.get('real_iv_entry', 0)
        real_iv_str = f"{real_iv:.0%}" if real_iv else '—'

        if ratio and 0.5 < ratio < 3.0:
            iv_ratios.append(ratio)

        print(f"  {c['ticker']:<8s} {c['entry_date'].strftime('%Y-%m-%d'):<12s} "
              f"${c['strike_bs']:>6.0f} ${c['real_strike']:>6.0f} {c['dte_bs']:>6d} {c.get('real_dte', 0):>5d} "
              f"${c['bs_entry_price']:>7.2f} ${c.get('bs_matched_price', 0):>7.2f} "
              f"${c.get('real_mid_entry', 0):>7.2f} {ratio_str:>8s} "
              f"{c['bs_iv']:.0%}  {real_iv_str:>6s} {note:<12s}")

    print('  ' + '-' * 120)

    # === RESUMEN: IV Premium Factor ===
    if iv_ratios:
        median_ratio = np.median(iv_ratios)
        mean_ratio = np.mean(iv_ratios)
        print(f"\n  IV Premium Ratio (Real_Mid / BS_adjusted):")
        print(f"    Trades válidos: {len(iv_ratios)}")
        print(f"    Mediana: {median_ratio:.2f}x")
        print(f"    Media:   {mean_ratio:.2f}x")
        print(f"    Rango:   {min(iv_ratios):.2f}x — {max(iv_ratios):.2f}x")
        if median_ratio > 1:
            print(f"    → BS subestima ~{(median_ratio-1)*100:.0f}% (IV mercado > HV)")
        else:
            print(f"    → BS sobreestima ~{(1-median_ratio)*100:.0f}% (HV > IV mercado)")
        print(f"    → Haircut recomendado para backtest: multiplicar coste entrada por {median_ratio:.2f}")
    else:
        print(f"\n  No hay suficientes matches válidos para calcular IV premium")

    # === TABLA 2: PnL comparison (si hay exit matches) ===
    pnl_matches = [c for c in comparisons if c.get('real_pnl') is not None]
    if pnl_matches:
        print(f"\n  {'Ticker':<8s} {'Entry':<12s} {'Exit':<12s} {'BS PnL':>10s} {'Real PnL':>10s} {'Diff':>10s}")
        print('  ' + '-' * 70)
        total_bs = sum(c['bs_pnl'] for c in pnl_matches)
        total_real = sum(c['real_pnl'] for c in pnl_matches)
        for c in pnl_matches:
            diff = c['bs_pnl'] - c['real_pnl']
            print(f"  {c['ticker']:<8s} {c['entry_date'].strftime('%Y-%m-%d'):<12s} "
                  f"{c['exit_date'].strftime('%Y-%m-%d') if c['exit_date'] else '???':<12s} "
                  f"€{c['bs_pnl']:>+9,.0f} €{c['real_pnl']:>+9,.0f} €{diff:>+9,.0f}")
        print('  ' + '-' * 70)
        print(f"  {'TOTAL':<8s} {'':24s} €{total_bs:>+9,.0f} €{total_real:>+9,.0f} €{total_bs - total_real:>+9,.0f}")

    return comparisons


# =============================================================================
# UNIVERSOS
# =============================================================================

# S&P 500 completo (mismo que v14)
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

EU_UNIVERSE = [
    'SAP', 'SIE.DE', 'ALV.DE', 'DTE.DE', 'MUV2.DE', 'BAS.DE', 'BMW.DE', 'MBG.DE', 'ADS.DE', 'IFX.DE',
    'OR.PA', 'MC.PA', 'SAN.PA', 'AI.PA', 'BNP.PA', 'SU.PA', 'AIR.PA', 'CS.PA', 'DG.PA', 'RI.PA',
    'ASML', 'INGA.AS', 'PHIA.AS', 'AD.AS',
    'IBE.MC', 'SAN.MC', 'TEF.MC', 'ITX.MC',
    'ENEL.MI', 'ISP.MI', 'UCG.MI', 'ENI.MI',
    'KBC.BR', 'ABI.BR',
    'NOK', 'NOVO-B.CO', 'ERIC-B.ST', 'VOLV-B.ST', 'SAND.ST', 'NESTE.HE',
    'SHEL', 'HSBC', 'BP', 'RIO', 'GSK', 'ULVR.L', 'LSEG.L', 'BATS.L', 'DGE.L',
    'NESN.SW', 'ROG.SW', 'NOVN.SW', 'UBSG.SW', 'ZURN.SW', 'ABBN.SW',
    'CRH',
]

ASIA_UNIVERSE = [
    '7203.T', '6758.T', '6861.T', '8306.T', '9984.T', '6501.T', '7267.T', '8035.T', '4063.T', '9432.T',
    'BHP.AX', 'CBA.AX', 'CSL.AX', 'NAB.AX', 'WBC.AX', 'FMG.AX', 'WDS.AX', 'RIO.AX',
    'BABA', 'JD', 'PDD', 'BIDU', '0700.HK',
]

ETF_UNIVERSE = [
    'GLD', 'SLV', 'GDX', 'GDXJ', 'USO', 'UNG', 'DBA',
    'XLE', 'XLF', 'XLK', 'XLV', 'XLI', 'XLU', 'SMH', 'XBI',
    'EEM', 'VWO', 'EWJ', 'EWZ', 'FXI',
    'TLT', 'IEF', 'HYG', 'LQD', 'AGG',
    'QQQ', 'IWM', 'SPY',
]


def compute_dollar_volume_rank(signals_data, all_data, current_date, lookback=20, option_pctl=90):
    """
    Calcula el dollar volume (precio × volumen) medio de los últimos `lookback` días
    para cada ticker con datos. Devuelve:
      - top_tickers: set con los tickers en el top 25% de TODO el universo (señales)
      - top_us_options: set con los tickers SP500 en el top 25% del SP500 (opciones US)
    100% ex-ante: solo usa datos hasta current_date.
    """
    dvol = {}
    for ticker, df in all_data.items():
        mask = df.index <= current_date
        recent = df[mask].tail(lookback)
        if len(recent) >= 10:
            avg_dvol = (recent['Close'] * recent['Volume']).mean()
            dvol[ticker] = avg_dvol

    if not dvol:
        return set(), set()

    # Top 25% de TODO el universo = señales elegibles
    threshold = np.percentile(list(dvol.values()), 75)
    top_tickers = {t for t, v in dvol.items() if v >= threshold}

    # Top N% SOLO del SP500 = opciones US elegibles (dinámico)
    sp500_set = set(SP500_TICKERS)
    sp500_dvol = {t: v for t, v in dvol.items() if t in sp500_set}
    if sp500_dvol:
        sp500_threshold = np.percentile(list(sp500_dvol.values()), option_pctl)
        top_us_options = {t for t, v in sp500_dvol.items() if v >= sp500_threshold}
    else:
        top_us_options = set()

    return top_tickers, top_us_options


def run_backtest_v16(months, label, all_data, use_options=False,
                     max_us_options=2, max_eu_options=0,
                     mcap_percentile=75, option_percentile=90, verbose=False):
    """
    Backtest con filtro dinámico de market cap proxy (dollar volume).
    En cada barra, solo se consideran señales de tickers en el top percentile.
    """
    print(f"\n{'='*70}")
    print(f"  {label} -- {months} MESES")
    if use_options:
        print(f"  Opciones: US max {max_us_options} @ 3% + EU max {max_eu_options} @ 10%")
        print(f"  Opciones US elegibles: top {100-option_percentile}% SP500 por dollar volume (~{int(500*(100-option_percentile)/100)} tickers)")
    print(f"  Filtro señales: top {100-mcap_percentile}% por dollar volume (20d)")
    print(f"{'='*70}")

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
    print(f"  Tickers con datos: {len(all_data)}")

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

    eu_options_set = set(OPTIONS_ELIGIBLE_EU)
    # US options: DINÁMICO — top 25% SP500 por dollar volume (recalculado cada 5 barras)
    # Ya no se usa set(SP500_TICKERS) completo — ese era el bug
    top_us_options = set()

    signals_filtered = 0
    mcap_cache_interval = 5  # recalculate every 5 bars for speed

    # =================================================================
    # LOOP PRINCIPAL
    # =================================================================
    bar_count = 0
    top_tickers = set()

    for current_date in all_dates:
        bar_count += 1

        # Recalculate dollar volume rank periodically (every 5 bars)
        if bar_count % mcap_cache_interval == 1 or not top_tickers:
            top_tickers, top_us_options = compute_dollar_volume_rank(
                signals_data, all_data, current_date, lookback=20, option_pctl=option_percentile)
            # Always include ETFs (no market cap filter for them)
            top_tickers |= set(ETF_UNIVERSE)

        # 1. GESTIONAR TRADES ACTIVOS
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

        # 3. BUSCAR NUEVAS SEÑALES
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

                # FILTRO CLAVE: solo tickers en el top 25% por dollar volume
                if ticker not in top_tickers:
                    signals_filtered += 1
                    continue

                df = signals_data[ticker]['df']
                bar = df.iloc[idx]

                # Decidir opción o acción
                # Opciones US: solo top 25% SP500 por dollar volume (dinámico)
                # Opciones EU: lista fija OPTIONS_ELIGIBLE_EU (misma que v12)
                is_eu_opt = ticker in eu_options_set
                is_us_opt = ticker in top_us_options
                open_as_option = False
                if use_options and (is_eu_opt or is_us_opt):
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
                    # Acción
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
    print(f"  Trades: {len(all_trades)} stock + {len(all_option_trades)} opts ({len(opt_us)} US + {len(opt_eu)} EU) = {total_count}")
    print(f"  WR: {win_rate:.1f}% | PnL: EUR {total_pnl:+,.0f}")
    print(f"  Señales filtradas por mcap: {signals_filtered}")
    if all_option_trades:
        print(f"  PnL opts US: EUR {pnl_opt_us:+,.0f} | EU: EUR {pnl_opt_eu:+,.0f}")
        # Detalle de cada opción
        print(f"\n  DETALLE OPCIONES ({len(all_option_trades)} trades):")
        for i, opt in enumerate(sorted(all_option_trades, key=lambda o: o.entry_date)):
            region = "EU" if opt.ticker in eu_options_set else "US"
            days = (opt.exit_date - opt.entry_date).days if opt.exit_date else 0
            pnl_pct = (opt.pnl_euros / opt.position_euros * 100) if opt.position_euros else 0
            sign = '+' if opt.pnl_euros >= 0 else ''
            print(f"    {i+1:2d}. {opt.entry_date.strftime('%Y-%m-%d')} -> {opt.exit_date.strftime('%Y-%m-%d') if opt.exit_date else '???'} "
                  f"| {opt.ticker:10s} [{region}] | K=${opt.strike:.2f} | "
                  f"P&L EUR {sign}{opt.pnl_euros:.0f} ({sign}{pnl_pct:.1f}%) | {days}d | {opt.exit_reason}")

    # Top 5 stock trades por PnL
    if all_trades:
        top5 = sorted(all_trades, key=lambda t: t.pnl_euros, reverse=True)[:5]
        bot5 = sorted(all_trades, key=lambda t: t.pnl_euros)[:5]
        print(f"\n  TOP 5 STOCK TRADES:")
        for t in top5:
            pnl_pct = (t.pnl_euros / t.position_euros * 100) if t.position_euros else 0
            print(f"    {t.ticker:10s} | {t.entry_date.strftime('%Y-%m-%d')} -> {t.exit_date.strftime('%Y-%m-%d') if t.exit_date else '???'} | EUR {t.pnl_euros:+,.0f} ({pnl_pct:+.1f}%) | {t.exit_reason}")
        print(f"  PEORES 5 STOCK TRADES:")
        for t in bot5:
            pnl_pct = (t.pnl_euros / t.position_euros * 100) if t.position_euros else 0
            print(f"    {t.ticker:10s} | {t.entry_date.strftime('%Y-%m-%d')} -> {t.exit_date.strftime('%Y-%m-%d') if t.exit_date else '???'} | EUR {t.pnl_euros:+,.0f} ({pnl_pct:+.1f}%) | {t.exit_reason}")

    return {
        'label': label,
        'stock_trades': len(all_trades),
        'option_trades': len(all_option_trades),
        'all_option_trades_obj': all_option_trades,  # objetos completos para validación
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
        'signals_filtered': signals_filtered,
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--months', type=int, default=120)
    parser.add_argument('--validate-only', action='store_true',
                        help='Solo v12 + v16 top10%% con validación real EODHD')
    args = parser.parse_args()
    months = args.months

    print(f"\n{'#'*70}")
    print(f"  TEST v16: FILTRO DINAMICO POR DOLLAR VOLUME (TOP 25%)")
    print(f"  Periodo: {months} meses | Fecha: {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'#'*70}")

    # Cargar caches existentes
    all_data = {}
    for cache_name in [f'v15_{months}m', f'v14_24m', f'v15_60m', f'v15_120m']:
        cache_dir = os.path.join(PROJECT_DIR, 'data_cache', cache_name)
        if os.path.exists(cache_dir):
            for f in os.listdir(cache_dir):
                if not f.endswith('.csv.gz'):
                    continue
                ticker = f.replace('.csv.gz', '').replace('_', '.')
                if ticker in all_data:
                    continue  # ya cargado de cache anterior
                fpath = os.path.join(cache_dir, f)
                df = pd.read_csv(fpath, compression='gzip')
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
    print(f"  Cache total: {len(all_data)} tickers")

    # Descargar faltantes
    all_needed = set(SP500_TICKERS + EU_UNIVERSE + ASIA_UNIVERSE + ETF_UNIVERSE + list(ASSETS.keys()))
    missing = [t for t in all_needed if t not in all_data]
    if missing:
        cache_dir = os.path.join(PROJECT_DIR, 'data_cache', f'v16_{months}m')
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
                safe = ticker.replace('.', '_')
                df[['Open', 'High', 'Low', 'Close', 'Volume']].to_csv(
                    os.path.join(cache_dir, f'{safe}.csv.gz'), compression='gzip')
            else:
                print(f"    FAILED: {ticker}")
            if (i + 1) % 50 == 0 or i == len(missing) - 1:
                print(f"\r  {i+1}/{len(missing)} procesados", end='')
        print()

    print(f"  Total tickers con datos: {len(all_data)}")

    v12_tickers = list(ASSETS.keys())
    v16_tickers = list(set(SP500_TICKERS + EU_UNIVERSE + ASIA_UNIVERSE + ETF_UNIVERSE))

    # =================================================================
    # TESTS
    # =================================================================
    results = []

    # 1) v12 COMPLETO referencia (2+2)
    t0 = time.time()
    r = run_backtest_eu(
        months=months, tickers=v12_tickers, label="v12 US+EU (2+2) REF",
        use_options=True,
        options_eligible_set=set(OPTIONS_ELIGIBLE) | set(OPTIONS_ELIGIBLE_EU),
        max_us_options=2, max_eu_options=2,
        preloaded_data=all_data,
    )
    if isinstance(r, dict) and 'error' not in r:
        r['signals_filtered'] = 0
        results.append(r)
    print(f"  [{time.time()-t0:.1f}s]")

    # 2) v16 stock-only (top 25% dollar volume)
    v16_data = {t: all_data[t] for t in v16_tickers if t in all_data}
    t0 = time.time()
    r = run_backtest_v16(
        months=months, label="v16 stock-only (top25%)",
        all_data=v16_data,
        use_options=False,
    )
    if isinstance(r, dict) and 'error' not in r:
        results.append(r)
    print(f"  [{time.time()-t0:.1f}s]")

    # 3) ITERACIONES: v16 con opciones a distintos filtros de percentil
    if args.validate_only:
        percentiles_to_test = [10]  # Solo top 10% para validación rápida
    else:
        percentiles_to_test = [10, 15, 20, 25]

    for opt_pctl_top in percentiles_to_test:
        opt_pctl = 100 - opt_pctl_top  # 90, 85, 80, 75
        t0 = time.time()
        r = run_backtest_v16(
            months=months, label=f"v16 opts top{opt_pctl_top}%",
            all_data=v16_data,
            use_options=True,
            max_us_options=2, max_eu_options=2,
            option_percentile=opt_pctl,
        )
        if isinstance(r, dict) and 'error' not in r:
            results.append(r)
        print(f"  [{time.time()-t0:.1f}s]")

    # =================================================================
    # TABLA COMPARATIVA
    # =================================================================
    print(f"\n\n{'='*130}")
    print(f"  COMPARATIVA v16 (DOLLAR VOL TOP 25%) vs v12 — {months} MESES")
    print(f"{'='*130}")
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
        print(f"\n\n{'='*90}")
        print(f"  GOLD OVERLAY 30% — {months} MESES")
        print(f"{'='*90}")
        print(f"{'Universo':<30s} {'CAGR sin Gold':>14s} {'CAGR con Gold':>14s} {'DD sin Gold':>12s} {'DD con Gold':>12s}")
        print('-' * 90)

        for r in results:
            if r.get('equity_curve') and r.get('option_trades', 0) > 0:
                try:
                    gold_r = simulate_gold_overlay(r, gld_data, gold_reserve_pct=0.30)
                    if gold_r:
                        cagr_no = r.get('annualized_return_pct', 0)
                        cagr_g = gold_r.get('ann_gold', 0)
                        dd_no = r.get('max_drawdown', 0)
                        dd_g = gold_r.get('maxdd_gold', 0)
                        print(f"{r['label']:<30s} {cagr_no:>+13.1f}% {cagr_g:>+13.1f}% {dd_no:>11.1f}% {dd_g:>11.1f}%")
                except Exception as e:
                    print(f"  Gold overlay error for {r['label']}: {e}")

    # =================================================================
    # VALIDACIÓN OPCIONES: PRECIOS REALES vs BLACK-SCHOLES
    # =================================================================
    if months <= 24:  # Solo si tenemos datos reales (EODHD ~2 años)
        print(f"\n\n{'#'*100}")
        print(f"  VALIDACIÓN CON PRECIOS REALES DE OPCIONES (EODHD)")
        print(f"{'#'*100}")

        for r in results:
            # v12 usa 'all_option_trades', v16 usa 'all_option_trades_obj'
            opts_obj = r.get('all_option_trades_obj', r.get('all_option_trades', []))
            if opts_obj:
                print(f"\n  >>> {r['label']} <<<")
                validate_options_real_vs_bs(opts_obj)


if __name__ == '__main__':
    main()

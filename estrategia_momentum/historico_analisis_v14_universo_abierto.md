# Análisis v14 — Universo Abierto con Filtro de Volatilidad
# Fecha: 17 Mar 2026

## Contexto

Tras descubrir que el universo de 225 tickers de v12 tiene sesgo de supervivencia
(mega-winners como NVDA, TSLA, META; sectores ausentes como airlines, acero, shipping),
se diseñó un test para verificar si el motor momentum funciona en universos "ciegos".

### Descubrimiento previo: Perfil de volatilidad (120m, stock-only)

Análisis de los 577 trades stock del v12 a 120m por quintil de volatilidad 60d pre-señal:

| Quintil Vol | Trades | WR | PF | Exp/trade | Total PnL |
|-------------|--------|-----|-----|-----------|-----------|
| Q1 (3-17%) | 116 | 37.1% | 1.29 | EUR 6 | EUR 692 |
| Q2 (17-22%) | 115 | 26.1% | 1.42 | EUR 9 | EUR 1,048 |
| Q3 (22-27%) | 115 | 29.6% | 2.88 | EUR 41 | EUR 4,740 |
| Q4 (27-37%) | 115 | 24.3% | 1.19 | EUR 7 | EUR 834 |
| Q5 (37-183%) | 116 | 35.3% | 5.66 | EUR 125 | EUR 14,514 |

Vol >27%: PF 3.04, 71% del PnL total, 41% de trades.
Vol <22%: PF 1.37, apenas edge.

### Señales US vs EU vs Asia (stock-only, 120m)

| Region | Trades | WR | PF | Exp/trade | Total PnL |
|--------|--------|-----|-----|-----------|-----------|
| US | 412 | 31.6% | 2.39 | EUR 35 | EUR 14,567 |
| EU | 165 | 23.6% | 1.70 | EUR 21 | EUR 3,465 |
| Asia-Pac | 66 | 27.3% | 3.06 | EUR 46 | EUR 3,066 |

Options US: PF 2.24, +EUR 43K. Options EU: PF 0.89, -EUR 2.4K.

## Test v14: Universo Abierto a 24 meses (stock-only)

### Setup
- Fuente de datos: EODHD (primary) + Yahoo Finance (fallback para .T, .MI delisted)
- 642 tickers únicos, 641 con datos, 1 fallido (PXD delisted)
- 14 tickers fallback Yahoo (japoneses .T + italianos .MI)
- Cache guardado: `data_cache/v14_24m/`

### Universos probados

1. **S&P 500** (501 tickers → 500 con datos)
2. **Nasdaq 100** (98 tickers con datos)
3. **ETFs** (41 tickers — commodities, sectoriales, intl, fixed income)
4. **v12 original** (225 tickers)
5. **Combinado SP500+NDX+ETFs** (556 tickers)

### Resultados STOCK-ONLY (sin opciones, sin gold)

| Universo | Filtro Vol | Tickers | Trades | WR | PF | CAGR | MaxDD | Final EUR |
|----------|-----------|---------|--------|-----|-----|------|-------|-----------|
| S&P 500 | Ninguno | 500 | 199 | 27.6% | 1.26 | +9.2% | -19.9% | 11,931 |
| S&P 500 | >25% | 500 | 55 | 23.6% | 1.41 | +6.4% | -12.7% | 11,317 |
| Nasdaq 100 | Ninguno | 98 | 190 | 25.8% | 1.12 | +5.8% | -12.7% | 11,201 |
| Nasdaq 100 | >25% | 98 | 32 | 25.0% | 0.67 | -2.6% | -6.8% | 9,493 |
| ETFs | Ninguno | 41 | 133 | 36.1% | 2.21 | +19.5% | -13.6% | 14,282 |
| ETFs | >25% | 41 | 24 | 16.7% | 0.58 | -3.1% | -7.7% | 9,388 |
| v12 original | Ninguno | 225 | 170 | 30.0% | 1.32 | +15.1% | -23.8% | 13,237 |
| v12 original | >25% | 225 | 31 | 22.6% | 0.20 | -23.4% | -41.4% | 5,863 |
| SP500+NDX+ETFs | Ninguno | 556 | 203 | 29.1% | 1.41 | +15.6% | -14.9% | 13,356 |
| SP500+NDX+ETFs | >25% | 556 | 38 | 23.7% | 1.02 | +0.2% | -8.2% | 10,048 |

### Impacto del filtro de volatilidad >25%

| Universo | ΔPF | ΔCAGR | ΔDD | Trades filtradas |
|----------|-----|-------|-----|-----------------|
| S&P 500 | +0.14 | -2.8pp | +7.2pp | 301 |
| Nasdaq 100 | -0.45 | -8.4pp | +5.9pp | 78 |
| ETFs | -1.63 | -22.6pp | +5.9pp | 124 |
| v12 original | -1.13 | -38.5pp | -17.6pp | 143 |
| SP500+NDX+ETFs | -0.39 | -15.3pp | +6.7pp | — |

### Conclusiones

1. **Filtro vol>25% DESTRUYE resultados a 24m**. En un rally generalizado (Mar 2024-Mar 2026),
   acciones "tranquilas" también producen breakouts rentables. El filtro descarta demasiadas
   señales buenas. Probablemente funcione mejor a horizontes largos (120m+) donde filtra
   señales en mercados laterales.

2. **ETFs = ganador absoluto** (PF 2.21, CAGR +19.5%). Commodities y sectoriales en rally
   (GLD, SLV, GDX, XLE, SMH) aportan diversificación real.

3. **S&P 500 sin sesgo funciona** (PF 1.26, +9.2%) pero peor que v12 (+15.1%).
   La diferencia (~6pp) viene más de la inclusión de ETFs que de cherry-picking.

4. **Nasdaq 100 sorprendentemente débil** (PF 1.12, +5.8%). Growth puro ≠ mejor momentum.

5. **Combinado SP500+NDX+ETFs** es el más equilibrado: PF 1.41, +15.6%, DD -14.9%.
   Similar al v12 en CAGR pero con menor DD (-14.9% vs -23.8%).

6. **El sesgo del universo v12 es MODERADO**: +15.1% vs +9.2% (S&P puro) = +6pp de ventaja,
   explicable por la inclusión de ETFs commodities/sectoriales, no por cherry-picking extremo.

### Limitación crítica: TEST ES STOCK-ONLY

El CAGR real de v12 viene de las opciones (triplican el retorno):
- v12 stock-only 240m: ~+10% CAGR
- v12 con opciones 240m: +36.3% CAGR
- v12g (+ gold) 120m: +51.1% CAGR

**Próximo paso**: Repetir test con opciones US (2 slots) para ver si el edge de opciones
se mantiene en universos sin sesgo.

---

## Test v14b: Con Opciones US (2 slots) — 24 meses

### Resultados

| Universo | Stock | Opts | Total | WR | PF | CAGR | MaxDD | PnL EUR | Opts PnL |
|----------|-------|------|-------|-----|-----|------|-------|---------|----------|
| v12 stock-only | 168 | 0 | 168 | 34.5% | 2.34 | +22.4% | -10.0% | +4,973 | — |
| v12 + opts US | 140 | 14 | 154 | 37.7% | 1.67 | +38.8% | -28.2% | +9,272 | +4,201 |
| SP500 stock-only | 193 | 0 | 193 | 29.0% | 1.27 | +5.5% | -12.5% | +1,137 | — |
| SP500 + opts US | 157 | 16 | 173 | 28.3% | 0.73 | -15.8% | -53.9% | -2,915 | -4,148 |
| NDX100 stock-only | 189 | 0 | 189 | 25.4% | 1.11 | +2.7% | -6.3% | +556 | — |
| NDX100 + opts US | 156 | 16 | 172 | 29.1% | 1.20 | +10.4% | -28.9% | +2,183 | +1,237 |
| ETFs stock-only | 103 | 0 | 103 | 32.0% | 2.03 | +8.9% | -4.9% | +1,851 | — |
| ETFs + opts US | 88 | 14 | 102 | 32.4% | 1.48 | +14.7% | -31.8% | +3,151 | +1,907 |
| ALL stock-only | 196 | 0 | 196 | 28.1% | 1.27 | +5.3% | -12.9% | +1,085 | — |
| ALL + opts US | 158 | 17 | 175 | 28.0% | 0.74 | -15.1% | -39.2% | -2,794 | -3,779 |

### Conclusiones v14b
- Opciones en SP500 DESTRUYEN valor (-€4,148). Señales de baja calidad amplificadas.
- Opciones en v12 CREAN valor (+€4,201). Universo curado → mejores señales para opciones.
- NDX100 y ETFs intermedios.

---

## Test v15: Survivorship-Free con Universo Rotativo

### Metodología
- Universo histórico real: top 10 por sector del S&P 500 COMO ERAN en cada momento.
- Snapshots: 2006, 2011, 2016, 2021. Rotación cada 5 años.
- ETFs fijos (sin survivorship bias): GLD, TLT, QQQ, etc.
- ~97 tickers por período + ~28 ETFs = ~125 tickers activos.
- Tickers delisted mapeados a sucesor si existe (16 delisted sin sucesor).
- Datos: sp500_historical_universe.py

### v15 vs v12 — 24 meses

| Variante | CAGR | MaxDD | PF | Opts PnL |
|----------|------|-------|-----|----------|
| v12 stock-only | +22.4% | -10.0% | 2.34 | — |
| v15 rotativo stock-only | +12.4% | -7.4% | 1.87 | — |
| v12 + opts US | +38.8% | -28.2% | 1.67 | +€4,201 |
| **v15 rotativo + opts US** | **+43.2%** | -28.6% | **2.34** | **+€7,471** |

### v15 vs v12 — 60 meses

| Variante | CAGR | MaxDD | PF | Opts PnL |
|----------|------|-------|-----|----------|
| v12 stock-only | +7.8% | -12.8% | 1.65 | — |
| v15 rotativo stock-only | +6.7% | -15.4% | 1.52 | — |
| v12 + opts US | +26.2% | -59.7% | 1.85 | +€18,256 |
| **v15 rotativo + opts US** | **+28.1%** | **-58.7%** | **2.00** | **+€20,427** |

### Hallazgo clave
1. **Stock-only**: v12 tiene ~1-10pp de ventaja → survivorship bias REAL pero MODERADO.
2. **Con opciones**: v15 rotativo IGUALA o SUPERA a v12 → el edge de opciones viene
   de señales en mega-caps líquidas, no de cherry-picking.
3. **Universo más pequeño y curado por market cap del momento → MEJOR para opciones**.
   Menos ruido → opciones amplifican ganancias en vez de pérdidas.

### Pendiente
- [ ] Resultados a 120m y 240m

## Archivos
- `test_v14_universo_abierto.py` — Test stock-only universo abierto
- `test_v14b_con_opciones.py` — Test con opciones US
- `test_v15_survivorship_free.py` — Test survivorship-free con universo rotativo
- `sp500_historical_universe.py` — Universos históricos S&P 500 (2006-2021)
- `data_cache/v14_24m/` — Cache de datos (641 tickers, EODHD + Yahoo fallback)
- `data_cache/v15_60m/` — Cache de datos v15 (158 tickers, EODHD + Yahoo fallback)

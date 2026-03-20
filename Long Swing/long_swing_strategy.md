---
name: Long Swing Strategy
description: Daily momentum swing trading strategy — config, backtest results (including survivorship-free SP500 validation), paper trading, and scheduled tasks
type: project
---

## Long Swing — Estado actual (18 Mar 2026)

### Qué es
Estrategia swing diaria long-only con pyramiding. Señales RSI+MACD reversal y EMA9x32 cross en barras diarias. Entrada al OPEN del día siguiente a la señal.

### Ubicación del código
- **Código ejecutable**: `/Users/rodrigomarchalpuchol/autoresearch-mlx/long_swing/`
- **Google Drive**: `Claude/Code/Long Swing/` (copia completa con data cache)
- **Git repo**: `Claude/Code/` inicializado 17-mar-2026 (commit 17089ec)

### Archivos clave
| Archivo | Descripción |
|---------|------------|
| `config.py` | Todos los parámetros centralizados |
| `strategy.py` | Motor de señales y simulación — **SIN bug de doble conteo** |
| `data.py` | Capa de datos EODHD (API key hardcoded) |
| `scanner.py` | Scanner diario con señales recientes y EMA status |
| `backtest.py` | Runner de backtest estándar |
| `paper_trading.py` | Paper trading tracker con estado persistente (JSON) |
| `backtest_sp500_survivorship.py` | Backtest SP500 PIT — **bug doble conteo corregido 17-mar** |
| `sp500_results_120m.json` | Resultados cacheados SP500 PIT (versión corregida) |
| `sp500_trades_120m.csv` | 59 trades (56 cerrados + 3 abiertos) con cum_pnl y return_pct |

### Parámetros (config.py)
- **Universe**: 76 tickers (67 US + 8 EU + BTC-USD)
- **MAX_POS**: 4 | **RESERVE_PCT**: 20% | **COST_BPS**: 4
- **Pyramid**: +15% trigger, 100% size
- **Exit**: EMA21 < EMA50 (tras EMA21 estar por encima) | Grace period: 60 bars
- **Macro**: SMA200+VIX30 (skip entries when SPY < SMA200 or VIX >= 30)
- **LOOKBACK**: 7305 días (~240 meses) | **INITIAL**: 12,000€

### Resultados backtest — 76 tickers baseline (VERIFICADO, sin bugs)
- **240m**: 1,003,889€ / CAGR +24.8% / DD -17.6% / PF 4.38 / 200 trades
- **120m**: 73,992€ / CAGR +19.9% / DD -20.9% / PF 3.47
- **Código**: `strategy.py` → `simulate()` usa `final = cash` directamente, sin doble conteo

### Validación SP500 Survivorship-Free (17-mar-2026)

**Metodología**: SP500 histórico point-in-time (Wikipedia changes), 702 tickers, EODHD data, cache parquet.

#### BUG CORREGIDO (17-mar-2026): Doble conteo equity
`backtest_sp500_survivorship.py` tenía un doble conteo de posiciones abiertas.
- **Corregido**: `equity = cash` (todo ya liquidado)

#### BUG CORREGIDO (18-mar-2026): Exit look-ahead (Close → Next-Open)
Exit usaba `Close[exit_idx]` del mismo día que la señal EMA cross. Esto es look-ahead porque la señal necesita el Close para calcularse.
- **Antes**: señal EMA cross al Close día N → vende al Close día N (imposible)
- **Después**: señal EMA cross al Close día N → vende al Open día N+1 (ejecutable)
- **Efecto**: resultados MEJORAN (+0.8pp CAGR, +3.6pp WR) porque Close está deprimido por el retroceso que genera la señal; Next-Open es mejor precio de venta
- **Simétrico con entry**: señal día N → compra Open día N+1 (ya era así)

#### Filtros aplicados progresivamente

| Test | Capital | CAGR | DD | PF | Alpha vs SPY |
|------|---------|------|-----|-----|-------------|
| SP500 sin filtros | 20,542€ | +5.5% | -32.1% | 1.26 | -9.2pp |
| + $1B liq (look-ahead, NO pyramid) | 42,110€ | +13.4% | -42.9% | 1.57 | -1.3pp |
| + $1B liq (look-ahead) + pyramid | 49,581€ | +15.2% | -40.4% | 1.92 | +0.5pp |
| **+ $1B liq POINT-IN-TIME + pyr + EMA** | **59,653€** | **+17.4%** | **-8.3%** | **4.31** | **+2.7pp** |
| 76 tickers baseline (120m) | 73,992€ | +19.9% | -20.9% | 3.47 | +5.4pp |
| SPY buy & hold | 46,292€ | +14.5% | ~-34% | — | — |

#### Versión final PIT (CORRECTA — exit Next-Open, 18-mar)
- **CAGR +18.2%** | DD -8.8% | PF 4.88 | 56 cerrados + 3 abiertos | Alpha +3.4pp vs SPY
- 381 señales filtradas por liquidez point-in-time
- **3 trades abiertos**: MU (+254%, +24,263€), CSCO (+17%, +1,583€), GE (-0.4%, -11€)
- PnL cerrados: +21,928€ | PnL abiertos: +25,835€ | Total: +47,763€

#### Comparación honesta con baseline
- El baseline de 76 tickers (+19.9% CAGR) **supera** al SP500 PIT (+17.4%)
- PERO: el baseline tiene survivorship bias (NVDA, META seleccionados a posteriori)
- PERO: el SP500 PIT tiene mejor DD (-8.3% vs -20.9%) y mejor PF (4.31 vs 3.47)
- La calidad de trades del SP500 PIT es superior, el CAGR menor viene de menos trades (56 vs más)

#### Conclusiones clave
1. **La estrategia genera alpha real** (+2.7pp vs SPY) sin survivorship bias
2. **El DD del SP500 PIT es excelente** (-8.3%) — 4x menor que SPY
3. **El baseline de 76 tickers tiene ~2.5pp de survivorship bias** (19.9% - 17.4%)
4. **Liquidez point-in-time es IMPRESCINDIBLE** — solo 12 de 82 tickers $1B coinciden entre 2016 y 2026
5. **El filtro EMA pre-entry es el mayor driver** — elimina grace exits
6. **Pyramiding es la base** — sin él, apenas empata con SPY

#### Solapamiento liquidez temporal
- 2016: solo 14 tickers pasaban $1B
- 2026: 82 tickers pasan $1B
- En ambos períodos: solo 12

### Fuente de datos
- **EODHD** (primary) — API key: 69b86cbae43f91.37277389
- BTC-USD → BTC-USD.CC en EODHD
- ^VIX → VIX.INDX en EODHD
- Yahoo Finance ya NO se usa en Long Swing
- **Cache**: `data_cache/sp500/` con parquet por ticker (696 tickers cacheados)

### Scheduled Tasks (Slack DM)
- **long-swing-scan-eu**: 9:00 L-V → DM Slack a U08PF7MNFV1
- **long-swing-scan-us**: 15:30 L-V → DM Slack a U08PF7MNFV1
- Tasks antiguas (`scanner-eu/us`) desactivadas

### Paper Trading
- **Inicio**: 17-mar-2026, capital 12,000€
- **Estado**: Sin posiciones abiertas. Sin señales del viernes 14-mar → sin acción lunes 17-mar
- **Comandos**: `uv run python -m long_swing.paper_trading [status|buy|sell|update|history|reset]`

### LEAPS + IV Rank Filter (18-mar-2026)

#### Concepto
Apalancamiento selectivo: comprar **LEAPS** (5% ITM, 365 DTE) cuando las opciones están baratas (HV Rank < 30), y **acciones** cuando la IV es cara. Esto captura leverage alto en entornos de tendencia limpia y evita pagar primas infladas.

#### Archivos LEAPS
| Archivo | Descripción |
|---------|------------|
| `backtest_leaps.py` | Motor de simulación LEAPS + acciones con filtro IV Rank |
| `leaps_ivr30_trades_120m.csv` | 59 trades (23 LEAPS + 36 stocks) con HV Rank |
| `leaps_ivrank_results_120m.json` | Resultados todos los umbrales de IV Rank |

#### Descubrimientos clave
1. **Leverage NO depende del tipo de acción, sino de condiciones de mercado (IV Rank)**
   - Misma acción tiene leverage muy distinto en distintas fechas (AAPL: 5.5x-8.3x, TSLA: 3.6x-8.6x)
   - Correlación IV-Leverage: -0.57 (fuerte negativa)
   - Años con IV baja (2017: 18%) → leverage 8.4x; IV alta (2018: 47%) → leverage 4.5x
2. **HV Rank < 30 es el filtro óptimo** — mejor eficiencia (CAGR/|DD|) de todas las variantes
3. **LEAPS en low IV** tienen WR 43% vs stocks 31% — selección natural de tendencias limpias
4. **Bug exit pricing corregido** (18-mar): EODHD query usaba `exp_date_from="2020-01-01"` → encontraba opciones corto plazo, no LEAPS. Fix: pasar fecha real de expiración

#### Resultados IVR<30 @ 120m (VERIFICADOS — exit Next-Open, 18-mar)
| Métrica | Solo Acciones | IVR<30 (LEAPS+Stock) | Solo LEAPS |
|---------|--------------|----------------------|------------|
| Capital | 12K→64K€ | **12K→542K€** | 12K→963K€ |
| CAGR | +18.2% | **+46.4%** | +55.0% |
| Max DD | -14.2% | **-23.0%** | -54.8% |
| PF | 7.58 | **16.20** | 10.93 |
| WR | 37% | 36% | 32% |
| Eficiencia | 1.29 | **2.02** | 1.00 |

#### Desglose IVR<30
- **LEAPS (23 trades, 39%)**: WR 43%, PnL +402,785€, avg leverage 5.9x, avg HVR 15.3
- **Stocks (36 trades, 61%)**: WR 31%, PnL +29,740€
- **Avg slots LEAPS**: 1.00 / 4 — media ~1 slot en LEAPS
- **Avg slots Stock**: 1.32 / 4
- **Days con posiciones**: 77% | 100% cash: 23%
- **Holding period**: LEAPS avg 111d, Stocks avg 94d
- **Pyramids**: 25 ejecutados

#### Grid de umbrales IV Rank
| Umbral | CAGR | MaxDD | PF | Eficiencia | #LEAPS |
|--------|------|-------|-----|------------|--------|
| IVR<20 | +36.8% | -23.3% | 18.62 | 1.58 | 14 |
| **IVR<30** | **+43.5%** | **-26.0%** | **16.44** | **1.67** | **23** |
| IVR<40 | +44.6% | -29.6% | 13.70 | 1.51 | 29 |
| IVR<50 | +44.8% | -29.6% | 13.29 | 1.51 | 32 |
| IVR<60 | +48.0% | -35.2% | 11.70 | 1.36 | 37 |
| IVR<70 | +43.8% | -46.0% | 10.26 | 0.95 | 43 |

#### Validación multi-periodo (18-mar-2026, exit Next-Open corregido)

| Periodo | Stock CAGR | Stock DD | IVR<30 CAGR | IVR<30 DD | IVR<30 PF | #LEAPS/#Stock |
|---------|-----------|----------|-------------|-----------|-----------|--------------|
| **24m** | +23.7% | -16.0% | **+14.2%** | -29.0% | 8.39 | 8/10 |
| **60m** | +24.6% | -17.7% | **+29.5%** | -26.4% | 15.39 | 13/23 |
| **120m** | +18.2% | -8.8% | **+46.4%** | -23.0% | 16.20 | 22/37 |

**120m**: LEAPS triplican CAGR (+18.2% → +46.4%) con DD controlado en -23%.
**60m**: LEAPS mejoran CAGR +24.6% → +29.5% con DD similar.
**24m**: Solo 18 trades. Estadísticamente poco significativo.

#### Pricing LEAPS
- **Oct 2023+**: IV real desde EODHD options API (key: 69ba6290ce4722.64310546)
- **Antes Oct 2023**: BS con IV = HV × 1.21 (premium medido: mediana de 20 muestras reales)
- **Exit**: EODHD real exit price si disponible, si no BS con misma IV y T restante
- **Cost**: 10 bps (opciones) vs 4 bps (acciones)

#### Robustez sin MU
- Sin el trade MU (77% del PnL LEAPS), CAGR IVR<30 sigue siendo **+26.5%** — el edge no depende de un solo trade

### Próximos pasos (3 acciones)
1. **Costes LEAPS realistas** — 300-500 bps (estimado -3 a -6pp CAGR)
2. **Walk-forward IVR** — optimizar en primera mitad, test en segunda
3. **Paper trading LEAPS** — 6-12 meses. Stock-only ya operable

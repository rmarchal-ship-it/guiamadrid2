# Long Swing — Resumen para continuar

**Fecha**: 18 Mar 2026
**Carpeta código**: `/Users/rodrigomarchalpuchol/autoresearch-mlx/long_swing/`
**Carpeta Google Drive**: `Mi unidad/Claude/Code/Long Swing/`

---

## 1. Qué es Long Swing

Estrategia swing diaria **long-only** sobre el SP500. Selección point-in-time de acciones con momentum, pyramiding en ganadores, macro filter para evitar mercados bajistas.

**Flujo operativo**:
1. Señal al Close del día N (RSI+MACD reversal o EMA9x32 cross)
2. Filtros: EMA21 >= EMA50 (tendencia), liquidez $1B dollar vol (point-in-time), macro (SPY>SMA200, VIX<30)
3. **Compra al Open del día N+1** (1 señal/día, RSI priority, ADX rank)
4. Pyramiding: +15% trigger → dobla posición
5. Exit: EMA21 < EMA50 cross → **vende al Open del día siguiente** (simétrico con entry)
6. 4 slots max, 20% reserva cash para pyramiding

## 2. Resultados verificados (18-mar-2026)

### Stock-only (SP500 PIT, exit Next-Open)

| Periodo | Equity | CAGR | DD | PF | Trades | WR | Alpha vs SPY |
|---------|--------|------|-----|-----|--------|-----|-------------|
| 24m | 18,354€ | +23.7% | -16.0% | 0.21 | 15 (1W/14L) | 7% | +4.5pp |
| 60m | 36,096€ | +24.6% | -17.7% | 3.14 | 33 (12W/21L) | 36% | +11.0pp |
| **120m** | **63,664€** | **+18.2%** | **-8.8%** | **4.88** | **56 (24W/32L)** | **43%** | **+3.4pp** |

### LEAPS IVR<30 (HV Rank < 30 → LEAPS 5% ITM 365 DTE, resto → acciones)

| Periodo | Equity | CAGR | DD | PF | #LEAPS/#Stock |
|---------|--------|------|-----|-----|--------------|
| 24m | 45,428€ | +14.2% | -29.0% | 8.39 | 8/10 |
| 60m | 159,605€ | +29.5% | -26.4% | 15.39 | 13/23 |
| **120m** | **542,078€** | **+46.4%** | **-23.0%** | **16.20** | **22/37** |

### Comparativa clave @ 120m

| Métrica | Stock-only | IVR<30 | Solo LEAPS |
|---------|-----------|--------|------------|
| CAGR | +18.2% | **+46.4%** | +55.0% |
| Max DD | -8.8% | **-23.0%** | -54.8% |
| PF | 4.88 | **16.20** | 10.93 |
| Eficiencia (CAGR/|DD|) | 2.07 | **2.02** | 1.00 |

## 3. Bugs corregidos

| Bug | Fecha | Impacto |
|-----|-------|---------|
| **Doble conteo equity** | 17-mar | Equity inflada 100K→60K. Corregido: `equity = cash` |
| **Exit look-ahead** | 18-mar | Exit al Close (imposible) → Next-Open. Resultados MEJORAN +0.8pp |
| **LEAPS exit pricing** | 18-mar | EODHD query encontraba opciones cortas, no LEAPS. Fix: pasar fecha expiración real |

## 4. Descubrimientos clave

1. **4 slots es óptimo** — 6 y 8 slots diluyen capital, CAGR cae a +13% y +10%
2. **1 señal/día es óptimo** — 2-4 señales/día dan peores resultados, la selectividad ES la estrategia
3. **Filtro EMA pre-entry = protección** — mismo CAGR, DD -8.8% vs -32.2% sin él
4. **ETFs destruyen alpha** — WR 27% para ETFs, roban slots de stocks con WR 39%
5. **Leverage LEAPS depende de IV Rank, no del tipo de acción** — correlación IV-Leverage -0.57
6. **LEAPS en low IV (IVR<30)**: WR 43%, avg leverage 5.9x, tendencias limpias
7. **Stocks en high IV (IVR>30)**: WR 31%, evitan pagar primas infladas
8. **Concentración moderada**: MU LEAPS = 77% del PnL, PERO sin MU el CAGR LEAPS IVR<30 sigue siendo **+26.5%** — el edge no depende de un solo trade
9. **Top 5 trades stock = ~80% del PnL stock**. Normal en momentum, implica paciencia entre outliers

## 5. Riesgos identificados (auditoría Cowork v2)

| Riesgo | Severidad | Estado |
|--------|-----------|--------|
| Survivorship bias | Resuelto | SP500 PIT elimina el sesgo |
| Exit look-ahead | **Resuelto** | Close→Next-Open (18-mar) |
| Dependencia de outliers | Inherente | 5 trades = 80% PnL. Estructura de momentum |
| Costes LEAPS (10bps vs 3-5% real) | Alto | Pendiente. Spread bid-ask LEAPS es 2-5% del premium |
| BS pricing 69% de LEAPS | Alto | Solo Oct 2023+ tiene datos reales (EODHD) |
| IVR<30 optimizado in-sample | Medio | Pendiente walk-forward |
| Muestra pequeña (56 trades/10y) | Medio | Inherente a la selectividad |
| Sin modelado fiscal | Medio | 19-28% sobre ganancias → -3 a -5pp CAGR neto |

## 6. Archivos en Google Drive

### Activos (carpeta principal)
| Archivo | Descripción |
|---------|------------|
| `backtest_sp500_survivorship.py` | Motor principal SP500 PIT (exit Next-Open) |
| `backtest_leaps.py` | Motor LEAPS con filtro IV Rank |
| `config.py` | Parámetros centralizados |
| `data.py` | Capa de datos EODHD |
| `scanner.py` | Scanner diario (señales recientes + EMA status) |
| `paper_trading.py` | Paper trading tracker |
| `sp500_trades_{24,60,120}m.csv` | Trades base por periodo |
| `sp500_results_{24,60,120}m.json` | Resultados base por periodo |
| `leaps_ivr30_trades_{24,60,120}m.csv` | Trades LEAPS+Stock IVR<30 |
| `leaps_ivrank_results_{24,60,120}m.json` | Resultados LEAPS por periodo |

### Obsoletos (`old_baseline/`)
Código y resultados del baseline de 76 tickers fijos (con survivorship bias y exit al Close).

## 7. Parámetros de la estrategia

```python
# config.py
MAX_POS = 4                     # slots simultáneos
RESERVE_PCT = 0.20              # 20% reserva para pyramiding
COST_BPS = 4                    # coste acciones (bps)
PYRAMID_TRIGGER = 0.15          # +15% para piramidear
PYRAMID_SIZE = 1.0              # dobla la posición
EMA_EXIT_FAST = 21              # EMA rápida para exit
EMA_EXIT_SLOW = 50              # EMA lenta para exit
GRACE_BARS = 60                 # barras antes de grace exit
INITIAL = 12_000                # capital inicial (€)

# LEAPS
ITM_PCT = 0.05                  # 5% in-the-money
MIN_DTE = 365                   # vencimiento mínimo 1 año
IV_HV_PREMIUM = 1.21            # IV = HV × 1.21 (medido)
LEAPS_COST_BPS = 10             # coste opciones (bps) — PENDIENTE subir a 300-500
```

## 8. Datos

- **EODHD** — API key stock: `69b86cbae43f91.37277389`
- **EODHD Options** — API key: `69ba6290ce4722.64310546` (marketplace, datos desde Oct 2023)
- **Cache**: `data_cache/sp500/` — 696 tickers en parquet
- **SP500 histórico**: Wikipedia changes (point-in-time)
- Yahoo Finance ya NO se usa

## 9. Operativa diaria

- **Scanner automático**: Slack DM a las 9:00 (EU) y 15:30 (US) L-V
- **Paper trading**: Iniciado 17-mar-2026, 12K€. Macro BEAR → sin posiciones nuevas
- **Comando scanner**: `cd autoresearch-mlx && uv run python -m long_swing.scanner`
- **Comando paper**: `cd autoresearch-mlx && uv run python -m long_swing.paper_trading [status|buy|sell]`

## 10. Próximos pasos (3 acciones pendientes)

1. **Costes LEAPS realistas** — subir de 10bps a 300-500bps (spread bid-ask real). Estimado: -3 a -6pp CAGR
2. **Walk-forward del umbral IVR** — optimizar en primera mitad (60m), test en segunda (60m)
3. **Paper trading LEAPS** — 6-12 meses antes de capital real. Stock-only ya operable

"""
Long Swing — Paper trading tracker.

Persistent state file (JSON) tracks positions, cash, closed trades.
Integrates with scanner signals and real market prices.

Usage:
  uv run python -m long_swing.paper_trading status       # show current state
  uv run python -m long_swing.paper_trading update       # check exits/pyramids with fresh prices
  uv run python -m long_swing.paper_trading buy TSLA 391.20  # record a buy at open price
  uv run python -m long_swing.paper_trading sell TSLA 400.00 [reason]  # manual sell
  uv run python -m long_swing.paper_trading history      # closed trades
"""
import sys
import json
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import pandas_ta as ta

from .config import (
    UNIVERSE, MAX_POS, RESERVE_PCT, COST_BPS, INITIAL,
    PYR_THRESHOLD, PYR_SIZE, EMA_EXIT_FAST, EMA_EXIT_SLOW, GRACE_BARS,
)
from .strategy import download_daily, get_macro_context

STATE_FILE = Path(__file__).resolve().parent / "paper_state.json"

# ── State management ─────────────────────────────────────────────────────

def _default_state():
    return {
        "initial": INITIAL,
        "cash": INITIAL,
        "positions": [],   # list of position dicts
        "closed": [],      # list of closed trade dicts
        "start_date": str(datetime.date.today()),
        "broker_costs": 0.0,  # accumulated real broker costs
    }


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return _default_state()


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


# ── Actions ──────────────────────────────────────────────────────────────

def buy(state, symbol, price, date=None, shares=None, broker_cost=0.0):
    """Open a new position or pyramid an existing one."""
    date = date or str(datetime.date.today())
    positions = state["positions"]
    cash = state["cash"]

    # Check if pyramiding existing position
    existing = [p for p in positions if p["symbol"] == symbol]
    if existing:
        pos = existing[0]
        if pos.get("pyramided"):
            print(f"  {symbol} ya tiene pyramid. No se puede añadir más.")
            return
        pct_gain = (price / pos["entry_price"] - 1.0)
        if pct_gain < PYR_THRESHOLD:
            print(f"  {symbol} solo +{pct_gain*100:.1f}% (necesita +{PYR_THRESHOLD*100:.0f}%). No pyramid.")
            return
        # Pyramid: add PYR_SIZE * original alloc
        pyr_alloc = pos["alloc"] * PYR_SIZE
        if pyr_alloc > cash:
            pyr_alloc = cash
            print(f"  Cash insuficiente para pyramid completo. Usando {pyr_alloc:.2f}€")
        if shares is None:
            pyr_shares = pyr_alloc / price
        else:
            pyr_shares = shares
            pyr_alloc = shares * price
        cost = pyr_alloc * COST_BPS / 10000
        state["cash"] -= (pyr_alloc + cost + broker_cost)
        state["broker_costs"] += broker_cost
        pos["pyr_price"] = price
        pos["pyr_date"] = date
        pos["pyr_shares"] = pyr_shares
        pos["pyr_alloc"] = pyr_alloc
        pos["pyramided"] = True
        pos["total_shares"] = pos["shares"] + pyr_shares
        print(f"  PYRAMID {symbol}: +{pyr_shares:.4f} shares @ {price:.2f} ({pyr_alloc:.2f}€)")
        save_state(state)
        return

    # New position
    n_open = len(positions)
    if n_open >= MAX_POS:
        print(f"  Max {MAX_POS} posiciones alcanzado. No se puede abrir {symbol}.")
        return

    free_slots = MAX_POS - n_open
    alloc = cash * (1 - RESERVE_PCT) / free_slots

    if shares is None:
        shares_to_buy = alloc / price
    else:
        shares_to_buy = shares
        alloc = shares * price

    cost = alloc * COST_BPS / 10000

    pos = {
        "symbol": symbol,
        "entry_price": price,
        "entry_date": date,
        "shares": shares_to_buy,
        "alloc": alloc,
        "pyramided": False,
        "pyr_price": None,
        "pyr_date": None,
        "pyr_shares": 0,
        "pyr_alloc": 0,
        "total_shares": shares_to_buy,
        "ema_was_above": False,
        "bars_held": 0,
    }

    state["cash"] -= (alloc + cost + broker_cost)
    state["broker_costs"] += broker_cost
    positions.append(pos)
    print(f"  BUY {symbol}: {shares_to_buy:.4f} shares @ {price:.2f} | Alloc: {alloc:.2f}€ | Cash left: {state['cash']:.2f}€")
    save_state(state)


def sell(state, symbol, price, reason="manual", date=None, broker_cost=0.0):
    """Close a position."""
    date = date or str(datetime.date.today())
    positions = state["positions"]
    match = [p for p in positions if p["symbol"] == symbol]
    if not match:
        print(f"  {symbol} no está en cartera.")
        return

    pos = match[0]
    proceeds = pos["total_shares"] * price
    cost = proceeds * COST_BPS / 10000
    total_invested = pos["alloc"] + pos.get("pyr_alloc", 0)
    pnl = proceeds - total_invested - cost - broker_cost

    closed = {
        **pos,
        "exit_price": price,
        "exit_date": date,
        "exit_reason": reason,
        "pnl": round(pnl, 2),
        "ret": round((proceeds / total_invested - 1) * 100, 2),
        "hold_days": (pd.Timestamp(date) - pd.Timestamp(pos["entry_date"])).days,
    }

    state["cash"] += (proceeds - cost - broker_cost)
    state["broker_costs"] += broker_cost
    positions.remove(pos)
    state["closed"].append(closed)

    tag = "W" if pnl > 0 else "L"
    print(f"  SELL {symbol}: {pos['total_shares']:.4f} shares @ {price:.2f} | PnL: {pnl:+.2f}€ ({tag}) | Reason: {reason}")
    save_state(state)


def status(state, all_data=None):
    """Print current portfolio status."""
    lines = []
    w = lines.append

    w(f"\n{'='*70}")
    w(f"  LONG SWING — Paper Trading")
    w(f"  Inicio: {state['start_date']} | Capital inicial: {state['initial']:.2f}€")
    w(f"{'='*70}")

    positions = state["positions"]

    # Get live prices if data available
    if all_data is None:
        try:
            syms = [p["symbol"] for p in positions] + ["SPY"]
            all_data = download_daily(syms, lookback_days=100, refresh=True)
        except Exception:
            all_data = {}

    # Positions
    w(f"\n  POSICIONES ABIERTAS ({len(positions)}/{MAX_POS})")
    w(f"  {'Sym':>8s} {'Entry':>8s} {'Now':>8s} {'PnL%':>7s} {'PnL€':>9s} {'Days':>5s} {'Pyr':>4s} {'EMA':>8s}")
    w("  " + "-" * 65)

    total_invested = 0
    total_value = 0

    for pos in positions:
        sym = pos["symbol"]
        df = all_data.get(sym)
        if df is not None and len(df) > 0:
            now_price = float(df["Close"].iloc[-1])
            # EMA status
            close = df["Close"].astype(float)
            if len(close) >= EMA_EXIT_SLOW:
                ema21 = float(ta.ema(close, length=EMA_EXIT_FAST).iloc[-1])
                ema50 = float(ta.ema(close, length=EMA_EXIT_SLOW).iloc[-1])
                ema_status = "21>50" if ema21 > ema50 else "EXIT!"
            else:
                ema_status = "n/a"
        else:
            now_price = pos["entry_price"]
            ema_status = "n/a"

        invested = pos["alloc"] + pos.get("pyr_alloc", 0)
        value = pos["total_shares"] * now_price
        pnl = value - invested
        pnl_pct = (value / invested - 1) * 100
        pyr_tag = "Y" if pos["pyramided"] else "-"
        days = (datetime.date.today() - datetime.date.fromisoformat(pos["entry_date"])).days

        total_invested += invested
        total_value += value

        w(f"  {sym:>8s} {pos['entry_price']:>8.2f} {now_price:>8.2f} {pnl_pct:>+6.1f}% {pnl:>+8.2f}€ {days:>5d} {pyr_tag:>4s} {ema_status:>8s}")

    # Cash & totals
    equity = state["cash"] + total_value
    total_pnl = equity - state["initial"]
    total_pnl_pct = (equity / state["initial"] - 1) * 100

    w(f"\n  Cash: {state['cash']:>10.2f}€")
    w(f"  Valor posiciones: {total_value:>10.2f}€")
    w(f"  Equity total: {equity:>10.2f}€")
    w(f"  PnL total: {total_pnl:>+10.2f}€ ({total_pnl_pct:>+.1f}%)")
    w(f"  Costes broker: {state['broker_costs']:>10.2f}€")

    # Closed trades summary
    closed = state["closed"]
    if closed:
        wins = [t for t in closed if t["pnl"] > 0]
        losses = [t for t in closed if t["pnl"] <= 0]
        total_closed_pnl = sum(t["pnl"] for t in closed)
        w(f"\n  TRADES CERRADOS: {len(closed)} ({len(wins)}W / {len(losses)}L)")
        w(f"  PnL cerrado: {total_closed_pnl:+.2f}€")

    w(f"\n{'='*70}")
    return "\n".join(lines)


def history(state):
    """Print closed trades."""
    closed = state["closed"]
    if not closed:
        print("  No hay trades cerrados.")
        return

    print(f"\n  {'Sym':>8s} {'Entry':>10s} {'Exit':>10s} {'Days':>5s} {'Ret%':>7s} {'PnL€':>9s} {'Reason':>12s} {'Pyr':>4s}")
    print("  " + "-" * 75)
    for t in closed:
        pyr_tag = "Y" if t.get("pyramided") else "-"
        print(f"  {t['symbol']:>8s} {t['entry_date']:>10s} {t['exit_date']:>10s} "
              f"{t['hold_days']:>5d} {t['ret']:>+6.1f}% {t['pnl']:>+8.2f}€ "
              f"{t['exit_reason']:>12s} {pyr_tag:>4s}")

    total = sum(t["pnl"] for t in closed)
    wins = len([t for t in closed if t["pnl"] > 0])
    print(f"\n  Total: {total:+.2f}€ | WR: {wins}/{len(closed)} ({wins/len(closed)*100:.0f}%)")


def update_ema_status(state, all_data=None):
    """Check EMA exit conditions and pyramid triggers for open positions."""
    if all_data is None:
        syms = [p["symbol"] for p in state["positions"]]
        if not syms:
            print("  No hay posiciones abiertas.")
            return []
        all_data = download_daily(syms, lookback_days=100, refresh=True)

    alerts = []
    for pos in state["positions"]:
        sym = pos["symbol"]
        df = all_data.get(sym)
        if df is None or len(df) < EMA_EXIT_SLOW:
            continue

        close = df["Close"].astype(float)
        now_price = float(close.iloc[-1])
        ema21 = float(ta.ema(close, length=EMA_EXIT_FAST).iloc[-1])
        ema50 = float(ta.ema(close, length=EMA_EXIT_SLOW).iloc[-1])

        # Update bars held
        days = (datetime.date.today() - datetime.date.fromisoformat(pos["entry_date"])).days
        pos["bars_held"] = days

        # Check EMA status
        if ema21 >= ema50:
            pos["ema_was_above"] = True

        # Exit signals
        if pos["ema_was_above"] and ema21 < ema50:
            alerts.append(f"  !! EXIT {sym}: EMA21 ({ema21:.2f}) < EMA50 ({ema50:.2f}) — VENDER a apertura")
        elif not pos["ema_was_above"] and days >= GRACE_BARS:
            alerts.append(f"  !! GRACE EXIT {sym}: {days} dias sin EMA21>50 — VENDER a apertura")

        # Pyramid trigger
        pct_gain = (now_price / pos["entry_price"] - 1.0)
        if pct_gain >= PYR_THRESHOLD and not pos.get("pyramided"):
            alerts.append(f"  >> PYRAMID {sym}: +{pct_gain*100:.1f}% — AÑADIR a apertura")

    save_state(state)

    if alerts:
        for a in alerts:
            print(a)
    else:
        print("  Sin alertas. Mantener posiciones.")

    return alerts


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:] if len(sys.argv) > 1 else ["status"]
    cmd = args[0]
    state = load_state()

    if cmd == "status":
        text = status(state)
        print(text)

    elif cmd == "buy":
        if len(args) < 3:
            print("  Uso: paper_trading buy SYMBOL PRICE [DATE] [SHARES] [BROKER_COST]")
            return
        symbol = args[1].upper()
        price = float(args[2])
        date = args[3] if len(args) > 3 else None
        shares = float(args[4]) if len(args) > 4 else None
        broker_cost = float(args[5]) if len(args) > 5 else 0.0
        buy(state, symbol, price, date=date, shares=shares, broker_cost=broker_cost)

    elif cmd == "sell":
        if len(args) < 3:
            print("  Uso: paper_trading sell SYMBOL PRICE [REASON] [DATE] [BROKER_COST]")
            return
        symbol = args[1].upper()
        price = float(args[2])
        reason = args[3] if len(args) > 3 else "manual"
        date = args[4] if len(args) > 4 else None
        broker_cost = float(args[5]) if len(args) > 5 else 0.0
        sell(state, symbol, price, reason=reason, date=date, broker_cost=broker_cost)

    elif cmd == "update":
        update_ema_status(state)

    elif cmd == "history":
        history(state)

    elif cmd == "reset":
        save_state(_default_state())
        print("  Paper trading reseteado.")

    else:
        print(f"  Comando desconocido: {cmd}")
        print("  Comandos: status, buy, sell, update, history, reset")


if __name__ == "__main__":
    main()

"""The Market Brain — one JSON file every agent reads from and writes to.

Holds cash, open positions (with the thesis and exit plan that travel with
each entry), the closed-trade journal, and the SPY benchmark anchor.
Deliberately a single flat file: the previous project died of distributed
state (silent DB failures corrupting what the agents reasoned over).
"""

from __future__ import annotations

import datetime as _dt
import json
import os

BRAIN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brain.json")


def _today() -> str:
    return _dt.date.today().isoformat()


_FRESH = {
    "spy_start": None,          # set on first run that has market data
    "positions": {},            # ticker -> position dict
    "journal": [],              # closed trades (the Outcome agent's ledger)
    "log": [],                  # every desk decision, append-only
    "briefs": [],               # every brief the desk produced + what you decided
    "history": [],              # [{date, equity, spy}] — one entry per day, for the chart
    "prices": {},               # last-known prices cache (dashboard marks)
    "prices_as_of": None,
    "macro": None,              # latest macro view {signal, note, regime, as_of}
    "last_scan": None,          # Scout's latest sweep {at, scanned, setups}
    "last_check": None,         # Sentinel's latest review {at, positions, flagged}
}


def load(cfg: dict) -> dict:
    if os.path.exists(BRAIN_PATH):
        with open(BRAIN_PATH) as f:
            brain = json.load(f)
        for key, default in _FRESH.items():  # upgrade older brains in place
            brain.setdefault(key, json.loads(json.dumps(default)))
        return brain
    brain = {
        "created": _today(),
        "starting_cash": cfg["starting_cash"],
        "cash": cfg["starting_cash"],
    }
    brain.update(json.loads(json.dumps(_FRESH)))
    return brain


def save(brain: dict) -> None:
    # Atomic write: the dashboard server may read this file at any moment.
    tmp = BRAIN_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(brain, f, indent=2)
    os.replace(tmp, BRAIN_PATH)


def record_history(brain: dict, equity: float, spy: float | None) -> None:
    today = _today()
    brain["history"] = [h for h in brain["history"] if h["date"] != today]
    brain["history"].append({"date": today, "equity": round(equity, 2),
                             "spy": spy})


def log(brain: dict, msg: str) -> None:
    brain["log"].append({"date": _today(), "msg": msg})


def equity(brain: dict, prices: dict[str, float]) -> float:
    total = brain["cash"]
    for t, pos in brain["positions"].items():
        total += pos["shares"] * prices.get(t, pos["entry_price"])
    return round(total, 2)


def open_position(brain: dict, ticker: str, shares: int, price: float,
                  stop: float, target: float, thesis: str, conviction: int,
                  spy: float | None) -> None:
    cost = round(shares * price, 2)
    brain["cash"] = round(brain["cash"] - cost, 2)
    brain["positions"][ticker] = {
        "shares": shares,
        "entry_price": price,
        "entry_date": _today(),
        "stop": stop,
        "target": target,
        "thesis": thesis,
        "conviction": conviction,
        "spy_entry": spy,
    }
    log(brain, f"BUY {shares} {ticker} @ {price} (stop {stop}, target {target})")


def close_position(brain: dict, ticker: str, shares_to_sell: int, price: float,
                   reason: str, spy: float | None) -> dict:
    """Sell all or part of a position; returns the journal entry (Outcome agent)."""
    pos = brain["positions"][ticker]
    price = round(price, 2)
    shares_to_sell = min(shares_to_sell, pos["shares"])
    proceeds = round(shares_to_sell * price, 2)
    brain["cash"] = round(brain["cash"] + proceeds, 2)

    pnl = round((price - pos["entry_price"]) * shares_to_sell, 2)
    pnl_pct = round((price / pos["entry_price"] - 1) * 100, 2)
    spy_pct = None
    if spy and pos.get("spy_entry"):
        spy_pct = round((spy / pos["spy_entry"] - 1) * 100, 2)
    alpha = round(pnl_pct - spy_pct, 2) if spy_pct is not None else None

    entry = {
        "ticker": ticker,
        "shares": shares_to_sell,
        "entry_price": pos["entry_price"],
        "exit_price": price,
        "entry_date": pos["entry_date"],
        "exit_date": _today(),
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "spy_pct_same_window": spy_pct,
        "alpha": alpha,
        "reason": reason,
        "thesis": pos["thesis"],
        "partial": shares_to_sell < pos["shares"],
    }
    brain["journal"].append(entry)

    pos["shares"] -= shares_to_sell
    if pos["shares"] <= 0:
        del brain["positions"][ticker]
    verb = "TRIM" if entry["partial"] else "SELL"
    log(brain, f"{verb} {shares_to_sell} {ticker} @ {price} ({reason}, P&L {pnl_pct:+.1f}%)")
    return entry

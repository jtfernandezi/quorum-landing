#!/usr/bin/env python3
"""Quorum desk — 13-agent paper-trading MVP.

One process, one brain file, one LLM call per brief. You approve every trade.

  python3 quorum.py scan        Scout finds setups -> opening briefs -> [B]uy / [P]ass
  python3 quorum.py brief NVDA  Run the full desk on one ticker
  python3 quorum.py check       Sentinel reviews open positions -> [T]rim / [H]old / [E]xit
  python3 quorum.py portfolio   Positions, P&L, benchmark vs SPY
  python3 quorum.py journal     Outcome agent's closed-trade ledger
  python3 quorum.py serve       Dashboard at http://127.0.0.1:4400 (briefs + buttons)

Flags: --dry (render only, save nothing)   --queue (save briefs, don't prompt —
decide later on the dashboard)   --no-llm (deterministic Strategist)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")

import agents
import brain as brainlib
import data as datalib

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
DASHBOARD_PATH = os.path.join(HERE, "dashboard.html")

# Which agent is working right now — the dashboard floor animates the real
# pipeline from this, so it must only ever hold truthful values.
STAGE = {"agent": None}


def _stage(agent: str | None) -> None:
    STAGE["agent"] = agent

# ------------------------------------------------------------------ rendering

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
SIG_COLOR = {"bull": "\033[32m", "neutral": "\033[36m", "caution": "\033[33m", "bear": "\033[31m"}
VERDICT_COLOR = {"BUY": "\033[32m", "PASS": DIM, "HOLD": "\033[36m",
                 "TRIM": "\033[33m", "EXIT": "\033[31m"}
ICON = {"scout": "🔭", "fundamental": "📈", "technical": "📊", "sentiment": "📰",
        "macro": "⚖️ ", "strategist": "🧠", "backtest": "🧪", "risk": "🛡️ ",
        "execution": "⚡", "portfolio": "🧭", "earnings": "📅", "sentinel": "👁️ ",
        "outcome": "📒"}
RULE = "─" * 76


def badge(sig: str) -> str:
    return f'{SIG_COLOR.get(sig, "")}[{sig.upper():^7}]{RESET}'


def agent_row(key: str, name: str, note: str, sig: str | None = None) -> None:
    tail = f"  {badge(sig)}" if sig else ""
    print(f'  {ICON[key]} {BOLD}{name:<12}{RESET} {note}{tail}')


def render_brief(desk: dict) -> None:
    p, v, risk = desk["packet"], desk["verdict"], desk.get("risk")
    mode = p["mode"]
    title = "OPENING BRIEF" if mode == "opening" else "POSITION UPDATE"
    print(f'\n{BOLD}┌{RULE}{RESET}')
    print(f'{BOLD}│ {title} · {p["ticker"]} · ${p["analysts"]["technical"]["data"]["price"]}'
          f'  {DIM}({p["as_of"]}){RESET}')
    print(f'{BOLD}├{RULE}{RESET}')
    if mode == "opening":
        agent_row("scout", "Scout", p["scout_reason"])
    else:
        pos = p["position"]
        pnl = (p["analysts"]["technical"]["data"]["price"] / pos["entry_price"] - 1) * 100
        agent_row("sentinel", "Sentinel",
                  f'{pos["shares"]} sh @ {pos["entry_price"]} ({pnl:+.1f}%) — '
                  + ("; ".join(t["msg"] for t in p["sentinel_triggers"]) or "thesis intact"))
    for key in ("fundamental", "technical", "macro", "earnings", "backtest"):
        a = p["analysts"][key]
        agent_row(key, key.capitalize(), a["note"], a["signal"])
    agent_row("sentiment", "Sentiment", v["sentiment_note"], v["sentiment_signal"])
    print(f'{BOLD}├{RULE}{RESET}')
    vc = VERDICT_COLOR.get(v["verdict"], "")
    print(f'  {ICON["strategist"]} {BOLD}Strategist{RESET}  '
          f'{vc}{BOLD}{v["verdict"]}{RESET} · {v["conviction"]}% conviction — {v["summary"]}')
    for line in v["bull_case"]:
        print(f'     {SIG_COLOR["bull"]}▲{RESET} {line}')
    for line in v["bear_case"]:
        print(f'     {SIG_COLOR["bear"]}▼{RESET} {line}')
    if risk:
        if risk["veto"]:
            print(f'  {ICON["risk"]}{BOLD}Risk{RESET}        '
                  f'{SIG_COLOR["bear"]}{BOLD}VETO{RESET} — {risk["veto"]}')
        else:
            print(f'  {ICON["risk"]}{BOLD}Risk{RESET}        {risk["note"]}')
    elif mode == "update":
        pos = p["position"]
        print(f'  {ICON["risk"]}{BOLD}Risk{RESET}        '
              f'exit plan: stop {pos["stop"]} · target {pos["target"]}')
    print(f'{BOLD}└{RULE}{RESET}')


# --------------------------------------------------------------- desk pipeline

def run_desk(ticker: str, cfg: dict, brain: dict, mode: str, use_llm: bool,
             hist=None, scout_reason: str | None = None,
             macro_view: tuple | None = None) -> dict | None:
    """Runs the analyst panel + Strategist on one ticker. Returns the desk packet."""
    _stage("technical")
    if hist is None:
        hist = datalib.history(ticker)
    if hist is None:
        print(f'  {DIM}{ticker}: no usable price history — skipped{RESET}')
        return None
    snap = datalib.snapshot(ticker, hist)
    _stage("fundamental")
    fund = datalib.fundamentals(ticker)
    _stage("earnings")
    days = datalib.days_to_earnings(ticker)
    if macro_view is None:
        _stage("macro")
        macro_view = agents.macro_agent(datalib.macro_data())
    m_sig, m_note, regime = macro_view

    _stage("backtest")
    f_sig, f_note = agents.fundamental_agent(fund)
    t_sig, t_note = agents.technical_agent(snap)
    e_sig, e_note = agents.earnings_agent(days)
    b_sig, b_note = agents.backtest_agent(hist)

    _stage("sentiment")
    heads = datalib.headlines(ticker)
    packet = {
        "mode": mode,
        "ticker": ticker,
        "as_of": _dt.date.today().isoformat(),
        "analysts": {
            "fundamental": {"signal": f_sig, "note": f_note, "data": fund},
            "technical": {"signal": t_sig, "note": t_note, "data": snap},
            "macro": {"signal": m_sig, "note": m_note},
            "earnings": {"signal": e_sig, "note": e_note},
            "backtest": {"signal": b_sig, "note": b_note},
        },
        "headlines": heads,
    }
    if mode == "opening":
        packet["scout_reason"] = scout_reason or "manual request"
    else:
        pos = brain["positions"][ticker]
        packet["position"] = dict(pos)
        packet["sentinel_triggers"] = agents.sentinel_agent(pos, snap, days)

    _stage("strategist")
    verdict = agents.strategist_agent(packet, cfg, use_llm=use_llm)

    risk = None
    if mode == "opening":
        _stage("risk")
        prices = {t: p["entry_price"] for t, p in brain["positions"].items()}
        prices[ticker] = snap["price"]
        equity = brainlib.equity(brain, prices)
        risk = agents.risk_agent(cfg, brain, equity, snap["price"], snap["atr14"],
                                 verdict["conviction"], regime)
    return {"packet": packet, "verdict": verdict, "risk": risk, "snap": snap,
            "macro_view": macro_view}


# --------------------------------------------------------- briefs (dashboard feed)

def save_brief(brain: dict, desk: dict, status: str) -> dict:
    """Persists a brief to the brain so the dashboard can render (and decide) it."""
    p, v = desk["packet"], desk["verdict"]
    ticker = p["ticker"]
    for b in brain["briefs"]:  # a fresh brief supersedes older pending ones
        if b["ticker"] == ticker and b["status"] in ("pending", "vetoed"):
            b["status"] = "expired"
    analysts = {k: {"signal": a["signal"], "note": a["note"]}
                for k, a in p["analysts"].items()}
    analysts["sentiment"] = {"signal": v["sentiment_signal"], "note": v["sentiment_note"]}
    brief = {
        "id": f'{ticker}-{int(time.time() * 1000)}',
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "mode": p["mode"],
        "ticker": ticker,
        "price": desk["snap"]["price"],
        "scout_reason": p.get("scout_reason"),
        "sentinel_triggers": p.get("sentinel_triggers"),
        "position": p.get("position"),
        "analysts": analysts,
        "verdict": {k: v[k] for k in ("verdict", "conviction", "summary",
                                      "bull_case", "bear_case", "source")},
        "risk": desk.get("risk"),
        "status": status,          # pending | vetoed | decided | expired
        "decision": None,
        "decided_at": None,
        "fill_price": None,
    }
    brain["briefs"].append(brief)
    brain["briefs"] = brain["briefs"][-60:]
    return brief


def mark_decided(brain: dict, brief: dict, decision: str, fill_price: float | None) -> None:
    brief.update(status="decided", decision=decision, fill_price=fill_price,
                 decided_at=_dt.datetime.now().isoformat(timespec="seconds"))


def refresh_marks(brain: dict) -> None:
    """Updates the price cache + daily equity/SPY history point (chart data)."""
    tickers = list(brain["positions"]) + ["SPY"]
    prices = datalib.last_prices(tickers)
    if prices:
        brain["prices"].update(prices)
        brain["prices_as_of"] = _dt.datetime.now().isoformat(timespec="seconds")
    spy = brain["prices"].get("SPY")
    if brain.get("spy_start") is None and spy:
        brain["spy_start"] = spy
    equity = brainlib.equity(brain, brain["prices"])
    brainlib.record_history(brain, equity, spy)


def remember_macro(brain: dict, macro_view: tuple) -> None:
    sig, note, regime = macro_view
    brain["macro"] = {"signal": sig, "note": note, "regime": regime,
                      "as_of": _dt.datetime.now().isoformat(timespec="seconds")}


# ---------------------------------------------------------- execution (agent 9)

def execute_buy(brain: dict, ticker: str, shares: int, price: float,
                stop: float, target: float, thesis: str, conviction: int) -> None:
    brainlib.open_position(brain, ticker, shares, price, stop, target,
                           thesis=thesis, conviction=conviction,
                           spy=datalib.spy_price())
    brainlib.save(brain)
    print(f'  {ICON["execution"]} {BOLD}Execution{RESET}   filled {shares} '
          f'{ticker} @ {price} (paper) — cash ${brain["cash"]:,.0f}')


def execute_sell(brain: dict, ticker: str, shares: int, price: float, reason: str) -> None:
    price = round(price, 2)
    entry = brainlib.close_position(brain, ticker, shares, price, reason,
                                    spy=datalib.spy_price())
    brainlib.save(brain)
    alpha = f' · alpha vs SPY {entry["alpha"]:+.1f}%' if entry["alpha"] is not None else ""
    print(f'  {ICON["execution"]} {BOLD}Execution{RESET}   sold {shares} {ticker} '
          f'@ {price} (paper) — P&L {entry["pnl_pct"]:+.1f}%{alpha}')


def decide_brief(cfg: dict, brain: dict, brief: dict, action: str) -> tuple[bool, str]:
    """Executes a decision on a persisted brief (used by the dashboard server)."""
    ticker = brief["ticker"]
    if brief["status"] not in ("pending", "vetoed"):
        return False, f'brief already {brief["status"]}'
    fresh = datalib.last_prices([ticker]).get(ticker) or brief["price"]

    if brief["mode"] == "opening":
        if action == "pass":
            brainlib.log(brain, f'PASS on {ticker} (dashboard)')
            mark_decided(brain, brief, "pass", None)
            return True, f"passed on {ticker}"
        if action != "buy":
            return False, f'"{action}" is not valid for an opening brief'
        if brief["status"] == "vetoed":
            return False, f'Risk veto stands: {brief["risk"]["veto"]}'
        if ticker in brain["positions"]:
            return False, f"{ticker} is already held"
        risk = brief["risk"]
        shares = min(risk["shares"], int(brain["cash"] // fresh))
        if shares < 1:
            return False, "not enough cash at the current price"
        execute_buy(brain, ticker, shares, fresh, risk["stop"], risk["target"],
                    brief["verdict"]["summary"], brief["verdict"]["conviction"])
        mark_decided(brain, brief, "buy", fresh)
        return True, f"bought {shares} {ticker} @ {fresh}"

    # update brief
    pos = brain["positions"].get(ticker)
    if not pos:
        return False, f"no open position in {ticker} anymore"
    if action == "hold":
        brainlib.log(brain, f'HOLD {ticker} (dashboard)')
        mark_decided(brain, brief, "hold", None)
        return True, f"holding {ticker}"
    if action == "trim":
        third = max(1, pos["shares"] // 3)
        execute_sell(brain, ticker, third, fresh, "user trim")
        mark_decided(brain, brief, "trim", fresh)
        return True, f"trimmed {third} {ticker} @ {fresh}"
    if action == "exit":
        shares = pos["shares"]
        execute_sell(brain, ticker, shares, fresh, "user exit")
        mark_decided(brain, brief, "exit", fresh)
        return True, f"exited {shares} {ticker} @ {fresh}"
    return False, f'"{action}" is not valid for a position update'


def ask(options: dict[str, str]) -> str:
    """options: key letter -> action name. Returns the action name."""
    legend = "  ".join(f'[{k.upper()}]{v[1:]}' for k, v in options.items())
    while True:
        try:
            choice = input(f'  {legend} > ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return list(options.values())[-1]  # default to the safest (last) option
        if choice in options:
            return options[choice]
        print(f'  {DIM}choose one of: {", ".join(options)}{RESET}')


# ------------------------------------------------------------------- commands

def cmd_scan(args, cfg, brain):
    print(f'\n{ICON["scout"]} {BOLD}Scout{RESET} scanning {len(cfg["universe"])} tickers…')
    _stage("macro")
    macro_view = agents.macro_agent(datalib.macro_data())
    remember_macro(brain, macro_view)
    print(f'{ICON["macro"]}{BOLD}Macro{RESET} {macro_view[1]}  {badge(macro_view[0])}')
    _stage("scout")
    histories = datalib.batch_history([t for t in cfg["universe"]
                                       if t not in brain["positions"]])
    candidates = agents.scout_agent(histories, exclude=brain["positions"],
                                    top_n=cfg["max_candidates_per_scan"])
    brain["last_scan"] = {   # so the dashboard team board can quote Scout
        "at": _dt.datetime.now().isoformat(timespec="seconds"),
        "scanned": len(cfg["universe"]),
        "setups": [{"ticker": c["ticker"], "reason": c["reason"]} for c in candidates],
    }
    if not candidates:
        print(f'\n{ICON["scout"]} No setups today — nothing cleared the Scout bar. '
              f'(Try "brief TICKER" to run the desk on demand.)')
        brainlib.save(brain)
        return
    print(f'{ICON["scout"]} {len(candidates)} candidate(s): '
          + ", ".join(f'{c["ticker"]} ({c["reason"]})' for c in candidates))
    for cand in candidates:
        desk = run_desk(cand["ticker"], cfg, brain, "opening", not args.no_llm,
                        hist=cand["hist"], scout_reason=cand["reason"],
                        macro_view=macro_view)
        if not desk:
            continue
        render_brief(desk)
        if args.dry:
            continue
        status = "vetoed" if desk["risk"]["veto"] else "pending"
        brief = save_brief(brain, desk, status)
        brainlib.save(brain)
        if args.queue:
            print(f'  {DIM}queued for the dashboard ({status}){RESET}')
            continue
        if status == "vetoed":
            print(f'  {DIM}Risk veto stands — no buy offered.{RESET}')
            continue
        action = ask({"b": "buy", "p": "pass"})
        if action == "buy":
            execute_buy(brain, cand["ticker"], desk["risk"]["shares"], desk["snap"]["price"],
                        desk["risk"]["stop"], desk["risk"]["target"],
                        desk["verdict"]["summary"], desk["verdict"]["conviction"])
            mark_decided(brain, brief, "buy", desk["snap"]["price"])
        else:
            brainlib.log(brain, f'PASS on {cand["ticker"]} '
                                f'(desk said {desk["verdict"]["verdict"]} '
                                f'{desk["verdict"]["conviction"]}%)')
            mark_decided(brain, brief, "pass", None)
        brainlib.save(brain)


def cmd_brief(args, cfg, brain):
    ticker = args.ticker.upper()
    mode = "update" if ticker in brain["positions"] else "opening"
    desk = run_desk(ticker, cfg, brain, mode, not args.no_llm)
    if not desk:
        return
    remember_macro(brain, desk["macro_view"])
    render_brief(desk)
    if args.dry:
        return
    if mode == "opening":
        status = "vetoed" if desk["risk"]["veto"] else "pending"
        brief = save_brief(brain, desk, status)
        brainlib.save(brain)
        if args.queue:
            print(f'  {DIM}queued for the dashboard ({status}){RESET}')
            return
        if status == "vetoed":
            print(f'  {DIM}Risk veto stands — no buy offered.{RESET}')
            return
        if ask({"b": "buy", "p": "pass"}) == "buy":
            execute_buy(brain, ticker, desk["risk"]["shares"], desk["snap"]["price"],
                        desk["risk"]["stop"], desk["risk"]["target"],
                        desk["verdict"]["summary"], desk["verdict"]["conviction"])
            mark_decided(brain, brief, "buy", desk["snap"]["price"])
        else:
            mark_decided(brain, brief, "pass", None)
        brainlib.save(brain)
    else:
        brief = save_brief(brain, desk, "pending")
        brainlib.save(brain)
        if args.queue:
            print(f'  {DIM}queued for the dashboard (pending){RESET}')
            return
        _position_action(brain, ticker, desk, brief)


def _position_action(brain, ticker, desk, brief=None):
    action = ask({"t": "trim", "h": "hold", "e": "exit"})
    price = desk["snap"]["price"]
    pos = brain["positions"][ticker]
    fill = None
    if action == "trim":
        third = max(1, pos["shares"] // 3)
        execute_sell(brain, ticker, third, price, "user trim")
        fill = price
    elif action == "exit":
        execute_sell(brain, ticker, pos["shares"], price, "user exit")
        fill = price
    else:
        brainlib.log(brain, f'HOLD {ticker} (desk said {desk["verdict"]["verdict"]})')
    if brief:
        mark_decided(brain, brief, action, fill)
    brainlib.save(brain)


def cmd_check(args, cfg, brain):
    now = _dt.datetime.now().isoformat(timespec="seconds")
    if not brain["positions"]:
        print(f'\n{ICON["sentinel"]}{BOLD}Sentinel{RESET} no open positions to watch.')
        brain["last_check"] = {"at": now, "positions": 0, "flagged": []}
        return
    n_watched = len(brain["positions"])
    flagged = []
    print(f'\n{ICON["sentinel"]}{BOLD}Sentinel{RESET} reviewing '
          f'{n_watched} open position(s)…')
    _stage("macro")
    macro_view = agents.macro_agent(datalib.macro_data())
    remember_macro(brain, macro_view)
    for ticker in list(brain["positions"]):
        _stage("sentinel")
        pos = brain["positions"][ticker]
        hist = datalib.history(ticker)
        snap = datalib.snapshot(ticker, hist) if hist is not None else None
        if not snap:
            print(f'  {DIM}{ticker}: no data — skipped{RESET}')
            continue
        days = datalib.days_to_earnings(ticker)
        triggers = agents.sentinel_agent(pos, snap, days)
        pnl = (snap["price"] / pos["entry_price"] - 1) * 100
        if not triggers:
            print(f'  {ICON["sentinel"]}{ticker:<6} {snap["price"]:>9.2f} '
                  f'({pnl:+.1f}%) — thesis intact, holding. '
                  f'{DIM}stop {pos["stop"]} · target {pos["target"]}{RESET}')
            continue
        flagged.append({"ticker": ticker, "triggers": [t["msg"] for t in triggers]})
        # Sentinel flagged a change -> the analyst panel re-evaluates (one LLM call)
        desk = run_desk(ticker, cfg, brain, "update", not args.no_llm,
                        hist=hist, macro_view=macro_view)
        if not desk:
            continue
        render_brief(desk)
        if args.dry:
            continue
        brief = save_brief(brain, desk, "pending")
        brainlib.save(brain)
        if args.queue:
            print(f'  {DIM}queued for the dashboard (pending){RESET}')
            continue
        _position_action(brain, ticker, desk, brief)
    brain["last_check"] = {"at": now, "positions": n_watched, "flagged": flagged}
    brainlib.save(brain)


def cmd_portfolio(args, cfg, brain):
    tickers = list(brain["positions"]) + ["SPY"]
    prices = datalib.last_prices(tickers)
    equity = brainlib.equity(brain, prices)
    print(f'\n{ICON["portfolio"]} {BOLD}Portfolio{RESET} (paper) — {_dt.date.today()}')
    print(RULE)
    if brain["positions"]:
        print(f'{BOLD}{"ticker":<8}{"shares":>7}{"entry":>10}{"now":>10}'
              f'{"P&L %":>9}{"stop":>9}{"target":>9}  thesis{RESET}')
        for t, pos in brain["positions"].items():
            now = prices.get(t, pos["entry_price"])
            pnl = (now / pos["entry_price"] - 1) * 100
            color = SIG_COLOR["bull"] if pnl >= 0 else SIG_COLOR["bear"]
            print(f'{t:<8}{pos["shares"]:>7}{pos["entry_price"]:>10.2f}{now:>10.2f}'
                  f'{color}{pnl:>+8.1f}%{RESET}{pos["stop"]:>9.2f}{pos["target"]:>9.2f}'
                  f'  {DIM}{pos["thesis"][:38]}{RESET}')
    else:
        print(f'{DIM}No open positions.{RESET}')
    print(RULE)
    ret = (equity / brain["starting_cash"] - 1) * 100
    line = (f'cash ${brain["cash"]:,.0f} · equity ${equity:,.0f} · '
            f'return {ret:+.2f}% since {brain["created"]}')
    spy_now = prices.get("SPY")
    if brain.get("spy_start") and spy_now:
        spy_ret = (spy_now / brain["spy_start"] - 1) * 100
        alpha = ret - spy_ret
        color = SIG_COLOR["bull"] if alpha >= 0 else SIG_COLOR["bear"]
        line += f' · SPY {spy_ret:+.2f}% · {color}alpha {alpha:+.2f}%{RESET}'
    print(line)
    for note in agents.portfolio_agent(brain, prices, equity):
        print(f'{ICON["portfolio"]} {note}')


def cmd_journal(args, cfg, brain):
    print(f'\n{ICON["outcome"]} {BOLD}Outcome{RESET} — closed-trade journal')
    print(RULE)
    if not brain["journal"]:
        print(f'{DIM}No closed trades yet.{RESET}')
        return
    for j in brain["journal"]:
        color = SIG_COLOR["bull"] if j["pnl"] >= 0 else SIG_COLOR["bear"]
        alpha = f' · alpha {j["alpha"]:+.1f}%' if j.get("alpha") is not None else ""
        tag = " (partial)" if j.get("partial") else ""
        print(f'{j["exit_date"]}  {j["ticker"]:<6} {j["shares"]:>5} sh  '
              f'{j["entry_price"]:>8.2f} → {j["exit_price"]:>8.2f}  '
              f'{color}{j["pnl_pct"]:>+6.1f}%{RESET}{alpha}  '
              f'{DIM}{j["reason"]}{tag}{RESET}')
    stats = agents.outcome_agent(brain["journal"])
    print(RULE)
    alpha = (f' · avg alpha vs SPY {stats["avg_alpha_vs_spy"]:+.2f}%'
             if stats.get("avg_alpha_vs_spy") is not None else "")
    print(f'{stats["trades"]} trades · {stats["win_rate_pct"]:.0f}% winners · '
          f'total P&L ${stats["total_pnl"]:,.0f} · avg {stats["avg_pnl_pct"]:+.2f}%{alpha}')
    print(f'{DIM}exits by reason: '
          + ", ".join(f"{r} ×{n}" for r, n in stats["by_reason"].items()) + RESET)


# ------------------------------------------------------------ dashboard server

def cmd_serve(args, cfg, brain):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    lock = threading.Lock()
    state = {"busy": None, "note": ""}
    use_llm = not args.no_llm

    print(f'{DIM}refreshing marks…{RESET}')
    refresh_marks(brain)
    brainlib.save(brain)

    def run_job(job: str):
        try:
            ns = argparse.Namespace(dry=False, queue=True, no_llm=args.no_llm, ticker=None)
            fresh = brainlib.load(cfg)
            (cmd_scan if job == "scan" else cmd_check)(ns, cfg, fresh)
            refresh_marks(fresh)
            brainlib.save(fresh)
            state["note"] = (f'{job} finished '
                             f'{_dt.datetime.now().strftime("%H:%M:%S")}')
        except Exception as e:
            state["note"] = f"{job} failed: {e}"
        finally:
            state["busy"] = None
            _stage(None)

    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, obj) -> None:
            body = json.dumps(obj, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html", "/dashboard.html"):
                try:
                    with open(DASHBOARD_PATH, "rb") as f:
                        body = f.read()
                except FileNotFoundError:
                    self._json(500, {"error": "dashboard.html missing"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/state":
                b = brainlib.load(cfg)
                self._json(200, {"brain": b, "config": cfg, "busy": state["busy"],
                                 "stage": STAGE["agent"], "note": state["note"],
                                 "live": True,
                                 "now": _dt.datetime.now().isoformat(timespec="seconds")})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self._json(400, {"ok": False, "msg": "bad request body"})
                return
            if self.path == "/api/run":
                job = body.get("job")
                if job not in ("scan", "check"):
                    self._json(400, {"ok": False, "msg": "job must be scan or check"})
                elif state["busy"]:
                    self._json(409, {"ok": False, "msg": f'{state["busy"]} already running'})
                else:
                    state["busy"] = job
                    state["note"] = f"{job} started…"
                    threading.Thread(target=run_job, args=(job,), daemon=True).start()
                    self._json(200, {"ok": True, "msg": f"{job} started"})
            elif self.path == "/api/decide":
                if state["busy"]:
                    self._json(409, {"ok": False,
                                     "msg": f'desk busy ({state["busy"]}) — try again in a moment'})
                    return
                with lock:
                    b = brainlib.load(cfg)
                    brief = next((x for x in b["briefs"] if x["id"] == body.get("id")), None)
                    if not brief:
                        self._json(404, {"ok": False, "msg": "brief not found"})
                        return
                    ok, msg = decide_brief(cfg, b, brief, body.get("action", ""))
                    if ok:
                        refresh_marks(b)
                    brainlib.save(b)
                print(f'  {ICON["execution"]} dashboard: {msg}')
                self._json(200 if ok else 409, {"ok": ok, "msg": msg})
            else:
                self._json(404, {"ok": False, "msg": "not found"})

        def log_message(self, fmt, *a):  # keep the serve terminal readable
            pass

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f'\n{BOLD}Quorum desk dashboard{RESET} → http://127.0.0.1:{args.port}')
    print(f'{DIM}Strategist: {"deterministic (--no-llm)" if args.no_llm else cfg.get("model")}'
          f' · Ctrl-C to stop{RESET}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


# ----------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(prog="quorum", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["scan", "brief", "check", "portfolio",
                                        "journal", "serve"])
    ap.add_argument("ticker", nargs="?", help="ticker (for the brief command)")
    ap.add_argument("--dry", action="store_true",
                    help="render briefs but save nothing / ask nothing")
    ap.add_argument("--queue", action="store_true",
                    help="save briefs as pending for the dashboard instead of prompting")
    ap.add_argument("--no-llm", action="store_true",
                    help="deterministic Strategist — no API call, no key needed")
    ap.add_argument("--port", type=int, default=4400, help="dashboard port (serve)")
    args = ap.parse_args()

    if args.command == "brief" and not args.ticker:
        ap.error("brief requires a ticker, e.g.: quorum.py brief NVDA")
    if (not sys.stdin.isatty() and not args.dry and not args.queue
            and args.command in ("scan", "brief", "check")):
        print(f"{DIM}(no interactive terminal — queueing briefs for the dashboard){RESET}")
        args.queue = True

    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    brain = brainlib.load(cfg)

    if args.command == "serve":
        cmd_serve(args, cfg, brain)
        return

    {"scan": cmd_scan, "brief": cmd_brief, "check": cmd_check,
     "portfolio": cmd_portfolio, "journal": cmd_journal}[args.command](args, cfg, brain)

    if not args.dry:
        refresh_marks(brain)
        brainlib.save(brain)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n(interrupted — brain saved on last completed action)")

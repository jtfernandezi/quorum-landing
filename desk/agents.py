"""The 13 agents of the Quorum desk.

Design rule (learned the hard way from the previous project): keep the
hallucination surface tiny. Twelve agents are deterministic — pure functions
over computed market data. Exactly one LLM call happens per brief: the
Strategist, which reads the verified numbers + raw headlines, plays the
Sentiment analyst, writes the bull/bear debate, and delivers the verdict.
If the LLM is unavailable, a deterministic vote stands in and says so.

Signals use the landing-page palette: bull / neutral / caution / bear.
"""

from __future__ import annotations

import json
import os
from typing import List, Literal

SIGNALS = ("bull", "neutral", "caution", "bear")


def _score_to_signal(score: float) -> str:
    if score >= 2:
        return "bull"
    if score <= -2:
        return "bear"
    if score < 0:
        return "caution"
    return "neutral"


# ---------------------------------------------------------------- 1. Scout 🔭

def scout_agent(histories: dict, exclude=(), top_n: int = 3) -> list[dict]:
    """Screens the universe for setups: breakouts, volume, momentum. Pure math."""
    from data import snapshot
    candidates = []
    for ticker, hist in histories.items():
        if ticker in exclude:
            continue
        snap = snapshot(ticker, hist)
        if not snap:
            continue
        score, reasons = 0, []
        if snap["breakout_20d"]:
            score += 2
            reasons.append("20d-high breakout")
        if (snap["volume_ratio_20d"] or 0) >= 1.5:
            score += 1
            reasons.append(f'{snap["volume_ratio_20d"]:.1f}× avg volume')
        if snap["change_1d_pct"] >= 2.5:
            score += 1
            reasons.append(f'+{snap["change_1d_pct"]:.1f}% today')
        if snap["sma50"] and snap["sma200"] and snap["price"] > snap["sma50"] > snap["sma200"]:
            score += 1
            reasons.append("uptrend (price > 50d > 200d)")
        if score >= 3:
            candidates.append({"ticker": ticker, "score": score,
                               "reason": ", ".join(reasons), "snap": snap, "hist": hist})
    candidates.sort(key=lambda c: -c["score"])
    return candidates[:top_n]


# ---------------------------------------------------------- 2. Fundamental 📈

def fundamental_agent(fund: dict) -> tuple[str, str]:
    if not fund:
        return "neutral", "No fundamental data available."
    score, notes = 0, []
    pe = fund.get("forwardPE") or fund.get("trailingPE")
    if pe:
        if pe < 18:
            score += 1
            notes.append(f"fwd P/E {pe:.0f} undemanding")
        elif pe > 45:
            score -= 1
            notes.append(f"fwd P/E {pe:.0f} rich")
        else:
            notes.append(f"fwd P/E {pe:.0f}")
    growth = fund.get("revenueGrowth")
    if growth is not None:
        if growth > 0.15:
            score += 1
        elif growth < 0:
            score -= 1
        notes.append(f"revenue {growth * 100:+.0f}% y/y")
    margins = fund.get("profitMargins")
    if margins is not None:
        if margins > 0.20:
            score += 1
            notes.append(f"{margins * 100:.0f}% net margins")
        elif margins < 0.05:
            score -= 1
            notes.append(f"thin {margins * 100:.0f}% margins")
    return _score_to_signal(score), ("; ".join(notes) or "Sparse data.")


# ------------------------------------------------------------ 3. Technical 📊

def technical_agent(snap: dict) -> tuple[str, str]:
    score, notes = 0, []
    price = snap["price"]
    if snap["sma50"]:
        score += 1 if price > snap["sma50"] else -1
    if snap["sma200"]:
        score += 1 if price > snap["sma200"] else -1
    trend = []
    if snap["sma50"] and price > snap["sma50"]:
        trend.append("50d")
    if snap["sma200"] and price > snap["sma200"]:
        trend.append("200d")
    notes.append("above " + "/".join(trend) if trend else "below key moving averages")
    if snap["breakout_20d"]:
        score += 1
        notes.append(f'20d breakout on {snap["volume_ratio_20d"]:.1f}× volume')
    rsi = snap["rsi14"]
    if rsi is not None:
        if rsi > 75:
            score -= 1
            notes.append(f"RSI {rsi:.0f} stretched")
        elif rsi < 30:
            notes.append(f"RSI {rsi:.0f} oversold")
        else:
            notes.append(f"RSI {rsi:.0f}")
    notes.append(f'{snap["pct_from_52w_high"]:+.0f}% vs 52w high')
    return _score_to_signal(score), "; ".join(notes)


# ----------------------------------------------------------------- 5. Macro ⚖️

def macro_agent(macro: dict) -> tuple[str, str, str]:
    """Returns (signal, note, regime) — regime feeds the Risk agent."""
    if not macro.get("spy"):
        return "neutral", "No market data.", "neutral"
    spy, sma50, sma200 = macro["spy"], macro.get("spy_sma50"), macro.get("spy_sma200")
    vix = macro.get("vix")
    above50 = sma50 and spy > sma50
    above200 = sma200 and spy > sma200
    parts = [f"SPY {'above' if above50 else 'below'} 50d"]
    if sma200:
        parts.append(f"{'above' if above200 else 'below'} 200d")
    if vix is not None:
        parts.append(f"VIX {vix:.0f}")
    note = ", ".join(parts)
    if (sma200 and not above200) or (vix is not None and vix > 28):
        return "bear", f"Risk-off: {note}", "risk-off"
    if not above50 or (vix is not None and vix > 20):
        return "caution", f"Mixed tape: {note}", "neutral"
    return "bull", f"Risk-on: {note}", "risk-on"


# -------------------------------------------------------------- 11. Earnings 📅

def earnings_agent(days: int | None) -> tuple[str, str]:
    if days is None:
        return "neutral", "No earnings date on the calendar."
    if days <= 7:
        return "caution", f"Earnings in {days}d — binary event risk."
    return "neutral", f"Next earnings in ~{days}d — clear runway."


# -------------------------------------------------------------- 7. Backtest 🧪

def backtest_agent(hist) -> tuple[str, str]:
    """Replays the Scout entry setup over this ticker's own history.
    Honest stats: reports the sample size, admits when it's too small."""
    close, vol = hist["Close"], hist["Volume"]
    high20 = close.rolling(20).max().shift(1)
    vol_avg = vol.rolling(20).mean().shift(1)
    setup_days = (close > high20) & (vol > 1.5 * vol_avg)
    fwd_20d = (close.shift(-20) / close - 1)
    returns = fwd_20d[setup_days].dropna()
    n = len(returns)
    if n < 5:
        return "neutral", f"Only {n} similar setups in 2y — not enough history to judge."
    win = float((returns > 0).mean()) * 100
    avg = float(returns.mean()) * 100
    if avg < 0:
        sig = "caution"
    elif win >= 55 and avg > 1:
        sig = "bull"
    else:
        sig = "neutral"
    return sig, f"{n} similar setups in 2y: {win:.0f}% positive after 20d, avg {avg:+.1f}%."


# ------------------------------------------------------------------ 8. Risk 🛡️

def risk_agent(cfg: dict, brain: dict, equity: float, price: float,
               atr: float | None, conviction: int, regime: str) -> dict:
    """Pure rules: sizing, stop, target, and the veto. No opinions, no LLM."""
    if not atr or atr <= 0:
        atr = max(price * 0.02, 0.01)  # conservative fallback: 2% daily range
    stop = round(price - cfg["stop_atr_mult"] * atr, 2)
    target = round(price + cfg["target_atr_mult"] * atr, 2)
    per_share_risk = price - stop

    risk_dollars = equity * cfg["risk_per_trade_pct"] / 100
    by_risk = int(risk_dollars // per_share_risk)
    by_value = int((equity * cfg["max_position_pct"] / 100) // price)
    free_cash = brain["cash"] - equity * cfg["cash_floor_pct"] / 100
    by_cash = int(max(0, free_cash) // price)
    shares = max(0, min(by_risk, by_value, by_cash))

    veto = None
    if len(brain["positions"]) >= cfg["max_positions"]:
        veto = f'desk is at max open positions ({cfg["max_positions"]})'
    elif shares < 1:
        veto = "no room inside risk limits (cash floor / position cap)"
    elif regime == "risk-off" and conviction < 65:
        veto = "macro risk-off and conviction below 65 — sit this one out"

    size = round(shares * price, 2)
    note = (f"size ${size:,.0f} ({size / equity * 100:.1f}% of equity), "
            f"stop {stop} ({(stop / price - 1) * 100:.1f}%), target {target} "
            f"(risking {cfg['risk_per_trade_pct']:.1f}% of equity)")
    return {"shares": shares, "size": size, "stop": stop, "target": target,
            "veto": veto, "note": note}


# -------------------------------------------------------------- 12. Sentinel 👁️

def sentinel_agent(pos: dict, snap: dict, days_to_earnings: int | None) -> list[dict]:
    """Watches an open position; returns triggers (empty list = thesis intact)."""
    triggers = []
    price = snap["price"]
    if price <= pos["stop"]:
        triggers.append({"level": "exit", "msg": f'stop {pos["stop"]} breached (price {price})'})
    if price >= pos["target"]:
        triggers.append({"level": "trim", "msg": f'profit target {pos["target"]} reached (price {price})'})
    if snap["sma50"] and price < snap["sma50"] and (snap["rsi14"] or 50) < 45:
        triggers.append({"level": "caution",
                         "msg": f'trend deteriorating: below 50d, RSI {snap["rsi14"]:.0f}'})
    if days_to_earnings is not None and days_to_earnings <= 3:
        triggers.append({"level": "caution", "msg": f"earnings in {days_to_earnings}d"})
    return triggers


# ----------------------------------------------- 6. Strategist 🧠 (+ 4. Sentiment 📰)

STRATEGIST_SYSTEM = """You are the Strategist Agent on Quorum, a disciplined AI trading desk.
You receive one JSON packet per brief containing VERIFIED, machine-computed market data
from the desk's analyst agents (fundamental, technical, macro, earnings, backtest) plus
raw news headlines.

Your job:
1. Play the Sentiment analyst: read the headlines and produce sentiment_signal
   (bull/neutral/caution/bear) plus a one-line sentiment_note. No headlines => "neutral".
2. Build the strongest honest bull case and bear case (2-3 short bullets each). Every
   bullet must be grounded in the data or headlines in the packet — never invent numbers,
   events, or facts, and do not rely on memorized knowledge about the company.
3. Deliver a verdict with calibrated conviction (0-100, where 50 = coin flip):
   - mode "opening": verdict is BUY or PASS. Be selective — most candidates deserve PASS.
     Only BUY when the evidence lines up across analysts.
   - mode "update": verdict is HOLD, TRIM, or EXIT for the open position in the packet.
     Respect the original thesis: EXIT when it is broken, TRIM to bank gains when the
     target is reached or evidence weakens, HOLD when the thesis is intact.
4. summary: one plain sentence a busy human reads first.

Style: terse, concrete, numbers over adjectives. This desk informs — the human decides."""

try:
    from openai import OpenAI
    from pydantic import BaseModel

    class DeskVerdict(BaseModel):
        sentiment_signal: Literal["bull", "neutral", "caution", "bear"]
        sentiment_note: str
        bull_case: List[str]
        bear_case: List[str]
        verdict: Literal["BUY", "PASS", "HOLD", "TRIM", "EXIT"]
        conviction: int
        summary: str

    _HAVE_SDK = True
except ImportError:  # desk still works without the SDK (deterministic mode)
    _HAVE_SDK = False

_client = None


def _llm_verdict(packet: dict, cfg: dict) -> dict:
    global _client
    if _client is None:
        _client = OpenAI()
    resp = _client.beta.chat.completions.parse(
        model=cfg.get("model", "gpt-4o"),
        messages=[
            {"role": "system", "content": STRATEGIST_SYSTEM},
            {"role": "user", "content": json.dumps(packet, default=str)},
        ],
        response_format=DeskVerdict,
    )
    choice = resp.choices[0]
    if choice.finish_reason == "refusal" or choice.message.parsed is None:
        raise RuntimeError("Strategist returned no verdict")
    out = choice.message.parsed.model_dump()
    out["conviction"] = max(0, min(100, out["conviction"]))
    allowed = {"opening": {"BUY", "PASS"}, "update": {"HOLD", "TRIM", "EXIT"}}[packet["mode"]]
    if out["verdict"] not in allowed:
        out["verdict"] = "PASS" if packet["mode"] == "opening" else "HOLD"
    out["source"] = "strategist"
    return out


def _vote_verdict(packet: dict) -> dict:
    """Deterministic fallback: weighted vote across the analyst signals."""
    weights = {"bull": 1.0, "neutral": 0.0, "caution": -0.5, "bear": -1.0}
    score = sum(weights.get(v["signal"], 0.0) for v in packet["analysts"].values())
    bull = [f'{n}: {v["note"]}' for n, v in packet["analysts"].items()
            if weights.get(v["signal"], 0) > 0] or ["No analyst is outright bullish."]
    bear = [f'{n}: {v["note"]}' for n, v in packet["analysts"].items()
            if weights.get(v["signal"], 0) < 0] or ["No analyst is outright bearish."]
    conviction = int(max(5, min(95, round(50 + 12 * score))))

    if packet["mode"] == "opening":
        verdict = "BUY" if conviction >= 60 else "PASS"
    else:
        levels = {t["level"] for t in packet.get("sentinel_triggers", [])}
        if "exit" in levels or score <= -2:
            verdict = "EXIT"
        elif "trim" in levels or score < 0:
            verdict = "TRIM"
        else:
            verdict = "HOLD"
    return {
        "sentiment_signal": "neutral",
        "sentiment_note": "Headlines not analyzed (deterministic mode).",
        "bull_case": bull, "bear_case": bear,
        "verdict": verdict, "conviction": conviction,
        "summary": f"Deterministic desk vote (score {score:+.1f}) — no LLM consulted.",
        "source": "vote",
    }


def strategist_agent(packet: dict, cfg: dict, use_llm: bool = True) -> dict:
    if use_llm and _HAVE_SDK:
        try:
            return _llm_verdict(packet, cfg)
        except Exception as e:
            reason = ("no API credentials -- set OPENAI_API_KEY"
                      if "authentication" in str(e).lower() or "api_key" in str(e).lower()
                      else type(e).__name__)
            out = _vote_verdict(packet)
            out["summary"] += f" (Strategist LLM unavailable: {reason})"
            return out
    return _vote_verdict(packet)


# -------------------------------------------------------------- 10. Portfolio 🧭

def portfolio_agent(brain: dict, prices: dict[str, float], equity: float) -> list[str]:
    notes = []
    cash_pct = brain["cash"] / equity * 100 if equity else 100
    notes.append(f"{len(brain['positions'])} open positions, {cash_pct:.0f}% cash")
    for t, pos in brain["positions"].items():
        weight = pos["shares"] * prices.get(t, pos["entry_price"]) / equity * 100
        if weight > 20:
            notes.append(f"⚠ {t} is {weight:.0f}% of equity — concentrated")
    if cash_pct > 80 and brain["positions"]:
        notes.append("high cash drag — the desk is barely deployed")
    return notes


# ---------------------------------------------------------------- 13. Outcome 📒

def outcome_agent(journal: list[dict]) -> dict:
    """Aggregates the closed-trade ledger into honest stats."""
    if not journal:
        return {}
    wins = [j for j in journal if j["pnl"] > 0]
    alphas = [j["alpha"] for j in journal if j.get("alpha") is not None]
    return {
        "trades": len(journal),
        "win_rate_pct": round(len(wins) / len(journal) * 100, 1),
        "total_pnl": round(sum(j["pnl"] for j in journal), 2),
        "avg_pnl_pct": round(sum(j["pnl_pct"] for j in journal) / len(journal), 2),
        "avg_alpha_vs_spy": round(sum(alphas) / len(alphas), 2) if alphas else None,
        "by_reason": {r: sum(1 for j in journal if j["reason"] == r)
                      for r in {j["reason"] for j in journal}},
    }

# Agents 9 (Execution ⚡) lives in quorum.py's execute functions — it is the only
# agent allowed to touch cash, and only after the human approves.

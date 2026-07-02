# Quorum Desk — MVP

The working prototype behind the [Quorum landing page](../index.html): a 13-agent
paper-trading desk with one shared Market Brain. **Paper trading only. You approve
every trade. Not financial advice.**

## Design in one paragraph

The previous attempt at this idea (stocks-investment-agent) lost to complexity, not
to bad ideas: a distributed n8n + DB pipeline silently corrupted the data its LLMs
reasoned over, and they hallucinated on top of it. This MVP inverts that: **one local
process, one JSON brain file, deterministic data, and exactly one LLM call per brief.**
Twelve of the thirteen agents are pure functions over computed market data (yfinance).
Only the Strategist calls Claude — it receives verified numbers + raw headlines,
plays the Sentiment analyst, writes the bull/bear debate, and returns a structured
verdict. If the API is unreachable, a deterministic vote stands in and says so.

## The 13 agents

| Agent | Type | What it does here |
|---|---|---|
| 🔭 Scout | deterministic | Screens the universe: 20d breakouts, volume surges, momentum, trend |
| 📈 Fundamental | deterministic | P/E, revenue growth, margins from Yahoo fundamentals |
| 📊 Technical | deterministic | SMA 20/50/200, RSI-14, breakout, distance from 52w high |
| 📰 Sentiment | LLM (inside Strategist call) | Reads raw headlines, emits signal + one-liner |
| ⚖️ Macro | deterministic | SPY vs 50/200d + VIX → risk-on / neutral / risk-off regime |
| 🧠 Strategist | **the one LLM call** | Bull case, bear case, verdict, calibrated conviction |
| 🧪 Backtest | deterministic | Replays the Scout setup on this ticker's own 2y history (honest n) |
| 🛡️ Risk | deterministic | ATR-based sizing/stop/target, position & cash caps, **veto power** |
| ⚡ Execution | deterministic | Paper fill at last price — only after *you* approve |
| 🧭 Portfolio | deterministic | Allocation, concentration and cash-drag warnings |
| 📅 Earnings | deterministic | Days to next earnings; flags binary-event risk |
| 👁️ Sentinel | deterministic | Watches open positions: stop/target/trend/earnings triggers |
| 📒 Outcome | deterministic | Journals closed trades, win rate, alpha vs SPY per trade |

The **Market Brain** is `brain.json` — cash, positions (each carrying the thesis and
exit plan that travel with the entry), journal, decision log, SPY benchmark anchor.

## Setup

```bash
cd desk
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-…   # only needed for the Strategist LLM
```

## Use

### The dashboard (recommended)

```bash
.venv/bin/python quorum.py serve       # → http://127.0.0.1:4400
```

One page, styled like the landing site, backed by a tiny localhost-only server:

- **Run scan / Check positions** buttons kick the desk from the browser
- pending briefs render as cards — the full debate — with **[Buy] [Pass]** or
  **[Trim ⅓] [Hold] [Exit all]** buttons (fills use a fresh price at click time)
- scoreboard (equity · cash · return · SPY · **alpha**), equity-vs-SPY chart,
  positions with stop→target bars and their theses, risk-guardrail gauges,
  the Outcome journal, the decision log, and the **team board** — one card per
  specialist, each showing the latest thing that agent reported and when

If you open `dashboard.html` through a plain static server instead, it falls back
to read-only (no buttons) over `brain.json`.

### The terminal (same desk, no server)

```bash
.venv/bin/python quorum.py scan        # Scout → opening briefs → [B]uy / [P]ass
.venv/bin/python quorum.py brief NVDA  # full desk on one ticker, on demand
.venv/bin/python quorum.py check       # Sentinel → update briefs → [T]rim / [H]old / [E]xit
.venv/bin/python quorum.py portfolio   # positions, P&L, alpha vs SPY since inception
.venv/bin/python quorum.py journal     # Outcome agent's closed-trade ledger
```

Flags: `--dry` renders briefs and saves nothing; `--queue` saves briefs as pending
(decide later on the dashboard) instead of prompting; `--no-llm` uses the
deterministic Strategist (no API key needed). Both surfaces share the same brain —
a brief queued in the terminal shows up on the dashboard and vice versa.

Suggested rhythm: `scan` once a day after the close, `check` whenever you like —
Sentinel only wakes the full panel (and spends an LLM call) when something changed.

**Benchmark:** the whole point. `portfolio` shows your return vs SPY since the brain
was created; `journal` shows per-trade alpha vs SPY over the same holding window.

## Config (`config.json`)

- `model` — Strategist model (default `claude-opus-4-8`)
- `universe` — tickers Scout watches (edit freely)
- `risk_per_trade_pct` 1% · `max_position_pct` 15% · `max_positions` 6 ·
  `cash_floor_pct` 10% — the Risk agent's hard rules
- `stop_atr_mult` 2 / `target_atr_mult` 3 — the exit plan attached to every entry

To start over: delete `brain.json`.

## Deliberately not built yet (next steps)

- Trailing stops / scaling-out exit management (the README-roadmap "exit" pillar)
- The behavioral mirror (Outcome learning your override patterns)
- Real broker (Alpaca paper) behind the Execution agent
- Scheduled scans (cron) feeding the dashboard's pending queue

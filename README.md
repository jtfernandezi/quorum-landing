# Quorum

**A 13-agent paper-trading desk built on one constraint: exactly one LLM call per decision.**

Twelve of the thirteen agents are pure functions over computed market data. One agent
talks to a model. That split is the whole architecture, and it exists because the
previous version of this project failed for the opposite reason.

> **Paper trading only. No broker is connected. You approve every trade.
> Not financial advice.**

```bash
cd desk && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python quorum.py brief NVDA --no-llm     # runs with no API key
```

---

## The design problem

The predecessor to this project (`stocks-investment-agent`) was a distributed system:
n8n workflows, a hosted Postgres, LLM calls at several stages. It lost to complexity.
The pipeline silently corrupted the data its models reasoned over, and the models
hallucinated confidently on top of the corruption. Nothing threw an error. The output
looked exactly as plausible as it had when the data was clean — which is the failure
mode that makes distributed LLM pipelines genuinely dangerous rather than merely buggy.

This rebuild inverts every one of those choices:

| Predecessor | This build |
|---|---|
| Distributed n8n pipeline | One local Python process |
| Hosted Postgres | One `brain.json` file |
| LLM calls at several stages | Exactly one, in one function |
| Silent data corruption | Deterministic math, inspectable at every step |
| Failure looked like success | Degradation announces itself |

The constraint isn't minimalism for its own sake. **A single LLM call site is a single
place where hallucination can enter the system.** Everything upstream of it is
arithmetic you can verify by hand; everything downstream is a structured object with a
validated schema. That's the safety model.

## Architecture

```
yfinance ──▶ data.py ──▶ 12 deterministic agents ──┐
             (pure math)   Scout · Fundamental ·   │
                           Technical · Macro ·     ├──▶ packet ──▶ Strategist ──▶ verdict
                           Backtest · Earnings ·   │              (THE LLM call)      │
                           Sentinel · Portfolio ·  │                                  │
                           Outcome                 │                                  ▼
                                                   │                          Risk agent (veto)
             brain.json ◀── Execution ◀── YOU ◀────┴──────────────────────────────────┘
             (the Market Brain)      (approve/reject)
```

**Three properties are load-bearing:**

**1. The LLM sees verified numbers, never raw feeds.** The Strategist receives a packet
of already-computed values — RSI, ATR, SMA crossovers, days-to-earnings, regime — plus
raw headlines. It plays the sentiment analyst, writes the bull and bear case, and returns
a Pydantic-validated `DeskVerdict`. It cannot invent a price, because it is never asked
for one. Its verdict is constrained to a per-mode allowlist (`BUY`/`PASS` when opening,
`HOLD`/`TRIM`/`EXIT` when updating) and conviction is clamped to 0–100 on the way out.

**2. Degradation is loud.** If the API is unreachable, unauthenticated, or the SDK isn't
installed, `_vote_verdict()` stands in with a deterministic weighted vote across the
analyst signals — and stamps the output: *"Deterministic desk vote (score +1.5) — no LLM
consulted."* The desk never silently substitutes a weaker brain for a stronger one.
`--no-llm` makes this the default path, which is why the quickstart above needs no key.

**3. The Risk agent holds a veto the LLM cannot override.** `risk_agent()` is pure rules:
ATR-based sizing, a 1%-of-equity risk budget per trade, a 15% position cap, a 10% cash
floor, max 6 open positions. It vetoes on any breach — and vetoes a 60-conviction idea
outright in a risk-off macro regime. No amount of model enthusiasm gets past it. The
Execution agent, the only code allowed to touch cash, runs only after a human clicks.

### The honesty constraint in the UI

The dashboard's "trading floor" animates which agent is currently working. That animation
is driven by a `STAGE` dict the server updates at real pipeline steps — not a timer, not
a loop. Idle means no pulses. The comment above it in [`quorum.py`](desk/quorum.py#L37)
reads: *"the dashboard floor animates the real pipeline from this, so it must only ever
hold truthful values."*

This sounds like a small thing. It is the same principle as the loud degradation: **a
system that reasons about money should never render activity it isn't performing.** Once
you allow decorative liveness, a user can no longer distinguish a working desk from a
hung one.

## The 13 agents

| Agent | Type | Role |
|---|---|---|
| 🔭 Scout | deterministic | Screens the universe — 20d breakouts, volume surges, momentum |
| 📈 Fundamental | deterministic | P/E, revenue growth, margins |
| 📊 Technical | deterministic | SMA 20/50/200, RSI-14, breakout, distance from 52w high |
| 📰 Sentiment | *LLM* | Reads raw headlines, emits a signal (inside the Strategist call) |
| ⚖️ Macro | deterministic | SPY vs 50/200d + VIX → risk-on / neutral / risk-off |
| 🧠 Strategist | **the one LLM call** | Bull case, bear case, verdict, calibrated conviction |
| 🧪 Backtest | deterministic | Replays the Scout setup on the ticker's own 2y history |
| 🛡️ Risk | deterministic | ATR sizing, stop, target, caps — **veto power** |
| ⚡ Execution | deterministic | Paper fill at last price, only after you approve |
| 🧭 Portfolio | deterministic | Allocation, concentration, cash-drag warnings |
| 📅 Earnings | deterministic | Days to next earnings; flags binary-event risk |
| 👁️ Sentinel | deterministic | Watches open positions for stop/target/trend/earnings triggers |
| 📒 Outcome | deterministic | Journals closed trades, win rate, alpha vs SPY per trade |

The **Market Brain** is a single `brain.json`: cash, open positions (each carrying the
thesis and exit plan recorded at entry), the closed-trade journal, a decision log, and an
SPY anchor for benchmarking.

## Tech stack

**Desk:** Python 3, `yfinance`, `pandas`, `openai` (structured outputs via Pydantic),
stdlib `ThreadingHTTPServer`. No framework, no ORM, no message queue, no build step.

**Dashboard:** one hash-routed `dashboard.html` — vanilla JS, no bundler.

**Landing page:** `index.html` / `styles.css` / `script.js` — vanilla, no dependencies.
The "how it works" pipeline animation measures live DOM badge positions and rebuilds the
SVG path on resize rather than hardcoding coordinates.

## Running it

Everything below runs on your machine. The server binds `127.0.0.1` only.

```bash
cd desk
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

**Fully runnable with no credentials** (deterministic Strategist):

```bash
.venv/bin/python quorum.py brief NVDA --no-llm   # full desk on one ticker
.venv/bin/python quorum.py scan --no-llm         # Scout → briefs → [B]uy / [P]ass
.venv/bin/python quorum.py portfolio             # positions, P&L, alpha vs SPY
.venv/bin/python quorum.py journal               # closed-trade ledger
.venv/bin/python quorum.py serve                 # dashboard → http://127.0.0.1:4400
```

**Requires `OPENAI_API_KEY`** (set in your environment; never committed) — omit `--no-llm`
to route the Strategist through the model set in `config.json`.

**Requires network** — all market data comes live from Yahoo Finance via `yfinance`.
There is no cached fixture set, so the desk needs a connection even in `--no-llm` mode.

**Not included:** no broker integration (Alpaca is on the roadmap, not built), no
scheduler, no hosted deployment, no auth on the local server — it is localhost-only by
design and should stay that way.

The landing page is separate and needs nothing:

```bash
python3 -m http.server 4321 --bind 127.0.0.1
```

### Tests

```bash
cd desk && .venv/bin/python -m pytest test_desk.py -q     # 21 passed in 0.4s
```

No network and no API key — every test builds its own price series and injects it,
so the suite exercises the real indicator math without touching a provider.

## Trade-offs I'd defend

**One JSON file instead of a database.** At single-user scale, `brain.json` is atomic
enough, diffable, and inspectable in a text editor. It would not survive concurrent
writers or a year of tick data — but choosing Postgres on day one is what sank the
predecessor. The file is a deliberate ceiling, not an oversight.

**One LLM call per brief, not a multi-agent conversation.** The obvious "13 agents" design
is 13 model calls debating each other. That is more impressive in a demo and worse in
every other way: 13× the cost, 13× the latency, 13 independent hallucination surfaces, and
no way to attribute a bad decision to a specific step. Twelve deterministic agents that
produce auditable numbers, feeding one call that reasons over them, gets the same output
shape with a fraction of the risk.

**Deterministic fallback over retry-and-fail.** A trading desk that goes dark when an API
rate-limits is worse than one that degrades to a weighted vote and says so out loud.

## What I'd do differently

- **Test coverage stops at the deterministic core.** 21 tests pin the Risk agent's sizing
  and veto, `snapshot()`'s partial-bar correction, and the fallback Strategist — the places
  where a silent arithmetic error would be most expensive. The HTTP server, the brief
  lifecycle and the brain's position accounting are still uncovered.
- **`yfinance` is a single point of failure.** No caching layer and no fallback provider,
  so a Yahoo outage or schema change takes the whole desk down. A thin provider interface
  with an on-disk cache would fix both.
- **`quorum.py` is ~690 lines** and carries the CLI, the HTTP server, and the execution
  logic. The server should be its own module; `execute_buy`/`execute_sell` belong next to
  the brain.
- **Backtest honesty has a ceiling.** Replaying a setup on the ticker's own 2y history
  gives a small `n` and cannot correct for survivorship bias. It is labeled as indicative
  rather than predictive, but it is the weakest agent in the roster.
- **No structured logging.** Debugging a bad verdict means re-running the brief and
  reading stdout.

## Repo layout

```
├── index.html · styles.css · script.js   Landing page (concept marketing, vanilla)
├── desk/
│   ├── quorum.py        CLI + localhost dashboard server + execution
│   ├── agents.py        All 13 agents; the single LLM call site is _llm_verdict()
│   ├── data.py          yfinance access + pure technical math
│   ├── brain.py         Market Brain load/save/position lifecycle
│   ├── dashboard.html   Hash-routed single-file dashboard
│   ├── test_desk.py     Risk sizing/veto, partial-bar, fallback Strategist
│   └── config.json      Universe + the Risk agent's hard limits
└── CLAUDE.md            Working notes / conventions for AI-assisted sessions
```

## A note on the numbers

Every figure on the landing page is an illustrative mock-up — no real or backtested
performance is shown anywhere, deliberately. The desk's own `brain.json` (its positions
and P&L) is gitignored and never published. This is a research and decision-support tool
that proposes; a human disposes.

## Naming

"Quorum" collides with ConsenSys/JPMorgan's blockchain platform of the same name. Noted,
unresolved, and not a trademark claim.

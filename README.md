# Quorum — Landing Page

> **Your AI trading desk. One shared brain.**
> A concept marketing landing page for *Quorum* — an agentic investing product where a team of
> 13 specialized AI agents (research, technical, risk, execution, …) share a single "Market Brain"
> to find, debate, risk-check and execute trade ideas. Inspired by the multi-agent "shared brain"
> pattern (cf. [getclarion.in](https://getclarion.in/)), adapted for stock/investment trading.

⚠️ **This is a product concept / demo page.** Every number, chart, score, agent output and
testimonial on the page is an **illustrative mock-up** — not real or backtested performance.
See [Compliance notes](#compliance-notes) before publishing anything.

---

## Tech stack

- **Plain HTML + CSS + vanilla JS.** No framework, no build step, no dependencies.
- Google Fonts (Inter + JetBrains Mono) loaded via CDN.
- Everything renders from three files.

## Project structure

```
quorum-landing/
├── index.html      # All page markup / sections
├── styles.css      # Design system (CSS variables) + all component styles
├── script.js       # Agent roster data, FAQ accordion, mobile nav, email capture,
│                    #   scroll reveal, and the "How it works" signal-flow animation
├── assets/         # (empty) drop images/logos here
├── desk/           # ★ The working product MVP — a 13-agent paper-trading desk
│                    #   (Python + yfinance + one LLM call per brief + web dashboard).
│                    #   Separate world from the landing page; see desk/README.md
├── README.md       # This file
└── CLAUDE.md       # Guidance for Claude Code sessions
```

## Run it locally

Any static file server works. Simplest:

```bash
cd quorum-landing
python3 -m http.server 4321 --bind 127.0.0.1
# open http://127.0.0.1:4321
```

Alternatives: `npx serve .` · `php -S localhost:4321` · or just open `index.html` in a browser
(a server is preferred so relative paths and the fetch-free JS behave consistently).

## Page sections (top → bottom)

1. **Nav** — sticky, blurred; links + sign-in/start CTAs; mobile hamburger.
2. **Hero** — headline, lead, **email capture form**, trust micro-line, animated dashboard mock.
3. **Trust band** — security signals (scoped tokens, can't withdraw, kill switch, SOC 2, you approve).
4. **Broker strip** — broker/data-feed names.
5. **Problem** — the "you react to <1% of what moves your portfolio" framing.
6. **Pillars** — "Why a desk beats a bot": debate · Risk Agent veto · you approve.
7. **Market Brain** — shared-knowledge concept + orbiting-agents visual.
8. **Debate** — bull-vs-bear researcher debate → verdict (the signature differentiator).
9. **How it works** — 8-step pipeline (Scan → … → Monitor), laid out as a **serpentine snake**
   with an animated **signal-flow** pulse threading through the steps (see below).
10. **Agents** — grid of all 13 agents (rendered from JS).
11. **Feature deep-dives** — consensus score, backtest/paper-trade, risk guardrails.
12. **Why not one AI** — single-agent vs. the desk comparison (the Robinhood/ChatGPT wedge).
13. **Stats band**, **Testimonials** (placeholder), **Pricing** (4 tiers), **FAQ**, **Final CTA**, **Footer + disclaimer**.

## The "How it works" signal-flow animation

The 8 steps are arranged as a **serpentine snake**: row 1 runs left→right (01→04), drops straight
down to **05 (directly under 04)**, then row 2 runs right→left, ending at **08 (directly under 01)**.
A faint dashed curve loops 08 back up to 01 — the "Monitor → next Scan" feedback loop.

A glowing green **comet** sweeps that whole route on a loop, and each number badge brightens exactly
as the pulse reaches it. It's built in [`script.js`](script.js) (the `signalFlow` IIFE):

- The SVG (`#flowSvg`) overlays the steps grid. The path is **measured from the live badge
  positions** (`getBoundingClientRect`) and the `viewBox` is set to the grid's pixel size, so the
  stroke never distorts. It **recomputes on `load` and on resize**, so it re-threads correctly when
  the grid collapses to 2-col (≤980px) or 1-col (≤720px).
- Three paths: `#flowBase` (subtle connector), `#flowReturn` (faint dashed loop), `#flowComet`
  (the bright dash that travels the full loop). Same-row / same-column segments are straight lines;
  only genuinely diagonal row-changes get a gentle curve.
- **Badge sync is exact:** the script samples the path to find the length at which the comet passes
  each badge, converts it to a cycle fraction, and sets each badge's `animationDelay` (negative, so
  there's no first-frame flash). The `badgeFlow` keyframe lives in `styles.css`.
- The serpentine column-reversal is a `@media (min-width: 981px)` block in `styles.css`
  (`.steps .step:nth-child(6…9)` — note the `+1` offset because the `<svg>` is the first child).
- Respects `prefers-reduced-motion`: the comet and badge pulsing are disabled, leaving the static
  connector.

## The 13 agents

Defined in [`script.js`](script.js) as the `AGENTS` array — edit there to add/remove/reorder; the grid re-renders automatically.

| Agent | Role |
|---|---|
| Scout | Discovery — unusual volume, breakouts, catalysts |
| Fundamental | Filings, earnings, valuation |
| Technical | Chart patterns, levels, timing |
| Sentiment | News, analyst moves, social chatter |
| Macro | Rates, CPI, market regime |
| Strategist | Reconciles views into a consensus score |
| Backtest | Historical replay + paper trading |
| Risk | Position sizing, stops, circuit-breakers (veto power) |
| Execution | Routes approved orders to the broker |
| Portfolio | Allocation & rebalancing |
| Earnings | Events, dividends, calendar |
| Sentinel | Monitors open positions, flags broken theses |
| Outcome | Journals closed trades, feeds lessons back |

## Customization

| Want to change… | Where |
|---|---|
| Colors / spacing / radius | `:root` variables at the top of [`styles.css`](styles.css) |
| Product name "Quorum" | Search-replace in `index.html` (also `<title>`, logo, footer) |
| Agent list | `AGENTS` array in [`script.js`](script.js) |
| Copy / sections | [`index.html`](index.html) — each section is clearly comment-delimited |
| Email capture destination | `wireCapture()` in [`script.js`](script.js) — currently `localStorage`; swap for a real API/webhook |
| Pricing tiers | `#pricing` section in `index.html` |
| Signal-flow speed / comet length | `FORWARD_SECONDS` and `COMET_LEN` in the `signalFlow` IIFE in [`script.js`](script.js) |
| Signal-flow glow / connector subtlety | `.flow-comet` drop-shadow + `.flow-base` / `.flow-return` opacity in [`styles.css`](styles.css) |
| Step snake layout | `@media (min-width: 981px)` `.steps .step:nth-child(…)` block in [`styles.css`](styles.css) |

### Wiring up the email capture

The hero and final CTA forms validate the address client-side and persist to `localStorage`
(key `quorum_waitlist`). To make it real, replace the `localStorage` block in `wireCapture()`
with a `fetch()` POST to your backend / form service (Formspree, a serverless function, etc.).

## Compliance notes

This page markets a trading product, which is a regulated space. Before going public:

- **No real/backtested performance numbers** in public, retail-facing advertising. The SEC
  Marketing Rule treats hypothetical/backtested performance as something that generally cannot be
  shown to a mass audience. The backtest panel deliberately shows *report structure*, not returns.
- **Testimonials are placeholders.** Real ones require disclosure of client status + compensation.
- **Positioning:** the page frames Quorum as a *research/execution tool* where *you approve every
  trade* — this is the intended defensive posture. If agents "recommend" specific securities, get
  legal review (could implicate investment-adviser registration).
- **Name check:** "Quorum" may collide with ConsenSys/JPMorgan's "Quorum" blockchain — verify
  trademark availability before committing to branding.
- Keep the footer **risk disclaimer** intact and update it with counsel before launch.

## Roadmap / product ideas

> **Update:** the first working prototype now lives in [`desk/`](desk/README.md) — a local
> paper-trading desk implementing the 13 agents, the Market Brain (`brain.json`), and the
> **brief format below** (opening briefs + Sentinel-triggered position updates, with
> [Buy]/[Pass]/[Trim ⅓]/[Hold]/[Exit all] decisions on a local web dashboard). Exit management
> beyond stop/target and the behavioral mirror remain unbuilt.

Captured for context — none of this is on the landing page yet:

- **Exit management as a first-class pillar.** The entry side is well covered; exits are the bigger
  value gap. Make the exit *plan* travel with each entry (profit target(s), stop, trailing stop),
  and lead with **scaling out** (e.g. trim ⅓ at +10%, trail the rest) so "bank it vs. let it run"
  stops being all-or-nothing. Owned by the **Risk** + **Sentinel** agents.
- **The behavioral mirror.** Every time the user overrides the desk (sells when it said hold, etc.)
  is a labeled data point on their risk psychology. The **Outcome** agent learns the user's style
  (typical hold time, take-profit %, drawdown tolerance) and **quantifies what it costs or earns**
  — e.g. "your early exits left ~X% on the table." Split *preference* (adapt to it) from *bias*
  (the disposition effect — coach against it with data). Could surface as a "Coach" persona.
- Compliance caveat: personalized "sell now" prompts edge toward individualized investment advice
  (more RIA-flavored). Keep the "informs & proposes a plan you approve" framing; behavioral
  feedback is more defensible than directives.
- **The "brief" format — the core in-app UI pattern (designed, not on the landing page).** Every
  trade gets one consistent brief, used on both sides:
  - **Opening brief** — triggered by Scout discovering an opportunity. Five agents present their
    angle: Fundamental, Technical, Sentiment, Macro each give a signal badge (Bullish / Mixed /
    Caution / Bearish / Headwind). The Strategist produces a conviction score and verdict (e.g.
    *Buy · 78%*). Risk Agent shows position size, stop, and staged-entry note. User sees
    **[Buy] [Pass]** — the decision is entirely theirs.
  - **Position update brief** — triggered by Sentinel when the thesis on an open position starts
    to shift. The same analyst panel re-evaluates the position. Strategist gives an updated verdict
    (e.g. *Trim · 67% — lock ⅓, trail the rest*). Sentinel status shows "thesis softening." User
    sees **[Trim ⅓] [Hold] [Exit all]** — they can sell whenever they see fit, or ignore the brief
    entirely.
  - The symmetry is the product: *one format, one brain, both sides of the trade, user always
    decides.* Continuously surfaces good opportunities (Scout as quality-gated deal-flow feed);
    continuously watches open positions (Sentinel as the mirror image of Scout).
  - Signal badge palette: `sig-bull` (green), `sig-neutral` (teal), `sig-caution` (gold),
    `sig-bear` (red). Verdict color: green for opens, gold for partial exit suggestions.
  - When building this: keep the "informs, you decide" framing. No "SELL NOW at $X" directives.

## Status

- **Landing page:** concept demo. Single page, no backend, no analytics. Not deployed.
- **Product MVP:** working prototype in [`desk/`](desk/README.md) — paper trading only,
  runs locally, benchmarked against SPY. See its README for setup and design rationale.

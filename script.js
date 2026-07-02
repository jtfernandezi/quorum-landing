/* ===========================================================
   Quorum landing — interactivity & agent roster
   =========================================================== */

// --- The 13 agents of the trading desk ---
const AGENTS = [
  { icon: "🔭", color: "rgba(25,224,138,0.12)",  role: "Discovery",  name: "Scout Agent",        desc: "Scans your universe for unusual volume, breakouts and catalysts before they hit headlines." },
  { icon: "📈", color: "rgba(54,209,220,0.12)",  role: "Fundamentals", name: "Fundamental Agent", desc: "Reads filings, earnings and valuations to judge whether a company is actually worth owning." },
  { icon: "📊", color: "rgba(124,92,255,0.12)",  role: "Technicals", name: "Technical Agent",     desc: "Tracks chart patterns, indicators and key levels to time entries and exits." },
  { icon: "📰", color: "rgba(245,196,81,0.12)",  role: "Sentiment",  name: "Sentiment Agent",     desc: "Gauges news, analyst moves and social chatter to read the crowd — and fade it when needed." },
  { icon: "⚖️", color: "rgba(54,209,220,0.12)",  role: "Macro",      name: "Macro Agent",         desc: "Watches rates, CPI, the Fed and market regime to set the backdrop for every trade." },
  { icon: "🧠", color: "rgba(124,92,255,0.12)",  role: "Consensus",  name: "Strategist Agent",    desc: "Reconciles every view into a single conviction score with a clear bull and bear case." },
  { icon: "🧪", color: "rgba(25,224,138,0.12)",  role: "Validation", name: "Backtest Agent",      desc: "Replays each idea across history and live paper trades to prove the edge before you commit." },
  { icon: "🛡️", color: "rgba(255,92,114,0.12)",  role: "Risk",       name: "Risk Agent",          desc: "Sizes positions, sets stops and enforces your limits — and freezes the desk when they break." },
  { icon: "⚡", color: "rgba(245,196,81,0.12)",  role: "Execution",  name: "Execution Agent",     desc: "Routes approved orders to your broker and works the fill to minimize slippage." },
  { icon: "🧭", color: "rgba(54,209,220,0.12)",  role: "Portfolio",  name: "Portfolio Agent",     desc: "Keeps allocation, diversification and rebalancing aligned with your target plan." },
  { icon: "📅", color: "rgba(124,92,255,0.12)",  role: "Calendar",   name: "Earnings Agent",      desc: "Tracks earnings dates, dividends and events so you're never blindsided by a known catalyst." },
  { icon: "👁️", color: "rgba(25,224,138,0.12)",  role: "Monitoring", name: "Sentinel Agent",      desc: "Watches every open position and pings you the moment the original thesis starts to break." },
  { icon: "📒", color: "rgba(255,92,114,0.12)",  role: "Review",     name: "Outcome Agent",       desc: "Journals every closed trade, measures real performance and feeds the lessons back to the desk." },
];

(function renderAgents() {
  const grid = document.getElementById("agentGrid");
  if (!grid) return;
  grid.innerHTML = AGENTS.map(a => `
    <div class="agent reveal">
      <div class="ico" style="background:${a.color}">${a.icon}</div>
      <span class="role">${a.role}</span>
      <h3>${a.name}</h3>
      <p>${a.desc}</p>
    </div>`).join("");
})();

// --- FAQ accordion ---
document.querySelectorAll(".faq-q").forEach(btn => {
  btn.addEventListener("click", () => {
    const item = btn.closest(".faq-item");
    const open = item.classList.contains("open");
    document.querySelectorAll(".faq-item").forEach(i => i.classList.remove("open"));
    if (!open) item.classList.add("open");
  });
});

// --- Mobile nav ---
const toggle = document.getElementById("navToggle");
const links = document.getElementById("navLinks");
if (toggle) {
  toggle.addEventListener("click", () => links.classList.toggle("show"));
  links.querySelectorAll("a").forEach(a => a.addEventListener("click", () => links.classList.remove("show")));
}

// --- Email capture (client-side waitlist) ---
function wireCapture(formId, inputId) {
  const form = document.getElementById(formId);
  const input = document.getElementById(inputId);
  if (!form || !input) return;
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const email = input.value.trim();
    const valid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
    if (!valid) {
      input.focus();
      input.style.borderColor = "var(--danger)";
      input.style.boxShadow = "0 0 0 3px rgba(255,92,114,0.2)";
      return;
    }
    // Persist locally so the waitlist survives a refresh (swap for a real API later).
    try {
      const list = JSON.parse(localStorage.getItem("quorum_waitlist") || "[]");
      if (!list.includes(email)) list.push(email);
      localStorage.setItem("quorum_waitlist", JSON.stringify(list));
    } catch (_) {}
    form.innerHTML = `<div class="capture-ok">✓ You're on the list — we'll be in touch at ${email}</div>`;
  });
}
wireCapture("heroForm", "heroEmail");
wireCapture("finalForm", "finalEmail");

// --- Signal flow through the "How it works" steps ---
(function signalFlow() {
  const grid    = document.getElementById("stepsGrid");
  const svg     = document.getElementById("flowSvg");
  const base    = document.getElementById("flowBase");
  const ret     = document.getElementById("flowReturn");
  const comet   = document.getElementById("flowComet");
  if (!grid || !svg || !base || !ret || !comet) return;

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const FORWARD_SECONDS = 5;   // ~time for the pulse to travel 01 → 08
  const COMET_LEN = 26;        // length of the bright comet dash (px)
  let styleTag;

  function build() {
    const badges = [...grid.querySelectorAll(".num")];
    if (badges.length < 2) return;

    const gb = grid.getBoundingClientRect();
    if (gb.width < 2) return;

    // Badge centres, relative to the grid (1 viewBox unit = 1px → no distortion)
    const pts = badges.map((b) => {
      const r = b.getBoundingClientRect();
      return { x: r.left - gb.left + r.width / 2, y: r.top - gb.top + r.height / 2, el: b };
    });
    svg.setAttribute("viewBox", `0 0 ${gb.width} ${gb.height}`);

    // Forward connector: straight along a row, gentle "down-and-back" curve on a row change.
    let fwd = `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}`;
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i];
      if (Math.abs(a.y - b.y) < 4 || Math.abs(a.x - b.x) < 4) {
        // straight run — horizontal along a row, or a vertical drop between stacked steps (04 → 05)
        fwd += ` L ${b.x.toFixed(1)} ${b.y.toFixed(1)}`;
      } else {
        const midY = (a.y + b.y) / 2;
        const off = Math.max(18, Math.min(50, Math.abs(b.x - a.x) * 0.4)); // gentle curve for a diagonal row-change
        fwd += ` C ${(a.x + off).toFixed(1)} ${midY.toFixed(1)} ${(b.x - off).toFixed(1)} ${midY.toFixed(1)} ${b.x.toFixed(1)} ${b.y.toFixed(1)}`;
      }
    }

    // Faint return path into step 01 — the "Monitor → next Scan" feedback loop.
    const last = pts[pts.length - 1], first = pts[0];
    const botY = Math.max(...pts.map((p) => p.y));
    let retSeg;
    if (Math.abs(last.x - first.x) < gb.width * 0.25) {
      // Serpentine: the last step sits under the first → bow gently left and rise straight up.
      const bowX = Math.max(6, Math.min(first.x, last.x) - 42);
      retSeg = ` C ${bowX.toFixed(1)} ${last.y.toFixed(1)} ${bowX.toFixed(1)} ${first.y.toFixed(1)} ${first.x.toFixed(1)} ${first.y.toFixed(1)}`;
    } else {
      // General layout: drop below the last row, sweep left, rise into step 01.
      const belowY = botY + (gb.height - botY) * 0.55;
      const leftX = Math.max(8, Math.min(first.x, pts[Math.min(4, pts.length - 1)].x) - 30);
      retSeg =
        ` C ${last.x.toFixed(1)} ${belowY.toFixed(1)} ${((last.x + leftX) / 2).toFixed(1)} ${belowY.toFixed(1)} ${leftX.toFixed(1)} ${belowY.toFixed(1)}` +
        ` C ${leftX.toFixed(1)} ${belowY.toFixed(1)} ${leftX.toFixed(1)} ${first.y.toFixed(1)} ${first.x.toFixed(1)} ${first.y.toFixed(1)}`;
    }

    base.setAttribute("d", fwd);
    ret.setAttribute("d", `M ${last.x.toFixed(1)} ${last.y.toFixed(1)}` + retSeg);
    comet.setAttribute("d", fwd + retSeg);   // one continuous loop for the pulse

    if (reduced) { comet.style.display = "none"; return; }

    const Lfwd  = base.getTotalLength();
    const Lfull = comet.getTotalLength();
    if (!Lfull) return;

    const fwdFrac = Lfwd / Lfull;                 // share of the loop that is 01 → 08
    const CYCLE   = Math.min(9, FORWARD_SECONDS / fwdFrac);

    // Find the cycle-fraction at which the comet reaches each badge (forward leg only).
    const SAMPLES = 500;
    const arrival = pts.map(() => ({ d: Infinity, L: 0 }));
    for (let s = 0; s <= SAMPLES; s++) {
      const L = (Lfwd * s) / SAMPLES;
      const p = base.getPointAtLength(L);
      for (let k = 0; k < pts.length; k++) {
        const dx = p.x - pts[k].x, dy = p.y - pts[k].y;
        const dist = dx * dx + dy * dy;
        if (dist < arrival[k].d) { arrival[k] = { d: dist, L }; }
      }
    }

    // Drive each badge so its peak lands exactly when the comet passes it.
    pts.forEach((p, k) => {
      const delay = (arrival[k].L / Lfull) * CYCLE;
      p.el.style.animation = `badgeFlow ${CYCLE.toFixed(2)}s linear infinite`;
      p.el.style.animationDelay = `${(delay - 1.5 * CYCLE).toFixed(2)}s`;   // negative → no first-frame flash
    });

    // The comet: one bright dash sweeping the whole loop, dimming on the return leg.
    const fwdPct  = (fwdFrac * 100).toFixed(1);
    const fadePct = Math.min(94, fwdFrac * 100 + 6).toFixed(1);
    if (!styleTag) {
      styleTag = document.createElement("style");
      styleTag.id = "flowKeyframes";
      document.head.appendChild(styleTag);
    }
    styleTag.textContent =
      `@keyframes flowCometRun {` +
      `0% { stroke-dashoffset: 0; opacity: 1; }` +
      `${fwdPct}% { opacity: 1; }` +
      `${fadePct}% { opacity: 0.12; }` +
      `94% { opacity: 0.12; }` +
      `100% { stroke-dashoffset: ${(-Lfull).toFixed(1)}px; opacity: 1; }` +
      `}`;
    comet.style.display = "";
    comet.style.strokeDasharray = `${COMET_LEN} ${(Lfull - COMET_LEN).toFixed(1)}`;
    comet.style.animation = `flowCometRun ${CYCLE.toFixed(2)}s linear infinite`;
  }

  let raf;
  const schedule = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(build); };
  build();
  window.addEventListener("load", schedule);
  window.addEventListener("resize", () => { clearTimeout(window.__flowT); window.__flowT = setTimeout(schedule, 150); });
})();

// --- Scroll reveal ---
const io = new IntersectionObserver((entries) => {
  entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
}, { threshold: 0.12 });
document.querySelectorAll(".reveal").forEach(el => io.observe(el));

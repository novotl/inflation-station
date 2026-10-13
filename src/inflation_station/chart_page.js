// The chart page: three layouts of the data Python wrote into #data, the traces of every chart included.
// Here: layout, colours by trace role (light/dark), private mode, the layout switcher.
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const P = D.portfolio;

// ---------- formatting ----------
const esc = s => String(s).replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
const nf = (x, digits = 0) => x == null ? "–" : x.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
// Absolute amounts, which private mode blurs.
const abs = html => `<span class="abs">${html}</span>`;
const czk = x => x == null ? "–" : abs(nf(x) + " CZK");
const pct = x => x == null ? "–" : (x >= 0 ? "+" : "") + (100 * x).toFixed(1) + " %";
const cls = x => x == null ? "muted" : x >= 0 ? "pos" : "neg";
// value / base - 1, or null when either is unknown.
const vs = (value, base) => value == null || base == null || base === 0 ? null : value / base - 1;
const minus = (a, b) => a == null || b == null ? null : a - b;

// ---------- theme ----------
// One colour per role, on every chart: value, amount invested, inflation (its two series told apart by dash).
const PALETTES = {
  light: { ink: "#2b211b", ink2: "#6f5f53", tick: "#8a796b", grid: "#f0e9df", line: "#ece4d9", tipBg: "#2b211b", tipInk: "#fffdfa",
    value: "#003d5c", invested: "#8a796b", inflation: "#c8553d", est: "#f3e9dc", zero: "#3d2f27",
    colorway: ["#003d5c", "#00546e", "#006b71", "#008162", "#009446", "#65a31c", "#b1aa00", "#ffa600"] },
  dark: { ink: "#f3ebe3", ink2: "#b8a899", tick: "#9c8c7f", grid: "#2c241f", line: "#362d27", tipBg: "#f3ebe3", tipInk: "#17120f",
    value: "#3f8fb8", invested: "#b8a899", inflation: "#e07a5f", est: "#2a221d", zero: "#b8a899",
    colorway: ["#3f8fb8", "#2a9bb5", "#1fa3a8", "#008162", "#009446", "#65a31c", "#b1aa00", "#ffa600"] },
};
const palette = () => PALETTES[document.documentElement.dataset.theme] || PALETTES.light;
const FONT = getComputedStyle(document.documentElement).getPropertyValue("--font");
const BASE_LAYOUT = {
  font: { family: FONT, size: 12 }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
  hoverlabel: { font: { family: FONT } }, hovermode: "x unified",
  xaxis: { tickfont: { size: 11 } }, yaxis: { tickfont: { size: 11 }, title: { font: { size: 12 } } },
  margin: { l: 56, r: 16, t: 16, b: 40 },
};
// The theme's colours, as relayout keys, applied on top of any chart when the theme changes.
function themeLayout() {
  const c = palette(), out = {
    "font.color": c.ink, colorway: c.colorway, "legend.font.color": c.ink2,
    "hoverlabel.bgcolor": c.tipBg, "hoverlabel.bordercolor": c.tipBg, "hoverlabel.font.color": c.tipInk,
  };
  for (const ax of ["xaxis", "yaxis"]) Object.assign(out, { [`${ax}.gridcolor`]: c.grid, [`${ax}.linecolor`]: c.line,
    [`${ax}.zerolinecolor`]: c.line, [`${ax}.tickfont.color`]: c.tick, [`${ax}.title.font.color`]: c.tick });
  return out;
}
function recolor(g) {
  const c = palette(), idx = [], colors = [];
  g.data.forEach((t, i) => { if (t.meta in c) { idx.push(i); colors.push(c[t.meta]); } });
  if (idx.length) Plotly.restyle(g, { "line.color": colors }, idx);
  const shapes = (g.layout.shapes || []).map(sh => sh.name === "est" ? { ...sh, fillcolor: c.est }
    : sh.name === "zero" ? { ...sh, line: { ...sh.line, color: c.zero } } : sh);
  Plotly.relayout(g, { ...themeLayout(), ...(shapes.length ? { shapes } : {}) });
}

// ---------- charts ----------
const isPrivate = () => "private" in document.documentElement.dataset;
const PRIVATE_HOVER = "•••••• CZK<extra></extra>";
// CZK charts lose their axis numbers and hover amounts in private mode; % charts are left alone.
function privacy(g) {
  if (g.dataset.pct) return;
  if (!g._ownHover) g._ownHover = g.data.map(t => t.hovertemplate);
  const on = isPrivate();
  Plotly.restyle(g, { hovertemplate: on ? g.data.map(() => PRIVATE_HOVER) : g._ownHover });
  Plotly.relayout(g, { "yaxis.showticklabels": !on });
}
// Many legend entries: on the right, out of the plot's way. Few: one row above the plot. On a narrow screen, below it.
const legendFor = n => innerWidth < 760 ? { orientation: "h", x: 0, xanchor: "left", y: -0.08, yanchor: "top" }
  : n > 5 ? { orientation: "v", x: 1.02, xanchor: "left", y: 1, yanchor: "top" }
  : { orientation: "h", x: 0, xanchor: "left", y: 1.02, yanchor: "bottom" };
const CONFIG = { responsive: true, displaylogo: false, displayModeBar: false };
async function plot(el, traces, layout = {}, { pct = false } = {}) {
  if (typeof el === "string") el = document.getElementById(el);
  // Copies, as plotly keeps and changes what it's given and the fund strip draws the same traces again.
  const data = traces.map(t => ({ ...t, line: { ...t.line } }));
  const legend = { font: { size: 11 }, ...legendFor(data.length), ...(layout.legend || {}) };
  const margin = { ...BASE_LAYOUT.margin, ...(legend.y > 1 && layout.showlegend !== false ? { t: 36 } : {}), ...(layout.margin || {}) };
  const full = { ...BASE_LAYOUT, ...layout, legend, margin,
    xaxis: { ...BASE_LAYOUT.xaxis, ...(layout.xaxis || {}) }, yaxis: { ...BASE_LAYOUT.yaxis, ...(layout.yaxis || {}) } };
  if (pct) el.dataset.pct = "1";
  const g = await Plotly.newPlot(el, data, full, CONFIG);
  recolor(g);
  privacy(g);
}
const czkChart = (el, traces, height) => plot(el, traces, { yaxis: { title: { text: "CZK" } }, height });
// The benchmark's estimated months shaded, and 0 % (kept up exactly) marked.
const relativeShapes = () => [
  ...(D.estimatedFrom ? [{ type: "rect", name: "est", xref: "x", yref: "paper", x0: D.estimatedFrom, x1: D.asOf, y0: 0, y1: 1,
    line: { width: 0 }, layer: "below" }] : []),
  { type: "line", name: "zero", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { width: 1 } },
];

// A Holding's ISIN and Account, and why it isn't valued.
const holdingLine = f => `${esc(f.isin)} · ${esc(f.account)}${f.notValued ? ` · <span class="neg">not valued: ${esc(f.notValued)}</span>` : ""}`;
// A chart, or why there is none: a Holding in a Managed Account that can't be valued has nothing to draw.
const czkChartOr = (el, item, height) => item.chart.length ? czkChart(el, item.chart, height)
  : el.innerHTML = `<p class="neg" style="padding:24px 0">Not valued: ${esc(item.notValued)}</p>`;

// Why an Account has no value, or what its value leaves out.
const accountNotes = a => a.notValued ? `<p class="warn">Not valued: ${esc(a.notValued)}</p>`
  : a.leftOut.length ? `<p class="warn">Left out of its value: ${a.leftOut.map(esc).join(", ")}</p>` : "";

// ---------- dashboard: figures, the overall chart, a section per Account, a table of funds whose rows open their chart ----------
function renderDashboard(el) {
  const kpi = (label, big, sub = "") => `<div class="kpi"><div class="label">${esc(label)}</div><div class="big">${big}</div><div class="sub">${sub}</div></div>`;
  const signed = (x, html) => `<span class="${cls(x)}">${html}</span>`;
  const gain = minus(P.value, P.invested);
  el.innerHTML = `<h1>Portfolio</h1><div class="kpis">
    ${kpi("Value today", czk(P.value), `<span class="muted">as of ${esc(D.asOf)}</span>`)}
    ${kpi("Invested", czk(P.invested), `<span class="muted">fees included</span>`)}
    ${kpi("Gain", signed(gain, czk(gain)), signed(gain, pct(vs(P.value, P.invested))))}
    ${P.hurdles.map(h => kpi(`vs inflation (${h.name})`, signed(minus(P.value, h.value), czk(minus(P.value, h.value))),
      `${signed(vs(P.value, h.value), pct(vs(P.value, h.value)))} <span class="muted">· hurdle ${czk(h.value)}</span>`)).join("")}
    </div><div class="card"><div id="dashboard-chart"></div></div>
    <h2>Accounts</h2><div class="accounts"></div>
    <h2>Funds</h2><div class="card table-card"><table class="funds"><thead><tr><th>Fund</th><th>Priced in</th><th>Value</th>
    <th>Invested</th><th>Gain</th><th>vs ${esc(D.benchmark ?? "inflation")}</th><th>Units</th></tr></thead><tbody></tbody></table></div>`;
  czkChart("dashboard-chart", P.chart, 420);
  const accounts = el.querySelector(".accounts");
  D.accounts.forEach(a => {
    const card = document.createElement("div");
    card.className = "card";
    const gain = minus(a.value, a.invested);
    card.innerHTML = `<h3>${esc(a.name)}</h3><div class="facts">
      <div><b>Value</b>${czk(a.value)}</div><div><b>Invested</b>${czk(a.invested)}${a.managed ? ` <span class="muted">(Deposits)</span>` : ""}</div>
      <div><b>Gain</b>${signed(gain, czk(gain))} ${signed(gain, pct(vs(a.value, a.invested)))}</div>
      ${a.hurdles.map(h => `<div><b>vs ${esc(h.name)}</b>${signed(minus(a.value, h.value), czk(minus(a.value, h.value)))}
        ${signed(vs(a.value, h.value), pct(vs(a.value, h.value)))}</div>`).join("")}
      </div>${accountNotes(a)}<div></div>`;
    accounts.append(card);
    czkChart(card.lastElementChild, a.chart, 360);
  });
  const tbody = el.querySelector("tbody");
  D.funds.forEach(f => {
    const row = document.createElement("tr");
    row.className = "row";
    const gain = vs(f.value, f.invested), real = vs(f.value, f.benchmarkHurdle);
    row.innerHTML = `<td>${esc(f.name)}<div class="isin">${holdingLine(f)}</div></td>
      <td>${esc(f.pricedIn)}</td><td>${czk(f.value)}${f.currencyValue ? `<div class="isin">${abs(esc(f.currencyValue))}</div>` : ""}</td>
      <td>${czk(f.invested)}</td><td class="${cls(gain)}">${pct(gain)}</td><td class="${cls(real)}">${pct(real)}</td><td>${abs(esc(f.units))}</td>`;
    const detail = document.createElement("tr");
    detail.hidden = true;
    detail.innerHTML = `<td colspan="7" style="text-align:left"><div></div></td>`;
    row.onclick = () => {
      detail.hidden = !detail.hidden;
      row.classList.toggle("open", !detail.hidden);
      if (!detail.hidden && !detail.dataset.drawn) { detail.dataset.drawn = "1"; czkChartOr(detail.querySelector("div"), f, 360); }
    };
    tbody.append(row, detail);
  });
}

// ---------- relative to inflation: how far above or below its benchmarks each value is, in % ----------
function renderRelative(el) {
  if (!P.relative.length) {
    el.innerHTML = `<h1>Beating inflation?</h1><p class="muted">Nothing is valued yet: fetch prices (and rates for funds not priced in CZK).</p>`;
    return;
  }
  const real = vs(P.value, P.benchmarkHurdle), nominal = vs(P.value, P.invested);
  el.innerHTML = `<h1>Beating inflation?</h1>
    <p class="muted">Each line is how far the value is above (+) or below (−) a benchmark, in %; 0 is exactly kept up.
    ${D.estimatedFrom ? `Shaded: ${esc(D.benchmark)} estimated, not published yet.` : ""}</p>
    <div class="kpis">
      ${D.benchmark ? `<div class="kpi"><div class="label">Portfolio vs ${esc(D.benchmark)}</div><div class="big ${cls(real)}">${pct(real)}</div>
        <div class="sub muted">${czk(P.value)} vs hurdle ${czk(P.benchmarkHurdle)}</div></div>` : ""}
      <div class="kpi"><div class="label">Portfolio vs invested</div><div class="big ${cls(nominal)}">${pct(nominal)}</div>
        <div class="sub muted">${czk(P.value)} vs ${czk(P.invested)}</div></div></div>
    <div class="card"><div id="relative-chart"></div></div>
    <h2>Per account and fund <span class="muted" style="font-size:14px;font-weight:normal">(same scale everywhere)</span></h2>
    <div class="grid accounts"></div><div class="grid funds"></div>`;
  plot("relative-chart", P.relative, { yaxis: { tickformat: "+.0%", zeroline: false }, shapes: relativeShapes(), height: 380, margin: { t: 10 } }, { pct: true });
  const all = D.accounts.concat(D.funds).flatMap(f => f.relative.flatMap(t => t.y)).filter(y => y != null);
  const range = all.length ? [Math.min(...all) - .05, Math.max(...all) + .05] : undefined;
  const cell = (grid, name, item, sub) => {
    const now = D.benchmark ? vs(item.value, item.benchmarkHurdle) : vs(item.value, item.invested);
    const div = document.createElement("div");
    div.className = "cell";
    div.innerHTML = `<h3><span>${esc(name)}</span><span class="pct ${cls(now)}">${item.notValued ? "not valued" : pct(now)}</span></h3>
      <div class="isin">${sub}</div><div></div>`;
    grid.append(div);
    const chart = div.lastElementChild;
    if (item.notValued) { chart.innerHTML = `<p class="neg" style="padding:24px 0">Not valued: ${esc(item.notValued)}</p>`; return; }
    // Nothing is invested in a Holding in a Managed Account, so there is nothing to measure it against.
    if (!item.relative.length) { chart.innerHTML = `<p class="muted" style="padding:24px 0">In a Managed Account: its Account is measured instead.</p>`; return; }
    plot(chart, item.relative, { yaxis: { tickformat: "+.0%", range, zeroline: false }, shapes: relativeShapes(), showlegend: false,
      height: 220, margin: { t: 6, b: 30, l: 50, r: 10 } }, { pct: true });
  };
  D.accounts.forEach(a => cell(el.querySelector(".grid.accounts"), a.name, a, `${a.managed ? "Managed Account · " : ""}${czk(a.value)}`));
  D.funds.forEach(f => cell(el.querySelector(".grid.funds"), f.name, f,
    `${esc(f.isin)} · ${esc(f.account)} · priced in ${esc(f.pricedIn)} · ${czk(f.value)}`));
}

// ---------- fund strip: a tile per Account and per fund above one big chart of the one picked ----------
function renderFunds(el) {
  el.innerHTML = `<div class="strip-page"><div class="strip"></div><div class="detail"></div></div>`;
  const strip = el.querySelector(".strip"), detail = el.querySelector(".detail");
  const standing = (value, hurdle, invested) => D.benchmark ? `${pct(vs(value, hurdle))} vs ${esc(D.benchmark)}` : `${pct(vs(value, invested))} vs invested`;
  const items = [{ key: "", name: "Whole portfolio", value: P.value, rel: D.benchmark ? vs(P.value, P.benchmarkHurdle) : vs(P.value, P.invested),
    label: standing(P.value, P.benchmarkHurdle, P.invested) }]
    .concat(D.accounts.map(a => ({ key: "a" + a.key, a, name: a.name, value: a.value,
      rel: D.benchmark ? vs(a.value, a.benchmarkHurdle) : vs(a.value, a.invested),
      label: a.notValued ? "not valued" : standing(a.value, a.benchmarkHurdle, a.invested) })))
    .concat(D.funds.map(f => ({ key: "f" + f.key, f, name: f.name, value: f.value,
      rel: f.managed ? null : D.benchmark ? vs(f.value, f.benchmarkHurdle) : vs(f.value, f.invested),
      label: f.notValued ? "not valued" : f.managed ? esc(f.account) : standing(f.value, f.benchmarkHurdle, f.invested) })));
  const height = () => Math.max(500, innerHeight - 300);
  let picked = "";
  const draw = () => {
    strip.innerHTML = items.map(it => `<div class="item ${it.key === picked ? "sel" : ""}" data-key="${esc(it.key)}"><div class="n">${esc(it.name)}</div>
      <div class="v"><span class="muted">${czk(it.value)}</span><span class="${cls(it.rel)}">${it.label}</span></div></div>`).join("");
    strip.querySelectorAll(".item").forEach(n => n.onclick = () => { picked = n.dataset.key; draw(); });
    const fact = (label, html) => `<div><b>${esc(label)}</b>${html}</div>`;
    if (!picked) {
      detail.innerHTML = `<h1>Whole portfolio</h1><div class="facts">${fact("Value", czk(P.value))}${fact("Invested", czk(P.invested))}
        ${P.hurdles.map(h => fact(`Hurdle (${h.name})`, czk(h.value))).join("")}</div><div></div>`;
      // Fund values stacked, so the top edge is the portfolio value.
      czkChart(detail.lastElementChild, P.composition, height());
    } else if (picked.startsWith("a")) {
      const { a } = items.find(it => it.key === picked);
      detail.innerHTML = `<h1>${esc(a.name)}</h1><div class="facts">${fact("Value", czk(a.value))}${fact(a.managed ? "Deposits" : "Invested", czk(a.invested))}
        ${a.hurdles.map(h => fact(`Hurdle (${h.name})`, czk(h.value))).join("")}</div>${accountNotes(a)}<div></div>`;
      czkChart(detail.lastElementChild, a.chart, height());
    } else {
      const { f } = items.find(it => it.key === picked);
      detail.innerHTML = `<h1>${esc(f.name)}</h1><div class="facts">${fact("ISIN", esc(f.isin))}${fact("Account", esc(f.account))}${fact("Priced in", esc(f.pricedIn))}
        ${fact("Value", czk(f.value) + (f.currencyValue ? ` (${abs(esc(f.currencyValue))})` : ""))}${f.managed ? "" : fact("Invested", czk(f.invested))}
        ${fact("Units", abs(esc(f.units)))}</div>${f.notValued ? `<p class="warn">Not valued: ${esc(f.notValued)}</p>` : ""}<div></div>`;
      // Not valued, in a Managed Account: the warning says why, and there is nothing to draw.
      if (f.chart.length) czkChart(detail.lastElementChild, f.chart, height());
    }
  };
  draw();
}

// ---------- top bar: as-of date, warnings, light/dark, private mode ----------
document.getElementById("asof").textContent = `as of ${D.asOf}`;
if (D.warnings.length) {
  document.getElementById("warnings").innerHTML = `<div class="warn"><b>Out of date</b><ul>${D.warnings.map(w => `<li>${esc(w)}</li>`).join("")}</ul></div>`;
}
const store = (key, value) => { try { localStorage.setItem(key, value); } catch (e) { /* not remembered; still applied */ } };
const stored = key => { try { return localStorage.getItem(key); } catch (e) { return null; } };
const themeBtn = document.getElementById("theme");
const labelTheme = () => themeBtn.textContent = document.documentElement.dataset.theme === "dark" ? "☾ Dark" : "☀ Light";
function setTheme(theme, remember) {
  document.documentElement.dataset.theme = theme;
  if (remember) store("theme", theme);
  labelTheme();
  document.querySelectorAll(".js-plotly-plot").forEach(recolor);
}
themeBtn.onclick = () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true);
// Follow the system until a choice is made here.
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", e => { if (!stored("theme")) setTheme(e.matches ? "dark" : "light", false); });
labelTheme();
const privateBtn = document.getElementById("private");
const labelPrivate = () => privateBtn.textContent = isPrivate() ? "◉ Private" : "◎ Amounts shown";
privateBtn.onclick = () => {
  const on = !isPrivate();
  if (on) document.documentElement.dataset.private = ""; else delete document.documentElement.dataset.private;
  store("private", on ? "1" : "0");
  labelPrivate();
  document.querySelectorAll(".js-plotly-plot").forEach(privacy);
};
labelPrivate();

// ---------- layout switcher: top-bar buttons, ← / →, ?view= ----------
const VIEWS = { dashboard: renderDashboard, relative: renderRelative, funds: renderFunds };
const KEYS = Object.keys(VIEWS), rendered = new Set();
let current;
function show(key) {
  if (!KEYS.includes(key)) key = KEYS[0];
  KEYS.forEach(k => document.getElementById("v-" + k).classList.toggle("active", k === key));
  if (!rendered.has(key)) { rendered.add(key); VIEWS[key](document.getElementById("v-" + key)); }
  document.querySelectorAll("#switcher button").forEach(b => b.classList.toggle("on", b.dataset.key === key));
  const url = new URL(location);
  url.searchParams.set("view", key);
  history.replaceState(null, "", url);
  window.dispatchEvent(new Event("resize")); // charts drawn while hidden need their size again
  current = key;
}
KEYS.forEach(key => {
  const b = document.createElement("button");
  b.dataset.key = key;
  b.textContent = document.getElementById("v-" + key).dataset.name;
  b.onclick = () => show(key);
  document.getElementById("switcher").append(b);
});
addEventListener("keydown", e => {
  if (e.target.closest?.("input, textarea, [contenteditable]")) return;
  const step = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
  if (step) show(KEYS[(KEYS.indexOf(current) + step + KEYS.length) % KEYS.length]);
});
show(new URLSearchParams(location.search).get("view"));

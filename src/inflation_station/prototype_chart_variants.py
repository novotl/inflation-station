# PROTOTYPE, throwaway: not held to these lint rules.
# ruff: noqa: ANN001, ANN201, ANN202, E501, RUF001, T201
"""PROTOTYPE, throwaway: what should the chart page look like? Not production code; delete once a layout has won.

Four layouts of the chart page, from the real data, switchable via `?variant=` (A-D) and a floating bottom bar:
A is today's page, B a dashboard with a fund table, C performance relative to inflation as small multiples,
D a sidebar of funds next to one big chart.

Run: uv run python -m inflation_station.prototype_chart_variants   # writes data/chart-prototype.html
"""

import json
from html import escape

from plotly.offline import get_plotlyjs

from inflation_station import clock
from inflation_station.chart import _by_last_value, _fund_section, _overall
from inflation_station.freshness import out_of_date
from inflation_station.price_index import NAMES
from inflation_station.settings import Settings
from inflation_station.store import Store
from inflation_station.valuation import CZK, timeline


def _f(values):
    return [None if v is None else float(v) for v in values]


def _hurdles(hurdles):
    return {
        series: {"name": NAMES[series], "values": _f(h.values), "estFrom": h.estimated_from.isoformat()}
        for series, h in hurdles.items()
    }


def main():
    data_dir = Settings().data_dir
    store = Store(data_dir)
    prices, rates, index_levels = store.fund_prices(), store.fx_rates(), store.index_levels()
    today = clock.today()
    t = timeline(store.purchases(), prices=prices, rates=rates, index_levels=index_levels, today=today)
    warnings = out_of_date(prices=prices, rates=rates, index_levels=index_levels, fund_names=t.fund_names, today=today)
    order = _by_last_value(t)
    data = {
        "dates": [d.isoformat() for d in t.dates],
        "invested": _f(t.amount_invested),
        "portfolio": None if t.portfolio_value is None else _f(t.portfolio_value),
        "hurdles": _hurdles(t.hurdles),
        "warnings": warnings,
        "funds": [
            {
                "isin": isin,
                "name": t.fund_names[isin],
                "pricedIn": t.priced_in[isin],
                "currency": t.fund_currencies.get(isin, CZK),
                "values": _f(t.fund_values[isin]) if isin in t.fund_values else None,
                "curValues": _f(t.fund_currency_values[isin]) if isin in t.fund_currency_values else None,
                "units": _f(t.units_held[isin]),
                "invested": _f(t.fund_amount_invested[isin]),
                "hurdles": _hurdles(t.fund_hurdles[isin]),
                "notValued": t.not_valued.get(isin),
            }
            for isin in order
        ],
    }
    # Variant A is today's page, built by the real chart code.
    variant_a = [_overall(t).to_html(full_html=False, include_plotlyjs=False)]
    variant_a += [_fund_section(t, isin) for isin in order]
    path = data_dir / "chart-prototype.html"
    path.write_text(
        PAGE.replace("{{PLOTLY}}", get_plotlyjs())
        .replace("{{DATA}}", json.dumps(data).replace("</", "<\\/"))
        .replace("{{VARIANT_A}}", "\n".join(variant_a))
        .replace("{{TODAY}}", escape(today.isoformat())),
        encoding="utf-8",
    )
    print(f"Prototype written to {path}; open it and use ←/→ or ?variant=A..D")


PAGE = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Portfolio (PROTOTYPE)</title>
<script>
  // Light or dark: the stored choice, else the system's. Set before anything paints.
  (() => { let t = null; try { t = localStorage.getItem("theme"); } catch (e) {}
    document.documentElement.dataset.theme = t || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    let p = null; try { p = localStorage.getItem("private"); } catch (e) {}
    if (p === "1") document.documentElement.dataset.private = ""; })();
</script>
<script>{{PLOTLY}}</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #f7f3ee; --surface: #fffdfa; --ink: #2b211b; --ink-2: #6f5f53; --muted: #a8998c; --line: #ece4d9;
    --accent: #c8553d; --accent-soft: #fbece6; --pos: #4d7c3a; --pos-soft: #eef4e6; --neg: #b8322a; --neg-soft: #fbe9e6;
    --surface-2: var(--surface-2); --hover: #f4ece2; --warn-bg: #fdf3df; --warn-line: #ecd29a; --warn-ink: #7a4a12;
    --radius: 14px; --shadow: 0 1px 2px rgba(60,35,20,.04), 0 4px 16px rgba(60,35,20,.07);
    color-scheme: light;
  }
  :root[data-theme="dark"] {
    --bg: #17120f; --surface: #211b17; --ink: #f3ebe3; --ink-2: #b8a899; --muted: #8a7b6e; --line: #362d27;
    --accent: #e07a5f; --accent-soft: #3a2620; --pos: #9cc97a; --pos-soft: #26301e; --neg: #f08070; --neg-soft: #3a211d;
    --surface-2: #1c1714; --hover: #2a221d; --warn-bg: #33270f; --warn-line: #5c4518; --warn-ink: #f2cf86;
    --shadow: 0 1px 2px rgba(0,0,0,.3), 0 4px 16px rgba(0,0,0,.35);
    color-scheme: dark;
  }
  body { transition: background .2s, color .2s; }
  .top-right { display: flex; align-items: center; gap: 10px; }
  #theme { border: 1px solid var(--line); background: var(--surface-2); color: var(--ink); border-radius: 999px; height: 30px;
    padding: 0 12px; display: flex; align-items: center; gap: 6px; cursor: pointer; font: 500 13px Inter, system-ui, sans-serif; }
  #theme:hover, #private:hover { background: var(--hover); }
  #private { border: 1px solid var(--line); background: var(--surface-2); color: var(--ink); border-radius: 999px; height: 30px;
    padding: 0 12px; display: flex; align-items: center; gap: 6px; cursor: pointer; font: 500 13px Inter, system-ui, sans-serif; }
  :root[data-private] #private { background: var(--ink); color: var(--surface); border-color: var(--ink); }
  /* Privacy: absolute amounts blurred, percentages left readable. */
  .abs { transition: filter .15s; }
  :root[data-private] .abs { filter: blur(7px); user-select: none; }
  * { box-sizing: border-box; }
  body { font-family: Inter, system-ui, -apple-system, "Segoe UI", sans-serif; margin: 0; color: var(--ink); background: var(--bg);
    -webkit-font-smoothing: antialiased; font-feature-settings: "tnum"; }
  .top { background: var(--surface); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 50; }
  .top .wrap { max-width: 1480px; margin: 0 auto; padding: 14px 24px; display: flex; align-items: center; justify-content: space-between; }
  .brand { font-weight: 700; letter-spacing: -.01em; display: flex; align-items: center; gap: 10px; }
  .brand::before { content: ""; width: 22px; height: 22px; border-radius: 7px; background: linear-gradient(135deg, #e0a526, #c8553d 55%, #7b2d4f); }
  .asof { font-size: 13px; color: var(--ink-2); background: var(--bg); padding: 4px 10px; border-radius: 999px; }
  .variant { display: none; max-width: 1480px; margin: 0 auto; padding: 28px 24px 48px; }
  .variant.active { display: block; }
  h1 { font-size: 28px; letter-spacing: -.02em; margin: 0 0 18px; font-weight: 700; }
  h2 { font-size: 18px; letter-spacing: -.01em; margin: 32px 0 12px; font-weight: 600; }
  .card, #v-A > div, #v-A > section, .cell, .md { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
    box-shadow: var(--shadow); padding: 16px 20px; margin-bottom: 20px; }
  #v-A section h2 { margin-top: 4px; }
  .pos { color: var(--pos); } .neg { color: var(--neg); } .muted { color: var(--ink-2); }
  .warn { background: var(--warn-bg); border: 1px solid var(--warn-line); color: var(--warn-ink); border-radius: 10px; padding: 10px 14px; margin-bottom: 20px; font-size: 14px; }
  .warn ul { margin: 4px 0 0; padding-left: 20px; }
  .note { color: var(--neg); }
  /* B */
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin: 0 0 20px; }
  .kpi { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); padding: 16px 18px; }
  .kpi .label { font-size: 11px; color: var(--ink-2); text-transform: uppercase; letter-spacing: .06em; font-weight: 600; }
  .kpi .big { font-size: 26px; font-weight: 700; letter-spacing: -.02em; margin-top: 6px; }
  .kpi .sub { font-size: 13px; margin-top: 4px; }
  .table-card { padding: 0; overflow-x: auto; }
  table.funds { border-collapse: collapse; width: 100%; font-size: 14px; }
  table.funds th { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--ink-2); font-weight: 600; background: var(--surface-2); }
  table.funds th, table.funds td { padding: 12px 16px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; }
  table.funds th:first-child, table.funds td:first-child { text-align: left; white-space: normal; }
  table.funds tr:last-child td { border-bottom: 0; }
  table.funds tr.row { cursor: pointer; transition: background .12s; } table.funds tr.row:hover { background: var(--hover); }
  table.funds tr.row.open { background: var(--accent-soft); }
  table.funds td.pos, table.funds td.neg { font-weight: 600; }
  .isin { font-size: 12px; color: var(--muted); margin-top: 2px; }
  /* C */
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px; }
  .cell { margin: 0; padding: 14px 16px 6px; }
  .cell h3 { font-size: 14px; font-weight: 600; margin: 0 0 2px; display: flex; justify-content: space-between; gap: 12px; }
  .cell h3 span.pct { white-space: nowrap; padding: 2px 8px; border-radius: 999px; font-size: 13px; }
  .cell h3 span.pct.pos { background: var(--pos-soft); } .cell h3 span.pct.neg { background: var(--neg-soft); }
  /* D */
  .md { display: flex; padding: 0; overflow: hidden; min-height: calc(100vh - 200px); }
  .side { width: 300px; flex: none; border-right: 1px solid var(--line); background: var(--surface-2); padding: 8px; }
  .side .item { padding: 10px 12px; cursor: pointer; border-radius: 10px; margin-bottom: 2px; transition: background .12s; }
  .side .item:hover { background: var(--hover); } .side .item.sel { background: var(--surface); box-shadow: var(--shadow); outline: 1px solid var(--line); }
  .side .item .n { font-weight: 600; font-size: 13px; line-height: 1.3; }
  .side .item .v { font-size: 12px; display: flex; justify-content: space-between; margin-top: 4px; }
  .detail { flex: 1; padding: 22px 26px; min-width: 0; }
  .detail h1 { font-size: 22px; }
  .facts { display: flex; gap: 28px; flex-wrap: wrap; font-size: 15px; font-weight: 600; margin: 0 0 12px; }
  .facts b { display: block; font-size: 11px; color: var(--ink-2); font-weight: 600; text-transform: uppercase; letter-spacing: .06em; margin-bottom: 2px; }
  @media (max-width: 760px) { .md { flex-direction: column; } .side { width: auto; border-right: 0; border-bottom: 1px solid var(--line); }
    .variant, .top .wrap { padding-left: 16px; padding-right: 16px; } }
  /* layout switcher, in the top bar; the dashed outline marks it as the prototype's, not part of a design */
  .top .wrap { gap: 16px; flex-wrap: wrap; }
  #switcher { display: flex; align-items: center; gap: 4px; padding: 3px; border: 1px dashed var(--muted); border-radius: 999px; }
  #switcher .proto { font-size: 10px; font-weight: 700; letter-spacing: .08em; color: var(--muted); padding: 0 8px 0 10px; }
  #switcher button { border: 0; background: transparent; color: var(--ink-2); border-radius: 999px; padding: 6px 12px; cursor: pointer;
    font: 500 13px Inter, system-ui, sans-serif; white-space: nowrap; transition: background .12s, color .12s; }
  #switcher button:hover { background: var(--hover); color: var(--ink); }
  #switcher button.on { background: var(--ink); color: var(--surface); }
  #switcher button b { font-weight: 700; margin-right: 6px; }
  @media (max-width: 1100px) { #switcher button span { display: none; } #switcher button b { margin: 0; } }
</style>
</head>
<body>
<header class="top"><div class="wrap"><span class="brand">inflation-station</span><nav id="switcher" title="Prototype layouts (← / → to cycle)"><span class="proto">PROTOTYPE</span></nav><span class="top-right"><span class="asof">as of {{TODAY}}</span><button id="private" title="Blur absolute amounts; percentages stay"></button><button id="theme" title="Switch light/dark"></button></span></div></header>
<div class="variant" id="v-A" data-name="Today's page">{{VARIANT_A}}</div>
<div class="variant" id="v-B" data-name="Dashboard + fund table"></div>
<div class="variant" id="v-C" data-name="Relative to inflation, small multiples"></div>
<div class="variant" id="v-D" data-name="Sidebar + one big chart"></div>
<script>
const D = {{DATA}};
const CPI = Object.keys(D.hurdles)[0];
const PALETTES = {
  light: { ink: "#2b211b", ink2: "#6f5f53", tick: "#8a796b", grid: "#f0e9df", line: "#ece4d9", tipBg: "#2b211b", tipInk: "#fffdfa",
    accent: "#c8553d", invested: "#6b5b4e", csu_cpi: "#3d2f27", eurostat_hicp: "#a39283", nominal: "#a39283", est: "#f3e9dc", zero: "#3d2f27",
    colorway: ["#003d5c", "#00546e", "#006b71", "#008162", "#009446", "#65a31c", "#b1aa00", "#ffa600"] },
  dark: { ink: "#f3ebe3", ink2: "#b8a899", tick: "#9c8c7f", grid: "#2c241f", line: "#362d27", tipBg: "#f3ebe3", tipInk: "#17120f",
    accent: "#e07a5f", invested: "#b8a899", csu_cpi: "#f3ebe3", eurostat_hicp: "#8a7b6e", nominal: "#8a7b6e", est: "#2a221d", zero: "#b8a899",
    colorway: ["#3f8fb8", "#2a9bb5", "#1fa3a8", "#008162", "#009446", "#65a31c", "#b1aa00", "#ffa600"] },
};
const P = () => PALETTES[document.documentElement.dataset.theme] || PALETTES.light;
const HSTYLE = { csu_cpi: { dash: "solid" }, eurostat_hicp: { dash: "dash" } };
// Lines with a fixed meaning get their colour from the palette by name, here and in today's page (A) alike.
function role(name = "") {
  if (name.startsWith("Amount invested")) return "invested";
  if (name.startsWith("Inflation hurdle (ČSÚ")) return "csu_cpi";
  if (name.startsWith("Inflation hurdle (Eurostat")) return "eurostat_hicp";
  if (name === "real" || name.endsWith("(real)")) return "accent";
  if (name === "nominal" || name.endsWith("(nominal)")) return "nominal";
  return null;
}
// Many lines: legend on the right, out of the plot's way. Few: one row above the plot.
const legendFor = n => n > 5
  ? { orientation: "v", x: 1.02, xanchor: "left", y: 1, yanchor: "top" }
  : { orientation: "h", x: 0, xanchor: "left", y: 1.02, yanchor: "bottom" };
// Only the theme's colours, as relayout keys: applied on top of any chart, ours or A's, when the mode changes.
function themeColors() {
  const c = P(), out = {
    "font.color": c.ink, colorway: c.colorway, "legend.font.color": c.ink2, "title.font.color": c.ink,
    "hoverlabel.bgcolor": c.tipBg, "hoverlabel.bordercolor": c.tipBg, "hoverlabel.font.color": c.tipInk,
  };
  for (const ax of ["xaxis", "yaxis"]) Object.assign(out, { [`${ax}.gridcolor`]: c.grid, [`${ax}.linecolor`]: c.line,
    [`${ax}.zerolinecolor`]: c.line, [`${ax}.tickfont.color`]: c.tick, [`${ax}.title.font.color`]: c.tick });
  return out;
}
const THEME = {
  font: { family: "Inter, system-ui, sans-serif", size: 12 }, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
  hoverlabel: { font: { family: "Inter, system-ui, sans-serif" } }, legend: { font: { size: 11 } },
  xaxis: { tickfont: { size: 11 } }, yaxis: { tickfont: { size: 11 }, title: { font: { size: 12 } } },
  margin: { l: 56, r: 16, t: 16, b: 40 },
};
function recolor(g) {
  const c = P(), idx = [], colors = [];
  g.data.forEach((t, i) => { const r = role(t.name); if (r) { idx.push(i); colors.push(c[r]); } });
  if (idx.length) Plotly.restyle(g, { "line.color": colors }, idx);
  const shapes = (g.layout.shapes || []).map(sh => sh.name === "est" ? { ...sh, fillcolor: c.est } : sh.name === "zero" ? { ...sh, line: { ...sh.line, color: c.zero } } : sh);
  Plotly.relayout(g, { ...themeColors(), ...(shapes.length ? { shapes } : {}) });
}
const isPrivate = () => "private" in document.documentElement.dataset;
const PRIVATE_HOVER = "•••••• CZK";
// CZK charts lose their axis numbers and hover amounts; % charts (tickformat with %) are left alone.
function privacy(g) {
  if ((g.layout.yaxis?.tickformat || "").includes("%")) return;
  if (!g._ownHover) g._ownHover = g.data.map(t => t.hovertemplate ?? null);
  const on = isPrivate();
  Plotly.restyle(g, { hovertemplate: on ? g.data.map(() => PRIVATE_HOVER) : g._ownHover });
  Plotly.relayout(g, { "yaxis.showticklabels": !on });
}
async function plot(id, traces, layout = {}, cfg) {
  const legend = { ...THEME.legend, ...legendFor(traces.length), ...(layout.legend || {}) };
  const margin = { ...THEME.margin, ...(legend.orientation === "h" && layout.showlegend !== false ? { t: 36 } : {}), ...(layout.margin || {}) };
  const full = { ...THEME, ...layout, legend, margin, xaxis: { ...THEME.xaxis, ...(layout.xaxis || {}) }, yaxis: { ...THEME.yaxis, ...(layout.yaxis || {}) } };
  if (typeof layout.yaxis?.title === "string") full.yaxis.title = { ...THEME.yaxis.title, text: layout.yaxis.title };
  const g = await Plotly.newPlot(id, traces, full, cfg);
  recolor(g);
  privacy(g);
}
const nf = (x, d = 0) => x == null ? "–" : x.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const abs = h => `<span class="abs">${h}</span>`;
const czk = x => x == null ? "–" : abs(nf(x) + " CZK");
const pct = x => x == null ? "–" : (x >= 0 ? "+" : "") + (100 * x).toFixed(1) + " %";
const cls = x => x == null ? "muted" : x >= 0 ? "pos" : "neg";
const last = a => { if (!a) return null; for (let i = a.length - 1; i >= 0; i--) if (a[i] != null) return a[i]; return null; };
const ratio = (a, b) => a.map((x, i) => x == null || b[i] == null || b[i] === 0 ? null : x / b[i] - 1);
const CONFIG = { responsive: true, displaylogo: false, displayModeBar: false };
const HOVER = "%{y:,.2f} CZK";

function hurdleTraces(h, series, extra = {}) {
  const name = `Inflation hurdle (${h.name})`, line = HSTYLE[series] || { color: "gray" };
  const pub = [], est = [];
  const estFrom = new Date(h.estFrom), dayBefore = new Date(estFrom - 864e5);
  D.dates.forEach((d, i) => { const dd = new Date(d); if (dd < estFrom) pub.push(i); if (dd >= dayBefore) est.push(i); });
  const tr = (idx, nm, ln) => ({ x: idx.map(i => D.dates[i]), y: idx.map(i => h.values[i]), name: nm, legendgroup: name, line: ln, hovertemplate: HOVER, ...extra });
  return [tr(pub, name, line), tr(est, name.replace(")", ", estimated)"), { ...line, dash: "dot" })].filter(t => t.x.length);
}
function fundValueTrace(f, extra = {}) {
  const cur = f.currency !== "CZK" ? ` (%{customdata[0]:,.2f} ${f.currency})` : "";
  return { x: D.dates, y: f.values, name: f.name, customdata: f.curValues.map((c, i) => [c, nf(f.units[i], 4)]),
    hovertemplate: `${HOVER}${cur} · %{customdata[1]} units`, ...extra };
}
function warningsHtml() {
  if (!D.warnings.length) return "";
  return `<div class="warn"><b>Out of date</b><ul>${D.warnings.map(w => `<li>${w}</li>`).join("")}</ul></div>`;
}
const total = { value: last(D.portfolio), invested: last(D.invested), hurdle: Object.fromEntries(Object.entries(D.hurdles).map(([s, h]) => [s, last(h.values)])) };

// ---------- B: dashboard, KPI tiles, overall chart without fund lines, table with expandable rows ----------
function renderB(el) {
  const kpi = (label, big, sub = "") => `<div class="kpi"><div class="label">${label}</div><div class="big">${big}</div><div class="sub">${sub}</div></div>`;
  const vsH = Object.entries(total.hurdle).map(([s, h]) =>
    kpi(`vs inflation (${D.hurdles[s].name})`, `<span class="${cls(total.value - h)}">${czk(total.value - h)}</span>`,
      `<span class="${cls(total.value / h - 1)}">${pct(total.value / h - 1)}</span> <span class="muted">· hurdle ${czk(h)}</span>`)).join("");
  el.innerHTML = `<h1>Portfolio</h1>${warningsHtml()}<div class="kpis">
    ${kpi("Value today", czk(total.value), `<span class="muted">as of ${D.dates.at(-1)}</span>`)}
    ${kpi("Invested", czk(total.invested), `<span class="muted">fees included</span>`)}
    ${kpi("Gain", `<span class="${cls(total.value - total.invested)}">${czk(total.value - total.invested)}</span>`, `<span class="${cls(total.value / total.invested - 1)}">${pct(total.value / total.invested - 1)}</span>`)}
    ${vsH}</div><div class="card"><div id="b-overall"></div></div>
    <h2>Funds</h2><div class="card table-card"><table class="funds"><thead><tr><th>Fund</th><th>Priced in</th><th>Value</th><th>Invested</th><th>Gain</th><th>vs ${D.hurdles[CPI]?.name ?? "inflation"}</th><th>Units</th></tr></thead><tbody id="b-rows"></tbody></table></div>`;
  const traces = [];
  if (D.portfolio) traces.push({ x: D.dates, y: D.portfolio, name: "Portfolio value", hovertemplate: HOVER, line: { width: 2.5 } });
  traces.push({ x: D.dates, y: D.invested, name: "Amount invested", line: { shape: "hv", color: "#6b5b4e", width: 1.5 }, hovertemplate: HOVER });
  Object.entries(D.hurdles).forEach(([s, h]) => traces.push(...hurdleTraces(h, s)));
  plot("b-overall", traces, { yaxis: { title: "CZK" }, hovermode: "x unified", margin: { t: 20 }, height: 420 }, CONFIG);
  const tbody = el.querySelector("#b-rows");
  D.funds.forEach((f, n) => {
    const v = last(f.values), inv = last(f.invested), h = last(f.hurdles[CPI]?.values);
    const tr = document.createElement("tr"); tr.className = "row";
    tr.innerHTML = `<td>${f.name}<div class="isin">${f.isin}${f.notValued ? ` · <span class="neg">not valued: ${f.notValued}</span>` : ""}</div></td>
      <td>${f.pricedIn}</td><td>${czk(v)}${f.currency !== "CZK" ? `<div class="isin">${abs(nf(last(f.curValues), 2) + " " + f.currency)}</div>` : ""}</td><td>${czk(inv)}</td>
      <td class="${cls(v == null ? null : v - inv)}">${v == null ? "–" : pct(v / inv - 1)}</td>
      <td class="${cls(v == null || h == null ? null : v - h)}">${v == null || h == null ? "–" : pct(v / h - 1)}</td><td>${abs(nf(last(f.units), 4))}</td>`;
    const detail = document.createElement("tr"); detail.style.display = "none";
    detail.innerHTML = `<td colspan="7" style="text-align:left"><div id="b-f${n}"></div></td>`;
    tr.onclick = () => {
      const open = detail.style.display === "none";
      detail.style.display = open ? "" : "none"; tr.classList.toggle("open", open);
      if (open && !detail.dataset.drawn) { detail.dataset.drawn = 1; drawFund(`b-f${n}`, f, 360); }
    };
    tbody.append(tr, detail);
  });
}
function drawFund(id, f, height) {
  const traces = [];
  if (f.values) traces.push(fundValueTrace(f, { name: "Value", line: { width: 3 } }));
  traces.push({ x: D.dates, y: f.invested, name: "Amount invested", line: { shape: "hv", color: "#6b5b4e", width: 1.5 }, hovertemplate: HOVER });
  Object.entries(f.hurdles).forEach(([s, h]) => traces.push(...hurdleTraces(h, s)));
  plot(id, traces, { yaxis: { title: "CZK" }, hovermode: "x unified", margin: { t: 10 }, height }, CONFIG);
}

// ---------- C: everything as % above/below the inflation hurdle; overall then a grid of small multiples ----------
function renderC(el) {
  const h = D.hurdles[CPI];
  const estShape = h ? [{ type: "rect", xref: "x", yref: "paper", x0: h.estFrom, x1: D.dates.at(-1), y0: 0, y1: 1, name: "est", fillcolor: "#f3e9dc", opacity: 1, line: { width: 0 }, layer: "below" }] : [];
  const zero = { name: "zero", type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: "#3d2f27", width: 1 } };
  const real = D.portfolio && h ? ratio(D.portfolio, h.values) : null, nominal = D.portfolio ? ratio(D.portfolio, D.invested) : null;
  el.innerHTML = `<h1>Beating inflation?</h1>${warningsHtml()}
    <p class="muted">Each line is how far the value is above (+) or below (−) a benchmark, in %. 0 = exactly kept up.
    Shaded: ${h ? h.name : "inflation"} estimated, not published yet.</p>
    <div class="kpis"><div class="kpi"><div class="label">Portfolio vs ${h?.name}</div><div class="big ${cls(last(real))}">${pct(last(real))}</div><div class="sub muted">${czk(total.value)} vs hurdle ${czk(total.hurdle[CPI])}</div></div>
    <div class="kpi"><div class="label">Portfolio vs invested</div><div class="big ${cls(last(nominal))}">${pct(last(nominal))}</div><div class="sub muted">${czk(total.value)} vs ${czk(total.invested)}</div></div></div>
    <div class="card"><div id="c-overall"></div></div><h2>Per fund <span class="muted" style="font-size:14px;font-weight:normal">(same scale everywhere)</span></h2><div class="grid" id="c-grid"></div>`;
  const pctHover = "%{y:+.1%}";
  const overall = [];
  if (real) overall.push({ x: D.dates, y: real, name: `vs ${h.name} (real)`, line: { width: 3, color: "#c8553d" }, hovertemplate: pctHover });
  if (nominal) overall.push({ x: D.dates, y: nominal, name: "vs amount invested (nominal)", line: { color: "#a39283" }, hovertemplate: pctHover });
  plot("c-overall", overall, { yaxis: { tickformat: "+.0%", zeroline: false }, shapes: [...estShape, zero], hovermode: "x unified", height: 380, margin: { t: 10 } }, CONFIG);
  const rows = D.funds.map(f => ({ f, real: f.values && f.hurdles[CPI] ? ratio(f.values, f.hurdles[CPI].values) : null, nominal: f.values ? ratio(f.values, f.invested) : null }));
  const all = rows.flatMap(r => [...(r.real || []), ...(r.nominal || [])]).filter(x => x != null);
  const range = all.length ? [Math.min(...all) - .05, Math.max(...all) + .05] : undefined;
  const grid = el.querySelector("#c-grid");
  rows.forEach((r, n) => {
    const cell = document.createElement("div"); cell.className = "cell";
    const now = last(r.real);
    cell.innerHTML = `<h3><span>${r.f.name}</span><span class="pct ${cls(now)}">${r.f.values ? pct(now) : "not valued"}</span></h3>
      <div class="isin">${r.f.isin} · priced in ${r.f.pricedIn} · ${czk(last(r.f.values))}</div><div id="c-f${n}"></div>`;
    grid.append(cell);
    if (!r.f.values) { cell.querySelector(`#c-f${n}`).innerHTML = `<p class="neg" style="padding:24px 0">Not valued: ${r.f.notValued}</p>`; return; }
    plot(`c-f${n}`, [
      { x: D.dates, y: r.real, name: "real", line: { color: "#c8553d", width: 2 }, hovertemplate: pctHover },
      { x: D.dates, y: r.nominal, name: "nominal", line: { color: "#a39283", width: 1 }, hovertemplate: pctHover },
    ], { yaxis: { tickformat: "+.0%", range, zeroline: false }, shapes: [...estShape, zero], showlegend: false, hovermode: "x unified", height: 220, margin: { t: 6, b: 30, l: 50, r: 10 } }, CONFIG);
  });
}

// ---------- D: master-detail; sidebar with every fund and its standing, one big chart on the right ----------
function renderD(el) {
  el.innerHTML = `<div class="md"><div class="side" id="d-side"></div><div class="detail" id="d-detail"></div></div>`;
  const side = el.querySelector("#d-side"), detail = el.querySelector("#d-detail");
  const items = [{ key: "all", name: "Whole portfolio", sub: `${D.funds.length} funds`, value: total.value, vs: total.value / total.hurdle[CPI] - 1 }]
    .concat(D.funds.map(f => ({ key: f.isin, f, name: f.name, sub: f.isin, value: last(f.values), vs: f.values ? last(f.values) / last(f.hurdles[CPI].values) - 1 : null })));
  let sel = "all";
  const draw = () => {
    side.innerHTML = items.map(it => `<div class="item ${it.key === sel ? "sel" : ""}" data-k="${it.key}"><div class="n">${it.name}</div>
      <div class="v"><span class="muted">${czk(it.value)}</span><span class="${cls(it.vs)}">${it.f && !it.f.values ? "not valued" : pct(it.vs) + " vs CPI"}</span></div></div>`).join("");
    side.querySelectorAll(".item").forEach(n => n.onclick = () => { sel = n.dataset.k; draw(); });
    if (sel === "all") {
      detail.innerHTML = `<h1>Whole portfolio</h1>${warningsHtml()}<div class="facts"><div><b>Value</b>${czk(total.value)}</div><div><b>Invested</b>${czk(total.invested)}</div>
        ${Object.entries(total.hurdle).map(([s, h]) => `<div><b>Hurdle (${D.hurdles[s].name})</b>${czk(h)}</div>`).join("")}</div><div id="d-chart"></div>`;
      // Composition: fund values stacked, so the top edge is the portfolio value.
      const traces = D.funds.filter(f => f.values).slice().reverse().map(f => fundValueTrace(f, { stackgroup: "v", line: { width: 0 } }));
      traces.push({ x: D.dates, y: D.invested, name: "Amount invested", line: { shape: "hv", color: "#2b211b", width: 2 }, hovertemplate: HOVER });
      Object.entries(D.hurdles).forEach(([s, h]) => traces.push(...hurdleTraces(h, s, { line: { ...HSTYLE[s], width: 2 } })));
      plot("d-chart", traces, { yaxis: { title: "CZK" }, hovermode: "x unified", height: Math.max(500, innerHeight - 260), margin: { t: 10 } }, CONFIG);
    } else {
      const f = D.funds.find(f => f.isin === sel);
      detail.innerHTML = `<h1>${f.name}</h1><div class="facts"><div><b>ISIN</b>${f.isin}</div><div><b>Priced in</b>${f.pricedIn}</div>
        <div><b>Value</b>${czk(last(f.values))}${f.currency !== "CZK" && f.values ? ` (${abs(nf(last(f.curValues), 2) + " " + f.currency)})` : ""}</div>
        <div><b>Invested</b>${czk(last(f.invested))}</div><div><b>Units</b>${abs(nf(last(f.units), 4))}</div></div>
        ${f.notValued ? `<p class="warn">Not valued: ${f.notValued}</p>` : ""}<div id="d-chart"></div>`;
      drawFund("d-chart", f, Math.max(500, innerHeight - 260));
    }
  };
  draw();
}

// ---------- light / dark ----------
const themeBtn = document.getElementById("theme");
const labelTheme = () => themeBtn.textContent = document.documentElement.dataset.theme === "dark" ? "☾ Dark" : "☀ Light";
function setTheme(t, remember) {
  document.documentElement.dataset.theme = t;
  if (remember) try { localStorage.setItem("theme", t); } catch (e) {}
  labelTheme();
  document.querySelectorAll(".js-plotly-plot").forEach(recolor);
}
themeBtn.onclick = () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true);
// Follow the system until a choice is made here.
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", e => {
  let stored = null; try { stored = localStorage.getItem("theme"); } catch (err) {}
  if (!stored) setTheme(e.matches ? "dark" : "light", false);
});
labelTheme();

// ---------- privacy ----------
const privBtn = document.getElementById("private");
const labelPrivate = () => privBtn.textContent = isPrivate() ? "◉ Private" : "◎ Amounts shown";
privBtn.onclick = () => {
  const on = !isPrivate();
  if (on) document.documentElement.dataset.private = ""; else delete document.documentElement.dataset.private;
  try { localStorage.setItem("private", on ? "1" : "0"); } catch (e) {}
  labelPrivate();
  document.querySelectorAll(".js-plotly-plot").forEach(privacy);
};
labelPrivate();

// ---------- switcher ----------
const KEYS = ["A", "B", "C", "D"], RENDER = { B: renderB, C: renderC, D: renderD }, rendered = new Set(["A"]);
function show(k) {
  if (!KEYS.includes(k)) k = "A";
  KEYS.forEach(x => document.getElementById("v-" + x).classList.toggle("active", x === k));
  const el = document.getElementById("v-" + k);
  if (!rendered.has(k)) { rendered.add(k); RENDER[k](el); }
  document.querySelectorAll("#switcher button").forEach(b => b.classList.toggle("on", b.dataset.k === k));
  const u = new URL(location); u.searchParams.set("variant", k); history.replaceState(null, "", u);
  if (k === "A" && !el.dataset.themed) {
    el.dataset.themed = 1;
    el.querySelectorAll(".js-plotly-plot").forEach(g => {
      const titled = !!g.layout.title?.text;
      Plotly.relayout(g, { paper_bgcolor: THEME.paper_bgcolor, plot_bgcolor: THEME.plot_bgcolor, "font.family": THEME.font.family,
        legend: { ...THEME.legend, ...legendFor(g.data.length) }, margin: { ...THEME.margin, t: titled ? 56 : 16 } });
      recolor(g);
      privacy(g);
    });
  }
  window.dispatchEvent(new Event("resize")); // plotly charts drawn while hidden need their size again
  current = k;
}
let current = new URLSearchParams(location.search).get("variant") || "A";
const step = d => show(KEYS[(KEYS.indexOf(current) + d + KEYS.length) % KEYS.length]);
KEYS.forEach(k => {
  const b = document.createElement("button");
  b.dataset.k = k; b.title = document.getElementById("v-" + k).dataset.name;
  b.innerHTML = `<b>${k}</b><span>${b.title}</span>`;
  b.onclick = () => show(k);
  document.getElementById("switcher").append(b);
});
addEventListener("keydown", e => {
  const t = e.target; if (t.closest && t.closest("input, textarea, [contenteditable]")) return;
  if (e.key === "ArrowLeft") step(-1); if (e.key === "ArrowRight") step(1);
});
show(current);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()

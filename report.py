"""Builds output/dashboard.html: a self-contained dashboard of the judge results.
Called by judge_eval.py on every run. Opens in any browser, no internet needed."""
import json

def write_report(path, data, site_page=False):
    """site_page=True labels the page '② LLM judge' and adds the shared site navigation."""
    html = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    if site_page:
        import re
        from site_nav import inject
        # Relabel by pattern (not exact text) so a redesigned template still gets the site label.
        html = re.sub(r"<title>.*?</title>", "<title>② LLM judge · LishePoa product validation</title>", html, count=1)
        html = re.sub(r"<h1>(.*?)</h1>", lambda m: f"<h1>② LLM judge: {m.group(1)}</h1>", html, count=1)
        html = inject(html, "llm")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Label Extraction Scorecard</title>
<style>
/* Layout: one column of panels, summary first (cards), then scorecard, then two charts. */
:root {
  color-scheme: light;
  --bg: #f6f5f2; --panel: #ffffff; --line: #e4e2dc; --fg: #1a1a19; --muted: #6b6a65; --grid: #ebe9e4;
  --ref: #55534e; --range: #d9d7d0; --ok: #1d7f37; --bad: #c3352a; --ok-bg: #e3f2e6; --bad-bg: #fbe7e5;
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a;
  --serif: Georgia, "Times New Roman", serif; --sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #111110; --panel: #1a1a19; --line: #2e2e2c; --fg: #f0efec; --muted: #a3a29a; --grid: #2a2a28;
    --ref: #c3c2b7; --range: #3a3a37; --ok: #4fc26b; --bad: #ef6b60; --ok-bg: #1d3323; --bad-bg: #3a1f1c;
    --s1: #3987e5; --s2: #d95926; --s3: #199e70;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #111110; --panel: #1a1a19; --line: #2e2e2c; --fg: #f0efec; --muted: #a3a29a; --grid: #2a2a28;
  --ref: #c3c2b7; --range: #3a3a37; --ok: #4fc26b; --bad: #ef6b60; --ok-bg: #1d3323; --bad-bg: #3a1f1c;
  --s1: #3987e5; --s2: #d95926; --s3: #199e70;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 14px/1.5 var(--sans); }
main { max-width: 1100px; margin: 0 auto; padding: 28px 16px 56px; display: flex; flex-direction: column; gap: 18px; }
h1 { font-family: var(--serif); font-weight: 400; font-size: 30px; margin: 0; }
h2 { font-size: 17px; font-weight: 600; margin: 0; }
.lede { font-size: 17px; margin: 4px 0 0; max-width: 62ch; }
.lede b { font-weight: 600; }
.meta { color: var(--muted); font-size: 12.5px; margin: 4px 0 0; }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 18px; min-width: 0; }
.sub { color: var(--muted); font-size: 12.5px; margin: 2px 0 12px; max-width: 75ch; }
.control { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; padding: 12px 18px; }
.control label { font-weight: 600; }
.control input { flex: 1 1 180px; min-width: 0; accent-color: var(--fg); }
.control output { font-weight: 600; font-variant-numeric: tabular-nums; min-width: 3.5em; }
.control .hint { flex-basis: 100%; color: var(--muted); font-size: 12.5px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }
.card { display: flex; flex-direction: column; gap: 4px; }
.card .name { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.card .rank { margin-left: auto; color: var(--muted); font-weight: 400; font-size: 12.5px; }
.card .big { font-family: var(--serif); font-size: 40px; line-height: 1.1; font-variant-numeric: tabular-nums; }
.card .bigsub { color: var(--muted); font-size: 12.5px; }
.chip { align-self: flex-start; border-radius: 999px; padding: 2px 10px; font-size: 12.5px; font-weight: 600; }
.chip.ok { background: var(--ok-bg); color: var(--ok); } .chip.bad { background: var(--bad-bg); color: var(--bad); }
.mini { display: grid; grid-template-columns: 1fr auto auto; gap: 2px 8px; margin-top: 8px; font-size: 12.5px; font-variant-numeric: tabular-nums; }
.mini .k { color: var(--muted); }
.ic.ok { color: var(--ok); } .ic.bad { color: var(--bad); }
.prod { margin-top: 4px; color: var(--muted); font-size: 12.5px; }
.prod b { color: var(--fg); font-weight: 600; }
.sw { width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex: none; }
.tablewrap { overflow-x: auto; }
table { border-collapse: separate; border-spacing: 3px; width: 100%; min-width: 540px; font-variant-numeric: tabular-nums; }
th { font-size: 12.5px; color: var(--muted); font-weight: 600; text-align: left; padding: 4px 8px; white-space: nowrap; }
th.m { text-align: center; } th.m span { display: inline-flex; align-items: center; gap: 6px; }
td { padding: 7px 8px; border-radius: 6px; white-space: nowrap; }
td.how { color: var(--muted); font-size: 12.5px; }
td.v { text-align: center; } td.v.ok { background: var(--ok-bg); } td.v.bad { background: var(--bad-bg); }
td.v.best .num { font-weight: 700; }
tr.grp td { padding-top: 12px; font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; font-weight: 600; }
tr.area td.lab { font-weight: 600; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 16px; font-size: 12.5px; color: var(--muted); margin-bottom: 8px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend .ref { width: 0; height: 12px; border-left: 2px solid var(--ref); }
.chart { position: relative; }
.chart svg { display: block; width: 100%; height: auto; overflow: visible; }
.chart text { fill: var(--muted); font-size: 12px; font-family: var(--sans); }
.chart text.lab { fill: var(--fg); font-size: 12.5px; }
.tip { position: absolute; pointer-events: none; background: var(--panel); border: 1px solid var(--line);
  box-shadow: 0 6px 20px rgba(0,0,0,.15); border-radius: 8px; padding: 8px 10px; font-size: 12.5px; min-width: 190px; z-index: 5; }
.tip .t { font-weight: 600; margin-bottom: 4px; }
.tip .r { display: flex; justify-content: space-between; gap: 12px; }
.tip .r span { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); }
.tip .r b { font-weight: 600; font-variant-numeric: tabular-nums; }
details { color: var(--muted); font-size: 12.5px; }
summary { cursor: pointer; }
details ul { padding-left: 18px; margin: 8px 0 0; max-width: 75ch; }
details li { margin: 4px 0; }
</style>
</head>
<body>
<main>
  <header>
    <h1>Label extraction scorecard</h1>
    <p class="lede" id="lede"></p>
    <p class="meta" id="meta"></p>
  </header>

  <div class="panel control">
    <label for="target">Pass mark</label>
    <input type="range" id="target" min="50" max="100" step="1">
    <output id="target-val" for="target"></output>
    <span class="hint">The pass mark decides ✓ or ✗. Accuracy percentages stay the same; what changes is which models and fields pass, and how many products count as mostly right.</span>
  </div>

  <div class="cards" id="cards"></div>

  <section class="panel">
    <h2>Scorecard</h2>
    <p class="sub">Share of values each model got right. Green ✓ meets the pass mark, red ✗ is below it; the best model in each row is in bold. Hover a cell for the counts.</p>
    <div class="tablewrap">
      <table aria-label="Accuracy per area and field for each model">
        <thead><tr id="thead"></tr></thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
  </section>

  <section class="panel">
    <h2>Products mostly right</h2>
    <p class="sub">Products where at least <span class="tval"></span> of their checks are correct, out of all products compared.</p>
    <div class="chart" id="c-products"></div>
  </section>

  <section class="panel">
    <h2>Nutrients on 50+ products</h2>
    <p class="sub">Value, unit and qualifier must all match. The vertical line is the pass mark. Hover a row for the numbers.</p>
    <div class="legend" id="nut-legend"></div>
    <div class="chart" id="c-nut"></div>
  </section>

  <details>
    <summary>How the checking works</summary>
    <ul>
      <li>Each model read photos of the same product labels. People typed the same labels by hand; that is the ground truth.</li>
      <li>Products are matched across files by their product ID. Products not in every file (such as F406) are left out.</li>
      <li>Text fields (name, brand, manufacturer, country, package type, ingredients, other label info) are graded by the judge model, which sees the models only as A, B and C.</li>
      <li>Numbers and codes (nutrients, barcode, sizes, category, nutrition basis) must match exactly; 1.5 l equals 1500 ml.</li>
      <li>A partly correct answer for ingredients or other label info counts as not correct. Fields empty in the ground truth and in every model are not counted.</li>
      <li>When all models disagree with the ground truth on the same value, the ground truth or the unit may be the problem.</li>
    </ul>
  </details>
</main>

<script>
const D = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const MODELS = D.models;
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const color = (i) => css("--s" + (i + 1));
const acc = (c) => (c && c[1] ? (100 * c[0]) / c[1] : null);
const pct = (v) => (v == null ? "—" : v.toFixed(1) + "%");
const int = (n) => n.toLocaleString("en-US");
const AREA_HOW = { overall: "all checks", nutrients: "exact check", codes: "exact check", text: "LLM judge" };
const AREA_LABEL = { overall: "Overall", nutrients: "Nutrient values", codes: "Codes and sizes", text: "Text fields" };
const area = (k) => D.areas.find((a) => a.key === k);

let T = Math.round(D.target * 100);
try { const s = +localStorage.getItem("scorecard-target"); if (s >= 50 && s <= 100) T = s; } catch (e) {}

function el(tag, attrs = {}, parent, text) {
  const e = ["svg", "line", "text", "circle", "path", "rect", "g"].includes(tag)
    ? document.createElementNS(NS, tag) : document.createElement(tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text != null) e.textContent = text;
  if (parent) parent.appendChild(e);
  return e;
}
function swatch(i, parent) { const s = el("i", { class: "sw" }, parent); s.style.background = color(i); return s; }
function measure(texts) { let w = 0; texts.forEach((t) => (w = Math.max(w, t.getComputedTextLength()))); return w; }
function productsPassing(i) { return D.product_scores[i].filter(([k, n]) => n && (100 * k) / n >= T).length; }

function header() {
  const overall = area("overall").counts.map(acc);
  const best = overall.indexOf(Math.max(...overall));
  const nutPass = area("nutrients").counts.map(acc).filter((v) => v >= T).length;
  const txtPass = area("text").counts.map(acc).filter((v) => v >= T).length;
  const L = document.getElementById("lede"); L.replaceChildren();
  el("b", {}, L, MODELS[best]);
  L.append(" reads labels most accurately, with ");
  el("b", {}, L, pct(overall[best]));
  L.append(` of all checks correct. ${nutPass} of ${MODELS.length} models meet the ${T}% pass mark on nutrient values, and ${txtPass} of ${MODELS.length} on text fields.`);
  document.getElementById("meta").textContent =
    `${int(D.products)} food products · ground truth typed by people · text graded by ${D.judge}, numbers and codes checked exactly · generated ${D.when}`;
  document.getElementById("target-val").textContent = T + "%";
  document.querySelectorAll(".tval").forEach((e) => (e.textContent = T + "%"));
}

function cards() {
  const box = document.getElementById("cards"); box.replaceChildren();
  const overall = area("overall").counts.map(acc);
  MODELS.forEach((m, i) => {
    const c = el("div", { class: "panel card" }, box);
    const nm = el("div", { class: "name" }, c); swatch(i, nm); el("span", {}, nm, m);
    el("span", { class: "rank" }, nm, `#${1 + overall.filter((v) => v > overall[i]).length} of ${MODELS.length}`);
    el("div", { class: "big" }, c, pct(overall[i]));
    el("div", { class: "bigsub" }, c, "of all checks correct");
    const ok = overall[i] >= T;
    el("span", { class: "chip " + (ok ? "ok" : "bad") }, c, (ok ? "✓ Meets " : "✗ Below ") + T + "% pass mark");
    const mini = el("div", { class: "mini" }, c);
    ["nutrients", "codes", "text"].forEach((k) => {
      const v = acc(area(k).counts[i]), pass = v >= T;
      el("span", { class: "k" }, mini, k === "nutrients" ? "Nutrients" : AREA_LABEL[k]);
      el("span", {}, mini, pct(v));
      el("span", { class: "ic " + (pass ? "ok" : "bad"), "aria-label": pass ? "meets pass mark" : "below pass mark" }, mini, pass ? "✓" : "✗");
    });
    const p = el("div", { class: "prod" }, c);
    el("b", {}, p, int(productsPassing(i)));
    p.append(` of ${int(D.products)} products at least ${T}% right`);
  });
}

function scorecard() {
  const th = document.getElementById("thead"); th.replaceChildren();
  el("th", {}, th, "Area or field"); el("th", {}, th, "Checked by");
  MODELS.forEach((m, i) => { const h = el("th", { class: "m" }, th); const s = el("span", {}, h); swatch(i, s); s.append(m); });
  const tb = document.getElementById("tbody"); tb.replaceChildren();
  const group = (label) => { const tr = el("tr", { class: "grp" }, tb); el("td", { colspan: 2 + MODELS.length }, tr, label); };
  const line = (label, how, counts, cls) => {
    const tr = el("tr", { class: cls }, tb);
    el("td", { class: "lab" }, tr, label); el("td", { class: "how" }, tr, how);
    const vals = counts.map(acc), best = Math.max(...vals.filter((v) => v != null));
    vals.forEach((v, i) => {
      if (v == null) { el("td", { class: "v" }, tr, "—"); return; }
      const pass = v >= T;
      const td = el("td", { class: "v " + (pass ? "ok" : "bad") + (v === best ? " best" : ""),
        title: `${MODELS[i]}: ${int(counts[i][0])} of ${int(counts[i][1])} correct` }, tr);
      el("span", { class: "ic " + (pass ? "ok" : "bad") }, td, pass ? "✓ " : "✗ ");
      el("span", { class: "num" }, td, pct(v));
    });
  };
  group("Areas");
  ["overall", "nutrients", "codes", "text"].forEach((k) => line(AREA_LABEL[k], AREA_HOW[k], area(k).counts, "area"));
  group("Fields");
  D.fields.forEach((f) => line(f.label, f.method, f.counts, "field"));
}

function productsChart() {
  const host = document.getElementById("c-products"); host.replaceChildren();
  const W = host.clientWidth || 600, barH = 18, gap = 16, total = D.products;
  const H = 6 + MODELS.length * (barH + gap);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Products with at least ${T}% of checks correct, per model` }, host);
  const labs = MODELS.map((m, i) => el("text", { class: "lab", y: 6 + i * (barH + gap) + barH / 2 + 4, "text-anchor": "end" }, svg, m));
  const labelW = Math.min(measure(labs) + 14, W * 0.4); labs.forEach((t) => t.setAttribute("x", labelW - 10));
  const probe = el("text", {}, svg, `${int(total)} (100%)`); const valW = probe.getComputedTextLength() + 12; probe.remove();
  const x = (v) => labelW + (v / total) * Math.max(40, W - valW - labelW);
  el("line", { x1: x(total), x2: x(total), y1: 0, y2: H - gap / 2, stroke: css("--grid") }, svg);
  MODELS.forEach((m, i) => {
    const n = productsPassing(i), y = 6 + i * (barH + gap), w = x(n) - labelW, r = Math.min(4, barH / 2, w);
    if (w > 0) el("path", { fill: color(i), d: `M${labelW},${y}H${labelW + w - r}Q${labelW + w},${y} ${labelW + w},${y + r}V${y + barH - r}Q${labelW + w},${y + barH} ${labelW + w - r},${y + barH}H${labelW}Z` }, svg);
    el("text", { x: x(n) + 6, y: y + barH / 2 + 4 }, svg, `${int(n)} (${Math.round((100 * n) / total)}%)`);
  });
}

function pretty(n) {
  const units = { g: "g", mg: "mg", kcal: "kcal", kj: "kJ" };
  const p = n.split("_"), u = units[p[p.length - 1]];
  const name = (u ? p.slice(0, -1) : p).join(" ").replace(/^vitamin (\w+)/, (m, v) => "vitamin " + v.toUpperCase());
  return name.charAt(0).toUpperCase() + name.slice(1) + (u ? ` (${u})` : "");
}

function nutrientChart() {
  const lg = document.getElementById("nut-legend"); lg.replaceChildren();
  MODELS.forEach((m, i) => { const s = el("span", {}, lg); swatch(i, s); s.append(m); });
  const r = el("span", {}, lg); el("i", { class: "ref" }, r); r.append("Pass mark");
  const host = document.getElementById("c-nut"); host.replaceChildren();
  const rows = D.nutrients.filter((n) => n.n >= 50).sort((a, b) => b.n - a.n);
  const W = host.clientWidth || 600, rowH = 26, top = 24, H = top + rows.length * rowH + 8;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Accuracy per nutrient for each model" }, host);
  const gridG = el("g", {}, svg);
  const hover = el("rect", { x: 0, width: W, height: rowH, rx: 6, fill: css("--grid"), opacity: 0 }, gridG);
  const labs = rows.map((n, i) => el("text", { class: "lab", y: top + i * rowH + rowH / 2 + 4, "text-anchor": "end" }, svg, pretty(n.label)));
  const labelW = Math.min(measure(labs) + 14, W * 0.45); labs.forEach((t) => t.setAttribute("x", labelW - 10));
  const all = rows.flatMap((n) => n.counts.map(acc)).filter((v) => v != null);
  const lo = Math.min(T, Math.floor(Math.min(...all) / 10) * 10);
  const x = (v) => labelW + ((v - lo) / (100 - lo)) * (W - 12 - labelW);
  const step = W < 420 ? 20 : 10;
  for (let v = Math.ceil(lo / step) * step; v <= 100; v += step) {
    el("line", { x1: x(v), x2: x(v), y1: top - 4, y2: H - 6, stroke: css("--grid") }, gridG);
    el("text", { x: x(v), y: top - 10, "text-anchor": "middle" }, svg, v + "%");
  }
  el("line", { x1: x(T), x2: x(T), y1: top - 4, y2: H - 6, stroke: css("--ref"), "stroke-width": 2 }, svg);
  const tip = el("div", { class: "tip" }, host); tip.hidden = true;
  rows.forEach((n, i) => {
    const cy = top + i * rowH + rowH / 2, vals = n.counts.map(acc), present = vals.filter((v) => v != null);
    el("line", { x1: x(Math.min(...present)), x2: x(Math.max(...present)), y1: cy, y2: cy, stroke: css("--range"), "stroke-width": 2 }, svg);
    vals.forEach((v, mi) => { if (v != null) el("circle", { cx: x(v), cy, r: 5, fill: color(mi), stroke: css("--panel"), "stroke-width": 2 }, svg); });
    const hit = el("rect", { x: 0, y: cy - rowH / 2, width: W, height: rowH, fill: "transparent" }, svg);
    hit.addEventListener("mousemove", (ev) => {
      hover.setAttribute("y", cy - rowH / 2); hover.setAttribute("opacity", 0.6);
      tip.replaceChildren(); tip.hidden = false;
      el("div", { class: "t" }, tip, `${pretty(n.label)} · ${int(n.n)} products`);
      MODELS.forEach((m, mi) => {
        const row = el("div", { class: "r" }, tip), s = el("span", {}, row); swatch(mi, s); s.append(m);
        const v = vals[mi];
        el("b", {}, row, v == null ? "—" : `${pct(v)} (${int(n.counts[mi][0])}/${int(n.counts[mi][1])}) ${v >= T ? "✓" : "✗"}`);
      });
      const b = host.getBoundingClientRect(), mx = ev.clientX - b.left, my = ev.clientY - b.top;
      tip.style.left = Math.max(0, Math.min(mx + 12, host.clientWidth - tip.offsetWidth)) + "px";
      tip.style.top = my + 14 + "px";
    });
    hit.addEventListener("mouseleave", () => { hover.setAttribute("opacity", 0); tip.hidden = true; });
  });
}

function drawAll() { header(); cards(); scorecard(); productsChart(); nutrientChart(); }

const slider = document.getElementById("target");
slider.value = T;
slider.addEventListener("input", () => {
  T = +slider.value;
  try { localStorage.setItem("scorecard-target", String(T)); } catch (e) {}
  drawAll();
});
drawAll();
let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(drawAll, 120); });
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", drawAll);
</script>
</body>
</html>
"""

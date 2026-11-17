"""Builds a self-contained HTML report (charts + tables) from the judge results.
Called by judge_eval.py; opens in any browser, no internet needed."""
import json

def write_report(path, data):
    html = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Extraction Accuracy Report</title>
<style>
:root {
  color-scheme: light;
  --bg: #f4f3f0; --surface: #fcfcfb; --grid: #e6e5e0; --band: #f0efec;
  --text: #0b0b0b; --text-2: #52514e; --muted: #7a7974;
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100; --s5: #e87ba4;
  --neutral: #6f6e69; --good: #0ca30c; --good-text: #006300; --critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --bg: #111110; --surface: #1a1a19; --grid: #2e2e2c; --band: #242422;
    --text: #f0efec; --text-2: #c3c2b7; --muted: #8f8e86;
    --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --s5: #d55181;
    --neutral: #9a9990; --good: #0ca30c; --good-text: #3fc23f; --critical: #e66767;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #111110; --surface: #1a1a19; --grid: #2e2e2c; --band: #242422;
  --text: #f0efec; --text-2: #c3c2b7; --muted: #8f8e86;
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --s5: #d55181;
  --neutral: #9a9990; --good: #0ca30c; --good-text: #3fc23f; --critical: #e66767;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1080px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 24px; margin: 0 0 4px; font-weight: 650; }
h2 { font-size: 17px; margin: 0 0 2px; font-weight: 600; }
.sub { color: var(--text-2); margin: 0; }
.muted { color: var(--muted); }
.card { background: var(--surface); border-radius: 12px; padding: 20px; margin-top: 16px;
  box-shadow: 0 0 0 1px var(--grid); }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 20px; }
.tile { background: var(--surface); border-radius: 12px; padding: 16px; box-shadow: 0 0 0 1px var(--grid); }
.tile .label { display: flex; align-items: center; gap: 8px; color: var(--text-2); font-size: 13px; }
.tile .value { font-size: 30px; font-weight: 600; margin: 4px 0 2px; font-variant-numeric: tabular-nums; }
.tile .detail { color: var(--text-2); font-size: 12.5px; }
.swatch { width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex: none; }
.status { display: inline-flex; align-items: center; gap: 4px; font-size: 12.5px; font-weight: 600; margin-top: 6px; }
.status.ok { color: var(--good-text); } .status.bad { color: var(--critical); }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 12px 0 4px; font-size: 13px; color: var(--text-2); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend .line { width: 14px; height: 0; border-top: 2px solid var(--text-2); }
.chart { position: relative; width: 100%; margin-top: 8px; }
.chart svg { display: block; width: 100%; height: auto; overflow: visible; }
.chart text { fill: var(--text-2); font-size: 12px; }
.chart .lab { fill: var(--text); font-size: 12.5px; }
.chart .small { fill: var(--muted); font-size: 11px; }
.chart .val { fill: var(--text-2); font-size: 11px; font-variant-numeric: tabular-nums; }
select { font: inherit; color: var(--text); background: var(--surface); border: 1px solid var(--grid);
  border-radius: 6px; padding: 4px 8px; }
details { margin-top: 14px; }
summary { cursor: pointer; color: var(--text-2); font-size: 13px; }
.tablewrap { overflow-x: auto; margin-top: 8px; }
table { border-collapse: collapse; font-size: 12.5px; min-width: 100%; font-variant-numeric: tabular-nums; }
th, td { text-align: right; padding: 4px 10px; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
th { color: var(--text-2); font-weight: 600; }
.notes { color: var(--text-2); font-size: 13px; padding-left: 18px; margin: 8px 0 0; }
.notes li { margin: 4px 0; }
.tip { position: fixed; pointer-events: none; z-index: 10; background: var(--surface); color: var(--text);
  box-shadow: 0 0 0 1px var(--grid), 0 6px 20px rgba(0,0,0,.15); border-radius: 8px; padding: 8px 10px;
  font-size: 12.5px; min-width: 180px; display: none; }
.tip .t { font-weight: 600; margin-bottom: 4px; }
.tip .r { display: flex; align-items: center; gap: 6px; justify-content: space-between; }
.tip .r span:first-child { display: inline-flex; align-items: center; gap: 6px; color: var(--text-2); }
.tip .r b { font-weight: 600; font-variant-numeric: tabular-nums; }
</style>
</head>
<body>
<main>
  <h1>Extraction accuracy vs human ground truth</h1>
  <p class="sub" id="meta"></p>
  <div class="tiles" id="tiles"></div>

  <section class="card">
    <h2>Accuracy by area</h2>
    <p class="sub">Share of checked values that match the ground truth. The line marks the <span class="target-txt"></span> target.</p>
    <div class="legend models"></div>
    <div class="chart" id="c-areas"></div>
    <details><summary>Show table</summary><div class="tablewrap" id="t-areas"></div></details>
  </section>

  <section class="card">
    <h2>Accuracy per product field</h2>
    <p class="sub">Text fields are graded by the LLM judge; numbers, codes and sizes are checked exactly in code.</p>
    <div class="legend models"></div>
    <div class="chart" id="c-fields"></div>
    <details><summary>Show table</summary><div class="tablewrap" id="t-fields"></div></details>
  </section>

  <section class="card">
    <h2>Accuracy per nutrient</h2>
    <p class="sub">Value, unit and qualifier must all match. Shown: nutrients found on at least 20 products, most common first.</p>
    <div class="legend models"></div>
    <div class="chart" id="c-nut"></div>
    <details><summary>Show table (all nutrients, including rare ones)</summary><div class="tablewrap" id="t-nut"></div></details>
  </section>

</main>
<div class="tip" id="tip"></div>

<script>
const D = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const M = D.models.length;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const color = i => css("--s" + (i + 1));
const pct = (v, d = 1) => v == null ? "–" : (v * 100).toFixed(d) + "%";
const acc = c => c[1] ? c[0] / c[1] : null;
const fmtN = n => n.toLocaleString("en-US");
const tgt = D.target;

function el(tag, attrs, parent, text) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text != null) e.textContent = text;
  if (parent) parent.appendChild(e);
  return e;
}
function h(tag, attrs = {}, html = "") {
  const e = document.createElement(tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  e.innerHTML = html;
  return e;
}
// bar with 4px rounded data-end, square at the baseline
function barPath(x0, x1, y, hgt) {
  const w = Math.max(0, x1 - x0), r = Math.min(4, hgt / 2, w);
  if (w <= 0) return "";
  return `M${x0},${y}H${x1 - r}Q${x1},${y} ${x1},${y + r}V${y + hgt - r}Q${x1},${y + hgt} ${x1 - r},${y + hgt}H${x0}Z`;
}
function niceTicks(max) {
  const raw = max / 4, p = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  const step = [1, 2, 5, 10].map(s => s * p).find(s => raw <= s);
  const t = []; for (let v = 0; v <= max + 1e-9; v += step) t.push(v);
  if (t[t.length - 1] < max) t.push(t[t.length - 1] + step);
  return t;
}

// ---------- tooltip
const tip = document.getElementById("tip");
function showTip(ev, title, rows) {
  tip.innerHTML = `<div class="t">${title}</div>` + rows.map(r =>
    `<div class="r"><span>${r.color ? `<i class="swatch" style="background:${r.color}"></i>` : ""}${r.name}</span><b>${r.value}</b></div>`).join("");
  tip.style.display = "block";
  const pad = 14, w = tip.offsetWidth, hh = tip.offsetHeight;
  let x = ev.clientX + pad, y = ev.clientY + pad;
  if (x + w > innerWidth - 8) x = ev.clientX - w - pad;
  if (y + hh > innerHeight - 8) y = ev.clientY - hh - pad;
  tip.style.left = Math.max(8, x) + "px"; tip.style.top = Math.max(8, y) + "px";
}
const hideTip = () => tip.style.display = "none";

// ---------- grouped horizontal bars
// cats: [{label, sub, counts:[[ok,n] or value per series]}], series: [{name,color}]
function hbar(host, cats, series, o) {
  host.innerHTML = "";
  const W = host.clientWidth, labelW = Math.min(o.labelW || 180, W * 0.4), right = 52;
  const plotW = Math.max(60, W - labelW - right);
  const S = series.length, barH = S > 1 ? 10 : 14, gap = 2, padB = 9;
  const bandH = S * barH + (S - 1) * gap + padB * 2, top = 26;
  const H = top + cats.length * bandH + 6;
  const max = o.max;
  const x = v => labelW + Math.max(0, Math.min(1, v / max)) * plotW;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": o.aria });
  host.appendChild(svg);
  const ticks = o.ticks || niceTicks(max);
  ticks.forEach(t => {
    el("line", { x1: x(t), x2: x(t), y1: top - 4, y2: H - 6, stroke: css("--grid"), "stroke-width": 1 }, svg);
    el("text", { x: x(t), y: top - 10, "text-anchor": "middle", class: "small" }, svg, o.tickFmt(t));
  });
  const hover = el("rect", { x: 0, width: W, height: bandH, fill: css("--band"), opacity: 0, rx: 6 }, svg);
  svg.insertBefore(hover, svg.firstChild);
  cats.forEach((c, ci) => {
    const y0 = top + ci * bandH;
    const cy = y0 + bandH / 2;
    el("text", { x: labelW - 10, y: c.sub ? cy - 2 : cy + 4, "text-anchor": "end", class: "lab" }, svg, c.label);
    if (c.sub) el("text", { x: labelW - 10, y: cy + 12, "text-anchor": "end", class: "small" }, svg, c.sub);
    series.forEach((s, si) => {
      const v = o.value(c, si);
      const y = y0 + padB + si * (barH + gap);
      if (v == null) { el("text", { x: labelW + 4, y: y + barH - 1, class: "val" }, svg, "–"); return; }
      el("path", { d: barPath(labelW, x(v), y, barH), fill: s.color }, svg);
      el("text", { x: x(v) + 5, y: y + barH - 1, class: "val" }, svg, o.valFmt(v));
    });
    const hit = el("rect", { x: 0, y: y0, width: W, height: bandH, fill: "transparent" }, svg);
    hit.addEventListener("mousemove", ev => {
      hover.setAttribute("y", y0); hover.setAttribute("opacity", 1);
      showTip(ev, c.label, series.map((s, si) => ({ name: s.name, color: s.color, value: o.tipFmt(c, si) })));
    });
    hit.addEventListener("mouseleave", () => { hover.setAttribute("opacity", 0); hideTip(); });
  });
  if (o.target != null) {
    const tx = x(o.target);
    el("line", { x1: tx, x2: tx, y1: top - 4, y2: H - 6, stroke: css("--text-2"), "stroke-width": 1.5 }, svg);
  }
}

// ---------- nutrient dot plot
function dotplot(host, rows) {
  host.innerHTML = "";
  if (!rows.length) { host.innerHTML = '<p class="muted">No nutrients match this filter.</p>'; return; }
  const W = host.clientWidth, labelW = Math.min(230, W * 0.45), right = 12;
  const plotW = Math.max(60, W - labelW - right), rowH = 26, top = 26, H = top + rows.length * rowH + 6;
  const x = v => labelW + v * plotW;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Accuracy per nutrient" });
  host.appendChild(svg);
  const hover = el("rect", { x: 0, width: W, height: rowH, fill: css("--band"), opacity: 0, rx: 6 }, svg);
  [0, .25, .5, .75, 1].forEach(t => {
    el("line", { x1: x(t), x2: x(t), y1: top - 4, y2: H - 6, stroke: css("--grid"), "stroke-width": 1 }, svg);
    el("text", { x: x(t), y: top - 10, "text-anchor": "middle", class: "small" }, svg, (t * 100) + "%");
  });
  const tx = x(tgt);
  el("line", { x1: tx, x2: tx, y1: top - 4, y2: H - 6, stroke: css("--text-2"), "stroke-width": 1.5 }, svg);
  rows.forEach((r, ri) => {
    const cy = top + ri * rowH + rowH / 2;
    el("text", { x: labelW - 10, y: cy + 4, "text-anchor": "end", class: "lab" }, svg, r.label);
    el("text", { x: labelW - 10 - 0, y: cy + 4, "text-anchor": "start", class: "small", dx: 4 }, svg, "");
    const vals = r.counts.map(acc);
    const lo = Math.min(...vals.filter(v => v != null)), hi = Math.max(...vals.filter(v => v != null));
    el("line", { x1: x(lo), x2: x(hi), y1: cy, y2: cy, stroke: css("--grid"), "stroke-width": 2 }, svg);
    vals.forEach((v, i) => {
      if (v == null) return;
      el("circle", { cx: x(v), cy, r: 5, fill: color(i), stroke: css("--surface"), "stroke-width": 2 }, svg);
    });
    const hit = el("rect", { x: 0, y: cy - rowH / 2, width: W, height: rowH, fill: "transparent" }, svg);
    hit.addEventListener("mousemove", ev => {
      hover.setAttribute("y", cy - rowH / 2); hover.setAttribute("opacity", 1);
      showTip(ev, `${r.label} · ${fmtN(r.n)} products`, D.models.map((m, i) => ({
        name: m, color: color(i), value: `${pct(acc(r.counts[i]))}  (${fmtN(r.counts[i][0])}/${fmtN(r.counts[i][1])})` })));
    });
    hit.addEventListener("mouseleave", () => { hover.setAttribute("opacity", 0); hideTip(); });
  });
}

// ---------- tables
function table(host, head, rows) {
  host.innerHTML = "<table><thead><tr>" + head.map(x => `<th>${x}</th>`).join("") + "</tr></thead><tbody>" +
    rows.map(r => "<tr>" + r.map(c => `<td>${c}</td>`).join("") + "</tr>").join("") + "</tbody></table>";
}
const modelHead = D.models.flatMap(m => [m, `${m} ✓/checked`]);
const modelCells = counts => counts.flatMap(c => [pct(acc(c)), `${fmtN(c[0])}/${fmtN(c[1])}`]);

// ---------- page
function series() { return D.models.map((m, i) => ({ name: m, color: color(i) })); }
function legend() {
  document.querySelectorAll(".legend.models").forEach(l => {
    l.innerHTML = D.models.map((m, i) => `<span><i class="swatch" style="background:${color(i)}"></i>${m}</span>`).join("")
      + `<span><i class="line"></i>${pct(tgt, 0)} target</span>`;
  });
}
const accOpts = {
  max: 1, ticks: [0, .25, .5, .75, 1], tickFmt: t => (t * 100) + "%", target: tgt,
  value: (c, i) => acc(c.counts[i]), valFmt: v => pct(v),
  tipFmt: (c, i) => `${pct(acc(c.counts[i]))}  (${fmtN(c.counts[i][0])}/${fmtN(c.counts[i][1])})`,
};

function header() {
  document.getElementById("meta").textContent =
    `Judge: ${D.judge} · ${fmtN(D.products)} products compared · ${D.models.length} models · target ${pct(tgt, 0)} · generated ${D.when}`;
  document.querySelectorAll(".target-txt").forEach(e => e.textContent = pct(tgt, 0));
  const overall = D.areas.find(a => a.key === "overall").counts.map(acc);
  const nut = D.areas.find(a => a.key === "nutrients").counts.map(acc);
  const txt = D.areas.find(a => a.key === "text").counts.map(acc);
  const best = overall.indexOf(Math.max(...overall));
  const tiles = document.getElementById("tiles"); tiles.innerHTML = "";
  D.models.forEach((m, i) => {
    const ok = overall[i] >= tgt;
    tiles.appendChild(h("div", { class: "tile" }, `
      <div class="label"><i class="swatch" style="background:${color(i)}"></i>${m}${i === best ? " · best overall" : ""}</div>
      <div class="value">${pct(overall[i])}</div>
      <div class="detail">overall accuracy · nutrients ${pct(nut[i])} · text ${pct(txt[i])}</div>
      <div class="detail">${fmtN(D.pass_products[i])} of ${fmtN(D.products)} products ≥ ${pct(tgt, 0)} correct</div>
      <div class="status ${ok ? "ok" : "bad"}">${ok ? "✓ Meets" : "✗ Below"} ${pct(tgt, 0)} target</div>`));
  });
}

function nutrientRows() {
  return D.nutrients.filter(n => n.n >= 20).sort((a, b) => b.n - a.n);
}

function draw() {
  const S = series();
  legend();
  header();
  hbar(document.getElementById("c-areas"), D.areas.map(a => ({ label: a.label, sub: `${fmtN(Math.max(...a.counts.map(c => c[1])))} checks`, counts: a.counts })),
    S, { ...accOpts, labelW: 190, aria: "Accuracy by area" });
  hbar(document.getElementById("c-fields"), D.fields.map(f => ({ label: f.label, sub: `${f.method} · ${fmtN(Math.max(...f.counts.map(c => c[1])))}`, counts: f.counts })),
    S, { ...accOpts, labelW: 170, aria: "Accuracy per product field" });
  dotplot(document.getElementById("c-nut"), nutrientRows());
}

function tables() {
  table(document.getElementById("t-areas"), ["Area", ...modelHead], D.areas.map(a => [a.label, ...modelCells(a.counts)]));
  table(document.getElementById("t-fields"), ["Field", "Graded by", ...modelHead], D.fields.map(f => [f.label, f.method, ...modelCells(f.counts)]));
  table(document.getElementById("t-nut"), ["Nutrient", "Products", ...modelHead],
    D.nutrients.slice().sort((a, b) => b.n - a.n).map(n => [n.label, fmtN(n.n), ...modelCells(n.counts)]));
}

tables();
draw();
let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(draw, 120); });
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", draw);
new MutationObserver(draw).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
</script>
</body>
</html>
"""

"""Interactive page: one self-contained HTML file (data inlined, Plotly from a CDN)
that can be embedded into the blog with a single <iframe>. Everything is computed here
in Python; the page only draws."""

import json
from pathlib import Path

import pandas as pd

from . import analysis, quote
from .config import CURRENCY_NAMES, HORIZONS

PLOTLY_CDN = "https://cdn.jsdelivr.net/npm/plotly.js-basic-dist-min@2.35.2/plotly-basic.min.js"


def _r(values, digits: int = 5) -> list:
    return [None if pd.isna(v) else round(float(v), digits) for v in values]


def payload(result: analysis.Result, bt: pd.DataFrame | None, source_note: str) -> dict:
    """JSON-ready data for the page; `bt` may be None while the history is too short."""
    data = {
        "as_of": result.as_of.strftime("%Y-%m-%d"),
        "source_note": source_note,
        "base": result.base,
        "horizons": list(HORIZONS),
        "performance": [
            {
                "code": c,
                "name": CURRENCY_NAMES[c],
                "returns": _r(result.returns.loc[c], 6),
                "zscore": _r([result.trend.at[c, "zscore"]], 3)[0],
                "signal": result.trend.at[c, "signal"],
            }
            for c in result.returns.index
        ],
        "quote": None,
    }
    if bt is None:
        return data

    freq = bt.attrs["freq"]
    label = quote.benchmark_label(bt)
    weights = bt.attrs["weights"].resample("W-FRI").last().dropna(how="all")
    status = quote.signal_status(bt)
    comp = quote.comparison(bt)
    annual = quote.annual_returns(bt)
    data["quote"] = {
        "benchmark_label": label,
        "settings": {k: bt.attrs[k] for k in ("lookback", "cap", "smoothing", "lag", "cost_bp", "carry")},
        "dates": bt.index.strftime("%Y-%m-%d").tolist(),
        "value_strategy": _r(bt["value_strategy"]),
        "value_benchmark": _r(bt["value_benchmark"]),
        "dd_strategy": _r(bt["dd_strategy"], 4),
        "dd_benchmark": _r(bt["dd_benchmark"], 4),
        "metrics": [
            {"label": name, "strategy": _r([row["Währungsquote"]], 6)[0], "benchmark": _r([row[label]], 6)[0]}
            for name, row in comp.iterrows()
        ],
        "annual": [
            {"year": int(y), "strategy": _r([r.strategy], 5)[0], "benchmark": _r([r.benchmark], 5)[0]}
            for y, r in annual.iterrows()
        ],
        "turnover_pa": round(float(bt["turnover"].sum() / (len(bt) / freq)), 3),
        "weight_dates": weights.index.strftime("%Y-%m-%d").tolist(),
        "weights": {c: _r(weights[c], 4) for c in weights.columns},
        "status": [
            {
                "code": code,
                "name": row["Währung"],
                "z": _r([row["z-Score"]], 3)[0],
                "base_weight": _r([row["Grundgewicht"]], 5)[0],
                "weight": _r([row["Gewicht"]], 5)[0],
            }
            for code, row in status.iterrows()
        ],
    }
    return data


def render(result: analysis.Result, bt: pd.DataFrame | None, path: Path, source_note: str) -> None:
    data = json.dumps(payload(result, bt, source_note), ensure_ascii=False, separators=(",", ":"))
    html = TEMPLATE.replace("__DATA__", data.replace("</", "<\\/")).replace("__PLOTLY__", PLOTLY_CDN)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


TEMPLATE = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FX Z-Score Signal – interaktiv</title>
<style>
:root{--paper:#fbfaf6;--ink:#1b2330;--soft:#5b6472;--line:#dcdad3;--gold:#b8944a;--neg:#b5523b;--pos:#2f7d6d}
@media (prefers-color-scheme:dark){:root{--paper:#161a20;--ink:#e8e6df;--soft:#9aa3b0;--line:#2c323b;--gold:#d2ad63;--neg:#d9775f;--pos:#4fb39f}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:20px 16px 12px}
h1{font-size:1.4rem;margin:0 0 2px}
h2{font-size:1.05rem;margin:32px 0 4px}
p.sub{margin:0 0 10px;color:var(--soft);font-size:.88rem}
.chart{width:100%;height:420px}
.chart.small{height:300px}
.chart.dd{height:200px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{font-weight:600;color:var(--soft);font-size:.8rem}
.scroll{overflow-x:auto}
.pos{color:var(--pos)}.neg{color:var(--neg)}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 8px}
button{font:inherit;font-size:.82rem;padding:3px 10px;border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:999px;cursor:pointer}
button[aria-pressed=true]{background:var(--ink);color:var(--paper);border-color:var(--ink)}
footer{margin:28px 0 8px;padding-top:10px;border-top:1px solid var(--line);color:var(--soft);font-size:.8rem;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
footer b{color:var(--gold)}
</style>
</head>
<body>
<main>
<h1>Währungen aus Sicht eines Euro-Anlegers</h1>
<p class="sub" id="asof"></p>

<section id="s-quote">
<h2>Währungsquote vs. Korb</h2>
<p class="sub" id="settings"></p>
<div class="tabs" id="range"></div>
<div id="c-value" class="chart"></div>
<div id="c-dd" class="chart dd"></div>

<h2>Kennzahlen</h2>
<div class="scroll"><table id="t-metrics"></table></div>

<h2>Kalenderjahre</h2>
<div id="c-annual" class="chart small"></div>

<h2>Währungsgewichte über die Zeit</h2>
<p class="sub">Summe immer 100 %. Wöchentliche Stichtage.</p>
<div id="c-weights" class="chart"></div>

<h2>Aktuelles Signal</h2>
<p class="sub">z-Score gegen das eigene gleitende Mittel. Hoch = teuer = Untergewicht, tief = billig = Übergewicht.</p>
<div class="scroll"><table id="t-status"></table></div>
</section>

<h2>Wertentwicklung gegenüber dem Euro</h2>
<div class="scroll"><table id="t-perf"></table></div>

<footer><span id="source"></span><b>joshuamaier.de</b></footer>
</main>
<script src="__PLOTLY__"></script>
<script>
const D = __DATA__;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const pct = (x, d = 1, sign = true) => x == null ? "–" : ((sign && x > 0 ? "+" : "") + (x * 100).toFixed(d) + " %").replace(".", ",").replace("-", "−");
const num = (x, d = 2, sign = false) => x == null ? "–" : ((sign && x > 0 ? "+" : "") + x.toFixed(d)).replace(".", ",").replace("-", "−");
const cls = x => x == null ? "" : x > 0 ? "pos" : x < 0 ? "neg" : "";
const el = id => document.getElementById(id);
const PCT_KEYS = ["Gesamtrendite", "Rendite p. a.", "Volatilität p. a.", "Max. Drawdown", "Schlechtester Tag", "Positive Tage"];
const cfg = {displayModeBar: false, responsive: true};
let rangeFrom = null;

document.title = "FX Z-Score Signal – " + D.as_of;
el("asof").textContent = "Stand " + D.as_of.split("-").reverse().join(".") + " · Basis " + D.base;
el("source").textContent = D.source_note;

function layout(extra) {
  return Object.assign({
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: {color: css("--soft"), size: 12, family: "system-ui,sans-serif"},
    margin: {l: 52, r: 12, t: 8, b: 32}, hovermode: "x unified",
    xaxis: {gridcolor: css("--line"), zeroline: false},
    yaxis: {gridcolor: css("--line"), zeroline: false},
    legend: {orientation: "h", y: 1.1, x: 0}
  }, extra || {});
}

function perfTable() {
  const head = "<tr><th>Währung</th>" + D.horizons.map(h => "<th>" + h + "</th>").join("") + "<th>z-Score</th></tr>";
  const rows = D.performance.map(p => "<tr><td>" + p.name + " (" + p.code + ")</td>" +
    p.returns.map(r => "<td class='" + cls(r) + "'>" + pct(r) + "</td>").join("") +
    "<td>" + num(p.zscore, 2, true) + "</td></tr>").join("");
  el("t-perf").innerHTML = head + rows;
}

function drawValue() {
  const Q = D.quote;
  const i = Q.dates.findIndex(d => d >= rangeFrom);
  const idx = i < 0 ? 0 : i;
  const xs = Q.dates.slice(idx);
  // Value lines are rebased to 1 at the start of the chosen range; drawdowns keep
  // measuring against the peak of the whole backtest.
  const rebase = a => a.slice(idx).map(v => v / a[idx]);
  const line = (y, name, color, width, extra) => Object.assign({x: xs, y, name, type: "scatter", mode: "lines", line: {color, width}}, extra || {});
  Plotly.react("c-value", [
    line(rebase(Q.value_benchmark), Q.benchmark_label, css("--soft"), 1.6),
    line(rebase(Q.value_strategy), "Währungsquote", css("--pos"), 2.2)
  ], layout({yaxis: {type: "log", gridcolor: css("--line"), title: {text: "Wert (Start = 1, log)"}}}), cfg);
  Plotly.react("c-dd", [
    line(Q.dd_benchmark.slice(idx), "Drawdown Korb", css("--soft"), 1),
    line(Q.dd_strategy.slice(idx), "Drawdown Währungsquote", css("--neg"), 1.2, {fill: "tozeroy", fillcolor: "rgba(181,82,59,.15)"})
  ], layout({yaxis: {gridcolor: css("--line"), tickformat: ".0%", title: {text: "Drawdown"}}}), cfg);
}

function quoteSection() {
  const Q = D.quote;
  if (!Q) { el("s-quote").style.display = "none"; return; }
  const s = Q.settings;
  el("settings").textContent = `Lookback ${s.lookback} T · Kappung ${num(s.cap)}σ · Glättung ${s.smoothing} T · Versatz ${s.lag} T · Kosten ${s.cost_bp} bp · ${s.carry ? "mit Carry (Leitzinsen)" : "ohne Carry"} · Umschlag ${num(Q.turnover_pa, 1)}× p. a.`;

  const last = Q.dates[Q.dates.length - 1];
  const ago = y => { const d = new Date(last); d.setFullYear(d.getFullYear() - y); return d.toISOString().slice(0, 10); };
  const ranges = [["Alles", Q.dates[0]], ["10 J", ago(10)], ["5 J", ago(5)], ["3 J", ago(3)], ["1 J", ago(1)]];
  if (rangeFrom === null) rangeFrom = ranges[0][1];
  el("range").innerHTML = "";
  ranges.forEach(([label, from]) => {
    const b = document.createElement("button");
    b.textContent = label; b.setAttribute("aria-pressed", from === rangeFrom);
    b.onclick = () => { rangeFrom = from; [...el("range").children].forEach(c => c.setAttribute("aria-pressed", c === b)); drawValue(); };
    el("range").appendChild(b);
  });
  drawValue();

  const bl = Q.benchmark_label;
  el("t-metrics").innerHTML = "<tr><th>Kennzahl</th><th>Währungsquote</th><th>" + bl + "</th><th>Differenz</th></tr>" +
    Q.metrics.map(m => {
      const isPct = PCT_KEYS.includes(m.label);
      const f = v => m.label.startsWith("Zeitraum") ? num(v, 1) : isPct ? pct(v, m.label.includes("Tag") ? 2 : 1, false) : num(v, 2);
      const d = m.strategy == null || m.benchmark == null ? null : m.strategy - m.benchmark;
      const df = d == null ? "–" : m.label.startsWith("Zeitraum") ? "" : isPct ? pct(d, 1) : num(d, 2, true);
      return "<tr><td>" + m.label + "</td><td>" + f(m.strategy) + "</td><td>" + f(m.benchmark) + "</td><td>" + df + "</td></tr>";
    }).join("");

  Plotly.react("c-annual", [
    {x: Q.annual.map(a => a.year), y: Q.annual.map(a => a.benchmark), name: bl, type: "bar", marker: {color: css("--soft")}},
    {x: Q.annual.map(a => a.year), y: Q.annual.map(a => a.strategy), name: "Währungsquote", type: "bar", marker: {color: css("--pos")}}
  ], layout({barmode: "group", yaxis: {gridcolor: css("--line"), tickformat: ".0%"}, xaxis: {dtick: 2}}), cfg);

  const order = Q.status.slice().sort((a, b) => b.weight - a.weight).map(x => x.code);
  const palette = ["#1b2330", "#2f7d6d", "#b8944a", "#7fa99e", "#5b6472", "#c9b27a", "#4c6a8a", "#b5523b", "#8d9aa8", "#a58f5a", "#8a5a83"];
  Plotly.react("c-weights", order.map((c, k) => ({
    x: Q.weight_dates, y: Q.weights[c], name: c, type: "scatter", mode: "lines", stackgroup: "w",
    line: {width: .5, color: css("--paper")}, fillcolor: palette[k % palette.length],
    hovertemplate: c + " %{y:.1%}<extra></extra>"
  })), layout({yaxis: {gridcolor: css("--line"), tickformat: ".0%", range: [0, 1]}, legend: {orientation: "h", y: -0.12}}), cfg);

  el("t-status").innerHTML = "<tr><th>Währung</th><th>z-Score</th><th>Grundgewicht</th><th>Gewicht</th><th>Über-/Untergewicht</th></tr>" +
    Q.status.map(r => {
      const d = (r.weight - r.base_weight) * 100;
      return "<tr><td>" + r.name + " (" + r.code + ")</td><td>" + num(r.z, 2, true) + "</td><td>" + pct(r.base_weight, 1, false) +
        "</td><td>" + pct(r.weight, 1, false) + "</td><td class='" + cls(d) + "'>" + (Math.abs(d) < 0.05 ? "±0" : num(d, 1, true)) + " pp</td></tr>";
    }).join("");
}

function draw() { perfTable(); quoteSection(); }
draw();
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", draw);

// Tell an embedding page how tall the content is, so the iframe can fit without a scrollbar.
function reportHeight() { parent.postMessage({fxHeight: document.documentElement.scrollHeight}, "*"); }
addEventListener("load", reportHeight);
new ResizeObserver(reportHeight).observe(document.body);
</script>
</body>
</html>
"""

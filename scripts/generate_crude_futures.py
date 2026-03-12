"""
generate_crude_futures.py — WTI Crude Oil December Futures Strip Dashboard
Fetches CLZ25–CLZ29 from Yahoo Finance and builds a static HTML dashboard.

Usage:
    python3 scripts/generate_crude_futures.py
"""

import json
import os
import sys
from datetime import datetime, timedelta

import yfinance as yf

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TICKERS = ["CLZ26.NYM", "CLZ27.NYM", "CLZ28.NYM", "CLZ29.NYM", "CLZ30.NYM"]
LABELS  = ["Dec 2026",   "Dec 2027",   "Dec 2028",   "Dec 2029",   "Dec 2030"]
SHORT   = ["Z26", "Z27", "Z28", "Z29", "Z30"]

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT   = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR  = os.path.join(REPO_ROOT, "reports", "crude-futures")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "index.html")

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Fetch data
# ---------------------------------------------------------------------------
print("Fetching WTI December futures data from Yahoo Finance...")

history_end   = datetime.today()
history_start = history_end - timedelta(days=730)  # ~2 years

stat_cards     = []
history_series = {}   # label → {date: price}
fetch_errors   = []

for ticker, label in zip(TICKERS, LABELS):
    try:
        obj  = yf.Ticker(ticker)
        hist = obj.history(start=history_start.strftime("%Y-%m-%d"),
                           end=history_end.strftime("%Y-%m-%d"),
                           interval="1d", auto_adjust=True)

        if hist.empty:
            print(f"  WARNING: no data for {ticker}")
            fetch_errors.append(ticker)
            stat_cards.append(None)
            history_series[label] = {}
            continue

        closes   = hist["Close"].dropna()
        last_px  = float(closes.iloc[-1])
        prev_px  = float(closes.iloc[-2]) if len(closes) >= 2 else last_px
        chg      = last_px - prev_px
        pct_chg  = (chg / prev_px * 100) if prev_px else 0.0

        hi_52  = float(closes.tail(252).max())
        lo_52  = float(closes.tail(252).min())
        rng    = hi_52 - lo_52
        pct_rng = ((last_px - lo_52) / rng * 100) if rng else 50.0

        stat_cards.append({
            "label":   label,
            "ticker":  ticker,
            "price":   round(last_px, 2),
            "chg":     round(chg, 2),
            "pct_chg": round(pct_chg, 2),
            "hi_52":   round(hi_52, 2),
            "lo_52":   round(lo_52, 2),
            "pct_rng": round(pct_rng, 1),
        })

        # History: keep only trading days with valid closes
        history_series[label] = {
            str(d.date()): round(float(p), 2)
            for d, p in closes.items()
        }
        print(f"  {ticker}: ${last_px:.2f}  ({chg:+.2f}, {pct_chg:+.2f}%)")

    except Exception as exc:
        print(f"  ERROR fetching {ticker}: {exc}")
        fetch_errors.append(ticker)
        stat_cards.append(None)
        history_series[label] = {}

# Replace None cards with placeholder so template never crashes
for i, card in enumerate(stat_cards):
    if card is None:
        stat_cards[i] = {
            "label":   LABELS[i],
            "ticker":  TICKERS[i],
            "price":   0.0,
            "chg":     0.0,
            "pct_chg": 0.0,
            "hi_52":   0.0,
            "lo_52":   0.0,
            "pct_rng": 0.0,
        }

# ---------------------------------------------------------------------------
# Derived series for charts
# ---------------------------------------------------------------------------
prices     = [c["price"] for c in stat_cards]
front_px   = prices[0] if prices else 0.0

# Calendar spreads: Z26−Z25, Z27−Z26, etc.
spread_labels = [f"{SHORT[i+1]}−{SHORT[i]}" for i in range(len(TICKERS) - 1)]
spread_values = [round(prices[i+1] - prices[i], 2) for i in range(len(prices) - 1)]

# Contango/backwardation relative to front month (used for bar colors)
bar_colors = []
for i, px in enumerate(prices):
    if i == 0:
        bar_colors.append("#4a9eda")   # front month — neutral blue
    elif px >= front_px:
        bar_colors.append("#4a9eda")   # contango — blue
    else:
        bar_colors.append("#e94560")   # backwardation — red

# Structure label
is_contango = all(prices[i] <= prices[i+1] for i in range(len(prices)-1)) if len(prices) > 1 else True
structure_label = "Contango" if is_contango else "Backwardation"

# Shared date axis for history chart (union of all dates, sorted)
all_dates = sorted({d for series in history_series.values() for d in series})

# Align each series to shared dates (fill forward if missing)
aligned = {}
for label, series in history_series.items():
    last_known = None
    row = []
    for d in all_dates:
        if d in series:
            last_known = series[d]
        row.append(last_known)
    aligned[label] = row

# Range data for dumbbell chart
range_labels = [c["label"] for c in stat_cards]
range_lo     = [c["lo_52"] for c in stat_cards]
range_hi     = [c["hi_52"] for c in stat_cards]
range_cur    = [c["price"] for c in stat_cards]
range_colors = ["#28a745" if c["pct_rng"] >= 50 else "#e94560" for c in stat_cards]

# ---------------------------------------------------------------------------
# Serialize to JSON (embedded in HTML)
# ---------------------------------------------------------------------------
data_json = json.dumps({
    "stat_cards":     stat_cards,
    "labels":         LABELS,
    "short":          SHORT,
    "prices":         prices,
    "bar_colors":     bar_colors,
    "structure":      structure_label,
    "spread_labels":  spread_labels,
    "spread_values":  spread_values,
    "spread_colors":  ["#28a745" if v >= 0 else "#e94560" for v in spread_values],
    "hist_dates":     all_dates,
    "hist_series":    aligned,
    "range_labels":   range_labels,
    "range_lo":       range_lo,
    "range_hi":       range_hi,
    "range_cur":      range_cur,
    "range_colors":   range_colors,
}, indent=2)

updated_ts = datetime.now().strftime("%B %d, %Y %H:%M UTC")

# ---------------------------------------------------------------------------
# HTML template — Treasury-matched color scheme
# White chart backgrounds, #2a3f5f navy text, #C8D4E3 grids,
# Plotly default colorway: #636efa #EF553B #00cc96 #ab63fa #FFA15A
# ---------------------------------------------------------------------------
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WTI Crude Oil — December Futures Strip</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  :root {{
    --bg:      #f4f7fb;
    --surface: #ffffff;
    --navy:    #2a3f5f;
    --navy-hd: #1a2e45;
    --blue-md: #3d5a8a;
    --text:    #2a3f5f;
    --muted:   #7b8faa;
    --border:  #d1dce9;
    --grid:    #C8D4E3;
    --green:   #2ca02c;
    --red:     #d62728;
    --accent:  #636efa;
  }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 14px;
    line-height: 1.5;
  }}

  /* ── Header ── */
  .dashboard-header {{
    background: linear-gradient(135deg, var(--navy-hd) 0%, var(--blue-md) 100%);
    padding: 28px 32px 24px;
    border-bottom: 1px solid #b8c8db;
    color: #ffffff;
  }}
  .header-top {{ display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: 12px; }}
  .dashboard-header h1 {{ font-size: 1.6rem; font-weight: 700; letter-spacing: -0.02em; color: #ffffff; }}
  .header-badges {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }}
  .badge {{
    display: inline-flex; align-items: center; gap: 4px;
    background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.25);
    border-radius: 20px; padding: 3px 10px; font-size: 11px; color: rgba(255,255,255,0.85);
  }}
  .badge .dot {{ width: 6px; height: 6px; border-radius: 50%; background: #00cc96; }}

  /* ── Stat cards ── */
  .stat-grid {{
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 14px;
    padding: 24px 32px;
  }}
  @media (max-width: 1100px) {{ .stat-grid {{ grid-template-columns: repeat(3, 1fr); }} }}
  @media (max-width: 700px)  {{ .stat-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
  @media (max-width: 420px)  {{ .stat-grid {{ grid-template-columns: 1fr; }} }}

  .stat-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 18px;
    box-shadow: 0 1px 4px rgba(42,63,95,0.08);
  }}
  .stat-card .contract {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 6px; }}
  .stat-card .price {{ font-size: 1.55rem; font-weight: 700; color: var(--navy); }}
  .stat-card .price span {{ font-size: 0.85rem; font-weight: 400; color: var(--muted); }}
  .stat-card .change {{ font-size: 0.88rem; font-weight: 600; margin-top: 3px; }}
  .stat-card .change.up   {{ color: var(--green); }}
  .stat-card .change.down {{ color: var(--red); }}
  .stat-card .change.flat {{ color: var(--muted); }}

  .range-bar-wrap {{ margin-top: 10px; }}
  .range-bar-label {{ display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-bottom: 3px; }}
  .range-bar-track {{
    height: 5px; background: #dde6f0; border-radius: 3px; position: relative;
  }}
  .range-bar-fill {{
    position: absolute; height: 100%; border-radius: 3px; background: var(--accent);
    transition: width 0.3s;
  }}
  .range-bar-dot {{
    position: absolute; top: 50%; transform: translate(-50%, -50%);
    width: 9px; height: 9px; border-radius: 50%; border: 2px solid #ffffff;
  }}

  /* ── Section ── */
  .section {{
    padding: 0 32px 32px;
  }}
  .section-title {{
    font-size: 0.75rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.1em; color: var(--muted); margin-bottom: 14px; padding-top: 4px;
  }}

  /* ── Chart grid ── */
  .chart-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }}
  @media (max-width: 900px) {{ .chart-grid {{ grid-template-columns: 1fr; }} }}

  .chart-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
    box-shadow: 0 1px 4px rgba(42,63,95,0.08);
  }}
  .chart-card h3 {{
    font-size: 0.82rem; font-weight: 600; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 10px;
  }}
  .plotly-chart {{ width: 100%; min-height: 300px; }}

  /* ── Footer ── */
  footer {{
    text-align: center; padding: 20px 32px; color: var(--muted);
    font-size: 11px; border-top: 1px solid var(--border);
  }}
  footer a {{ color: var(--muted); text-decoration: none; }}
  footer a:hover {{ color: var(--navy); }}

  .structure-badge {{
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 11px; font-weight: 700; margin-left: 8px; vertical-align: middle;
  }}
  .structure-badge.contango      {{ background: rgba(99,110,250,0.1); color: #636efa; border: 1px solid #636efa; }}
  .structure-badge.backwardation {{ background: rgba(214,39,40,0.1);  color: #d62728; border: 1px solid #d62728; }}
</style>
</head>
<body>

<header class="dashboard-header">
  <div class="header-top">
    <h1>🛢️ WTI Crude Oil — December Futures Strip</h1>
  </div>
  <div class="header-badges">
    <span class="badge"><span class="dot"></span> Updated: {updated_ts}</span>
    <span class="badge">Data: Yahoo Finance</span>
    <span class="badge">5 contracts tracked (CLZ26–CLZ30)</span>
    <span class="badge">WTI · NYMEX</span>
  </div>
</header>

<div class="stat-grid" id="stat-grid">
  <!-- filled by JS -->
</div>

<section class="section">
  <div class="section-title">Market Structure &amp; Price History</div>
  <div class="chart-grid">

    <div class="chart-card">
      <h3>Futures Term Structure <span class="structure-badge" id="struct-badge"></span></h3>
      <div class="plotly-chart" id="chart-term"></div>
    </div>

    <div class="chart-card">
      <h3>Calendar Spreads ($/bbl)</h3>
      <div class="plotly-chart" id="chart-spreads"></div>
    </div>

    <div class="chart-card" style="grid-column: 1 / -1;">
      <h3>Historical Price Evolution — Last 24 Months</h3>
      <div class="plotly-chart" id="chart-history" style="min-height:360px;"></div>
    </div>

    <div class="chart-card" style="grid-column: 1 / -1;">
      <h3>52-Week Range Positioning</h3>
      <div class="plotly-chart" id="chart-range" style="min-height:260px;"></div>
    </div>

  </div>
</section>

<footer>
  <p>Data sourced from <strong>Yahoo Finance</strong> via yfinance. Prices in USD/bbl. Futures settle in December of each calendar year. &nbsp;|&nbsp;
  <a href="../../index.html">← Back to boquin.xyz</a></p>
</footer>

<script>
const DATA = {data_json};

// ── Stat cards ──────────────────────────────────────────────────────────────
const grid = document.getElementById('stat-grid');
DATA.stat_cards.forEach(c => {{
  const dir      = c.chg > 0 ? 'up' : c.chg < 0 ? 'down' : 'flat';
  const sign     = c.chg > 0 ? '+' : '';
  const pct      = c.pct_rng;
  const dotColor = pct >= 50 ? '#2ca02c' : '#d62728';
  grid.innerHTML += `
    <div class="stat-card">
      <div class="contract">${{c.label}} · ${{c.ticker.split('.')[0]}}</div>
      <div class="price">${{c.price.toFixed(2)}} <span>$/bbl</span></div>
      <div class="change ${{dir}}">${{sign}}${{c.chg.toFixed(2)}} (${{sign}}${{c.pct_chg.toFixed(2)}}%)</div>
      <div class="range-bar-wrap">
        <div class="range-bar-label">
          <span>${{c.lo_52.toFixed(1)}}</span>
          <span style="font-size:9px;">52-week</span>
          <span>${{c.hi_52.toFixed(1)}}</span>
        </div>
        <div class="range-bar-track">
          <div class="range-bar-fill" style="width:${{pct}}%"></div>
          <div class="range-bar-dot" style="left:${{pct}}%;background:${{dotColor}}"></div>
        </div>
      </div>
    </div>`;
}});

// Structure badge
const badge = document.getElementById('struct-badge');
badge.textContent = DATA.structure;
badge.className = 'structure-badge ' + DATA.structure.toLowerCase();

// ── Plotly config — Treasury palette ────────────────────────────────────────
const CHART_BG  = 'white';
const GRID_COL  = '#C8D4E3';
const GRID_LITE = '#EBF0F8';
const TEXT_COL  = '#2a3f5f';
const FONT_FAM  = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
const COLORWAY  = ['#636efa','#EF553B','#00cc96','#ab63fa','#FFA15A'];
const PLOTLY_CFG = {{ responsive: true, displayModeBar: false }};

// Contango=blue (#636efa), backwardation=red (#d62728)
const BAR_COLORS = DATA.bar_colors.map(c =>
  c === '#4a9eda' ? '#636efa' : '#d62728'
);
const SPREAD_COLORS = DATA.spread_colors.map(c =>
  c === '#28a745' ? '#636efa' : '#d62728'
);
const RANGE_COLORS = DATA.range_colors.map(c =>
  c === '#28a745' ? '#2ca02c' : '#d62728'
);

function baseLayout(extra) {{
  return Object.assign({{
    paper_bgcolor: CHART_BG,
    plot_bgcolor:  CHART_BG,
    font: {{ color: TEXT_COL, family: FONT_FAM, size: 11 }},
    margin: {{ l: 55, r: 20, t: 20, b: 50 }},
    xaxis: {{ gridcolor: GRID_LITE, linecolor: GRID_COL, zerolinecolor: GRID_COL }},
    yaxis: {{ gridcolor: GRID_COL,  linecolor: GRID_COL, zerolinecolor: GRID_COL }},
    showlegend: false,
    hovermode: 'closest',
    colorway: COLORWAY,
  }}, extra || {{}});
}}

// ── Chart 1: Term Structure ──────────────────────────────────────────────────
(function() {{
  const mid  = DATA.prices.reduce((a,b) => a+b, 0) / DATA.prices.length;
  const span = Math.max(...DATA.prices) - Math.min(...DATA.prices);
  const pad  = Math.max(span * 2, 2);   // padding so line sits in middle
  Plotly.newPlot('chart-term', [{{
    type: 'scatter',
    mode: 'lines+markers',
    x: DATA.labels,
    y: DATA.prices,
    line: {{ color: '#636efa', width: 2.5 }},
    marker: {{ color: '#636efa', size: 8, line: {{ color: 'white', width: 1.5 }} }},
    hovertemplate: '<b>%{{x}}</b><br>$%{{y:.2f}}/bbl<extra></extra>',
  }}], baseLayout({{
    yaxis: {{ title: '$/bbl', range: [mid - pad/2, mid + pad/2] }},
  }}), PLOTLY_CFG);
}})();

// ── Chart 2: Calendar Spreads ───────────────────────────────────────────────
Plotly.newPlot('chart-spreads', [{{
  type: 'bar',
  x: DATA.spread_labels,
  y: DATA.spread_values,
  marker: {{ color: SPREAD_COLORS, opacity: 0.9 }},
  hovertemplate: '<b>%{{x}}</b><br>%{{y:+.2f}} $/bbl<extra></extra>',
}}], baseLayout({{
  yaxis: {{ title: 'Spread ($/bbl)', zeroline: true, zerolinecolor: '#A2B1C6', zerolinewidth: 1.5 }},
}}), PLOTLY_CFG);

// ── Chart 3: Historical Price Evolution ─────────────────────────────────────
const histTraces = DATA.labels.map((lbl, i) => ({{
  type: 'scatter',
  mode: 'lines',
  name: lbl,
  x: DATA.hist_dates,
  y: DATA.hist_series[lbl],
  line: {{ color: COLORWAY[i % COLORWAY.length], width: 1.8 }},
  hovertemplate: '<b>' + lbl + '</b><br>%{{x}}<br>$%{{y:.2f}}<extra></extra>',
}}));

Plotly.newPlot('chart-history', histTraces, baseLayout({{
  showlegend: true,
  legend: {{ orientation:'h', yanchor:'bottom', y:1.02, xanchor:'right', x:1,
             bgcolor:'rgba(0,0,0,0)', font:{{ size:10 }} }},
  yaxis: {{ title:'$/bbl' }},
  xaxis: {{ type:'date' }},
  hovermode: 'x unified',
}}), PLOTLY_CFG);

// ── Chart 4: 52-Week Range Dumbbell ─────────────────────────────────────────
const dumbbell = [];

// Light gray range bars
DATA.range_labels.forEach((lbl, i) => {{
  dumbbell.push({{
    type: 'scatter',
    mode: 'lines',
    x: [DATA.range_lo[i], DATA.range_hi[i]],
    y: [lbl, lbl],
    line: {{ color: '#DFE8F3', width: 12 }},
    hoverinfo: 'skip',
    showlegend: false,
  }});
}});

// Current price dots
dumbbell.push({{
  type: 'scatter',
  mode: 'markers',
  name: 'Current Price',
  x: DATA.range_cur,
  y: DATA.range_labels,
  marker: {{
    color: RANGE_COLORS,
    size: 14,
    line: {{ color: 'white', width: 2 }},
  }},
  hovertemplate: '<b>%{{y}}</b><br>Current: $%{{x:.2f}}<extra></extra>',
}});

// Low / high tick marks
dumbbell.push({{
  type: 'scatter', mode: 'markers', name: '52-week low',
  x: DATA.range_lo, y: DATA.range_labels,
  marker: {{ color: '#A2B1C6', size: 9, symbol: 'line-ns', line: {{ color: '#A2B1C6', width: 2 }} }},
  hovertemplate: '52-week low: $%{{x:.2f}}<extra></extra>',
}});
dumbbell.push({{
  type: 'scatter', mode: 'markers', name: '52-week high',
  x: DATA.range_hi, y: DATA.range_labels,
  marker: {{ color: '#A2B1C6', size: 9, symbol: 'line-ns', line: {{ color: '#A2B1C6', width: 2 }} }},
  hovertemplate: '52-week high: $%{{x:.2f}}<extra></extra>',
}});

Plotly.newPlot('chart-range', dumbbell, baseLayout({{
  showlegend: false,
  xaxis: {{ title: 'Price ($/bbl)' }},
  yaxis: {{ gridcolor: 'transparent', linecolor: 'transparent', fixedrange: true }},
  margin: {{ l: 80, r: 30, t: 20, b: 50 }},
  hovermode: 'y unified',
}}), PLOTLY_CFG);

</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Write output
# ---------------------------------------------------------------------------
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\nDone! Dashboard written to: {OUTPUT_PATH}")
if fetch_errors:
    print(f"WARNING: failed to fetch: {', '.join(fetch_errors)}")

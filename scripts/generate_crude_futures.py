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
# HTML template
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
    --navy:    #1a1a2e;
    --surface: #16213e;
    --blue:    #0f3460;
    --accent:  #e94560;
    --green:   #28a745;
    --red:     #dc3545;
    --text:    #e0e0e0;
    --muted:   #9a9ab0;
    --border:  #2a2a4a;
    --gold:    #f59e0b;
  }}

  body {{
    background: var(--navy);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 14px;
    line-height: 1.5;
  }}

  /* ── Header ── */
  .dashboard-header {{
    background: linear-gradient(135deg, var(--navy) 0%, var(--blue) 100%);
    padding: 28px 32px 24px;
    border-bottom: 1px solid var(--border);
  }}
  .header-top {{ display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: 12px; }}
  .dashboard-header h1 {{ font-size: 1.6rem; font-weight: 700; letter-spacing: -0.02em; }}
  .header-badges {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }}
  .badge {{
    display: inline-flex; align-items: center; gap: 4px;
    background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.15);
    border-radius: 20px; padding: 3px 10px; font-size: 11px; color: var(--muted);
  }}
  .badge .dot {{ width: 6px; height: 6px; border-radius: 50%; background: var(--green); }}

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
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
  }}
  .stat-card .contract {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 6px; }}
  .stat-card .price {{ font-size: 1.55rem; font-weight: 700; color: var(--text); }}
  .stat-card .price span {{ font-size: 0.85rem; font-weight: 400; color: var(--muted); }}
  .stat-card .change {{ font-size: 0.88rem; font-weight: 600; margin-top: 3px; }}
  .stat-card .change.up   {{ color: var(--green); }}
  .stat-card .change.down {{ color: var(--red); }}
  .stat-card .change.flat {{ color: var(--muted); }}

  .range-bar-wrap {{ margin-top: 10px; }}
  .range-bar-label {{ display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-bottom: 3px; }}
  .range-bar-track {{
    height: 5px; background: var(--border); border-radius: 3px; position: relative;
  }}
  .range-bar-fill {{
    position: absolute; height: 100%; border-radius: 3px; background: #4a9eda;
    transition: width 0.3s;
  }}
  .range-bar-dot {{
    position: absolute; top: 50%; transform: translate(-50%, -50%);
    width: 9px; height: 9px; border-radius: 50%; border: 2px solid var(--navy);
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
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
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
  footer a:hover {{ color: var(--text); }}

  .structure-badge {{
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 11px; font-weight: 700; margin-left: 8px; vertical-align: middle;
  }}
  .structure-badge.contango     {{ background: rgba(74,158,218,0.2); color: #4a9eda; border: 1px solid #4a9eda; }}
  .structure-badge.backwardation {{ background: rgba(233,69,96,0.2); color: var(--accent); border: 1px solid var(--accent); }}
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
  const dir   = c.chg > 0 ? 'up' : c.chg < 0 ? 'down' : 'flat';
  const sign  = c.chg > 0 ? '+' : '';
  const pct   = c.pct_rng;
  const dotColor = pct >= 50 ? '#28a745' : '#e94560';
  grid.innerHTML += `
    <div class="stat-card">
      <div class="contract">${{c.label}} · ${{c.ticker.split('.')[0]}}</div>
      <div class="price">${{c.price.toFixed(2)}} <span>$/bbl</span></div>
      <div class="change ${{dir}}">${{sign}}${{c.chg.toFixed(2)}} (${{sign}}${{c.pct_chg.toFixed(2)}}%)</div>
      <div class="range-bar-wrap">
        <div class="range-bar-label">
          <span>${{c.lo_52.toFixed(1)}}</span>
          <span style="color:#9a9ab0;font-size:9px;">52-week</span>
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

// ── Plotly config ────────────────────────────────────────────────────────────
const DARK_BG   = '#16213e';
const GRID_COL  = '#2a2a4a';
const TEXT_COL  = '#e0e0e0';
const FONT_FAM  = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
const PLOTLY_CFG = {{ responsive: true, displayModeBar: false }};

function darkLayout(extra) {{
  return Object.assign({{
    paper_bgcolor: DARK_BG,
    plot_bgcolor:  DARK_BG,
    font: {{ color: TEXT_COL, family: FONT_FAM, size: 11 }},
    margin: {{ l: 50, r: 20, t: 20, b: 50 }},
    xaxis: {{ gridcolor: GRID_COL, zerolinecolor: GRID_COL }},
    yaxis: {{ gridcolor: GRID_COL, zerolinecolor: GRID_COL }},
    showlegend: false,
    hovermode: 'closest',
  }}, extra || {{}});
}}

// ── Chart 1: Term Structure ──────────────────────────────────────────────────
Plotly.newPlot('chart-term', [
  {{
    type: 'bar',
    x: DATA.labels,
    y: DATA.prices,
    marker: {{ color: DATA.bar_colors, opacity: 0.85 }},
    hovertemplate: '<b>%{{x}}</b><br>$%{{y:.2f}}/bbl<extra></extra>',
  }},
  {{
    type: 'scatter',
    mode: 'lines+markers',
    x: DATA.labels,
    y: DATA.prices,
    line: {{ color: '#ffffff', width: 1.5, dash: 'dot' }},
    marker: {{ color: '#ffffff', size: 6 }},
    hoverinfo: 'skip',
  }}
], darkLayout({{ yaxis: {{ title: '$/bbl', gridcolor: GRID_COL }} }}), PLOTLY_CFG);

// ── Chart 2: Calendar Spreads ───────────────────────────────────────────────
Plotly.newPlot('chart-spreads', [{{
  type: 'bar',
  x: DATA.spread_labels,
  y: DATA.spread_values,
  marker: {{ color: DATA.spread_colors, opacity: 0.9 }},
  hovertemplate: '<b>%{{x}}</b><br>%{{y:+.2f}} $/bbl<extra></extra>',
}}], darkLayout({{
  yaxis: {{ title: 'Spread ($/bbl)', gridcolor: GRID_COL, zeroline: true, zerolinecolor: '#555577', zerolinewidth: 1.5 }},
  shapes: [{{ type:'line', x0:-0.5, x1: DATA.spread_labels.length-0.5, y0:0, y1:0,
              line:{{ color:'#555577', width:1, dash:'dash' }} }}]
}}), PLOTLY_CFG);

// ── Chart 3: Historical Price Evolution ─────────────────────────────────────
const PALETTE = ['#4a9eda','#f59e0b','#e94560','#28a745','#a78bfa'];
const histTraces = DATA.labels.map((lbl, i) => ({{
  type: 'scatter',
  mode: 'lines',
  name: lbl,
  x: DATA.hist_dates,
  y: DATA.hist_series[lbl],
  line: {{ color: PALETTE[i % PALETTE.length], width: 1.8 }},
  hovertemplate: '<b>' + lbl + '</b><br>%{{x}}<br>$%{{y:.2f}}<extra></extra>',
}}));

Plotly.newPlot('chart-history', histTraces, darkLayout({{
  showlegend: true,
  legend: {{ orientation:'h', yanchor:'bottom', y:1.02, xanchor:'right', x:1,
             bgcolor:'rgba(0,0,0,0)', font:{{ size:10 }} }},
  yaxis: {{ title:'$/bbl', gridcolor: GRID_COL }},
  xaxis: {{ type:'date', gridcolor: GRID_COL }},
  hovermode: 'x unified',
}}), PLOTLY_CFG);

// ── Chart 4: 52-Week Range Dumbbell ─────────────────────────────────────────
const dumbbell = [];

// Gray range bars
DATA.range_labels.forEach((lbl, i) => {{
  dumbbell.push({{
    type: 'scatter',
    mode: 'lines',
    x: [DATA.range_lo[i], DATA.range_hi[i]],
    y: [lbl, lbl],
    line: {{ color: '#3a3a5a', width: 10 }},
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
    color: DATA.range_colors,
    size: 14,
    line: {{ color: DARK_BG, width: 2 }},
  }},
  hovertemplate: '<b>%{{y}}</b><br>Current: $%{{x:.2f}}<extra></extra>',
}});

// Low / high end dots
dumbbell.push({{
  type: 'scatter', mode: 'markers', name: '52-week low',
  x: DATA.range_lo, y: DATA.range_labels,
  marker: {{ color: '#3a3a5a', size: 9, symbol: 'line-ns', line: {{ color: '#666688', width: 2 }} }},
  hovertemplate: '52-week low: $%{{x:.2f}}<extra></extra>',
}});
dumbbell.push({{
  type: 'scatter', mode: 'markers', name: '52-week high',
  x: DATA.range_hi, y: DATA.range_labels,
  marker: {{ color: '#3a3a5a', size: 9, symbol: 'line-ns', line: {{ color: '#666688', width: 2 }} }},
  hovertemplate: '52-week high: $%{{x:.2f}}<extra></extra>',
}});

Plotly.newPlot('chart-range', dumbbell, darkLayout({{
  showlegend: false,
  xaxis: {{ title: 'Price ($/bbl)', gridcolor: GRID_COL }},
  yaxis: {{ gridcolor: 'transparent', fixedrange: true }},
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

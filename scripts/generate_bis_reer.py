#!/usr/bin/env python3
"""
BIS REER Interactive Dashboard Generator
Fetches BIS Broad Real Effective Exchange Rate data and generates
a self-contained interactive HTML report.

Run from the repo root:
    python3 scripts/generate_bis_reer.py
"""

import pandas as pd
import numpy as np
import json
import os
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────

BIS_URL = "https://www.bis.org/statistics/eer/broad.xlsx"

COUNTRIES = [
    "Australia", "Brazil", "Canada", "Chile", "China", "Colombia", "Czechia",
    "Euro area", "Hungary", "Iceland", "India", "Indonesia", "Israel", "Japan",
    "Korea", "Malaysia", "Mexico", "New Zealand", "Norway", "Peru",
    "Philippines", "Poland", "Romania", "Russia", "South Africa", "Sweden",
    "Switzerland", "Thailand", "United Kingdom", "United States",
]

OUTPUT_DIR = "reports/bis-reer"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "index.html")

# ── Data Loading ──────────────────────────────────────────────────────────────

def load_data():
    print("Fetching BIS REER broad data...")
    df = pd.read_excel(BIS_URL, header=3)
    df.index = df.iloc[:, 0]
    df = df.iloc[1:, 1:]
    # Keep only target countries (handle possible column name variations)
    available = [c for c in COUNTRIES if c in df.columns]
    missing = [c for c in COUNTRIES if c not in df.columns]
    if missing:
        print(f"  Warning — columns not found: {missing}")
    df = df[available].copy()
    df.index = pd.to_datetime(df.index)
    df = df.sort_index().apply(pd.to_numeric, errors="coerce")
    print(f"  Loaded {len(df)} months × {len(df.columns)} countries")
    print(f"  Date range: {df.index[0].strftime('%b %Y')} → {df.index[-1].strftime('%b %Y')}")
    return df


# ── Compute metrics per window ────────────────────────────────────────────────

def compute_window(df, years):
    months = years * 12
    roll_mean = df.rolling(months, min_periods=months).mean()
    roll_std = df.rolling(months, min_periods=months).std()
    df_z = (df - roll_mean) / roll_std
    df_pct = ((df / roll_mean) - 1) * 100
    return df_z, df_pct


# ── Build embedded data dict ──────────────────────────────────────────────────

def build_window_data(df, years):
    df_z, df_pct = compute_window(df, years)

    # Last snapshot
    latest_pct = {c: round(v, 2) for c, v in df_pct.iloc[-1].items() if pd.notna(v)}
    latest_z   = {c: round(v, 2) for c, v in df_z.iloc[-1].items()   if pd.notna(v)}

    # Grid / explorer: last 240 months
    tail_pct = df_pct.iloc[-240:]
    tail_raw = df.iloc[-240:]
    dates_grid = [d.strftime("%Y-%m-%d") for d in tail_pct.index]

    grid = {}
    for c in df.columns:
        grid[c] = {
            "pct": [round(v, 2) if pd.notna(v) else None for v in tail_pct[c]],
            "raw": [round(v, 2) if pd.notna(v) else None for v in tail_raw[c]],
        }

    # Undervalued count series (ex-US, last 240 months)
    # We store raw pct_series so JS can recompute for any threshold
    tail_pct_uv = df_pct.loc[:, df_pct.columns != "United States"].iloc[-240:]
    uv_dates = [d.strftime("%Y-%m-%d") for d in tail_pct_uv.index]
    pct_series = {
        c: [round(v, 2) if pd.notna(v) else None for v in tail_pct_uv[c]]
        for c in tail_pct_uv.columns
    }

    return {
        "latest_pct": latest_pct,
        "latest_z": latest_z,
        "dates_grid": dates_grid,
        "grid": grid,
        "uv_dates": uv_dates,
        "pct_series": pct_series,
    }


# ── HTML generation ───────────────────────────────────────────────────────────

def generate_html(df):
    last_date = df.index[-1].strftime("%B %Y")
    generated = datetime.now().strftime("%Y-%m-%d")

    windows_data = {}
    for yr in [5, 10, 15]:
        windows_data[str(yr)] = build_window_data(df, yr)

    # Serialise
    windows_json = json.dumps(windows_data, separators=(",", ":"))
    countries_json = json.dumps(list(df.columns))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BIS REER Dashboard — boquin.xyz</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#f5f7fa;color:#1a1a1a;font-size:14px}}

/* Header */
.hdr{{background:#1a3a2f;color:#fff;padding:20px 32px}}
.hdr h1{{font-size:1.4rem;font-weight:700;letter-spacing:-.4px}}
.hdr .sub{{font-size:.82rem;opacity:.72;margin-top:5px}}
.hdr .meta{{font-size:.75rem;opacity:.55;margin-top:3px}}

/* Controls bar */
.ctrl-bar{{background:#fff;border-bottom:1px solid #e4e8ec;padding:10px 32px;display:flex;gap:24px;align-items:center;flex-wrap:wrap}}
.ctrl-lbl{{font-size:.78rem;color:#666;font-weight:600;white-space:nowrap}}
.btn-grp{{display:flex;gap:3px}}
.btn{{padding:4px 11px;border:1px solid #cdd4db;border-radius:5px;background:#fff;cursor:pointer;font-size:.78rem;color:#555;transition:background .12s,color .12s}}
.btn.active{{background:#1a3a2f;color:#fff;border-color:#1a3a2f}}
.btn:hover:not(.active){{background:#f0f5f0}}

/* Tabs */
.tabs{{background:#fff;border-bottom:1px solid #e4e8ec;padding:0 32px;display:flex;overflow-x:auto}}
.tab{{padding:11px 18px;font-size:.85rem;cursor:pointer;border-bottom:3px solid transparent;color:#666;white-space:nowrap;transition:all .12s}}
.tab.active{{color:#1a3a2f;border-bottom-color:#1a3a2f;font-weight:600}}
.tab:hover:not(.active){{background:#f8faf8;color:#333}}

/* Content */
.content{{padding:20px 32px;max-width:1440px;margin:0 auto}}
.panel{{display:none}}.panel.active{{display:block}}
.card{{background:#fff;border:1px solid #e4e8ec;border-radius:10px;padding:16px;margin-bottom:18px;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
.card-title{{font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#999;margin-bottom:12px}}

/* Snapshot table */
.tbl-wrap{{max-height:620px;overflow-y:auto}}
table{{width:100%;border-collapse:collapse;font-size:.82rem}}
thead th{{background:#f0f4f1;padding:8px 12px;text-align:left;font-weight:600;color:#333;border-bottom:2px solid #cdd4db;position:sticky;top:0;z-index:1}}
tbody td{{padding:6px 12px;border-bottom:1px solid #f0f0f0;vertical-align:middle}}
tbody tr:hover td{{background:#fafcfa}}
.cname{{font-weight:500}}
.vpos{{color:#1565c0;font-weight:700}}
.vneg{{color:#c62828;font-weight:700}}
.zval{{color:#666}}
.bar-wrap{{width:110px;height:10px;background:#f0f0f0;border-radius:5px;overflow:hidden;position:relative}}
.bar-inner{{height:100%;border-radius:5px;position:absolute}}
.bar-pos-clr{{background:#1976d2}}
.bar-neg-clr{{background:#d32f2f}}

/* Explorer */
.xctrl{{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px}}
.xsel{{padding:6px 10px;border:1px solid #cdd4db;border-radius:6px;font-size:.82rem;min-width:170px}}
.xbtn{{padding:5px 14px;border:1px solid #1a3a2f;border-radius:6px;background:#1a3a2f;color:#fff;cursor:pointer;font-size:.78rem}}
.xbtn:hover{{background:#2d5a47}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;min-height:26px}}
.chip{{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:20px;font-size:.75rem;cursor:default;border:1px solid transparent}}
.chip .rm{{opacity:.55;cursor:pointer;font-size:.65rem;margin-left:2px}}
.chip .rm:hover{{opacity:1}}

@media(max-width:640px){{
  .hdr{{padding:16px 16px}}.ctrl-bar,.content,.tabs{{padding-left:12px;padding-right:12px}}
}}
</style>
</head>
<body>

<div class="hdr">
  <h1>BIS Real Effective Exchange Rate Dashboard</h1>
  <div class="sub">Broad REER — 30 economies · Over/undervaluation vs rolling historical averages</div>
  <div class="meta">Source: Bank for International Settlements · Last data point: {last_date} · Generated: {generated}</div>
</div>

<div class="ctrl-bar">
  <span class="ctrl-lbl">Rolling window:</span>
  <div class="btn-grp" id="yr-grp">
    <button class="btn" data-yr="5"  onclick="setYears(5)">5yr</button>
    <button class="btn active" data-yr="10" onclick="setYears(10)">10yr</button>
    <button class="btn" data-yr="15" onclick="setYears(15)">15yr</button>
  </div>
  <span class="ctrl-lbl" style="margin-left:12px">Undervaluation threshold:</span>
  <div class="btn-grp" id="thr-grp">
    <button class="btn" data-thr="3"  onclick="setThreshold(3)">3%</button>
    <button class="btn active" data-thr="5"  onclick="setThreshold(5)">5%</button>
    <button class="btn" data-thr="10" onclick="setThreshold(10)">10%</button>
  </div>
</div>

<div class="tabs">
  <div class="tab active"  onclick="showTab('rankings')">Rankings</div>
  <div class="tab"         onclick="showTab('snapshot')">Snapshot Table</div>
  <div class="tab"         onclick="showTab('grid')">Small Multiples</div>
  <div class="tab"         onclick="showTab('explorer')">Country Explorer</div>
  <div class="tab"         onclick="showTab('undervalued')">Undervalued Count</div>
</div>

<div class="content">

  <!-- RANKINGS -->
  <div class="panel active" id="panel-rankings">
    <div class="card">
      <div class="card-title" id="rankings-title">Most Over/Undervalued — top &amp; bottom 10 · 10-year window</div>
      <div id="chart-rankings" style="height:520px"></div>
    </div>
  </div>

  <!-- SNAPSHOT TABLE -->
  <div class="panel" id="panel-snapshot">
    <div class="card">
      <div class="card-title" id="snapshot-title">All economies — latest month, sorted by deviation · 10-year window</div>
      <div class="tbl-wrap">
        <table id="snapshot-table">
          <thead><tr>
            <th>Country</th><th>% vs avg</th><th>Z-score</th><th>Deviation bar</th>
          </tr></thead>
          <tbody id="snapshot-body"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- SMALL MULTIPLES -->
  <div class="panel" id="panel-grid">
    <div class="card">
      <div class="card-title" id="grid-title">REER % vs 10-year rolling average — all 30 economies (last 20 years)</div>
      <div id="chart-grid" style="height:1200px"></div>
    </div>
  </div>

  <!-- EXPLORER -->
  <div class="panel" id="panel-explorer">
    <div class="card">
      <div class="card-title">Country explorer — compare up to 8 economies</div>
      <div class="xctrl">
        <select class="xsel" id="xpicker"></select>
        <button class="xbtn" onclick="xAddCountry()">+ Add</button>
        <div class="btn-grp">
          <button class="btn active" id="xbtn-dev" onclick="xSetMode('dev')">% vs avg</button>
          <button class="btn" id="xbtn-raw" onclick="xSetMode('raw')">Raw index</button>
        </div>
      </div>
      <div class="chips" id="xchips"></div>
      <div id="chart-explorer" style="height:420px"></div>
    </div>
  </div>

  <!-- UNDERVALUED COUNT -->
  <div class="panel" id="panel-undervalued">
    <div class="card">
      <div class="card-title" id="uv-title">Economies with REER more than 5% undervalued vs 10yr avg (ex-US)</div>
      <div id="chart-undervalued" style="height:360px"></div>
    </div>
  </div>

</div><!-- /content -->

<script>
// ── Embedded data ─────────────────────────────────────────────────────────────
const WD = {windows_json};
const COUNTRIES = {countries_json};

// ── State ─────────────────────────────────────────────────────────────────────
let CYR = 10, CTHR = 5, XMODE = 'dev';
let XSEL = ['United States','Euro area','Japan','Brazil'];
const COLORS = ['#1565c0','#c62828','#2e7d32','#e65100','#6a1b9a','#00838f','#558b2f','#4e342e'];
const TABS = ['rankings','snapshot','grid','explorer','undervalued'];
let GRID_DRAWN = false, XDRAWN = false;

// ── Tabs ──────────────────────────────────────────────────────────────────────
function showTab(name) {{
  TABS.forEach((t,i) => {{
    document.getElementById('panel-'+t).classList.toggle('active', t===name);
    document.querySelectorAll('.tab')[i].classList.toggle('active', t===name);
  }});
  if(name==='grid' && !GRID_DRAWN) {{ drawGrid(); GRID_DRAWN=true; }}
  if(name==='explorer' && !XDRAWN) {{ initExplorer(); XDRAWN=true; }}
  if(name==='undervalued') drawUV();
}}

// ── Year / threshold toggles ──────────────────────────────────────────────────
function setYears(yr) {{
  CYR = yr;
  document.querySelectorAll('#yr-grp .btn').forEach(b=>b.classList.toggle('active', +b.dataset.yr===yr));
  refreshAll();
}}
function setThreshold(thr) {{
  CTHR = thr;
  document.querySelectorAll('#thr-grp .btn').forEach(b=>b.classList.toggle('active', +b.dataset.thr===thr));
  drawUV();
  document.getElementById('uv-title').textContent =
    `Economies with REER more than ${{CTHR}}% undervalued vs ${{CYR}}yr avg (ex-US)`;
}}
function refreshAll() {{
  const w = WD[String(CYR)];
  drawRankings(w);
  drawSnapshotTable(w);
  if(GRID_DRAWN) drawGrid();
  if(XDRAWN) drawExplorer();
  drawUV();
  document.getElementById('rankings-title').textContent =
    `Most Over/Undervalued — top & bottom 10 · ${{CYR}}-year window`;
  document.getElementById('snapshot-title').textContent =
    `All economies — latest month, sorted by deviation · ${{CYR}}-year window`;
  document.getElementById('grid-title').textContent =
    `REER % vs ${{CYR}}-year rolling average — all 30 economies (last 20 years)`;
  document.getElementById('uv-title').textContent =
    `Economies with REER more than ${{CTHR}}% undervalued vs ${{CYR}}yr avg (ex-US)`;
}}

// ── Rankings chart ────────────────────────────────────────────────────────────
function drawRankings(w) {{
  const pct = w.latest_pct, z = w.latest_z;
  const entries = Object.entries(pct).sort((a,b)=>a[1]-b[1]);
  const bot10 = entries.slice(0,10), top10 = entries.slice(-10);
  const combined = [...bot10, ...top10];

  const entsZ = Object.entries(z).sort((a,b)=>a[1]-b[1]);
  const bot10z = entsZ.slice(0,10), top10z = entsZ.slice(-10);
  const combinedZ = [...bot10z, ...top10z];

  const cmap = v => v < 0 ? '#d32f2f' : '#1565c0';

  const trPct = {{
    type:'bar', orientation:'h',
    x: combined.map(e=>e[1]),
    y: combined.map(e=>e[0]),
    marker:{{color: combined.map(e=>cmap(e[1]))}},
    hovertemplate:'%{{y}}: %{{x:+.1f}}%<extra></extra>',
    name:'% vs avg'
  }};
  const trZ = {{
    type:'bar', orientation:'h',
    x: combinedZ.map(e=>e[1]),
    y: combinedZ.map(e=>e[0]),
    marker:{{color: combinedZ.map(e=>cmap(e[1]))}},
    hovertemplate:'%{{y}}: %{{x:+.2f}}<extra></extra>',
    name:'Z-score'
  }};

  const layout = {{
    grid:{{rows:1,columns:2,pattern:'independent'}},
    annotations:[
      {{text:`% vs ${{CYR}}-yr avg`, showarrow:false, xref:'paper',yref:'paper', x:0.22,y:1.05, font:{{size:12,color:'#333'}}}},
      {{text:`Z-score vs ${{CYR}}-yr window`, showarrow:false, xref:'paper',yref:'paper', x:0.78,y:1.05, font:{{size:12,color:'#333'}}}},
    ],
    xaxis:{{domain:[0,0.44], gridcolor:'#f0f0f0', zerolinecolor:'#bbb', title:''}},
    yaxis:{{tickfont:{{size:11}}}},
    xaxis2:{{domain:[0.56,1], gridcolor:'#f0f0f0', zerolinecolor:'#bbb', title:'', anchor:'y2'}},
    yaxis2:{{tickfont:{{size:11}}, anchor:'x2'}},
    height:520, showlegend:false,
    plot_bgcolor:'white', paper_bgcolor:'white',
    margin:{{l:120,r:20,t:50,b:30}},
  }};
  trZ.xaxis='x2'; trZ.yaxis='y2';

  Plotly.react('chart-rankings',[trPct,trZ],layout,{{responsive:true}});
}}

// ── Snapshot table ────────────────────────────────────────────────────────────
function drawSnapshotTable(w) {{
  const pct = w.latest_pct, z = w.latest_z;
  const sorted = Object.entries(pct).sort((a,b)=>a[1]-b[1]);
  let html = '';
  sorted.forEach(([country, val]) => {{
    const zv = z[country] ?? null;
    const cls = val < 0 ? 'vneg' : 'vpos';
    const bw = Math.min(Math.abs(val)*1.8, 100).toFixed(1);
    const bcls = val < 0 ? 'bar-neg-clr' : 'bar-pos-clr';
    const bpos = val < 0 ? `right:0` : `left:0`;
    html += `<tr>
      <td class="cname">${{country}}</td>
      <td class="${{cls}}">${{val > 0 ? '+' : ''}}${{val.toFixed(1)}}%</td>
      <td class="zval">${{zv !== null ? (zv>0?'+':'')+zv.toFixed(2) : '—'}}</td>
      <td><div class="bar-wrap"><div class="bar-inner ${{bcls}}" style="width:${{bw}}%;${{bpos}}"></div></div></td>
    </tr>`;
  }});
  document.getElementById('snapshot-body').innerHTML = html;
}}

// ── Small multiples ───────────────────────────────────────────────────────────
function drawGrid() {{
  const w = WD[String(CYR)];
  const ROWS=6, COLS=5;
  const traces=[], annotations=[], domains=[];
  const gap=0.01;
  const cw=(1-(COLS-1)*gap)/COLS, rh=(1-(ROWS-1)*gap)/ROWS;

  let i=0;
  const countries = Object.keys(w.grid);
  countries.forEach(country => {{
    const r=Math.floor(i/COLS), c=i%COLS;
    const x0=c*(cw+gap), x1=x0+cw;
    const y0=1-(r+1)*(rh+gap)+gap, y1=y0+rh;

    const ser = w.grid[country];
    const vals = ser.pct;
    const colors = vals.map(v => v===null?'#ccc': v<0?'#ef5350':'#42a5f5');

    const axN = i===0 ? '' : String(i+1);
    traces.push({{
      type:'bar', x:w.dates_grid, y:vals,
      marker:{{color:colors}}, name:country,
      xaxis:'x'+axN, yaxis:'y'+axN,
      hovertemplate:`<b>${{country}}</b><br>%{{x|%b %Y}}: %{{y:.1f}}%<extra></extra>`,
      showlegend:false
    }});

    annotations.push({{
      text:country, showarrow:false,
      xref:'paper',yref:'paper',
      x:(x0+x1)/2, y:y1+0.003,
      xanchor:'center',yanchor:'bottom',
      font:{{size:9,color:'#444'}}
    }});

    const axObj = {{
      domain:[x0,x1], gridcolor:'#f5f5f5',
      showticklabels:false, zerolinecolor:'#bbb',zerolinewidth:1
    }};
    if(i===0) {{
      domains.push(['xaxis',axObj]);
      domains.push(['yaxis',{{domain:[y0,y1],gridcolor:'#f5f5f5',showticklabels:false,tickfont:{{size:7}}}}]);
    }} else {{
      domains.push(['xaxis'+axN,axObj]);
      domains.push(['yaxis'+axN,{{domain:[y0,y1],gridcolor:'#f5f5f5',showticklabels:false,tickfont:{{size:7}}}}]);
    }}
    i++;
  }});

  const layout = Object.fromEntries(domains);
  layout.height=1200; layout.showlegend=false;
  layout.plot_bgcolor='white'; layout.paper_bgcolor='white';
  layout.margin={{l:10,r:10,t:30,b:10}};
  layout.annotations=annotations;

  Plotly.react('chart-grid', traces, layout, {{responsive:true}});
}}

// ── Undervalued count ─────────────────────────────────────────────────────────
function drawUV() {{
  const w = WD[String(CYR)];
  const counts = w.uv_dates.map((_,i) => {{
    return Object.values(w.pct_series).filter(s => s[i]!==null && s[i] < -CTHR).length;
  }});

  const tr = {{
    type:'scatter', mode:'lines',
    x: w.uv_dates, y: counts,
    fill:'tozeroy',
    line:{{color:'#1565c0',width:2}},
    fillcolor:'rgba(21,101,192,0.12)',
    hovertemplate:'%{{x|%b %Y}}: %{{y}} economies<extra></extra>'
  }};
  const layout = {{
    height:360, plot_bgcolor:'white', paper_bgcolor:'white',
    xaxis:{{gridcolor:'#f0f0f0',title:''}},
    yaxis:{{gridcolor:'#f0f0f0',title:'# economies',rangemode:'tozero'}},
    margin:{{l:55,r:20,t:20,b:40}},
  }};
  Plotly.react('chart-undervalued',[tr],layout,{{responsive:true}});
}}

// ── Country explorer ──────────────────────────────────────────────────────────
function initExplorer() {{
  const sel = document.getElementById('xpicker');
  COUNTRIES.forEach(c => {{
    const o=document.createElement('option');
    o.value=c; o.textContent=c; sel.appendChild(o);
  }});
  drawExplorer();
}}
function xAddCountry() {{
  const c=document.getElementById('xpicker').value;
  if(c && !XSEL.includes(c) && XSEL.length<8) {{ XSEL.push(c); drawExplorer(); }}
}}
function xRemoveCountry(c) {{ XSEL=XSEL.filter(x=>x!==c); drawExplorer(); }}
function xSetMode(m) {{
  XMODE=m;
  document.getElementById('xbtn-dev').classList.toggle('active',m==='dev');
  document.getElementById('xbtn-raw').classList.toggle('active',m==='raw');
  drawExplorer();
}}
function drawExplorer() {{
  const w = WD[String(CYR)];
  const chips=document.getElementById('xchips');
  chips.innerHTML='';
  const traces=[];
  XSEL.forEach((country,i) => {{
    const col=COLORS[i%COLORS.length];
    const g=w.grid[country]; if(!g) return;
    const y=XMODE==='dev' ? g.pct : g.raw;
    traces.push({{
      type:'scatter', mode:'lines',
      x:w.dates_grid, y,
      name:country, line:{{color:col,width:2}},
      hovertemplate:`<b>${{country}}</b> %{{x|%b %Y}}: %{{y:.1f}}<extra></extra>`
    }});
    const chip=document.createElement('div');
    chip.className='chip';
    chip.style.cssText=`background:${{col}}18;border-color:${{col}};color:${{col}}`;
    chip.innerHTML=`${{country}}<span class="rm" onclick="xRemoveCountry('${{country}}')">&nbsp;✕</span>`;
    chips.appendChild(chip);
  }});

  const shapes=[];
  if(XMODE==='dev' && traces.length) {{
    shapes.push({{type:'line',xref:'x',yref:'y',
      x0:w.dates_grid[0],x1:w.dates_grid[w.dates_grid.length-1],y0:0,y1:0,
      line:{{color:'#888',width:1,dash:'dash'}}}});
  }}
  const layout={{
    height:420, showlegend:false,
    plot_bgcolor:'white', paper_bgcolor:'white',
    xaxis:{{gridcolor:'#f0f0f0', title:''}},
    yaxis:{{
      gridcolor:'#f0f0f0', zerolinecolor:'#ccc',
      title: XMODE==='dev' ? `% vs ${{CYR}}-yr avg` : 'REER index'
    }},
    margin:{{l:60,r:20,t:16,b:40}},
    hovermode:'x unified',
    shapes
  }};
  Plotly.react('chart-explorer',traces,layout,{{responsive:true}});
}}

// ── Init ──────────────────────────────────────────────────────────────────────
(function() {{
  const w = WD['10'];
  drawRankings(w);
  drawSnapshotTable(w);
  // Lazy: grid and explorer drawn on first tab visit
}})();
</script>
</body>
</html>"""
    return html


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    df = load_data()

    print("Computing rolling windows (5yr, 10yr, 15yr)...")
    html = generate_html(df)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = os.path.getsize(OUTPUT_FILE) / 1024
    print(f"Report saved → {OUTPUT_FILE}  ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()

"""
US Oil Supply/Demand Monitor
Sources:
  - FRED API (EIA petroleum weekly series + WTI/Brent prices)
    FRED carries EIA petroleum supply weekly data with the same series IDs.
  - yfinance (futures prices for 3-2-1 crack spread)

Required env vars:
  FRED_API_KEY

Run from repo root:
    FRED_API_KEY=xxx python3 scripts/generate_us_oil_monitor.py
"""

import os
import json
import warnings
import requests
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

# ── Config ────────────────────────────────────────────────────────────────────
FRED_API_KEY = os.environ.get("FRED_API_KEY")
if not FRED_API_KEY:
    raise EnvironmentError("FRED_API_KEY environment variable is not set.")

# EIA petroleum weekly series — FRED carries these with the same series IDs
# Source: EIA Petroleum Supply Weekly (PSW), published via FRED
EIA_SERIES = {
    "crude_stocks":        "WCESTUS1",
    "cushing_stocks":      "WCSSTUS1",
    "spr_stocks":          "WCSSTX2",
    "production":          "WCRFPUS2",
    "imports":             "WCRIMUS2",
    "exports":             "WCREXUS2",
    "refinery_util":       "WREFUPUS2",
    "gasoline_supplied":   "WGFUPUS2",
    "distillate_supplied": "WDISTPUS2",
    "jet_supplied":        "WKJUPUS2",
}

FRED_SERIES = {
    "wti":   "DCOILWTICO",
    "brent": "DCOILBRENTEU",
}
# Baker Hughes rig count — try these FRED series IDs in order
RIG_COUNT_SERIES_IDS = ["DRIGFES05USD", "RIGFETOTALUS", "RIGFES", "DRIGFES05USS"]

OUTPUT_DIR = Path(__file__).parent.parent / "reports" / "us-oil-monitor"
OUTPUT_FILE = OUTPUT_DIR / "index.html"

SCALE_STOCKS = 1 / 1000   # thousand barrels → million barrels (MMB)
SCALE_PROD   = 1 / 1000   # thousand bbl/d → million bbl/d (MMBbl/d)
CURRENT_YEAR = date.today().year


# ── Fetch EIA v2 ──────────────────────────────────────────────────────────────
# ── Fetch EIA via DNAV Excel (no API key required) ────────────────────────────
# EIA publishes weekly petroleum series as public Excel files at:
#   https://www.eia.gov/dnav/pet/hist_xls/{SERIES_ID}w.xls
# No authentication required.
def fetch_eia_dnav(series_id: str) -> pd.Series:
    import io
    url = f"https://www.eia.gov/dnav/pet/hist_xls/{series_id}w.xls"
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.raise_for_status()
    # Sheet 1 = "Data 1"; row 0 = series ID, row 1 = column headers; data from row 2
    df = pd.read_excel(
        io.BytesIO(resp.content),
        sheet_name=1,
        skiprows=2,
        header=None,
        names=["date", "value"],
        engine="xlrd",
    )
    df = df.dropna(subset=["date", "value"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).set_index("date")
    s = df["value"].astype(float).sort_index()
    s.name = series_id
    return s


# ── Fetch from FRED ───────────────────────────────────────────────────────────
def fetch_fred_series(series_id: str, start: str = "2018-01-01") -> pd.Series:
    from fredapi import Fred
    _fred = Fred(api_key=FRED_API_KEY)
    s = _fred.get_series(series_id, observation_start=start)
    s = s.dropna().sort_index()
    s.name = series_id
    return s


# ── Fetch yfinance prices ─────────────────────────────────────────────────────
def fetch_price_data(start: str) -> dict:
    import yfinance as yf
    result = {}
    for ticker in ["CL=F", "RB=F", "HO=F"]:
        try:
            df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
            if not df.empty:
                close = df["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                result[ticker] = close.dropna()
                print(f"  ✓ {ticker}: {len(result[ticker])} rows, latest {result[ticker].index[-1].date()}")
        except Exception as e:
            print(f"  ✗ {ticker}: {e}")
    return result


# ── 5-year seasonal band ──────────────────────────────────────────────────────
def compute_5yr_band(series: pd.Series) -> pd.DataFrame:
    """
    Group by ISO week number over the 5 complete years before CURRENT_YEAR.
    Returns DataFrame: week | ref_date | min | max | mean
    where ref_date is the Friday of that ISO week in CURRENT_YEAR.
    """
    hist_years = list(range(CURRENT_YEAR - 5, CURRENT_YEAR))
    hist = series[series.index.year.isin(hist_years)].copy()

    df = pd.DataFrame({"value": hist})
    df["week"] = df.index.isocalendar().week.astype(int)

    band = (
        df.groupby("week")["value"]
        .agg(["min", "max", "mean"])
        .reset_index()
    )
    band.columns = ["week", "min", "max", "mean"]

    ref_dates = []
    for w in band["week"]:
        try:
            ref_dates.append(pd.Timestamp(date.fromisocalendar(CURRENT_YEAR, int(w), 5)))
        except Exception:
            ref_dates.append(pd.NaT)
    band["ref_date"] = ref_dates
    return band.dropna(subset=["ref_date"]).reset_index(drop=True)


# ── 3-2-1 crack spread ────────────────────────────────────────────────────────
def compute_crack_spread(wti: pd.Series, rbob: pd.Series, ho: pd.Series) -> pd.Series:
    """(2 × RBOB×42 + HO×42 − 3 × WTI) / 3. RBOB/HO in $/gal → ×42 = $/bbl."""
    df = pd.concat([wti, rbob * 42, ho * 42], axis=1, join="inner").dropna()
    df.columns = ["wti", "rbob_bbl", "ho_bbl"]
    crack = (2 * df["rbob_bbl"] + df["ho_bbl"] - 3 * df["wti"]) / 3
    crack.name = "crack_321"
    return crack


# ── Serialization helpers ─────────────────────────────────────────────────────
def to_payload(series: pd.Series, decimals: int = 2) -> dict:
    s = series.dropna()
    if not isinstance(s.index, pd.DatetimeIndex) or len(s) == 0:
        return {"dates": [], "values": []}
    return {
        "dates":  s.index.strftime("%Y-%m-%d").tolist(),
        "values": [round(float(v), decimals) for v in s],
    }


def band_to_payload(band: pd.DataFrame) -> dict:
    if band.empty or "ref_date" not in band.columns:
        return {"dates": [], "min": [], "max": [], "mean": []}
    b = band.dropna(subset=["ref_date"])
    return {
        "dates": b["ref_date"].dt.strftime("%Y-%m-%d").tolist(),
        "min":   [round(float(v), 2) for v in b["min"]],
        "max":   [round(float(v), 2) for v in b["max"]],
        "mean":  [round(float(v), 2) for v in b["mean"]],
    }


# ── Overview scorecard ────────────────────────────────────────────────────────
def compute_overview(eia: dict, fred: dict, crack: pd.Series) -> dict:
    def last2(s, scale=1.0):
        s = s.dropna() * scale
        if len(s) < 2:
            return None, None
        return round(float(s.iloc[-1]), 2), round(float(s.iloc[-1] - s.iloc[-2]), 2)

    def pct_vs_5yr(s, scale=1.0):
        s = s.dropna() * scale
        if len(s) == 0:
            return None
        latest_week = s.index[-1].isocalendar()[1]
        hist = s[s.index.year.isin(range(CURRENT_YEAR - 5, CURRENT_YEAR))]
        same_wk = hist[[d.isocalendar()[1] == latest_week for d in hist.index]]
        if len(same_wk) == 0:
            return None
        avg = float(same_wk.mean())
        if avg == 0:
            return None
        return round((float(s.iloc[-1]) - avg) / avg * 100, 1)

    crude_v, crude_c = last2(eia.get("crude_stocks", pd.Series()), SCALE_STOCKS)
    crude_pct = pct_vs_5yr(eia.get("crude_stocks", pd.Series()), SCALE_STOCKS)

    cush_v, cush_c = last2(eia.get("cushing_stocks", pd.Series()), SCALE_STOCKS)
    spr_v, spr_c   = last2(eia.get("spr_stocks", pd.Series()), SCALE_STOCKS)
    prod_v, prod_c = last2(eia.get("production", pd.Series()), SCALE_PROD)
    ref_v, ref_c   = last2(eia.get("refinery_util", pd.Series()))

    gas = eia.get("gasoline_supplied", pd.Series()).dropna() * SCALE_PROD
    gas_ma = gas.rolling(4).mean().dropna()
    gas_v  = round(float(gas_ma.iloc[-1]), 2)  if len(gas_ma) > 4 else None
    gas_c  = round(float(gas_ma.iloc[-1] - gas_ma.iloc[-2]), 2) if len(gas_ma) > 4 else None

    wti_s = fred.get("wti", pd.Series()).dropna()
    wti_v  = round(float(wti_s.iloc[-1]), 2)  if len(wti_s) > 0 else None
    wti_c  = round(float(wti_s.iloc[-1] - wti_s.iloc[-5]), 2) if len(wti_s) > 5 else None

    crack_v = round(float(crack.iloc[-1]), 2)  if len(crack) > 0 else None
    crack_c = round(float(crack.iloc[-1] - crack.iloc[-5]), 2) if len(crack) > 5 else None

    rig_s = fred.get("rig_count", pd.Series()).dropna()
    rig_v  = int(rig_s.iloc[-1])  if len(rig_s) > 0 else None
    rig_c  = int(rig_s.iloc[-1] - rig_s.iloc[-2]) if len(rig_s) > 1 else None

    return {
        "crude_stocks":    {"val": crude_v, "chg": crude_c, "pct_5yr": crude_pct, "unit": "MMB",      "label": "Crude Stocks", "bullish_if_negative": True},
        "cushing_stocks":  {"val": cush_v,  "chg": cush_c,  "pct_5yr": None,      "unit": "MMB",      "label": "Cushing Stocks", "bullish_if_negative": True},
        "spr_stocks":      {"val": spr_v,   "chg": spr_c,   "pct_5yr": None,      "unit": "MMB",      "label": "SPR Stocks",     "bullish_if_negative": None},
        "production":      {"val": prod_v,  "chg": prod_c,  "pct_5yr": None,      "unit": "MMBbl/d",  "label": "Crude Production","bullish_if_negative": True},
        "refinery_util":   {"val": ref_v,   "chg": ref_c,   "pct_5yr": None,      "unit": "%",        "label": "Refinery Util",  "bullish_if_negative": False},
        "gasoline_demand": {"val": gas_v,   "chg": gas_c,   "pct_5yr": None,      "unit": "MMBbl/d",  "label": "Gas Demand 4W MA","bullish_if_negative": False},
        "wti":             {"val": wti_v,   "chg": wti_c,   "pct_5yr": None,      "unit": "$/bbl",    "label": "WTI Spot",       "bullish_if_negative": None},
        "crack_321":       {"val": crack_v, "chg": crack_c, "pct_5yr": None,      "unit": "$/bbl",    "label": "3-2-1 Crack",    "bullish_if_negative": False},
        "rig_count":       {"val": rig_v,   "chg": rig_c,   "pct_5yr": None,      "unit": "rigs",     "label": "Baker Hughes Rigs","bullish_if_negative": True},
    }


# ── HTML builder ──────────────────────────────────────────────────────────────
def build_html(data_json: str, last_updated: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>US Oil Market Monitor</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
  :root {{
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #22253a;
    --border: #2d3148;
    --accent: #f59e0b;
    --accent2: #fbbf24;
    --green: #22c55e;
    --red: #ef4444;
    --blue: #60a5fa;
    --muted-green: rgba(34,197,94,0.15);
    --muted-red: rgba(239,68,68,0.15);
    --text: #e2e8f0;
    --muted: #94a3b8;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; }}
  header {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 16px 32px; display: flex; align-items: center; justify-content: space-between; }}
  header h1 {{ font-size: 1.25rem; font-weight: 700; color: var(--accent2); }}
  header .meta {{ color: var(--muted); font-size: 0.8rem; text-align: right; }}
  .tabs {{ display: flex; gap: 4px; padding: 16px 32px 0; border-bottom: 1px solid var(--border); background: var(--surface); overflow-x: auto; }}
  .tab {{ padding: 8px 20px; border-radius: 6px 6px 0 0; cursor: pointer; color: var(--muted); border: 1px solid transparent; border-bottom: none; transition: all .2s; font-weight: 500; white-space: nowrap; }}
  .tab:hover {{ color: var(--text); background: var(--surface2); }}
  .tab.active {{ color: var(--accent2); border-color: var(--border); background: var(--bg); }}
  .view {{ display: none; padding: 24px 32px; }}
  .view.active {{ display: block; }}
  .section-title {{ font-size: 0.72rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; margin-bottom: 12px; margin-top: 20px; }}
  .section-title:first-child {{ margin-top: 0; }}
  .scoreboard {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(175px, 1fr)); gap: 10px; margin-bottom: 24px; }}
  .score-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; }}
  .score-card.bull {{ border-left: 3px solid var(--green); }}
  .score-card.bear {{ border-left: 3px solid var(--red); }}
  .score-card.neutral {{ border-left: 3px solid var(--muted); }}
  .sc-label {{ font-size: 0.72rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; margin-bottom: 4px; }}
  .sc-val {{ font-size: 1.35rem; font-weight: 700; color: var(--text); }}
  .sc-chg {{ font-size: 0.78rem; margin-top: 3px; }}
  .sc-pct {{ font-size: 0.78rem; color: var(--muted); margin-top: 2px; }}
  .chart-wrap {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 16px; }}
  .chart-grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }}
  .chart-grid-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-bottom: 16px; }}
  @media (max-width: 900px) {{
    .chart-grid-2, .chart-grid-3 {{ grid-template-columns: 1fr; }}
    header, .tabs, .view {{ padding-left: 16px; padding-right: 16px; }}
  }}
</style>
</head>
<body>

<header>
  <div>
    <h1>🛢️ US Oil Market Monitor</h1>
    <div style="color:var(--muted);font-size:.75rem;margin-top:2px;">
      EIA weekly supply/demand · FRED prices · Baker Hughes rig count
    </div>
  </div>
  <div class="meta">Updated: {last_updated}<br><span style="font-size:.7rem">EIA releases Wednesdays 10:30 AM ET</span></div>
</header>

<div class="tabs">
  <div class="tab active"  onclick="switchTab('overview')">Overview</div>
  <div class="tab"         onclick="switchTab('inventory')">Inventories</div>
  <div class="tab"         onclick="switchTab('production')">Production &amp; Trade</div>
  <div class="tab"         onclick="switchTab('demand')">Demand</div>
  <div class="tab"         onclick="switchTab('prices')">Price Structure</div>
</div>

<!-- ── OVERVIEW ── -->
<div id="view-overview" class="view active">
  <p class="section-title">Scorecard — current week values &amp; week-over-week change</p>
  <div class="scoreboard" id="scoreboard"></div>
  <p class="section-title" style="margin-top:8px;color:var(--muted);font-size:.68rem;">
    Green border = bullish signal (draws / strong demand / tight supply) · Red = bearish · Grey = neutral
  </p>
</div>

<!-- ── INVENTORY ── -->
<div id="view-inventory" class="view">
  <p class="section-title">Crude Oil Stocks vs 5-Year Seasonal Range (MMB)</p>
  <div class="chart-wrap" id="inv-crude" style="height:340px;"></div>
  <div class="chart-grid-2">
    <div>
      <p class="section-title">Cushing, OK Crude Stocks (MMB)</p>
      <div class="chart-wrap" id="inv-cushing" style="height:300px;"></div>
    </div>
    <div>
      <p class="section-title">Strategic Petroleum Reserve (MMB)</p>
      <div class="chart-wrap" id="inv-spr" style="height:300px;"></div>
    </div>
  </div>
</div>

<!-- ── PRODUCTION & TRADE ── -->
<div id="view-production" class="view">
  <div class="chart-grid-2">
    <div>
      <p class="section-title">US Crude Production (MMBbl/d) — 4-Week MA</p>
      <div class="chart-wrap" id="prod-main" style="height:320px;"></div>
    </div>
    <div>
      <p class="section-title">Net Crude Imports (MMBbl/d) &amp; Baker Hughes Rig Count</p>
      <div class="chart-wrap" id="prod-trade" style="height:320px;"></div>
    </div>
  </div>
</div>

<!-- ── DEMAND ── -->
<div id="view-demand" class="view">
  <p class="section-title">Refinery Utilization (%) vs 5-Year Seasonal Range</p>
  <div class="chart-wrap" id="dem-refutil" style="height:320px;"></div>
  <div class="chart-grid-2">
    <div>
      <p class="section-title">Gasoline Product Supplied — Current vs Prior Year 4W MA (MMBbl/d)</p>
      <div class="chart-wrap" id="dem-gas" style="height:300px;"></div>
    </div>
    <div>
      <p class="section-title">Distillate &amp; Jet Fuel Supplied (MMBbl/d)</p>
      <div class="chart-wrap" id="dem-dist" style="height:300px;"></div>
    </div>
  </div>
</div>

<!-- ── PRICES ── -->
<div id="view-prices" class="view">
  <p class="section-title">WTI vs Brent Spot Prices ($/bbl) — Last 12 Months</p>
  <div class="chart-wrap" id="price-wti-brent" style="height:340px;"></div>
  <div class="chart-grid-2">
    <div>
      <p class="section-title">3-2-1 Crack Spread ($/bbl) — Last 12 Months</p>
      <div class="chart-wrap" id="price-crack" style="height:300px;"></div>
    </div>
    <div>
      <p class="section-title">WTI Price vs Baker Hughes Rig Count (2020–present)</p>
      <div class="chart-wrap" id="price-rig" style="height:300px;"></div>
    </div>
  </div>
</div>

<script>
const DATA = {data_json};

const LAYOUT_BASE = {{
  paper_bgcolor: 'transparent',
  plot_bgcolor: 'transparent',
  font: {{ color: '#e2e8f0', size: 11 }},
  margin: {{ l: 52, r: 36, t: 28, b: 44 }},
  xaxis: {{ gridcolor: '#2d3148', zerolinecolor: '#2d3148' }},
  yaxis: {{ gridcolor: '#2d3148', zerolinecolor: '#2d3148' }},
  legend: {{ bgcolor: 'transparent', font: {{ size: 10 }} }},
}};
const CFG = {{ responsive: true, displayModeBar: false }};

// ── Tab switcher ──────────────────────────────────────────────────────────────
const TAB_NAMES = ['overview','inventory','production','demand','prices'];
let rendered = {{}};

function switchTab(name) {{
  document.querySelectorAll('.tab').forEach((t, i) => t.classList.toggle('active', TAB_NAMES[i] === name));
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById('view-' + name).classList.add('active');
  if (!rendered[name]) {{ rendered[name] = true; RENDER[name](); }}
}}

// ── Overview ──────────────────────────────────────────────────────────────────
function renderOverview() {{
  const ov = DATA.overview;
  const keys = ['crude_stocks','cushing_stocks','spr_stocks','production','refinery_util',
                 'gasoline_demand','wti','crack_321','rig_count'];
  const el = document.getElementById('scoreboard');
  el.innerHTML = '';

  keys.forEach(k => {{
    const d = ov[k];
    if (!d) return;

    // Determine border color
    let cls = 'neutral';
    if (d.bullish_if_negative === true) {{
      cls = (d.chg !== null && d.chg < 0) ? 'bull' : 'bear';
    }} else if (d.bullish_if_negative === false) {{
      cls = (d.chg !== null && d.chg > 0) ? 'bull' : 'bear';
    }}
    // For crude stocks also check pct_5yr
    if (k === 'crude_stocks' && d.pct_5yr !== null) {{
      cls = d.pct_5yr < 0 ? 'bull' : 'bear';
    }}

    const chgColor = (d.chg === null) ? '' : (
      (d.bullish_if_negative === true  && d.chg < 0) ? 'color:#22c55e' :
      (d.bullish_if_negative === false && d.chg > 0) ? 'color:#22c55e' :
      (d.chg === 0) ? '' : 'color:#ef4444'
    );
    const chgSign = (d.chg !== null && d.chg > 0) ? '+' : '';
    const pctLine = (d.pct_5yr !== null)
      ? `<div class="sc-pct" style="color:${{d.pct_5yr < 0 ? '#22c55e' : '#ef4444'}}">${{d.pct_5yr > 0 ? '+' : ''}}${{d.pct_5yr}}% vs 5Y avg</div>`
      : '';

    const card = document.createElement('div');
    card.className = 'score-card ' + cls;
    card.innerHTML = `
      <div class="sc-label">${{d.label}}</div>
      <div class="sc-val">${{d.val !== null ? d.val.toLocaleString() : '—'}} <span style="font-size:.75rem;color:var(--muted)">${{d.unit}}</span></div>
      <div class="sc-chg" style="${{chgColor}}">${{d.chg !== null ? chgSign + d.chg.toLocaleString() + ' WoW' : ''}}</div>
      ${{pctLine}}
    `;
    el.appendChild(card);
  }});
}}

// ── Band helpers ──────────────────────────────────────────────────────────────
function bandTraces(b, label) {{
  return [
    // max boundary (invisible, for fill reference)
    {{ x: b.dates, y: b.max, mode: 'lines', line: {{width:0}}, showlegend: false, hoverinfo: 'skip' }},
    // min boundary with fill
    {{ x: b.dates, y: b.min, mode: 'lines', fill: 'tonexty',
       fillcolor: 'rgba(180,180,180,0.2)', line: {{width:0}},
       name: '5Y Min/Max', hovertemplate: '%{{x|%b %d}}<br>Range: %{{y:.1f}}–%{{customdata:.1f}}<extra>5Y range</extra>',
       customdata: b.max }},
    // mean dashed
    {{ x: b.dates, y: b.mean, mode: 'lines',
       line: {{color:'rgba(150,150,150,0.7)', width:1.5, dash:'dash'}},
       name: '5Y Mean', hovertemplate: '%{{x|%b %d}}<br>5Y Mean: %{{y:.1f}}<extra></extra>' }},
  ];
}}

function currYearTrace(s, label, color) {{
  // Filter to current year only
  const cy = {CURRENT_YEAR};
  const dates = [], vals = [];
  s.dates.forEach((d,i) => {{
    if (new Date(d).getFullYear() === cy) {{ dates.push(d); vals.push(s.values[i]); }}
  }});
  return {{ x: dates, y: vals, mode: 'lines', line: {{color, width:2.5}},
            name: cy + ' YTD', hovertemplate: '%{{x|%b %d}}<br><b>%{{y:.1f}}</b><extra>' + label + '</extra>' }};
}}

// ── Inventory ─────────────────────────────────────────────────────────────────
function renderInventory() {{
  const inv = DATA.inventory;

  // Crude
  const crudeTraces = [...bandTraces(inv.crude_band, '5Y Crude'), currYearTrace(inv.crude, 'Crude', '#60a5fa')];
  Plotly.newPlot('inv-crude', crudeTraces, {{
    ...LAYOUT_BASE,
    xaxis: {{ ...LAYOUT_BASE.xaxis, tickformat: '%b', dtick: 'M1' }},
    yaxis: {{ ...LAYOUT_BASE.yaxis, title: 'MMB' }},
    legend: {{ ...LAYOUT_BASE.legend, orientation: 'h', y: 1.08 }},
    hovermode: 'x unified',
  }}, CFG);

  // Cushing
  const cushTraces = [...bandTraces(inv.cushing_band, '5Y Cushing'), currYearTrace(inv.cushing, 'Cushing', '#a78bfa')];
  Plotly.newPlot('inv-cushing', cushTraces, {{
    ...LAYOUT_BASE,
    xaxis: {{ ...LAYOUT_BASE.xaxis, tickformat: '%b', dtick: 'M1' }},
    yaxis: {{ ...LAYOUT_BASE.yaxis, title: 'MMB' }},
    legend: {{ ...LAYOUT_BASE.legend, orientation: 'h', y: 1.1 }},
    hovermode: 'x unified',
  }}, CFG);

  // SPR — long trend
  Plotly.newPlot('inv-spr', [{{
    x: inv.spr.dates, y: inv.spr.values, mode: 'lines',
    line: {{color: '#f59e0b', width: 2}},
    name: 'SPR', fill: 'tozeroy', fillcolor: 'rgba(245,158,11,0.08)',
    hovertemplate: '%{{x|%b %d, %Y}}<br><b>%{{y:.1f}} MMB</b><extra>SPR</extra>',
  }}], {{
    ...LAYOUT_BASE,
    yaxis: {{ ...LAYOUT_BASE.yaxis, title: 'MMB' }},
    hovermode: 'x unified',
  }}, CFG);
}}

// ── Production & Trade ────────────────────────────────────────────────────────
function renderProduction() {{
  const p = DATA.production;

  // Production + 4W MA — last 2 years
  Plotly.newPlot('prod-main', [
    {{ x: p.production.dates, y: p.production.values, mode: 'lines',
       line: {{color:'rgba(96,165,250,0.4)', width:1}}, name: 'Weekly', hoverinfo: 'skip' }},
    {{ x: p.production_ma.dates, y: p.production_ma.values, mode: 'lines',
       line: {{color:'#60a5fa', width:2.5}}, name: '4W MA',
       hovertemplate: '%{{x|%b %d, %Y}}<br><b>%{{y:.2f}} MMBbl/d</b><extra>4W MA</extra>' }},
  ], {{
    ...LAYOUT_BASE,
    yaxis: {{ ...LAYOUT_BASE.yaxis, title: 'MMBbl/d' }},
    legend: {{ ...LAYOUT_BASE.legend, orientation: 'h', y: 1.1 }},
    hovermode: 'x unified',
  }}, CFG);

  // Net imports + rig count (dual y)
  Plotly.newPlot('prod-trade', [
    {{ x: p.net_imports.dates, y: p.net_imports.values, mode: 'lines',
       line: {{color:'#34d399', width:2}}, name: 'Net Imports', yaxis: 'y',
       hovertemplate: '%{{x|%b %d, %Y}}<br>Net Imports: %{{y:.2f}} MMBbl/d<extra></extra>' }},
    {{ x: p.rig_count.dates, y: p.rig_count.values, mode: 'lines',
       line: {{color:'#f97316', width:1.5, dash:'dot'}}, name: 'Rig Count (→)', yaxis: 'y2',
       hovertemplate: '%{{x|%b %d, %Y}}<br>Rig Count: %{{y}}<extra></extra>' }},
  ], {{
    ...LAYOUT_BASE,
    yaxis:  {{ ...LAYOUT_BASE.yaxis, title: 'MMBbl/d' }},
    yaxis2: {{ title: 'Rig Count', overlaying: 'y', side: 'right',
               gridcolor: 'transparent', zerolinecolor: '#2d3148' }},
    legend: {{ ...LAYOUT_BASE.legend, orientation: 'h', y: 1.1 }},
    hovermode: 'x unified',
  }}, CFG);
}}

// ── Demand ────────────────────────────────────────────────────────────────────
function renderDemand() {{
  const d = DATA.demand;

  // Refinery util vs 5Y band
  const refTraces = [
    ...bandTraces(d.refinery_band, '5Y Refinery'),
    currYearTrace(d.refinery_util, 'Refinery Util', '#fb923c'),
  ];
  Plotly.newPlot('dem-refutil', refTraces, {{
    ...LAYOUT_BASE,
    xaxis: {{ ...LAYOUT_BASE.xaxis, tickformat: '%b', dtick: 'M1' }},
    yaxis: {{ ...LAYOUT_BASE.yaxis, title: '%', ticksuffix: '%' }},
    legend: {{ ...LAYOUT_BASE.legend, orientation: 'h', y: 1.08 }},
    hovermode: 'x unified',
  }}, CFG);

  // Gasoline: current vs prior year 4W MA
  Plotly.newPlot('dem-gas', [
    {{ x: d.gasoline_curr.dates, y: d.gasoline_curr.values, mode: 'lines',
       line: {{color:'#60a5fa', width:2.5}}, name: '{CURRENT_YEAR} 4W MA',
       hovertemplate: '%{{x|%b %d}}<br><b>%{{y:.2f}} MMBbl/d</b><extra>{CURRENT_YEAR}</extra>' }},
    {{ x: d.gasoline_prev.dates, y: d.gasoline_prev.values, mode: 'lines',
       line: {{color:'rgba(148,163,184,0.5)', width:1.5, dash:'dash'}}, name: 'Prior Year 4W MA',
       hovertemplate: '%{{x|%b %d}}<br>%{{y:.2f}} MMBbl/d<extra>Prior Year</extra>' }},
  ], {{
    ...LAYOUT_BASE,
    yaxis: {{ ...LAYOUT_BASE.yaxis, title: 'MMBbl/d' }},
    legend: {{ ...LAYOUT_BASE.legend, orientation: 'h', y: 1.1 }},
    hovermode: 'x unified',
  }}, CFG);

  // Distillate + Jet: last 52 weeks
  const distSlice = d.distillate.dates.slice(-52);
  const distVals  = d.distillate.values.slice(-52);
  const jetSlice  = d.jet.dates.slice(-52);
  const jetVals   = d.jet.values.slice(-52);
  Plotly.newPlot('dem-dist', [
    {{ x: distSlice, y: distVals, type: 'bar', name: 'Distillate',
       marker: {{color: 'rgba(251,191,36,0.8)'}},
       hovertemplate: '%{{x|%b %d, %Y}}<br>Distillate: %{{y:.2f}}<extra></extra>' }},
    {{ x: jetSlice, y: jetVals, type: 'bar', name: 'Jet Fuel',
       marker: {{color: 'rgba(96,165,250,0.7)'}},
       hovertemplate: '%{{x|%b %d, %Y}}<br>Jet Fuel: %{{y:.2f}}<extra></extra>' }},
  ], {{
    ...LAYOUT_BASE,
    barmode: 'stack',
    yaxis: {{ ...LAYOUT_BASE.yaxis, title: 'MMBbl/d' }},
    legend: {{ ...LAYOUT_BASE.legend, orientation: 'h', y: 1.1 }},
    hovermode: 'x unified',
  }}, CFG);
}}

// ── Price Structure ───────────────────────────────────────────────────────────
function renderPrices() {{
  const p = DATA.prices;

  // WTI vs Brent + spread
  Plotly.newPlot('price-wti-brent', [
    {{ x: p.wti.dates, y: p.wti.values, mode: 'lines',
       line: {{color:'#60a5fa', width:2}}, name: 'WTI',
       hovertemplate: '%{{x|%b %d, %Y}}<br>WTI: $%{{y:.2f}}<extra></extra>' }},
    {{ x: p.brent.dates, y: p.brent.values, mode: 'lines',
       line: {{color:'#f59e0b', width:2}}, name: 'Brent',
       hovertemplate: '%{{x|%b %d, %Y}}<br>Brent: $%{{y:.2f}}<extra></extra>' }},
    {{ x: p.spread.dates, y: p.spread.values, type: 'bar',
       marker: {{color: p.spread.values.map(v => v >= 0 ? 'rgba(34,197,94,0.5)' : 'rgba(239,68,68,0.5)')}},
       name: 'Brent−WTI (→)', yaxis: 'y2',
       hovertemplate: '%{{x|%b %d, %Y}}<br>Spread: $%{{y:.2f}}<extra>Brent−WTI</extra>' }},
  ], {{
    ...LAYOUT_BASE,
    yaxis:  {{ ...LAYOUT_BASE.yaxis, title: '$/bbl' }},
    yaxis2: {{ title: 'Spread $/bbl', overlaying: 'y', side: 'right',
               gridcolor: 'transparent', zerolinecolor: '#2d3148' }},
    legend: {{ ...LAYOUT_BASE.legend, orientation: 'h', y: 1.08 }},
    hovermode: 'x unified',
  }}, CFG);

  // Crack spread
  Plotly.newPlot('price-crack', [
    {{ x: p.crack.dates, y: p.crack.values, mode: 'lines',
       fill: 'tozeroy',
       fillcolor: p.crack.values.length && p.crack.values[p.crack.values.length-1] > 20
                  ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
       line: {{color:'#34d399', width:2}}, name: '3-2-1 Crack',
       hovertemplate: '%{{x|%b %d, %Y}}<br><b>$%{{y:.2f}}/bbl</b><extra>3-2-1 Crack</extra>' }},
    {{ x: p.crack.dates, y: Array(p.crack.dates.length).fill(20),
       mode: 'lines', line: {{color:'rgba(148,163,184,0.4)', width:1, dash:'dot'}},
       name: '$20 ref', hoverinfo: 'skip' }},
  ], {{
    ...LAYOUT_BASE,
    yaxis: {{ ...LAYOUT_BASE.yaxis, title: '$/bbl', tickprefix: '$' }},
    legend: {{ ...LAYOUT_BASE.legend, orientation: 'h', y: 1.1 }},
    hovermode: 'x unified',
  }}, CFG);

  // WTI vs rig count (2020–present, dual y)
  Plotly.newPlot('price-rig', [
    {{ x: p.wti_long.dates, y: p.wti_long.values, mode: 'lines',
       line: {{color:'#60a5fa', width:2}}, name: 'WTI',
       hovertemplate: '%{{x|%b %Y}}<br>WTI: $%{{y:.1f}}<extra></extra>' }},
    {{ x: p.rig_count_long.dates, y: p.rig_count_long.values, mode: 'lines',
       line: {{color:'#f97316', width:1.5, dash:'dot'}}, name: 'Rig Count (→)', yaxis: 'y2',
       hovertemplate: '%{{x|%b %Y}}<br>Rigs: %{{y}}<extra></extra>' }},
  ], {{
    ...LAYOUT_BASE,
    yaxis:  {{ ...LAYOUT_BASE.yaxis, title: '$/bbl', tickprefix: '$' }},
    yaxis2: {{ title: 'Rig Count', overlaying: 'y', side: 'right',
               gridcolor: 'transparent', zerolinecolor: '#2d3148' }},
    legend: {{ ...LAYOUT_BASE.legend, orientation: 'h', y: 1.1 }},
    hovermode: 'x unified',
  }}, CFG);
}}

// ── Render map & init ─────────────────────────────────────────────────────────
const RENDER = {{
  overview:   renderOverview,
  inventory:  renderInventory,
  production: renderProduction,
  demand:     renderDemand,
  prices:     renderPrices,
}};

rendered['overview'] = true;
renderOverview();
</script>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    from fredapi import Fred
    _fred = Fred(api_key=FRED_API_KEY)

    # 1. EIA petroleum weekly data via public DNAV Excel files (no API key)
    print("Fetching EIA petroleum weekly data via DNAV Excel files...")
    eia = {}
    for name, sid in EIA_SERIES.items():
        try:
            eia[name] = fetch_eia_dnav(sid)
            print(f"  ✓ {name} ({sid}): {len(eia[name])} rows, latest {eia[name].index[-1].date()}")
        except Exception as e:
            print(f"  ✗ {name} ({sid}): {e}")
            eia[name] = pd.Series(dtype=float)

    # 2. FRED price data
    print("\nFetching FRED price data...")
    fred = {}
    for name, sid in FRED_SERIES.items():
        try:
            s = _fred.get_series(sid, observation_start="2018-01-01")
            fred[name] = s.dropna().sort_index()
            print(f"  ✓ {name}: {len(fred[name])} rows, latest {fred[name].index[-1].date()}")
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            fred[name] = pd.Series(dtype=float)

    # Baker Hughes rig count — try multiple FRED series IDs
    rig_count = pd.Series(dtype=float)
    for rig_sid in RIG_COUNT_SERIES_IDS:
        try:
            s = _fred.get_series(rig_sid, observation_start="2018-01-01")
            rig_count = s.dropna().sort_index()
            print(f"  ✓ rig_count ({rig_sid}): {len(rig_count)} rows, latest {rig_count.index[-1].date()}")
            break
        except Exception as e:
            print(f"  ✗ rig_count ({rig_sid}): {e}")
    fred["rig_count"] = rig_count

    # 3. yfinance futures
    print("\nFetching futures data from yfinance...")
    start_2yr = (datetime.today() - timedelta(days=730)).strftime("%Y-%m-%d")
    prices = fetch_price_data(start=start_2yr)

    # 4. Derived series
    # Net imports
    imp = eia.get("imports", pd.Series())
    exp = eia.get("exports", pd.Series())
    common_ie = imp.index.intersection(exp.index)
    net_imports = (imp.loc[common_ie] - exp.loc[common_ie]) * SCALE_PROD

    # 3-2-1 crack spread
    crack = pd.Series(dtype=float)
    if all(t in prices for t in ["CL=F", "RB=F", "HO=F"]):
        try:
            crack = compute_crack_spread(prices["CL=F"], prices["RB=F"], prices["HO=F"])
            print(f"\n  ✓ 3-2-1 Crack: {len(crack)} rows, latest ${crack.iloc[-1]:.2f}/bbl")
        except Exception as e:
            print(f"\n  ✗ Crack spread: {e}")

    # Brent−WTI spread
    wti_d = fred.get("wti", pd.Series())
    brent_d = fred.get("brent", pd.Series())
    spread = pd.Series(dtype=float)
    if len(wti_d) > 0 and len(brent_d) > 0:
        ci = wti_d.index.intersection(brent_d.index)
        spread = brent_d.loc[ci] - wti_d.loc[ci]

    # Production 4W MA
    prod_raw = eia.get("production", pd.Series()) * SCALE_PROD
    prod_ma  = prod_raw.rolling(4).mean().dropna() if isinstance(prod_raw.index, pd.DatetimeIndex) else pd.Series(dtype=float)

    # Gasoline current vs prior year 4W MA
    gas_raw = eia.get("gasoline_supplied", pd.Series()) * SCALE_PROD
    gas_curr = pd.Series(dtype=float)
    gas_prev = pd.Series(dtype=float)
    if isinstance(gas_raw.index, pd.DatetimeIndex) and len(gas_raw) > 0:
        gas_curr = gas_raw[gas_raw.index.year == CURRENT_YEAR].rolling(4, min_periods=1).mean()
        gas_prev_raw = gas_raw[gas_raw.index.year == (CURRENT_YEAR - 1)].rolling(4, min_periods=1).mean()
        gas_prev = gas_prev_raw.copy()
        gas_prev.index = gas_prev.index + pd.DateOffset(years=1)

    # 5. 5-year seasonal bands
    print("\nComputing 5-year seasonal bands...")
    bands = {}
    for name in ["crude_stocks", "cushing_stocks", "refinery_util"]:
        if len(eia.get(name, pd.Series())) > 100:
            bands[name] = compute_5yr_band(eia[name])
            print(f"  ✓ {name}: {len(bands[name])} weeks")

    empty_band = pd.DataFrame(columns=["week", "ref_date", "min", "max", "mean"])

    # 6. Overview scorecard
    overview = compute_overview(eia, fred, crack)

    # 7. Last-12-months filter for price charts
    start_12m = (datetime.today() - timedelta(days=365)).strftime("%Y-%m-%d")
    start_2020 = "2020-01-01"

    def trim(s, start):
        return s[s.index >= pd.Timestamp(start)] if len(s) > 0 else s

    # 8. Assemble payload
    payload = {
        "last_updated": date.today().strftime("%B %d, %Y"),
        "overview": overview,
        "inventory": {
            "crude":       to_payload(eia.get("crude_stocks", pd.Series()) * SCALE_STOCKS),
            "crude_band":  band_to_payload(bands.get("crude_stocks", empty_band)),
            "cushing":     to_payload(eia.get("cushing_stocks", pd.Series()) * SCALE_STOCKS),
            "cushing_band": band_to_payload(bands.get("cushing_stocks", empty_band)),
            "spr":         to_payload(trim(eia.get("spr_stocks", pd.Series()) * SCALE_STOCKS, start_2020)),
        },
        "production": {
            "production":    to_payload(trim(prod_raw, start_2020)),
            "production_ma": to_payload(trim(prod_ma, start_2020)),
            "net_imports":   to_payload(trim(net_imports, start_2020)),
            "rig_count":     to_payload(trim(fred.get("rig_count", pd.Series()), start_2020), decimals=0),
        },
        "demand": {
            "refinery_util":  to_payload(eia.get("refinery_util", pd.Series())),
            "refinery_band":  band_to_payload(bands.get("refinery_util", empty_band)),
            "gasoline_curr":  to_payload(gas_curr),
            "gasoline_prev":  to_payload(gas_prev),
            "distillate":     to_payload(trim(eia.get("distillate_supplied", pd.Series()) * SCALE_PROD, start_2020)),
            "jet":            to_payload(trim(eia.get("jet_supplied", pd.Series()) * SCALE_PROD, start_2020)),
        },
        "prices": {
            "wti":           to_payload(trim(wti_d, start_12m)),
            "brent":         to_payload(trim(brent_d, start_12m)),
            "spread":        to_payload(trim(spread, start_12m)),
            "crack":         to_payload(trim(crack, start_12m)),
            "wti_long":      to_payload(trim(wti_d, start_2020)),
            "rig_count_long": to_payload(trim(fred.get("rig_count", pd.Series()), start_2020), decimals=0),
        },
    }

    data_json = json.dumps(payload, allow_nan=False, default=str)
    html = build_html(data_json, date.today().strftime("%B %d, %Y"))
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"\n✅ Dashboard saved → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

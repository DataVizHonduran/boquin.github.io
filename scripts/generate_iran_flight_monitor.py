#!/usr/bin/env python3
"""
Iran Airspace Monitor
=====================
Tracks daily flight counts at 8 strategic Iranian airports and 10 major
airports in neighboring countries using the FlightRadar24 API. A sustained
drop in flights signals airspace closure, carrier pullout, or active conflict
disruption near Iran.

Iranian airports monitored:
  IKA  Tehran Imam Khomeini  — main international gateway
  THR  Tehran Mehrabad       — domestic hub + regional flights
  BND  Bandar Abbas          — Strait of Hormuz, naval/military proximity
  IFN  Isfahan               — near nuclear/military facilities
  SYZ  Shiraz                — major southern hub
  MHD  Mashhad               — northeast hub, near Afghanistan
  AWZ  Ahvaz                 — near Iraq/Kuwait border
  KSH  Kermanshah            — near Iraq border

Neighboring country airports monitored:
  DXB  Dubai International        — UAE
  IST  Istanbul Airport           — Turkey
  DOH  Hamad International        — Qatar
  AUH  Abu Dhabi International    — UAE
  KWI  Kuwait International       — Kuwait
  BGW  Baghdad International      — Iraq
  GYD  Baku Heydar Aliyev         — Azerbaijan
  KHI  Karachi Jinnah             — Pakistan
  RUH  King Khalid (Riyadh)       — Saudi Arabia
  ASB  Ashgabat International     — Turkmenistan

Data source:
  FlightRadar24 API v1 — https://fr24api.flightradar24.com
  Endpoint: GET /api/v1/flights/summary/light
  Auth: Bearer token via FR24_API_KEY environment variable

Cache:
  reports/iran-flight-monitor/data/cache.json  (committed to repo)
  Format: { "IKA": { "2025-10-01": {"arrivals": 42, "departures": 40}, ... }, ... }
  Only missing dates are fetched on each run (cache-forward pattern).

Output:
  reports/iran-flight-monitor/index.html

Environment variables:
  FR24_API_KEY   — FlightRadar24 API key (Explorer tier or higher)

Run from repo root:
  cd ~/boquin.github.io
  FR24_API_KEY=xxx python3 scripts/generate_iran_flight_monitor.py

Authors: boquin.github.io
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, date, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
FR24_API_KEY = os.environ.get("FR24_API_KEY")
if not FR24_API_KEY:
    print("ERROR: FR24_API_KEY environment variable is not set.", file=sys.stderr)
    sys.exit(1)

CONFLICT_START_DATE = "2025-10-01"   # adjust to actual escalation date
LOOKBACK_DAYS = 90
RATE_LIMIT_SLEEP = 0.6               # seconds between API calls

AIRPORTS = [
    # ── Iran ──────────────────────────────────────────────────────────────────
    {"iata": "IKA", "icao": "OIIE", "name": "Tehran Imam Khomeini", "flag": "🇮🇷", "group": "Iran"},
    {"iata": "THR", "icao": "OIII", "name": "Tehran Mehrabad",       "flag": "🇮🇷", "group": "Iran"},
    {"iata": "BND", "icao": "OIKB", "name": "Bandar Abbas",          "flag": "🇮🇷", "group": "Iran"},
    {"iata": "IFN", "icao": "OIFM", "name": "Isfahan",               "flag": "🇮🇷", "group": "Iran"},
    {"iata": "SYZ", "icao": "OISF", "name": "Shiraz",                "flag": "🇮🇷", "group": "Iran"},
    {"iata": "MHD", "icao": "OIMM", "name": "Mashhad",               "flag": "🇮🇷", "group": "Iran"},
    {"iata": "AWZ", "icao": "OIAW", "name": "Ahvaz",                 "flag": "🇮🇷", "group": "Iran"},
    {"iata": "KSH", "icao": "OICC", "name": "Kermanshah",            "flag": "🇮🇷", "group": "Iran"},
    # ── Neighboring countries ─────────────────────────────────────────────────
    {"iata": "DXB", "icao": "OMDB", "name": "Dubai International",      "flag": "🇦🇪", "group": "Neighbors"},
    {"iata": "IST", "icao": "LTFM", "name": "Istanbul Airport",         "flag": "🇹🇷", "group": "Neighbors"},
    {"iata": "DOH", "icao": "OTHH", "name": "Hamad International",      "flag": "🇶🇦", "group": "Neighbors"},
    {"iata": "AUH", "icao": "OMAA", "name": "Abu Dhabi International",  "flag": "🇦🇪", "group": "Neighbors"},
    {"iata": "KWI", "icao": "OKBK", "name": "Kuwait International",     "flag": "🇰🇼", "group": "Neighbors"},
    {"iata": "BGW", "icao": "ORBI", "name": "Baghdad International",    "flag": "🇮🇶", "group": "Neighbors"},
    {"iata": "GYD", "icao": "UBBB", "name": "Baku Heydar Aliyev",       "flag": "🇦🇿", "group": "Neighbors"},
    {"iata": "KHI", "icao": "OPKC", "name": "Karachi Jinnah",           "flag": "🇵🇰", "group": "Neighbors"},
    {"iata": "RUH", "icao": "OERK", "name": "King Khalid (Riyadh)",     "flag": "🇸🇦", "group": "Neighbors"},
    {"iata": "ASB", "icao": "UTAA", "name": "Ashgabat International",   "flag": "🇹🇲", "group": "Neighbors"},
]

REPO_ROOT = Path(__file__).parent.parent
CACHE_PATH = REPO_ROOT / "reports/iran-flight-monitor/data/cache.json"
OUTPUT_PATH = REPO_ROOT / "reports/iran-flight-monitor/index.html"

FR24_BASE = "https://fr24api.flightradar24.com"


# ── Cache I/O ─────────────────────────────────────────────────────────────────
def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_cache(cache: dict):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2, sort_keys=True)


# ── FR24 API ──────────────────────────────────────────────────────────────────
def fr24_headers() -> dict:
    return {
        "Authorization": f"Bearer {FR24_API_KEY}",
        "Accept": "application/json",
        "Accept-Version": "v1",
    }


def fetch_flights_for_day(iata: str, day: date) -> dict:
    """
    Fetch arrivals and departures for one airport on one calendar day.
    Returns {"arrivals": int, "departures": int}.
    Uses /api/v1/flights/summary/light with pagination.
    Falls back to arrivals + departures endpoints if summary doesn't support
    airport filtering at the Explorer tier.
    """
    day_from = f"{day}T00:00:00Z"
    day_to   = f"{day}T23:59:59Z"

    arrivals = 0
    departures = 0

    # Try summary/light first
    url = f"{FR24_BASE}/api/v1/flights/summary/light"
    page = 1
    per_page = 100
    found_any = False

    while True:
        params = {
            "airport":              iata,
            "flight_datetime_from": day_from,
            "flight_datetime_to":   day_to,
            "limit":                per_page,
            "page":                 page,
        }
        try:
            resp = requests.get(url, headers=fr24_headers(), params=params, timeout=30)
            if resp.status_code == 404:
                return None   # airport not in FR24 database
            if resp.status_code == 422:
                # endpoint doesn't support airport filter at this tier — fall back
                break
            resp.raise_for_status()
            data = resp.json()
            flights = data.get("data", [])
            if not flights:
                break
            found_any = True
            for flight in flights:
                dest   = (flight.get("destination", {}) or {}).get("iata", "")
                origin = (flight.get("origin", {}) or {}).get("iata", "")
                if dest.upper() == iata.upper():
                    arrivals += 1
                if origin.upper() == iata.upper():
                    departures += 1
            # pagination
            meta = data.get("meta", {})
            total = meta.get("total", 0) if meta else 0
            if page * per_page >= total or len(flights) < per_page:
                break
            page += 1
            time.sleep(RATE_LIMIT_SLEEP)
        except requests.RequestException as e:
            print(f"  Warning: summary/light error for {iata} {day}: {e}")
            break

    if found_any:
        return {"arrivals": arrivals, "departures": departures}

    # Fallback: dedicated arrivals + departures endpoints
    arrivals = _fetch_endpoint_count(iata, day_from, day_to, "arrivals")
    if arrivals is None:
        return None   # airport not in FR24 database
    time.sleep(RATE_LIMIT_SLEEP)
    departures = _fetch_endpoint_count(iata, day_from, day_to, "departures")
    return {"arrivals": arrivals, "departures": departures or 0}


def _fetch_endpoint_count(iata: str, day_from: str, day_to: str, direction: str) -> int:
    """
    Fetch total flight count from /api/v1/airports/{iata}/arrivals or /departures.
    Paginates until exhausted.
    """
    url = f"{FR24_BASE}/api/v1/airports/{iata}/{direction}"
    page = 1
    count = 0
    per_page = 100

    while True:
        params = {
            "flight_datetime_from": day_from,
            "flight_datetime_to":   day_to,
            "limit":                per_page,
            "page":                 page,
        }
        try:
            resp = requests.get(url, headers=fr24_headers(), params=params, timeout=30)
            if resp.status_code == 404:
                return None   # airport not in FR24 database
            resp.raise_for_status()
            data = resp.json()
            flights = data.get("data", [])
            if not flights:
                break
            count += len(flights)
            meta = data.get("meta", {})
            total = meta.get("total", 0) if meta else 0
            if page * per_page >= total or len(flights) < per_page:
                break
            page += 1
            time.sleep(RATE_LIMIT_SLEEP)
        except requests.RequestException as e:
            print(f"  Warning: {direction} endpoint error for {iata}: {e}")
            break

    return count


# ── Stats ─────────────────────────────────────────────────────────────────────
def compute_stats(cache: dict, iata: str, today: date) -> dict:
    """
    Compute rolling averages, baseline, and % change for one airport.
    Returns series (list of dicts) and summary scalars.
    """
    airport_cache = cache.get(iata, {})
    window_start = today - timedelta(days=LOOKBACK_DAYS - 1)
    conflict_start = date.fromisoformat(CONFLICT_START_DATE)

    # Build daily series for the 90-day window
    series = []
    for n in range(LOOKBACK_DAYS):
        d = window_start + timedelta(days=n)
        key = str(d)
        rec = airport_cache.get(key)
        if rec:
            total = rec["arrivals"] + rec["departures"]
            series.append({"date": key, "arrivals": rec["arrivals"],
                           "departures": rec["departures"], "total": total})
        else:
            series.append({"date": key, "arrivals": None,
                           "departures": None, "total": None})

    # Pre-conflict baseline (all cached dates before conflict start)
    baseline_vals = [
        v["arrivals"] + v["departures"]
        for k, v in airport_cache.items()
        if date.fromisoformat(k) < conflict_start
        and v["arrivals"] is not None and v["departures"] is not None
    ]
    baseline_avg = round(sum(baseline_vals) / len(baseline_vals), 1) if baseline_vals else None

    # 7D and 30D rolling avg (most recent complete days)
    recent_totals = [s["total"] for s in series[-7:] if s["total"] is not None]
    avg_7d = round(sum(recent_totals) / len(recent_totals), 1) if recent_totals else None

    recent_30 = [s["total"] for s in series[-30:] if s["total"] is not None]
    avg_30d = round(sum(recent_30) / len(recent_30), 1) if recent_30 else None

    pct_vs_baseline = None
    if avg_7d is not None and baseline_avg and baseline_avg > 0:
        pct_vs_baseline = round((avg_7d - baseline_avg) / baseline_avg * 100, 1)

    return {
        "series":         series,
        "avg_7d":         avg_7d,
        "avg_30d":        avg_30d,
        "baseline_avg":   baseline_avg,
        "pct_vs_baseline": pct_vs_baseline,
    }


# ── HTML rendering ────────────────────────────────────────────────────────────
def render_html(stats_by_airport: dict, today: date) -> str:
    updated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Build per-airport chart specs for inline JS
    airport_data_js = []
    for ap in AIRPORTS:
        iata = ap["iata"]
        st = stats_by_airport[iata]
        ser = st["series"]

        dates      = [s["date"] for s in ser]
        arrivals   = [s["arrivals"] for s in ser]
        departures = [s["departures"] for s in ser]

        # 7D rolling average on total
        totals = [s["total"] for s in ser]
        rolling7 = []
        for i in range(len(totals)):
            window = [t for t in totals[max(0, i-6):i+1] if t is not None]
            rolling7.append(round(sum(window)/len(window), 1) if window else None)

        airport_data_js.append({
            "iata":      iata,
            "name":      ap["name"],
            "flag":      ap["flag"],
            "group":     ap["group"],
            "dates":     dates,
            "arrivals":  arrivals,
            "departures": departures,
            "rolling7":  rolling7,
            "avg_7d":    st["avg_7d"],
            "avg_30d":   st["avg_30d"],
            "baseline":  st["baseline_avg"],
            "pct":       st["pct_vs_baseline"],
        })

    data_json = json.dumps(airport_data_js)
    conflict_date = CONFLICT_START_DATE

    tab_buttons = ""
    last_group = None
    for i, ap in enumerate(AIRPORTS):
        if ap["group"] != last_group:
            label = "🇮🇷 Iran" if ap["group"] == "Iran" else "🌍 Neighbors"
            tab_buttons += f'<span class="tab-group-label">{label}</span>\n'
            last_group = ap["group"]
        active = "active" if i == 0 else ""
        tab_buttons += f'<button class="tab-btn {active}" onclick="showTab(\'{ap["iata"]}\')" id="tab-{ap["iata"]}">{ap["flag"]} {ap["iata"]}</button>\n'

    tab_buttons += '<span class="tab-group-label">─</span>\n'
    tab_buttons += '<button class="tab-btn" onclick="showTab(\'ALL\')" id="tab-ALL">All</button>\n'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Iran Airspace Monitor — boquin.xyz</title>
<script src="https://cdn.plot.ly/plotly-3.4.0.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f8f9fa; color: #1a1a2e; min-height: 100vh;
  }}
  header {{
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
    color: #fff; padding: 28px 24px 22px;
  }}
  header h1 {{ font-size: 1.7rem; font-weight: 700; letter-spacing: -0.02em; }}
  header .subtitle {{ font-size: 0.9rem; color: #a8b3cf; margin-top: 4px; }}
  header .updated {{ font-size: 0.78rem; color: #7a8ba8; margin-top: 6px; }}
  .conflict-strip {{
    background: #fff3cd; border-left: 4px solid #e6a817; padding: 10px 20px;
    font-size: 0.85rem; color: #664d03;
  }}
  nav.tabs {{
    background: #fff; border-bottom: 1px solid #e2e8f0;
    padding: 0 20px; display: flex; flex-wrap: wrap; gap: 2px;
  }}
  .tab-btn {{
    background: none; border: none; padding: 12px 16px;
    font-size: 0.88rem; font-weight: 500; cursor: pointer;
    color: #64748b; border-bottom: 3px solid transparent;
    transition: all 0.15s;
  }}
  .tab-btn:hover {{ color: #0f3460; }}
  .tab-btn.active {{ color: #0f3460; border-bottom-color: #0f3460; }}
  .tab-group-label {{
    display: flex; align-items: center; padding: 0 8px;
    font-size: 0.72rem; font-weight: 600; color: #94a3b8;
    text-transform: uppercase; letter-spacing: 0.06em; white-space: nowrap;
  }}
  main {{ max-width: 1200px; margin: 0 auto; padding: 24px 20px; }}
  .tab-panel {{ display: none; }}
  .tab-panel.active {{ display: block; }}
  .panel-header {{ margin-bottom: 14px; }}
  .panel-header h2 {{ font-size: 1.2rem; font-weight: 600; }}
  .stats-row {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
    margin: 16px 0;
  }}
  .stat-card {{
    background: #fff; border-radius: 8px; padding: 14px 16px;
    border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,.05);
  }}
  .stat-label {{ font-size: 0.75rem; color: #64748b; text-transform: uppercase;
    letter-spacing: 0.05em; margin-bottom: 4px; }}
  .stat-value {{ font-size: 1.4rem; font-weight: 700; color: #0f3460; }}
  .stat-value.negative {{ color: #dc2626; }}
  .stat-value.positive {{ color: #16a34a; }}
  .chart-box {{ background: #fff; border-radius: 8px; border: 1px solid #e2e8f0;
    box-shadow: 0 1px 3px rgba(0,0,0,.05); overflow: hidden; }}
  .all-grid {{
    display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px;
    margin-top: 8px;
  }}
  .mini-card {{ background: #fff; border-radius: 8px; border: 1px solid #e2e8f0;
    padding: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.05); }}
  .mini-card h4 {{ font-size: 0.9rem; font-weight: 600; margin-bottom: 8px; }}
  .methodology {{
    margin-top: 32px; background: #fff; border-radius: 8px; padding: 20px 24px;
    border: 1px solid #e2e8f0; font-size: 0.85rem; color: #475569; line-height: 1.7;
  }}
  .methodology h3 {{ font-size: 1rem; font-weight: 600; color: #1a1a2e;
    margin-bottom: 10px; }}
  footer {{
    text-align: center; padding: 24px; font-size: 0.8rem; color: #94a3b8;
    border-top: 1px solid #e2e8f0; margin-top: 32px;
  }}
  @media (max-width: 640px) {{
    .stats-row {{ grid-template-columns: repeat(2, 1fr); }}
    .all-grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>

<header>
  <h1>✈️ Iran Airspace Monitor</h1>
  <div class="subtitle">Daily flight counts at Iranian airports and neighboring hubs — tracking conflict-related airspace disruption</div>
  <div class="updated">Last updated: {updated}</div>
</header>

<div class="conflict-strip">
  ⚠️ Conflict reference date: <strong>{conflict_date}</strong> — vertical line on each chart.
  A sustained drop in total flights (arrivals + departures) may signal airspace closure,
  carrier pullout, or active conflict disruption. Note: Iran restricts ADS-B transponder
  data; FlightRadar24 coverage may undercount actual military or domestic traffic.
</div>

<nav class="tabs">
{tab_buttons}</nav>

<main>
  <div id="panels">
  </div>

  <div class="methodology">
    <h3>Methodology &amp; Caveats</h3>
    <p><strong>Data source:</strong> FlightRadar24 API v1 (<code>/api/v1/flights/summary/light</code>).
    Flights are counted per calendar day (UTC) per airport by IATA code. Each daily count
    reflects the sum of arrivals (destination = airport) and departures (origin = airport)
    as reported in the FR24 database.</p>
    <p style="margin-top:8px"><strong>Pre-conflict baseline:</strong> Average daily total flights
    in all cached dates before {conflict_date}. The % vs. baseline metric compares the
    most recent 7-day rolling average against this baseline.</p>
    <p style="margin-top:8px"><strong>Coverage caveat:</strong> Iran restricts ADS-B transponder
    broadcasts; FlightRadar24 relies on ground receiver networks which have limited coverage
    inside Iranian airspace. Counts reflect tracked flights only and may significantly undercount
    actual military, cargo, or short-haul domestic traffic.</p>
    <p style="margin-top:8px"><strong>Cache:</strong> Historical data is cached in
    <code>reports/iran-flight-monitor/data/cache.json</code>. Only missing dates are
    fetched on each run to minimize API usage.</p>
  </div>
</main>

<footer>
  <a href="https://boquin.xyz" style="color:#94a3b8">boquin.xyz</a> &mdash;
  Source: <a href="https://github.com/DataVizHonduran/boquin.github.io/tree/main/scripts/generate_iran_flight_monitor.py"
    style="color:#94a3b8">generate_iran_flight_monitor.py</a>
</footer>

<script>
const AIRPORTS = {data_json};
const CONFLICT_DATE = "{conflict_date}";

function fmtNum(v) {{
  if (v === null || v === undefined) return "—";
  return v.toFixed(1);
}}

function pctColor(v) {{
  if (v === null || v === undefined) return "";
  return v < 0 ? "negative" : "positive";
}}

function pctStr(v) {{
  if (v === null || v === undefined) return "—";
  const sign = v > 0 ? "+" : "";
  return sign + v.toFixed(1) + "%";
}}

function buildChart(ap, divId, height) {{
  const traces = [
    {{
      type: "bar", name: "Arrivals",
      x: ap.dates, y: ap.arrivals,
      marker: {{ color: "#3b82f6" }},
    }},
    {{
      type: "bar", name: "Departures",
      x: ap.dates, y: ap.departures,
      marker: {{ color: "#93c5fd" }},
    }},
    {{
      type: "scatter", name: "7D Avg", mode: "lines",
      x: ap.dates, y: ap.rolling7,
      line: {{ color: "#dc2626", width: 2, dash: "solid" }},
    }},
  ];

  const shapes = [{{
    type: "line", xref: "x", yref: "paper",
    x0: CONFLICT_DATE, x1: CONFLICT_DATE,
    y0: 0, y1: 1,
    line: {{ color: "#f97316", width: 2, dash: "dot" }},
  }}];

  const annotations = [{{
    xref: "x", yref: "paper",
    x: CONFLICT_DATE, y: 1,
    text: "Conflict ref",
    showarrow: false,
    font: {{ size: 10, color: "#f97316" }},
    xanchor: "left", yanchor: "top",
    xshift: 4,
  }}];

  const layout = {{
    barmode: "stack",
    height: height || 340,
    margin: {{ t: 20, r: 20, b: 60, l: 50 }},
    paper_bgcolor: "#fff", plot_bgcolor: "#fff",
    xaxis: {{
      type: "date", gridcolor: "#f1f5f9",
      tickfont: {{ size: 11 }}, showgrid: true,
    }},
    yaxis: {{
      title: "Flights", gridcolor: "#f1f5f9",
      tickfont: {{ size: 11 }}, rangemode: "tozero",
    }},
    legend: {{ orientation: "h", y: -0.18, font: {{ size: 11 }} }},
    shapes: shapes,
    annotations: annotations,
  }};

  Plotly.newPlot(divId, traces, layout, {{responsive: true, displayModeBar: false}});
}}

function buildStatsRow(ap) {{
  return `
  <div class="stats-row">
    <div class="stat-card">
      <div class="stat-label">7D Avg (total flights)</div>
      <div class="stat-value">${{fmtNum(ap.avg_7d)}}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">30D Avg</div>
      <div class="stat-value">${{fmtNum(ap.avg_30d)}}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Pre-conflict baseline</div>
      <div class="stat-value">${{fmtNum(ap.baseline)}}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">7D avg vs baseline</div>
      <div class="stat-value ${{pctColor(ap.pct)}}">${{pctStr(ap.pct)}}</div>
    </div>
  </div>`;
}}

function buildPanels() {{
  const container = document.getElementById("panels");

  // Per-airport panels
  AIRPORTS.forEach((ap, idx) => {{
    const panel = document.createElement("div");
    panel.className = "tab-panel" + (idx === 0 ? " active" : "");
    panel.id = "panel-" + ap.iata;
    panel.innerHTML = `
      <div class="panel-header">
        <h2>${{ap.iata}} — ${{ap.name}}</h2>
      </div>
      ${{buildStatsRow(ap)}}
      <div class="chart-box">
        <div id="chart-${{ap.iata}}" style="width:100%"></div>
      </div>`;
    container.appendChild(panel);
  }});

  // All airports panel
  const allPanel = document.createElement("div");
  allPanel.className = "tab-panel";
  allPanel.id = "panel-ALL";
  let allHtml = '<div class="panel-header"><h2>All 8 Airports — Overview</h2></div><div class="all-grid">';
  AIRPORTS.forEach(ap => {{
    allHtml += `<div class="mini-card">
      <h4>${{ap.iata}} — ${{ap.name}}</h4>
      <div id="mini-chart-${{ap.iata}}" style="width:100%"></div>
    </div>`;
  }});
  allHtml += "</div>";
  allPanel.innerHTML = allHtml;
  container.appendChild(allPanel);
}}

function showTab(iata) {{
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  document.getElementById("panel-" + iata).classList.add("active");
  document.getElementById("tab-" + iata).classList.add("active");

  if (iata === "ALL") {{
    // Build mini charts if not already built
    AIRPORTS.forEach(ap => {{
      const el = document.getElementById("mini-chart-" + ap.iata);
      if (el && el.children.length === 0) {{
        buildChart(ap, "mini-chart-" + ap.iata, 200);
      }}
    }});
  }}
}}

// Init
buildPanels();
AIRPORTS.forEach(ap => buildChart(ap, "chart-" + ap.iata, 340));
</script>
</body>
</html>"""
    return html


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    today = date.today()
    window_start = today - timedelta(days=LOOKBACK_DAYS - 1)

    print(f"Iran Airspace Monitor — {today}")
    print(f"Window: {window_start} → {today}  ({LOOKBACK_DAYS} days)")
    print()

    cache = load_cache()
    total_fetched = 0

    for ap in AIRPORTS:
        iata = ap["iata"]
        print(f"[{iata}] {ap['name']}")

        if iata not in cache:
            cache[iata] = {}

        airport_cache = cache[iata]
        missing_dates = []
        d = window_start
        while d <= today:
            if str(d) not in airport_cache:
                missing_dates.append(d)
            d += timedelta(days=1)

        if not missing_dates:
            print(f"  All {LOOKBACK_DAYS} days cached, skipping.")
        else:
            print(f"  Fetching {len(missing_dates)} missing date(s)...")
            not_found_streak = 0
            for i, day in enumerate(missing_dates):
                print(f"  [{i+1}/{len(missing_dates)}] {day} ...", end=" ", flush=True)
                try:
                    result = fetch_flights_for_day(iata, day)
                    if result is None:
                        not_found_streak += 1
                        print("not in FR24 (skipped)")
                        if not_found_streak >= 3:
                            print(f"  {iata} returned 404 three times in a row — skipping remaining dates.")
                            break
                    else:
                        not_found_streak = 0
                        airport_cache[str(day)] = result
                        total = result["arrivals"] + result["departures"]
                        print(f"arr={result['arrivals']} dep={result['departures']} total={total}")
                        total_fetched += 1
                except Exception as e:
                    print(f"ERROR: {e}")
                time.sleep(RATE_LIMIT_SLEEP)

    print()
    print(f"Total API calls made: {total_fetched}")
    save_cache(cache)
    print(f"Cache saved → {CACHE_PATH}")

    # Compute stats
    print("Computing stats...")
    stats_by_airport = {}
    for ap in AIRPORTS:
        stats_by_airport[ap["iata"]] = compute_stats(cache, ap["iata"], today)

    # Render
    print("Rendering HTML...")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    html = render_html(stats_by_airport, today)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard → {OUTPUT_PATH}")
    print("Done.")


if __name__ == "__main__":
    main()

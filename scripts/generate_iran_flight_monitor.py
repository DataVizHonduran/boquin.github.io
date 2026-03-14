#!/usr/bin/env python3
"""
Iran Airspace Monitor
=====================
Tracks daily flight counts at 10 major airports in Iran's neighboring region
using the OpenSky Network API. A sustained drop in flights signals airspace
closure, carrier pullout, or active conflict disruption near Iran.

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
  OpenSky Network API — https://opensky-network.org/api
  Endpoints: /flights/arrival and /flights/departure
  Auth: OAuth2 client credentials (OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET)

Cache:
  reports/iran-flight-monitor/data/cache.json  (committed to repo)
  Format: { "DXB": { "2025-10-01": {"arrivals": 42, "departures": 40}, ... }, ... }
  Only missing dates are fetched on each run (cache-forward pattern).

Output:
  reports/iran-flight-monitor/index.html

Environment variables:
  OPENSKY_CLIENT_ID     — OpenSky OAuth2 client ID
  OPENSKY_CLIENT_SECRET — OpenSky OAuth2 client secret

Run from repo root:
  cd ~/boquin.github.io
  OPENSKY_CLIENT_ID=xxx OPENSKY_CLIENT_SECRET=yyy python3 scripts/generate_iran_flight_monitor.py

Authors: boquin.github.io
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
OPENSKY_CLIENT_ID     = os.environ.get("OPENSKY_CLIENT_ID")
OPENSKY_CLIENT_SECRET = os.environ.get("OPENSKY_CLIENT_SECRET")
if not OPENSKY_CLIENT_ID or not OPENSKY_CLIENT_SECRET:
    print("ERROR: OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET must be set", file=sys.stderr)
    sys.exit(1)

OPENSKY_BASE      = "https://opensky-network.org/api"
OPENSKY_TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"

CONFLICT_START_DATE = "2025-10-01"   # adjust to actual escalation date
LOOKBACK_DAYS = 90
RATE_LIMIT_SLEEP = 0.5               # seconds between API calls
WINDOW_DAYS = 2                      # OpenSky max: 2 calendar-day partitions per request

AIRPORTS = [
    {"iata": "DXB", "icao": "OMDB", "name": "Dubai International",     "flag": "🇦🇪"},
    {"iata": "IST", "icao": "LTFM", "name": "Istanbul Airport",        "flag": "🇹🇷"},
    {"iata": "DOH", "icao": "OTHH", "name": "Hamad International",     "flag": "🇶🇦"},
    {"iata": "AUH", "icao": "OMAA", "name": "Abu Dhabi International", "flag": "🇦🇪"},
    {"iata": "KWI", "icao": "OKBK", "name": "Kuwait International",    "flag": "🇰🇼"},
    {"iata": "BGW", "icao": "ORBI", "name": "Baghdad International",   "flag": "🇮🇶"},
    {"iata": "GYD", "icao": "UBBB", "name": "Baku Heydar Aliyev",      "flag": "🇦🇿"},
    {"iata": "KHI", "icao": "OPKC", "name": "Karachi Jinnah",          "flag": "🇵🇰"},
    {"iata": "RUH", "icao": "OERK", "name": "King Khalid (Riyadh)",    "flag": "🇸🇦"},
    {"iata": "ASB", "icao": "UTAA", "name": "Ashgabat International",  "flag": "🇹🇲"},
]

REPO_ROOT  = Path(__file__).parent.parent
CACHE_PATH = REPO_ROOT / "reports/iran-flight-monitor/data/cache.json"
OUTPUT_PATH = REPO_ROOT / "reports/iran-flight-monitor/index.html"


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


# ── OpenSky Auth ──────────────────────────────────────────────────────────────
def get_token() -> str:
    resp = requests.post(OPENSKY_TOKEN_URL, data={
        "client_id": OPENSKY_CLIENT_ID,
        "client_secret": OPENSKY_CLIENT_SECRET,
        "grant_type": "client_credentials",
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


# ── OpenSky API ───────────────────────────────────────────────────────────────
def fetch_window(icao: str, begin: int, end: int, direction: str, token: str) -> tuple:
    """Fetch one airport/direction/window. Returns (flights, token) — token may be refreshed on 401."""
    url = f"{OPENSKY_BASE}/flights/{direction}"
    resp = requests.get(url,
        params={"airport": icao, "begin": begin, "end": end},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30)
    if resp.status_code == 404:
        return [], token
    if resp.status_code == 401:
        print("  Token expired — refreshing...")
        token = get_token()
        print("  Token refreshed.")
        return fetch_window(icao, begin, end, direction, token)
    if resp.status_code == 429:
        retry_after = min(int(resp.headers.get("X-Rate-Limit-Retry-After-Seconds", 60)), 120)
        print(f"  Rate limited — sleeping {retry_after}s")
        time.sleep(retry_after)
        return fetch_window(icao, begin, end, direction, token)
    if not resp.ok:
        print(f"  HTTP {resp.status_code} body: {resp.text[:400]}")
        resp.raise_for_status()
    return resp.json() or [], token


def window_to_daily_counts(flights: list, direction: str) -> dict:
    """Map flight records to {date_str: count} using UTC date of firstSeen/lastSeen."""
    counts = {}
    ts_field = "firstSeen" if direction == "departure" else "lastSeen"
    for f in flights:
        ts = f.get(ts_field)
        if ts:
            day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
            counts[day] = counts.get(day, 0) + 1
    return counts


def date_to_unix(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def windows_of_n(dates: list, n: int) -> list:
    """Group sorted dates into consecutive n-day windows starting from each new gap."""
    if not dates:
        return []
    result = []
    current_start = dates[0]
    for d in dates:
        if (d - current_start).days >= n:
            result.append(current_start)
            current_start = d
    result.append(current_start)
    return result


# ── Stats ─────────────────────────────────────────────────────────────────────
def compute_stats(cache: dict, iata: str, today: date) -> dict:
    airport_cache = cache.get(iata, {})
    window_start = today - timedelta(days=LOOKBACK_DAYS - 1)
    conflict_start = date.fromisoformat(CONFLICT_START_DATE)

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

    baseline_vals = [
        v["arrivals"] + v["departures"]
        for k, v in airport_cache.items()
        if date.fromisoformat(k) < conflict_start
        and v["arrivals"] is not None and v["departures"] is not None
    ]
    baseline_avg = round(sum(baseline_vals) / len(baseline_vals), 1) if baseline_vals else None

    recent_totals = [s["total"] for s in series[-7:] if s["total"] is not None]
    avg_7d = round(sum(recent_totals) / len(recent_totals), 1) if recent_totals else None

    recent_30 = [s["total"] for s in series[-30:] if s["total"] is not None]
    avg_30d = round(sum(recent_30) / len(recent_30), 1) if recent_30 else None

    pct_vs_baseline = None
    if avg_7d is not None and baseline_avg and baseline_avg > 0:
        pct_vs_baseline = round((avg_7d - baseline_avg) / baseline_avg * 100, 1)

    return {
        "series":          series,
        "avg_7d":          avg_7d,
        "avg_30d":         avg_30d,
        "baseline_avg":    baseline_avg,
        "pct_vs_baseline": pct_vs_baseline,
    }


# ── HTML rendering ────────────────────────────────────────────────────────────
def render_html(stats_by_airport: dict, today: date) -> str:
    updated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    airport_data_js = []
    for ap in AIRPORTS:
        iata = ap["iata"]
        st = stats_by_airport[iata]
        ser = st["series"]

        dates      = [s["date"] for s in ser]
        arrivals   = [s["arrivals"] for s in ser]
        departures = [s["departures"] for s in ser]

        totals = [s["total"] for s in ser]
        rolling7 = []
        for i in range(len(totals)):
            window = [t for t in totals[max(0, i-6):i+1] if t is not None]
            rolling7.append(round(sum(window)/len(window), 1) if window else None)

        airport_data_js.append({
            "iata":       iata,
            "name":       ap["name"],
            "flag":       ap["flag"],
            "dates":      dates,
            "arrivals":   arrivals,
            "departures": departures,
            "rolling7":   rolling7,
            "avg_7d":     st["avg_7d"],
            "avg_30d":    st["avg_30d"],
            "baseline":   st["baseline_avg"],
            "pct":        st["pct_vs_baseline"],
        })

    data_json = json.dumps(airport_data_js)
    conflict_date = CONFLICT_START_DATE

    tab_buttons = ""
    for i, ap in enumerate(AIRPORTS):
        active = "active" if i == 0 else ""
        tab_buttons += f'<button class="tab-btn {active}" onclick="showTab(\'{ap["iata"]}\')" id="tab-{ap["iata"]}">{ap["flag"]} {ap["iata"]}</button>\n'
    tab_buttons += '<span class="tab-sep">|</span>\n'
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
    padding: 0 20px; display: flex; flex-wrap: wrap; gap: 2px; align-items: center;
  }}
  .tab-btn {{
    background: none; border: none; padding: 12px 16px;
    font-size: 0.88rem; font-weight: 500; cursor: pointer;
    color: #64748b; border-bottom: 3px solid transparent;
    transition: all 0.15s;
  }}
  .tab-btn:hover {{ color: #0f3460; }}
  .tab-btn.active {{ color: #0f3460; border-bottom-color: #0f3460; }}
  .tab-sep {{
    color: #e2e8f0; font-size: 1.2rem; padding: 0 4px; user-select: none;
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
  <div class="subtitle">Daily flight counts at 10 airports in Iran's neighboring region — tracking conflict-related airspace disruption</div>
  <div class="updated">Last updated: {updated}</div>
</header>

<div class="conflict-strip">
  ⚠️ Conflict reference date: <strong>{conflict_date}</strong> — vertical line on each chart.
  A sustained drop in total flights (arrivals + departures) may signal airspace closure,
  carrier pullout, or active conflict disruption.
</div>

<nav class="tabs">
{tab_buttons}</nav>

<main>
  <div id="panels">
  </div>

  <div class="methodology">
    <h3>Methodology &amp; Caveats</h3>
    <p><strong>Data source:</strong> OpenSky Network API (<code>/api/flights/arrival</code> and
    <code>/api/flights/departure</code>). Flights are counted per calendar day (UTC) per airport
    by ICAO code. Each daily count reflects the sum of arrivals and departures as recorded in
    the OpenSky database, which aggregates ADS-B and MLAT data from a global network of receivers.
    Data is batch-processed overnight; only dates up to yesterday are fetched.</p>
    <p style="margin-top:8px"><strong>Airport scope:</strong> Only the 10 airports in neighboring
    countries are tracked. Iranian airports are excluded because ADS-B ground receiver coverage
    inside Iran is too sparse to produce meaningful counts.</p>
    <p style="margin-top:8px"><strong>Pre-conflict baseline:</strong> Average daily total flights
    in all cached dates before {conflict_date}. The % vs. baseline metric compares the most
    recent 7-day rolling average against this baseline.</p>
    <p style="margin-top:8px"><strong>Cache:</strong> Historical data is cached in
    <code>reports/iran-flight-monitor/data/cache.json</code>. Only missing dates are
    fetched on each run to minimize API usage. Fetch windows are up to 7 days per request
    per direction per airport.</p>
    <p style="margin-top:8px"><strong>Attribution:</strong> Flight data provided by
    <a href="https://opensky-network.org" style="color:#0f3460">The OpenSky Network</a>,
    Matthias Schäfer, Martin Strohmeier, Vincent Lenders, Ivan Martinovic and Matthias Wilhelm.
    "Bringing Up OpenSky: A Large-scale ADS-B Sensor Network for Research." IPSN 2014.</p>
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

  AIRPORTS.forEach((ap, idx) => {{
    const panel = document.createElement("div");
    panel.className = "tab-panel" + (idx === 0 ? " active" : "");
    panel.id = "panel-" + ap.iata;
    panel.innerHTML = `
      <div class="panel-header">
        <h2>${{ap.flag}} ${{ap.iata}} — ${{ap.name}}</h2>
      </div>
      ${{buildStatsRow(ap)}}
      <div class="chart-box">
        <div id="chart-${{ap.iata}}" style="width:100%"></div>
      </div>`;
    container.appendChild(panel);
  }});

  const allPanel = document.createElement("div");
  allPanel.className = "tab-panel";
  allPanel.id = "panel-ALL";
  let allHtml = '<div class="panel-header"><h2>All 10 Airports — Overview</h2></div><div class="all-grid">';
  AIRPORTS.forEach(ap => {{
    allHtml += `<div class="mini-card">
      <h4>${{ap.flag}} ${{ap.iata}} — ${{ap.name}}</h4>
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
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true",
                        help="Test mode: fetch last 3 days for DXB, BGW, IST only")
    args = parser.parse_args()

    today = date.today()
    # Only fetch up to yesterday — today's data not yet batch-processed
    fetch_end = today - timedelta(days=1)

    if args.test:
        lookback = 3
        airports = [ap for ap in AIRPORTS if ap["iata"] in ("DXB", "BGW", "IST")]
        print("*** TEST MODE — 3 airports × 3 days ***")
    else:
        lookback = LOOKBACK_DAYS
        airports = AIRPORTS

    window_start = fetch_end - timedelta(days=lookback - 1)

    print(f"Iran Airspace Monitor — {today}")
    print(f"Fetch window: {window_start} → {fetch_end}  ({lookback} days)")
    print()

    print("Fetching OpenSky OAuth2 token...")
    token = get_token()
    print("Token acquired.")
    print()

    cache = load_cache()
    total_windows = 0

    for ap in airports:
        iata = ap["iata"]
        icao = ap["icao"]
        print(f"[{iata}] {ap['name']} (ICAO: {icao})")

        if iata not in cache:
            cache[iata] = {}

        airport_cache = cache[iata]

        # Collect missing dates in the fetch window
        missing_dates = sorted([
            window_start + timedelta(days=n)
            for n in range(lookback)
            if str(window_start + timedelta(days=n)) not in airport_cache
        ])

        if not missing_dates:
            print(f"  All {lookback} days cached, skipping.")
            continue

        print(f"  Fetching {len(missing_dates)} missing date(s) in 7-day windows...")

        # Group missing dates into 7-day windows
        win_starts = windows_of_n(missing_dates, WINDOW_DAYS)

        for ws in win_starts:
            # Cap window end at start-of-today (exclusive upper bound for yesterday's data)
            we = min(ws + timedelta(days=WINDOW_DAYS), fetch_end + timedelta(days=1))
            begin_ts = date_to_unix(ws)
            end_ts   = date_to_unix(we)

            print(f"  Window {ws} → {we} ...", end=" ", flush=True)
            try:
                arr_flights, token = fetch_window(icao, begin_ts, end_ts, "arrival", token)
                dep_flights, token = fetch_window(icao, begin_ts, end_ts, "departure", token)
                arr_by_day  = window_to_daily_counts(arr_flights, "arrival")
                dep_by_day  = window_to_daily_counts(dep_flights, "departure")

                # Store results for each missing date that falls in this window
                window_dates = [ws + timedelta(days=i) for i in range(WINDOW_DAYS)]
                written = 0
                for wd in window_dates:
                    day_str = str(wd)
                    if wd in missing_dates and wd <= fetch_end:
                        airport_cache[day_str] = {
                            "arrivals":   arr_by_day.get(day_str, 0),
                            "departures": dep_by_day.get(day_str, 0),
                        }
                        written += 1

                sample = next(
                    (airport_cache[str(d)] for d in window_dates
                     if str(d) in airport_cache and d in missing_dates),
                    None
                )
                if sample:
                    print(f"arr={sample['arrivals']} dep={sample['departures']} ({written} days written)")
                else:
                    print(f"({written} days written, all zeros)")

                total_windows += 1
            except Exception as e:
                print(f"ERROR: {e}")

            time.sleep(RATE_LIMIT_SLEEP)

    print()
    print(f"Total API windows fetched: {total_windows} (×2 directions = {total_windows*2} calls)")
    save_cache(cache)
    print(f"Cache saved → {CACHE_PATH}")

    # Compute stats for all airports (not just fetched subset)
    print("Computing stats...")
    stats_by_airport = {}
    for ap in AIRPORTS:
        stats_by_airport[ap["iata"]] = compute_stats(cache, ap["iata"], today)

    print("Rendering HTML...")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    html = render_html(stats_by_airport, today)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard → {OUTPUT_PATH}")
    print("Done.")


if __name__ == "__main__":
    main()

"""
Macro Aviation Pulse — Static HTML Generator
=============================================
Fetches real-time aircraft counts from the OpenSky Network REST API for four
EM airspaces (Brazil, Mexico, South Korea, China), computes a 7-day Congestion
Index, and writes a standalone Plotly HTML report.

History is persisted in reports/macro-aviation-pulse/history.json so each run
appends a new row and the CI accumulates over time.

Required env vars (registered OpenSky account — ~4,000 req/day):
    OPENSKY_USERNAME
    OPENSKY_PASSWORD

Anonymous access (~100 req/day) works but will hit rate limits quickly.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import plotly.graph_objects as go
import requests
from plotly.subplots import make_subplots

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).parent.parent
OUTPUT_DIR  = ROOT / "reports" / "macro-aviation-pulse"
OUTPUT_FILE = OUTPUT_DIR / "index.html"
HISTORY_FILE = OUTPUT_DIR / "history.json"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Region definitions ───────────────────────────────────────────────────────
# To add a new region: append one entry here. Nothing else needs changing.
REGIONS: dict[str, dict] = {
    "Brazil": {
        "lamin": -34.0, "lomin": -74.0, "lamax":  5.0, "lomax": -34.0,
        "color": "#00b4d8", "flag": "🇧🇷",
    },
    "Mexico": {
        "lamin":  14.0, "lomin": -118.0, "lamax": 33.0, "lomax": -86.0,
        "color": "#f4a261", "flag": "🇲🇽",
    },
    "South Korea": {
        "lamin":  33.0, "lomin": 124.0, "lamax": 38.5, "lomax": 130.0,
        "color": "#e76f51", "flag": "🇰🇷",
    },
    "China": {
        "lamin":  18.0, "lomin":  73.0, "lamax": 53.0, "lomax": 135.0,
        "color": "#2a9d8f", "flag": "🇨🇳",
    },
}

ALERT_CI_THRESHOLD  = 0.80
ROLLING_WINDOW_DAYS = 7
OPENSKY_URL         = "https://opensky-network.org/api/states/all"
REQUEST_TIMEOUT_S   = 20

# OpenSky state-vector field indices
ICAO24_IDX   = 0
CALLSIGN_IDX = 1
LON_IDX      = 5
LAT_IDX      = 6


# ── OpenSky API ──────────────────────────────────────────────────────────────

def _auth() -> tuple[str, str] | None:
    user = os.environ.get("OPENSKY_USERNAME")
    pw   = os.environ.get("OPENSKY_PASSWORD")
    if user and pw:
        return (user, pw)
    print("  [warn] OPENSKY credentials not set — using anonymous access", file=sys.stderr)
    return None


def fetch_region_states(region_name: str) -> list[list] | None:
    """
    Fetch raw state vectors for one region bounding box.
    Returns list-of-lists (one per aircraft) or None on failure.
    """
    bbox = REGIONS[region_name]
    params = {
        "lamin": bbox["lamin"], "lomin": bbox["lomin"],
        "lamax": bbox["lamax"], "lomax": bbox["lomax"],
    }
    try:
        resp = requests.get(
            OPENSKY_URL, params=params, auth=_auth(), timeout=REQUEST_TIMEOUT_S
        )
        if resp.status_code == 429:
            print(f"  [warn] Rate limited on {region_name} (HTTP 429)", file=sys.stderr)
            return None
        if resp.status_code == 401:
            print(f"  [error] Auth failed (HTTP 401) — check credentials", file=sys.stderr)
            return None
        resp.raise_for_status()
        data = resp.json()
        return data.get("states") or []
    except requests.Timeout:
        print(f"  [warn] Timeout fetching {region_name}", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"  [warn] Error fetching {region_name}: {exc}", file=sys.stderr)
        return None


def get_count_and_positions(region_name: str) -> tuple[int, list[dict]]:
    """
    Returns (unique_aircraft_count, [{lat, lon, callsign}]) for one region.
    On API failure returns (0, []).
    """
    states = fetch_region_states(region_name)
    if states is None:
        return 0, []

    seen_icao: set[str] = set()
    positions: list[dict] = []

    for s in states:
        try:
            icao = s[ICAO24_IDX] or ""
            if icao not in seen_icao:
                seen_icao.add(icao)
            lat = s[LAT_IDX]
            lon = s[LON_IDX]
            if lat is not None and lon is not None:
                positions.append({
                    "lat":      float(lat),
                    "lon":      float(lon),
                    "callsign": (s[CALLSIGN_IDX] or icao).strip(),
                })
        except (IndexError, TypeError):
            continue

    return len(seen_icao), positions


# ── History (JSON persistence) ───────────────────────────────────────────────

def load_history() -> list[dict]:
    """Load existing history rows; returns [] if file missing or corrupt."""
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def append_and_save_history(history: list[dict], new_row: dict) -> list[dict]:
    """
    Append new_row to history, prune rows older than ROLLING_WINDOW_DAYS,
    and write back to disk.
    """
    history.append(new_row)
    cutoff = time.time() - ROLLING_WINDOW_DAYS * 86400
    history = [r for r in history if r["ts"] >= cutoff]
    HISTORY_FILE.write_text(json.dumps(history, indent=2))
    return history


# ── Congestion Index ─────────────────────────────────────────────────────────

def compute_ci(region: str, current_count: int, history: list[dict]) -> float:
    """
    CI = current_count / rolling_7day_mean.
    Returns 1.0 if no history exists yet.
    """
    counts = [r["counts"][region] for r in history if region in r.get("counts", {})]
    if not counts:
        return 1.0
    mean = sum(counts) / len(counts)
    if mean == 0:
        return 1.0
    return round(current_count / mean, 4)


# ── Figure builders ──────────────────────────────────────────────────────────

_DARK = dict(paper_bgcolor="#0d1117", plot_bgcolor="#161b22", font_color="#e6edf3")
_GRID = dict(gridcolor="#21262d", zerolinecolor="#30363d")


def build_map_figure(all_positions: dict[str, list[dict]]) -> go.Figure:
    """Scattergeo — one trace per region; Plotly built-in geo (no token needed)."""
    fig = go.Figure()
    total = sum(len(v) for v in all_positions.values())

    for region, positions in all_positions.items():
        if not positions:
            continue
        color = REGIONS[region]["color"]
        flag  = REGIONS[region]["flag"]
        fig.add_trace(go.Scattergeo(
            lat=[p["lat"] for p in positions],
            lon=[p["lon"] for p in positions],
            mode="markers",
            marker=dict(size=4, color=color, opacity=0.75),
            name=f"{flag} {region}",
            text=[f"{p['callsign']}<br>{region}" for p in positions],
            hovertemplate="%{text}<extra></extra>",
        ))

    fig.update_layout(
        geo=dict(
            showland=True,       landcolor="#1c2128",
            showocean=True,      oceancolor="#0d1117",
            showcountries=True,  countrycolor="#30363d",
            showcoastlines=True, coastlinecolor="#30363d",
            showframe=False,
            bgcolor="#0d1117",
            projection_type="natural earth",
            # zoom into the 4 EM regions
            lataxis_range=[-40, 60],
            lonaxis_range=[-130, 145],
        ),
        margin=dict(l=0, r=0, t=0, b=0),
        height=420,
        legend=dict(bgcolor="rgba(22,27,34,0.85)", bordercolor="#30363d",
                    borderwidth=1, font=dict(size=11)),
        annotations=[dict(
            text=f"{total:,} aircraft tracked across {len(REGIONS)} EM regions",
            x=0.01, y=0.98, xref="paper", yref="paper",
            showarrow=False, font=dict(size=11, color="#8b949e"),
            bgcolor="rgba(22,27,34,0.7)", align="left",
        )],
        **_DARK,
    )
    return fig


def build_timeseries_figure(history: list[dict]) -> go.Figure:
    """Multi-line time series — aircraft count per region over the last 7 days."""
    fig = go.Figure()

    for region, cfg in REGIONS.items():
        rows = [(r["ts"], r["counts"].get(region, 0))
                for r in history if "counts" in r]
        rows.sort(key=lambda x: x[0])

        x = [datetime.fromtimestamp(ts, tz=timezone.utc) for ts, _ in rows]
        y = [cnt for _, cnt in rows]

        fig.add_trace(go.Scatter(
            x=x, y=y,
            mode="lines+markers",
            name=f"{cfg['flag']} {region}",
            line=dict(color=cfg["color"], width=2),
            marker=dict(size=4),
            hovertemplate=f"<b>{region}</b><br>%{{x|%b %d %H:%M UTC}}<br>%{{y:,}} aircraft<extra></extra>",
        ))

    fig.update_layout(
        xaxis=dict(title="UTC", showgrid=True, tickformat="%b %d %H:%M", **_GRID),
        yaxis=dict(title="Aircraft Count", showgrid=True, **_GRID),
        hovermode="x unified",
        height=320,
        margin=dict(l=60, r=20, t=20, b=60),
        legend=dict(bgcolor="rgba(22,27,34,0.85)", bordercolor="#30363d", borderwidth=1),
        **_DARK,
    )

    if not history:
        fig.add_annotation(
            text="No historical data yet — will accumulate across runs",
            x=0.5, y=0.5, xref="paper", yref="paper",
            showarrow=False, font=dict(size=13, color="#8b949e"),
        )
    return fig


def build_ci_bar_figure(ci_values: dict[str, float]) -> go.Figure:
    """Horizontal bar chart of Congestion Index per region."""
    regions = list(ci_values.keys())
    values  = [ci_values[r] for r in regions]
    colors  = [
        "#f85149" if v < ALERT_CI_THRESHOLD else
        "#e3b341" if v < 0.95 else
        "#2ea043"
        for v in values
    ]
    labels  = [f"{REGIONS[r]['flag']} {r}" for r in regions]

    fig = go.Figure(go.Bar(
        x=values,
        y=labels,
        orientation="h",
        marker_color=colors,
        text=[f"{v:.2f}" for v in values],
        textposition="outside",
        hovertemplate="%{y}: CI %{x:.3f}<extra></extra>",
    ))

    fig.add_vline(
        x=ALERT_CI_THRESHOLD,
        line=dict(color="#f85149", width=1.5, dash="dash"),
        annotation_text=f"Alert threshold ({ALERT_CI_THRESHOLD:.0%})",
        annotation_font=dict(color="#f85149", size=11),
        annotation_position="top right",
    )
    fig.add_vline(
        x=1.0,
        line=dict(color="#484f58", width=1, dash="dot"),
    )

    fig.update_layout(
        xaxis=dict(title="Congestion Index (1.0 = 7-day baseline)", range=[0, max(values) * 1.2 + 0.1], **_GRID),
        yaxis=dict(showgrid=False),
        height=220,
        margin=dict(l=120, r=60, t=20, b=50),
        **_DARK,
    )
    return fig


# ── HTML assembly ─────────────────────────────────────────────────────────────

def build_kpi_html(counts: dict[str, int], ci_values: dict[str, float],
                   alerts: list[str]) -> str:
    cards = []
    for region, count in counts.items():
        ci    = ci_values[region]
        cfg   = REGIONS[region]
        color = cfg["color"]
        flag  = cfg["flag"]

        if ci < ALERT_CI_THRESHOLD:
            ci_color, ci_label = "#f85149", "ALERT"
            border_color = "#f85149"
        elif ci < 0.95:
            ci_color, ci_label = "#e3b341", "below avg"
            border_color = "#e3b341"
        else:
            ci_color, ci_label = "#2ea043", "nominal"
            border_color = "#2ea043"

        cards.append(f"""
        <div class="kpi-card" style="border-left: 3px solid {color};">
            <div class="kpi-region">{flag} {region}</div>
            <div class="kpi-count">{count:,}</div>
            <div class="kpi-label">aircraft</div>
            <div class="kpi-ci" style="color:{ci_color};">
                CI {ci:.2f} &nbsp;·&nbsp; {ci_label}
            </div>
        </div>""")

    alert_html = ""
    if alerts:
        alert_items = "".join(
            f'<li>{REGIONS[r]["flag"]} <strong>{r}</strong> &mdash; traffic &gt;20% below 7-day baseline</li>'
            for r in alerts
        )
        alert_html = f"""
        <div class="alert-box">
            <div class="alert-title">⚠ Congestion Alert</div>
            <ul>{alert_items}</ul>
        </div>"""
    else:
        alert_html = """
        <div class="alert-ok">
            ✓ All regions within normal range
        </div>"""

    return f"""
    <div class="kpi-strip">{"".join(cards)}</div>
    {alert_html}
    """


CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0d1117; color: #e6edf3; font-family: 'Courier New', monospace; }
.header { background: #161b22; border-bottom: 1px solid #30363d; padding: 20px 32px; display: flex; align-items: center; gap: 14px; }
.header h1 { font-size: 1.4rem; font-weight: 600; letter-spacing: .04em; }
.header .sub { font-size: .8rem; color: #8b949e; margin-top: 3px; }
.pulse { width: 10px; height: 10px; border-radius: 50%; background: #2ea043; animation: pulse 2s infinite; flex-shrink: 0; }
@keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(46,160,67,.6)} 70%{box-shadow:0 0 0 8px rgba(46,160,67,0)} 100%{box-shadow:0 0 0 0 rgba(46,160,67,0)} }
.content { padding: 24px 32px; display: flex; flex-direction: column; gap: 20px; max-width: 1400px; margin: 0 auto; }
.section-title { font-size: .72rem; text-transform: uppercase; letter-spacing: .1em; color: #8b949e; padding-bottom: 8px; border-bottom: 1px solid #21262d; margin-bottom: 12px; }
.kpi-strip { display: flex; gap: 16px; flex-wrap: wrap; }
.kpi-card { flex: 1; min-width: 155px; background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px 20px; }
.kpi-region { font-size: .7rem; text-transform: uppercase; letter-spacing: .07em; color: #8b949e; margin-bottom: 6px; }
.kpi-count { font-size: 2rem; font-weight: 700; line-height: 1; margin-bottom: 3px; }
.kpi-label { font-size: .7rem; color: #8b949e; margin-bottom: 8px; }
.kpi-ci { font-size: .8rem; font-weight: 600; }
.alert-box { background: #1f1215; border: 1px solid #f85149; border-radius: 6px; padding: 14px 18px; }
.alert-title { color: #f85149; font-weight: 700; font-size: .9rem; margin-bottom: 8px; }
.alert-box ul { list-style: none; display: flex; flex-direction: column; gap: 4px; }
.alert-box li { font-size: .85rem; color: #e6edf3; }
.alert-ok { background: #0f1f13; border: 1px solid #2ea043; border-radius: 6px; padding: 12px 18px; color: #2ea043; font-size: .85rem; font-weight: 600; }
.row { display: flex; gap: 20px; }
.col-main { flex: 2; min-width: 0; }
.col-side { flex: 1; min-width: 260px; }
.panel { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
.footer { font-size: .7rem; color: #484f58; text-align: right; padding: 8px 0 16px; }
"""


def render_html(
    counts: dict[str, int],
    ci_values: dict[str, float],
    alerts: list[str],
    all_positions: dict[str, list[dict]],
    history: list[dict],
    generated_at: str,
) -> str:
    map_fig = build_map_figure(all_positions)
    ts_fig  = build_timeseries_figure(history)
    ci_fig  = build_ci_bar_figure(ci_values)
    kpi_html = build_kpi_html(counts, ci_values, alerts)

    map_div = map_fig.to_html(full_html=False, include_plotlyjs=False, div_id="map")
    ts_div  = ts_fig.to_html(full_html=False, include_plotlyjs=False, div_id="ts")
    ci_div  = ci_fig.to_html(full_html=False, include_plotlyjs=False, div_id="ci")

    total_aircraft = sum(counts.values())

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Macro Aviation Pulse — EM Air Traffic Monitor</title>
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
  <style>{CSS}</style>
</head>
<body>

<div class="header">
  <div class="pulse"></div>
  <div>
    <h1>✈ Macro Aviation Pulse</h1>
    <div class="sub">Real-time air traffic density · EM economic activity proxy · {generated_at} UTC</div>
  </div>
</div>

<div class="content">

  <!-- KPI strip + alerts -->
  {kpi_html}

  <!-- Map + CI bar -->
  <div class="row">
    <div class="col-main panel">
      <div class="section-title">Live Aircraft Positions — {total_aircraft:,} aircraft tracked</div>
      {map_div}
    </div>
    <div class="col-side panel">
      <div class="section-title">Congestion Index (CI = current ÷ 7-day mean)</div>
      {ci_div}
      <div style="font-size:.72rem;color:#484f58;margin-top:12px;line-height:1.5;">
        CI &gt; 0.95 = nominal &nbsp;·&nbsp;
        CI 0.80–0.95 = below average &nbsp;·&nbsp;
        CI &lt; 0.80 = alert
      </div>
    </div>
  </div>

  <!-- 7-day time series -->
  <div class="panel">
    <div class="section-title">7-Day Traffic Trend</div>
    {ts_div}
  </div>

  <div class="footer">
    Data: OpenSky Network REST API &nbsp;·&nbsp;
    Bounding boxes: BR, MX, KR, CN airspaces &nbsp;·&nbsp;
    Updated: {generated_at} UTC &nbsp;·&nbsp;
    <a href="https://github.com/DataVizHonduran/boquin.github.io/blob/main/scripts/generate_aviation_pulse.py"
       style="color:#58a6ff;">Source</a>
  </div>

</div>
</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    generated_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    print(f"Macro Aviation Pulse — {generated_at} UTC")

    # 1. Load history
    history = load_history()
    print(f"  Loaded {len(history)} historical rows")

    # 2. Fetch current data (stagger calls to respect rate limits)
    counts: dict[str, int] = {}
    all_positions: dict[str, list[dict]] = {}

    for i, region in enumerate(REGIONS):
        print(f"  Fetching {region}…")
        count, positions = get_count_and_positions(region)
        counts[region]       = count
        all_positions[region] = positions
        print(f"    → {count} aircraft, {len(positions)} with position fix")
        if i < len(REGIONS) - 1:
            time.sleep(3)  # short stagger — OpenSky asks for polite clients

    # 3. Append to history
    new_row = {"ts": int(time.time()), "counts": counts}
    history = append_and_save_history(history, new_row)
    print(f"  History now has {len(history)} rows (last 7 days)")

    # 4. Compute Congestion Index
    ci_values: dict[str, float] = {
        r: compute_ci(r, counts[r], history) for r in REGIONS
    }
    alerts = [r for r, ci in ci_values.items() if ci < ALERT_CI_THRESHOLD]

    print("  Congestion Index:")
    for r, ci in ci_values.items():
        flag = " ⚠ ALERT" if r in alerts else ""
        print(f"    {r}: {ci:.3f}{flag}")

    # 5. Render and write HTML
    html = render_html(counts, ci_values, alerts, all_positions, history, generated_at)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"  Written → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

# app.py — Macro Aviation Pulse
# Real-time EM air traffic monitoring dashboard (Plotly Dash)
#
# Usage:
#   export OPENSKY_USERNAME=<your_user>
#   export OPENSKY_PASSWORD=<your_pass>
#   python app.py
#
# Dashboard: http://127.0.0.1:8050

import datetime
import logging
import threading
import time

import plotly.graph_objects as go
from dash import Dash, Input, Output, dcc, html

from config import (
    ALERT_CI_THRESHOLD,
    POLL_INTERVAL_MS,
    POLL_STAGGER_SECONDS,
    REGIONS,
)
from data.opensky import fetch_aircraft_positions, fetch_region_count
from utils.metrics import (
    compute_ci,
    get_all_alerts,
    get_history_24h,
    get_latest_counts,
    init_db,
    write_sample,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Figure builders
# ---------------------------------------------------------------------------

_DARK = dict(paper_bgcolor="#0d1117", plot_bgcolor="#161b22", font_color="#e6edf3")
_GRID = dict(gridcolor="#21262d", zerolinecolor="#30363d")


def _build_map_figure(all_positions: dict[str, list[dict]]) -> go.Figure:
    """One Scattermapbox trace per region; open-street-map style (no token)."""
    fig = go.Figure()

    total = sum(len(v) for v in all_positions.values())

    for region, positions in all_positions.items():
        if not positions:
            continue
        color = REGIONS[region]["color"]
        fig.add_trace(
            go.Scattermapbox(
                lat=[p["lat"] for p in positions],
                lon=[p["lon"] for p in positions],
                mode="markers",
                marker=dict(size=5, color=color, opacity=0.75),
                name=region,
                text=[
                    f"{p['callsign'] or p['icao24']}<br>{region}"
                    for p in positions
                ],
                hovertemplate="%{text}<extra></extra>",
            )
        )

    fig.update_layout(
        mapbox=dict(style="open-street-map", zoom=1, center=dict(lat=20, lon=60)),
        margin=dict(l=0, r=0, t=0, b=0),
        legend=dict(
            bgcolor="rgba(22,27,34,0.8)",
            bordercolor="#30363d",
            borderwidth=1,
            font=dict(color="#e6edf3", size=11),
        ),
        showlegend=True,
        **_DARK,
        annotations=[
            dict(
                text=f"{total} aircraft tracked across {len(REGIONS)} regions",
                x=0.01, y=0.99,
                xref="paper", yref="paper",
                showarrow=False,
                font=dict(size=11, color="#8b949e"),
                align="left",
                bgcolor="rgba(22,27,34,0.7)",
            )
        ],
    )
    return fig


def _build_timeseries_figure(history: dict[str, list[dict]]) -> go.Figure:
    """Multi-line 24h time series, one trace per region."""
    fig = go.Figure()

    has_data = any(len(v) > 0 for v in history.values())

    for region, rows in history.items():
        color = REGIONS[region]["color"]
        if rows:
            x = [datetime.datetime.utcfromtimestamp(r["timestamp"]) for r in rows]
            y = [r["count"] for r in rows]
        else:
            x, y = [], []

        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="lines+markers",
                name=region,
                line=dict(color=color, width=2),
                marker=dict(size=4, color=color),
                hovertemplate=f"<b>{region}</b><br>%{{x|%H:%M UTC}}<br>%{{y}} aircraft<extra></extra>",
            )
        )

    fig.update_layout(
        xaxis=dict(
            title="UTC",
            showgrid=True,
            tickformat="%H:%M",
            **_GRID,
        ),
        yaxis=dict(
            title="Aircraft Count",
            showgrid=True,
            **_GRID,
        ),
        legend=dict(
            bgcolor="rgba(22,27,34,0.8)",
            bordercolor="#30363d",
            borderwidth=1,
            font=dict(color="#e6edf3", size=11),
        ),
        hovermode="x unified",
        margin=dict(l=60, r=20, t=20, b=50),
        **_DARK,
    )

    if not has_data:
        fig.add_annotation(
            text="Awaiting first poll cycle — data will appear within 5 minutes",
            x=0.5, y=0.5,
            xref="paper", yref="paper",
            showarrow=False,
            font=dict(size=13, color="#8b949e"),
        )

    return fig


def _build_alert_panel(alerts: list[dict]) -> list:
    """Return Dash HTML components for the alert panel."""
    if not alerts:
        all_clear = html.Div(
            [
                html.Div("✓", style={"fontSize": "2rem", "color": "#2ea043", "marginBottom": "8px"}),
                html.Div("All regions nominal", className="no-alerts"),
                html.Div(
                    f"CI threshold: {ALERT_CI_THRESHOLD:.0%}",
                    style={"fontSize": "0.7rem", "color": "#484f58", "textAlign": "center"},
                ),
            ],
            style={"paddingTop": "16px"},
        )
        return [all_clear]

    cards = []
    for a in alerts:
        ts_str = (
            datetime.datetime.utcfromtimestamp(a["timestamp"]).strftime("%H:%M UTC")
            if a["timestamp"]
            else "—"
        )
        cards.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(a["region"], className="alert-region-name"),
                            html.Span(f"CI {a['ci']:.2f}", className="alert-ci-badge"),
                        ]
                    ),
                    html.Div(
                        f"{a['count']} aircraft · {ts_str}",
                        className="alert-detail",
                    ),
                ],
                className="alert-card",
            )
        )
    return cards


def _build_kpi_strip(latest: dict[str, dict]) -> list:
    """Return 4 KPI cards, one per region."""
    cards = []
    for region, data in latest.items():
        ci    = data["ci"]
        count = data["count"]
        color = REGIONS[region]["color"]

        if ci >= 0.95:
            ci_class = "kpi-ci-ok"
            ci_label = "nominal"
        elif ci >= ALERT_CI_THRESHOLD:
            ci_class = "kpi-ci-warn"
            ci_label = "below avg"
        else:
            ci_class = "kpi-ci-alert"
            ci_label = "ALERT"

        cards.append(
            html.Div(
                [
                    html.Div(region, className="kpi-region"),
                    html.Div(f"{count:,}", className="kpi-count"),
                    html.Div("aircraft", className="kpi-count-label"),
                    html.Div(
                        [
                            html.Span("CI:", className="kpi-ci-label"),
                            html.Span(
                                f" {ci:.2f} ({ci_label})",
                                className=f"kpi-ci-value {ci_class}",
                            ),
                        ],
                        className="kpi-ci-row",
                    ),
                ],
                className="kpi-card",
                style={"--region-color": color},
            )
        )
    return cards


# ---------------------------------------------------------------------------
# Background polling thread
# ---------------------------------------------------------------------------

def _poll_loop() -> None:
    """
    Daemon thread that fetches each region sequentially with a stagger delay.
    Writes results to SQLite so the Dash callback can read without blocking.

    Cycle timing:
      - 4 regions × 60s stagger = ~4 min of API calls
      - Remaining time (~1 min) is slept before the next cycle starts
      - Total cycle ≈ 5 minutes, matching the dcc.Interval period
    """
    logger.info("Background polling thread started")
    while True:
        cycle_start = time.time()

        for region in REGIONS:
            try:
                count = fetch_region_count(region)
                ci    = compute_ci(region, count)
                write_sample(region, count, ci)
                logger.info("Polled %s: count=%d ci=%.3f", region, count, ci)
            except Exception as exc:
                logger.error("Error polling %s: %s", region, exc)

            # Stagger: wait before next region to spread API load
            time.sleep(POLL_STAGGER_SECONDS)

        elapsed = time.time() - cycle_start
        sleep_remaining = max(0, 300 - elapsed)  # pad to 5-min cycle
        if sleep_remaining > 0:
            logger.debug("Cycle complete in %.0fs, sleeping %.0fs", elapsed, sleep_remaining)
            time.sleep(sleep_remaining)


# ---------------------------------------------------------------------------
# Dash application
# ---------------------------------------------------------------------------

app = Dash(
    __name__,
    title="Macro Aviation Pulse",
    update_title=None,
)

app.layout = html.Div(
    [
        # ── Header ────────────────────────────────────────────────────────
        html.Div(
            [
                html.Div(className="pulse-dot"),
                html.Div(
                    [
                        html.H1("Macro Aviation Pulse"),
                        html.P(
                            "Real-time air traffic density · Brazil · Mexico · South Korea · China",
                            className="subtitle",
                        ),
                    ]
                ),
            ],
            className="app-header",
        ),

        # ── Silent auto-refresh trigger ───────────────────────────────────
        dcc.Interval(id="interval", interval=POLL_INTERVAL_MS, n_intervals=0),

        # ── Main content ──────────────────────────────────────────────────
        html.Div(
            [
                # KPI strip
                html.Div(id="kpi-strip", className="kpi-strip"),

                # Map + Alert panel
                html.Div(
                    [
                        html.Div(
                            [
                                html.P("Live Aircraft Positions", className="section-title"),
                                html.Div(
                                    dcc.Graph(
                                        id="map-figure",
                                        config={"displayModeBar": False},
                                        style={"height": "420px"},
                                    ),
                                    className="graph-container",
                                ),
                            ],
                            className="col-map",
                        ),
                        html.Div(
                            [
                                html.P("Congestion Alerts", className="section-title"),
                                html.Div(id="alert-panel", className="alert-panel"),
                            ],
                            className="col-alerts",
                        ),
                    ],
                    className="row",
                ),

                # Time-series
                html.Div(
                    [
                        html.P("24h Traffic Trend", className="section-title"),
                        html.Div(
                            dcc.Graph(
                                id="timeseries-figure",
                                config={"displayModeBar": "hover"},
                                style={"height": "300px"},
                            ),
                            className="graph-container",
                        ),
                    ]
                ),

                # Last updated
                html.Div(id="last-updated", className="last-updated"),
            ],
            className="main-content",
        ),
    ]
)


# ---------------------------------------------------------------------------
# Callback — reads from DB (fast), never calls the API directly
# ---------------------------------------------------------------------------

@app.callback(
    Output("map-figure", "figure"),
    Output("timeseries-figure", "figure"),
    Output("alert-panel", "children"),
    Output("kpi-strip", "children"),
    Output("last-updated", "children"),
    Input("interval", "n_intervals"),
)
def update_dashboard(_n: int) -> tuple:
    """
    Fires every POLL_INTERVAL_MS.  Reads pre-fetched data from SQLite and
    live aircraft positions from OpenSky, then rebuilds all four dashboard
    components.

    Returns a tuple of (map_fig, ts_fig, alert_children, kpi_children, ts_str).
    """
    # Live positions for map (direct API call — fast, positions not stored in DB)
    all_positions: dict[str, list[dict]] = {}
    for region in REGIONS:
        try:
            all_positions[region] = fetch_aircraft_positions(region)
        except Exception as exc:
            logger.warning("Position fetch failed for %s: %s", region, exc)
            all_positions[region] = []

    # Historical data from DB
    history = {region: get_history_24h(region) for region in REGIONS}
    alerts  = get_all_alerts()
    latest  = get_latest_counts()

    ts = datetime.datetime.utcnow().strftime("Last updated: %Y-%m-%d %H:%M UTC")

    return (
        _build_map_figure(all_positions),
        _build_timeseries_figure(history),
        _build_alert_panel(alerts),
        _build_kpi_strip(latest),
        ts,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # 1. Initialise SQLite schema
    init_db()

    # 2. Launch background polling thread (daemon — exits when main process exits)
    poller = threading.Thread(target=_poll_loop, name="aviation-poller", daemon=True)
    poller.start()

    # 3. Run Dash dev server
    logger.info("Starting Dash server at http://127.0.0.1:8050")
    app.run(debug=False, host="127.0.0.1", port=8050)

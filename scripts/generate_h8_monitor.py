"""
H.8 Systemic Credit Risk Monitor
Tracks weekly Federal Reserve H.8 commercial bank data — loan growth,
C&I credit signals, real estate concentration, Senior Loan Officer Survey,
deposit dynamics, financial conditions indices, and NBF lending.

Requires: FRED_API_KEY environment variable
Output:   reports/h8-monitor/index.html

NBF (nonbank financial) lending: attempts direct FRED series first;
falls back to residual derivation (TOTLL - BUSLOANS - REALLN - CONSUMER).
"""

import json
import os
import time
from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
from dateutil.relativedelta import relativedelta
from fredapi import Fred
from plotly.subplots import make_subplots

# ── Constants ──────────────────────────────────────────────────────────────────
OUTPUT_PATH  = "reports/h8-monitor/index.html"
FRED_API_KEY = os.environ.get("FRED_API_KEY")
if not FRED_API_KEY:
    raise EnvironmentError("FRED_API_KEY environment variable is not set.")

os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
fred = Fred(api_key=FRED_API_KEY)

HISTORY_YEARS = 7

# Direct FRED series for NBF institutional loans (weekly SA).
# Set to a valid FRED ID if one is discovered; None triggers residual derivation.
NBF_DIRECT_SERIES = None

COLORS = {
    "navy":       "#1f4e79",
    "orange":     "#d67f00",
    "steel_blue": "#4472c4",
    "green":      "#2ca02c",
    "purple":     "#7b2d8b",
    "red":        "#d62728",
    "forest":     "#1a3a2f",
}

# Signal thresholds
# direction = "lower_bad": WARN/STRESS fire when value is below threshold
# direction = "upper_bad": WARN/STRESS fire when value is above threshold
# direction = "two_sided": fires on both ends (NBF loans)
THRESHOLDS = {
    "tot_yoy":  {"warn": -1.0,  "stress": -3.0,  "dir": "lower_bad"},
    "ci_yoy":   {"warn": -2.0,  "stress": -5.0,  "dir": "lower_bad"},
    "re_yoy":   {"warn": -1.0,  "stress": -3.0,  "dir": "lower_bad"},
    "con_yoy":  {"warn": -1.0,  "stress": -3.0,  "dir": "lower_bad"},
    "nbf_yoy":  {
        "warn_lo": -5.0, "stress_lo": -10.0,
        "warn_hi": 20.0, "stress_hi":  30.0,
        "dir": "two_sided",
    },
    "stlfsi4":  {"warn": 1.0,   "stress": 2.0,   "dir": "upper_bad"},
    "nfci":     {"warn": 0.3,   "stress": 0.7,   "dir": "upper_bad"},
    "ci_slo":   {"warn": 20.0,  "stress": 40.0,  "dir": "upper_bad"},
    "nbf_slo":  {"warn": 20.0,  "stress": 40.0,  "dir": "upper_bad"},
    "disc_win": {"warn": 5.0,   "stress": 20.0,  "dir": "upper_bad"},
}


# ── FRED helpers ───────────────────────────────────────────────────────────────
def get_fred(series_id, years=HISTORY_YEARS):
    start = date.today() - relativedelta(years=years)
    return fred.get_series(series_id, observation_start=start).dropna()


def get_fred_safe(series_id, years=HISTORY_YEARS):
    try:
        return get_fred(series_id, years)
    except Exception as e:
        print(f"  ⚠️  {series_id}: {e}")
        return None


def add_recession_shading(fig, recession, row, col, y0=-1e6, y1=1e6):
    """Overlay NBER recession bars on a subplot using data coordinates."""
    in_rec = False
    rec_start = None
    for dt, val in recession.items():
        if val == 1 and not in_rec:
            in_rec = True
            rec_start = dt
        elif val == 0 and in_rec:
            in_rec = False
            fig.add_shape(
                type="rect",
                x0=rec_start, x1=dt, y0=y0, y1=y1,
                fillcolor="lightgray", opacity=0.4,
                line_width=0, layer="below",
                row=row, col=col,
            )
    if in_rec:
        fig.add_shape(
            type="rect",
            x0=rec_start, x1=recession.index[-1], y0=y0, y1=y1,
            fillcolor="lightgray", opacity=0.4,
            line_width=0, layer="below",
            row=row, col=col,
        )


# ── Data fetching ──────────────────────────────────────────────────────────────
def fetch_all():
    """Fetch all required FRED series. Returns raw dict."""
    print("Fetching NBER recession data...")
    recession = get_fred("USREC", years=100)

    print("Fetching H.8 weekly series...")
    raw = {"RECESSION": recession, "SLO": {}}

    weekly_ids = [
        "TOTLL", "BUSLOANS", "REALLN",
        "CREACBW027SBOG", "RREACBW027SBOG", "CONSUMER",
        "DPSACBW027SBOG", "TLAACBW027SBOG",
        "STLFSI4", "NFCI",
    ]
    for sid in weekly_ids:
        time.sleep(0.15)
        s = get_fred_safe(sid)
        if s is not None:
            raw[sid] = s
            print(f"  ✓ {sid}: {len(s)} obs, latest {s.index[-1].date()}")

    # Discount window: $M → $B
    time.sleep(0.15)
    dpc = get_fred_safe("DPCREDIT")
    if dpc is not None:
        raw["DPCREDIT"] = dpc / 1000.0
        print(f"  ✓ DPCREDIT (discount window): converted to $B")

    # BTFP — 5-year history, active Mar 2023–Mar 2024; $M → $B
    time.sleep(0.15)
    wbtfp = get_fred_safe("WBTFP", years=5)
    if wbtfp is not None:
        raw["WBTFP"] = wbtfp / 1000.0
        print(f"  ✓ WBTFP (BTFP borrowings): converted to $B")

    # Direct NBF series attempt
    raw["NBF"] = None
    raw["NBF_LABEL"] = None
    if NBF_DIRECT_SERIES:
        time.sleep(0.15)
        nbf_direct = get_fred_safe(NBF_DIRECT_SERIES)
        if nbf_direct is not None:
            raw["NBF"] = nbf_direct
            raw["NBF_LABEL"] = "Loans to NBF Institutions"
            print(f"  ✓ NBF direct: {NBF_DIRECT_SERIES}")

    # Quarterly SLO series (forward-filled to weekly downstream)
    print("Fetching Senior Loan Officer Survey series...")
    slo_ids = {
        "DRTSCILM":  "C&I (Large/Med)",
        "DRTSCLCC":  "Consumer CC",
        "DRTSFLNFC": "CRE (Nonfarm)",
        "DRTSNBFI":  "NBF Institutions",
    }
    for sid, label in slo_ids.items():
        time.sleep(0.15)
        s = get_fred_safe(sid)
        if s is not None:
            raw["SLO"][sid] = s
            print(f"  ✓ {sid} [{label}]: {len(s)} obs")

    return raw


# ── Transforms ─────────────────────────────────────────────────────────────────
def compute_transforms(raw):
    t = {}

    # NBF level: direct series or residual proxy
    if raw["NBF"] is not None:
        t["nbf"] = raw["NBF"]
        t["nbf_label"] = raw["NBF_LABEL"]
    else:
        req = ["TOTLL", "BUSLOANS", "REALLN", "CONSUMER"]
        if all(k in raw for k in req):
            idx = raw["TOTLL"].index
            nbf_proxy = (
                raw["TOTLL"]
                .sub(raw["BUSLOANS"].reindex(idx, method="ffill"), fill_value=0)
                .sub(raw["REALLN"].reindex(idx, method="ffill"),   fill_value=0)
                .sub(raw["CONSUMER"].reindex(idx, method="ffill"), fill_value=0)
            )
            t["nbf"] = nbf_proxy.dropna()
        else:
            t["nbf"] = None
        t["nbf_label"] = "Other/NBF Loans (derived: TOTLL − C&I − RE − Consumer)"

    # YoY % — 52-week pct change
    for sid in ["TOTLL", "BUSLOANS", "REALLN", "CONSUMER", "DPSACBW027SBOG"]:
        if sid in raw:
            t[f"yoy_{sid}"] = (raw[sid].pct_change(52) * 100).dropna()

    nbf = t.get("nbf")
    if nbf is not None and len(nbf) >= 52:
        t["yoy_NBF"] = (nbf.pct_change(52) * 100).dropna()

    # WoW change for C&I
    if "BUSLOANS" in raw:
        t["wow_BUSLOANS"] = raw["BUSLOANS"].diff().dropna()

    # Real estate concentration shares
    if "TOTLL" in raw:
        for sid, key in [
            ("REALLN",           "share_RE"),
            ("CREACBW027SBOG",   "share_CRE"),
            ("RREACBW027SBOG",   "share_RRE"),
        ]:
            if sid in raw:
                t[key] = (raw[sid] / raw["TOTLL"] * 100).dropna()

    # Loan-to-deposit ratio
    if "TOTLL" in raw and "DPSACBW027SBOG" in raw:
        t["ld_ratio"] = (raw["TOTLL"] / raw["DPSACBW027SBOG"] * 100).dropna()

    # SLO — resample quarterly to weekly Wed, ffill
    t["slo_aligned"] = {}
    for sid, s in raw["SLO"].items():
        if len(s) == 0:
            continue
        weekly_idx = pd.date_range(s.index[0], pd.Timestamp.today(), freq="W-WED")
        aligned = s.reindex(weekly_idx, method="ffill").dropna()
        if len(aligned) > 0:
            t["slo_aligned"][sid] = aligned

    return t


# ── Figure builder ─────────────────────────────────────────────────────────────
def build_figure(raw, t):
    recession = raw["RECESSION"]

    specs = [
        [{"secondary_y": False}, {"secondary_y": True}],
        [{"secondary_y": False}, {"secondary_y": True}],
        [{"secondary_y": False}, {"secondary_y": False}],
        [{"secondary_y": True},  {"secondary_y": False}],
    ]
    panel_titles = [
        "Loan Growth YoY %",
        "C&I Loans: Level + WoW Change",
        "Real Estate Concentration % of Total Loans",
        "Deposit Dynamics + L/D Ratio",
        "Senior Loan Officer Survey — Credit Standards",
        "Financial Conditions Indices",
        f"NBF Institution Lending",
        "Fed Borrowings / Liquidity Stress",
    ]
    fig = make_subplots(
        rows=4, cols=2,
        specs=specs,
        subplot_titles=panel_titles,
        vertical_spacing=0.09,
        horizontal_spacing=0.10,
    )

    # ── Panel 1: Loan Growth YoY % ────────────────────────────────────────────
    p1_series = [
        ("yoy_TOTLL",    "Total Loans",  COLORS["navy"]),
        ("yoy_BUSLOANS", "C&I",          COLORS["orange"]),
        ("yoy_REALLN",   "Real Estate",  COLORS["steel_blue"]),
        ("yoy_CONSUMER", "Consumer",     COLORS["green"]),
        ("yoy_NBF",      "NBF/Other",    COLORS["purple"]),
    ]
    for key, name, color in p1_series:
        s = t.get(key)
        if s is not None and len(s) > 0:
            fig.add_trace(go.Scatter(
                x=s.index, y=s.values, mode="lines", name=name,
                line=dict(color=color, width=1.8),
                legendgroup="p1", legendgrouptitle_text="",
            ), row=1, col=1)

    fig.add_hline(y=-5, line_dash="dash", line_color="red",  line_width=1, row=1, col=1)
    fig.add_hline(y=0,  line_dash="dot",  line_color="gray", line_width=1, row=1, col=1)
    add_recession_shading(fig, recession, 1, 1, y0=-40, y1=40)
    fig.update_yaxes(title_text="YoY %", title_font_size=10, row=1, col=1)

    # ── Panel 2: C&I Level + WoW ─────────────────────────────────────────────
    if "BUSLOANS" in raw:
        bl = raw["BUSLOANS"]
        fig.add_trace(go.Scatter(
            x=bl.index, y=bl.values, mode="lines", name="C&I Level ($B)",
            line=dict(color=COLORS["navy"], width=2),
            legendgroup="p2",
        ), row=1, col=2, secondary_y=False)

    wow = t.get("wow_BUSLOANS")
    if wow is not None and len(wow) > 0:
        bar_colors = [COLORS["green"] if v >= 0 else COLORS["red"] for v in wow.values]
        fig.add_trace(go.Bar(
            x=wow.index, y=wow.values, name="WoW Change ($B)",
            marker_color=bar_colors, opacity=0.55,
            legendgroup="p2",
        ), row=1, col=2, secondary_y=True)

    fig.update_yaxes(title_text="Level ($B)",      title_font_size=10, row=1, col=2, secondary_y=False)
    fig.update_yaxes(title_text="WoW Change ($B)", title_font_size=10, row=1, col=2, secondary_y=True)

    # ── Panel 3: RE Concentration % ──────────────────────────────────────────
    p3_series = [
        ("share_RE",  "RE / Total",   COLORS["steel_blue"]),
        ("share_CRE", "CRE / Total",  COLORS["orange"]),
        ("share_RRE", "RRE / Total",  COLORS["green"]),
    ]
    for key, name, color in p3_series:
        s = t.get(key)
        if s is not None and len(s) > 0:
            fig.add_trace(go.Scatter(
                x=s.index, y=s.values, mode="lines", name=name,
                line=dict(color=color, width=1.8),
                legendgroup="p3",
            ), row=2, col=1)

    cre_share = t.get("share_CRE")
    if cre_share is not None and len(cre_share) > 0:
        q90 = float(cre_share.quantile(0.90))
        fig.add_hline(
            y=q90, line_dash="dash", line_color="red", line_width=1, row=2, col=1,
            annotation_text=f"CRE 90th pct: {q90:.1f}%", annotation_font_size=9,
        )

    add_recession_shading(fig, recession, 2, 1, y0=0, y1=70)
    fig.update_yaxes(title_text="% of Total Loans", title_font_size=10, row=2, col=1)

    # ── Panel 4: Deposit Dynamics + L/D Ratio ────────────────────────────────
    dep_yoy = t.get("yoy_DPSACBW027SBOG")
    if dep_yoy is not None and len(dep_yoy) > 0:
        dep_colors = [COLORS["green"] if v >= 0 else COLORS["red"] for v in dep_yoy.values]
        fig.add_trace(go.Bar(
            x=dep_yoy.index, y=dep_yoy.values, name="Deposits YoY %",
            marker_color=dep_colors, opacity=0.55,
            legendgroup="p4",
        ), row=2, col=2, secondary_y=False)

    ld = t.get("ld_ratio")
    if ld is not None and len(ld) > 0:
        fig.add_trace(go.Scatter(
            x=ld.index, y=ld.values, mode="lines", name="L/D Ratio %",
            line=dict(color=COLORS["navy"], width=2),
            legendgroup="p4",
        ), row=2, col=2, secondary_y=True)

        q90_ld = float(ld.quantile(0.90))
        fig.add_trace(go.Scatter(
            x=[ld.index[0], ld.index[-1]], y=[q90_ld, q90_ld],
            mode="lines", name=f"L/D 90th pct ({q90_ld:.1f}%)",
            line=dict(dash="dash", color="darkorange", width=1),
            legendgroup="p4",
        ), row=2, col=2, secondary_y=True)

    fig.update_yaxes(title_text="Deposits YoY %", title_font_size=10, row=2, col=2, secondary_y=False)
    fig.update_yaxes(title_text="L/D Ratio %",    title_font_size=10, row=2, col=2, secondary_y=True)

    # ── Panel 5: Senior Loan Officer Survey ──────────────────────────────────
    slo_specs = [
        ("DRTSCILM",  "C&I (Large/Med)",  COLORS["navy"]),
        ("DRTSCLCC",  "Consumer CC",      COLORS["orange"]),
        ("DRTSFLNFC", "CRE Nonfarm",      COLORS["steel_blue"]),
        ("DRTSNBFI",  "NBF Institutions", COLORS["purple"]),
    ]
    for sid, name, color in slo_specs:
        s = t["slo_aligned"].get(sid)
        if s is not None and len(s) > 0:
            fig.add_trace(go.Scatter(
                x=s.index, y=s.values, mode="lines", name=name,
                line=dict(color=color, width=1.8, shape="hv"),
                legendgroup="p5",
            ), row=3, col=1)

    fig.add_hline(y=0, line_dash="dot", line_color="gray", line_width=1, row=3, col=1)
    add_recession_shading(fig, recession, 3, 1, y0=-80, y1=120)
    fig.update_yaxes(title_text="Net % Tightening", title_font_size=10, row=3, col=1)

    # ── Panel 6: Financial Conditions ────────────────────────────────────────
    fc_specs = [
        ("STLFSI4", "St. Louis FSI", COLORS["red"]),
        ("NFCI",    "Chicago NFCI",  COLORS["navy"]),
    ]
    for sid, name, color in fc_specs:
        s = raw.get(sid)
        if s is not None and len(s) > 0:
            fig.add_trace(go.Scatter(
                x=s.index, y=s.values, mode="lines", name=name,
                line=dict(color=color, width=1.8),
                legendgroup="p6",
            ), row=3, col=2)

    fig.add_hline(y=0, line_dash="dot",  line_color="gray",       line_width=1, row=3, col=2)
    fig.add_hline(y=1, line_dash="dash", line_color="darkorange", line_width=1, row=3, col=2)
    add_recession_shading(fig, recession, 3, 2, y0=-8, y1=12)
    fig.update_yaxes(title_text="Z-Score", title_font_size=10, row=3, col=2)

    # ── Panel 7: NBF Institution Lending ─────────────────────────────────────
    nbf     = t.get("nbf")
    nbf_yoy = t.get("yoy_NBF")

    if nbf is not None and len(nbf) > 0:
        fig.add_trace(go.Scatter(
            x=nbf.index, y=nbf.values, mode="lines", name="NBF Level ($B)",
            line=dict(color=COLORS["navy"], width=2),
            legendgroup="p7",
        ), row=4, col=1, secondary_y=False)

    if nbf_yoy is not None and len(nbf_yoy) > 0:
        fig.add_trace(go.Scatter(
            x=nbf_yoy.index, y=nbf_yoy.values, mode="lines", name="NBF YoY %",
            line=dict(color=COLORS["purple"], width=1.6, dash="dot"),
            legendgroup="p7",
        ), row=4, col=1, secondary_y=True)
        # Zero line on secondary y via trace
        fig.add_trace(go.Scatter(
            x=[nbf_yoy.index[0], nbf_yoy.index[-1]], y=[0, 0],
            mode="lines", name="Zero line",
            line=dict(dash="dot", color="gray", width=1),
            showlegend=False, legendgroup="p7",
        ), row=4, col=1, secondary_y=True)

    nbf_label = t.get("nbf_label", "")
    if "derived" in nbf_label:
        fig.add_annotation(
            text="Note: Derived residual (includes ag &amp; misc loans)",
            xref="x7", yref="y7",
            x=0.02, y=0.05, xanchor="left",
            showarrow=False,
            font=dict(size=8, color="gray"),
        )

    add_recession_shading(fig, recession, 4, 1, y0=0, y1=15000)
    fig.update_yaxes(title_text="Level ($B)", title_font_size=10, row=4, col=1, secondary_y=False)
    fig.update_yaxes(title_text="YoY %",      title_font_size=10, row=4, col=1, secondary_y=True)

    # ── Panel 8: Fed Borrowings ───────────────────────────────────────────────
    cutoff5 = pd.Timestamp.today() - pd.DateOffset(years=5)

    disc = raw.get("DPCREDIT")
    if disc is not None and len(disc) > 0:
        d5 = disc[disc.index >= cutoff5]
        fig.add_trace(go.Bar(
            x=d5.index, y=d5.values, name="Discount Window ($B)",
            marker_color=COLORS["red"], opacity=0.8,
            legendgroup="p8",
        ), row=4, col=2)

    btfp = raw.get("WBTFP")
    if btfp is not None and len(btfp) > 0:
        b5 = btfp[btfp.index >= cutoff5]
        if len(b5) > 0 and b5.sum() > 0:
            fig.add_trace(go.Bar(
                x=b5.index, y=b5.values, name="BTFP ($B)",
                marker_color=COLORS["orange"], opacity=0.8,
                legendgroup="p8",
            ), row=4, col=2)

    fig.update_layout(barmode="stack")
    fig.update_yaxes(title_text="$B borrowed from Fed", title_font_size=10, row=4, col=2)

    # ── Global layout ─────────────────────────────────────────────────────────
    last_updated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    fig.update_layout(
        title=dict(
            text="H.8 Systemic Credit Risk Monitor",
            x=0.5, xanchor="center",
            font=dict(size=22, color=COLORS["forest"]),
        ),
        height=1900,
        showlegend=True,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.01,
            xanchor="center", x=0.5,
            font=dict(size=9),
            tracegroupgap=6,
        ),
        template="plotly_white",
        margin=dict(t=140, l=65, r=55, b=60),
    )
    fig.update_annotations(font_size=12, font_color="#1a1a2e")
    fig.add_annotation(
        text=(
            f"Last Updated: {last_updated} | "
            "Source: FRED / Federal Reserve H.8 &amp; SLOOS | "
            "Gray shading = NBER recessions"
        ),
        xref="paper", yref="paper",
        x=0.5, y=-0.02, showarrow=False,
        font=dict(size=10, color="gray"),
    )
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor="#eeeeee")
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor="#eeeeee")

    return fig


# ── Scorecard ─────────────────────────────────────────────────────────────────
def _signal_badge(value, key):
    """Return colored HTML badge based on threshold rules."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return '<span class="badge badge-na">N/A</span>'

    thresh = THRESHOLDS.get(key)
    if thresh is None:
        return '<span class="badge badge-na">—</span>'

    direction = thresh["dir"]

    if direction == "two_sided":
        lo_s = thresh["stress_lo"]
        lo_w = thresh["warn_lo"]
        hi_w = thresh["warn_hi"]
        hi_s = thresh["stress_hi"]
        if value <= lo_s or value >= hi_s:
            cls = "badge-stress"
        elif value <= lo_w or value >= hi_w:
            cls = "badge-warn"
        else:
            cls = "badge-ok"

    elif direction == "lower_bad":
        if value <= thresh["stress"]:
            cls = "badge-stress"
        elif value <= thresh["warn"]:
            cls = "badge-warn"
        else:
            cls = "badge-ok"

    else:  # upper_bad
        if value >= thresh["stress"]:
            cls = "badge-stress"
        elif value >= thresh["warn"]:
            cls = "badge-warn"
        else:
            cls = "badge-ok"

    label = {"badge-ok": "OK", "badge-warn": "WARN", "badge-stress": "STRESS"}[cls]
    return f'<span class="badge {cls}">{label}</span>'


def _fmt(val, decimals=2, signed=False):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    fmt = f"{val:+.{decimals}f}" if signed else f"{val:.{decimals}f}"
    return fmt


def _last(s):
    return float(s.iloc[-1]) if s is not None and len(s) > 0 else None

def _wow(s):
    return float(s.iloc[-1] - s.iloc[-2]) if s is not None and len(s) >= 2 else None

def _avg(s, n):
    return float(s.iloc[-n:].mean()) if s is not None and len(s) >= 1 else None


def compute_scorecard(raw, t):
    slo = raw["SLO"]
    rows = [
        {
            "metric":  "Total Loans YoY %",
            "latest":  _last(t.get("yoy_TOTLL")),
            "wow":     _wow(t.get("yoy_TOTLL")),
            "avg4":    _avg(t.get("yoy_TOTLL"), 4),
            "avg52":   _avg(t.get("yoy_TOTLL"), 52),
            "thresh":  "tot_yoy",
        },
        {
            "metric":  "C&I Loans YoY %",
            "latest":  _last(t.get("yoy_BUSLOANS")),
            "wow":     _wow(t.get("yoy_BUSLOANS")),
            "avg4":    _avg(t.get("yoy_BUSLOANS"), 4),
            "avg52":   _avg(t.get("yoy_BUSLOANS"), 52),
            "thresh":  "ci_yoy",
        },
        {
            "metric":  "Real Estate Loans YoY %",
            "latest":  _last(t.get("yoy_REALLN")),
            "wow":     _wow(t.get("yoy_REALLN")),
            "avg4":    _avg(t.get("yoy_REALLN"), 4),
            "avg52":   _avg(t.get("yoy_REALLN"), 52),
            "thresh":  "re_yoy",
        },
        {
            "metric":  "Consumer Loans YoY %",
            "latest":  _last(t.get("yoy_CONSUMER")),
            "wow":     _wow(t.get("yoy_CONSUMER")),
            "avg4":    _avg(t.get("yoy_CONSUMER"), 4),
            "avg52":   _avg(t.get("yoy_CONSUMER"), 52),
            "thresh":  "con_yoy",
        },
        {
            "metric":  "NBF/Other Loans YoY % ↕",
            "latest":  _last(t.get("yoy_NBF")),
            "wow":     _wow(t.get("yoy_NBF")),
            "avg4":    _avg(t.get("yoy_NBF"), 4),
            "avg52":   _avg(t.get("yoy_NBF"), 52),
            "thresh":  "nbf_yoy",
        },
        {
            "metric":  "St. Louis FSI (STLFSI4)",
            "latest":  _last(raw.get("STLFSI4")),
            "wow":     _wow(raw.get("STLFSI4")),
            "avg4":    _avg(raw.get("STLFSI4"), 4),
            "avg52":   _avg(raw.get("STLFSI4"), 52),
            "thresh":  "stlfsi4",
        },
        {
            "metric":  "Chicago NFCI",
            "latest":  _last(raw.get("NFCI")),
            "wow":     _wow(raw.get("NFCI")),
            "avg4":    _avg(raw.get("NFCI"), 4),
            "avg52":   _avg(raw.get("NFCI"), 52),
            "thresh":  "nfci",
        },
        {
            "metric":  "C&I SLO Tightening %",
            "latest":  _last(slo.get("DRTSCILM")),
            "wow":     None,
            "avg4":    None,
            "avg52":   None,
            "thresh":  "ci_slo",
        },
        {
            "metric":  "NBF SLO Tightening %",
            "latest":  _last(slo.get("DRTSNBFI")),
            "wow":     None,
            "avg4":    None,
            "avg52":   None,
            "thresh":  "nbf_slo",
        },
        {
            "metric":  "L/D Ratio %",
            "latest":  _last(t.get("ld_ratio")),
            "wow":     _wow(t.get("ld_ratio")),
            "avg4":    _avg(t.get("ld_ratio"), 4),
            "avg52":   _avg(t.get("ld_ratio"), 52),
            "thresh":  None,
        },
        {
            "metric":  "Discount Window ($B)",
            "latest":  _last(raw.get("DPCREDIT")),
            "wow":     _wow(raw.get("DPCREDIT")),
            "avg4":    _avg(raw.get("DPCREDIT"), 4),
            "avg52":   _avg(raw.get("DPCREDIT"), 52),
            "thresh":  "disc_win",
        },
        {
            "metric":  "CRE / Total Loans %",
            "latest":  _last(t.get("share_CRE")),
            "wow":     _wow(t.get("share_CRE")),
            "avg4":    _avg(t.get("share_CRE"), 4),
            "avg52":   _avg(t.get("share_CRE"), 52),
            "thresh":  None,
        },
    ]
    return rows


def build_scorecard_html(scorecard):
    rows_html = ""
    for r in scorecard:
        badge = _signal_badge(r["latest"], r["thresh"])
        rows_html += f"""
        <tr>
          <td>{r["metric"]}</td>
          <td>{_fmt(r["latest"])}</td>
          <td>{_fmt(r["wow"], signed=True)}</td>
          <td>{_fmt(r["avg4"])}</td>
          <td>{_fmt(r["avg52"])}</td>
          <td>{badge}</td>
        </tr>"""

    return f"""<table class="scorecard">
  <thead>
    <tr>
      <th>Metric</th>
      <th>Latest</th>
      <th>WoW Δ</th>
      <th>4-Wk Avg</th>
      <th>52-Wk Avg</th>
      <th>Signal</th>
    </tr>
  </thead>
  <tbody>{rows_html}
  </tbody>
</table>"""


# ── HTML template ──────────────────────────────────────────────────────────────
_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>H.8 Systemic Credit Risk Monitor</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@400;600;700&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --forest:       #1a3a2f;
    --forest-light: #2d5a47;
    --cream:        #faf9f7;
    --charcoal:     #1a1a1a;
    --warm-gray:    #6b6b6b;
    --mint:         #e8f0ec;
    --border:       #d4d9d6;
    --font-display: 'Fraunces', Georgia, serif;
    --font-body:    'DM Sans', system-ui, sans-serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: var(--font-body); background: var(--cream); color: var(--charcoal); }}
  header {{
    background: var(--forest);
    color: #fff;
    padding: 20px 32px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  header h1 {{
    font-family: var(--font-display);
    font-size: 1.45rem;
    font-weight: 600;
  }}
  header .subtitle {{
    font-size: 0.78rem;
    color: rgba(255,255,255,0.65);
    margin-top: 4px;
  }}
  header .meta {{
    font-size: 0.78rem;
    color: rgba(255,255,255,0.65);
    text-align: right;
  }}
  header .meta a {{
    color: rgba(255,255,255,0.6);
    text-decoration: none;
  }}
  .chart-wrap {{ padding: 24px 28px 0; }}
  .scorecard-wrap {{ padding: 24px 28px 48px; }}
  .scorecard-wrap h2 {{
    font-family: var(--font-display);
    font-size: 1.05rem;
    color: var(--forest);
    margin-bottom: 6px;
  }}
  .scorecard-wrap .note {{
    font-size: 0.78rem;
    color: var(--warm-gray);
    margin-bottom: 14px;
  }}
  table.scorecard {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.84rem;
  }}
  table.scorecard th {{
    background: var(--forest);
    color: #fff;
    padding: 8px 12px;
    text-align: left;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }}
  table.scorecard td {{
    padding: 7px 12px;
    border-bottom: 1px solid var(--border);
  }}
  table.scorecard tbody tr:hover {{ background: var(--mint); }}
  .badge {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.71rem;
    font-weight: 600;
    letter-spacing: 0.04em;
  }}
  .badge-ok     {{ background: #d4edda; color: #155724; }}
  .badge-warn   {{ background: #fff3cd; color: #856404; }}
  .badge-stress {{ background: #f8d7da; color: #721c24; }}
  .badge-na     {{ background: #e9ecef; color: #6c757d; }}
  @media (max-width: 768px) {{
    header {{ flex-direction: column; gap: 10px; align-items: flex-start; }}
    .chart-wrap, .scorecard-wrap {{ padding: 16px; }}
  }}
</style>
</head>
<body>

<header>
  <div>
    <h1>🏦 H.8 Systemic Credit Risk Monitor</h1>
    <div class="subtitle">
      Federal Reserve H.8 · Commercial Bank Assets &amp; Liabilities · Weekly (SA)
    </div>
  </div>
  <div class="meta">
    Updated: {last_updated}<br>
    <a href="https://boquin.xyz">← boquin.xyz</a>
  </div>
</header>

<div class="chart-wrap">
  <div id="chart-div"></div>
</div>

<div class="scorecard-wrap">
  <h2>Credit Risk Scorecard</h2>
  <p class="note">
    ↕ NBF signal is <strong>two-sided</strong>: rapid growth (&gt;+20% YoY) and sharp
    contraction (&lt;−5% YoY) both signal elevated systemic risk (leverage buildup vs.
    deleveraging shock). Quarterly SLO tightening rows show latest survey reading only.
  </p>
  {scorecard_html}
</div>

<script>
var figData = {fig_json};
Plotly.newPlot('chart-div', figData.data, figData.layout, {{
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ['lasso2d','select2d','toggleSpikelines'],
  displaylogo: false
}});
</script>

</body>
</html>"""


def build_html(fig, scorecard_html, last_updated):
    fig_json = fig.to_json()
    return _HTML_TEMPLATE.format(
        last_updated=last_updated,
        fig_json=fig_json,
        scorecard_html=scorecard_html,
    )


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("H.8 Systemic Credit Risk Monitor")
    print("=" * 60)

    raw = fetch_all()
    t   = compute_transforms(raw)
    fig = build_figure(raw, t)

    scorecard      = compute_scorecard(raw, t)
    scorecard_html = build_scorecard_html(scorecard)

    last_updated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    html = build_html(fig, scorecard_html, last_updated)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✅ Dashboard saved → {OUTPUT_PATH}")

    # Summary printout
    for key, label in [
        ("yoy_TOTLL",    "Total Loans YoY"),
        ("yoy_BUSLOANS", "C&I Loans YoY  "),
    ]:
        s = t.get(key)
        if s is not None and len(s) > 0:
            print(f"  {label}: {s.iloc[-1]:.2f}%  ({s.index[-1].date()})")

    ld = t.get("ld_ratio")
    if ld is not None and len(ld) > 0:
        print(f"  L/D Ratio      : {ld.iloc[-1]:.1f}%")

    fsi = raw.get("STLFSI4")
    if fsi is not None and len(fsi) > 0:
        print(f"  STLFSI4        : {fsi.iloc[-1]:.3f}")

    nbf_yoy = t.get("yoy_NBF")
    if nbf_yoy is not None and len(nbf_yoy) > 0:
        print(f"  NBF YoY ({t['nbf_label'][:20]}...): {nbf_yoy.iloc[-1]:.2f}%")


if __name__ == "__main__":
    main()

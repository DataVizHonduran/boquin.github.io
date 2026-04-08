"""
10Y Treasury Yield — MA Monitor
================================
Two-panel interactive dashboard with dropdown to switch between:
  • 200-Day MA
  • 200-Week MA
  • 200-Month MA

Each view shows:
  Panel 1 — 10Y yield vs selected MA (40-year history)
  Panel 2 — Residual with ±1σ and ±2σ mean-reversion bands

Output: reports/10y-ma-monitor/index.html
Requires: FRED_API_KEY environment variable
"""

import os
import json
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date
from dateutil.relativedelta import relativedelta
from fredapi import Fred

OUTPUT_PATH = "reports/10y-ma-monitor/index.html"
YEARS       = 40

FRED_API_KEY = os.environ.get("FRED_API_KEY")
if not FRED_API_KEY:
    raise EnvironmentError("FRED_API_KEY environment variable is not set.")

os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
fred = Fred(api_key=FRED_API_KEY)

# ── Fetch raw daily series ───────────────────────────────────────────────────
start = date.today() - relativedelta(years=YEARS)
raw   = fred.get_series("DGS10", observation_start=start).dropna()
raw.index = pd.to_datetime(raw.index)
raw.name  = "10Y Yield"
latest_yield = raw.iloc[-1]
latest_date  = raw.index[-1].strftime("%Y-%m-%d")

# ── Compute three MAs + residuals ────────────────────────────────────────────
def compute_ma(series, freq, window):
    """Resample → rolling MA → reindex back to daily (ffill)."""
    resampled = series.resample(freq).last()
    ma = resampled.rolling(window).mean()
    return ma.reindex(series.index, method="ffill")

ma_d = raw.rolling(200).mean()                  # 200-day (on daily)
ma_w = compute_ma(raw, "W",  200)               # 200-week
ma_m = compute_ma(raw, "MS", 200)               # 200-month

res_d = (raw - ma_d).dropna()
res_w = (raw - ma_w).dropna()
res_m = (raw - ma_m).dropna()

def sigma_stats(res, ma):
    s    = res.std()
    last = res.iloc[-1]
    return dict(
        sigma=s,
        latest_residual=last,
        zscore=last / s,
        latest_ma=ma.dropna().iloc[-1],
    )

sd = sigma_stats(res_d, ma_d)
sw = sigma_stats(res_w, ma_w)
sm = sigma_stats(res_m, ma_m)

configs = [
    dict(label="200-Day MA",   res=res_d, ma=ma_d, stats=sd, ma_label="200d MA"),
    dict(label="200-Week MA",  res=res_w, ma=ma_w, stats=sw, ma_label="200w MA"),
    dict(label="200-Month MA", res=res_m, ma=ma_m, stats=sm, ma_label="200m MA"),
]

MA_COLORS   = ["firebrick", "#e07b00", "#6a0dad"]
BAND_COLORS = [("#d62728", "#1f77b4"),   # red/blue for day
               ("#d62728", "#1f77b4"),
               ("#d62728", "#1f77b4")]

# ── Trace index layout ───────────────────────────────────────────────────────
# 0      : 10Y Yield (always visible)
# 1-3    : MA lines (one per config)
# 4-6    : Residual fills (one per config)
# 7-14   : σ band traces — 4 per config (±1σ, ±2σ) × 3
# 15-17  : Latest dot (one per config)
# Total  : 18 traces

N = len(configs)   # 3
TRACE_YIELD     = 0
TRACE_MA        = [1, 2, 3]
TRACE_RES       = [4, 5, 6]
TRACE_BANDS_OFF = 7          # bands start here; 4 traces per config × 3 configs = 12 traces (7-18)
TRACE_DOT       = [19, 20, 21]
TOTAL_TRACES    = 22

def vis(active):
    """Return visibility list for the given active config index (0/1/2)."""
    v = [False] * TOTAL_TRACES
    v[TRACE_YIELD] = True
    v[TRACE_MA[active]]  = True
    v[TRACE_RES[active]] = True
    for k in range(4):
        v[TRACE_BANDS_OFF + active * 4 + k] = True
    v[TRACE_DOT[active]] = True
    return v

def make_title(cfg):
    s = cfg["stats"]
    return (
        f"10Y US Treasury Yield — {cfg['label']} Monitor<br>"
        f"<sub>Latest: {latest_yield:.2f}%  |  "
        f"{cfg['ma_label']}: {s['latest_ma']:.2f}%  |  "
        f"Residual: {s['latest_residual']:+.3f} pp  "
        f"(z = {s['zscore']:+.2f}σ)  |  Updated {latest_date}</sub>"
    )

# ── Build figure ─────────────────────────────────────────────────────────────
fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    row_heights=[0.55, 0.45],
    vertical_spacing=0.07,
    subplot_titles=[
        "10Y Treasury Yield vs Moving Average",
        "Residual (10Y Yield − MA)"
    ]
)

x0, xend = raw.index[0], raw.index[-1]

# Trace 0 — yield (always on)
fig.add_trace(go.Scatter(
    x=raw.index, y=raw.values,
    mode="lines", line=dict(color="#2c7bb6", width=1.3),
    name="10Y Yield",
    hovertemplate="%{x|%Y-%m-%d}: %{y:.2f}%<extra>10Y Yield</extra>"
), row=1, col=1)

# Traces 1-3 — MA lines
for i, cfg in enumerate(configs):
    fig.add_trace(go.Scatter(
        x=cfg["ma"].index, y=cfg["ma"].values,
        mode="lines", line=dict(color=MA_COLORS[i], width=2, dash="dot"),
        name=cfg["label"],
        visible=(i == 0),
        hovertemplate="%{x|%Y-%m-%d}: %{y:.2f}%<extra>" + cfg["label"] + "</extra>"
    ), row=1, col=1)

# Traces 4-6 — Residual fills
for i, cfg in enumerate(configs):
    fig.add_trace(go.Scatter(
        x=cfg["res"].index, y=cfg["res"].values,
        mode="lines", line=dict(color="#2c7bb6", width=0.9),
        fill="tozeroy", fillcolor="rgba(44,123,182,0.15)",
        name="Residual",
        visible=(i == 0),
        showlegend=False,
        hovertemplate="%{x|%Y-%m-%d}: %{y:+.3f} pp<extra>Residual</extra>"
    ), row=2, col=1)

# Traces 7-18 — sigma bands (4 per config: +1σ, -1σ, +2σ, -2σ)
for i, cfg in enumerate(configs):
    s   = cfg["stats"]["sigma"]
    rc, bc = BAND_COLORS[i]
    bands = [
        ( s,    rc, "dash", "+1σ"),
        (-s,    bc, "dash", "−1σ"),
        ( 2*s,  rc, "dot",  "+2σ"),
        (-2*s,  bc, "dot",  "−2σ"),
    ]
    for val, color, dash, lbl in bands:
        fig.add_trace(go.Scatter(
            x=[x0, xend], y=[val, val],
            mode="lines+text",
            text=["", lbl],
            textposition="middle right",
            textfont=dict(color=color, size=10),
            line=dict(color=color, width=1 if "1σ" in lbl else 1.4, dash=dash),
            showlegend=False,
            visible=(i == 0),
            hoverinfo="skip"
        ), row=2, col=1)

# Traces 15-17 — latest dot
for i, cfg in enumerate(configs):
    s = cfg["stats"]
    dot_color = "#d62728" if s["latest_residual"] >= 0 else "#1f77b4"
    fig.add_trace(go.Scatter(
        x=[cfg["res"].index[-1]], y=[s["latest_residual"]],
        mode="markers",
        marker=dict(color=dot_color, size=8, line=dict(color="white", width=1.5)),
        name=f"Latest: {s['latest_residual']:+.3f} pp",
        visible=(i == 0),
        hovertemplate=(
            f"{latest_date}: {s['latest_residual']:+.3f} pp "
            f"(z={s['zscore']:+.2f}σ)<extra></extra>"
        )
    ), row=2, col=1)

# ── Zero line (shape — always visible) ──────────────────────────────────────
fig.add_hline(y=0, line_color="black", line_width=1.5, row=2, col=1)

# ── Dropdown ─────────────────────────────────────────────────────────────────
buttons = []
for i, cfg in enumerate(configs):
    buttons.append(dict(
        label=cfg["label"],
        method="update",
        args=[
            {"visible": vis(i)},
            {"title.text": make_title(cfg)}
        ]
    ))

fig.update_layout(
    updatemenus=[dict(
        buttons=buttons,
        direction="down",
        showactive=True,
        x=0.01, y=1.13,
        xanchor="left", yanchor="top",
        bgcolor="white",
        bordercolor="#ccc",
        font=dict(size=12)
    )],
    title=dict(text=make_title(configs[0]), font=dict(size=17)),
    plot_bgcolor="white",
    paper_bgcolor="white",
    hovermode="x unified",
    height=720,
    margin=dict(l=60, r=80, t=110, b=50),
    legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.8)",
                bordercolor="#ccc", borderwidth=1),
    font=dict(family="Arial, sans-serif", size=12)
)

fig.update_xaxes(showgrid=True, gridcolor="#ebebeb", tickformat="%Y")
fig.update_yaxes(showgrid=True, gridcolor="#ebebeb")
fig.update_yaxes(title_text="Yield (%)",      row=1, col=1)
fig.update_yaxes(title_text="Residual (pp)",  zeroline=False, row=2, col=1)

# ── Stats JSON for JS stats bar ───────────────────────────────────────────────
stats_json = json.dumps({
    cfg["label"]: {
        "ma":       f"{cfg['stats']['latest_ma']:.2f}%",
        "residual": f"{cfg['stats']['latest_residual']:+.3f} pp",
        "zscore":   f"{cfg['stats']['zscore']:+.2f}σ",
        "sigma":    f"{cfg['stats']['sigma']:.3f} pp",
        "pos":      bool(cfg['stats']['latest_residual'] >= 0),
    }
    for cfg in configs
})

chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn", div_id="ma-chart")

# ── HTML wrapper ──────────────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>10Y Treasury MA Monitor — boquin.xyz</title>
  <style>
    body  {{ margin:0; background:#f9f9f9; font-family:Arial,sans-serif; }}
    .header {{
      background:#1a1a2e; color:#fff; padding:18px 28px 14px;
      display:flex; align-items:center; justify-content:space-between;
    }}
    .header h1 {{ margin:0; font-size:1.15rem; font-weight:600; }}
    .header a  {{ color:#7eb8f7; font-size:0.85rem; text-decoration:none; }}
    .header a:hover {{ text-decoration:underline; }}
    .stats {{
      display:flex; gap:28px; flex-wrap:wrap;
      background:#fff; border-bottom:1px solid #e0e0e0;
      padding:12px 28px; font-size:0.88rem; color:#444;
      align-items:flex-end;
    }}
    .stat {{ display:flex; flex-direction:column; }}
    .stat-label {{ font-size:0.72rem; color:#888; text-transform:uppercase;
                   letter-spacing:.05em; margin-bottom:2px; }}
    .stat-value {{ font-size:1.05rem; font-weight:600; color:#1a1a2e; }}
    .pos {{ color:#d62728 !important; }}
    .neg {{ color:#1f77b4 !important; }}
    .chart-wrap {{ padding:12px 16px 20px; }}
    .footer {{ text-align:center; padding:12px; font-size:0.78rem; color:#aaa; }}
  </style>
</head>
<body>
  <div class="header">
    <h1>📈 10Y Treasury Yield — MA Monitor</h1>
    <a href="/">← boquin.xyz</a>
  </div>

  <div class="stats">
    <div class="stat">
      <span class="stat-label">10Y Yield</span>
      <span class="stat-value">{latest_yield:.2f}%</span>
    </div>
    <div class="stat">
      <span class="stat-label">Selected MA</span>
      <span class="stat-value" id="stat-ma">{sd['latest_ma']:.2f}%</span>
    </div>
    <div class="stat">
      <span class="stat-label">Residual</span>
      <span class="stat-value {'pos' if sd['latest_residual'] >= 0 else 'neg'}" id="stat-res">{sd['latest_residual']:+.3f} pp</span>
    </div>
    <div class="stat">
      <span class="stat-label">Z-Score</span>
      <span class="stat-value {'pos' if sd['zscore'] >= 0 else 'neg'}" id="stat-z">{sd['zscore']:+.2f}σ</span>
    </div>
    <div class="stat">
      <span class="stat-label">σ (history)</span>
      <span class="stat-value" id="stat-sigma">{sd['sigma']:.3f} pp</span>
    </div>
    <div class="stat">
      <span class="stat-label">As of</span>
      <span class="stat-value">{latest_date}</span>
    </div>
  </div>

  <div class="chart-wrap">
    {chart_html}
  </div>

  <div class="footer">
    Data: FRED (DGS10) · Updated daily on business days ·
    <a href="https://github.com/DataVizHonduran/boquin.github.io/tree/main/scripts/generate_10y_ma_monitor.py">Source code</a>
  </div>

  <script>
    const STATS = {stats_json};
    const MA_LABELS = ["200-Day MA", "200-Week MA", "200-Month MA"];

    function updateStatsBar(label) {{
      const s = STATS[label];
      if (!s) return;
      document.getElementById('stat-ma').textContent    = s.ma;
      document.getElementById('stat-res').textContent   = s.residual;
      document.getElementById('stat-z').textContent     = s.zscore;
      document.getElementById('stat-sigma').textContent = s.sigma;
      ['stat-res','stat-z'].forEach(id => {{
        const el = document.getElementById(id);
        el.className = 'stat-value ' + (s.pos ? 'pos' : 'neg');
      }});
    }}

    // Detect Plotly dropdown selection via plotly_restyle event
    const div = document.getElementById('ma-chart');
    div.on('plotly_restyle', function() {{
      // The active button index is stored in the updatemenus state
      const menu = div._fullLayout.updatemenus[0];
      if (menu && typeof menu.active === 'number') {{
        updateStatsBar(MA_LABELS[menu.active]);
      }}
    }});
  </script>
</body>
</html>"""

with open(OUTPUT_PATH, "w") as f:
    f.write(html)

print(f"✅  Saved: {OUTPUT_PATH}")
for cfg in configs:
    s = cfg["stats"]
    print(f"   {cfg['label']:15s}  MA={s['latest_ma']:.2f}%  "
          f"res={s['latest_residual']:+.3f} pp  z={s['zscore']:+.2f}σ  σ={s['sigma']:.3f}")
print(f"   As of: {latest_date}")

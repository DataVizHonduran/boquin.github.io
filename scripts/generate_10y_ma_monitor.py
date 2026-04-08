"""
10Y Treasury Yield — 200-Day MA Monitor
========================================
Generates a two-panel interactive dashboard:
  Panel 1 — 10Y yield vs its 200-day moving average (40-year history)
  Panel 2 — Residual (yield − MA) with ±1σ and ±2σ reference bands

Output: reports/10y-ma-monitor/index.html
Requires: FRED_API_KEY environment variable
"""

import os
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from fredapi import Fred

# ---------------------------------------------------------------------------
OUTPUT_PATH = "reports/10y-ma-monitor/index.html"
YEARS       = 40
MA_WINDOW   = 200   # trading days
# ---------------------------------------------------------------------------

FRED_API_KEY = os.environ.get("FRED_API_KEY")
if not FRED_API_KEY:
    raise EnvironmentError("FRED_API_KEY environment variable is not set.")

os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

fred = Fred(api_key=FRED_API_KEY)

# ── Fetch data ──────────────────────────────────────────────────────────────
start = date.today() - relativedelta(years=YEARS)
raw   = fred.get_series("DGS10", observation_start=start).dropna()
raw.index = pd.to_datetime(raw.index)
raw.name  = "10Y Yield"

ma     = raw.rolling(MA_WINDOW).mean()
ma.name = "200-Day MA"

residual       = (raw - ma).dropna()
sigma          = residual.std()
latest_yield   = raw.iloc[-1]
latest_ma      = ma.dropna().iloc[-1]
latest_residual = residual.iloc[-1]
latest_date    = raw.index[-1].strftime("%Y-%m-%d")
zscore_now     = latest_residual / sigma

# ── Build chart ─────────────────────────────────────────────────────────────
fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    row_heights=[0.55, 0.45],
    vertical_spacing=0.07,
    subplot_titles=[
        "10Y Treasury Yield vs 200-Day Moving Average",
        "Residual (10Y Yield − 200-Day MA)"
    ]
)

# ── Panel 1: yield + MA ──────────────────────────────────────────────────────
fig.add_trace(go.Scatter(
    x=raw.index, y=raw.values,
    mode="lines", line=dict(color="#2c7bb6", width=1.3),
    name="10Y Yield",
    hovertemplate="%{x|%Y-%m-%d}: %{y:.2f}%<extra>10Y Yield</extra>"
), row=1, col=1)

fig.add_trace(go.Scatter(
    x=ma.index, y=ma.values,
    mode="lines", line=dict(color="firebrick", width=2, dash="dot"),
    name="200-Day MA",
    hovertemplate="%{x|%Y-%m-%d}: %{y:.2f}%<extra>200d MA</extra>"
), row=1, col=1)

# ── Panel 2: residual + sigma bands ─────────────────────────────────────────
fig.add_trace(go.Scatter(
    x=residual.index, y=residual.values,
    mode="lines", line=dict(color="#2c7bb6", width=0.9),
    fill="tozeroy", fillcolor="rgba(44,123,182,0.15)",
    name="Residual",
    hovertemplate="%{x|%Y-%m-%d}: %{y:+.3f} pp<extra>Residual</extra>"
), row=2, col=1)

fig.add_hline(y=0,          line_color="black",     line_width=1.5,              row=2, col=1)
fig.add_hline(y= sigma,     line_color="#d62728",   line_width=1, line_dash="dash",
              annotation_text="+1σ", annotation_position="right", row=2, col=1)
fig.add_hline(y=-sigma,     line_color="#1f77b4",   line_width=1, line_dash="dash",
              annotation_text="−1σ", annotation_position="right", row=2, col=1)
fig.add_hline(y= 2*sigma,   line_color="#d62728",   line_width=1.4, line_dash="dot",
              annotation_text="+2σ", annotation_position="right", row=2, col=1)
fig.add_hline(y=-2*sigma,   line_color="#1f77b4",   line_width=1.4, line_dash="dot",
              annotation_text="−2σ", annotation_position="right", row=2, col=1)

# ── Colour the last residual dot ─────────────────────────────────────────────
dot_color = "#d62728" if latest_residual > 0 else "#1f77b4"
fig.add_trace(go.Scatter(
    x=[residual.index[-1]], y=[latest_residual],
    mode="markers", marker=dict(color=dot_color, size=8, line=dict(color="white", width=1.5)),
    name=f"Latest: {latest_residual:+.3f} pp",
    hovertemplate=f"{latest_date}: {latest_residual:+.3f} pp  (z={zscore_now:+.2f}σ)<extra></extra>"
), row=2, col=1)

# ── Layout ───────────────────────────────────────────────────────────────────
fig.update_layout(
    title=dict(
        text=(
            f"10Y US Treasury Yield — Level & Mean-Reversion Monitor<br>"
            f"<sub>Latest: {latest_yield:.2f}%  |  200d MA: {latest_ma:.2f}%  |  "
            f"Residual: {latest_residual:+.3f} pp  (z = {zscore_now:+.2f}σ)  |  "
            f"Updated {latest_date}</sub>"
        ),
        font=dict(size=17)
    ),
    plot_bgcolor="white",
    paper_bgcolor="white",
    hovermode="x unified",
    height=700,
    margin=dict(l=60, r=80, t=90, b=50),
    legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.8)", bordercolor="#ccc", borderwidth=1),
    font=dict(family="Arial, sans-serif", size=12)
)

fig.update_xaxes(showgrid=True, gridcolor="#ebebeb", tickformat="%Y", row=1, col=1)
fig.update_xaxes(showgrid=True, gridcolor="#ebebeb", tickformat="%Y", title_text="", row=2, col=1)
fig.update_yaxes(showgrid=True, gridcolor="#ebebeb", title_text="Yield (%)", row=1, col=1)
fig.update_yaxes(showgrid=True, gridcolor="#ebebeb", title_text="Residual (pp)",
                 zeroline=False, row=2, col=1)

# ── Wrap in minimal HTML with a header strip ─────────────────────────────────
chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

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
    .header h1  {{ margin:0; font-size:1.15rem; font-weight:600; }}
    .header a   {{ color:#7eb8f7; font-size:0.85rem; text-decoration:none; }}
    .header a:hover {{ text-decoration:underline; }}
    .stats {{
      display:flex; gap:24px; flex-wrap:wrap;
      background:#fff; border-bottom:1px solid #e0e0e0;
      padding:12px 28px; font-size:0.88rem; color:#444;
    }}
    .stat {{ display:flex; flex-direction:column; }}
    .stat-label {{ font-size:0.75rem; color:#888; text-transform:uppercase; letter-spacing:.04em; }}
    .stat-value {{ font-size:1.05rem; font-weight:600; color:#1a1a2e; }}
    .{"positive"} {{ color:#d62728 !important; }}
    .{"negative"} {{ color:#1f77b4 !important; }}
    .chart-wrap {{ padding:16px 20px 24px; }}
    .footer {{ text-align:center; padding:12px; font-size:0.78rem; color:#aaa; }}
  </style>
</head>
<body>
  <div class="header">
    <h1>📈 10Y Treasury Yield — 200-Day MA Monitor</h1>
    <a href="/">← boquin.xyz</a>
  </div>

  <div class="stats">
    <div class="stat">
      <span class="stat-label">10Y Yield</span>
      <span class="stat-value">{latest_yield:.2f}%</span>
    </div>
    <div class="stat">
      <span class="stat-label">200-Day MA</span>
      <span class="stat-value">{latest_ma:.2f}%</span>
    </div>
    <div class="stat">
      <span class="stat-label">Residual</span>
      <span class="stat-value {'positive' if latest_residual >= 0 else 'negative'}">{latest_residual:+.3f} pp</span>
    </div>
    <div class="stat">
      <span class="stat-label">Z-Score</span>
      <span class="stat-value {'positive' if zscore_now >= 0 else 'negative'}">{zscore_now:+.2f}σ</span>
    </div>
    <div class="stat">
      <span class="stat-label">σ (full history)</span>
      <span class="stat-value">{sigma:.3f} pp</span>
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
</body>
</html>"""

with open(OUTPUT_PATH, "w") as f:
    f.write(html)

print(f"✅  Saved: {OUTPUT_PATH}")
print(f"   10Y Yield : {latest_yield:.2f}%")
print(f"   200d MA   : {latest_ma:.2f}%")
print(f"   Residual  : {latest_residual:+.3f} pp  (z = {zscore_now:+.2f}σ)")
print(f"   σ         : {sigma:.3f} pp")
print(f"   As of     : {latest_date}")

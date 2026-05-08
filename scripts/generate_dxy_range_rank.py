#!/usr/bin/env python3
"""
DXY Four-Year Range Rank
Rolling percentile rank of DXY within its 4-year high/low range.
Formula: (close - rolling_4yr_min) / (rolling_4yr_max - rolling_4yr_min) * 100
"""

import os
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── Config ─────────────────────────────────────────────────────────────────────
WINDOW       = 252 * 4   # 4-year rolling window in trading days
OS_THRESHOLD = 10        # rank below this = Oversold
CLUSTER_DAYS = 1260      # ~5 years: merge OS episodes closer than this into one trough
OUTPUT_DIR   = os.path.expanduser("~/boquin.github.io/reports/dxy-range-rank")
OUTPUT_FILE  = os.path.join(OUTPUT_DIR, "index.html")

# ── Data ───────────────────────────────────────────────────────────────────────
print("Fetching DXY data from Yahoo Finance…")
raw = yf.download("DX-Y.NYB", period="max", auto_adjust=True, progress=False)

# Flatten MultiIndex if present
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)

close = raw["Close"].dropna()
print(f"  {close.index[0].date()} → {close.index[-1].date()}  ({len(close)} rows)")

# ── Indicator ──────────────────────────────────────────────────────────────────
roll_min = close.rolling(WINDOW, min_periods=int(WINDOW * 0.25)).min()
roll_max = close.rolling(WINDOW, min_periods=int(WINDOW * 0.25)).max()
rank = (close - roll_min) / (roll_max - roll_min) * 100
rank = rank.clip(0, 100)

current_rank  = rank.iloc[-1]
current_price = close.iloc[-1]
last_date     = close.index[-1]
print(f"  Current price: {current_price:.2f}  |  Four-Year Range Rank: {current_rank:.2f}")

# ── Detect OS troughs ──────────────────────────────────────────────────────────
# Group all OS days into episodes, merge episodes within CLUSTER_DAYS, keep deepest
os_days = rank.index[rank < OS_THRESHOLD]
trough_dates = []
cluster_start = None
cluster_min_idx = None
cluster_min_val = None

for dt in os_days:
    if cluster_start is None:
        cluster_start, cluster_min_idx, cluster_min_val = dt, dt, rank[dt]
    elif (dt - cluster_start).days <= CLUSTER_DAYS:
        if rank[dt] < cluster_min_val:
            cluster_min_idx, cluster_min_val = dt, rank[dt]
    else:
        trough_dates.append(cluster_min_idx)
        cluster_start, cluster_min_idx, cluster_min_val = dt, dt, rank[dt]

if cluster_min_idx is not None:
    trough_dates.append(cluster_min_idx)

print(f"  OS troughs ({len(trough_dates)}): {[str(d.date()) for d in trough_dates]}")

# ── Chart ──────────────────────────────────────────────────────────────────────
fig = make_subplots(
    rows=2, cols=1,
    row_heights=[0.60, 0.40],
    shared_xaxes=True,
    vertical_spacing=0.06,
)

# Top panel — DXY price
fig.add_trace(go.Scatter(
    x=close.index, y=close.values,
    mode="lines",
    line=dict(color="#111111", width=1.2),
    name="DXY",
    hovertemplate="%{x|%Y-%m-%d}<br>%{y:.2f}<extra></extra>",
), row=1, col=1)

# Red dot + label at each OS trough on price panel
for dt in trough_dates:
    px_val = close.loc[dt]
    fig.add_trace(go.Scatter(
        x=[dt], y=[px_val],
        mode="markers+text",
        marker=dict(color="red", size=10),
        text=[dt.strftime("%m/%d/%Y")],
        textposition="top right",
        textfont=dict(size=10, color="#333333"),
        showlegend=False,
        hovertemplate=f"{dt.strftime('%Y-%m-%d')}<br>DXY: {px_val:.2f}<extra></extra>",
    ), row=1, col=1)

# Dashed red vertical lines on both panels at OS troughs
for dt in trough_dates:
    fig.add_vline(
        x=dt, line=dict(color="red", width=1.2, dash="dash"),
        row="all", col=1,
    )

# Bottom panel — Four-Year Range Rank
fig.add_trace(go.Scatter(
    x=rank.index, y=rank.values,
    mode="lines",
    fill="tozeroy",
    fillcolor="rgba(100, 149, 237, 0.30)",
    line=dict(color="cornflowerblue", width=1.4),
    name="Four-Year Range Rank",
    hovertemplate="%{x|%Y-%m-%d}<br>Rank: %{y:.1f}<extra></extra>",
), row=2, col=1)

# OB/OS reference lines
for level, label in [(90, "OB"), (10, "OS")]:
    fig.add_hline(
        y=level,
        line=dict(color="rgba(200,50,50,0.4)", width=1, dash="dot"),
        row=2, col=1,
    )

# ── Annotations ────────────────────────────────────────────────────────────────
fig.add_annotation(
    text=f"<b>Four-Year Range Rank</b>  <span style='color:cornflowerblue'>{current_rank:.2f}</span>",
    xref="paper", yref="paper",
    x=0.01, y=0.01,
    xanchor="left", yanchor="bottom",
    showarrow=False,
    font=dict(size=12),
    bgcolor="rgba(255,255,255,0.7)",
    borderpad=4,
)

# Current price label on right axis of top panel
fig.add_annotation(
    text=f"<b>{current_price:.2f}</b>",
    xref="paper", yref="y",
    x=1.01, y=current_price,
    xanchor="left", yanchor="middle",
    showarrow=False,
    font=dict(size=11, color="red"),
)

# ── Layout ─────────────────────────────────────────────────────────────────────
fig.update_layout(
    title=dict(
        text=(
            "<b>The U.S. Dollar Index sits at a crucial inflection point</b><br>"
            f"<span style='font-size:13px;color:#555'>DXY · Four-Year Range Rank from OB to OS  "
            f"<b style='color:red'>{current_rank:.2f}</b></span>"
        ),
        x=0.01, xanchor="left",
        font=dict(size=16),
    ),
    height=700,
    paper_bgcolor="#ffffff",
    plot_bgcolor="#f9f9f9",
    hovermode="x unified",
    showlegend=False,
    margin=dict(l=40, r=80, t=90, b=40),
    font=dict(family="Inter, sans-serif", size=11),
)

fig.update_yaxes(side="right", showgrid=True, gridcolor="#e5e5e5", row=1, col=1)
fig.update_yaxes(
    side="right", showgrid=True, gridcolor="#e5e5e5",
    range=[-2, 105], tickvals=[10, 30, 50, 70, 90],
    row=2, col=1,
)
fig.update_xaxes(showgrid=False, rangeslider_visible=False)

# ── Write HTML ─────────────────────────────────────────────────────────────────
os.makedirs(OUTPUT_DIR, exist_ok=True)

html_body = fig.to_html(
    include_plotlyjs="cdn",
    full_html=False,
    config={"displayModeBar": True, "scrollZoom": True},
)

updated = last_date.strftime("%B %d, %Y")
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DXY Four-Year Range Rank | boquin.xyz</title>
<style>
  body {{ margin: 0; font-family: Inter, sans-serif; background: #fff; color: #111; }}
  .header {{ padding: 18px 24px 0; border-bottom: 1px solid #eee; }}
  .header a {{ text-decoration: none; color: #0066cc; font-size: 13px; }}
  .meta {{ padding: 6px 24px 12px; font-size: 12px; color: #888; }}
  .chart-wrap {{ padding: 0 16px 24px; }}
  .footnote {{ padding: 0 24px 24px; font-size: 11px; color: #aaa; }}
</style>
</head>
<body>
<div class="header"><a href="/">← boquin.xyz</a></div>
<div class="meta">Last updated: {updated} &nbsp;·&nbsp; Data: Yahoo Finance (DX-Y.NYB)</div>
<div class="chart-wrap">{html_body}</div>
<div class="footnote">
  Four-Year Range Rank = (close − 4yr low) / (4yr high − 4yr low) × 100.
  Rolling window: 1,008 trading days. OB ≥ 90 · OS ≤ 10.
  Red dashed verticals mark prior OS cycle troughs.
</div>
</body>
</html>"""

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Written → {OUTPUT_FILE}")

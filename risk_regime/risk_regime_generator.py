import pandas_datareader.data as web
import pandas as pd
import numpy as np
import datetime
import plotly.graph_objects as go
import plotly.offline as pyo
from plotly.subplots import make_subplots

# Define tickers using only non-ETF, Stooq-available instruments
tickers = {
    "SPX": "SPY.US",
    "DAX": "EWG.US",
    "NIKKEI": "EWJ.US",
    "EMEQ": "EEM.US",
    "HYG": "HYG.US",
    "LQD": "LQD.US",
    "TLT": "TLT.US",
    "VIX": "VIXY.US",
    "DBC": "DBC.US",
    "GLD": "GLD.US",
    "USO": "USO.US",
    "CPER": "CPER.US",
    "VNQ": "VNQ.US",
    "UUP": "UUP.US"
}

invert_list = ["VIX", "TLT", "GLD", "UUP"]
start = datetime.datetime(2002, 1, 1)
end = datetime.datetime.today()

# Download and align data
data = {}
for name, ticker in tickers.items():
    try:
        df = web.DataReader(ticker, "stooq", start, end)
        df = df[::-1]  # Newest to oldest → oldest to newest
        data[name] = df["Close"]
        print(f"Successfully loaded {name} ({ticker})")
    except Exception as e:
        print(f"Failed to load {name} ({ticker}): {e}")

# Combine and drop missing
df_all = pd.concat(data.values(), axis=1)
df_all.columns = data.keys()
df_all.dropna(inplace=True)
print(f"Combined data shape: {df_all.shape}")

# Calculate z-scores of distance from moving average
z_scores = pd.DataFrame(index=df_all.index)
n_day = 100
n_smooth = 20

for col in df_all.columns:
    price = df_all[col]
    ma_period = price.rolling(n_day).mean()
    std = price.rolling(90).std()
    
    z = (price - ma_period) / std
    
    # Invert for assets where lower value = more risk-on
    if col in invert_list:
        z = -z
    
    z_scores[col] = z

# Composite Risk Regime Score
z_scores["Risk_Regime_Score"] = z_scores.median(axis=1)
z_scores["Risk_Regime_Score_Smoothed"] = z_scores["Risk_Regime_Score"].rolling(n_smooth).mean()

# Get current regime
current_score = z_scores["Risk_Regime_Score_Smoothed"].iloc[-1]
if current_score > 1:
    current_regime = "RISK-ON"
elif current_score < -1:
    current_regime = "RISK-OFF" 
else:
    current_regime = "NEUTRAL"

print(f"Current Risk Regime: {current_regime} (Score: {current_score:.2f})")

# Create enhanced figure
fig = make_subplots(
    rows=2, cols=1,
    subplot_titles=('Risk Regime Indicator', 'Individual Asset Z-Scores (Last 252 Days)'),
    vertical_spacing=0.12,
    row_heights=[0.7, 0.3]
)

# Main risk regime chart
fig.add_trace(go.Scatter(
    x=z_scores.index,
    y=z_scores["Risk_Regime_Score"],
    mode="lines",
    name="Raw Score",
    line=dict(width=1, color='lightblue'),
    opacity=0.6
), row=1, col=1)

# Smoothed regime score
fig.add_trace(go.Scatter(
    x=z_scores.index,
    y=z_scores["Risk_Regime_Score_Smoothed"],
    mode="lines",
    name="Smoothed (20d)",
    line=dict(width=3, color='darkblue')
), row=1, col=1)

# Add threshold lines to main chart
fig.add_hline(y=1, line_dash="dash", line_color="green", 
              annotation_text="Risk-On", annotation_position="top right", row=1)
fig.add_hline(y=0, line_dash="dash", line_color="gray", 
              annotation_text="Neutral", annotation_position="top right", row=1)
fig.add_hline(y=-1, line_dash="dash", line_color="red", 
              annotation_text="Risk-Off", annotation_position="bottom right", row=1)

# Individual asset z-scores (last year only for clarity)
recent_data = z_scores.iloc[-252:] if len(z_scores) > 252 else z_scores
colors = ['red', 'blue', 'green', 'orange', 'purple', 'brown', 'pink', 'gray', 'olive', 'cyan', 'magenta', 'yellow', 'lime', 'navy']
for i, col in enumerate(df_all.columns):
    fig.add_trace(go.Scatter(
        x=recent_data.index,
        y=recent_data[col],
        mode="lines",
        name=col,
        line=dict(width=1, color=colors[i % len(colors)]),
        opacity=0.7,
        showlegend=False
    ), row=2, col=1)

# Simple, clean title
title_text = "Risk Regime Dashboard"

fig.update_layout(
    title={
        'text': title_text,
        'x': 0.5,
        'xanchor': 'center',
        'font': {'size': 20}
    },
    height=800,
    template="plotly_white",
    hovermode='x unified',
    showlegend=True,
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1
    )
)

fig.update_xaxes(title_text="Date", row=2, col=1)
fig.update_yaxes(title_text="Z-Score", row=1, col=1)
fig.update_yaxes(title_text="Z-Score", row=2, col=1)

# Create config to hide plotly toolbar
config = {
    'displayModeBar': False,
    'responsive': True
}

# Save as standalone HTML file for GitHub Pages
output_filename = "index.html"
pyo.plot(fig, filename=output_filename, auto_open=False, config=config)

print(f"Chart saved as '{output_filename}'")
print("Dashboard will be available at /risk_regime/")

# Also create summary data
summary_data = {
    'current_regime': current_regime,
    'current_score': round(current_score, 3),
    'last_updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'recent_scores': z_scores["Risk_Regime_Score_Smoothed"].iloc[-30:].round(3).tolist()
}

import json
with open('data.json', 'w') as f:
    json.dump(summary_data, f, indent=2)

print("Data summary saved as 'data.json'")

"""
3-Month SOFR Futures Curve Dashboard for GitHub Actions
Pulls per-contract quotes from Yahoo Finance chart API (ticker SR3<month><YY>.CME)
No auth required. CME's own site blocks scraping — Yahoo mirrors settle prices.
"""

import os
import time
import requests
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timezone

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'reports', 'sofr-curve', 'index.html'
)

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
HEADERS = {"User-Agent": "Mozilla/5.0"}
MONTH_CODES = {'H': 3, 'M': 6, 'U': 9, 'Z': 12}  # IMM quarterly cycle
MONTH_LABEL = {'H': 'Mar', 'M': 'Jun', 'U': 'Sep', 'Z': 'Dec'}

STALE_DAYS = 5  # drop contracts whose last trade is older than this (expired/delisted)


def fetch_meta(ticker):
    url = CHART_URL.format(ticker=ticker)
    r = requests.get(url, headers=HEADERS, timeout=10)
    if r.status_code != 200:
        return None
    js = r.json()
    result = js.get("chart", {}).get("result")
    if not result:
        return None
    return result[0]["meta"]


def get_curve(start_year=25, n_years=6):
    """Query every quarterly IMM contract from start_year out n_years, keep active ones."""
    rows = []
    now = datetime.now(timezone.utc).timestamp()
    for y in range(start_year, start_year + n_years + 1):
        for code in ['H', 'M', 'U', 'Z']:
            ticker = f"SR3{code}{y}.CME"
            meta = fetch_meta(ticker)
            if not meta:
                continue
            last_trade = meta.get("regularMarketTime", 0)
            if now - last_trade > STALE_DAYS * 86400:
                continue  # expired/delisted contract, stale quote
            price = meta.get("regularMarketPrice")
            if price is None:
                continue
            rows.append({
                "ticker": ticker,
                "expiry": pd.Timestamp(year=2000 + y, month=MONTH_CODES[code], day=1),
                "label": f"{MONTH_LABEL[code]}{y}",
                "price": price,
                "rate": 100 - price,
                "prev_close": meta.get("previousClose", price),
                "day_high": meta.get("regularMarketDayHigh", price),
                "day_low": meta.get("regularMarketDayLow", price),
                "wk52_high": meta.get("fiftyTwoWeekHigh", price),
                "wk52_low": meta.get("fiftyTwoWeekLow", price),
                "volume": meta.get("regularMarketVolume", 0),
            })
            time.sleep(0.2)  # be polite
    df = pd.DataFrame(rows).sort_values("expiry").reset_index(drop=True)
    return df


def get_front_month_history(days=252):
    """Continuous front-month contract history (SR3=F) for the time-series panel."""
    url = CHART_URL.format(ticker="SR3=F") + f"?range=1y&interval=1d"
    r = requests.get(url, headers=HEADERS, timeout=10)
    js = r.json()["chart"]["result"][0]
    ts = js["timestamp"]
    closes = js["indicators"]["quote"][0]["close"]
    idx = pd.to_datetime(ts, unit="s")
    s = pd.Series(closes, index=idx).dropna()
    return (100 - s).tail(days)  # implied rate


def plot_curve(df, front_hist):
    fig = make_subplots(
        rows=2, cols=2,
        vertical_spacing=0.15,
        horizontal_spacing=0.1,
        subplot_titles=(
            'Implied SOFR Curve (Futures-Derived)',
            'Front-Month Implied Rate (1Y)',
            'Quarter-over-Quarter Spread (Priced Hikes/Cuts)',
            'Current vs 52-Week Range, by Contract'
        )
    )

    # 1. Current curve: implied rate by contract expiry
    fig.add_trace(go.Scatter(
        x=df['label'], y=df['rate'],
        mode='lines+markers+text',
        text=[f'{r:.3f}' for r in df['rate']],
        textposition='top center',
        line=dict(width=4, color='#1f77b4'),
        name='Implied Rate'
    ), row=1, col=1)

    # 2. Front-month history
    fig.add_trace(go.Scatter(
        x=front_hist.index, y=front_hist.values,
        name='Front Month', line=dict(color='#1f77b4'), opacity=0.9
    ), row=1, col=2)

    # 3. Calendar spreads (rate[n] - rate[n-1]) — negative means market pricing cuts between those quarters
    spreads = df['rate'].diff().dropna() * 100  # bps
    spread_labels = df['label'].iloc[1:]
    colors = ['#d62728' if v < 0 else '#2ca02c' for v in spreads]
    fig.add_trace(go.Bar(
        x=spread_labels, y=spreads, marker_color=colors, name='QoQ Spread'
    ), row=2, col=1)
    fig.add_hline(y=0, line_dash="dash", line_color="black", row=2, col=1)

    # 4. Current vs 52-week range
    for col, color, dash in [('wk52_low', '#aec7e8', 'dot'), ('rate', '#1f77b4', 'solid'), ('wk52_high', '#ff7f0e', 'dot')]:
        y = 100 - df[col] if col != 'rate' else df[col]
        fig.add_trace(go.Scatter(
            x=df['label'], y=y, mode='lines+markers',
            name={'wk52_low': '52W High (rate)', 'rate': 'Current', 'wk52_high': '52W Low (rate)'}[col],
            line=dict(color=color, dash=dash)
        ), row=2, col=2)

    fig.update_layout(
        height=900,
        template='plotly_white',
        title_text="3-Month SOFR Futures Curve (CME SR3)",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    fig.update_yaxes(ticksuffix="%", row=1, col=1)
    fig.update_yaxes(ticksuffix="%", row=1, col=2)
    fig.update_yaxes(ticksuffix=" bps", row=2, col=1)
    fig.update_yaxes(ticksuffix="%", row=2, col=2)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    fig.write_html(OUTPUT_PATH)
    print(f"✅ Dashboard saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    curve = get_curve()
    if curve.empty:
        raise RuntimeError("No SOFR futures data retrieved")
    hist = get_front_month_history()
    plot_curve(curve, hist)

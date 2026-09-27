"""
Fed Funds Rate: Hiking Cycles Aligned at Start
================================================
Every Fed hiking cycle since 1990, month 0 = last trough reading before the
first hike, plotted on a common "months since first hike" x-axis so cycles
can be compared on speed and magnitude regardless of calendar date.

Cycle boundaries below are historical FOMC record (fixed, won't change).
The last entry is treated as ongoing: its end date is whatever the latest
FRED data shows, with the current partial month backfilled from the daily
effective rate (DFF) since the monthly FEDFUNDS average lags ~3-4 weeks.

Required env var: FRED_API_KEY (loaded from fred_client/.env if not set).
"""

import os
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.expanduser(
    "~/claude_projects/fred_client/.env"
))
FRED_API_KEY = os.environ.get("FRED_API_KEY")

OUTPUT_PATH = os.path.expanduser(
    "~/claude_projects/boquin.github.io/reports/fed-hiking-cycles/index.html"
)

# (label, trough_month, hardcoded_end_month_or_None)
# None end = ongoing, extended dynamically to latest data.
CYCLES = [
    ("1994-95", "1994-01-01", "1995-02-01"),
    ("1997",    "1997-02-01", "1997-04-01"),
    ("1999-00", "1999-05-01", "2000-05-01"),
    ("2004-06", "2004-05-01", "2006-06-01"),
    ("2015-18", "2015-11-01", "2018-12-01"),
    ("2022-23", "2022-02-01", "2023-07-01"),
    ("2026-",   "2026-02-01", None),
]

LABELS = {
    "1994-95": "Feb 1994 – Feb 1995",
    "1997":    "Mar 1997 (single hike)",
    "1999-00": "Jun 1999 – May 2000",
    "2004-06": "Jun 2004 – Jun 2006",
    "2015-18": "Dec 2015 – Dec 2018",
    "2022-23": "Mar 2022 – Jul 2023",
    "2026-":   "Sep 2026 – ongoing",
}

COLORS = {
    "1994-95": "#2a78d6",
    "1997":    "#008300",
    "1999-00": "#eb6834",
    "2004-06": "#1baf7a",
    "2015-18": "#eda100",
    "2022-23": "#e87ba4",
    "2026-":   "#4a3aa7",
}

ORDER = ["1994-95", "1997", "1999-00", "2004-06", "2015-18", "2022-23", "2026-"]


def fetch_fred(series_id: str, freq: str, start: str) -> pd.Series:
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id, "api_key": FRED_API_KEY,
        "file_type": "json", "observation_start": start, "frequency": freq,
    }
    r = requests.Session().get(url, params=params, timeout=30)
    r.raise_for_status()
    df = pd.DataFrame(r.json()["observations"])[["date", "value"]]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna().set_index("date")["value"]


def build_series() -> dict:
    monthly = fetch_fred("FEDFUNDS", "m", "1990-01-01")
    daily = fetch_fred("DFF", "d", "2026-01-01")

    out = {}
    for label, start, end in CYCLES:
        if end is not None:
            vals = monthly.loc[start:end].tolist()
        else:
            vals = monthly.loc[start:].tolist()
            latest_daily = daily.iloc[-1]
            latest_monthly_month = monthly.loc[start:].index[-1].to_period("M")
            latest_daily_month = daily.index[-1].to_period("M")
            if latest_daily_month > latest_monthly_month:
                vals.append(float(latest_daily))
        out[label] = vals
    return out


def build_chart(series: dict) -> go.Figure:
    fig = go.Figure()
    for key in ORDER:
        vals = series[key]
        months = list(range(len(vals)))
        fig.add_trace(go.Scatter(
            x=months, y=vals, mode="lines+markers" if len(vals) <= 4 else "lines",
            name=LABELS[key],
            line=dict(color=COLORS[key], width=2.5,
                       dash="dot" if key == ORDER[-1] else "solid"),
            marker=dict(size=7),
            hovertemplate="Month %{x}<br>Fed Funds: %{y:.2f}%<extra>" + LABELS[key] + "</extra>",
        ))
        fig.add_annotation(
            x=months[-1], y=vals[-1],
            text=LABELS[key].split("–")[0].split("(")[0].strip(),
            showarrow=False, xanchor="left", xshift=6,
            font=dict(color=COLORS[key], size=11), align="left",
        )

    fig.update_layout(
        xaxis=dict(title="Months since first hike", gridcolor="#e1e0d9",
                    zeroline=False, linecolor="#c3c2b7"),
        yaxis=dict(title="Fed funds rate (%)", gridcolor="#e1e0d9",
                    zeroline=False, linecolor="#c3c2b7", ticksuffix="%"),
        plot_bgcolor="#fcfcfb", paper_bgcolor="#fcfcfb",
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", color="#0b0b0b"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=11)),
        margin=dict(r=170, t=30, l=60, b=60),
        hovermode="x unified",
    )
    return fig


def build_html(fig: go.Figure) -> str:
    today = date.today().strftime("%B %d, %Y")
    chart_div = fig.to_html(
        full_html=False, include_plotlyjs="cdn",
        config={"displayModeBar": True, "displaylogo": False},
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Fed Hiking Cycles</title>
  <style>
    body {{ margin: 0; padding: 32px 16px 48px; background: #fcfcfb; }}
    h1 {{
      text-align: center; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 26px; font-weight: 700; color: #0b0b0b; margin-bottom: 4px;
    }}
    .subtitle {{
      text-align: center; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 14px; color: #52514e; margin-bottom: 24px;
    }}
    .chart-wrap {{ max-width: 1100px; margin: 0 auto 36px; }}
    .source {{
      text-align: center; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 12px; color: #898781;
    }}
  </style>
</head>
<body>
  <h1>Fed Funds Rate: Hiking Cycles Aligned at Start</h1>
  <p class="subtitle">Every FOMC tightening cycle since 1990, month 0 = trough before first hike &nbsp;|&nbsp; Updated {today}</p>
  <div class="chart-wrap">
    {chart_div}
  </div>
  <p class="source">Source: Federal Reserve (FEDFUNDS, DFF) via FRED. Refreshed monthly.</p>
</body>
</html>"""


def main():
    print("[1/3] Fetching FRED data...")
    series = build_series()
    for k, v in series.items():
        print(f"  {k}: {len(v)} months, {v[0]:.2f}% -> {v[-1]:.2f}%")

    print("[2/3] Building chart...")
    fig = build_chart(series)

    print("[3/3] Writing HTML report...")
    html = build_html(fig)
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Done -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

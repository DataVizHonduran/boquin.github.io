"""
Weekly Crude Oil Stocks — Time Series Chart Generator
=====================================================
Fetches EIA Weekly Petroleum Status Report (U.S. total crude stocks)
and generates a single-panel PNG:
  - Line: last 252 calendar days of weekly crude stock levels
  - Grey band: 5-year seasonal high-low range (same week of year)

Required env var:
  EIA_API_KEY  — Register free at https://www.eia.gov/opendata/register.php

Run: python scripts/generate_crude_stocks_weekly.py
Output: reports/crude-stocks/Crude_Stocks_Weekly_YYYY_MM_DD.png
"""

import os
import sys
import requests
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
EIA_API_BASE = "https://api.eia.gov/v2/petroleum/stoc/wstk/data/"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "reports", "crude-stocks")

WINDOW_DAYS   = 252   # current-period line length
HISTORY_YEARS = 7     # total history to fetch (5-yr band + 2 yr buffer)


def get_api_key() -> str:
    key = os.environ.get("EIA_API_KEY", "")
    if not key:
        print(
            "WARNING: EIA_API_KEY not set. Using DEMO_KEY (heavily rate-limited).\n"
            "Register a free key at https://www.eia.gov/opendata/register.php"
        )
        return "DEMO_KEY"
    return key


def fetch_us_crude(api_key: str) -> pd.Series:
    """
    Fetch weekly U.S. total crude oil ending stocks going back HISTORY_YEARS.
    Returns a Series indexed by date, values in Million Barrels.
    """
    weeks_needed = HISTORY_YEARS * 53 + 10  # generous buffer

    params = {
        "api_key": api_key,
        "frequency": "weekly",
        "data[0]": "value",
        "facets[duoarea][]": "NUS",   # U.S. total
        "facets[product][]": "EPC0",  # Crude Oil
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": weeks_needed,
    }

    try:
        resp = requests.get(EIA_API_BASE, params=params, timeout=30)
        resp.raise_for_status()
    except requests.HTTPError as e:
        print(f"ERROR: EIA API request failed — {e}")
        sys.exit(1)
    except requests.RequestException as e:
        print(f"ERROR: Network error — {e}")
        sys.exit(1)

    data = resp.json()
    if "response" not in data:
        print(f"ERROR: Unexpected API response — {data.get('error', data)}")
        sys.exit(1)

    rows = data["response"]["data"]
    if not rows:
        print("ERROR: EIA API returned no data for U.S. crude stocks.")
        sys.exit(1)

    records = []
    for row in rows:
        try:
            val = float(row["value"]) / 1_000.0  # Thousand Bbls → MMBbls
            records.append({"date": pd.to_datetime(row["period"]), "value": val})
        except (ValueError, TypeError):
            continue

    s = (
        pd.DataFrame(records)
        .set_index("date")["value"]
        .sort_index()
    )
    print(f"  Fetched {len(s)} weeks of data ({s.index[0].date()} – {s.index[-1].date()})")
    return s


def check_freshness(s: pd.Series) -> None:
    latest = s.index.max()
    age = (pd.Timestamp(date.today()) - latest).days
    if age > 8:
        print(
            f"EIA update not yet available. Most recent data: {latest.date()} "
            f"({age} days ago). Check back after Wednesday 10:30 AM ET."
        )
        sys.exit(0)
    print(f"  Most recent EIA data: week ending {latest.date()}")


def build_seasonal_band(s: pd.Series, current_window: pd.Series) -> tuple:
    """
    For each date in current_window, find the same ISO week across the
    5 years prior and return (lo, hi) arrays aligned to current_window.index.
    """
    lo_vals, hi_vals = [], []

    for dt in current_window.index:
        iso_week = dt.isocalendar()[1]
        iso_year = dt.isocalendar()[0]

        # Collect values from the same ISO week in years [y-1 .. y-5]
        bucket = []
        for offset in range(1, 6):
            target_year = iso_year - offset
            mask = (
                s.index.map(lambda d: d.isocalendar()[1]) == iso_week
            ) & (
                s.index.map(lambda d: d.isocalendar()[0]) == target_year
            )
            vals = s[mask]
            if not vals.empty:
                bucket.append(float(vals.iloc[0]))

        if bucket:
            lo_vals.append(min(bucket))
            hi_vals.append(max(bucket))
        else:
            lo_vals.append(np.nan)
            hi_vals.append(np.nan)

    return np.array(lo_vals), np.array(hi_vals)


def build_chart(s: pd.Series) -> plt.Figure:
    cutoff = s.index.max() - pd.Timedelta(days=WINDOW_DAYS)
    current = s[s.index >= cutoff]

    lo, hi = build_seasonal_band(s, current)

    latest_val   = current.iloc[-1]
    latest_date  = current.index[-1]
    lo_latest    = lo[-1] if not np.isnan(lo[-1]) else None
    hi_latest    = hi[-1] if not np.isnan(hi[-1]) else None

    # --- figure ---
    fig, ax = plt.subplots(figsize=(14, 6), facecolor="#0e1117")
    ax.set_facecolor("#0e1117")

    # 5-year hi-lo band
    ax.fill_between(
        current.index, lo, hi,
        color="#475569", alpha=0.35, label="5-Year Range (Hi–Lo)",
        zorder=2,
    )

    # Current line
    ax.plot(
        current.index, current.values,
        color="#3b82f6", linewidth=2.2, label="U.S. Crude Stocks", zorder=4,
    )

    # Latest dot
    ax.scatter([latest_date], [latest_val], color="#3b82f6", s=55, zorder=5)

    # Annotation: current value vs range
    pct_str = ""
    if lo_latest and hi_latest and hi_latest > lo_latest:
        pct = (latest_val - lo_latest) / (hi_latest - lo_latest) * 100
        pct_str = f"  ({pct:.0f}th pct of 5-yr range)"

    ax.annotate(
        f"{latest_val:.1f} MMBbl{pct_str}",
        xy=(latest_date, latest_val),
        xytext=(10, 8),
        textcoords="offset points",
        color="#93c5fd",
        fontsize=9,
        fontweight="bold",
    )

    # Axes formatting
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}"))
    ax.set_ylabel("Million Barrels", color="#94a3b8", fontsize=10)
    ax.tick_params(colors="#64748b", labelsize=9)

    for spine in ax.spines.values():
        spine.set_color("#1e293b")

    ax.yaxis.grid(True, color="#1e293b", linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)
    ax.set_xlim(current.index[0], current.index[-1] + pd.Timedelta(days=7))

    ax.set_title(
        f"U.S. Crude Oil Stocks — Last 252 Days with 5-Year Seasonal Range\n"
        f"Week Ending {latest_date.strftime('%B %d, %Y')}",
        color="#f1f5f9", fontsize=13, fontweight="bold", pad=14,
    )

    legend = ax.legend(
        facecolor="#161b22", edgecolor="#334155",
        labelcolor="#e2e8f0", fontsize=9, loc="upper left",
    )

    ax.text(
        0.99, 0.02,
        "Source: EIA Weekly Petroleum Status Report",
        transform=ax.transAxes,
        ha="right", va="bottom",
        color="#475569", fontsize=8,
    )

    plt.tight_layout()
    return fig


def generate_index_html(filename: str, latest_date_str: str, output_dir: str) -> None:
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>U.S. Crude Oil Stocks — {latest_date_str}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0e1117;
      color: #e2e8f0;
      font-family: 'Inter', Arial, sans-serif;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 2rem 1rem;
      min-height: 100vh;
    }}
    header {{ text-align: center; margin-bottom: 1.5rem; }}
    header h1 {{ font-size: 1.5rem; font-weight: 700; color: #f1f5f9; }}
    header p {{ color: #94a3b8; font-size: 0.9rem; margin-top: 0.4rem; }}
    .chart-wrapper {{
      width: 100%; max-width: 1200px;
      background: #161b22;
      border: 1px solid #1e293b;
      border-radius: 8px;
      padding: 1rem;
    }}
    .chart-wrapper img {{ width: 100%; height: auto; display: block; border-radius: 4px; }}
    footer {{
      margin-top: 1.5rem; font-size: 0.8rem;
      color: #475569; text-align: center;
    }}
    footer a {{ color: #3b82f6; text-decoration: none; }}
    footer a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <header>
    <h1>&#x1F6E2;&#xFE0F; U.S. Crude Oil Stocks</h1>
    <p>Last 252 days with 5-year seasonal range &mdash; week ending {latest_date_str}</p>
  </header>
  <div class="chart-wrapper">
    <img src="{filename}" alt="U.S. Crude Oil Stocks {latest_date_str}" />
  </div>
  <footer>
    Source: <a href="https://www.eia.gov/petroleum/supply/weekly/" target="_blank">EIA Weekly Petroleum Status Report</a>
    &nbsp;&bull;&nbsp;
    <a href="https://github.com/DataVizHonduran/boquin.github.io/blob/main/scripts/generate_crude_stocks_weekly.py" target="_blank">Source Code</a>
    &nbsp;&bull;&nbsp;
    <a href="https://boquin.xyz" target="_blank">boquin.xyz</a>
  </footer>
</body>
</html>"""
    index_path = os.path.join(output_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved: {index_path}")


def main():
    api_key = get_api_key()

    print("Fetching U.S. crude oil stock data from EIA API...")
    s = fetch_us_crude(api_key)

    check_freshness(s)

    print("Building chart...")
    fig = build_chart(s)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    today_str = date.today().strftime("%Y_%m_%d")
    filename = f"Crude_Stocks_Weekly_{today_str}.png"
    output_path = os.path.join(OUTPUT_DIR, filename)
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Saved: {output_path}")

    latest_date_str = s.index.max().strftime("%Y-%m-%d")
    generate_index_html(filename, latest_date_str, OUTPUT_DIR)


if __name__ == "__main__":
    main()

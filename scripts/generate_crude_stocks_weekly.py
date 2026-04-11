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

    Uses the known WCRSTUS1 series ID to guarantee we only get the U.S.
    total series — avoids EIA API bracket-encoding quirks with facet filters.
    """
    weeks_needed = HISTORY_YEARS * 53 + 10  # generous buffer

    # Build query string manually so bracket params encode correctly
    qs = (
        f"api_key={api_key}"
        f"&frequency=weekly"
        f"&data[0]=value"
        f"&facets[series][]=WCRSTUS1"   # U.S. total crude stocks — single known series
        f"&sort[0][column]=period"
        f"&sort[0][direction]=desc"
        f"&length={weeks_needed}"
    )
    url = f"{EIA_API_BASE}?{qs}"

    try:
        resp = requests.get(url, timeout=30)
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
        if row.get("duoarea") != "NUS":   # safety filter: U.S. total only
            continue
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

    x_dates = current.index
    x_num   = mdates.date2num(x_dates.to_pydatetime())

    # ------------------------------------------------------------------ figure
    fig, ax = plt.subplots(figsize=(10, 5.5), facecolor="white")
    ax.set_facecolor("white")

    # ---- gradient grey band (dark at top → white at bottom) ---------------
    # Achieved by stacking N thin fill_between strips with decreasing alpha.
    N = 80
    for i in range(N):
        frac_lo = i / N
        frac_hi = (i + 1) / N
        band_lo = lo + frac_lo * (hi - lo)
        band_hi = lo + frac_hi * (hi - lo)
        alpha   = 0.55 * (1 - frac_lo) ** 0.6   # dark at top, fades down
        ax.fill_between(x_dates, band_lo, band_hi,
                        color="#606060", alpha=alpha, linewidth=0, zorder=2)

    # ---- blue weekly line -------------------------------------------------
    ax.plot(x_dates, current.values,
            color="#2196F3", linewidth=1.6, label="Weekly", zorder=4)

    # ---- axes style -------------------------------------------------------
    ax.set_xlim(x_dates[0], x_dates[-1])

    # y-axis: label on top-left, no rotation
    y_min = min(np.nanmin(lo), current.min())
    y_max = max(np.nanmax(hi), current.max())
    pad   = (y_max - y_min) * 0.08
    ax.set_ylim(y_min - pad, y_max + pad * 1.5)

    ax.yaxis.set_major_locator(mticker.MultipleLocator(20))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}"))
    ax.tick_params(axis="y", labelsize=9, length=0, colors="#333333")
    ax.tick_params(axis="x", labelsize=9, length=4, colors="#333333")

    # "Million Barrels" above y-axis, flush left
    ax.text(-0.01, 1.01, "Million Barrels", transform=ax.transAxes,
            ha="left", va="bottom", fontsize=9, color="#333333")

    # horizontal grid lines only
    ax.yaxis.grid(True, color="#cccccc", linewidth=0.6, zorder=0)
    ax.xaxis.grid(False)
    ax.set_axisbelow(True)

    # spines: keep only bottom and left, light grey
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#cccccc")
    ax.spines["bottom"].set_color("#333333")

    # ---- x-axis: MM/DD ticks + year band labels below --------------------
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))

    # Draw year labels below the tick labels (EIA style)
    # Find year boundaries within the plotted range
    fig.canvas.draw()          # needed to get tick positions
    years_in_range = sorted(set(x_dates.year))
    ax_xmin, ax_xmax = mdates.date2num(x_dates[0].to_pydatetime()), \
                       mdates.date2num(x_dates[-1].to_pydatetime())

    trans = ax.get_xaxis_transform()   # blended: data x, axes y
    for yr in years_in_range:
        yr_start = mdates.date2num(pd.Timestamp(f"{yr}-01-01").to_pydatetime())
        yr_end   = mdates.date2num(pd.Timestamp(f"{yr}-12-31").to_pydatetime())
        x_left   = max(yr_start, ax_xmin)
        x_right  = min(yr_end,   ax_xmax)
        if x_right <= x_left:
            continue
        x_mid_num  = (x_left + x_right) / 2
        x_mid_frac = (x_mid_num - ax_xmin) / (ax_xmax - ax_xmin)
        # horizontal line using axhline-equivalent in blended coords
        import matplotlib.lines as mlines
        line = mlines.Line2D([x_left, x_right], [-0.08, -0.08],
                             transform=trans, color="#333333",
                             linewidth=0.8, clip_on=False)
        ax.add_line(line)
        ax.text(x_mid_frac, -0.13, str(yr),
                transform=ax.transAxes,
                ha="center", va="top", fontsize=9, color="#333333")

    # ---- title ------------------------------------------------------------
    ax.set_title("U.S. Crude Oil Stocks", fontsize=12, color="#222222",
                 fontweight="normal", pad=10)

    # ---- legend below chart -----------------------------------------------
    from matplotlib.patches import Patch
    from matplotlib.lines  import Line2D
    legend_elements = [
        Patch(facecolor="#888888", edgecolor="none", label="5-yr Range"),
        Line2D([0], [0], color="#2196F3", linewidth=1.6, label="Weekly"),
    ]
    ax.legend(handles=legend_elements, loc="lower center",
              bbox_to_anchor=(0.5, -0.28), ncol=2,
              frameon=False, fontsize=9, handlelength=1.5,
              handleheight=0.9, columnspacing=1.0)

    plt.tight_layout(rect=[0, 0.05, 1, 1])
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
      background: #f5f5f5;
      color: #222;
      font-family: Arial, sans-serif;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 2rem 1rem;
      min-height: 100vh;
    }}
    header {{ text-align: center; margin-bottom: 1.5rem; }}
    header h1 {{ font-size: 1.4rem; font-weight: bold; color: #222; }}
    header p {{ color: #555; font-size: 0.85rem; margin-top: 0.4rem; }}
    .chart-wrapper {{
      width: 100%; max-width: 900px;
      background: white;
      border: 1px solid #ddd;
      border-radius: 4px;
      padding: 1rem;
    }}
    .chart-wrapper img {{ width: 100%; height: auto; display: block; }}
    footer {{
      margin-top: 1.5rem; font-size: 0.8rem;
      color: #888; text-align: center;
    }}
    footer a {{ color: #2196F3; text-decoration: none; }}
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

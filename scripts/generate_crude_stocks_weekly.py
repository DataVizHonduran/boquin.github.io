"""
Weekly Crude Oil Stocks by PAD District — Chart Generator
=========================================================
Fetches EIA Weekly Petroleum Status Report data via the EIA Open Data API v2
and generates a two-panel PNG visualization:
  - Chart A: Current vs. Prior-Year stocks by PADD (grouped bar)
  - Chart B: Week-over-Week change by PADD (diverging bar)

Required env var:
  EIA_API_KEY  — Register free at https://www.eia.gov/opendata/register.php

Run: python scripts/generate_crude_stocks_weekly.py
Output: reports/crude-stocks/Crude_Stocks_Weekly_YYYY_MM_DD.png
"""

import os
import sys
import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from datetime import date, datetime, timedelta

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
EIA_API_BASE = "https://api.eia.gov/v2/petroleum/stoc/wstk/data/"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "reports", "crude-stocks")

PADD_ORDER = [
    "PADD 1",
    "PADD 2",
    "Cushing, OK",
    "PADD 3",
    "PADD 4",
    "PADD 5",
]

AREA_LABELS = {
    "PADD 1": "PADD 1\n(East Coast)",
    "PADD 2": "PADD 2\n(Midwest)",
    "Cushing, OK": "Cushing,\nOK",
    "PADD 3": "PADD 3\n(Gulf Coast)",
    "PADD 4": "PADD 4\n(Rocky Mtn)",
    "PADD 5": "PADD 5\n(West Coast)",
}

# EIA area-name values to canonical key (substring match, case-insensitive)
AREA_NAME_MAP = {
    "east coast (padd 1)": "PADD 1",
    "padd 1":              "PADD 1",
    "midwest (padd 2)":    "PADD 2",
    "padd 2":              "PADD 2",
    "cushing":             "Cushing, OK",
    "gulf coast (padd 3)": "PADD 3",
    "padd 3":              "PADD 3",
    "rocky mountain":      "PADD 4",
    "padd 4":              "PADD 4",
    "west coast (padd 5)": "PADD 5",
    "padd 5":              "PADD 5",
}


def get_api_key() -> str:
    key = os.environ.get("EIA_API_KEY", "")
    if not key:
        print(
            "WARNING: EIA_API_KEY not set. Using DEMO_KEY (heavily rate-limited).\n"
            "Register a free key at https://www.eia.gov/opendata/register.php"
        )
        return "DEMO_KEY"
    return key


def _call_api(params: dict) -> list:
    """Make one EIA API call and return the data rows, or exit on error."""
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
    return data["response"]["data"]


def fetch_crude_stocks(api_key: str) -> pd.DataFrame:
    """
    Fetch ~60 weeks of weekly crude oil ending stocks for all PADD areas + Cushing.
    Uses two queries:
      1. PADD 1–5 targeted by duoarea facets (R10–R50)
      2. Broad query to discover Cushing's duoarea code by area-name match
    Returns a DataFrame with columns: period, area_key, value_mmbbl
    """
    base_params = {
        "api_key": api_key,
        "frequency": "weekly",
        "data[0]": "value",
        "facets[product][]": "EPC0",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
    }

    # --- Query 1: PADD 1–5 via duoarea facets (clean, targeted) ---
    padd_params = {
        **base_params,
        "facets[duoarea][]": ["R10", "R20", "R30", "R40", "R50"],
        "length": 5000,
    }
    padd_rows = _call_api(padd_params)

    # --- Query 2: Discover Cushing (unknown duoarea code) ---
    # Fetch a broad recent window and look for any area-name containing "cushing"
    cushing_params = {
        **base_params,
        "length": 5000,
    }
    all_rows = _call_api(cushing_params)

    # Debug: show all unique area-names so Cushing's label is visible in logs
    unique_areas = sorted({r.get("area-name", "") for r in all_rows})
    print(f"  Available EIA area-names: {unique_areas}")

    combined_rows = padd_rows + all_rows

    if not combined_rows:
        print("ERROR: EIA API returned no data.")
        sys.exit(1)

    records = []
    seen = set()  # deduplicate (period, area_key) pairs
    for row in combined_rows:
        area_raw = row.get("area-name", "").strip().lower()
        area_key = None
        for pattern, key in AREA_NAME_MAP.items():
            if pattern in area_raw:
                area_key = key
                break
        if area_key is None:
            continue

        try:
            value_mmbbl = float(row["value"]) / 1_000.0
        except (ValueError, TypeError):
            continue

        dedup_key = (row["period"], area_key)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        records.append(
            {
                "period": row["period"],
                "area_key": area_key,
                "value_mmbbl": value_mmbbl,
            }
        )

    df = pd.DataFrame(records)
    if df.empty:
        print("ERROR: No PADD crude stock rows found in API response.")
        sys.exit(1)

    df["period"] = pd.to_datetime(df["period"])
    df = df.sort_values("period", ascending=False).reset_index(drop=True)
    return df


def check_freshness(df: pd.DataFrame) -> str:
    """
    Return the most recent data date as a string, or exit if stale.
    'Stale' = latest data point is older than 8 days (EIA publishes every Wednesday).
    """
    latest_date = df["period"].max()
    today = pd.Timestamp(date.today())
    age_days = (today - latest_date).days

    if age_days > 8:
        week_str = latest_date.strftime("%Y-%m-%d")
        print(
            f"EIA update not yet available. Most recent data: week ending {week_str} "
            f"({age_days} days ago). Check back after Wednesday 10:30 AM ET."
        )
        sys.exit(0)

    return latest_date.strftime("%Y-%m-%d")


def build_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each PADD area, extract:
      current   — most recent week
      previous  — one week prior
      prior_year — same week approximately one year ago (nearest available)
    Returns a DataFrame indexed by PADD_ORDER.
    """
    latest_date = df["period"].max()
    prev_date = latest_date - pd.Timedelta(weeks=1)
    py_target = latest_date - pd.Timedelta(weeks=52)

    summary = []
    for area in PADD_ORDER:
        adf = df[df["area_key"] == area].set_index("period")["value_mmbbl"]

        def nearest(target):
            # Pick row closest to target within ±14 days
            raw_deltas = adf.index - target
            deltas = pd.Series(raw_deltas.map(abs), index=adf.index)
            mask = deltas <= pd.Timedelta(days=14)
            if not mask.any():
                return float("nan")
            closest_label = deltas[mask].idxmin()
            return float(adf.loc[closest_label])

        current = nearest(latest_date)
        previous = nearest(prev_date)
        prior_year = nearest(py_target)

        if current != current:  # NaN check
            print(f"WARNING: No current data found for {area}, skipping.")
            continue

        summary.append(
            {
                "area": area,
                "label": AREA_LABELS[area],
                "current": current,
                "previous": previous,
                "prior_year": prior_year,
                "wow_change": current - previous,
            }
        )

    return pd.DataFrame(summary)


def build_chart(summary: pd.DataFrame, latest_date_str: str) -> plt.Figure:
    """Build and return a two-panel matplotlib figure."""
    fig, (ax1, ax2) = plt.subplots(
        1, 2,
        figsize=(16, 7),
        facecolor="#0e1117",
    )
    fig.patch.set_facecolor("#0e1117")

    labels = summary["label"].tolist()
    x = range(len(labels))
    bar_w = 0.35

    # ------------------------------------------------------------------
    # Chart A — Current vs. Prior Year grouped bar
    # ------------------------------------------------------------------
    ax1.set_facecolor("#161b22")
    bars_curr = ax1.bar(
        [i - bar_w / 2 for i in x],
        summary["current"],
        width=bar_w,
        label="Current Week",
        color="#3b82f6",
        zorder=3,
    )
    bars_py = ax1.bar(
        [i + bar_w / 2 for i in x],
        summary["prior_year"],
        width=bar_w,
        label="Prior Year",
        color="#94a3b8",
        zorder=3,
    )

    # Value labels on bars
    for bar in bars_curr:
        h = bar.get_height()
        if h == h:  # not NaN
            ax1.text(
                bar.get_x() + bar.get_width() / 2,
                h + 0.3,
                f"{h:.1f}",
                ha="center", va="bottom",
                fontsize=7.5, color="#e2e8f0",
            )
    for bar in bars_py:
        h = bar.get_height()
        if h == h:
            ax1.text(
                bar.get_x() + bar.get_width() / 2,
                h + 0.3,
                f"{h:.1f}",
                ha="center", va="bottom",
                fontsize=7.5, color="#94a3b8",
            )

    ax1.set_xticks(list(x))
    ax1.set_xticklabels(labels, color="#cbd5e1", fontsize=9)
    ax1.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))
    ax1.set_ylabel("Million Barrels", color="#cbd5e1", fontsize=10)
    ax1.set_title(
        f"U.S. Crude Oil Stocks by PADD: Current vs. Prior Year\n"
        f"Week Ending {latest_date_str}",
        color="#f1f5f9", fontsize=12, fontweight="bold", pad=12,
    )
    ax1.tick_params(colors="#cbd5e1")
    ax1.spines["bottom"].set_color("#334155")
    ax1.spines["left"].set_color("#334155")
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.yaxis.grid(True, color="#1e293b", linewidth=0.7, zorder=0)
    ax1.set_axisbelow(True)
    ax1.legend(
        facecolor="#1e293b", edgecolor="#334155", labelcolor="#e2e8f0",
        fontsize=9, loc="upper right",
    )

    # ------------------------------------------------------------------
    # Chart B — Week-over-Week diverging bar
    # ------------------------------------------------------------------
    ax2.set_facecolor("#161b22")
    wow = summary["wow_change"].tolist()
    colors = ["#22c55e" if v >= 0 else "#ef4444" for v in wow]

    bars_wow = ax2.bar(x, wow, width=0.55, color=colors, zorder=3)

    for bar, val in zip(bars_wow, wow):
        if val != val:
            continue
        offset = 0.08 if val >= 0 else -0.12
        ax2.text(
            bar.get_x() + bar.get_width() / 2,
            val + offset,
            f"{val:+.2f}",
            ha="center",
            va="bottom" if val >= 0 else "top",
            fontsize=8, color="#f1f5f9", fontweight="bold",
        )

    ax2.axhline(0, color="#475569", linewidth=1.2, zorder=2)
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(labels, color="#cbd5e1", fontsize=9)
    ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter("%+.1f"))
    ax2.set_ylabel("Change (Million Barrels)", color="#cbd5e1", fontsize=10)
    ax2.set_title(
        "Week-over-Week Change by PADD\n(Build = Green  |  Draw = Red)",
        color="#f1f5f9", fontsize=12, fontweight="bold", pad=12,
    )
    ax2.tick_params(colors="#cbd5e1")
    ax2.spines["bottom"].set_color("#334155")
    ax2.spines["left"].set_color("#334155")
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    ax2.yaxis.grid(True, color="#1e293b", linewidth=0.7, zorder=0)
    ax2.set_axisbelow(True)

    fig.suptitle(
        "EIA Weekly Petroleum Status Report — Crude Oil Stocks",
        color="#94a3b8", fontsize=10, y=0.02,
    )
    plt.tight_layout(rect=[0, 0.04, 1, 1])
    return fig


def generate_index_html(filename: str, latest_date_str: str, output_dir: str) -> None:
    """Write an index.html that displays the current week's PNG."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Weekly Crude Oil Stocks by PADD — {latest_date_str}</title>
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
    header {{
      text-align: center;
      margin-bottom: 1.5rem;
    }}
    header h1 {{
      font-size: 1.5rem;
      font-weight: 700;
      color: #f1f5f9;
    }}
    header p {{
      color: #94a3b8;
      font-size: 0.9rem;
      margin-top: 0.4rem;
    }}
    .chart-wrapper {{
      width: 100%;
      max-width: 1200px;
      background: #161b22;
      border: 1px solid #1e293b;
      border-radius: 8px;
      padding: 1rem;
    }}
    .chart-wrapper img {{
      width: 100%;
      height: auto;
      display: block;
      border-radius: 4px;
    }}
    footer {{
      margin-top: 1.5rem;
      font-size: 0.8rem;
      color: #475569;
      text-align: center;
    }}
    footer a {{ color: #3b82f6; text-decoration: none; }}
    footer a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <header>
    <h1>&#x1F6E2;&#xFE0F; U.S. Crude Oil Stocks by PAD District</h1>
    <p>EIA Weekly Petroleum Status Report &mdash; week ending {latest_date_str}</p>
  </header>
  <div class="chart-wrapper">
    <img src="{filename}" alt="Crude Oil Stocks by PADD {latest_date_str}" />
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

    print("Fetching crude oil stock data from EIA API...")
    df = fetch_crude_stocks(api_key)

    latest_date_str = check_freshness(df)
    print(f"Most recent EIA data: week ending {latest_date_str}")

    summary = build_summary(df)
    if summary.empty:
        print("ERROR: Could not build summary table — no matching PADD rows.")
        sys.exit(1)

    print("Building charts...")
    fig = build_chart(summary, latest_date_str)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    today_str = date.today().strftime("%Y_%m_%d")
    filename = f"Crude_Stocks_Weekly_{today_str}.png"
    output_path = os.path.join(OUTPUT_DIR, filename)
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Saved: {output_path}")

    generate_index_html(filename, latest_date_str, OUTPUT_DIR)


if __name__ == "__main__":
    main()

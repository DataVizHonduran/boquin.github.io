"""
TSA Checkpoint Throughput Tracker
Scrapes TSA year pages via Playwright (bypasses Akamai).
Data is embedded as an HTML table — no Excel needed.
Chart: 2026 YTD blue line | 2021-2025 min/max grey band | 2025 dotted reference
"""

import json
import pathlib
import sys
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "reports" / "tsa-tracker"
OUTPUT_FILE = OUTPUT_DIR / "index.html"
CACHE_FILE = OUTPUT_DIR / "historical.json"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://www.tsa.gov/travel/passenger-volumes"
HIST_YEARS = [2021, 2022, 2023, 2024, 2025]
CURR_YEAR = 2026

MONTH_TICKS = {
    1: "Jan 1", 32: "Feb 1", 60: "Mar 1", 91: "Apr 1",
    121: "May 1", 152: "Jun 1", 182: "Jul 1", 213: "Aug 1",
    244: "Sep 1", 274: "Oct 1", 305: "Nov 1", 335: "Dec 1",
}


def scrape_year(page, year: int) -> list[dict]:
    url = BASE_URL if year == CURR_YEAR else f"{BASE_URL}/{year}"
    print(f"  Fetching {year} from {url}...")
    page.goto(url, wait_until="networkidle", timeout=60000)
    rows = page.locator("table tr").all()
    records = []
    for row in rows[1:]:  # skip header row
        cells = row.locator("td").all()
        if len(cells) < 2:
            continue
        date_str = cells[0].inner_text().strip()
        num_str = cells[1].inner_text().strip().replace(",", "").replace(" ", "")
        try:
            dt = pd.to_datetime(date_str)
            travelers = int(num_str)
            if travelers <= 0:
                continue
            records.append({
                "date": dt.strftime("%Y-%m-%d"),
                "day_of_year": dt.timetuple().tm_yday,
                "year": year,
                "travelers": travelers,
            })
        except (ValueError, TypeError):
            continue
    print(f"    -> {len(records)} records")
    return records


def load_all_data() -> pd.DataFrame:
    records = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Always fetch current year
        curr_records = scrape_year(page, CURR_YEAR)

        # Fetch historical years — use cache if available
        if CACHE_FILE.exists():
            print("Loading historical data from cache...")
            hist_records = json.loads(CACHE_FILE.read_text())
        else:
            print("No cache — fetching historical years...")
            hist_records = []
            for y in HIST_YEARS:
                hist_records.extend(scrape_year(page, y))
            CACHE_FILE.write_text(json.dumps(hist_records))
            print(f"Cached {len(hist_records)} historical records")

        browser.close()
        records = hist_records + curr_records

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["year", "day_of_year"]).reset_index(drop=True)
    return df


def build_chart(df: pd.DataFrame) -> go.Figure:
    hist = (
        df[df["year"].isin(HIST_YEARS)]
        .groupby("day_of_year")["travelers"]
        .agg(low="min", high="max")
        .reset_index()
        .sort_values("day_of_year")
    )
    yr2025 = df[df["year"] == 2025].sort_values("day_of_year")
    curr = df[df["year"] == CURR_YEAR].sort_values("day_of_year")

    last_updated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    last_data = curr["date"].max().strftime("%b %-d, %Y") if not curr.empty else "N/A"

    fig = go.Figure()

    # Grey band — 2021–2025 min/max
    fig.add_trace(go.Scatter(
        x=hist["day_of_year"],
        y=hist["high"],
        mode="lines",
        line=dict(width=0),
        showlegend=False,
        hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=hist["day_of_year"],
        y=hist["low"],
        mode="lines",
        line=dict(width=0),
        fill="tonexty",
        fillcolor="rgba(160,160,160,0.25)",
        name="2021–2025 Range",
        hovertemplate="Day %{x}<br>%{y:,.0f}<extra>2021–2025 Range</extra>",
    ))

    # 2025 dotted reference line
    if not yr2025.empty:
        fig.add_trace(go.Scatter(
            x=yr2025["day_of_year"],
            y=yr2025["travelers"],
            mode="lines",
            line=dict(color="rgba(110,110,110,0.55)", width=1.2, dash="dot"),
            name="2025",
            hovertemplate="Day %{x}<br>%{y:,.0f}<extra>2025</extra>",
        ))

    # 2026 YTD line
    if not curr.empty:
        fig.add_trace(go.Scatter(
            x=curr["day_of_year"],
            y=curr["travelers"],
            mode="lines",
            line=dict(color="#2563EB", width=2.5),
            name="2026 YTD",
            hovertemplate="Day %{x}<br>%{y:,.0f}<extra>2026</extra>",
        ))

    fig.update_layout(
        title=dict(
            text="TSA Checkpoint Throughput",
            font=dict(size=22, color="#111"),
            x=0.5,
        ),
        annotations=[dict(
            text=f"2026 YTD (blue) vs. 2021–2025 min/max range (grey) | Latest: {last_data} | Updated: {last_updated}",
            xref="paper", yref="paper",
            x=0.5, y=1.055,
            showarrow=False,
            font=dict(size=12, color="#555"),
            xanchor="center",
        )],
        xaxis=dict(
            title="",
            tickvals=list(MONTH_TICKS.keys()),
            ticktext=list(MONTH_TICKS.values()),
            range=[1, 366],
            showgrid=True,
            gridcolor="rgba(200,200,200,0.4)",
            tickfont=dict(size=11),
        ),
        yaxis=dict(
            title="Daily Travelers",
            tickformat=",",
            showgrid=True,
            gridcolor="rgba(200,200,200,0.4)",
        ),
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.06,
            xanchor="right",
            x=1,
            font=dict(size=12),
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(t=110, b=50, l=90, r=20),
        height=560,
    )
    return fig


def main():
    print("Loading TSA data...")
    df = load_all_data()
    print(f"Total records: {len(df)} | Years: {sorted(df['year'].unique())}")

    print("Building chart...")
    fig = build_chart(df)
    fig.write_html(
        OUTPUT_FILE,
        include_plotlyjs="cdn",
        full_html=True,
        config={"displayModeBar": True, "responsive": True},
    )
    print(f"Written: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

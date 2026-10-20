"""
generate_oecd_inventory_brent_timeseries.py — OECD Inventory vs Brent, time series view
Same EIA STEO regression as generate_oecd_inventory_brent_scatter.py (brent ~ inventory, OLS)
but plotted as a monthly line chart:
  - Actual Brent price
  - Regression-predicted Brent price (fitted value from that month's inventory level)
  - Residual (actual - predicted), on a secondary axis

Required env var:
  EIA_API_KEY  — Register free at https://www.eia.gov/opendata/register.php

Run: python scripts/generate_oecd_inventory_brent_timeseries.py
Output: reports/oecd-inventory-brent-timeseries/index.html
"""

import os
import requests
import numpy as np
import pandas as pd
import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
EIA_API_BASE = "https://api.eia.gov/v2/steo/data/"
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT    = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR   = os.path.join(REPO_ROOT, "reports", "oecd-inventory-brent-timeseries")
OUTPUT_PATH  = os.path.join(OUTPUT_DIR, "index.html")

INVENTORY_SERIES = "PASC_OECD_T3"   # OECD commercial crude + other liquids inventory, mn bbl
BRENT_SERIES     = "BREPUUS"        # Brent crude oil spot price, $/bbl

START_YEAR = 2010

COLORS = {
    "actual":    "#1f77b4",
    "predicted": "#a8325e",
    "residual":  "#888888",
}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def get_api_key() -> str:
    key = os.environ.get("EIA_API_KEY", "")
    if not key:
        print("WARNING: EIA_API_KEY not set. Using DEMO_KEY (heavily rate-limited).")
        return "DEMO_KEY"
    return key


def fetch_steo_series(api_key: str, series_id: str) -> pd.Series:
    resp = requests.get(EIA_API_BASE, params={
        "api_key": api_key,
        "frequency": "monthly",
        "data[0]": "value",
        "facets[seriesId][]": series_id,
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "length": 5000,
    }, timeout=30)
    resp.raise_for_status()
    rows = resp.json()["response"]["data"]
    s = pd.Series(
        {pd.to_datetime(r["period"]): float(r["value"]) for r in rows if r.get("value") not in (None, "")}
    ).sort_index()
    s = s[~s.index.duplicated()]
    return s


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------
def build_figure(df: pd.DataFrame) -> tuple[go.Figure, str, float]:
    slope, intercept = np.polyfit(df["inventory"], df["brent"], 1)
    df["predicted"] = slope * df["inventory"] + intercept
    df["residual"] = df["brent"] - df["predicted"]

    ss_res = (df["residual"] ** 2).sum()
    ss_tot = ((df["brent"] - df["brent"].mean()) ** 2).sum()
    r_squared = 1 - ss_res / ss_tot
    per_100mn = -100 * slope

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df.index, y=df["brent"], mode="lines", name="Actual Brent",
        line=dict(color=COLORS["actual"], width=2),
        hovertemplate="%{x|%b %Y}<br>Actual: $%{y:.1f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df.index, y=df["predicted"], mode="lines", name="Predicted Brent (inventory regression)",
        line=dict(color=COLORS["predicted"], width=2, dash="dash"),
        hovertemplate="%{x|%b %Y}<br>Predicted: $%{y:.1f}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=df.index, y=df["residual"], name="Residual (actual − predicted)",
        marker=dict(color=COLORS["residual"]),
        opacity=0.5, yaxis="y2",
        hovertemplate="%{x|%b %Y}<br>Residual: $%{y:.1f}<extra></extra>",
    ))

    fig.update_layout(
        title="Actual vs. inventory-predicted Brent, and the residual"
              "<br><sup>Monthly average Brent crude vs. OLS fit on OECD commercial crude oil "
              f"inventories, since {START_YEAR} &middot; R&sup2; = {r_squared:.2f}</sup>",
        xaxis_title="Month",
        yaxis=dict(title="$ per barrel"),
        yaxis2=dict(title="Residual ($/bbl)", overlaying="y", side="right",
                     showgrid=False, zeroline=True, zerolinecolor="#999", zerolinewidth=1),
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    bgcolor="rgba(250,246,241,0.7)"),
        width=1000, height=750,
        plot_bgcolor="#faf6f1", paper_bgcolor="#faf6f1",
        margin=dict(t=100),
        hovermode="x unified",
    )

    latest = df.iloc[-1]
    footnote = (
        f"<b>Rule of thumb:</b> every 100 mn barrel draw in OECD commercial crude inventories &asymp; "
        f"+${per_100mn:.1f}/bbl on Brent (and symmetrically, a 100 mn barrel build &asymp; -${per_100mn:.1f}/bbl). "
        f"Fit: y = {intercept:,.1f} + ({slope:.4f})&middot;x, R&sup2; = {r_squared:.2f}.<br>"
        f"<b>Latest residual:</b> {latest.name.strftime('%b %Y')} actual Brent ${latest['brent']:.1f} vs. "
        f"predicted ${latest['predicted']:.1f} &mdash; a ${latest['residual']:+.1f}/bbl residual, "
        f"{'above' if latest['residual'] > 0 else 'below'} what the inventory relationship alone implies "
        f"(e.g. geopolitical risk premium or demand/positioning effects not captured by inventories)."
    )
    return fig, footnote, per_100mn


def write_page(fig: go.Figure, footnote: str, latest_label: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    chart_html = fig.to_html(include_plotlyjs="cdn", full_html=False)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>OECD Crude Inventories vs. Brent Price — Time Series | boquin.xyz</title>
  <style>
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         margin:0;padding:1.5rem;background:#faf6f1;color:#222;
         display:flex;flex-direction:column;align-items:center}}
    header{{max-width:1000px;width:100%;margin-bottom:1rem}}
    header h1{{font-size:1.3rem;font-weight:bold;margin:0}}
    header p{{color:#555;font-size:.85rem;margin-top:.4rem}}
    .chart-wrapper{{width:100%;max-width:1040px;background:#fff;
                   border:1px solid #ddd;border-radius:4px;padding:1rem}}
    .footnote{{width:100%;max-width:1040px;font-size:.8rem;color:#555;
              line-height:1.5;margin-top:.75rem;padding:0 .25rem}}
    footer{{margin-top:1.5rem;font-size:.8rem;color:#888;text-align:center}}
    footer a{{color:#2196F3;text-decoration:none}}
  </style>
</head>
<body>
  <header>
    <h1>&#x1F6E2;&#xFE0F; OECD Commercial Crude Inventories vs. Brent Price &mdash; Time Series</h1>
    <p>Monthly since {START_YEAR} &mdash; latest point: {latest_label}</p>
  </header>
  <div class="chart-wrapper">
    {chart_html}
  </div>
  <p class="footnote">{footnote}</p>
  <footer>
    Source: <a href="https://www.eia.gov/outlooks/steo/" target="_blank">EIA Short-Term Energy Outlook</a>
    (series {INVENTORY_SERIES}, {BRENT_SERIES})
    &nbsp;&bull;&nbsp;
    <a href="https://github.com/DataVizHonduran/boquin.github.io/blob/main/scripts/generate_oecd_inventory_brent_timeseries.py" target="_blank">Source Code</a>
    &nbsp;&bull;&nbsp;
    <a href="../oecd-inventory-brent/index.html">Scatter version</a>
    &nbsp;&bull;&nbsp;
    <a href="https://boquin.xyz" target="_blank">boquin.xyz</a>
  </footer>
</body>
</html>"""
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved: {OUTPUT_PATH}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    api_key = get_api_key()

    print("Fetching EIA STEO series...")
    inventory = fetch_steo_series(api_key, INVENTORY_SERIES)
    brent     = fetch_steo_series(api_key, BRENT_SERIES)

    df = pd.concat([inventory.rename("inventory"), brent.rename("brent")], axis=1, join="inner")
    df = df[df.index >= f"{START_YEAR}-01-01"]
    last_complete_month = (pd.Timestamp.today().to_period("M") - 1).to_timestamp()
    df = df[df.index <= last_complete_month]
    print(f"  {len(df)} months, {df.index.min().date()} - {df.index.max().date()}")

    fig, footnote, per_100mn = build_figure(df)
    latest = df.index.max()
    latest_label = f"{latest.strftime('%b %Y')} (inventory {df['inventory'].iloc[-1]:,.0f} mn bbl, Brent ${df['brent'].iloc[-1]:.1f})"
    write_page(fig, footnote, latest_label)


if __name__ == "__main__":
    main()

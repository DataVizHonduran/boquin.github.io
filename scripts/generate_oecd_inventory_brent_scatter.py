"""
generate_oecd_inventory_brent_scatter.py — OECD Crude Inventories vs Brent Price
EIA STEO data only:
  - x: OECD commercial crude oil + other liquids inventories (mn barrels)
  - y: Monthly average Brent crude oil price ($/bbl)

Single OLS fit (brent ~ inventory) feeds three views, rendered as tabs:
  1. Scatter — the FT/Capital Economics-style scatter, 2022 and "Since Iran
     conflict" highlighted against the full since-2010 cloud.
  2. Actual vs. fair value — monthly line chart of actual Brent vs. the
     regression-predicted ("fair value") price.
  3. Residual — actual minus predicted, as a bar chart.

Required env var:
  EIA_API_KEY  — Register free at https://www.eia.gov/opendata/register.php

Run: python scripts/generate_oecd_inventory_brent_scatter.py
Output: reports/oecd-inventory-brent/index.html
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
OUTPUT_DIR   = os.path.join(REPO_ROOT, "reports", "oecd-inventory-brent")
OUTPUT_PATH  = os.path.join(OUTPUT_DIR, "index.html")

INVENTORY_SERIES = "PASC_OECD_T3"   # OECD commercial crude + other liquids inventory, mn bbl
BRENT_SERIES     = "BREPUUS"        # Brent crude oil spot price, $/bbl

START_YEAR = 2010

# Months highlighted as "Since Iran conflict" (red) — the 2026 price-spike window
IRAN_START = pd.Timestamp("2026-02-01")

COLORS = {
    "Other since 2010":   "#cfc7bb",
    "2022":               "#1f77b4",
    "Since Iran conflict": "#a8325e",
    "actual":              "#1f77b4",
    "predicted":           "#a8325e",
    "residual_pos":        "#1f77b4",
    "residual_neg":        "#a8325e",
}
ORDER = ["Other since 2010", "2022", "Since Iran conflict"]


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


def categorize(d: pd.Timestamp) -> str:
    if d >= IRAN_START:
        return "Since Iran conflict"
    if d.year == 2022:
        return "2022"
    return "Other since 2010"


# ---------------------------------------------------------------------------
# Regression
# ---------------------------------------------------------------------------
def fit_regression(df: pd.DataFrame):
    slope, intercept = np.polyfit(df["inventory"], df["brent"], 1)
    predicted = slope * df["inventory"] + intercept
    ss_res = ((df["brent"] - predicted) ** 2).sum()
    ss_tot = ((df["brent"] - df["brent"].mean()) ** 2).sum()
    r_squared = 1 - ss_res / ss_tot
    return slope, intercept, r_squared


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
def build_scatter_figure(df: pd.DataFrame, slope: float, intercept: float, r_squared: float) -> go.Figure:
    fig = go.Figure()
    for cat in ORDER:
        sub = df[df["cat"] == cat]
        fig.add_trace(go.Scatter(
            x=sub["inventory"], y=sub["brent"],
            mode="markers",
            name=cat,
            marker=dict(size=10, color=COLORS[cat], line=dict(width=0)),
            hovertemplate="%{text}<br>Inventory: %{x:,.0f} mn bbl<br>Brent: $%{y:.1f}<extra></extra>",
            text=[d.strftime("%b %Y") for d in sub.index],
        ))

    x_line = np.array([df["inventory"].min(), df["inventory"].max()])
    y_line = slope * x_line + intercept
    fig.add_trace(go.Scatter(
        x=x_line, y=y_line,
        mode="lines",
        name=f"OLS fit: y = {intercept:,.1f} + ({slope:.4f})·x, R² = {r_squared:.2f}",
        line=dict(color="#444444", width=2, dash="dash"),
        hoverinfo="skip",
    ))

    iran_pts = df[df["cat"] == "Since Iran conflict"]
    for d, row in iran_pts.iterrows():
        fig.add_annotation(
            x=row["inventory"], y=row["brent"],
            text=d.strftime("%b %Y"), showarrow=False,
            font=dict(size=11, color=COLORS["Since Iran conflict"]),
            xanchor="left", xshift=10, yshift=6,
        )

    fig.update_layout(
        title="Continued oil inventory drawdowns would pressure prices higher"
              "<br><sup>Monthly average Brent crude vs. OECD commercial crude oil "
              f"inventories, since {START_YEAR}</sup>",
        xaxis_title="OECD commercial crude oil inventories (mn barrels)",
        yaxis_title="Monthly average Brent crude oil price ($ per barrel)",
        template="plotly_white",
        legend=dict(orientation="v", yanchor="top", y=0.99, xanchor="right", x=0.99,
                    bgcolor="rgba(250,246,241,0.7)"),
        width=1000, height=650,
        plot_bgcolor="#faf6f1", paper_bgcolor="#faf6f1",
        margin=dict(t=80),
    )
    return fig


def build_fair_value_figure(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df.index, y=df["brent"], mode="lines", name="Actual Brent",
        line=dict(color=COLORS["actual"], width=2),
        hovertemplate="%{x|%b %Y}<br>Actual: $%{y:.1f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df.index, y=df["predicted"], mode="lines", name="Fair value (inventory regression)",
        line=dict(color=COLORS["predicted"], width=2, dash="dash"),
        hovertemplate="%{x|%b %Y}<br>Fair value: $%{y:.1f}<extra></extra>",
    ))
    fig.update_layout(
        title="Actual Brent vs. inventory-implied fair value"
              f"<br><sup>Monthly average Brent crude vs. OLS fit on OECD commercial crude oil "
              f"inventories, since {START_YEAR}</sup>",
        xaxis_title="Month",
        yaxis_title="$ per barrel",
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    bgcolor="rgba(250,246,241,0.7)"),
        width=1000, height=550,
        plot_bgcolor="#faf6f1", paper_bgcolor="#faf6f1",
        margin=dict(t=100),
        hovermode="x unified",
    )
    return fig


def build_residual_figure(df: pd.DataFrame) -> go.Figure:
    colors = [COLORS["residual_pos"] if v >= 0 else COLORS["residual_neg"] for v in df["residual"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df.index, y=df["residual"], name="Residual (actual − fair value)",
        marker=dict(color=colors),
        hovertemplate="%{x|%b %Y}<br>Residual: $%{y:+.1f}<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color="#999", width=1))
    fig.update_layout(
        title="Residual: actual Brent minus inventory-implied fair value"
              "<br><sup>Positive = Brent trading rich to the inventory relationship "
              "(e.g. risk premium); negative = trading cheap</sup>",
        xaxis_title="Month",
        yaxis_title="Residual ($ per barrel)",
        template="plotly_white",
        showlegend=False,
        width=1000, height=550,
        plot_bgcolor="#faf6f1", paper_bgcolor="#faf6f1",
        margin=dict(t=100),
    )
    return fig


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
def write_page(scatter_fig: go.Figure, fair_value_fig: go.Figure, residual_fig: go.Figure,
               scatter_footnote: str, timeseries_footnote: str, latest_label: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    scatter_html = scatter_fig.to_html(include_plotlyjs="cdn", full_html=False, div_id="scatter-chart")
    fair_value_html = fair_value_fig.to_html(include_plotlyjs=False, full_html=False, div_id="fair-value-chart")
    residual_html = residual_fig.to_html(include_plotlyjs=False, full_html=False, div_id="residual-chart")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>OECD Crude Inventories vs. Brent Price | boquin.xyz</title>
  <style>
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         margin:0;padding:1.5rem;background:#faf6f1;color:#222;
         display:flex;flex-direction:column;align-items:center}}
    header{{max-width:1040px;width:100%;margin-bottom:1rem}}
    header h1{{font-size:1.3rem;font-weight:bold;margin:0}}
    header p{{color:#555;font-size:.85rem;margin-top:.4rem}}
    .tabs{{width:100%;max-width:1040px;display:flex;gap:.5rem;margin-bottom:.75rem}}
    .tab-btn{{font-family:inherit;font-size:.85rem;font-weight:600;padding:.5rem 1rem;
             border:1px solid #ddd;border-radius:4px;background:#fff;color:#555;cursor:pointer}}
    .tab-btn.active{{background:#2196F3;border-color:#2196F3;color:#fff}}
    .tab-panel{{display:none;width:100%;max-width:1040px}}
    .tab-panel.active{{display:block}}
    .chart-wrapper{{width:100%;background:#fff;border:1px solid #ddd;border-radius:4px;
                   padding:1rem;margin-bottom:1rem}}
    .footnote{{width:100%;font-size:.8rem;color:#555;line-height:1.5;margin-top:.25rem;padding:0 .25rem}}
    footer{{margin-top:1.5rem;font-size:.8rem;color:#888;text-align:center}}
    footer a{{color:#2196F3;text-decoration:none}}
  </style>
</head>
<body>
  <header>
    <h1>&#x1F6E2;&#xFE0F; OECD Commercial Crude Inventories vs. Brent Price</h1>
    <p>Monthly since {START_YEAR} &mdash; latest point: {latest_label}</p>
  </header>

  <div class="tabs">
    <button class="tab-btn active" data-tab="scatter">Scatter</button>
    <button class="tab-btn" data-tab="timeseries">Actual vs. Fair Value &amp; Residual</button>
  </div>

  <div id="scatter" class="tab-panel active">
    <div class="chart-wrapper">{scatter_html}</div>
    <p class="footnote">{scatter_footnote}</p>
  </div>

  <div id="timeseries" class="tab-panel">
    <div class="chart-wrapper">{fair_value_html}</div>
    <div class="chart-wrapper">{residual_html}</div>
    <p class="footnote">{timeseries_footnote}</p>
  </div>

  <footer>
    Source: <a href="https://www.eia.gov/outlooks/steo/" target="_blank">EIA Short-Term Energy Outlook</a>
    (series {INVENTORY_SERIES}, {BRENT_SERIES})
    &nbsp;&bull;&nbsp;
    <a href="https://github.com/DataVizHonduran/boquin.github.io/blob/main/scripts/generate_oecd_inventory_brent_scatter.py" target="_blank">Source Code</a>
    &nbsp;&bull;&nbsp;
    <a href="https://boquin.xyz" target="_blank">boquin.xyz</a>
  </footer>

  <script>
    document.querySelectorAll('.tab-btn').forEach(function (btn) {{
      btn.addEventListener('click', function () {{
        document.querySelectorAll('.tab-btn').forEach(function (b) {{ b.classList.remove('active'); }});
        document.querySelectorAll('.tab-panel').forEach(function (p) {{ p.classList.remove('active'); }});
        btn.classList.add('active');
        document.getElementById(btn.dataset.tab).classList.add('active');
        window.dispatchEvent(new Event('resize'));
      }});
    }});
  </script>
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
    df["cat"] = df.index.map(categorize)
    print(f"  {len(df)} months, {df.index.min().date()} - {df.index.max().date()}")

    slope, intercept, r_squared = fit_regression(df)
    df["predicted"] = slope * df["inventory"] + intercept
    df["residual"] = df["brent"] - df["predicted"]
    per_100mn = -100 * slope

    scatter_fig = build_scatter_figure(df, slope, intercept, r_squared)
    fair_value_fig = build_fair_value_figure(df)
    residual_fig = build_residual_figure(df)

    iran_pts = df[df["cat"] == "Since Iran conflict"]
    start, end = iran_pts.iloc[0], iran_pts.iloc[-1]
    inv_draw = start["inventory"] - end["inventory"]
    actual_move = end["brent"] - start["brent"]
    implied_move = (inv_draw / 100) * per_100mn
    scatter_footnote = (
        f"<b>Rule of thumb:</b> every 100 mn barrel draw in OECD commercial crude inventories &asymp; "
        f"+${per_100mn:.1f}/bbl on Brent (and symmetrically, a 100 mn barrel build &asymp; -${per_100mn:.1f}/bbl).<br>"
        f"<b>Sanity check:</b> inventories fell from {start['inventory']:,.0f} mn bbl "
        f"({start.name.strftime('%b %Y')}) to {end['inventory']:,.0f} mn bbl ({end.name.strftime('%b %Y')}) "
        f"&mdash; a {inv_draw:,.0f} mn barrel draw &mdash; which the regression would put at roughly "
        f"+${implied_move:.0f}/bbl, while Brent actually moved from ${start['brent']:.0f} to ${end['brent']:.0f}, "
        f"a ${actual_move:.0f}/bbl jump. The actual move ran hotter than the historical relationship alone "
        f"would predict &mdash; consistent with a geopolitical risk premium layered on top of the inventory effect."
    )

    latest = df.iloc[-1]
    timeseries_footnote = (
        f"<b>Fit:</b> y = {intercept:,.1f} + ({slope:.4f})&middot;x, R&sup2; = {r_squared:.2f} "
        f"&mdash; every 100 mn barrel draw &asymp; +${per_100mn:.1f}/bbl on fair value.<br>"
        f"<b>Latest residual:</b> {latest.name.strftime('%b %Y')} actual Brent ${latest['brent']:.1f} vs. "
        f"fair value ${latest['predicted']:.1f} &mdash; a ${latest['residual']:+.1f}/bbl residual, "
        f"{'above' if latest['residual'] > 0 else 'below'} what the inventory relationship alone implies "
        f"(e.g. geopolitical risk premium or demand/positioning effects not captured by inventories)."
    )

    latest_label = f"{latest.name.strftime('%b %Y')} (inventory {latest['inventory']:,.0f} mn bbl, Brent ${latest['brent']:.1f})"
    write_page(scatter_fig, fair_value_fig, residual_fig, scatter_footnote, timeseries_footnote, latest_label)


if __name__ == "__main__":
    main()

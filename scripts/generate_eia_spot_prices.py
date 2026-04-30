"""
generate_eia_spot_prices.py — EIA Petroleum Spot Prices Table
Fetches daily spot prices for key petroleum products via EIA Open Data API v2
and generates a static HTML table with % changes across 6 time horizons.

Required env var:
  EIA_API_KEY  — Register free at https://www.eia.gov/opendata/register.php

Run: python scripts/generate_eia_spot_prices.py
Output: reports/eia-spot-prices/index.html
"""

import os
import sys
import requests
from datetime import datetime, date, timedelta, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
EIA_API_BASE = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT       = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR      = os.path.join(REPO_ROOT, "reports", "eia-spot-prices")
OUTPUT_PATH     = os.path.join(OUTPUT_DIR, "index.html")

# Each product: (display_label, unit, [ranked keyword sets to match against series description])
# Keyword sets are tried in order; first series matching ALL keywords in a set wins.
PRODUCTS = [
    ("WTI Crude Oil (Cushing, OK)",       "$/bbl",  [["cushing", "wti"],          ["cushing", "crude"]]),
    ("Brent Crude Oil (Europe)",           "$/bbl",  [["brent", "europe"],         ["brent", "spot"]]),
    ("NY Harbor No. 2 Heating Oil",        "$/gal",  [["heating oil", "new york"], ["heating oil", "harbor"]]),
    ("Gulf Coast Kerosene-Type Jet Fuel",  "$/gal",  [["jet fuel", "gulf"],        ["kerosene", "gulf"]]),
    ("NY Harbor RBOB Regular Gasoline",    "$/gal",  [["rbob", "new york"],        ["rbob", "harbor"]]),
    ("LA RBOB Regular Gasoline",           "$/gal",  [["rbob", "los angeles"],     ["rbob", "angeles"]]),
    ("NY Harbor ULS No. 2 Diesel",         "$/gal",  [["ultra-low", "diesel", "new york"], ["uls", "diesel", "harbor"]]),
    ("Gulf Coast ULS No. 2 Diesel",        "$/gal",  [["ultra-low", "diesel", "gulf"],     ["uls", "diesel", "gulf"]]),
    ("LA ULS CARB Diesel",                 "$/gal",  [["carb", "diesel", "los angeles"],   ["carb", "diesel", "angeles"]]),
    ("Propane (Mont Belvieu, TX)",          "$/gal",  [["propane", "mont belvieu"],         ["propane", "belvieu"]]),
]

# Calendar-day lookback windows for each % change column
PERIODS = [
    ("1D",   1),
    ("1W",   7),
    ("1M",   30),
    ("3M",   91),
    ("12M",  365),
    ("5Y",   1825),
]

# ---------------------------------------------------------------------------
# Series discovery
# ---------------------------------------------------------------------------

def discover_series(api_key: str) -> list[dict]:
    """
    Fetch a recent slice of all series (no series filter) and collect
    unique series IDs + descriptions from the response rows.
    """
    try:
        resp = requests.get(
            EIA_API_BASE,
            params={
                "api_key":              api_key,
                "frequency":            "daily",
                "data[0]":              "value",
                "sort[0][column]":      "period",
                "sort[0][direction]":   "desc",
                "start":                "2026-04-01",
                "length":               5000,
            },
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json().get("response", {}).get("data", [])

        seen: dict[str, dict] = {}
        for row in rows:
            sid  = row.get("series", "")
            desc = row.get("seriesDescription", "")
            if sid and sid not in seen:
                seen[sid] = {"id": sid, "description": desc}

        catalog = list(seen.values())
        print(f"  Discovered {len(catalog)} series in petroleum/pri/spt")
        for item in catalog:
            print(f"    {item['id']} — {item['description']}")
        return catalog
    except Exception as exc:
        print(f"  WARNING: series discovery failed ({exc}); skipping all")
        return []


def match_series(label: str, keyword_sets: list[list[str]], catalog: list[dict]) -> str | None:
    """
    Find the best series ID from catalog for a given product.
    Tries each keyword_set in order; returns first series whose description
    contains all keywords in the set (case-insensitive).
    """
    for kws in keyword_sets:
        for item in catalog:
            desc = item.get("description", item.get("name", "")).lower()
            if all(k in desc for k in kws):
                return item["id"]
    return None


# ---------------------------------------------------------------------------
# EIA API fetch
# ---------------------------------------------------------------------------

def fetch_series(series_id: str, api_key: str, start: str) -> dict[str, float]:
    """Fetch daily data for one series from `start` date to today. Returns {date_str: price}."""
    params = {
        "api_key":              api_key,
        "frequency":            "daily",
        "data[0]":              "value",
        "facets[series][]":     series_id,
        "sort[0][column]":      "period",
        "sort[0][direction]":   "desc",
        "start":                start,
        "length":               2200,
        "offset":               0,
    }

    try:
        resp = requests.get(EIA_API_BASE, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        print(f"  ERROR fetching {series_id}: {exc}")
        return {}

    rows   = payload.get("response", {}).get("data", [])
    result = {}
    for row in rows:
        period = row.get("period", "")
        val    = row.get("value")
        if period and val is not None:
            try:
                result[period] = float(val)
            except (TypeError, ValueError):
                pass

    return result


# ---------------------------------------------------------------------------
# % change helper
# ---------------------------------------------------------------------------

def pct_change(prices: dict[str, float], lookback_days: int) -> float | None:
    """Return % change from ~lookback_days calendar days ago to latest."""
    if not prices:
        return None

    dates     = sorted(prices.keys())
    latest    = dates[-1]
    latest_dt = datetime.strptime(latest, "%Y-%m-%d")
    target_dt = latest_dt - timedelta(days=lookback_days)
    target_str = target_dt.strftime("%Y-%m-%d")

    past_dates = [d for d in dates if d <= target_str]
    if not past_dates:
        return None

    px_now  = prices[latest]
    px_then = prices[past_dates[-1]]

    if px_then == 0:
        return None
    return (px_now - px_then) / px_then * 100


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def fmt_pct(val: float | None) -> tuple[str, str]:
    if val is None:
        return "—", "na"
    sign = "+" if val >= 0 else ""
    cls  = "pos" if val >= 0 else "neg"
    return f"{sign}{val:.1f}%", cls


def build_html(rows: list[dict], generated_at: str) -> str:
    period_headers = "".join(f"<th>{p}</th>" for p, _ in PERIODS)

    body_rows = []
    for row in rows:
        cells = [
            f'<td class="product-name">{row["label"]}</td>',
            f'<td class="spot-price">{row["spot"]}<span class="unit">{row["unit"]}</span></td>',
        ]
        for p, days in PERIODS:
            val       = row["changes"].get(p)
            text, cls = fmt_pct(val)
            cells.append(f'<td class="pct {cls}">{text}</td>')
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    body_html = "\n            ".join(body_rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EIA Petroleum Spot Prices</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  :root {{
    --bg:      #f4f7fb;
    --surface: #ffffff;
    --navy:    #2a3f5f;
    --navy-hd: #1a2e45;
    --blue-md: #3d5a8a;
    --text:    #2a3f5f;
    --muted:   #7b8faa;
    --border:  #d1dce9;
    --green:   #1a7f3c;
    --green-bg:#e8f5ee;
    --red:     #c0392b;
    --red-bg:  #fdecea;
    --na:      #9aa8bb;
  }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 14px;
    line-height: 1.5;
    min-height: 100vh;
  }}

  .dashboard-header {{
    background: linear-gradient(135deg, var(--navy-hd) 0%, var(--blue-md) 100%);
    padding: 28px 32px 24px;
    border-bottom: 1px solid #b8c8db;
    color: #ffffff;
  }}
  .dashboard-header h1 {{
    font-size: 1.6rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: #ffffff;
    margin-bottom: 6px;
  }}
  .header-meta {{
    font-size: 12px;
    color: rgba(255,255,255,0.7);
  }}
  .back-link {{
    display: inline-block;
    margin-bottom: 14px;
    color: rgba(255,255,255,0.75);
    text-decoration: none;
    font-size: 12px;
    letter-spacing: 0.02em;
  }}
  .back-link:hover {{ color: #fff; }}

  .main-content {{
    max-width: 1100px;
    margin: 32px auto;
    padding: 0 24px;
  }}

  .table-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
  }}

  thead th {{
    background: var(--navy);
    color: #fff;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    padding: 11px 14px;
    text-align: right;
    white-space: nowrap;
    position: sticky;
    top: 0;
    z-index: 1;
  }}
  thead th.product-name,
  thead th:first-child {{ text-align: left; }}

  tbody tr {{
    border-bottom: 1px solid var(--border);
    transition: background 0.12s;
  }}
  tbody tr:last-child {{ border-bottom: none; }}
  tbody tr:hover {{ background: #f0f4fa; }}

  td {{
    padding: 11px 14px;
    text-align: right;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }}
  td.product-name {{
    text-align: left;
    font-weight: 500;
    color: var(--navy);
  }}
  td.spot-price {{
    font-weight: 600;
    color: var(--navy);
  }}
  .unit {{
    font-size: 10px;
    font-weight: 400;
    color: var(--muted);
    margin-left: 3px;
  }}

  td.pct {{
    font-weight: 600;
    font-size: 13px;
    border-radius: 4px;
  }}
  td.pct.pos {{ color: var(--green); background: var(--green-bg); }}
  td.pct.neg {{ color: var(--red);   background: var(--red-bg);   }}
  td.pct.na  {{ color: var(--na);   font-weight: 400;             }}

  .footer {{
    text-align: center;
    margin: 28px 0 40px;
    font-size: 11px;
    color: var(--muted);
  }}
  .footer a {{ color: var(--muted); }}

  @media (max-width: 768px) {{
    .main-content {{ padding: 0 12px; margin: 16px auto; }}
    td, th {{ padding: 9px 8px; font-size: 12px; }}
    td.product-name {{ min-width: 160px; }}
  }}
</style>
</head>
<body>

<div class="dashboard-header">
  <a class="back-link" href="../../index.html">← boquin.xyz</a>
  <h1>⛽ EIA Petroleum Spot Prices</h1>
  <div class="header-meta">Daily spot prices · Source: EIA Open Data API v2 · Updated: {generated_at}</div>
</div>

<div class="main-content">
  <div class="table-card">
    <table>
      <thead>
        <tr>
          <th class="product-name">Product</th>
          <th>Spot Price</th>
          {period_headers}
        </tr>
      </thead>
      <tbody>
            {body_html}
      </tbody>
    </table>
  </div>

  <div class="footer">
    Data: <a href="https://www.eia.gov/dnav/pet/pet_pri_spt_s1_d.htm" target="_blank">EIA Petroleum &amp; Other Liquids — Spot Prices</a> ·
    % changes measured from closest available trading day.
  </div>
</div>

</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    api_key = os.environ.get("EIA_API_KEY", "").strip()
    if not api_key:
        print("ERROR: EIA_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 6 years of history covers the 5Y % change column
    start_date   = (date.today() - timedelta(days=365 * 6)).strftime("%Y-%m-%d")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Discover all available series from EIA
    print("Discovering available series...")
    catalog = discover_series(api_key)

    rows = []
    for label, unit, keyword_sets in PRODUCTS:
        series_id = match_series(label, keyword_sets, catalog)

        if not series_id:
            print(f"  WARNING: no series matched for '{label}' — skipping")
            rows.append({"label": label, "spot": "N/A", "unit": unit,
                         "changes": {p: None for p, _ in PERIODS}})
            continue

        print(f"Fetching: {label} → {series_id}...")
        prices = fetch_series(series_id, api_key, start_date)

        if not prices:
            spot_str = "N/A"
            changes  = {p: None for p, _ in PERIODS}
        else:
            dates     = sorted(prices.keys())
            latest_px = prices[dates[-1]]
            spot_str  = f"{latest_px:.2f}" if unit == "$/bbl" else f"{latest_px:.4f}"
            changes   = {p: pct_change(prices, days) for p, days in PERIODS}
            print(f"  Latest ({dates[-1]}): {latest_px}")

        rows.append({"label": label, "spot": spot_str, "unit": unit, "changes": changes})

    html = build_html(rows, generated_at)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nWrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

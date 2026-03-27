"""
iShares EMB Holdings — Duration vs Yield Bubble Chart
Source: iShares JP Morgan USD Emerging Markets Bond ETF daily holdings CSV
Output: reports/emb-bubble/index.html

Run: python3 scripts/generate_emb_bubble.py
"""

import csv
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

# ── Config ────────────────────────────────────────────────────────────────────
ISHARES_URL = (
    "https://www.ishares.com/us/products/239572/"
    "ishares-jp-morgan-usd-emerging-markets-bond-etf/"
    "1467271812596.ajax?fileType=csv&fileName=EMB_holdings&dataType=fund"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.ishares.com/us/products/239572/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

OUTPUT_DIR = Path(__file__).parent.parent / "reports" / "emb-bubble"
OUTPUT_FILE = OUTPUT_DIR / "index.html"
CACHE_DIR = Path.home() / ".claude" / "cache" / "emb"
CACHE_FILE = CACHE_DIR / "emb_holdings.csv"
CACHE_META = CACHE_DIR / "emb_meta.json"

# Duration column candidates (in priority order)
DURATION_COLS = ["Effective Duration", "Modified Duration", "Duration"]
# Yield column candidates
YIELD_COLS = ["Yield to Maturity (%)", "YTM (%)", "Yield to Maturity", "YTM", "Yield (%)"]


# ── Fetch CSV ─────────────────────────────────────────────────────────────────
def fetch_csv() -> tuple[str, bool]:
    """Return (csv_text, is_fresh). Falls back to cache if fetch fails."""
    try:
        print("Fetching iShares EMB holdings CSV…")
        resp = requests.get(ISHARES_URL, headers=HEADERS, timeout=45)
        resp.raise_for_status()
        text = resp.text
        if len(text) < 1000 or "Name" not in text:
            raise ValueError(f"Response too short or missing data ({len(text)} chars)")
        # Cache for fallback
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(text, encoding="utf-8")
        CACHE_META.write_text(
            json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )
        print(f"  Fetched {len(text):,} chars successfully")
        return text, True
    except Exception as e:
        print(f"  Fetch failed: {e}", file=sys.stderr)
        if CACHE_FILE.exists():
            print("  Falling back to cached CSV", file=sys.stderr)
            return CACHE_FILE.read_text(encoding="utf-8"), False
        raise RuntimeError("No cached CSV available — cannot continue") from e


# ── Parse CSV ─────────────────────────────────────────────────────────────────
def parse_csv(text: str) -> tuple[pd.DataFrame, str]:
    """
    iShares CSV has 2–3 metadata rows before the column header.
    We find the header row by locating the line that starts with 'Name' or 'Ticker'.
    Returns (df, as_of_date_str).
    """
    lines = text.splitlines()

    # Extract as-of date from metadata rows (typically row 1 or 2).
    # The CSV line looks like: Fund Holdings as of,"Mar 25, 2026"
    # We use regex to find a quoted date value rather than splitting on commas.
    as_of = ""
    DATE_PATTERNS = [
        (r"(\w{3}\s+\d{1,2},\s*\d{4})", "%b %d, %Y"),
        (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
        (r"(\d{1,2}/\d{1,2}/\d{4})", "%m/%d/%Y"),
        (r"(\d{1,2}-\w{3}-\d{4})", "%d-%b-%Y"),
    ]
    for line in lines[:8]:
        if "as of" in line.lower() or "holdings date" in line.lower():
            # Strip quotes, then search for date patterns
            clean = line.replace('"', "")
            for pattern, fmt in DATE_PATTERNS:
                m = re.search(pattern, clean)
                if m:
                    try:
                        dt = datetime.strptime(m.group(1).strip(), fmt)
                        as_of = dt.strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        pass
            if as_of:
                break

    # Find header row index
    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip().strip('"')
        if stripped.startswith("Name") or stripped.startswith("Ticker"):
            header_idx = i
            break

    if header_idx is None:
        raise ValueError("Could not find header row in iShares CSV")

    print(f"  Header row at line {header_idx}, as-of: {as_of or 'unknown'}")

    csv_body = "\n".join(lines[header_idx:])
    df = pd.read_csv(io.StringIO(csv_body), thousands=",", low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    return df, as_of


# ── Clean & extract ───────────────────────────────────────────────────────────
def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to fixed income bonds with valid duration & yield."""
    # Keep only Fixed Income rows
    if "Asset Class" in df.columns:
        df = df[df["Asset Class"].str.strip() == "Fixed Income"].copy()

    # Find duration column
    dur_col = None
    for c in DURATION_COLS:
        if c in df.columns:
            dur_col = c
            break
    if dur_col is None:
        # Try partial match
        for col in df.columns:
            if "duration" in col.lower():
                dur_col = col
                break
    if dur_col is None:
        raise ValueError(f"No duration column found. Columns: {list(df.columns)}")

    # Find yield column
    ytm_col = None
    for c in YIELD_COLS:
        if c in df.columns:
            ytm_col = c
            break
    if ytm_col is None:
        for col in df.columns:
            if "yield" in col.lower() or "ytm" in col.lower():
                ytm_col = col
                break
    if ytm_col is None:
        raise ValueError(f"No yield column found. Columns: {list(df.columns)}")

    print(f"  Using duration col: '{dur_col}', yield col: '{ytm_col}'")

    # Find market value column
    mv_col = None
    for candidate in ["Market Value", "Notional Value", "Market Value (USD)"]:
        if candidate in df.columns:
            mv_col = candidate
            break
    if mv_col is None:
        for col in df.columns:
            if "market" in col.lower() and "value" in col.lower():
                mv_col = col
                break

    # Find weight column
    wt_col = None
    for candidate in ["Weight (%)", "Weight", "Portfolio Weight"]:
        if candidate in df.columns:
            wt_col = candidate
            break

    # Find coupon column
    cp_col = None
    for candidate in ["Coupon (%)", "Coupon", "Coupon Rate"]:
        if candidate in df.columns:
            cp_col = candidate
            break

    # Find maturity column
    mat_col = None
    for candidate in ["Maturity", "Maturity Date"]:
        if candidate in df.columns:
            mat_col = candidate
            break

    # Find location/country column
    loc_col = None
    for candidate in ["Location", "Country", "Country of Risk"]:
        if candidate in df.columns:
            loc_col = candidate
            break

    def to_float(series):
        return pd.to_numeric(
            series.astype(str).str.replace(",", "").str.replace("%", "").str.strip(),
            errors="coerce",
        )

    df["_duration"] = to_float(df[dur_col])
    df["_ytm"] = to_float(df[ytm_col])
    df["_market_value"] = to_float(df[mv_col]) if mv_col else 0.0
    df["_weight"] = to_float(df[wt_col]) if wt_col else 0.0
    df["_coupon"] = to_float(df[cp_col]) if cp_col else None
    df["_maturity"] = df[mat_col].astype(str).str.strip() if mat_col else ""
    df["_country"] = df[loc_col].astype(str).str.strip() if loc_col else "Unknown"
    df["_name"] = df["Name"].astype(str).str.strip() if "Name" in df.columns else ""

    # Drop rows missing the key chart fields
    df = df.dropna(subset=["_duration", "_ytm"])
    df = df[df["_duration"] > 0]
    df = df[df["_ytm"] > 0]
    df = df[~df["_country"].isin(["", "nan", "N/A", "-"])]

    print(f"  {len(df)} valid fixed-income bonds after cleaning")
    return df


# ── Build JSON payload ────────────────────────────────────────────────────────
def build_payload(df: pd.DataFrame, as_of: str, fetched_at: str, is_fresh: bool) -> dict:
    bonds = []
    for _, row in df.iterrows():
        bonds.append(
            {
                "name": row["_name"],
                "country": row["_country"],
                "duration": round(float(row["_duration"]), 3),
                "ytm": round(float(row["_ytm"]), 3),
                "market_value": round(float(row["_market_value"]), 0),
                "weight": round(float(row["_weight"]), 3) if row["_weight"] else 0.0,
                "coupon": round(float(row["_coupon"]), 3) if pd.notna(row["_coupon"]) else None,
                "maturity": row["_maturity"],
            }
        )

    countries = sorted(df["_country"].unique().tolist())

    return {
        "as_of": as_of,
        "fetched_at": fetched_at,
        "is_fresh": is_fresh,
        "bond_count": len(bonds),
        "country_count": len(countries),
        "countries": countries,
        "bonds": bonds,
    }


# ── Generate HTML ─────────────────────────────────────────────────────────────
def generate_html(payload: dict) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)

    fetched_display = ""
    if payload["fetched_at"]:
        try:
            dt = datetime.fromisoformat(payload["fetched_at"].replace("Z", "+00:00"))
            fetched_display = dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            fetched_display = payload["fetched_at"]

    if payload["is_fresh"]:
        update_badge = f'Data fetched {fetched_display}'
        update_class = "badge-fresh"
    else:
        update_badge = f'&#9888; Using cached data from {fetched_display} — live fetch failed'
        update_class = "badge-stale"

    holdings_date = payload.get("as_of") or "unknown"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EMB Holdings — Duration vs Yield</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  :root {{
    --forest: #1a3a2f;
    --forest-light: #2d5a47;
    --moss: #3d6b56;
    --mint: #e8f0ec;
    --cream: #faf9f7;
    --charcoal: #1a1a1a;
    --warm-gray: #6b6b6b;
    --accent: #4f46e5;
    --c1: #0072B2;
    --c2: #E69F00;
    --c3: #009E73;
    --c4: #CC79A7;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif; background: var(--cream); color: var(--charcoal); }}

  /* Header */
  .page-header {{
    background: linear-gradient(135deg, var(--forest) 0%, var(--forest-light) 100%);
    color: #fff;
    padding: 24px 32px 20px;
  }}
  .page-header h1 {{ font-size: 1.5rem; font-weight: 700; letter-spacing: -0.01em; }}
  .page-header p {{ font-size: 0.85rem; opacity: 0.8; margin-top: 4px; }}
  .badges {{ display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; align-items: center; }}
  .badge {{
    font-size: 0.72rem; padding: 3px 10px; border-radius: 999px; font-weight: 500;
  }}
  .badge-holdings {{ background: rgba(255,255,255,0.15); color: #fff; }}
  .badge-fresh {{ background: rgba(0,200,100,0.2); color: #7fffd4; }}
  .badge-stale {{ background: rgba(255,180,0,0.2); color: #ffd580; }}

  /* Main layout */
  .main {{ max-width: 1300px; margin: 0 auto; padding: 20px 24px 40px; }}

  /* Country selector */
  .selector-panel {{
    background: #fff;
    border: 1px solid #e4e8ef;
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 16px;
  }}
  .selector-panel h3 {{
    font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--warm-gray); margin-bottom: 12px; font-weight: 600;
  }}
  .selector-hint {{
    font-size: 0.75rem; color: var(--warm-gray); margin-bottom: 10px;
  }}
  .country-pills {{
    display: flex; flex-wrap: wrap; gap: 6px; max-height: 200px;
    overflow-y: auto; padding: 2px;
  }}
  .pill {{
    cursor: pointer;
    padding: 4px 12px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 500;
    border: 1.5px solid #dde3ec;
    background: #f8f9fc;
    color: var(--charcoal);
    transition: all 0.15s;
    user-select: none;
  }}
  .pill:hover {{ border-color: #aab3c8; background: #eef1f7; }}
  .pill.active-0 {{ background: var(--c1); border-color: var(--c1); color: #fff; }}
  .pill.active-1 {{ background: var(--c2); border-color: var(--c2); color: #fff; }}
  .pill.active-2 {{ background: var(--c3); border-color: var(--c3); color: #fff; }}
  .pill.active-3 {{ background: var(--c4); border-color: var(--c4); color: #fff; }}
  .pill.disabled {{ opacity: 0.4; cursor: not-allowed; }}

  /* Chart */
  .chart-card {{
    background: #fff;
    border: 1px solid #e4e8ef;
    border-radius: 10px;
    padding: 4px;
    margin-bottom: 16px;
  }}
  #bubble-chart {{ width: 100%; height: 600px; }}

  /* Summary stats */
  .stats-row {{
    display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap;
  }}
  .stat-card {{
    background: #fff; border: 1px solid #e4e8ef; border-radius: 8px;
    padding: 12px 16px; flex: 1; min-width: 120px;
  }}
  .stat-label {{ font-size: 0.70rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--warm-gray); }}
  .stat-value {{ font-size: 1.3rem; font-weight: 700; color: var(--charcoal); margin-top: 2px; }}
  .stat-sub {{ font-size: 0.72rem; color: var(--warm-gray); margin-top: 1px; }}

  /* Footer */
  .page-footer {{
    border-top: 1px solid #e4e8ef;
    margin-top: 8px;
    padding-top: 14px;
    font-size: 0.72rem;
    color: var(--warm-gray);
    display: flex; justify-content: space-between; flex-wrap: wrap; gap: 6px;
  }}
  .footer-update {{ display: flex; align-items: center; gap: 6px; }}
  .update-indicator {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}
  .update-indicator.fresh {{ background: #2ca02c; }}
  .update-indicator.stale {{ background: #d4a800; }}

  @media (max-width: 600px) {{
    .page-header {{ padding: 16px; }}
    .main {{ padding: 12px; }}
    #bubble-chart {{ height: 420px; }}
  }}
</style>
</head>
<body>

<header class="page-header">
  <h1>&#128200; EMB Holdings — Duration vs Yield</h1>
  <p>iShares JP Morgan USD Emerging Markets Bond ETF · Individual bond positions</p>
  <div class="badges">
    <span class="badge badge-holdings">Holdings date: {holdings_date}</span>
    <span class="badge {update_class}">{update_badge}</span>
  </div>
</header>

<main class="main">

  <div class="stats-row" id="stats-row">
    <!-- populated by JS -->
  </div>

  <div class="selector-panel">
    <h3>Select Countries to Display</h3>
    <p class="selector-hint">Choose up to <strong>4 countries</strong>. Each country shows all its bonds as bubbles (size = market value).</p>
    <div class="country-pills" id="country-pills">
      <!-- populated by JS -->
    </div>
  </div>

  <div class="chart-card">
    <div id="bubble-chart"></div>
  </div>

  <div class="page-footer">
    <div class="footer-update">
      <span class="update-indicator {'fresh' if payload['is_fresh'] else 'stale'}"></span>
      <span id="footer-update-text">{update_badge}</span>
    </div>
    <div>
      Source: <a href="https://www.ishares.com/us/products/239572/" target="_blank" rel="noopener">iShares EMB</a>
      &nbsp;|&nbsp; Bubble size = market value &nbsp;|&nbsp; Fixed income holdings only
    </div>
  </div>

</main>

<script>
const DATA = {data_json};

// ── State ──────────────────────────────────────────────────────────────────
const COLORS = ['#0072B2', '#E69F00', '#009E73', '#CC79A7'];
const MAX_COUNTRIES = 4;
let selected = []; // array of country names, in selection order

// ── Init ───────────────────────────────────────────────────────────────────
function init() {{
  renderStats();
  // Default: pick the 4 largest countries by total market value
  const ranked = rankCountries();
  const defaults = ranked.slice(0, 4).map(d => d.country);
  defaults.forEach(c => addCountry(c));
  renderPills(); // must come AFTER defaults are added so active/disabled state is correct
  renderChart();
}}

function rankCountries() {{
  const mv = {{}};
  DATA.bonds.forEach(b => {{
    mv[b.country] = (mv[b.country] || 0) + b.market_value;
  }});
  return Object.entries(mv)
    .map(([country, total]) => ({{ country, total }}))
    .sort((a, b) => b.total - a.total);
}}

// ── Stats ──────────────────────────────────────────────────────────────────
function renderStats() {{
  const el = document.getElementById('stats-row');
  const totalMV = DATA.bonds.reduce((s, b) => s + (b.market_value || 0), 0);
  const wtAvgDur = wavg(DATA.bonds, 'duration', 'market_value');
  const wtAvgYTM = wavg(DATA.bonds, 'ytm', 'market_value');

  el.innerHTML = `
    <div class="stat-card">
      <div class="stat-label">Total Holdings</div>
      <div class="stat-value">${{DATA.bond_count}}</div>
      <div class="stat-sub">fixed income bonds</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Countries</div>
      <div class="stat-value">${{DATA.country_count}}</div>
      <div class="stat-sub">in the fund</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Avg Duration</div>
      <div class="stat-value">${{wtAvgDur.toFixed(1)}}y</div>
      <div class="stat-sub">market-value weighted</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Avg YTM</div>
      <div class="stat-value">${{wtAvgYTM.toFixed(2)}}%</div>
      <div class="stat-sub">market-value weighted</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Total Market Value</div>
      <div class="stat-value">${{fmtMV(totalMV)}}</div>
      <div class="stat-sub">displayed holdings</div>
    </div>
  `;
}}

function wavg(bonds, field, wField) {{
  let sumW = 0, sumWX = 0;
  bonds.forEach(b => {{
    const w = b[wField] || 0;
    sumW += w;
    sumWX += w * (b[field] || 0);
  }});
  return sumW > 0 ? sumWX / sumW : 0;
}}

function fmtMV(v) {{
  if (v >= 1e9) return (v / 1e9).toFixed(1) + 'B';
  if (v >= 1e6) return (v / 1e6).toFixed(0) + 'M';
  return v.toFixed(0);
}}

// ── Pills ──────────────────────────────────────────────────────────────────
function renderPills() {{
  const container = document.getElementById('country-pills');
  container.innerHTML = '';
  DATA.countries.forEach(country => {{
    const idx = selected.indexOf(country);
    const isActive = idx >= 0;
    const isDisabled = !isActive && selected.length >= MAX_COUNTRIES;
    const pill = document.createElement('span');
    pill.className = 'pill' + (isActive ? ' active-' + idx : '') + (isDisabled ? ' disabled' : '');
    pill.textContent = country;
    pill.dataset.country = country;
    pill.addEventListener('click', () => onPillClick(country));
    container.appendChild(pill);
  }});
}}

function onPillClick(country) {{
  const idx = selected.indexOf(country);
  if (idx >= 0) {{
    // Deselect
    selected.splice(idx, 1);
  }} else {{
    if (selected.length >= MAX_COUNTRIES) return; // silently ignore
    selected.push(country);
  }}
  renderPills();
  renderChart();
}}

function addCountry(country) {{
  if (!selected.includes(country) && selected.length < MAX_COUNTRIES) {{
    selected.push(country);
  }}
}}

// ── Chart ──────────────────────────────────────────────────────────────────
function renderChart() {{
  const traces = [];

  if (selected.length === 0) {{
    // Show empty placeholder
    Plotly.react('bubble-chart', [], getLayout('Select countries above to display bonds'));
    return;
  }}

  // Compute size scale: sqrt(mv), normalized so max = 60
  const allBonds = DATA.bonds.filter(b => selected.includes(b.country));
  const maxMV = Math.max(...allBonds.map(b => b.market_value || 1));

  selected.forEach((country, colorIdx) => {{
    const bonds = DATA.bonds.filter(b => b.country === country);
    if (bonds.length === 0) return;

    const x = bonds.map(b => b.duration);
    const y = bonds.map(b => b.ytm);
    const sizes = bonds.map(b => {{
      const s = Math.sqrt((b.market_value || 1) / maxMV) * 60;
      return Math.max(s, 4);
    }});
    const text = bonds.map(b => `${{b.name}}<br>`
      + `Duration: ${{b.duration.toFixed(1)}}y<br>`
      + `YTM: ${{b.ytm.toFixed(2)}}%<br>`
      + (b.coupon != null ? `Coupon: ${{b.coupon.toFixed(2)}}%<br>` : '')
      + (b.maturity ? `Maturity: ${{b.maturity}}<br>` : '')
      + `Market Value: $${{fmtMV(b.market_value)}}<br>`
      + `Weight: ${{b.weight.toFixed(2)}}%`
    );

    traces.push({{
      type: 'scatter',
      mode: 'markers',
      name: country,
      x, y,
      text,
      hovertemplate: '%{{text}}<extra>' + country + '</extra>',
      marker: {{
        size: sizes,
        sizemode: 'diameter',
        color: COLORS[colorIdx],
        opacity: 0.75,
        line: {{ color: 'rgba(255,255,255,0.6)', width: 1 }},
      }},
    }});
  }});

  Plotly.react('bubble-chart', traces, getLayout());
}}

function getLayout(annotation) {{
  const layout = {{
    xaxis: {{
      title: 'Effective Duration (years)',
      gridcolor: 'rgba(200,200,200,0.4)',
      zeroline: false,
    }},
    yaxis: {{
      title: 'Yield to Maturity (%)',
      gridcolor: 'rgba(200,200,200,0.4)',
      zeroline: false,
    }},
    plot_bgcolor: '#fff',
    paper_bgcolor: '#fff',
    margin: {{ l: 60, r: 30, t: 30, b: 60 }},
    legend: {{
      orientation: 'h',
      yanchor: 'bottom',
      y: 1.01,
      xanchor: 'left',
      x: 0,
    }},
    hovermode: 'closest',
  }};
  if (annotation) {{
    layout.annotations = [{{
      text: annotation,
      xref: 'paper', yref: 'paper',
      x: 0.5, y: 0.5,
      showarrow: false,
      font: {{ size: 16, color: '#aaa' }},
    }}];
  }}
  return layout;
}}

// ── Run ────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>
"""


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    csv_text, is_fresh = fetch_csv()
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    df, as_of = parse_csv(csv_text)
    print(f"  Parsed {len(df)} rows, as-of date: {as_of!r}")

    df = clean_data(df)

    payload = build_payload(df, as_of, fetched_at, is_fresh)
    print(f"  Payload: {payload['bond_count']} bonds, {payload['country_count']} countries")

    html = generate_html(payload)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"Saved → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

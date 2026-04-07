"""
Daily US Markets Update — Gemma 4 economist analyst notes.

Checks the FRED release calendar for the past 48 hours, matches against a
whitelist of major releases, pulls the relevant data series for each match,
and generates a sell-side-style analyst note via Gemma 4 on HuggingFace.

Usage:
    FRED_API_KEY=xxx HF_TOKEN=xxx python scripts/generate_markets_update.py

GitHub Actions secrets required:
    FRED_API_KEY
    HF_TOKEN

Adding a new release: add one entry each to RELEASE_WHITELIST and RELEASE_SERIES.
"""

import os
import sys
import json
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from huggingface_hub import InferenceClient

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL_ID  = "google/gemma-4-31B-it"
FRED_BASE = "https://api.stlouisfed.org/fred"
LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", 48))
OUTPUT_DIR = Path(__file__).parent.parent / "reports" / "markets-update"

# FRED release IDs for major US macro releases.
# Add a new entry here (and in RELEASE_SERIES below) to cover more releases.
RELEASE_WHITELIST = {
    50:  "Employment Situation (NFP)",
    10:  "Consumer Price Index (CPI)",
    31:  "Producer Price Index (PPI)",
    54:  "Personal Income and Outlays (PCE)",
    53:  "Gross Domestic Product (GDP)",
    84:  "Advance Retail Sales",
    180: "Unemployment Insurance Weekly Claims",
    21:  "Industrial Production and Capacity Utilization",
}

# Series to pull for each release (FRED release_id → list of (label, series_id)).
# Months of history fetched: 13 (gives 12 MoM comparisons).
RELEASE_SERIES = {
    50: [  # NFP
        ("Nonfarm Payrolls (thousands, SA)",            "PAYEMS"),
        ("Unemployment Rate (%, SA)",                   "UNRATE"),
        ("U-6 Underemployment Rate (%, SA)",            "U6RATE"),
        ("Labor Force Participation Rate (%, SA)",      "CIVPART"),
        ("Avg Hourly Earnings, Private ($/hr, SA)",     "CES0500000003"),
        ("Avg Weekly Hours, Private (hrs, SA)",         "AWHNONAG"),
        ("Private Payrolls (thousands, SA)",            "USPRIV"),
        ("Government Payrolls (thousands, SA)",         "USGOVT"),
        ("Manufacturing Payrolls (thousands, SA)",      "MANEMP"),
        ("Long-term Unemployed 27+ weeks (thousands)",  "UEMP27OV"),
    ],
    10: [  # CPI
        ("CPI All Items (index, SA)",                   "CPIAUCSL"),
        ("CPI YoY % (SA)",                              "CPIAUCSL"),  # transform applied below
        ("Core CPI ex Food & Energy (index, SA)",       "CPILFESL"),
        ("CPI Food (index, unadj)",                     "CPIUFDSL"),
        ("CPI Energy (index, unadj)",                   "CPIENGSL"),
        ("CPI Shelter (index, SA)",                     "CUSR0000SAH1"),
        ("CPI Medical Care (index, unadj)",             "CPIMEDSL"),
    ],
    31: [  # PPI
        ("PPI Final Demand (index, SA)",                "PPIACO"),
        ("PPI ex Food & Energy (index, SA)",            "PPIFES"),
        ("PPI Goods (index, SA)",                       "PPIGFD"),
        ("PPI Services (index, SA)",                    "PPIS"),
    ],
    54: [  # PCE
        ("PCE Price Index (index, SA)",                 "PCEPI"),
        ("Core PCE Price Index (index, SA)",            "PCEPILFE"),
        ("Personal Income MoM % (SA)",                  "PI"),
        ("Personal Consumption Expenditures (bn $, SA)","PCE"),
        ("Personal Saving Rate (%, SA)",                "PSAVERT"),
    ],
    53: [  # GDP
        ("Real GDP (bn 2017$, SAAR)",                   "GDPC1"),
        ("GDP Deflator (index, SA)",                    "GDPDEF"),
        ("Real Private Investment (bn 2017$, SAAR)",    "GPDIC1"),
        ("Real Government Consumption (bn 2017$, SAAR)","GCEC1"),
        ("Real Exports (bn 2017$, SAAR)",               "EXPGSC1"),
        ("Real Imports (bn 2017$, SAAR)",               "IMPGSC1"),
    ],
    84: [  # Retail Sales
        ("Retail Sales (mn $, SA)",                     "RSAFS"),
        ("Retail Sales ex Autos (mn $, SA)",            "RSFSXMV"),
        ("Retail Sales ex Autos & Gas (mn $, SA)",      "RSFSDG"),
    ],
    180: [  # Jobless Claims
        ("Initial Jobless Claims (thousands, SA)",      "ICSA"),
        ("Continued Claims (thousands, SA)",            "CCSA"),
        ("4-Week Avg Initial Claims (thousands, SA)",   "IC4WSA"),
    ],
    21: [  # Industrial Production
        ("Industrial Production Index (index, SA)",     "INDPRO"),
        ("Capacity Utilization, Total (%, SA)",         "TCU"),
        ("Manufacturing Production (index, SA)",        "IPMAN"),
        ("Mining Production (index, SA)",               "IPB10001N"),
        ("Utilities Production (index, SA)",            "IPG2211S"),
    ],
}

SYSTEM_PROMPT = """\
You are an economist at a top investment bank. The user will provide you with \
a structured data summary of a recent US economic release. Read it carefully \
and produce a professional analyst-style note structured exactly as follows:

1. Executive Summary — 1-2 concise paragraphs outlining the overall tone and \
key policy signals.
2. Five Main Views — exactly five bullet points capturing the central messages.
3. Macro Characterization — one paragraph each on (i) growth, (ii) labor \
market, and (iii) inflation, reflecting how the data describes them.
4. Fiscal Commentary — highlight any implications for fiscal policy, \
credibility, or fiscal risks, and why they matter for monetary policy \
transmission. If none, say so briefly.
5. Policy Outlook — provide a reasoned forecast for the next Fed move (timing \
and direction), grounded in the data and balance of risks.

Style guidelines:
- Write in the tone of a sell-side economist's client note (tight, analytical, \
jargon-appropriate).
- Avoid generic filler; anchor every judgment in the numbers provided.
- Compute and reference month-on-month and year-on-year changes where relevant.\
"""


# ---------------------------------------------------------------------------
# FRED helpers
# ---------------------------------------------------------------------------

def fred_get(endpoint: str, params: dict, api_key: str) -> dict:
    params = {"api_key": api_key, "file_type": "json", **params}
    resp = requests.get(f"{FRED_BASE}/{endpoint}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def recent_release_ids(api_key: str, lookback_hours: int) -> set[int]:
    """Return FRED release IDs that published data in the last `lookback_hours`."""
    since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).strftime("%Y-%m-%d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = fred_get("releases/dates", {
        "realtime_start": since,
        "realtime_end":   today,
        "limit":          1000,
        "include_release_dates_with_no_data": "false",
    }, api_key)
    return {int(r["release_id"]) for r in data.get("release_dates", [])}


def fetch_series(series_id: str, api_key: str, limit: int = 13) -> list[dict]:
    data = fred_get("series/observations", {
        "series_id":  series_id,
        "sort_order": "desc",
        "limit":      limit,
    }, api_key)
    obs = [o for o in data.get("observations", []) if o["value"] != "."]
    return list(reversed(obs))


def build_data_block(release_id: int, release_name: str, api_key: str) -> str:
    series_list = RELEASE_SERIES.get(release_id, [])
    lines = [f"{release_name.upper()} — LATEST FRED DATA\n"]
    seen = set()
    for label, sid in series_list:
        if sid in seen:
            continue
        seen.add(sid)
        try:
            obs = fetch_series(sid, api_key)
        except Exception as e:
            print(f"  WARNING: skipping {sid} — {e}", file=sys.stderr)
            continue
        if not obs:
            continue
        lines.append(f"{label}  [{sid}]")
        for o in obs:
            lines.append(f"  {o['date'][:7]}  {float(o['value']):>12.3f}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gemma inference
# ---------------------------------------------------------------------------

def generate_note(data_block: str, hf_token: str) -> str:
    client = InferenceClient(model=MODEL_ID, token=hf_token, timeout=300)
    stream = client.chat.completions.create(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": (
                "Please analyze the following economic data and produce your economist note:\n\n"
                + data_block
            )},
        ],
        temperature=0.3,
        max_tokens=2048,
        stream=True,
    )
    parts = []
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            parts.append(delta)
            print(delta, end="", flush=True)
    print()
    return "".join(parts)


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def markdown_to_html_body(md: str) -> str:
    """Minimal markdown → HTML for the analyst note sections."""
    import re
    lines = md.split("\n")
    html_parts = []
    in_ul = False

    for line in lines:
        # H3 ### or H2 ##
        if line.startswith("### "):
            if in_ul: html_parts.append("</ul>"); in_ul = False
            html_parts.append(f"<h3>{line[4:].strip()}</h3>")
        elif line.startswith("## "):
            if in_ul: html_parts.append("</ul>"); in_ul = False
            html_parts.append(f"<h2>{line[3:].strip()}</h2>")
        elif line.startswith("# "):
            if in_ul: html_parts.append("</ul>"); in_ul = False
            html_parts.append(f"<h2>{line[2:].strip()}</h2>")
        # Numbered section headings like "1. Executive Summary"
        elif re.match(r"^\d+\.\s+\*\*(.+?)\*\*", line):
            if in_ul: html_parts.append("</ul>"); in_ul = False
            title = re.sub(r"^\d+\.\s+\*\*(.+?)\*\*.*", r"\1", line)
            rest  = re.sub(r"^\d+\.\s+\*\*.+?\*\*\s*[—-]?\s*", "", line)
            html_parts.append(f'<h3 class="section-heading">{title}</h3>')
            if rest.strip():
                html_parts.append(f"<p>{_inline(rest)}</p>")
        # Bullet points
        elif line.strip().startswith("- ") or line.strip().startswith("* "):
            if not in_ul: html_parts.append("<ul>"); in_ul = True
            html_parts.append(f"<li>{_inline(line.strip()[2:])}</li>")
        # Blank line
        elif not line.strip():
            if in_ul: html_parts.append("</ul>"); in_ul = False
            html_parts.append("")
        else:
            if in_ul: html_parts.append("</ul>"); in_ul = False
            html_parts.append(f"<p>{_inline(line)}</p>")

    if in_ul:
        html_parts.append("</ul>")
    return "\n".join(html_parts)


def _inline(text: str) -> str:
    import re
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         text)
    return text


def render_html(release_name: str, date_str: str, data_block: str, note_md: str) -> str:
    note_html = markdown_to_html_body(note_md)
    # Extract key metrics for summary cards (latest value of first 3 series)
    card_html = ""
    lines = data_block.split("\n")
    cards = []
    current_label = None
    for line in lines:
        if "[" in line and "]" in line and not line.startswith(" "):
            current_label = line.split("[")[0].strip()
        elif line.startswith("  ") and current_label:
            parts = line.split()
            if len(parts) == 2:
                cards.append((current_label, parts[0], parts[1]))
                current_label = None
        if len(cards) == 4:
            break

    for label, period, value in cards:
        short = label.split("(")[0].strip()
        card_html += f"""
        <div class="card">
            <h3>{value}</h3>
            <p>{short}</p>
            <p class="card-period">{period}</p>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{release_name} — {date_str}</title>
    <style>
        :root {{
            --fed-blue: #003366;
            --fed-gold: #b8860b;
            --light-bg: #f8f9fa;
            --border-color: #dee2e6;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                         'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #fff;
        }}
        header {{
            background: linear-gradient(135deg, var(--fed-blue) 0%, #004080 100%);
            color: white;
            padding: 30px;
            border-radius: 8px;
            margin-bottom: 30px;
        }}
        header h1 {{ font-size: 2rem; margin-bottom: 8px; }}
        header .subtitle {{ opacity: 0.9; font-size: 1.1rem; }}
        header .meta {{ opacity: 0.75; font-size: 0.9rem; margin-top: 6px; }}
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .card {{
            background: var(--light-bg);
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid var(--fed-blue);
        }}
        .card h3 {{ color: var(--fed-blue); font-size: 1.8rem; margin-bottom: 4px; }}
        .card p {{ color: #666; font-size: 0.85rem; }}
        .card .card-period {{ color: #999; font-size: 0.8rem; }}
        .note-body {{ max-width: 860px; }}
        .note-body h2 {{
            color: var(--fed-blue);
            border-bottom: 2px solid var(--fed-blue);
            padding-bottom: 8px;
            margin: 30px 0 15px;
            font-size: 1.3rem;
        }}
        .note-body h3 {{
            color: var(--fed-blue);
            margin: 25px 0 10px;
            font-size: 1.1rem;
        }}
        .note-body h3.section-heading {{
            background: var(--light-bg);
            border-left: 4px solid var(--fed-gold);
            padding: 8px 14px;
            border-radius: 0 4px 4px 0;
            margin: 28px 0 12px;
        }}
        .note-body p {{ margin-bottom: 12px; color: #444; }}
        .note-body ul {{ margin: 10px 0 16px 24px; }}
        .note-body li {{ margin-bottom: 6px; color: #444; }}
        .note-body strong {{ color: #222; }}
        .data-block {{
            background: #f4f6f9;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 20px;
            margin-top: 40px;
            font-family: 'SF Mono', 'Fira Code', monospace;
            font-size: 0.8rem;
            color: #555;
            white-space: pre;
            overflow-x: auto;
        }}
        .data-block summary {{
            font-family: inherit;
            font-size: 0.9rem;
            cursor: pointer;
            color: var(--fed-blue);
            margin-bottom: 12px;
            font-weight: 600;
        }}
        footer {{
            margin-top: 50px;
            padding-top: 20px;
            border-top: 1px solid var(--border-color);
            font-size: 0.85rem;
            color: #888;
        }}
        footer a {{ color: var(--fed-blue); }}
    </style>
</head>
<body>
    <header>
        <h1>📊 {release_name}</h1>
        <div class="subtitle">Economist Analyst Note</div>
        <div class="meta">Generated {date_str} · Data: FRED · Model: Gemma 4 31B</div>
    </header>

    <div class="summary-cards">
        {card_html}
    </div>

    <div class="note-body">
        {note_html}
    </div>

    <details class="data-block">
        <summary>Raw data fed to model</summary>
{data_block}
    </details>

    <footer>
        <p>Data sourced from <a href="https://fred.stlouisfed.org">FRED</a> ·
        Analysis generated by <a href="https://huggingface.co/google/gemma-4-31B-it">Gemma 4 31B-IT</a> ·
        <a href="index.html">← All reports</a></p>
    </footer>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Index page
# ---------------------------------------------------------------------------

def update_index(reports: list[dict]) -> None:
    """Regenerate the markets-update index.html from all HTML files in the dir."""
    existing = sorted(OUTPUT_DIR.glob("markets-update-*.html"), reverse=True)

    rows = ""
    for f in existing:
        name = f.stem  # e.g. markets-update-2026-04-07-nfp
        parts = name.split("-", 4)  # ['markets', 'update', 'YYYY', 'MM', 'DD-slug']
        if len(parts) >= 5:
            date_part = "-".join(parts[2:5])
            slug = parts[5] if len(parts) > 5 else ""
        else:
            date_part = ""
            slug = ""
        rows += f'<tr><td><a href="{f.name}">{f.stem}</a></td><td>{date_part}</td></tr>\n'

    # Also include any just-generated reports passed in
    for r in reports:
        fname = Path(r["path"]).name
        if not any(fname in row for row in rows):
            rows += f'<tr><td><a href="{fname}">{Path(r["path"]).stem}</a></td><td>{r["date"]}</td></tr>\n'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>US Markets Update — Archive</title>
    <style>
        body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 40px auto; padding: 20px; color: #333; }}
        h1 {{ color: #003366; border-bottom: 2px solid #003366; padding-bottom: 10px; margin-bottom: 24px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ background: #003366; color: white; padding: 12px; text-align: left; }}
        td {{ padding: 10px 12px; border-bottom: 1px solid #dee2e6; }}
        tr:hover {{ background: #f8f9fa; }}
        a {{ color: #003366; }}
        .meta {{ color: #888; font-size: 0.9rem; margin-bottom: 20px; }}
    </style>
</head>
<body>
    <h1>📊 US Markets Update</h1>
    <p class="meta">Daily analyst notes on major US economic releases. Generated by Gemma 4 31B via FRED data.</p>
    <table>
        <thead><tr><th>Report</th><th>Date</th></tr></thead>
        <tbody>
{rows}
        </tbody>
    </table>
</body>
</html>"""

    index_path = OUTPUT_DIR / "index.html"
    index_path.write_text(html, encoding="utf-8")
    print(f"  Index updated: {index_path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    fred_key = os.environ.get("FRED_API_KEY")
    hf_token = os.environ.get("HF_TOKEN")

    if not fred_key:
        print("ERROR: FRED_API_KEY not set.", file=sys.stderr); sys.exit(1)
    if not hf_token:
        print("ERROR: HF_TOKEN not set.", file=sys.stderr); sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"Checking FRED release calendar (last {LOOKBACK_HOURS}h) ...", file=sys.stderr)
    fired = recent_release_ids(fred_key, LOOKBACK_HOURS)
    matched = {rid: name for rid, name in RELEASE_WHITELIST.items() if rid in fired}

    if not matched:
        print("No whitelisted releases in the last 48h — nothing to do.", file=sys.stderr)
        sys.exit(0)

    print(f"Matched releases: {list(matched.values())}", file=sys.stderr)

    generated = []
    for release_id, release_name in matched.items():
        slug = release_name.split("(")[0].strip().lower().replace(" ", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")
        out_path = OUTPUT_DIR / f"markets-update-{today}-{slug}.html"

        if out_path.exists():
            print(f"  Already exists, skipping: {out_path.name}", file=sys.stderr)
            generated.append({"path": str(out_path), "date": today})
            continue

        print(f"\n--- {release_name} ---", file=sys.stderr)
        print(f"  Fetching FRED series ...", file=sys.stderr)
        data_block = build_data_block(release_id, release_name, fred_key)

        print(f"  Generating analyst note via {MODEL_ID} ...\n", file=sys.stderr)
        note_md = generate_note(data_block, hf_token)

        html = render_html(release_name, today, data_block, note_md)
        out_path.write_text(html, encoding="utf-8")
        print(f"\n  Saved: {out_path}", file=sys.stderr)
        generated.append({"path": str(out_path), "date": today})

    update_index(generated)
    print(f"\nDone. {len(generated)} report(s) written.", file=sys.stderr)


if __name__ == "__main__":
    main()

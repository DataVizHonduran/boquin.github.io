#!/usr/bin/env python3
"""
CTA Signals Commentary — Daily AI Analysis
Scrapes boquin.xyz/reports/cta-signals/, feeds content to Gemma 4,
and injects a structured commentary section at the bottom of index.html.

Usage:
    HF_TOKEN=hf_xxx python3 scripts/cta_commentary.py

Required environment variables:
    HF_TOKEN  — HuggingFace API token

Output:
    reports/cta-signals/index.html  (commentary injected before </body>)
    reports/cta-signals/commentary-YYYY-MM-DD.md  (archive copy)
"""

import os
import sys
import re
import time
import markdown as md_lib
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from huggingface_hub import InferenceClient

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL_ID = "google/gemma-4-31B-it"
TARGET_URL = "https://boquin.xyz/reports/cta-signals/"
OUTPUT_DIR = Path("reports/cta-signals")
INDEX_HTML = OUTPUT_DIR / "index.html"

MARKER_START = "<!-- cta-commentary-start -->"
MARKER_END   = "<!-- cta-commentary-end -->"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; CTACommentary/1.0; "
        "+https://github.com/DataVizHonduran/boquin.github.io)"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
}

# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

def scrape_data() -> str:
    resp = requests.get(TARGET_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text[:8000]


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

def call_gemma(messages: list[dict], hf_token: str, max_tokens: int = 2048) -> str:
    client = InferenceClient(model=MODEL_ID, token=hf_token, timeout=300)
    for attempt in range(5):
        try:
            stream = client.chat.completions.create(
                messages=messages,
                temperature=0.2,
                max_tokens=max_tokens,
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
        except Exception as e:
            is_rate_limit = any(x in str(e) for x in ("429", "503", "Too Many Requests", "Service Temporarily Unavailable"))
            if is_rate_limit and attempt < 4:
                wait = 60 * (attempt + 1)
                print(f"\n  HF rate limit — waiting {wait}s (attempt {attempt+1}/5) ...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


def generate_report(data: str, hf_token: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = f"""[ROLE]: Senior Macro/Quant Analyst specializing in CTA trend-following and exhaustion signals.

[TASK]: Analyze the following content scraped from a live CTA positioning dashboard as of {today}.
Produce a structured Markdown commentary covering:
1. Current positioning extremes (most overbought/oversold currencies)
2. Exhaustion signal count and what it implies for trend momentum
3. Key divergences between fast and slow mode signals
4. Overall risk sentiment (risk-on / risk-off / mixed)
5. One actionable watch-list item for the next 5 trading days

[FORMAT]:
- Use Markdown headers (##, ###)
- Include a summary table: | Currency | Mode | Signal | Score |
- Use bullet points for observations
- Keep total length under 600 words

[DATA]:
{data}"""

    return call_gemma([{"role": "user", "content": prompt}], hf_token)


# ---------------------------------------------------------------------------
# HTML injection
# ---------------------------------------------------------------------------

def build_commentary_block(commentary_md: str, generated_at: str) -> str:
    body_html = md_lib.markdown(commentary_md, extensions=["tables"])
    return f"""{MARKER_START}
<div style="max-width:1400px;margin:40px auto 0;padding:0 20px 40px;">
  <div style="background:white;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,0.1);padding:30px;">
    <div style="border-left:4px solid #007bff;padding-left:16px;margin-bottom:20px;">
      <h2 style="color:#333;margin:0 0 4px;">AI Commentary</h2>
      <p style="color:#666;font-size:0.85em;margin:0;">Generated {generated_at} UTC &nbsp;·&nbsp; google/gemma-4-31B-it</p>
    </div>
    <div style="line-height:1.7;color:#444;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
      <style>
        .cta-commentary table {{border-collapse:collapse;width:100%;margin:16px 0;}}
        .cta-commentary th,
        .cta-commentary td {{border:1px solid #dee2e6;padding:8px 12px;text-align:left;}}
        .cta-commentary th {{background:#f8f9fa;font-weight:600;}}
        .cta-commentary h2,.cta-commentary h3 {{color:#333;margin:20px 0 8px;}}
        .cta-commentary ul {{padding-left:20px;}}
        .cta-commentary li {{margin:4px 0;}}
      </style>
      <div class="cta-commentary">{body_html}</div>
    </div>
  </div>
</div>
{MARKER_END}"""


def inject_into_index(block: str) -> None:
    if not INDEX_HTML.exists():
        print(f"  WARNING: {INDEX_HTML} not found — skipping injection", file=sys.stderr)
        return

    html = INDEX_HTML.read_text(encoding="utf-8")

    # Replace existing block if present, otherwise insert before </body>
    if MARKER_START in html:
        html = re.sub(
            re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
            block,
            html,
            flags=re.DOTALL,
        )
    else:
        html = html.replace("</body>", block + "\n</body>")

    INDEX_HTML.write_text(html, encoding="utf-8")
    print(f"  Injected commentary into {INDEX_HTML}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print("ERROR: HF_TOKEN environment variable not set", file=sys.stderr)
        sys.exit(1)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    print(f"Scraping {TARGET_URL} ...")
    data = scrape_data()
    print(f"  Extracted {len(data)} chars of page content")

    print("\nGenerating commentary via Gemma 4 ...")
    commentary = generate_report(data, hf_token)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Archive copy
    dated_path = OUTPUT_DIR / f"commentary-{today}.md"
    dated_path.write_text(commentary, encoding="utf-8")
    print(f"\nWrote archive: {dated_path}")

    # Inject into index.html
    block = build_commentary_block(commentary, generated_at)
    inject_into_index(block)

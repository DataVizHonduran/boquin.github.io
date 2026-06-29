#!/usr/bin/env python3
"""
Iran/US Diplomacy OSINT Monitor — Standalone Script

Tracks official statements on Iran/US diplomacy from third-party regional
and multilateral actors only (no US, no Iran sources).

Data sources (zero paid APIs):
  - iaea.org          — nuclear safeguards statements (direct scrape)
  - mid.ru            — Russia MFA official statements (direct scrape)
  - fmprc.gov.cn      — China MFA spokesperson briefings (direct scrape)
  - press.un.org      — UN Secretary-General / UNSC (direct scrape)
  - eeas.europa.eu    — EU External Action Service (direct scrape)
  - Google News RSS   — targeted queries for Oman, Qatar, Saudi, Turkey, Iraq MFAs

LLM layer:
  - HuggingFace Inference API (google/gemma-4-31B-it)

Usage:
    HF_TOKEN=hf_xxx python3 scripts/iran_diplo_standalone.py
    HF_TOKEN=hf_xxx python3 scripts/iran_diplo_standalone.py --days 14
    HF_TOKEN=hf_xxx python3 scripts/iran_diplo_standalone.py --dry-run
    HF_TOKEN=hf_xxx python3 scripts/iran_diplo_standalone.py --output-dir reports/iran-diplo/

Required environment variables:
    HF_TOKEN  — HuggingFace API token

Output:
    reports/iran-diplo/iran-diplo-YYYY-MM-DD.html
    reports/iran-diplo/iran-diplo-YYYY-MM-DD.md
"""

import os
import sys
import re
import time
import argparse
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urljoin
from pathlib import Path

import requests
import feedparser
import markdown as md_lib
from bs4 import BeautifulSoup
from huggingface_hub import InferenceClient

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL_ID = "google/gemma-4-31B-it"

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; IranDiploMonitor/1.0; "
        "+https://github.com/DataVizHonduran/boquin.github.io)"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Encoding": "gzip, deflate",
}

RATE_LIMIT_SLEEP = 0.5

# ---------------------------------------------------------------------------
# Actor definitions — official third-party sources only (no US, no Iran)
# ---------------------------------------------------------------------------

ACTORS = {
    "Oman MFA": {
        "country": "Oman",
        "institution": "Ministry of Foreign Affairs",
        "role": "Back-channel mediator",
        "baseline": "Pro-engagement. Historic host of US-Iran back-channel talks (2013, 2023). "
                    "Maintains open diplomatic channels with Tehran and Washington simultaneously.",
    },
    "Qatar MFA": {
        "country": "Qatar",
        "institution": "Ministry of Foreign Affairs",
        "role": "Active mediator / message conduit",
        "baseline": "Constructive engagement. Hosts US CENTCOM and maintains Tehran ties. "
                    "Often acts as intermediary for prisoner swaps and indirect communications.",
    },
    "EU High Representative / E3": {
        "country": "EU + France, Germany, UK",
        "institution": "EEAS / E3 Foreign Ministries",
        "role": "JCPOA coordinator and formal party",
        "baseline": "Pro-revival of nuclear deal. E3 activated dispute resolution mechanism in 2020. "
                    "Supports diplomacy but has threatened snapback sanctions. Key interlocutor in Vienna talks.",
    },
    "Russia MFA": {
        "country": "Russia",
        "institution": "Ministry of Foreign Affairs",
        "role": "JCPOA party / sanctions opponent",
        "baseline": "Supports Iran sanctions relief and opposes US pressure campaign. "
                    "Has geopolitical interest in a weakened US position in the region. "
                    "Participated in Vienna JCPOA talks. Relations with Iran deepened post-2022.",
    },
    "China MFA": {
        "country": "China",
        "institution": "Ministry of Foreign Affairs",
        "role": "JCPOA party / economic partner",
        "baseline": "Opposes US unilateral sanctions. Largest buyer of Iranian oil under sanctions. "
                    "25-year strategic partnership with Iran signed 2021. "
                    "Supports diplomacy but cautious about overt mediation role.",
    },
    "IAEA": {
        "country": "International",
        "institution": "International Atomic Energy Agency",
        "role": "Nuclear inspection and safeguards authority",
        "baseline": "Technically neutral but reports to UNSC. Director General Grossi has repeatedly "
                    "stated Iran is not cooperating fully with inspections. "
                    "Has reported 60% enrichment and reduced inspector access since 2021.",
    },
    "UN Secretary-General": {
        "country": "International",
        "institution": "United Nations",
        "role": "Multilateral mediator",
        "baseline": "Calls for diplomacy, warns against military escalation. "
                    "UNSC resolutions on Iran nuclear program remain in force. "
                    "SG office channels communications but has limited direct role.",
    },
    "Saudi Arabia MFA": {
        "country": "Saudi Arabia",
        "institution": "Ministry of Foreign Affairs",
        "role": "Regional power / skeptic",
        "baseline": "Historically opposed to Iran deal without regional security components. "
                    "China-brokered Saudi-Iran normalization (Mar 2023) shifted posture. "
                    "Now cautiously supports diplomacy but demands Iran stop proxy interference.",
    },
    "Turkey MFA": {
        "country": "Turkey",
        "institution": "Ministry of Foreign Affairs",
        "role": "Bridge state / trade partner",
        "baseline": "Pragmatic. Maintains trade relations with Iran despite sanctions. "
                    "NATO member but does not enforce US sanctions on Tehran. "
                    "Supports diplomacy; occasionally offers mediation.",
    },
    "Iraq MFA": {
        "country": "Iraq",
        "institution": "Ministry of Foreign Affairs",
        "role": "Geographic and political bridge",
        "baseline": "Deeply tied to both Iran and the US by treaty and proximity. "
                    "Baghdad has hosted Iran-Saudi talks. "
                    "Iraqi government avoids direct involvement in nuclear file but monitors closely.",
    },
}

# ---------------------------------------------------------------------------
# Google News RSS queries — targeted to official actors and Iran diplomacy
# ---------------------------------------------------------------------------

NEWS_QUERIES = [
    '"Oman" "Iran" "foreign minister" OR "MFA" OR "statement" 2026',
    '"Qatar" Iran foreign minister official statement 2026',
    '"Saudi Arabia" Iran foreign minister official statement 2026',
    '"UAE" OR "United Arab Emirates" Iran foreign minister statement 2026',
    '"Turkey" Iran MFA foreign minister official 2026',
    '"Iraq" Iran foreign minister official statement 2026',
    'IAEA Iran nuclear safeguards inspection 2026',
    '"JCPOA" OR "nuclear deal" EU E3 France Germany UK Iran 2026',
    'Russia MFA "Iran" nuclear diplomacy official 2026',
    'China MFA "Iran" nuclear diplomacy official 2026',
    '"UN Secretary-General" OR "UNSC" Iran nuclear 2026',
    '"Badr al-Busaidi" OR "Omani" Iran talks 2026',
    '"Mohammed bin Abdulrahman" Qatar Iran 2026',
    '"Sergei Lavrov" OR "Zakharova" Iran nuclear 2026',
    '"Wang Yi" OR "Lin Jian" Iran nuclear diplomacy 2026',
    '"Rafael Grossi" IAEA Iran 2026',
    '"Kaja Kallas" OR "EU" Iran nuclear 2026',
]

# ---------------------------------------------------------------------------
# Layer 1 — Direct scraping per official source
# ---------------------------------------------------------------------------

def _get(url: str, timeout: int = 20) -> requests.Response | None:
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=BASE_HEADERS, timeout=timeout)
            if resp.status_code == 200:
                time.sleep(RATE_LIMIT_SLEEP)
                return resp
            if resp.status_code in (429, 503):
                wait = 30 * (attempt + 1)
                print(f"  Rate limited ({resp.status_code}) — waiting {wait}s ...", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"  HTTP {resp.status_code} for {url}", file=sys.stderr)
                return None
        except Exception as e:
            print(f"  Fetch error ({url}): {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    return None


def _soup(url: str) -> BeautifulSoup | None:
    resp = _get(url)
    if resp is None:
        return None
    return BeautifulSoup(resp.text, "html.parser")


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _parse_rss_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _is_iran_relevant(text: str) -> bool:
    """Return True if text contains Iran/nuclear-deal/JCPOA keywords."""
    text_lower = text.lower()
    keywords = [
        "iran", "tehran", "jcpoa", "nuclear deal", "enrichment", "sanctions",
        "hormuz", "iaea", "safeguards", "natanz", "fordow",
    ]
    return any(k in text_lower for k in keywords)


def scrape_iaea(days: int = 14) -> list[dict]:
    """Scrape iaea.org/newscenter/news for Iran-related press releases."""
    url = "https://www.iaea.org/newscenter/news"
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    print(f"Fetching IAEA news: {url}", file=sys.stderr)
    soup = _soup(url)
    if not soup:
        return []

    items = []
    seen: set[str] = set()

    for article in soup.find_all(["article", "div", "li"], limit=200):
        # Look for links that might be news items
        for link in article.find_all("a", href=True):
            href = link.get("href", "")
            title = link.get_text(strip=True)
            if not title or len(title) < 15:
                continue
            if not any(k in href for k in ["/newscenter/news/", "/press-releases/", "/statements/"]):
                continue
            full_url = href if href.startswith("http") else f"https://www.iaea.org{href}"
            if full_url in seen:
                continue
            if not _is_iran_relevant(title):
                continue
            seen.add(full_url)

            # Try to extract date from surrounding text
            parent_text = article.get_text(separator=" ", strip=True)
            pub_date = _parse_date_from_text(parent_text)
            if pub_date and pub_date < cutoff:
                continue

            items.append({
                "actor": "IAEA",
                "source": "IAEA Press Release",
                "date": pub_date.strftime("%Y-%m-%d") if pub_date else "",
                "title": title,
                "url": full_url,
                "summary": "",
            })

    print(f"  IAEA: {len(items)} Iran-related items found.", file=sys.stderr)
    return items


def scrape_russia_mfa(days: int = 14) -> list[dict]:
    """Scrape Russia MFA official statements in English."""
    url = "https://mid.ru/en/press_service/spokesman/official_statement/"
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    print(f"Fetching Russia MFA: {url}", file=sys.stderr)
    soup = _soup(url)
    if not soup:
        return []

    items = []
    seen: set[str] = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        title = link.get_text(strip=True)
        if not title or len(title) < 15:
            continue
        if not _is_iran_relevant(title):
            continue
        full_url = href if href.startswith("http") else f"https://mid.ru{href}"
        if full_url in seen:
            continue
        seen.add(full_url)

        parent_text = link.find_parent().get_text(separator=" ", strip=True) if link.find_parent() else ""
        pub_date = _parse_date_from_text(parent_text) or _parse_date_from_text(href)
        if pub_date and pub_date < cutoff:
            continue

        items.append({
            "actor": "Russia MFA",
            "source": "Russia MFA Official Statement",
            "date": pub_date.strftime("%Y-%m-%d") if pub_date else "",
            "title": title,
            "url": full_url,
            "summary": "",
        })

    print(f"  Russia MFA: {len(items)} Iran-related items found.", file=sys.stderr)
    return items


def scrape_china_mfa(days: int = 14) -> list[dict]:
    """Scrape China MFA spokesperson briefing press releases."""
    url = "https://www.fmprc.gov.cn/mfa_eng/xwfw_665399/s2510_665401/"
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    print(f"Fetching China MFA: {url}", file=sys.stderr)
    soup = _soup(url)
    if not soup:
        return []

    items = []
    seen: set[str] = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        title = link.get_text(strip=True)
        if not title or len(title) < 15:
            continue
        if not _is_iran_relevant(title):
            continue
        full_url = href if href.startswith("http") else f"https://www.fmprc.gov.cn{href}"
        if full_url in seen:
            continue
        seen.add(full_url)

        parent_text = link.find_parent().get_text(separator=" ", strip=True) if link.find_parent() else ""
        pub_date = _parse_date_from_text(parent_text) or _parse_date_from_text(href)
        if pub_date and pub_date < cutoff:
            continue

        items.append({
            "actor": "China MFA",
            "source": "China MFA Spokesperson Briefing",
            "date": pub_date.strftime("%Y-%m-%d") if pub_date else "",
            "title": title,
            "url": full_url,
            "summary": "",
        })

    print(f"  China MFA: {len(items)} Iran-related items found.", file=sys.stderr)
    return items


def scrape_un_press(days: int = 14) -> list[dict]:
    """Scrape press.un.org for SG and UNSC statements on Iran."""
    url = "https://press.un.org/en/content/secretary-general"
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    print(f"Fetching UN press: {url}", file=sys.stderr)
    soup = _soup(url)
    if not soup:
        return []

    items = []
    seen: set[str] = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        title = link.get_text(strip=True)
        if not title or len(title) < 15:
            continue
        if not _is_iran_relevant(title):
            continue
        full_url = href if href.startswith("http") else f"https://press.un.org{href}"
        if full_url in seen:
            continue
        seen.add(full_url)

        parent_text = link.find_parent().get_text(separator=" ", strip=True) if link.find_parent() else ""
        pub_date = _parse_date_from_text(parent_text)
        if pub_date and pub_date < cutoff:
            continue

        items.append({
            "actor": "UN Secretary-General",
            "source": "UN Press Release",
            "date": pub_date.strftime("%Y-%m-%d") if pub_date else "",
            "title": title,
            "url": full_url,
            "summary": "",
        })

    print(f"  UN press: {len(items)} Iran-related items found.", file=sys.stderr)
    return items


def scrape_eeas(days: int = 14) -> list[dict]:
    """Scrape EU EEAS press releases for Iran/JCPOA items."""
    url = "https://www.eeas.europa.eu/eeas/press-releases_en"
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    print(f"Fetching EU EEAS: {url}", file=sys.stderr)
    soup = _soup(url)
    if not soup:
        return []

    items = []
    seen: set[str] = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        title = link.get_text(strip=True)
        if not title or len(title) < 15:
            continue
        if not _is_iran_relevant(title):
            continue
        full_url = href if href.startswith("http") else f"https://www.eeas.europa.eu{href}"
        if full_url in seen:
            continue
        seen.add(full_url)

        parent_text = link.find_parent().get_text(separator=" ", strip=True) if link.find_parent() else ""
        pub_date = _parse_date_from_text(parent_text)
        if pub_date and pub_date < cutoff:
            continue

        items.append({
            "actor": "EU High Representative / E3",
            "source": "EU EEAS Press Release",
            "date": pub_date.strftime("%Y-%m-%d") if pub_date else "",
            "title": title,
            "url": full_url,
            "summary": "",
        })

    print(f"  EU EEAS: {len(items)} Iran-related items found.", file=sys.stderr)
    return items


def _parse_date_from_text(text: str) -> datetime | None:
    """Extract a date from free-form text."""
    text = text.strip()
    patterns = [
        ("%d %B %Y",   r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b"),
        ("%B %d, %Y",  r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b"),
        ("%Y-%m-%d",   r"\b\d{4}-\d{2}-\d{2}\b"),
        ("%d/%m/%Y",   r"\b\d{1,2}/\d{1,2}/\d{4}\b"),
        ("%Y%m%d",     r"\b20\d{6}\b"),
    ]
    for fmt, pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                return datetime.strptime(m.group(), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def scrape_all_official(days: int = 14) -> list[dict]:
    """Run all Layer 1 scrapers and combine results."""
    results = []
    for fn in [scrape_iaea, scrape_russia_mfa, scrape_china_mfa, scrape_un_press, scrape_eeas]:
        try:
            results.extend(fn(days=days))
        except Exception as e:
            print(f"  Scraper {fn.__name__} failed: {e}", file=sys.stderr)
    return results


# ---------------------------------------------------------------------------
# Layer 2 — Google News RSS
# ---------------------------------------------------------------------------

def search_google_news(query: str, max_results: int = 8) -> list[dict]:
    url = (
        f"https://news.google.com/rss/search?"
        f"q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
    )
    feed = feedparser.parse(url)
    items = []
    for entry in feed.entries[:max_results]:
        pub_date = _parse_rss_date(entry)
        items.append({
            "actor": "",  # will be inferred by LLM from title/summary
            "source": "Google News RSS",
            "query": query,
            "date": pub_date.strftime("%Y-%m-%d") if pub_date else "",
            "title": getattr(entry, "title", ""),
            "url": getattr(entry, "link", ""),
            "summary": _strip_html(getattr(entry, "summary", "")),
        })
    return items


def search_news(queries: list[str], days: int = 14) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    seen_urls: set[str] = set()
    results = []

    for q in queries:
        print(f"  News search: {q[:70]} ...", file=sys.stderr)
        for item in search_google_news(q):
            if item["url"] in seen_urls:
                continue
            if not _is_iran_relevant(item["title"] + " " + item.get("summary", "")):
                continue
            if item["date"]:
                try:
                    d = datetime.fromisoformat(item["date"]).replace(tzinfo=timezone.utc)
                    if d < cutoff:
                        continue
                except ValueError:
                    pass
            seen_urls.add(item["url"])
            results.append(item)
        time.sleep(0.5)

    print(f"  Total news items after dedup/filter: {len(results)}", file=sys.stderr)
    return results


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_context_prompt(
    official_items: list[dict],
    news_items: list[dict],
    days: int,
    today: str,
) -> str:

    actors_md = "\n".join(
        f"- **{name}** ({info['role']}, {info['country']}): {info['baseline']}"
        for name, info in ACTORS.items()
    )

    def _fmt_official(items: list[dict]) -> str:
        parts = []
        for it in items:
            chunk = f"[{it.get('date', 'n/a')}] [{it['actor']}] {it['title']}"
            if it.get("url"):
                chunk += f"\n  URL: {it['url']}"
            if it.get("summary"):
                chunk += f"\n  Summary: {it['summary'][:600]}"
            parts.append(chunk)
        return "\n\n".join(parts) if parts else "(none found)"

    def _fmt_news(items: list[dict]) -> str:
        parts = []
        for it in items:
            chunk = f"[{it.get('date', 'n/a')}] {it['title']}"
            if it.get("url"):
                chunk += f"\n  URL: {it['url']}"
            if it.get("summary"):
                chunk += f"\n  {it['summary'][:400]}"
            parts.append(chunk)
        return "\n\n".join(parts) if parts else "(none found)"

    prompt = f"""You are a seasoned intelligence analyst covering Iranian foreign policy and Middle East diplomacy. You write for a senior audience of diplomats, investors, and policy professionals who read fast and think slow — they want blunt, specific, and surprising analysis, not diplomatic boilerplate.

Today: {today}
Coverage period: last {days} days
HARD CONSTRAINT: Only cite non-US and non-Iranian official sources. Never attribute statements to US or Iranian government officials.

## Actor Background (priors — override only with direct evidence from the data)

{actors_md}

---

## RAW INTELLIGENCE DATA

### Direct Official Scrapes ({len(official_items)} items)
{_fmt_official(official_items)}

### News Coverage of Official Statements ({len(news_items)} items)
{_fmt_news(news_items)}

---

## YOUR TASK

Write a real-time intelligence brief. This is NOT a template-filling exercise. Think like a journalist who has been covering this beat for 10 years and just read everything above — what's the actual story? What's new? What's being missed? What do the silences tell you?

Structure your brief as follows:

---

## The Lead

One paragraph, 3-5 sentences. What is the single most important development in the past {days} days based on official third-party sources? Don't bury it. State the most surprising or consequential thing that happened, and what it means. If multiple actors moved in the same direction, say so and explain why that convergence matters.

## What the Data Actually Shows

3-5 focused paragraphs. Write thematically, not actor-by-actor. Connect dots across sources. Each paragraph should make a specific analytical claim and back it with the data above. Good themes to consider (use the ones that are actually supported by your data — don't force themes that aren't):

- Where are mediators (Oman, Qatar) actually focusing their energy right now, and is it different from what media is covering?
- What are Russia and China's stated positions, and do they diverge from each other in any subtle way?
- What is the IAEA's operational stance — is the "nuclear track" moving independently of the political track?
- What are Gulf states (Saudi, UAE) actually signaling vs. what their public statements say?
- Who is conspicuously silent, and what does that silence suggest?

## Divergence Watch

2-4 bullets. Where do official third-party sources directly contradict or complicate what media is reporting? Be specific — name the claim, name the source that contradicts it. If official sources CONFIRM a media claim, that's also worth noting. Format:

**[CONFIRMS / CONTRADICTS / COMPLICATES]** "[media claim]" — [actor], [date], [what they actually said]

Only include bullets where you have direct sourced evidence from the data above.

## What to Watch

3-4 bullets of forward-looking signals. Based on what third-party officials are saying now, what specific events, statements, or actor behaviors in the next 7-14 days would confirm or deny the current trajectory? These should be concrete and testable, not vague.

## Diplomatic Temperature

End with one line:
**[🔵 COLD / 🟡 CAUTIOUS / 🟠 TENTATIVE / 🟢 ACTIVE / ⭐ BREAKTHROUGH]** — one sentence explaining the call, citing the most authoritative source.

---

Writing rules:
- No filler phrases: "it is worth noting", "it should be mentioned", "in conclusion", "overall".
- Short paragraphs. No paragraph over 5 sentences.
- If an actor has no data in this period, do not write a section about them — skip entirely. Do NOT write "No official statements found."
- Do NOT fabricate quotes. Paraphrase what sources report officials said, and cite the source.
- URLs must come from the data above only — do not construct or guess them.
- Avoid repeating the actor baseline descriptions verbatim — your job is to analyze change and significance, not describe who these actors are.
"""
    return prompt


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

def call_gemma(messages: list[dict], hf_token: str, max_tokens: int = 4096) -> str:
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


# ---------------------------------------------------------------------------
# HTML / output
# ---------------------------------------------------------------------------

ACCENT = "#1a472a"  # diplomacy green

HTML_CSS = f"""
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    max-width: 1100px; margin: 0 auto; padding: 20px;
    line-height: 1.6; background: #f5f5f5; color: #333;
}}
.container {{ background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }}
h1 {{ color: {ACCENT}; border-bottom: 3px solid {ACCENT}; padding-bottom: 10px; }}
h2 {{ color: {ACCENT}; border-bottom: 2px solid #d4edda; padding-bottom: 6px; margin-top: 36px; }}
h3 {{ color: #333; border-bottom: 1px solid #eee; padding-bottom: 4px; margin-top: 28px; }}
h4 {{ color: #555; margin-top: 20px; }}
.meta {{ color: #777; font-size: 0.85em; margin: 6px 0 20px; }}
.back-link {{ display: inline-block; margin-bottom: 20px; color: {ACCENT}; text-decoration: none; }}
.back-link:hover {{ text-decoration: underline; }}
.disclaimer {{
    background: #fff3cd; border-left: 4px solid #ffc107;
    padding: 10px 16px; margin: 16px 0; border-radius: 0 4px 4px 0;
    font-size: 0.9em; color: #856404;
}}
table {{ border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 0.88em; overflow-x: auto; display: block; }}
th {{ background: {ACCENT}; color: white; padding: 10px 12px; text-align: left; white-space: nowrap; }}
td {{ border: 1px solid #ddd; padding: 8px 12px; vertical-align: top; }}
tr:nth-child(even) td {{ background: #f8f9fa; }}
pre {{
    background: #f5f5f5; border: 1px solid #ddd; border-radius: 6px;
    padding: 16px; overflow-x: auto; font-size: 0.88em; white-space: pre-wrap;
}}
code {{ background: #f0f0f0; padding: 2px 5px; border-radius: 3px; font-size: 0.88em; }}
pre code {{ background: none; padding: 0; }}
blockquote {{
    border-left: 4px solid {ACCENT}; margin: 16px 0; padding: 8px 16px;
    background: #d4edda; border-radius: 0 4px 4px 0; color: #333;
}}
strong {{ color: #111; }}
ul, ol {{ padding-left: 1.5em; }}
li {{ margin: 4px 0; }}
hr {{ border: none; border-top: 2px solid #eee; margin: 32px 0; }}
a {{ color: {ACCENT}; }}
"""

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Iran/US Diplomacy Monitor — {date}</title>
    <style>{css}</style>
</head>
<body>
<div class="container">
    <a href="index.html" class="back-link">&#8592; Iran Diplomacy Monitor Archive</a>
    <h1>&#127758; Iran/US Diplomacy OSINT Monitor &#8212; {date}</h1>
    <p class="meta">
        Generated: {generated_at} UTC &nbsp;|&nbsp;
        Coverage: last {days} days &nbsp;|&nbsp;
        Sources: IAEA &middot; Russia MFA &middot; China MFA &middot; UN &middot; EU EEAS &middot; Google News RSS &nbsp;|&nbsp;
        Model: {model}
    </p>
    <div class="disclaimer">
        <strong>OSINT Notice:</strong> This report aggregates official statements from third-party regional and multilateral actors only.
        No US government or Iranian government sources are included. All source URLs link to official institutions.
    </div>
    <hr>
    {body}
</div>
</body>
</html>"""

INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Iran/US Diplomacy Monitor &#8212; Archive</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 900px; margin: 0 auto; padding: 20px;
            background: #f5f5f5; color: #333;
        }}
        .container {{ background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }}
        h1 {{ color: #1a472a; border-bottom: 3px solid #1a472a; padding-bottom: 10px; }}
        .description {{ color: #555; margin: 16px 0 32px; line-height: 1.6; }}
        .report-list {{ list-style: none; padding: 0; }}
        .report-list li {{
            border-left: 4px solid #1a472a; padding: 12px 16px; margin: 10px 0;
            background: #f8f9fa; border-radius: 0 6px 6px 0;
            display: flex; align-items: center; justify-content: space-between;
        }}
        .report-list a {{ color: #1a472a; text-decoration: none; font-weight: 500; font-size: 1.05em; }}
        .report-list a:hover {{ text-decoration: underline; }}
        .report-date {{ color: #888; font-size: 0.85em; }}
        .badge-latest {{
            font-size: 0.75em; background: #d4edda; color: #155724;
            padding: 3px 8px; border-radius: 10px; margin-left: 8px;
        }}
        .back-link {{ display: inline-block; margin-bottom: 20px; color: #1a472a; text-decoration: none; }}
        .back-link:hover {{ text-decoration: underline; }}
        .actors {{ font-size: 0.88em; color: #555; margin: 0 0 24px; }}
    </style>
</head>
<body>
<div class="container">
    <a href="../../index.html" class="back-link">&#8592; Back to Portfolio</a>
    <h1>&#127758; Iran/US Diplomacy OSINT Monitor</h1>
    <p class="description">
        Third-party official source intelligence on Iran/US diplomacy — no US, no Iran.
        Tracks <strong>Oman, Qatar, EU/E3, Russia, China, IAEA, UN, Saudi Arabia, Turkey, Iraq</strong>
        official communiqués and press releases. Analyzes engagement signals, red lines,
        and cross-checks media claims against verifiable official statements.
        Powered by Gemma 4.
    </p>
    <ul class="report-list">
        {items}
    </ul>
</div>
</body>
</html>"""


def _markdown_to_html(md_text: str) -> str:
    return md_lib.markdown(
        md_text,
        extensions=["tables", "fenced_code", "nl2br"],
    )


def regenerate_index(out_dir: Path) -> None:
    reports = sorted(out_dir.glob("iran-diplo-*.html"), reverse=True)
    items = []
    for i, path in enumerate(reports):
        date_str = path.stem.replace("iran-diplo-", "")
        badge = '<span class="badge-latest">latest</span>' if i == 0 else ""
        items.append(
            f'<li>'
            f'<a href="{path.name}">Iran/US Diplomacy Monitor &#8212; {date_str}{badge}</a>'
            f'<span class="report-date">{date_str}</span>'
            f'</li>'
        )
    (out_dir / "index.html").write_text(
        INDEX_TEMPLATE.format(items="\n        ".join(items) if items else "<li>No reports yet.</li>"),
        encoding="utf-8",
    )


def save_output(report: str, today: str, out_dir: Path, days: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    md_header = (
        f"# Iran/US Diplomacy OSINT Monitor — {today}\n\n"
        f"**Generated:** {generated_at} UTC  \n"
        f"**Coverage:** {days} days ending {today}  \n"
        f"**Sources:** IAEA, Russia MFA, China MFA, UN, EU EEAS, Google News RSS  \n"
        f"**Model:** {MODEL_ID}\n\n"
        "---\n\n"
    )
    md_path = out_dir / f"iran-diplo-{today}.md"
    md_path.write_text(md_header + report, encoding="utf-8")

    body_html = _markdown_to_html(report)
    html_content = HTML_TEMPLATE.format(
        date=today,
        generated_at=generated_at,
        days=days,
        model=MODEL_ID,
        css=HTML_CSS,
        body=body_html,
    )
    html_path = out_dir / f"iran-diplo-{today}.html"
    html_path.write_text(html_content, encoding="utf-8")

    regenerate_index(out_dir)

    print(f"\nMarkdown : {md_path}", file=sys.stderr)
    print(f"HTML     : {html_path}", file=sys.stderr)
    print(f"Index    : {out_dir / 'index.html'}", file=sys.stderr)
    return html_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Iran/US Diplomacy OSINT Monitor")
    parser.add_argument("--days", type=int, default=14, help="Lookback window in days (default 14)")
    parser.add_argument("--output-dir", default=None,
                        help="Output directory (default: reports/iran-diplo/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scrape only, skip LLM call and file write")
    args = parser.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else Path("reports/iran-diplo")

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token and not args.dry_run:
        raise EnvironmentError("HF_TOKEN environment variable is not set.")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"=== Iran/US Diplomacy OSINT Monitor — {today} (lookback {args.days}d) ===", file=sys.stderr)

    # --- Layer 1: Direct scrapes ---
    print("\n--- Layer 1: Direct official source scraping ---", file=sys.stderr)
    official_items = scrape_all_official(days=args.days)

    # --- Layer 2: Google News RSS ---
    print("\n--- Layer 2: Google News RSS ---", file=sys.stderr)
    news_items = search_news(NEWS_QUERIES, days=args.days)

    total = len(official_items) + len(news_items)
    print(f"\n--- Scrape summary ---", file=sys.stderr)
    print(f"  Official source items: {len(official_items)}", file=sys.stderr)
    print(f"  News RSS items:        {len(news_items)}", file=sys.stderr)
    print(f"  TOTAL:                 {total}", file=sys.stderr)

    if args.dry_run:
        print("\n[dry-run] Skipping LLM call.", file=sys.stderr)
        return

    if total == 0:
        print("No data gathered — aborting.", file=sys.stderr)
        sys.exit(1)

    # --- Build prompt ---
    context = build_context_prompt(official_items, news_items, args.days, today)

    est_tokens = len(context) // 4
    print(f"\nContext prompt: ~{est_tokens:,} tokens", file=sys.stderr)
    if est_tokens > 90_000:
        print("  WARNING: prompt may exceed model context — truncating news.", file=sys.stderr)
        news_items = news_items[:30]
        context = build_context_prompt(official_items, news_items, args.days, today)

    # --- LLM ---
    print("\n--- Calling Gemma 4 ---", file=sys.stderr)
    messages = [
        {"role": "system", "content": "You are a senior geopolitical analyst specializing in Middle East diplomacy and Iranian foreign policy."},
        {"role": "user",   "content": context},
    ]
    report = call_gemma(messages, hf_token, max_tokens=4096)

    # --- Save ---
    save_output(report, today, out_dir, args.days)
    print(f"\nDone. Report: {out_dir}/iran-diplo-{today}.html", file=sys.stderr)


if __name__ == "__main__":
    main()

"""Refresh ratings in reports/swiss-pairing/index.html until the 2026 K-12 Grade Championships end.

- Rafael's starting rating: Glitchess live rating (USCF 32629257).
- Opponent fields: King Registration entry list 26K12Grades (ratings only, Unrated -> 400, Rafael removed).
Writes the page only when a rating or the field changed. Stops after Dec 13, 2026 (ET).
"""
import json
import re
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

PAGE = "reports/swiss-pairing/index.html"
RAFA_ID = "32629257"
END = date(2026, 12, 13)
ENTRY_URL = "https://www.kingregistration.com/entrylist/26K12Grades"
GLITCHESS_URL = f"https://api.glitchess.com/api/players/{RAFA_ID}"
ORDER = ["Kindergarten"] + ["1st Grade", "2nd Grade", "3rd Grade"] + [f"{n}th Grade" for n in range(4, 13)]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def warn(msg):
    print(f"::warning::{msg}")
    sys.exit(0)  # keep the last good page


def fetch_sections():
    html = requests.get(ENTRY_URL, headers=HEADERS, timeout=60).text
    sections = {s: [] for s in ORDER}
    entry_rating = None
    for row in re.findall(r"<tr data-rowid.*?</tr>", html, re.S):
        td = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(td) < 8 or td[7] not in sections:
            continue
        m = re.match(r"\d+", td[2])
        r = int(m.group()) if m else 400
        if td[3] == RAFA_ID:
            entry_rating = r
            continue
        sections[td[7]].append(r)
    for v in sections.values():
        v.sort(reverse=True)
    return sections, entry_rating


def main():
    today = datetime.now(ZoneInfo("America/New_York")).date()
    if today > END:
        print(f"{today}: tournament over (ended {END}), nothing to do.")
        return

    try:
        live = int(requests.get(GLITCHESS_URL, headers=HEADERS, timeout=30).json()["live_rating"])
    except Exception as e:
        warn(f"Glitchess fetch failed: {e}")
    try:
        sections, entry_rating = fetch_sections()
    except Exception as e:
        warn(f"Entry list fetch failed: {e}")

    page = open(PAGE, encoding="utf-8").read()
    old = json.loads(re.search(r"const SECTIONS=(\{.*?\});", page).group(1))
    total, old_total = sum(map(len, sections.values())), sum(map(len, old.values()))
    if total < 0.8 * old_total or not all(sections.values()):
        warn(f"Entry list looks wrong ({total} players vs {old_total} before), not updating.")
    if not 100 <= live <= 3000:
        warn(f"Odd Glitchess rating {live}, not updating.")
    if entry_rating is None:
        entry_rating = int(re.search(r"the entry list (?:still )?shows (\d+)", page).group(1))

    new = re.sub(r"const SECTIONS=\{.*?\};", lambda _: "const SECTIONS=" + json.dumps(sections, separators=(",", ":")) + ";", page, count=1)
    new = re.sub(r"let RR=\d+", f"let RR={live}", new, count=1)
    new = re.sub(r'(id="rating"[^>]*value=")\d+', rf"\g<1>{live}", new, count=1)
    new = re.sub(r"Rafael starts at \d+, [^.(]*\(the entry list (?:still )?shows \d+\)",
                 f"Rafael starts at {live}, his live rating on Glitchess (the entry list shows {entry_rating})", new, count=1)
    if new == page:
        print(f"No change (Rafael {live}, {total} players).")
        return

    stamp = f"{today:%b} {today.day}, {today.year}"
    new = re.sub(r"as of [A-Z][a-z]{2} \d{1,2}, \d{4}", f"as of {stamp}", new, count=1)
    new = re.sub(r"26K12Grades, [A-Z][a-z]{2} \d{1,2},? \d{4}", f"26K12Grades, {stamp}", new, count=1)
    open(PAGE, "w", encoding="utf-8").write(new)
    print(f"Updated: Rafael {live}, {total} players (was {old_total}).")


if __name__ == "__main__":
    main()

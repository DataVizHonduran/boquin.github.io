#!/usr/bin/env python3
"""
NYRR Registration Timeline Watcher
Monitors nyrr.org/run/race-calendar/race-registration-launch-timeline for changes.
Outputs reports/nyrr/index.html to boquin.xyz; state persisted in data/nyrr_timeline_state.json.

Usage:
    python scripts/nyrr_watcher.py
    python scripts/nyrr_watcher.py --dry-run   # fetch + render but don't write
"""

import argparse
import difflib
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ---------------------------------------------------------------------------
TIMELINE_URL = "https://www.nyrr.org/run/race-calendar/race-registration-launch-timeline"
REPO_ROOT = Path(__file__).parent.parent
STATE_FILE = REPO_ROOT / "data" / "nyrr_timeline_state.json"
OUTPUT_FILE = REPO_ROOT / "reports" / "nyrr" / "index.html"
# ---------------------------------------------------------------------------


def fetch_timeline() -> str:
    """Return visible text of the NYRR registration launch timeline section."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()

        try:
            page.goto(TIMELINE_URL, wait_until="networkidle", timeout=45_000)
        except PlaywrightTimeout:
            # Site might still have partial content — continue
            pass

        # Detect virtual waiting room redirect
        if "virtualcorral.nyrr.org" in page.url or "queue" in page.url.lower():
            browser.close()
            raise RuntimeError(
                f"NYRR site is in virtual queue mode (redirected to {page.url}). "
                "Try again outside peak hours."
            )

        # Try to grab the main content area; fall back to full body text
        content = ""
        for selector in [
            "main",
            "[class*='content']",
            "[class*='race-calendar']",
            "article",
            "body",
        ]:
            el = page.query_selector(selector)
            if el:
                content = el.inner_text().strip()
                if len(content) > 200:
                    break

        browser.close()

    if not content:
        raise RuntimeError("Could not extract any content from the NYRR page.")

    # Strip noisy repeated whitespace
    lines = [ln.strip() for ln in content.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"hash": "", "content": "", "last_changed": None, "changelog": []}


def save_state(state: dict, dry_run: bool) -> None:
    if dry_run:
        return
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def compute_diff_summary(old: str, new: str) -> str:
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=2))
    if not diff:
        return ""
    added = [ln[1:] for ln in diff if ln.startswith("+") and not ln.startswith("+++")]
    removed = [ln[1:] for ln in diff if ln.startswith("-") and not ln.startswith("---")]
    parts = []
    if added:
        parts.append("Added:\n" + "\n".join(f"  + {l}" for l in added[:10]))
    if removed:
        parts.append("Removed:\n" + "\n".join(f"  - {l}" for l in removed[:10]))
    return "\n".join(parts)


def render_html(state: dict, now_str: str) -> str:
    last_changed = state.get("last_changed") or "Never detected"
    try:
        changed_dt = datetime.fromisoformat(last_changed)
        changed_age_days = (datetime.now(timezone.utc) - changed_dt).days
        changed_label = changed_dt.strftime("%B %d, %Y")
        highlight_class = "highlight-recent" if changed_age_days <= 7 else ""
    except Exception:
        changed_label = last_changed
        highlight_class = ""
        changed_age_days = 999

    changelog = state.get("changelog", [])
    changelog_rows = ""
    for entry in reversed(changelog[-20:]):
        diff_html = entry.get("diff", "").replace("<", "&lt;").replace(">", "&gt;")
        diff_block = f'<pre class="diff-block">{diff_html}</pre>' if diff_html else ""
        changelog_rows += f"""
        <div class="changelog-entry">
            <span class="changelog-date">{entry['date']}</span>
            <span class="changelog-msg">{entry.get('summary', 'Content changed')}</span>
            {diff_block}
        </div>"""

    if not changelog_rows:
        changelog_rows = '<p class="muted">No changes detected yet.</p>'

    content_html = (
        state.get("content", "No content fetched yet.")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NYRR Registration Timeline — boquin.xyz</title>
    <link rel="stylesheet" href="../../styles.css">
    <style>
        .meta-bar {{
            display: flex; gap: 2rem; flex-wrap: wrap;
            margin: 1.5rem 0; padding: 1rem 1.2rem;
            background: var(--card-bg, #1e2130);
            border-radius: 8px; border: 1px solid var(--border, #2d3148);
        }}
        .meta-item {{ display: flex; flex-direction: column; gap: .2rem; }}
        .meta-label {{ font-size: .75rem; color: var(--muted, #8892b0); text-transform: uppercase; letter-spacing: .06em; }}
        .meta-value {{ font-size: 1rem; font-weight: 600; }}
        .highlight-recent {{ color: #5af078; }}
        .changelog-entry {{
            padding: .75rem 0; border-bottom: 1px solid var(--border, #2d3148);
        }}
        .changelog-date {{ font-weight: 600; margin-right: .75rem; }}
        .changelog-msg {{ color: var(--muted, #8892b0); }}
        .diff-block {{
            margin-top: .5rem; padding: .5rem .75rem;
            background: #111320; border-radius: 4px;
            font-size: .8rem; white-space: pre-wrap; word-break: break-word;
            color: #a8b2d8;
        }}
        .timeline-content {{
            white-space: pre-wrap; word-break: break-word;
            font-family: ui-monospace, monospace; font-size: .85rem;
            line-height: 1.6; padding: 1rem 1.2rem;
            background: var(--card-bg, #1e2130);
            border-radius: 8px; border: 1px solid var(--border, #2d3148);
            max-height: 60vh; overflow-y: auto;
        }}
        .muted {{ color: var(--muted, #8892b0); }}
        h2 {{ margin-top: 2rem; font-size: 1.1rem; text-transform: uppercase; letter-spacing: .05em; }}
    </style>
</head>
<body>
    <main class="container" style="max-width:900px; margin:0 auto; padding:2rem 1rem;">
        <h1>🏃 NYRR Registration Timeline</h1>
        <p class="muted">Monitors <a href="{TIMELINE_URL}" target="_blank">nyrr.org race registration launch timeline</a> for updates. Refreshed twice daily via GitHub Actions.</p>

        <div class="meta-bar">
            <div class="meta-item">
                <span class="meta-label">Last Checked</span>
                <span class="meta-value">{now_str}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Last Changed</span>
                <span class="meta-value {highlight_class}">{changed_label}{"  ← recent" if changed_age_days <= 7 else ""}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Changes Detected</span>
                <span class="meta-value">{len(changelog)}</span>
            </div>
        </div>

        <h2>Changelog</h2>
        <div class="changelog-section">{changelog_rows}</div>

        <h2>Current Content</h2>
        <div class="timeline-content">{content_html}</div>
    </main>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")

    print(f"[nyrr_watcher] {now_str} — fetching timeline...")

    try:
        content = fetch_timeline()
    except RuntimeError as exc:
        print(f"[nyrr_watcher] WARN: {exc}", file=sys.stderr)
        # Render page with last-known state so timestamp still updates
        state = load_state()
        html = render_html(state, now_str + " (fetch failed — queue active)")
        if not args.dry_run:
            OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
            OUTPUT_FILE.write_text(html)
        sys.exit(0)

    state = load_state()
    new_hash = sha256(content)
    changed = new_hash != state["hash"]

    if changed and state["hash"]:
        diff_summary = compute_diff_summary(state["content"], content)
        print(f"[nyrr_watcher] Content changed!\n{diff_summary}")
        state["changelog"].append(
            {
                "date": now.strftime("%Y-%m-%d"),
                "summary": "Timeline page updated",
                "diff": diff_summary,
            }
        )
        state["last_changed"] = now.isoformat()
    elif not state["hash"]:
        print("[nyrr_watcher] First run — baseline established.")
        state["last_changed"] = now.isoformat()
    else:
        print("[nyrr_watcher] No change detected.")

    state["hash"] = new_hash
    state["content"] = content

    html = render_html(state, now_str)

    if not args.dry_run:
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(html)
        save_state(state, dry_run=False)
        print(f"[nyrr_watcher] Written → {OUTPUT_FILE}")
    else:
        print("[nyrr_watcher] Dry-run: no files written.")
        print(f"  Content preview: {content[:300]!r}")


if __name__ == "__main__":
    main()

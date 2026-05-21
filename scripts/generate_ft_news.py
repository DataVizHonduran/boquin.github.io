#!/usr/bin/env python3
"""Generate reports/news/index.html — FT News Feed for boquin.xyz"""

import feedparser
import json
import os
import re
import sys
from datetime import datetime, timezone

TOPICS = [
    {
        "tag":   "oil and gas",
        "label": "Oil & Gas",
        "color": "#d97706",
        "bg":    "#fffbeb",
        "feed":  "https://www.ft.com/energy?format=rss",
    },
    {
        "tag":   "corporate earnings and results",
        "label": "Corporate Earnings",
        "color": "#059669",
        "bg":    "#ecfdf5",
        "feed":  "https://www.ft.com/companies?format=rss",
    },
    {
        "tag":   "middle east war",
        "label": "Middle East War",
        "color": "#dc2626",
        "bg":    "#fef2f2",
        "feed":  "https://www.ft.com/middle-east?format=rss",
    },
    {
        "tag":   "shipping",
        "label": "Shipping",
        "color": "#2563eb",
        "bg":    "#eff6ff",
        "feed":  "https://www.ft.com/shipping?format=rss",
    },
    {
        "tag":   "artificial intelligence",
        "label": "Artificial Intelligence",
        "color": "#7c3aed",
        "bg":    "#f5f3ff",
        "feed":  "https://www.ft.com/artificial-intelligence?format=rss",
    },
    {
        "tag":   "us-china relations",
        "label": "US–China Relations",
        "color": "#ea580c",
        "bg":    "#fff7ed",
        "feed":  "https://www.ft.com/geopolitics?format=rss",
    },
]

OUT_DIR  = os.path.join(os.path.dirname(__file__), "..", "reports", "news")
OUT_FILE = os.path.join(OUT_DIR, "index.html")


def fetch_articles():
    articles = []
    seen = set()

    for topic in TOPICS:
        print(f"  Fetching {topic['label']} …", flush=True)
        feed = feedparser.parse(topic["feed"])

        for entry in feed.entries:
            guid = entry.get("id", entry.get("link", ""))
            if guid in seen:
                continue
            seen.add(guid)

            dt = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

            articles.append({
                "title":      re.sub(r"\s+", " ", entry.get("title", "")).strip(),
                "url":        entry.get("link", ""),
                "summary":    re.sub(r"\s+", " ", entry.get("summary", "")).strip(),
                "date_iso":   dt.isoformat() if dt else "",
                "date_label": dt.strftime("%d %b %Y") if dt else "",
                "tag":        topic["tag"],
            })

    articles.sort(key=lambda a: a["date_iso"], reverse=True)
    return articles


def build_html(articles):
    now_str = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    articles_json = json.dumps(articles, ensure_ascii=False)
    topics_json   = json.dumps(
        [{"tag": t["tag"], "label": t["label"], "color": t["color"], "bg": t["bg"]}
         for t in TOPICS],
        ensure_ascii=False,
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FT News Feed | boquin.xyz</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Inter',system-ui,sans-serif;line-height:1.6;color:#475569;background:#f6f7f9;min-height:100vh}}

/* ── navbar ── */
.navbar{{background:rgba(255,255,255,.95);backdrop-filter:blur(10px);position:fixed;top:0;width:100%;z-index:1000;box-shadow:0 1px 0 #e4e8ef}}
.nav-inner{{max-width:1400px;margin:0 auto;padding:0 2rem;display:flex;justify-content:space-between;align-items:center;height:70px}}
.nav-brand{{font-size:1.1rem;font-weight:700;color:#0f172a;text-decoration:none}}
.nav-back{{font-size:.9rem;color:#64748b;text-decoration:none;font-weight:500;transition:color .2s}}
.nav-back:hover{{color:#4f46e5}}

/* ── hero ── */
.hero{{padding:6rem 2rem 2.5rem;text-align:center;background:#f6f7f9}}
.hero h1{{font-size:2.4rem;font-weight:800;color:#0f172a;margin-bottom:.5rem}}
.hero p{{color:#64748b;font-size:1rem}}

/* ── controls ── */
.controls{{max-width:1200px;margin:0 auto;padding:1.5rem 2rem 0}}
.tag-bar{{display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:1.25rem}}
.tag-btn{{padding:.35rem .9rem;border-radius:9999px;border:1.5px solid transparent;
  font-size:.82rem;font-weight:600;cursor:pointer;transition:all .18s;white-space:nowrap}}
.tag-btn.all{{background:#f1f5f9;color:#475569;border-color:#e2e8f0}}
.tag-btn.all.active{{background:#0f172a;color:#fff;border-color:#0f172a}}
.tag-btn.active{{color:#fff!important;border-color:transparent!important}}
.tag-btn:not(.active){{background:#fff;border-color:#e2e8f0}}

.slider-row{{display:flex;align-items:center;gap:1rem;padding:.75rem 0 1rem}}
.slider-row label{{font-size:.88rem;color:#475569;white-space:nowrap;min-width:130px;font-weight:500}}
#days-slider{{flex:1;max-width:320px;accent-color:#4f46e5;height:4px;cursor:pointer}}
.slider-ticks{{display:flex;justify-content:space-between;max-width:320px;margin-top:.2rem}}
.slider-ticks span{{font-size:.72rem;color:#94a3b8}}

.meta-row{{font-size:.8rem;color:#94a3b8;padding:.25rem 0 1.25rem;border-bottom:1px solid #e4e8ef;margin-bottom:1.5rem}}
.meta-row strong{{color:#475569}}

/* ── grid ── */
.grid{{max-width:1200px;margin:0 auto;padding:0 2rem 4rem;
  display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:1.25rem}}

/* ── card ── */
.card{{background:#fff;border-radius:12px;padding:1.25rem 1.4rem 1.1rem;
  box-shadow:0 1px 3px rgba(0,0,0,.06);border:1px solid #e8ecf2;
  display:flex;flex-direction:column;gap:.6rem;transition:box-shadow .18s}}
.card:hover{{box-shadow:0 4px 12px rgba(0,0,0,.1)}}
.card-top{{display:flex;justify-content:space-between;align-items:flex-start;gap:.5rem}}
.badge{{padding:.18rem .6rem;border-radius:9999px;font-size:.7rem;font-weight:700;
  white-space:nowrap;flex-shrink:0}}
.card-date{{font-size:.75rem;color:#94a3b8;flex-shrink:0;padding-top:.1rem}}
.card-title{{font-size:.97rem;font-weight:700;color:#0f172a;line-height:1.4}}
.card-title a{{color:inherit;text-decoration:none}}
.card-title a:hover{{color:#4f46e5;text-decoration:underline}}
.card-summary{{font-size:.83rem;color:#64748b;line-height:1.5;
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}}
.card-link{{margin-top:auto;font-size:.78rem;font-weight:600;color:#4f46e5;
  text-decoration:none;display:inline-flex;align-items:center;gap:.3rem}}
.card-link:hover{{text-decoration:underline}}

/* ── empty state ── */
.empty{{max-width:1200px;margin:2rem auto;padding:3rem 2rem;text-align:center;color:#94a3b8;font-size:.95rem}}

/* ── footer ── */
.footer{{text-align:center;padding:2rem;font-size:.8rem;color:#94a3b8;border-top:1px solid #e4e8ef}}

@media(max-width:600px){{
  .hero h1{{font-size:1.8rem}}
  .grid{{grid-template-columns:1fr;padding:0 1rem 3rem}}
  .controls{{padding:1rem 1rem 0}}
}}
</style>
</head>
<body>

<nav class="navbar">
  <div class="nav-inner">
    <a href="../../index.html" class="nav-brand">Global Macro Dashboards</a>
    <a href="../../index.html" class="nav-back">← Back to Dashboards</a>
  </div>
</nav>

<main>
  <div class="hero">
    <h1>📰 FT News Feed</h1>
    <p>Financial Times headlines by topic — updated from live RSS feeds</p>
  </div>

  <div class="controls">
    <div class="tag-bar" id="tag-bar">
      <button class="tag-btn all active" data-tag="all">All</button>
      <!-- topic buttons injected by JS -->
    </div>

    <div class="slider-row">
      <label>Last <strong id="days-val">7</strong> day(s)</label>
      <div>
        <input type="range" id="days-slider" min="1" max="21" value="7">
        <div class="slider-ticks"><span>1d</span><span>7d</span><span>14d</span><span>21d</span></div>
      </div>
    </div>

    <div class="meta-row" id="meta-row">
      Fetched <strong>{now_str}</strong>
    </div>
  </div>

  <div class="grid" id="grid"></div>
  <div class="empty" id="empty" style="display:none">No articles match the current filters.</div>
</main>

<footer class="footer">
  Last updated {now_str} &nbsp;·&nbsp; Source: <a href="https://www.ft.com" target="_blank" rel="noopener">Financial Times RSS</a>
  &nbsp;·&nbsp; <a href="../../index.html">boquin.xyz</a>
</footer>

<script>
const ARTICLES = {articles_json};
const TOPICS   = {topics_json};

/* build tag buttons */
const tagBar = document.getElementById('tag-bar');
TOPICS.forEach(t => {{
  const btn = document.createElement('button');
  btn.className = 'tag-btn';
  btn.dataset.tag = t.tag;
  btn.textContent = t.label;
  btn.style.color = t.color;
  btn.style.background = t.bg;
  btn.style.borderColor = t.color + '55';
  tagBar.appendChild(btn);
}});

const topicMap = {{}};
TOPICS.forEach(t => topicMap[t.tag] = t);

/* state */
let activeTag  = 'all';
let activeDays = 7;

/* controls */
const slider   = document.getElementById('days-slider');
const daysVal  = document.getElementById('days-val');
const grid     = document.getElementById('grid');
const empty    = document.getElementById('empty');
const metaRow  = document.getElementById('meta-row');

slider.addEventListener('input', () => {{
  activeDays = +slider.value;
  daysVal.textContent = activeDays;
  render();
}});

tagBar.addEventListener('click', e => {{
  const btn = e.target.closest('.tag-btn');
  if (!btn) return;
  activeTag = btn.dataset.tag;
  tagBar.querySelectorAll('.tag-btn').forEach(b => {{
    b.classList.remove('active');
    const t = topicMap[b.dataset.tag];
    if (t) {{ b.style.color = t.color; b.style.background = t.bg; b.style.borderColor = t.color + '55'; }}
  }});
  btn.classList.add('active');
  if (btn.dataset.tag === 'all') {{
    btn.style.cssText = 'background:#0f172a;color:#fff;border-color:#0f172a';
  }} else {{
    const t = topicMap[activeTag];
    btn.style.background = t.color;
    btn.style.color = '#fff';
    btn.style.borderColor = t.color;
  }}
  render();
}});

function render() {{
  const cutoff = new Date(Date.now() - activeDays * 864e5).toISOString();
  const filtered = ARTICLES.filter(a =>
    (activeTag === 'all' || a.tag === activeTag) &&
    (!a.date_iso || a.date_iso >= cutoff)
  );

  metaRow.innerHTML = `Showing <strong>${{filtered.length}}</strong> article${{filtered.length !== 1 ? 's' : ''}} &nbsp;·&nbsp; Fetched <strong>{now_str}</strong>`;

  if (!filtered.length) {{
    grid.innerHTML = '';
    empty.style.display = '';
    return;
  }}
  empty.style.display = 'none';

  grid.innerHTML = filtered.map(a => {{
    const t = topicMap[a.tag] || {{color:'#64748b', bg:'#f1f5f9', label: a.tag}};
    return `<div class="card">
      <div class="card-top">
        <span class="badge" style="background:${{t.bg}};color:${{t.color}}">${{t.label}}</span>
        <span class="card-date">${{a.date_label}}</span>
      </div>
      <div class="card-title"><a href="${{a.url}}" target="_blank" rel="noopener">${{escHtml(a.title)}}</a></div>
      ${{a.summary ? `<div class="card-summary">${{escHtml(a.summary)}}</div>` : ''}}
      <a class="card-link" href="${{a.url}}" target="_blank" rel="noopener">Read on FT ↗</a>
    </div>`;
  }}).join('');
}}

function escHtml(s) {{
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

render();
</script>
</body>
</html>"""


def main():
    print("Building FT News page …")
    articles = fetch_articles()
    print(f"  {len(articles)} total articles fetched")

    os.makedirs(OUT_DIR, exist_ok=True)
    html = build_html(articles)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Written → {OUT_FILE}")


if __name__ == "__main__":
    main()

# Injecting Gemma 4 Commentary into Existing HTML Pages

Reusable pattern for any script in this repo that loads structured data, calls Gemma 4, and injects the output into an existing generated HTML file.

---

## The Pattern (4 steps)

### 1. Load data from a local structured file (preferred) or scrape

**Preferred: read the generator's output file directly.**
Pages in this repo are built from local JSON/CSV files. Reading those directly gives Gemma actual numeric data (positions, scores, signals) instead of page chrome text. No network call needed.

```python
def load_data() -> str:
    with open(SUMMARY) as f:
        d = json.load(f)
    # Build a human-readable text summary Gemma can reason over
    lines = []
    # ... extract and format the fields that matter
    return "\n".join(lines)
```

What to include depends on the page, but aim for:
- Sorted numeric values (extremes are most useful)
- Divergences / deltas between related series
- Recent signal or event metadata (last 14 days)
- Cap output at ~8000 chars to stay within token budget

**Fallback: scrape the live URL** — use only when there is no local data file. Strips `<script>`, `<style>`, `<nav>`, `<footer>` before extracting text. Plotly/JS chart data will NOT be captured this way.

```python
def scrape_data(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text[:8000]
```

---

### 2. Call Gemma 4 with a structured prompt

Use `InferenceClient` from `huggingface_hub` with streaming. Include retry logic for 429/503 rate limits. `HF_TOKEN` always comes from `os.environ`.

```python
MODEL_ID = "google/gemma-4-31B-it"

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
                time.sleep(wait)
            else:
                raise
```

Prompt structure that works well:

```python
prompt = f"""[ROLE]: <persona>
[TASK]: <what to analyze and what sections to produce>
[FORMAT]: Markdown with ## headers, bullet points, tables where relevant. Under 600 words.
[DATA]:
{data}"""
```

---

### 3. Convert Markdown → HTML and wrap in a styled block

Use `markdown.markdown(text, extensions=["tables"])` (already in `requirements.txt`).

Wrap in a div that matches the site's existing aesthetic (white card, blue left-border, same font stack):

```python
import markdown as md_lib

MARKER_START = "<!-- commentary-start -->"   # use a unique marker per page
MARKER_END   = "<!-- commentary-end -->"

def build_commentary_block(commentary_md: str, generated_at: str) -> str:
    body_html = md_lib.markdown(commentary_md, extensions=["tables"])
    return f"""{MARKER_START}
<div style="max-width:1400px;margin:40px auto 0;padding:0 20px 40px;">
  <div style="background:white;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,0.1);padding:30px;">
    <div style="border-left:4px solid #007bff;padding-left:16px;margin-bottom:20px;">
      <h2 style="color:#333;margin:0 0 4px;">AI Commentary</h2>
      <p style="color:#666;font-size:0.85em;margin:0;">Generated {{generated_at}} UTC · google/gemma-4-31B-it</p>
    </div>
    <div class="commentary" style="line-height:1.7;color:#444;">
      <style>
        .commentary table {{border-collapse:collapse;width:100%;margin:16px 0;}}
        .commentary th, .commentary td {{border:1px solid #dee2e6;padding:8px 12px;text-align:left;}}
        .commentary th {{background:#f8f9fa;font-weight:600;}}
        .commentary h2,.commentary h3 {{color:#333;margin:20px 0 8px;}}
        .commentary ul {{padding-left:20px;}}
        .commentary li {{margin:4px 0;}}
      </style>
      {{body_html}}
    </div>
  </div>
</div>
{MARKER_END}"""
```

> **Marker naming:** use a unique marker per page (e.g. `<!-- boj-commentary-start -->`) so multiple injections on the same page don't collide.
> **CSS class naming:** use a unique class name per page for the same reason.

---

### 4. Inject into the existing HTML file

Two cases handled automatically:
- **First run:** inserts before `</body>`
- **Re-run / manual trigger:** replaces existing block in-place via regex

```python
def inject_into_html(index_html: Path, block: str) -> None:
    html = index_html.read_text(encoding="utf-8")
    # Strip ALL existing blocks (handles re-runs and any duplication)
    html = re.sub(
        re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
        "",
        html,
        flags=re.DOTALL,
    )
    # Use rfind — str.replace hits every </body>, causing duplication on re-runs
    last_body = html.rfind("</body>")
    html = html[:last_body] + block + "\n</body>" + html[last_body + len("</body>"):]
    index_html.write_text(html, encoding="utf-8")
```

> **Never use `str.replace("</body>", ...)`** — it replaces every occurrence. If a previous run left extra `</body>` tags, you get duplicate blocks. Always use `rfind`.

---

## GitHub Actions Workflow

Schedule the commentary job to run **after** the page generator job, not at the same time.

```yaml
name: Daily <Page> Commentary

on:
  schedule:
    - cron: '0 7 * * *'   # adjust to fire after the generator cron
  workflow_dispatch:

jobs:
  commentary:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -r requirements.txt
      - run: git pull
      - name: Run commentary script
        env:
          HF_TOKEN: ${{ secrets.HF_TOKEN }}
        run: python scripts/<page>_commentary.py
      - name: Commit and push
        run: |
          git config --local user.email "action@github.com"
          git config --local user.name "GitHub Action"
          git add reports/<page>/
          git diff --staged --quiet || (
            git commit -m "<Page> Commentary — $(date +'%Y-%m-%d') 🤖" &&
            git pull --rebase &&
            git push
          )
```

---

## Checklist for a new page

- [ ] Identify the local data file the generator writes (JSON, CSV) — prefer this over scraping
- [ ] Copy `scripts/cta_commentary.py`, swap `SUMMARY`/`OUTPUT_DIR`/`INDEX_HTML`, marker names, CSS class name, and the prompt
- [ ] Use a unique `MARKER_START` / `MARKER_END` string per page
- [ ] Set cron to fire after the page's generator workflow
- [ ] Confirm `HF_TOKEN` secret exists in repo Settings → Secrets → Actions
- [ ] Trigger `workflow_dispatch` once to verify before relying on the schedule

# OECD MEI Interactive Dashboard

Interactive Jupyter notebook pulling all four OECD Main Economic Indicator
categories for 30 countries via the free, unauthenticated OECD SDMX REST API.

---

## How to Run

```bash
cd ~/boquin.github.io/reports/oecd-mei
jupyter lab OECD-MEI-Dashboard.ipynb
```

Then **Cell → Run All Cells**.

---

## Dependencies

```bash
pip install jupyter jupyterlab ipywidgets plotly pandas numpy requests
```

No API keys required — OECD SDMX is open access.

---

## Runtime

| Run | Time |
|---|---|
| First run (cold cache) | ~2–3 min (live API fetches) |
| Subsequent runs (within 24h) | <10 sec (local cache) |

Cache files live in `./oecd_cache/` and expire after 24 hours.

---

## What's Included

| Block | Content |
|---|---|
| A | Imports, file cache, SDMX API client |
| B | Leading Indicators — CLI / BCI / CCI |
| C | Industrial Production & Prices — IPI, CPI, PPI |
| D | Labour Market — harmonised unemployment rate |
| E | Financial & Monetary — short/long rates, yield spread, equity |
| F | Cross-country heatmap (z-scored, 10 indicators × 17+ countries) |
| G | ipywidgets controls — country selector, date range, smoothing toggle |

---

## Troubleshooting

**Widgets don't appear** — run `pip install ipywidgets` and restart the kernel.

**429 errors** — the API rate limit is 20 queries/minute. The client enforces a
3.5s delay between requests and retries automatically using the `Retry-After`
header. Just wait and re-run the affected cell.

**Stale data** — delete `./oecd_cache/` to force a fresh fetch on next run.

**Test connectivity** — uncomment `test_connection()` at the bottom of cell A3.
It fetches one month of US CLI and prints the parsed rows.

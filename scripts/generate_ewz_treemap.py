"""EWZ treemap: boxes = holdings (size = fund weight), grouped by sector, colored by forward P/E.
Output: reports/ewz-treemap/index.html
"""
import io
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import yfinance as yf

URL = "https://www.ishares.com/us/products/239612/ishares-msci-brazil-etf/latest-holdings.csv"
OUT = Path(__file__).resolve().parent.parent / "reports" / "ewz-treemap" / "index.html"


def load_holdings(path=None):
    raw = Path(path).read_text() if path else requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30).text
    lines = raw.splitlines()
    asof = next(l for l in lines if l.startswith("Fund Holdings as of")).split(",", 1)[1].strip('"')
    start = next(i for i, l in enumerate(lines) if l.startswith("Ticker,"))
    end = next(i for i in range(start + 1, len(lines)) if not lines[i].strip())
    df = pd.read_csv(io.StringIO("\n".join(lines[start:end])), thousands=",")
    df = df[df["Asset Class"] == "Equity"].copy()
    df["yf"] = np.where(df["Exchange"] == "XBSP", df["Ticker"] + ".SA", df["Ticker"])
    return df, asof


def fetch_pe(sym):
    try:
        info = yf.Ticker(sym).info
    except Exception:
        return None, None
    # forward P/E: trailing breaks on units (…11, per-share EPS vs unit price) and one-off writedowns
    pe = info.get("forwardPE")
    if pe is None:
        mc, ni = info.get("marketCap"), info.get("netIncomeToCommon")
        if mc and ni:
            pe = mc / ni if ni > 0 else -1.0  # -1 = losing money
    return pe, info.get("shortName")


def main():
    df, asof = load_holdings(sys.argv[1] if len(sys.argv) > 1 else None)
    pes = [fetch_pe(s) for s in df["yf"]]
    df["pe"] = [p for p, _ in pes]
    df["name"] = df["Name"].str.title()

    PE_LO, PE_MID, PE_HI = 4, 10, 25  # log color scale; cheap green ↔ pricey red
    def cval(pe):
        if pe is None or (isinstance(pe, float) and math.isnan(pe)) or pe <= 0:
            return None
        return math.log(min(max(pe, PE_LO), PE_HI))

    def tag(pe):
        if pe is None or (isinstance(pe, float) and math.isnan(pe)):
            return "no data"
        if pe <= 0:
            return "losing money"
        return "cheap" if pe < 7 else "fair" if pe < 14 else "pricey"

    ids, labels, parents, values, colors, hover, text = [], [], [], [], [], [], []
    for sec, g in df.groupby("Sector"):
        w = g["Weight (%)"].sum()
        wpe = g[g["pe"].fillna(-1) > 0]
        # sector P/E = weight-weighted harmonic mean (how index P/E is computed)
        spe = wpe["Weight (%)"].sum() / (wpe["Weight (%)"] / wpe["pe"]).sum() if len(wpe) else None
        ids.append(sec); labels.append(sec); parents.append(""); values.append(w)
        colors.append(cval(spe)); text.append(f"P/E {spe:.1f}" if spe else "")
        hover.append(f"<b>{sec}</b><br>{w:.1f}% of fund<br>Sector P/E: {spe:.1f}" if spe else f"<b>{sec}</b><br>{w:.1f}% of fund")
        for _, r in g.iterrows():
            pe = r["pe"]
            pe_s = "n/a" if pe is None or pd.isna(pe) else ("negative" if pe <= 0 else f"{pe:.1f}")
            ids.append(f"{sec}/{r['Ticker']}"); labels.append(r["Ticker"]); parents.append(sec)
            values.append(r["Weight (%)"]); colors.append(cval(pe))
            text.append(f"{r['name']}<br>P/E {pe_s}")
            hover.append(f"<b>{r['name']}</b> ({r['Ticker']})<br>{r['Weight (%)']:.2f}% of fund<br>"
                         f"P/E: {pe_s} — {tag(pe)}")

    GRAY = "#9a988f"
    lo, hi = math.log(PE_LO), math.log(PE_HI)
    mid = (math.log(PE_MID) - lo) / (hi - lo)
    scale = [[0, "#1a9850"], [mid * 0.5, "#91cf60"], [mid, "#f7f3c6"], [mid + (1 - mid) * 0.5, "#fc8d59"], [1, "#d73027"]]

    def to_rgb(v):
        if v is None:
            return GRAY
        t = (v - lo) / (hi - lo)
        from plotly.colors import sample_colorscale
        return sample_colorscale(scale, [t])[0]

    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents, values=values, branchvalues="total",
        marker=dict(colors=[to_rgb(c) for c in colors], line=dict(width=1.5, color="#ffffff")),
        text=text, texttemplate="<b>%{label}</b><br>%{text}", hovertext=hover,
        hovertemplate="%{hovertext}<extra></extra>", pathbar=dict(visible=True),
        textfont=dict(color="#111"), tiling=dict(pad=3),
    ))
    # colorbar via invisible scatter
    ticks = [4, 6, 10, 15, 25]
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", showlegend=False, hoverinfo="skip",
        marker=dict(colorscale=scale, cmin=lo, cmax=hi, color=[lo], showscale=True,
                    colorbar=dict(title="P/E", tickvals=[math.log(t) for t in ticks],
                                  ticktext=[f"{t}" + (" cheap" if t == 4 else " pricey" if t == 25 else "") for t in ticks],
                                  len=0.6, thickness=14))))
    fig.update_layout(margin=dict(t=10, l=10, r=10, b=10), height=720,
                      xaxis=dict(visible=False), yaxis=dict(visible=False),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")

    n_missing = df["pe"].isna().sum()
    chart = fig.to_html(full_html=False, include_plotlyjs="cdn", config={"displaylogo": False, "responsive": True})
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Brazil Stock Map (EWZ)</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 16 16%22><text y=%2214%22 font-size=%2214%22>🇧🇷</text></svg>">
<style>
 :root {{ --bg:#fcfcfb; --fg:#0b0b0b; --muted:#52514e; --card:#f4f3f0; }}
 @media (prefers-color-scheme: dark) {{ :root {{ --bg:#1a1a19; --fg:#fff; --muted:#c3c2b7; --card:#232322; }} }}
 body {{ margin:0; background:var(--bg); color:var(--fg); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }}
 .wrap {{ max-width:1200px; margin:0 auto; padding:20px 16px; }}
 h1 {{ margin:0 0 4px; font-size:1.6rem; }}
 .sub {{ color:var(--muted); margin:0 0 14px; }}
 .how {{ background:var(--card); border-radius:10px; padding:12px 16px; margin-bottom:14px; line-height:1.5; }}
 .how b {{ white-space:nowrap; }}
 .foot {{ color:var(--muted); font-size:.85rem; margin-top:10px; }}
 a {{ color:inherit; }}
</style></head><body><div class="wrap">
<h1>🇧🇷 Brazil Stock Map</h1>
<p class="sub">Every company inside the EWZ fund (iShares MSCI Brazil) · holdings as of {asof}</p>
<div class="how">
 <b>📦 Box size</b> = how much of the fund that company is (bigger box = more money invested).<br>
 <b>🗂️ Groups</b> = the type of business (banks, oil, mining, electricity…). Click a group to zoom in; click the top bar to zoom back out.<br>
 <b>🎨 Color</b> = <b>price-to-earnings (P/E)</b>: how many dollars you pay for each $1 the company is expected to earn over the next year.
 <span style="color:#1a9850;font-weight:600">Green = cheap</span> (low P/E),
 <span style="color:#d73027;font-weight:600">red = pricey</span> (high P/E),
 <span style="color:{GRAY};font-weight:600">gray = losing money or no data</span>.
 A P/E of 5 means if profits stayed the same, the company would "earn back" its price in 5 years.
</div>
{chart}
<p class="foot">Source: iShares holdings file; P/E = forward (next-12-month analyst estimates) from Yahoo Finance ({n_missing} with no data). Sector P/E is weight-averaged the way index P/Es are. Not investment advice — just for learning. <a href="../../index.html">← boquin.xyz</a></p>
</div></body></html>"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    print(f"wrote {OUT}  ({len(df)} holdings, {n_missing} missing P/E)")
    print(df[["Ticker", "Sector", "Weight (%)", "pe"]].to_string())


if __name__ == "__main__":
    main()

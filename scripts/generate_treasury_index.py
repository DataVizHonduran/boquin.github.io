"""
Generate index.html for Treasury CTA signals landing page.
Reads summary.json produced by generate_treasury_cta_signals.py.
"""

import os
import json
import numpy as np
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio

OUTPUT_DIR                = "reports/treasury-cta-signals"
HIGH_CONVICTION_THRESHOLD = 60
RECENT_SIGNALS_COUNT      = 12

TENOR_ORDER = ['2Y', '5Y', '10Y', '30Y']

# ── Load summary ──────────────────────────────────────────────────────────────
with open(os.path.join(OUTPUT_DIR, 'summary.json'), 'r') as f:
    all_summaries = json.load(f)

fast_positions   = all_summaries['fast']['latest_positions']
slow_positions   = all_summaries['slow']['latest_positions']
latest_yields    = all_summaries['fast'].get('latest_yields', {})
data_as_of       = all_summaries['fast'].get('data_as_of', 'N/A')
generated_at     = datetime.fromisoformat(all_summaries['fast']['generated_at'])


# ── Signal table helpers ──────────────────────────────────────────────────────

def build_combined_signals(all_summaries, max_recent=RECENT_SIGNALS_COUNT):
    combined = []
    for mode in ['fast', 'slow']:
        for sig in all_summaries.get(mode, {}).get('signal_metadata', []):
            combined.append({**sig, 'mode': mode.upper()})
    combined.sort(key=lambda x: x['date'], reverse=True)
    return combined[:max_recent]


def build_high_conviction_signals(all_summaries, threshold=HIGH_CONVICTION_THRESHOLD):
    combined = []
    for mode in ['fast', 'slow']:
        for sig in all_summaries.get(mode, {}).get('signal_metadata', []):
            if sig.get('strength_score', 0) >= threshold:
                combined.append({**sig, 'mode': mode.upper()})
    combined.sort(key=lambda x: (x['strength_score'], x['date']), reverse=True)
    return combined[:20]


def render_signal_row(sig):
    direction_class = 'dir-long' if sig['direction'] == 'Long' else 'dir-short'
    direction_arrow = '▲' if sig['direction'] == 'Long' else '▼'
    score       = int(sig.get('strength_score', 0))
    score_class = 'score-high' if score >= 60 else ('score-mid' if score >= 35 else 'score-low')
    consensus_badge = (' <span class="consensus-badge">✓ Consensus</span>'
                       if sig.get('consensus_score', 0) > 0 else '')
    direction_label = ('Long Duration' if sig['direction'] == 'Long'
                       else 'Short Duration')
    return (
        f'<tr>'
        f'<td>{sig["date"]}</td>'
        f'<td><strong>{sig.get("tenor", sig.get("currency", ""))}</strong></td>'
        f'<td class="{direction_class}">{direction_arrow} {direction_label}{consensus_badge}</td>'
        f'<td><span class="mode-badge mode-{sig["mode"].lower()}">{sig["mode"]}</span></td>'
        f'<td class="score-cell {score_class}">{score}</td>'
        f'<td class="peak-cell">{sig.get("peak_position", 0):.1f}</td>'
        f'</tr>'
    )


recent_signals = build_combined_signals(all_summaries)
hc_signals     = build_high_conviction_signals(all_summaries)
recent_rows    = '\n'.join(render_signal_row(s) for s in recent_signals)
hc_rows        = '\n'.join(render_signal_row(s) for s in hc_signals)


# ── CTA reversal charts (z-score of positioning residuals) ───────────────────

def _build_cta_reversal_divs(output_dir, tenor_order, z_window=252):
    """Build one 2-row Plotly chart per tenor: yield + CTA positioning z-score.
    Returns a dict {tenor: html_div_string}."""
    pos_fast  = pd.read_csv(os.path.join(output_dir, 'positions_fast.csv'),
                            index_col=0, parse_dates=True)
    yields_df = pd.read_csv(os.path.join(output_dir, 'yields.csv'),
                            index_col=0, parse_dates=True)

    divs = {}
    for tenor in tenor_order:
        if tenor not in pos_fast.columns or tenor not in yields_df.columns:
            continue

        pos = pos_fast[tenor].dropna()
        yld = yields_df[tenor].reindex(pos.index).ffill()

        # Rolling z-score of positioning (1-year window)
        roll = pos.rolling(z_window, min_periods=126)
        z = (pos - roll.mean()) / roll.std()

        # Crossback reversal markers
        prev_z = z.shift(1)
        sell_rev = pos.index[(prev_z > 1.0) & (z <= 1.0)]   # crowded short unwinds
        buy_rev  = pos.index[(prev_z < -1.0) & (z >= -1.0)] # crowded long unwinds

        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            row_heights=[0.45, 0.55],
            vertical_spacing=0.06,
            subplot_titles=(
                f"{tenor} Treasury Yield",
                f"{tenor} CTA Positioning Z-Score (252d rolling) — Reversal Signals",
            ),
        )

        # Row 1: yield
        fig.add_trace(go.Scatter(
            x=yld.index, y=yld,
            name=f"{tenor} Yield",
            line=dict(color="#1f77b4", width=1.5),
            hovertemplate="%{x|%Y-%m-%d}: %{y:.2f}%<extra></extra>",
        ), row=1, col=1)

        # Row 2: positioning z-score
        fig.add_trace(go.Scatter(
            x=z.index, y=z,
            name="Positioning Z",
            line=dict(color="#444", width=1.2),
            hovertemplate="%{x|%Y-%m-%d}: %{y:.2f}σ<extra>Z-Score</extra>",
        ), row=2, col=1)

        fig.add_hline(y=0,    line=dict(color="#aaa", width=1, dash="dot"), row=2, col=1)
        fig.add_hline(y=1.0,  line=dict(color="#dc3545", width=1, dash="dash"), row=2, col=1)
        fig.add_hline(y=-1.0, line=dict(color="#28a745", width=1, dash="dash"), row=2, col=1)

        # Sell-reversal: crowded short unwind (CTAs were max short duration, now covering)
        if len(sell_rev):
            fig.add_trace(go.Scatter(
                x=sell_rev, y=z.reindex(sell_rev),
                mode="markers", name="Short Unwind",
                marker=dict(symbol="triangle-down", size=12, color="#dc3545",
                            line=dict(color="white", width=1)),
                hovertemplate="%{x|%Y-%m-%d}: Z=%{y:.2f}σ<extra>Short Unwind</extra>",
            ), row=2, col=1)

        # Buy-reversal: crowded long unwind (CTAs were max long duration, now selling)
        if len(buy_rev):
            fig.add_trace(go.Scatter(
                x=buy_rev, y=z.reindex(buy_rev),
                mode="markers", name="Long Unwind",
                marker=dict(symbol="triangle-up", size=12, color="#28a745",
                            line=dict(color="white", width=1)),
                hovertemplate="%{x|%Y-%m-%d}: Z=%{y:.2f}σ<extra>Long Unwind</extra>",
            ), row=2, col=1)

        # Background shading on row 1: extreme z episodes
        for sign, color in [(1, "rgba(220,53,69,0.07)"), (-1, "rgba(40,167,69,0.07)")]:
            in_ep, ep_start = False, None
            for dt, zv in z.items():
                if not in_ep and (sign * zv) > 1.0:
                    in_ep, ep_start = True, dt
                elif in_ep and (sign * zv) <= 1.0:
                    fig.add_vrect(x0=ep_start, x1=dt, fillcolor=color,
                                  layer="below", line_width=0, row=1, col=1)
                    in_ep = False
            if in_ep:
                fig.add_vrect(x0=ep_start, x1=z.index[-1], fillcolor=color,
                              layer="below", line_width=0, row=1, col=1)

        fig.update_layout(
            height=480, template="plotly_white",
            margin=dict(t=60, l=55, r=20, b=40),
            hovermode="x unified",
            legend=dict(orientation="h", x=0.01, y=-0.08, font=dict(size=11)),
            showlegend=True,
        )
        fig.update_yaxes(ticksuffix="%", row=1, col=1)
        fig.update_yaxes(title_text="Z-Score (σ)", row=2, col=1)

        divs[tenor] = pio.to_html(fig, full_html=False, include_plotlyjs=False,
                                   config={"displayModeBar": False})
    return divs


# ── CTA positioning bar chart ─────────────────────────────────────────────────

def create_position_bar_chart(positions, mode):
    tenors = [t for t in TENOR_ORDER if t in positions]
    values = [positions[t] for t in tenors]
    colors = ['#28a745' if v > 0 else '#dc3545' for v in values]

    fig = go.Figure(go.Bar(
        x=tenors, y=values,
        marker_color=colors,
        text=[f'{v:+.1f}' for v in values],
        textposition='outside',
        textfont=dict(size=14, color='#333'),
    ))
    fig.update_layout(
        title=dict(
            text=f'CTA Positioning — {mode.upper()} Mode',
            x=0.5, xanchor='center', font=dict(size=16, color='#1a1a2e')
        ),
        xaxis=dict(title='Tenor', tickfont=dict(size=13)),
        yaxis=dict(title='Position Score', range=[-55, 55],
                   zeroline=True, zerolinecolor='black', zerolinewidth=1.5,
                   tickfont=dict(size=12)),
        plot_bgcolor='white',
        width=540, height=380,
        margin=dict(t=60, b=60, l=60, r=30),
        showlegend=False,
    )
    fig.add_annotation(
        text="+ = Short Duration / − = Long Duration",
        xref='paper', yref='paper', x=0.5, y=-0.17,
        showarrow=False, font=dict(size=11, color='grey')
    )
    return fig


fig_fast = create_position_bar_chart(fast_positions, 'fast')
fig_slow = create_position_bar_chart(slow_positions, 'slow')

fast_chart_div = pio.to_html(fig_fast, full_html=False, include_plotlyjs=False)
slow_chart_div = pio.to_html(fig_slow, full_html=False, include_plotlyjs=False)

print("Building CTA Treasury Reversal charts...")
reversal_chart_divs = _build_cta_reversal_divs(OUTPUT_DIR, TENOR_ORDER)
reversal_grid_html = ''.join(
    f'<div style="background:white;border-radius:10px;padding:14px;'
    f'box-shadow:0 2px 8px rgba(0,0,0,0.07);">{reversal_chart_divs.get(t,"")}</div>'
    for t in TENOR_ORDER
)


# ── Yield snapshot table ──────────────────────────────────────────────────────

def render_yield_row(tenor):
    yld = latest_yields.get(tenor, 'N/A')
    fp  = fast_positions.get(tenor, 0)
    sp  = slow_positions.get(tenor, 0)
    avg = (fp + sp) / 2

    pos_label = ('Short Duration' if avg > 10
                 else 'Long Duration' if avg < -10
                 else 'Neutral')
    pos_class = ('dir-short' if avg > 10
                 else 'dir-long' if avg < -10
                 else '')
    return (
        f'<tr>'
        f'<td><strong>{tenor}</strong></td>'
        f'<td>{yld:.2f}%</td>'
        f'<td>{fp:+.1f}</td>'
        f'<td>{sp:+.1f}</td>'
        f'<td class="{pos_class}">{pos_label}</td>'
        f'</tr>'
    )


yield_rows = '\n'.join(render_yield_row(t) for t in TENOR_ORDER if t in latest_yields)

# Fast / Slow signal count summary
fast_total = all_summaries['fast']['signal_count']
slow_total = all_summaries['slow']['signal_count']
fast_hc    = all_summaries['fast']['high_conviction_count']
slow_hc    = all_summaries['slow']['high_conviction_count']


# ── Chart links ───────────────────────────────────────────────────────────────
def chart_card(tenor, mode):
    fname = f"{tenor}_exhaustion_{mode}.html"
    return (
        f'<a href="{fname}" class="chart-card">'
        f'<div class="chart-tenor">{tenor}</div>'
        f'<div class="chart-mode">{mode.upper()}</div>'
        f'</a>'
    )


chart_links_fast = ' '.join(chart_card(t, 'fast') for t in TENOR_ORDER)
chart_links_slow = ' '.join(chart_card(t, 'slow') for t in TENOR_ORDER)


# ── Build HTML ─────────────────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Treasury CTA Exhaustion Signals</title>
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
<style>
  :root {{
    --navy:  #1a1a2e;
    --teal:  #16213e;
    --blue:  #0f3460;
    --accent:#e94560;
    --green: #28a745;
    --red:   #dc3545;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f5f7fa;
    color: #333;
  }}
  header {{
    background: linear-gradient(135deg, var(--navy), var(--blue));
    color: white;
    padding: 28px 40px;
  }}
  header h1 {{ font-size: 2rem; margin-bottom: 4px; }}
  header p  {{ opacity: 0.75; font-size: 0.95rem; }}
  .badge-row {{ display: flex; gap: 12px; margin-top: 14px; flex-wrap: wrap; }}
  .badge {{
    background: rgba(255,255,255,0.15);
    border: 1px solid rgba(255,255,255,0.3);
    border-radius: 20px;
    padding: 4px 14px;
    font-size: 0.82rem;
  }}
  main {{ max-width: 1300px; margin: 0 auto; padding: 30px 24px; }}
  h2 {{
    font-size: 1.25rem; color: var(--navy);
    border-bottom: 2px solid var(--accent);
    padding-bottom: 6px; margin-bottom: 18px;
  }}
  /* ── Yield snapshot ── */
  .yield-table {{
    width: 100%; border-collapse: collapse; margin-bottom: 32px;
    background: white; border-radius: 10px; overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
  }}
  .yield-table th, .yield-table td {{
    padding: 12px 16px; text-align: center; font-size: 0.9rem;
  }}
  .yield-table th {{
    background: var(--navy); color: white; font-weight: 600;
  }}
  .yield-table tr:nth-child(even) {{ background: #f9f9f9; }}
  /* ── Bar charts ── */
  .charts-grid {{
    display: grid; grid-template-columns: 1fr 1fr; gap: 20px;
    margin-bottom: 32px;
  }}
  .chart-box {{
    background: white; border-radius: 10px; padding: 16px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
  }}
  /* ── Top-level page tabs ── */
  .page-tab-bar {{
    display: flex; gap: 0; margin: 0 0 30px;
    border-bottom: 3px solid var(--navy);
  }}
  .page-tab-btn {{
    padding: 10px 28px; cursor: pointer;
    border: none; border-radius: 8px 8px 0 0;
    background: #e8eaf0; font-weight: 700;
    color: var(--navy); font-size: 0.95rem;
    transition: all 0.2s; margin-right: 4px;
  }}
  .page-tab-btn.active {{ background: var(--navy); color: white; }}
  .page-tab-pane {{ display: none; }}
  .page-tab-pane.active {{ display: block; }}
  /* ── Mode tabs (inner) ── */
  .tab-bar {{
    display: flex; gap: 8px; margin-bottom: 14px;
  }}
  .tab-btn {{
    padding: 7px 20px; border-radius: 20px; cursor: pointer;
    border: 2px solid var(--navy); background: white;
    font-weight: 600; color: var(--navy); font-size: 0.88rem;
    transition: all 0.2s;
  }}
  .tab-btn.active {{ background: var(--navy); color: white; }}
  .tab-pane {{ display: none; }}
  .tab-pane.active {{ display: block; }}
  /* ── Chart card links ── */
  .chart-cards {{
    display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 32px;
  }}
  .chart-card {{
    display: flex; flex-direction: column; align-items: center;
    justify-content: center;
    width: 110px; height: 80px;
    background: white; border-radius: 10px;
    border: 2px solid #ddd;
    text-decoration: none; color: var(--navy);
    transition: all 0.2s;
    box-shadow: 0 2px 6px rgba(0,0,0,0.07);
  }}
  .chart-card:hover {{
    border-color: var(--accent); box-shadow: 0 4px 12px rgba(233,69,96,0.2);
    transform: translateY(-2px);
  }}
  .chart-tenor {{ font-size: 1.1rem; font-weight: 700; }}
  .chart-mode  {{ font-size: 0.72rem; color: #888; text-transform: uppercase; }}
  /* ── Signal tables ── */
  .signal-table {{
    width: 100%; border-collapse: collapse; margin-bottom: 32px;
    background: white; border-radius: 10px; overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
  }}
  .signal-table th, .signal-table td {{
    padding: 10px 14px; text-align: center; font-size: 0.87rem;
  }}
  .signal-table th   {{ background: var(--navy); color: white; font-weight: 600; }}
  .signal-table tr:nth-child(even) {{ background: #f9f9f9; }}
  .dir-long  {{ color: var(--green); font-weight: 600; }}
  .dir-short {{ color: var(--red);   font-weight: 600; }}
  .mode-badge {{
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    font-size: 0.78rem; font-weight: 700; letter-spacing: 0.5px;
  }}
  .mode-fast {{ background: #fff3cd; color: #856404; }}
  .mode-slow {{ background: #cce5ff; color: #004085; }}
  .score-high {{ color: #155724; font-weight: 700; }}
  .score-mid  {{ color: #856404; font-weight: 600; }}
  .score-low  {{ color: #888;    font-weight: 400; }}
  .score-cell {{ font-size: 0.95rem; font-variant-numeric: tabular-nums; }}
  .peak-cell  {{ font-variant-numeric: tabular-nums; }}
  .consensus-badge {{
    background: #d4edda; color: #155724;
    border-radius: 10px; padding: 1px 6px; font-size: 0.75rem;
    margin-left: 4px;
  }}
  /* ── Stats cards ── */
  .stats-row {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px;
    margin-bottom: 32px;
  }}
  .stat-card {{
    background: white; border-radius: 10px; padding: 18px 16px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.07); text-align: center;
  }}
  .stat-value {{ font-size: 1.8rem; font-weight: 700; color: var(--navy); }}
  .stat-label {{ font-size: 0.8rem; color: #888; margin-top: 4px; }}
  footer {{
    text-align: center; padding: 28px;
    color: #aaa; font-size: 0.82rem; margin-top: 20px;
  }}
  @media (max-width: 768px) {{
    .charts-grid {{ grid-template-columns: 1fr; }}
    .stats-row   {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>

<header>
  <h1>🏛️ Treasury CTA Exhaustion Signals</h1>
  <p>Trend-following positioning model applied to 2Y / 5Y / 10Y / 30Y US Treasury yields</p>
  <div class="badge-row">
    <span class="badge">Data as of {data_as_of}</span>
    <span class="badge">Generated {generated_at.strftime('%Y-%m-%d %H:%M')}</span>
    <span class="badge">FRED: DGS2 · DGS5 · DGS10 · DGS30</span>
    <span class="badge">Fast (20/50/100) + Slow (50/100/200)</span>
  </div>
</header>

<main>

  <!-- ── Top-level page tabs ── -->
  <div class="page-tab-bar">
    <button class="page-tab-btn active" onclick="switchPage('overview', this)">CTA Exhaustion</button>
    <button class="page-tab-btn"        onclick="switchPage('reversal', this)">CTA Treasury Reversal</button>
  </div>

  <!-- ══ Tab: CTA Exhaustion (existing content) ══ -->
  <div id="page-tab-overview" class="page-tab-pane active">

    <!-- ── Current yield snapshot ── -->
    <h2>Current Treasury Yield Snapshot</h2>
    <table class="yield-table">
      <thead>
        <tr>
          <th>Tenor</th>
          <th>Yield</th>
          <th>Fast Position</th>
          <th>Slow Position</th>
          <th>CTA Lean</th>
        </tr>
      </thead>
      <tbody>
        {yield_rows}
      </tbody>
    </table>

    <!-- ── Positioning bar charts ── -->
    <h2>CTA Positioning by Mode</h2>
    <div class="charts-grid">
      <div class="chart-box">{fast_chart_div}</div>
      <div class="chart-box">{slow_chart_div}</div>
    </div>

    <!-- ── Chart links ── -->
    <h2>Individual Tenor Charts</h2>
    <div class="tab-bar">
      <button class="tab-btn active" onclick="switchTab('fast', this)">Fast Mode (20/50/100)</button>
      <button class="tab-btn"       onclick="switchTab('slow', this)">Slow Mode (50/100/200)</button>
    </div>
    <div id="tab-fast" class="tab-pane active">
      <div class="chart-cards">{chart_links_fast}</div>
    </div>
    <div id="tab-slow" class="tab-pane">
      <div class="chart-cards">{chart_links_slow}</div>
    </div>

  </div><!-- /page-tab-overview -->

  <!-- ══ Tab: CTA Treasury Reversal ══ -->
  <div id="page-tab-reversal" class="page-tab-pane">
    <h2>CTA Treasury Reversal — Positioning Residuals &amp; Z-Score Signals</h2>
    <p style="color:#666;font-size:0.9rem;margin-bottom:22px;">
      Z-score of CTA fast-mode positioning (252-day rolling). Extremes flag crowded positions;
      crossbacks through ±1σ mark the unwind.
      <span style="color:#dc3545;font-weight:600;">▼ Short Unwind</span> = crowded short-duration bet reversing &nbsp;·&nbsp;
      <span style="color:#28a745;font-weight:600;">▲ Long Unwind</span> = crowded long-duration bet reversing.
    </p>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
      {reversal_grid_html}
    </div>
  </div><!-- /page-tab-reversal -->

</main>

<footer>
  Data sourced from FRED (Federal Reserve Bank of St. Louis) · DGS2, DGS5, DGS10, DGS30<br>
  CTA exhaustion model: dual-mode EMA positioning with rolling percentile thresholds, ROC filter, RSI confirmation, and strength scoring.<br>
  Positive position = short duration (rising yields) · Negative position = long duration (falling yields)
</footer>

<script>
function switchPage(page, btn) {{
  document.querySelectorAll('.page-tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.page-tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('page-tab-' + page).classList.add('active');
  btn.classList.add('active');
}}
function switchTab(mode, btn) {{
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + mode).classList.add('active');
  btn.classList.add('active');
}}
</script>

</body>
</html>"""

out_path = os.path.join(OUTPUT_DIR, 'index.html')
with open(out_path, 'w') as f:
    f.write(html)

print(f"✅ index.html written → {out_path}")
print(f"   Fast: {fast_total} signals ({fast_hc} high-conviction)")
print(f"   Slow: {slow_total} signals ({slow_hc} high-conviction)")

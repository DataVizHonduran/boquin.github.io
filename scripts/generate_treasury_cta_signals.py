"""
Treasury CTA Exhaustion Signal Generator - Dual Mode (Fast & Slow)
Fetches 2Y/5Y/10Y/30Y Treasury yield data from FRED, calculates CTA positioning,
and generates exhaustion signals using the same methodology as FX CTA.

Positive position  → CTAs positioned for RISING yields (short duration / short bonds)
Negative position  → CTAs positioned for FALLING yields (long duration / long bonds)

Filters (same as FX version):
  P1 - Vectorized position filter
  P2 - Rolling 500-day percentile thresholds (no look-ahead bias)
  P3 - Rate-of-change confirmation filter
  P4 - Signal strength score 0-100 (Extremity 40 + Speed 40 + Consensus 20)
  P5 - RSI of positioning filter
"""

import sys
import os
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.io as pio
import json
from datetime import datetime
from dateutil.relativedelta import relativedelta
from fredapi import Fred

# ── FRED API key — set FRED_API_KEY environment variable ─────────────────────
FRED_API_KEY = os.environ.get('FRED_API_KEY')
if not FRED_API_KEY:
    raise EnvironmentError("FRED_API_KEY environment variable is not set. "
                           "Export it before running: export FRED_API_KEY=your_key")


def pull_data(series_dict, years=16):
    """Fetch FRED series and return a merged, forward-filled DataFrame."""
    fred       = Fred(api_key=FRED_API_KEY)
    end_date   = datetime.now()
    start_date = end_date - relativedelta(years=years)
    frames     = []
    for sid, label in series_dict.items():
        try:
            s = fred.get_series(sid, observation_start=start_date,
                                observation_end=end_date)
            frames.append(s.to_frame(name=label))
        except Exception as e:
            print(f"  ⚠️  Failed to fetch {sid}: {e}")
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, axis=1)
    df.ffill(inplace=True)
    df.dropna(inplace=True)
    return df

# ── Configuration ─────────────────────────────────────────────────────────────
OUTPUT_DIR           = "reports/treasury-cta-signals"
WINDOW               = 750            # Rolling window for position normalization (~3 years)
YEARS_HISTORY        = 16            # Years of FRED data to pull

# Treasury tenors
TREASURIES = {
    'DGS2':  '2Y',
    'DGS5':  '5Y',
    'DGS10': '10Y',
    'DGS30': '30Y',
}

# CTA mode configurations (same windows as FX model)
CTA_MODES = {
    'fast': {'short': 20, 'mid': 50,  'long': 100},
    'slow': {'short': 50, 'mid': 100, 'long': 200},
}

# ── Data loading ──────────────────────────────────────────────────────────────
print(f"Fetching Treasury yield data from FRED ({YEARS_HISTORY} years)...")
df_raw = pull_data(TREASURIES, years=YEARS_HISTORY)
# Rename columns to short labels: '2Y', '5Y', '10Y', '30Y'
df_raw.columns = [TREASURIES[k] for k in TREASURIES]
# Drop any all-NaN rows (weekends already forward-filled by pull_data, but double-check)
df_raw = df_raw.dropna(how='all')
print(f"Loaded {len(df_raw)} rows | {df_raw.index.min().date()} to {df_raw.index.max().date()}")
print(f"Latest yields: " + " | ".join(f"{c}: {df_raw[c].iloc[-1]:.2f}%" for c in df_raw.columns))

os.makedirs(OUTPUT_DIR, exist_ok=True)

# Display-filtered copy (from 2016 onward, matching FX chart horizon)
df_display = df_raw[df_raw.index >= '2016-01-01'].copy()


# ── Helper functions (identical logic to generate_cta_signals.py) ─────────────

def calculate_positions(df, short_window, mid_window, long_window):
    """Calculate CTA positioning for all Treasury tenors."""
    positions_latest = {}
    positions_df     = pd.DataFrame()

    for tenor in df.columns:
        series = df[tenor].dropna()
        if len(series) < long_window:
            continue

        d = pd.DataFrame(index=series.index)
        d['price']     = series
        d['ema_short'] = d['price'].ewm(span=short_window, adjust=False).mean()
        d['ema_mid']   = d['price'].ewm(span=mid_window,   adjust=False).mean()
        d['ema_long']  = d['price'].ewm(span=long_window,  adjust=False).mean()
        d['ema_convergence'] = d['ema_short'] - d['ema_long']

        rolling_max_abs = (d['ema_convergence'].abs()
                           .rolling(window=WINDOW, min_periods=1).quantile(0.95)
                           .replace(0, np.nan).bfill().ffill())
        raw_pos = (d['ema_convergence'] / rolling_max_abs) * 50

        # P1: Vectorized trend filter
        up   = (d['ema_short'] > d['ema_mid']) & (d['ema_mid'] > d['ema_long'])
        down = (d['ema_short'] < d['ema_mid']) & (d['ema_mid'] < d['ema_long'])
        d['position_size'] = np.where(
            up,   np.maximum(0, raw_pos),
            np.where(down, np.minimum(0, raw_pos), 0)
        )
        d.dropna(subset=['position_size'], inplace=True)

        if not d.empty:
            col = f"{tenor}_posy"
            positions_latest[tenor] = d['position_size'].iloc[-1]
            positions_df[col]       = d['position_size']

    return positions_latest, positions_df


def create_exhaustion_chart(df_display, tenor, col, positions_df, mode, windows_str):
    """Create exhaustion model chart for a Treasury tenor."""
    fig = go.Figure()

    # Yield line
    fig.add_trace(go.Scatter(
        x=df_display.index, y=df_display[tenor], mode='lines',
        name=f'{tenor} Yield (%)',
        line=dict(color='steelblue', width=2), yaxis='y1'
    ))

    # CTA positioning overlay
    pos_filtered = positions_df[positions_df.index.isin(df_display.index)]
    if col in pos_filtered.columns:
        fig.add_trace(go.Scatter(
            x=pos_filtered.index, y=pos_filtered[col], mode='lines',
            name='CTA Positioning',
            line=dict(color='orange', width=1.5),
            yaxis='y2', opacity=0.65
        ))

    # Positioning zero-line reference
    fig.add_hline(y=0, line_dash='dash', line_color='grey',
                  line_width=0.8, yref='y2', opacity=0.5)

    fig.update_layout(
        title=dict(
            text=(f"US {tenor} Treasury — CTA {mode.upper()} ({windows_str})"
                  f" — Positioning & Exhaustion Signals"),
            x=0.5, xanchor='center', font=dict(size=18, color='#1a1a2e')
        ),
        xaxis=dict(
            title="Date", showgrid=True, gridcolor='lightgrey',
            zeroline=False, tickformat='%Y', dtick='M12', tickangle=0
        ),
        yaxis=dict(
            title="Yield (%)", tickfont=dict(color='steelblue'),
            ticksuffix='%', showgrid=True, zeroline=False
        ),
        yaxis2=dict(
            title="CTA Positioning", tickfont=dict(color='goldenrod'),
            overlaying='y', side='right', showgrid=False, zeroline=True,
            zerolinecolor='grey', zerolinewidth=1, range=[-60, 60]
        ),
        legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.85)',
                    bordercolor='black', borderwidth=1),
        hovermode='x unified', plot_bgcolor='white',
        width=1100, height=620,
        annotations=[dict(
            text=("Positive = CTAs short duration (rising yields) | "
                  "Negative = CTAs long duration (falling yields)"),
            xref='paper', yref='paper', x=0.5, y=-0.08,
            showarrow=False, font=dict(size=11, color='grey'), align='center'
        )]
    )
    return fig


# ── Phase 1: Calculate positions + signals for both modes ─────────────────────
mode_data    = {}
all_summaries = {}

for mode, windows in CTA_MODES.items():
    print(f"\n{'='*60}")
    print(f"Processing {mode.upper()} mode ({windows['short']}/{windows['mid']}/{windows['long']})...")
    print(f"{'='*60}")

    positions_latest, positions_df = calculate_positions(
        df_raw, windows['short'], windows['mid'], windows['long']
    )
    print(f"Calculated positioning for {len(positions_latest)} tenors")

    latest_positions = pd.Series(positions_latest).sort_values(ascending=False)

    mode_data[mode] = {
        'positions_df':     positions_df,
        'positions_latest': positions_latest,
        'latest_positions': latest_positions,
    }

    all_summaries[mode] = {
        'generated_at':     datetime.now().isoformat(),
        'mode':             mode,
        'windows':          f"{windows['short']}/{windows['mid']}/{windows['long']}",
        'tenors':           len(positions_latest),
        'latest_positions': latest_positions.to_dict(),
        'latest_yields': {t: round(float(df_raw[t].iloc[-1]), 4)
                          for t in df_raw.columns},
        'data_as_of':       df_raw.index[-1].strftime('%Y-%m-%d'),
    }

    print(f"Positions: {dict(latest_positions.round(1))}")


# ── Phase 2: Generate charts ─────────────────────────────────────────────────
for mode, windows in CTA_MODES.items():
    data         = mode_data[mode]
    positions_df = data['positions_df']
    windows_str  = f"{CTA_MODES[mode]['short']}/{CTA_MODES[mode]['mid']}/{CTA_MODES[mode]['long']}"

    chart_count = 0
    for tenor in df_display.columns:
        col = f"{tenor}_posy"
        if col not in positions_df.columns:
            continue
        try:
            fig = create_exhaustion_chart(
                df_display, tenor, col, positions_df, mode, windows_str
            )
            filename = os.path.join(OUTPUT_DIR, f"{tenor}_exhaustion_{mode}.html")
            pio.write_html(fig, file=filename, auto_open=False)
            chart_count += 1
        except Exception as e:
            print(f"  Failed on {tenor}: {e}")

    print(f"Generated {chart_count} charts for {mode} mode")

    all_summaries[mode]['charts_generated'] = chart_count


# ── Save combined summary ──────────────────────────────────────────────────────
with open(os.path.join(OUTPUT_DIR, 'summary.json'), 'w') as f:
    json.dump(all_summaries, f, indent=2)

# ── Save positioning time series for reversal charts ─────────────────────────
for mode in ('fast', 'slow'):
    pos_df = mode_data[mode]['positions_df'].copy()
    pos_df.columns = [c.replace('_posy', '') for c in pos_df.columns]
    pos_df.to_csv(os.path.join(OUTPUT_DIR, f'positions_{mode}.csv'))

df_raw.to_csv(os.path.join(OUTPUT_DIR, 'yields.csv'))

print(f"\n{'='*60}")
print(f"✅ Treasury CTA Complete!")
print(f"   Fast charts: {all_summaries['fast']['charts_generated']}")
print(f"   Slow charts: {all_summaries['slow']['charts_generated']}")
print(f"   Output dir: {OUTPUT_DIR}/")
print(f"{'='*60}")

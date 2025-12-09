"""
CTA Exhaustion Signal Generator - Dual Mode (Fast & Slow)
Fetches FX data, calculates CTA positioning, and generates exhaustion signals
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.io as pio
import os
import json
from datetime import datetime

# Configuration
FX_DATA_URL = "https://raw.githubusercontent.com/DataVizHonduran/EMFX_risk_diffusion/main/fx_data_raw.csv"
OUTPUT_DIR = "reports/cta-signals"
GAP = 5  # Hysteresis band for exhaustion signals
WINDOW = 2500  # Rolling window for position normalization

# CTA mode configurations
CTA_MODES = {
    'fast': {'short': 20, 'mid': 50, 'long': 100},
    'slow': {'short': 50, 'mid': 100, 'long': 200}
}

print(f"Loading FX data from {FX_DATA_URL}...")
df_fx = pd.read_csv(FX_DATA_URL, index_col=0, parse_dates=True)
df_fx = df_fx.apply(pd.to_numeric, errors='coerce')
print(f"Loaded {len(df_fx)} rows and {len(df_fx.columns)} currencies")

# Process currencies
inverse = ["EUR", "GBP", "AUD", "NZD"]
df_fx[inverse] = 1 / df_fx[inverse]
euroy = ["GBP", "SEK", "NOK", "HUF", "PLN", "CZK"]
df_fx[euroy] = df_fx[euroy].multiply(df_fx["EUR"], axis=0)

# Prepare display data
inverse_display = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"]
df_display = df_fx.copy()
df_display[inverse] = 1 / df_display[inverse]
# Filter to start from 2016
df_display = df_display[df_display.index >= '2016-01-01']

os.makedirs(OUTPUT_DIR, exist_ok=True)

def calculate_positions(df_fx, short_window, mid_window, long_window):
    """Calculate CTA positioning for all currencies"""
    positions_latest = {}
    positions_df = pd.DataFrame()

    for currency in df_fx.columns:
        price_series = df_fx[currency].dropna()
        if len(price_series) < long_window:
            continue

        df = pd.DataFrame(index=price_series.index)
        df['price'] = price_series
        df['ema_short'] = df['price'].ewm(span=short_window, adjust=False).mean()
        df['ema_mid'] = df['price'].ewm(span=mid_window, adjust=False).mean()
        df['ema_long'] = df['price'].ewm(span=long_window, adjust=False).mean()
        df['ema_convergence'] = df['ema_short'] - df['ema_long']

        rolling_max_abs_conv = df['ema_convergence'].abs().rolling(window=WINDOW, min_periods=1).max()
        rolling_max_abs_conv = rolling_max_abs_conv.replace(0, np.nan).bfill().ffill()
        raw_position_rolling = (df['ema_convergence'] / rolling_max_abs_conv) * 50

        def filtered_position(row):
            if row['ema_short'] > row['ema_mid'] > row['ema_long']:
                return max(0, raw_position_rolling.loc[row.name])
            elif row['ema_short'] < row['ema_mid'] < row['ema_long']:
                return min(0, raw_position_rolling.loc[row.name])
            else:
                return 0

        df['position_size'] = df.apply(filtered_position, axis=1)
        df.dropna(inplace=True)

        if not df.empty:
            positions_latest[currency] = df['position_size'].iloc[-1]
            positions_df[f"{currency}_posy"] = df['position_size']

    return positions_latest, positions_df

def generate_exhaustion_signals(positions_df, thresholds):
    """Generate directional exhaustion signals"""
    signals = pd.DataFrame(index=positions_df.index, columns=positions_df.columns, dtype=int)
    extreme_mode = {col: None for col in positions_df.columns}

    for col in positions_df.columns:
        upper_enter, upper_exit, lower_enter, lower_exit = thresholds.get(col, (45, 40, -45, -40))

        for i in range(len(positions_df)):
            pos = positions_df.iloc[i][col]

            if extreme_mode[col] is None:
                if pos >= upper_enter:
                    extreme_mode[col] = 'long'
                    signals.iloc[i, signals.columns.get_loc(col)] = 0
                elif pos <= lower_enter:
                    extreme_mode[col] = 'short'
                    signals.iloc[i, signals.columns.get_loc(col)] = 0
                else:
                    signals.iloc[i, signals.columns.get_loc(col)] = 0
            elif extreme_mode[col] == 'long':
                if pos < upper_exit:
                    signals.iloc[i, signals.columns.get_loc(col)] = 1
                    extreme_mode[col] = None
                else:
                    signals.iloc[i, signals.columns.get_loc(col)] = 0
            elif extreme_mode[col] == 'short':
                if pos > lower_exit:
                    signals.iloc[i, signals.columns.get_loc(col)] = 1
                    extreme_mode[col] = None
                else:
                    signals.iloc[i, signals.columns.get_loc(col)] = 0

    return signals

def create_exhaustion_chart(df, ccy, currency, positions_df, signals_df, mode, windows):
    """Create exhaustion model chart"""
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df.index, y=df[ccy], mode='lines',
        name='Price', line=dict(color='teal', width=2), yaxis='y1'
    ))

    # Filter positioning to match price data timeframe
    pos_filtered = positions_df[positions_df.index.isin(df.index)]

    fig.add_trace(go.Scatter(
        x=pos_filtered.index, y=pos_filtered[currency], mode='lines',
        name='CTA Positioning', line=dict(color='orange', width=1.5),
        yaxis='y2', opacity=0.6
    ))

    if currency in signals_df.columns:
        signal_points = signals_df[currency] == 1
        signal_dates = signals_df.index[signal_points].intersection(df.index)
        signal_prices = df.loc[signal_dates, ccy]

        fig.add_trace(go.Scatter(
            x=signal_dates, y=signal_prices, mode='markers',
            marker=dict(color='red', size=10, line=dict(color='black', width=1)),
            name='Exhaustion Signals', yaxis='y1'
        ))

    fig.update_layout(
        title=dict(
            text=f"{ccy} - CTA {mode.upper()} ({windows}) - Positioning & Exhaustion Signals",
            x=0.5, xanchor='center', font=dict(size=18, color='darkblue')
        ),
        xaxis=dict(title="Date", showgrid=True, gridcolor='lightgrey',
                   zeroline=False, tickformat='%Y', dtick='M12', tickangle=0),
        yaxis=dict(title="Price", tickfont=dict(color='teal'),
                   showgrid=True, zeroline=False),
        yaxis2=dict(title="CTA Positioning", tickfont=dict(color='goldenrod'),
                    overlaying='y', side='right', showgrid=False, zeroline=False),
        legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.8)',
                    bordercolor='black', borderwidth=1),
        hovermode='x unified', plot_bgcolor='white',
        width=1000, height=600
    )
    return fig

# Process both fast and slow modes
all_summaries = {}

for mode, windows in CTA_MODES.items():
    print(f"\n{'='*60}")
    print(f"Processing {mode.upper()} mode ({windows['short']}/{windows['mid']}/{windows['long']})...")
    print(f"{'='*60}")

    # Calculate positions
    positions_latest, positions_df = calculate_positions(
        df_fx, windows['short'], windows['mid'], windows['long']
    )
    print(f"Calculated positioning for {len(positions_latest)} currencies")

    # Calculate thresholds
    percentiles_90 = positions_df.quantile(0.85).round()
    percentiles_10 = positions_df.quantile(0.15).round()

    thresholds = {
        cur: (upper, upper - GAP if upper - GAP > 0 else upper - 3,
              lower, lower + GAP if lower + GAP < 0 else lower + 3)
        for cur, upper, lower in zip(percentiles_90.index, percentiles_90, percentiles_10)
    }

    # Generate signals
    signals_df = generate_exhaustion_signals(positions_df, thresholds)
    print(f"Generated exhaustion signals")

    # Generate charts
    chart_count = 0
    for ccy in df_display.columns:
        currency = ccy + "_posy"
        if currency not in positions_df.columns:
            continue
        try:
            fig = create_exhaustion_chart(
                df_display, ccy, currency, positions_df, signals_df,
                mode, f"{windows['short']}/{windows['mid']}/{windows['long']}"
            )
            filename = os.path.join(OUTPUT_DIR, f"{ccy}_exhaustion_{mode}.html")
            pio.write_html(fig, file=filename, auto_open=False)
            chart_count += 1
        except Exception as e:
            print(f"Failed on {currency}: {e}")

    print(f"Generated {chart_count} charts for {mode} mode")

    # Save summary
    latest_positions = pd.Series(positions_latest).sort_values(ascending=False)
    all_summaries[mode] = {
        'generated_at': datetime.now().isoformat(),
        'mode': mode,
        'windows': f"{windows['short']}/{windows['mid']}/{windows['long']}",
        'currencies': len(positions_latest),
        'charts_generated': chart_count,
        'latest_positions': latest_positions.to_dict()
    }

    print(f"\nTop 5 Long: {list(latest_positions.head().items())}")
    print(f"Top 5 Short: {list(latest_positions.tail().items())}")

# Save combined summary
with open(os.path.join(OUTPUT_DIR, 'summary.json'), 'w') as f:
    json.dump(all_summaries, f, indent=2)

print(f"\n{'='*60}")
print(f"✅ Complete! Generated charts for both FAST and SLOW modes")
print(f"Summary saved to {OUTPUT_DIR}/summary.json")
print(f"{'='*60}")

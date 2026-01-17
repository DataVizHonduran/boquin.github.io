"""
CTA Exhaustion Signal Generator for Top 20 Cryptocurrencies
Fetches crypto data from CoinGecko, calculates CTA positioning, and generates exhaustion signals
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.io as pio
import os
import json
import requests
from datetime import datetime
import time

# Configuration
OUTPUT_DIR = "reports/crypto-cta-signals"
GAP = 5  # Hysteresis band for exhaustion signals
WINDOW = 500  # Rolling window for position normalization (shorter for crypto due to less history)

# CTA mode configurations
CTA_MODES = {
    'fast': {'short': 20, 'mid': 50, 'long': 100},
    'slow': {'short': 50, 'mid': 100, 'long': 200}
}

# Top 20 cryptocurrencies by market cap (CoinGecko IDs)
TOP_20_CRYPTOS = [
    'bitcoin', 'ethereum', 'tether', 'xrp', 'bnb',
    'solana', 'usdc', 'cardano', 'dogecoin', 'tron',
    'avalanche-2', 'chainlink', 'polkadot', 'polygon',
    'near', 'litecoin', 'uniswap', 'bitcoin-cash', 'stellar', 'internet-computer'
]

# Mapping from CoinGecko ID to display symbol
CRYPTO_SYMBOLS = {
    'bitcoin': 'BTC', 'ethereum': 'ETH', 'tether': 'USDT', 'xrp': 'XRP',
    'bnb': 'BNB', 'solana': 'SOL', 'usdc': 'USDC', 'cardano': 'ADA',
    'dogecoin': 'DOGE', 'tron': 'TRX', 'avalanche-2': 'AVAX',
    'chainlink': 'LINK', 'polkadot': 'DOT', 'polygon': 'MATIC',
    'near': 'NEAR', 'litecoin': 'LTC', 'uniswap': 'UNI',
    'bitcoin-cash': 'BCH', 'stellar': 'XLM', 'internet-computer': 'ICP'
}

# Stablecoins to exclude from CTA analysis (they don't trend)
STABLECOINS = ['tether', 'usdc']


def fetch_crypto_data(crypto_id: str, days: int = 1825, max_retries: int = 3) -> pd.DataFrame:
    """
    Fetch historical price data from CoinGecko API with retry logic
    """
    url = f"https://api.coingecko.com/api/v3/coins/{crypto_id}/market_chart"
    params = {
        'vs_currency': 'usd',
        'days': days,
        'interval': 'daily'
    }

    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, timeout=30)

            # Handle rate limiting specifically
            if response.status_code == 429:
                wait_time = 60 * (attempt + 1)  # 60s, 120s, 180s
                print(f"    Rate limited. Waiting {wait_time}s before retry {attempt + 1}/{max_retries}...")
                time.sleep(wait_time)
                continue

            response.raise_for_status()
            data = response.json()

            prices = data.get('prices', [])
            if not prices:
                return pd.DataFrame()

            df = pd.DataFrame(prices, columns=['timestamp', 'price'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df.index = df.index.normalize()  # Remove time component
            df = df[~df.index.duplicated(keep='first')]  # Remove duplicate dates

            return df

        except requests.exceptions.HTTPError as e:
            if response.status_code == 429 and attempt < max_retries - 1:
                continue
            print(f"Error fetching {crypto_id}: {e}")
            return pd.DataFrame()
        except Exception as e:
            print(f"Error fetching {crypto_id}: {e}")
            if attempt < max_retries - 1:
                time.sleep(10 * (attempt + 1))
                continue
            return pd.DataFrame()

    return pd.DataFrame()


def fetch_all_crypto_data() -> pd.DataFrame:
    """Fetch data for all top 20 cryptos and combine into single DataFrame"""
    print("Fetching cryptocurrency data from CoinGecko...")
    print("Note: Using conservative rate limiting to avoid 429 errors")

    all_data = {}
    cryptos_to_analyze = [c for c in TOP_20_CRYPTOS if c not in STABLECOINS]

    for i, crypto_id in enumerate(cryptos_to_analyze):
        symbol = CRYPTO_SYMBOLS.get(crypto_id, crypto_id.upper())
        print(f"  [{i+1}/{len(cryptos_to_analyze)}] Fetching {symbol}...")

        df = fetch_crypto_data(crypto_id)
        if not df.empty:
            all_data[symbol] = df['price']
            print(f"    ✓ Got {len(df)} days of data")
        else:
            print(f"    ✗ No data retrieved")

        # Conservative rate limiting - CoinGecko free tier is strict
        # 10-30 calls/minute, so 6 seconds between calls is safe
        if i < len(cryptos_to_analyze) - 1:  # Don't sleep after last request
            time.sleep(6)

    if not all_data:
        raise ValueError("No data fetched from CoinGecko")

    df_combined = pd.DataFrame(all_data)
    df_combined = df_combined.sort_index()

    # Forward fill missing values (some cryptos have less history)
    df_combined = df_combined.ffill()

    print(f"Loaded {len(df_combined)} rows and {len(df_combined.columns)} cryptocurrencies")
    return df_combined


def calculate_positions(df_crypto: pd.DataFrame, short_window: int, mid_window: int, long_window: int):
    """Calculate CTA positioning for all cryptocurrencies"""
    positions_latest = {}
    positions_df = pd.DataFrame()

    for crypto in df_crypto.columns:
        price_series = df_crypto[crypto].dropna()
        if len(price_series) < long_window:
            print(f"  Skipping {crypto}: insufficient data ({len(price_series)} < {long_window})")
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
            positions_latest[crypto] = df['position_size'].iloc[-1]
            positions_df[f"{crypto}_posy"] = df['position_size']

    return positions_latest, positions_df


def generate_exhaustion_signals(positions_df: pd.DataFrame, thresholds: dict) -> pd.DataFrame:
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


def create_exhaustion_chart(df_display: pd.DataFrame, crypto: str, positions_df: pd.DataFrame,
                            signals_df: pd.DataFrame, mode: str, windows: str) -> go.Figure:
    """Create exhaustion model chart for a cryptocurrency"""
    fig = go.Figure()

    currency = f"{crypto}_posy"

    fig.add_trace(go.Scatter(
        x=df_display.index, y=df_display[crypto], mode='lines',
        name='Price (USD)', line=dict(color='teal', width=2), yaxis='y1'
    ))

    # Filter positioning to match price data timeframe
    pos_filtered = positions_df[positions_df.index.isin(df_display.index)]

    if currency in pos_filtered.columns:
        fig.add_trace(go.Scatter(
            x=pos_filtered.index, y=pos_filtered[currency], mode='lines',
            name='CTA Positioning', line=dict(color='orange', width=1.5),
            yaxis='y2', opacity=0.6
        ))

    if currency in signals_df.columns:
        signal_points = signals_df[currency] == 1
        signal_dates = signals_df.index[signal_points].intersection(df_display.index)
        if len(signal_dates) > 0:
            signal_prices = df_display.loc[signal_dates, crypto]

            fig.add_trace(go.Scatter(
                x=signal_dates, y=signal_prices, mode='markers',
                marker=dict(color='red', size=10, line=dict(color='black', width=1)),
                name='Exhaustion Signals', yaxis='y1'
            ))

    fig.update_layout(
        title=dict(
            text=f"{crypto}/USD - CTA {mode.upper()} ({windows}) - Positioning & Exhaustion Signals",
            x=0.5, xanchor='center', font=dict(size=18, color='darkblue')
        ),
        xaxis=dict(title="Date", showgrid=True, gridcolor='lightgrey',
                   zeroline=False, tickformat='%Y-%m', dtick='M6', tickangle=45),
        yaxis=dict(title="Price (USD)", tickfont=dict(color='teal'),
                   showgrid=True, zeroline=False, type='log'),  # Log scale for crypto prices
        yaxis2=dict(title="CTA Positioning", tickfont=dict(color='goldenrod'),
                    overlaying='y', side='right', showgrid=False, zeroline=False,
                    range=[-55, 55]),
        legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.8)',
                    bordercolor='black', borderwidth=1),
        hovermode='x unified', plot_bgcolor='white',
        width=1100, height=650
    )
    return fig


def create_positioning_heatmap(positions_latest: dict, mode: str, windows: str) -> go.Figure:
    """Create a heatmap showing current CTA positioning across all cryptos"""
    cryptos = list(positions_latest.keys())
    positions = list(positions_latest.values())

    # Sort by position size
    sorted_pairs = sorted(zip(cryptos, positions), key=lambda x: x[1], reverse=True)
    cryptos_sorted = [p[0] for p in sorted_pairs]
    positions_sorted = [p[1] for p in sorted_pairs]

    colors = ['#2ecc71' if p > 0 else '#e74c3c' if p < 0 else '#95a5a6' for p in positions_sorted]

    fig = go.Figure(go.Bar(
        x=positions_sorted,
        y=cryptos_sorted,
        orientation='h',
        marker_color=colors,
        text=[f'{p:.1f}' for p in positions_sorted],
        textposition='outside'
    ))

    fig.update_layout(
        title=dict(
            text=f"CTA {mode.upper()} Positioning ({windows}) - Current Snapshot",
            x=0.5, xanchor='center', font=dict(size=18, color='darkblue')
        ),
        xaxis=dict(title="Position Size", range=[-55, 55], zeroline=True, zerolinecolor='black'),
        yaxis=dict(title=""),
        plot_bgcolor='white',
        width=800, height=600
    )

    return fig


def main():
    """Main execution function"""
    print("=" * 60)
    print("CTA Exhaustion Signal Generator - Cryptocurrency Edition")
    print("=" * 60)

    # Fetch crypto data
    df_crypto = fetch_all_crypto_data()

    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Save raw data for reference
    df_crypto.to_csv(os.path.join(OUTPUT_DIR, 'crypto_prices.csv'))
    print(f"Saved price data to {OUTPUT_DIR}/crypto_prices.csv")

    # Process both fast and slow modes
    all_summaries = {}

    for mode, windows in CTA_MODES.items():
        print(f"\n{'='*60}")
        print(f"Processing {mode.upper()} mode ({windows['short']}/{windows['mid']}/{windows['long']})...")
        print(f"{'='*60}")

        # Calculate positions
        positions_latest, positions_df = calculate_positions(
            df_crypto, windows['short'], windows['mid'], windows['long']
        )
        print(f"Calculated positioning for {len(positions_latest)} cryptocurrencies")

        if positions_df.empty:
            print(f"No valid positions for {mode} mode, skipping...")
            continue

        # Calculate thresholds based on historical percentiles
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

        # Generate individual charts
        chart_count = 0
        for crypto in df_crypto.columns:
            currency = f"{crypto}_posy"
            if currency not in positions_df.columns:
                continue
            try:
                fig = create_exhaustion_chart(
                    df_crypto, crypto, positions_df, signals_df,
                    mode, f"{windows['short']}/{windows['mid']}/{windows['long']}"
                )
                filename = os.path.join(OUTPUT_DIR, f"{crypto}_exhaustion_{mode}.html")
                pio.write_html(fig, file=filename, auto_open=False)
                chart_count += 1
            except Exception as e:
                print(f"Failed on {crypto}: {e}")

        print(f"Generated {chart_count} charts for {mode} mode")

        # Generate positioning heatmap
        try:
            heatmap_fig = create_positioning_heatmap(
                positions_latest, mode, f"{windows['short']}/{windows['mid']}/{windows['long']}"
            )
            heatmap_file = os.path.join(OUTPUT_DIR, f"positioning_heatmap_{mode}.html")
            pio.write_html(heatmap_fig, file=heatmap_file, auto_open=False)
            print(f"Generated positioning heatmap: {heatmap_file}")
        except Exception as e:
            print(f"Failed to generate heatmap: {e}")

        # Save summary
        latest_positions = pd.Series(positions_latest).sort_values(ascending=False)

        # Count recent signals
        recent_signals = {}
        for col in signals_df.columns:
            crypto_name = col.replace('_posy', '')
            recent = signals_df[col].tail(30).sum()  # Signals in last 30 days
            if recent > 0:
                recent_signals[crypto_name] = int(recent)

        all_summaries[mode] = {
            'generated_at': datetime.now().isoformat(),
            'mode': mode,
            'windows': f"{windows['short']}/{windows['mid']}/{windows['long']}",
            'cryptocurrencies': len(positions_latest),
            'charts_generated': chart_count,
            'latest_positions': {k: round(v, 2) for k, v in latest_positions.to_dict().items()},
            'recent_signals_30d': recent_signals
        }

        print(f"\n📈 Top 5 Long Positions:")
        for crypto, pos in list(latest_positions.head().items()):
            print(f"   {crypto}: {pos:.1f}")

        print(f"\n📉 Top 5 Short Positions:")
        for crypto, pos in list(latest_positions.tail().items()):
            print(f"   {crypto}: {pos:.1f}")

        if recent_signals:
            print(f"\n🚨 Recent Exhaustion Signals (30d): {recent_signals}")

    # Save combined summary
    summary_file = os.path.join(OUTPUT_DIR, 'summary.json')
    with open(summary_file, 'w') as f:
        json.dump(all_summaries, f, indent=2)

    print(f"\n{'='*60}")
    print(f"✅ Complete! Generated charts for both FAST and SLOW modes")
    print(f"📁 Output directory: {OUTPUT_DIR}")
    print(f"📊 Summary saved to: {summary_file}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

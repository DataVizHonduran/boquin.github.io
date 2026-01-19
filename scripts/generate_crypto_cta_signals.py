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
WINDOW = 500  # Rolling window for position normalization

# CTA mode configurations
CTA_MODES = {
    'fast': {'short': 20, 'mid': 50, 'long': 100},
    'slow': {'short': 50, 'mid': 100, 'long': 200}
}

# Top 20 cryptocurrencies by market cap (CoinGecko IDs)
TOP_20_CRYPTOS = [
    'bitcoin', 'ethereum', 'tether', 'xrp', 'bnb', 'solana', 'usdc', 'cardano', 
    'dogecoin', 'tron', 'avalanche-2', 'chainlink', 'polkadot', 'polygon', 
    'near', 'litecoin', 'uniswap', 'bitcoin-cash', 'stellar', 'internet-computer'
]

# Mapping from CoinGecko ID to display symbol
CRYPTO_SYMBOLS = {
    'bitcoin': 'BTC', 'ethereum': 'ETH', 'tether': 'USDT', 'xrp': 'XRP',
    'bnb': 'BNB', 'solana': 'SOL', 'usdc': 'USDC', 'cardano': 'ADA',
    'dogecoin': 'DOGE', 'tron': 'TRX', 'avalanche-2': 'AVAX', 'chainlink': 'LINK',
    'polkadot': 'DOT', 'polygon': 'MATIC', 'near': 'NEAR', 'litecoin': 'LTC',
    'uniswap': 'UNI', 'bitcoin-cash': 'BCH', 'stellar': 'XLM', 'internet-computer': 'ICP'
}

def fetch_crypto_data(crypto_id: str, days: int = 1825, max_retries: int = 3) -> pd.DataFrame:
    """Fetches historical price data with explicit status logging."""
    url = f"https://api.coingecko.com/api/v3/coins/{crypto_id}/market_chart"
    api_key = os.environ.get('COINGECKO_API_KEY')
    headers = {'x-cg-demo-api-key': api_key} if api_key else {}
    params = {'vs_currency': 'usd', 'days': days, 'interval': 'daily'}
    
    for attempt in range(max_retries):
        try:
            print(f"  --> Fetching {crypto_id} (Attempt {attempt + 1})...")
            # Reduced timeout to 15s to fail faster and retry
            response = requests.get(url, params=params, headers=headers, timeout=15)
            
            if response.status_code == 429:
                print(f"  !! Rate Limited (429) for {crypto_id}. Waiting 60s...")
                time.sleep(60)
                continue
                
            response.raise_for_status()
            data = response.json()
            
            print(f"  ok: {crypto_id} data received.")
            df = pd.DataFrame(data['prices'], columns=['timestamp', 'price'])
            df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('date', inplace=True)
            return df['price']
            
        except requests.exceptions.Timeout:
            print(f"  !! Timeout error for {crypto_id}.")
        except Exception as e:
            print(f"  !! Error fetching {crypto_id}: {e}")
            
        if attempt < max_retries - 1:
            wait_time = (attempt + 1) * 20
            print(f"  Retrying in {wait_time}s...")
            time.sleep(wait_time)
            
    return None
    
def calculate_cta_position(prices: pd.Series, mode: str = 'fast') -> pd.Series:
    """Calculates CTA positioning based on moving average crossovers."""
    config = CTA_MODES[mode]
    
    s = prices.rolling(window=config['short']).mean()
    m = prices.rolling(window=config['mid']).mean()
    l = prices.rolling(window=config['long']).mean()
    
    # Position: +1 if short > mid and mid > long, -1 if reverse, 0 otherwise
    pos = pd.Series(0, index=prices.index)
    pos[(s > m) & (m > l)] = 1
    pos[(s < m) & (m < l)] = -1
    
    return pos.rolling(window=10).mean() # Smooth the transitions

def generate_signals():
    """Main execution function to generate signals for all cryptos."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Initialize data structure expected by generate_crypto_index.py
    summary_data = {
        'fast': {
            'latest_positions': {},
            'cryptocurrencies': 0,
            'windows': '20/50/100',
            'generated_at': datetime.now().isoformat(),
            'recent_signals_30d': {}
        },
        'slow': {
            'latest_positions': {},
            'cryptocurrencies': 0,
            'windows': '50/100/200',
            'generated_at': datetime.now().isoformat(),
            'recent_signals_30d': {}
        }
    }

    for i, crypto_id in enumerate(TOP_20_CRYPTOS):
        print(f"Processing {crypto_id} ({i+1}/{len(TOP_20_CRYPTOS)})...")

        prices = fetch_crypto_data(crypto_id)
        if prices is None or len(prices) < 200:
            continue

        symbol = CRYPTO_SYMBOLS.get(crypto_id, crypto_id.upper())

        # Calculate fast and slow positions separately
        pos_fast = calculate_cta_position(prices, 'fast')
        pos_slow = calculate_cta_position(prices, 'slow')

        # Store positions scaled to -50 to +50 range for chart display
        summary_data['fast']['latest_positions'][symbol] = round(pos_fast.iloc[-1] * 50, 1)
        summary_data['slow']['latest_positions'][symbol] = round(pos_slow.iloc[-1] * 50, 1)

        # Rate limiting: 10 seconds between calls for CoinGecko Demo API safety
        if i < len(TOP_20_CRYPTOS) - 1:
            time.sleep(10)

    # Update crypto counts
    summary_data['fast']['cryptocurrencies'] = len(summary_data['fast']['latest_positions'])
    summary_data['slow']['cryptocurrencies'] = len(summary_data['slow']['latest_positions'])

    # Save summary
    with open(f"{OUTPUT_DIR}/summary.json", 'w') as f:
        json.dump(summary_data, f, indent=4)
    print(f"Update complete. Processed {summary_data['fast']['cryptocurrencies']} cryptocurrencies.")

if __name__ == "__main__":
    generate_signals()

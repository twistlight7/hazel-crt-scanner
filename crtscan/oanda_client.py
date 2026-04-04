"""
OANDA API Client for CRT Scanner
=================================
Replaces yfinance for Forex pairs. Real-time, broker-grade candles.

Setup:
1. Create OANDA practice (demo) account: https://www.oanda.com/account/
2. Get API token from: Account Settings → Manage API Access
3. Add to .env:
   OANDA_API_TOKEN=your_token_here
   OANDA_ACCOUNT_ID=your_account_id_here
"""

import os
import json
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

OANDA_API = "https://api-fxpractice.oanda.com"
OANDA_TOKEN = os.getenv("OANDA_API_TOKEN", "")
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID", "")

# Map scanner pair names to OANDA instrument names
OANDA_INSTRUMENTS = {
    "EURUSD": "EUR_USD",
    "GBPUSD": "GBP_USD",
    "XAUUSD": "XAU_USD",
    "USDJPY": "USD_JPY",
    "GBPJPY": "GBP_JPY",
}

# Map timeframe to OANDA granularity
OANDA_GRANULARITY = {
    "H1": "H1",
    "H4": "H4",
    "D1": "D",
}

HEADERS = {
    "Authorization": f"Bearer {OANDA_TOKEN}",
    "Content-Type": "application/json",
}


def check_connection() -> bool:
    """Test if OANDA API is accessible with current credentials."""
    if not OANDA_TOKEN:
        print("❌ OANDA_API_TOKEN not set in .env")
        return False
    try:
        resp = requests.get(
            f"{OANDA_API}/v3/accounts",
            headers=HEADERS,
            timeout=10
        )
        if resp.status_code == 200:
            accounts = resp.json().get("accounts", [])
            print(f"✅ Connected — {len(accounts)} account(s) found")
            return True
        else:
            print(f"❌ OANDA API error {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False


def fetch_candles(instrument: str, granularity: str, count: int = 10) -> list:
    """
    Fetch OHLCV candles from OANDA.
    
    Args:
        instrument: OANDA instrument name (e.g., "EUR_USD")
        granularity: Candle timeframe ("H1", "H4", "D")
        count: Number of candles to fetch (max 5000)
    
    Returns:
        List of dicts: [{"open", "high", "low", "close", "volume"}, ...]
        Oldest first, matching the scanner's expected format.
    """
    url = f"{OANDA_API}/v3/instruments/{instrument}/candles"
    params = {
        "granularity": granularity,
        "count": count,
        "price": "M",  # Midpoint pricing (default for practice accounts)
    }
    
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        candles = []
        for candle in data.get("candles", []):
            if candle.get("complete", False):  # Only use fully closed candles
                mid = candle["mid"]
                candles.append({
                    "open": float(mid["o"]),
                    "high": float(mid["h"]),
                    "low": float(mid["l"]),
                    "close": float(mid["c"]),
                    "volume": int(candle.get("volume", 0)),
                    "time": candle["time"],
                })
        
        return candles
    
    except requests.exceptions.HTTPError as e:
        print(f"❌ OANDA HTTP error for {instrument} {granularity}: {e}")
        return []
    except Exception as e:
        print(f"❌ OANDA fetch error for {instrument} {granularity}: {e}")
        return []


def get_all_pair_candles(pair: str, tf: str) -> list:
    """
    Convenience wrapper for the scanner.
    
    Args:
        pair: Scanner pair name (e.g., "EURUSD")
        tf: Timeframe ("H1", "H4", "D1")
    
    Returns:
        List of candle dicts in scanner format.
    """
    instrument = OANDA_INSTRUMENTS.get(pair)
    granularity = OANDA_GRANULARITY.get(tf)
    
    if not instrument or not granularity:
        print(f"❌ Unknown pair or timeframe: {pair} {tf}")
        return []
    
    count_map = {"H1": 5, "H4": 10, "D1": 10}
    count = count_map.get(tf, 10)
    
    return fetch_candles(instrument, granularity, count=count)


if __name__ == "__main__":
    print("=== OANDA Connection Test ===")
    if check_connection():
        print("\n=== Fetching EURUSD H1 (5 candles) ===")
        candles = get_all_pair_candles("EURUSD", "H1")
        for c in candles:
            print(f"  O:{c['open']:.5f} H:{c['high']:.5f} L:{c['low']:.5f} C:{c['close']:.5f} V:{c['volume']}")
        
        print("\n=== Fetching XAUUSD D1 (3 candles) ===")
        candles = get_all_pair_candles("XAUUSD", "D1")
        for c in candles:
            print(f"  O:{c['open']:.2f} H:{c['high']:.2f} L:{c['low']:.2f} C:{c['close']:.2f} V:{c['volume']}")

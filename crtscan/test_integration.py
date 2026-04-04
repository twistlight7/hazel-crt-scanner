#!/usr/bin/env python3
"""
Test integration of liquidity_poi.py with crtscan.py
Tests EURUSD H1 specifically as requested by Blue.
"""

import sys
sys.path.insert(0, '/home/modtrader/.openclaw/workspace/crtscan')

from liquidity_poi import validate_crt_sweep, get_pair_tolerance, detect_liquidity_pools, detect_poi_levels
from datetime import datetime, timezone

# Test data: Simulated EURUSD H1 candles (OHLC format)
# This is test data only — in production, candles come from yfinance/OANDA
EURUSD_H1_CANDLES = [
    # Older candles (for context)
    {"timestamp": 1712160000000, "open": 1.08200, "high": 1.08350, "low": 1.08150, "close": 1.08300},
    {"timestamp": 1712163600000, "open": 1.08300, "high": 1.08400, "low": 1.08250, "close": 1.08380},
    {"timestamp": 1712167200000, "open": 1.08380, "high": 1.08450, "low": 1.08320, "close": 1.08350},
    # C1 (Base candle) - establishes range
    {"timestamp": 1712170800000, "open": 1.08350, "high": 1.08500, "low": 1.08300, "close": 1.08320},
    # C2 (Sweep candle) - sweeps C1 low, closes back above
    {"timestamp": 1712174400000, "open": 1.08320, "high": 1.08380, "low": 1.08250, "close": 1.08340},
    # Current forming candle (excluded from detection)
    {"timestamp": 1712178000000, "open": 1.08340, "high": 1.08400, "low": 1.08320, "close": 1.08380},
]

def test_eurusd_h1():
    """Test EURUSD H1 CRT detection with liquidity/POI validation."""
    print("=" * 60)
    print("EURUSD H1 INTEGRATION TEST")
    print("=" * 60)
    
    pair = "EURUSD"
    timeframe = "H1"
    
    # Test tolerance
    tolerance = get_pair_tolerance(pair)
    print(f"\n📏 Pair Tolerance: {tolerance:.5f} ({tolerance/0.0001:.0f} pips)")
    
    # C1 and C2 (exclude forming candle)
    c1 = EURUSD_H1_CANDLES[-3]  # Base candle
    c2 = EURUSD_H1_CANDLES[-2]  # Sweep candle
    
    print(f"\n🕯️ C1 (Base):")
    print(f"   O: {c1['open']:.5f}  H: {c1['high']:.5f}  L: {c1['low']:.5f}  C: {c1['close']:.5f}")
    
    print(f"\n🕯️ C2 (Sweep):")
    print(f"   O: {c2['open']:.5f}  H: {c2['high']:.5f}  L: {c2['low']:.5f}  C: {c2['close']:.5f}")
    
    # Check if C2 swept C1 low
    c1_low = c1["low"]
    c2_low = c2["low"]
    swept = c2_low < c1_low
    reclaimed = c2["close"] > c1_low
    
    print(f"\n✅ Sweep Detection:")
    print(f"   C2 low ({c2_low:.5f}) < C1 low ({c1_low:.5f}): {swept}")
    print(f"   C2 close ({c2['close']:.5f}) > C1 low ({c1_low:.5f}): {reclaimed}")
    print(f"   Valid CRT: {swept and reclaimed}")
    
    # Validate against liquidity/POI
    print(f"\n🔍 Liquidity/POI Validation:")
    validation = validate_crt_sweep(EURUSD_H1_CANDLES, c1, c2, pair, timeframe, "bullish")
    
    print(f"   Valid: {validation['valid']}")
    print(f"   Quality Tier: {validation['quality_tier']} ({validation['quality_score']}%)")
    print(f"   Total Confluences: {validation['total_confluences']}")
    
    if validation['swept_pools']:
        print(f"   Swept Pools: {', '.join(validation['swept_pools'])}")
    else:
        print(f"   Swept Pools: None detected")
    
    if validation['tapped_pois']:
        print(f"   Tapped POIs: {', '.join(validation['tapped_pois'])}")
    else:
        print(f"   Tapped POIs: None detected")
    
    # Show detected liquidity pools
    print(f"\n📊 Detected Liquidity Pools:")
    liq = validation['liquidity_pools']
    if liq.get('equal_lows'):
        print(f"   Equal Lows: {liq['equal_lows']:.5f}")
    if liq.get('equal_highs'):
        print(f"   Equal Highs: {liq['equal_highs']:.5f}")
    if liq.get('pdh'):
        print(f"   PDH: {liq['pdh']:.5f}")
    if liq.get('pdl'):
        print(f"   PDL: {liq['pdl']:.5f}")
    if liq.get('sessions'):
        for session, levels in liq['sessions'].items():
            print(f"   {session}: H={levels['high']:.5f} L={levels['low']:.5f}")
    
    # Show detected POIs
    print(f"\n📍 Detected POI Levels:")
    poi = validation['poi_levels']
    if poi['order_blocks']['bullish']:
        ob = poi['order_blocks']['bullish']
        print(f"   Bullish OB: {ob['low']:.5f} - {ob['high']:.5f}")
    if poi['order_blocks']['bearish']:
        ob = poi['order_blocks']['bearish']
        print(f"   Bearish OB: {ob['low']:.5f} - {ob['high']:.5f}")
    if poi['fvg']['bullish']:
        fvg = poi['fvg']['bullish']
        print(f"   Bullish FVG: {fvg['low']:.5f} - {fvg['high']:.5f}")
    if poi['fvg']['bearish']:
        fvg = poi['fvg']['bearish']
        print(f"   Bearish FVG: {fvg['low']:.5f} - {fvg['high']:.5f}")
    if poi['breaker']:
        br = poi['breaker']
        print(f"   {br['type'].replace('_', ' ').title()}: {br['low']:.5f} - {br['high']:.5f}")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    
    return validation

if __name__ == "__main__":
    result = test_eurusd_h1()
    
    # Summary
    print(f"\n📋 SUMMARY:")
    print(f"   Signal Valid: {result['valid']}")
    print(f"   Quality: {result['quality_tier']} ({result['quality_score']}%)")
    print(f"   Confluences: {result['total_confluences']}")
    
    if result['total_confluences'] > 0:
        print(f"   ✅ Integration working — detecting liquidity/POI confluences!")
    else:
        print(f"   ⚠️ No confluences detected (may need more historical data)")

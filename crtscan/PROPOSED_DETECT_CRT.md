# 📋 PROPOSED detect_crt() — For Blue's Approval

**Date:** 2026-04-03 22:49 UTC  
**Directive:** Two filters only (institutional candle + key level)

---

## 🔧 APPROVED FILTERS (Per Blue)

| Filter | Requirement | Removed |
|--------|-------------|---------|
| ✅ Institutional Candle | C1 range ≥1.2x ATR(14) | — |
| ✅ Key Level | C1 overlaps with liquidity pool OR POI | — |
| ❌ Session Filter | — | REMOVED (per Blue) |
| ❌ C3 Confirmation | — | REMOVED (per Blue) |

**Detection:** Back to 2-candle (C1 + C2), gated by 2 structural filters.

---

## 📝 PROPOSED detect_crt() FUNCTION

```python
def detect_crt(candles: list, timeframe: str, pair: str, 
               liquidity_pools: dict, poi_levels: dict,
               atr_14: float) -> dict | None:
    """
    Detect CRT pattern with institutional candle + key level filters.
    
    BLUE'S DIRECTIVE (2026-04-03 22:49 UTC):
    - 2-candle detection (C1 + C2)
    - Filter 1: C1 range ≥1.2x ATR(14) (institutional candle)
    - Filter 2: C1 must overlap with liquidity pool OR POI
    - NO session filter
    - NO C3 confirmation
    
    Args:
        candles: List of OHLC candles (oldest → newest)
                 candles[-2] = C1 (reference/institutional)
                 candles[-1] = C2 (sweeper)
        timeframe: "H1", "H4", or "D1"
        pair: Symbol name (e.g., "EURUSD", "BTCUSDT")
        liquidity_pools: From liquidity_poi.detect_liquidity_pools()
        poi_levels: From liquidity_poi.detect_poi_levels()
        atr_14: 14-period ATR value for institutional candle filter
    
    Returns:
        Signal dict if valid CRT, None otherwise
    """
    if len(candles) < 2:
        return None
    
    # Correct indexing (per Hermes audit 2026-04-03 22:39 UTC)
    c1 = candles[-2]  # Reference/institutional candle
    c2 = candles[-1]  # Sweeper candle
    
    h = c1["high"]
    l = c1["low"]
    rng = h - l
    
    # ─────────────────────────────────────────────────────────────────
    # FILTER 1: INSTITUTIONAL CANDLE (C1 range ≥1.2x ATR)
    # ─────────────────────────────────────────────────────────────────
    if rng < atr_14 * 1.2:
        log.info(f"  ⏭ {pair} {timeframe} — C1 range ({rng:.5f}) < 1.2x ATR ({atr_14 * 1.2:.5f})")
        return None
    
    # ─────────────────────────────────────────────────────────────────
    # FILTER 2: KEY LEVEL (C1 overlaps with liquidity pool OR POI)
    # ─────────────────────────────────────────────────────────────────
    c1_overlaps_key_level = False
    
    # Check liquidity pool overlap
    if liquidity_pools:
        # Equal highs/lows
        if liquidity_pools.get("equal_highs"):
            if abs(h - liquidity_pools["equal_highs"]) < get_pair_tolerance(pair):
                c1_overlaps_key_level = True
        if liquidity_pools.get("equal_lows"):
            if abs(l - liquidity_pools["equal_lows"]) < get_pair_tolerance(pair):
                c1_overlaps_key_level = True
        
        # PDH/PDL
        if liquidity_pools.get("pdh"):
            if abs(h - liquidity_pools["pdh"]) < get_pair_tolerance(pair):
                c1_overlaps_key_level = True
        if liquidity_pools.get("pdl"):
            if abs(l - liquidity_pools["pdl"]) < get_pair_tolerance(pair):
                c1_overlaps_key_level = True
        
        # Session levels
        for session, levels in liquidity_pools.get("sessions", {}).items():
            if abs(h - levels["high"]) < get_pair_tolerance(pair):
                c1_overlaps_key_level = True
            if abs(l - levels["low"]) < get_pair_tolerance(pair):
                c1_overlaps_key_level = True
    
    # Check POI overlap
    if poi_levels and not c1_overlaps_key_level:
        # Order blocks
        for ob_type in ["bullish", "bearish"]:
            ob = poi_levels["order_blocks"].get(ob_type)
            if ob:
                # C1 overlaps if C1 range intersects OB range
                if not (h < ob["low"] or l > ob["high"]):
                    c1_overlaps_key_level = True
                    break
        
        # FVGs
        for fvg_type in ["bullish", "bearish"]:
            fvg = poi_levels["fvg"].get(fvg_type)
            if fvg:
                # C1 overlaps if C1 range intersects FVG
                if not (h < fvg["low"] or l > fvg["high"]):
                    c1_overlaps_key_level = True
                    break
        
        # Breakers
        breaker = poi_levels.get("breaker")
        if breaker and not c1_overlaps_key_level:
            if not (h < breaker["low"] or l > breaker["high"]):
                c1_overlaps_key_level = True
    
    if not c1_overlaps_key_level:
        log.info(f"  ⏭ {pair} {timeframe} — C1 not at key level (no liquidity/POI overlap)")
        return None
    
    # ─────────────────────────────────────────────────────────────────
    # SWEEP DETECTION (2-candle logic)
    # ─────────────────────────────────────────────────────────────────
    
    # Bullish CRT
    if c2["low"] < l and c2["close"] > l:
        # Check delivery (Blue's rule: skip if >50% delivered)
        delivery = check_delivery_bullish(c1, c2)
        if delivery > 0.50:
            log.info(f"  ⏭ {pair} {timeframe} — >50% delivered ({delivery*100:.1f}%)")
            return None
        
        # Validate against liquidity/POI for confluence scoring
        validation = validate_crt_sweep(candles, c1, c2, pair, timeframe, "bullish")
        
        sweep_depth = l - c2["low"]
        reclaim_strength = c2["close"] - l
        quality = round(reclaim_strength / rng, 2)
        
        log.info(f"  C1 (Base): O:{c1['open']:.5f} H:{c1['high']:.5f} L:{c1['low']:.5f} C:{c1['close']:.5f}")
        log.info(f"  C2 (Sweep): O:{c2['open']:.5f} H:{c2['high']:.5f} L:{c2['low']:.5f} C:{c2['close']:.5f}")
        
        return {
            "type":         "BULLISH",
            "timeframe":    timeframe,
            "entry":        round(c2["close"], 5),
            "tp":           round(h, 5),
            "sl":           round(c2["low"] - (rng * 0.05), 5),
            "range_high":   round(h, 5),
            "range_low":    round(l, 5),
            "sweep_size":   round(sweep_depth, 5),
            "quality":      quality,
            "rr":           round((h - c2["close"]) / (c2["close"] - c2["low"]), 2),
            "delivery":     round(delivery * 100, 1),
            "room_left":    round((1 - delivery) * 100, 1),
            "c1_data":      {k: round(v, 5) for k, v in c1.items() if k in ['open', 'high', 'low', 'close']},
            "c2_data":      {k: round(v, 5) for k, v in c2.items() if k in ['open', 'high', 'low', 'close']},
            # Confluence info from liquidity_poi validation
            "quality_tier":      validation["quality_tier"],
            "quality_score":     validation["quality_score"],
            "swept_pools":       validation["swept_pools"],
            "tapped_pois":       validation["tapped_pois"],
            "total_confluences": validation["total_confluences"],
        }
    
    # Bearish CRT
    if c2["high"] > h and c2["close"] < h:
        # Check delivery
        delivery = check_delivery_bearish(c1, c2)
        if delivery > 0.50:
            log.info(f"  ⏭ {pair} {timeframe} — >50% delivered ({delivery*100:.1f}%)")
            return None
        
        # Validate against liquidity/POI for confluence scoring
        validation = validate_crt_sweep(candles, c1, c2, pair, timeframe, "bearish")
        
        sweep_depth = c2["high"] - h
        reclaim_strength = h - c2["close"]
        quality = round(reclaim_strength / rng, 2)
        
        log.info(f"  C1 (Base): O:{c1['open']:.5f} H:{c1['high']:.5f} L:{c1['low']:.5f} C:{c1['close']:.5f}")
        log.info(f"  C2 (Sweep): O:{c2['open']:.5f} H:{c2['high']:.5f} L:{c2['low']:.5f} C:{c2['close']:.5f}")
        
        return {
            "type":         "BEARISH",
            "timeframe":    timeframe,
            "entry":        round(c2["close"], 5),
            "tp":           round(l, 5),
            "sl":           round(c2["high"] + (rng * 0.05), 5),
            "range_high":   round(h, 5),
            "range_low":    round(l, 5),
            "sweep_size":   round(sweep_depth, 5),
            "quality":      quality,
            "rr":           round((c2["close"] - l) / (c2["high"] - c2["close"]), 2),
            "delivery":     round(delivery * 100, 1),
            "room_left":    round((1 - delivery) * 100, 1),
            "c1_data":      {k: round(v, 5) for k, v in c1.items() if k in ['open', 'high', 'low', 'close']},
            "c2_data":      {k: round(v, 5) for k, v in c2.items() if k in ['open', 'high', 'low', 'close']},
            # Confluence info from liquidity_poi validation
            "quality_tier":      validation["quality_tier"],
            "quality_score":     validation["quality_score"],
            "swept_pools":       validation["swept_pools"],
            "tapped_pois":       validation["tapped_pois"],
            "total_confluences": validation["total_confluences"],
        }
    
    return None
```

---

## 🔧 REQUIRED CHANGES TO scan_pair()

```python
def scan_pair(pair: str, yf_ticker: str = None, ccxt_symbol: str = None):
    """Run CRT scan across H1, H4, D1 for one pair."""
    log.info("Scanning %s ...", pair)
    pair_signals = {}
    
    # Calculate ATR(14) for this pair (needed for institutional candle filter)
    # This needs to be added to get_candles_for_pair() or calculated separately
    atr_14 = calculate_atr(candles, period=14)  # NEW FUNCTION
    
    for tf in ["D1", "H4", "H1"]:
        candles = get_candles_for_pair(pair, yf_ticker, ccxt_symbol, tf)
        if len(candles) < 2:
            log.warning("%s %s: not enough candles", pair, tf)
            continue
        
        # Detect liquidity and POI for key level filter
        current_time = datetime.now(timezone.utc)
        liquidity = detect_liquidity_pools(candles, pair, tf, current_time)
        poi = detect_poi_levels(candles)
        
        # NEW: Pass liquidity, poi, and atr_14 to detect_crt()
        signal = detect_crt(candles, tf, pair, liquidity, poi, atr_14)
        
        pair_signals[tf] = signal
        if signal:
            confluence_note = f" ({signal.get('total_confluences', 0)} confluences, {signal.get('quality_tier', 'B')} tier)"
            log.info("  ✅ %s CRT on %s %s (quality %.0f%%)%s",
                     signal["type"], pair, tf, signal["quality"] * 100, confluence_note)
    
    # ... rest of function unchanged (bias, alert filtering, etc.)
```

---

## 📊 FILTER LOGIC SUMMARY

| Step | Check | If Fails |
|------|-------|----------|
| 1 | `len(candles) >= 2` | Return None |
| 2 | C1 range ≥1.2x ATR(14) | Log "C1 range < 1.2x ATR", return None |
| 3 | C1 overlaps liquidity pool OR POI | Log "C1 not at key level", return None |
| 4 | C2 sweeps C1 + closes back | Continue (no filter) |
| 5 | Delivery ≤50% | Log ">50% delivered", return None |
| 6 | All passed | Return signal dict with confluence info |

---

## 🙏 AWAITING BLUE'S APPROVAL

**Please review:**
1. ✅ Institutional candle filter: `rng < atr_14 * 1.2`
2. ✅ Key level filter: C1 overlaps liquidity pool OR POI (using `liquidity_poi` module)
3. ✅ 2-candle detection (C1 + C2, no C3)
4. ✅ No session filter
5. ✅ Correct candle indexing (C1=candles[-2], C2=candles[-1])
6. ✅ Delivery filter retained (Blue's rule)
7. ✅ Confluence/quality tier system retained

**Reply:**
- ✅ **APPROVED** — Implement as written
- ❌ **CHANGES** — Specify what to adjust

— Hazel 🌰

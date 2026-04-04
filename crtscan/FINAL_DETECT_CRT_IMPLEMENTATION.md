# 🔧 FINAL detect_crt() IMPLEMENTATION — For Hermes/Blue Audit

**Date:** 2026-04-03 22:51 UTC  
**Status:** Ready for code review before deployment  
**Directive:** Approved by Blue with 2 implementation notes

---

## 📋 IMPLEMENTATION NOTES (Per Hermes)

1. ✅ Pass `pair` and `timeframe` (needed for tolerance lookup in liquidity_poi)
2. ✅ ATR(14) computed inside function from full candle list (self-contained)

---

## 🆕 NEW HELPER FUNCTION: calculate_atr()

```python
def calculate_atr(candles: list, period: int = 14) -> float:
    """
    Calculate ATR (Average True Range) over last `period` candles.
    
    True Range = max(H-L, |H-prev_C|, |L-prev_C|)
    ATR = Simple average of TR over period
    
    Args:
        candles: List of OHLC candles (oldest → newest)
        period: ATR period (default 14)
    
    Returns:
        ATR value (float)
    """
    if len(candles) < 2:
        return 0.0
    
    true_ranges = []
    for i in range(1, min(len(candles), period + 1)):
        c = candles[i]
        prev = candles[i - 1]
        
        tr = max(
            c["high"] - c["low"],
            abs(c["high"] - prev["close"]),
            abs(c["low"] - prev["close"]),
        )
        true_ranges.append(tr)
    
    if not true_ranges:
        return 0.0
    
    return sum(true_ranges) / len(true_ranges)
```

---

## 🆕 REVISED detect_crt() FUNCTION

```python
def detect_crt(candles: list, timeframe: str, pair: str) -> dict | None:
    """
    Detect CRT pattern with institutional candle + key level filters.
    
    BLUE'S DIRECTIVE (2026-04-03 22:49 UTC):
    - 2-candle detection (C1 + C2)
    - Filter 1: C1 range ≥1.2x ATR(14) (institutional candle)
    - Filter 2: C1 must overlap with liquidity pool OR POI
    - NO session filter
    - NO C3 confirmation
    
    HERMES NOTES (2026-04-03 22:51 UTC):
    - ATR(14) computed inside function (self-contained)
    - pair and timeframe passed for tolerance lookup
    
    Args:
        candles: List of OHLC candles (oldest → newest)
                 candles[-2] = C1 (reference/institutional)
                 candles[-1] = C2 (sweeper)
        timeframe: "H1", "H4", or "D1"
        pair: Symbol name (e.g., "EURUSD", "BTCUSDT")
    
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
    # COMPUTE ATR(14) INSIDE FUNCTION (self-contained)
    # ─────────────────────────────────────────────────────────────────
    atr_14 = calculate_atr(candles, period=14)
    if atr_14 == 0:
        log.warning(f"  ⚠️ {pair} {timeframe} — ATR(14) = 0, insufficient data")
        return None
    
    # ─────────────────────────────────────────────────────────────────
    # FILTER 1: INSTITUTIONAL CANDLE (C1 range ≥1.2x ATR)
    # ─────────────────────────────────────────────────────────────────
    if rng < atr_14 * 1.2:
        log.info(f"  ⏭ {pair} {timeframe} — C1 range ({rng:.5f}) < 1.2x ATR ({atr_14 * 1.2:.5f})")
        return None
    
    # ─────────────────────────────────────────────────────────────────
    # FILTER 2: KEY LEVEL (C1 overlaps with liquidity pool OR POI)
    # ─────────────────────────────────────────────────────────────────
    # Detect liquidity and POI (pass pair and timeframe for tolerance)
    current_time = datetime.now(timezone.utc)
    liquidity = detect_liquidity_pools(candles, pair, timeframe, current_time)
    poi = detect_poi_levels(candles)
    
    c1_overlaps_key_level = False
    
    # Check liquidity pool overlap
    if liquidity:
        # Equal highs/lows
        if liquidity.get("equal_highs"):
            tolerance = get_pair_tolerance(pair)
            if abs(h - liquidity["equal_highs"]) < tolerance:
                c1_overlaps_key_level = True
        if liquidity.get("equal_lows"):
            tolerance = get_pair_tolerance(pair)
            if abs(l - liquidity["equal_lows"]) < tolerance:
                c1_overlaps_key_level = True
        
        # PDH/PDL
        if liquidity.get("pdh"):
            tolerance = get_pair_tolerance(pair)
            if abs(h - liquidity["pdh"]) < tolerance:
                c1_overlaps_key_level = True
        if liquidity.get("pdl"):
            tolerance = get_pair_tolerance(pair)
            if abs(l - liquidity["pdl"]) < tolerance:
                c1_overlaps_key_level = True
        
        # Session levels
        for session, levels in liquidity.get("sessions", {}).items():
            tolerance = get_pair_tolerance(pair)
            if abs(h - levels["high"]) < tolerance:
                c1_overlaps_key_level = True
            if abs(l - levels["low"]) < tolerance:
                c1_overlaps_key_level = True
    
    # Check POI overlap
    if poi and not c1_overlaps_key_level:
        # Order blocks
        for ob_type in ["bullish", "bearish"]:
            ob = poi["order_blocks"].get(ob_type)
            if ob:
                # C1 overlaps if C1 range intersects OB range
                if not (h < ob["low"] or l > ob["high"]):
                    c1_overlaps_key_level = True
                    break
        
        # FVGs
        for fvg_type in ["bullish", "bearish"]:
            fvg = poi["fvg"].get(fvg_type)
            if fvg:
                # C1 overlaps if C1 range intersects FVG
                if not (h < fvg["low"] or l > fvg["high"]):
                    c1_overlaps_key_level = True
                    break
        
        # Breakers
        breaker = poi.get("breaker")
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
            "rr":           round((h - c2["close"]) / (c2["close"] - c2["low"]), 2) if c2["close"] != c2["low"] else 0,
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
            "rr":           round((c2["close"] - l) / (c2["high"] - c2["close"]), 2) if c2["high"] != c2["close"] else 0,
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

## 🔄 UPDATED scan_pair() FUNCTION

```python
def scan_pair(pair: str, yf_ticker: str = None, ccxt_symbol: str = None):
    """Run CRT scan across H1, H4, D1 for one pair."""
    log.info("Scanning %s ...", pair)
    pair_signals = {}

    for tf in ["D1", "H4", "H1"]:
        candles = get_candles_for_pair(pair, yf_ticker, ccxt_symbol, tf)
        if len(candles) < 2:
            log.warning("%s %s: not enough candles", pair, tf)
            continue
        
        # NEW: detect_crt() now takes only (candles, tf, pair)
        # ATR and liquidity/POI detection happen inside detect_crt()
        signal = detect_crt(candles, tf, pair)
        
        pair_signals[tf] = signal
        if signal:
            confluence_note = f" ({signal.get('total_confluences', 0)} confluences, {signal.get('quality_tier', 'B')} tier)"
            log.info("  ✅ %s CRT on %s %s (quality %.0f%%)%s",
                     signal["type"], pair, tf, signal["quality"] * 100, confluence_note)

    # Build multi-TF bias
    bias = get_multi_tf_bias(pair_signals)

    # Alert on valid setups (A-tier minimum)
    for tf, signal in pair_signals.items():
        if not signal:
            continue

        confidence, total_past = get_confidence(pair, tf)

        # Filter: if we have enough history and confidence is too low, skip
        if total_past >= MIN_SIGNALS_FOR_FILTER and confidence < MIN_CONFIDENCE:
            log.info("  ⏭ Skipping %s %s — low confidence (%.0f%%)",
                     pair, tf, confidence * 100)
            continue

        # Skip if H1 signal conflicts with D1 bias
        if tf == "H1" and bias == "CONFLICTED":
            log.info("  ⏭ Skipping H1 — conflicted HTF bias")
            continue

        # Get quality tier
        quality_tier = signal.get("quality_tier", "B")
        quality_score = signal.get("quality_score", 50)
        total_confluences = signal.get("total_confluences", 0)
        
        # Log tier distribution for 24h monitoring
        log.info(f"  📊 {pair} {tf} — Tier: {quality_tier} ({quality_score}%), Confluences: {total_confluences}")
        
        # Track tier for 24h monitoring
        log_tier(quality_tier, pair, tf)

        # ACTIVATION RULE: A-tier minimum for alerts
        if quality_tier == "B":
            log.info(f"  ⏭ {pair} {tf} — B-tier (no confluence) — logged, no alert")
            continue
        
        # A or A+ tier — send alert
        log.info(f"  🚨 {pair} {tf} — {quality_tier} tier ({quality_score}%) — ALERT SENT")

        # Send Telegram alert
        msg = build_alert(pair, tf, signal, confidence, total_past, bias)
        send_alert_sync(msg)

    # Update current price for outcome tracking
    if candles := get_candles_for_pair(pair, yf_ticker, ccxt_symbol, "H1"):
        current_prices[pair] = candles[-1]["close"]
```

---

## 📊 CODE DIFF SUMMARY

| File | Change | Lines |
|------|--------|-------|
| `crtscan.py` | Add `calculate_atr()` function | +25 lines |
| `crtscan.py` | Replace `detect_crt()` signature | Modified |
| `crtscan.py` | Add ATR computation inside `detect_crt()` | +5 lines |
| `crtscan.py` | Add liquidity/POI detection inside `detect_crt()` | +40 lines |
| `crtscan.py` | Simplify `scan_pair()` call | -3 lines |
| `liquidity_poi.py` | No changes (already has pair/timeframe params) | — |

---

## 🙏 AWAITING HERMES/BLUE AUDIT

**Please verify:**
1. ✅ ATR(14) computed inside `detect_crt()` (self-contained)
2. ✅ `pair` and `timeframe` passed through (for tolerance lookup)
3. ✅ Institutional candle filter: `rng < atr_14 * 1.2`
4. ✅ Key level filter: C1 overlaps liquidity OR POI
5. ✅ 2-candle detection (C1 + C2, no C3)
6. ✅ Correct candle indexing (C1=candles[-2], C2=candles[-1])
7. ✅ Delivery filter retained (Blue's rule)
8. ✅ Confluence/quality tier system retained

**Reply:**
- ✅ **APPROVED** — Deploy to production
- ❌ **CHANGES** — Specify adjustments needed

— Hazel 🌰

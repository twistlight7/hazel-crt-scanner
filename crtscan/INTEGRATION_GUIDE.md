# 🔌 liquidity_poi.py Integration Guide for crtscan.py

**FIX #3:** Updated function signatures require `pair` and `timeframe` parameters.

---

## 📋 CHANGED FUNCTION SIGNATURES

### Before → After:

```python
# OLD (will break):
find_equal_highs(candles)
detect_liquidity_pools(candles, current_time)
validate_crt_sweep(candles, c1, c2, direction)

# NEW (correct):
find_equal_highs(candles, pair)
detect_liquidity_pools(candles, pair, timeframe, current_time)
validate_crt_sweep(candles, c1, c2, pair, timeframe, direction)
```

---

## 🔧 INTEGRATION STEPS

### Step 1: Import the Module

At top of `crtscan.py`:

```python
from liquidity_poi import validate_crt_sweep, get_pair_tolerance
```

### Step 2: Update `detect_crt()` Function

In `crtscan.py`, the `detect_crt()` function needs to:
1. Accept `pair` and `timeframe` parameters
2. Call `validate_crt_sweep()` with all required args
3. Use the returned quality tier/score

**Example:**

```python
def detect_crt(candles: list, timeframe: str, pair: str) -> dict | None:
    """
    Detect CRT pattern and validate against liquidity/POI.
    
    NEW ARGS:
      pair: Symbol name (e.g., "EURUSD", "BTCUSDT")
      timeframe: "H1", "H4", or "D1"
    """
    if len(candles) < 3:
        return None

    c1 = candles[-3]   # base candle (2 ago — FULLY CLOSED)
    c2 = candles[-2]   # sweep candle (1 ago — FULLY CLOSED)

    h = c1["high"]
    l = c1["low"]
    rng = h - l

    # Minimum range filter
    if rng < 0.0001 * c1["close"]:
        return None

    # ── Bullish CRT ──
    if c2["low"] < l and c2["close"] > l:
        # Check delivery
        delivery = check_delivery_bullish(c1, c2)
        if delivery > 0.50:
            return None
        
        # Validate against liquidity/POI
        validation = validate_crt_sweep(candles, c1, c2, pair, timeframe, "bullish")
        
        sweep_depth = l - c2["low"]
        reclaim_strength = c2["close"] - l
        quality = round(reclaim_strength / rng, 2)

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
            # NEW — Confluence info
            "quality_tier":      validation["quality_tier"],
            "quality_score":     validation["quality_score"],
            "swept_pools":       validation["swept_pools"],
            "tapped_pois":       validation["tapped_pois"],
            "total_confluences": validation["total_confluences"],
        }

    # ── Bearish CRT ──
    if c2["high"] > h and c2["close"] < h:
        # Check delivery
        delivery = check_delivery_bearish(c1, c2)
        if delivery > 0.50:
            return None
        
        # Validate against liquidity/POI
        validation = validate_crt_sweep(candles, c1, c2, pair, timeframe, "bearish")
        
        sweep_depth = c2["high"] - h
        reclaim_strength = h - c2["close"]
        quality = round(reclaim_strength / rng, 2)

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
            # NEW — Confluence info
            "quality_tier":      validation["quality_tier"],
            "quality_score":     validation["quality_score"],
            "swept_pools":       validation["swept_pools"],
            "tapped_pois":       validation["tapped_pois"],
            "total_confluences": validation["total_confluences"],
        }

    return None
```

### Step 3: Update `scan_pair()` Function

Where `detect_crt()` is called, pass `pair` and `timeframe`:

```python
# OLD:
signal = detect_crt(candles, tf)

# NEW:
signal = detect_crt(candles, tf, pair)
```

### Step 4: Update `build_alert()` Function

Include confluence info in alerts:

```python
def build_alert(pair: str, tf: str, signal: dict, confidence: float,
                total_past: int, bias: str) -> str:
    # ... existing code ...
    
    # Add confluence info
    confluence_line = ""
    if signal.get("total_confluences", 0) > 0:
        pools = ", ".join(signal.get("swept_pools", []))
        pois = ", ".join(signal.get("tapped_pois", []))
        confluence_line = f"\n🔹 Liquidity: {pools}" if pools else ""
        confluence_line += f"\n🔹 POI: {pois}" if pois else ""
        confluence_line += f"\n🔹 Tier: {signal.get('quality_tier', 'B')} ({signal.get('quality_score', 50)}%)"
    
    lines = [
        f"<b>━━━ CRT SIGNAL DETECTED ━━━</b>",
        f"{em} <b>{signal['type']} CRT</b> — {pair} {tf}",
        # ... existing lines ...
        confluence_line,  # Add here
        # ... rest of lines ...
    ]
    return "\n".join(lines)
```

---

## 📊 EXAMPLE ALERT OUTPUT

```
🟢 BULLISH CRT — EURUSD H1

Entry: 1.08450
TP: 1.08620 | SL: 1.08380
R:R: 2.4R

🔹 Liquidity: Equal Lows, Asian Low
🔹 POI: Bullish OB
🔹 Tier: A (70%)

⏱ 2026-04-03 22:00 UTC
```

---

## ✅ INTEGRATION CHECKLIST

- [ ] Import `validate_crt_sweep` and `get_pair_tolerance`
- [ ] Update `detect_crt()` signature: add `pair` and `timeframe` params
- [ ] Call `validate_crt_sweep(candles, c1, c2, pair, timeframe, direction)`
- [ ] Add confluence fields to signal dict
- [ ] Update `scan_pair()` to pass `pair` to `detect_crt()`
- [ ] Update `build_alert()` to show confluence info
- [ ] Test with one pair (e.g., EURUSD) before enabling all

---

## 🙏 READY FOR BLUE'S REVIEW

Once these integration changes are made to `crtscan.py`, the scanner will:
- Use dynamic tolerance per pair
- Detect swing-point liquidity pools
- Validate sweeps against real liquidity/POI
- Return quality tiers (A+/A/B) based on confluences
- Show confluence info in every alert

**Awaiting approval to proceed with integration.** 🙏

— Hazel 🌰

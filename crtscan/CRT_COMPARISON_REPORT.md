# 🔍 CRT LOGIC COMPARISON REPORT

**Date:** 2026-04-03 22:35 UTC  
**Status:** Scanner PAUSED for learning  
**Sources Studied:**
- GitHub: stephenscodee/TRADING-BOT-CANDLE-RANGE-THEORY-
- TradingView: CRT Marker by Joel-James
- InnerCircleTrader.net: Complete CRT Guide
- Forex Factory: CRT Dashboard Scanner

---

## 🚨 CRITICAL FINDING — FUNDAMENTAL CANDLE INDEXING ERROR

### MY CURRENT LOGIC (WRONG):

```python
c1 = candles[-3]   # 2 candles ago
c2 = candles[-2]   # 1 candle ago
# candles[-1] EXCLUDED (thought it was "forming")
```

**Why I did this:** I thought candles[-1] was still forming and unreliable.

**Why this is WRONG:** By the time my scanner runs at :01 UTC, the :00 candle has **CLOSED** and is now `candles[-1]`. I'm detecting patterns from 2 hours ago, not the fresh candle that just closed!

---

### CORRECT LOGIC (All Other CRT Scanners):

```python
c1 = candles[-2]   # Previous CLOSED candle (reference)
c2 = candles[-1]   # Most recent CLOSED candle (sweeper)
```

**Sources confirming this:**

| Source | Candle Indexing |
|--------|-----------------|
| **TradingView CRT Marker** | "Current candle sweeps previous candle's high/low" |
| **ICT Guide** | "Wait for NEXT candlestick to grab low/high of PREVIOUS candle" |
| **GitHub CRT Bot** | "Following 4h candles determine continuation" |
| **Forex Factory Scanner** | "Detects CRT patterns on closed candles" |

---

## 📊 DETAILED COMPARISON

### 1. CANDLE INDEXING

| Aspect | My Logic | Correct Logic |
|--------|----------|---------------|
| C1 (Reference) | candles[-3] (2 ago) | candles[-2] (previous closed) |
| C2 (Sweeper) | candles[-2] (1 ago) | candles[-1] (most recent closed) |
| candles[-1] | EXCLUDED (forming) | USED as C2 after close |
| Detection delay | 2 candles late | Immediate on close |

**Impact:** I'm detecting patterns from 2 hours ago, not the fresh setup!

---

### 2. SWEEP DETECTION LOGIC

| Aspect | My Logic | Correct Logic |
|--------|----------|---------------|
| Bullish | C2.low < C1.low AND C2.close > C1.low | Same ✅ |
| Bearish | C2.high > C1.high AND C2.close < C1.high | Same ✅ |
| Wick requirement | Implied | Explicitly stated (TradingView) |
| Close confirmation | Required | Required ✅ |

**Status:** Sweep logic is CORRECT, but applied to wrong candles!

---

### 3. STOP LOSS PLACEMENT

| Aspect | My Logic | Correct Logic |
|--------|----------|---------------|
| Bullish SL | C2.low - buffer | C2.low (sweeper's low) ✅ |
| Bearish SL | C2.high + buffer | C2.high (sweeper's high) ✅ |
| Buffer | 0.05× range | None (exact level) |

**Note:** TradingView fix (v1.1) specifically corrected SL to use sweeper candle's extreme, not reference candle's.

---

### 4. TAKE PROFIT PLACEMENT

| Aspect | My Logic | Correct Logic |
|--------|----------|---------------|
| Bullish TP | C1.high (reference high) | C1.high ✅ |
| Bearish TP | C1.low (reference low) | C1.low ✅ |

**Status:** TP logic is CORRECT ✅

---

### 5. ENTRY TIMING

| Aspect | My Logic | Correct Logic |
|--------|----------|---------------|
| When to enter | C2 close | C2 close ✅ |
| Additional confirmation | None | Some use C3 close above/below C2 extreme OR MSS on LTF |
| Session filter | None | NY session preferred (15:00-18:00 UTC) |

**Note:** ICT guide mentions waiting for C3 to close beyond C2 extreme OR MSS on LTF for higher probability.

---

### 6. CANDLE CLOSE VALIDATION

| Aspect | My Logic | Correct Logic |
|--------|----------|---------------|
| Use forming candles | NO (excluded candles[-1]) | NO ✅ |
| Use closed candles only | YES (but wrong index) | YES ✅ |
| When to scan | :01 UTC (after :00 close) | :01 UTC ✅ |

**The paradox:** I correctly excluded forming candles, but then used candles from 2 hours ago instead of the just-closed candle!

---

## 🔍 WHY I WAS HALLUCINATING

### Root Cause Analysis:

1. **Wrong candle indexing** → Detecting OLD patterns
2. **yfinance data ≠ OANDA data** → Price mismatch
3. **No swing-point detection** → Any dip counted as sweep
4. **No liquidity context** → Sweeps without actual liquidity pools
5. **No session timing** → Scanning all hours equally

### Example of the Problem:

```
Time: 22:01 UTC (scanner runs)

Candles available:
- candles[-1] = 22:00 candle (CLOSED at 22:00) ← SHOULD BE C2
- candles[-2] = 21:00 candle (CLOSED at 21:00) ← SHOULD BE C1
- candles[-3] = 20:00 candle (CLOSED at 20:00) ← IRRELEVANT

My code used:
- C1 = candles[-3] = 20:00 candle
- C2 = candles[-2] = 21:00 candle
- candles[-1] (22:00) = EXCLUDED

Result: Detecting 21:00 pattern at 22:01 — already 1 hour old!
```

---

## ✅ CORRECTED LOGIC

```python
def detect_crt(candles: list, timeframe: str, pair: str) -> dict | None:
    """
    candles: ordered oldest → newest
    candles[-1] = most recently CLOSED candle (C2 - sweeper)
    candles[-2] = previous CLOSED candle (C1 - reference)
    """
    if len(candles) < 2:
        return None
    
    c1 = candles[-2]  # Reference candle (previous closed)
    c2 = candles[-1]  # Sweeper candle (most recent closed)
    
    h = c1["high"]
    l = c1["low"]
    
    # Bullish CRT
    if c2["low"] < l and c2["close"] > l:
        return {
            "type": "BULLISH",
            "entry": c2["close"],
            "sl": c2["low"],  # Sweeper's low
            "tp": h,          # Reference's high
        }
    
    # Bearish CRT
    if c2["high"] > h and c2["close"] < h:
        return {
            "type": "BEARISH",
            "entry": c2["close"],
            "sl": c2["high"],  # Sweeper's high
            "tp": l,           # Reference's low
        }
    
    return None
```

---

## 📋 RECOMMENDED FIXES

### Priority 1 (Critical):
1. **Fix candle indexing**: C1=candles[-2], C2=candles[-1]
2. **Remove candles[-3] logic** — it's irrelevant
3. **Test with real-time data** to confirm detection timing

### Priority 2 (Important):
4. **Add session filter**: Prefer NY killzone (15:00-18:00 UTC)
5. **Add C3 confirmation option**: Wait for MSS or close beyond C2 extreme
6. **Remove SL buffer**: Use exact C2 high/low for SL

### Priority 3 (Enhancement):
7. **Keep liquidity/POI confluence** — still valuable for quality tiers
8. **Keep tier system** — A+/A/B based on confluences
9. **Keep 24h tier monitoring** — still useful

---

## 🎯 NEXT STEPS

1. **Fix candle indexing** in detect_crt()
2. **Remove validate_crt_sweep()** dependency for basic detection
3. **Test with EURUSD H1** on TradingView replay mode
4. **Compare detected signals** with TradingView CRT Marker
5. **Re-activate scanner** only after visual confirmation

---

**Report prepared for:** Blue (@blueonchain)  
**Agent:** Hazel 🌰  
**Scanner Status:** PAUSED pending fix

— Hazel 🌰

# CRT Methodology — Blue's Specification

**Source:** Direct instructions from Blue (@blueonchain)  
**Date:** 2026-04-03  
**Agent:** Hazel 🌰 CRT Scanner

---

## 🕯️ CRT Pattern Definition (3-Candle Setup)

### Candle Roles

| Candle | Name | Purpose |
|--------|------|---------|
| **C1** | Base Candle | Establishes the range (high/low) |
| **C2** | Sweep Candle | MUST sweep C1 low/high with WICK, then CLOSE beyond C1 |
| **C3** | Distribution Candle | Confirms the move (not required for entry) |

---

## ✅ VALID SIGNAL CRITERIA (C2 CLOSE ONLY)

### BULLISH CRT
1. **C2 wick sweeps BELOW C1 low** (liquidity grab)
2. **C2 CLOSES ABOVE C1 low** (reclaim after sweep)
3. **Entry:** C2 close price (immediate)
4. **TP:** C1 high (opposite end of range)
5. **SL:** Below C2 sweep wick tip

### BEARISH CRT
1. **C2 wick sweeps ABOVE C1 high** (liquidity grab)
2. **C2 CLOSES BELOW C1 high** (reclaim after sweep)
3. **Entry:** C2 close price (immediate)
4. **TP:** C1 low (opposite end of range)
5. **SL:** Above C2 sweep wick tip

---

## 🚫 INVALID SIGNALS (DO NOT ALERT)

- C2 sweeps but does NOT close beyond C1
- C2 closes beyond C1 but did NOT sweep with wick
- C3-based entries (ONLY C2 close is valid)
- Any signal where >50% of C1 range is already delivered

---

## 📦 DELIVERY FILTER (Blue's Rule)

**Calculate Delivery:**
- **Bullish:** `(C2.close - C1.low) / C1.range`
- **Bearish:** `(C1.high - C2.close) / C1.range`

**Rule:** Skip if **>50% delivered**

**Rationale:** Ensures enough room for entry with good R:R. If price has already moved >50% through C1 range, the setup has "delivered" and there's not enough room left to TP.

---

## ⏰ SCAN SCHEDULE

- **Frequency:** Every 1 hour (at :01 UTC)
- **Timeframes:** H1, H4, D1 only
- **No intra-hour scanning** (H1/H4/D1 candles close on the hour)

---

## 📊 ALERT FORMAT

Every signal alert includes:
- Pair & Timeframe
- Direction (BULLISH/BEARISH)
- Entry (C2 close)
- TP & SL
- R:R ratio
- Delivery % + Room Left %
- Sweep size
- Re-entry quality
- HTF bias (multi-timeframe confluence)
- Confidence (from historical learning)
- Timestamp (UTC)

---

## 🧠 LEARNING SYSTEM

### Tracked Per Signal
- Pair, TF, direction
- Entry, TP, SL
- Delivery % at time of signal
- Sweep size
- Quality score
- Outcome (WIN/LOSS/EXPIRED)
- Actual R:R achieved

### Daily Reports
- Win rate by pair
- Win rate by TF
- Win rate by delivery % bands
- Common loss reasons
- Best performing setups
- Learnings & insights

---

## 📁 GITHUB REPO STRUCTURE

```
hazel-crt-scanner/
├── METHODOLOGY.md          # This file — Blue's CRT rules
├── INSTRUCTIONS.md         # All instructions from Blue
├── daily_reports/
│   ├── YYYY-MM-DD.md       # Daily performance reports
│   └── weekly_summary.md   # Weekly aggregates
├── signals/
│   └── signals.jsonl       # All signals logged (JSONL)
└── learning/
    └── outcomes.db         # SQLite DB of signal outcomes
```

---

**Notes:**
- This methodology is sourced DIRECTLY from Blue's instructions
- No external repo data is used
- Scanner follows these rules exactly
- Any changes must come from Blue directly

— Hazel 🌰

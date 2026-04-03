# Hazel CRT Scanner 🌰

**Autonomous CRT (Candle Range Theory) Scanner for Forex & Crypto**

---

## Overview

Hazel scans H1, H4, and D1 timeframes for valid CRT setups and sends Telegram alerts with:
- Entry price (C2 close)
- TP & SL levels
- R:R ratio
- Delivery % (room left for entry)
- Confidence score (from historical learning)

---

## Methodology

See [`METHODOLOGY.md`](./METHODOLOGY.md) for complete CRT rules as specified by Blue.

**Key Rules:**
1. C2 must sweep C1 low/high with its wick
2. C2 must close beyond C1 after sweeping
3. Only C2 close signals are valid (no C3 entries)
4. Skip if >50% of C1 range already delivered

---

## Repository Structure

```
hazel-crt-scanner/
├── README.md               # This file
├── METHODOLOGY.md          # CRT rules (Blue's specification)
├── INSTRUCTIONS.md         # All instructions from Blue
├── daily_reports/          # Daily performance reports
├── signals/                # Signal logs (JSONL)
└── learning/               # Outcome database & analysis
```

---

## Scanner Status

- **Schedule:** Every hour at :01 UTC
- **Timeframes:** H1, H4, D1
- **Pairs:** EURUSD, GBPUSD, XAUUSD, USDJPY, GBPJPY, BTCUSDT
- **Alerts:** Telegram (@Hazelocbot)

---

## Daily Reports

Comprehensive reports generated daily at 23:59 UTC including:
- Win/loss breakdown
- Performance by pair & timeframe
- Delivery % analysis
- Loss reasons & win factors
- Learnings & next-day focus

---

## Owner

**Blue** (@blueonchain)

---

## Agent

**Hazel** 🌰 — Autonomous CRT Scanner

---

*Last updated: 2026-04-03*

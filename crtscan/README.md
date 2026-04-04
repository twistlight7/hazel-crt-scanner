# CRTSCAN - Candle Range Theory Scanner

Automated CRT pattern scanner for FOREX and Crypto markets.

## Features

- **Multi-market**: Scans FOREX (EURUSD, GBPUSD, XAUUSD, USDJPY, GBPJPY) + BTC/USDT
- **Multi-timeframe**: H1, H4, D1 CRT pattern detection
- **Learning engine**: Tracks signal outcomes in SQLite, adjusts confidence per pair+timeframe
- **Live pricing**: Binance WebSocket for real-time BTC price tracking
- **Auto-alerts**: Telegram notifications for valid setups
- **Scheduled scans**: Runs at every H1 candle close (:01 UTC)

## CRT Detection Rules

**Bullish CRT:**
1. C2 sweeps below C1 low (liquidity grab)
2. C2 closes back inside C1 range
3. Target = C1 high, SL = C2 low (below sweep wick)

**Bearish CRT:**
1. C2 sweeps above C1 high
2. C2 closes back inside C1 range
3. Target = C1 low, SL = C2 high (above sweep wick)

## Setup

```bash
cd crtscan
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Telegram credentials
python crtscan.py
```

## Database

Signals stored in `~/.crtscan/learning.db`

- Tracks all detected signals with outcomes (WIN/LOSS/EXPIRED/PENDING)
- Confidence scoring based on last 30 signals per pair+timeframe
- Minimum 5 signals required before confidence filtering applies
- Signals expire after 5 days if not hit

## Alert Filtering

- Minimum confidence: 45% win rate (after 5+ historical signals)
- H1 signals skipped if HTF bias is CONFLICTED
- D1 bias overrides lower timeframes when aligned

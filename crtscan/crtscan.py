"""
CRTSCAN - Candle Range Theory Scanner
======================================
Scans FOREX + BTC for valid CRT setups on H1, H4, D1.
Uses WebSocket (Binance) for live BTC price tracking.
Schedules REST candle checks at every candle close.
Learning engine: tracks signal outcomes in SQLite, 
adjusts confidence score per pair+timeframe.
Sends alerts to Telegram.
"""

import os
import json
import time
import sqlite3
import asyncio
import logging
import threading
import websocket
import ccxt
import yfinance as yf
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from telegram import Bot
from apscheduler.schedulers.background import BackgroundScheduler

# OANDA client (optional — DISABLED until credentials configured)
OANDA_AVAILABLE = False

# Liquidity & POI detection module (FIX #3 integration)
from liquidity_poi import validate_crt_sweep, get_pair_tolerance, detect_liquidity_pools, detect_poi_levels

# Tier tracker for 24h monitoring
from tier_tracker import log_tier, get_summary

load_dotenv()

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

FOREX_PAIRS = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "XAUUSD": "GC=F",       # Gold
    "USDJPY": "USDJPY=X",
    "GBPJPY": "GBPJPY=X",
}

CRYPTO_PAIRS = {
    "BTCUSDT": "BTC/USDT",
}

TIMEFRAMES = {
    "H1":  {"yf": "1h",  "ccxt": "1h",  "bars": 5,  "interval_min": 60},
    "H4":  {"yf": "1h",  "ccxt": "4h",  "bars": 10, "interval_min": 240},
    "D1":  {"yf": "1d",  "ccxt": "1d",  "bars": 10, "interval_min": 1440},
}

DB_PATH = os.path.expanduser("~/.crtscan/learning.db")
MIN_CONFIDENCE = 0.45   # Only alert if win rate >= 45% (starts at 0.5 neutral)
MIN_SIGNALS_FOR_FILTER = 5  # Need at least 5 past signals before filtering by confidence

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("CRTSCAN")

# ─────────────────────────────────────────────
# DATABASE — Learning Engine
# ─────────────────────────────────────────────

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            pair        TEXT NOT NULL,
            timeframe   TEXT NOT NULL,
            signal_type TEXT NOT NULL,       -- BULLISH / BEARISH
            entry_price REAL NOT NULL,
            tp_price    REAL NOT NULL,
            sl_price    REAL NOT NULL,
            range_high  REAL NOT NULL,
            range_low   REAL NOT NULL,
            detected_at TEXT NOT NULL,
            outcome     TEXT DEFAULT 'PENDING',  -- PENDING / WIN / LOSS / EXPIRED
            closed_at   TEXT,
            rr_ratio    REAL,
            session     TEXT,              -- ASIAN / LONDON / NY / LATE_NY
            pillar_score INTEGER DEFAULT 50,  -- 0-100 confluence score
            structure   TEXT,              -- UPTREND/DOWNTREND/RANGE
            poi         TEXT,              -- Order block, FVG, etc.
            liquidity_type TEXT           -- What liquidity was swept
        )
    """)
    
    # Add new columns if table exists (migration)
    try:
        c.execute("ALTER TABLE signals ADD COLUMN session TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    try:
        c.execute("ALTER TABLE signals ADD COLUMN pillar_score INTEGER DEFAULT 50")
    except sqlite3.OperationalError:
        pass
    
    try:
        c.execute("ALTER TABLE signals ADD COLUMN structure TEXT")
    except sqlite3.OperationalError:
        pass
    
    try:
        c.execute("ALTER TABLE signals ADD COLUMN poi TEXT")
    except sqlite3.OperationalError:
        pass
    
    try:
        c.execute("ALTER TABLE signals ADD COLUMN liquidity_type TEXT")
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    conn.close()
    log.info("DB ready: %s", DB_PATH)


def log_signal(pair, tf, signal):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Determine session/killzone
    utc_hour = datetime.now(timezone.utc).hour
    session = get_session_name(utc_hour)
    
    # Basic pillar scoring (to be enhanced)
    pillar_score = 50  # Default neutral
    structure = "UNKNOWN"
    poi = ""
    liquidity = "SWEEP"  # Default
    
    c.execute("""
        INSERT INTO signals
        (pair, timeframe, signal_type, entry_price, tp_price, sl_price,
         range_high, range_low, detected_at, session, pillar_score,
         structure, poi, liquidity_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        pair, tf,
        signal["type"],
        signal["entry"],
        signal["tp"],
        signal["sl"],
        signal["range_high"],
        signal["range_low"],
        datetime.utcnow().isoformat(),
        session,
        pillar_score,
        structure,
        poi,
        liquidity
    ))
    conn.commit()
    conn.close()


def get_session_name(utc_hour: int) -> str:
    """Return session name for given UTC hour."""
    if 0 <= utc_hour < 8:
        return "ASIAN"
    elif 8 <= utc_hour < 12:
        return "LONDON"
    elif 12 <= utc_hour < 17:
        return "NY"
    else:
        return "LATE_NY"


def get_confidence(pair, timeframe):
    """
    Returns (win_rate, total_signals).
    win_rate is float 0-1. Returns 0.5 (neutral) if not enough data.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT outcome FROM signals
        WHERE pair=? AND timeframe=? AND outcome IN ('WIN','LOSS')
        ORDER BY detected_at DESC LIMIT 30
    """, (pair, timeframe))
    rows = c.fetchall()
    conn.close()

    if len(rows) < MIN_SIGNALS_FOR_FILTER:
        return 0.5, len(rows)   # neutral / not enough data

    wins   = sum(1 for r in rows if r[0] == "WIN")
    total  = len(rows)
    return round(wins / total, 2), total


def update_outcomes(current_prices: dict):
    """
    Check all PENDING signals and mark WIN/LOSS/EXPIRED.
    current_prices = {"EURUSD": 1.0850, "BTCUSDT": 65000, ...}
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, pair, signal_type, tp_price, sl_price, detected_at
        FROM signals WHERE outcome='PENDING'
    """)
    pending = c.fetchall()

    for row in pending:
        sid, pair, stype, tp, sl, detected_at = row
        price = current_prices.get(pair)
        if not price:
            continue

        detected = datetime.fromisoformat(detected_at)
        age_hours = (datetime.utcnow() - detected).total_seconds() / 3600

        outcome = None
        if stype == "BULLISH":
            if price >= tp:
                outcome = "WIN"
            elif price <= sl:
                outcome = "LOSS"
        else:  # BEARISH
            if price <= tp:
                outcome = "WIN"
            elif price >= sl:
                outcome = "LOSS"

        # Expire after 5 days
        if outcome is None and age_hours > 120:
            outcome = "EXPIRED"

        if outcome:
            # Calculate actual RR based on original signal (use stored range as proxy)
            c.execute("SELECT entry_price, range_high, range_low FROM signals WHERE id=?", (sid,))
            row = c.fetchone()
            if row:
                entry, rh, rl = row
                risk = abs(entry - sl) if stype == "BULLISH" else abs(sl - entry)
                reward = abs(tp - entry)
                rr = round(reward / risk, 2) if risk > 0 else 1.0
            else:
                rr = 1.0
            c.execute("""
                UPDATE signals
                SET outcome=?, closed_at=?, rr_ratio=?
                WHERE id=?
            """, (outcome, datetime.utcnow().isoformat(), rr, sid))
            log.info("Signal #%d %s %s → %s (RR: %s)", sid, pair, stype, outcome, rr)

    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# CRT DETECTION ENGINE
# ─────────────────────────────────────────────

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
        tolerance = get_pair_tolerance(pair)
        # Equal highs/lows
        if liquidity.get("equal_highs"):
            if abs(h - liquidity["equal_highs"]) < tolerance:
                c1_overlaps_key_level = True
        if liquidity.get("equal_lows"):
            if abs(l - liquidity["equal_lows"]) < tolerance:
                c1_overlaps_key_level = True
        
        # PDH/PDL
        if liquidity.get("pdh"):
            if abs(h - liquidity["pdh"]) < tolerance:
                c1_overlaps_key_level = True
        if liquidity.get("pdl"):
            if abs(l - liquidity["pdl"]) < tolerance:
                c1_overlaps_key_level = True
        
        # Session levels
        for session, levels in liquidity.get("sessions", {}).items():
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


def check_delivery_bullish(c1: dict, c2: dict) -> float:
    """Calculate delivery for bullish CRT (C2 close relative to C1 range from low)."""
    h = c1["high"]
    l = c1["low"]
    rng = h - l
    if rng == 0:
        return 1.0
    return (c2["close"] - l) / rng


def check_delivery_bearish(c1: dict, c2: dict) -> float:
    """Calculate delivery for bearish CRT (C2 close relative to C1 range from high)."""
    h = c1["high"]
    l = c1["low"]
    rng = h - l
    if rng == 0:
        return 1.0
    return (h - c2["close"]) / rng


def get_multi_tf_bias(pair_signals: dict) -> str:
    """
    pair_signals = {"D1": signal_or_None, "H4": signal_or_None, "H1": signal_or_None}
    Returns: "BULLISH" / "BEARISH" / "CONFLICTED" / "NONE"
    """
    types = {tf: s["type"] for tf, s in pair_signals.items() if s}
    if not types:
        return "NONE"

    # D1 bias overrides
    if "D1" in types:
        d1_bias = types["D1"]
        aligned = [v for v in types.values() if v == d1_bias]
        return d1_bias if len(aligned) >= 2 else "CONFLICTED"

    if len(set(types.values())) == 1:
        return list(types.values())[0]

    return "CONFLICTED"


# ─────────────────────────────────────────────
# DATA FETCHING
# ─────────────────────────────────────────────

exchange = ccxt.binance({"enableRateLimit": True})

def fetch_crypto_candles(symbol: str, timeframe: str, limit: int = 5) -> list:
    """
    Fetch OHLCV from Binance via ccxt.
    
    FIX (2026-04-04 06:00 UTC): Include ALL closed candles.
    At scan time (:01 UTC), the :00 candle IS CLOSED.
    ccxt returns only closed candles by default.
    """
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        candles = []
        for o in ohlcv:  # Include all candles (all are closed at :01 UTC)
            candles.append({
                "timestamp": o[0],
                "open":  o[1], "high": o[2],
                "low":   o[3], "close": o[4],
                "volume": o[5]
            })
        return candles
    except Exception as e:
        log.error("Crypto fetch error %s %s: %s", symbol, timeframe, e)
        return []


def fetch_forex_candles(yf_ticker: str, period: str, interval: str, limit: int = 5) -> list:
    """
    Fetch OHLCV from yfinance for forex.
    
    FIX (2026-04-04 06:00 UTC): Include ALL closed candles.
    At scan time (:01 UTC), the :00 candle IS CLOSED.
    yfinance may include forming candle, so we use tail(limit) to get exactly `limit` closed candles.
    """
    try:
        ticker = yf.Ticker(yf_ticker)
        df = ticker.history(period=period, interval=interval)
        if df.empty:
            return []
        # Get exactly `limit` closed candles (yfinance may include forming candle at end)
        df = df.tail(limit)
        candles = []
        for ts, row in df.iterrows():
            candles.append({
                "timestamp": int(ts.timestamp() * 1000),  # Convert to milliseconds
                "open":  row["Open"],  "high": row["High"],
                "low":   row["Low"],   "close": row["Close"],
                "volume": row.get("Volume", 0)
            })
        return candles
    except Exception as e:
        log.error("Forex fetch error %s: %s", yf_ticker, e)
        return []


def get_candles_for_pair(pair: str, yf_ticker: str | None, ccxt_symbol: str | None, tf: str) -> list:
    tf_cfg = TIMEFRAMES[tf]
    if ccxt_symbol:
        # Crypto — always use ccxt/Binance
        return fetch_crypto_candles(ccxt_symbol, tf_cfg["ccxt"], limit=tf_cfg["bars"])
    elif OANDA_AVAILABLE:
        # Forex — try OANDA first (broker-grade candles)
        candles = oanda_fetch(pair, tf)
        if candles:
            return candles[-tf_cfg["bars"]:]
        # Fallback to yfinance if OANDA fails
        log.warning("OANDA fetch failed for %s %s, falling back to yfinance", pair, tf)
        period_map = {"H1": "7d", "H4": "60d", "D1": "1y"}
        return fetch_forex_candles(yf_ticker, period_map[tf], tf_cfg["yf"], limit=tf_cfg["bars"])
    else:
        # No OANDA — use yfinance
        period_map = {"H1": "7d", "H4": "60d", "D1": "1y"}
        return fetch_forex_candles(yf_ticker, period_map[tf], tf_cfg["yf"], limit=tf_cfg["bars"])
    return []


# ─────────────────────────────────────────────
# TELEGRAM ALERTS
# ─────────────────────────────────────────────

bot = None
if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
    bot = Bot(token=TELEGRAM_TOKEN)
    log.info("✅ Telegram bot configured")
else:
    log.warning("⚠️ Telegram not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")

EMOJI = {"BULLISH": "🟢", "BEARISH": "🔴", "CONFLICTED": "⚠️"}

def send_alert_sync(message: str):
    """Synchronous Telegram sender for use in scheduler context."""
    if not bot:
        log.warning("Telegram not configured — skipping alert")
        log.info("Alert would have been: %s", message[:200])
        return
    try:
        # Use synchronous request to avoid event loop issues
        import urllib.request
        import json
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = json.dumps({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            if result.get("ok"):
                log.info("✅ Alert sent to Telegram")
            else:
                log.error("Telegram send failed: %s", result)
    except Exception as e:
        log.error("Telegram send error: %s", e)


async def send_alert(message: str):
    """Async wrapper for backward compatibility."""
    send_alert_sync(message)


def build_alert(pair: str, tf: str, signal: dict, confidence: float,
                total_past: int, bias: str) -> str:
    em = EMOJI.get(signal["type"], "⚪")
    wr = f"{round(confidence * 100)}%"
    data_note = f"({total_past} past signals)" if total_past >= MIN_SIGNALS_FOR_FILTER else "(new pair — no history yet)"
    
    # Delivery info (Blue's rule: ≤50% delivered = valid entry)
    delivery = signal.get("delivery", 0)
    room_left = signal.get("room_left", 100)
    delivery_status = "✅ GOOD" if delivery <= 50 else "⚠️ DELIVERED"
    
    # C1 and C2 OHLC data for validation
    c1 = signal.get("c1_data", {})
    c2 = signal.get("c2_data", {})
    
    # FIX #3: Confluence info
    quality_tier = signal.get("quality_tier", "B")
    quality_score = signal.get("quality_score", 50)
    swept_pools = signal.get("swept_pools", [])
    tapped_pois = signal.get("tapped_pois", [])
    total_confluences = signal.get("total_confluences", 0)
    
    confluence_lines = []
    if total_confluences > 0:
        if swept_pools:
            confluence_lines.append(f"🔹 <b>Liquidity:</b> {', '.join(swept_pools)}")
        if tapped_pois:
            confluence_lines.append(f"🔹 <b>POI:</b> {', '.join(tapped_pois)}")
        confluence_lines.append(f"🔹 <b>Tier:</b> {quality_tier} ({quality_score}%)")

    lines = [
        f"<b>━━━ CRT SIGNAL DETECTED ━━━</b>",
        f"{em} <b>{signal['type']} CRT</b> — {pair} {tf}",
        f"",
        f"📍 <b>Entry:</b>  <code>{signal['entry']}</code>",
        f"🎯 <b>TP:</b>     <code>{signal['tp']}</code>",
        f"🛑 <b>SL:</b>     <code>{signal['sl']}</code>",
        f"📐 <b>R:R:</b>    {signal['rr']}R",
        f"",
        f"<b>━━━ CANDLE DATA (for validation) ━━━</b>",
        f"<b>C1 (Base):</b> O:{c1.get('open', 'N/A')} H:{c1.get('high', 'N/A')} L:{c1.get('low', 'N/A')} C:{c1.get('close', 'N/A')}",
        f"<b>C2 (Sweep):</b> O:{c2.get('open', 'N/A')} H:{c2.get('high', 'N/A')} L:{c2.get('low', 'N/A')} C:{c2.get('close', 'N/A')}",
        f"",
        f"📊 <b>Range High:</b> {signal['range_high']}",
        f"📊 <b>Range Low:</b>  {signal['range_low']}",
        f"🔀 <b>Sweep Size:</b> {signal['sweep_size']}",
        f"✅ <b>Re-entry Quality:</b> {round(signal['quality'] * 100)}%",
        f"",
        f"📦 <b>Delivery:</b>   {delivery}% ({delivery_status})",
        f"💰 <b>Room Left:</b>  {room_left}%",
    ]
    
    # Add confluence lines if any
    if confluence_lines:
        lines.append(f"")
        lines.extend(confluence_lines)
    
    lines.extend([
        f"",
        f"🔭 <b>HTF Bias:</b> {bias}",
        f"🧠 <b>Confidence:</b> {wr} {data_note}",
        f"",
        f"⏱ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC",
        f"<i>Verify on chart — C2 must sweep C1 with wick, then close beyond.</i>"
    ])
    return "\n".join(lines)


# ─────────────────────────────────────────────
# MAIN SCAN LOGIC
# ─────────────────────────────────────────────

current_prices = {}  # live prices updated by WS / poll

def poll_forex_prices():
    """
    Poll current prices for all FOREX pairs and update current_prices dict.
    Called periodically to keep forex prices fresh for outcome tracking.
    Uses OANDA if available, falls back to yfinance.
    """
    for pair, yf_ticker in FOREX_PAIRS.items():
        try:
            if OANDA_AVAILABLE:
                candles = oanda_fetch(pair, "H1")
                if candles:
                    current_prices[pair] = candles[-1]["close"]
                    continue
            
            # Fallback: yfinance
            ticker = yf.Ticker(yf_ticker)
            df = ticker.history(period="1d", interval="1m")
            if not df.empty:
                current_prices[pair] = df["Close"].iloc[-1]
        except Exception as e:
            log.debug("Forex price poll error for %s: %s", pair, e)


def scan_pair(pair: str, yf_ticker: str = None, ccxt_symbol: str = None):
    """Run CRT scan across H1, H4, D1 for one pair."""
    log.info("Scanning %s ...", pair)
    pair_signals = {}

    for tf in ["D1", "H4", "H1"]:
        candles = get_candles_for_pair(pair, yf_ticker, ccxt_symbol, tf)
        if len(candles) < 2:  # FIX (2026-04-04 06:00 UTC): detect_crt needs only 2 candles
            log.warning("%s %s: not enough candles", pair, tf)
            continue
        # Pass pair to detect_crt()
        signal = detect_crt(candles, tf, pair)
        pair_signals[tf] = signal
        if signal:
            confluence_note = f" ({signal.get('total_confluences', 0)} confluences, {signal.get('quality_tier', 'B')} tier)"
            log.info("  ✅ %s CRT on %s %s (quality %.0f%%)%s",
                     signal["type"], pair, tf, signal["quality"] * 100, confluence_note)

    # Build multi-TF bias
    bias = get_multi_tf_bias(pair_signals)

    # Alert on valid setups (ACTIVATION 2026-04-03 22:18 UTC)
    # ALERT THRESHOLD: A-tier minimum (A or A+). B-tier logged only.
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

        # Log to DB for learning (all signals, including B-tier)
        log_signal(pair, tf, signal)
        
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


def run_full_scan():
    log.info("══ Running full CRT scan ══")

    # Poll forex prices for real-time outcome tracking
    poll_forex_prices()

    # Update outcomes of past signals first
    update_outcomes(current_prices)

    # Scan forex
    for pair, yf_ticker in FOREX_PAIRS.items():
        scan_pair(pair, yf_ticker=yf_ticker)
        time.sleep(1)  # rate limit yfinance

    # Scan crypto
    for pair, ccxt_symbol in CRYPTO_PAIRS.items():
        scan_pair(pair, ccxt_symbol=ccxt_symbol)

    log.info("══ Scan complete ══")


# ─────────────────────────────────────────────
# BINANCE WEBSOCKET — Live BTC Price
# ─────────────────────────────────────────────

def on_btc_message(ws, message):
    data = json.loads(message)
    if "c" in data:  # 'c' = current price in Binance mini-ticker stream
        current_prices["BTCUSDT"] = float(data["c"])


def on_ws_error(ws, error):
    log.error("BTC WebSocket error: %s", error)


def on_ws_close(ws, close_status, close_msg):
    log.warning("BTC WebSocket closed — will reconnect via run_forever")


def on_ws_open(ws):
    log.info("✅ BTC WebSocket connected")


def _run_btc_websocket_thread():
    """
    Single WebSocket thread with automatic reconnection.
    Uses ping_interval/ping_timeout for connection health.
    """
    while True:
        try:
            ws = websocket.WebSocketApp(
                "wss://stream.binance.com:9443/ws/btcusdt@miniTicker",
                on_message=on_btc_message,
                on_error=on_ws_error,
                on_close=on_ws_close,
                on_open=on_ws_open,
            )
            # ping_interval/ping_timeout handle keepalive and reconnection
            # ping_interval must be > ping_timeout
            ws.run_forever(ping_interval=30, ping_timeout=20)
        except Exception as e:
            log.error("WS thread error: %s — reconnecting in 5s", e)
            time.sleep(5)


def start_btc_websocket():
    wst = threading.Thread(target=_run_btc_websocket_thread, daemon=True)
    wst.start()
    log.info("🔌 BTC WebSocket thread started")


# ─────────────────────────────────────────────
# SCHEDULER
# ─────────────────────────────────────────────

def start_scheduler():
    """
    Runs scan every hour at :01 UTC.
    Timeframes: H1, H4, D1 only (as per Blue's specification).
    No intra-hour polling needed — H1/H4/D1 candles close on the hour.
    """
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(run_full_scan, "cron", minute=1)   # 1 min past each hour
    scheduler.start()
    log.info("⏰ Scheduler started — scanning at :01 of every hour UTC")
    log.info("📊 Timeframes: H1, H4, D1 only")
    return scheduler


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  CRTSCAN BOT STARTING")
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━")
    
    # Report data source status
    if OANDA_AVAILABLE:
        from oanda_client import check_connection
        if check_connection():
            log.info("✅ OANDA: broker-grade candles (primary for Forex)")
        else:
            log.warning("⚠️ OANDA: module found but connection failed — using yfinance fallback")
    else:
        log.info("ℹ️  OANDA: not available — using yfinance (set OANDA_API_TOKEN for better data)")

    # Init DB
    init_db()

    # Start BTC live WebSocket
    start_btc_websocket()

    # Run one immediate scan on startup
    run_full_scan()

    # Start hourly scheduler
    scheduler = start_scheduler()

    # Keep main thread alive
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        scheduler.shutdown()
        log.info("CRTSCAN stopped.")

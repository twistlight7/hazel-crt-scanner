#!/usr/bin/env python3
"""
Tier Tracker — Monitor A+/A/B tier distribution for first 24 hours

Logs tier distribution to /workspace/crtscan/tier_distribution.log
Alerts if >70% B-tier signals (indicates need for sweep quality filters)
"""

import os
import json
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path("/home/modtrader/.openclaw/workspace/crtscan/tier_distribution.log")
STATE_FILE = Path("/home/modtrader/.openclaw/workspace/crtscan/tier_state.json")

def load_state():
    """Load tracking state from file."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "start_time": datetime.now(timezone.utc).isoformat(),
        "total_signals": 0,
        "a_plus": 0,
        "a_tier": 0,
        "b_tier": 0,
    }

def save_state(state):
    """Save tracking state to file."""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def log_tier(quality_tier: str, pair: str, timeframe: str):
    """Log a signal's tier and update stats."""
    state = load_state()
    
    state["total_signals"] += 1
    if quality_tier == "A+":
        state["a_plus"] += 1
    elif quality_tier == "A":
        state["a_tier"] += 1
    else:  # B-tier
        state["b_tier"] += 1
    
    save_state(state)
    
    # Log to file
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with open(LOG_FILE, 'a') as f:
        f.write(f"{timestamp} | {pair} {timeframe} | Tier: {quality_tier}\n")
    
    # Check if >70% B-tier
    if state["total_signals"] >= 10:  # Need minimum sample size
        b_tier_pct = (state["b_tier"] / state["total_signals"]) * 100
        if b_tier_pct > 70:
            warning = f"\n⚠️ WARNING: {b_tier_pct:.1f}% B-tier signals (>{state['total_signals']} signals)\n"
            warning += f"Recommendation: Add sweep quality filters\n"
            with open(LOG_FILE, 'a') as f:
                f.write(warning)
            print(warning)
    
    return state

def get_summary():
    """Get tier distribution summary."""
    state = load_state()
    total = state["total_signals"]
    
    if total == 0:
        return "No signals tracked yet"
    
    a_plus_pct = (state["a_plus"] / total) * 100
    a_tier_pct = (state["a_tier"] / total) * 100
    b_tier_pct = (state["b_tier"] / total) * 100
    
    summary = f"""
╔════════════════════════════════════════════════╗
║  TIER DISTRIBUTION (Last 24h)                 ║
╠════════════════════════════════════════════════╣
║  Total Signals: {total:<27}║
║                                                ║
║  A+ Tier: {state['a_plus']:<6} ({a_plus_pct:5.1f}%)                        ║
║  A  Tier: {state['a_tier']:<6} ({a_tier_pct:5.1f}%)                        ║
║  B  Tier: {state['b_tier']:<6} ({b_tier_pct:5.1f}%)                        ║
╠════════════════════════════════════════════════╣
║  A+/A Combined: {state['a_plus'] + state['a_tier']:<6} ({a_plus_pct + a_tier_pct:5.1f}%)                ║
╚════════════════════════════════════════════════╝
"""
    
    if b_tier_pct > 70:
        summary += "\n⚠️  WARNING: >70% B-tier — sweep quality filters needed!\n"
    elif b_tier_pct > 50:
        summary += "\n⚠️  CAUTION: >50% B-tier — monitor closely\n"
    else:
        summary += "\n✅ Tier distribution healthy\n"
    
    return summary

if __name__ == "__main__":
    print(get_summary())

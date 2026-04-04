#!/usr/bin/env python3
"""
generate_daily_report.py — Daily CRT Signal Performance Report Generator

Reads from ~/.crtscan/learning.db and generates comprehensive daily reports.
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = os.path.expanduser("~/.crtscan/learning.db")
REPORTS_DIR = Path("/home/modtrader/.openclaw/workspace/signals/daily_reports")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_daily_signals(date_str: str):
    """Get all signals for a specific date."""
    conn = get_db_connection()
    c = conn.cursor()
    
    start = f"{date_str}T00:00:00"
    end = f"{date_str}T23:59:59"
    
    c.execute("""
        SELECT * FROM signals
        WHERE detected_at >= ? AND detected_at <= ?
        ORDER BY detected_at DESC
    """, (start, end))
    
    signals = c.fetchall()
    conn.close()
    return signals

def calculate_stats(signals):
    """Calculate performance statistics."""
    total = len(signals)
    resolved = [s for s in signals if s['outcome'] in ('WIN', 'LOSS')]
    pending = [s for s in signals if s['outcome'] == 'PENDING']
    expired = [s for s in signals if s['outcome'] == 'EXPIRED']
    
    wins = [s for s in resolved if s['outcome'] == 'WIN']
    losses = [s for s in resolved if s['outcome'] == 'LOSS']
    
    win_rate = (len(wins) / len(resolved) * 100) if resolved else 0
    avg_rr = sum(s['rr_ratio'] or 0 for s in resolved) / len(resolved) if resolved else 0
    
    return {
        'total': total,
        'resolved': len(resolved),
        'pending': len(pending),
        'expired': len(expired),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': round(win_rate, 1),
        'avg_rr': round(avg_rr, 2),
    }

def get_pair_stats(signals):
    """Get statistics by pair."""
    pairs = {}
    for s in signals:
        pair = s['pair']
        if pair not in pairs:
            pairs[pair] = {'signals': 0, 'wins': 0, 'losses': 0, 'rr_sum': 0}
        
        pairs[pair]['signals'] += 1
        if s['outcome'] == 'WIN':
            pairs[pair]['wins'] += 1
            pairs[pair]['rr_sum'] += s['rr_ratio'] or 0
        elif s['outcome'] == 'LOSS':
            pairs[pair]['losses'] += 1
            pairs[pair]['rr_sum'] += s['rr_ratio'] or 0
    
    result = []
    for pair, stats in pairs.items():
        resolved = stats['wins'] + stats['losses']
        wr = (stats['wins'] / resolved * 100) if resolved else 0
        avg_rr = stats['rr_sum'] / resolved if resolved else 0
        result.append({
            'pair': pair,
            'signals': stats['signals'],
            'wins': stats['wins'],
            'losses': stats['losses'],
            'win_rate': round(wr, 1),
            'avg_rr': round(avg_rr, 2),
        })
    
    return sorted(result, key=lambda x: x['win_rate'], reverse=True)

def get_tf_stats(signals):
    """Get statistics by timeframe."""
    tfs = {}
    for s in signals:
        tf = s['timeframe']
        if tf not in tfs:
            tfs[tf] = {'signals': 0, 'wins': 0, 'losses': 0, 'rr_sum': 0}
        
        tfs[tf]['signals'] += 1
        if s['outcome'] == 'WIN':
            tfs[tf]['wins'] += 1
            tfs[tf]['rr_sum'] += s['rr_ratio'] or 0
        elif s['outcome'] == 'LOSS':
            tfs[tf]['losses'] += 1
            tfs[tf]['rr_sum'] += s['rr_ratio'] or 0
    
    result = []
    for tf, stats in tfs.items():
        resolved = stats['wins'] + stats['losses']
        wr = (stats['wins'] / resolved * 100) if resolved else 0
        avg_rr = stats['rr_sum'] / resolved if resolved else 0
        result.append({
            'timeframe': tf,
            'signals': stats['signals'],
            'wins': stats['wins'],
            'losses': stats['losses'],
            'win_rate': round(wr, 1),
            'avg_rr': round(avg_rr, 2),
        })
    
    return sorted(result, key=lambda x: x['win_rate'], reverse=True)

def categorize_loss(signal):
    """Categorize why a signal lost."""
    # Basic categorization based on signal data
    if signal['rr_ratio'] and signal['rr_ratio'] < 1.0:
        return "Low R:R setup"
    
    # Could be enhanced with more analysis
    return "Market moved against setup"

def generate_report(date_str: str = None):
    """Generate a daily report."""
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    signals = get_daily_signals(date_str)
    
    if not signals:
        print(f"No signals found for {date_str}")
        return None
    
    stats = calculate_stats(signals)
    pair_stats = get_pair_stats(signals)
    tf_stats = get_tf_stats(signals)
    
    # Build report
    template_path = REPORTS_DIR / "report_template.md"
    if template_path.exists():
        with open(template_path) as f:
            template = f.read()
    else:
        template = "# Daily Report\n\n{CONTENT}"
    
    # Build tables
    wins = [s for s in signals if s['outcome'] == 'WIN']
    losses = [s for s in signals if s['outcome'] == 'LOSS']
    pending = [s for s in signals if s['outcome'] == 'PENDING']
    
    win_table = ""
    for i, s in enumerate(wins, 1):
        win_table += f"| {i} | {s['pair']} | {s['timeframe']} | {s['signal_type']} | {s['entry_price']} | {s['tp_price']} | {s['sl_price']} | WIN | {s['rr_ratio']} | - |\n"
    
    loss_table = ""
    loss_reasons = {}
    for i, s in enumerate(losses, 1):
        reason = categorize_loss(s)
        loss_reasons[reason] = loss_reasons.get(reason, 0) + 1
        loss_table += f"| {i} | {s['pair']} | {s['timeframe']} | {s['signal_type']} | {s['entry_price']} | {s['sl_price']} | {s['tp_price']} | LOSS | {s['rr_ratio']} | {reason} |\n"
    
    pending_table = ""
    for i, s in enumerate(pending, 1):
        detected = datetime.fromisoformat(s['detected_at'])
        age = (datetime.now(timezone.utc) - detected.replace(tzinfo=timezone.utc)).total_seconds() / 3600
        pending_table += f"| {i} | {s['pair']} | {s['timeframe']} | {s['signal_type']} | {s['entry_price']} | {s['tp_price']} | {s['sl_price']} | {age:.1f}h | - |\n"
    
    pair_stats_table = ""
    for p in pair_stats:
        pair_stats_table += f"| {p['pair']} | {p['signals']} | {p['wins']} | {p['losses']} | {p['win_rate']}% | {p['avg_rr']}R |\n"
    
    tf_stats_table = ""
    for t in tf_stats:
        tf_stats_table += f"| {t['timeframe']} | {t['signals']} | {t['wins']} | {t['losses']} | {t['win_rate']}% | {t['avg_rr']}R |\n"
    
    loss_reasons_table = ""
    total_losses = len(losses)
    for reason, count in sorted(loss_reasons.items(), key=lambda x: x[1], reverse=True):
        pct = (count / total_losses * 100) if total_losses else 0
        loss_reasons_table += f"| {reason} | {count} | {pct:.1f}% |\n"
    
    # Fill template
    report = template.format(
        DATE=date_str,
        TIMESTAMP=datetime.now(timezone.utc).isoformat(),
        SESSION="UTC",
        TOTAL_SIGNALS=stats['total'],
        RESOLVED=stats['resolved'],
        PENDING=stats['pending'],
        WIN_RATE=stats['win_rate'],
        AVG_RR=stats['avg_rr'],
        BEST_PAIR=pair_stats[0]['pair'] if pair_stats else "N/A",
        WORST_PAIR=pair_stats[-1]['pair'] if pair_stats else "N/A",
        WIN_COUNT=len(wins),
        LOSS_COUNT=len(losses),
        PENDING_COUNT=len(pending),
        WIN_TABLE=win_table or "No wins today\n",
        LOSS_TABLE=loss_table or "No losses today\n",
        PENDING_TABLE=pending_table or "No pending signals\n",
        PAIR_STATS=pair_stats_table or "No data\n",
        TF_STATS=tf_stats_table or "No data\n",
        LOSS_REASONS=loss_reasons_table or "No losses to analyze\n",
        LOSS_ANALYSIS="Detailed loss analysis requires more data collection\n",
        WIN_ANALYSIS="Detailed win analysis requires more data collection\n",
        INSIGHT_1="Awaiting more signal data",
        INSIGHT_2="Continue monitoring",
        IMPROVEMENT_1="Track loss reasons more precisely",
        IMPROVEMENT_2="Add session-based analysis",
        OBSERVATION_1="Pattern recognition developing",
        OBSERVATION_2="Learning from outcomes",
        FOCUS_1="Monitor pending signals",
        FOCUS_2="Track win/loss patterns",
        FOCUS_3="Refine entry criteria based on results",
    )
    
    # Save report
    report_path = REPORTS_DIR / f"{date_str}.md"
    with open(report_path, 'w') as f:
        f.write(report)
    
    print(f"Report generated: {report_path}")
    return report_path

if __name__ == "__main__":
    import sys
    date = sys.argv[1] if len(sys.argv) > 1 else None
    generate_report(date)

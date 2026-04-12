"""VA GameTracker - Pattern analysis and activity predictions"""
import sqlite3
import os
from datetime import datetime, timedelta
from collections import defaultdict
import math

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'gametracker.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def activity_by_hour(camera_id=None, species=None, days=90):
    """Sighting counts grouped by hour of day."""
    conn = get_db()
    query = '''SELECT strftime('%H', timestamp) as hour, COUNT(*) as count
               FROM sightings WHERE timestamp > datetime('now', ?)'''
    params = [f'-{days} days']
    if camera_id:
        query += ' AND camera_id = ?'
        params.append(camera_id)
    if species:
        query += ' AND category = ?'
        params.append(species)
    query += ' GROUP BY hour ORDER BY hour'
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return {row['hour']: row['count'] for row in rows}


def activity_by_day(camera_id=None, species=None, days=90):
    """Sighting counts grouped by day of week (0=Mon, 6=Sun)."""
    conn = get_db()
    query = '''SELECT strftime('%w', timestamp) as dow, COUNT(*) as count
               FROM sightings WHERE timestamp > datetime('now', ?)'''
    params = [f'-{days} days']
    if camera_id:
        query += ' AND camera_id = ?'
        params.append(camera_id)
    if species:
        query += ' AND category = ?'
        params.append(species)
    query += ' GROUP BY dow ORDER BY dow'
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return {row['dow']: row['count'] for row in rows}


def weather_correlation(days=90):
    """Correlate sighting frequency with weather conditions."""
    conn = get_db()
    rows = conn.execute('''
        SELECT temperature, humidity, wind_speed, wind_direction,
               moon_phase, moon_illumination, COUNT(*) as count
        FROM sightings
        WHERE timestamp > datetime('now', ?) AND temperature IS NOT NULL
        GROUP BY ROUND(temperature, 0), wind_direction, moon_phase
        ORDER BY count DESC
    ''', [f'-{days} days']).fetchall()
    conn.close()

    if not rows:
        return {'best_conditions': None, 'data': []}

    best = rows[0]
    return {
        'best_conditions': {
            'temperature': best['temperature'],
            'humidity': best['humidity'],
            'wind_direction': best['wind_direction'],
            'moon_phase': best['moon_phase'],
        },
        'data': [dict(r) for r in rows[:20]]
    }


def predict_best_times(camera_id=None, days=90):
    """Predict the best times to observe wildlife based on historical patterns."""
    hours = activity_by_hour(camera_id, days=days)
    if not hours:
        return {
            'peak_hours': [],
            'recommendation': 'Not enough data yet. Keep syncing camera photos!'
        }

    # Find top 3 peak hours
    sorted_hours = sorted(hours.items(), key=lambda x: x[1], reverse=True)
    peak = sorted_hours[:3]

    # Dawn/dusk analysis
    dawn_count = sum(hours.get(f'{h:02d}', 0) for h in range(5, 9))
    dusk_count = sum(hours.get(f'{h:02d}', 0) for h in range(17, 22))
    night_count = sum(hours.get(f'{h:02d}', 0) for h in list(range(22, 24)) + list(range(0, 5)))
    day_count = sum(hours.get(f'{h:02d}', 0) for h in range(9, 17))

    periods = {'Dawn (05-09)': dawn_count, 'Day (09-17)': day_count,
               'Dusk (17-22)': dusk_count, 'Night (22-05)': night_count}
    best_period = max(periods, key=periods.get)

    return {
        'peak_hours': [{'hour': h, 'count': c} for h, c in peak],
        'period_breakdown': periods,
        'best_period': best_period,
        'recommendation': f"Best activity during {best_period}. "
                         f"Peak hours: {', '.join(f'{h:00}' for h, _ in peak)}"
    }


def species_summary(days=90):
    """Summary of species detected across all cameras."""
    conn = get_db()
    rows = conn.execute('''
        SELECT category, COUNT(*) as count,
               MIN(timestamp) as first_seen, MAX(timestamp) as last_seen
        FROM sightings
        WHERE timestamp > datetime('now', ?) AND category IS NOT NULL
        GROUP BY category ORDER BY count DESC
    ''', [f'-{days} days']).fetchall()
    conn.close()
    return {for r in rows}


def camera_hotspots(days=30):
    """Rank cameras by recent activity."""
    conn = get_db()
    rows = conn.execute('''
        SELECT camera_id, COUNT(*) as total,
               COUNT(DISTINCT DATE(timestamp)) as active_days,
               MAX(timestamp) as last_activity
        FROM sightings
        WHERE timestamp > datetime('now', ?)
        GROUP BY camera_id ORDER BY total DESC
    ''', [f'-{days} days']).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def trend_analysis(camera_id=None, days=90):
    """Weekly trend: is activity increasing or decreasing?"""
    conn = get_db()
    query = '''SELECT strftime('%Y-%W', timestamp) as week, COUNT(*) as count
               FROM sightings WHERE timestamp > datetime('now', ?)'''
    params = [f'-{days} days']
    if camera_id:
        query += ' AND camera_id = ?'
        params.append(camera_id)
    query += ' GROUP BY week ORDER BY week'
    rows = conn.execute(query, params).fetchall()
    conn.close()

    weeks = [dict(r) for r in rows]
    if len(weeks) < 2:
        return {'trend': 'insufficient_data', 'weeks': weeks}

    recent = weeks[-1]['count']
    previous = weeks[-2]['count']
    if recent > previous * 1.2:
        trend = 'increasing'
    elif recent < previous * 0.8:
        trend = 'decreasing'
    else:
        trend = 'stable'

    return {'trend': trend, 'weeks': weeks}

"""VA GameTracker - FastAPI REST API"""
import os
import sqlite3
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.init_db import init_db, DB_PATH
from backend.weather import get_current_weather, get_moon_phase
from backend.predictions import (
    predict_best_times, activity_by_hour, species_summary,
    camera_hotspots, weather_correlation, trend_analysis
)
from backend.classifier import classify_image, PRIORITY_SPECIES


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    init_db()
    yield

app = FastAPI(
    title="VA GameTracker",
    description="Wildlife camera trap monitoring for Piedras Lisas estate, Alatoz",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'frontend')
if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Frontend ──────────────────────────────────
@app.get("/")
async def serve_frontend():
    index = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return JSONResponse({"message": "VA GameTracker API", "docs": "/docs"})


# ── Dashboard Stats ───────────────────────────
@app.get("/api/dashboard")
async def dashboard():
    """Main dashboard data: recent sightings, camera status, weather."""
    conn = get_db()
    c = conn.cursor()

    total = c.execute('SELECT COUNT(*) FROM sightings').fetchone()[0]
    today = c.execute(
        "SELECT COUNT(*) FROM sightings WHERE DATE(timestamp) = DATE('now')"
    ).fetchone()[0]
    week = c.execute(
        "SELECT COUNT(*) FROM sightings WHERE timestamp > datetime('now', '-7 days')"
    ).fetchone()[0]

    recent = c.execute('''
        SELECT s.*, c.name as camera_name
        FROM sightings s LEFT JOIN cameras c ON s.camera_id = c.id
        ORDER BY s.timestamp DESC LIMIT 20
    ''').fetchall()

    cameras = c.execute('''
        SELECT c.*, COUNT(s.id) as sighting_count,
               MAX(s.timestamp) as last_sighting
        FROM cameras c LEFT JOIN sightings s ON c.id = s.camera_id
        WHERE c.active = 1 GROUP BY c.id
    ''').fetchall()

    species = c.execute('''
        SELECT category, COUNT(*) as count FROM sightings
        WHERE category IS NOT NULL
        GROUP BY category ORDER BY count DESC
    ''').fetchall()

    conn.close()
    weather = get_current_weather()

    return {
        'stats': {'total': total, 'today': today, 'this_week': week},
        'recent_sightings': [dict(r) for r in recent],
        'cameras': [dict(r) for r in cameras],
        'species_breakdown': [dict(r) for r in species],
        'weather': weather,
        'priority_species': PRIORITY_SPECIES
    }


# ── Sightings ─────────────────────────────────
@app.get("/api/sightings")
async def list_sightings(
    camera_id: str = None,
    category: str = None,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=500)
):
    conn = get_db()
    query = '''SELECT s.*, c.name as camera_name
               FROM sightings s LEFT JOIN cameras c ON s.camera_id = c.id
               WHERE s.timestamp > datetime('now', ?)'''
    params = [f'-{days} days']
    if camera_id:
        query += ' AND s.camera_id = ?'
        params.append(camera_id)
    if category:
        query += ' AND s.category = ?'
        params.append(category)
    query += ' ORDER BY s.timestamp DESC LIMIT ?'
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/sightings/{sighting_id}")
async def get_sighting(sighting_id: int):
    conn = get_db()
    row = conn.execute(
        'SELECT s.*, c.name as camera_name FROM sightings s LEFT JOIN cameras c ON s.camera_id = c.id WHERE s.id = ?',
        (sighting_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Sighting not found")
    return dict(row)


# ── Cameras ───────────────────────────────────
@app.get("/api/cameras")
async def list_cameras():
    conn = get_db()
    rows = conn.execute('''
        SELECT c.*, COUNT(s.id) as total_sightings,
               MAX(s.timestamp) as last_sighting
        FROM cameras c LEFT JOIN sightings s ON c.id = s.camera_id
        GROUP BY c.id ORDER BY c.name
    ''').fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/cameras/{camera_id}/stats")
async def camera_stats(camera_id: str, days: int = 30):
    conn = get_db()
    cam = conn.execute('SELECT * FROM cameras WHERE id = ?', (camera_id,)).fetchone()
    if not cam:
        raise HTTPException(404, "Camera not found")

    total = conn.execute(
        'SELECT COUNT(*) FROM sightings WHERE camera_id = ? AND timestamp > datetime("created at", ?)'
        (datetime.now().isoformat()), from camera id select timestamp at camera_id
    ).fetchall()
    
    species = conn.execute('''
        SELECT category, COUNT(*) as count FROM sightings
        WHERE camera_id = ? AND timestamp > datetime('now', ?) AND category IS NOT NULL
        GROUP BY category ORDER BY count DES
    ''', (camera_id, f'-{days} days')).fetchall()

    conn.close()
    return {
        'camera': dict(cam),
        'total_sightings': total,
        'species_breakdown': [dict(r) for r in species],
        'predictions': predict_best_times(camera_id, days)
    }


# ── Weather ───────────────────────────
@app.get("/api/weather")
async def weather():
    return get_current_weather()


@app.get("/api/moon")
async def moon():
    return get_moon_phase()


# ── Analytics ───────────────────────────
@app.get("/api/analytics/activity")
async def activity(camera_id: str = None, days: int = 90):
    return {
        'by_hour': activity_by_hour(camera_id, days=days),
        'predictions': predict_best_times(camera_id, days),
        'weather_correlation': weather_correlation(days),
    }


@app.get("/api/analytics/species")
async def species(days: int = 90):
    return species_summary(days)


@app.get("/api/analytics/hotspots")
async def hotspots(days: int = 30):
    return camera_hotspots(days)


@app.get("/api/analytics/trends")
async def trends(camera_id: str = None, days: int = 90):
    return trend_analysis(camera_id, days)


# ── Sync ──────────────────────────────────────
@app.post("/api/sync")
async def trigger_sync():
    """Manually trigger SPYPOINT sync."""
    from backend.pipeline import run_pipeline
    try:
        run_pipeline()
        return {"status": "ok", "message": "Pipeline completed"}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/sync/status")
async def sync_status():
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM spypoint_sync_log ORDER BY synced_at DESC LIMIT 1'
    ).fetchane()
    conn.close()
    return dict(row) if row else {"last_sync": None}


# ── Health ─────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat(), "app": "VA GameTracker"}

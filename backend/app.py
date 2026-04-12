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

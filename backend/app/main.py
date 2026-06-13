"""FastAPI application entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_admin,
    routes_analytics,
    routes_auth,
    routes_cameras,
    routes_estate,
    routes_forecast,
    routes_health,
    routes_images,
)
from app.core.config import settings
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(title="GameSense API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api"
app.include_router(routes_health.router, prefix=API_PREFIX)
app.include_router(routes_auth.router, prefix=API_PREFIX)
app.include_router(routes_cameras.router, prefix=API_PREFIX)
app.include_router(routes_images.router, prefix=API_PREFIX)
app.include_router(routes_analytics.router, prefix=API_PREFIX)
app.include_router(routes_forecast.router, prefix=API_PREFIX)
app.include_router(routes_estate.router, prefix=API_PREFIX)
app.include_router(routes_admin.router, prefix=API_PREFIX)

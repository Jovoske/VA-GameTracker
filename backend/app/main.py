"""FastAPI application entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_admin,
    routes_alerts,
    routes_analytics,
    routes_animals,
    routes_auth,
    routes_camera_accounts,
    routes_cameras,
    routes_client_errors,
    routes_estate,
    routes_forecast,
    routes_harvests,
    routes_health,
    routes_images,
    routes_insights,
    routes_map,
    routes_notes,
    routes_notifications,
    routes_photos,
    routes_species,
    routes_stands,
    routes_users,
    routes_zones,
)
from app.core.config import settings
from app.core.logging import configure_logging
from app.version import __version__

configure_logging()

# The interactive docs are a map of every endpoint, admin ones included: off on the
# public address unless ENABLE_API_DOCS is set (audit K-12).
_docs = settings.enable_api_docs
app = FastAPI(
    title="GameSense API", version=__version__,
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)

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
app.include_router(routes_alerts.router, prefix=API_PREFIX)
app.include_router(routes_forecast.router, prefix=API_PREFIX)
app.include_router(routes_insights.router, prefix=API_PREFIX)
app.include_router(routes_estate.router, prefix=API_PREFIX)
app.include_router(routes_animals.router, prefix=API_PREFIX)
app.include_router(routes_admin.router, prefix=API_PREFIX)
app.include_router(routes_species.router, prefix=API_PREFIX)
app.include_router(routes_users.router, prefix=API_PREFIX)
app.include_router(routes_stands.router, prefix=API_PREFIX)
app.include_router(routes_camera_accounts.router, prefix=API_PREFIX)
app.include_router(routes_zones.router, prefix=API_PREFIX)
app.include_router(routes_notifications.router, prefix=API_PREFIX)
app.include_router(routes_photos.router, prefix=API_PREFIX)
app.include_router(routes_map.router, prefix=API_PREFIX)
app.include_router(routes_notes.router, prefix=API_PREFIX)
app.include_router(routes_client_errors.router, prefix=API_PREFIX)
app.include_router(routes_harvests.router, prefix=API_PREFIX)

import mimetypes
import os

from app.frontend import mount_frontend

# Windows has no registry entry for these, so Starlette guessed text/plain and
# served the app's own typeface as if it were a text file. Browsers do not
# MIME-check @font-face so it still rendered, but anything stricter in front of
# this (a proxy, a CDN, a future Safari) is entitled to refuse it.
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("application/manifest+json", ".webmanifest")

mount_frontend(app, os.environ.get("FRONTEND_DIST", ""))

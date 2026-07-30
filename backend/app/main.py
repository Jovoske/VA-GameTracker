"""FastAPI application entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_admin,
    routes_spypoint_accounts,
    routes_stands,
    routes_users,
    routes_alerts,
    routes_analytics,
    routes_animals,
    routes_auth,
    routes_cameras,
    routes_estate,
    routes_forecast,
    routes_health,
    routes_images,
    routes_insights,
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
app.include_router(routes_alerts.router, prefix=API_PREFIX)
app.include_router(routes_forecast.router, prefix=API_PREFIX)
app.include_router(routes_insights.router, prefix=API_PREFIX)
app.include_router(routes_estate.router, prefix=API_PREFIX)
app.include_router(routes_animals.router, prefix=API_PREFIX)
app.include_router(routes_admin.router, prefix=API_PREFIX)
app.include_router(routes_users.router, prefix=API_PREFIX)
app.include_router(routes_spypoint_accounts.router, prefix=API_PREFIX)
app.include_router(routes_stands.router, prefix=API_PREFIX)

import os
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

_DIST = os.environ.get("FRONTEND_DIST", "")
if _DIST and os.path.isdir(_DIST):
    _assets = os.path.join(_DIST, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    _DIST_REAL = os.path.realpath(_DIST)

    @app.get("/{full_path:path}")
    def _spa(full_path: str):
        # os.path.join() happily walks out of the directory: a request for
        # ..%2f..%2fetc/passwd resolved to a real file and was served. Resolve the
        # candidate and confirm it is still inside the dist root before returning it.
        candidate = os.path.realpath(os.path.join(_DIST_REAL, full_path))
        inside = candidate == _DIST_REAL or candidate.startswith(_DIST_REAL + os.sep)
        if full_path and inside and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_DIST_REAL, "index.html"))

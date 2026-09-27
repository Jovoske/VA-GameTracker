"""Serving the built app (frontend/dist) from the API process, as Db01 does.

Three rules keep an installed app from going blank after a deploy:

* ``index.html``, ``sw.js`` and the manifest are sent with ``Cache-Control:
  no-cache``. Without it a browser keeps index.html by heuristic (a tenth of its
  age), asks for a bundle the deploy just deleted, and paints nothing.
* ``/assets/*`` are content-hashed, so they are cached for a year and never asked
  for again. That also keeps the app's own code on the phone for the next launch.
* An unknown ``/api/...`` path is a JSON 404, never the app's HTML with a 200.
  An old screen calling an endpoint that moved then says "not found" instead of
  "Unexpected token '<'".
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, JSONResponse

FRESH = "no-cache"
FOREVER = "public, max-age=31536000, immutable"
# Files the browser must re-check every time: the shell, the worker, the manifest.
_ALWAYS_CHECK = {"index.html", "sw.js", "manifest.webmanifest"}


class _HashedAssets(StaticFiles):
    """StaticFiles for content-hashed names: cached for good once fetched."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if resp.status_code == 200:
            resp.headers["Cache-Control"] = FOREVER
        return resp


def mount_frontend(app: FastAPI, dist: str) -> None:
    """Serve `dist` at /, with the app shell as the fallback for client routes."""
    if not dist or not os.path.isdir(dist):
        return
    assets = os.path.join(dist, "assets")
    if os.path.isdir(assets):
        app.mount("/assets", _HashedAssets(directory=assets), name="assets")
    root = os.path.realpath(dist)

    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        # os.path.join() happily walks out of the directory: a request for
        # ..%2f..%2fetc/passwd resolved to a real file and was served. Resolve the
        # candidate and confirm it is still inside the dist root.
        candidate = os.path.realpath(os.path.join(root, full_path))
        inside = candidate == root or candidate.startswith(root + os.sep)
        if full_path and inside and os.path.isfile(candidate):
            name = os.path.basename(candidate)
            headers = {"Cache-Control": FRESH} if name in _ALWAYS_CHECK else None
            return FileResponse(candidate, headers=headers)
        return FileResponse(os.path.join(root, "index.html"), headers={"Cache-Control": FRESH})

"""Native (no-Docker) service entrypoint.

Docker's compose loaded .env into the container environment; there is no such step in
the native Windows build. pydantic-settings reads .env for its own fields, but it does
NOT populate os.environ — so values read directly from the environment (FRONTEND_DIST in
app.main, ANTHROPIC_API_KEY in the Anthropic SDK) would be missing. This entrypoint loads
.env into os.environ first, then starts uvicorn, so every consumer sees the same config.
"""
import os
from pathlib import Path

_env = Path(__file__).with_name(".env")
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _key, _val = _line.split("=", 1)
        os.environ.setdefault(_key.strip(), _val.strip())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.environ.get("API_HOST", "0.0.0.0"),
        port=int(os.environ.get("API_PORT", "8090")),
        log_level="info",
    )

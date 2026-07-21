# Deliverable 9 — Deployment Strategy

The portability test: **the same artifacts run on the Windows laptop (Phase 1) and a Linux server (Phase 2) with only env vars and volume paths changing.** No code changes to migrate.

## Phase 1 — Local (Windows laptop)

### Path A — Docker (recommended, matches spec)
- `compose.yaml` defines `postgres` (PostGIS+pgvector image), `redis`, `api`, `worker`, `beat`, `frontend`.
- `docker compose up` → migrations + seed run automatically (entrypoint), app reachable at `http://localhost:8080`.
- Windows wrapper: `start.bat` (and a `make dev` equivalent) so it's genuinely one command.
- **Requires installing Docker Desktop** (not currently on this machine).

### Path B — Native (no Docker)
- `start.bat` launches: local **PostgreSQL** (installer or portable) with PostGIS/pgvector, **Redis** (Memurai or WSL), `uvicorn` for the API, a Celery `worker` + `beat`, and Vite for the frontend.
- More moving parts to install, but zero Docker dependency. We keep `compose.yaml` for the server regardless.

### Path C — Lite (fastest smoke test)
- A reduced profile (SQLite + in-process scheduler + filesystem media, AI optional) purely to click around the UI without standing up the full stack. Not for real use — escape hatch for "does it run at all."

> **Decision: Path A (Docker Desktop).** It's the spec's intent and makes Phase 2 a non-event. Paths B and C remain documented as fallbacks but are not the primary route.

### The disk constraint (decision: server-only retention)
C: has **~24 GB free**, so 12 months of originals can't live on the laptop. Resolved approach:
- **Laptop = dev/test:** keep only a recent rolling window of images (`MEDIA_RETENTION_DAYS`, small default); a scheduled prune job enforces it. Detection + `env_snapshots` rows are kept forever regardless.
- **Phase-2 server = the archive:** `MEDIA_RETENTION_DAYS ≥ 365` on a big disk.
- The media path is a single config value, so relocating it (other drive / server volume) is a setting, not a code change.
- Mind Docker's own footprint (Postgres + a torch/onnx image want several GB); relocate Docker Desktop's data root off C: if it gets tight.

## Phase 2 — Server (Linux VPS / dedicated / home server)

> **Implemented:** `compose.prod.yaml` + `.env.production.example` + the step-by-step
> runbook in [`10-db01-deploy.md`](10-db01-deploy.md) (target server: **Db01**).

- **Same `compose.yaml`.** Differences are external: a `.env.production`, real volume mounts (big disk for media, separate for Postgres), and a front edge.
- Add **Caddy** (or nginx) reverse proxy with automatic TLS; expose only 80/443.
- **Backups:** nightly `pg_dump` + media `rsync`/snapshot to a second location; documented restore.
- **Resourcing:** if the server has a GPU, the AI worker uses it automatically (CUDA) — same code, faster; otherwise CPU as on the laptop.
- Migration procedure: `git pull` → `docker compose pull/up -d` → migrations auto-run → healthcheck. (This is exactly what the self-update panel automates — see `08-git-update.md`.)

## Cross-cutting

- **Config:** `pydantic-settings` from `.env`; secrets never committed (`.env` gitignored, `.env.example` documents keys).
- **Observability:** structured JSON logging to stdout (+ rotating file); `/api/health` (liveness) and `/api/ready` (DB+Redis reachable) endpoints; per-service healthchecks in compose.
- **CI (added early):** GitHub Actions runs ruff + mypy + pytest (backend) and tsc + eslint + vitest (frontend) on every push; build the images to catch Dockerfile drift.
- **Decoupling from Render:** the legacy `render.yaml` is kept only as a reference; nothing Render-specific (port 10000, ephemeral disk assumptions) leaks into the new code. Render remains a valid *optional* host because the app is just standard containers.

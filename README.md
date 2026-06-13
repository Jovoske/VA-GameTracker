# GameSense

**Turn your trail cameras into a hunting forecast.**

A local-first wildlife-intelligence platform: it ingests SPYPOINT camera images, identifies and
profiles European game with AI, correlates sightings with weather / moon / solar / wind, and
produces plain-language recommendations — where to sit tonight, when, for what, and which stands to
avoid. The product is the **Tonight card** and the **Map**, not a photo gallery.

> Built for the Piedras Lisas estate (Alatoz, Spain). European wildlife only.

---

## Quick start (Docker)

1. **Install Docker Desktop** (one time): https://www.docker.com/products/docker-desktop/
2. From this folder, run:

   ```bat
   start.bat
   ```

   (or `docker compose up --build`). This brings up Postgres (PostGIS + pgvector), Redis, the API,
   a background worker, the scheduler, and the frontend, runs migrations, and seeds an admin user.

3. Open **http://localhost:8080** and sign in with the credentials from `.env`
   (`ADMIN_EMAIL` / `ADMIN_PASSWORD`, default `admin@gamesense.local` / `changeme`).

The API is at **http://localhost:8000** (interactive docs at `/docs`).

Edit `.env` (created from `.env.example` on first run) to set your SPYPOINT credentials and secrets.

---

## What works today (Milestone 0)

A runnable foundation:

- One-command Docker startup; six services wired together with health checks.
- PostgreSQL + PostGIS + pgvector schema (full model) via Alembic migrations.
- FastAPI backend with secure login (Argon2 + JWT), health/readiness probes, structured logging.
- Celery worker + beat scheduler (SPYPOINT sync is a heartbeat until M1).
- React + TypeScript frontend shell: login + an honest "still learning" Tonight placeholder.

See [`docs/`](docs/00-overview.md) for the full design (audit, architecture, schema, SPYPOINT,
AI pipeline, forecasting, deployment, Git self-update). Build order and roadmap are in
[`docs/00-overview.md`](docs/00-overview.md).

---

## Project layout

```
backend/     FastAPI app, SQLAlchemy models, Alembic, Celery tasks, tests
frontend/    React + TypeScript (Vite), MapLibre to come in M1/M3
docker/      service Dockerfiles (custom Postgres with PostGIS + pgvector)
docs/        design & decision documents (the pre-build deliverables)
compose.yaml one-command local stack
start.bat    Windows launcher
```

## Local development notes

- **Backend tests:** `cd backend && pip install -r requirements-dev.txt && python -m pytest`
- **Frontend typecheck/build:** `cd frontend && npm install && npm run build`
- **Migrations:** generated against the running Postgres — `alembic revision --autogenerate -m "..."`.
- Secrets live in `.env` (gitignored). Never commit real credentials.

## Roadmap

- **M1** — real SPYPOINT sync (image download, battery/signal, pagination) + correct weather/moon/solar enrichment.
- **M2** — AI: MegaDetector + DeepFaune (European), bounding boxes, annotated images.
- **M3** — the Tonight card: per-stand forecast, wind-safe analysis, GO/MARGINAL/SKIP with reasons.
- **Tier 2+** — individual re-ID, movement inference, correlations, alerts, Git self-update panel.

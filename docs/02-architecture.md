# Deliverable 3 — Recommended Architecture

## 1. Principles

- **Local-first.** Everything runs on the laptop with no cloud dependency except free data APIs (weather). The user's images stay on the user's machine — a stated differentiator.
- **Insight over data.** The architecture exists to feed two screens: the **Tonight card** and the **Map**. Every module earns its place by improving a decision.
- **Portable by construction.** The same artifacts run on the Windows laptop (Phase 1) and a Linux server (Phase 2) with only env vars and volume paths changing. No code changes to migrate — that's the acceptance test.
- **Honest by default.** Confidence travels with every inference, end to end, into the UI. Never assert certainty.

## 2. Service topology

```
┌──────────────────────────────────────────────────────────────────┐
│  docker compose  (or native processes on Windows)                  │
│                                                                    │
│  ┌────────────┐   ┌──────────────┐   ┌───────────────────────┐    │
│  │ frontend   │   │ api          │   │ worker (Celery)        │    │
│  │ React/TS   │──►│ FastAPI      │◄─►│  - spypoint.sync       │    │
│  │ MapLibre   │   │  - auth      │   │  - ai.infer            │    │
│  │ (Vite)     │   │  - REST      │   │  - enrich.env          │    │
│  └────────────┘   │  - serves    │   │  - forecast.nightly    │    │
│                   │    /api      │   └───────────┬───────────┘    │
│                   └──────┬───────┘               │                 │
│         ┌────────────────┼───────────────────────┤                 │
│         ▼                ▼                        ▼                 │
│  ┌────────────┐  ┌──────────────┐        ┌──────────────┐         │
│  │ PostgreSQL │  │ Redis        │        │ beat         │         │
│  │ +PostGIS   │  │ broker+cache │        │ (scheduler)  │         │
│  │ +pgvector  │  └──────────────┘        └──────────────┘         │
│  └────────────┘                                                    │
│         ▼ (volume)                                                  │
│  ┌────────────────────────────┐    ┌────────────────────────────┐ │
│  │ media/  originals+annotated │    │ models/  AI weights cache  │ │
│  └────────────────────────────┘    └────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
            ▲                         ▲
      SPYPOINT REST            Open-Meteo (weather/archive)
```

Six logical services: **frontend, api, worker, beat (scheduler), postgres, redis.** Media and model weights are volumes. On Windows without Docker, the same six run as native processes via `start.bat` (uvicorn, a Celery worker+beat, and a local Postgres/Redis — or SQLite/in-process fallback for the lightest dev path; see `07-deployment.md`).

## 3. Backend module layout (FastAPI, modular)

```
backend/
  core/          config (pydantic-settings), logging, security/auth, db session, storage interface
  models/        SQLAlchemy ORM models  (1:1 with 03-database-schema.md)
  schemas/       Pydantic request/response DTOs
  api/           routers: auth, cameras, sightings, animals, forecast, map, insights, admin
  ingestion/     spypoint client + sync orchestration (ports the kept logic)
  enrichment/    weather, moon, solar providers + per-sighting enrichment
  ai/            detector (MegaDetector), classifier (DeepFaune), attributes, reid, annotate
  forecasting/   feature builder, model train/predict, wind-safe, recommendation engine
  tasks/         celery app + task definitions + beat schedule
  alembic/       migrations
  tests/         ingestion, forecasting, reid (the risky bits) — per spec
```

Dependency rule: `api` and `tasks` depend on domain modules (`ingestion`, `ai`, …); domain modules depend on `core` and `models`; nothing depends back up. Keeps the graph acyclic and testable.

## 4. Frontend (React + TypeScript)

- **Build:** Vite. **Routing:** React Router. **Server state:** TanStack Query (cache + polling). **Maps:** MapLibre GL (no token cost) with a wind-particle velocity layer. **Charts:** a lightweight lib (Recharts/visx). **Styling:** CSS variables + a small token system (design tokens below); component primitives kept minimal and bespoke for the field-instrument look.
- **Screens** (one per job, per spec §2): `Tonight` (home), `Map`, `Cameras`, `Animals`, `Forecast`, `Insights`, `Settings/Admin`.
- **Design tokens** (carry the spec's identity into code):

```css
--bg:#0E1311; --surface:#161D1A; --surface-2:#1E2723;
--go:#3FB950; --marginal:#E3A008; --skip:#E5534B;
--accent-teal:#3FB9B0; --accent-sand:#D9B370;
--text:#E6EDEA; --text-dim:#8A9A92; --border:#26322D;
--radius:14px; --font:Inter, system-ui, sans-serif; /* tabular figures for all numbers */
```

Dark-first, high-contrast, mobile-first, thumb-reachable primary actions, a "field mode" contrast boost. Confidence is always a labeled bar/ring, never bare text.

## 5. Data flow (one sighting, end to end)

1. **beat** fires `spypoint.sync` every N minutes (default 15).
2. **worker** authenticates, pages new photos per camera, **downloads originals** to `media/<estate>/<camera>/<date>/`, writes `cameras.battery/signal/last_sync`, inserts `images` rows (deduped by `file_hash` + `spypoint_photo_id`).
3. On new image, worker enqueues `enrich.env` (attach weather **at captured_at** via Open-Meteo archive/forecast, moon, solar) and `ai.infer`.
4. **ai.infer**: MegaDetector finds animal boxes → crops → DeepFaune classifies species → attribute heads estimate sex/age/group (low-confidence, honest) → re-ID embedding stored in pgvector → annotated image written. Empty-frame triggers flagged early and skipped.
5. Nightly, **forecast.nightly** rebuilds per-stand/species models and writes `forecasts` + refreshes `correlations`.
6. The **Tonight card** reads the latest forecast + tonight's weather/moon/solar + wind-safe analysis and renders GO/MARGINAL/SKIP with reasons.

## 6. Technology choices (confirmed vs. spec)

| Layer | Choice | Rationale |
|---|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic | Spec; async, typed, auto-docs. |
| DB | PostgreSQL 16 + PostGIS + pgvector | Spatial (movement/proximity) + embedding search (re-ID) without reinventing them. |
| Jobs | Celery + Redis (RQ fallback) | Scheduled sync, async inference, nightly forecasts. |
| AI | PyTorch (CPU), ONNX Runtime for speed | MegaDetector + DeepFaune; European-only weights. CPU-only on this laptop. |
| Frontend | React + TS + Vite + MapLibre GL | Spec; open mapping, no token. |
| Weather | Open-Meteo (forecast + archive) | Free, no key, already proven in the repo. |
| Auth | JWT session, Argon2 password hash | Secure local login; admin role gates the update panel. |
| Storage | Local FS behind a `Storage` interface | S3/MinIO becomes a config swap later. |

## 7. Repository & Git strategy

- This working directory becomes the new project root and Git repo (the source of truth). Proposed structure: `backend/`, `frontend/`, `docs/`, `docker/`, `scripts/`, `compose.yaml`, `README.md`.
- **Branching:** `main` (always runnable) + short-lived feature branches per milestone; tag releases `v0.1.0`, `v0.2.0` … so the self-update/rollback panel has clean targets.
- **Existing GitHub repo:** three options to decide at kickoff — (a) push the rebuild onto `Jovoske/VA-GameTracker` `main` preserving history via a fresh commit, (b) a `v2` branch for side-by-side, or (c) a new repo. Recommended: **(a)** — keep one home, tag the current state `v1-legacy` first so nothing is lost.
- Every milestone is committed; conventional-commit messages; CI later runs lint + type-check + tests.

## 8. Non-functional targets (from spec §12)

Tonight-card load < 1 s on mobile · first useful screen < 5 min after onboarding · sync success > 99% · forecast calibration surfaced to the user after ~30 nights · full type safety (mypy + TS strict) · structured logging · graceful, user-friendly errors.

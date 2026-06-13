# GameSense — Pre-Build Deliverables & Decision Package

> **Status:** Awaiting approval. No application code has been written yet.
> This package is the gate the spec requires ("Only after approval should implementation begin").
> Prepared 2026-06-13 against `Jovoske/VA-GameTracker` @ `e5b0286` (latest commit 2026-04-13).

---

## 1. What this package contains

The spec asked for ten deliverables before coding. Here they are, mapped to documents:

| # | Deliverable | Document |
|---|---|---|
| 1 | Full repository audit | [`01-audit.md`](01-audit.md) |
| 2 | Existing architecture review | [`01-audit.md`](01-audit.md) |
| 3 | Recommended architecture | [`02-architecture.md`](02-architecture.md) |
| 4 | Database schema | [`03-database-schema.md`](03-database-schema.md) |
| 5 | SPYPOINT integration plan | [`04-spypoint-integration.md`](04-spypoint-integration.md) |
| 6 | AI pipeline design | [`05-ai-pipeline.md`](05-ai-pipeline.md) |
| 7 | Forecasting architecture | [`06-forecasting.md`](06-forecasting.md) |
| 8 | UI/UX mockup | Tonight-card mockup (rendered in chat) + [`02-architecture.md`](02-architecture.md) §UI |
| 9 | Deployment strategy | [`07-deployment.md`](07-deployment.md) |
| 10 | Git update strategy | [`08-git-update.md`](08-git-update.md) |

---

## 2. Audit verdict in one paragraph

The existing repo is a competent **proof-of-concept**, not a production base. It is ~37 KB of Python (7 files) plus a single 15 KB HTML dashboard, built to run on Render's free tier. The genuinely valuable, hard-won asset is the **SPYPOINT authentication and photo-fetch logic** — we keep that. The **Open-Meteo weather integration** and **moon-phase math** are also reusable. Almost everything else is reshaped: SQLite → PostgreSQL/PostGIS/pgvector, single-file HTML → React/TypeScript, generic ImageNet-API classification → local European wildlife models, and a synchronous manual pipeline → a scheduled background-job system. Two defects in the current code would, if carried forward, quietly invalidate the whole product premise — see the two red flags below.

## 3. Two defects you should know about immediately

1. **Weather is recorded wrong.** Every sighting is tagged with the weather *at the moment it was processed*, not the weather *when the animal walked past the camera*. (`weather.py:111` calls `get_current_weather()` and ignores the photo timestamp; the working `get_historical_weather()` is never called.) The entire correlation/forecasting value proposition depends on accurate per-sighting environmental data, so this is not cosmetic — it silently poisons the dataset. Fixed in the new design.
2. **Images are never stored.** Despite a "store ≥12 months" requirement, the current sync saves only the SPYPOINT CDN **URL**, not the image (`spypoint_sync.py:150`, comment "don't download — ephemeral storage"). Those URLs expire, after which the photo is gone. Effective retention today is ~zero. The new design downloads and persists originals + annotated copies.

## 4. Environment findings (this laptop)

Probed on the target Windows 11 machine:

| Resource | Finding | Implication |
|---|---|---|
| GPU | Intel Iris Xe only (no NVIDIA/CUDA) | AI inference runs **CPU-only**. Fine for a handful of cameras on a 15-min cadence; must be async + queued, never in the request path. |
| CPU / RAM | i7-1355U (10C/12T), 31.6 GB RAM | Plenty for Postgres + Redis + CPU inference. |
| Disk (C:) | **24 GB free** of 476 GB | **12 months of original images will not fit on C:.** Needs a decision (see below). |
| Docker | **Not installed** | The spec's "one-command Docker startup" requires installing Docker Desktop, or we provide a native fallback. Decision below. |
| Tooling present | git, Node 24, Python 3.12, npm | Native dev path is viable if we don't go Docker-first. |

## 5. Decisions (resolved 2026-06-13)

1. **Local stack → Docker Desktop.** `docker compose up` is the one-command start; Phase-2 Linux migration becomes a non-event. Requires a one-time Docker Desktop install on the laptop.
2. **AI model → MegaDetector v5 (detection) + DeepFaune (European species classifier).** Both open, free, European-focused, CPU-runnable. See `05-ai-pipeline.md`.
3. **Image retention → server-only.** The laptop keeps a recent rolling window only (configurable `MEDIA_RETENTION_DAYS`, small default); the full ≥12-month archive lives on the Phase-2 server. Detection + environment rows are kept forever everywhere (we lose pixels, never the signal). This sidesteps the 24 GB free-disk limit.

## 6. Recommended build sequence (after approval)

Following the spec's own guidance — "ship Tier 0 + a working Tonight card before touching individual recognition or animated wind."

1. **Milestone 0 — Skeleton up.** Repo restructure, Docker Compose (or native scripts), Postgres schema + migrations, FastAPI app, React shell, auth, health checks. One-command start works.
2. **Milestone 1 — Data flowing.** SPYPOINT client (with real image download, battery/signal, pagination), scheduled sync, weather/moon/solar enrichment done *correctly*, Cameras screen showing real photos.
3. **Milestone 2 — AI online.** MegaDetector + DeepFaune inference worker, detections with bounding boxes + confidence, annotated images, species on the dashboard.
4. **Milestone 3 — The Tonight card.** Per-stand forecast model, wind-safe analysis, the GO/MARGINAL/SKIP card with "why," empty/learning state.
5. **Then Tier 2+** — individual re-ID, movement inference, correlations-as-sentences, multi-day forecasts, alerts.

Each milestone is independently demoable and committed to Git.

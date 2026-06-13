# Deliverables 1 & 2 — Repository Audit & Existing Architecture Review

Audited `Jovoske/VA-GameTracker` @ `e5b0286`. The entire application:

```
backend/
  app.py            (8.4 KB)  FastAPI app: ~15 REST endpoints, serves the HTML
  spypoint_sync.py  (7.1 KB)  SPYPOINT auth + photo fetch  ← the valuable part
  classifier.py     (6.3 KB)  Species ID via HuggingFace public ViT API
  predictions.py    (5.9 KB)  SQL-based activity stats ("predictions")
  weather.py        (4.5 KB)  Open-Meteo weather + moon-phase math
  pipeline.py       (3.4 KB)  Orchestrates sync → classify → enrich
  init_db.py        (2.1 KB)  SQLite schema (4 tables)
frontend/
  index.html        (15.6 KB) Single-file dark dashboard (vanilla JS)
Dockerfile, render.yaml, requirements.txt, .env.example, .gitignore
```

13 commits, single developer, last active April 2026. The commit history is revealing: it shows three successive attempts at the AI layer — `MegaDetector + SpeciesNet` → `iNaturalist Vision API` → `HuggingFace ViT API` — each lighter than the last. The trajectory is someone fighting Render's free-tier RAM/CPU limits by progressively offloading inference to external APIs. That constraint disappears once we run locally, so we can return to proper local models.

---

## As-is architecture

```
SPYPOINT Cloud ──REST──► spypoint_sync.py ──► SQLite (sightings table, CDN URL only)
                                                  │
Open-Meteo  ──────────► weather.py  ──────────────┤  (enrichment, see Bug #1)
                                                  │
HF Inference API ◄──── classifier.py ─────────────┤  (species, see Bug #3)
                                                  ▼
                          app.py (FastAPI) ──► frontend/index.html (polls every 5 min)
```

- **Process model:** one synchronous FastAPI process. No workers, no scheduler. Sync happens only on a manual `POST /api/sync` button press, which runs the *entire* pipeline inline in the request (`app.py:225`).
- **Storage:** SQLite file at `data/gametracker.db`; `data/` is gitignored and ephemeral on Render. Images are not stored at all (URLs only).
- **Frontend:** one HTML file, vanilla JS, polls `/api/dashboard`, `/api/analytics/*` every 5 minutes. Dark theme, stat cards, an hour-of-day bar chart, species bars, a camera list, a recent-sightings table with thumbnail lightbox.
- **Deploy:** Render free web service, Docker runtime, port 10000, healthcheck `/api/health`.

---

## Findings (defects & gaps), by severity

### 🔴 Critical — would invalidate the product if carried forward

| # | Finding | Evidence | Why it matters |
|---|---|---|---|
| C1 | **Weather enrichment ignores the sighting's real time.** It stamps current weather onto historical photos. | `weather.py:111-129` — `enrich_sighting_weather(timestamp)` builds `get_current_weather()` and only the moon uses `ts`. `get_historical_weather()` (`weather.py:91`) is dead code. | Every environmental correlation and forecast is built on wrong data. This is the silent killer. |
| C2 | **Images are never persisted.** Only the SPYPOINT CDN URL is stored. | `spypoint_sync.py:150-161` stores `image_url`; `download_photo()` (`:95`) is never called. Comment: "don't download — ephemeral storage." | Violates the ≥12-month retention requirement outright. Signed CDN URLs expire → permanent data loss. |
| C3 | **Schema can't express the product.** One photo = one flat row with a single free-text `category`. | `init_db.py:34-54` `sightings` table. | No bounding boxes, no multiple animals per frame, no separate sex/age confidence, no group composition. The spec's core data shapes are unrepresentable. |

### 🟠 Major — architectural blockers

| # | Finding | Evidence |
|---|---|---|
| M1 | **No background jobs / scheduler.** 15-min auto-sync and async AI inference are impossible in a single sync process. | `app.py:225` runs the pipeline in-request. |
| M2 | **SQLite, not PostgreSQL.** No PostGIS (spatial), no pgvector (re-ID embeddings), weak concurrency. | `init_db.py:9` |
| M3 | **No authentication.** Open CORS, no login. | `app.py:33-38` `allow_origins=["*"]`, no auth dependency anywhere. |
| M4 | **Generic, non-wildlife classifier.** ImageNet ViT via HF public API + a hand-maintained label map; no bounding boxes; no sex/age; rate-limited & cold-starts (`503` handling at `classifier.py:133`). | `classifier.py:108-165` |
| M5 | **`individuals` table is boar-only.** `CHECK(category IN ('Big Boar','Sow','Juvenile','Piglet'))`. | `init_db.py:26` |
| M6 | **No incremental/paginated photo fetch.** Hard limit 50 photos, `dateEnd` only. Can't backfill 12 months or page large cameras. | `spypoint_sync.py:63-80` |
| M7 | **No camera metadata captured.** Battery, signal, GPS, model — all required by spec, none read from the SPYPOINT response. | `spypoint_sync.py:126-171` |

### 🟡 Minor — quality/hygiene

- No tests, no migrations, no structured logging (`print()` throughout), no type checking, no linting.
- Hardcoded estate: coordinates fixed to Alatoz (`weather.py:6-8`); camera names hardcoded `PL14/PL15B/PL15D/PL19` (`spypoint_sync.py:174-185`).
- `predictions.py` "predictions" are descriptive SQL aggregates (peak hours, dawn/dusk buckets), not a forecasting model — fine as analytics, mislabeled as prediction.
- Render-specific assumptions (port 10000, ephemeral disk) leak into the design.

---

## Keep / Reuse / Replace — component verdicts

| Component | Verdict | Notes |
|---|---|---|
| **SPYPOINT auth + photo URL logic** (`spypoint_sync.py:22-92`) | ✅ **KEEP (port carefully)** | The endpoints (`/api/v3/user/login`, `GET /camera/all`, `POST /photo/all`) and the `photo_url()` host+path reconstruction (`:83-92`) are the real IP. Re-home into a typed client with retries, pagination, and metadata extraction. |
| **Open-Meteo weather** (`weather.py:50-108`) | ✅ **KEEP** | Correct API usage. Reuse for forecast **and** (properly this time) the historical archive endpoint already coded at `:91`. |
| **Moon-phase synodic math** (`weather.py:25-47`) | ✅ **KEEP as fallback, upgrade** | Works for phase/illumination. Add a real ephemeris (skyfield/astral) for moonrise/set + solar twilight, which the spec requires and this lacks. |
| **Dark UI palette / dashboard ideas** (`index.html:10-15`) | ♻️ **REFERENCE** | Good instinct; superseded by the React design system in `02-architecture.md`. |
| **Dockerfile / render.yaml** | ♻️ **REFERENCE** | Basis for the new multi-service compose; decouple from Render specifics. |
| **SQLite schema** (`init_db.py`) | ❌ **REPLACE** | → PostgreSQL + PostGIS + pgvector, normalized (`03-database-schema.md`). |
| **HF/ImageNet classifier** (`classifier.py`) | ❌ **REPLACE** | → local MegaDetector + DeepFaune with bounding boxes (`05-ai-pipeline.md`). |
| **Synchronous pipeline** (`pipeline.py`, `app.py:225`) | ❌ **REPLACE** | → Celery/RQ + Redis scheduled tasks (`05-ai-pipeline.md`). |
| **Single-file HTML frontend** (`index.html`) | ❌ **REPLACE** | → React + TypeScript (`02-architecture.md`). |
| **`predictions.py`** | ❌ **REPLACE (keep ideas)** | Descriptive stats survive as an Analytics module; real forecasting is `06-forecasting.md`. |

**Bottom line:** keep the SPYPOINT knowledge, the weather/moon integration, and the visual instinct. Rebuild the foundation (DB, jobs, AI, frontend, auth) — it's a reshaping, not a rewrite-from-zero, because the expensive-to-rediscover parts are preserved.

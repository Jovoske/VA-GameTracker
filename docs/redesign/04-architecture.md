# 04 — Technical Architecture

> Deliverable 13, plus performance, offline behaviour and future scalability.
> Scoped honestly: this is a self-hosted app for one estate with a handful of users, maintained by
> one person. Anything that cannot be maintained at that scale is excluded, however good it sounds.

---

## 1. The single most important change

**Move the forecast off the request path and persist it.**

Today, `GET /forecast/tonight`, `GET /alerts` and `GET /insights` each independently call
`forecast_tonight()` → `driver_map()` → `compute_patterns()` → up to two `httpx.get(timeout=30)`
calls to Open-Meteo, cached in a module-level dict that is per-process and incoherent with more than
one worker. The Tonight page fires two of these endpoints on mount.

One change — a nightly job that writes `forecasts` rows plus a `ModelRun`, and an API that only
reads them — simultaneously eliminates:

- blocking third-party HTTP on the request path (D19)
- the `_WCACHE` multi-worker incoherence (D20)
- the per-camera query fan-out
- duplicate computation across three endpoints
- the impossibility of evaluation — **because a forecast now exists as a row before the night
  happens**, scoring it becomes a 40-line job instead of an architectural impossibility

Target: `GET /forecast/tonight` p99 **under 50 ms, with no outbound HTTP, ever.**

---

## 2. Services

Same count, changed roles.

| Service | Configuration | Why |
|---|---|---|
| `db` | `postgres:16-alpine` | Drop the custom PostGIS/pgvector image — it is still built and still declared in `requirements.txt` and `README.md` despite the feature being removed. |
| `redis` | no host port | Currently published unauthenticated on the host. |
| `api` | gunicorn + uvicorn workers, **2 workers, no `--reload`** | `entrypoint.sh` ships `--reload` as production. |
| `worker-io` | concurrency 4 | Sync, enrichment, aggregates. |
| `worker-ml` | **concurrency 1**, `--max-tasks-per-child=200`, prefetch 1 | One model in RAM, ever. Default prefork concurrency = nCPU, each child lazily loading MegaDetector + ViT-L ≈ 2 GB RSS. |
| `beat` | — | Scheduler only. |
| `caddy` | static frontend + TLS | Replaces the Vite dev server currently shipped as the product (`frontend/Dockerfile:9`). |
| `backup` | nightly `pg_dump \| zstd` + media rsync, 14 dailies | **`pgdata` is a bare volume today.** One `docker compose down -v` ends the estate. |

---

## 3. Schema

### Migration repair — do this before anything else

`0001_initial.py` is `Base.metadata.create_all()` and `0003` is an explicit no-op. The commit that
dropped PostGIS/pgvector therefore shipped **no migration**: a fresh database gets the new shape
while the live estate database keeps the old one, at the **same alembic head**.

1. Freeze `0001` as explicit `op.create_table(...)` calls reflecting the original schema.
2. Write a real `0004` with `IF EXISTS` branches converting `estates.centroid` / `cameras.location`
   / `stands.location` → `lat`/`lon`, and `detections.embedding` vector → JSONB.
3. Add a CI check that `alembic upgrade head` from an empty database produces a schema identical to
   `Base.metadata` — this class of bug cannot recur silently.

### New tables

```sql
camera_night(camera_id, night, exposure_state, frames, empty_frames, window_minutes_covered)
    -- exposure_state ∈ {CONFIRMED, PRESUMED_UP, UNKNOWN, UNPROCESSED}
    -- THE denominator. See 02-recommendation-engine §7.

deployment(id, camera_id, site_id, from_ts, to_ts, lat, lon, aim_deg, height_m,
           target, flash_type, trigger_delay_s, burst_n)
    -- target ∈ {bait, water, trail}
    -- ALL analysis keys on deployment, never camera. Moving a camera today rewrites history
    -- in place: pre-move and post-move detections merge into one "presence here" figure.

camera_telemetry(camera_id, observed_at, battery_pct, signal_pct)   -- append-only
    -- "Was this camera alive on 3 March?" is currently unanswerable.

stand(...)  -- existing table, finally given a write path, routes and UI
sit(id, stand_id, user_id, claimed_at, started_at, ended_at, outcome, wind_gate_verdict)
    -- outcome ∈ {seen, shootable_no_shot, shot, nothing, unreported}
harvest(sit_id, species_id, sex, age_class, precinto, sample_id, at)
```

### Materialised view

```sql
night_activity(estate_id, night_local, camera_id, deployment_id, species_id,
               sex, group_type, n_frames, n_visits, n_animals)
```

`REFRESH MATERIALIZED VIEW CONCURRENTLY` nightly. **Every dashboard, insight and pattern query reads
this, not `detections`.** Note the three distinct count columns — the current code calls all three
"sightings" and computes only the first.

### Constraints and indexes

```sql
UNIQUE (camera_id, spypoint_photo_id)    -- fixes the SELECT-then-INSERT race (D14)
UNIQUE (file_hash)                       -- dedupe you already compute and discard
CREATE INDEX ON detections (image_id);              -- the join in every single query
CREATE INDEX ON detections (species_id, image_id);
CREATE INDEX ON detection_individual (individual_id);
CREATE INDEX ON images (captured_at DESC);
CREATE INDEX ON images (camera_id, is_empty_frame, captured_at DESC);
```

Add `estate_id` denormalised onto `images`, and **filter it in every analytic query**. Today only
`routes_cameras.py:23` filters by estate; `model.py`, `patterns.py`, all of `routes_analytics` and
`routes_insights` query globally, and `reid.py:72` is literally `select(Estate.id).limit(1)`.

The architect's hill — *do this now, before the second estate exists* — is upheld. It is nine
`WHERE` clauses today. Retrofitting tenancy after a second estate has data means silently
cross-contaminated history that can never be separated.

### `env_hourly`

Replace per-photo `EnvSnapshot` with `env_hourly(estate_id, observed_hour, …)` — one grid point, one
row per hour, ~9k rows/year instead of one per photo. `EnvSnapshot` becomes a view for
compatibility. Today enrichment makes **one HTTP call per camera-day** keyed on rounded per-camera
coordinates, so six cameras on one estate make six times the calls for identical weather, and a
13-month backfill is thousands of serial 20-second calls inside one transaction.

---

## 4. Jobs

| Cadence | Job | Notes |
|---|---|---|
| 15 min | `spypoint_sync` | **Cursor-based** — walk `dateEnd` until a known `spypoint_photo_id`. Fixes D13, where `limit=100` newest-first silently drops overflow, biased toward peak activity. Commit per camera. No enrichment inline. |
| 15 min | `enrich_hourly` | Fill `env_hourly` for the estate grid point only. |
| continuous | `ml_queue` | MegaDetector → DeepFaune → embed. Single worker, `SELECT … FOR UPDATE SKIP LOCKED` on an explicit `work_queue` table. This kills the overlapping-beat problem: today `scan_empty(5000)` every 20 min and `classify_species(2000)` every 25 min overlap for hours on CPU and re-scan the same rows. |
| 02:00 | `nightly_recompute` | Refresh `camera_night` and `night_activity`; fit; **write `forecasts` for tonight + horizon**; write a `ModelRun` with `git_sha`, `code_version`, `input_row_count`, `params`, and the permutation-null percentiles. |
| 03:00 | `evaluate_forecasts` | Score yesterday's forecasts against `night_activity`; write `forecast_outcomes`; append Brier/log-loss and reliability bins to the `ModelRun`. |
| weekly | `retention` | Actually enforce `media_retention_days` (D18 — the setting exists and is read by nothing). Keep frames referenced by a confirmed `Individual` or a `harvest`. Rows, then files, then vacuum. |

**Nothing writes a `Detection` or a `Forecast` without a `model_run_id`.** That single rule makes
every number in the product traceable to the code version and input set that produced it.

---

## 5. API contracts

`GET /api/forecast/tonight` — a pure read. Payload gains:

```json
{
  "generated_at": "...", "model_run_id": "...", "rule_version": "clm-2026-01",
  "reference_class": "camera_detection_in_window",
  "calibration": { "brier_30d": 0.19, "climatology_brier": 0.24, "n_evaluated": 41 },
  "exposure":    { "n_confirmed": 38, "n_excluded": 7 },
  "changed":     { "kind": "return", "camera": "Puente", "text": "..." }
}
```

`reference_class` as a **stored field rather than prose** is what stops the app's central honesty
property from drifting as copy is edited.

`POST /api/animals/recompute` returns `202 {task_id}` — today it runs synchronously inside the HTTP
request with DINOv2-L loaded into the API process (D21). Add `GET /api/tasks/{id}`.

---

## 6. Security fixes

| Fix | Effort |
|---|---|
| Normalise the path join in `main.py` `_spa()` — directory traversal (D3) | 15 min |
| Authenticate `routes_images` with short-lived signed URLs (D4) | 1 h |
| Remove `JWT_SECRET`/`ADMIN_PASSWORD` defaults from `.env.example`; generate on first run (D5) | 30 min |
| Remove `db` and `redis` host port mappings | 10 min |
| `deps.py` — catch `ValueError` on malformed UUID, return 401 not 500 (D15) | 5 min |
| Handle MegaDetector's **person** class rather than silently dropping it (`detector.py:20`); auto-blur or auto-delete, and enforce retention | 3 h |
| Suppress protected-species locations (the DeepFaune class list includes wolf, lynx, bear, otter) below admin role | 2 h |

The person-detection item is not optional politeness. Trail cameras photograph people; the endpoint
serving those images is currently unauthenticated by design; and the retention policy that would
bound the exposure is a setting no code reads.

---

## 7. Re-ID and embeddings

`Detection.embedding` is JSONB at ~15–20 KB per row, `SELECT`ed in full into Python for a greedy
O(n·clusters) NumPy loop, run synchronously inside an HTTP request. At 100k detections that is ~2 GB
of JSON text parsing per recompute.

The architect wants `pgvector` restored with an HNSW index, doing candidate retrieval in SQL
(`ORDER BY embedding <=> $1 LIMIT 50`) and the merge in Python over 50 rows instead of 100,000.

**Resolution, siding with the PM and red team:** the *feature* is being demoted off the hunter's
navigation because it does not work on night IR — by the page's own admission. Restoring a Postgres
extension and a Windows build dependency to accelerate a demoted feature is the wrong trade. Keep
JSONB, move the recompute to a background job with a bounded batch, and revisit only if individual
re-ID ever becomes a real product surface.

If it does, the fallback that avoids the extension is a `faiss`/`hnswlib` index rebuilt nightly into
`/data/models` — not a JSONB full-table scan.

---

## 8. Frontend and offline

| Change | Detail |
|---|---|
| **Real production build** | `vite build` behind Caddy. `frontend/Dockerfile:9` currently runs `npm run dev --host` — unbundled ES modules plus all of MapLibre over rural cellular, with an HMR WebSocket reconnect loop eating battery in the truck. |
| **Workbox precache** | Of the real built manifest. The current handler filters `req.destination` to `image`/`style` plus navigations, so **no JS module is ever cached** — the offline bug is unfixable by tweaking it. |
| **Never return HTML for `/api/*`** | Return `{stale: true}`. Today the fallback serves `caches.match('/')`, and `api.ts:23` `resp.json()` chokes on the HTML. |
| **IndexedDB, stale-while-revalidate** | One nightly plan document. Render cached instantly, refresh underneath. |
| **JWT** | Refresh silently on every successful call; store in IndexedDB, not `localStorage` (Safari ITP evicts it after ~7 days of non-use, and `App.tsx:14` checks token *presence*, never expiry — so the first hunt after a quiet week hits a login screen with no signal). |
| **Thumbnails** | Populate the existing, unused `thumbnail_path` with 320 px WebP at ingest; `Cache-Control: immutable`; `loading="lazy"`. Cameras currently pushes 80–240 MB of full-resolution originals per visit to render them at 100×74. |
| **Lazy-load MapLibre** | `React.lazy`, `/map` route only. Currently statically imported on the critical path. |
| **Safe areas** | `index.html` sets `viewport-fit=cover` and `black-translucent`; no `env(safe-area-inset-*)` exists anywhere in `src/`. |
| **Performance budget** | ≤60 KB gzip JS for the Tonight route; LCP ≤1.5 s on Slow 4G; ≤400 ms warm-offline. |

**Deferred as clever-but-unjustified at this user count:** the service-worker-as-template-engine
(injecting the plan JSON into the cached shell so the verdict is in the first paint) and dusk push
pre-provisioning. Both are genuinely elegant; both are 30–50 hours for a handful of users, and the
plain IndexedDB path gets most of the benefit.

---

## 9. Testing

Current state: four files, ~25 assertions, zero coverage of forecasting, patterns, ingestion, re-ID,
or any route beyond `/health`. No conftest, no database fixture.

Minimum viable suite, in priority order:

1. **Exposure classification** — every branch of `camera_night` state, especially `UNPROCESSED` and
   the bracketing rule for `PRESUMED_UP`.
2. **Night boundary** — a detection at 02:00 must key to the *previous* evening's night. This is
   defect D7 and it is exactly the kind of bug a single test prevents forever.
3. **Timestamp quality** — `_parse_dt` must raise, never fabricate; unparseable photos are dropped
   with a log line.
4. **Wind geometry** — known wind/approach combinations → expected verdict, including the
   below-8 km/h "too light to call" branch.
5. **Legal-light clamp** — windows outside the configured offset are clipped or refused.
6. **Scoring** — a known forecast/outcome pair produces the expected Brier contribution.
7. **Migration round-trip** — `alembic upgrade head` from empty equals `Base.metadata`.

---

## 10. Future scalability

Honest positioning: this product's moat is depth on one estate over years, not breadth across
estates. The scaling work that matters is therefore **temporal**, not horizontal.

- **Data growth** is dominated by media. Enforcing retention (already a setting) and generating
  thumbnails bounds it. Detections and `night_activity` are trivial by comparison — ~750
  camera-nights a year.
- **Multi-estate** costs nine `WHERE` clauses now and a data-integrity incident later. Do the
  clauses; do not build multi-tenant SaaS.
- **Model complexity** is capped by data, not compute: the specified hierarchical model is ~600–900
  rows and fits in seconds on CPU. There is no future in which this dataset needs a GPU for
  forecasting.
- **The real scaling risk is human attention**, not machines. Every feature that demands a new
  per-sit input competes with the one interaction the hunter will reliably give. That budget, not
  CPU, is what constrains the roadmap in document 05.

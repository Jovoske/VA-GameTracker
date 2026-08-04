# 01 — Brutally Honest Review & Verified Defect Register

> Deliverables 1 and 2. Every claim below was checked against the code. Claims that experts made but
> that did not survive verification are marked **[corrected]** and stated accurately.

---

## Part 1 — The honest review

### What is genuinely good

Say this first, because the rest is unsparing and the good parts are real.

- **The empty-frame filter works and is the highest-value thing in the repo.** `empty_filter.py`
  keeps a frame on uncertainty and on error — conservative in the right direction. Stripping empties
  from a cellular camera feed is the single biggest quality-of-life win a trail-camera user gets.
- **The AI pipeline is competently assembled** — MegaDetector → crop → DeepFaune, with the European
  class list, run locally. This is the correct architecture and it is not trivial to get working.
- **The tone is honest where it counts.** `Animals.tsx` openly tells the user that individual re-ID
  from night IR is beyond the model and that the page is a manual tool. That is rare and admirable.
  `model.py`'s docstring explicitly says it is a transparent statistical model and never claims
  certainty.
- **The design documents are better than the build.** `docs/06-forecasting.md` specifies wind-safe
  geometry, isotonic calibration, forecast scoring into `forecast_outcomes`, and a nightly job. The
  right answers were already written down.

That last point reframes everything. This is not a team that doesn't know what to build. It is a
codebase where the hard, high-value, low-glamour items on the plan were skipped and the seductive
one — correlation mining — was built instead.

### The core problem

**The app answers "will this camera photograph this species at some point in the next 24 hours?"
The hunter is asking "will I get a shootable animal in front of me during the three hours I can
actually sit, at a stand I can approach without being winded, in legal light?"**

Every downstream artefact inherits the mismatch:

- `_verdict()` applies thresholds of 0.5 and 0.2 to the wrong quantity.
- `_best_window()` finds the best 3-hour block over a 24-hour histogram, so it routinely returns
  02:00–05:00 — a window that is often illegal and always unsittable.
- `alerts.py` fires "Strong night ahead" on that same quantity.
- The "×47 Stag" chips count *photographs*, not stags.

No additional data closes this gap, because the two quantities are measurements of different events.
A camera watches one bait point for fourteen hours. A hunter watches two hundred metres of ground
for three, and their presence is itself the disturbance.

### The second problem: the app cannot be wrong

`Forecast`, `ForecastOutcome`, `ModelRun`, `Correlation` and `Stand` are declared in `models.py` and
written by **zero lines of code anywhere in the repository**. There is no hunt log, no sit log, no
harvest record. The forecast is recomputed on every GET and discarded.

An advisor that never records what it said and never learns what happened is not an uncertain
advisor — it is an unfalsifiable one. `docs/06-forecasting.md:27` promises the app will one day
display *"predictions verified correct 71% of nights."* As architected, that figure is not merely
unbuilt; it is unbuildable.

### The third problem: the numbers are noise, and can be shown to be

The behaviour-driver engine searches 8 variables × 3 scopes = 24 hypotheses, filters on the estimate
itself (`MIN_EFFECT`, `confidence`), sorts by `effect_pct × confidence`, and shows the top 6 as
declarative sentences.

Running the **real `_driver()` function** on counts generated to be statistically independent of
every covariate:

| Nights | ≥1 "driver" found in a null run | Median reported effect | Share clearing `confidence ≥ 0.25` |
|---|---|---|---|
| 15 | 95.5% | 108% | 29% |
| 30 | 99.5% | 72% | 48% |
| 45 | 99.8% | 55% | 62% |
| 90 | 97.8% | 46% | 39% |

The effect statistic is `(top-tercile mean − bottom-tercile mean) / overall mean` after sorting on
the covariate. Its expectation under the null is strictly positive; **it cannot return zero**. The
`confidence` figure multiplies `n/45` by `|r| × 1.6` — a *strength* measure used as a *precision*
measure — so pure noise at n=45 scores ≈0.19, above the 0.15 display cutoff.

Then `tonight_multiplier` takes effects derived from **terciles** and applies them at the **median**
(`split = pairs[n//2][0]`), multiplies collinear drivers together as if independent, and clamps the
result to [0.6, 1.5]. Every clamp in this codebase — `min(0.97,…)`, `max(0.02,…)`, `min(90,…)`,
`min(0.85,…)` — is a confession that the estimator underneath produces impossible values.

### The fourth problem: the sensor is treated as ground truth

The system has no concept of sensor state. `Camera.active` is never written. `SyncLog` rows are
created with **no `camera_id`** (`sync.py:141`), so no per-camera sync history exists anywhere.
`patterns.py` walks the full date range imputing `0` for every night without detections.

So each of these produces an identical "zero animals" signal, which is then regressed against
weather:

- a flat battery on a cold dawn
- a full SD card
- a lost cellular link
- a camera knocked askew by a sow
- a web across the lens, or grass grown into the detection zone
- **a night whose frames simply have not been classified yet** — `is_empty_frame` is tri-state
  (`True`/`False`/`None`) and `species.py:45` filters `IS FALSE`, so an unprocessed backlog is
  indistinguishable from a confirmed empty night

Add PIR physics: on a 28–30 °C Iberian night, thermal contrast between an animal and ambient
collapses and the effective detection radius shrinks — while heat-sagged lithium cells suppress
transmission on the same nights. The app learns "cooler nights = more activity" and feeds it into
the verdict. That is a spec sheet being sold as ecology.

### The fifth problem: it is a dashboard, not a decision aid

The Tonight screen renders nothing until three network calls resolve, two of which independently
recompute a whole-season weather model over live HTTP with a 30-second timeout. When it does load,
roughly 60% of the vertical space is lifetime aggregate charts — activity by hour, sightings by
camera, species totals — none of which change any decision at 18:00. The verdict is a lifetime
average, so it names the same stand nearly every night. That is how a decision aid becomes wallpaper.

Meanwhile the things that decide a night are absent: wind relative to the approach, legal light, a
countdown to last light, what changed since yesterday, who else is sitting tonight, and when to
leave without burning the stand.

### Would an experienced hunter use it?

The 32-year guide on the panel: *"I'd read it, nod politely, and go where I was going anyway."*

The most damning detail is not statistical. `Tonight.tsx:183` labels a list of **cameras** as
"OTHER STANDS". Cameras are placed where animals go. Stands exist where a bullet can safely stop.
The app is already shipping that conflation in the interface — the place where it can get someone
hurt.

---

## Part 2 — Weaknesses ranked by impact on real decisions

Ranked by how much each costs a hunter in animals seen, decisions corrupted, or risk incurred.

| # | Weakness | Consequence |
|---|---|---|
| **1** | Predicts camera detection, not hunter encounter | Every number is systematically, unknowably optimistic. Guarantees disappointment and eventual abandonment. |
| **2** | No forecast or outcome is ever persisted | The product cannot improve, cannot be audited, and cannot honestly claim anything. |
| **3** | Weather/moon "drivers" are indistinguishable from noise *and* feed the verdict | The headline verdict moves on statistical artefacts. |
| **4** | Camera downtime and unprocessed backlogs are imputed as zero animals | A dead battery becomes a moon-phase finding; a good new stand reads SKIP. |
| **5** | Wind is displayed and never used; `Stand` geometry is dead schema | The single most decisive field variable is decoration. |
| **6** | No hunting-pressure data of any kind | The largest real driver of what you see is invisible to the model. |
| **7** | `_best_window` ignores the sun and legal light | Routinely recommends windows that are unsittable or illegal. |
| **8** | Exposure denominator is estate-wide, not per-camera | Late-deployed cameras are structurally capped and can never say GO. |
| **9** | `confidence = 30 + nights_present × 2`, rendered larger than the probability | Salience inversion: the most meaningless number is the most visually dominant. |
| **10** | Detections count frames, not animals | Over-counts loitering singles, under-counts herds; `group_size` is computed and never used. |
| **11** | 7-night outlook is one number repeated with a moon wobble | Fabricated precision; contradicts the app's own learned moon driver on an adjacent tab. |
| **12** | Offline is broken in the exact place the app matters | No signal → parse error, not a plan. |
| **13** | No legal layer at all | The app can recommend a species in veda, at an illegal hour, to an unidentified guest. |
| **14** | Migration/backup gap | Doing nothing can lose the season's data. |
| **15** | Tonight screen is majority lifetime analytics | Pushes the verdict off-screen; answers no 18:00 question. |

---

## Part 3 — Verified defect register

Correctness and safety bugs, confirmed by reading the code or by reproduction. These are ordinary
bugs, independent of any redesign opinion, and several are cheap.

### Data-loss and security

| ID | Location | Defect |
|---|---|---|
| D1 | `alembic/versions/0001_initial.py`, `0003_…` | `0001` is `Base.metadata.create_all()` and `0003` is an explicit no-op. The commit that dropped PostGIS/pgvector shipped **no migration**. Fresh databases get the new shape; the live estate database keeps the old one — **same alembic head, two schemas**. Next `docker compose up` can strand a season of data. |
| D2 | `compose.yaml` | `pgdata` is a bare volume with no backup. One `docker compose down -v` ends the estate. |
| D3 | `main.py` `_spa()` | `os.path.join(_DIST, full_path)` with **no path normalization** — directory traversal when `FRONTEND_DIST` is set (the documented native build). |
| D4 | `routes_images.py:18` | Image files served **unauthenticated** by design ("unguessable UUID"). |
| D5 | `.env.example` | Ships `JWT_SECRET=dev-secret-change-me-please` and `ADMIN_PASSWORD=changeme`; `start.bat` copies it automatically. `compose.yaml` publishes Postgres and unauthenticated Redis on the host. |
| D6 | `Map.tsx:55,64` | Markers are `draggable: true` unconditionally; `dragend` PUTs a new camera location with `.catch(() => {})`. An accidental pan silently and irreversibly corrupts camera coordinates. |

### Correctness

| ID | Location | Defect |
|---|---|---|
| D7 | `patterns.py:90-92` vs `:109` | **Night-boundary mismatch.** Weather keys a night as 18:00 D → 06:00 D+1; detections key by calendar date. All post-midnight detections pair with the following night's weather. Reproduced. |
| D8 | `model.py:165` | `now.astimezone().replace(hour=22)` — `now` is UTC and containers set no `TZ`, so this samples 22:00 UTC = 00:00 *next day* Madrid. Tonight's weather is fetched for the wrong hour and often the wrong date, then fed into the verdict. |
| D9 | `spypoint.py:108-114` | `_parse_dt` returns `datetime.now(timezone.utc)` on parse failure — **fabricates capture timestamps**. Also prefers `p["date"]` over `originDate`; SPYPOINT batches on signal return, so a late upload can manufacture a dawn "peak window". |
| D10 | `model.py:70` vs `:197` | `presence = nights_present / total_nights` — numerator per-camera-and-species, denominator estate-wide distinct capture dates. |
| D11 | `insights.py:108-118` | `_moon()` draws both numerator and denominator from a query already joined to `Detection`, so zero-detection nights can never enter. The dark/bright ratio is structurally biased. |
| D12 | `insights.py:33-35` | `EnvSnapshot.observed_at == Image.captured_at` exact-timestamp join silently drops every image without a matching snapshot — an undocumented, camera-biased filter. |
| D13 | `sync.py:96` | `limit=100` newest-first with no cursor; >100 uploads between 15-minute syncs are never paged to and never ingested. Loss is biased toward peak activity. |
| D14 | `sync.py:60` | SELECT-then-INSERT on `spypoint_photo_id`; concurrent sync raises IntegrityError. |
| D15 | `deps.py:26` | `uuid.UUID(subject)` on a malformed token raises `ValueError` → HTTP 500 instead of 401. |
| D16 | `sync.py:141` | `SyncLog` created with no `camera_id` — no per-camera sync history exists. |
| D17 | `astro.py` | `moon_rise`/`moon_set` columns exist in `EnvSnapshot` and are never computed. Moon *phase* is stored; moon *timing* — which is what matters — is not. |
| D18 | `config.py:35` | `media_retention_days` is never read by any code. Media grows unbounded; `.env.example` advertises a retention policy that does not exist. |

### Performance and operations

| ID | Location | Defect |
|---|---|---|
| D19 | `model.py:222`, `alerts.py:36`, `insights.py:185` | Third-party HTTP on the request path. `/forecast/tonight`, `/alerts` and `/insights` each independently trigger up to two 30-second Open-Meteo calls; the Tonight page fires two of these endpoints. |
| D20 | `patterns.py:31` | `_WCACHE` is a module-level dict — per-process, unbounded TTL, incoherent with more than one worker. |
| D21 | `routes_animals.py:256` | Re-ID recompute runs **synchronously inside the HTTP request**, loading DINOv2-L into the API process. |
| D22 | `models.py:125` | Embeddings stored as JSONB (~15–20 KB/row) and scanned into Python for similarity — a full-table scan per recompute. |
| D23 | `celery_app.py:21-26` | Beat fires `scan_empty(5000)` every 20 min and `classify_species(2000)` every 25 min; CPU MegaDetector at 1–3 s/frame means runs take hours and overlap, re-scanning the same rows. |
| D24 | `entrypoint.sh`, `frontend/Dockerfile:9` | `uvicorn --reload` and `npm run dev` shipped as production commands. |
| D25 | schema | No index on `detections.image_id` (the join in every query), `detections.species_id`, or `images.captured_at` alone. |
| D26 | `vision_sex.py` | Only persists `sex != unknown`, so every re-run re-pays for every previously-unknown crop; a new API client is constructed per image. Cost is unbounded and repeatable by a button. |

### Interface

| ID | Location | Defect |
|---|---|---|
| D27 | `sw.js:28-36` | Caches only `navigate`/`image`/`style` — **no JS module is ever cached**. API GETs fall back to `caches.match('/')`, returning HTML that `api.ts:23` `resp.json()` rejects. Offline shows a parse error. |
| D28 | `Layout.tsx:23-31` | ~635 px of nav in a 390 px viewport, no wrap, ~33 px targets, top-anchored. Half the navigation is physically off-screen and unreachable one-handed. |
| D29 | `Tonight.tsx:66` | `if (!f || !d) return 'Loading…'` — a slow `/analytics/overview` blanks a verdict that has already arrived. |
| D30 | `theme.css:5-6` | Verdict colours are near-isoluminant: `--go` vs `--marginal` = **1.12:1**, `--go` vs `--skip` = **1.46:1**, with colour as the only channel on an 8 px dot. **[corrected]** The replacement pair proposed during review (`#2E9E43`/`#F0C674`) measures **2.14:1**, also below the 3:1 threshold — three verdict states cannot be separated by colour alone on this background, so shape must be load-bearing. |
| D31 | `Insights.tsx:226` | Hardcoded "Early patterns from ~1 month of data" while Tonight reads live `nights_of_data`. |
| D32 | `index.html` | Sets `viewport-fit=cover` and `black-translucent`, but no `env(safe-area-inset-*)` exists anywhere in `src/` — content sits under the notch in standalone mode. |
| D33 | `models.py:144` | `thumbnail_path` exists and is never populated; `Cameras.tsx` renders full-resolution originals at 100×74 px. |
| D34 | `alerts.py:71-76` | The "camera quiet" alert joins Detection→Image→Camera only, ignoring `battery_pct`, `signal_pct` and `last_sync_at` on the same row, and never fires for a camera that died before accumulating 15 detections. |

### Counting semantics — the defect that corrupts every statistic

`species.py:33` writes **one `Detection` row per image**, taking species from the highest-confidence
box, with `group_size` holding the box count.

Therefore:
- a burst of 30 frames of one loitering boar → **30 rows**
- a herd of 12 deer in a single frame → **1 row** (`group_size = 12`)

Every count in the product — `by_species`, the `×N` class chips, the nightly activity series driving
the correlations — counts rows. The app **over-counts loitering singles and under-counts herds**
simultaneously, and `group_size`, which is computed correctly, is used in no statistic anywhere.
Mixed-species frames receive a single label.

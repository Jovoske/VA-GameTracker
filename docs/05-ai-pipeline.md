# Deliverable 6 — AI Pipeline Design

**Hardware reality:** this laptop has no NVIDIA GPU (Intel Iris Xe only), so inference is **CPU-only**. That is acceptable for a few cameras on a 15-minute cadence, provided inference never runs in the request path and is queued. Models are exported/run via **ONNX Runtime** where possible for CPU speed. Weights cache in a `models/` volume, downloaded on first run.

## Five honest stages

### Stage 1 — Detection (find the animals)
- **MegaDetector v5** (via PytorchWildlife / Ultralytics export). Outputs bounding boxes for `animal / person / vehicle` + confidence.
- **Empty-frame rejection:** no animal box above threshold → mark `images.is_empty_frame = true`, skip downstream work. Trail cameras fire on wind/vegetation constantly; this saves storage and compute early (spec requirement).
- Person/vehicle boxes recorded but not classified as wildlife (useful for security/poaching awareness later).

### Stage 2 — Species (what is it)
- **DeepFaune** classifier on each animal crop. DeepFaune is purpose-built for **European** wildlife (boar, red/roe/fallow deer, fox, badger, mouflon, hare, etc.) — a direct fit for the spec's "Europe-only, don't load NA/African/Asian models."
- Output: `species_id` + `species_conf`, mapped into the `species` reference table. Below-threshold → `Unknown` (honest default, never a guess).
- This satisfies the minimum species list (wild boar, roe/red/fallow deer, mouflon, fox, badger, rabbit, hare, common birds) and stays expandable — new species = new label, no rearchitecture.

### Stage 3 — Attributes (sex / age / group) — *low confidence by design*
- **Group size & type:** derived structurally from the detection set in a frame (count of same-species boxes → `single` / `sow_and_piglets` / `deer_group` / `multiple_boars`). This is the most reliable attribute and needs no extra model.
- **Sex & age class:** estimated, **defaulting to `Unknown`**. A single nighttime IR frame rarely supports confident sex/age calls. We start with conservative heuristics (relative body size within a frame, antler presence for deer where visible) and a low confidence cap; a fine-tuned head can be added later. The spec is explicit: *don't market certainty you can't deliver.* The UI shows these as estimates with their confidence, or "Unknown."

### Stage 4 — Individual re-ID (who is it) — *Tier 2, human-in-the-loop*
- Compute an **embedding** per animal crop (re-ID backbone, e.g. MiewID-style or DeepFaune features) → store in `detections.embedding` (pgvector).
- **Candidate match:** HNSW nearest-neighbour against existing individuals of the same species, blended with temporal/behavioral priors (same camera, plausible time gaps). Produce `match_conf`.
- **The user is the oracle.** Above a high threshold we *suggest* "likely Large Male Boar #3 (80%)"; the user confirms / merges / splits. Confirmed matches (`confirmed_by_user`) anchor future matching. We **never auto-assert identity** above real confidence — the spec's hard rule. This human-in-the-loop design is also what makes perceived accuracy climb over time.

### Stage 5 — Annotate
- Render boxes + species label + confidence onto a copy → `annotated_path`. Original is never modified.

## Execution & performance

- One Celery task per image (`ai.infer`), enqueued at ingest. Idempotent (keyed by `image_id`); re-runnable when models upgrade (new `model_runs` row).
- Rough CPU budget on this i7-1355U: detector ~1–3 s/image, classifier ~0.1–0.5 s/crop. Daily volume (a few cameras × tens of photos) is trivial. The **12-month backfill** (potentially tens of thousands of frames) runs as a throttled background job over hours — surfaced with a progress meter, not blocking anything.
- Concurrency capped to leave CPU for the API and Postgres; configurable worker count.

## Honesty & guardrails (built into the data contract)

- Confidence is stored and surfaced for species, sex, age, and identity — always.
- `Unknown` is a first-class, preferred answer over a low-confidence guess.
- `model_runs` records which model/version produced each detection, so results are reproducible and re-scorable after upgrades — and so the system can later **show its own track record**.

## Tests (one of the three risky bits, per spec)

Re-ID matcher gets unit tests on synthetic embeddings (known same/different individuals → expected match/no-match), threshold behavior, and merge/split bookkeeping. Detection/classification tested against a small fixture image set with expected species + box counts.

# Deliverable 6 — AI Pipeline Design

**Hardware reality:** this laptop has no NVIDIA GPU (Intel Iris Xe only), so inference is **CPU-only**. That is acceptable for a few cameras on a 15-minute cadence, provided inference never runs in the request path and is queued. Models are exported/run via **ONNX Runtime** where possible for CPU speed. Weights cache in a `models/` volume, downloaded on first run.

## Five honest stages

### Stage 1 — Detection (find the animals)
- **MegaDetector v5** (via PytorchWildlife / Ultralytics export). Outputs bounding boxes for `animal / person / vehicle` + confidence.
- **Empty-frame rejection:** no animal box above threshold → mark `images.is_empty_frame = true`, skip downstream work. Trail cameras fire on wind/vegetation constantly; this saves storage and compute early (spec requirement).
- **People and vehicles (feature 25):** the same look keeps MegaDetector's surest person and vehicle box per frame (`images.person_conf`, `vehicle_conf`; NULL = not looked for). A frame with a person (≥ 0.2) or a vehicle (≥ 0.4) is an admin's alone (`api/visibility.PEOPLE`): out of every shared list, gallery, note and push, and out of every count, whatever else is in it. Admins see them under Photos → "People & vehicles", and can say "Nobody in it" (`images.people_cleared`) when the detector misread a feeder or a rock. Photos checked before this are looked at again for people in daylight, all of them back to the first, newest first, a few a run (they show as they always have until then). A frame nobody has looked at yet (straight after a sync, or one the AI gave up on) is an admin's too until the AI pass has looked at it (`visibility.NOT_LOOKED_AT`): minutes after the fetch.

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

## As built (Sep 2026)

The design above is the original plan. What runs today (`backend/app/ai/checking.py`):

- **One pass, one look per photo.** Each photo waiting goes through MegaDetector v6
  once, asked for boxes down to 0.05 (Ultralytics' default of 0.25 used to hide the
  faint ones). Under 0.10 it is empty; a kept one goes straight to DeepFaune with
  the same boxes, cropped square around the surest box. Newest first, at most 300
  photos or 10 minutes a run, so a backlog never holds the photo fetch up.
- **Only this estate's animals, only when sure.** DeepFaune picks among the classes
  that can be at Alatoz (no moose, bison, reindeer, chamois, wolf…) and names one
  only at 0.5 or more; below that the photo is an "Animal" nobody named, and the
  guess is kept with the sighting (`bbox.guess`). A new species joins the Tonight
  advice only when it is game here (boar, red/roe/fallow deer, mouflon, ibex).
- **Groups.** A box mostly inside a bigger one is the same animal (no more "Sow +
  piglets" for one boar with its head boxed twice), and a smaller animal is only a
  youngster when it stands on the same ground line, not further back.
- **One visit, one species.** Frames of a camera within 2 minutes of each other vote
  (by confidence); frames that disagree or could not name it take the visit's
  species, unless the model was sure of its own (0.9+). Each frame's own reading is
  kept (`bbox.own`), so a vote can always be taken again.
- **Failures are never "empty".** A model that cannot load stops the pass before it
  touches a photo, and says why in Settings → Photo checking. A photo that fails is
  tried on the next runs and given up on after 3 (`images.ai_failed_at`); its night
  stays "not checked" in the exposure table. Several failing in a row are checked
  against a plain test picture first: if the models fail there too, the pass stops
  without counting it against the photos.
- **A hunter's flag always wins.** The detector's verdict is written only while the
  photo is still unreviewed, in one statement.
- **Stag / hind** (cloud, `vision_sex.py`, hourly, its own lock): newest first; the
  prompt knows the month, so from February to April "no antlers" is not a hind. A
  refused key, no credit or no answer from Anthropic stops the pass and is not
  counted as the photo's one attempt.
- Photos judged empty at the old 0.25 cut-off in the last 30 days are looked at again
  at 0.05, 100 a run, in daylight only.

## Tests (one of the three risky bits, per spec)

Re-ID matcher gets unit tests on synthetic embeddings (known same/different individuals → expected match/no-match), threshold behavior, and merge/split bookkeeping. Detection/classification tested against a small fixture image set with expected species + box counts.

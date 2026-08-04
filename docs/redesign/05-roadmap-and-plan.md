# 05 — Roadmap and Prioritised Implementation Plan

> Deliverables 12 and 18. Highest ROI first.
> Effort is estimated for one maintainer with agent leverage — the repository's actual history is
> 20 commits by one author across four calendar days, ~5,600 LOC, then dormant for five weeks. The
> plan is sized to that reality, not to a team that does not exist.

---

## The two constraints that shape everything

**1. Human attention, not compute.** The thirteen experts collectively requested roughly **eight
discrete data entries per sit-night** from a person who sits perhaps thirty nights a year and takes
their phone out at last light, in the dark, in gloves. Every proposal was re-costed against a hard
budget of **one interaction per sit, plus one one-time setup per stand.**

**2. Nothing is validatable against sit outcomes for years — but camera-nights validate this
season.** ~750 scoreable camera-nights per season arrive with zero human input; 35–45 sits do not.
Every scoring claim in this plan is against camera-nights.

---

## Phase 0 — Stop losing data and stop lying (~20 hours)

Nothing here is a feature. All of it is either a correctness bug or a claim the app cannot support.
**If only one phase is ever done, do this one.**

| Hours | Task | Ref |
|---|---|---|
| 4 | Real migration `0004` with `IF EXISTS` branches; freeze `0001` as explicit `create_table`; add the schema-equality CI check; `pg_dump` backup sidecar | D1, D2 |
| 1 | **Night-boundary fix** — key detections to night-of (18:00→06:00), not calendar date | D7 |
| 1 | Fix the weather-hour timezone bug (`now.astimezone()` under a container with no `TZ`) | D8 |
| 1 | `_parse_dt` raises instead of returning `now()`; prefer `originDate`; drop unparseable photos | D9 |
| 0.5 | `Map.tsx` `draggable: false` outside an explicit edit mode | D6 |
| 2 | Normalise the `_spa()` path join; authenticate `/images`; strip `.env.example` secrets; unpublish db/redis ports; fix the 500-on-bad-UUID | D3, D4, D5, D15 |
| 3 | Delete `confidence`, the `tonight_multiplier` path, `_outlook`, the p≥0.7 alert and the battery-blind quiet alert. Strip causal language from Insights | — |
| 3 | Real `vite build` behind Caddy; drop `--reload`; populate `thumbnail_path` at 320 px WebP | D24, D33 |
| 2 | Move `compute_patterns` off the request path (largely free once the drivers are deleted) | D19, D20 |
| 2.5 | Replace the verdict with the natural-frequency sentence carrying its own reference class | — |

**Why this is first:** it is the only phase where *doing nothing* can lose the season's data, and the
deletions remove claims that are actively misleading a user tonight. It requires no new data, no new
UI, and no model.

---

## Phase 1 — Make the app legal and honest (~1 week)

| Hours | Task |
|---|---|
| 8 | **Legal-light gating.** Owner-configured, effective-dated offsets around sunrise/sunset (regional hunting orders change annually — never hardcode). Clamp every window; show last light and a countdown; refuse to render a window outside it, with the reason. Stamp every verdict with the rule version. |
| 6 | **Bottom navigation**, three tabs, 56 px + safe-area insets. Decouple the three Tonight fetches so a slow analytics call cannot blank an arrived verdict. |
| 6 | **Verdict re-encoding**: word + shape load-bearing, colour redundant. `BEST ODDS ▲ / WORTH A LOOK ◐ / QUIET ○ / NO DATA ▨`. Retire `--skip` red for verdicts, reserve it for safety refusal. |
| 8 | **Persist the forecast at issue time** — nightly job writes `forecasts` + `ModelRun`; `GET /forecast/tonight` becomes a pure read with `generated_at`, `model_run_id`, `reference_class`. |
| 4 | **Empty/loading/stale states** — freshness chip, cached-first render, `NO DATA` distinct from `QUIET`. |

**Outcome:** the app stops recommending illegal hours, stops being unreachable one-handed, stops
blanking on a slow request, and becomes unable to silently rewrite what it said.

---

## Phase 2 — Exposure and the descriptive floor (~1 week)

The unit-of-analysis repair. Everything numerical downstream depends on it.

| Hours | Task |
|---|---|
| 10 | **`camera_night` exposure table** — `CONFIRMED` / `PRESUMED_UP` / `UNKNOWN` / `UNPROCESSED`. NULL, never zero. Built from the empty-frame stream, which is currently discarded as noise and is the only per-camera liveness evidence in the system. |
| 2 | **Forced daily time-lapse frame** per camera — converts exposure from inference to ground truth. |
| 6 | **Burst collapse into independent visits** (same camera, same species, 30-minute quiet interval); `night_activity` materialised view with distinct `n_frames` / `n_visits` / `n_animals` columns. |
| 4 | **Per-camera base rate + sun-anchored diel curve** with partial pooling. This is the baseline model, and very likely the best model available this season. |
| 6 | **Sunset-anchored actogram** with exposure hatching; **last-night delta strip**; the specified `changed` field. |
| 2 | **Free diagnostic:** regress `Detection.bbox` area against ambient temperature. If animals are detected closer on hot nights, temperature is refuted as an activity driver from the app's own data, at zero cost. |

**Outcome:** every count in the product finally has a denominator, camera downtime stops
masquerading as absence, and "what changed since yesterday" becomes real.

---

## Phase 3 — Stands, wind and the claim (~1.5 weeks)

The first phase that asks a human for anything, and it asks once per stand plus once per sit.

| Hours | Task |
|---|---|
| 10 | **`Stand` as the primary entity** — CRUD, routes, UI. Cameras become evidence and stop being recommendable. Auto-seed `approach_dirs_deg` from sequential cross-camera detections; present for one-tap confirmation rather than asking anyone to draw arrows. |
| 8 | **Wind geometry** with its competence boundary: scent cone vs approach arc above 8 km/h; *"too light to call — thermals will decide this"* below it; *"no arcs entered — yours to solve"* when unconfigured. **Advisory, never a veto.** Logged as a gate with its own outcome column so it can eventually be falsified on the same terms as the model. |
| 6 | **The Claim** — claiming a stand for tonight, with the conflict interlock (refuse overlapping shooting arcs). This is the data-capture mechanism, and it works because claiming has a selfish payoff. |
| 10 | **Sit Mode** — true black, amber monochrome, imagery unmounted, network frozen, one giant button. Tap = seen, long-press = nothing, two-finger hold = end. The `ForecastOutcome` write path and the only glove-safe interaction, in one feature. |
| 4 | **Dark exit** — earliest historically-empty approach corridor time, plus the crosswind bearing out. |

**Outcome:** the app answers *which stand*, not *which camera* — and starts recording what a night
actually cost and produced.

---

## Phase 4 — Scoring (~3 days)

| Hours | Task |
|---|---|
| 8 | **T+1 `evaluate_forecasts`** against camera-nights; write `forecast_outcomes`; append Brier, log-loss and reliability bins to the `ModelRun`. Baselines: per-camera climatology, persistence. |
| 6 | **Block-permutation null** — 500 circular shuffles (≥30-day shift) per candidate driver, percentile stored in `model_runs.metrics`. Publish nothing below the 95th percentile; print the noise floor on screen. |
| 4 | **Track-record surface** in Insights: reliability diagram, Brier vs baselines, `n` evaluated — shown even when the model is losing. |

**Outcome:** the app can be wrong, in public, with a number. This is the precondition for every
claim in `docs/06-forecasting.md`.

---

## Phase 5 — Offline (~4 days)

Deliberately after Phase 1, on the architect's sequencing argument: once the nightly forecast is a
persisted document, caching it is small; before that, "offline" means caching a computation, which
is precisely why `sw.js` is broken today.

| Hours | Task |
|---|---|
| 10 | Workbox precache of the real built manifest; IndexedDB stale-while-revalidate of the plan document; `/api/*` returns `{stale:true}`, never HTML; JWT refreshed silently and stored in IndexedDB. |
| 6 | Night mode; lazy-load MapLibre; performance budget enforcement. |

---

## Phase 6 — Compliance as product (~1 week, before the first season-end return)

| Hours | Task |
|---|---|
| 12 | **Cupo burn-down** from the estate's game-management plan: quota by species/sex/age, remaining, projected exhaustion. |
| 10 | **Harvest log** — hunter, stand, timestamp, species/sex/age, seal number, sample ID. Auto-decrements quota. |
| 8 | **Season export** — the annual return, generated from the same rows that produced the forecast. |
| 6 | **Person-detection handling** (auto-blur or auto-delete), enforced media retention, protected-species location suppression below admin role. |

This phase is the PM's "compliance trojan horse": harvest entry is *already* legally required
paperwork, so it has a ~90% completion rate where an optional log has 10–20%. It is the one capture
point that reliably feeds itself.

---

## Deferred, with entry criteria

| Item | Unlocks when |
|---|---|
| Hierarchical Bayesian model with covariates | Only if it beats the Phase-2 baseline on prequential Brier. Honest expectation: **under 10% chance in season one** — the design is underpowered by roughly an order of magnitude for realistic weather effects. |
| Moon-in-window coefficient on screen | ≥10 lunations of clean exposure data + beats its own permutation null + 90% interval excluding zero |
| Negative-binomial visit layer | Poisson log-score beats the Bernoulli `P(≥1)` out of sample |
| Burn half-life per stand | ~25 logged sits at that stand — late season two at the earliest |
| Rank agreement (app vs hunter) | ~35 logged blind picks |
| Individual re-ID as a product surface | Not on this roadmap. It does not work on night IR by the page's own admission. |

## Cut permanently

| Item | Why |
|---|---|
| **"You vs GameSense" scoreboard** | At 25–40 sits the paired Brier confidence interval is wider than the entire plausible skill range. A coin flip presented as a verdict on the machine's competence — the exact sin this review prosecutes. |
| **LightGBM / GBT plan** (`docs/06-forecasting.md:16`) | At one estate you gain ~365 nights a year and the dominant covariate is seasonal. Hierarchical pooling wins here permanently, not temporarily. Strike it from the design doc. |
| **Camera→sit conversion ratio ρ** | Needs ~200 sits, and is not a scalar — it varies by stand, species and wind. Ship ordering, never magnitude. |
| **Service-worker-as-template-engine, dusk push pre-provisioning** | Elegant; 30–50 hours for a handful of users; IndexedDB gets most of the benefit. |
| **Multi-estate SaaS** | Do the nine `estate_id` clauses. Do not build the product. |
| **Restoring pgvector** | Accelerates a feature being demoted off the navigation. |

---

## If there are only 40 hours

The red team's honest minimum, adopted essentially unchanged. No trigonometry, no sampler, no
scoreboard.

| Hours | Task |
|---|---|
| 4 | Migration `0004` + freeze `0001` + `pg_dump` sidecar |
| 1 | Night-boundary fix |
| 1 | `_parse_dt` raises instead of fabricating timestamps |
| 1 | Weather-hour timezone fix |
| 0.5 | `Map.tsx` `draggable:false` |
| 2 | Path-join normalisation, `/images` auth, `.env.example` secrets |
| 3 | `vite build` behind nginx, drop `--reload`, 320 px thumbnails |
| 3 | Delete `confidence`, `tonight_multiplier`, `_outlook`, both bad alerts; strip causal language |
| 4 | Legal-light clamp + last-light countdown |
| 3 | Natural-frequency verdict sentence with its reference class |
| 2 | Persist the forecast JSON at issue time (score nothing yet) |
| 6 | The Claim + a 4-field sit outcome — one screen, one table, one big button |
| 4 | Bottom navigation, 56 px + safe area |
| 2 | Move `compute_patterns` off the request path |
| **36.5** | **3.5 h slack** |

Then wait two seasons, accumulate 60–80 logged sits and ~1,500 camera-nights, and ask again whether
there is anything worth modelling. That question will then have an answer instead of a guess.

---

## Five years out

What would exist here that no competitor has — because none of it can be bought, only accumulated on
one property over years:

1. **Per-stand burn half-life in nights**, measured from paired claim-vs-camera-control. Turns
   "rest it or sit it" from folklore into a number, and it is the cost every hunter currently pays
   blind.
2. **A multi-year record of each hunter's blind pick versus the model** — the only honest way to know
   whether the software ever added anything.
3. **Rule-version-stamped verdicts** that double as a legal audit trail: what the app advised, under
   which season's rules, to whom, on which night.
4. **Effective IR detection radius per deployment**, derived from the camera's own flash photometry —
   the actual sampled area, which is what makes counts comparable across cameras at all.
5. **The season's cull return generated from the same rows that produced the forecast** — compliance
   and intelligence as one artefact rather than two systems.

**What makes an experienced hunter refuse to hunt without it** is none of the above, and it is not a
probability. It is opening the app at 18:00 and seeing that Solana is already claimed, that tonight's
south-westerly puts their scent straight into that person's approach line, and that Puente has been
rested nine nights.

No competitor has the sit register. So no competitor can say any of that.

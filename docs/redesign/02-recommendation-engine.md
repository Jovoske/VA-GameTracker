# 02 — The Recommendation Engine, Rebuilt

> Deliverables 6, 11, 14, 15, plus the metric and confidence-scoring redesign.
> This document is the output of the prediction panel (statistician, ML engineer, wildlife biologist,
> decision scientist, hunting guide, field-ops specialist) after cross-examination, with the red
> team's power analysis applied on top.

---

## 1. What should be predicted

### The current target is wrong

`P(species s photographed at camera c at any point in a 24-hour period)` — estimated as
`nights_present / total_nights` with an estate-wide denominator.

### The replacement

> **Primary estimand: `Y(c,s,n) ∈ {0,1}` — was species *s* detected at camera *c* during window *W*
> on night *n*, where *W* = the hunter's chosen sit window ∩ legal shooting light.**

Four properties earn it the primary slot:

1. **Binary kills the overdispersion.** Because `species.py` writes one row per *image*, counts
   measure burst settings and loiter duration. A 0/1 outcome is immune to that entirely.
2. **The window is inside the estimand, not a post-hoc slice.** The current code computes a "best
   window" and then reports a probability that ignores it.
3. **It is observable at T+1 without asking a human anything.** This is the property that makes the
   whole system validatable — see §5.
4. **It is honest about what it measures.** It is a statement about a camera, and the interface says
   so in words.

### What the alternatives become

| Proposal | Disposition |
|---|---|
| Expected visits per camera-armed-hour (negative binomial) | **Optional second layer.** Ships only if its Poisson log-score beats the Bernoulli-derived `P(≥1)`. The ML engineer conceded it as primary. |
| E[shootable animals per sit] | **A display transform, not a fitted model**: `p × class-eligibility share × legal-light overlap`. The decision scientist conceded this — fitting it requires data that does not exist. |
| "Nothing beyond base rates and diel timing is estimable" | **Becomes the covariate whitelist**, not a rival estimand. |
| Camera→sit conversion ratio ρ | **Not identifiable. Does not ship, this season or probably ever** — see §3. |

---

## 2. Variables: what earns a place, what is deleted

### Deleted outright

| Variable | Why |
|---|---|
| `darkness_minutes` | `1440 − daylight` — a *deterministic function of day-of-year*. Correlating it with activity detects the calendar and labels it an environmental driver. |
| Temperature (as an activity driver) | ~90% collinear with day-of-year within one season. Moves to the **detection layer** instead — see below. |
| Pressure, pressure trend, cloud, rain | Unidentifiable at n ≈ 150 estate-nights after day-of-year is controlled. `rain` is ~75% zeros, so its tercile split compares zero-rain nights to zero-rain nights. |
| Wind (as a fitted coefficient) | Ships as deterministic geometry instead — §4. The empty-frame trigger rate is retained as a *diagnostic* to test whether "windy = active" is really PIR false-trigger rate. |

### Kept, but re-specified — the moon

The biologist's round-one position was "delete the moon entirely." The statistician's was "no
environmental effect is estimable from one season, full stop." **Both are too strong**, and one
measurement settles it:

```
150-night season = 5.1 lunations
corr(day-of-year, moon illumination) = -0.12      → effectively orthogonal
corr(day-of-year, darkness_minutes)  ≈ 1.0        → deterministic by construction
```

The moon carries a genuine within-season contrast that the seasonal spline cannot absorb. It is the
one environmental term with an identifiable design. But the guide reframed *which* moon number
matters, and he is right:

> Illumination on a night is not what moves animals. Whether the moon is **up during the hours you
> are sitting** is.

**Covariate: `moonlit_minutes_in_W`** — minutes within the sit window when the moon is above the
horizon, weighted by illuminated fraction. This requires computing `moon_rise`/`moon_set`, whose
columns already exist in `EnvSnapshot` and are never filled (defect D17).

Note this replaces **three** current moon terms: `_VARS["moon_illum"]`, the `±0.05` nudge in
`_outlook`, and the structurally-biased dark/bright ratio in `_correlations`.

### Moved to the detection layer — temperature

PIR sensors trigger on thermal contrast. On a 28–30 °C Iberian night, the contrast between an
animal's surface and ambient collapses and the effective detection radius shrinks. Learning
"cooler nights = more activity" is learning the sensor.

**This is falsifiable from data already stored, at zero cost.** `Detection.bbox` is populated.
Regress median bbox area against ambient temperature. If animals are detected systematically
*closer* on hot nights, the detection radius shrank, and the temperature "driver" is refuted by the
app's own data. **Run this before shipping any thermal claim.**

---

## 3. The camera-is-not-a-hunter problem

The guide's hill: *"a camera's hit rate is not a sit's success rate, and no amount of data fixes
it."* The ML engineer proposed learning a stand-vs-camera detectability ratio ρ from a sit log.

**The guide wins, on arithmetic.** At a stand encounter rate near 0.15, pinning ρ to ±0.05 needs
roughly 200 logged sits — three to five seasons on one estate — and ρ is not a scalar: it varies by
stand, by species, and by wind. The ML engineer conceded.

**What ships instead:**

1. **No conversion, ever.** The app never multiplies a camera number into a sit number.
2. **Ordering, not magnitude.** Rank agreement between the app's stand ordering and the hunter's is
   reportable at ~35 sits (Spearman), long before any probability is transferable.
3. **The sentence carries the reference class.** The interface names the camera as the observer, in
   the hero copy, not in a footnote.

---

## 4. Wind: geometry, not a coefficient — with an honest competence boundary

Every panel wanted wind-vs-stand geometry. The red team attacked it hard, and the attack was
partially successful. Both are reflected here.

**The case for:** it needs zero training data, it is the first thing any guide checks, and
`Stand.approach_dirs_deg` / `shooting_dirs_deg` already exist in the schema.

**The red team's counter, which stands:**
- `_tonight_conditions` fetches weather from **one grid point** for the whole estate, from a cell of
  order 2–11 km. That is synoptic wind, not the wind in a barranco.
- The guide's own testimony: below ~8 km/h, thermal drainage dominates and synoptic direction is
  irrelevant. In inland Albacete in early autumn, calm evenings are common.
- Nobody has ever entered an approach bearing. The data does not exist and must come from a human.

**Resolution — wind ships, but as a statement with a declared competence boundary, never a veto:**

| Condition | What the app says |
|---|---|
| No arcs entered for this stand | *"WIND SW 12 km/h — no approach arcs entered for Puente. Yours to solve."* |
| Wind ≥ 8 km/h, arcs entered, scent cone clear of approach | *"WIND SW 12 km/h — clean for Puente. Your scent goes down the barranco, not across the approach."* |
| Wind ≥ 8 km/h, arcs entered, cone intersects approach | *"WIND SW 12 km/h — carries straight down your approach. Take Solana instead."* |
| **Wind < 8 km/h** | *"WIND SW 4 km/h — too light to call. Thermals will decide this; read them at the truck."* |

That last row is the one the red team's critique buys, and it is the difference between a tool and a
liability. The app declaring the limits of its own competence is worth more than a confident bearing
that contradicts the smoke the hunter just watched.

**Arc entry is not an upfront gate.** Seed `approach_dirs_deg` automatically: for sequential
detections of the same species across camera pairs within a plausible travel time, take the bearing
from the earlier camera. The herd tells you its own approach lines. Present the seeded arcs for
one-tap confirmation rather than asking anyone to draw arrows on a map.

**Wind advice is logged as a gate with its own outcome column**, so the sit log can eventually
falsify the guide's rule on the same terms as everything else. The guide conceded this.

---

## 5. Validation — and the finding that reframes it

Everyone demanded a scoring loop. The red team then showed, correctly, that scoring against **sit
outcomes** is hopeless at this scale. Simulated Brier Skill Score confidence intervals at a
realistic skill level:

| Logged sits | BSS 90% CI (true BSS = 0.05) | Verdict |
|---|---|---|
| 25 | [−0.095, +0.188] | indistinguishable from useless |
| 40 | [−0.058, +0.157] | indistinguishable |
| 80 | [−0.028, +0.125] | indistinguishable |
| 150 | [−0.006, +0.104] | indistinguishable |
| 310 | [+0.011, +0.089] | distinguishable |

At 35–45 sits per season, that is **4–8 seasons**. The "You vs GameSense" scoreboard is therefore
statistically meaningless in season one, and it is cut.

**But the primary estimand is not scored against sits.** It is scored against **camera-nights**,
which arrive automatically:

| Camera-nights | BSS 90% lower bound (true BSS = 0.05) | Verdict |
|---|---|---|
| 150 (1 camera, 1 season) | −0.006 | not yet |
| 375 (5 cameras × 75 nights) | **+0.015** | distinguishable |
| 750 (5 cameras × 1 season) | **+0.024** | distinguishable |

**This is the hinge of the redesign.** Five cameras over one season produce ~750 scoreable
observations with **zero human input**. Forecast and score the thing you can observe automatically;
never claim to forecast the thing you cannot.

### The validation gate

Nothing reaches the screen without passing all four:

1. **Forward-only prequential scoring** on ≥30 evaluated camera-nights, written by a T+1 job.
2. **Brier Skill Score > 0** against *both* per-camera climatology and persistence ("seen here in
   the last 3 nights"), plus a reliability diagram with slope in [0.7, 1.3].
3. **Any environmental term must beat its own null**: ≥95th percentile against 500 circular
   block-permutation shuffles (shift ≥30 days — preserves autocorrelation and seasonality, destroys
   the night-specific weather link). The noise floor is **printed on screen**: *"noise floor for
   this dataset: 57%."*
4. **The reference class is a stored field on the payload**, not prose that can drift.

---

## 6. The model — and an honest expectation of its value

### Specification

```
logit P(Y(c,s,n) = 1) = α_s + b_(c,s) + f_s(doy) + g_s(t_sunset) + β_s · moonlit_minutes_in_W

b_(c,s) ~ Normal(0, σ_s)      partial pooling across cameras — fixes the winner's curse
f_s(doy)                       RW1 spline on day-of-year: a FIXED CONTROL, never a learned feature
g_s(t_sunset)                  circular KDE on sun-anchored time (Ridout & Linkie 2009)
β_s ~ Normal(0, 0.35)          standardised; weakly informative
```

Partial pooling is the specific fix for a measured pathology: with six *identical* cameras at true
p = 0.30, taking the maximum of six noisy ratios yields a mean headline of 0.409 — a bias of +0.11 —
and at p = 0.45 the current code says GO 97% of the time.

Day-of-year enters as a **fixed control, never a learned feature**. A gradient-boosted tree given
day-of-year-collinear inputs will happily fit rut and montanera into "pressure" and "temperature" and
produce a confident, biologically empty model. `docs/06-forecasting.md`'s LightGBM plan should be
struck: at one estate you gain ~365 nights a year and the dominant covariate is seasonal, so
hierarchical pooling beats a GBT here *permanently*, not temporarily.

### The honest expectation

The red team's power analysis applies to the covariates too. Iberian synoptic autocorrelation is
3–5 days, so ~180 nights gives ~40–45 effective independent weather draws. Detectable standardised
effect at 80% power is ~0.45 sd; published weather effects on ungulate activity are 0.05–0.15 sd.
**Underpowered by roughly an order of magnitude.**

After the prior does its work, every environmental coefficient will shrink toward zero and the
posterior predictive will approximate *per-camera base rate + diel curve* — which is six hours of
SQL, not a sampler.

**Therefore the sequencing is:**

1. **Ship the baseline first**: per-camera base rate with partial pooling + sun-anchored diel curve.
   This is cheap, honest, and is very likely the best available model this season.
2. **Build the exposure table and the scoring loop** — these have value regardless of which model
   sits on top.
3. **Only add the sampler when the gate can actually be passed.** If the hierarchical model cannot
   beat the baseline on prequential Brier, it does not ship. That is a real possibility, and the
   plan treats it as the expected outcome rather than a failure.

---

## 7. Exposure — the foundation everything rests on

Built first. Every other number depends on it.

**Night window:** `N(c,n) = [sunset(c,n) − 60 min, sunrise(c,n+1) + 60 min]`, read from stored
`EnvSnapshot.sunset`/`sunrise`. This also fixes defect D7 — the night-boundary mismatch — because
detections and covariates finally key on the same interval.

**Per camera-night state:**

| State | Definition | Treatment |
|---|---|---|
| `CONFIRMED` | ≥1 frame (empty or not) inside `N`, with `processed_at NOT NULL` — or a forced daily time-lapse frame | Real observation |
| `PRESUMED_UP` | No frames in `N`, but frames in both `N(c,n−1)` and `N(c,n+1)` with a matching background hash | Admitted as a true zero |
| `UNKNOWN` | Otherwise | **NULL** — excluded from the likelihood, excluded count displayed |
| `UNPROCESSED` | Any frame in `N` with `processed_at IS NULL` | **NULL** — kills the "backlog reads as zero animals" artefact |

Materialise as `camera_night(camera_id, night, exposure_state, frames, empty_frames,
window_minutes_covered)`.

**The empty-frame stream is the most valuable data in this system, and it is currently discarded as
noise.** Every blank frame is proof that the camera was alive, aimed and triggering at a known
second. It is the only per-camera liveness evidence that exists — `SyncLog` rows carry no
`camera_id` (D16). Forcing one daily time-lapse frame per camera converts this from an inference
into ground truth.

The field-ops specialist demanded pure NULL for missing nights; the ML engineer objected that
informative zeros are data. **Resolution:** a zero is admitted only when the camera is *provably*
up — bracketed by frames either side, or a time-lapse frame. Otherwise NULL. Both conceded.

---

## 8. Metrics — what replaces the percentages

Challenged, per the brief. Nothing survives unless it changes a decision.

| Deleted | Replaced by |
|---|---|
| `confidence = 30 + nights_present × 2` | **Nothing.** No second number on the card. Deleted, not fixed — two probabilities on one card is one too many, and users read the larger one as the verdict. |
| Bare `probability` percentage | **Natural frequency with the reference class in the sentence**: *"On the 38 nights this camera was up, boar showed on 11."* |
| `share_pct` of the best window | Deleted — the maximum of 24 overlapping 3-hour windows can never fall below 12.5%; it is not a statistic. |
| Driver `effect_pct` and `confidence` | Percentile against the variable's own block-permutation null, with the noise floor printed. |
| 7-night outlook probabilities | A moon-and-daylight strip with **no probability at all** until a real covariate model exists. |
| GO / MARGINAL / SKIP | **BEST ODDS / WORTH A LOOK / QUIET / NO DATA** — descriptive of the ground, not imperative to the hunter. Cut points from the model's own tertiles over 30 nights, not hardcoded at 0.5/0.2. |

**New decision products** (definitions are exact; units stated):

| Metric | Definition | Decision it drives |
|---|---|---|
| **Dot strip** | 20 dots from Beta(k+½, n−k+½) on that camera's own confirmed nights | Go or not — *and* whether the model is entitled to an opinion. A 4-night camera renders as a cloud spanning the axis. |
| **Percentile rank** | Tonight's estimate vs this camera's last 30 exposed nights | *"Tonight is the 78th-best night this season"* changes behaviour; "62%" does not. |
| **Value of Waiting** `VoW(k)` | `max(j≤k) E_j − E_tonight`, in the same units as E | The *"wait until Thursday"* the app currently cannot say. Shown only when materially positive. |
| **Δ since yesterday** | Last night's independent visits per deployment vs that deployment's trailing-30-night median over confirmed nights | The one comparison the hunter cannot make from memory. |
| **Burn half-life** *(future)* | Exponential recovery of a camera's rate over the 1–14 nights after a logged sit, vs matched non-sit nights | Rest it or sit it. Requires ~25 logged sits per stand — late season two at the earliest. |

`NO DATA` as a fourth state is not cosmetic. A `SKIP` verdict on a camera with no recent data is a
hardware report, not a hunting recommendation. Likewise the `recent_nights == 0 → −0.15` penalty is
an offline penalty wearing a biology costume, and is deleted.

---

## 9. AI explanation framework

The current "WHY" is a list of `+++` / `--` glyphs. They read as an additive ledger over what is
actually a multiplicative model, they are unlabelled ordinal marks, and users will do arithmetic on
them. Deleted.

**Four rules for every explanation the app produces:**

**Rule 1 — Every claim names its evidence and its sample.** Not *"boar are active on dark nights"*
but *"boar came past on 11 of the 38 nights this camera was up."*

**Rule 2 — Every claim names its reference class in the same sentence, not a footnote.**
> *"That's what the camera sees over a whole night. You'll be there three hours, and the wind is
> yours to solve."*

**Rule 3 — Explanations are ranked by how much they moved the answer, and state the direction and
the mechanism.** A factor that did not move the estimate is not shown, however interesting.

**Rule 4 — The app states the limits of its own competence explicitly.** The light-wind wind line
(§4), the `NO DATA` state, the printed noise floor, and *"nothing changed — same as the last few
nights"* are all instances of the same rule. **An advisor that says "I don't know" on the nights it
doesn't know is the only kind whose "I do know" is worth anything.**

**Handling a miss.** Persist the forecast at issue time so the app cannot silently rewrite what it
said. The morning after a blank recommended night:

> *"We said 11-in-30 here. Tonight was one of the 19. Nothing went wrong — that's what 11-in-30
> means."*

Pre-registering the miss rate *before* the miss is the strongest available inoculation against
algorithm aversion.

**Handling an override.** If the hunter sits a QUIET stand anyway:
> *"Quiet call from us — you're the experiment. Tell us what you saw."*

Log it, and surface it later: *"You've beaten our QUIET calls 4 times at Roble Bajo. We're wrong
about that stand."* Never shame, and never withhold the verdict on a night the hunter overrode.

---

## 10. Data collection improvements

Ordered by value per unit of human effort — because human attention is the binding constraint, not
compute.

### Free (no human input at all)

1. **Forced daily time-lapse frame per camera** — converts exposure from inference to ground truth.
2. **Persist `originDate`, `received_at`, timezone offset and a `time_quality` enum**
   (`exif` / `origin` / `transmit` / `fabricated`). **Never fabricate a timestamp** (D9). Exclude
   non-`exif`/`origin` timestamps from every hour histogram.
3. **Burst collapse into independent events** — same camera, same species, 30-minute quiet interval.
4. **`CameraTelemetry`** append-only (battery, signal, timestamp) so "was this camera alive on
   3 March?" becomes answerable.
5. **Background-hash monitoring** — a step change in the daily median perceptual hash detects a
   knocked or re-aimed camera; falling Laplacian variance detects a web or condensation.
6. **Compute `moon_rise`/`moon_set`** into the columns that already exist.
7. **Store `species_conf` usage** — currently stored and used in no statistic. Gate sex- and
   class-derived claims on it; say "unsexed" below threshold rather than printing "Stag ×12".

### One-time human input, per stand (~15 minutes each, once)

8. **`Stand` records**: name, position, shooting arcs, approach arcs (auto-seeded from cross-camera
   sequences and confirmed with one tap), boundary offset, vehicle drop point.

### Per-sit — **hard budget: one interaction**

9. **The claim.** Claiming a stand is the capture mechanism, not the log. It has a *selfish* payoff
   — you claim to get the wind verdict, the legal-light window, and the "is anyone else on that
   ridge" check — so the row is written *before* the sit, when the phone is out and hands are clean.
   It exists whether or not the hunter ever reports an outcome.
10. **The outcome**, via Sit Mode: one tap = seen, long-press = nothing. Unanswered after 48 h
    becomes `unreported` — **never** `blank`.

### Realistic completion, stated honestly

| Capture point | Expected completion |
|---|---|
| Unprompted log entry | 10–20% |
| Sit Mode tap on a *claimed* sit | 50–60% |
| Harvest with a precinto number | 90%+ (it is already legally required paperwork) |

So the outcome log will be ~40% complete and **biased toward successes**. Consequences, applied
throughout:

- **Never impute a blank.** Missing is missing.
- **Keep two estimands permanently separate**: camera-night detections (complete, no missingness,
  ~750/season) and sit outcomes (incomplete, always displayed with `n` and completion rate).
- **Selection correction at one estate's sample size is a fantasy.** Say so on screen.
- Burn half-life and the "what the hunter picked before we spoke" baseline depend on the **claim**
  alone, so they survive a low outcome-reporting rate intact.

---

## 11. Entry criteria — when each future capability unlocks

No capability ships on enthusiasm. Each has a stated, checkable gate.

| Capability | Gate |
|---|---|
| Verdict labels (BEST ODDS etc.) | ≥40 CONFIRMED camera-nights for that camera **and** BSS > 0 vs climatology |
| Any environmental coefficient on screen | ≥95th percentile vs its own block-permutation null **and** 90% posterior interval excluding zero **and** improved out-of-sample Brier |
| Moon-in-window term | The above, plus ≥10 lunations of clean exposure data |
| Negative-binomial visit layer | Poisson log-score beats the Bernoulli-derived `P(≥1)` out of sample |
| Stand-vs-camera ratio ρ | ~200 logged sits — 3–5 seasons. Probably never as a single number. |
| Burn half-life per stand | ~25 logged sits at that stand |
| Rank agreement (app vs hunter) | ~35 logged blind picks |
| "You vs GameSense" scoreboard | ~310 logged sits. **Cut from the roadmap** — do not build it. |

**Temperature's gate is different and cheap**: run the bbox-area-vs-ambient-temperature regression on
data already in the database. If detection distance shrinks on hot nights, temperature is refuted as
an activity driver and is confined to the detection layer permanently.

# Deliverable 7 — Forecasting & Recommendation Architecture

The forecasting layer turns detections + environment into the product's reason to exist: the **Tonight card**. Design rule from the spec — *start simple and honest, beat a fragile neural net with calibrated gradient-boosted trees, and show the model its own track record.*

## What we predict

| Output | Granularity | Used by |
|---|---|---|
| Species presence probability | per camera/stand × species × night | Tonight card, Forecast page, Map |
| Best time window | per camera/stand × species × night | Tonight card |
| Individual presence probability | per individual × night | Animal page, target alerts |
| Multi-day outlook | tonight / tomorrow / 3-day / 7-day | Forecast page |

## Model

- **Primary:** gradient-boosted trees (**LightGBM**), one model per `(camera, species)` for presence, trained on historical hourly buckets: target = "≥1 detection of species S at camera C in hour-bucket T." Predicts per-hour probability → aggregate to a nightly probability and extract the **best contiguous window**.
- **Why GBT:** robust on small/medium tabular data, handles nonlinear interactions (moon × hour, wind × season), gives feature importances that become the card's **"why."** No fragile deep net on sparse data.
- **Individuals:** sparser data → a lighter model with Bayesian smoothing toward the species model, conditioned on that individual's own sighting history and recency.

### Features (built from `env_snapshots` + detection history)

Temporal: hour-of-night, minutes-from-sunset, day-of-year/season. Lunar: illumination %, phase, moonrise/set proximity, darkness minutes. Weather: temp, pressure **and pressure trend**, wind speed/gust, **wind direction relative to stand approach geometry**, rain, cloud cover. Activity: detections at this camera over trailing 3/7/14 days, days-since-last-seen (per species and per individual).

## Calibration & trust

- Probabilities calibrated (isotonic / Platt) so "76%" means 76%.
- Every forecast is later scored against what actually happened (`forecast_outcomes`) → surfaced as **"predictions verified correct 71% of nights."** This is both honesty and a trust/marketing asset.

## Cold start (the empty state matters)

Before ~30 nights of data, the GBT is unreliable. We fall back to a **transparent heuristic** — crepuscular base rates (dawn/dusk priors) adjusted by moon illumination, darkness, and wind-safe geometry — and the Tonight card explicitly shows a **learning meter** ("14 nights of data — predictions sharpen after ~30"). We never fake precision we don't have.

## Wind-safe analysis (per stand)

Pure geometry, high value, no ML: given the forecast `wind_dir_deg` and the stand's `approach_dirs_deg` (where animals come from) and `shooting_dirs_deg`:
- Scent carried **away** from approach routes → **Favorable**.
- Scent carried **toward** likely approach → **Risky / Bad** (flag "avoid this stand tonight").
Rendered as a verdict + arrow on the Tonight card and as a per-stand layer on the Map.

## Recommendation engine (assembles the card)

For tonight, for each stand: combine presence probability + wind-safe verdict + moon/darkness + best window into a single score → **GO / MARGINAL / SKIP** with confidence, the recommended stand, two alternates, and the **3–4 driving factors** as plain text. Stands with bad wind are surfaced as "avoid." This is the literal answer to the spec's questions: *where, when, which animal, which stand, which wind, which stand to avoid.*

## Differentiating intelligence (Tier 2)

- **Multi-camera movement:** PostGIS proximity + plausible time gaps across cameras infer probable corridors ("Camera A 22:00 → B 23:15 → C 01:10 — likely same animal"), always probabilistic.
- **Correlations as sentences:** periodic analysis emits plain-language statements with strength + sample size ("Boar arrive ~40 min later within 3 days of full moon — moderate confidence") into `correlations`.
- **Pattern-break detection:** a regular individual going quiet, or a seasonal shift, raises an insight/alert.
- **Opportunity alerts:** tonight's feature vector lands in the top decile of historical success → notify ("conditions in top 10% of past successful nights").

## Nightly job

`forecast.nightly` (Celery beat): refresh feature tables → retrain/update models incrementally → write `forecasts` for tonight + horizon → score yesterday's forecasts into `forecast_outcomes` → refresh `correlations` → fire any opportunity/target/pattern-break alerts.

## Tests (third risky bit, per spec)

Forecasting gets tests on the feature builder (correct env join on `captured_at`, no leakage), the wind-safe geometry (known wind/approach combos → expected verdict), and calibration plumbing (outcomes scored correctly).

## As built (September 2026, plan items 9–11)

The design above is where this started; what Tonight, the alerts and Insights actually do now:

- **Nights, not dates.** Every count uses the night key (18:00 → 06:00, keyed by the evening; `exposure.night_expr`, `exposure.current_night`). A boar at 23:40 and again at 00:20 is one night. "Recent" is the last 7 nights that are over, never the one under way.
- **Only watched nights count.** "Seen X of Y nights" divides by the nights the camera was demonstrably watching (`camera_nights` CONFIRMED or PRESUMED_UP). A night the AI hasn't checked, or one the camera was out of credits or dead, is left out and named in the footnote for that camera ("7 nights at Cerro left out: photos not checked yet"). Only a gap of at most two frameless nights between nights with frames is presumed watched; a longer silence is unknown.
- **Visits, not photos.** Presence, the classes on the card ("Sow + piglets · 12 visits"), the alerts and Insights count visits (`visits.visit_rows`: frames of one species less than 30 minutes apart are one arrival). Each visit is of one class (`visits.class_visits`): the most telling label among its frames (sexed or grouped over the plain species), then the one most frames carry, so the classes of an animal add up to its visits on Tonight, the map and Insights. Photo counts sit behind "Show the numbers".
- **Ranking.** Cameras that can be judged (15+ watched nights) rank first; "Not enough to say" is the headline only when no camera can be judged. A camera with no photo for over 7 days is left out of the ranking and listed as such. An admin can **Retire** a camera (Cameras → Details); a retired camera is out of the plan, the alerts, Insights, the exposure rebuild and the track record, and its photos stay.
- **The recency nudge** (+0.10 when the animal came on 4+ of the last 7 nights, −0.15 when it came on none) applies only when the camera is sending and at least 4 of those 7 nights were watched.
- **Hidden stays hidden.** One predicate (`api/visibility.VISIBLE_SIGHTING`, and `visits.CHECKED_ANIMAL` for visits) is on every forecast, alert, insight, pattern, scoring and push query: a species hidden in Settings, or a photo marked "nothing in it", never counts. Marking a photo recounts that camera's nights and grades an already-graded night again.
- **Track record per verdict.** Claims are matched to cameras by id and graded on 18:00–06:00 of their night (from the moment the claim was made, if later). What shows is what the hunter read, per camera claim: "When it called a camera Best odds, animals came there 7 of 9 times" (with four cameras, 14 nights are 56 claims), after 14 scored nights and 5 claims of that verdict; "Not enough to say" is not graded. Whether the odds beat each camera's own usual rate is said after 30 nights.
- **Weather and moon: no finding unless it beats chance.** The series is visits per watching camera on watched nights only. Each condition's high third is compared with its low third (the middle bar is shown, never tested), on each night's visits less the average of the moon cycle of dates around it, so a season that drifts (boar building up on the acorns, nights lengthening) is not "more wild boar on long nights". A difference is only stated when it is bigger than 95% of the biggest differences seen in 200 week-block shuffles of the same season, across all conditions and animals, and points the way the bars do; it is worded from the two ends that were tested ("More wild boar on a dark moon than on a bright moon."). Everything else is "Could be chance" behind the fold. When the thirds tie (a dry autumn: two nights in three read 0 mm) the nights at the common reading are compared with the rest (dry against wet); with too few of those it says "Too few wet nights to compare". The weather history is never a long wait: nights fetched before are served at once and the rest fetched in the background; only a first visit waits, 6 seconds at most. A failed fetch is retried after 10 minutes and said as "Weather history unavailable right now".
- **Alerts** never work the plan out again; the plan's own "Cameras not sending" card carries the offline/out-of-credits/silent cameras and those whose photos are not coming in, the line above the plan names a login that stopped, and /alerts adds only what neither can say (a flat battery on a camera still sending, sightings in visits, a usually-busy camera quiet on its last watched nights).

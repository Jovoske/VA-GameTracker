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

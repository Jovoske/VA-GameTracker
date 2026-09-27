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
- **Visits, not photos.** Presence, the classes on the card ("Sow + piglets · 12 visits"), the alerts and Insights count visits (`visits.visit_rows`: frames of one species less than 30 minutes apart are one arrival). Each visit is of one class (`visits.class_visits`): the most telling label among its frames (sexed or grouped over the plain species), then the one most frames carry, so the classes of an animal add up to its visits on Tonight, the map and Insights. The plain species is called by its name in Settings, as its tiles are, so an admin's rename reaches the classes and the Insights photos behind them. Photo counts sit behind "Show the numbers".
- **Ranking.** Cameras that can be judged (15+ watched nights) rank first; "Not enough to say" is the headline only when no camera can be judged. A camera with no photo for over 7 days is left out of the ranking and listed as such. An admin can **Retire** a camera (Cameras → Details); a retired camera is out of the plan, the alerts, Insights, the exposure rebuild and the track record, and its photos stay.
- **The recency nudge** (+0.10 when the animal came on 4+ of the last 7 nights, −0.15 when it came on none) applies only when the camera is sending and at least 4 of those 7 nights were watched.
- **Hidden stays hidden.** One predicate (`api/visibility.VISIBLE_SIGHTING`, and `visits.CHECKED_ANIMAL` for visits) is on every forecast, alert, insight, pattern, scoring and push query: a species hidden in Settings, or a photo marked "nothing in it", never counts. Marking a photo recounts that camera's nights and grades an already-graded night again.
- **Track record per verdict.** Claims are matched to cameras by id and graded on 18:00–06:00 of their night (from the moment the claim was made, if later). What shows is what the hunter read, per camera claim: "When it called a camera Best odds, animals came there 7 of 9 times" (with four cameras, 14 nights are 56 claims), after 14 scored nights and 5 claims of that verdict; "Not enough to say" is not graded. Whether the odds beat each camera's own usual rate is said after 30 nights.
- **Weather and moon: no finding unless it beats chance.** The series is visits per watching camera on watched nights only. Each condition's high third is compared with its low third (the middle bar is shown, never tested), on each night's visits less the average of the moon cycle of dates around it, so a season that drifts (boar building up on the acorns, nights lengthening) is not "more wild boar on long nights". A difference is only stated when it is bigger than 95% of the biggest differences seen in 200 week-block shuffles of the same season, across all conditions and animals, and points the way the bars do; it is worded from the two ends that were tested ("More wild boar on a dark moon than on a bright moon."). Everything else is "Could be chance" behind the fold. When the thirds tie (a dry autumn: two nights in three read 0 mm) the nights at the common reading are compared with the rest (dry against wet); with too few of those it says "Too few wet nights to compare". The weather history is never a long wait: nights fetched before are served at once and the rest fetched in the background; only a first visit waits, 6 seconds at most. A failed fetch is retried after 10 minutes and said as "Weather history unavailable right now".
- **Alerts** never work the plan out again; the plan's own "Cameras not sending" card carries the offline/out-of-credits/silent cameras and those whose photos are not coming in, the line above the plan names a login that stopped, and /alerts adds only what neither can say (a flat battery on a camera still sending, sightings in visits, a usually-busy camera quiet on its last watched nights, by the Changed line's own rule, `changes.quiet_cameras`: at least one visit on a usual watched night and none on the last three, so Tonight can't say "Nothing changed" beside "Puente quiet").

## As built (September 2026, plan items 7 and 8)

- **One wind verdict** (`forecasting/conditions.wind_verdict`). Tonight, a reservation, Sit mode (`GET /stands/{id}/wind`), Stands and the map all judge a stand with the bedding and thermals model (`bedding.stand_wind_report`): scent against the drawn bedding, and on a calm evening against the slope's cold-air drainage. A stand off the map or with no bedding drawn falls back to its approach arcs if it has any; otherwise it says what can't be judged ("No bedding drawn yet…"), and a missing forecast reads "No wind forecast tonight", never calm. Tonight judges the stand linked to its top camera, or the nearest placed stand within 500 m, and names it.
- **Judged at sit time.** The wind, the thermals, the scent-safe shading and the moon are for 45 minutes after tonight's sunset, or for now once that has passed, until 06:00 (`conditions.sit_time`). From 06:00 "tonight" is the coming evening, so a plan, the map or a reservation made at 07:00 is judged for this evening's sit, never for the dawn air; a dawn sit still on after 06:00 asks for the air now (`GET /stands/{id}/wind?sit=<id>`). Every verdict carries that time (`at_local`, "for 20:41"), said only under a call (not under "Not on the map yet" or "No bedding drawn yet"), and a reservation keeps it (`sits.wind_at`), so Sit mode and Stands say "when you reserved at 17:05, for 20:41". A sit also carries its sunset and sunrise, so Sit mode shows them with no signal. "Tonight" is the night key: at 00:30 it is the night under way, and sunrise and sunset are compared as instants on the estate's calendar day, so the dark before dawn drains downhill.
- **Fresh forecast.** A forecast day is fetched again after 30 minutes; if Open-Meteo doesn't answer, the last good copy is served, marked stale with when it was fetched, and nobody waits on it again for 10 minutes. The pause is per service (the archive for old photos, the forecast for tonight), and a refusal (4xx) pauses only the day asked for. One fetch at a time: the others serve the copy there is, called stale only if the last try failed. 5 s timeout (3 s to connect), hours matched as instants (`timeformat=unixtime`, so 25 Oct has two 02:00 hours). The forecast is fetched with the request's database transaction ended, so a hanging Open-Meteo never holds a pooled connection.
- **Scent cone against the outline.** The cone is tested against the bedding's edges exactly (`geo.cone_reaches_polygon`), and distances are to the nearest edge, not the nearest corner. The scent-safe shading uses the same plume as the stand verdicts, each drainage square with its own slope.
- **Best hours follow sunset.** Each visit is placed by its minutes after its own night's sunset (quarter-hour steps, the last three weeks counting double the three before), the best three hours are found in that frame (starts somebody can sit, the visits centred when several starts hold them all), and put back on the clock with tonight's sunset, to the quarter hour: "Best hours 19:45 to 22:45, from 15 min before sunset". Animals never seen at an hour somebody can sit get no best hours, and the why says so. Insights' "busiest between" moves each visit the same way (evening ones by sunset, morning ones by sunrise), so its hours are tonight's too. Tonight and Sit mode show "Sunset 19:56". The dark exit is placed the same way, in visits, from 3 h after sunset. No legal-light rule is applied (owner decision).
- **Suntek clocks.** The mail receiver records the mail server's receipt time (INTERNALDATE); the importer puts right a capture time a whole 1–2 hours after the receipt (a camera that missed the clock change), says so on the camera card, and files anything else impossible at its receipt time. A camera known to be fast has a photo stamped more than 2 minutes after its receipt (a late upload) put right by its known hours, and the card's warning goes only after three photos in a row arrive on time (up to 5 minutes after they were taken, or stamped at most 2 minutes after arriving: a clock set right by hand, a little fast). Each photo keeps its receipt time (`images.received_at`), and the Cameras page says how long a camera's photos take to arrive (the median of its last 50): an hour there is a clock running an hour slow, which the import can't tell from a slow upload.

## As built (September 2026, feature 22)

- **The wind hour by hour** (`forecasting/wind_week.py`, `GET /forecast/wind-week`, `?stand=<id>` for one). Every stand is judged at every hour from 17:00 to 24:00, tonight and the next six evenings, with the one wind verdict above (`conditions.wind_verdict`): the same bedding, slope drainage and scent cone, so the hour of tonight's sit on the strip says what Stands, the map and Sit mode say. The week's forecast is one Open-Meteo call (`weather.forecast_hours`), kept in the same day copies `weather_at` reads, so Tonight's wind at the sit and its hour on the strip are the same forecast.
- **One line up front.** "Right wind for Charca: tonight 19–21 h, Thu, Sat": tonight's right hours still to come (the hour under way counts), then the evenings with at least two right hours in a row. Right is the verdict "clean"; too light to call is not right. A stand that can't be judged says why instead ("isn't on the map yet", "No bedding drawn yet"), and no forecast reads "No wind forecast for the week yet", never calm. After midnight the week starts at the coming evening.
- **Kept for the hour.** 56 verdicts a stand is real work, so an answer is kept until the hour turns, and made again sooner only when what it rests on changes: a stand moved or its arcs set, bedding drawn or redrawn, the hill shape loaded, a newer forecast. Each stand also carries `tonight`, its verdict at the sit, worked out on every call: Stands reads both from this one call.
- **On screen.** Stands shows tonight's wind and the week's line on every card, in room kept from the first paint, with the hours behind "Wind hour by hour": a row an evening, a column an hour, ✓ right, ✗ wrong, ~ too light to call, where the wind comes from under each, the hours gone greyed. Tonight shows the line for the stand its wind line names, with the hours behind "Hour by hour". The phone keeps the last copy for no signal (and the service worker does too), with its age; a copy from an earlier night is dropped.

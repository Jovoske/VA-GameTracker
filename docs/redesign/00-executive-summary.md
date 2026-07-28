# GameSense — Product Review & Redesign

**A cross-functional expert review of the app as it stands, and a redesign built to make hunters
decide better — not to make the app prettier.**

Thirteen specialists reviewed the codebase independently, then cross-examined each other in four
panels, then a red team attacked the resulting consensus. Every load-bearing claim in these
documents was verified directly against the code or by simulation; where a claim did not survive
verification, it was cut or corrected, including claims made by the experts themselves.

| # | Document |
|---|---|
| 00 | **Executive summary** (this file) |
| 01 | [Brutally honest review + verified defect register](01-review-and-defects.md) |
| 02 | [The recommendation engine, rebuilt](02-recommendation-engine.md) |
| 03 | [Product, navigation and screens](03-product-and-screens.md) |
| 04 | [Technical architecture](04-architecture.md) |
| 05 | [Roadmap and prioritised implementation plan](05-roadmap-and-plan.md) |

---

## The verdict in one paragraph

GameSense is a well-built trail-camera triage tool with a statistics screensaver bolted on top. The
parts that work — MegaDetector stripping empty frames, DeepFaune species labels, a clean gallery, an
honest tone in the docstrings — are genuinely good. The part branded as intelligence is a single
ratio (`nights_present / total_nights`) with a wrong denominator, multiplied by coefficients mined
from correlations that a null simulation shows are indistinguishable from noise, displayed next to a
"confidence" figure that is `30 + nights_present × 2`. The app has never been wrong, because it has
never recorded a prediction or an outcome: `Forecast`, `ForecastOutcome`, `ModelRun`, `Correlation`
and `Stand` all exist in the schema and are written by **zero lines of code**. The design documents
in `docs/` specified the right things — wind-safe geometry, calibration, a nightly scoring job — and
the build skipped all of them in favour of correlation mining. This is not a vision problem. It is
an execution problem, plus one category error.

## The category error

**The app predicts whether a camera will photograph a species somewhere in 24 hours. The hunter is
asking whether they will see a shootable animal during a three-hour sit.**

These differ by a large and unknown factor. Every number, threshold, verdict and alert in the
product inherits that mismatch. No amount of additional data fixes it, because the two quantities
measure different events.

## The five findings that mattered most

Each was verified by the moderator, not merely asserted.

**1. The behaviour-driver engine cannot distinguish signal from noise.** Running the real `_driver()`
code on counts generated to be statistically *independent* of every covariate:

| Nights | ≥1 "driver" found | Median reported effect |
|---|---|---|
| 15 | 95.5% | 108% |
| 30 | 99.5% | 72% |
| 45 | 99.8% | 55% |
| 90 | 97.8% | 46% |

The code advertises `MIN_EFFECT = 15.0` as its noise floor. The true floor is 3–7× higher.
"~40% more activity on rising pressure" is the *expected output of pure noise*, and roughly half of
these phantom drivers clear the confidence threshold that feeds `tonight_multiplier` straight into
the user-facing verdict.

**2. Weather is joined to the wrong night.** `_overnight_weather` keys a night by its evening date
(18:00 D → 06:00 D+1); `_nightly_activity` keys detections by calendar date. Every post-midnight
detection — the bulk of nocturnal boar activity — is paired with the *following* night's weather.
The join itself is wrong, independently of every statistical objection.

**3. Missing data is silently converted into "no animals."** A flat battery, a lost cell signal, a
full card, a spider web, a camera knocked by a boar, or simply a night whose frames have not been
through `classify_species` yet all produce zero detections — and `patterns.py` walks the date range
imputing `0` for each. `is_empty_frame` is tri-state and `species.py:45` requires `IS FALSE`, so an
unprocessed backlog reads as a confirmed empty night. The system measures its own hardware and
calls it deer.

**4. Half the environmental variables are the calendar wearing a disguise.** `darkness_minutes =
1440 − daylight` is a deterministic function of day-of-year, and overnight temperature in Albacete
is nearly so. Correlating them with activity detects rut, montanera and camera deployment, then
labels the result "Dark hours" and "Temperature". **The moon is the exception** — it completes ~5.1
cycles in a 150-night season, giving `corr(day-of-year, illumination) = −0.12`. That single
measurement overturned two experts' round-one positions: the biologist's "delete the moon outright"
and the statistician's "no environmental effect is estimable, full stop" are both too strong.

**5. Nothing is validatable — but it can be, cheaply, and not the way the panel assumed.** The red
team correctly showed that scoring against *sit outcomes* is hopeless at this scale: at a realistic
skill level you need 150–310 logged sits (4–8 seasons) before a Brier Skill Score is
distinguishable from zero. But the estimand this review recommends is scored against
**camera-nights** — ~750 per season across five cameras, with **zero human input** — and that is
distinguishable within a single season. This is the hinge of the whole redesign: *forecast and
score the thing you can observe automatically; never claim to forecast the thing you cannot.*

## The product, redefined

> **GameSense is the estate's sit register — who has claimed which stand tonight, whether the wind,
> the law and the other guns permit it, and what came of it — with a forecast that must earn its
> place against that record.**

That makes the camera gallery a feeder, not the product; makes the `Stand` the primary entity and
the camera merely evidence; and makes every statistic subordinate to a decision someone is about to
take.

## What ships, in order

The full ordering, with dependencies and effort, is in
[05-roadmap-and-plan.md](05-roadmap-and-plan.md). The shape of it:

0. **Stop losing data.** A real migration, a backup, and four one-line correctness fixes. Today the
   next `docker compose up` can strand the season.
1. **Stop lying.** Delete the fabricated confidence figure, the noise drivers, the fake 7-night
   outlook. Replace the verdict with a sentence that carries its own reference class.
2. **Stop recommending illegal light.** `astro.solar()` already returns sunset and civil dusk; the
   code throws them away and keeps `darkness_minutes` as an attractant score.
3. **Start recording.** Persist each forecast at issue time; add the claim-and-sit log.
4. **Start scoring** — against camera-nights, automatically.
5. Only then, and only behind a validation gate it may well fail: a model.

## The constraint nobody costed

Thirteen experts each asked the same scarce person for "one small thing": stand bearings, shooting
arcs, deployment metadata, a sit log, arrival and departure times, a four-state outcome, a
pre-commitment wager, harvest entry, precinto numbers, trichinella sample IDs, quota reconciliation,
and a signed season-rules file. That totals roughly **eight discrete entries per sit-night**, imposed
on someone who sits perhaps thirty nights a year and takes their phone out at last light, in the
dark, in gloves.

The panel priced CPU carefully and priced human attention at zero.

**Hard budget for the redesign: one interaction per sit, plus one one-time setup per stand.**
Any feature that needs more must justify itself against that ceiling or not ship. This constraint,
more than any statistical argument, is what shapes the plan in document 05.

## An honest statement of limits

With one season on one estate, this product **can** support: per-camera relative base rates with
partial pooling, diel activity timing anchored to sunset, species composition, a crude seasonal
trend, deterministic legal-light and wind geometry, and an accurate record of what happened.

It **cannot** yet support: a validated weather effect, a camera-to-sit conversion factor, a
hunting-pressure model, individual-animal identity, or a meaningful "you vs the app" scoreboard.
Each of those has a stated entry criterion in document 02. Until a criterion is met, the honest
move is to show the data and say so — not to print a percentage.

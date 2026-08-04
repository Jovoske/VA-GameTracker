# 03 — Product, Navigation and Screens

> Deliverables 3, 4, 5, 7, 8, 9, 10, 16, 17. Output of the interface panel (UX, mobile, data
> visualization, behavioural psychology, hunting guide) after cross-examination, with the red team's
> deletion-risk and effort objections applied.

---

## 1. Product definition

> **GameSense is the estate's sit register — who has claimed which stand tonight, whether the wind,
> the law and the other guns permit it, and what came of it — with a forecast that must earn its
> place against that record.**

Consequences of accepting that sentence:

- The **`Stand`** becomes the primary entity. **Cameras become evidence**, and stop being
  recommendable objects entirely. The architect wanted `Stand` deleted as dead schema; he conceded
  when three other voices independently needed the same entity — safety arcs, wind geometry, and the
  sit register — and when it was pointed out that `Tonight.tsx:183` already labels cameras "OTHER
  STANDS" in the UI, which is the fiction shipping in the one place it can get someone hurt.
- The photo gallery is a **feeder**, not the product.
- Every statistic is subordinate to a decision someone is about to take, tonight.

---

## 2. Features to remove

Removal is justified per item by the decision it fails to change.

### Remove entirely

| Feature | Why |
|---|---|
| **`confidence` percentage** (`model.py:101`, `Tonight.tsx:116`) | `30 + nights_present × 2`. Deleted, not redesigned — the panel was unanimous. It is rendered *larger* than the probability, which is salience inversion of the least meaningful number. |
| **7-night outlook** (`insights.py:_outlook`, `Insights.tsx:80-113`) | One number repeated seven times with a ±0.05 moon wobble. Its hardcoded moon direction can contradict the app's own learned moon driver on an adjacent tab. Fabricated precision is worse than absence. |
| **Behaviour drivers as a product surface** | Shown to be indistinguishable from noise (document 01). The *computation* stays behind an admin/debug view with its permutation null attached; the user-facing card goes. |
| **`tonight_multiplier` feedback path** (`model.py:225-231`) | Feeds those noise coefficients into the headline verdict. |
| **Three lifetime bar charts on Tonight** (`Tonight.tsx:239-289`) | Activity-by-hour (clock-anchored), sightings-by-camera, species. None answer an 18:00 question; together they push the verdict off-screen. |
| **PATTERNS strength bars and driver-confidence bars** (`Insights.tsx:184-186, 216-217`) | `strength` is `share_pct/100` for one statement type and `ratio − 1` for another — different quantities, same pixels, no axis. |
| **The "camera quiet" alert** (`alerts.py:71-76`) | Ignores `battery_pct`, `signal_pct` and `last_sync_at` on the same row. Nine times in ten the camera is dead, not the ground. |
| **The p≥0.7 "Strong night ahead" alert** | Fires on the top camera most nights; a variable-ratio reinforcement schedule pushing sits the hunter would not otherwise take. |
| **`SKIP` as a verdict** | Replaced by `QUIET` (few animals) and `NO DATA` (we don't know). Conflating them is a hardware report presented as hunting advice. |
| **Git self-update panel** (`Admin.tsx`) | A one-command Docker product does not need an in-app updater. |
| **`runner_up`, `_is_nocturnal`, `share_pct`** | Computed, returned, never rendered — or not a statistic. |

### Demote, don't delete

| Feature | New home |
|---|---|
| **Animals page + re-ID** | Off the hunter's navigation entirely; survives as a desktop admin tool. Its own copy admits the model cannot do the job. The PM wanted the code deleted; **the red team's counter is accepted** — deletion is not free, and a working manual merge tool costs nothing to leave in place off the main path. |
| **Insights** | Becomes a strictly **descriptive** "what the cameras saw" page with all causal language stripped. |
| **Cloud sex pass** | Manual, cost-capped, and must persist `unknown` results so re-runs stop re-paying for the same crops (D26). |

### The deletion-risk objection, and the answer

The red team asked: *after deleting everything uncertain, is there enough left to open?*

The answer is yes, and it clarifies the principle. **The objection is to the *causal* surface, not
the *descriptive* one.** An app that shows which camera fired last night, at what hour relative to
sunset, with what in the frame, is worth opening every morning and makes no claims it cannot
support. That floor already exists in this codebase and is not touched by any deletion above.

---

## 3. Navigation

**Current:** a desktop top nav — six links plus a Sign-out button, ~635 px of content in a 390 px
viewport with no wrap, ~33 px targets, top-anchored. Half of it is physically off-screen and none of
it is reachable one-handed.

**Replacement: three bottom tabs, 56 px + `env(safe-area-inset-bottom)`, 48×48 minimum targets.**

| Tab | Contains |
|---|---|
| **Tonight** | The decision. Default route. |
| **Stands** | Per-stand history, arcs, claim status, rest days, sparklines. |
| **Cameras** | The gallery and camera health. |

Settings and Admin move behind a header affordance on Stands. Animals leaves the hunter's build.

Six tabs → three. The mobile designer's hill — *ship the ugly bottom nav before any visual
refinement* — was upheld unanimously: the information hierarchy is already good; the problem is that
the navigation is off the edge of the phone.

---

## 4. The Tonight screen — mock screen description

390 px wide, top to bottom. **Everything above the disclosure renders from the injected shell JSON
before any network call.** Nothing on this screen waits on a fetch.

```
┌──────────────────────────────────────────┐
│ Plan from 18:04 · offline                │  28px, --surface-2, non-dismissible
├──────────────────────────────────────────┤
│                                          │
│  ▲ BEST ODDS · PUENTE                    │  26px/700, shape glyph inline
│                                          │
│  SIT 21:40–23:10 · legal light ends 22:14│  15px
│                                          │
│  WIND SW 12 km/h — clean for Puente.     │  15px, tappable → wind polar
│  Your scent goes down the barranco,      │
│  not across the approach.                │
│                                          │
│  CHANGED: boar back at Puente after      │  15px, "CHANGED:" 11px caps dim
│  6 quiet nights.                         │
│                                          │
│  DARK EXIT 23:35 — out east, wind on     │  15px
│  your left cheek.                        │
│                                          │
│  ●●●●●●●●●●●○○○○○○○○○                    │  28px, 20 dots, 11 filled
│  On the last 20 nights this camera was   │  13px
│  up, boar came past on 11.               │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │           START SIT                │  │  56px, full width
│  └────────────────────────────────────┘  │
│                                          │
│  Why this stand                        › │  44px disclosure row
├──────────────────────────────────────────┤
│  OTHER STANDS                            │
│  ◐ Solana      7/20                      │  no percentages
│  ○ Roble Bajo  2/20                      │
│  ▨ Charca      no data                   │
├──────────────────────────────────────────┤
│   Tonight   │   Stands   │   Cameras     │  56px + safe area
└──────────────────────────────────────────┘
```

**Every element justified by a decision:**

| Element | Decision it changes |
|---|---|
| Freshness chip | Whether to trust what follows. In EFB and triage design, the age of data *is* data. Turns `--alert` above 12 h. |
| Verdict + stand name | Where to go. The guide's concession from the dataviz panel: *"a dot cloud does not name a stand"* — position encoding goes **under** the name, never instead of it. |
| Sit window + legal light | When to arrive, and whether it is legal. Currently absent despite `astro.solar()` already returning both. |
| Wind line | Which stand, and whether to divert. Declares its own competence boundary below 8 km/h. |
| CHANGED | The only comparison a hunter cannot make from memory. Computed server-side, **never blank**. |
| DARK EXIT | How to leave without burning the stand — the guide's point that no app models the exit. |
| Dot strip | Go or not, *and* whether the model has earned an opinion. Satisfies dataviz (position + interval) and psychology (natural frequency, reference class) in one element. |
| START SIT | The one budgeted interaction per sit. |

**What is *not* on this screen:** any percentage, any confidence figure, any lifetime chart, any
species totals.

### Terminology changes

| Old | New | Reason |
|---|---|---|
| GO / MARGINAL / SKIP | **BEST ODDS / WORTH A LOOK / QUIET / NO DATA** | Descriptive of the ground, not imperative to the hunter. No promise to break, no one to blame, agency retained. Adds the missing "we don't know" state. |
| "stand" (meaning camera) | **camera** — and `Stand` becomes a real, separate entity | Safety. Cameras go where animals go; stands exist where a bullet can safely stop. |
| "confidence" | *(deleted)* | Two competing scales, neither meaningful. |
| "sightings" | **detections** (frames) vs **visits** (independent events) vs **animals** (`group_size`) | Currently all three are called "sightings" and counted as frames. |

---

## 5. Colour and visual hierarchy

Verdict colours were measured, not eyeballed:

| Pair | Contrast |
|---|---|
| `--go` `#3FB950` vs `--marginal` `#E3A008` | **1.12:1** |
| `--go` vs `--skip` `#E5534B` | **1.46:1** |
| Replacement pair proposed in review (`#2E9E43`/`#F0C674`) | **2.14:1** — still below 3:1 |

Three verdict states **cannot** be separated by colour alone against `#0E1311`. Under a 660 nm red
headlamp the situation is worse than degradation: `--go` reads near-black and `--skip` reads white,
so the dots **invert meaning**.

**Therefore: word + shape are load-bearing; colour is a redundant third channel.**

| State | Glyph | Token |
|---|---|---|
| BEST ODDS | `▲` | `--v-best #6FCB7F` |
| WORTH A LOOK | `◐` | `--v-look #F0C674` |
| QUIET | `○` | `--v-quiet #8A9A92` |
| NO DATA | `▨` | transparent + 2 px `--text-dim` 45° hatch |

`--skip #E5534B` is **retired from verdicts** and reserved exclusively for legal/safety refusal —
the guide's point that if red also means "few pigs," the one time it means "don't take that shot"
it will be read past. A new `--alert` token stops severity `high` from borrowing `--go`, which
currently makes green mean both "go hunt" and "urgent" in adjacent cards.

**Night mode**, auto after sunset: true black `#000000` (OLED — a non-black background is a lit
rectangle in a dark high seat, costing both battery and concealment), amber monochrome `#FFB000`
family, in-app brightness scrim below the OS minimum.

---

## 6. Charts — keep, kill, rebuild

| Chart | Verdict | Detail |
|---|---|---|
| Activity-by-hour histogram | **Rebuild + relocate** | Clock-anchored hours smear as sunset drifts ~3 h across a season, and the ticks at `hour % 6` never label the peak. Becomes a **sunset-anchored actogram** and moves to Why/camera detail. Dataviz conceded the flagship chart is one level down, not on Tonight. |
| Sightings-by-camera bars | **Rebuild + relocate** | Raw counts across cameras with unequal uptime is a chart of deployment history. Becomes sparkline rows on Stands: **length encodes rate** (detections per 100 camera-nights), **printed numeral is the raw count**, **downtime is hatched**. Two channels, no lie — this resolved the rate-vs-count dispute without either side losing. |
| Species bars | **Kill** | Two species on the estate. A bar chart of two categories is a sentence. |
| 7-night outlook | **Kill** | See §2. |
| Strength / confidence bars | **Kill** | Not statistics. |
| Map bubble sizing | **Fix** | `min(44, 18 + √n × 2)` — the `+18` offset and the 44 px clamp destroy the area-proportionality `√` was there to provide. Use `r = 6·√rate`, no offset, no clamp, with a 44 px transparent hit area. |

### New charts

**A. Sunset-anchored actogram** *(Why / camera detail)*
y = night, one 3 px row, newest at top. x = hours relative to local sunset, −2 h to +12 h. Fill =
quantile-binned detections, 5 bins, sequential single hue. **Nights with no frames at all render as
4 px diagonal hatching** — so "camera was down" is visually distinct from "camera was up and saw
nothing," which is exactly the distinction the current model cannot express. Civil dusk and moonrise
overlaid as 1 px sweeping lines. Small-multiple per camera on a shared x-scale.

This is standard chronobiology practice, it is the correct chart for this data, and it costs one API
field the backend already returns.

**B. Last-night delta strip** *(top of Why)*
Dot-strip, one row per camera. Season distribution as 40%-opacity jittered dots; season median as a
2 px rule; **last night as a filled 7 px dot with a white ring**. Sorted by |last night − median|.
This is "what changed since yesterday" rendered rather than asserted.

**C. Wind-vs-stand polar sector** *(tap the wind line)*
72 px circle per stand: `approach_dirs_deg` as a filled 30% arc, `shooting_dirs_deg` as a 60% arc,
tonight's wind as an arrow with length ∝ speed, and a 45°-wide downwind **scent cone**. Huntable iff
the cone does not intersect the approach arc — rendered as a solid vs dashed ring. Below 8 km/h the
whole circle renders greyed with "thermals — read at the truck."

---

## 7. The "Why" view

One disclosure below the hero. Order:

1. **Last-night delta strip** — all cameras, sorted by change.
2. **Sunset-anchored actogram** for this stand's camera.
3. **Wind polar** — approach arc, shooting arc, scent cone, huntable ring.
4. **The natural-frequency paragraph**, with the reference class in the sentence, plus the printed
   noise floor: *"Noise floor for this dataset: 57%."*
5. **Provenance footer**: `generated_at`, `model_run_id`, and — once the scoring loop has run —
   *"right 63% of the time over 41 camera-nights."* This is what replaces the invented confidence
   figure, and it is a real number rather than a rescaled sample size.

---

## 8. Insights, redesigned

Currently: a fabricated 7-night outlook, herd-makeup bars, noise-derived behaviour drivers, and
tautological "patterns" (the best of 24 overlapping windows; the top 2 of ~5 cameras).

**Replacement — a strictly descriptive "What the cameras saw" page.** No causal language anywhere.

| Section | Content |
|---|---|
| **Season so far** | Confirmed camera-nights, excluded nights (with reasons), independent visits by species, and the completion rate of the sit log. Effort is stated before any count. |
| **Activity clock** | Sun-anchored circular KDE per species. This is genuinely estimable from one season — thousands of timestamps — and is the most defensible statistic in the product. |
| **Actogram wall** | Small multiples, one per camera, exposure hatched. |
| **Herd makeup** | Kept, but counting `group_size`-aware **visits**, not frames, and labelled as composition of observed groups rather than population structure. |
| **Camera health** | Battery/signal history, uptime %, last confirmed frame, background-hash drift, days since blinding check. |
| **Model track record** *(once scoring runs)* | Reliability diagram, Brier vs climatology and persistence, `n` evaluated. Shown even — especially — when the model is losing. |

Everything causal that survives its permutation null moves here, with the null percentile attached.
Everything that does not survive is not shown at all.

---

## 9. Completely new features

Ordered by value, with the panel's attributions and the red team's cuts applied.

### 9.1 The Claim — *the highest-value new feature in this document*

Claiming a stand for tonight is the data-capture mechanism, and it works because it has a **selfish
payoff**: you claim in order to get the wind verdict, the legal-light window, and the answer to
"is anyone else sitting that ridge tonight."

Why this beats a hunt log: the row is written **before** the sit, at 18:00, when the phone is out
and hands are clean — not at 23:40 in the dark after a blank evening. It exists whether or not the
hunter ever reports an outcome. Both the psychologist and the decision scientist conceded their own
log designs to it.

The claim also provides, for free: the conflict interlock (refuse two stands with overlapping
shooting arcs), the disturbance record for burn half-life, and the "what the hunter picked before we
spoke" baseline.

### 9.2 Sit Mode

One tap from Tonight. True black, amber monochrome, 20% brightness, **all imagery unmounted**,
network frozen with queued local-first writes, wake lock, orientation locked.

- Top 15%: stand name, running clock, `DARK EXIT 23:35`.
- Bottom 85% is one button: **tap = SEEN** (then a 3-chip class picker, 88 px targets, auto-dismiss
  8 s), **long-press 1.5 s = NOTHING YET**, **two-finger hold 3 s = END SIT**.

This is simultaneously the only glove-and-darkness-safe interaction in the product and the missing
write path for `ForecastOutcome`. Night ergonomics and model calibration turn out to be the same
feature.

### 9.3 Legal-light gating

`astro.solar()` already returns `sunset` and `civil_twilight_end`; `_tonight_conditions` discards
both and keeps `darkness_minutes` as an *attractant score*. Clamp every recommended window to a
config-set offset around sunrise/sunset, show last light and a countdown, and never render a window
outside it. Roughly one day of work, and it removes the most likely way this app puts a guest in
front of an enforcement officer.

The offset must be **owner-configured and effective-dated**, not hardcoded — it is set by the
regional annual hunting order and varies by year and community.

### 9.4 Dark exit

Every app tells you when to arrive. Animals leave an estate because someone walked out through them
at 21:30 with a head torch. Compute, per stand: the earliest time the approach corridor is
historically empty, and the bearing that walks the hunter out crosswind of the feed area. Log
whether it was followed. This is the guide's contribution and no competitor has anything like it.

### 9.5 The blind pick *(reduced from the "pre-commitment wager")*

The psychologist proposed the app open blind — the hunter's own pick before the model reveals its
own — with a season-long "You vs GameSense" scoreboard.

**The mechanism ships; the scoreboard is cut.** The red team's power analysis is decisive: at 25–40
logged sits, a paired Brier comparison has a confidence interval wider than the entire plausible
skill range. A scoreboard on that sample is a coin flip presented as a verdict on the machine's
competence — exactly the sin this review is prosecuting.

What survives, and why it still earns its place: capturing the pick **before** the reveal prevents
anchoring, so the hunter's own woodcraft is exercised rather than replaced; and the pick is a
genuinely useful second recommendation source when the model has no data.

Hard gates — the blind prompt is **suppressed entirely** when any of: now > (civil dusk − 45 min);
device moved >15 km/h in the last 5 minutes; the plan is stale; or it has already asked tonight. It
renders as a sheet **over** the already-painted verdict, with a 44 px "Show me" dismiss. The
psychologist conceded the gating; the mobile designer conceded the sheet.

### 9.6 What changed since yesterday — specified

Every expert asked for it; none defined it. Computed server-side into the nightly document as
`changed: {kind, camera, text}`, comparing last night's independent visits **per deployment**
against that deployment's trailing-30-night median over **confirmed-uptime nights only** (NULL
nights excluded, never zero-imputed).

Priority order: (a) return after ≥4 quiet nights; (b) a new class appearing; (c) silence ≥3 nights at
a normally-active camera; (d) a camera sending nothing at all. If none apply:

> *"CHANGED: nothing — same as the last few nights."*

**It is never blank.** A decision aid that goes silent on quiet nights teaches the user that silence
means broken.

---

## 10. Empty, loading and offline states

The current empty/loading design is a bare `Loading…` string that blocks a verdict which has already
arrived, and an offline state that produces `Couldn't load: Unexpected token '<'`.

| State | Design |
|---|---|
| **Cold start, no data** | Not an error. *"3 nights of data at this camera. Too early to call it — here's what came past."* Plus the dot cloud spanning the axis, which is the honest picture. |
| **Loading** | Never blocking. The shell paints the last known plan instantly with its freshness chip; fresh data replaces it underneath. Charts skeleton in independently. The three Tonight fetches are decoupled — a slow analytics call must never blank the verdict. |
| **Offline** | The plan renders from cache with `Plan from 18:04 · offline`. Writes queue locally with a visible count. The service worker must return a JSON stub `{stale: true}` for `/api/*`, **never** HTML. |
| **Stale** | `Plan from last night 19:12 · 22 h old`, non-dismissible, `--alert` border past 12 h. |
| **Camera down** | `NO DATA ▨` — never `QUIET`, and never a silent zero. |
| **Model unvalidated** | Show counts and the dot strip; withhold the verdict word. |

**Offline sequencing.** The mobile designer argued it blocks launch; the architect argued it is
downstream. **The architect wins on sequencing and the mobile designer wins on priority**: once the
nightly forecast is a persisted document, caching it is small. Before that, "offline" means caching a
computation, which is precisely why `sw.js` is broken today. So: persist the document first, then
cache it — but do both before any visual redesign.

The red team's cut applies here too: **real `vite build` behind nginx** (`frontend/Dockerfile:9`
currently ships `npm run dev`), Workbox precache of the actual script manifest, and one cached
nightly JSON document. The service-worker-as-template-engine and dusk push pre-provisioning are
genuinely clever and are deferred — 30–50 hours for a handful of users.

---

## 11. Filters and user flow

**Filters are removed as a concept from Tonight.** A decision screen has no filters; it has an
answer. Filtering belongs on Cameras (by camera, species, date, flagged) and Insights (by species,
by scope).

**The 18:00 flow, end to end:**

1. Open → verdict painted from cache in <300 ms, offline or not.
2. *(Optional, gated)* blind pick sheet → dismiss or answer in one tap.
3. Read three lines: where, wind, what changed.
4. Tap CLAIM → conflict and arc check → stand is reserved, others see it.
5. Drive. Walk in on the stated bearing.
6. Tap START SIT → Sit Mode, black screen, one button.
7. Tap once when something comes past. Long-press if nothing.
8. Two-finger hold to end. Dark-exit time and bearing shown.
9. Morning: one push digest of last night's frames per stand. No other notifications.

**Notifications, redesigned.** One fixed-schedule notification per day, sunset-anchored, sent
**every** night including quiet ones. Fixed schedule rather than variable-ratio is deliberate: the
current p≥0.7 alert is an intermittent high-arousal reward schedule, which is the architecture of a
slot machine and pushes sits the hunter would not otherwise take. The body carries the whole plan —
`▲ BEST ODDS · PUENTE · 21:40–23:10` — so that on the best nights the app never needs to be opened
at all.

No streaks. No badges. No harvest counters. Any scoreboard scores **prediction**, never kills.

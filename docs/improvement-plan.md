# GameSense improvement plan (26 Sep 2026)

This plan comes from an audit on 26 Sep 2026. Ten auditors each took one area:
Tonight/Sit, Map, Photos/Cameras/Animals, app shell/PWA, ingestion, AI, forecasting, ops, a live Playwright run
of the real app, and product/competitor research. A completeness pass followed. An independent verifier then
tried to refute every finding. **269 of 271 findings survived**, most of them reproduced with a test or a browser
run. The full evidence, file:line references and fix notes are in
[`audit/2026-09-findings.md`](audit/2026-09-findings.md), grouped by the item numbers below.

Baseline at the time of the audit: all 263 backend tests pass against a real Postgres, and `npm run build` passes.
5 of the 7 frontend UI scripts fail on current main, and nothing runs them.

**Two dates drive the order:**
- **8 Oct:** the general big-game season opens in Castilla-La Mancha.
- **25 Oct:** clocks go back. After that, "Best hours" will be 1–2 h late (item 8), and wall-clock camera
  times need checking.

Sizes: **S** ≈ half a day, **M** ≈ 1 day, **L** ≈ 2–3 days.

---

## Part A: fixes (things that are broken or feel broken)

### 1. The app never goes blank (M)
**Problem:** four confirmed ways to get a completely blank screen:
- coming back to the app with a photo open deep in the feed;
- tapping Map after any deploy;
- tapping Map offline before it was ever opened;
- the first launch after "Add to Home Screen", then no signal.

Nobody is told when it happens.

**Changes:**
- A top-level error boundary around the page outlet, with "Something broke. Reload". It reloads once by itself
  on a chunk-load error (`vite:preloadError`, with a sessionStorage guard).
- Photos: returning to the app adds only the newer photos to the top. It does not reset the list to the first
  60, and it does nothing while the viewer is open. The lightbox tracks the photo by id, not by index.
- Service worker: never answer a script or style request with `index.html`. Precache the built assets at
  install. Treat 5xx and Cloudflare 52x/530 like no signal, so the saved plan shows instead of an error page.
- Crash reporting: the phone posts errors to a small `/api/client-errors` endpoint, and admins see the last few
  in Settings.

**Covers:** B-02, C-02, D-01, D-18, D-20, H-06, I-01, I-06, K-02, K-03, K-14

### 2. Sit reports are never lost or overwritten (L)
**Problem:** the most important data the app collects is the easiest to lose.
- A later tap or a replayed no-signal tap turns **SHOT** into "Saw animals". The whole screen is the
  SAW ANIMALS button, so a glove brush is enough.
- Reports queued while a flush is running are deleted.
- END SIT doesn't end the sit, but the first tap does. After that there is no way back into Sit mode and no
  way to correct the report.
- Unreported sits vanish at 06:00.
- Two hunters can reserve the same stand at the same moment.

**Changes:**
- The server never lowers an outcome (shot > shootable-no-shot > seen > nothing). A correction from Stands
  can still lower it on purpose.
- Every write carries the time of the tap, and older writes are ignored.
- One queued entry per sit. A single sender that concurrent callers share. The queue is cleared on sign-out.
- A real "end sit" call. "Back to sit" stays available while the sit is running.
- "What happened last night?" is shown the next morning for any sit that wasn't reported.
- Reserving a stand takes a per-night lock, with a unique index as backstop, so two hunters can't get the
  same stand or crossing fire lanes.
- Keep-screen-on is taken again after the phone comes back to the app.

**Covers:** A-01, A-02, A-06, A-07, A-17, A-20, A-23, A-25, I-02, I-03, I-09, I-23, J-02, J-03, J-11, J-15, J-22

### 3. Safe deploys and a test gate (M)
**Problem:** every push to `main` goes live on Db01 within 10 minutes, at any hour, with no tests run. A
dusk deploy is what triggers the blank-screen and error-page cases in item 1. The deploy also has these problems:
- it swaps the frontend before the backup and migration;
- it never retries a failed build;
- it keeps running half-deployed after a failure;
- it never rolls back.

The health checks report "ok" with the database down.

**Changes:**
- A GitHub Actions workflow: backend pytest with a Postgres service, the frontend build, and the repaired UI
  smoke scripts. `update.ps1` deploys only a commit that passed.
- `update.ps1`:
  - swap the frontend after the migration;
  - retry pip and vite once;
  - roll back if `/api/health` fails after a restart;
  - optionally skip deploys from 1 h before sunset to 01:00.
- `/api/health` and `/api/ready` report the real state.
- Keep the output of scheduled jobs. Add a disk-space warning. Put the backup and restore check in the repo.
- Store photo paths relative to the media root.

**Covers:** B-25, D-22, H-04, H-05, H-07, H-08, H-09, H-10, H-15, H-18, H-21, I-29, K-09

### 4. No gaps in photo ingestion; broken camera logins are visible (L)
**Problem:** photos can go missing for good, and the app then counts those nights as "no animals".
- A SPYPOINT photo whose download fails once is never retried.
- A routine sync reads only the newest 100 photos per camera, so any outage leaves a permanent hole.
- UBox looks back only 24 h.
- A broken camera login still reports "ok". The camera card stays green for 36 h, then tells the hunter to
  check the battery.
- "Check for new photos" can spin forever or say "Nothing new" when a login failed.

**Changes:**
- Retry failed downloads, plus a repair pass for rows with no file.
- Page backwards until the sync meets a photo it already has.
- A longer UBox catch-up.
- One transaction per account, so one error doesn't discard every camera's photos.
- Per-login status in Settings ("SPYPOINT refused the password — re-add this login").
- A camera card that says "Photos not coming in — login needs attention".
- Stop duplicate logins. Ignore obviously wrong camera clocks.
- FTP/email cameras are not marked offline after 36 quiet hours.
- A clear result line on the Check button.

**Covers:** C-07, C-08, E-01–E-08, E-10, E-13, E-15, E-17–E-23, H-20, H-22, I-30

### 5. Background jobs and the AI pass run reliably (L)
**Problem:** the pipeline lock is a file checked by age.
- A crash blocks syncing for 3 h. A run longer than 3 h lets a second run in, which duplicates detections.
- The 17:00 plan job and the 11:00 score job silently skip whenever a sync holds the lock, and a missed night
  is never scored.
- A detector failure is recorded as "watched, no animals".
- One network or credit failure in the cloud stag/hind pass permanently uses up each photo's only attempt.
- Manual checks load the AI models into the web server.

**Changes:**
- An atomic lock with an owner, a heartbeat and PID checks.
- Plan and score wait for the lock instead of skipping. Score catches up any unscored night in the last 14 days.
- AI failures are counted and retried a few times, then marked failed. They are never recorded as empty nights.
- If a model can't load, the whole pass stops and says why.
- The stag/hind pass doesn't count API failures as attempts, and it stops on an auth or credit error.
- Manual checks run in the worker, not the API.
- Admin status shows the AI backlog and the last error.

**Covers:** C-21, C-22, E-11, E-12, F-01, F-02, F-04, F-05, F-08, F-09, F-10, F-12–F-15, F-17, G-15, H-02,
H-03, H-11, H-19, J-01

### 6. Tonight is fast and honest on weak signal (M)
**Problem:**
- With no signal, the installed app shows a days-old plan as "Plan from just now".
- Tonight never paints the saved plan first. It waits on the network with no timeout, so the spinner can run
  for minutes.
- Switching species with no signal wipes the page.
- Stands doesn't open offline.
- Every tab starts over from "Loading…" and keeps downloading after you leave it.

**Changes:**
- Show the saved plan immediately and refresh underneath (stale-while-revalidate).
- Read the service worker's stale headers so the age is true: "No signal. Plan from 14 h ago".
- A plan counts as stale when it was made before tonight's 06:00 cutover.
- Request timeouts and abort-on-leave.
- A small in-memory cache across tabs.
- Stands works from its cached copy.
- A saved species pick that no longer exists falls back to "All".

**Covers:** A-04, A-05, A-15, A-16, A-18, C-27, D-02, D-03, D-09, G-19, I-05, I-07, I-10, I-24, J-05, J-06, K-08

### 7. Weather and wind: fresh, and one answer everywhere (L)
**Problem:**
- Tonight's wind is fetched once a day and never refreshed, so dusk shows the morning's forecast.
- Tonight, Stands, Sit mode and Map use **different wind models**, and can tell the same hunter opposite
  things about the same stand.
- The map judges scent at the moment you open it, not at sit time.
- Before dawn it says "calm and sunny, air moving upslope", because it compares local time with UTC sunrise.
- The scent check aims at the middle of the bedding and misses the near end.
- A slow weather service stalls every page for everyone, because it holds database connections.

**Changes:**
- A forecast cache that expires after 30–60 min and falls back to the last good copy.
- Weather fetched outside the database session, with a short timeout and a cache for failures.
- **One wind verdict** (the bedding and thermals model), used by Tonight, reserving, Sit mode, Stands and Map.
- Judged at sit time (sunset + 45 min), and labelled with that time.
- Timezone-correct sunrise and sunset, and "tonight" stays tonight after midnight.
- The scent cone is tested against the bedding outline, with true point-to-edge distance.
- A missing forecast reads "no wind forecast", not "calm".

**Covers:** A-09, A-10, A-11, A-22, B-03, B-04, B-05, B-07, B-14, B-15, B-19, B-20, F-03, G-07–G-10, I-04,
J-04, J-07, K-04

### 8. Best hours follow sunset; sunset and last legal light on screen (L) — before 25 Oct
**Problem:**
- "Best hours" come from a season-long histogram of clock hours. Sunset moves about 3 h between early August
  and late October (counting the clock change), so after 25 Oct the window will start after the animals arrive.
- The app never shows sunset or last light.
- It will recommend red deer at 21:00–00:00, which is after legal light.

**Changes:**
- Bin sightings by minutes after that night's sunset, weighted to recent weeks, and convert back using
  tonight's sunset.
- Show "Sunset 19:56 · last legal 20:56" on Tonight and in Sit mode.
- Legal hours are owner-set per species (default: sunset + 60 min; boar allowed at night). The best window is
  clipped to them, with the reason shown.
- Check the Suntek camera clocks across the clock change.
- Fix the moon-phase names, which are off by one night.

**Covers:** A-08, A-27, E-14, F-21, F-22, G-05, H-17, J-08, J-18

### 9. The forecast counts nights and ranks cameras correctly (M)
**Problem:**
- Nights are counted by calendar date, so the app says "Wild boar seen 8 of the last 7 nights". One visit
  either side of midnight counts twice, which pushes a Worth a look spot up to Best odds.
- A camera added a few days ago takes over the headline as "Not enough to say".
- A camera taken down weeks ago keeps topping Tonight as Best odds, and it can't be retired.
- Nights the classifier hasn't reached yet count as empty.
- The "Changed" line reports the night still in progress.
- Counts are photos, not visits.
- The track record grades "Worth a look" as a prediction of no animals.

**Changes:**
- Use the 18:00→06:00 night key everywhere.
- Cameras that can be judged rank first.
- Cameras silent for more than about 7 days drop out of the ranking, and there is a "Retire camera" switch.
- Unprocessed nights are left out. The quiet-camera assumption has an age cap.
- Show visits ("3 visits") with photo counts behind the fold.
- Grade per verdict ("When it said Best odds, animals came 7 of 9 nights").
- Match camera claims by id, not name.
- Alerts no longer recompute the whole forecast.

**Covers:** A-03, A-12, A-13, A-14, A-24, A-26, G-01–G-03, G-11–G-14, G-16–G-18, G-22, G-24, H-12, I-20,
I-26, J-10, J-12, J-24, K-01, K-10

### 10. Hidden animals and hidden photos stay hidden everywhere (S)
**Problem:** hiding a species (e.g. fox, rabbit) still leaves it in alerts, Insights, the Changed line and the
weather patterns. Hiding a false-alarm photo removes it from Photos, but Tonight still counts it as a sighting.

**Changes:**
- One shared "visible" filter applied to every forecast, alert, insight and pattern query.
- Recompute that camera's nights after a photo is hidden.
- One test per screen asserting that hidden things never appear.

**Covers:** C-05, C-23, G-06, I-25, K-05

### 11. Insights stops presenting chance as findings (S)
**Problem:** the "More sightings when…" weather and moon lines appear from pure noise in 86–99% of simulated
runs. They also count nights when the cameras were down as quiet nights.

**Changes:**
- Now: drop the headline sentences, and keep the bars behind "Show the numbers", marked "not tested".
- Later: build the series from nights the cameras were actually watching, and show a finding only when it
  beats a shuffle test.

**Covers:** A-19, G-04, G-20, J-09

### 12. Access and security (M)
**Problem:**
- Removing a guest who ever reserved a stand, drew a zone or added a camera login fails with a 500, so their
  access can't be revoked.
- The public login has no throttling and pre-fills the admin email.
- A password change doesn't end old sessions.
- 30-day tokens sit in every photo URL and still work for removed users.
- Members see admin-only buttons that silently fail.
- Any member can delete bedding or move cameras.
- `/docs` is public.

**Changes:**
- Removing a person keeps their history and switches off their camera logins.
- Login throttling that understands Cloudflare, and no pre-filled email.
- A per-user token version, so a password change or removal ends sessions.
- Short-lived signed image URLs.
- Role checks on map, camera and hide edits, and admin buttons hidden from members.
- API docs are off in production. The app refuses to start with the default secrets.

**Covers:** B-08, C-09, C-19, C-28, D-05–D-08, D-11, D-12, D-23, E-09, H-01, H-13, H-14, H-23, I-12, I-13, I-15, K-12

### 13. Photos and Animals fixes (L)
**Problem:**
- Grids download full-size originals.
- Paging skips photos that share a timestamp.
- "Show older photos" can get stuck on Loading.
- The viewer stops at the last loaded photo.
- **A name given to an animal is wiped the next time anyone taps "Look for repeats"**, and merging throws the
  typed name away.
- A failed rename is silent.
- The Animals gallery stops at 300 photos.
- Photos groups by calendar day, which splits a night at midnight.

**Changes:**
- 320 px WebP thumbnails, and long-lived caching for photo files.
- Paging by a (time, id) cursor. The viewer loads more as you swipe.
- Named animals survive re-ID and merges.
- Errors are shown in plain words.
- The Animals gallery pages past 300.
- Photos is grouped by night.

**Covers:** C-01, C-03, C-04, C-10–C-18, C-20, C-25, C-29, E-24, F-11, I-18, I-19, I-27, I-28, J-13, J-14

### 14. Map fixes (M)
**Problem:**
- "Try again" on a satellite error wipes the bedding and wind layers, and leaves "Loading map…" on screen.
- A camera placed by hand snaps back to SPYPOINT's position at the next sync.
- Save errors appear off-screen.
- Malformed shapes return a 500.
- Drawing on a phone fights the keyboard and the tab bar.
- "See photos" opens the whole camera list.

**Changes:**
- Retry reloads only the tiles, and the error clears when the tiles load.
- A position set by hand wins over SPYPOINT's.
- Save errors appear next to the control.
- Shape validation returns readable errors.
- Drawing layout fixed for phones.
- "See photos" opens that camera's photos.
- Only bedding is drawn as bedding. A north-reset control. A zoom limit on the satellite layer.

**Covers:** B-01, B-09–B-13, B-17, B-18, B-21–B-24, E-16, G-25, I-11

### 15. Notifications that respect the hunter (M)
**Problem:**
- One sounder at a feeder buzzes the phone every 15 minutes all night.
- Alerts silently stop after a network blip while Settings still says "This phone gets alerts".
- Quick taps on alert switches can leave the server out of step with the screen.
- Signing out leaves the phone getting that person's alerts.
- An alert tapped later can open nothing.

**Changes:**
- A per-species cooldown (a silent update within 2 h), with optional quiet hours.
- Re-subscribe and check the subscription on open.
- Settings saves are debounced and confirmed.
- Unsubscribe on sign-out.
- The alert link carries the photo's time, so older photos still open.
- Pushes are held while the hunter is sitting, and delivered as one summary afterwards.

**Covers:** D-04, D-14, D-17, D-19, D-21, G-23, I-14, I-21, J-21, K-06, K-07

### 16. Glove-sized and small-screen UI polish (M)
**Problem:**
- Chips, switches, map zoom and the hide button are 25–34 px.
- On 320 px screens the Settings tab sits off-screen.
- Stands and Insights jump when data arrives.
- Signing in lands on Tonight, not on the photo the alert pointed to.
- Sessions end on a fixed date even for daily users.
- Photos can't be rotated to landscape.

**Changes:**
- A 44–56 px minimum for primary controls. A "More" tab below 380 px.
- Space reserved for late-loading content.
- Return to the intended page after sign-in. A sliding session.
- Landscape allowed in the photo viewer.
- Double-submit guards.

**Covers:** A-21, B-16, C-24, C-26, D-10, D-13, D-15, D-16, D-24, G-21, I-08, I-16, I-22, K-11, K-13

### 17. AI accuracy (M)
**Problem:**
- MegaDetector runs at its default 0.25 cut-off, so the 0.10 "keep faint animals" setting never applies.
- The classifier keeps its top guess with no confidence floor and no Iberian species list.
- A lone boar in nested boxes becomes "Sow + piglets".
- One burst can flip between species.
- "No antlers = hind" is wrong while stags have cast (Feb–Apr).
- Every frame runs through the detector twice.

**Changes:**
- Pass the intended threshold through to the detector.
- A confidence floor plus an allowed species list.
- Remove nested boxes before building groups.
- A majority vote per visit.
- A season-aware stag/hind prompt.
- Detect once per frame.
- A hunter's flag is never overwritten by a scan.

**Covers:** F-06, F-07, F-16, F-18, F-19, F-20, F-23

---

## Part B: new features

These are ranked by value for this estate. Each one respects the product's rules: one estate, a few hunters,
one tap per sit, plain words.

| # | Feature | Why | Size |
|---|---|---|---|
| 18 | **Tonight names a stand**, with one-tap Reserve / Start sit, "Taken tonight: Solana (Pedro)" and "Rested 9 nights" | Tonight's headline is a camera. The 18:00 flow today is four screens. HuntStand's most-used club feature is shared stand reservations | M |
| 19 | **One plan push per day**, about 2 h before sunset: "▲ Puente · wind right · sunset 19:56" | The redesign's single notification; the plan job already computes it (needs item 5) | S |
| 20 | **Fix a wrong species or false alarm from the photo viewer**; readable species names ("Hare", not "Rabbit"; no "Micromammal") | Hunters look at photos in the viewer, but corrections live elsewhere | M |
| 21 | **Finish stand setup**: shooting-arc entry, so the crossing-fire-lanes check actually works; "a stand at each camera"; dark exit time (after item 8) | Already built in the backend but unreachable from the UI. The safety check can never fire today | M |
| 22 | **Hour-by-hour wind for the sit**, plus "right wind for Puente: tonight 19–21 h, Thu, Sat" | Wind is the first thing a hunter checks. The hourly data is already fetched (needs item 7) | M |
| 23 | **Harvest log**: species, sex, age class, seal number, prompted the morning after SHOT, plus a season CSV export | Paperwork the owner already keeps for the annual return | M |
| 24 | **Map works offline**: cached stands, cameras, bedding and imagery for the estate | Valleys with no signal | L |
| 25 | **People and vehicles on camera** (admin-only filter, no pushes by default) | Today these frames are silently filed as empty | S |

---

## Recommended order

1. **This week (before the 8 Oct opener):** 1, 2, 3, 4, 5, 6.
2. **Before the 25 Oct clock change:** 7, 8, 9, 10, 11.
3. **Then:** 12–17, then the features in the order listed.

Each item ships as its own PR with tests. The DB-backed suite runs with `GAMESENSE_REQUIRE_DB=1`, the UI
scripts are repaired, and changed flows get a Playwright check.

## Decisions needed from the owner
- **Legal hours per species** (item 8): the proposed default is last legal light = sunset + 60 min for all
  species, with boar allowed at night (aguardo). Confirm against the estate's permits.
- **Removing a guest** (item 12): the proposed default switches off the camera logins they added (history kept).
- **Deploy freeze** (item 3): whether to skip auto-deploys from 1 h before sunset to 01:00. Proposed: yes.

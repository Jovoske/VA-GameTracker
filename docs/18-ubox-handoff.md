# UBox (UBIA) 4G camera integration: build handoff

Goal: photos from a UBox Pro camera land in GameSense like SPYPOINT photos do, so
detection, species, the Tonight forecast and sighting notifications all work for it
without special cases. The original plan was written 2026-09-16 before the camera
arrived; the live findings below now supersede its unverified protocol assumptions.

**Implementation status (2026-09-16):** deployed to Db01 at commit `ba07f9b`,
with migration `0013_ubox` applied and the API healthy. The active UBox Pro account
is stored encrypted, and camera **FoxCon1** has 18 imported photos processed by
the real detector/classifier. All 18 authenticated live gallery image endpoints
returned valid 4608 × 2592 JPEGs. See the live findings and operating notes below.

## The camera and its platform

- Bought on AliExpress: a €69 "UCON PRO" 4G solar pan/tilt camera, 5 MP, no-glow IR,
  PIR, IP66. SIM only, no WiFi. App: **UBox Pro** (`com.ubianet.uboxpro`, by UBIA
  Technologies).
- It is a security-style live-view camera on UBIA's cloud, not a trail camera. There is
  **no FTP, SMTP or email upload in its menu**, so the Suntek paths (`ftp-receiver/`,
  `mail-receiver/`) do not apply. It sits behind carrier NAT, so RTSP/ONVIF cannot
  reach it either.
- Everything the app shows comes from a plain HTTPS REST API at
  `https://portal.ubianet.com`. Motion events are stored in UBIA's cloud with a
  snapshot image per event. That snapshot is what we ingest.

## Read first

- [09-deployment.md](09-deployment.md) and [09-handoff.md](09-handoff.md): Db01,
  native install, `git push` deploys, scheduled tasks, no Celery.
- `backend/app/ingestion/spypoint.py` and `sync.py`: the pattern to copy. Client class
  with typed dataclasses, `_run()` orchestration over accounts, `_ingest_photo()`
  writing an `Image` row, `enrich_image()`, `SyncLog`.
- `backend/app/api/routes_camera_accounts.py` and `app/core/crypto.py`: how a guest
  SPYPOINT login is verified before saving and stored Fernet-encrypted.
- `backend/app/ingestion/ftp_import.py`: the conventions for a camera that is **not**
  SPYPOINT (`cameras.spypoint_id IS NULL`), dedupe on `(camera_id, file_hash)`,
  media path layout `MEDIA_ROOT/<estate>/<camera>/<YYYY-MM-DD>/`.
- `backend/app/health.py`: `camera_health()` reads `last_report_at`, `battery_pct`,
  `photo_count`/`photo_limit`. Fill what applies so the camera is not reported
  offline by mistake.
- [17-notifications.md](17-notifications.md): nothing to do, dispatch hooks on
  `classify_unclassified()`, so UBox photos notify automatically once classified.
- Community reference: [JEMcats/ubox_camera_api](https://github.com/JEMcats/ubox_camera_api)
  (Node). Read `src/main/requests.js`, `hash_password.js`, `docs/` and `api_docs/`.
  It is unofficial; treat it as a map, not a spec.

## What the community project establishes

**Login.** `POST https://portal.ubianet.com/api/v3/login`, JSON body:

```json
{"account": "<email>", "password": "<hash>", "lang": "en", "app": "uboxpro",
 "device_token": "<random 30 chars>", "device_type": 2}
```

`password` is **HMAC-SHA1 with an empty key over the plaintext password, base64,
then `+` → `-`, `/` → `_`, and `=` → `,`**. In Python:

```python
import base64, hashlib, hmac
digest = hmac.new(b"", password.encode(), hashlib.sha1).digest()
hashed = base64.b64encode(digest).decode().translate(str.maketrans("+/=", "-_,"))
```

Response `data.Token` is the session token, with `token_valid_hours`, `uuid`, `kuid`.
The token is included in the JSON body as `token` and in the
`x-ubia-auth-usertoken` header. The live account's password contains punctuation
and works; there is no need to remove special characters.

**Devices.** `POST /api/v2/user/device_list`.
Two arrays: `items` (basic) and `infos` (detail). Fields seen: `device_uid`,
`device_name`, `model_num`, `online_state` ("2" = online), `battery`,
`is_battery_charging`, `signal`, `firmware_ver`, `time_diff` (seconds), `icc_id`,
`has_cloud_storage`, `latest_active_utc`.

**Events.** `POST /api/user/cloud_list` with `device_uid: [...]`,
`timestamp: [start, end]` (Unix), `page`, `time_diff`, `summer_time`,
`time_revised`. Each item has `event_time`, `device_uid`, `type`, `status`,
`ai_flag`, `ai_result`, `cloud_image_url` (event thumbnail), `img` (image url),
`video_info`, plus pagination (`total`, pages, current page). There is also
`user/event_calendar` (which days have events) and `user/get_cloud_video_url`
(clips, ignore for now).

**Remaining open questions after the live checks:** whether snapshots remain
available **without a paid cloud plan or after a trial expires**; how long events
stay listed; whether `event_time` is UTC or device-local (that is what `time_diff`
is for); what the `type` codes mean (PIR vs AI person/animal); how long the signed
image URLs remain valid; rate limits. HD snapshots are verified at 4608 × 2592 pixels, with
1280 × 720 regular snapshots as fallback. One timestamp sample is consistent
with Unix UTC; the three-event comparison against the app remains pending.

## Phase 0: probe (half a day)

A throwaway script, run **on Db01** in `C:\GameSense\venv` so it uses the server's
network path, credentials typed by the user into a local `.env` that is never
committed.

1. Log in with the hash above. Print `token_valid_hours`.
2. `device_list`: print every field of the camera, save the raw JSON (scrub SIM ids)
   as a test fixture under `backend/tests/fixtures/ubox/`.
3. `cloud_list` for the last 24 h and for the last 7 days: count events, print
   `type`/`ai_result` distribution, save one raw page as a fixture.
4. Download one `cloud_image_url` and one `img` with a plain GET: record HTTP status,
   content type, pixel size, file size, whether the URL works again an hour later.
5. Run MegaDetector on that JPEG (`app.ai.detector.detect_animals`) to see the
   snapshot is detectable at its resolution.
6. Compare three `event_time` values with what UBox Pro shows to settle the timezone.

Write the answers into this file under a new "Phase 0 findings" heading before
continuing. If snapshots need a cloud plan, stop and report; the cheapest plan may
still be worth it, but that is the user's call.

## Phase 1: client `backend/app/ingestion/ubox.py`

Mirror `spypoint.py`:

- `class UboxError(Exception)`.
- `@dataclass UboxDevice`: `uid`, `name`, `model`, `battery_pct`, `charging`,
  `signal`, `online`, `firmware`, `time_diff_s`, `last_active_at`, `has_cloud`, `raw`.
- `@dataclass UboxEvent`: `event_id` (build one if the API has none:
  `f"{device_uid}:{event_time}"`), `device_uid`, `captured_at` (aware UTC),
  `image_url`, `type`, `ai_result`, `raw`.
- `class UboxClient(email, password)` using `httpx.Client` with a 20 s timeout and a
  fixed user agent: `login()`, `list_devices()`, `list_events(device_uid, since,
  until, page_size)` paging until exhausted, `download(url) -> bytes`. Re-login once on
  401 or on the API's own "token expired" code, like `SpypointClient` does.
- Pace requests (0.5 s between pages) and never loop on an empty page.
- Log with `structlog` keys `ubox.*`, never the token or password.

## Phase 2: schema, migration `0013_ubox`

Keep it additive and idempotent, and keep the ORM in `models.py` in step
(`tests/test_migrations.py` fails otherwise):

- `camera_accounts.provider varchar NOT NULL DEFAULT 'spypoint'` with a check
  constraint `provider IN ('spypoint','ubox')`. Existing rows stay SPYPOINT.
- `cameras.ubox_uid varchar UNIQUE NULL`. Leave `spypoint_id` alone; a camera has one
  or the other, and `ftp_import.py`'s "not SPYPOINT" checks keep working.
- `images.ubox_event_id varchar UNIQUE NULL` for dedupe by event, in addition to the
  `(camera_id, file_hash)` check.

Update `docs/03-database-schema.md`.

## Phase 3: sync `backend/app/ingestion/ubox_sync.py`

- `_ubox_accounts(db)`: active `CameraAccount` rows with `provider == 'ubox'`,
  passwords via `crypto.decrypt`. No `.env` primary account; UBox logins are added in
  Settings only.
- `upsert_camera()` keyed on `ubox_uid`: name, model (`f"UBox {model_num}"`),
  `battery_pct`, `signal_pct`, `last_report_at` from `latest_active_utc`,
  `last_sync_at`. Leave `photo_count`/`photo_limit` NULL so `camera_health()` never
  reports it out of credits.
- `sync_ubox_all(db, hours=24)`: for each account and device, events since
  `max(camera.last_sync_at - 2h, now - hours)`; for each event not already in
  `images.ubox_event_id`, download, write to
  `MEDIA_ROOT/<estate>/<camera>/<date>/ubox_<event_id>.jpg`, create `Image`
  (`captured_at`, `original_path`, `cdn_url`, `file_hash`, `width`, `height`),
  `enrich_image()`. One `SyncLog` row per run, `status ok/error`.
- `backfill_ubox_account(db, account_id, days=7)` for a newly connected account.
- Hook points: `pipeline.py` mode `sync` (after `sync_all`, before the AI pass) and
  `routes_cameras._sync_work()`. Do not add a scheduled task.
- Skip event types that carry no image; log the count so a wrong type mapping is
  visible in the sync log rather than silent.

## Phase 4: Settings UI

In `frontend/src/pages/Admin.tsx`, the Camera accounts card gets a provider choice
(SPYPOINT / UBox Pro) on the add form; the list shows the provider as a small tag.
`routes_camera_accounts.add_account` branches on provider: verify with `UboxClient`
(login + device count) before saving, `encrypt()` the password, then kick
`backfill_ubox_account` as a background task under the pipeline lock exactly as the
SPYPOINT branch does. Removing an account keeps photos (`cameras.account_id` nulled).

## Phase 5: tests

- `tests/test_ubox_client.py`: parse the Phase 0 fixtures into `UboxDevice`/
  `UboxEvent`; the password hash against a known vector (compute one with the Node
  script and pin it); timezone handling of `event_time` + `time_diff`.
- `tests/test_ubox_sync.py` (`@requires_db`): a fake client yielding two events →
  two images, second run adds nothing, `SyncLog` written, camera upserted once.
- Extend `test_migrations.py` fresh-upgrade and idempotence checks for the three new
  columns.
- `npm run typecheck` for the frontend.

## Phase 6: deploy and verify on Db01

1. `git push`; watch `C:\GameSense\logs\update.log` for the migration line and
   "API healthy".
2. Settings → Camera accounts → add the UBox login. Expect "Connected, 1 camera".
3. After the next `GameSense-Sync` run (≤15 min): the camera appears on Cameras with
   battery and signal; its snapshots appear in the gallery; the sync log shows
   `ubox` counts.
4. Trigger the camera by walking past it. Within one sync the photo is classified;
   if a subscribed species is selected in Notifications, the phone gets the push.
5. Place the camera on the Map (no GPS in this unit).

## Risks and decisions to make

- **Unofficial API.** Same standing as SPYPOINT: a vendor change breaks it, the sync
  log makes it visible, nothing else is affected.
- **Snapshot quality.** HD JPEGs are verified at 4608 × 2592 and preferred over the
  1280 × 720 regular snapshot. Detection quality for small or distant wildlife
  still needs field observations; the live samples are indoor/person test frames.
- **Trigger noise.** A PTZ security camera may fire on wind, birds and light. The
  empty-frame filter handles that, but expect a higher empty ratio than the SPYPOINTs.
- **Timezone.** Get this right in Phase 0; every pattern in Insights depends on
  capture time.
- **Credentials.** New accounts can be connected in Settings on the live app.
  Stored passwords are encrypted; never include credentials in commits, docs or logs.

## Definition of done

A UBox account connected from Settings syncs its camera every 15 minutes, its
snapshots show in Cameras and Animals with species labels, the Tonight forecast
includes the camera once it has nights of data, sighting notifications fire for it,
the migration is idempotent and the test suite is green, and this document has a
"Phase 0 findings" section with the verified API facts.

## Phase 0 findings

### Live follow-up, 2026-09-16

The user confirmed **UBox Pro** and a **one-minute camera trigger interval**.
The real account was probed directly from the development machine, with hidden
credential entry and scrubbed output. No credentials, session tokens or signed
image URLs are committed.

- The original `app="ubox"` returned vendor code `20002`, "Invalid account".
  **`app="uboxpro"` succeeds** on the same `portal.ubianet.com` endpoint. The
  production client now defaults to the verified Pro identifier.
- The complete hash substitution is documented in
  [the Android-derived client](https://github.com/asyrk/ubox-web/blob/master/server.js#L24).
  Both substitutions omitted by the older community script now have test vectors.
- Login returned a 696-hour token. One camera was online, model `2592`, with 85%
  battery. Its signal value was `3`; the scale remains unverified.
- Both the past-day and past-week queries returned 14 events, all type `1`, with
  snapshot URLs. The account reports cloud storage opened; this does **not** prove
  that snapshots remain available without a plan or after a trial expires.
- `cloud_hd_image_url` returned HTTP 200, `image/jpg`, a **4608 × 2592 JPEG** of
  **404,196 bytes**. `cloud_image_url` returned a **1280 × 720 JPEG** of **42,478
  bytes**. `img` was not a usable HTTPS URL. The importer now prefers the verified
  HD field and falls back to the regular snapshot.
- One sample's image overlay was 16:27:20 local against an API event of 14:27:25
  UTC, consistent with UTC+2 and a five-second event/image difference. The camera
  reports `time_diff=3600` and DST enabled. A three-event comparison against the
  app remains pending; no extra offset is subtracted from Unix timestamps.
- Samples are indoor/person test frames. The detector should put these under
  **Review photos marked empty** in Cameras; Animals lists classified wildlife.

### Db01 deployment and live gallery verification, 2026-09-16

- Db01 is running commit **`ba07f9b`**. Migration **`0013_ubox`** is applied,
  the API is healthy, and the served frontend contains the **UBox Pro** provider
  label.
- The authorized account is active and its password is stored encrypted.
  Its camera, **FoxCon1**, appears in the app.
- The initial live import found **22 events**: **18 photos imported**, **4 skipped
  by the minimum interval**, and **zero failures**.
- All **18 photos** completed the real detector/classifier pipeline; **17 were
  marked empty**. To view filtered shots, open **Cameras → FoxCon1 → Review photos
  marked empty**. Animals shows classified wildlife rather than every camera frame.
- Every one of the **18 authenticated live gallery image endpoints** returned
  **HTTP 200** and a valid **4608 × 2592 JPEG**. These are the locally stored images
  served by GameSense.
- The account retains a **60-second minimum import gap** and **500-photo daily
  ceiling per camera**. The camera's own trigger interval is also one minute.
  Ongoing imports use the normal **15-minute scheduled sync**.

This confirms deployment, ingestion, inference and image delivery. Cloud access
after a trial or without a paid plan, retention, and the three-event timestamp
comparison remain unresolved; the successful import does not settle those points.

The following source-only notes describe the earlier implementation stage:

No UBox credentials or real camera were available during implementation. The
fixtures in `backend/tests/fixtures/ubox/` are explicitly synthetic. They verify
the parser and transport contract; they do not prove live account compatibility.

Inspection of the [community request implementation](https://github.com/JEMcats/ubox_camera_api/blob/main/src/main/requests.js)
and [transport helper](https://github.com/JEMcats/ubox_camera_api/blob/main/src/main/helpers.js),
[device example](https://github.com/JEMcats/ubox_camera_api/blob/main/api_docs/portal.ubianet.com/api/v2/user/device_list.json)
and [event documentation](https://github.com/JEMcats/ubox_camera_api/blob/main/docs/user_cloud_list.md)
establishes these corrections to the plan:

- The cloud device-list request is **POST**, not GET. GET belongs to the community
  project's local proxy. Authenticated cloud calls use `x-ubia-auth-usertoken`;
  the implementation also includes `token` in the JSON body.
- Device records merge `data.items` and `data.infos` by `device_uid`. Battery,
  charging, online state and signal are under `dynamic_info` in the reference.
- Cloud events are in `data.list`, with pagination in `data.count`. The importer
  prefers `cloud_hd_image_url`, then an HTTPS `img`, with `cloud_image_url` fallback.
- The HMAC-SHA1/base64/comma hash matches a pinned Node-generated test vector.
  The live follow-up verified vendor acceptance of a password containing
  punctuation using the complete `+`/`/`/`=` substitutions documented above.
- Numeric `event_time` is treated as Unix UTC seconds. Requests use `time_diff=0`,
  `summer_time=0`, `time_revised=false`. **This neutral-UTC interpretation still
  needs comparison with three events in the real UBox Pro app.** Naive timestamp
  strings are not assigned an invented timezone.
- The signal scale is unknown (the reference contains `signal=1`). GameSense
  leaves the signal percentage unavailable rather than displaying a made-up
  percentage. Actual device heartbeat/online state and saved captures feed health.
- Whether a paid cloud plan is necessary after a trial, retention, URL expiry,
  event-type meanings and rate limits remain unknown. Image dimensions are now
  verified by the live checks above. No plan was purchased during these checks;
  the user set the camera's trigger interval to one minute.

For future provider diagnostics, use the operator probe in
`backend/app/ingestion/ubox_probe.py` from the Db01 venv. Its CLI help describes credential entry,
scrubbed diagnostic output and the optional local detector check. Record the
actual observations here; never include a password, token, signed image URL or
SIM identifier. If the account lists motion events without image URLs, Settings
shows the no-snapshot count instead of creating broken gallery images. Confirm
cloud-plan requirements in UBox Pro before buying anything.

## Picture volume and app behavior

Settings → Camera accounts now has a **SPYPOINT / UBox Pro** provider choice. UBox Pro
credentials are verified, encrypted and saved through the same account flow.
Connecting imports the previous seven days. A connection made during another
pipeline run gets that initial history on the next scheduled sync.

UBox Pro defaults, separately enforced for every camera on the account:

- **Minimum gap: 60 seconds** between saved snapshots (adjustable 10–3600).
- **Daily ceiling: 500 snapshots**, by the estate's local calendar day
  (adjustable 1–5000).

These are import limits, not camera trigger settings. Extra snapshots are skipped
before download and AI; the camera keeps recording according to its own settings.
Skipped events can include a brief animal sighting. UBox cloud originals remain
subject to the vendor's retention. Changing the limits affects future imports and
the normal overlapping retry window; it does not recover all previously skipped
history. Existing GameSense images are retained.

Events are processed newest first within daily backfill windows, prioritizing
current sightings over potentially expired history. The importer
counts stored snapshots as well as newly accepted ones, including both neighbors
of a late-arriving event, so reruns, backfills and midnight do not bypass the gap.
Database advisory locks serialize imports for a camera. Event IDs and per-camera
file hashes remove duplicates. Settings shows the latest added, interval-skipped,
daily-limit-skipped, missing-snapshot and failed counts; `sync_log.details` keeps
the corresponding per-camera counters.

Snapshot bytes must decode as a bounded JPEG before an Image row is saved. Files
are written atomically beneath the normal media directory with hashed, Windows-
safe basenames. Cameras and Animals use the same authenticated local image route
as SPYPOINT. Detection, classification, notifications and nightly exposure then
use the existing pipeline. The importer never relies on a signed vendor URL for
gallery display and never creates blank tiles for failed downloads.

The normal 15-minute scheduled sync and the app's Sync button include UBox; no
additional scheduled job is required. Pagination is bounded and paced; saturated
daily queries split into smaller periods (down to one minute) so a high trigger
rate does not exhaust a fixed daily page allowance. Five failed
snapshot imports stop a daily window; failures leave its watermark unchanged for
retry. SyncLog records errors without passwords, tokens or signed URLs.

## Implementation validation

- Full backend suite after live-protocol fixes: **241 passed**, with database tests required, against an
  isolated local PostgreSQL instance. No production database was used.
- After the final recovery changes: **23 UBox sync tests passed**, covering
  local image serving, Animals/species gallery integration, notification dispatch
  wiring, adaptive pagination, expired historical URLs, commit/file recovery and
  concurrent imports sharing the same allowance.
- **43 client/probe tests** (including the additional scrubbed live-response test)
  and **16 account API tests** passed. Classifier outputs in tests are synthetic,
  so these tests do not measure real-camera AI quality.
- Frontend typecheck and production build passed. Mocked browser checks exercised
  provider selection, validation, connecting, editing saved limits and layout at
  320/390/768/1280 px.
- Migration tests cover a fresh install, repeated upgrades and actual prior-schema
  upgrades while retaining credentials, camera IDs and images.

Two unrelated calibration tests used September 2025 dates that had fallen outside
their rolling one-year window; their fixtures now use relative recent dates.
The ORM also now declares the zones index already created by migration 0010, so
fresh-schema comparison is accurate. No unrelated production behavior changed.

The automated checks use synthetic accounts and inference outputs. The separate
live checks above used the actual authorized account and real inference. Db01
deployment and all 18 live gallery image endpoints are verified as recorded above.

# Deliverable 5 — SPYPOINT Integration Plan

Built on the **kept** logic in the legacy `spypoint_sync.py`, hardened into a production client.

## Confirmed API surface (from working legacy code)

Base: `https://restapi.spypoint.com/api/v3`

| Call | Method | Endpoint | Body / notes |
|---|---|---|---|
| Login | POST | `/user/login` | `{username, password}` → `{ token }` (Bearer) |
| List cameras | GET | `/camera/all` | `Authorization: Bearer <token>` → camera objects |
| List photos | POST | `/photo/all` | `{ camera:[id], dateEnd, favorite:false, hd:false, limit }` → `{ photos:[…] }` |
| Photo URL | — | — | reconstruct `https://{large.host}/{large.path}` (fallback `small`, then `url`/`originUrl`) |

This endpoint set and the host/path URL reconstruction are the genuinely valuable knowledge we're preserving.

## What the new client adds (the production gaps)

1. **Real image download.** Fetch the reconstructed URL and persist the bytes to `media/…` (fixes audit bug C2). Dedupe by `file_hash` + `spypoint_photo_id`; skip if already on disk.
2. **Pagination & backfill.** Legacy fetches only the latest 50. New client pages using `dateEnd` as a backward cursor (oldest photo's timestamp → next page) for a **one-time 12-month backfill task**, and uses a stored "last seen photo time" for **incremental** sync (fetch only newer than last sync).
3. **Camera metadata extraction.** Read and persist **battery, signal, GPS (lat/lng), model, last-activity** from the `/camera/all` response into `cameras`. (Exact field names verified on first live call — see Unknowns.)
4. **Token lifecycle.** Cache the bearer token; on `401`, re-authenticate once and retry. Handle expiry transparently.
5. **Resilience.** Timeouts, exponential backoff on `429/5xx`, per-camera isolation (one camera failing doesn't abort the run), structured `sync_log` rows with counts + errors.
6. **Credentials.** From encrypted app settings / env (`SPYPOINT_USERNAME`, `SPYPOINT_PASSWORD`); never logged, never committed.
7. **Timestamps are camera wall clock.** `originDate` (and `date`, `dateEnd`) carry the camera's own clock with a `Z` suffix, not UTC: a frame the camera stamps 10:30 arrives as `10:30:00.000Z`. The client reads them as wall times in `ESTATE_TIMEZONE` and stores real UTC, and expresses the `dateEnd` cursor the same way. Migration `0015_spypoint_local_time` corrected rows imported before this (and their env snapshots) once, recorded under `app_settings.spypoint_capture_times_localized`.

## How a fetch works now (Sep 2026, plan item 4)

- **Paging back to what is already listed.** Each camera keeps `photos_listed_to`: every
  photo captured up to then has been listed. A routine fetch pages back from the newest
  photo to that mark less 48 h (late uploads from a camera out of signal; at most 3
  pages past the mark), at most 20 pages of 100, committing each page with how far it
  got. A camera with no mark yet (fetched before this) pages back to its newest stored
  photo instead. A login whose history was never imported (added while the pipeline
  was busy) gets the 2-month backfill on its first fetch, and counts as imported once
  that has been tried, whatever failed.
- **Outages longer than the cap.** What a fetch cut short (by the cap or an error) did
  not reach is kept as the camera's gap (`photos_gap_from` / `photos_gap_to`); later
  fetches page on through it with what is left of their 20 pages until it is closed.
- **Retried downloads.** A photo whose file fails to download (or cannot be written) is
  stored without one and tried again with the freshest link on the next 5 fetches; a
  repair pass also retries recent file-less rows the listing no longer shows. Once the
  fetch has given up on it (or after a day), the detector lets such a row through as
  "no file", so it stops holding its night as "not checked yet"; if the file comes
  later, the photo is looked at again.
- **Sign-ins are kept.** A login's sign-in token is kept between fetches, sealed like its
  password (`camera_accounts.session_enc`, or the .env login's `app_settings` record),
  and it signs in again only when SPYPOINT (or UBox, whose token lasts weeks) refuses
  it. Re-entering a password starts a new one.
- **One error costs one photo or one camera.** Photo inserts and enrichment run in
  savepoints, pages commit on their own, and a login or camera failing never stops the
  others (or UBox, or the AI pass: `app.ingestion.fetch`).
- **Camera clocks.** An `originDate` more than 30 days before SPYPOINT's `date`, or more
  than 3 h after it, is a reset or wrong clock: the photo is filed at `date` instead.
- **Busy.** A 429 or 5xx with `Retry-After` of up to 30 s is waited out once (SPYPOINT
  and UBox, sign-in included).
- **Login status.** Every fetch records per login (guests on `camera_accounts`, the .env
  login in `app_settings.spypoint_primary_login`) when it last tried, when it last
  worked and, if not, why in words. Settings, the camera cards, the map sheet, the alerts
  and Tonight read it (`app.ingestion.logins`). No good fetch for 2 h is "stopped",
  unless a long job has held the pipeline since before then ("busy"). A camera whose own
  listing failed while its login worked says so on its card (`cameras.fetch_error`).
- **Who fetches a camera.** A camera two logins list belongs to the first that lists it
  in a run: the .env login, then guests' in the order they were added. A copy of the
  .env login (added before copies were refused) is not fetched, and its cameras go back
  to the .env login.
- **Cameras no login lists.** A camera no login listed is switched off (`active = false`)
  once the login that fetched it has listed its cameras without it, or when it has no
  login any more: shown as "Not connected", left out of Tonight's ranking, photos kept
  (and still in the Photos camera filter). A login listing it again switches it back on.

## Client shape

```python
class SpypointClient:
    def login(self) -> str: ...                    # cached, auto-refresh on 401
    def list_cameras(self) -> list[CameraDTO]: ...  # incl. battery/signal/gps/model
    def list_photos(self, camera_id, *, since=None, before=None, limit=100) -> list[PhotoDTO]: ...
    def photo_url(self, photo: PhotoDTO) -> str: ... # ported large→small→url fallback
    def download(self, url: str) -> bytes: ...
```

`ingestion/sync.py` orchestrates: for each active camera → upsert metadata → page photos since `last_sync` → download + insert `images` → enqueue `enrich.env` + `ai.infer` → write `sync_log`.

## Scheduling

- Celery beat task `spypoint.sync` on a configurable interval, **default 15 min** (spec).
- Separate throttled `spypoint.backfill` task for the initial 12-month pull, rate-limited to be gentle on the API and the CPU inference queue behind it.
- Manual "Sync now" button → enqueues the same task (returns immediately; no more blocking requests — fixes audit M1/sync-blocking).

## Unknowns to verify on first live run

These can't be confirmed from static code; the client logs the raw first response (once) so we can map fields precisely:

- Exact field names/units for **battery %, signal, GPS** in `/camera/all`.
- **Token TTL** and whether a refresh endpoint exists (we assume re-login on 401).
- Whether **HD** originals are available (`hd:true`) and worth the bandwidth/storage given the 24 GB disk limit.
- **Rate limits** (to tune backoff and backfill pacing).
- Whether SPYPOINT returns server-side **species tags** (legacy `classify_from_spypoint_tags` hints at a `tags`/`tag` field) — if present, useful as a weak label to cross-check our own AI.

## Test plan

Unit-test the client against **recorded fixtures** (captured first live response, secrets stripped) — auth, pagination cursor math, URL reconstruction, dedupe, metadata mapping, 401-retry. Per spec, ingestion is one of the three "risky bits" that must have tests.

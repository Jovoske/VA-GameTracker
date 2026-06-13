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

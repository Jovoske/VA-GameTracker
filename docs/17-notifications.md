# Notifications — a push when a camera sees an animal you care about

A hunter should not have to open the app to learn that a sounder crossed PL19 at
22:14. GameSense now pushes that to the phone, and each person chooses which
animals they hear about from **Settings → Notifications**.

## What the user sees

- **Sighting alerts** — the master switch for their account. Turning it on also
  asks the browser for permission and subscribes that device.
- **Notify me about** — one switch per species, most-seen first. Defaults to the
  priority species (boar, red/roe/fallow deer, fox, mouflon, ibex, badger).
- **Send a test** — pushes a test message to every device they have subscribed.
- **Recent** — the last few notifications, with "no device" / "not delivered" when
  push did not reach anything. This is how a quiet night is told apart from a
  broken subscription.

Each device subscribes from that device: a phone and a tablet are two rows in
`push_subscriptions`, both owned by the same user. Turning alerts off silences
all of them.

### iPhone

Safari only delivers web push to an app installed on the Home Screen (iOS 16.4+),
never to a tab. The settings card says so when it detects Safari-in-a-tab, and the
switch does the account half regardless, so the device can be subscribed later from
the installed app. Push also needs a secure origin, so it works at
`https://gamesense.daa-ops.com` and not at `http://db01:8090`.

## How it works

```
pipeline sync (every 15 min)
  └─ classify_unclassified()            new Detection rows
       └─ dispatch_new_sightings()      app/notifications/dispatch.py
            ├─ detections created since the watermark, photos < 24h old
            ├─ grouped per species: cameras, photo count, latest time
            ├─ one Notification row per (user, species) for users whose prefs match
            └─ push.send_to_user()      pywebpush, VAPID-signed, aes128gcm
```

**Trigger.** The dispatcher runs at the end of every classification pass, whether
that pass came from the scheduled `sync`, the in-app "Sync now" / "Scan" buttons,
or a guest connecting a SPYPOINT account. No new scheduled task is needed.

**Watermark, not flags.** `app_settings.notify_cursor` holds the newest
`detections.created_at` already announced. The first run ever only primes it: a
fresh install has a season of photos and none of them are news.

**Two guards** keep this an alert rather than a firehose:

- photos captured more than `NOTIFY_LOOKBACK_HOURS` (24) ago are never announced,
  so a backfill stays silent;
- one notification per species per run however many frames a sounder produced,
  and a run with more than five species for one person collapses into a single
  summary ("12 new sightings, 6 species").

**Keys.** The VAPID key pair is generated on first use and stored in
`app_settings` (`vapid`). Nothing to configure. Rotating it would force every phone
to re-subscribe, which the frontend handles: a subscription made under a different
server key is dropped and remade.

**Dead devices.** A push service answering 404/410 deletes the subscription; ten
consecutive failures of any other kind do the same. A push failure never fails the
classification pass.

## Tables (migration 0012)

| Table | Holds |
|---|---|
| `app_settings` | key → JSON: the VAPID pair, the dispatch watermark |
| `notification_prefs` | per user: `enabled`, `species_ids` (JSON list) |
| `push_subscriptions` | per device: endpoint (unique), `p256dh`, `auth`, owner, failure count |
| `notifications` | what was sent: title, body, url, species, photo, `push_status`, `read_at` |

## API

All per-user, any role.

| Route | Does |
|---|---|
| `GET /api/notifications/settings` | prefs + species list + VAPID public key + device count |
| `PUT /api/notifications/settings` | `{enabled?, species_ids?}` partial update |
| `POST /api/notifications/subscriptions` | register this browser's `PushSubscription.toJSON()` |
| `DELETE /api/notifications/subscriptions` | `{endpoint}` |
| `GET /api/notifications?limit=` | the user's feed, newest first, with unread count |
| `POST /api/notifications/read` | mark all read |
| `POST /api/notifications/test` | push a test to the user's devices |

## Config

| Variable | Default | Meaning |
|---|---|---|
| `VAPID_SUBJECT` | `mailto:<ADMIN_EMAIL>` | contact a push service may use about this sender |
| `NOTIFY_LOOKBACK_HOURS` | `24` | photos older than this are never announced |

## Deploying

`backend/requirements.txt` gained `pywebpush==2.3.0` (the last release that accepts
the pinned `cryptography==44.0.0`), which `deploy/update.ps1` installs because the
manifest changed. Migration 0012 is idempotent and runs on the same update. Nothing
to register: dispatch rides on the existing `GameSense-Sync` task.

## Checking it on the server

```powershell
# the key pair and watermark exist once the first sync after deploy has run
Invoke-Command -ComputerName Db01 {
  & C:\GameSense\pg\pgsql\bin\psql.exe -p 5433 -U gamesense -d gamesense -c "select key, updated_at from app_settings"
}

# what the dispatcher did on the last sync
Invoke-Command -ComputerName Db01 {
  Select-String -Path C:\GameSense\logs\*.log -Pattern 'notify.dispatched|notify.failed|push\.' | Select-Object -Last 20
}
```

Then on the phone: install to the Home Screen, sign in, Settings → Notifications →
Sighting alerts on → allow → **Send a test**.

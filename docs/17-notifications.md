# Notifications — a push when a camera sees an animal you care about

A hunter should not have to open the app to learn that a sounder crossed PL19 at
22:14. GameSense now pushes that to the phone, and each person chooses which
animals they hear about from **Settings → Notifications**.

Every push is written in the language of the person it goes to (their
`users.language`), whoever's run sends it; see [19-languages.md](19-languages.md).
The examples below are the English.

## What the user sees

- **Alerts** — the master switch for their account. Turning it on also asks the
  browser for permission (straight from the tap, before anything is saved: an
  iPhone only shows the prompt while the tap is fresh) and subscribes that device.
  The line under it says what the app found when it checked this phone on both
  sides, the browser's subscription and the server's copy of it: "This phone gets
  alerts", "Set up on this phone, but the server couldn't be reached to check it"
  (with **Check again**), or "not getting alerts yet" (with **Get alerts on this
  phone**).
- **Tonight's plan before sunset** — opt-in: one push a day, about two hours
  before sunset, with the whole plan on the lock screen:
  "▲ Charca · wind right · sunset 19:56" / "Best odds. Wild boar, best 20:40 to
  22:10." Every day, quiet nights too. See *Tonight's plan* below. It comes
  through Alerts, so turning it on while Alerts are off turns Alerts on too, from
  the same tap (permission asked, this phone subscribed), and says so: "Alerts are
  on too; the plan comes with them. Switch off any animal below you don't want."
- **Notify me about** — one switch per species, most-seen first. Defaults to the
  priority species (boar, red/roe/fallow deer, fox, mouflon, ibex, badger).
- **Quiet hours** — optional, on the estate's clock (23:00 to 07:00 to start;
  either time can be changed, and they may run over midnight). Nothing buzzes
  inside them; what comes in waits and arrives as **one message** when they end
  ("During your quiet hours" / "Wild boar 3 visits and Red deer 1 visit, last one
  04:10 last night."). If the photo check finds something new before the notify
  run has sent that message, the message goes first and is the buzz: the new
  sighting of the same animal is then a quiet update, not a second buzz.
- **While you sit** — nothing buzzes from Start sit to End sit, whatever the
  settings: a phone lighting up in the high seat is the worst thing it can do.
  What came in arrives as one message ("While you sat") the moment END SIT is
  tapped; a sit nobody ended stops holding when it stops being on (06:00, or 12
  hours after it started), and the message goes on the next `notify` run.
- **Send a test** — pushes a test message to every device they have subscribed.
- **Recent** — the last few notifications, with how each one went: "waiting", "in
  one message", "not sent", and "no device" / "not delivered" when push did not
  reach anything. This is how a quiet night is told apart from a broken
  subscription. Quiet updates are not listed on their own: an alert shows its
  latest running total and "2 quiet updates", so one sounder all night is one row
  per buzz and the plan and team notes stay in view.

The animal switches, quiet hours and the plan switch save a moment after the last
tap, one save at a time; the screen says "Saving…" and then "Saved." under what
changed, or, if a save fails, shows what the server has and says why. With no
signal the server can't be asked either: the switches go back to the last copy the
server confirmed (on opening, or at the last save that went through), so the
screen never shows a choice that wasn't saved.

- **Cameras** — one switch per camera, all on to start. Muting one (the busy
  feeder) stops every alert from it for that person only; the rest of the team
  still hears from it. The same switch is on the camera's sheet on the map
  ("Alerts from this camera"). Each tap saves at once and says so under the
  switch ("Saved. No alerts from Charca."); a save that fails puts the switch back
  and says why.
- **Worth a look** — when a teammate marks a photo and turns on "Tell the team",
  everyone else with alerts on gets one push: "Worth a look: Wild boar at Charca" /
  "Pedro: Big boar, third night running". It opens that photo. It is not a species
  alert, so it comes whichever animals you picked, but never from a camera you
  muted.

Each device subscribes from that device: a phone and a tablet are two rows in
`push_subscriptions`, both owned by the same user. Turning alerts off silences
all of them.

### iPhone

Safari only delivers web push to an app installed on the Home Screen (iOS 16.4+),
never to a tab. It also shows every push as a new banner that sounds: it ignores
`renotify`, `silent` and `tag` (MDN browser-compat-data). So an iPhone is not sent
the quiet updates inside the two-hour cooldown (`push.apple()` spots Apple's push
service, `web.push.apple.com`): it gets the buzz, once per animal per two hours,
and the running total is in Recent. Settings says so on an iPhone ("One buzz per
animal every two hours. On an iPhone the count goes on in Recent below."). The settings card says so when it detects Safari-in-a-tab, and the
switch does the account half regardless, so the device can be subscribed later from
the installed app. Push also needs a secure origin, so it works at
`https://gamesense.daa-ops.com` and not at `http://db01:8090`.

## How it works

```
pipeline sync (every 15 min)
  └─ check_photos()                     app/ai/checking.py: new Detection rows
       └─ dispatch_new_sightings()      every 20 photos, and at the end
            ├─ detections created since the watermark, photos < 24h old
            ├─ grouped per species: cameras, visits (not frames), latest time
            ├─ one Notification row per (user, species) for users whose prefs match
            └─ push.send_to_user()      pywebpush, VAPID-signed, aes128gcm
```

**Trigger.** The dispatcher runs after every batch of 20 photos the AI pass checks,
and at its end, whether that pass came from the scheduled `sync`, the in-app "Check
for new photos" button, or a guest connecting a camera login (each a `pipeline.py`
run). No new scheduled task is needed.

**Watermark, not flags.** `app_settings.notify_cursor` holds the newest
`detections.created_at` already announced. The first run ever only primes it: a
fresh install has a season of photos and none of them are news.

**Guards** keep this an alert rather than a firehose:

- photos captured more than `NOTIFY_LOOKBACK_HOURS` (24) ago are never announced,
  so a backfill stays silent;
- one notification per species per run however many frames a sounder produced,
  and a run with more than five species for one person collapses into a single
  summary ("12 new sightings, 6 species"), which opens Photos on those animals;
- **one buzz per animal per two hours** (`COOLDOWN`). The sync runs every 15
  minutes, so one sounder at the feeder used to buzz the phone every 15 minutes
  all night. Inside the two hours the push still goes, as a quiet update of the
  banner already on the phone (`renotify: false, silent: true`, same tag), with
  the running total since the buzz: "Wild boar at PL19" / "3 visits since 00:55,
  last one 02:40." Not to an iPhone, which would sound it (see *iPhone*). Each
  alert keeps what it counted (`notifications.detail`: visits, cameras, first and
  last frame, the photos), a quiet update names the alert it updates
  (`detail.update_of`), and a boar that stayed across two checks is one visit, not
  two;
- nothing is pushed while the person is sitting or inside their quiet hours: the
  record is kept as `held` and goes out as one message after
  (`app/notifications/hold.py`). Team notes ("Worth a look") wait the same way.
  The message is about what is still there when it goes: each held alert kept its
  photos, and they are looked up again under the rules every screen uses, so a
  photo marked "nothing in it" while it waited, an animal hidden or no longer
  picked, or a camera muted since, is left out and the visits counted again. If
  nothing is left, no message goes (the records say `withdrawn`, "not sent" in
  Recent).

**The day in the text.** The day goes by the night, as every screen counts nights
(06:00 to 06:00), not by the calendar. A boar at 23:50 told of at 00:30 is the same
night and says only "23:50"; read the next morning it says "1 visit at 23:50 last
night." (one seen in daylight the day before, "yesterday"), and anything older has
its date, "23:50 on Thu 24 Sep".

**The photo's time in the link.** A sighting's link is
`/photos?species=wild_boar&image=<id>&at=<captured_at>`. Photos opens the photo if
it is on the first page; otherwise it asks for the frames up to that time and opens
the photo among them (its burst), however many newer photos came in since; a photo
hidden or deleted since says so in one line.

**Visits, not photos.** The count in a push is visits, as on every other screen:
frames of one species at one camera within 30 minutes of each other are one visit.
One boar's burst of three frames reads "Wild boar at PL19 Charca / 1 visit at
03:00.", not "3 photos". The species is written as the app writes it ("Wild boar",
"Roe deer"), not as stored.

**Muted cameras.** Each person's digest is built only from their unmuted cameras,
so a muted camera is as if it saw nothing: no push and no line in Recent (the
point of muting the feeder is to stop hearing about it). A run where only a muted
camera saw something tells that person nothing.

**Keys.** The VAPID key pair is generated on first use and stored in
`app_settings` (`vapid`). Nothing to configure. Rotating it would force every phone
to re-subscribe, which the frontend handles: a subscription made under a different
server key is dropped and remade.

**Dead devices.** A push service answering 404/410 deletes the subscription. Any
other failure (the server's own internet, DNS, a push service's bad hour) says
nothing about the phone: a subscription is dropped for failing only after ten
failures in a row *and* no push taken for 14 days. It used to go after ten failures
of any kind, so one evening's blip ended a hunter's alerts while Settings still said
"This phone gets alerts". Besides, the app sends its subscription every time it
opens (`checkThisDevice` in `src/push.ts`; the server keeps one row per endpoint),
which puts back a lost copy, and the service worker subscribes again when the
browser replaces a subscription (`pushsubscriptionchange`) and asks the open app to
send it. A push failure never fails the classification pass.

**Signing out** removes this phone's subscription on both sides (with the leaving
person's token, best effort, so it works with no signal), so a borrowed phone stops
getting the last person's alerts.

## Tonight's plan

`pipeline.py notify` (task `GameSense-Notify`, every 15 minutes) sends it once it is
two hours before tonight's sunset, never after sunset, once per person per night
(`app/notifications/plan.py`). Task Scheduler can't start a job at sunset, which
moves by three hours over the season, hence the 15-minute run. The run writes a
`plan` row per person and night under a per-night lock before pushing anything, so
two runs at once can't both send it. A send that reached no phone (`failed` or
`no_subscription`: the server's internet down for a moment, or a phone whose copy
was lost and not yet put back by the app) is tried again by the next run until
sunset, on the same row (`detail.tries`).

It reads the plan on record for tonight, the claim the 17:00 `plan` run writes (the
one scored tomorrow): the top camera by verdict and odds, its animal and best hours.
From late October the push is due before 17:00, and then the plan is worked out as
Tonight works it out, without writing a claim. The wind is judged at the stand for
that camera, for the sit time, as Tonight judges it: "wind right", "wind wrong",
"wind too light to call" or "no wind forecast"; a stand that can't be judged leaves
the wind out. Someone already sitting or in their quiet hours isn't sent it (the
row says `skipped`).

`notify` also delivers the one message after quiet hours or a sit nobody ended. It
loads no model, takes seconds, and has a lock of its own (`notify.lock`), so it
never waits behind the photo check; `pipeline.py busy` counts it, so a deploy waits
for it.

## Tables (migration 0012)

| Table | Holds |
|---|---|
| `app_settings` | key → JSON: the VAPID pair, the dispatch watermark |
| `notification_prefs` | per user: `enabled`, `species_ids` (JSON list) |
| `push_subscriptions` | per device: endpoint (unique), `p256dh`, `auth`, owner, failure count |
| `notifications` | what was sent: title, body, url, species, photo, `push_status`, `read_at`; `kind` is `sighting`, `team_note` or `test` |

Migration `0019_camera_alerts_photo_notes` adds `notification_prefs.muted_camera_ids`
(JSON list of camera ids, default `[]`, so every camera starts on) and the
`photo_notes` table behind "Worth a look" (see `docs/map-ux-update.md`).

Migration `0029_quiet_alerts_and_plan_push` adds `notification_prefs.quiet_start` /
`quiet_end` (local times, both or neither), `notification_prefs.plan_push` (off for
everyone until they turn it on) and `notifications.detail` (JSON: what a sighting
counted, why one was held, a plan's night). `kind` gains `summary` (the one message
after a sit or quiet hours) and `plan`; `push_status` gains `updated`, `held`,
`in_summary`, `skipped` and `withdrawn`.

## API

All per-user, any role.

| Route | Does |
|---|---|
| `GET /api/notifications/settings` | prefs (with `quiet_start`, `quiet_end`, `plan_push`) + species list + cameras with their switch + VAPID public key + device count |
| `PUT /api/notifications/settings` | `{enabled?, species_ids?, muted_camera_ids?, quiet?, quiet_start?, quiet_end?, plan_push?}` partial update, answered with what was saved; unknown or other estates' cameras are a 400, and so are quiet hours with no end or ending when they start |
| `PUT /api/notifications/cameras/{id}` | `{alerts}`: one camera on or muted, for you; answers with `enabled` too |
| `POST /api/notifications/subscriptions` | register this browser's `PushSubscription.toJSON()` (again on every app open); answers with the device count, the server's key and whether alerts are on |
| `DELETE /api/notifications/subscriptions` | `{endpoint}` |
| `GET /api/notifications?limit=` | the user's feed, newest first, with unread count; quiet updates folded into the alert they update (`updates`, `updated_at`, and its latest title and body) |
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
manifest changed. Migration 0012 is idempotent and runs on the same update. Dispatch rides on
the existing `GameSense-Sync` task. The plan push and the message after quiet hours
need `GameSense-Notify`: re-run `deploy/register-tasks.ps1` once (idempotent).

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

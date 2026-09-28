# GameSense

**Turn your trail cameras into a hunting forecast.**

A local-first wildlife-intelligence platform: it ingests SPYPOINT camera images, identifies and
profiles European game with AI, correlates sightings with weather / moon / solar / wind, and
produces plain-language recommendations — where to sit tonight, when, for what, and which stands to
avoid. The product is the **Tonight card** and the **Map**, not a photo gallery.

> Built for the Piedras Lisas estate (Alatoz, Spain). European wildlife only.

---

## Quick start (Docker)

1. **Install Docker Desktop** (one time): https://www.docker.com/products/docker-desktop/
2. From this folder, run:

   ```bat
   start.bat
   ```

   (or `docker compose up --build`). This brings up Postgres (PostGIS + pgvector), Redis, the API,
   a background worker, the scheduler, and the frontend, runs migrations, and seeds an admin user.

3. Open **http://localhost:8080** and sign in with the credentials from `.env`
   (`ADMIN_EMAIL` / `ADMIN_PASSWORD`, default `admin@gamesense.local` / `changeme`).

The API is at **http://localhost:8000** (interactive docs at `/docs` when `ENABLE_API_DOCS=1`;
they are off by default so the public address doesn't hand out a map of every endpoint).

The server itself (`backend/serve.py`, how Db01 runs it) never runs on the published
`JWT_SECRET`: it writes a fresh one into `backend/.env` as it starts (everyone signs in
again once). An admin on the published password can't sign in with it from the internet,
only on the server's own network. From `backend/`: `python -m app.manage new-secret` and
`python -m app.manage set-password EMAIL`. `APP_ENV=development` skips all of it on a laptop.

Edit `.env` (created from `.env.example` on first run) to set your SPYPOINT credentials and secrets.

---

## What works (September 2026)

The whole [improvement plan](docs/improvement-plan.md) is in, apart from two features the owner
parked for later (18, Tonight names a stand; 21, shooting arcs and safety). In short:

- **Photos in, none lost.** SPYPOINT, UBox and Suntek (FTP or email) photos come in on a schedule; a
  download that fails is tried again while the camera still lists it, an outage is caught up, and a
  login that stops is said on Settings, the camera card and Tonight. A photo whose file never came
  leaves its night "not watched", never "no animals".
- **The AI reads the estate right.** MegaDetector and DeepFaune with the estate's species list, a
  confidence floor, one vote per visit, people and vehicles kept to the admin; a hunter's fix from the
  photo viewer (**Wrong?**) is never overwritten.
- **Tonight** ranks the cameras that can be judged, in visits over watched nights (18:00 to 06:00, the
  same night the Changed line, Insights and the track record count), with best hours that follow
  sunset, one wind verdict for the sit time, the hour-by-hour wind for the week, and the plan on the
  phone about two hours before sunset. It shows the saved plan at once with no signal, and says how old.
- **Sits** are never lost or overwritten: a report only goes up, a tap with no signal is queued and
  sent later, a stand can't be reserved twice, and the morning after asks about an unreported sit and
  a shot (the harvest book, with its season CSV).
- **The map** (WeHunt-style): cameras as their latest photo, Activity and Replay, stands and bedding,
  + / − zoom buttons, and the whole estate downloadable for no signal (details below).
- **Alerts that respect the hunter:** one buzz per animal per two hours, quiet hours, nothing while
  sitting.
- **Safe to run:** sign-in limits that understand the Cloudflare tunnel, sessions a password change
  ends (and its alerts), short-lived photo passes, role checks; only tested commits deploy, and a
  deploy that doesn't come back healthy rolls back ([deployment](docs/09-deployment.md)).
- **Five languages:** English, Suomi, Svenska, Norsk, Español, for the screens, the server's sentences
  and the pushes ([translations](docs/translations.md); the four non-English ones were machine-written
  and want one read-through by a native-speaking hunter).

### The cameras on the map (September 2026)

The Map tab is built around what the trail cameras see, WeHunt-style ([scope](docs/wehunt-features.md),
[details](docs/map-ux-update.md)). Each camera sits on the map as its latest animal photo with a count of
what is new to *you*; tapping it opens a sheet with last night in visits ("Wild boar · 2 visits"), a strip
of its photos, and its alert switch. **Activity** sizes a circle at each camera by visits per night it was
working, filtered by animal, part of the night and period; **Replay** plays one night back camera by camera,
with a dashed arrow, marked as a guess, where the same animal likely went next. Every view counts visits
(a burst of frames is one visit) over the same 18:00–08:00 night, and hidden species and "nothing in it"
photos never count. Each person can mute a busy camera, and anyone but a viewer can mark a photo
**Worth a look** with a short note, which the team finds on Photos and on that camera's sheet. Hunt
planning, collaboration and safety are parked for later.

### The map with no signal (September 2026)

Map sheet → **Offline** → **Download the estate for offline** keeps the estate's map pictures (IGN aerial or
topo, zoom 11 to 18, only the estate's box, within a size budget), the stands, cameras, bedding and each
camera's sheet on the phone, and says what it has: "Estate map saved on this phone · 38 MB · 2 days ago".
With no signal the map then opens with its pictures, every pin and the camera photos, and says how old
they are. A camera placed by hand stays where it was put, bedding can be renamed and redrawn, the hill
shape loads in the background and reaches every stand, and "Likely paths" come from the replay's links
seen on more than one night ([details](docs/map-ux-update.md)).

### Photos, and putting the AI right (September 2026)

Photos is filed by night ("Last night", "Thu night": 18:00 to 06:00 on the estate's clock, as the server
counts nights) with the daytime ones under the day ("Today", "Yesterday"), and pages on by the last photo's
time and id, so no frame of a burst is lost at a page break; the photo viewer carries on into older photos
as you swipe (on Cameras too), and says so at once when there is no signal for them. In the viewer,
members and admins have **Wrong?**: say what the animal really is, from the animals that can be on the
estate, or "Nothing here" for a false alarm, with Undo. The fix is the hunter's: the AI never changes it
back, a burst is one animal so the rest of the visit follows it, and every list, count, the map and the
forecast read it. Undo puts the photo, and its visit, back exactly as the AI had them.
Animals are called what hunters call them ("Hare or rabbit", "Mouse or rat", "Marten or weasel"), and an
admin can rename any of them in Settings. A name given to an animal on Animals survives "Look for repeats"
and merges, and its gallery pages to the oldest photo.

See [`docs/`](docs/00-overview.md) for the full design (audit, architecture, schema, SPYPOINT,
AI pipeline, forecasting, deployment, Git self-update). Build order and roadmap are in
[`docs/00-overview.md`](docs/00-overview.md).

---

## Project layout

```
backend/     FastAPI app, SQLAlchemy models, Alembic, Celery tasks, tests
frontend/    React + TypeScript (Vite), MapLibre to come in M1/M3
docker/      service Dockerfiles (custom Postgres with PostGIS + pgvector)
docs/        design & decision documents (the pre-build deliverables)
compose.yaml one-command local stack
start.bat    Windows launcher
```

## Local development notes

Suntek HC801LTE cameras have two optional input paths: the [email mailbox poller](docs/16-suntek-email.md) (outbound IMAP only, works behind a locked-down network; the one in use on Db01) and the [FTP receiver](docs/14-suntek-ftp.md) (needs an inbound port). Both feed the same importer; the services are opt-in.

The agent deploying this integration should start with the [Suntek server handoff](docs/15-suntek-server-handoff.md).

- **Backend tests:** `cd backend && pip install -r requirements-dev.txt && python -m pytest`
- **Frontend typecheck/build:** `cd frontend && npm install && npm run build`
- **Migrations:** generated against the running Postgres — `alembic revision --autogenerate -m "..."`.
- Secrets live in `.env` (gitignored). Never commit real credentials.

## Tests, and what reaches the server

Every push and pull request runs `.github/workflows/ci.yml`, and the server only
installs a commit on `main` that passed all of it
([deployment](docs/09-deployment.md#the-loop)):

- **Backend:** the tests against a real PostgreSQL built from `docker/postgres`
  (PostGIS + pgvector). On a laptop, point them at one and make a missing database
  fail rather than skip:

  ```bash
  cd backend
  GAMESENSE_TEST_DSN=postgresql+psycopg://postgres:postgres@localhost:5432/postgres \
  GAMESENSE_REQUIRE_DB=1 python -m pytest -q
  ```
- **Ruff:** no errors, and no new finding in a backend file a change touches:
  `cd backend && python scripts/ruff_ratchet.py origin/main`.
- **Frontend:** `npm run build`.
- **UI scripts** (`frontend/tests/*.cjs`, Playwright with its own Chromium) against a
  started stack. Most answer `/api` from a fake server of their own; a few sign in to
  the real API as the made-up people of `backend/scripts/demo_data.py`:

  ```bash
  # the API, on an empty database (never the real one)
  cd backend
  alembic upgrade head && python -m app.seed && python scripts/demo_data.py
  python -m uvicorn app.main:app --port 8000 &
  # the app, built (two scripts serve dist/) and served by Vite in front of the API
  cd ../frontend && npm run build && npx vite --port 5173 &
  # every script, or name some: npm run test:ui -- stands insights
  PLAYWRIGHT_MODULE=/path/to/node_modules/playwright npm run test:ui
  ```

  `frontend/tests/run.sh` lists the settings it reads (`BASE_URL`, `API_URL`,
  `PW_CHANNEL` for Edge or Chrome instead of Chromium, `UI_TIMEOUT`, `UI_LOGS`), runs
  the scripts one after another and fails if any does.
- **The schema guard:** `backend/tests/fixtures/schema/snapshot.sql` is a database
  migrated long ago; the tests upgrade it and fail when a model changed with no
  migration. After adding a migration, refresh it with
  `cd backend && python -m tests.schema_snapshot` (needs `pg_dump`).

## Roadmap

- **M1** — real SPYPOINT sync (image download, battery/signal, pagination) + correct weather/moon/solar enrichment.
- **M2** — AI: MegaDetector + DeepFaune (European), bounding boxes, annotated images.
- **M3** — the Tonight card: per-stand forecast, wind-safe analysis, GO/MARGINAL/SKIP with reasons.
- **Tier 2+** — individual re-ID, movement inference, correlations, alerts, Git self-update panel.
- **Notifications** — per-species push to the phone (Settings → Alerts on my phone): one buzz per animal every two hours with quiet updates between (an iPhone, which would buzz for each, gets the buzz alone), nothing while you sit or in your quiet hours (one message after), and an opt-in plan push about two hours before sunset; see [docs/17-notifications.md](docs/17-notifications.md).

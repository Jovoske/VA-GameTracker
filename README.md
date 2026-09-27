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

The server itself (`backend/serve.py`, how Db01 runs it) refuses to start with the
published `JWT_SECRET` or while an admin still has the published password. The fixes
are one command each, from `backend/`: `python -m app.manage new-secret` and
`python -m app.manage set-password EMAIL`. `APP_ENV=development` skips the check on a laptop.

Edit `.env` (created from `.env.example` on first run) to set your SPYPOINT credentials and secrets.

---

## What works today (Milestone 0)

A runnable foundation:

- One-command Docker startup; six services wired together with health checks.
- PostgreSQL + PostGIS + pgvector schema (full model) via Alembic migrations.
- FastAPI backend with secure login (Argon2 + JWT), health/readiness probes, structured logging.
- Celery worker + beat scheduler (SPYPOINT sync is a heartbeat until M1).
- React + TypeScript frontend shell: login + an honest "still learning" Tonight placeholder.

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

## Roadmap

- **M1** — real SPYPOINT sync (image download, battery/signal, pagination) + correct weather/moon/solar enrichment.
- **M2** — AI: MegaDetector + DeepFaune (European), bounding boxes, annotated images.
- **M3** — the Tonight card: per-stand forecast, wind-safe analysis, GO/MARGINAL/SKIP with reasons.
- **Tier 2+** — individual re-ID, movement inference, correlations, alerts, Git self-update panel.
- **Notifications** — per-species push to the phone (Settings → Notifications); see [docs/17-notifications.md](docs/17-notifications.md).

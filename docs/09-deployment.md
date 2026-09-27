# Deployment — how code reaches the server

GameSense runs natively (no Docker) on **Db01**, a Windows Server 2022 VM.
Deploying is **`git push` to `main`**: GitHub runs the tests, and the server puts a
commit live within 10 minutes of it passing them. A commit that fails them never
reaches the server.

## The loop

```
laptop --git push main--> GitHub --CI: tests--> `deploy` branch --(<=10 min)--> Db01
```

**The test gate.** `.github/workflows/ci.yml` runs on every push and pull request:

- the backend tests against a real PostgreSQL (the repo's own PostGIS + pgvector
  image, `docker/postgres`) with `GAMESENSE_REQUIRE_DB=1`, so a missing database
  fails instead of skipping;
- ruff: errors anywhere, and no new finding in any backend file the change touches
  (`backend/scripts/ruff_ratchet.py`: the old findings stay until someone is in that
  file anyway);
- the frontend build (`tsc` + `vite build`);
- every UI script in `frontend/tests` against a started stack (API with demo data
  from `backend/scripts/demo_data.py`, Vite in front of it), with Playwright's
  Chromium (`frontend/tests/run.sh`).

When all of it passes on a push to `main`, the last job moves the **`deploy` branch**
to that commit, only ever forward. The server deploys `deploy`. Until CI has run
once and made that branch, the server deploys `main` as it always did, so nothing
stops when this lands first. A commit can be put live by hand, past the tests, with
`git push origin <commit>:deploy`; don't, unless CI itself is what's broken. If
`main`'s branch protection refuses the Actions bot, allow it to push `deploy`.

**On the server.** `deploy/update.ps1` runs every 10 minutes as the
`GameSense-Update` scheduled task (SYSTEM), at any hour: there is no evening pause
(the owner's decision). A deploy restarts the API for a few seconds, and an open app
rides that out (plan item 1). Each run:

1. Stands down while a job runs (`pipeline.py busy` exits 3): a photo fetch, the AI
   pass, the plan, the score, the stag/hind pass, a notify run.
2. Asks GitHub whether a `deploy` branch exists and fetches it (or `main` when there
   is none). If GitHub doesn't answer, it waits for the next run: it never falls
   back to `main` because the line was down. **Exits quietly when nothing is new** —
   the normal case — after writing `deploy-status.json` (below).
3. Takes **every job's lock** (`pipeline.py hold`, audit H-09) and keeps it until the
   new version answers, so no job starts on new code with the old schema, or has
   its rows moved by a data migration halfway through. A job that waited for a lock
   meanwhile (the plan, the score, a queued Check) starts again on the new code
   rather than finish on a mix of the two. The Check button says "The server is
   installing an update. New photos come in when it finishes." and fetches then.
4. `git reset --hard <commit>`. The server is deploy-only and never carries local
   edits.
5. `pip install` if `backend/requirements.txt` changed (and the camera receiver's, if
   that moved). **Tried twice**, a minute apart (H-04).
6. `serve.py check`: the new version has to load. It also notes in `update.log` what
   the new version will do about the secrets published with GameSense as it starts.
7. `npm install` + `vite build` into `frontend\dist` if anything under `frontend/`
   changed. **Tried twice.** Nothing is live yet: `C:\GameSense\web` still holds the
   old screens (H-05).
8. **A `pg_dump -Fc` to `C:\GameSense\backups`, when a migration is waiting**
   (`alembic current` isn't at the new head). The newest 10 are kept; they are only
   taken before a schema change, so they go back a long way. If the dump cannot be
   taken the deploy stops before the database is touched: a deploy that stops is
   visible and recoverable, a half-applied migration with no backup is neither.
9. `alembic upgrade head`. PostgreSQL runs a deploy's migrations in one transaction,
   so one that fails leaves the database as it was.
10. The new screens go live: `C:\GameSense\web` is copied to
    `C:\GameSense\web-previous`, then `frontend\dist` over it.
11. Restarts `GameSenseAPI` (and `GameSenseFTPImport`, `GameSenseFTP`,
    `GameSenseMail` when installed).
12. **`/api/health` must answer "ok" from the new commit within 90 seconds.** It
    answers only when the API can reach its database, and it names the commit the
    running process started from, so an old process that never went away is not
    taken for the new one (H-07).

**When a step fails**, everything it changed goes back: the code (`git reset --hard`
to the last good commit), the packages (pip install of the old requirements), the
screens (`web-previous`), and, if the API was restarted, it is restarted on the old
version and checked again (K-09). The schema stays where the migration took it:
migrations only ever add, so the old code runs on it. To undo a migration, restore
the dump by hand (below): an automatic restore would destroy rows written since.

A commit counts as deployed only once step 12 passes: it is then written to
`C:\GameSense\data\deployed.sha`, and every run deploys what moved since *that*, not
since whatever is checked out. So a failed step is tried again on the next run, 3
times, then every 6 hours or as soon as a newer commit arrives; the old script
skipped a failed pip install or build for good.

Progress goes to `C:\GameSense\logs\update.log`; per-step output to
`update-git.log`, `update-pip.log`, `update-check.log`, `update-npm.log`,
`update-dump.log`, `update-alembic.log`.

**What Settings shows.** Each run writes `C:\GameSense\data\deploy-status.json`
(beside the job locks), and Settings → App version reads it (`app/ops.py`): the
change that runs and since when, whether only tested changes go in, how many newer
changes wait for their tests, and, in red, an update that didn't go in, why, what was
put back and when it is tried again, or that the update task hasn't looked for 30
minutes. The old "Check for updates" asked GitHub for release tags, which stopped at
v0.17.0, and said "Up to date" whatever the server ran (D-22); it is gone.

The script lives in the repo, so it updates itself. The run that pulls a change to
it still runs the old copy (PowerShell reads a script whole before it starts), so a
new step first works on the deploy after the one that brought it. The first run of
this version takes whatever is checked out as deployed.

### Health checks

| | Answers 200 when | Otherwise |
|---|---|---|
| `GET /api/health` | the database answers `SELECT 1`; the body names the version and commit | 503, `"status": "down"` |
| `GET /api/ready` | as above, and the schema is at the code's newest migration; Redis too where a Celery broker is set up (`REDIS_URL`, the Docker stack) | 503, with the check that failed |

The native server runs no Celery and has no Redis, so `/api/ready` doesn't ask about
it there: it used to read "degraded" for ever.

## Scheduled jobs

There is no Celery in the native build — every recurring job is a scheduled task.
`deploy/register-tasks.ps1` registers all of them (idempotent: a task that exists is
brought back to what the script says):

| Task | When | Runs | Does |
|---|---|---|---|
| `GameSense-Update` | every 10 min | `deploy/update.ps1` | the loop above |
| `GameSense-Sync` | every 15 min | `pipeline.py sync` | SPYPOINT and UBox Pro pull + local AI (up to 300 photos, newest first) + exposure recompute |
| `GameSense-Notify` | every 15 min | `pipeline.py notify` | alerts that waited for a sit or quiet hours, as one message; tonight's plan push about 2 h before sunset |
| `GameSense-Sex` | hourly | `pipeline.py sex` | cloud vision stag/hind pass (costs API credit) |
| `GameSense-Plan` | 17:00 daily | `pipeline.py plan` | record tonight's claims **before** the night |
| `GameSense-Score` | 11:00 daily | `pipeline.py score` | grade the claims of every finished night not graded yet (last 14 days) |
| `GameSense-Backup` | 03:00 daily | `deploy/backup.ps1` | the database and the photos to the backup disk (below) |
| `GameSense-RestoreCheck` | Sundays 04:30 | `deploy/restore-check.ps1` | restore the newest backup into a scratch database and check it (below) |

**Their output is kept.** Task Scheduler throws a task's output away, so each task
runs through `cmd.exe` with its errors appended to
`C:\GameSense\logs\tasks-stderr.log`: a job that dies before it can write its own
log (an import that fails) still leaves the reason. `pipeline.py` writes everything
it logs to `pipeline.log` itself; `update.ps1`, `backup.ps1` and `restore-check.ps1`
keep their own logs in the same folder, rolled over at 5 MB.

Sighting notifications are sent by the dispatcher at the end of every
classification pass, so the `sync` task carries them. `notify` is for what can't
wait for new photos: the message after a sit or someone's quiet hours, and the
daily plan push, which Task Scheduler can't anchor to sunset (it moves by three
hours over the season), so the task runs every 15 minutes and sends the plan once
it is due, once a day. See [Notifications](17-notifications.md).

Two optional NSSM services carry the Suntek 4G camera's photos in over FTP; see the
[Suntek guide](14-suntek-ftp.md) and `deploy/install-ftp.ps1`:

| Service | Does |
|---|---|
| `GameSenseFTP` | upload-only FTP receiver for the camera, publishes completed JPEGs to `C:\GameSense\data\ftp-spool` |
| `GameSenseFTPImport` | imports ready packages into the camera gallery every 30 s; the normal `sync` AI pass then classifies them |

`plan` and `score` are what make the forecast falsifiable. Without them nothing
is ever recorded or graded, the Tonight card keeps saying *"0 scored nights"*
forever, and the app is back to making claims nobody checks. Order matters:
`plan` must run before dark or it is not a forecast, and `score` must run after
the night's photos have synced and been classified.

Register them (also checks the backup tools and preflights a `pg_dump`):

```powershell
Invoke-Command -ComputerName Db01 {
    powershell -ExecutionPolicy Bypass -File C:\GameSense\app\deploy\register-tasks.ps1
}
```

The two services (`GameSensePG`, PostgreSQL on port 5433; `GameSenseAPI`, `serve.py`
under NSSM) are checked by `deploy/register-services.ps1`, which on a rebuilt server
also creates a missing one with `-Apply` (it never changes one that exists).

### The pipeline lock

Every `pipeline.py` mode but `sex` and `notify` takes one lock, `C:\GameSense\data\pipeline.lock`
(`backend/app/jobs.py`), so no two runs ever hold the database and the CPU models at
once. The lock is created atomically and names its owner (the mode, process id, host
and start time); the run touches it every minute while it works. A lock whose run
died (its process is gone, or it stopped touching the file 10 minutes ago) is taken
over by the next run, so a crash or a reboot no longer blocks syncing for 3 hours,
and a long backfill that keeps working is never mistaken for a dead one. A run only
ever removes its own lock.

- `sync` (and the app's one-off jobs) give way when the lock is held; the next fetch
  is 15 minutes off.
- `plan` and `score` **wait** for it (up to 40 minutes, inside the tasks' 1-hour
  limit) and exit 1 if it never frees, so Task Scheduler shows a failure rather
  than a silent success.
- `score` grades every finished night of the last 14 days that still has an
  ungraded claim, not only yesterday; a night whose photos were still being
  checked is tried again the next morning.
- If the 17:00 `plan` run never managed tonight's claim, the next fetch or photo
  check writes it, from 17:00 (or an hour before sunset, in December) until sunset.
  Never after dark: a claim made after dark is not a forecast. A `plan` run that
  finds tonight already claimed leaves it be: one claim a night.
- The cloud stag/hind pass (`sex`) has its own lock (`sexpass.lock`): it needs no
  local model, and it must not hold the photo fetch up for an hour. A deploy still
  waits for it, as it did when the pass shared the pipeline lock (`pipeline.py busy`
  answers busy for any of them).
- `notify` has its own lock too (`notify.lock`), so the plan push is never late
  behind an hour of photo checking; two `notify` runs never overlap, and each send
  is also guarded in the database (one plan push per person per night).

The app's buttons (Check for new photos, a new camera login's first import, Look for
repeats, the stag/hind pass) start `pipeline.py` as a process of its own under the
same locks, so the AI models never load into the web server. They are started
through a launcher that exits at once, so the job is not a child of GameSenseAPI:
NSSM stops a service by killing its whole process tree, and a deploy's restart no
longer stops a job a button started. A Check press while Look for repeats (or the
plan or the score) holds the lock is queued (`pipeline.py sync queued`) and fetches
the moment that job ends.

A run that stalls for more than 10 minutes (a paused VM) loses its lock to the next
run; it notices within seconds and stops, rather than checking the same photos
alongside it.

**Logs.** Every run appends to `C:\GameSense\logs\pipeline.log` (rolled over at
5 MB, three old files kept): Task Scheduler throws a scheduled run's output away.
Settings → Photo checking shows the AI backlog, the photos it gave up on and why
the last pass stopped, if it did.

```powershell
# is anything running, and what?
Invoke-Command -ComputerName Db01 { C:\GameSense\venv\Scripts\python.exe C:\GameSense\app\backend\pipeline.py busy }
# what the scheduled runs did
Invoke-Command -ComputerName Db01 { Get-Content C:\GameSense\logs\pipeline.log -Tail 40 }
```

## Layout on Db01

| Path | What |
|---|---|
| `C:\GameSense\app` | git clone of this repo (the deployed code) |
| `C:\GameSense\app\backend\.env` | secrets — gitignored, **never** overwritten by a pull |
| `C:\GameSense\web` | built SPA, served by FastAPI (`FRONTEND_DIST`) |
| `C:\GameSense\web-previous` | the screens before the last deploy, put back if it fails |
| `C:\GameSense\data\media` | permanent photo archive (`MEDIA_ROOT`) |
| `C:\GameSense\data` | also the job locks, `deployed.sha`, `deploy-status.json`, `backup-status.json`, `restore-check.json` |
| `C:\GameSense\backups` | the dumps taken before a migration |
| `D:\GameSense-Backup` | the nightly backup (`BACKUP_DIR`) |
| `C:\GameSense\logs` | every log |
| `C:\GameSense\tools` | git, node, nssm, cloudflared |
| `C:\GameSense\venv` | Python environment |

## Backups, and proving they restore

`deploy/backup.ps1` runs at 03:00 (`GameSense-Backup`) and copies to `BACKUP_DIR` in
`backend\.env`, else `D:\GameSense-Backup` — a disk other than the one the database
and the photos are on, or it is no backup of them (audit H-10):

- `db\gamesense-<date>.dump`: `pg_dump -Fc`, read back with `pg_restore --list` to
  be sure it is a backup. The newest 14 are kept.
- `media\`: the photos, new and changed files only. A photo gone from the server
  stays in the backup. This matters most: once SPYPOINT drops its cloud copy (after
  about 30 days) the server holds the only one. Thumbnails are left out (they are
  made again).
- `config\backend.env`: without its `JWT_SECRET` / `CREDENTIALS_KEY` the camera
  passwords saved in a restored database can't be read. It holds secrets: keep the
  backup folder no more open than `C:\GameSense`.

It writes `C:\GameSense\data\backup-status.json`, and Settings → System shows it:
"Last backup 5 h ago", or in red when it failed, when the last good one is more than
36 hours old, or when there has never been one. It also says how many photos the
server and the backup hold; a backup with fewer counts as failed.

`deploy/restore-check.ps1` runs on Sundays at 04:30 (`GameSense-RestoreCheck`). It
restores the newest dump into a scratch database (`gamesense_restorecheck`) on the
same server, compares it with the live one table by table, looks for 50 of its photos
in the backup's photo folder (`python -m app.backup_check`), and drops the scratch
database. The live database is only read. Settings → System shows "Restore test:
passed 2 d ago", or why it failed.

Run either by hand:

```powershell
Invoke-Command -ComputerName Db01 { powershell -ExecutionPolicy Bypass -File C:\GameSense\app\deploy\backup.ps1 }
Invoke-Command -ComputerName Db01 { powershell -ExecutionPolicy Bypass -File C:\GameSense\app\deploy\restore-check.ps1 }
```

**A real restore** (the disk failed, or a migration went wrong):

1. Stop the jobs and the API: `Disable-ScheduledTask -TaskName 'GameSense-*'`,
   `Stop-Service GameSenseAPI`.
2. Photos: copy `D:\GameSense-Backup\media` to where `MEDIA_ROOT` says (or point
   `MEDIA_ROOT` at a new folder, below).
3. Settings: `backend\.env` from `D:\GameSense-Backup\config\backend.env` if the
   server's own is gone.
4. Database: with the service `GameSensePG` running,
   `dropdb -p 5433 -U gamesense gamesense`, `createdb -p 5433 -U gamesense gamesense`,
   `pg_restore -p 5433 -U gamesense -d gamesense --no-owner <the dump>` (a dump from
   `C:\GameSense\backups` for a migration that went wrong: the one named
   `...-before-<commit>`).
5. `alembic upgrade head` from `backend\`, `Start-Service GameSenseAPI`, check
   `http://db01:8090/api/ready`, then `Enable-ScheduledTask -TaskName 'GameSense-*'`.

## Photos on another disk

Photo paths are stored relative to `MEDIA_ROOT` (`<estate>/<camera>/2026-09-01/x.jpg`),
so moving the photos is a change to `MEDIA_ROOT` in `backend\.env` and a restart
(H-21). Photos stored before this with an absolute path (`C:\GameSense\data\media\...`)
are still found where they say and, once moved, under the new `MEDIA_ROOT` from the
estate's folder on, so nothing has to be rewritten in the database.

## Disk space

The photos, the database and the pre-migration dumps share `C:`. Settings → System
says "Space for photos: 12 GB free. Getting full" in amber under 20 GB, and in red
under 5 GB, where the photo fetch stops downloading (the photos wait on the cameras'
clouds and come in once there is room) so the database keeps room to work (H-18). A
deploy notes a warning under 10 GB free and doesn't start under 2 GB.

## Gotchas

- **PowerShell 5.1 turns native stderr into a terminating error.** git, npm, vite
  and alembic all write progress to stderr, so `$ErrorActionPreference='Stop'`
  plus `2>&1` kills the script on a *successful* command. Use `Continue` with
  explicit `$LASTEXITCODE` checks and send native output to files.
- **`.env` is not in git.** A fresh clone needs it copied in by hand, or the app
  will not start.
- Postgres listens on **5433**, not 5432 — Db01 also runs a production MS SQL
  Server that must not be disturbed.
- Node and git are local to `C:\GameSense\tools`, not on the system PATH; the
  update script adds them itself.
- **`.env` is read like pydantic reads it** (python-dotenv, H-15): quotes around a
  value and a trailing `# note` are not part of it, for the API, the pipeline,
  alembic and the importer alike. A value set in the service's own environment wins.
- The deploy scripts are for Windows PowerShell 5.1 (no `??`, `?.`, `&&`). CI parses
  them with PowerShell 7 (`backend/tests/test_safe_deploys.py`); a harness that runs
  `update.ps1` end to end against a fake server lives outside the repo.

## Manual control

```powershell
# force an update now instead of waiting for the timer
Invoke-Command -ComputerName Db01 { schtasks /Run /TN 'GameSense-Update' }

# watch what it did
Invoke-Command -ComputerName Db01 { Get-Content C:\GameSense\logs\update.log -Tail 20 }

# what it runs, and what the last update did (Settings -> App version shows the same)
Invoke-Command -ComputerName Db01 { Get-Content C:\GameSense\data\deploy-status.json }

# pause automatic deploys (e.g. while debugging on the server)
Invoke-Command -ComputerName Db01 { Disable-ScheduledTask -TaskName 'GameSense-Update' }

# try a commit that gave up again now (it otherwise waits 6 hours or a newer commit)
Invoke-Command -ComputerName Db01 { Remove-Item C:\GameSense\data\deploy-status.json; schtasks /Run /TN 'GameSense-Update' }
```

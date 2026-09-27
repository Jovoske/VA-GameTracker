# Deployment — how code reaches the server

GameSense runs natively (no Docker) on **Db01**, a Windows Server 2022 VM.
Deploying is just **`git push`**: the server pulls from `main` and applies the
change itself, within 10 minutes.

## The loop

```
laptop  --git push-->  github.com/Jovoske/VA-GameTracker  --git pull-->  Db01
```

`deploy/update.ps1` runs on Db01 every 10 minutes as the `GameSense-Update`
scheduled task (SYSTEM). Each run:

1. Stands down while a pipeline run holds its lock (`pipeline.py busy` exits 3),
   so an update never interrupts a photo import. It asks again just before
   restarting `GameSenseAPI` and waits up to 10 minutes for a job to finish.
2. Fetches `origin/main`. **Exits silently when there is nothing new** — the
   normal case.
3. `git reset --hard origin/main`. The server is deploy-only and never carries
   local edits.
4. `pip install` only if `backend/requirements.txt` changed.
5. `npm install` + `vite build` only if anything under `frontend/` changed, then
   mirrors `frontend/dist` to `C:\GameSense\web` (served by FastAPI).
6. **`pg_dump -Fc` to `C:\GameSense\backups`**, keeping the last 7. Connection
   details are parsed from the same `DATABASE_URL` the app uses, so the backup
   cannot dump a different database than the one about to change. **If the dump
   cannot be taken, the update refuses to migrate** and rolls the code back — a
   deploy that stops is visible and recoverable, a half-applied migration with no
   backup is neither.
7. `alembic upgrade head`. If migrations fail it **rolls the code back** and does
   not restart, rather than running new code against an old schema. The *schema*
   is restored by hand from the dump — deliberately manual, because an automatic
   restore destroys rows written since the backup.
8. Restarts `GameSenseAPI` and checks `/api/health`.

Progress goes to `C:\GameSense\logs\update.log`; per-step output to
`update-git.log`, `update-pip.log`, `update-npm.log`, `update-dump.log`,
`update-alembic.log`.

The script lives in the repo, so it updates itself on the next pull.

## Scheduled jobs

There is no Celery in the native build — every recurring job is a scheduled task
driving `backend/pipeline.py`.

| Task | When | Mode | Does |
|---|---|---|---|
| `GameSense-Update` | every 10 min | — | `deploy/update.ps1`, the loop above |
| `GameSense-Sync` | every 15 min | `sync` | SPYPOINT and UBox Pro pull + local AI (up to 300 photos, newest first) + exposure recompute |
| `GameSense-Sex` | hourly | `sex` | cloud vision stag/hind pass (costs API credit) |
| `GameSense-Plan` | 17:00 daily | `plan` | record tonight's claims **before** the night |
| `GameSense-Score` | 11:00 daily | `score` | grade the claims of every finished night not graded yet (last 14 days) |
| `GameSense-Notify` | every 15 min | `notify` | alerts that waited for a sit or quiet hours, as one message; tonight's plan push about 2 h before sunset |

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

Register them (idempotent: `plan`, `score` and `notify`; also preflights the backup path):

```powershell
Invoke-Command -ComputerName Db01 {
    powershell -ExecutionPolicy Bypass -File C:\GameSense\app\deploy\register-tasks.ps1
}
```

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
| `C:\GameSense\web` | built SPA, served by FastAPI |
| `C:\GameSense\data\media` | permanent photo archive |
| `C:\GameSense\tools` | git, node, nssm, cloudflared, backup script |
| `C:\GameSense\venv` | Python environment |

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

## Manual control

```powershell
# force an update now instead of waiting for the timer
Invoke-Command -ComputerName Db01 { schtasks /Run /TN 'GameSense-Update' }

# watch what it did
Invoke-Command -ComputerName Db01 { Get-Content C:\GameSense\logs\update.log -Tail 20 }

# pause automatic deploys (e.g. while debugging on the server)
Invoke-Command -ComputerName Db01 { Disable-ScheduledTask -TaskName 'GameSense-Update' }
```

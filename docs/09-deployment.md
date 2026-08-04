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

1. Stands down if the sync/AI pipeline holds `C:\GameSense\data\pipeline.lock`,
   so an update never interrupts a photo import.
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
| `GameSense-Sync` | every 15 min | `sync` | SPYPOINT pull + local AI + exposure recompute |
| `GameSense-Sex` | hourly | `sex` | cloud vision stag/hind pass (costs API credit) |
| `GameSense-Plan` | 17:00 daily | `plan` | record tonight's claims **before** the night |
| `GameSense-Score` | 11:00 daily | `score` | grade last night's claims against the cameras |

`plan` and `score` are what make the forecast falsifiable. Without them nothing
is ever recorded or graded, the Tonight card keeps saying *"0 scored nights"*
forever, and the app is back to making claims nobody checks. Order matters:
`plan` must run before dark or it is not a forecast, and `score` must run after
the night's photos have synced and been classified.

Register the two new ones (idempotent, also preflights the backup path):

```powershell
Invoke-Command -ComputerName Db01 {
    powershell -ExecutionPolicy Bypass -File C:\GameSense\app\deploy\register-tasks.ps1
}
```

A lock file serialises every `pipeline.py` mode, so these can never run on top of
a sync that is holding the database and the CPU models.

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

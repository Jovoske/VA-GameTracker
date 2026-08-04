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
6. `alembic upgrade head`. If migrations fail it **rolls the code back** and does
   not restart, rather than running new code against an old schema.
7. Restarts `GameSenseAPI` and checks `/api/health`.

Progress goes to `C:\GameSense\logs\update.log`; per-step output to
`update-git.log`, `update-pip.log`, `update-npm.log`, `update-alembic.log`.

The script lives in the repo, so it updates itself on the next pull.

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

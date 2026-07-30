# 09 — Deployment handoff (Db01)

> Provided by the operator. Describes the **live production system**, which is
> ahead of this repository — see "Divergence" at the end before acting on it.

## What it is

A local-first wildlife intelligence & hunting decision platform for a private
estate (Piedras Lisas, Alatoz, Spain). Ingests SPYPOINT trail-camera photos,
identifies animals with AI, correlates activity against weather/moon, and produces
a nightly recommendation per camera. Production is **v0.20.1**.

## Where it runs

Natively on **Db01**, a Windows Server 2022 VM on the LAN — **no Docker** (VMware
guest with nested virtualisation disabled, so WSL2/Docker cannot run). Everything
under `C:\GameSense\`: `app\backend`, `web` (built frontend), `data\media`,
`data\models`, `pgdata`, `logs`, `tools`, `venv`.

Four auto-start Windows services:

| Service | Role |
|---|---|
| `GameSensePG` | PostgreSQL 16 on **port 5433** — deliberately not 5432, because Db01 also runs a production MS SQL Server that must not be disturbed |
| `GameSenseAPI` | FastAPI/uvicorn on `0.0.0.0:8090` via NSSM, entrypoint `serve.py`; also serves the built React SPA as static files |
| `Cloudflared` | Cloudflare Tunnel for public HTTPS |
| Task Scheduler | As SYSTEM, **no Celery/Redis**: sync every 15 min, cloud vision pass hourly, backup daily 03:00 → `D:\GameSense-Backup` |

All scheduled work is serialised by `C:\GameSense\data\pipeline.lock`.

**URLs:** `https://gamesense.daa-ops.com` (public), `http://db01:8090` (LAN).
Login `admin@gamesense.local`. The apex `daa-ops.com` is a separate dashboard
behind Cloudflare Access — untouched, shares only the domain.

## Where data comes from

- **SPYPOINT REST API** (`restapi.spypoint.com/api/v3`) — cameras + photos.
  Photos are downloaded and kept **permanently**: SPYPOINT purges its cloud copy
  after ~30 days, and the legacy app stored only expiring URLs and lost
  everything. Free plan is **100 photos/month/camera**, which throttles volume.
  Multiple SPYPOINT accounts supported (guests connect their own; passwords
  Fernet-encrypted in `camera_accounts`).
- **Open-Meteo** archive + forecast (free) for per-night weather backfill;
  `astral` for moon/solar.
- **Anthropic API** — the only paid component (Claude Opus 5 vision, stag/hind and
  boar/sow only).

## AI pipeline

MegaDetector v6 (local, finds animals / filters empty frames) → DeepFaune v1.3
DINOv2 ViT-L (local, species) → Claude Opus 5 (cloud, sex/class). The first two
are free and run on CPU.

## Deploying

Development happens on the operator's Windows 11 laptop at
`C:\Users\julle\Documents\Claude\VA Gametracker` (git, branch `main`). Deploy by
robocopy over the admin share:

- Backend → `\\Db01\c$\GameSense\app\backend`, then `Restart-Service GameSenseAPI`
- Frontend → build on the laptop (`vite build`; **Node is not installed on Db01**),
  copy `frontend\dist` → `\\Db01\c$\GameSense\web`
- Migrations → `alembic upgrade head` on Db01 (**currently at 0007**)
- Remote admin via `Invoke-Command -ComputerName Db01 { ... }` (WinRM)

## Stack

FastAPI · SQLAlchemy 2.0 · Alembic · **vanilla PostgreSQL 16** (PostGIS and
pgvector deliberately dropped — lat/lon are plain Floats, embeddings are JSONB) ·
React 18 + TypeScript + Vite · MapLibre GL.

## Gotchas

- `Expand-Archive` is broken on Db01 → use .NET `ZipFile`. The Windows side is
  PowerShell 5.1: no `??`, no `%-d` date formats.
- **Any scheduled AI pass must record that it ran, not just its successes.** A bug
  where inconclusive vision results were not stored caused **6,502 redundant paid
  API calls in 5 days** (fixed in 0.20.1 via `detections.sex_attempts`).
- **The forecast must not exclude cameras that are offline or out of credits.** An
  earlier attempt did, hid the estate's best camera, and made every night read
  SKIP. Offline cameras stay ranked on historical presence; only the *recency*
  penalty is skipped. Presence rate divides by each camera's **own active nights**,
  not the estate-wide date range.

---

## Divergence from this repository (verified 2026-07-30)

Production is **not** built from any branch on GitHub. Recorded here so the next
person does not assume otherwise.

| | GitHub | Production |
|---|---|---|
| Version | `main` and the redesign branch are **v0.17.0** | **v0.20.1** |
| Multi-account table | `spypoint_accounts` (redesign branch) | `camera_accounts` |
| `detections.sex_attempts` | absent | present |
| Photo-credit alerts | absent from every branch | present |
| Alembic head | `0007_sits` (redesign branch) | `0007` — **different migration** |

Three GitHub branches exist and none matches production: `main` (`ce6384e`),
`claude/app-hosting-status-07kqr0` (stale — still targets PostGIS + pgvector,
contradicting the vanilla-PostgreSQL decision above), and
`claude/hunting-companion-redesign-6w8z1h`.

**Consequences before any merge:**

1. **Revision-ID collision.** Both the redesign branch and production define
   revisions `0004`–`0007` with different content. Running `alembic upgrade head`
   after a naive merge will either fail on duplicate IDs or produce divergent
   heads.
2. **Duplicate feature, two schemas.** Multi-SPYPOINT accounts were built twice
   and independently — `spypoint_accounts` vs `camera_accounts`, both with
   Fernet-encrypted passwords. Only one can survive.
3. **The same bug was fixed twice.** The presence-rate denominator (per-camera
   active nights rather than the estate-wide range) exists in both.
4. **Unversioned production code.** The photo-credit work exists only on Db01 or
   the operator's laptop. A `git pull`-style deploy would destroy it. Commit it
   before merging anything.

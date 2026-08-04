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
- Migrations → `alembic upgrade head` on Db01 (**0009_sits** after this branch)
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

## Divergence from this repository — resolved 2026-08-04

Production ran ahead of every GitHub branch for a while. The gap has now been
closed on `claude/redesign-on-v0.21`, which is based on `main` at **v0.21.0** —
the release that carries the production work (`camera_accounts`,
`detections.sex_attempts`, photo-credit alerts). Recorded here because the
resolution constrains what future work may do.

### What was divergent, and how it was settled

| | Was | Now |
|---|---|---|
| Version | GitHub v0.17.0 vs production v0.20.1 | both on v0.21.0 |
| Multi-account table | `spypoint_accounts` (redesign) vs `camera_accounts` (prod) | **`camera_accounts` kept**; the redesign's duplicate was dropped |
| `detections.sex_attempts` | redesign branch only had it absent | kept from production |
| Photo-credit alerts | production only | kept, and now also feed camera exposure |
| Alembic head | two conflicting `0004`–`0007` chains | production's chain kept; redesign work renumbered to `0008_camera_nights`, `0009_sits` |

The redesign's `spypoint_accounts` table and its migrations were discarded
rather than merged: production's `camera_accounts` already had Fernet-encrypted
passwords and live rows behind it, and only one of the two could survive.

### Rules this leaves behind

1. **`JWT_SECRET` must never be rotated casually.** It signs sessions *and*
   derives the Fernet key for `camera_accounts.password_enc`. Changing it logs
   every user out **and** makes every stored SPYPOINT password undecryptable.
2. **`0001` runs `create_all()` against the current ORM**, so every later
   revision must be idempotent — `IF NOT EXISTS`, or an explicit no-op — or
   fresh installs break. `backend/tests/test_migrations.py` enforces this, and
   also asserts that a session issued *before* an upgrade still validates after
   it.
3. **Migrations are additive only** against the live database. Nothing in the
   `0008`/`0009` chain drops or rewrites a column.
4. `claude/app-hosting-status-07kqr0` is stale — it still targets PostGIS +
   pgvector, contradicting the vanilla-PostgreSQL decision above. Do not merge it.

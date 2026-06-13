# Deliverable 10 — Git-Based Self-Update Strategy

Goal: a deployed installation can update itself from Git, safely, from an **admin-only** panel — check version, pull, migrate, restart, health-check, and roll back on failure.

## Admin endpoints (guarded, `role = admin`)

| Endpoint | Does |
|---|---|
| `GET /api/admin/version` | Current tag/SHA + build date + dirty-tree flag. |
| `GET /api/admin/version/check` | `git fetch` + compare local vs `origin/main` (and latest tag); returns "up to date" or "N commits behind, vX.Y.Z available" + changelog. |
| `POST /api/admin/update` | Run the update sequence (below) in a background task; stream status. |
| `POST /api/admin/rollback` | Check out the previous tag and restart; restore DB from the pre-update backup if needed. |
| `GET /api/admin/update/status` | Progress/log of an in-flight update, for the maintenance banner. |

## Update sequence (transactional, fail-safe)

1. **Preflight:** ensure clean working tree, on a known tag/branch, disk space OK; refuse otherwise.
2. **Backup:** `pg_dump` the database; record current tag for rollback.
3. **Maintenance mode:** set a flag → UI shows a maintenance banner; the API returns 503 for mutating calls.
4. **Pull:** `git fetch` + fast-forward to the target tag (no merge surprises; tags only).
5. **Dependencies:** rebuild images (`docker compose build`) or `pip/npm install` (native).
6. **Migrate:** `alembic upgrade head`.
7. **Restart:** recreate services (`docker compose up -d`) or restart native processes.
8. **Health-check:** poll `/api/ready` until green within a timeout.
9. **Commit or auto-rollback:** green → clear maintenance mode, record new version. Failed → **auto-rollback** to the previous tag + restore DB, then report the failure with logs.

## Safety properties

- **Tags are the unit of release** (`v0.1.0`, `v0.2.0`, …) so both update targets and rollback points are explicit and clean — every milestone is tagged.
- **Fast-forward only**; never an interactive merge on a server.
- **DB backup before every migrate**; migrations are reversible where practical.
- **Admin-gated + audit-logged**; the endpoint shells out through a single narrow, allow-listed helper (no arbitrary command passthrough), rate-limited.
- **Idempotent & observable:** re-running a half-applied update converges; all steps logged and surfaced in the panel.

## Implementation notes

- Lives in `backend/api/admin.py` + a small `core/updater.py` that wraps the git/compose/alembic calls behind typed functions with timeouts.
- Works in both deploy modes: Docker (recreate services) and native (restart supervised processes). The mode is a config value.
- The frontend **Settings → Admin** screen renders current vs latest version, a one-click "Update now" with live progress, and a guarded "Roll back" — matching the spec's admin panel.

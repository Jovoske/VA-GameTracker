# GameSense self-update: pull from GitHub and apply, on the server.
#
# Canonical copy lives in the repo, so `git pull` updates this script too.
# Run by the GameSense-Update scheduled task (SYSTEM). Safe to run any time:
# it does nothing when the remote has no new commits, and it stands down while
# the sync/AI pipeline holds its lock so an update never interrupts an import.
#
#   Deploy flow:  laptop -> git push -> (<=10 min) -> Db01 pulls, builds, restarts.
#
# NOTE ON ERROR HANDLING: git, npm, vite and alembic all write ordinary progress to
# stderr. Under PowerShell 5.1 that becomes a NativeCommandError, so with
# $ErrorActionPreference='Stop' the script dies on a *successful* command. Hence
# 'Continue' plus explicit $LASTEXITCODE checks, and native output sent to files
# rather than piped through 2>&1.

$ErrorActionPreference = 'Continue'
$repo  = 'C:\GameSense\app'
$git   = 'C:\GameSense\tools\git\cmd\git.exe'
$npm   = 'C:\GameSense\tools\node\npm.cmd'
$venv  = 'C:\GameSense\venv\Scripts'
$web   = 'C:\GameSense\web'
$logs  = 'C:\GameSense\logs'
$log   = "$logs\update.log"
$lock  = 'C:\GameSense\data\pipeline.lock'
$env:PATH = "C:\GameSense\tools\node;C:\GameSense\tools\git\cmd;$env:PATH"

function Note($msg) {
    Add-Content -Path $log -Value ("{0}  {1}" -f (Get-Date -Format 's'), $msg)
}

# A sync/AI run in progress is holding the database and the models; let it finish.
if ((Test-Path $lock) -and ((Get-Date) - (Get-Item $lock).LastWriteTime).TotalHours -lt 3) {
    Note 'skip: pipeline busy'
    exit 0
}

Set-Location $repo
$before = (& $git rev-parse HEAD).Trim()
& $git fetch --quiet origin main *> "$logs\update-git.log"
$after = (& $git rev-parse origin/main).Trim()

if ($before -eq $after) { exit 0 }   # already current - the common case, stay quiet

Note "update: $($before.Substring(0,7)) -> $($after.Substring(0,7))"
& $git reset --hard origin/main --quiet *>> "$logs\update-git.log"   # deploy-only; no local edits
if ($LASTEXITCODE -ne 0) { Note 'ERROR: git reset failed - aborting'; exit 1 }
$changed = (& $git diff --name-only $before $after) -join "`n"

# Python deps only when the manifest moved.
if ($changed -match '(?m)^backend/requirements\.txt$') {
    Note 'pip install'
    & "$venv\python.exe" -m pip install -q -r "$repo\backend\requirements.txt" *> "$logs\update-pip.log"
    if ($LASTEXITCODE -ne 0) { Note 'ERROR: pip install failed - see update-pip.log' }
}

# Rebuild the SPA only when the frontend moved (npm + vite is the slow part).
if ($changed -match '(?m)^frontend/') {
    Note 'npm build'
    Push-Location "$repo\frontend"
    & $npm install --no-audit --no-fund --silent *> "$logs\update-npm.log"
    & "$repo\frontend\node_modules\.bin\vite.cmd" build *>> "$logs\update-npm.log"
    $built = $LASTEXITCODE
    Pop-Location
    if ($built -eq 0 -and (Test-Path "$repo\frontend\dist\index.html")) {
        robocopy "$repo\frontend\dist" $web /MIR /NFL /NDL /NP /NJH *> $null
        Note 'frontend deployed'
    } else {
        Note 'ERROR: vite build failed - keeping previous frontend (see update-npm.log)'
    }
}

# Back up before touching the schema. Rolling the code back cannot roll a migration
# back, so without this a half-applied migration leaves the estate's only copy of a
# season of sightings in whatever state alembic stopped in. Keep the last 7.
$dumps = 'C:\GameSense\backups'
New-Item -ItemType Directory -Force -Path $dumps *> $null
$dump = Join-Path $dumps ("gamesense-{0}.dump" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))

# Connection details come from the same DATABASE_URL the app uses, so the backup can
# never quietly dump a different database than the one about to be migrated.
$dbUrl = (Select-String -Path "$repo\backend\.env" -Pattern '^DATABASE_URL=' -EA SilentlyContinue |
          Select-Object -First 1).Line -replace '^DATABASE_URL=', ''
$m = [regex]::Match($dbUrl, '://(?<u>[^:]+):(?<p>[^@]+)@(?<h>[^:/]+):(?<port>\d+)/(?<db>[^?]+)')
# Find pg_dump rather than assume a path: the installed major version moves, and a
# wrong guess here would mean discovering there is no backup at the worst moment.
# PGDUMP in .env overrides everything, for an install that is somewhere unusual.
$pgDump = $null
$override = (Select-String -Path "$repo\backend\.env" -Pattern '^PGDUMP=' -EA SilentlyContinue |
             Select-Object -First 1).Line -replace '^PGDUMP=', ''
foreach ($cand in @(
    $override,
    (Get-Command pg_dump.exe -EA SilentlyContinue).Source,
    'C:\GameSense\pg\pgsql\bin\pg_dump.exe',      # where the EDB zip actually unpacks on Db01
    'C:\GameSense\tools\pgsql\bin\pg_dump.exe'
)) {
    if ($cand -and (Test-Path $cand)) { $pgDump = $cand; break }
}
if (-not $pgDump) {
    # Newest major version wins, so an upgraded server keeps working untouched.
    $pgDump = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\pg_dump.exe' -EA SilentlyContinue |
              Sort-Object { [int]($_.Directory.Parent.Name) } -Descending |
              Select-Object -First 1 -ExpandProperty FullName
}

if (-not $m.Success -or -not $pgDump) {
    # Refuse rather than migrate blind. A deploy that stops here is visible and
    # recoverable; a half-applied migration with no backup is neither.
    Note "ERROR: cannot back up (DATABASE_URL parsed=$($m.Success), pg_dump found=$([bool]$pgDump)) - not migrating, rolling code back"
    & $git reset --hard $before --quiet *>> "$logs\update-git.log"
    exit 1
}

$env:PGPASSWORD = [uri]::UnescapeDataString($m.Groups['p'].Value)
& $pgDump -h $m.Groups['h'].Value -p $m.Groups['port'].Value -U $m.Groups['u'].Value `
          -d $m.Groups['db'].Value -Fc -f $dump *> "$logs\update-dump.log"
$dumped = $LASTEXITCODE
$env:PGPASSWORD = ''
if ($dumped -ne 0 -or -not (Test-Path $dump)) {
    Note 'ERROR: pg_dump failed - not migrating, rolling code back (see update-dump.log)'
    & $git reset --hard $before --quiet *>> "$logs\update-git.log"
    exit 1
}
Note ("backup: {0} ({1:N1} MB)" -f (Split-Path $dump -Leaf), ((Get-Item $dump).Length / 1MB))
Get-ChildItem $dumps -Filter 'gamesense-*.dump' |
    Sort-Object LastWriteTime -Descending | Select-Object -Skip 7 | Remove-Item -Force

# Migrations are idempotent; run every update so the schema can never lag the code.
# If they fail, roll the code back rather than restart into a schema mismatch. The
# schema itself must be restored by hand from the dump above - deliberately manual,
# because an automatic restore can destroy rows written since the backup.
$env:PYTHONPATH = "$repo\backend"
Push-Location "$repo\backend"
& "$venv\alembic.exe" upgrade head *> "$logs\update-alembic.log"
$migrated = $LASTEXITCODE
Pop-Location
if ($migrated -ne 0) {
    Note 'ERROR: migration failed - rolling code back, not restarting'
    & $git reset --hard $before --quiet *>> "$logs\update-git.log"
    exit 1
}
Select-String -Path "$logs\update-alembic.log" -Pattern 'Running upgrade' -EA SilentlyContinue |
    ForEach-Object { Note ($_.Line.Trim()) }

Restart-Service GameSenseAPI
Start-Sleep -Seconds 8
try {
    Invoke-WebRequest 'http://localhost:8090/api/health' -UseBasicParsing -TimeoutSec 15 | Out-Null
    Note 'done: API healthy'
} catch {
    Note "ERROR: API unhealthy after update - $($_.Exception.Message)"
}

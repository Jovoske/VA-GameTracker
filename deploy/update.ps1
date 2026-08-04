# GameSense self-update: pull from GitHub and apply, on the server.
#
# Canonical copy lives in the repo, so `git pull` updates this script too.
# Run by the GameSense-Update scheduled task (SYSTEM). Safe to run any time:
# it does nothing when the remote has no new commits, and it stands down while
# the sync/AI pipeline holds its lock so an update never interrupts an import.
#
#   Deploy flow:  laptop -> git push -> (<=10 min) -> Db01 pulls, builds, restarts.

$ErrorActionPreference = 'Stop'
$repo  = 'C:\GameSense\app'
$git   = 'C:\GameSense\tools\git\cmd\git.exe'
$npm   = 'C:\GameSense\tools\node\npm.cmd'
$venv  = 'C:\GameSense\venv\Scripts'
$web   = 'C:\GameSense\web'
$log   = 'C:\GameSense\logs\update.log'
$lock  = 'C:\GameSense\data\pipeline.lock'
$env:PATH = "C:\GameSense\tools\node;C:\GameSense\tools\git\cmd;$env:PATH"

function Note($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format 's'), $msg
    Add-Content -Path $log -Value $line
    Write-Output $line
}

# A sync/AI run in progress is holding the DB and the models; let it finish.
if ((Test-Path $lock) -and ((Get-Date) - (Get-Item $lock).LastWriteTime).TotalHours -lt 3) {
    Note 'skip: pipeline busy'
    exit 0
}

Set-Location $repo
$before = (& $git rev-parse HEAD).Trim()
& $git fetch --quiet origin main
$after = (& $git rev-parse origin/main).Trim()

if ($before -eq $after) { exit 0 }   # already current — the common case, stay quiet

Note "update: $($before.Substring(0,7)) -> $($after.Substring(0,7))"
& $git reset --hard origin/main --quiet      # server is deploy-only; never has local edits
$changed = & $git diff --name-only $before $after

# Python deps only when the manifest moved.
if ($changed -match '^backend/requirements\.txt$') {
    Note 'pip install'
    & "$venv\python.exe" -m pip install -q -r "$repo\backend\requirements.txt"
}

# Rebuild the SPA only when the frontend moved (npm + vite is the slow part).
if ($changed -match '^frontend/') {
    Note 'npm build'
    Push-Location "$repo\frontend"
    if (-not (Test-Path 'node_modules')) { & $npm install --no-audit --no-fund --silent }
    else { & $npm install --no-audit --no-fund --silent }
    & "$repo\frontend\node_modules\.bin\vite.cmd" build
    Pop-Location
    if (Test-Path "$repo\frontend\dist\index.html") {
        robocopy "$repo\frontend\dist" $web /MIR /NFL /NDL /NP /NJH | Out-Null
        Note 'frontend deployed'
    } else {
        Note 'ERROR: vite build produced no dist - keeping previous frontend'
    }
}

# Migrations are idempotent; run every update so the schema can never lag the code.
$env:PYTHONPATH = "$repo\backend"
Push-Location "$repo\backend"
& "$venv\alembic.exe" upgrade head 2>&1 | Where-Object { $_ -match 'Running upgrade' } | ForEach-Object { Note $_ }
Pop-Location

Restart-Service GameSenseAPI
Start-Sleep -Seconds 8
try {
    $h = (Invoke-WebRequest 'http://localhost:8090/api/health' -UseBasicParsing -TimeoutSec 15).StatusCode
    Note "done: API healthy ($h)"
} catch {
    Note "ERROR: API unhealthy after update - $($_.Exception.Message)"
}

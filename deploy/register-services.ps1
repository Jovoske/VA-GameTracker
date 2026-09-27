# Check, and on a rebuilt server create, the two GameSense Windows services (audit H-10).
#
#   GameSensePG    PostgreSQL 16 on port 5433 (Db01 also runs an MS SQL Server that
#                  must not be disturbed, so never 5432), data in C:\GameSense\pgdata
#   GameSenseAPI   backend\serve.py under NSSM: the API on port 8090, which also serves
#                  the app's screens from C:\GameSense\web (FRONTEND_DIST)
#
# By default it only looks and says what it finds. With -Apply it creates a service
# that is missing and starts it; a service that exists is never changed, because a
# running server's settings are not for a script to guess at.
#
#     powershell -ExecutionPolicy Bypass -File C:\GameSense\app\deploy\register-services.ps1
#     powershell -ExecutionPolicy Bypass -File C:\GameSense\app\deploy\register-services.ps1 -Apply
#
# The scheduled tasks are deploy\register-tasks.ps1; the Suntek services are
# install-ftp.ps1 and install-mail.ps1; the tunnel is Cloudflare's own installer.

param(
    [string]$Root = 'C:\GameSense',
    [switch]$Apply
)

$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\lib.ps1"

$python  = "$Root\venv\Scripts\python.exe"
$backend = "$Root\app\backend"
$envFile = "$backend\.env"
$logs    = "$Root\logs"
$pgdata  = "$Root\pgdata"

function Say($msg) { Write-Host $msg }

# ---- GameSensePG ----------------------------------------------------------------------------
$pg = Get-Service GameSensePG -EA SilentlyContinue
if ($pg) {
    Say "GameSensePG   present, $($pg.Status), starts $($pg.StartType)"
} else {
    $pgCtl = Find-PgTool 'pg_ctl' $envFile $Root
    if (-not $pgCtl) { Say 'GameSensePG   MISSING, and pg_ctl.exe was not found' }
    elseif (-not (Test-Path "$pgdata\PG_VERSION")) { Say "GameSensePG   MISSING, and there is no database in $pgdata (restore one first: docs/09-deployment.md)" }
    elseif ($Apply) {
        & $pgCtl register -N GameSensePG -D $pgdata -S auto -o '-p 5433'
        Start-Service GameSensePG
        Say 'GameSensePG   created and started (port 5433)'
    } else { Say "GameSensePG   MISSING - -Apply registers it: $pgCtl register -N GameSensePG -D $pgdata -S auto -o `"-p 5433`"" }
}

# ---- GameSenseAPI ---------------------------------------------------------------------------
$api = Get-Service GameSenseAPI -EA SilentlyContinue
$nssm = (Get-Command nssm.exe -EA SilentlyContinue).Source
if (-not $nssm) {
    $nssm = Get-ChildItem "$Root\tools" -Recurse -Filter nssm.exe -EA SilentlyContinue |
            Sort-Object { $_.FullName -notmatch 'win64' } | Select-Object -First 1 -ExpandProperty FullName
}
if (-not (Read-EnvValue $envFile 'FRONTEND_DIST')) {
    Say "note: FRONTEND_DIST is not in backend\.env - the API serves no screens unless the service sets it ($Root\web)"
}
if ($api) {
    Say "GameSenseAPI  present, $($api.Status), starts $($api.StartType)"
    if ($nssm) { Say ("              runs: {0} {1} (in {2})" -f (& $nssm get GameSenseAPI Application), (& $nssm get GameSenseAPI AppParameters), (& $nssm get GameSenseAPI AppDirectory)) }
} elseif (-not $nssm) {
    Say "GameSenseAPI  MISSING, and nssm.exe was not found (on PATH or under $Root\tools)"
} elseif ($Apply) {
    New-Item -ItemType Directory -Force -Path $logs | Out-Null
    & $nssm install GameSenseAPI $python serve.py
    & $nssm set GameSenseAPI AppDirectory $backend
    & $nssm set GameSenseAPI AppEnvironmentExtra "FRONTEND_DIST=$Root\web"
    & $nssm set GameSenseAPI AppStdout "$logs\api.log"
    & $nssm set GameSenseAPI AppStderr "$logs\api.log"
    & $nssm set GameSenseAPI AppRotateFiles 1
    & $nssm set GameSenseAPI AppRotateBytes 5242880
    & $nssm set GameSenseAPI Start SERVICE_AUTO_START
    & $nssm set GameSenseAPI DependOnService GameSensePG
    Start-Service GameSenseAPI
    Say 'GameSenseAPI  created and started (backend\serve.py, logs in logs\api.log)'
} else {
    Say "GameSenseAPI  MISSING - -Apply installs it with $nssm"
}

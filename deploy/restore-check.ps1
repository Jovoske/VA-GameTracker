# GameSense restore rehearsal: prove the newest backup can be put back (weekly).
#
# Run by the GameSense-RestoreCheck scheduled task (SYSTEM), Sundays at 04:30
# (register-tasks.ps1), after the night's backup. It restores the newest dump from the
# backup folder into a scratch database, gamesense_restorecheck, on the same server;
# compares it with the live database; looks for a sample of its photos in the
# backup's photo folder (python -m app.backup_check); and drops the scratch database
# again. The live database is only read. Settings -> System shows the result, in red
# when it failed.
#
# Run it by hand:  powershell -ExecutionPolicy Bypass -File C:\GameSense\app\deploy\restore-check.ps1
# A real restore (after a disk failure) is in docs/09-deployment.md.

param(
    [string]$Root = 'C:\GameSense',
    [string]$Target = ''
)

$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\lib.ps1"

$app     = "$Root\app"
$envFile = "$app\backend\.env"
$python  = "$Root\venv\Scripts\python.exe"
$logs    = "$Root\logs"
$log     = "$logs\restore-check.log"
$scratch = 'gamesense_restorecheck'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
Limit-Log $log

function Note($msg) {
    Add-Content -Path $log -Value ("{0}  {1}" -f (Get-Date -Format 's'), $msg)
}

if (-not $Target) { $Target = Read-EnvValue $envFile 'BACKUP_DIR' }
if (-not $Target) { $Target = 'D:\GameSense-Backup' }

$db = Get-DbTarget $envFile
$psql = Find-PgTool 'psql' $envFile $Root
$pgRestore = Find-PgTool 'pg_restore' $envFile $Root
$dump = Get-ChildItem "$Target\db" -Filter 'gamesense-*.dump' -EA SilentlyContinue |
        Sort-Object Name -Descending | Select-Object -First 1 -ExpandProperty FullName

function Check([string[]]$Extra) {
    Push-Location "$app\backend"
    $dumpArgs = @()
    if ($dump) { $dumpArgs = @('--dump', $dump) }
    & $python -m app.backup_check --restored-db $scratch --media "$Target\media" @dumpArgs @Extra *> "$logs\restore-check-result.log"
    $code = $LASTEXITCODE
    Pop-Location
    Get-Content "$logs\restore-check-result.log" -EA SilentlyContinue | Select-Object -Last 1 | ForEach-Object { Note $_ }
    return $code
}

function Drop-Scratch {
    & $psql -h $db.Host -p $db.Port -U $db.User -d postgres -c "DROP DATABASE IF EXISTS $scratch" *>> "$logs\restore-check-psql.log"
}

if (-not $db -or -not $psql -or -not $pgRestore) {
    Check @('--error', 'psql or pg_restore not found, or DATABASE_URL unreadable, so no restore was tried.') | Out-Null
    exit 1
}
if (-not $dump) {
    Check @('--error', "There is no dump in $Target\db to restore.") | Out-Null
    exit 1
}

Note "restoring $(Split-Path $dump -Leaf) into $scratch"
$env:PGPASSWORD = $db.Password
Drop-Scratch
& $psql -h $db.Host -p $db.Port -U $db.User -d postgres -c "CREATE DATABASE $scratch" *> "$logs\restore-check-psql.log"
if ($LASTEXITCODE -ne 0) {
    $env:PGPASSWORD = ''
    Check @('--error', "The scratch database couldn't be made (see restore-check-psql.log).") | Out-Null
    exit 1
}
& $pgRestore -h $db.Host -p $db.Port -U $db.User -d $scratch --no-owner --no-privileges $dump *> "$logs\restore-check-restore.log"
$restored = $LASTEXITCODE
if ($restored -ne 0) {
    Drop-Scratch
    $env:PGPASSWORD = ''
    Check @('--error', 'pg_restore reported errors (see restore-check-restore.log).') | Out-Null
    exit 1
}
$code = Check @()
Drop-Scratch
$env:PGPASSWORD = ''
exit $code

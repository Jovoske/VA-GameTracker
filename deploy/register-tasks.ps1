# Register every GameSense scheduled task on Db01. Idempotent - safe to re-run: a task
# that exists is brought back to what is written here, one that doesn't is made.
#
# The native build has no Celery: every recurring job is a Windows scheduled task, and
# until now half of them lived only on the server (audit H-10). All of them:
#
#   GameSense-Update        every 10 min   deploy\update.ps1: the newest tested commit
#                                          goes live (any hour; docs/09-deployment.md)
#   GameSense-Sync          every 15 min   pipeline.py sync: SPYPOINT + UBox + the AI pass
#   GameSense-Notify        every 15 min   pipeline.py notify: alerts that waited, and
#                                          tonight's plan about two hours before sunset
#   GameSense-Sex           hourly         pipeline.py sex: stag/hind, boar/sow (paid)
#   GameSense-Plan          17:00 daily    pipeline.py plan: tonight's claims BEFORE dark
#   GameSense-Score         11:00 daily    pipeline.py score: grade last night's claims
#   GameSense-Backup        03:00 daily    deploy\backup.ps1: database + photos to D:
#   GameSense-RestoreCheck  Sun 04:30      deploy\restore-check.ps1: restore the newest
#                                          dump into a scratch database, check it
#
# Task Scheduler throws a task's output away, so each one runs through cmd.exe with
# its errors appended to C:\GameSense\logs\tasks-stderr.log: a job that dies before it
# can write its own log (an import that fails) still leaves the reason somewhere.
# pipeline.py, update.ps1 and backup.ps1 keep their own logs in the same folder.
#
# Run once, elevated, on Db01 (and again after changing this file):
#     powershell -ExecutionPolicy Bypass -File C:\GameSense\app\deploy\register-tasks.ps1

param([string]$Root = 'C:\GameSense')

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\lib.ps1"

$python  = "$Root\venv\Scripts\python.exe"
$work    = "$Root\app\backend"
$deploy  = "$Root\app\deploy"
$logs    = "$Root\logs"
$errors  = "$logs\tasks-stderr.log"
$envFile = "$work\.env"

if (-not (Test-Path $python)) { throw "python not found at $python" }
if (-not (Test-Path "$work\pipeline.py")) { throw "pipeline.py not found in $work" }
New-Item -ItemType Directory -Force -Path $logs | Out-Null

# What a task runs: the command line, through cmd.exe so its errors are kept.
function Pipeline-Action([string]$Mode) {
    New-ScheduledTaskAction -Execute 'cmd.exe' -WorkingDirectory $work `
        -Argument "/c `"`"$python`" pipeline.py $Mode 1>NUL 2>>`"$errors`"`""
}
function Script-Action([string]$Script) {
    New-ScheduledTaskAction -Execute 'cmd.exe' -WorkingDirectory $work `
        -Argument "/c `"powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$deploy\$Script`" 1>NUL 2>>`"$errors`"`""
}

# From midnight today, every $Minutes minutes, for good: with no -RepetitionDuration
# the repetition never ends (a [TimeSpan]::MaxValue duration is refused on Windows
# Server 2016 and later).
function Every([int]$Minutes) {
    New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes $Minutes)
}

function Register-GameSense($Name, $Action, $Trigger, [int]$LimitMinutes, $Description) {
    # SYSTEM: the service account owns the data directory.
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    # A missed run is made up as soon as the machine is back (a night never claimed can
    # never be scored); a run still going when the next is due is left to finish.
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
        -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes $LimitMinutes)
    if (Get-ScheduledTask -TaskName $Name -EA SilentlyContinue) {
        Set-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger `
            -Principal $principal -Settings $settings | Out-Null
        Write-Host "updated  $Name"
    } else {
        Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger `
            -Principal $principal -Settings $settings -Description $Description | Out-Null
        Write-Host "created  $Name"
    }
}

# The deploy holds every job's lock for a few minutes at most, and lets go after 90.
Register-GameSense 'GameSense-Update' (Script-Action 'update.ps1') (Every 10) 120 `
    'Put the newest tested commit live (deploy branch; main until CI has made it).'
Register-GameSense 'GameSense-Sync' (Pipeline-Action 'sync') (Every 15) 120 `
    'Fetch photos from SPYPOINT and UBox, look for animals, recount the nights.'
# notify takes seconds, so ten minutes is a hung one.
Register-GameSense 'GameSense-Notify' (Pipeline-Action 'notify') (Every 15) 10 `
    "Alerts that waited for a sit or quiet hours, and tonight's plan about two hours before sunset."
Register-GameSense 'GameSense-Sex' (Pipeline-Action 'sex') (Every 60) 60 `
    'Mark red deer stag or hind and wild boar male or female (cloud vision, costs credit).'
# plan and score wait up to 40 minutes for a running job, inside the hour.
Register-GameSense 'GameSense-Plan' (Pipeline-Action 'plan') (New-ScheduledTaskTrigger -Daily -At '17:00') 60 `
    "Record tonight's forecast before the night, so it can be scored tomorrow."
Register-GameSense 'GameSense-Score' (Pipeline-Action 'score') (New-ScheduledTaskTrigger -Daily -At '11:00') 60 `
    "Grade the forecast of every finished night against what the cameras recorded."
Register-GameSense 'GameSense-Backup' (Script-Action 'backup.ps1') (New-ScheduledTaskTrigger -Daily -At '03:00') 240 `
    'Copy the database and the photos to the backup disk (BACKUP_DIR, else D:\GameSense-Backup).'
Register-GameSense 'GameSense-RestoreCheck' (Script-Action 'restore-check.ps1') `
    (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '04:30') 120 `
    'Restore the newest backup into a scratch database and check it holds the season.'

Write-Host ''
Write-Host 'Checking the backup tools (update.ps1 refuses to migrate without pg_dump)...'
$db = Get-DbTarget $envFile
$pgDump = Find-PgTool 'pg_dump' $envFile $Root
foreach ($tool in @('pg_restore', 'psql')) {
    if (-not (Find-PgTool $tool $envFile $Root)) { Write-Warning "$tool.exe not found - backup.ps1 and restore-check.ps1 need it." }
}
$target = Read-EnvValue $envFile 'BACKUP_DIR'
if (-not $target) { $target = 'D:\GameSense-Backup' }
$qualifier = Split-Path -Qualifier $target -EA SilentlyContinue
if ($qualifier -and -not (Test-Path "$qualifier\")) { Write-Warning "The backup disk $qualifier isn't there - set BACKUP_DIR in backend\.env." }
if (-not $db) { Write-Warning 'DATABASE_URL in backend\.env did not parse - deploys will refuse to migrate.' }
elseif (-not $pgDump) { Write-Warning 'pg_dump.exe not found - deploys will refuse to migrate. Set PGDUMP=<full path> in backend\.env.' }
else {
    Write-Host "  pg_dump: $pgDump"
    Write-Host ("  target : {0}@{1}:{2}/{3}" -f $db.User, $db.Host, $db.Port, $db.Db)
    # A dry run now beats discovering the backup is broken during a migration.
    $ErrorActionPreference = 'Continue'
    $env:PGPASSWORD = $db.Password
    & $pgDump -h $db.Host -p $db.Port -U $db.User -d $db.Db --schema-only -f "$env:TEMP\gamesense-preflight.sql"
    $rc = $LASTEXITCODE
    $env:PGPASSWORD = ''
    if ($rc -eq 0) { Write-Host '  backup preflight OK' }
    else { Write-Warning "pg_dump exited $rc - deploys will refuse to migrate until this works." }
    Remove-Item "$env:TEMP\gamesense-preflight.sql" -EA SilentlyContinue
}

Write-Host ''
Write-Host 'Done. Check with:  Get-ScheduledTask GameSense-*'

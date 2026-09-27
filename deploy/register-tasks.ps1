# Register every GameSense scheduled task on Db01. Idempotent - safe to re-run: a task
# that exists is brought back to what is written here, one that doesn't is made.
#
# The native build has no Celery: every recurring job is a Windows scheduled task, and
# until now half of them lived only on the server (audit H-10). All of them:
#
#   GameSense-Update        every 10 min   deploy\update.ps1: the newest tested commit
#                                          goes live (any hour; docs/09-deployment.md)
#   GameSense-Sync          every 15 min   pipeline.py sync: SPYPOINT + UBox + the AI pass
#                           (from :01)
#   GameSense-Notify        every 15 min   pipeline.py notify: alerts that waited, and
#                           (from :02)     tonight's plan about two hours before sunset
#   GameSense-Sex           hourly (:04)   pipeline.py sex: stag/hind, boar/sow (paid)
#   GameSense-Plan          17:00 daily    pipeline.py plan: tonight's claims BEFORE dark
#   GameSense-Score         11:00 daily    pipeline.py score: grade last night's claims
#   GameSense-Backup        03:07 daily    deploy\backup.ps1: database + photos to D:
#   GameSense-RestoreCheck  Sun 04:37      deploy\restore-check.ps1: restore the newest
#                                          dump into a scratch database, check it
#
# The repeating jobs start a minute or two apart, so they don't all start in the same
# second (and the update's quick look, when nothing is new, is over before the fetch).
#
# Task Scheduler throws a task's output away, so each one runs through cmd.exe with
# its errors appended to a file of its own, C:\GameSense\logs\task-<job>.err.log: a job
# that dies before it can write its own log (an import that fails) still leaves the
# reason somewhere. Never one file for two tasks: cmd.exe keeps its redirect open, and
# shut to other writers, until the job ends, so a second task sent to the same file
# would not start at all. A task never runs twice at once (IgnoreNew), so its own file
# is free when it starts. update.ps1 and backup.ps1 roll them over at 5 MB
# (Limit-TaskLogs in lib.ps1). pipeline.py, update.ps1 and backup.ps1 keep their own
# logs in the same folder.
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
$envFile = "$work\.env"

if (-not (Test-Path $python)) { throw "python not found at $python" }
if (-not (Test-Path "$work\pipeline.py")) { throw "pipeline.py not found in $work" }
New-Item -ItemType Directory -Force -Path $logs | Out-Null

# Where a task's errors go: a file of its own (above).
function Task-Errors([string]$Job) { return "$logs\task-$Job.err.log" }

# What a task runs: the command line, through cmd.exe so its errors are kept.
function Pipeline-Action([string]$Mode) {
    New-ScheduledTaskAction -Execute 'cmd.exe' -WorkingDirectory $work `
        -Argument "/c `"`"$python`" pipeline.py $Mode 1>NUL 2>>`"$(Task-Errors $Mode)`"`""
}
function Script-Action([string]$Script) {
    $job = [System.IO.Path]::GetFileNameWithoutExtension($Script)
    New-ScheduledTaskAction -Execute 'cmd.exe' -WorkingDirectory $work `
        -Argument "/c `"powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$deploy\$Script`" 1>NUL 2>>`"$(Task-Errors $job)`"`""
}

# From midnight today plus $Offset minutes, every $Minutes minutes, for good: with no
# -RepetitionDuration the repetition never ends (a [TimeSpan]::MaxValue duration is
# refused on Windows Server 2016 and later).
function Every([int]$Minutes, [int]$Offset = 0) {
    New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes($Offset) `
        -RepetitionInterval (New-TimeSpan -Minutes $Minutes)
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
Register-GameSense 'GameSense-Sync' (Pipeline-Action 'sync') (Every 15 1) 120 `
    'Fetch photos from SPYPOINT and UBox, look for animals, recount the nights.'
# notify takes seconds, so ten minutes is a hung one.
Register-GameSense 'GameSense-Notify' (Pipeline-Action 'notify') (Every 15 2) 10 `
    "Alerts that waited for a sit or quiet hours, and tonight's plan about two hours before sunset."
Register-GameSense 'GameSense-Sex' (Pipeline-Action 'sex') (Every 60 4) 60 `
    'Mark red deer stag or hind and wild boar male or female (cloud vision, costs credit).'
# plan and score wait up to 40 minutes for a running job, inside the hour.
Register-GameSense 'GameSense-Plan' (Pipeline-Action 'plan') (New-ScheduledTaskTrigger -Daily -At '17:00') 60 `
    "Record tonight's forecast before the night, so it can be scored tomorrow."
Register-GameSense 'GameSense-Score' (Pipeline-Action 'score') (New-ScheduledTaskTrigger -Daily -At '11:00') 60 `
    "Grade the forecast of every finished night against what the cameras recorded."
Register-GameSense 'GameSense-Backup' (Script-Action 'backup.ps1') (New-ScheduledTaskTrigger -Daily -At '03:07') 240 `
    'Copy the database and the photos to the backup disk (BACKUP_DIR, else D:\GameSense-Backup).'
Register-GameSense 'GameSense-RestoreCheck' (Script-Action 'restore-check.ps1') `
    (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '04:37') 120 `
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
# The weekly restore test makes a scratch database of its own: the login needs CREATEDB.
$psql = Find-PgTool 'psql' $envFile $Root
if ($db -and $psql) {
    $ErrorActionPreference = 'Continue'
    $env:PGPASSWORD = $db.Password
    $can = & $psql -h $db.Host -p $db.Port -U $db.User -d $db.Db -tAc 'SELECT rolcreatedb OR rolsuper FROM pg_roles WHERE rolname = current_user' 2> $null
    $rc = $LASTEXITCODE
    $env:PGPASSWORD = ''
    if ($rc -ne 0) { Write-Warning "psql exited $rc - the restore test's rights couldn't be checked." }
    elseif ("$can".Trim() -eq 't') { Write-Host '  restore test: the database login may make its scratch database' }
    else {
        Write-Warning ("The database login {0} can't create databases, so the weekly restore test will fail. As postgres: ALTER ROLE {0} CREATEDB;" -f $db.User)
    }
}

Write-Host ''
Write-Host 'Done. Check with:  Get-ScheduledTask GameSense-*'

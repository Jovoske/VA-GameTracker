# Register the GameSense scheduled tasks on Db01. Idempotent - safe to re-run.
#
# The native build has no Celery: every recurring job is a Windows scheduled task
# driving `pipeline.py`. Two of them are new and the estate needs them, because
# without them the forecast can never be scored and the app is back to making
# claims nobody checks:
#
#   GameSense-Plan   17:00 daily  record tonight's claims BEFORE the night
#   GameSense-Score   11:00 daily  grade last night's claims against the cameras
#
# Order matters. `plan` must run before dark or it is not a forecast, and `score`
# must run after the night's photos have synced and been classified.
#
# Run once, elevated, on Db01:
#     powershell -ExecutionPolicy Bypass -File C:\GameSense\app\deploy\register-tasks.ps1

$ErrorActionPreference = 'Stop'
$venv = 'C:\GameSense\venv\Scripts\python.exe'
$work = 'C:\GameSense\app\backend'

if (-not (Test-Path $venv)) { throw "python not found at $venv" }
if (-not (Test-Path "$work\pipeline.py")) { throw "pipeline.py not found in $work" }

function Register-GameSenseTask($name, $mode, $at, $description) {
    $action  = New-ScheduledTaskAction -Execute $venv -Argument "pipeline.py $mode" -WorkingDirectory $work
    $trigger = New-ScheduledTaskTrigger -Daily -At $at
    # SYSTEM, matching GameSense-Update: the service account owns the data directory.
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    # Missed runs matter here - a night that is never claimed can never be scored,
    # and the gap is invisible afterwards.
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1)

    if (Get-ScheduledTask -TaskName $name -EA SilentlyContinue) {
        Set-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
            -Principal $principal -Settings $settings | Out-Null
        Write-Host "updated  $name  ($at)"
    } else {
        Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
            -Principal $principal -Settings $settings -Description $description | Out-Null
        Write-Host "created  $name  ($at)"
    }
}

Register-GameSenseTask 'GameSense-Plan'  'plan'  '17:00' `
    "Record tonight's forecast before the night, so it can be scored tomorrow."
Register-GameSenseTask 'GameSense-Score' 'score' '11:00' `
    "Grade yesterday's forecast against what the cameras actually recorded."

Write-Host ''
Write-Host 'Verifying the deploy backup path (update.ps1 refuses to migrate without it)...'
$dbUrl = (Select-String -Path "$work\.env" -Pattern '^DATABASE_URL=' -EA SilentlyContinue |
          Select-Object -First 1).Line -replace '^DATABASE_URL=', ''
$m = [regex]::Match($dbUrl, '://(?<u>[^:]+):(?<p>[^@]+)@(?<h>[^:/]+):(?<port>\d+)/(?<db>[^?]+)')
$pgDump = $null
$override = (Select-String -Path "$work\.env" -Pattern '^PGDUMP=' -EA SilentlyContinue |
             Select-Object -First 1).Line -replace '^PGDUMP=', ''
foreach ($cand in @($override, (Get-Command pg_dump.exe -EA SilentlyContinue).Source,
                    'C:\GameSense\pg\pgsql\bin\pg_dump.exe',
                    'C:\GameSense\tools\pgsql\bin\pg_dump.exe')) {
    if ($cand -and (Test-Path $cand)) { $pgDump = $cand; break }
}
if (-not $pgDump) {
    $pgDump = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\pg_dump.exe' -EA SilentlyContinue |
              Sort-Object { [int]($_.Directory.Parent.Name) } -Descending |
              Select-Object -First 1 -ExpandProperty FullName
}

if (-not $m.Success) { Write-Warning 'DATABASE_URL in backend\.env did not parse - deploys will refuse to migrate.' }
elseif (-not $pgDump) { Write-Warning 'pg_dump.exe not found - deploys will refuse to migrate. Set PGDUMP=<full path> in backend\.env.' }
else {
    Write-Host "  pg_dump: $pgDump"
    Write-Host ("  target : {0}@{1}:{2}/{3}" -f $m.Groups['u'].Value, $m.Groups['h'].Value,
                                                $m.Groups['port'].Value, $m.Groups['db'].Value)
    # A dry run now beats discovering the backup is broken during a migration.
    $env:PGPASSWORD = [uri]::UnescapeDataString($m.Groups['p'].Value)
    & $pgDump -h $m.Groups['h'].Value -p $m.Groups['port'].Value -U $m.Groups['u'].Value `
              -d $m.Groups['db'].Value --schema-only -f $env:TEMP\gamesense-preflight.sql
    $rc = $LASTEXITCODE
    $env:PGPASSWORD = ''
    if ($rc -eq 0) { Write-Host '  backup preflight OK' }
    else { Write-Warning "pg_dump exited $rc - deploys will refuse to migrate until this works." }
    Remove-Item "$env:TEMP\gamesense-preflight.sql" -EA SilentlyContinue
}

Write-Host ''
Write-Host 'Done. Check with:  Get-ScheduledTask GameSense-*'

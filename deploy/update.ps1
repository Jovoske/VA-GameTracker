# GameSense self-update: put the newest tested commit live, on the server.
#
# Canonical copy lives in the repo, so a deploy updates this script too. Run by the
# GameSense-Update scheduled task (SYSTEM) every 10 minutes, at any hour. Safe to run
# any time: it does nothing when there is nothing new, and it stands down while a job
# (a photo fetch, the AI pass, the plan, the score, the stag/hind pass) is running.
#
#   laptop -> git push main -> GitHub Actions: tests -> 'deploy' branch -> (<=10 min) Db01
#
# WHAT IT DEPLOYS. The 'deploy' branch, which CI (.github/workflows/ci.yml) moves to a
# commit of main only once the backend tests, the frontend build and the UI tests have
# passed on it. Until CI has made that branch it deploys main, as it always did, so
# nothing stops when this lands before CI is live. Moving 'deploy' by hand also works:
# git push origin <commit>:deploy.
#
# ONLY EVER FORWARD. A target older than what runs (the branch CI makes at a commit
# before the one main already put live) is waited for, not deployed: the server stays
# on what runs until the branch passes it. Putting an older commit back on purpose is
# a step by hand: move 'deploy' back, then run this script with -AllowOlder on the
# server (docs/09-deployment.md).
#
# IN WHAT ORDER, and why:
#   1. Every job's lock is taken (pipeline.py hold) and kept until the new version
#      answers, so no job runs new code on the old schema, or has its rows moved by a
#      data migration halfway through (audit H-09).
#   2. The code: git reset --hard <target>.
#   3. Python packages when requirements.txt moved. Tried twice (H-04).
#   4. serve.py check: does the new version load at all.
#   5. The app's screens are built into frontend\dist when frontend/ moved. Tried
#      twice. Nothing is live yet: C:\GameSense\web still holds the old ones (H-05).
#   6. A pg_dump, only when a migration is waiting: with no schema change there is
#      nothing a dump taken now could undo that the nightly backup can't.
#   7. alembic upgrade head.
#   8. The new screens go live (the old ones kept in C:\GameSense\web-previous).
#   9. GameSenseAPI is restarted (and the Suntek services, when installed).
#  10. /api/health must answer "ok" from the new commit within 90 seconds. If it
#      doesn't, everything goes back: the code, the screens and the packages, and the
#      service is restarted on the version before (K-09). The schema stays where the
#      migration took it: migrations only ever add, so the old code runs on it.
#
# A deploy counts as done only when step 10 passes: the commit is then written to
# <data>\deployed.sha. Anything that failed on the way is put back and tried again on
# the next run (3 goes, then every 6 hours or as soon as a newer commit arrives), so a
# PyPI hiccup no longer leaves the server half-deployed for good. What happened goes to
# <data>\deploy-status.json, which Settings -> App version shows.
#
# NOTE ON ERROR HANDLING: git, npm, vite and alembic all write ordinary progress to
# stderr. Under PowerShell 5.1 that becomes a NativeCommandError, so with
# $ErrorActionPreference='Stop' the script dies on a *successful* command. Hence
# 'Continue' plus explicit $LASTEXITCODE checks, and native output sent to files
# rather than piped through 2>&1.

param(
    # Everything lives under here; a test run points it somewhere else.
    [string]$Root = 'C:\GameSense',
    # How long the new version gets to answer /api/health after the restart.
    [int]$HealthSeconds = 90,
    # The pause before a failed pip install or build gets its second go.
    [int]$RetryPauseSeconds = 60,
    # By hand only: deploy the target even when it is older than what runs.
    [switch]$AllowOlder
)

$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\lib.ps1"

$app     = "$Root\app"
$git     = "$Root\tools\git\cmd\git.exe"
$node    = "$Root\tools\node\node.exe"
$npm     = "$Root\tools\node\npm.cmd"
$venv    = "$Root\venv\Scripts"
$python  = "$venv\python.exe"
$web     = "$Root\web"
$webPrev = "$Root\web-previous"
$logs    = "$Root\logs"
$log     = "$logs\update.log"
$envFile = "$app\backend\.env"
$data    = Get-DataDir $envFile $Root
$shaFile = "$data\deployed.sha"
$statusFile = "$data\deploy-status.json"
$env:PATH = "$Root\tools\node;$Root\tools\git\cmd;$env:PATH"

# A commit that keeps failing is tried this many times, then every RETRY_HOURS.
$MAX_TRIES = 3
$RETRY_HOURS = 6

New-Item -ItemType Directory -Force -Path $logs | Out-Null
New-Item -ItemType Directory -Force -Path $data | Out-Null
Limit-Log $log
Limit-TaskLogs $logs

function Note($msg) {
    Add-Content -Path $log -Value ("{0}  {1}" -f (Get-Date -Format 's'), $msg)
}

# ---- what the app shows: <data>\deploy-status.json ---------------------------------------

# PowerShell 7 reads an ISO date in JSON back as a date; the app wants the text.
function As-Stamp($value) {
    if ($value -is [datetime]) { return $value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
    return $value
}

$previous = Read-JsonFile $statusFile
$status = [ordered]@{
    checked_at = Get-UtcStamp
    source = $null
    running = $null
    running_subject = $null
    running_since = $null
    waiting_for_tests = $null
    state = 'current'
    failed = $null
    disk_free_gb = $null
    # The target, while it is older than what runs and so is waited for.
    behind = $null
}
if ($previous) {
    $status.running_since = As-Stamp $previous.running_since
    if ($previous.failed) {
        $was = $previous.failed
        $status.failed = [ordered]@{
            commit = $was.commit; subject = $was.subject; step = $was.step; reason = $was.reason
            at = As-Stamp $was.at; attempts = [int]$was.attempts; gave_up = [bool]$was.gave_up
            rolled_back = [bool]$was.rolled_back
        }
    }
}

function Save-Status {
    if (Test-Path $shaFile) {
        $running = (Get-Content -Path $shaFile -Raw).Trim()
        $status.running = $running
        $status.running_subject = (& $git -C $app log -1 --format=%s $running 2> $null)
    }
    Write-JsonFile $statusFile $status
}

# ---- 0. a job is running: let it finish ---------------------------------------------------

# pipeline.py knows its own locks (owner, process, heartbeat): exit 3 while a live run
# holds one. A run that died no longer counts within minutes.
function PipelineBusy {
    & $python "$app\backend\pipeline.py" busy *> "$logs\update-busy.log"
    return ($LASTEXITCODE -eq 3)
}
if (PipelineBusy) {
    Note "skip: pipeline busy ($((Get-Content "$logs\update-busy.log" -EA SilentlyContinue) -join ' '))"
    $status.state = 'busy'
    Save-Status
    exit 0
}

# ---- 1. what should be live ---------------------------------------------------------------

Set-Location $app
& $git fetch --quiet origin '+refs/heads/main:refs/remotes/origin/main' *> "$logs\update-git.log"
$fetched = $LASTEXITCODE
$deployRef = & $git ls-remote origin 'refs/heads/deploy' 2>> "$logs\update-git.log"
$listed = $LASTEXITCODE
if ($fetched -ne 0 -or $listed -ne 0) {
    # GitHub or the line is down: try again in 10 minutes. Never fall back to main
    # here, or a dropped connection would deploy an untested commit.
    $status.state = 'offline'
    Save-Status
    exit 0
}
if ($deployRef) {
    & $git fetch --quiet origin '+refs/heads/deploy:refs/remotes/origin/deploy' *>> "$logs\update-git.log"
    if ($LASTEXITCODE -ne 0) { $status.state = 'offline'; Save-Status; exit 0 }
    $status.source = 'deploy'
    $target = (& $git rev-parse 'refs/remotes/origin/deploy').Trim()
    $status.waiting_for_tests = [int]((& $git rev-list --count "$target..refs/remotes/origin/main").Trim())
} else {
    $status.source = 'main'
    $target = (& $git rev-parse 'refs/remotes/origin/main').Trim()
}

$head = (& $git rev-parse HEAD).Trim()
$good = $null
if (Test-Path $shaFile) { $good = (Get-Content -Path $shaFile -Raw).Trim() }
if ($good) {
    & $git cat-file -e "$good^{commit}" 2> $null
    if ($LASTEXITCODE -ne 0) { $good = $null }
}
if (-not $good) {
    # The first run of this script: what runs now is taken to be deployed.
    $good = $head
    Write-TextFile $shaFile $good
    if (-not $status.running_since) { $status.running_since = Get-UtcStamp }
}

if ($target -ne $good -and -not $AllowOlder) {
    & $git merge-base --is-ancestor $target $good *> $null
    if ($LASTEXITCODE -eq 0) {
        # What runs is newer than the target: main put it live before CI made the
        # deploy branch at an older commit, or the branch was moved back. Deploys only
        # go forward, so what runs stays until the branch passes it (and is put back
        # on disk, should an interrupted run have left something else there).
        if (-not $previous -or $previous.behind -ne $target) {
            Note ("wait: {0} ({1}) is behind what runs, {2} - waiting for it to pass" -f
                  $target.Substring(0, 7), $status.source, $good.Substring(0, 7))
        }
        $status.behind = $target
        $status.waiting_for_tests = [int]((& $git rev-list --count "$good..refs/remotes/origin/main").Trim())
        $target = $good
    }
}

if ($target -eq $good -and $head -eq $good) {
    # Already current, the common case: stay quiet. A failure stays on the page while
    # its commit is still the one waiting; once the target has moved on, it is history.
    if ($status.failed -and $status.failed.commit -ne $target) { $status.failed = $null }
    Save-Status
    exit 0
}

# The same failing commit: 3 goes, then one every RETRY_HOURS.
$tries = 0
if ($status.failed -and $status.failed.commit -eq $target) {
    $tries = [int]$status.failed.attempts
    $lastTry = [datetime]::MinValue
    if ($status.failed.at) { $lastTry = ([datetime]$status.failed.at).ToUniversalTime() }
    if ($tries -ge $MAX_TRIES -and ((Get-Date).ToUniversalTime() - $lastTry).TotalHours -lt $RETRY_HOURS) {
        $status.state = 'failed'
        $status.failed.gave_up = $true
        Save-Status
        exit 0
    }
}

$subject = (& $git log -1 --format=%s $target 2> $null)
Note "update: $($good.Substring(0,7)) -> $($target.Substring(0,7)) ($($status.source)) $subject"

# What moved: from what is deployed, and from whatever an interrupted run left on disk.
$changed = @(& $git diff --name-only $good $target)
if ($head -ne $good) { $changed += @(& $git diff --name-only $head $target) }
$changed = ($changed | Sort-Object -Unique) -join "`n"
$pipNeeded = $changed -match '(?m)^backend/requirements\.txt$'
$ftpPipNeeded = ($changed -match '(?m)^ftp-receiver/requirements\.txt$') -and (Test-Path "$Root\venv-ftp\Scripts\python.exe")
$buildNeeded = $changed -match '(?m)^frontend/'

$free = Get-FreeGB $Root
$status.disk_free_gb = $free
if ($free -ne $null -and $free -lt 2) {
    Note "skip: only $free GB free on the server's disk - not deploying until there is room"
    $status.state = 'failed'
    $status.failed = [ordered]@{ commit = $target; subject = $subject; step = 'disk'
        reason = "Only $free GB free on the server's disk."; at = Get-UtcStamp
        attempts = $tries + 1; gave_up = $false; rolled_back = $false }
    Save-Status
    exit 1
}
if ($free -ne $null -and $free -lt 10) { Note "WARNING: only $free GB free on the server's disk" }

# ---- the job locks, held until the new version answers --------------------------------------

$script:holder = $null
function Start-Hold {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = Get-FullPath $python
    $psi.Arguments = "`"$app\backend\pipeline.py`" hold"
    $psi.WorkingDirectory = Get-FullPath "$app\backend"
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.CreateNoWindow = $true
    try { $p = [System.Diagnostics.Process]::Start($psi) } catch { return "could not start it: $($_.Exception.Message)" }
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        $read = $p.StandardOutput.ReadLineAsync()
        $left = [int][math]::Max(1, ($deadline - (Get-Date)).TotalMilliseconds)
        if (-not $read.Wait($left)) { break }
        $line = $read.Result
        if ($null -eq $line) { break }                 # it ended without an answer
        if ($line -eq 'held') { $script:holder = $p; return 'held' }
        if ($line -like 'busy*') { $p.WaitForExit(5000) | Out-Null; return $line }
    }
    try { $p.Kill() } catch { }
    return 'no answer'
}
function Stop-Hold {
    if (-not $script:holder) { return }
    try {
        $script:holder.StandardInput.Close()           # the deploy is over: let go
        if (-not $script:holder.WaitForExit(15000)) { $script:holder.Kill() }
    } catch { }
    $script:holder = $null
}

$held = Start-Hold
if ($held -like 'busy*') {
    Note "skip: pipeline busy ($held)"
    $status.state = 'busy'
    Save-Status
    exit 0
}
if ($held -ne 'held') {
    # An older pipeline.py without `hold` (the deploy that brings it), or python not
    # starting: go on as before, on the busy check alone.
    Note "note: could not hold the job locks ($held) - deploying on the busy check alone"
}

# ---- when a step fails: put everything back ---------------------------------------------------

$script:pipRan = $false
$script:webSwapped = $false
$script:restarted = $false
$script:lastHealth = 'no answer'

function Restart-GameSense {
    try {
        Restart-Service GameSenseAPI -EA Stop
    } catch {
        Note "ERROR: Restart-Service GameSenseAPI - $($_.Exception.Message)"
    }
    # The Suntek FTP/mail services (install-ftp.ps1, install-mail.ps1) run repo code too;
    # restart them when present so no importer keeps an old module loaded. A restart
    # mid-upload is safe: the receiver only publishes completed files, and the importer
    # replays anything it had not committed.
    foreach ($svc in @('GameSenseFTPImport', 'GameSenseFTP', 'GameSenseMail')) {
        if (Get-Service $svc -EA SilentlyContinue) { Restart-Service $svc -EA SilentlyContinue; Note "restarted $svc" }
    }
}

function Test-Healthy([string]$Want, [int]$Seconds) {
    $port = Read-EnvValue $envFile 'API_PORT'
    if (-not $port) { $port = '8090' }
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        Start-Sleep -Seconds 3
        try {
            $r = Invoke-WebRequest "http://localhost:$port/api/health" -UseBasicParsing -TimeoutSec 10
            $j = $r.Content | ConvertFrom-Json
            # A version from before /api/health named its commit only says "ok".
            if ($j.status -eq 'ok' -and (-not $j.commit -or $j.commit -eq $Want)) { return $true }
            $script:lastHealth = "it answered $($j.status) from $($j.commit)"
        } catch {
            $script:lastHealth = $_.Exception.Message
        }
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Fail([string]$Step, [string]$Reason) {
    Note "ERROR ($Step): $Reason - putting $($good.Substring(0,7)) back"
    & $git reset --hard $good --quiet *>> "$logs\update-git.log"
    if ($script:pipRan) {
        & $python -m pip install -q -r "$app\backend\requirements.txt" *> "$logs\update-pip-back.log"
    }
    if ($script:webSwapped) {
        robocopy $webPrev $web /MIR /NFL /NDL /NP /NJH /NJS *> $null
        Note 'previous screens put back'
    }
    if ($script:restarted) {
        Restart-GameSense
        if (Test-Healthy $good $HealthSeconds) { Note "rolled back: $($good.Substring(0,7)) is running and healthy" }
        else { Note "ERROR: after rolling back, the API still doesn't answer ($script:lastHealth)" }
    }
    $status.state = 'failed'
    $status.failed = [ordered]@{
        commit = $target; subject = $subject; step = $Step; reason = $Reason
        at = Get-UtcStamp; attempts = $tries + 1; gave_up = ($tries + 1 -ge $MAX_TRIES)
        rolled_back = $script:restarted
    }
    Stop-Hold
    Save-Status
    exit 1
}

# Twice, a minute apart: a PyPI, proxy or npm registry hiccup is the usual failure.
function Try-Twice([scriptblock]$Step, [string]$What) {
    if (& $Step) { return $true }
    Note "$What failed - trying once more in $RetryPauseSeconds seconds"
    Start-Sleep -Seconds $RetryPauseSeconds
    return (& $Step)
}

# ---- 2. the code ----------------------------------------------------------------------------

& $git reset --hard $target --quiet *>> "$logs\update-git.log"
if ($LASTEXITCODE -ne 0) { Fail 'code' 'git reset failed (see update-git.log)' }

# ---- 3. Python packages ---------------------------------------------------------------------

if ($pipNeeded) {
    Note 'pip install'
    $script:pipRan = $true
    $ok = Try-Twice {
        & $python -m pip install -q -r "$app\backend\requirements.txt" *> "$logs\update-pip.log"
        $LASTEXITCODE -eq 0
    } 'pip install'
    if (-not $ok) { Fail 'pip' "The server's Python packages didn't install (see update-pip.log)." }
}
if ($ftpPipNeeded) {
    Note 'pip install (ftp receiver)'
    $ok = Try-Twice {
        & "$Root\venv-ftp\Scripts\python.exe" -m pip install -q -r "$app\ftp-receiver\requirements.txt" *> "$logs\update-pip-ftp.log"
        $LASTEXITCODE -eq 0
    } 'pip install (ftp receiver)'
    if (-not $ok) { Fail 'pip' "The camera receiver's packages didn't install (see update-pip-ftp.log)." }
}

# ---- 4. does the new version load -----------------------------------------------------------

# Also says what it will do about the secrets published with GameSense as it starts
# (backend/serve.py check, which changes nothing).
Push-Location "$app\backend"
& $python "$app\backend\serve.py" check *> "$logs\update-check.log"
$loads = $LASTEXITCODE
Pop-Location
if ($loads -ne 0) { Fail 'check' "The new version doesn't start (see update-check.log)." }
Get-Content "$logs\update-check.log" -EA SilentlyContinue |
    Where-Object { $_.Trim() } | ForEach-Object { Note ("check: " + $_.Trim()) }

# ---- 5. the app's screens, built but not live yet -----------------------------------------------

if ($buildNeeded) {
    Note 'npm build'
    $ok = Try-Twice {
        Push-Location "$app\frontend"
        Remove-Item "$app\frontend\dist" -Recurse -Force -EA SilentlyContinue
        & $npm install --no-audit --no-fund --silent *> "$logs\update-npm.log"
        $installed = $LASTEXITCODE
        & $node "$app\frontend\node_modules\vite\bin\vite.js" build *>> "$logs\update-npm.log"
        $built = $LASTEXITCODE
        Pop-Location
        ($installed -eq 0) -and ($built -eq 0) -and (Test-Path "$app\frontend\dist\index.html")
    } 'npm build'
    if (-not $ok) { Fail 'build' "The app's screens didn't build (see update-npm.log)." }
}

# ---- 6. a backup, when the schema is about to change ------------------------------------------

$env:PYTHONPATH = "$app\backend"
Push-Location "$app\backend"
& "$venv\alembic.exe" current *> "$logs\update-alembic.log"
$askedCurrent = $LASTEXITCODE
Pop-Location
$atHead = ($askedCurrent -eq 0) -and ((Get-Content "$logs\update-alembic.log" -Raw) -match '\(head\)')
if (-not $atHead) {
    # Rolling the code back cannot roll a migration back, so without this a migration
    # that went wrong would leave the season's only copy in whatever state it stopped.
    $db = Get-DbTarget $envFile
    $pgDump = Find-PgTool 'pg_dump' $envFile $Root
    if (-not $db -or -not $pgDump) {
        # Refuse rather than migrate blind: a deploy that stops here is visible and
        # recoverable; a half-applied migration with no backup is neither.
        Fail 'backup' "No backup could be taken (DATABASE_URL read: $([bool]$db), pg_dump found: $([bool]$pgDump)), so the database was not changed."
    }
    $dumps = "$Root\backups"
    New-Item -ItemType Directory -Force -Path $dumps | Out-Null
    $dump = Join-Path $dumps ("gamesense-{0}-before-{1}.dump" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $target.Substring(0, 7))
    $env:PGPASSWORD = $db.Password
    & $pgDump -h $db.Host -p $db.Port -U $db.User -d $db.Db -Fc -f $dump *> "$logs\update-dump.log"
    $dumped = $LASTEXITCODE
    $env:PGPASSWORD = ''
    if ($dumped -ne 0 -or -not (Test-Path $dump)) {
        Fail 'backup' 'The backup before the database change failed (see update-dump.log), so the database was not changed.'
    }
    Note ("backup: {0} ({1:N1} MB)" -f (Split-Path $dump -Leaf), ((Get-Item $dump).Length / 1MB))
    # These are only taken before a schema change, so ten go back a long way.
    Get-ChildItem $dumps -Filter 'gamesense-*.dump' |
        Sort-Object LastWriteTime -Descending | Select-Object -Skip 10 | Remove-Item -Force
}

# ---- 7. the schema -----------------------------------------------------------------------------

# alembic runs every migration of a deploy in one transaction on PostgreSQL: one that
# fails leaves the database as it was, and the old code goes back on it.
Push-Location "$app\backend"
& "$venv\alembic.exe" upgrade head *> "$logs\update-alembic.log"
$migrated = $LASTEXITCODE
Pop-Location
if ($migrated -ne 0) { Fail 'migrate' 'The database change failed (see update-alembic.log).' }
Select-String -Path "$logs\update-alembic.log" -Pattern 'Running upgrade' -EA SilentlyContinue |
    ForEach-Object { Note ($_.Line.Trim()) }

# ---- 8. the new screens go live ------------------------------------------------------------------

if ($buildNeeded) {
    New-Item -ItemType Directory -Force -Path $web | Out-Null
    robocopy $web $webPrev /MIR /NFL /NDL /NP /NJH /NJS *> $null
    $script:webSwapped = $true
    robocopy "$app\frontend\dist" $web /MIR /NFL /NDL /NP /NJH /NJS *> $null
    if ($LASTEXITCODE -ge 8) { Fail 'screens' "The new screens couldn't be copied into $web." }
    Note 'frontend deployed'
}

# ---- 9 + 10. restart, and the new version must answer --------------------------------------------

$script:restarted = $true
Restart-GameSense
if (-not (Test-Healthy $target $HealthSeconds)) {
    Note "health: $script:lastHealth"
    Fail 'health' "The new version didn't answer as healthy within $HealthSeconds seconds."
}

Write-TextFile $shaFile $target
Stop-Hold
$status.state = 'current'
$status.running_since = Get-UtcStamp
$status.failed = $null
Save-Status
Note "done: $($target.Substring(0,7)) is live and healthy"
exit 0

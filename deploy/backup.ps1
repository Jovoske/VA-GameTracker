# GameSense nightly backup: the database and the photos, onto another disk.
#
# Run by the GameSense-Backup scheduled task (SYSTEM) at 03:00 (register-tasks.ps1).
# The photos matter most: once SPYPOINT drops its cloud copy (after about 30 days),
# C:\GameSense\data\media holds the only one. So each night:
#
#   1. pg_dump -Fc of the database to <target>\db, checked by listing it back with
#      pg_restore. The newest 14 are kept.
#   2. The photos, copied to <target>\media. New and changed files only; a photo
#      is never deleted from the backup because it went from the server. Every photo
#      the server held when the copy started must be in the backup after it; one the
#      fetch brings in meanwhile is the next night's. No photo folder is a failure.
#   3. backend\.env to <target>\config: without its JWT_SECRET / CREDENTIALS_KEY the
#      saved camera passwords in a restored database can't be read. It holds secrets:
#      the target folder must be no more open than C:\GameSense is.
#   4. What happened, to <data>\backup-status.json. Settings -> System shows it, in
#      red when the last good backup is more than 36 hours old or this one failed.
#
# The target is BACKUP_DIR in backend\.env, else D:\GameSense-Backup: a disk other
# than the one the database and the photos are on, or it is no backup of them.
# deploy/restore-check.ps1 restores the newest dump every week to prove it works.
#
# Run it by hand:  powershell -ExecutionPolicy Bypass -File C:\GameSense\app\deploy\backup.ps1

param(
    [string]$Root = 'C:\GameSense',
    [string]$Target = ''
)

$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\lib.ps1"

$app     = "$Root\app"
$envFile = "$app\backend\.env"
$logs    = "$Root\logs"
$log     = "$logs\backup.log"
$data    = Get-DataDir $envFile $Root
$statusFile = "$data\backup-status.json"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
Limit-Log $log
Limit-TaskLogs $logs

function Note($msg) {
    Add-Content -Path $log -Value ("{0}  {1}" -f (Get-Date -Format 's'), $msg)
}

if (-not $Target) { $Target = Read-EnvValue $envFile 'BACKUP_DIR' }
if (-not $Target) { $Target = 'D:\GameSense-Backup' }
$media = Read-EnvValue $envFile 'MEDIA_ROOT'
if (-not $media) { $media = "$data\media" }
# A relative MEDIA_ROOT is the app's, and the app runs in backend\.
if (-not [System.IO.Path]::IsPathRooted($media)) { $media = Join-Path "$app\backend" $media }

# The last one that worked, so a failed night still says how old the good copy is.
$previous = Read-JsonFile $statusFile
$lastOk = $null
if ($previous) {
    $lastOk = $previous.last_ok_at
    if ($previous.ok -eq $true) { $lastOk = $previous.finished_at }
    if ($lastOk -is [datetime]) { $lastOk = $lastOk.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
}

$status = [ordered]@{
    started_at = Get-UtcStamp
    finished_at = $null
    ok = $false
    last_ok_at = $lastOk
    target = $Target
    dump = $null
    dump_mb = $null
    photos_on_server = $null
    photos_in_backup = $null
    target_free_gb = $null
    error = $null
}

function Finish([string]$Problem) {
    $status.finished_at = Get-UtcStamp
    $status.target_free_gb = Get-FreeGB $Target
    if ($Problem) {
        $status.error = $Problem
        Note "ERROR: $Problem"
    } else {
        $status.ok = $true
        $status.last_ok_at = $status.finished_at
        Note ("done: {0} ({1} MB), {2} of {3} photos in the backup, {4} GB free there" -f
              $status.dump, $status.dump_mb, $status.photos_in_backup, $status.photos_on_server,
              $status.target_free_gb)
    }
    Write-JsonFile $statusFile $status
    if ($Problem) { exit 1 } else { exit 0 }
}

Note "backup to $Target"
try {
    New-Item -ItemType Directory -Force -Path "$Target\db", "$Target\media", "$Target\config" -EA Stop | Out-Null
} catch {
    Finish "The backup folder $Target can't be written ($($_.Exception.Message))."
}

# ---- 1. the database ------------------------------------------------------------------------

$db = Get-DbTarget $envFile
$pgDump = Find-PgTool 'pg_dump' $envFile $Root
$pgRestore = Find-PgTool 'pg_restore' $envFile $Root
if (-not $db) { Finish "DATABASE_URL in backend\.env can't be read." }
if (-not $pgDump -or -not $pgRestore) { Finish 'pg_dump or pg_restore not found (set PGDUMP / PGRESTORE in backend\.env).' }

$name = 'gamesense-{0}.dump' -f (Get-Date -Format 'yyyyMMdd-HHmmss')
$dump = Join-Path "$Target\db" $name
$env:PGPASSWORD = $db.Password
& $pgDump -h $db.Host -p $db.Port -U $db.User -d $db.Db -Fc -f $dump *> "$logs\backup-dump.log"
$dumped = $LASTEXITCODE
# A dump pg_restore can't list is not a backup: read it back.
& $pgRestore --list $dump *> "$logs\backup-list.log"
$listed = $LASTEXITCODE
$env:PGPASSWORD = ''
if ($dumped -ne 0 -or -not (Test-Path $dump)) { Finish 'pg_dump failed (see backup-dump.log).' }
if ($listed -ne 0) { Finish "The dump can't be read back (see backup-list.log)." }
$status.dump = $name
$status.dump_mb = [math]::Round((Get-Item $dump).Length / 1MB, 1)
Get-ChildItem "$Target\db" -Filter 'gamesense-*.dump' |
    Sort-Object Name -Descending | Select-Object -Skip 14 | Remove-Item -Force

# ---- 2. the photos --------------------------------------------------------------------------

# What is not a photo of its own: thumbnails (made again from the photos) and a
# download still being written (the fetch's *.tmp, the camera receiver's .ftp-*).
$notPhoto = '^thumbs[\\/]|\.tmp$|(^|[\\/])\.ftp-[^\\/]*$'
# Every photo under $Dir, by its path below it. Throws when the folder can't be read.
function Get-Photos([string]$Dir) {
    $base = (Get-Item -LiteralPath $Dir -Force -EA Stop).FullName.TrimEnd('\', '/')
    Get-ChildItem -LiteralPath $Dir -Recurse -File -Force -EA Stop |
        ForEach-Object { $_.FullName.Substring($base.Length + 1) } |
        Where-Object { $_ -notmatch $notPhoto }
}

if (-not (Test-Path -LiteralPath $media -PathType Container)) {
    Finish "The photo folder $media isn't there, so no photos were backed up."
}
# The photos as they are before the copy starts: one the fetch brings in while
# robocopy runs (GameSense-Sync runs every 15 minutes, all night) is the next night's
# to copy, not a hole in this one.
try {
    $onServer = @(Get-Photos $media)
} catch {
    Finish "The photo folder $media can't be read ($($_.Exception.Message)), so no photos were backed up."
}
# /E every folder; no /MIR: a photo gone from the server stays in the backup.
robocopy $media "$Target\media" /E /XD (Join-Path $media 'thumbs') /XF *.tmp .ftp-* /R:2 /W:5 /NP /NFL /NDL /NJH /NJS *> "$logs\backup-media.log"
$copied = $LASTEXITCODE
if ($copied -ge 8) { Finish "Some photos couldn't be copied (see backup-media.log)." }
$inBackup = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
try {
    foreach ($photo in (Get-Photos "$Target\media")) { [void]$inBackup.Add($photo) }
} catch {
    Finish "The backup's photo folder can't be read ($($_.Exception.Message))."
}
# Each of them must be in the backup now, unless it has gone from the server since.
$missing = @($onServer | Where-Object {
    -not $inBackup.Contains($_) -and (Test-Path -LiteralPath (Join-Path $media $_))
})
$status.photos_on_server = $onServer.Count
$status.photos_in_backup = $inBackup.Count
if ($missing.Count -gt 0) {
    Note ("not in the backup: {0}" -f (($missing | Select-Object -First 5) -join ', '))
    Finish ("{0} of the server's {1} photos aren't in the backup (see backup-media.log)." -f
            $missing.Count, $onServer.Count)
}

# ---- 3. the settings that unlock it ---------------------------------------------------------------

Copy-Item -Force -Path $envFile -Destination "$Target\config\backend.env" -EA SilentlyContinue

Finish $null

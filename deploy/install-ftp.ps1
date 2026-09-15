# Install the Suntek HC801LTE (4G) camera FTP path on Db01: an FTP receiver and a
# photo importer, both as auto-start NSSM services. Idempotent - safe to re-run
# after changing ftp.env. Run once, elevated, on Db01:
#
#     powershell -ExecutionPolicy Bypass -File C:\GameSense\app\deploy\install-ftp.ps1
#
# Before running, create C:\GameSense\ftp.env (outside the repo - never in git):
#
#     FTP_USERNAME=suntek-01
#     FTP_PASSWORD=                 long random camera-only password, 13+ chars,
#                                   letters/digits/-_.:! only (never the app password)
#     FTP_CAMERA_ID=                leave blank: the script registers the camera and fills it in
#     FTP_CAMERA_TIMEZONE=Europe/Madrid
#     FTP_BIND=127.0.0.1            0.0.0.0 to accept the camera (opens Windows Firewall too)
#     FTP_CONTROL_PORT=2121
#     FTP_PUBLIC_IP=                the router's public IPv4; required once FTP_BIND is 0.0.0.0
#
# What it does, in order:
#   1. creates the spool C:\GameSense\data\ftp-spool and the receiver venv C:\GameSense\venv-ftp
#   2. registers the camera in the app if FTP_CAMERA_ID is blank
#   3. installs/updates services GameSenseFTP (receiver) and GameSenseFTPImport (importer)
#   4. starts the receiver and uploads a test JPEG over loopback; fails loudly if it does not land
#   5. starts the importer, opens Windows Firewall when not bound to loopback, prints camera settings
#
# The router still has to forward TCP FTP_CONTROL_PORT and TCP 50000-50009 to Db01 by hand,
# and someone at the camera has to load the settings via MMSCONFIG. See docs/14-suntek-ftp.md.
#
# Native stderr from python/pip/nssm would be a terminating error under 'Stop' in PowerShell 5.1,
# hence 'Continue' with explicit $LASTEXITCODE checks, same as update.ps1.

param(
    [string]$Config = 'C:\GameSense\ftp.env'
)

$ErrorActionPreference = 'Continue'
$repo      = 'C:\GameSense\app'
$backend   = "$repo\backend"
$receiver  = "$repo\ftp-receiver"
$venv      = 'C:\GameSense\venv'
$venvFtp   = 'C:\GameSense\venv-ftp'
$spool     = 'C:\GameSense\data\ftp-spool'
$logs      = 'C:\GameSense\logs'
$svcRecv   = 'GameSenseFTP'
$svcImport = 'GameSenseFTPImport'
$passiveLo = 50000
$passiveHi = 50009

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }
function Step($msg) { Write-Host "== $msg" -ForegroundColor Cyan }

# ---- preflight -------------------------------------------------------------------------------
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
        ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail 'run this from an elevated PowerShell (services and firewall rules need it)'
}
$python = "$venv\Scripts\python.exe"
if (-not (Test-Path $python))                     { Fail "backend python not found at $python" }
if (-not (Test-Path "$backend\.env"))             { Fail "backend .env not found at $backend\.env" }
if (-not (Test-Path "$receiver\receiver.py"))     { Fail "receiver not found at $receiver - has Db01 pulled main yet? (C:\GameSense\logs\update.log)" }
if (-not (Test-Path "$backend\app\ingestion\ftp_import.py")) { Fail 'importer not found - has Db01 pulled main yet?' }
if (-not (Test-Path $Config))                     { Fail "config not found at $Config - create it from the header of this script" }

$nssm = (Get-Command nssm.exe -EA SilentlyContinue).Source
if (-not $nssm) {
    $nssm = Get-ChildItem 'C:\GameSense\tools' -Recurse -Filter nssm.exe -EA SilentlyContinue |
            Where-Object { $_.FullName -match 'win64' } | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $nssm) {
    $nssm = Get-ChildItem 'C:\GameSense\tools' -Recurse -Filter nssm.exe -EA SilentlyContinue |
            Select-Object -First 1 -ExpandProperty FullName
}
if (-not $nssm) { Fail 'nssm.exe not found on PATH or under C:\GameSense\tools' }

# ---- config -----------------------------------------------------------------------------------
$cfg = @{}
foreach ($line in Get-Content $Config) {
    $line = $line.Trim()
    if (-not $line -or $line.StartsWith('#') -or -not $line.Contains('=')) { continue }
    $k, $v = $line.Split('=', 2)
    $cfg[$k.Trim()] = $v.Trim()
}
function Cfg($key, $default) { if ($cfg.ContainsKey($key) -and $cfg[$key] -ne '') { $cfg[$key] } else { $default } }

$ftpUser  = Cfg 'FTP_USERNAME' ''
$ftpPass  = Cfg 'FTP_PASSWORD' ''
$cameraId = Cfg 'FTP_CAMERA_ID' ''
$tz       = Cfg 'FTP_CAMERA_TIMEZONE' 'Europe/Madrid'
$bind     = Cfg 'FTP_BIND' '127.0.0.1'
$port     = [int](Cfg 'FTP_CONTROL_PORT' '2121')
$publicIp = Cfg 'FTP_PUBLIC_IP' ''

if (-not $ftpUser)                                    { Fail 'FTP_USERNAME is empty' }
if ($ftpPass.Length -lt 13)                           { Fail 'FTP_PASSWORD must be at least 13 characters' }
if ($ftpUser -notmatch '^[A-Za-z0-9._-]+$')           { Fail 'FTP_USERNAME: letters, digits, . _ - only' }
if ($ftpPass -notmatch '^[A-Za-z0-9._:!-]+$')         { Fail 'FTP_PASSWORD: letters, digits, . _ - : ! only (no spaces or quotes)' }
if ($port -lt 1 -or $port -gt 65535)                  { Fail 'FTP_CONTROL_PORT out of range' }
if ($bind -ne '127.0.0.1' -and -not $publicIp)        { Fail 'FTP_PUBLIC_IP is required when FTP_BIND is not 127.0.0.1 (passive replies must carry the public address)' }
if ($publicIp -and $publicIp -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { Fail 'FTP_PUBLIC_IP must be an IPv4 literal' }
$backendUrl = (Select-String -Path "$backend\.env" -Pattern '^DATABASE_URL=' -EA SilentlyContinue | Select-Object -First 1).Line
if ($backendUrl -and $backendUrl.Contains($ftpPass)) { Fail 'FTP_PASSWORD must not be the database password' }

# ---- 1. spool + receiver venv + backend deps -----------------------------------------------
Step 'spool and python environments'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
foreach ($d in @($spool, "$spool\staging", "$spool\ready", "$spool\ftp-home",
                 "$spool\processing", "$spool\failed", "$spool\processed")) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}

if (-not (Test-Path "$venvFtp\Scripts\python.exe")) {
    & $python -m venv $venvFtp *> "$logs\ftp-install-venv.log"
    if ($LASTEXITCODE -ne 0) { Fail "could not create $venvFtp - see ftp-install-venv.log" }
}
& "$venvFtp\Scripts\python.exe" -m pip install -q -r "$receiver\requirements.txt" *> "$logs\ftp-install-pip.log"
if ($LASTEXITCODE -ne 0) { Fail 'receiver pip install failed - see ftp-install-pip.log' }

& $python -c 'import PIL, tzdata' *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host '   backend is missing Pillow/tzdata - installing backend/requirements.txt'
    & $python -m pip install -q -r "$backend\requirements.txt" *>> "$logs\ftp-install-pip.log"
    if ($LASTEXITCODE -ne 0) { Fail 'backend pip install failed - see ftp-install-pip.log' }
}

# ---- 2. camera registration ------------------------------------------------------------------
Step 'camera'
Push-Location $backend
if (-not $cameraId) {
    & $python -m app.ingestion.ftp_import list *> "$logs\ftp-install-list.json"
    if ($LASTEXITCODE -ne 0) { Pop-Location; Fail 'could not list estates - see ftp-install-list.json' }
    $listing = Get-Content "$logs\ftp-install-list.json" -Raw | ConvertFrom-Json
    $estates = @($listing.estates)
    $existing = @($listing.cameras | Where-Object { $_.ftp_eligible -and $_.name -match 'Suntek' })
    if ($existing.Count -eq 1) {
        $cameraId = $existing[0].id
        Write-Host "   reusing existing camera '$($existing[0].name)' $cameraId"
    } elseif ($estates.Count -ne 1) {
        Pop-Location
        Write-Host ($listing | ConvertTo-Json -Depth 4)
        Fail 'more than one estate (or none) - set FTP_CAMERA_ID in ftp.env after registering by hand'
    } else {
        & $python -m app.ingestion.ftp_import register --estate-id $estates[0].id --name 'Suntek HC801LTE' *> "$logs\ftp-install-register.log"
        if ($LASTEXITCODE -ne 0) { Pop-Location; Fail 'camera registration failed - see ftp-install-register.log' }
        $cameraId = (Get-Content "$logs\ftp-install-register.log" | Where-Object { $_ -match '^[0-9a-f-]{36}$' } | Select-Object -Last 1)
        if (-not $cameraId) { Pop-Location; Fail 'registration printed no camera UUID - see ftp-install-register.log' }
        Write-Host "   registered camera 'Suntek HC801LTE' in estate '$($estates[0].name)': $cameraId"
    }
    # Persist it so a re-run never registers a second camera.
    $text = Get-Content $Config -Raw
    if ($text -match '(?m)^FTP_CAMERA_ID=') { $text = $text -replace '(?m)^FTP_CAMERA_ID=.*$', "FTP_CAMERA_ID=$cameraId" }
    else { $text = $text.TrimEnd() + "`r`nFTP_CAMERA_ID=$cameraId`r`n" }
    Set-Content -Path $Config -Value $text -NoNewline
}
Pop-Location
Write-Host "   camera id $cameraId, timezone $tz"

# ---- 3. services -----------------------------------------------------------------------------
Step 'services'
function Ensure-Service($name, $exe) {
    if (Get-Service $name -EA SilentlyContinue) {
        Stop-Service $name -Force -EA SilentlyContinue
        & $nssm set $name Application $exe *> $null
    } else {
        & $nssm install $name $exe *> "$logs\ftp-install-nssm.log"
        if ($LASTEXITCODE -ne 0) { Fail "nssm install $name failed - see ftp-install-nssm.log" }
    }
}
function Set-Svc($name, $key) {
    $rest = $args
    & $nssm set $name $key @rest *> $null
    if ($LASTEXITCODE -ne 0) { Fail "nssm set $name $key failed" }
}

Ensure-Service $svcRecv "$venvFtp\Scripts\python.exe"
Set-Svc $svcRecv AppParameters 'receiver.py'
Set-Svc $svcRecv AppDirectory $receiver
Set-Svc $svcRecv AppEnvironmentExtra "FTP_USERNAME=$ftpUser" "FTP_PASSWORD=$ftpPass" "FTP_SPOOL_ROOT=$spool" `
    "FTP_BIND=$bind" "FTP_PORT=$port" "FTP_PUBLIC_IP=$publicIp" "PYTHONUNBUFFERED=1"
Set-Svc $svcRecv AppStdout "$logs\ftp-receiver.log"
Set-Svc $svcRecv AppStderr "$logs\ftp-receiver.log"
Set-Svc $svcRecv AppRotateFiles 1
Set-Svc $svcRecv AppRotateBytes 10485760
Set-Svc $svcRecv AppExit Default Restart
Set-Svc $svcRecv AppRestartDelay 5000
Set-Svc $svcRecv Start SERVICE_AUTO_START
Set-Svc $svcRecv Description 'GameSense: FTP receiver for the Suntek 4G camera (upload-only, one account)'

Ensure-Service $svcImport $python
Set-Svc $svcImport AppParameters "-m app.ingestion.ftp_import run --camera-id $cameraId --spool $spool --timezone $tz --watch --interval 30"
Set-Svc $svcImport AppDirectory $backend
Set-Svc $svcImport AppEnvironmentExtra "PYTHONUNBUFFERED=1"
Set-Svc $svcImport AppStdout "$logs\ftp-importer.log"
Set-Svc $svcImport AppStderr "$logs\ftp-importer.log"
Set-Svc $svcImport AppRotateFiles 1
Set-Svc $svcImport AppRotateBytes 10485760
Set-Svc $svcImport AppExit Default Restart
Set-Svc $svcImport AppRestartDelay 5000
Set-Svc $svcImport Start SERVICE_AUTO_START
Set-Svc $svcImport Description 'GameSense: imports Suntek FTP photos into the camera gallery and AI pipeline'
Write-Host "   $svcRecv and $svcImport registered"

# ---- 4. loopback upload test (importer still stopped, so the test photo never enters the app) --
Step 'receiver smoke test'
Start-Service $svcRecv
$testHost = if ($bind -eq '0.0.0.0') { '127.0.0.1' } else { $bind }
$up = $false
foreach ($i in 1..20) {
    Start-Sleep -Milliseconds 500
    if ((Get-Service $svcRecv).Status -ne 'Running') { break }
    if (Test-NetConnection $testHost -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue) { $up = $true; break }
}
if (-not $up) { Fail "receiver is not listening on ${testHost}:$port - see $logs\ftp-receiver.log" }

$smoke = @'
import ftplib, io, os, sys, time
from pathlib import Path
from PIL import Image
host, port, user, password, spool = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4], Path(sys.argv[5])
buf = io.BytesIO(); Image.new("RGB", (64, 48), (90, 120, 60)).save(buf, "JPEG"); buf.seek(0)
before = {p.name for p in (spool / "ready").iterdir()}
ftp = ftplib.FTP(); ftp.connect(host, port, timeout=20); ftp.login(user, password)
ftp.set_pasv(True); ftp.trust_server_pasv_ipv4_address = False
reply = ftp.storbinary("STOR PICT_INSTALLTEST.JPG", buf); ftp.quit()
print("ftp reply:", reply)
for _ in range(20):
    new = [p for p in (spool / "ready").iterdir() if p.name not in before]
    if new: break
    time.sleep(0.25)
else:
    sys.exit("upload acknowledged but no ready package appeared")
pkg = new[0]
ok = (pkg / "photo.jpg").is_file() and (pkg / "metadata.json").is_file()
print("ready package:", pkg.name, "complete" if ok else "INCOMPLETE")
for f in pkg.iterdir(): f.unlink()
pkg.rmdir()
sys.exit(0 if ok else 1)
'@
$smokePath = "$logs\ftp-install-smoke.py"
Set-Content -Path $smokePath -Value $smoke -Encoding ASCII
& $python $smokePath $testHost $port $ftpUser $ftpPass $spool *> "$logs\ftp-install-smoke.log"
$smokeExit = $LASTEXITCODE
Get-Content "$logs\ftp-install-smoke.log" | ForEach-Object { Write-Host "   $_" }
if ($smokeExit -ne 0) { Fail "loopback upload failed - see $logs\ftp-install-smoke.log and $logs\ftp-receiver.log" }

# ---- 5. importer, firewall, summary ---------------------------------------------------------
Step 'importer'
Start-Service $svcImport
Start-Sleep -Seconds 5
if ((Get-Service $svcImport).Status -ne 'Running') { Fail "importer did not stay running - see $logs\ftp-importer.log" }
Write-Host "   running"

if ($bind -ne '127.0.0.1') {
    Step 'windows firewall'
    if (-not (Get-NetFirewallRule -DisplayName 'GameSense FTP control' -EA SilentlyContinue)) {
        New-NetFirewallRule -DisplayName 'GameSense FTP control' -Direction Inbound -Protocol TCP -LocalPort $port -Action Allow | Out-Null
    }
    if (-not (Get-NetFirewallRule -DisplayName 'GameSense FTP passive' -EA SilentlyContinue)) {
        New-NetFirewallRule -DisplayName 'GameSense FTP passive' -Direction Inbound -Protocol TCP -LocalPort "$passiveLo-$passiveHi" -Action Allow | Out-Null
    }
    Write-Host "   inbound TCP $port and $passiveLo-$passiveHi allowed on Db01"
}

Write-Host ''
Write-Host 'Done. Services:' -ForegroundColor Green
Get-Service $svcRecv, $svcImport | Format-Table Name, Status -AutoSize
Write-Host 'Camera settings (MMSCONFIG -> FTP):'
Write-Host "   Server    : $(if ($publicIp) { $publicIp } else { '<set FTP_PUBLIC_IP and FTP_BIND=0.0.0.0 in ftp.env, then re-run>' })"
Write-Host "   Port      : $port"
Write-Host '   Folder    : /'
Write-Host "   Account   : $ftpUser"
Write-Host "   Password  : (FTP_PASSWORD from $Config)"
Write-Host '   Mode      : photo only, passive FTP'
Write-Host ''
Write-Host 'Still to do by hand:'
if ($bind -eq '127.0.0.1') {
    Write-Host '   1. set FTP_BIND=0.0.0.0 and FTP_PUBLIC_IP=<public IPv4> in ftp.env and re-run this script'
}
Write-Host "   2. on the router, forward TCP $port and TCP $passiveLo-$passiveHi to this server"
Write-Host '   3. test an upload from outside the LAN (phone hotspot) with any FTP client'
Write-Host '   4. load the camera settings via MMSCONFIG / Parameter.dat and trigger one photo'
Write-Host "   5. watch $logs\ftp-receiver.log and $logs\ftp-importer.log; the photo appears under the camera in the app"

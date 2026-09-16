# Install the Suntek 4G camera EMAIL path on Db01: a mailbox poller (IMAP, outbound only)
# that drops each emailed JPEG into the spool the GameSenseFTPImport importer already
# watches. Nothing listens on a port; no router or firewall change is needed.
# Idempotent - safe to re-run after changing mail.env. Run once, elevated, on Db01:
#
#     powershell -ExecutionPolicy Bypass -File C:\GameSense\app\deploy\install-mail.ps1
#
# Prerequisite: deploy\install-ftp.ps1 has run at least once (it registers the camera and
# installs the importer service). The FTP receiver itself may be removed; only the importer
# is needed here.
#
# Before running, create C:\GameSense\mail.env (outside the repo - never in git):
#
#     MAIL_IMAP_HOST=imap.gmail.com
#     MAIL_IMAP_PORT=993
#     MAIL_USERNAME=                the camera mailbox address (a dedicated account)
#     MAIL_PASSWORD=                its app password (Gmail: 16 letters; spaces are ignored)
#     MAIL_FOLDER=INBOX
#     MAIL_FROM_FILTER=             optional: only import mail whose From contains this text
#     MAIL_POLL_SECONDS=60
#
# What it does, in order:
#   1. checks the importer service and the spool exist, creates the receiver venv if missing
#   2. installs/updates the auto-start NSSM service GameSenseMail (logs: C:\GameSense\logs\mail-receiver.log)
#   3. proves the mailbox login works with a one-shot poll BEFORE starting the service
#   4. starts the service and prints the camera's SMTP settings
#
# Native stderr from python/nssm would be a terminating error under 'Stop' in PowerShell 5.1,
# hence 'Continue' with explicit $LASTEXITCODE checks, same as update.ps1.

param(
    [string]$Config = 'C:\GameSense\mail.env'
)

$ErrorActionPreference = 'Continue'
$repo      = 'C:\GameSense\app'
$receiver  = "$repo\mail-receiver"
$venv      = 'C:\GameSense\venv'
$venvFtp   = 'C:\GameSense\venv-ftp'
$spool     = 'C:\GameSense\data\ftp-spool'
$logs      = 'C:\GameSense\logs'
$svcMail   = 'GameSenseMail'
$svcImport = 'GameSenseFTPImport'

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }
function Step($msg) { Write-Host "== $msg" -ForegroundColor Cyan }

# ---- preflight -------------------------------------------------------------------------------
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
        ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail 'run this from an elevated PowerShell (services need it)'
}
$python = "$venv\Scripts\python.exe"
if (-not (Test-Path $python))                 { Fail "backend python not found at $python" }
if (-not (Test-Path "$receiver\receiver.py")) { Fail "mail receiver not found at $receiver - has Db01 pulled main yet? (C:\GameSense\logs\update.log)" }
if (-not (Test-Path $Config))                 { Fail "config not found at $Config - create it from the header of this script" }
if (-not (Get-Service $svcImport -EA SilentlyContinue)) { Fail "$svcImport service missing - run deploy\install-ftp.ps1 first (it registers the camera and the importer)" }
if (-not (Test-Path $spool))                  { Fail "spool $spool missing - run deploy\install-ftp.ps1 first" }

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

$host_    = Cfg 'MAIL_IMAP_HOST' 'imap.gmail.com'
$port     = [int](Cfg 'MAIL_IMAP_PORT' '993')
$user     = Cfg 'MAIL_USERNAME' ''
$pass     = (Cfg 'MAIL_PASSWORD' '') -replace ' ', ''
$folder   = Cfg 'MAIL_FOLDER' 'INBOX'
$fromFilt = Cfg 'MAIL_FROM_FILTER' ''
$poll     = [int](Cfg 'MAIL_POLL_SECONDS' '60')

if (-not $user)                                 { Fail 'MAIL_USERNAME is empty' }
if ($pass.Length -lt 8)                         { Fail 'MAIL_PASSWORD is missing or too short' }
if (($user + $pass + $host_) -match '["\r\n]')  { Fail 'mail settings must not contain quotes or newlines' }
if ($port -lt 1 -or $port -gt 65535)            { Fail 'MAIL_IMAP_PORT out of range' }
if ($poll -lt 5)                                { Fail 'MAIL_POLL_SECONDS must be at least 5' }
$backendUrl = (Select-String -Path "$repo\backend\.env" -Pattern '^DATABASE_URL=' -EA SilentlyContinue | Select-Object -First 1).Line
if ($backendUrl -and $backendUrl.Contains($pass)) { Fail 'MAIL_PASSWORD must not be the database password' }

# ---- 1. environment ----------------------------------------------------------------------------
Step 'python environment'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
if (-not (Test-Path "$venvFtp\Scripts\python.exe")) {
    & $python -m venv $venvFtp *> "$logs\mail-install-venv.log"
    if ($LASTEXITCODE -ne 0) { Fail "could not create $venvFtp - see mail-install-venv.log" }
}
$pyMail = "$venvFtp\Scripts\python.exe"
Write-Host "   $pyMail (standard library only, no packages needed)"

# ---- 2. service ----------------------------------------------------------------------------------
Step 'service'
if (Get-Service $svcMail -EA SilentlyContinue) {
    Stop-Service $svcMail -Force -EA SilentlyContinue
    & $nssm set $svcMail Application $pyMail *> $null
} else {
    & $nssm install $svcMail $pyMail *> "$logs\mail-install-nssm.log"
    if ($LASTEXITCODE -ne 0) { Fail "nssm install $svcMail failed - see mail-install-nssm.log" }
}
function Set-Svc($key) {
    $rest = $args
    & $nssm set $svcMail $key @rest *> $null
    if ($LASTEXITCODE -ne 0) { Fail "nssm set $svcMail $key failed" }
}
$envExtra = @("MAIL_IMAP_HOST=$host_", "MAIL_IMAP_PORT=$port", "MAIL_USERNAME=$user", "MAIL_PASSWORD=$pass",
              "MAIL_FOLDER=$folder", "MAIL_SPOOL_ROOT=$spool", "MAIL_POLL_SECONDS=$poll", "PYTHONUNBUFFERED=1")
if ($fromFilt) { $envExtra += "MAIL_FROM_FILTER=$fromFilt" }
Set-Svc AppParameters 'receiver.py'
Set-Svc AppDirectory $receiver
Set-Svc AppEnvironmentExtra @envExtra
Set-Svc AppStdout "$logs\mail-receiver.log"
Set-Svc AppStderr "$logs\mail-receiver.log"
Set-Svc AppRotateFiles 1
Set-Svc AppRotateBytes 10485760
Set-Svc AppExit Default Restart
Set-Svc AppRestartDelay 5000
Set-Svc Start SERVICE_AUTO_START
Set-Svc Description 'GameSense: polls the Suntek 4G camera mailbox (IMAP) into the photo spool'
Write-Host "   $svcMail registered"

# ---- 3. mailbox login smoke test (service still stopped) --------------------------------------
Step 'mailbox smoke test'
$env:MAIL_IMAP_HOST = $host_; $env:MAIL_IMAP_PORT = "$port"; $env:MAIL_USERNAME = $user
$env:MAIL_PASSWORD = $pass;   $env:MAIL_FOLDER = $folder;    $env:MAIL_SPOOL_ROOT = $spool
$env:MAIL_POLL_SECONDS = "$poll"; $env:PYTHONUNBUFFERED = '1'
if ($fromFilt) { $env:MAIL_FROM_FILTER = $fromFilt }
Push-Location $receiver
& $pyMail receiver.py --once *> "$logs\mail-install-smoke.log"
$smokeExit = $LASTEXITCODE
Pop-Location
Get-Content "$logs\mail-install-smoke.log" | ForEach-Object { Write-Host "   $_" }
if ($smokeExit -ne 0) { Fail "could not log in to $user@$host_ or read $folder - see mail-install-smoke.log (Gmail needs 2-Step Verification + an App password)" }

# ---- 4. start ------------------------------------------------------------------------------------
Step 'start'
Start-Service $svcMail
Start-Sleep -Seconds 5
if ((Get-Service $svcMail).Status -ne 'Running') { Fail "$svcMail did not stay running - see $logs\mail-receiver.log" }
if ((Get-Service $svcImport).Status -ne 'Running') { Start-Service $svcImport -EA SilentlyContinue }
Get-Service $svcMail, $svcImport | Format-Table Name, Status -AutoSize

Write-Host 'Done.' -ForegroundColor Green
Write-Host 'Camera settings (MMSCONFIG -> SMTP / Email):'
Write-Host '   Send mode  : instant / each photo, picture only'
if ($host_ -eq 'imap.gmail.com') {
    Write-Host '   SMTP server: smtp.gmail.com'
    Write-Host '   SMTP port  : 465 (SSL on)  - if the camera has no SSL option try 587 (TLS)'
} else {
    Write-Host "   SMTP server: the SMTP host that belongs to $host_"
    Write-Host '   SMTP port  : 465 (SSL) or 587 (TLS)'
}
Write-Host "   Account    : $user"
Write-Host "   Password   : (MAIL_PASSWORD from $Config)"
Write-Host "   Send to    : $user"
Write-Host ''
Write-Host "Watch $logs\mail-receiver.log and $logs\ftp-importer.log; the photo appears under the camera in the app."

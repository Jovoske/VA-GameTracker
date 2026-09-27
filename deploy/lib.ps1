# Shared helpers for the deploy scripts (update.ps1, backup.ps1, restore-check.ps1,
# register-tasks.ps1). Dot-source it:   . "$PSScriptRoot\lib.ps1"
#
# Written for Windows PowerShell 5.1, which is what Db01 has: no ?? or ?., no
# ternaries, no && / ||, and Set-Content -Encoding UTF8 writes a byte-order mark,
# hence Write-JsonFile.

# A value from backend\.env, read the way python-dotenv (and so the app) reads it:
# `export ` and surrounding quotes are not part of it, nor is a trailing " # note"
# after an unquoted value. $null when the key is not there.
function Read-EnvValue([string]$File, [string]$Key) {
    if (-not (Test-Path $File)) { return $null }
    foreach ($raw in Get-Content -Path $File -Encoding UTF8) {
        $line = $raw.Trim()
        if ($line.StartsWith('export ')) { $line = $line.Substring(7).TrimStart() }
        if (-not $line -or $line.StartsWith('#') -or -not $line.Contains('=')) { continue }
        $parts = $line.Split('=', 2)
        if ($parts[0].Trim() -ne $Key) { continue }
        $value = $parts[1].Trim()
        if ($value.Length -ge 2 -and ($value[0] -eq '"' -or $value[0] -eq "'")) {
            $end = $value.IndexOf($value[0], 1)
            if ($end -gt 0) { return $value.Substring(1, $end - 1) }
        }
        $hash = $value.IndexOf(' #')
        if ($hash -ge 0) { $value = $value.Substring(0, $hash).TrimEnd() }
        return $value
    }
    return $null
}

# Where the app keeps its locks and status files: beside the models folder, as
# app.jobs.data_dir() has it (MODELS_ROOT's parent), else <Root>\data.
function Get-DataDir([string]$EnvFile, [string]$Root) {
    $models = Read-EnvValue $EnvFile 'MODELS_ROOT'
    if ($models) { return (Split-Path -Parent $models) }
    return (Join-Path $Root 'data')
}

# DATABASE_URL split into what pg_dump and psql take; $null when it doesn't parse.
function Get-DbTarget([string]$EnvFile) {
    $url = Read-EnvValue $EnvFile 'DATABASE_URL'
    if (-not $url) { return $null }
    $m = [regex]::Match($url, '://(?<u>[^:@/]+)(:(?<p>[^@]*))?@(?<h>[^:/?]+)(:(?<port>\d+))?/(?<db>[^?]+)')
    if (-not $m.Success) { return $null }
    $port = $m.Groups['port'].Value
    if (-not $port) { $port = '5432' }
    return @{
        User = $m.Groups['u'].Value
        Password = [uri]::UnescapeDataString($m.Groups['p'].Value)
        Host = $m.Groups['h'].Value
        Port = $port
        Db = $m.Groups['db'].Value
    }
}

# A PostgreSQL client tool (pg_dump, pg_restore, psql). Looked for, not assumed: the
# installed major version moves. <NAME>=<full path> in .env (PGDUMP, PGRESTORE, PSQL)
# wins, for an install somewhere unusual; then the PATH, the EDB zip where it
# unpacks on Db01, and the newest C:\Program Files\PostgreSQL\<major>.
function Find-PgTool([string]$Name, [string]$EnvFile, [string]$Root) {
    $key = $Name.ToUpper().Replace('_', '')
    $exe = "$Name.exe"
    $override = Read-EnvValue $EnvFile $key
    $onPath = Get-Command $exe -EA SilentlyContinue
    if (-not $onPath) { $onPath = Get-Command $Name -EA SilentlyContinue }
    $candidates = @($override)
    if ($onPath) { $candidates += $onPath.Source }
    $candidates += @((Join-Path $Root "pg\pgsql\bin\$exe"), (Join-Path $Root "tools\pgsql\bin\$exe"))
    foreach ($cand in $candidates) {
        if ($cand -and (Test-Path $cand)) { return $cand }
    }
    return Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\$exe" -EA SilentlyContinue |
        Sort-Object { [int]($_.Directory.Parent.Name) } -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}

# Now, in UTC, as the app reads it (ISO 8601 with a Z).
function Get-UtcStamp { return (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }

# A path as .NET needs it: .NET resolves a relative path against the process's folder,
# not PowerShell's current location, and takes \ literally off Windows.
function Get-FullPath([string]$Path) {
    return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
}

# Text with no byte-order mark (Set-Content -Encoding UTF8 writes one in PowerShell
# 5.1), written beside and then moved over the old file, so a reader never sees half.
function Write-TextFile([string]$Path, [string]$Text) {
    $full = Get-FullPath $Path
    $dir = Split-Path -Parent $full
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    [System.IO.File]::WriteAllText("$full.new", $Text, (New-Object System.Text.UTF8Encoding $false))
    Move-Item -Force -Path "$full.new" -Destination $full
}

# JSON the app reads (app.ops).
function Write-JsonFile([string]$Path, $Value) {
    Write-TextFile $Path ($Value | ConvertTo-Json -Depth 6)
}

function Read-JsonFile([string]$Path) {
    if (-not (Test-Path $Path)) { return $null }
    try { return (Get-Content -Raw -Path $Path -Encoding UTF8 | ConvertFrom-Json) } catch { return $null }
}

# Free space, in GB, on the disk that holds $Path; $null when it can't be told.
function Get-FreeGB([string]$Path) {
    try {
        $full = Get-FullPath $Path
        $drive = New-Object System.IO.DriveInfo ([System.IO.Path]::GetPathRoot($full))
        return [math]::Round($drive.AvailableFreeSpace / 1GB, 1)
    } catch {
        return $null
    }
}

# A log that has grown past $MaxMB becomes <name>.1 (the one before is dropped).
function Limit-Log([string]$Path, [int]$MaxMB = 5) {
    if ((Test-Path $Path) -and ((Get-Item $Path).Length -gt $MaxMB * 1MB)) {
        Move-Item -Force -Path $Path -Destination "$Path.1" -EA SilentlyContinue
    }
}

# Shared by the other scripts in this folder (dot-sourced). Windows PowerShell 5.1.
#
# Docker runs one of two ways, and these helpers hide which:
#   - Docker Desktop: `docker` on the Windows PATH, project anywhere on C:.
#   - Docker Engine inside WSL: the project lives in WSL, seen from Windows as
#     \\wsl.localhost\<distro>\home\..., and compose runs through wsl.exe.

$ErrorActionPreference = 'Stop'

function Get-RepoRoot {
    [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))   # plain path, also for \\wsl.localhost
}

# \\wsl.localhost\Ubuntu-24.04\home\me\proj -> distro + /home/me/proj, else $null.
function Get-WslTarget([string]$Path) {
    if ($Path -match '^(?:Microsoft\.PowerShell\.Core\\FileSystem::)?\\\\wsl(?:\.localhost|\$)\\([^\\]+)\\(.*)$') {
        return @{ Distro = $Matches[1]; Path = '/' + ($Matches[2] -replace '\\', '/') }
    }
    return $null
}

# G:\My Drive\PhoneUsage -> /mnt/g/My Drive/PhoneUsage (for compose run in WSL).
function ConvertTo-WslPath([string]$WinPath) {
    if ($WinPath -match '^([A-Za-z]):\\(.*)$') {
        return '/mnt/' + $Matches[1].ToLower() + '/' + ($Matches[2] -replace '\\', '/')
    }
    return $WinPath -replace '\\', '/'
}

function Test-DockerDesktop {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { return $false }
    & docker info *> $null
    return $LASTEXITCODE -eq 0
}

# Docker Desktop normally starts at sign-in; if it isn't running yet, start it
# and wait for the engine (up to ~2 minutes).
function Start-DockerDesktop {
    if (Test-DockerDesktop) { return $true }
    $exe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (-not (Test-Path $exe)) { return $false }
    Start-Process $exe | Out-Null
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 2
        if (Test-DockerDesktop) { return $true }
    }
    return $false
}

# Run `docker compose <args>` for this project; returns the exit code.
function Invoke-Compose([string[]]$ComposeArgs) {
    $repo = Get-RepoRoot
    $wsl = Get-WslTarget $repo
    if ($wsl) {
        $joined = ($ComposeArgs | ForEach-Object { "'" + ($_ -replace "'", "'\''") + "'" }) -join ' '
        # Out-Host: a native command's output would otherwise become part of
        # this function's return value instead of just the exit code.
        & wsl.exe -d $wsl.Distro -- bash -lc "cd '$($wsl.Path)' && docker compose $joined" | Out-Host
        return $LASTEXITCODE
    }
    if (-not (Start-DockerDesktop)) {
        throw 'Docker Desktop is not running and could not be started. Install it from https://www.docker.com/products/docker-desktop/ and start it once.'
    }
    Push-Location $repo
    try { & docker compose @ComposeArgs | Out-Host; return $LASTEXITCODE }
    finally { Pop-Location }
}

# "My Drive" as Google Drive for desktop shows it: a drive letter (G:\My Drive,
# the default) or a folder in the user profile (mirror mode).
function Find-MyDrive {
    $candidates = @()
    foreach ($d in Get-PSDrive -PSProvider FileSystem) {
        if ($d.Root) { $candidates += (Join-Path $d.Root 'My Drive') }
    }
    $candidates += (Join-Path $env:USERPROFILE 'My Drive')
    $candidates += (Join-Path $env:USERPROFILE 'Google Drive\My Drive')
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath (Join-Path $c 'PhoneUsage\phone')) { return $c }
    }
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) { return $c }
    }
    return $null
}

function Read-DotEnv {
    $file = Join-Path (Get-RepoRoot) '.env'
    $vals = @{}
    if (Test-Path -LiteralPath $file) {
        foreach ($line in Get-Content -LiteralPath $file) {
            if ($line -match '^\s*([A-Z_]+)\s*=\s*"?(.*?)"?\s*$') { $vals[$Matches[1]] = $Matches[2] }
        }
    }
    return $vals
}

function Get-DashboardUrl {
    $port = (Read-DotEnv)['DASHBOARD_PORT']
    if (-not $port) { $port = '5000' }
    return "http://127.0.0.1:$port/"
}

function Wait-Dashboard([int]$Seconds = 60) {
    $url = Get-DashboardUrl
    for ($i = 0; $i -lt $Seconds; $i++) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { return $true }
        } catch { }
        Start-Sleep -Seconds 1
    }
    return $false
}

# A message box, for scripts started without a console window.
function Show-Message([string]$Text, [string]$Title = 'Phone Usage') {
    (New-Object -ComObject WScript.Shell).Popup($Text, 0, $Title, 0x40) | Out-Null
}

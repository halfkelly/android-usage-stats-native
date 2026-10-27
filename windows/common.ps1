# Shared by the other scripts in this folder (dot-sourced). Windows PowerShell 5.1.
#
# Two ways the project runs, chosen by where it lives:
#   - Native (the usual): an ordinary Windows folder. setup.ps1 puts Python in
#     <project>\python (the embeddable package: no installer, no admin, nothing
#     system-wide), and everything runs as `python -m wellbeing ...`.
#   - WSL + Docker (the maintainer's PC): the project lives in WSL, seen from
#     Windows as \\wsl.localhost\<distro>\home\..., and runs in Docker there.

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

function Get-PythonDir { Join-Path (Get-RepoRoot) 'python' }
function Get-Python { Join-Path (Get-PythonDir) 'python.exe' }
function Get-Pythonw { Join-Path (Get-PythonDir) 'pythonw.exe' }

# Run `python -m wellbeing <args>` with the project's own Python; returns the exit code.
function Invoke-Wellbeing([string[]]$WellbeingArgs) {
    $py = Get-Python
    if (-not (Test-Path -LiteralPath $py)) { throw "No Python in $(Get-PythonDir): run 'Set up (Windows).bat' first." }
    & $py -m wellbeing @WellbeingArgs | Out-Host
    return $LASTEXITCODE
}

# Run `docker compose <args>` in WSL for a project that lives there; returns the exit code.
function Invoke-Compose([string[]]$ComposeArgs) {
    $wsl = Get-WslTarget (Get-RepoRoot)
    if (-not $wsl) { throw 'Docker is only used for a project inside WSL.' }
    $joined = ($ComposeArgs | ForEach-Object { "'" + ($_ -replace "'", "'\''") + "'" }) -join ' '
    # Out-Host: a native command's output would otherwise become part of this
    # function's return value instead of just the exit code.
    & wsl.exe -d $wsl.Distro -- bash -lc "cd '$($wsl.Path)' && docker compose $joined" | Out-Host
    return $LASTEXITCODE
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

function Write-DotEnv([hashtable]$Values) {
    $lines = $Values.Keys | Sort-Object | ForEach-Object { "$_=`"$($Values[$_])`"" }
    [IO.File]::WriteAllText((Join-Path (Get-RepoRoot) '.env'), (($lines -join "`n") + "`n"),
                            (New-Object Text.UTF8Encoding $false))
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

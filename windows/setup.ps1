# One-time setup on a Windows PC. Run "Set up (Windows).bat" in the project
# folder; running it again is safe (it repairs and updates).
#
# Before this: Google Drive for desktop signed in to the same Google account as
# the phone, and the phone app connected to Drive with one upload done (Usage
# Dump -> Run now), because the phone has to create My Drive\PhoneUsage itself.
#
# Nothing else to install: setup puts Python in <project>\python (no admin,
# nothing system-wide). A project inside WSL uses Docker there instead.
#
# The parameters are for testing a second setup beside a real one.

param(
    [string]$DrivePath,                          # 'X:\My Drive' if it isn't found
    [string]$UsagePath,                          # the PhoneUsage folder itself
    [string]$TaskName = 'PhoneUsageAutosync',
    [string]$ShortcutName = 'Phone Usage Dashboard',
    [switch]$NoBrowser
)
. "$PSScriptRoot\common.ps1"

$PythonVersion = '3.12.10'   # the last 3.12 with Windows packages

function Step($text) { Write-Host ''; Write-Host "== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host ''; Write-Host $text -ForegroundColor Red; exit 1 }

$repo = Get-RepoRoot
$wsl = Get-WslTarget $repo
Write-Host "Phone Usage dashboard - setup"
Write-Host "Project: $repo"

Step 'Google Drive'
if (-not $UsagePath) {
    if (-not $DrivePath) { $DrivePath = Find-MyDrive }
    if (-not $DrivePath) {
        Fail ("Couldn't find Google Drive (no 'My Drive' folder on any drive letter or in your user folder).`n" +
              "  Install Google Drive for desktop, sign in with the phone's Google account, then run this again.`n" +
              "  If it's somewhere unusual: setup.ps1 -DrivePath 'X:\My Drive'")
    }
    Write-Host "  My Drive: $DrivePath"
    $UsagePath = Join-Path $DrivePath 'PhoneUsage'
}
if (-not (Test-Path -LiteralPath (Join-Path $UsagePath 'phone\device.json'))) {
    # The phone app must create PhoneUsage: its Drive permission only covers
    # folders it made, so one created here would be invisible to it.
    Fail ("No upload from the phone yet in $UsagePath\phone.`n" +
          "  On the phone: install the app, Connect Google Drive, then tap Run now.`n" +
          "  Wait a minute for Google Drive to bring it to this PC, then run this again.`n" +
          "  (Don't create the PhoneUsage folder yourself: the phone app has to.)")
}
Write-Host "  Phone uploads found in $UsagePath\phone"
Write-Host '  Tip: in Google Drive, right-click PhoneUsage > Available offline.'

if (-not $wsl) {
    # The database is written all day: in a folder that syncs to the cloud it
    # would be uploaded mid-write, with locks and conflict copies to follow.
    # Windows often keeps Documents and the Desktop in OneDrive.
    $synced = @($env:OneDrive, $env:OneDriveConsumer, $env:OneDriveCommercial, (Split-Path $UsagePath -Parent)) |
        Where-Object { $_ -and $repo.StartsWith($_.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) }
    if ($synced) {
        Fail ("This folder is inside $(@($synced)[0]), which syncs to the cloud.`n" +
              "  Move the whole folder to $env:USERPROFILE (your user folder) and run Set up (Windows).bat from there.")
    }
    # A ZIP from the internet marks every file in it, and Windows would then
    # ask before running each .bat. Running setup is the one time it's needed.
    Get-ChildItem -LiteralPath $repo, (Join-Path $repo 'windows') -File | Unblock-File -ErrorAction SilentlyContinue
}

Step 'Settings (.env)'
$settings_ = Read-DotEnv
$settings_['PHONE_USAGE_DRIVE'] = if ($wsl) { ConvertTo-WslPath $UsagePath } else { $UsagePath }
Write-DotEnv $settings_
Write-Host "  PHONE_USAGE_DRIVE=$($settings_['PHONE_USAGE_DRIVE'])"
New-Item -ItemType Directory -Force -Path (Join-Path $repo 'data') | Out-Null

if ($wsl) {
    # ---- the maintainer's PC: Docker inside WSL ---------------------------
    Step "Docker in WSL ($($wsl.Distro))"
    & wsl.exe -d $wsl.Distro -- bash -lc 'docker info >/dev/null 2>&1'
    if ($LASTEXITCODE -ne 0) { Fail "Docker isn't running inside WSL ($($wsl.Distro))." }
    if ((Invoke-Compose @('build', 'dashboard')) -ne 0) { Fail 'The build failed; see above.' }
    if ((Invoke-Compose @('up', '-d', 'dashboard')) -ne 0) { Fail "The dashboard didn't start; see above." }
    Step 'First sync'
    if ((Invoke-Compose @('run', '--rm', 'sync', 'python', '-m', 'wellbeing', 'ingest-phone')) -ne 0) {
        Fail 'The first sync failed; see above.'
    }
    $taskExe = 'powershell.exe'
    $taskArgs = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'sync.ps1')`""
    $lnkExe = 'powershell.exe'
    $lnkArgs = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'open-dashboard.ps1')`""
} else {
    # ---- everyone else: Python in the project folder -----------------------
    Step "Python $PythonVersion (in $(Get-PythonDir))"
    $py = Get-Python
    if (-not (Test-Path -LiteralPath $py)) {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $ProgressPreference = 'SilentlyContinue'          # Invoke-WebRequest is slow with the bar
        $dir = Get-PythonDir
        $zip = Join-Path $env:TEMP "python-$PythonVersion-embed-amd64.zip"
        Write-Host '  Downloading Python (11 MB)...'
        Invoke-WebRequest "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" -OutFile $zip -UseBasicParsing
        Expand-Archive -LiteralPath $zip -DestinationPath $dir -Force
        Remove-Item -LiteralPath $zip
        # The embeddable package ignores the current folder and site-packages
        # unless its ._pth says otherwise: allow both, plus the project itself.
        $pth = Get-ChildItem -LiteralPath $dir -Filter 'python*._pth' | Select-Object -First 1
        $tag = $pth.BaseName
        [IO.File]::WriteAllText($pth.FullName, "$tag.zip`r`n.`r`n..`r`nimport site`r`n")
        Write-Host '  Installing pip...'
        $getpip = Join-Path $dir 'get-pip.py'
        Invoke-WebRequest 'https://bootstrap.pypa.io/get-pip.py' -OutFile $getpip -UseBasicParsing
        & $py $getpip --no-warn-script-location | Out-Host
        if ($LASTEXITCODE -ne 0) { Fail 'Installing pip failed; see above.' }
        Remove-Item -LiteralPath $getpip
    } else {
        Write-Host '  Already there'
    }
    Write-Host '  Installing the app''s libraries...'
    & $py -m pip install --quiet --disable-pip-version-check --no-warn-script-location -r (Join-Path $repo 'requirements.txt') | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail 'Installing the libraries failed; see above.' }

    Step 'First sync'
    if ((Invoke-Wellbeing @('ingest-phone')) -ne 0) {
        Fail ("The first sync failed; see above.`n" +
              "  If it says the time zone doesn't match, set Windows to the phone's time zone and run this again.")
    }
    $taskExe = Get-Pythonw
    $taskArgs = '-m wellbeing autosync'
    $lnkExe = Get-Pythonw
    $lnkArgs = '-m wellbeing open'
}

Step 'Scheduled sync (03:00, 09:00, 15:00, 21:00)'
$action = New-ScheduledTaskAction -Execute $taskExe -Argument $taskArgs -WorkingDirectory $repo
$triggers = '03:00', '09:00', '15:00', '21:00' | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
$taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $taskSettings `
    -Principal $principal -Description 'Reads the phone usage uploads from Google Drive into the dashboard.' `
    -Force | Out-Null
Write-Host "  Task '$TaskName' registered (runs when you're signed in; catches up after a shutdown)"

Step 'Desktop shortcut'
$desktop = [Environment]::GetFolderPath('Desktop')
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop "$ShortcutName.lnk"))
$lnk.TargetPath = $lnkExe
$lnk.Arguments = $lnkArgs
$lnk.WorkingDirectory = $repo
$lnk.IconLocation = "$env:SystemRoot\System32\imageres.dll,170"
$lnk.Description = 'Open the phone usage dashboard'
$lnk.Save()
$oldBat = Join-Path $desktop "$ShortcutName.bat"   # an earlier launcher, if any
if (Test-Path -LiteralPath $oldBat) { Remove-Item -LiteralPath $oldBat }
Write-Host "  '$ShortcutName' on the Desktop"

Step 'Done'
if ($wsl) {
    $ok = Wait-Dashboard 60
} else {
    $ok = (Invoke-Wellbeing @('open', '--no-browser')) -eq 0
}
if ($ok) {
    Write-Host "  Dashboard at $(Get-DashboardUrl)" -ForegroundColor Green
    if (-not $NoBrowser) { Start-Process (Get-DashboardUrl) }
} else {
    Write-Host "  Set up, but the dashboard didn't start yet. Try the Desktop shortcut in a minute." -ForegroundColor Yellow
}

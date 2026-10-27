# One-time setup on a Windows PC. Run "Set up (Windows).bat" in the project
# folder; running it again is safe (it repairs and updates).
#
# Before this: Docker Desktop installed and started once; Google Drive for
# desktop signed in to the same Google account as the phone; and the phone app
# connected to Drive with one upload done (Usage Dump -> Run now), because the
# phone has to create My Drive\PhoneUsage itself.

param([string]$DrivePath)
. "$PSScriptRoot\common.ps1"

function Step($text) { Write-Host ''; Write-Host "== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host ''; Write-Host $text -ForegroundColor Red; exit 1 }

$repo = Get-RepoRoot
$wsl = Get-WslTarget $repo
Write-Host "Phone Usage dashboard - setup"
Write-Host "Project: $repo"

Step 'Docker'
if ($wsl) {
    & wsl.exe -d $wsl.Distro -- bash -lc 'docker info >/dev/null 2>&1'
    if ($LASTEXITCODE -ne 0) { Fail "Docker isn't running inside WSL ($($wsl.Distro))." }
    Write-Host "  Docker in WSL ($($wsl.Distro))"
} elseif (Start-DockerDesktop) {
    Write-Host '  Docker Desktop is running'
} else {
    Fail ("Docker Desktop isn't installed or won't start.`n" +
          "  Install it from https://www.docker.com/products/docker-desktop/ , start it once, then run this again.")
}

Step 'Google Drive'
if (-not $DrivePath) { $DrivePath = Find-MyDrive }
if (-not $DrivePath) {
    Fail ("Couldn't find Google Drive (no 'My Drive' folder on any drive letter or in your user folder).`n" +
          "  Install Google Drive for desktop, sign in with the phone's Google account, then run this again.`n" +
          "  If it's somewhere unusual: setup.ps1 -DrivePath 'X:\My Drive'")
}
$usage = Join-Path $DrivePath 'PhoneUsage'
Write-Host "  My Drive: $DrivePath"
if (-not (Test-Path -LiteralPath (Join-Path $usage 'phone\device.json'))) {
    # The phone app must create PhoneUsage: its Drive permission only covers
    # folders it made, so one created here would be invisible to it.
    Fail ("No upload from the phone yet in $usage\phone.`n" +
          "  On the phone: install the app, Connect Google Drive, then tap Run now.`n" +
          "  Wait a minute for Google Drive to bring it to this PC, then run this again.`n" +
          "  (Don't create the PhoneUsage folder yourself: the phone app has to.)")
}
Write-Host "  Phone uploads found in $usage\phone"
Write-Host '  Tip: in Google Drive, right-click PhoneUsage > Available offline.'

Step 'Settings (.env)'
$driveForCompose = if ($wsl) { ConvertTo-WslPath $usage } else { $usage -replace '\\', '/' }
$env_ = Read-DotEnv
$env_['PHONE_USAGE_DRIVE'] = $driveForCompose
$lines = $env_.Keys | Sort-Object | ForEach-Object { "$_=`"$($env_[$_])`"" }
[IO.File]::WriteAllText((Join-Path $repo '.env'), (($lines -join "`n") + "`n"), (New-Object Text.UTF8Encoding $false))
Write-Host "  PHONE_USAGE_DRIVE=$driveForCompose"

Step 'Building (a few minutes the first time)'
if ((Invoke-Compose @('build', 'dashboard')) -ne 0) { Fail 'The build failed; see above.' }

Step 'First sync'
if ((Invoke-Compose @('up', '-d', 'dashboard')) -ne 0) { Fail "The dashboard didn't start; see above." }
if ((Invoke-Compose @('run', '--rm', 'sync', 'python', '-m', 'wellbeing', 'ingest-phone')) -ne 0) {
    Fail 'The first sync failed; see above.'
}

Step 'Scheduled sync (03:00, 09:00, 15:00, 21:00)'
$taskName = 'PhoneUsageAutosync'
$syncScript = Join-Path $PSScriptRoot 'sync.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$syncScript`""
$triggers = '03:00', '09:00', '15:00', '21:00' | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings `
    -Principal $principal -Description 'Reads the phone usage uploads from Google Drive into the dashboard.' `
    -Force | Out-Null
Write-Host "  Task '$taskName' registered (runs when you're signed in; catches up after a shutdown)"

Step 'Desktop shortcut'
$desktop = [Environment]::GetFolderPath('Desktop')
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop 'Phone Usage Dashboard.lnk'))
$lnk.TargetPath = 'powershell.exe'
$lnk.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'open-dashboard.ps1')`""
$lnk.IconLocation = "$env:SystemRoot\System32\imageres.dll,170"
$lnk.Description = 'Open the phone usage dashboard'
$lnk.Save()
$oldBat = Join-Path $desktop 'Phone Usage Dashboard.bat'   # the earlier launcher, if any
if (Test-Path -LiteralPath $oldBat) { Remove-Item -LiteralPath $oldBat }
Write-Host "  'Phone Usage Dashboard' on the Desktop"

Step 'Done'
if (Wait-Dashboard 60) {
    Write-Host "  Dashboard at $(Get-DashboardUrl)" -ForegroundColor Green
    Start-Process (Get-DashboardUrl)
} else {
    Write-Host "  Set up, but the dashboard didn't answer yet. Try the Desktop shortcut in a minute." -ForegroundColor Yellow
}

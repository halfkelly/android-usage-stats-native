# Undo setup: the scheduled task, the Desktop shortcut, a running dashboard,
# and the project's Python (or the containers). Keeps data\ -- the database --
# and everything in Google Drive.
param([string]$TaskName = 'PhoneUsageAutosync', [string]$ShortcutName = 'Phone Usage Dashboard')
. "$PSScriptRoot\common.ps1"
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) "$ShortcutName.lnk"
if (Test-Path -LiteralPath $lnk) { Remove-Item -LiteralPath $lnk }
if (Get-WslTarget (Get-RepoRoot)) {
    Invoke-Compose @('down') | Out-Null
} elseif (Test-Path -LiteralPath (Get-Python)) {
    Invoke-Wellbeing @('stop') | Out-Null
    Start-Sleep -Seconds 1
    Remove-Item -LiteralPath (Get-PythonDir) -Recurse -Force
}
Write-Host 'Removed the scheduled task, the Desktop shortcut and the app''s Python (or containers).'
Write-Host 'Kept: data\ in the project folder, and My Drive\PhoneUsage.'

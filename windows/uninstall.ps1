# Undo setup: remove the scheduled task, the Desktop shortcut and the
# containers. Keeps data\ (the database) and everything in Google Drive.
. "$PSScriptRoot\common.ps1"
Unregister-ScheduledTask -TaskName 'PhoneUsageAutosync' -Confirm:$false -ErrorAction SilentlyContinue
$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Phone Usage Dashboard.lnk'
if (Test-Path -LiteralPath $lnk) { Remove-Item -LiteralPath $lnk }
Invoke-Compose @('down') | Out-Null
Write-Host 'Removed the scheduled task, the Desktop shortcut and the containers.'
Write-Host 'Kept: data\ in the project folder and My Drive\PhoneUsage.'

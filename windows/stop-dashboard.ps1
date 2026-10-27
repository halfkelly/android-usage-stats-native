# Stop the dashboard container. The phone keeps collecting; the scheduled sync
# and the Desktop shortcut start it again.
. "$PSScriptRoot\common.ps1"
try {
    if ((Invoke-Compose @('stop', 'dashboard')) -ne 0) { throw "docker compose couldn't stop it." }
    Show-Message 'Dashboard stopped. The phone keeps collecting.'
} catch {
    Show-Message "Couldn't stop the dashboard.`n`n$($_.Exception.Message)"
}

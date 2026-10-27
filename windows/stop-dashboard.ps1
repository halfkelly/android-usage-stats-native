# Stop the dashboard. The phone keeps collecting; the Desktop shortcut and the
# scheduled sync start it again.
. "$PSScriptRoot\common.ps1"
try {
    if (Get-WslTarget (Get-RepoRoot)) {
        if ((Invoke-Compose @('stop', 'dashboard')) -ne 0) { throw "docker compose couldn't stop it." }
        Show-Message 'Dashboard stopped. The phone keeps collecting.'
    } else {
        Invoke-Wellbeing @('stop') | Out-Null
    }
} catch {
    Show-Message "Couldn't stop the dashboard.`n`n$($_.Exception.Message)"
}

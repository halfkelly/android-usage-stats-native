# The Desktop shortcut: make sure the dashboard container runs, then open it.
. "$PSScriptRoot\common.ps1"
try {
    if ((Invoke-Compose @('up', '-d', 'dashboard')) -ne 0) { throw "docker compose couldn't start the dashboard." }
    if (-not (Wait-Dashboard 60)) { throw "The dashboard didn't answer at $(Get-DashboardUrl)." }
    Start-Process (Get-DashboardUrl)
} catch {
    Show-Message ("Couldn't open the dashboard.`n`n$($_.Exception.Message)`n`n" +
                  "Is Docker running? If this keeps happening, run 'Set up (Windows).bat' again.")
}

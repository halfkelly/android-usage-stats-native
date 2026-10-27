# Open the dashboard, starting it first if it isn't running. (In the native
# setup the Desktop shortcut runs `pythonw -m wellbeing open` directly.)
. "$PSScriptRoot\common.ps1"
try {
    if (Get-WslTarget (Get-RepoRoot)) {
        if ((Invoke-Compose @('up', '-d', 'dashboard')) -ne 0) { throw "docker compose couldn't start the dashboard." }
        if (-not (Wait-Dashboard 60)) { throw "The dashboard didn't answer at $(Get-DashboardUrl)." }
        Start-Process (Get-DashboardUrl)
    } else {
        if ((Invoke-Wellbeing @('open')) -ne 0) { throw 'See the message above.' }
    }
} catch {
    Show-Message ("Couldn't open the dashboard.`n`n$($_.Exception.Message)`n`n" +
                  "If this keeps happening, run 'Set up (Windows).bat' again.")
}

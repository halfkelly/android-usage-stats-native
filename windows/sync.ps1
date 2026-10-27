# The scheduled sync in the WSL + Docker setup: start the dashboard if needed,
# then read the phone's uploads once. Runs hidden; details go to
# data\autosync.log. (The native setup's task runs `pythonw -m wellbeing
# autosync` directly.)
. "$PSScriptRoot\common.ps1"
$log = Join-Path (Get-RepoRoot) 'data\windows-task.log'
function Note($text) { Add-Content -LiteralPath $log -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $text" }
try {
    New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
    if (Get-WslTarget (Get-RepoRoot)) {
        if ((Invoke-Compose @('up', '-d', 'dashboard')) -ne 0) { Note 'dashboard did not start' }
        Note "sync exit $(Invoke-Compose @('run', '--rm', 'sync'))"
    } else {
        Note "sync exit $(Invoke-Wellbeing @('autosync'))"
    }
} catch {
    Note "failed: $($_.Exception.Message)"
}

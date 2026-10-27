# The scheduled task: start the dashboard if needed, then read the phone's
# uploads once. Runs hidden; the details go to data\autosync.log.
. "$PSScriptRoot\common.ps1"
$log = Join-Path (Get-RepoRoot) 'data\windows-task.log'
function Note($text) { Add-Content -LiteralPath $log -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $text" }
try {
    New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
    if ((Invoke-Compose @('up', '-d', 'dashboard')) -ne 0) { Note 'dashboard did not start' }
    $code = Invoke-Compose @('run', '--rm', 'sync')
    Note "sync exit $code"
} catch {
    Note "failed: $($_.Exception.Message)"
}

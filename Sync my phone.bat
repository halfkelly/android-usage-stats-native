@echo off
REM Double-click to sync the phone and update the shared archive.
REM Runs the same script the Mac uses, inside WSL.
setlocal
set DISTRO=Ubuntu-24.04
wsl.exe -d %DISTRO% -- bash -lc "cd ~/adb_usage_stats && ./sync.sh"
echo.
pause

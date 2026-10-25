@echo off
REM Double-click to start the dashboard and open it in your browser.
setlocal
set DISTRO=Ubuntu-24.04
start "" http://localhost:5000
wsl.exe -d %DISTRO% -- bash -lc "cd ~/android-usage-stats-native && ./dashboard.sh"
echo.
pause

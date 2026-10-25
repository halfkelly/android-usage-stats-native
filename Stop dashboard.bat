@echo off
REM Double-click to stop the dashboard container. The phone keeps collecting,
REM and the scheduled sync starts it again; so does Phone Usage Dashboard.
setlocal
set DISTRO=Ubuntu-24.04
wsl.exe -d %DISTRO% -- bash -lc "cd ~/android-usage-stats-native && docker compose stop dashboard && echo '  Dashboard stopped.'"
echo.
pause

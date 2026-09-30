@echo off
REM Double-click to stop the dashboard.
setlocal
set DISTRO=Ubuntu-24.04
wsl.exe -d %DISTRO% -- bash -lc "pkill -f 'wellbeing serve' && echo '  Dashboard stopped.' || echo '  It was not running.'"
echo.
pause

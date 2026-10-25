@echo off
REM Double-click to open the dashboard: reads the latest from Google Drive,
REM starts the server inside WSL, then opens the page once it is ready.
setlocal
set DISTRO=Ubuntu-24.04
echo   Reading the latest phone data from Google Drive...
wsl.exe -d %DISTRO% -- bash -lc "cd ~/android-usage-stats-native && ./dashboard.sh"
if errorlevel 1 (
  echo.
  echo   Something went wrong -- see above.
  pause
)

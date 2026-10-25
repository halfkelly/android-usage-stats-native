@echo off
REM Double-click to bring in what the phone uploaded to Google Drive
REM (My Drive\PhoneUsage\phone) and update the archive. No cable needed:
REM the phone collects and uploads on its own every 6 hours.
setlocal
set DISTRO=Ubuntu-24.04
wsl.exe -d %DISTRO% -- bash -lc "cd ~/android-usage-stats-native && docker compose run --rm sync python -m wellbeing ingest-phone"
echo.
pause

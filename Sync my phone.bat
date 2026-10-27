@echo off
REM Read the phone's latest uploads from Google Drive now.
if exist "%~dp0python\python.exe" ("%~dp0python\python.exe" -m wellbeing ingest-phone) else (powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\sync.ps1" & echo   Details: data\autosync.log)
echo.
pause

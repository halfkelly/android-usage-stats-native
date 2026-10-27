@echo off
REM Read the phone's latest uploads from Google Drive now.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\sync.ps1"
echo   Done: see data\autosync.log for details.
pause

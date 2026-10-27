@echo off
REM One-time setup: Python for the app (inside this folder), Google Drive,
REM the scheduled sync and a Desktop shortcut. Safe to run again.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\setup.ps1"
echo.
pause

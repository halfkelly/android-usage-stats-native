@echo off
REM One-time setup: Docker, Google Drive, the scheduled sync and a Desktop shortcut.
REM Safe to run again.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\setup.ps1"
echo.
pause

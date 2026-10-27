@echo off
REM Stop the dashboard. The phone keeps collecting.
if exist "%~dp0python\python.exe" ("%~dp0python\python.exe" -m wellbeing stop) else (powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\stop-dashboard.ps1")
pause

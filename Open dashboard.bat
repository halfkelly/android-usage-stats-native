@echo off
REM Start the dashboard if needed and open it in the browser.
if exist "%~dp0python\pythonw.exe" (start "" "%~dp0python\pythonw.exe" -m wellbeing open) else (powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\open-dashboard.ps1")

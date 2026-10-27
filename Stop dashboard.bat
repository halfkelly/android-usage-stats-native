@echo off
REM Stop the dashboard. The phone keeps collecting.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\stop-dashboard.ps1"

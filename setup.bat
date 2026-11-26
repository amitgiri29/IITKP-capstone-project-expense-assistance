@echo off
rem Windows: double-click to set up and start the app. Options are passed through, e.g. setup.bat -NoStart
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
if errorlevel 1 pause

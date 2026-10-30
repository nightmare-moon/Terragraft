@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0RUN.ps1"
if errorlevel 1 echo STARTUP FAILED. See the error above.
pause

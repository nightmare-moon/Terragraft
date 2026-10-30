@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL.ps1"
if errorlevel 1 echo INSTALL FAILED. See the error above.
pause

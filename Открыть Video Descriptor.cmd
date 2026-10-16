@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-app\Start-App.ps1"
if errorlevel 1 pause

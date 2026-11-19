@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_demo.ps1"
set "demoExitCode=%ERRORLEVEL%"
if not "%demoExitCode%"=="0" pause
exit /b %demoExitCode%

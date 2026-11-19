@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
pushd "%~dp0"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_demo.ps1" -OneClick %*
set "demoExitCode=%ERRORLEVEL%"
popd
exit /b %demoExitCode%

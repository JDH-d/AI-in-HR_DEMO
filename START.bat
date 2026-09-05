@echo off
setlocal DisableDelayedExpansion
title PeopleFlow AI
pushd "%~dp0"
if errorlevel 1 (
  echo Cannot open the PeopleFlow project folder. Extract the ZIP first.
  echo Press any key to close this window.
  pause >nul
  exit /b 1
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launcher.ps1"
set "launcher_exit=%errorlevel%"
popd
if not "%launcher_exit%"=="0" (
  echo.
  echo PeopleFlow could not finish startup. The error is shown above.
  echo Press any key to close this window.
  pause >nul
)
exit /b %launcher_exit%

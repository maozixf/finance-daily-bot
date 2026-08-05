@echo off
setlocal
title Finance Daily Bot - Configure Email API
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0configure-email-api.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" (
  echo Configuration failed with exit code %EXIT_CODE%.
) else (
  echo Configuration completed.
)
echo Press any key to close this window.
pause >nul
exit /b %EXIT_CODE%

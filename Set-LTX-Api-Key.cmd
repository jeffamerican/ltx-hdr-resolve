@echo off
setlocal

cd /d "%~dp0"

where pwsh >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  set "POWERSHELL_EXE=pwsh"
) else (
  set "POWERSHELL_EXE=powershell"
)

"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\set_ltx_api_key.ps1"
set "RESULT=%ERRORLEVEL%"

if not "%RESULT%"=="0" (
  echo.
  echo LTX API key setup failed with exit code %RESULT%.
  echo.
  pause
)

exit /b %RESULT%

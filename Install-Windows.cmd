@echo off
setlocal

cd /d "%~dp0"

where pwsh >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  set "POWERSHELL_EXE=pwsh"
) else (
  set "POWERSHELL_EXE=powershell"
)

"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_windows.ps1"
set "INSTALL_RESULT=%ERRORLEVEL%"

if not "%INSTALL_RESULT%"=="0" (
  echo.
  echo LTX HDR Resolve installer failed with exit code %INSTALL_RESULT%.
  echo.
  pause
)

exit /b %INSTALL_RESULT%

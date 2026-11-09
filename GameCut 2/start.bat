@echo off
rem GameCut for Windows - double-click this file to open the app
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
title GameCut

set "PY="
for %%V in (3.12 3.13 3.11 3.10) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; assert sys.version_info >= (3,10)" >nul 2>&1 && set "PY=python"
)
if not defined PY goto nopython

%PY% "%~dp0setup_win.py" %*
if errorlevel 1 pause
exit /b

:nopython
echo.
echo   ======================================================
echo    GameCut needs Python 3.12 (free) - it is not installed
echo   ======================================================
echo.
where winget >nul 2>&1
if errorlevel 1 goto manual
choice /M "   Install Python 3.12 now"
if errorlevel 2 goto manual
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
echo.
echo   Python installed. Close this window and double-click start.bat again.
echo.
pause
exit /b

:manual
echo.
echo   1. Download Python 3.12 from  https://www.python.org/downloads/windows/
echo   2. In the installer, tick  "Add python.exe to PATH"
echo   3. Double-click start.bat again
echo.
pause
exit /b

@echo off
REM start_live.bat — double-clickable launcher for the MSNR live web terminal.
REM Uses the Python 3.11 install explicitly, so it works regardless of PATH.
set "PY=C:\Users\Hp\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PY%" (
    echo ERROR: expected interpreter not found: %PY%
    echo Edit this file and set PY= to your Python 3.11+ with bot deps installed.
    pause
    exit /b 1
)
cd /d "%~dp0"
"%PY%" start_live.py %*
if errorlevel 1 pause

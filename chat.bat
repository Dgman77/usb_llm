@echo off
setlocal enabledelayedexpansion
title DiagramAI -- CLI Chat
color 0A

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "DRIVE=%ROOT:~0,2%"

echo.
echo  ================================================
echo   DiagramAI  --  CLI Chat
echo  ================================================
echo.

REM ── Find Python (LAST match wins — venv listed last so it takes priority) ────
set "PYTHON="
if exist "%DRIVE%\python\python.exe"        set "PYTHON=%DRIVE%\python\python.exe"
if exist "%ROOT%\python_runtime\python.exe" set "PYTHON=%ROOT%\python_runtime\python.exe"
if exist "%ROOT%\.myenv\Scripts\python.exe" set "PYTHON=%ROOT%\.myenv\Scripts\python.exe"
if exist "%ROOT%\myenv\Scripts\python.exe"  set "PYTHON=%ROOT%\myenv\Scripts\python.exe"
if exist "%ROOT%\venv\Scripts\python.exe"   set "PYTHON=%ROOT%\venv\Scripts\python.exe"
if exist "%DRIVE%\venv\Scripts\python.exe"  set "PYTHON=%DRIVE%\venv\Scripts\python.exe"

REM Fall back to system Python
if not defined PYTHON (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYTHON=python"
)

if not defined PYTHON (
    echo  [ERROR] No Python found.
    echo  Checked: %DRIVE%\venv\  %ROOT%\venv\  %DRIVE%\python\
    pause & exit /b 1
)

REM Verify fastapi is installed (packages check)
"%PYTHON%" -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] FastAPI not installed in: %PYTHON%
    echo.
    echo  Run this to install packages:
    echo  "%PYTHON%" -m pip install -r "%ROOT%\backend\requirements.txt"
    echo.
    pause & exit /b 1
)

echo  [OK] Python: %PYTHON%
echo.

REM ── Launch CLI chat ───────────────────────────────────────────────────────────
"%PYTHON%" "%ROOT%\chat.py"
pause
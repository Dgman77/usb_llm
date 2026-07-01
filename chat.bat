@echo off
setlocal enabledelayedexpansion
title Flash AI with RAG  -- CLI Chat
color 0A

REM ─────────────────────────────────────────────────────────────────
REM ROOT & DRIVE DETECTION  (works on any drive letter: C, D, E, G…)
REM ─────────────────────────────────────────────────────────────────
SET "ROOT=%~dp0"
IF "%ROOT:~-1%"=="\" SET "ROOT=%ROOT:~0,-1%"
SET "DRIVE=%ROOT:~0,2%"

echo.
echo  ================================================
echo    Flash AI with RAG   --  CLI Chat
echo  ================================================
echo.
echo  USB Root : %ROOT%
echo  Drive    : %DRIVE%
echo.

REM ─────────────────────────────────────────────────────────────────
REM FIND PYTHON  (priority: portable python folder > system python)
REM Mirrors the same search order used in start.bat
REM ─────────────────────────────────────────────────────────────────
SET "PYTHON="

REM 1. Portable python folder next to this bat (most common setup)
IF EXIST "%ROOT%\python\python.exe"         SET "PYTHON=%ROOT%\python\python.exe"

REM 2. Drive-root portable python (older layout)
IF NOT DEFINED PYTHON (
    IF EXIST "%DRIVE%\python\python.exe"    SET "PYTHON=%DRIVE%\python\python.exe"
)

REM 3. Any local venv the user may have created
IF NOT DEFINED PYTHON (
    IF EXIST "%ROOT%\venv\Scripts\python.exe"  SET "PYTHON=%ROOT%\venv\Scripts\python.exe"
)
IF NOT DEFINED PYTHON (
    IF EXIST "%ROOT%\.myenv\Scripts\python.exe" SET "PYTHON=%ROOT%\.myenv\Scripts\python.exe"
)
IF NOT DEFINED PYTHON (
    IF EXIST "%ROOT%\myenv\Scripts\python.exe"  SET "PYTHON=%ROOT%\myenv\Scripts\python.exe"
)
IF NOT DEFINED PYTHON (
    IF EXIST "%DRIVE%\venv\Scripts\python.exe"  SET "PYTHON=%DRIVE%\venv\Scripts\python.exe"
)

REM 4. Fall back to system Python
IF NOT DEFINED PYTHON (
    python --version >nul 2>&1
    IF NOT ERRORLEVEL 1 SET "PYTHON=python"
)

IF NOT DEFINED PYTHON (
    echo  [ERROR] No Python found.
    echo.
    echo  Checked locations:
    echo    %ROOT%\python\python.exe
    echo    %DRIVE%\python\python.exe
    echo    %ROOT%\venv\Scripts\python.exe
    echo.
    echo  Place your portable Python in:  %ROOT%\python\
    echo  OR install Python system-wide and re-run.
    echo.
    pause & exit /b 1
)

echo  [OK] Python: %PYTHON%

REM ─────────────────────────────────────────────────────────────────
REM VERIFY DEPENDENCIES
REM ─────────────────────────────────────────────────────────────────
"%PYTHON%" -c "import fastapi" >nul 2>&1
IF ERRORLEVEL 1 (
    echo.
    echo  [ERROR] FastAPI not found in: %PYTHON%
    echo.
    echo  Install with:
    echo  "%PYTHON%" -m pip install -r "%ROOT%\backend\requirements.txt"
    echo.
    pause & exit /b 1
)

"%PYTHON%" -c "import llama_cpp" >nul 2>&1
IF ERRORLEVEL 1 (
    echo.
    echo  [ERROR] llama-cpp-python not found in: %PYTHON%
    echo.
    echo  Install with:
    echo  "%PYTHON%" -m pip install llama-cpp-python
    echo.
    pause & exit /b 1
)

REM ─────────────────────────────────────────────────────────────────
REM LAUNCH CLI CHAT
REM ─────────────────────────────────────────────────────────────────
echo.
echo  [Launching CLI chat...]
echo.

"%PYTHON%" "%ROOT%\chat.py"
SET EXIT_CODE=!ERRORLEVEL!

IF !EXIT_CODE! NEQ 0 (
    echo.
    echo  [ERROR] Chat exited with code !EXIT_CODE!
    echo  Check the error messages above.
    echo.
)

pause
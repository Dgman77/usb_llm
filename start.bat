@echo off
setlocal enabledelayedexpansion
title DiagramAI -- Offline AI
color 0A

REM ─────────────────────────────────────────────
REM ROOT DETECTION (portable-safe)
REM ─────────────────────────────────────────────
SET ROOT=%~dp0
IF "%ROOT:~-1%"=="\" SET ROOT=%ROOT:~0,-1%

SET DRIVE=%ROOT:~0,2%
SET BACKEND=%ROOT%\backend
SET WAITER=%ROOT%\wait_for_server.py

echo.
echo ===============================================
echo   DiagramAI -- Offline AI (Portable Mode)
echo ===============================================
echo.
echo USB Drive : %DRIVE%
echo USB Root  : %ROOT%
echo.

REM ─────────────────────────────────────────────
REM FIND PYTHON (STRICT)
REM ─────────────────────────────────────────────
SET PYTHON=

IF EXIST "%ROOT%\python\python.exe" SET PYTHON=%ROOT%\python\python.exe
IF EXIST "%ROOT%\venv\Scripts\python.exe" SET PYTHON=%ROOT%\venv\Scripts\python.exe

IF NOT DEFINED PYTHON (
    echo [ERROR] Portable Python NOT FOUND
    echo Expected: %ROOT%\python\python.exe
    pause & exit /b 1
)

echo [OK] Python: %PYTHON%

REM ─────────────────────────────────────────────
REM HARD ISOLATION (CRITICAL)
REM ─────────────────────────────────────────────
FOR %%I IN ("%PYTHON%") DO SET PY_DIR=%%~dpI
SET PY_DIR=%PY_DIR:~0,-1%

SET PY_SCRIPTS=%PY_DIR%\Scripts

SET PATH=%PY_DIR%;%PY_SCRIPTS%
SET PYTHONHOME=%PY_DIR%
SET PYTHONNOUSERSITE=1
SET PYTHONPATH=
SET PYTHONEXECUTABLE=%PYTHON%

echo [OK] Environment isolated
echo.

REM ─────────────────────────────────────────────
REM MODEL DETECTION (ROBUST)
REM ─────────────────────────────────────────────
SET MODEL_PATH=

IF NOT EXIST "%ROOT%\models" (
    mkdir "%ROOT%\models"
)

REM Check saved path
IF EXIST "%ROOT%\models\model_path.txt" (
    FOR /F "usebackq tokens=* delims=" %%A IN ("%ROOT%\models\model_path.txt") DO (
        IF NOT DEFINED MODEL_PATH SET MODEL_PATH=%%A
    )
    IF NOT EXIST "!MODEL_PATH!" SET MODEL_PATH=
)

REM Scan models folder
IF NOT DEFINED MODEL_PATH (
    FOR %%F IN ("%ROOT%\models\*.gguf") DO (
        SET MODEL_PATH=%%F
        goto :model_found
    )
)

REM If still not found → error
IF NOT DEFINED MODEL_PATH (
    echo.
    echo [ERROR] No .gguf model found!
    echo.
    echo Put your model inside:
    echo %ROOT%\models\
    echo.
    echo Example:
    echo %ROOT%\models\Phi-3-mini-4k-instruct-q4.gguf
    echo.
    pause & exit /b 1
)

:model_found
echo [OK] Model: !MODEL_PATH!

REM Save for next run
(echo !MODEL_PATH!) > "%ROOT%\models\model_path.txt"

REM Pass to backend
SET DIAGRAMAI_MODEL=!MODEL_PATH!
SET DIAGRAMAI_ROOT=%ROOT%

echo.

REM ─────────────────────────────────────────────
REM CHECK REQUIRED FILES
REM ─────────────────────────────────────────────
IF NOT EXIST "%BACKEND%\main.py" (
    echo [ERROR] Backend not found: %BACKEND%\main.py
    pause & exit /b 1
)

IF NOT EXIST "%WAITER%" (
    echo [ERROR] Missing: wait_for_server.py
    pause & exit /b 1
)

REM ─────────────────────────────────────────────
REM START SERVER (NO "start" → FIXED)
REM ─────────────────────────────────────────────
cd /d "%BACKEND%"

echo [1/3] Starting server...
echo.

start "" "%PYTHON%" -m uvicorn main:app --host 0.0.0.0 --port 8787

REM ─────────────────────────────────────────────
REM WAIT FOR SERVER
REM ─────────────────────────────────────────────
echo.
echo +----------------------------------------------+
echo ^|  [2/3] Loading AI model into memory...      ^|
echo ^|                                              ^|
echo ^|  Takes 1-3 minutes. Please wait.             ^|
echo ^|  DO NOT close this window                    ^|
echo +----------------------------------------------+
echo.

"%PYTHON%" "%WAITER%"
SET WAIT_RESULT=!ERRORLEVEL!

IF !WAIT_RESULT! NEQ 0 (
    echo.
    echo +----------------------------------------------+
    echo   SERVER FAILED TO START
    echo +----------------------------------------------+
    echo.
    echo Python used  : %PYTHON%
    echo Model path   : !MODEL_PATH!
    echo.
    echo Check server window for error
    echo.
    pause & exit /b 1
)

REM ─────────────────────────────────────────────
REM OPEN BROWSER
REM ─────────────────────────────────────────────
echo [3/3] Opening browser...
echo.

start "" http://localhost:8787

echo +----------------------------------------------+
echo   Running at: http://localhost:8787
echo   Press any key to STOP
echo +----------------------------------------------+

pause >nul
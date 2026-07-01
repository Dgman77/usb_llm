@echo off
setlocal enabledelayedexpansion
title Flash AI with RAG  -- Offline AI
color 0A

REM ─────────────────────────────────────────────────────────────────
REM ROOT DETECTION  (works on any drive letter: C, D, E, G, USB…)
REM ─────────────────────────────────────────────────────────────────
SET "ROOT=%~dp0"
IF "%ROOT:~-1%"=="\" SET "ROOT=%ROOT:~0,-1%"
SET "DRIVE=%ROOT:~0,2%"
SET "BACKEND=%ROOT%\backend"
SET "WAITER=%ROOT%\wait_for_server.py"

echo.
echo ===============================================
echo   Flash AI with RAG  -- Offline AI
echo ===============================================
echo.
echo  Drive  : %DRIVE%
echo  Root   : %ROOT%
echo.

REM ─────────────────────────────────────────────────────────────────
REM FIND PYTHON  (portable python folder has highest priority)
REM ─────────────────────────────────────────────────────────────────
SET "PYTHON="

REM 1. Portable python folder inside the USB root (standard layout)
IF EXIST "%ROOT%\python\python.exe"         SET "PYTHON=%ROOT%\python\python.exe"

REM 2. Drive-root portable python (legacy layout)
IF NOT DEFINED PYTHON (
    IF EXIST "%DRIVE%\python\python.exe"    SET "PYTHON=%DRIVE%\python\python.exe"
)

REM 3. Local venv variants
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

IF NOT DEFINED PYTHON (
    echo.
    echo [ERROR] Portable Python NOT FOUND
    echo.
    echo Expected location:  %ROOT%\python\python.exe
    echo.
    echo  1. Download embeddable Python from python.org
    echo  2. Extract it to:  %ROOT%\python\
    echo  3. Run setup.bat to install dependencies
    echo.
    pause & exit /b 1
)

echo [OK] Python: %PYTHON%

REM ─────────────────────────────────────────────────────────────────
REM HARD ISOLATION  (prevent system-Python bleed-in)
REM ─────────────────────────────────────────────────────────────────
FOR %%I IN ("%PYTHON%") DO SET "PY_DIR=%%~dpI"
IF "%PY_DIR:~-1%"=="\" SET "PY_DIR=%PY_DIR:~0,-1%"
SET "PY_SCRIPTS=%PY_DIR%\Scripts"

SET "PATH=%PY_DIR%;%PY_SCRIPTS%"
SET "PYTHONHOME=%PY_DIR%"
SET "PYTHONNOUSERSITE=1"
SET "PYTHONPATH="
SET "PYTHONEXECUTABLE=%PYTHON%"

echo [OK] Environment isolated to: %PY_DIR%
echo.

REM ─────────────────────────────────────────────────────────────────
REM MODEL DETECTION  (drive-letter agnostic)
REM ─────────────────────────────────────────────────────────────────
SET "MODEL_PATH="

IF NOT EXIST "%ROOT%\models" (
    mkdir "%ROOT%\models"
    echo [INFO] Created models folder: %ROOT%\models
)

REM Check saved model path (may reference any drive)
IF EXIST "%ROOT%\models\model_path.txt" (
    FOR /F "usebackq tokens=* delims=" %%A IN ("%ROOT%\models\model_path.txt") DO (
        IF NOT DEFINED MODEL_PATH SET "MODEL_PATH=%%A"
    )
    REM Validate saved path still exists
    IF DEFINED MODEL_PATH (
        IF NOT EXIST "!MODEL_PATH!" (
            echo [WARN] Saved model path no longer valid: !MODEL_PATH!
            SET "MODEL_PATH="
        )
    )
)

REM Scan models folder in USB root
IF NOT DEFINED MODEL_PATH (
    FOR %%F IN ("%ROOT%\models\*.gguf") DO (
        SET "FNAME=%%~nxF"
        SET "IS_CHAT=1"
        SET "TEMP_NAME=!FNAME!"
        SET "TEMP_NAME=!TEMP_NAME:embed=!"
        SET "TEMP_NAME=!TEMP_NAME:rerank=!"
        SET "TEMP_NAME=!TEMP_NAME:nomic=!"
        IF NOT "!TEMP_NAME!"=="!FNAME!" SET "IS_CHAT=0"
        IF "!IS_CHAT!"=="1" (
            IF NOT DEFINED MODEL_PATH SET "MODEL_PATH=%%F"
        )
    )
)

IF NOT DEFINED MODEL_PATH (
    echo.
    echo [ERROR] No .gguf chat model found!
    echo.
    echo Place a .gguf model inside:  %ROOT%\models\
    echo Example:  %ROOT%\models\Qwen2.5-3B.Q6_K.gguf
    echo.
    echo  TIP: The embed model nomic-embed-text*.gguf is found automatically.
    echo.
    pause & exit /b 1
)

echo [OK] Model: !MODEL_PATH!

REM Save for next run (absolute path — works after drive letter change too)
(echo !MODEL_PATH!) > "%ROOT%\models\model_path.txt"

SET "FLASH_AI_MODEL=!MODEL_PATH!"
SET "FLASH_AI_ROOT=%ROOT%"

echo.

REM ─────────────────────────────────────────────────────────────────
REM CHECK REQUIRED FILES
REM ─────────────────────────────────────────────────────────────────
IF NOT EXIST "%BACKEND%\main.py" (
    echo [ERROR] Backend not found: %BACKEND%\main.py
    pause & exit /b 1
)
IF NOT EXIST "%WAITER%" (
    echo [ERROR] Missing: %WAITER%
    pause & exit /b 1
)

REM ─────────────────────────────────────────────────────────────────
REM START SERVER
REM ─────────────────────────────────────────────────────────────────
cd /d "%BACKEND%"

echo [1/3] Starting Flash AI server...
echo.

start "Flash AI Server" "%PYTHON%" -m uvicorn main:app --host 0.0.0.0 --port 8787 --log-level warning

REM ─────────────────────────────────────────────────────────────────
REM WAIT FOR SERVER READY
REM ─────────────────────────────────────────────────────────────────
echo.
echo +----------------------------------------------+
echo ^|  [2/3] Loading AI model into memory...      ^|
echo ^|                                              ^|
echo ^|  This takes 1-3 minutes on first run.        ^|
echo ^|  DO NOT close this window.                   ^|
echo +----------------------------------------------+
echo.

"%PYTHON%" "%WAITER%"
SET "WAIT_RESULT=!ERRORLEVEL!"

IF !WAIT_RESULT! NEQ 0 (
    echo.
    echo +----------------------------------------------+
    echo   [ERROR] SERVER FAILED TO START
    echo +----------------------------------------------+
    echo.
    echo  Python   : %PYTHON%
    echo  Model    : !MODEL_PATH!
    echo  Backend  : %BACKEND%
    echo.
    echo  Check the "Flash AI Server" window for details.
    echo.
    pause & exit /b 1
)

REM ─────────────────────────────────────────────────────────────────
REM OPEN BROWSER
REM ─────────────────────────────────────────────────────────────────
echo [3/3] Opening browser...
echo.
start "" http://localhost:8787

echo +----------------------------------------------+
echo   Flash AI running at: http://localhost:8787
echo.
echo   Press any key to STOP the server.
echo +----------------------------------------------+
echo.

pause >nul

echo.
echo [Shutting down server...]
taskkill /FI "WINDOWTITLE eq Flash AI Server*" /F >nul 2>&1
echo [Done] Server stopped.
pause
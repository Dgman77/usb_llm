@echo off
setlocal enabledelayedexpansion
title Flash AI — Data Cleaner
color 0E

REM ─────────────────────────────────────────────────────────────
REM ROOT DETECTION (works on any drive letter: C, D, E, G, USB…)
REM ─────────────────────────────────────────────────────────────
SET "ROOT=%~dp0"
IF "%ROOT:~-1%"=="\" SET "ROOT=%ROOT:~0,-1%"
SET "DATA=%ROOT%\data"
SET "DB=%ROOT%\metadata.db"
SET "IDX=%ROOT%\index.faiss"

echo.
echo ============================================================
echo   Flash AI — Data Cleaner
echo ============================================================
echo.
echo   Root : %ROOT%
echo   Data : %DATA%
echo.

IF NOT EXIST "%DATA%" (
    echo [INFO] Data folder not found: %DATA%
    echo [INFO] Nothing to clean.
    echo.
    pause
    exit /b 0
)

echo   This will DELETE all files inside:
echo     %DATA%\
echo.
echo   Folder structure will be preserved.
echo.

set /p CONFIRM="  Are you sure? (y/N): "
IF /I NOT "%CONFIRM%"=="y" (
    echo.
    echo   Cancelled.
    pause
    exit /b 0
)

echo.

REM ─────────────────────────────────────────────────────────────
REM DELETE ALL FILES IN data\ (keep folders)
REM ─────────────────────────────────────────────────────────────
SET /A REMOVED=0

FOR /R "%DATA%" %%F IN (*) DO (
    del /f /q "%%F" >nul 2>&1
    IF NOT ERRORLEVEL 1 (
        SET /A REMOVED+=1
        echo   Deleted: %%F
    ) ELSE (
        echo   [ERROR] Could not delete: %%F
    )
)

echo.
echo   [OK] Removed !REMOVED! file(s) from data\ folder.

REM ─────────────────────────────────────────────────────────────
REM CLEAR RAG METADATA DATABASE
REM ─────────────────────────────────────────────────────────────
IF EXIST "%DB%" (
    REM Use portable Python if available, otherwise system Python
    SET "PY="
    IF EXIST "%ROOT%\python\python.exe" SET "PY=%ROOT%\python\python.exe"
    IF NOT DEFINED PY (
        python --version >nul 2>&1
        IF NOT ERRORLEVEL 1 SET "PY=python"
    )

    IF DEFINED PY (
        "!PY!" -c "import sqlite3; c=sqlite3.connect(r'%DB%'); c.execute('DELETE FROM chunks'); c.execute('DELETE FROM doc_names'); c.commit(); c.close(); print('  [OK] Cleared RAG metadata in metadata.db')"
    ) ELSE (
        del /f /q "%DB%" >nul 2>&1
        echo   [OK] Removed metadata.db (no Python found to clear tables)
    )
)

IF EXIST "%IDX%" (
    del /f /q "%IDX%" >nul 2>&1
    echo   [OK] Removed index.faiss
)

echo.
echo ============================================================
echo   [DONE] All data cleaned. Folder structure preserved.
echo ============================================================
echo.
pause
exit /b 0

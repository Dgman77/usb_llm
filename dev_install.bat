@echo off
setlocal enabledelayedexpansion

:: ============================================================
:: PENDRIVE AI - ONE TIME SETUP
:: ============================================================

SET ROOT=%~dp0
IF "%ROOT:~-1%"=="\" SET ROOT=%ROOT:~0,-1%

SET PY=%ROOT%\python\python.exe

echo ============================================================
echo   PENDRIVE AI SETUP
echo   Root: %ROOT%
echo ============================================================
echo.

:: ─────────────────────────────────────────────
:: CHECK PYTHON
:: ─────────────────────────────────────────────
IF NOT EXIST "%PY%" (
    echo [ERROR] Portable Python not found!
    echo Expected: %ROOT%\python\python.exe
    pause & exit /b 1
)

echo [OK] Python found: %PY%
echo.

:: ─────────────────────────────────────────────
:: HARD ISOLATION (IMPORTANT)
:: ─────────────────────────────────────────────
SET PYTHONHOME=%ROOT%\python
SET PYTHONNOUSERSITE=1
SET PYTHONPATH=
SET PATH=%ROOT%\python;%ROOT%\python\Scripts

echo [OK] Environment isolated
echo.

:: ─────────────────────────────────────────────
:: STEP 1 - Upgrade pip
:: ─────────────────────────────────────────────
echo [1/9] Upgrading pip...
"%PY%" -m pip install --upgrade pip || goto :error
echo.

:: ─────────────────────────────────────────────
:: STEP 2 - Core backend
:: ─────────────────────────────────────────────
echo [2/9] Installing FastAPI stack...
"%PY%" -m pip install fastapi uvicorn python-multipart aiofiles || goto :error
echo.

:: ─────────────────────────────────────────────
:: STEP 3 - PDF support
:: ─────────────────────────────────────────────
echo [3/9] Installing PyMuPDF...
"%PY%" -m pip install PyMuPDF || goto :error
echo.

:: ─────────────────────────────────────────────
:: STEP 4 - RAG search
:: ─────────────────────────────────────────────
echo [4/9] Installing FAISS + BM25...
"%PY%" -m pip install faiss-cpu rank-bm25 || goto :error
echo.

:: ─────────────────────────────────────────────
:: STEP 5 - Numpy
:: ─────────────────────────────────────────────
echo [5/9] Installing Numpy...
"%PY%" -m pip install "numpy>=1.24,<2.0" || goto :error
echo.

:: ─────────────────────────────────────────────
:: STEP 6 - Pydantic
:: ─────────────────────────────────────────────
echo [6/9] Installing Pydantic...
"%PY%" -m pip install pydantic || goto :error
echo.

:: ─────────────────────────────────────────────
:: STEP 7 - DOCX support
:: ─────────────────────────────────────────────
echo [7/9] Installing python-docx...
"%PY%" -m pip install python-docx || goto :error
echo.

:: ─────────────────────────────────────────────
:: STEP 8 - llama-cpp (PREBUILT ONLY)
:: ─────────────────────────────────────────────
echo [8/9] Installing llama-cpp-python...

SET WHEEL_FOUND=

FOR %%F IN ("%ROOT%\wheels\llama_cpp_python-*.whl") DO (
    SET WHEEL_FOUND=%%F
)

IF DEFINED WHEEL_FOUND (
    echo Found wheel: !WHEEL_FOUND!
    "%PY%" -m pip install "!WHEEL_FOUND!" || goto :error
) ELSE (
    echo.
    echo [ERROR] llama-cpp wheel NOT FOUND
    echo Download from:
    echo https://github.com/abetlen/llama-cpp-python/releases
    echo Place inside: %ROOT%\wheels\
    echo.
    pause & exit /b 1
)

echo.

:: ─────────────────────────────────────────────
:: STEP 9 - canvas support
:: ─────────────────────────────────────────────
echo [9/9] Installing canvas and python-docx...
"%PY%" -m pip install canvas python-docx || goto :error
echo.


:: ─────────────────────────────────────────────
:: VERIFY INSTALLS
:: ─────────────────────────────────────────────
echo ============================================================
echo VERIFYING INSTALLATIONS
echo ============================================================

"%PY%" -c "import fastapi, uvicorn; print('FastAPI OK')"
"%PY%" -c "import fitz; print('PyMuPDF OK')"
"%PY%" -c "import faiss; print('FAISS OK')"
"%PY%" -c "import numpy; print('NumPy OK')"
"%PY%" -c "import pydantic; print('Pydantic OK')"
"%PY%" -c "import rank_bm25; print('BM25 OK')"
"%PY%" -c "import docx; print('DOCX OK')"
"%PY%" -c "from llama_cpp import Llama; print('LLM OK')"
"%PY%" -c "from canvas; print('canvas OK')"

echo.
echo ============================================================
echo SETUP COMPLETE ✅
echo Pendrive is ready to run on ANY PC 🚀
echo ============================================================
pause
exit /b 0

:error
echo.
echo ❌ INSTALL FAILED
echo Check error above
pause
exit /b 1
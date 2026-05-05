@echo off
setlocal enabledelayedexpansion
title LLM with RAG and Diagram -- Setup
color 0A

:: ─────────────────────────────────────────────────────────────
:: ROOT PATH  (strip trailing backslash)
:: ─────────────────────────────────────────────────────────────
SET ROOT=%~dp0
IF "%ROOT:~-1%"=="\" SET ROOT=%ROOT:~0,-1%

SET PY=%ROOT%\python\python.exe
SET PY_DIR=%ROOT%\python
SET SITE=%ROOT%\python\Lib\site-packages
SET SCRIPTS=%ROOT%\python\Scripts
SET WHEELS=%ROOT%\wheels

SET PYTHONHOME=%PY_DIR%
SET PYTHONNOUSERSITE=1
SET PYTHONPATH=
SET PATH=%PY_DIR%;%SCRIPTS%;%SystemRoot%\system32;%SystemRoot%

echo.
echo ============================================================
echo   LLM with RAG and Diagram -- Setup   ^|   Drive: %ROOT:~0,2%
echo ============================================================
echo.

:: ─────────────────────────────────────────────────────────────
:: DETECT DOWNLOAD TOOL
:: ─────────────────────────────────────────────────────────────
SET DOWNLOADER=

curl --version >nul 2>&1
IF NOT ERRORLEVEL 1 (
    SET DOWNLOADER=curl
    echo [OK] Downloader: curl
    goto :python_check
)

bitsadmin /? >nul 2>&1
IF NOT ERRORLEVEL 1 (
    SET DOWNLOADER=bitsadmin
    echo [OK] Downloader: bitsadmin
    goto :python_check
)

powershell -Command "exit 0" >nul 2>&1
IF NOT ERRORLEVEL 1 (
    SET DOWNLOADER=powershell
    echo [OK] Downloader: powershell
    goto :python_check
)

echo [ERROR] No download tool found (curl / bitsadmin / powershell).
echo.
echo  Download Python 3.11.9 manually:
echo  https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip
echo  Extract to: %PY_DIR%\   then re-run this script.
pause & exit /b 1

:: ─────────────────────────────────────────────────────────────
:: :download   ARG1=URL   ARG2=OUTPUT_FILE
:: ─────────────────────────────────────────────────────────────
:download
SET _URL=%~1
SET _OUT=%~2
IF /I "%DOWNLOADER%"=="curl" (
    curl -L --progress-bar -o "%_OUT%" "%_URL%"
    exit /b %ERRORLEVEL%
)
IF /I "%DOWNLOADER%"=="bitsadmin" (
    bitsadmin /transfer "LLM_RAG_Download" /download /priority normal "%_URL%" "%_OUT%"
    exit /b %ERRORLEVEL%
)
IF /I "%DOWNLOADER%"=="powershell" (
    powershell -Command "& { $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%_URL%' -OutFile '%_OUT%' }"
    exit /b %ERRORLEVEL%
)
exit /b 1

:: ─────────────────────────────────────────────────────────────
:: :progress_bar   ARG1=CURRENT   ARG2=TOTAL   ARG3=LABEL   ARG4=STATUS
:: ─────────────────────────────────────────────────────────────
:progress_bar
SET /A _CUR=%~1
SET /A _TOT=%~2
SET "_LBL=%~3"
SET "_STS=%~4"
SET /A _BAR_W=28

IF %_TOT% EQU 0 SET /A _TOT=1
SET /A _FILL=(_CUR*_BAR_W)/_TOT
SET /A _EMPTY=_BAR_W-_FILL
SET /A _PCT=(_CUR*100)/_TOT

SET "_F="
SET "_E="
FOR /L %%B IN (1,1,%_FILL%)  DO SET "_F=!_F!#"
FOR /L %%B IN (1,1,%_EMPTY%) DO SET "_E=!_E!."

SET "_PAD=!_LBL!                              "
SET "_PAD=!_PAD:~0,26!"

SET "_PP=  %_PCT%"
SET "_PP=!_PP:~-3!"

SET "_CP=   %_CUR%"
SET "_CP=!_CP:~-3!"

IF /I "!_STS!"=="ok"      echo   [!_F!!_E!] !_PP!%%  (!_CP!/%_TOT%)  !_PAD!  [  OK  ]
IF /I "!_STS!"=="skip"    echo   [!_F!!_E!] !_PP!%%  (!_CP!/%_TOT%)  !_PAD!  [ SKIP ]
IF /I "!_STS!"=="fail"    echo   [!_F!!_E!] !_PP!%%  (!_CP!/%_TOT%)  !_PAD!  [ FAIL ]
IF /I "!_STS!"=="working" echo   [!_F!!_E!] !_PP!%%  (!_CP!/%_TOT%)  !_PAD!  [ .... ]
exit /b 0

:: ─────────────────────────────────────────────────────────────
:: PYTHON CHECK / INSTALL
:: ─────────────────────────────────────────────────────────────
:python_check
IF EXIST "%PY%" (
    echo [SKIP] Python already installed at %PY%
    echo.
    goto :pip_check
)

echo [NEED] Python not found -- downloading Python 3.11.9 ...
echo.
IF NOT EXIST "%PY_DIR%" mkdir "%PY_DIR%"

SET PY_ZIP=%ROOT%\py_embed.zip
call :download "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip" "%PY_ZIP%"

IF NOT EXIST "%PY_ZIP%" (
    echo [ERROR] Download failed.
    echo  Manual URL: https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip
    echo  Extract to: %PY_DIR%\   then re-run.
    pause & exit /b 1
)
echo [OK] Downloaded

powershell -Command "& { Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::ExtractToDirectory('%PY_ZIP%', '%PY_DIR%') }" >nul 2>&1
IF ERRORLEVEL 1 tar -xf "%PY_ZIP%" -C "%PY_DIR%"
del "%PY_ZIP%" >nul 2>&1

IF NOT EXIST "%PY%" (
    echo [ERROR] Extraction failed -- extract manually to %PY_DIR%\
    pause & exit /b 1
)
echo [OK] Python 3.11.9 extracted
echo.

:: Enable site-packages in embedded Python
SET PTH=%PY_DIR%\python311._pth
powershell -Command "& { (Get-Content '%PTH%') -replace '#import site','import site' | Set-Content '%PTH%' }" >nul 2>&1
IF ERRORLEVEL 1 (
    "%PY%" -c "f=open(r'%PTH%');c=f.read();f.close();f=open(r'%PTH%','w');f.write(c.replace('#import site','import site'));f.close()"
)
echo [OK] site-packages enabled
echo.

:: ─────────────────────────────────────────────────────────────
:: PIP CHECK / INSTALL
:: ─────────────────────────────────────────────────────────────
:pip_check
"%PY%" -m pip --version >nul 2>&1
IF NOT ERRORLEVEL 1 (
    echo [SKIP] pip already installed
    echo.
    goto :packages
)

echo [NEED] pip not found -- downloading get-pip.py ...
SET GETPIP=%ROOT%\get-pip.py
call :download "https://bootstrap.pypa.io/get-pip.py" "%GETPIP%"
IF NOT EXIST "%GETPIP%" (
    echo [ERROR] Failed to download get-pip.py
    pause & exit /b 1
)
"%PY%" "%GETPIP%" --quiet
IF ERRORLEVEL 1 (
    echo [ERROR] pip bootstrap failed.
    del "%GETPIP%" >nul 2>&1
    pause & exit /b 1
)
del "%GETPIP%" >nul 2>&1
"%PY%" -m pip install --upgrade pip --quiet
echo [OK] pip installed
echo.

:: ─────────────────────────────────────────────────────────────
:: PACKAGES
:: ─────────────────────────────────────────────────────────────
:packages
IF NOT EXIST "%WHEELS%" mkdir "%WHEELS%"
IF NOT EXIST "%SITE%"   mkdir "%SITE%"

SET /A PKG_TOTAL=0

call :reg  fastapi              "fastapi>=0.110.0"
call :reg  uvicorn              "uvicorn>=0.29.0"
call :reg  multipart            "python-multipart>=0.0.9"
call :reg  aiofiles             "aiofiles>=23.0.0"
call :reg  fitz                 "PyMuPDF>=1.23.0"
call :reg  faiss                "faiss-cpu>=1.7.4"
call :reg  numpy                "numpy>=1.24.0,<2.0.0"
call :reg  pydantic             "pydantic>=2.0.0"
call :reg  rank_bm25            "rank-bm25>=0.2.2"
call :reg  docx                 "python-docx"
call :reg  sentence_transformers "sentence-transformers>=2.2.0"
call :reg  httpx                "httpx>=0.24.0"

:: ── Scan: split into already-installed vs. needs-install ──────
SET /A SKIP_COUNT=0
SET /A NEED_COUNT=0
SET /A INSTALL_COUNT=0
SET /A _LAST=%PKG_TOTAL%-1

FOR /L %%I IN (0,1,%_LAST%) DO (
    IF EXIST "%SITE%\!PKG_FOLDER[%%I]!" (
        SET /A SKIP_COUNT+=1
    ) ELSE (
        SET "INSTALL_FOLDER[!INSTALL_COUNT!]=!PKG_FOLDER[%%I]!"
        SET "INSTALL_SPEC[!INSTALL_COUNT!]=!PKG_SPEC[%%I]!"
        SET /A INSTALL_COUNT+=1
        SET /A NEED_COUNT+=1
    )
)

echo ============================================================
echo   Package Status
echo ============================================================
echo   Total registered : %PKG_TOTAL%
echo   Already installed: %SKIP_COUNT%
echo   To install       : %NEED_COUNT%
echo ============================================================
echo.

:: ── Show already-installed packages ───────────────────────────
IF %SKIP_COUNT% GTR 0 (
    echo   Already installed:
    echo.
    SET /A _SI=0
    FOR /L %%I IN (0,1,%_LAST%) DO (
        IF EXIST "%SITE%\!PKG_FOLDER[%%I]!" (
            SET /A _SI+=1
            call :progress_bar !_SI! %SKIP_COUNT% "!PKG_FOLDER[%%I]!" skip
        )
    )
    echo.
)

:: ── Install missing packages ───────────────────────────────────
IF %NEED_COUNT% EQU 0 (
    echo   All packages already up to date.
    echo.
    goto :llama_cpp
)

echo   Installing %NEED_COUNT% missing package(s):
echo.

SET /A _LAST2=%INSTALL_COUNT%-1
SET /A _FAIL=0

FOR /L %%I IN (0,1,%_LAST2%) DO (
    SET /A _STEP=%%I+1
    SET "_SPEC=!INSTALL_SPEC[%%I]!"
    SET "_FOLD=!INSTALL_FOLDER[%%I]!"

    call :progress_bar !_STEP! %INSTALL_COUNT% "!_FOLD!" working

    "%PY%" -m pip install "!_SPEC!" --quiet >nul 2>&1
    SET _PERR=!ERRORLEVEL!

    IF !_PERR! EQU 0 (
        call :progress_bar !_STEP! %INSTALL_COUNT% "!_FOLD!" ok
    ) ELSE (
        call :progress_bar !_STEP! %INSTALL_COUNT% "!_FOLD!" fail
        SET /A _FAIL+=1
    )
)

echo.
IF %_FAIL% GTR 0 (
    echo   [WARNING] %_FAIL% package(s) failed.
    echo             Re-run as Administrator or check internet connection.
    echo.
) ELSE (
    echo   [OK] All %NEED_COUNT% package(s) installed successfully.
    echo.
)

:: ─────────────────────────────────────────────────────────────
:: LLAMA-CPP  (pre-built wheel required in .\wheels\)
:: ─────────────────────────────────────────────────────────────
:llama_cpp
echo ============================================================
echo   llama_cpp
echo ============================================================
echo.

IF EXIST "%SITE%\llama_cpp" (
    call :progress_bar 1 1 "llama_cpp" skip
    echo.
    goto :verify
)

:: Search for any matching wheel in the wheels folder
SET "WHEEL_PATH="
FOR %%F IN ("%WHEELS%\llama_cpp_python-*.whl") DO SET "WHEEL_PATH=%%F"

IF NOT DEFINED WHEEL_PATH (
    echo  +------------------------------------------------------+
    echo  ^|  WHEEL NOT FOUND                                     ^|
    echo  ^|  Download from:                                      ^|
    echo  ^|  github.com/abetlen/llama-cpp-python/releases        ^|
    echo  ^|  Tag  : v0.2.90                                      ^|
    echo  ^|  File : llama_cpp_python-0.2.90-cp311-cp311-         ^|
    echo  ^|         win_amd64.whl                                ^|
    echo  ^|  Save to: %ROOT%\wheels\          ^|
    echo  +------------------------------------------------------+
    echo.
    pause & exit /b 1
)

echo   Found wheel: %WHEEL_PATH%
echo.
call :progress_bar 0 1 "llama_cpp" working
"%PY%" -m pip install "%WHEEL_PATH%" --quiet
IF ERRORLEVEL 1 (
    call :progress_bar 1 1 "llama_cpp" fail
    echo.
    echo  [HINT] Possible reasons:
    echo    1. Wrong Python version -- wheel needs cp311 (Python 3.11)
    echo    2. Wrong architecture  -- wheel needs win_amd64 (64-bit)
    echo    3. VC++ runtime missing -- install Visual C++ Redistributable
    echo.
    goto :error
)
call :progress_bar 1 1 "llama_cpp" ok
echo.

:: ─────────────────────────────────────────────────────────────
:: VERIFY KEY IMPORTS
:: ─────────────────────────────────────────────────────────────
:verify
echo ============================================================
echo   Verifying Imports
echo ============================================================
echo.

SET /A V_FAIL=0

"%PY%" -c "import fastapi" >nul 2>&1
IF ERRORLEVEL 1 ( echo   [FAIL] fastapi & SET /A V_FAIL+=1 ) ELSE ( echo   [ OK ] fastapi )

"%PY%" -c "import uvicorn" >nul 2>&1
IF ERRORLEVEL 1 ( echo   [FAIL] uvicorn & SET /A V_FAIL+=1 ) ELSE ( echo   [ OK ] uvicorn )

"%PY%" -c "import fitz" >nul 2>&1
IF ERRORLEVEL 1 ( echo   [FAIL] PyMuPDF (fitz) & SET /A V_FAIL+=1 ) ELSE ( echo   [ OK ] PyMuPDF (fitz) )

"%PY%" -c "import faiss" >nul 2>&1
IF ERRORLEVEL 1 ( echo   [FAIL] faiss-cpu & SET /A V_FAIL+=1 ) ELSE ( echo   [ OK ] faiss-cpu )

"%PY%" -c "import numpy" >nul 2>&1
IF ERRORLEVEL 1 ( echo   [FAIL] numpy & SET /A V_FAIL+=1 ) ELSE ( echo   [ OK ] numpy )

"%PY%" -c "from llama_cpp import Llama" >nul 2>&1
IF ERRORLEVEL 1 ( echo   [FAIL] llama_cpp & SET /A V_FAIL+=1 ) ELSE ( echo   [ OK ] llama_cpp )

echo.
IF %V_FAIL% GTR 0 (
    echo   [WARNING] %V_FAIL% import(s) failed -- re-run setup or check errors above.
) ELSE (
    echo   [OK] All imports verified successfully.
)
echo.

:: ─────────────────────────────────────────────────────────────
:: CREATE MODELS FOLDER
:: ─────────────────────────────────────────────────────────────
IF NOT EXIST "%ROOT%\models" (
    mkdir "%ROOT%\models"
    echo [OK] Created models\ folder
)

:: ─────────────────────────────────────────────────────────────
:done
echo.
echo ============================================================
echo   ALL DONE -- Pendrive ready for any Windows laptop
echo   Models folder : %ROOT%\models\
echo   Users run     : start.bat
echo ============================================================
echo.
pause
exit /b 0

:: ─────────────────────────────────────────────────────────────
:: SUBROUTINES
:: ─────────────────────────────────────────────────────────────

:reg
SET "PKG_FOLDER[%PKG_TOTAL%]=%~1"
SET "PKG_SPEC[%PKG_TOTAL%]=%~2"
SET /A PKG_TOTAL+=1
exit /b 0

:error
echo.
echo [ERROR] Install failed -- try running as Administrator
pause
exit /b 1
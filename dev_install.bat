@echo off
setlocal enabledelayedexpansion
title DiagramAI -- Setup
color 0A

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
echo   DiagramAI -- Setup   ^|   Drive: %ROOT:~0,2%
echo ============================================================
echo.

:: ─────────────────────────────────────────────────────────────
:: DETECT DOWNLOAD TOOL: curl first, then bitsadmin, then powershell
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

echo [ERROR] No download tool found.
echo         curl / bitsadmin / powershell all missing.
echo         Please download Python 3.11.9 manually:
echo         https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip
echo         Extract it to: %PY_DIR%\
echo         Then re-run this script.
pause & exit /b 1

:: ─────────────────────────────────────────────────────────────
:: DOWNLOAD SUBROUTINE
:: Usage: call :download  URL  OUTPUTFILE
:: ─────────────────────────────────────────────────────────────
:download
SET _URL=%~1
SET _OUT=%~2

IF "%DOWNLOADER%"=="curl" (
    curl -L --progress-bar -o "%_OUT%" "%_URL%"
    goto :download_done
)
IF "%DOWNLOADER%"=="bitsadmin" (
    bitsadmin /transfer DiagramAI_Download /download /priority normal "%_URL%" "%_OUT%"
    goto :download_done
)
IF "%DOWNLOADER%"=="powershell" (
    powershell -Command "& { $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%_URL%' -OutFile '%_OUT%' }"
    goto :download_done
)

:download_done
exit /b 0

:: ─────────────────────────────────────────────────────────────
:: PYTHON CHECK
:: ─────────────────────────────────────────────────────────────
:python_check
IF EXIST "%PY%" (
    echo [SKIP] Python already installed
    echo        %PY%
    echo.
    goto :packages
)

echo [NEED] Python not found -- downloading Python 3.11.9...
echo.

IF NOT EXIST "%PY_DIR%" mkdir "%PY_DIR%"

SET PY_ZIP=%ROOT%\py_embed.zip
SET PY_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip

call :download "%PY_URL%" "%PY_ZIP%"

IF NOT EXIST "%PY_ZIP%" (
    echo.
    echo [ERROR] Download failed.
    echo.
    echo  Download manually from:
    echo  https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip
    echo.
    echo  Extract contents into: %PY_DIR%\
    echo  Then re-run this script.
    pause & exit /b 1
)
echo [OK] Downloaded

:: Extract
IF "%DOWNLOADER%"=="powershell" (
    powershell -Command "& { Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::ExtractToDirectory('%PY_ZIP%', '%PY_DIR%') }"
) ELSE (
    :: curl/bitsadmin machines still have PowerShell for extraction
    powershell -Command "& { Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::ExtractToDirectory('%PY_ZIP%', '%PY_DIR%') }" >nul 2>&1
    IF ERRORLEVEL 1 (
        :: Fallback: use tar (available Windows 10 build 17063+)
        tar -xf "%PY_ZIP%" -C "%PY_DIR%"
    )
)

del "%PY_ZIP%" >nul 2>&1

IF NOT EXIST "%PY%" (
    echo [ERROR] Extraction failed.
    echo         Manually extract the zip to: %PY_DIR%\
    pause & exit /b 1
)
echo [OK] Python 3.11.9 extracted
echo.

:: ── Fix _pth ─────────────────────────────────────────────────
SET PTH=%PY_DIR%\python311._pth
powershell -Command "& { (Get-Content '%PTH%') -replace '#import site','import site' | Set-Content '%PTH%' }" >nul 2>&1
IF ERRORLEVEL 1 (
    :: manual patch fallback using Python itself after extraction
    "%PY%" -c "f=open(r'%PTH%');c=f.read();f.close();f=open(r'%PTH%','w');f.write(c.replace('#import site','import site'));f.close()"
)
echo [OK] site-packages enabled
echo.

:: ── Install pip ──────────────────────────────────────────────
SET GETPIP=%ROOT%\get-pip.py
call :download "https://bootstrap.pypa.io/get-pip.py" "%GETPIP%"

IF NOT EXIST "%GETPIP%" (
    echo [ERROR] Failed to download get-pip.py
    pause & exit /b 1
)

"%PY%" "%GETPIP%" --quiet
del "%GETPIP%" >nul 2>&1
"%PY%" -m pip install --upgrade pip --quiet
echo [OK] pip installed
echo.

:: ─────────────────────────────────────────────────────────────
:: PACKAGES — check site-packages folder, skip if exists
:: ─────────────────────────────────────────────────────────────
:packages
echo Checking packages...
echo.

IF NOT EXIST "%WHEELS%" mkdir "%WHEELS%"
IF NOT EXIST "%SITE%"   mkdir "%SITE%"

SET INSTALL_LIST=
SET SKIP=0
SET NEED=0

call :chk  fastapi        "fastapi>=0.110.0"
call :chk  uvicorn        "uvicorn>=0.29.0"
call :chk  multipart      "python-multipart>=0.0.9"
call :chk  aiofiles       "aiofiles>=23.0.0"
call :chk  fitz           "PyMuPDF>=1.23.0"
call :chk  faiss          "faiss-cpu>=1.7.4"
call :chk  numpy          "numpy>=1.24.0,<2.0.0"
call :chk  pydantic       "pydantic>=2.0.0"
call :chk  rank_bm25      "rank-bm25>=0.2.2"
call :chk  docx           "python-docx"

echo.
echo   Skipped : %SKIP%   ^|   To install : %NEED%
echo.

IF DEFINED INSTALL_LIST (
    echo Installing missing packages...
    "%PY%" -m pip install %INSTALL_LIST%
    IF ERRORLEVEL 1 goto :error
    echo [OK] Packages installed
    echo.
)

:: ─────────────────────────────────────────────────────────────
:: LLAMA-CPP
:: ─────────────────────────────────────────────────────────────
IF EXIST "%SITE%\llama_cpp" (
    echo   [SKIP] llama_cpp  already installed
) ELSE (
    echo   [NEED] llama_cpp  -- searching wheel...
    SET WHEEL_PATH=
    FOR %%F IN ("%WHEELS%\llama_cpp_python-*.whl") DO SET WHEEL_PATH=%%F

    IF DEFINED WHEEL_PATH (
        "%PY%" -m pip install "!WHEEL_PATH!"
        IF ERRORLEVEL 1 goto :error
        echo   [OK]  llama_cpp installed
    ) ELSE (
        echo.
        echo  ┌──────────────────────────────────────────────────────┐
        echo  │  WHEEL NOT FOUND                                     │
        echo  │                                                      │
        echo  │  Download:                                           │
        echo  │  github.com/abetlen/llama-cpp-python/releases        │
        echo  │  Tag  : v0.2.90                                      │
        echo  │  File : llama_cpp_python-0.2.90-cp311-cp311-         │
        echo  │         win_amd64.whl                                │
        echo  │  Save to : %ROOT%\wheels\          │
        echo  └──────────────────────────────────────────────────────┘
        echo.
        pause & exit /b 1
    )
)

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
:chk
IF EXIST "%SITE%\%~1" (
    echo   [SKIP] %~1
    SET /A SKIP+=1
) ELSE (
    echo   [NEED] %~1
    SET INSTALL_LIST=!INSTALL_LIST! %~2
    SET /A NEED+=1
)
exit /b 0

:error
echo.
echo [ERROR] Install failed -- try running as Administrator
pause
exit /b 1
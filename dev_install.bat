```bat
@echo off
setlocal EnableDelayedExpansion
title DiagramAI -- Setup
color 0A

:: ============================================================
:: ROOT PATH
:: ============================================================
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "PY_DIR=%ROOT%\python"
set "PY=%PY_DIR%\python.exe"
set "SCRIPTS=%PY_DIR%\Scripts"
set "WHEELS=%ROOT%\wheels"

set "PYTHONHOME=%PY_DIR%"
set "PYTHONNOUSERSITE=1"
set "PATH=%PY_DIR%;%SCRIPTS%;%SystemRoot%\system32;%SystemRoot%"

echo.
echo ============================================================
echo   DiagramAI -- Setup
echo   Drive: %ROOT:~0,2%
echo ============================================================
echo.

:: ============================================================
:: INSTALL EMBEDDED PYTHON IF MISSING
:: ============================================================
if exist "%PY%" (
    echo [SKIP] Embedded Python already installed
    echo        %PY%
    echo.
    goto :CHECK_PACKAGES
)

echo [INFO] Embedded Python not found. Installing...
echo.

if not exist "%PY_DIR%" mkdir "%PY_DIR%"

set "PY_ZIP=%ROOT%\python_embed.zip"

echo [INFO] Downloading Python...
powershell -Command ^
"$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip' -OutFile '%PY_ZIP%'"

if not exist "%PY_ZIP%" (
    echo [ERROR] Python download failed.
    pause
    exit /b 1
)

echo [INFO] Extracting Python...
powershell -Command ^
"Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::ExtractToDirectory('%PY_ZIP%', '%PY_DIR%')"

del "%PY_ZIP%"

if not exist "%PY%" (
    echo [ERROR] Python extraction failed.
    pause
    exit /b 1
)

echo [OK] Embedded Python installed
echo.

:: ============================================================
:: ENABLE SITE-PACKAGES
:: ============================================================
echo [INFO] Enabling site-packages...
powershell -Command ^
"$f='%PY_DIR%\python311._pth'; $c=Get-Content $f; $c=$c -replace '#import site','import site'; if ($c -notcontains 'Lib\site-packages') { $c += 'Lib\site-packages' }; Set-Content $f $c"

echo [OK] site-packages enabled
echo.

:: ============================================================
:: INSTALL PIP
:: ============================================================
echo [INFO] Installing pip...
powershell -Command ^
"$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%ROOT%\get-pip.py'"

"%PY%" "%ROOT%\get-pip.py" --quiet
del "%ROOT%\get-pip.py"

"%PY%" -m pip install --upgrade pip --quiet

echo [OK] pip installed
echo.

:: ============================================================
:: CHECK REQUIRED PACKAGES
:: ============================================================
:CHECK_PACKAGES

set "INSTALL_LIST="
set /a SKIP=0
set /a NEED=0

call :CHECK fastapi fastapi
call :CHECK uvicorn uvicorn
call :CHECK multipart python-multipart
call :CHECK aiofiles aiofiles
call :CHECK fitz PyMuPDF
call :CHECK faiss faiss-cpu
call :CHECK numpy numpy
call :CHECK pydantic pydantic
call :CHECK rank_bm25 rank-bm25
call :CHECK docx python-docx

echo.
echo Packages already installed : %SKIP%
echo Packages to install       : %NEED%
echo.

if defined INSTALL_LIST (
    echo [INFO] Installing missing packages...
    "%PY%" -m pip install %INSTALL_LIST%
    if errorlevel 1 goto :ERROR
    echo [OK] Packages installed
) else (
    echo [OK] All required packages already installed
)

echo.

:: ============================================================
:: INSTALL LLAMA_CPP IF MISSING
:: ============================================================
"%PY%" -c "import llama_cpp" >nul 2>&1
if not errorlevel 1 (
    echo [SKIP] llama_cpp already installed
    goto :DONE
)

echo [INFO] llama_cpp not installed
set "WHEEL_FILE="

for %%F in ("%WHEELS%\llama_cpp_python-*.whl") do (
    set "WHEEL_FILE=%%F"
)

if not defined WHEEL_FILE (
    echo.
    echo [ERROR] llama_cpp wheel not found
    echo Place wheel in:
    echo %WHEELS%
    echo.
    pause
    exit /b 1
)

echo [INFO] Installing llama_cpp...
"%PY%" -m pip install "!WHEEL_FILE!"
if errorlevel 1 goto :ERROR

echo [OK] llama_cpp installed
echo.

:: ============================================================
:: DONE
:: ============================================================
:DONE
echo ============================================================
echo   SETUP COMPLETE
echo   Put GGUF models in:
echo   %ROOT%\models\
echo   Users can now run run.bat
echo ============================================================
echo.
pause
exit /b 0

:: ============================================================
:: PACKAGE CHECK SUBROUTINE
:: %1 = import name
:: %2 = pip package name
:: ============================================================
:CHECK
"%PY%" -c "import %~1" >nul 2>&1
if not errorlevel 1 (
    echo [SKIP] %~2
    set /a SKIP+=1
) else (
    echo [NEED] %~2
    set "INSTALL_LIST=!INSTALL_LIST! %~2"
    set /a NEED+=1
)
exit /b 0

:ERROR
echo.
echo [ERROR] Installation failed.
pause
exit /b 1
```

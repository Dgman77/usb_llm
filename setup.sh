#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# LLM with RAG and Diagram -- Setup (Linux / macOS)
# ─────────────────────────────────────────────────────────────

set -euo pipefail

# ── Colors ───────────────────────────────────────────────────
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
CYAN="\033[0;36m"
RESET="\033[0m"

# ─────────────────────────────────────────────────────────────
# ROOT PATH  (directory of this script, no trailing slash)
# ─────────────────────────────────────────────────────────────
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PY_DIR="$ROOT/python"
PY="$PY_DIR/bin/python3"
SITE="$PY_DIR/lib/python3.11/site-packages"
WHEELS="$ROOT/wheels"
VENV="$ROOT/venv"

echo ""
echo "============================================================"
echo "  LLM with RAG and Diagram -- Setup  |  Root: $ROOT"
echo "============================================================"
echo ""

# ─────────────────────────────────────────────────────────────
# HELPER: progress_bar  CURRENT  TOTAL  LABEL  STATUS
# ─────────────────────────────────────────────────────────────
progress_bar() {
    local CUR=$1 TOT=$2 LBL=$3 STS=$4
    local BAR_W=28
    [[ $TOT -eq 0 ]] && TOT=1
    local FILL=$(( CUR * BAR_W / TOT ))
    local EMPTY=$(( BAR_W - FILL ))
    local PCT=$(( CUR * 100 / TOT ))

    local F="" E=""
    for (( i=0; i<FILL;  i++ )); do F+="#"; done
    for (( i=0; i<EMPTY; i++ )); do E+="."; done

    local PAD
    PAD=$(printf "%-26s" "$LBL")
    local PP
    PP=$(printf "%3d" "$PCT")
    local CP
    CP=$(printf "%3d" "$CUR")

    case "$STS" in
        ok)      echo -e "  [${F}${E}] ${PP}%  (${CP}/${TOT})  ${PAD}  [${GREEN}  OK  ${RESET}]" ;;
        skip)    echo -e "  [${F}${E}] ${PP}%  (${CP}/${TOT})  ${PAD}  [${CYAN} SKIP ${RESET}]" ;;
        fail)    echo -e "  [${F}${E}] ${PP}%  (${CP}/${TOT})  ${PAD}  [${RED} FAIL ${RESET}]" ;;
        working) echo -e "  [${F}${E}] ${PP}%  (${CP}/${TOT})  ${PAD}  [${YELLOW} .... ${RESET}]" ;;
    esac
}

# ─────────────────────────────────────────────────────────────
# DETECT DOWNLOADER
# ─────────────────────────────────────────────────────────────
DOWNLOADER=""
if command -v curl &>/dev/null;  then DOWNLOADER="curl";  echo -e "[${GREEN}OK${RESET}] Downloader: curl"
elif command -v wget &>/dev/null; then DOWNLOADER="wget";  echo -e "[${GREEN}OK${RESET}] Downloader: wget"
else
    echo -e "[${RED}ERROR${RESET}] No download tool found (curl / wget)."
    echo "  Install curl:  sudo apt install curl   OR   brew install curl"
    exit 1
fi
echo ""

# ─────────────────────────────────────────────────────────────
# HELPER: download  URL  OUTPUT
# ─────────────────────────────────────────────────────────────
download() {
    local URL="$1" OUT="$2"
    if [[ "$DOWNLOADER" == "curl" ]]; then
        curl -L --progress-bar -o "$OUT" "$URL"
    else
        wget -q --show-progress -O "$OUT" "$URL"
    fi
}

# ─────────────────────────────────────────────────────────────
# PYTHON CHECK (use system python3 or venv)
# ─────────────────────────────────────────────────────────────
python_check() {
    echo "============================================================"
    echo "  Python Check"
    echo "============================================================"
    echo ""

    # Prefer venv if already created
    if [[ -f "$VENV/bin/python3" ]]; then
        PY="$VENV/bin/python3"
        SITE="$VENV/lib/python3.11/site-packages"
        echo -e "[${CYAN}SKIP${RESET}] Virtualenv already exists at $VENV"
        echo ""
        return
    fi

    # Find system python 3.11 or any python3
    local SYS_PY=""
    for candidate in python3.11 python3 python; do
        if command -v "$candidate" &>/dev/null; then
            local VER
            VER=$("$candidate" -c "import sys; print(sys.version_info[:2])" 2>/dev/null || true)
            if [[ "$VER" == "(3, 11)" || "$VER" == "(3, 10)" || "$VER" == "(3, 12)" ]]; then
                SYS_PY="$candidate"
                break
            fi
        fi
    done

    if [[ -z "$SYS_PY" ]]; then
        echo -e "[${RED}ERROR${RESET}] Python 3.10/3.11/3.12 not found."
        echo "  Install: sudo apt install python3.11 python3.11-venv  OR  brew install python@3.11"
        exit 1
    fi

    echo -e "[${GREEN}OK${RESET}] Found system Python: $SYS_PY  ($($SYS_PY --version))"
    echo ""
    echo "  Creating virtualenv at: $VENV"
    "$SYS_PY" -m venv "$VENV"
    PY="$VENV/bin/python3"
    SITE="$("$PY" -c "import site; print(site.getsitepackages()[0])")"
    echo -e "[${GREEN}OK${RESET}] Virtualenv created"
    echo ""
}

# ─────────────────────────────────────────────────────────────
# PIP CHECK
# ─────────────────────────────────────────────────────────────
pip_check() {
    if "$PY" -m pip --version &>/dev/null; then
        echo -e "[${CYAN}SKIP${RESET}] pip already installed"
        echo ""
        return
    fi

    echo "  Downloading get-pip.py ..."
    local GETPIP="$ROOT/get-pip.py"
    download "https://bootstrap.pypa.io/get-pip.py" "$GETPIP"
    "$PY" "$GETPIP" --quiet
    rm -f "$GETPIP"
    "$PY" -m pip install --upgrade pip --quiet
    echo -e "[${GREEN}OK${RESET}] pip installed"
    echo ""
}

# ─────────────────────────────────────────────────────────────
# PACKAGES
# ─────────────────────────────────────────────────────────────
PKG_FOLDERS=()
PKG_SPECS=()

reg_pkg() {
    PKG_FOLDERS+=("$1")
    PKG_SPECS+=("$2")
}

install_packages() {
    reg_pkg "fastapi"     "fastapi>=0.110.0"
    reg_pkg "uvicorn"     "uvicorn>=0.29.0"
    reg_pkg "multipart"   "python-multipart>=0.0.9"
    reg_pkg "aiofiles"    "aiofiles>=23.0.0"
    reg_pkg "fitz"        "PyMuPDF>=1.23.0"
    reg_pkg "faiss"       "faiss-cpu>=1.7.4"
    reg_pkg "numpy"       "numpy>=1.24.0,<2.0.0"
    reg_pkg "pydantic"    "pydantic>=2.0.0"
    reg_pkg "rank_bm25"   "rank-bm25>=0.2.2"
    reg_pkg "docx"        "python-docx>=1.1.0"

    local PKG_TOTAL=${#PKG_FOLDERS[@]}
    local SKIP_COUNT=0 NEED_COUNT=0 FAIL_COUNT=0

    # ── Scan ─────────────────────────────────────────────────
    local INSTALL_FOLDERS=() INSTALL_SPECS=()
    for (( i=0; i<PKG_TOTAL; i++ )); do
        if "$PY" -c "import ${PKG_FOLDERS[$i]}" &>/dev/null 2>&1; then
            (( SKIP_COUNT++ )) || true
        else
            INSTALL_FOLDERS+=("${PKG_FOLDERS[$i]}")
            INSTALL_SPECS+=("${PKG_SPECS[$i]}")
            (( NEED_COUNT++ )) || true
        fi
    done

    echo "============================================================"
    echo "  Package Status"
    echo "============================================================"
    echo "  Total registered : $PKG_TOTAL"
    echo "  Already installed: $SKIP_COUNT"
    echo "  To install       : $NEED_COUNT"
    echo "============================================================"
    echo ""

    # ── Show skipped ─────────────────────────────────────────
    if [[ $SKIP_COUNT -gt 0 ]]; then
        echo "  Already installed:"
        echo ""
        local SI=0
        for (( i=0; i<PKG_TOTAL; i++ )); do
            if "$PY" -c "import ${PKG_FOLDERS[$i]}" &>/dev/null 2>&1; then
                (( SI++ )) || true
                progress_bar "$SI" "$SKIP_COUNT" "${PKG_FOLDERS[$i]}" skip
            fi
        done
        echo ""
    fi

    # ── Install missing ───────────────────────────────────────
    if [[ $NEED_COUNT -eq 0 ]]; then
        echo "  All packages already up to date."
        echo ""
        return
    fi

    echo "  Installing $NEED_COUNT missing package(s):"
    echo ""
    local INST_TOTAL=${#INSTALL_FOLDERS[@]}
    for (( i=0; i<INST_TOTAL; i++ )); do
        local STEP=$(( i + 1 ))
        progress_bar "$STEP" "$INST_TOTAL" "${INSTALL_FOLDERS[$i]}" working

        if "$PY" -m pip install "${INSTALL_SPECS[$i]}" --quiet &>/dev/null 2>&1; then
            progress_bar "$STEP" "$INST_TOTAL" "${INSTALL_FOLDERS[$i]}" ok
        else
            progress_bar "$STEP" "$INST_TOTAL" "${INSTALL_FOLDERS[$i]}" fail
            (( FAIL_COUNT++ )) || true
        fi
    done

    echo ""
    if [[ $FAIL_COUNT -gt 0 ]]; then
        echo -e "  [${YELLOW}WARNING${RESET}] $FAIL_COUNT package(s) failed."
        echo "            Check internet connection or run with sudo."
        echo ""
    else
        echo -e "  [${GREEN}OK${RESET}] All $NEED_COUNT package(s) installed successfully."
        echo ""
    fi
}

# ─────────────────────────────────────────────────────────────
# LLAMA-CPP  (pre-built wheel in ./wheels/)
# ─────────────────────────────────────────────────────────────
install_llama_cpp() {
    echo "============================================================"
    echo "  llama_cpp Wheel Status"
    echo "============================================================"
    echo ""

    # ── Step 1: Already installed? ────────────────────────────
    if "$PY" -c "from llama_cpp import Llama" &>/dev/null 2>&1; then
        echo -e "  [STATUS] llama_cpp install  >>  Already installed"
        echo -e "  [STATUS] Import check       >>  PASSED"
        echo ""
        progress_bar 1 1 "llama_cpp" skip
        echo ""
        return
    fi

    echo -e "  [STATUS] llama_cpp install  >>  NOT installed"
    echo -e "  [STATUS] Scanning wheels folder ..."
    echo    "  Wheels folder : $WHEELS"
    echo ""

    mkdir -p "$WHEELS"

    # ── Step 2: Dynamic wheel detection ───────────────────────
    local WHEEL_PATH=""
    for whl in "$WHEELS"/llama_cpp_python-*.whl; do
        [[ -f "$whl" ]] && WHEEL_PATH="$whl" && break
    done

    # ── Step 3: Wheel file status ─────────────────────────────
    if [[ -z "$WHEEL_PATH" ]]; then
        echo -e "  [STATUS] Wheel file   >>  ${RED}NOT FOUND${RESET}"
        echo ""
        echo "  +------------------------------------------------------+"
        echo "  |  WHEEL NOT FOUND                                     |"
        echo "  |  Download from:                                      |"
        echo "  |  github.com/abetlen/llama-cpp-python/releases        |"
        echo "  |  Pick the .whl matching your Python & OS:            |"
        echo "  |    Linux : llama_cpp_python-*-linux_x86_64.whl       |"
        echo "  |    macOS : llama_cpp_python-*-macosx_*.whl           |"
        echo "  |  Save to : $WHEELS/"
        echo "  +------------------------------------------------------+"
        echo ""
        exit 1
    fi

    echo -e "  [STATUS] Wheel file   >>  ${GREEN}FOUND${RESET}"
    echo    "  Path : $WHEEL_PATH"
    echo ""

    # ── Step 4: METHOD 1 -- pip install (with deps) ───────────
    echo "  [METHOD 1] pip install (with dependencies) ..."
    echo ""
    progress_bar 0 1 "llama_cpp" working

    local PIP_LOG="$ROOT/llama_pip_error.log"

    if "$PY" -m pip install "$WHEEL_PATH" --quiet > "$PIP_LOG" 2>&1; then
        rm -f "$PIP_LOG"
        if "$PY" -c "from llama_cpp import Llama" &>/dev/null 2>&1; then
            progress_bar 1 1 "llama_cpp" ok
            echo ""
            echo -e "  [STATUS] Wheel extracted  >>  ${GREEN}SUCCESS${RESET}  (pip method)"
            echo -e "  [STATUS] Import check     >>  ${GREEN}PASSED${RESET}   (from llama_cpp import Llama)"
            echo ""
            return
        else
            progress_bar 1 1 "llama_cpp" fail
            echo ""
            echo -e "  [STATUS] pip install OK but import ${RED}FAILED${RESET}"
            echo    "  [TIP]    Wheel platform mismatch -- check Python version & OS arch"
            exit 1
        fi
    fi

    # pip failed -- show real error
    progress_bar 1 1 "llama_cpp" fail
    echo ""
    echo -e "  [STATUS] pip install  >>  ${RED}FAILED${RESET}"
    echo    "  --------------------------------------------------------"
    echo    "  pip error output:"
    echo    "  --------------------------------------------------------"
    cat "$PIP_LOG"
    rm -f "$PIP_LOG"
    echo    "  --------------------------------------------------------"
    echo ""

    # ── Step 5: METHOD 2 -- unzip fallback ───────────────────
    echo "  [METHOD 2] Trying unzip extraction fallback ..."
    echo ""
    progress_bar 0 1 "llama_cpp" working

    local UNZIP_OK=false
    if command -v unzip &>/dev/null; then
        unzip -q "$WHEEL_PATH" -d "$SITE" && UNZIP_OK=true
    elif command -v python3 &>/dev/null; then
        "$PY" -c "import zipfile, sys; zipfile.ZipFile('$WHEEL_PATH').extractall('$SITE')" \
            &>/dev/null && UNZIP_OK=true
    fi

    if $UNZIP_OK && "$PY" -c "from llama_cpp import Llama" &>/dev/null 2>&1; then
        progress_bar 1 1 "llama_cpp" ok
        echo ""
        echo -e "  [STATUS] Wheel extracted  >>  ${GREEN}SUCCESS${RESET}  (unzip method)"
        echo -e "  [STATUS] Import check     >>  ${GREEN}PASSED${RESET}   (from llama_cpp import Llama)"
        echo ""
        return
    fi

    progress_bar 1 1 "llama_cpp" fail
    echo ""
    echo -e "  [STATUS] Both methods  >>  ${RED}FAILED${RESET}"
    echo ""
    echo    "  Manual fix -- run this yourself:"
    echo    "  $PY -m pip install \"$WHEEL_PATH\""
    echo ""
    exit 1
}

# ─────────────────────────────────────────────────────────────
# VERIFY KEY IMPORTS
# ─────────────────────────────────────────────────────────────
verify_imports() {
    echo "============================================================"
    echo "  Verifying Imports"
    echo "============================================================"
    echo ""

    local V_FAIL=0
    local IMPORTS=("fastapi"  "uvicorn"  "multipart"      "aiofiles"  "fitz"          "faiss"     "numpy"  "pydantic"  "rank_bm25"  "docx"        "llama_cpp")
    local LABELS=( "fastapi"  "uvicorn"  "python-multipart" "aiofiles" "PyMuPDF (fitz)" "faiss-cpu" "numpy" "pydantic"  "rank-bm25"  "python-docx" "llama_cpp")

    for (( i=0; i<${#IMPORTS[@]}; i++ )); do
        if "$PY" -c "import ${IMPORTS[$i]}" &>/dev/null 2>&1; then
            echo -e "  [${GREEN} OK ${RESET}] ${LABELS[$i]}"
        else
            echo -e "  [${RED}FAIL${RESET}] ${LABELS[$i]}"
            (( V_FAIL++ )) || true
        fi
    done

    # llama_cpp needs deeper import check
    if "$PY" -c "from llama_cpp import Llama" &>/dev/null 2>&1; then
        echo -e "  [${GREEN} OK ${RESET}] llama_cpp (Llama class)"
    else
        echo -e "  [${RED}FAIL${RESET}] llama_cpp (Llama class)"
        (( V_FAIL++ )) || true
    fi

    echo ""
    if [[ $V_FAIL -gt 0 ]]; then
        echo -e "  [${YELLOW}WARNING${RESET}] $V_FAIL import(s) failed -- re-run setup or check errors above."
    else
        echo -e "  [${GREEN}OK${RESET}] All imports verified successfully."
    fi
    echo ""
}

# ─────────────────────────────────────────────────────────────
# CLEAN __pycache__  (remove stale bytecode from other Python versions)
# ─────────────────────────────────────────────────────────────
clean_pycache() {
    echo "============================================================"
    echo "  Cleaning __pycache__"
    echo "============================================================"
    echo ""

    local COUNT
    COUNT=$(find "$ROOT" -type d -name "__pycache__" 2>/dev/null | wc -l | tr -d ' ')

    if [[ "$COUNT" -eq 0 ]]; then
        echo -e "  [${CYAN}SKIP${RESET}] No __pycache__ folders found"
    else
        find "$ROOT" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
        echo -e "  [${GREEN}OK${RESET}] Removed $COUNT __pycache__ folder(s)"
        echo    "  [INFO] Stale .pyc files from Python 3.12 / 3.14 etc. cleared"
    fi
    echo ""
}

# ─────────────────────────────────────────────────────────────
# CREATE MODELS FOLDER
# ─────────────────────────────────────────────────────────────
create_models_dir() {
    if [[ ! -d "$ROOT/models" ]]; then
        mkdir -p "$ROOT/models"
        echo -e "[${GREEN}OK${RESET}] Created models/ folder"
    fi
}

# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
python_check
pip_check
install_packages
install_llama_cpp
verify_imports
clean_pycache
create_models_dir

echo ""
echo "============================================================"
echo "  ALL DONE -- Environment ready"
echo "  Root folder   : $ROOT/"
echo "  Models folder : $ROOT/models/"
echo "  Python        : $PY"
echo "  Wheels folder : $WHEELS/"
echo "  Run app with  : bash start.sh"
echo "============================================================"
echo ""
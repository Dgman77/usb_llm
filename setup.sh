#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Flash AI with RAG-- Setup (Linux / macOS)
# ─────────────────────────────────────────────────────────────
set -euo pipefail

# ── Colours ───────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

# ── Root = directory containing this script ───────────────────
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VENV_DIR="$ROOT/venv"
PY="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"
WHEELS="$ROOT/Wheels"
EXTRACT_DIR="$ROOT/extracted_wheels"
MODELS="$ROOT/models"

REQUIRED_PY_MAJOR=3
REQUIRED_PY_MINOR=11

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
ok()   { echo -e "  ${GREEN}[  OK  ]${RESET} $*"; }
skip() { echo -e "  ${CYAN}[ SKIP ]${RESET} $*"; }
fail() { echo -e "  ${RED}[ FAIL ]${RESET} $*"; }
info() { echo -e "  ${YELLOW}[ INFO ]${RESET} $*"; }
die()  { echo -e "\n${RED}[ERROR]${RESET} $*\n"; exit 1; }

# progress_bar  CURRENT  TOTAL  LABEL  STATUS(ok|skip|fail|working)
progress_bar() {
    local cur="$1" tot="$2" lbl="$3" sts="$4"
    local bar_w=28
    [[ $tot -eq 0 ]] && tot=1
    local fill=$(( cur * bar_w / tot ))
    local empty=$(( bar_w - fill ))
    local pct=$(( cur * 100 / tot ))
    local bar
    bar="$(printf '%0.s#' $(seq 1 $fill) 2>/dev/null || true)"
    bar+="$(printf '%0.s.' $(seq 1 $empty) 2>/dev/null || true)"
    local pad
    pad="$(printf '%-26s' "$lbl")"
    local badge
    case "$sts" in
        ok)      badge="${GREEN}[  OK  ]${RESET}" ;;
        skip)    badge="${CYAN}[ SKIP ]${RESET}" ;;
        fail)    badge="${RED}[ FAIL ]${RESET}" ;;
        working) badge="${YELLOW}[ .... ]${RESET}" ;;
        *)       badge="[      ]" ;;
    esac
    printf "  [%-${bar_w}s] %3d%%  (%3d/%d)  %-26s  " "$bar" "$pct" "$cur" "$tot" "$lbl"
    echo -e "$badge"
}

# ─────────────────────────────────────────────────────────────
# BANNER
# ─────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}============================================================${RESET}"
echo -e "${BOLD}  Flash AI with RAG-- Setup   |   Root: $ROOT${RESET}"
echo -e "${BOLD}============================================================${RESET}"
echo

# ─────────────────────────────────────────────────────────────
# DETECT OS
# ─────────────────────────────────────────────────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"
echo -e "  Platform : $OS / $ARCH"

# ─────────────────────────────────────────────────────────────
# FIND SYSTEM PYTHON 3.11
# ─────────────────────────────────────────────────────────────
SYS_PY=""
for candidate in python3.11 python3 python; do
    if command -v "$candidate" &>/dev/null; then
        ver="$("$candidate" -c 'import sys; print(sys.version_info[:2])'  2>/dev/null || true)"
        maj="$("$candidate" -c 'import sys; print(sys.version_info[0])'  2>/dev/null || true)"
        min="$("$candidate" -c 'import sys; print(sys.version_info[1])'  2>/dev/null || true)"
        if [[ "$maj" == "$REQUIRED_PY_MAJOR" && "$min" -ge "$REQUIRED_PY_MINOR" ]]; then
            SYS_PY="$(command -v "$candidate")"
            echo -e "  Python   : $SYS_PY  ($maj.$min)"
            break
        fi
    fi
done

if [[ -z "$SYS_PY" ]]; then
    echo
    echo -e "${RED}[ERROR]${RESET} Python 3.11+ not found."
    echo
    echo "  Install it with one of:"
    echo
    if [[ "$OS" == "Darwin" ]]; then
        echo "    brew install python@3.11"
        echo "    or: https://www.python.org/downloads/macos/"
    else
        echo "    sudo apt  install python3.11 python3.11-venv   # Debian/Ubuntu"
        echo "    sudo dnf  install python3.11                   # Fedora/RHEL"
        echo "    sudo pacman -S python                          # Arch"
        echo "    or: https://www.python.org/downloads/"
    fi
    echo
    exit 1
fi

# ─────────────────────────────────────────────────────────────
# CREATE / REUSE VIRTUALENV
# ─────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}============================================================${RESET}"
echo -e "${BOLD}  Virtual Environment${RESET}"
echo -e "${BOLD}============================================================${RESET}"
echo

if [[ -x "$PY" ]]; then
    skip "venv already exists at $VENV_DIR"
else
    info "Creating venv at $VENV_DIR ..."
    "$SYS_PY" -m venv "$VENV_DIR"
    ok "venv created"
fi

# Upgrade pip silently
"$PIP" install --upgrade pip --quiet
ok "pip up to date  ($("$PIP" --version | cut -d' ' -f2))"
echo

# ─────────────────────────────────────────────────────────────
# PACKAGE REGISTRY
# ─────────────────────────────────────────────────────────────
declare -a PKG_FOLDER=()
declare -a PKG_SPEC=()

reg_pkg() {
    PKG_FOLDER+=("$1")
    PKG_SPEC+=("$2")
}

reg_pkg  "fastapi"               "fastapi>=0.110.0"
reg_pkg  "uvicorn"               "uvicorn>=0.29.0"
reg_pkg  "multipart"             "python-multipart>=0.0.9"
reg_pkg  "aiofiles"              "aiofiles>=23.0.0"
reg_pkg  "fitz"                  "PyMuPDF>=1.23.0"
reg_pkg  "faiss"                 "faiss-cpu>=1.7.4"
reg_pkg  "numpy"                 "numpy>=1.24.0,<2.0.0"
reg_pkg  "pydantic"              "pydantic>=2.0.0"
reg_pkg  "rank_bm25"             "rank-bm25>=0.2.2"
reg_pkg  "docx"                  "python-docx"
reg_pkg  "sentence_transformers" "sentence-transformers>=2.2.0"
reg_pkg  "httpx"                 "httpx>=0.24.0"

PKG_TOTAL=${#PKG_FOLDER[@]}
SITE="$VENV_DIR/lib/python3.*/site-packages"

# ─────────────────────────────────────────────────────────────
# SCAN: installed vs. needed
# ─────────────────────────────────────────────────────────────
declare -a INSTALL_FOLDER=()
declare -a INSTALL_SPEC=()
SKIP_COUNT=0
NEED_COUNT=0

for (( i=0; i<PKG_TOTAL; i++ )); do
    folder="${PKG_FOLDER[$i]}"
    # Use pip show for reliable detection inside venv
    if "$PIP" show "${folder//_/-}" &>/dev/null 2>&1 || \
       "$PIP" show "$folder"          &>/dev/null 2>&1; then
        (( SKIP_COUNT++ )) || true
    else
        INSTALL_FOLDER+=("$folder")
        INSTALL_SPEC+=("${PKG_SPEC[$i]}")
        (( NEED_COUNT++ )) || true
    fi
done

echo -e "${BOLD}============================================================${RESET}"
echo -e "${BOLD}  Package Status${RESET}"
echo -e "${BOLD}============================================================${RESET}"
printf "  Total registered  : %d\n" "$PKG_TOTAL"
printf "  Already installed : %d\n" "$SKIP_COUNT"
printf "  To install        : %d\n" "$NEED_COUNT"
echo -e "${BOLD}============================================================${RESET}"
echo

# ── Show already-installed ─────────────────────────────────────
if [[ $SKIP_COUNT -gt 0 ]]; then
    echo "  Already installed:"
    echo
    si=0
    for (( i=0; i<PKG_TOTAL; i++ )); do
        folder="${PKG_FOLDER[$i]}"
        if "$PIP" show "${folder//_/-}" &>/dev/null 2>&1 || \
           "$PIP" show "$folder"          &>/dev/null 2>&1; then
            (( si++ )) || true
            progress_bar "$si" "$SKIP_COUNT" "$folder" skip
        fi
    done
    echo
fi

# ── Build single install command for all missing packages ─────────
FAIL_COUNT=0
if [[ ${#INSTALL_FOLDER[@]} -gt 0 ]]; then
    echo "  Installing ${#INSTALL_FOLDER[@]} missing package(s) in one batch:"
    echo


    progress_bar 1 ${#INSTALL_FOLDER[@]} "all packages" working

    if "$PIP" install "${INSTALL_SPEC[@]}" --quiet 2>/dev/null; then
        progress_bar ${#INSTALL_FOLDER[@]} ${#INSTALL_FOLDER[@]} "all packages" ok
        echo
    else
        progress_bar ${#INSTALL_FOLDER[@]} ${#INSTALL_FOLDER[@]} "all packages" fail
        echo
        echo -e "  ${RED}[ERROR]${RESET} Batch install failed -- some packages may be missing."
        echo "           Check the pip error message above."
        echo
        FAIL_COUNT=1
    fi

    # Summary
    if [[ $FAIL_COUNT -gt 0 ]]; then
        echo -e "  ${YELLOW}[WARNING]${RESET} Batch install failed -- some packages may be missing."
        echo "           Check the pip error message or internet connection."
        echo
    else
        ok "All ${#INSTALL_FOLDER[@]} package(s) installed successfully."
        echo
    fi
else
    echo "  All packages already up to date."
    echo
fi

# ─────────────────────────────────────────────────────────────
# LLAMA-CPP
# ─────────────────────────────────────────────────────────────
echo -e "${BOLD}============================================================${RESET}"
echo -e "${BOLD}  llama_cpp${RESET}"
echo -e "${BOLD}============================================================${RESET}"
echo

if "$PIP" show llama-cpp-python &>/dev/null 2>&1 && [[ -d "$EXTRACT_DIR/llama_cpp" ]]; then
    progress_bar 1 1 "llama_cpp" skip
    echo
else
    # ── Try local wheel first ──────────────────────────────────
    mkdir -p "$WHEELS"
    WHEEL_PATH=""
    for f in "$WHEELS"/llama_cpp_python-*.whl; do
        [[ -f "$f" ]] && WHEEL_PATH="$f" && break
    done

    if [[ -n "$WHEEL_PATH" ]]; then
        info "Found wheel: $WHEEL_PATH"
        echo
        progress_bar 0 1 "llama_cpp" working
        if "$PIP" install "$WHEEL_PATH" --quiet 2>/dev/null; then
            progress_bar 1 1 "llama_cpp" ok
            echo
            # Extract wheel to extracted_wheels/ for inspection/backup
            info "Extracting WHL to $EXTRACT_DIR/llama_cpp/ ..."
            mkdir -p "$EXTRACT_DIR/llama_cpp"
            if unzip -q "$WHEEL_PATH" -d "$EXTRACT_DIR/llama_cpp" 2>/dev/null; then
                ok "WHL extracted successfully"
            else
                if "$PY" -c "import zipfile; zipfile.ZipFile(r'$WHEEL_PATH').extractall(r'$EXTRACT_DIR/llama_cpp')" 2>/dev/null; then
                    ok "WHL extracted successfully (via Python zipfile)"
                else
                    fail "WHL extraction failed"
                fi
            fi
            echo
        else
            progress_bar 1 1 "llama_cpp" fail
            echo
            echo -e "  ${YELLOW}[HINT]${RESET} Wheel install failed -- the .whl may be for Windows only."
            echo "         Trying pip install from PyPI instead ..."
            echo
            goto_pypi=1
        fi
    else
        goto_pypi=1
    fi

    # ── Fallback: install from PyPI (CPU-only, no GPU) ─────────
    if [[ "${goto_pypi:-0}" == "1" ]]; then
        info "No compatible wheel found -- installing from PyPI (CPU build) ..."
        echo
        progress_bar 0 1 "llama_cpp" working

        # CMAKE_ARGS controls build flags; empty = CPU-only
        if CMAKE_ARGS="" "$PIP" install llama-cpp-python --quiet 2>/dev/null; then
            progress_bar 1 1 "llama_cpp" ok
            echo
        else
            progress_bar 1 1 "llama_cpp" fail
            echo
            echo -e "  ${RED}[ERROR]${RESET} llama_cpp install failed."
            echo
            echo "  Manual steps:"
            echo "    1. Activate venv:  source $VENV_DIR/bin/activate"
            echo "    2. Install:        pip install llama-cpp-python"
            echo "    3. Or download a pre-built wheel:"
            echo "       https://github.com/abetlen/llama-cpp-python/releases"
            echo "       Place the .whl in: $WHEELS/"
            echo "       Then re-run this script."
            echo
            exit 1
        fi
    fi
fi

# ─────────────────────────────────────────────────────────────
# VERIFY KEY IMPORTS
# ─────────────────────────────────────────────────────────────
echo -e "${BOLD}============================================================${RESET}"
echo -e "${BOLD}  Verifying Imports${RESET}"
echo -e "${BOLD}============================================================${RESET}"
echo

V_FAIL=0

verify_import() {
    local module="$1" label="$2"
    if "$PY" -c "import $module" 2>/dev/null; then
        ok "$label"
    else
        fail "$label"
        (( V_FAIL++ )) || true
    fi
}

verify_import fastapi          "fastapi"
verify_import uvicorn          "uvicorn"
verify_import fitz             "PyMuPDF (fitz)"
verify_import faiss            "faiss-cpu"
verify_import numpy            "numpy"
verify_import llama_cpp        "llama_cpp"

echo
if [[ $V_FAIL -gt 0 ]]; then
    echo -e "  ${YELLOW}[WARNING]${RESET} $V_FAIL import(s) failed -- re-run setup."
else
    ok "All imports verified successfully."
fi
echo

# ─────────────────────────────────────────────────────────────
# CREATE MODELS FOLDER & ACTIVATION HELPER
# ─────────────────────────────────────────────────────────────
mkdir -p "$MODELS"
ok "Models folder ready: $MODELS"

# Write a helper activate script so users can source it easily
ACTIVATE_HELPER="$ROOT/activate_env.sh"
cat > "$ACTIVATE_HELPER" <<ACTIVATESCRIPT
#!/usr/bin/env bash
# Source this file to activate the project venv:
#   source activate_env.sh
source "$VENV_DIR/bin/activate"
echo "venv activated -- python: \$(which python)"
ACTIVATESCRIPT
chmod +x "$ACTIVATE_HELPER"
ok "Activation helper: $ACTIVATE_HELPER"
echo

# ─────────────────────────────────────────────────────────────
echo -e "${BOLD}============================================================${RESET}"
echo -e "${BOLD}  ALL DONE${RESET}"
echo -e "${BOLD}============================================================${RESET}"
echo
echo "  Models folder : $MODELS"
echo "  Activate venv : source $VENV_DIR/bin/activate"
echo "  Start app     : bash start.sh"
echo
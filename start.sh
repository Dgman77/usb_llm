#!/usr/bin/env bash

# ============================================================

# LLM + RAG + Diagram Setup Script

# Linux / macOS / GitHub Codespaces

# ============================================================

set -uo pipefail

# ------------------------------------------------------------

# Colours

# ------------------------------------------------------------

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
RESET='\033[0m'

ok()   { echo -e "${GREEN}[ OK ]${RESET} $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $*"; }
err()  { echo -e "${RED}[ERR ]${RESET} $*" >&2; }
skip() { echo -e "${CYAN}[SKIP]${RESET} $*"; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/venv"
MODELS="$ROOT/models"
WHEELS="$ROOT/wheels"
STATIC="$ROOT/static"

mkdir -p "$MODELS" "$WHEELS" "$STATIC"

echo
echo "============================================================"
echo "  LLM with RAG and Diagram -- Setup"
echo "============================================================"
echo "  Root : $ROOT"
echo "============================================================"
echo

# ------------------------------------------------------------

# Downloader

# ------------------------------------------------------------

if command -v curl >/dev/null 2>&1; then
DOWNLOADER="curl"
ok "Downloader: curl"
elif command -v wget >/dev/null 2>&1; then
DOWNLOADER="wget"
ok "Downloader: wget"
else
err "Neither curl nor wget is installed."
exit 1
fi

download() {
local url="$1"
local output="$2"

```
if [[ "$DOWNLOADER" == "curl" ]]; then
    curl -L --progress-bar -o "$output" "$url"
else
    wget -q --show-progress -O "$output" "$url"
fi
```

}

# ------------------------------------------------------------

# Python Detection

# ------------------------------------------------------------

echo
echo "============================================================"
echo "  Python Check"
echo "============================================================"

SYS_PY=""

for p in python3.12 python3.11 python3.10 python3; do
if command -v "$p" >/dev/null 2>&1; then
SYS_PY="$(command -v "$p")"
break
fi
done

if [[ -z "$SYS_PY" ]]; then
err "Python 3 not found."
exit 1
fi

ok "Using Python: $SYS_PY"

if ! "$SYS_PY" -m venv --help >/dev/null 2>&1; then
err "Python venv module missing."
echo "Ubuntu/Debian:"
echo "sudo apt install python3-venv"
exit 1
fi

# ------------------------------------------------------------

# Create Virtual Environment

# ------------------------------------------------------------

if [[ -d "$VENV" ]]; then
skip "Virtualenv already exists at $VENV"
else
echo "Creating virtual environment..."
"$SYS_PY" -m venv "$VENV"
fi

if [[ ! -x "$VENV/bin/python" ]]; then
err "Virtual environment creation failed."
exit 1
fi

PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

ok "Virtualenv ready"

echo
echo "Updating pip..."
"$PIP" install --upgrade pip setuptools wheel

# ------------------------------------------------------------

# Python Packages

# ------------------------------------------------------------

PACKAGES=(
"fastapi>=0.110.0"
"uvicorn>=0.29.0"
"python-multipart>=0.0.9"
"aiofiles>=23.0.0"
"PyMuPDF>=1.23.0"
"faiss-cpu>=1.7.4"
"numpy>=1.24,<2"
"pydantic>=2.0"
"python-docx>=1.1.0"
"openpyxl>=3.1.0"
"python-pptx>=0.6.21"
"beautifulsoup4>=4.12.0"
"striprtf>=0.0.26"
"Pillow>=10.0.0"
"graphviz>=0.20.1"
)

echo
echo "============================================================"
echo "  Installing Python Packages"
echo "============================================================"

FAIL_COUNT=0

for pkg in "${PACKAGES[@]}"; do
echo "Installing: $pkg"

```
if "$PIP" install "$pkg" --quiet; then
    ok "$pkg"
else
    warn "$pkg failed"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi
```

done

if [[ $FAIL_COUNT -gt 0 ]]; then
warn "$FAIL_COUNT package(s) failed."
fi

# ------------------------------------------------------------

# llama_cpp

# ------------------------------------------------------------

echo
echo "============================================================"
echo "  llama_cpp"
echo "============================================================"

if "$PY" -c "from llama_cpp import Llama" >/dev/null 2>&1; then
skip "llama_cpp already installed"
else

```
WHEEL=""

PYTAG=$("$PY" -c 'import sys; print(f"cp{sys.version_info.major}{sys.version_info.minor}")')

for f in "$WHEELS"/*"$PYTAG"*.whl; do
    [[ -f "$f" ]] && WHEEL="$f" && break
done

if [[ -n "$WHEEL" ]]; then
    echo "Installing wheel: $WHEEL"

    if "$PIP" install "$WHEEL"; then
        ok "llama_cpp installed"
    else
        warn "Failed to install llama_cpp wheel"
    fi
else
    warn "No compatible llama_cpp wheel found in $WHEELS"
fi
```

fi

# ------------------------------------------------------------

# Graphviz Binary

# ------------------------------------------------------------

echo
echo "============================================================"
echo "  Graphviz"
echo "============================================================"

if command -v dot >/dev/null 2>&1; then
ok "$(dot -V 2>&1)"
else
OS="$(uname -s)"

```
if [[ "$OS" == "Linux" ]]; then

    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y graphviz

    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y graphviz

    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --noconfirm graphviz
    fi

elif [[ "$OS" == "Darwin" ]]; then

    if command -v brew >/dev/null 2>&1; then
        brew install graphviz
    fi
fi
```

fi

# ------------------------------------------------------------

# Viz.js

# ------------------------------------------------------------

echo
echo "============================================================"
echo "  Viz.js"
echo "============================================================"

VIZ_VERSION="3.4.0"
VIZ_JS="$STATIC/viz-standalone.js"

if [[ -f "$VIZ_JS" ]]; then
skip "Viz.js already exists"
else
download 
"https://unpkg.com/@viz-js/viz@${VIZ_VERSION}/lib/viz-standalone.js" 
"$VIZ_JS"

```
ok "Viz.js downloaded"
```

fi

if command -v npm >/dev/null 2>&1; then
if [[ ! -d "$ROOT/node_modules/@viz-js/viz" ]]; then
npm install "@viz-js/viz@$VIZ_VERSION" --prefix "$ROOT"
fi
fi

# ------------------------------------------------------------

# Verify Imports

# ------------------------------------------------------------

echo
echo "============================================================"
echo "  Verifying Imports"
echo "============================================================"

MODULES=(
fastapi
uvicorn
multipart
aiofiles
fitz
faiss
numpy
pydantic
docx
graphviz
)

VERIFY_FAIL=0

for mod in "${MODULES[@]}"; do
if "$PY" -c "import $mod" >/dev/null 2>&1; then
ok "$mod"
else
warn "$mod"
VERIFY_FAIL=$((VERIFY_FAIL + 1))
fi
done

if "$PY" -c "from llama_cpp import Llama" >/dev/null 2>&1; then
ok "llama_cpp"
else
warn "llama_cpp"
fi

# ------------------------------------------------------------

# Models

# ------------------------------------------------------------

echo
echo "============================================================"
echo "  Models"
echo "============================================================"

EMBED_MODEL="$MODELS/nomic-embed-text-v1.5.Q8_0.gguf"

if [[ ! -f "$EMBED_MODEL" ]]; then
echo "Downloading embedding model..."
download 
"https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q8_0.gguf" 
"$EMBED_MODEL"
else
skip "Embedding model already exists"
fi

RERANK_MODEL="$MODELS/bge-reranker-v2-m3-Q8_0.gguf"

if [[ ! -f "$RERANK_MODEL" ]]; then
echo "Downloading reranker model..."
download 
"https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF/resolve/main/bge-reranker-v2-m3-Q8_0.gguf" 
"$RERANK_MODEL"
else
skip "Reranker model already exists"
fi

# ------------------------------------------------------------

# Finish

# ------------------------------------------------------------

echo
echo "============================================================"
echo "  SETUP COMPLETE"
echo "============================================================"
echo "Python : $PY"
echo "Venv   : $VENV"
echo "Models : $MODELS"
echo
echo "Activate manually:"
echo "source $VENV/bin/activate"
echo
echo "Run:"
echo "./start.sh"
echo "============================================================"

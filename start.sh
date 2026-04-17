#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────
# ROOT DETECTION (portable-safe)
# ─────────────────────────────────────────────
ROOT="$(cd "$(dirname "$0")" && pwd)"
DRIVE="$(df "$ROOT" | awk 'NR==2 {print $1}')"
BACKEND="$ROOT/backend"
WAITER="$ROOT/wait_for_server.py"

echo
echo "==============================================="
echo "  DiagramAI -- Offline AI (Portable Mode)"
echo "==============================================="
echo
echo "USB Drive : $DRIVE"
echo "USB Root  : $ROOT"
echo

# ─────────────────────────────────────────────
# FIND PYTHON (STRICT)
# ─────────────────────────────────────────────
PYTHON=""

if [ -x "$ROOT/python/python" ]; then
    PYTHON="$ROOT/python/python"
elif [ -x "$ROOT/venv/bin/python" ]; then
    PYTHON="$ROOT/venv/bin/python"
fi

if [ -z "$PYTHON" ]; then
    echo "[ERROR] Portable Python NOT FOUND"
    echo "Expected: $ROOT/python/python"
    exit 1
fi

echo "[OK] Python: $PYTHON"

# ─────────────────────────────────────────────
# HARD ISOLATION (CRITICAL)
# ─────────────────────────────────────────────
PY_DIR="$(dirname "$PYTHON")"
PY_SCRIPTS="$PY_DIR/Scripts"

export PATH="$PY_DIR:$PY_SCRIPTS"
export PYTHONHOME="$PY_DIR"
export PYTHONNOUSERSITE=1
unset PYTHONPATH
export PYTHONEXECUTABLE="$PYTHON"

echo "[OK] Environment isolated"
echo

# ─────────────────────────────────────────────
# MODEL DETECTION (ROBUST)
# ─────────────────────────────────────────────
MODEL_PATH=""

mkdir -p "$ROOT/models"

if [ -f "$ROOT/models/model_path.txt" ]; then
    MODEL_PATH="$(cat "$ROOT/models/model_path.txt")"
    [ -f "$MODEL_PATH" ] || MODEL_PATH=""
fi

if [ -z "$MODEL_PATH" ]; then
    MODEL_PATH="$(ls "$ROOT"/models/*.gguf 2>/dev/null | head -n 1 || true)"
fi

if [ -z "$MODEL_PATH" ]; then
    echo
    echo "[ERROR] No .gguf model found!"
    echo
    echo "Put your model inside:"
    echo "$ROOT/models/"
    echo
    echo "Example:"
    echo "$ROOT/models/Phi-3-mini-4k-instruct-q4.gguf"
    echo
    exit 1
fi

echo "[OK] Model: $MODEL_PATH"
echo "$MODEL_PATH" > "$ROOT/models/model_path.txt"

export DIAGRAMAI_MODEL="$MODEL_PATH"
export DIAGRAMAI_ROOT="$ROOT"

echo

# ─────────────────────────────────────────────
# CHECK REQUIRED FILES
# ─────────────────────────────────────────────
if [ ! -f "$BACKEND/main.py" ]; then
    echo "[ERROR] Backend not found: $BACKEND/main.py"
    exit 1
fi

if [ ! -f "$WAITER" ]; then
    echo "[ERROR] Missing: wait_for_server.py"
    exit 1
fi

# ─────────────────────────────────────────────
# START SERVER
# ─────────────────────────────────────────────
cd "$BACKEND"

echo "[1/3] Starting server..."
echo

"$PYTHON" -m uvicorn main:app --host 0.0.0.0 --port 8787 &
SERVER_PID=$!

# ─────────────────────────────────────────────
# WAIT FOR SERVER
# ─────────────────────────────────────────────
echo
echo "+----------------------------------------------+"
echo "|  [2/3] Loading AI model into memory...       |"
echo "|                                              |"
echo "|  Takes 1-3 minutes. Please wait.             |"
echo "|  DO NOT close this window                    |"
echo "+----------------------------------------------+"
echo

"$PYTHON" "$WAITER"
WAIT_RESULT=$?

if [ $WAIT_RESULT -ne 0 ]; then
    echo
    echo "+----------------------------------------------+"
    echo "   SERVER FAILED TO START"
    echo "+----------------------------------------------+"
    echo
    echo "Python used  : $PYTHON"
    echo "Model path   : $MODEL_PATH"
    echo
    kill $SERVER_PID || true
    exit 1
fi

# ─────────────────────────────────────────────
# OPEN BROWSER
# ─────────────────────────────────────────────
echo "[3/3] Opening browser..."
echo

xdg-open "http://localhost:8787" >/dev/null 2>&1 || open "http://localhost:8787"

echo "+----------------------------------------------+"
echo "  Running at: http://localhost:8787"
echo "  Press Ctrl+C to STOP"
echo "+----------------------------------------------+"

wait $SERVER_PID

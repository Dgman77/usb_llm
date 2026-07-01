#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Flash AI with RAG -- Offline AI (Linux / macOS Startup Script)
# ─────────────────────────────────────────────────────────────

set -euo pipefail

# Colors
GREEN="\033[0;32m"
YELLOW="\033[1;33"
RED="\033[0;31m"
RESET="\033[0m"

ok()   { echo -e "${GREEN}[OK]${RESET} $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $*"; }
err()  { echo -e "${RED}[ERROR]${RESET} $*" >&2; }

# Root detection
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
WAITER="$ROOT/wait_for_server.py"

echo
echo "==============================================="
echo "  Flash AI with RAG  -- Offline AI (Startup)"
echo "==============================================="
echo "  Root Folder : $ROOT"
echo

# 1. Find Python inside virtual environment
PYTHON="$ROOT/venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    err "Virtual environment Python not found at: $PYTHON"
    err "Please run ./setup.sh first to build the environment."
    exit 1
fi
ok "Python: $PYTHON"

# 2. Scan models folder for a chat model
MODEL_PATH=""
MODELS_DIR="$ROOT/models"

if [[ -f "$MODELS_DIR/model_path.txt" ]]; then
    SAVED_PATH=$(cat "$MODELS_DIR/model_path.txt" | xargs)
    if [[ -n "$SAVED_PATH" && -f "$SAVED_PATH" ]]; then
        MODEL_PATH="$SAVED_PATH"
    fi
fi

if [[ -z "$MODEL_PATH" ]]; then
    # Look for any GGUF file in models/ directory, excluding embed/rerank/nomic models
    for f in "$MODELS_DIR"/*.gguf; do
        if [[ -f "$f" ]]; then
            filename=$(basename "$f" | tr '[:upper:]' '[:lower:]')
            if [[ ! "$filename" =~ (embed|rerank|nomic) ]]; then
                MODEL_PATH="$f"
                break
            fi
        fi
    done
fi

if [[ -z "$MODEL_PATH" ]]; then
    err "No chat model (.gguf) found in: $MODELS_DIR"
    err "Please drop a chat model GGUF file into the models/ folder and restart."
    exit 1
fi

ok "Chat Model: $(basename "$MODEL_PATH")"

# Save path for next time
echo "$MODEL_PATH" > "$MODELS_DIR/model_path.txt"

export FLASH_AI_MODEL="$MODEL_PATH"
export FLASH_AI_ROOT="$ROOT"

# 3. Check backend files
if [[ ! -f "$BACKEND/main.py" ]]; then
    err "Backend entrypoint main.py not found at: $BACKEND/main.py"
    exit 1
fi

# 4. Start Server
cd "$BACKEND"

echo "[1/3] Starting server..."
"$PYTHON" -m uvicorn main:app --host 0.0.0.5 --port 8787 --log-level warning &
SERVER_PID=$!

# Ensure server stops on exit
cleanup() {
    echo
    echo "[Stopping server...]"
    kill $SERVER_PID 2>/dev/null || true
    echo "[Done] Server stopped."
}
trap cleanup EXIT

# 5. Wait for Server to be ready
echo
echo "+----------------------------------------------+"
echo "|  [2/3] Loading AI model into memory...      |"
echo "|                                              |"
echo "|  This takes 1-3 minutes. Please wait.        |"
echo "|  DO NOT close this window.                   |"
echo "+----------------------------------------------+"
echo

if ! "$PYTHON" "$WAITER"; then
    err "Server failed to start or verify."
    exit 1
fi

# 6. Open Browser
echo "[3/3] Opening browser..."
URL="http://localhost:8787"

if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL"
elif command -v open >/dev/null 2>&1; then
    open "$URL"
else
    ok "Running at: $URL (Please open manually)"
fi

echo
echo "+----------------------------------------------+"
echo "  Running at: http://localhost:8787"
echo "  Press Ctrl+C to STOP the server"
echo "+----------------------------------------------+"
echo

# Wait for Ctrl+C
while true; do
    sleep 1
done

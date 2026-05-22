#!/usr/bin/env bash
# start_local.sh — boot the full local Omi backend stack.
#
# Starts (in order):
#   1. Qdrant      — Docker container 'omi-qdrant' on port 6333
#   2. Ollama      — LLM runtime on port 11434
#   3. FastAPI     — uvicorn main_local:app on 0.0.0.0:8088 (all interfaces)
#
# Usage:
#   ./start_local.sh                      # default — binds all interfaces, port 8088
#   ./start_local.sh --port 9000          # custom port
#   ./start_local.sh --host 127.0.0.1     # localhost-only (no LAN access)
#
# The script exits on the first error (set -e).  Ctrl-C stops uvicorn;
# Qdrant and Ollama keep running in the background (by design).
# To stop everything: ./stop_local.sh  (or see the individual commands below).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=8088
HOST=0.0.0.0

# PyTorch and ctranslate2 (used by faster-whisper) both bundle their own
# OpenMP runtime. On macOS this causes an abort unless this flag is set.
export KMP_DUPLICATE_LIB_OK=TRUE

# ── Parse args ─────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --host) HOST="$2"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

# ── Helpers ────────────────────────────────────────────────────────────────────
ok()   { echo "[ok]  $*"; }
info() { echo "[..] $*"; }
fail() { echo "[err] $*" >&2; exit 1; }

# ── 1. Docker / Qdrant ─────────────────────────────────────────────────────────
info "Checking Docker …"
if ! docker info >/dev/null 2>&1; then
    info "Docker not running — attempting to start …"
    if open -a "Docker Desktop" 2>/dev/null || open -a "Docker" 2>/dev/null; then
        echo "     Waiting up to 60 s for Docker to start …"
        for i in $(seq 1 30); do
            sleep 2
            docker info >/dev/null 2>&1 && break
            if [[ $i -eq 30 ]]; then
                fail "Docker did not start within 60 s.
       If Docker Desktop is not installed, install it from https://www.docker.com/products/docker-desktop/
       Or install Docker CLI only: brew install docker colima && colima start
       Then retry: bash start_local.sh"
            fi
        done
    else
        fail "Docker is not running and could not be auto-started.
       Install Docker Desktop: https://www.docker.com/products/docker-desktop/
       Or: brew install docker colima && colima start
       Then retry: bash start_local.sh"
    fi
fi
ok "Docker is running"

info "Starting Qdrant …"
if docker ps --filter name=omi-qdrant --filter status=running --format '{{.Names}}' | grep -q omi-qdrant; then
    ok "Qdrant already running"
elif docker ps -a --filter name=omi-qdrant --format '{{.Names}}' | grep -q omi-qdrant; then
    docker start omi-qdrant >/dev/null
    ok "Qdrant container started"
else
    # First boot — create with a named volume so data survives container recreation.
    info "Creating omi-qdrant container (first run) …"
    docker run -d --name omi-qdrant \
        -p 6333:6333 -p 6334:6334 \
        -v omi_qdrant_storage:/qdrant/storage \
        qdrant/qdrant:latest >/dev/null
    ok "Qdrant container created and started"
fi

# Give Qdrant a moment to accept connections.
for i in $(seq 1 10); do
    curl -sf "${QDRANT_URL:-http://localhost:6333}/healthz" >/dev/null 2>&1 && break
    [[ $i -eq 10 ]] && fail "Qdrant did not become healthy within 10 s"
    sleep 1
done
ok "Qdrant healthy at ${QDRANT_URL:-http://localhost:6333}"

# Read env vars from .env if not already in the environment.
_read_env_var() {
    local var="$1"
    local val="${!var:-}"
    if [[ -z "$val" ]] && [[ -f "$SCRIPT_DIR/.env" ]]; then
        val=$(grep -E "^${var}=" "$SCRIPT_DIR/.env" | cut -d= -f2- | tr -d '"'"'" | head -1)
    fi
    echo "${val:-}"
}

# ── 2. Ollama ──────────────────────────────────────────────────────────────────
OLLAMA_HOST="$(_read_env_var OLLAMA_HOST)"
OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"

# Determine if Ollama is local or remote.
_ollama_is_local() {
    echo "$OLLAMA_HOST" | grep -qE "localhost|127\.0\.0\.1"
}

info "Checking Ollama at $OLLAMA_HOST …"
if curl -sf "$OLLAMA_HOST/api/version" >/dev/null 2>&1; then
    ok "Ollama reachable"
elif _ollama_is_local; then
    info "Starting local Ollama …"
    if open -a Ollama 2>/dev/null; then
        echo "     Waiting up to 30 s for Ollama daemon …"
        for i in $(seq 1 15); do
            sleep 2
            curl -sf "$OLLAMA_HOST/api/version" >/dev/null 2>&1 && break
            [[ $i -eq 15 ]] && fail "Ollama did not start within 30 s. Run 'open -a Ollama' and retry."
        done
        ok "Ollama started"
    elif command -v ollama >/dev/null 2>&1; then
        ollama serve >/tmp/ollama.log 2>&1 &
        echo "     Waiting up to 30 s for Ollama daemon …"
        for i in $(seq 1 15); do
            sleep 2
            curl -sf "$OLLAMA_HOST/api/version" >/dev/null 2>&1 && break
            [[ $i -eq 15 ]] && fail "Ollama did not start. Check /tmp/ollama.log."
        done
        ok "Ollama started (headless)"
    else
        fail "Ollama not found at $OLLAMA_HOST and no local install found."
    fi
else
    fail "Remote Ollama at $OLLAMA_HOST is not reachable. Check that it is running and accessible on the network."
fi

# Model verification — skip pull for remote hosts (can't manage remote model stores).
OLLAMA_MODEL="$(_read_env_var OLLAMA_MODEL)"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:0.6b}"
OLLAMA_CHAT_MODEL="$(_read_env_var OLLAMA_CHAT_MODEL)"
OLLAMA_EXTRACT_MODEL="$(_read_env_var OLLAMA_EXTRACT_MODEL)"

_ollama_has_model() {
    # Query the Ollama API directly — works for both local and remote hosts.
    local model="$1"
    curl -sf "$OLLAMA_HOST/api/tags" 2>/dev/null | grep -qF "\"$model\""
}

_seen_models=""
for _m in "$OLLAMA_MODEL" "$OLLAMA_CHAT_MODEL" "$OLLAMA_EXTRACT_MODEL"; do
    [[ -z "$_m" ]] && continue
    echo "$_seen_models" | grep -qF "|${_m}|" && continue
    _seen_models="${_seen_models}|${_m}|"

    if _ollama_has_model "$_m"; then
        ok "Model '$_m' present on Ollama server"
    elif _ollama_is_local; then
        info "Model '$_m' not found — pulling …"
        if ( ollama pull "$_m" ); then
            ok "Model '$_m' ready"
        else
            echo "[warn] Pull failed for '$_m'. If the model store is read-only, add it from a machine with write access."
        fi
    else
        echo "[warn] Model '$_m' not found on remote Ollama at $OLLAMA_HOST."
        echo "       Add it on that machine with: ollama pull $_m"
    fi
done

# ── 3. FastAPI ─────────────────────────────────────────────────────────────────
info "Activating conda env 'omilocal' …"
CONDA_BASE="$(conda info --base 2>/dev/null || echo /opt/miniconda3)"
# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate omilocal

cd "$SCRIPT_DIR"

LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "")

echo ""
echo "════════════════════════════════════════════════════"
echo "  Omi local backend"
if [[ -n "$LAN_IP" ]]; then
    echo "  API            →  http://${LAN_IP}:$PORT"
    echo "  Swagger UI     →  http://${LAN_IP}:$PORT/docs"
else
    echo "  API            →  http://localhost:$PORT  (LAN IP not detected — Wi-Fi connected?)"
    echo "  Swagger UI     →  http://localhost:$PORT/docs"
fi
echo "  Ctrl-C to stop the API (Qdrant + Ollama keep running)"
echo "════════════════════════════════════════════════════"
echo ""

exec uvicorn main_local:app --host "$HOST" --port "$PORT" --reload

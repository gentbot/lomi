#!/usr/bin/env bash
# One-shot launcher: activate omilocal, ensure deps, fetch a JWT, run the bridge.
#
#   ./run.sh                                              # uses OMI_EMAIL / OMI_PASSWORD env
#   OMI_EMAIL=you@omi.dev OMI_PASSWORD=hunter2 ./run.sh
#   ./run.sh --scan-only                                  # passes through to pin_bridge.py
#   ./run.sh --thin --backend ws://<YOUR_SERVER_IP>:8088    # remote backend, no local Opus decode
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Pre-scan args so we can configure login/deps before handing off ──────────
_thin=false
_backend=""
_args=("$@")
for ((i = 0; i < ${#_args[@]}; i++)); do
  case "${_args[$i]}" in
    --thin) _thin=true ;;
    --backend=*) _backend="${_args[$i]#--backend=}" ;;
    --backend)
      if ((i + 1 < ${#_args[@]})); then
        _backend="${_args[$((i + 1))]}"
      fi
      ;;
  esac
done

# If --backend was passed, derive the HTTP base URL for login.sh automatically.
# ws://host:port  →  http://host:port
# wss://host:port →  https://host:port
if [[ -n "$_backend" && -z "${OMI_LOCAL_BACKEND_HTTP:-}" ]]; then
  _http="${_backend/ws:\/\//http://}"
  _http="${_http/wss:\/\//https://}"
  export OMI_LOCAL_BACKEND_HTTP="$_http"
  echo "[run.sh] derived OMI_LOCAL_BACKEND_HTTP=$OMI_LOCAL_BACKEND_HTTP"
fi

# 1. Activate the conda env. Path is the same one main_local uses.
if ! command -v conda >/dev/null 2>&1; then
  if [[ -f "$(brew --prefix miniforge 2>/dev/null)/etc/profile.d/conda.sh" ]]; then
    # shellcheck disable=SC1091
    source "$(brew --prefix miniforge)/etc/profile.d/conda.sh"
  elif [[ -f "$HOME/miniforge3/etc/profile.d/conda.sh" ]]; then
    # shellcheck disable=SC1091
    source "$HOME/miniforge3/etc/profile.d/conda.sh"
  else
    echo "conda not found. See SETUP_FROM_SCRATCH.md to install Miniforge." >&2
    exit 1
  fi
fi
conda activate omilocal

# 2. Ensure pip deps — skip opuslib in thin mode (backend decodes Opus instead).
if $_thin; then
  python -m pip install --quiet bleak websockets
else
  python -m pip install --quiet bleak opuslib websockets
fi

# 3. If no token in env, log in to fetch one.
if [[ -z "${OMI_LOCAL_JWT:-}" ]]; then
  if [[ -z "${OMI_EMAIL:-}" || -z "${OMI_PASSWORD:-}" ]]; then
    echo "Set OMI_EMAIL and OMI_PASSWORD, or pass --token directly to pin_bridge.py" >&2
    exit 64
  fi
  export OMI_LOCAL_JWT="$("$HERE/login.sh")"
  echo "[run.sh] obtained JWT (length=${#OMI_LOCAL_JWT})"
fi

# 4. Hand off to the bridge with whatever extra flags the user passed.
exec python "$HERE/pin_bridge.py" --token "$OMI_LOCAL_JWT" "$@"

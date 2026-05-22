#!/usr/bin/env bash
# Helper that registers (idempotently) and logs in against main_local,
# then prints the JWT to stdout. Pipe into `OMI_LOCAL_JWT=$(...)` or save
# to a file.
#
# Usage:
#   ./login.sh you@omi.dev hunter2
#   ./login.sh                       # uses OMI_EMAIL / OMI_PASSWORD env vars
#
# Env knobs:
#   OMI_LOCAL_BACKEND_HTTP   default http://127.0.0.1:8088
#   OMI_EMAIL, OMI_PASSWORD  fallbacks for positional args
set -euo pipefail

EMAIL="${1:-${OMI_EMAIL:-}}"
PASSWORD="${2:-${OMI_PASSWORD:-}}"
BASE="${OMI_LOCAL_BACKEND_HTTP:-http://127.0.0.1:8088}"

if [[ -z "$EMAIL" || -z "$PASSWORD" ]]; then
  echo "usage: $0 <email> <password>" >&2
  exit 64
fi

# Register — ignore "already exists".
curl -sS -X POST "$BASE/v1/auth/register" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" \
  >/dev/null || true

# Login — print just the token.
curl -sS -X POST "$BASE/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'

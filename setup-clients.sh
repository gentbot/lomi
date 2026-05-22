#!/usr/bin/env bash
# ── LOCAL ONLY — no upstream equivalent ──
# setup-clients.sh — one-time setup for all local client config files.
#
# Creates the three env files needed to run the local backend and its clients.
# Safe to re-run — existing files are never overwritten.
#
# Usage (from project root):
#   bash setup-clients.sh
#
# What it does:
#   1. backend/.env       ← combined from .env.template + env.local.template
#   2. desktop/.env.app   ← minimal local config (LOCAL_MACHINE_HOST=localhost)
#   3. app/.dev.env       ← copied from .dev.env.example, then LAN IP synced in
#
# After running:
#   - Edit backend/.env and set LOCAL_JWT_SECRET to something secure.
#   - If the backend will serve other devices on the LAN, change LOCAL_MACHINE_HOST
#     in desktop/.env.app to the backend Mac's LAN IP, then re-run this script.
#   - To use the iOS app, regenerate Flutter env constants:
#       cd app && flutter pub run build_runner build --delete-conflicting-outputs

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_green()  { printf '\033[32m  [created] %s\033[0m\n' "$*"; }
_yellow() { printf '\033[33m  [skip]    %s\033[0m\n' "$*"; }
_cyan()   { printf '\033[36m  [synced]  %s\033[0m\n' "$*"; }
_red()    { printf '\033[31m  [warn]    %s\033[0m\n' "$*"; }
_bold()   { printf '\033[1m%s\033[0m\n' "$*"; }

echo
_bold "Omi Local — Client Setup"
_bold "========================"
echo

# ── 1. Backend .env ───────────────────────────────────────────────────────────
BACKEND_ENV="$HERE/backend/.env"

if [[ -f "$BACKEND_ENV" ]]; then
    _yellow "backend/.env already exists — skipping"
else
    cat "$HERE/backend/.env.template" \
        "$HERE/backend/env.local.template" \
        > "$BACKEND_ENV"
    _green "backend/.env"
    echo "             ↳ Edit LOCAL_JWT_SECRET before first boot."
    echo "             ↳ Optional: set BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD."
fi

# ── 2. Desktop .env.app ───────────────────────────────────────────────────────
DESKTOP_ENV="$HERE/desktop/.env.app"

if [[ -f "$DESKTOP_ENV" ]]; then
    _yellow "desktop/.env.app already exists — skipping"
else
    cat > "$DESKTOP_ENV" <<'EOF'
# Created by setup-clients.sh
# Change LOCAL_MACHINE_HOST to your LAN IP for multi-machine use,
# then re-run: bash setup-clients.sh
LOCAL_MACHINE_HOST=localhost
DEEPGRAM_API_KEY=
EOF
    _green "desktop/.env.app"
    echo "             ↳ Default: LOCAL_MACHINE_HOST=localhost (single-machine mode)."
    echo "             ↳ For LAN access, set LOCAL_MACHINE_HOST=<your LAN IP>."
fi

# ── 3. App .dev.env — delegate to sync-local-ip.sh ───────────────────────────
# sync-local-ip.sh creates .dev.env from .dev.env.example if missing,
# then writes API_BASE_URL from LOCAL_MACHINE_HOST in .env.app.

SYNC_SCRIPT="$HERE/scripts/sync-local-ip.sh"

if [[ ! -f "$SYNC_SCRIPT" ]]; then
    _red "scripts/sync-local-ip.sh not found — skipping app .dev.env setup"
else
    HOST=$(grep -m1 '^LOCAL_MACHINE_HOST=' "$DESKTOP_ENV" 2>/dev/null \
           | cut -d= -f2 | tr -d '[:space:]')
    HOST="${HOST:-localhost}"

    if bash "$SYNC_SCRIPT" >/dev/null 2>&1; then
        _cyan "app/.dev.env — API_BASE_URL=http://${HOST}:8088"
    else
        _red "sync-local-ip.sh failed — run it manually: bash scripts/sync-local-ip.sh"
    fi
fi

# ── Security warnings ─────────────────────────────────────────────────────────
if [[ -f "$BACKEND_ENV" ]]; then
    _JWT=$(grep -m1 '^LOCAL_JWT_SECRET=' "$BACKEND_ENV" 2>/dev/null | cut -d= -f2 | tr -d '[:space:]')
    _ENC=$(grep -m1 '^ENCRYPTION_SECRET=' "$BACKEND_ENV" 2>/dev/null | cut -d= -f2 | tr -d "' ")

    if [[ "$_JWT" == "change-me-in-production" || -z "$_JWT" ]]; then
        _red "LOCAL_JWT_SECRET is not set — edit backend/.env before first boot!"
    fi
    if [[ "$_ENC" == "omi_ZwB2ZNqB2HHpMK6wStk7sTpavJiPTFg7gXUHnc4tFABPU6pZ2c2DKgehtfgi4RZv" ]]; then
        _red "ENCRYPTION_SECRET is still the default — change it in backend/.env!"
        printf '             ↳ Generate one: python3 -c "import secrets; print('"'"'omi_'"'"' + secrets.token_urlsafe(48))"\n'
    fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo
_bold "Next steps"
_bold "----------"
echo
echo "  1. Edit backend/.env:"
echo "       - Change LOCAL_JWT_SECRET to a secure random value."
echo "       - Change ENCRYPTION_SECRET to a unique value per install."
echo "         Generate: python3 -c \"import secrets; print('omi_' + secrets.token_urlsafe(48))\""
echo
echo "  2. Start the backend:"
echo "       conda activate omilocal"
echo "       cd backend"
echo "       uvicorn main_local:app --host 0.0.0.0 --port 8088"
echo
echo "  3. macOS Desktop app:"
echo "       cd desktop && ./run-local.sh"
echo
echo "  4. iOS app — after changing LOCAL_MACHINE_HOST or first-time setup:"
echo "       cd app"
echo "       flutter pub run build_runner build --delete-conflicting-outputs"
echo "       flutter run --flavor dev -d <device-id>"
echo "       NOTE: iOS app recording does not produce transcripts (Opus issue)."
echo "             Use pin_bridge (cd pin_bridge && bash run.sh) for transcription."
echo
echo "  Full setup guide:  docs-local/SETUP_FROM_SCRATCH.md"
echo "  Operations guide:  docs-local/RUNBOOK.md"
echo

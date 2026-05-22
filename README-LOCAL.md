# Omi — Local Build

A fully local fork of [BasedHardware/omi](https://github.com/BasedHardware/omi).
Runs the backend, transcription, LLM, and vector search entirely on your own Mac —
no Firebase, no cloud APIs, no data leaving your network.

---

## What's different from upstream

| Upstream | This fork |
|----------|-----------|
| Firebase auth | Local JWT auth (`AUTH_PROVIDER=local`) |
| Firestore | SQLite (`DB_PROVIDER=sqlite`) |
| Deepgram STT | faster-whisper running locally (`STT_PROVIDER=local`) |
| OpenAI LLM | Ollama (`LLM_PROVIDER=ollama`) |
| Pinecone | Qdrant in Docker (`VECTOR_DB_PROVIDER=qdrant`) |
| Cloud backend | `backend/main_local.py` — drop-in local entry point |

All local additions live in paths upstream doesn't touch (`backend/routers_local/`,
`backend/database/sql/`, `docs-local/`, `pin_bridge/`) so the fork can track upstream
cleanly. See `docs-local/FORK_AND_MERGE_GUIDE.md`.

---

## Prerequisites

- macOS (Apple Silicon or Intel)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) running
- [Ollama](https://ollama.com) installed (`brew install ollama` or the .app)
- Homebrew (`brew`) and `conda` (Miniforge) — the setup guide installs both

---

## Quick start

**First time on a new machine — follow the full guide:**

```
docs-local/SETUP_FROM_SCRATCH.md
```

This covers installing Homebrew, Miniforge, Ollama, Qdrant, Python deps, and
booting the API. Takes 30–60 minutes (mostly downloads).

**After the backend is running, set up client config files:**

```bash
bash setup-clients.sh
```

This creates `backend/.env`, `desktop/.env.app`, and `app/.dev.env`
from their templates in one step. Safe to re-run — existing files are never
overwritten.

---

## Key documents

| Document | What it covers |
|----------|---------------|
| `docs-local/SETUP_FROM_SCRATCH.md` | Full install guide — zero to running backend |
| `docs-local/RUNBOOK.md` | Day-to-day operations, all clients, troubleshooting |
| `docs-local/LOCAL_CAPABILITIES.md` | What works locally and what's still cloud-dependent |
| `docs-local/FORK_AND_MERGE_GUIDE.md` | How to sync upstream changes into this fork |
| `pin_bridge/README.md` | BLE bridge — connect the Omi pin without the iOS app |
| `backend/.env.reference` | Every backend environment variable documented |

---

## Connecting clients

All clients are optional and independent. The backend runs standalone.

| Client | How to start |
|--------|-------------|
| Admin UI | `http://localhost:8088/admin` — user management, docs viewer, config |
| macOS Desktop app | `cd desktop && ./run-local.sh` (CommandLineTools-only: run `bash desktop/scripts/patch-for-local-build.sh` once first) |
| Omi pin (BLE) | `cd pin_bridge && bash run.sh` — see `pin_bridge/README.md` |
| iOS app | `docs-local/RUNBOOK.md §10.3` — requires Xcode and an Apple Developer account. **Note: recording via the iOS app does not produce transcripts** (Opus codec issue — use pin_bridge instead). |

For multi-machine setups (backend on one Mac, clients on others), set
`LOCAL_MACHINE_HOST` in `desktop/.env.app` to the backend Mac's LAN IP,
then re-run `bash setup-clients.sh`. See `docs-local/RUNBOOK.md §10.5`.

---

## Repository layout

```
backend/                Python FastAPI backend
  main_local.py         ← local entry point (not upstream's main.py)
  routers_local/        ← local-only API routers
  database/sql/         ← SQLite persistence layer
  admin_local/          ← local admin UI
app/                    Flutter iOS/Android app
desktop/                macOS Swift app
omi/firmware/           Omi pin firmware

pin_bridge/             BLE bridge — Omi pin → local backend (no iOS app needed)
docs-local/             All local documentation
scripts/                Helper scripts (sync-local-ip.sh, etc.)
setup-clients.sh        One-command client config setup (start here)
```

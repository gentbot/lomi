# Omi Local Backend — Setup From Scratch (macOS)

End-to-end installation guide for a brand-new Mac that has never seen this project. Assumes only:

- macOS (Apple Silicon or Intel)
- System Python is present (any version; we won't use it directly)
- Docker Desktop is installed and running
- Internet access

Everything else — Homebrew, Miniforge/conda, the project source, Ollama, Python deps, Qdrant — gets installed by the steps below. End state: a running `main_local` API on `http://127.0.0.1:8088` with `local_mode: true`.

Time required: **~30–60 minutes** (most of it is downloads — Ollama models and the embeddings model are the big ones).

Disk required: **~10–15 GB** (Miniforge ~500 MB + Python deps ~3 GB + Ollama model ~500 MB to 5 GB depending on choice + Qdrant image ~150 MB + sentence-transformers cache ~100 MB).

---

## 1. Verify Docker

```bash
docker --version
docker info > /dev/null && echo "Docker OK" || echo "Docker NOT running — open Docker Desktop"
```
If Docker Desktop isn't installed: https://www.docker.com/products/docker-desktop/ → install → launch → wait for the whale icon to settle.

---

## 2. Install Homebrew

Skip this step if `brew --version` already prints a version.

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

After it finishes, the installer prints two `eval` lines that add Homebrew to your `PATH`. **Run them**, then verify:
```bash
# Apple Silicon path:
eval "$(/opt/homebrew/bin/brew shellenv)"
# Intel path (only if /opt/homebrew doesn't exist):
# eval "$(/usr/local/bin/brew shellenv)"

brew --version
```

---

## 3. Install supporting CLI tools

```bash
brew install git curl wget jq sqlite ffmpeg opus
```

**Note:** `ffmpeg` is required because `faster-whisper` decodes uploaded audio through it. `opus` provides the native Opus codec library (`libopus`) needed by `opuslib` when running `pin_bridge.py`. If you're only using the backend API without `pin_bridge`, you can omit `opus` from this command.

---

## 4. Install Miniforge (conda)

The project's conda env is called `omilocal` and pins Python 3.11. Miniforge is the lightest conda distro; it's also the only one that has Apple Silicon-native binaries by default.

```bash
brew install --cask miniforge
```

Initialize conda for your shell (replace `zsh` with `bash` if that's what you use):
```bash
conda init zsh
exec $SHELL -l        # reload the shell so `conda activate` works
conda --version
```

If `conda init` complains, source it manually for the rest of this guide:
```bash
source "$(brew --prefix miniforge)/etc/profile.d/conda.sh"
```

---

## 5. Install Ollama

Local LLM runtime.

```bash
brew install --cask ollama
open -a Ollama        # launches the menu-bar app, which starts the daemon
sleep 3
curl -s http://localhost:11434/api/version
# → {"version":"..."}
```

Pull a small model. This guide uses `qwen3:0.6b` for the smoke test (fast, ~500 MB) and you can swap in something bigger later:
```bash
ollama pull qwen3:0.6b
ollama list
```

---

## 6. Get the project source

If you already have the project on the machine, skip the clone and just `cd` in.

```bash
mkdir -p ~/Documents/codebase/OMI
cd ~/Documents/codebase/OMI
git clone https://github.com/<your-fork-or-mirror>/omi-local code
# or, if you're transferring the directory another way (rsync/scp/zip),
# unpack it under ~/Documents/codebase/OMI/code
cd ~/Documents/codebase/OMI/code
ls
```

You should see at least `omi/`, `MIGRATION_STATUS.md`, `RUNBOOK.md`, and this file. The backend lives at `backend/`.

---

## 7. Create the conda environment

```bash
cd ~/Documents/codebase/OMI/code
conda create -y -n omilocal python=3.11
conda activate omilocal
python --version
# → Python 3.11.x
```

From here on, **every Python command must run with `omilocal` activated**. If you open a new terminal, `conda activate omilocal` first.

---

## 8. Install Python dependencies

The local stack uses a small slice of the full backend's deps. Install only what `main_local` needs:

```bash
cd backend

pip install --upgrade pip

pip install \
  "fastapi>=0.110" "uvicorn[standard]>=0.27" \
  "python-dotenv>=1.0" "python-multipart>=0.0.9" \
  "pydantic>=2.6" "pydantic-settings>=2.2" \
  "email-validator>=2" \
  "httpx>=0.27" "websockets>=12" \
  "SQLAlchemy>=2.0,<3" \
  "PyJWT>=2.8,<3" \
  "qdrant-client>=1.9,<2" \
  "sentence-transformers>=2.7,<3" \
  "faster-whisper>=1.0,<2"
```

If `sentence-transformers` install pulls a torch wheel that's slow, that's expected — it's roughly a 1 GB download.

Verify:
```bash
python -c "import fastapi, uvicorn, sqlalchemy, jwt, qdrant_client, sentence_transformers, faster_whisper; print('OK')"
```

---

## 9. Start Qdrant

One Docker container, runs in the background. Make sure Docker Desktop is open (whale icon in menu bar) before running this.

> **Data persistence:** §9.1 stores vectors inside the container — `docker rm omi-qdrant` wipes all semantic memory. Use §9.2 (named volume) if you want vectors to survive container recreation. The `start_local.sh` script always creates the container with a named volume, so this only matters if you create the container manually.

### 9.1 Quick start (data is throwaway)

```bash
docker run -d --name omi-qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant:latest
sleep 3
curl -s http://localhost:6333/healthz
# → "healthz check passed"
```

What this does:
- Pulls the `qdrant/qdrant:latest` image (~150 MB) from Docker Hub.
- Creates a container named `omi-qdrant`.
- Maps port `6333` (REST API, what `main_local` talks to) and `6334` (gRPC).
- Runs detached (`-d`) so it keeps going after you close the terminal.
- The container also appears in Docker Desktop under **Containers** with start/stop/restart buttons.

> **Caveat:** without a volume (see §9.2), all vectors live inside the container's filesystem. `docker rm omi-qdrant` deletes them. That's fine for first-day experimentation — recreating the container is fast and your SQLite memory rows survive — but you'll have to re-index by re-creating each memory.

### 9.2 Persistent storage (recommended)

If you want your vectors to survive container recreation, attach a volume. A volume is a directory that lives **outside** the container's writable layer, so wiping the container doesn't wipe the data.

Two flavors:

**Named volume (recommended on macOS).** Docker creates and manages the directory itself. Tidy and fast — no file-sharing overhead from Docker Desktop's host-path layer:
```bash
docker rm -f omi-qdrant 2>/dev/null
docker run -d --name omi-qdrant \
  -p 6333:6333 -p 6334:6334 \
  -v omi_qdrant_storage:/qdrant/storage \
  qdrant/qdrant:latest
```
Reference it by name (`omi_qdrant_storage`); under the hood it lives inside the Docker Desktop Linux VM at roughly `/var/lib/docker/volumes/omi_qdrant_storage/_data`. You don't need to interact with that path.

**Bind mount.** Maps a real folder on your Mac into the container. Use this if you want to back up the directory yourself, snapshot it, or browse it in Finder:
```bash
mkdir -p ~/omi-qdrant-data
docker rm -f omi-qdrant 2>/dev/null
docker run -d --name omi-qdrant \
  -p 6333:6333 -p 6334:6334 \
  -v ~/omi-qdrant-data:/qdrant/storage \
  qdrant/qdrant:latest
```
The path before the colon is a real macOS directory; `cd ~/omi-qdrant-data && ls` works.

In both cases:
- The path **after** the colon — `/qdrant/storage` — is where Qdrant writes inside the container. Don't change it.
- The path/name **before** the colon is what persists. That's the only place your vectors live.

Useful commands once you're using a named volume:
```bash
docker volume ls                              # list all named volumes
docker volume inspect omi_qdrant_storage      # see metadata + actual path
docker volume rm omi_qdrant_storage           # delete the volume (wipes Qdrant data)
```

### 9.3 Start, stop, restart

After the initial `docker run`, you don't run it again. Use:
```bash
docker stop omi-qdrant      # stop the container
docker start omi-qdrant     # start it again (after a reboot, etc.)
docker restart omi-qdrant   # both
```
Or click the corresponding buttons in Docker Desktop's **Containers** view.

### 9.4 Reset / start over

```bash
docker rm -f omi-qdrant                   # delete the container
docker volume rm omi_qdrant_storage       # delete the named volume (only if you used one)
# then re-run §9.1 or §9.2 to recreate.
```

---

## 10. Configure environment variables

Create a `.env` so you don't have to re-export them every shell:

```bash
cd backend
cat > .env <<'EOF'
LLM_PROVIDER=ollama
STT_PROVIDER=local
EMBEDDINGS_PROVIDER=local
VECTOR_DB_PROVIDER=qdrant
AUTH_PROVIDER=local
DB_PROVIDER=sqlite
EVENT_PROVIDER=websocket
SEARCH_PROVIDER=disabled
ENABLE_DIARIZATION=false

OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen3:0.6b
OLLAMA_TIMEOUT=300

QDRANT_URL=http://localhost:6333

LOCAL_EMBEDDINGS_MODEL=sentence-transformers/all-MiniLM-L6-v2
LOCAL_EMBEDDINGS_DIM=384

LOCAL_WHISPER_MODEL=base
LOCAL_WHISPER_DEVICE=cpu
LOCAL_WHISPER_COMPUTE_TYPE=int8

SQLITE_PATH=./omi_local.db
LOCAL_JWT_SECRET=change-me-in-production
LOCAL_JWT_TTL_SECONDS=86400

# IMPORTANT: Change this to a unique value — it encrypts all stored data.
# Generate: python3 -c "import secrets; print('omi_' + secrets.token_urlsafe(48))"
ENCRYPTION_SECRET='omi_ZwB2ZNqB2HHpMK6wStk7sTpavJiPTFg7gXUHnc4tFABPU6pZ2c2DKgehtfgi4RZv'

# Accept Firebase ID tokens without the firebase-admin SDK.
# Required if you use the iOS app or Desktop app with Firebase login.
# WARNING: also disables JWT signature verification for all tokens — only use on a trusted local network.
LOCAL_AUTH_BYPASS=true

# Optional: auto-create an admin account on first boot.
# There is NO default user — uncomment these and set real values,
# or register via the admin UI ("Register first account") after booting.
# BOOTSTRAP_ADMIN_EMAIL=admin@omi.dev
# BOOTSTRAP_ADMIN_PASSWORD=changeme
EOF
```

`main_local.py` calls `load_dotenv()` on startup, so this file is read automatically.

---

## 11. Boot the API

```bash
cd backend
conda activate omilocal     # if not already active
uvicorn main_local:app --host 127.0.0.1 --port 8088 --reload
```

Expected log lines:
```
INFO:local_bootstrap:Provider matrix: stt=local, llm=ollama, embeddings=local, vector_db=qdrant, auth=local, db=sqlite, events=websocket, search=disabled, diarization=off
INFO:local_bootstrap:SQLite schema initialized
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8088
```

The first run also creates `omi_local.db` (SQLite) in the backend dir. Leave this terminal open; the server logs to stdout here. Open a second terminal for the smoke test below.

---

## 12. Smoke test (second terminal)

```bash
# Health
curl -s http://127.0.0.1:8088/healthz | python -m json.tool

# Register a user (note: .local TLDs are rejected by email-validator — use .dev)
curl -s -X POST http://127.0.0.1:8088/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"alice@omi.dev","password":"hunter2"}'

# Login → JWT
TOKEN=$(curl -s -X POST http://127.0.0.1:8088/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"alice@omi.dev","password":"hunter2"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
echo "Token len: ${#TOKEN}"

# Whoami
curl -s http://127.0.0.1:8088/v1/auth/me -H "Authorization: Bearer $TOKEN"

# Create a memory (writes SQLite + Qdrant)
curl -s -X POST http://127.0.0.1:8088/v1/memories \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"content":"buy oat milk","category":"errand"}'

# Semantic search
curl -s -X POST http://127.0.0.1:8088/v1/memories/search \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"groceries"}'

# Chat (first call may take 30–60 s while Ollama loads the model)
curl -s -X POST http://127.0.0.1:8088/v1/chat \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"reply with one word: ready"}]}' \
  --max-time 240
```

Final response should be `{"content":"ready"}` (or similar). If it is, the local stack is fully wired.

For an interactive UI, browse to **http://127.0.0.1:8088/docs**.

---

## 13. Per-boot startup (after this initial install)

The full install only happens once. After a reboot, you only need:

```bash
# 1. Make sure Docker Desktop is running.
docker start omi-qdrant

# 2. Make sure Ollama is running. If you installed via brew --cask, it auto-starts.
#    If not: open -a Ollama   (or)   ollama serve &

# 3. Boot the API.
cd backend
conda activate omilocal
uvicorn main_local:app --host 0.0.0.0 --port 8088 --reload
```

`--host 0.0.0.0` makes the backend reachable over the LAN, which is required for the iOS app and `pin_bridge.py`. Use `--host 127.0.0.1` only if you're certain no other device needs to reach the backend.

A one-shot script (save as `start_local.sh` next to `main_local.py`):
```bash
#!/usr/bin/env bash
set -e
docker start omi-qdrant >/dev/null 2>&1 || \
  docker run -d --name omi-qdrant -p 6333:6333 qdrant/qdrant:latest
pgrep -f "ollama serve" >/dev/null || open -a Ollama
source "$(brew --prefix miniforge)/etc/profile.d/conda.sh"
conda activate omilocal
cd "$(dirname "$0")"
exec uvicorn main_local:app --host 0.0.0.0 --port 8088 --reload
```
`chmod +x start_local.sh` and run with `./start_local.sh`.

---

## 14. Stopping everything

```bash
# Foreground uvicorn:  Ctrl-C in its terminal.
# Background uvicorn:
pkill -f "uvicorn main_local"

# Qdrant
docker stop omi-qdrant

# Ollama
osascript -e 'quit app "Ollama"'   # or: pkill -f "ollama serve"
```

To completely uninstall and start over later:
```bash
# Project data
rm -rf ~/Documents/codebase/OMI/code/backend/omi_local.db
docker rm -f omi-qdrant

# Conda env
conda remove -n omilocal --all -y

# Tools (optional — only if you also want to remove them)
brew uninstall --cask ollama miniforge
brew uninstall git curl wget jq sqlite ffmpeg
```

---

## 15. Where to go next

**Set up client config files** (one command, from the project root):
```bash
bash setup-clients.sh
```
This creates `backend/.env`, `desktop/.env.app`, and `app/.dev.env`
from their templates. Run it now if you haven't already — it's safe to re-run.

Then:

- `RUNBOOK.md` — connecting the Omi pin and all clients (Desktop app, iOS app, pin bridge), day-to-day operations, troubleshooting.
- `LOCAL_CAPABILITIES.md` — what works locally and what cloud features remain.
- The Swagger UI at http://127.0.0.1:8088/docs is the easiest way to explore the API without writing code.

**macOS Desktop app (CommandLineTools-only machines):**
If you installed only Xcode Command Line Tools (not full Xcode) and get a `#Preview` macro compile error when building the Desktop app, run this patch once:
```bash
bash desktop/scripts/patch-for-local-build.sh
```
Then use `desktop/run-local.sh` (not `run.sh`) to launch the app.

---

## 16. Common install snags

| Symptom | Fix |
|---------|-----|
| `command not found: brew` after install | Run the `eval "$(/opt/homebrew/bin/brew shellenv)"` line the installer printed; add it to `~/.zprofile` to persist. |
| `command not found: conda` after `brew install --cask miniforge` | `conda init zsh` then `exec $SHELL -l`. Or source `"$(brew --prefix miniforge)/etc/profile.d/conda.sh"`. |
| `pip install` fails compiling `tokenizers` / `sentencepiece` | Install Xcode CLT: `xcode-select --install`. Reopen the terminal, retry. |
| `email-validator is not installed` on register | `pip install 'email-validator>=2'` inside `omilocal`. |
| `Failed to connect to localhost port 11434` | Ollama isn't running. `open -a Ollama`, wait a few seconds, retry. |
| `Failed to connect to localhost port 6333` | Qdrant isn't running. `docker start omi-qdrant`. |
| `value is not a valid email address` (`.local` TLD) | Use `.dev`, `.test`, or any normal domain. |
| First `/v1/chat` request times out | Cold model load. Keep `OLLAMA_TIMEOUT=300`. Use a small model first (`qwen3:0.6b`). Subsequent calls are fast. |
| `database is locked` | Don't run multiple uvicorn workers against the same SQLite file. `--workers 1` (the default). |
| `'QdrantClient' object has no attribute 'search'` | You installed an old `qdrant-client` (<1.10). Bump: `pip install 'qdrant-client>=1.9,<2'`. The repo includes a compat shim that handles ≥1.10. |
| Apple Silicon torch is slow / segfaults | The default `pip install sentence-transformers` pulls CPU torch. For Metal: `pip install --upgrade torch torchvision` (the universal wheel uses MPS automatically). Unrelated to first-boot. |

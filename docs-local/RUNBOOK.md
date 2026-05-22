# Omi Local Backend — Operator Runbook

How to start, stop, log into, and administer the local-only Omi backend, plus where the UI lives.

---

## 1. Where things live

| Thing | Path |
|-------|------|
| Backend code | `<PROJECT_ROOT>/backend/` |
| Local entrypoint | `backend/main_local.py` |
| SQLite database file | `backend/omi_local.db` (created on first boot) |
| Server logs | `/tmp/omi_local.log` |
| Conda env | `omilocal` (Python 3.11) |
| BLE pin bridge | `code/pin_bridge/` — connects pin directly to backend, no iOS app needed |
| Admin UI | `backend/admin_local/index.html` — served at `/admin/` |
| Migration spec | `code/MIGRATION_STATUS.md` |
| This runbook | `code/RUNBOOK.md` |

---

## 2. Prerequisites

These must be installed and runnable:

- **Conda** with the `omilocal` environment (Python 3.11). Verify:
  ```bash
  conda activate omilocal && python --version
  # → Python 3.11.x
  ```
- **Docker** (for Qdrant). Verify: `docker --version`
- **Ollama** running locally on `http://localhost:11434`. Verify: `curl -s http://localhost:11434/api/version`
- A pulled Ollama model. The runbook uses `qwen3:0.6b` because it's fast. List installed models:
  ```bash
  curl -s http://localhost:11434/api/tags | python -c "import sys,json;[print(m['name']) for m in json.load(sys.stdin)['models']]"
  ```
  If you don't have one yet: `ollama pull qwen3:0.6b` (≈ 500 MB).

If any of those are missing, install them before continuing.

---

## 3. Starting the backend

### 3.1 Start the supporting services

**Qdrant** (vector database). Start once; persists across reboots as long as the container exists:
```bash
docker start omi-qdrant 2>/dev/null || docker run -d --name omi-qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant:latest
curl -s http://localhost:6333/healthz   # → "healthz check passed"
```

**Ollama** (LLM). If not already running:
```bash
ollama serve &                          # leave running in a terminal/tab
curl -s http://localhost:11434/api/version
```

### 3.2 Boot the API

```bash
cd <PROJECT_ROOT>/backend
conda activate omilocal

export LLM_PROVIDER=ollama
export STT_PROVIDER=local
export EMBEDDINGS_PROVIDER=local
export VECTOR_DB_PROVIDER=qdrant
export AUTH_PROVIDER=local
export DB_PROVIDER=sqlite
export EVENT_PROVIDER=websocket
export SEARCH_PROVIDER=disabled
export ENABLE_DIARIZATION=false
export OLLAMA_HOST=http://localhost:11434
export OLLAMA_MODEL=qwen3:0.6b
export OLLAMA_TIMEOUT=300
export QDRANT_URL=http://localhost:6333
export LOCAL_EMBEDDINGS_MODEL=sentence-transformers/all-MiniLM-L6-v2
export LOCAL_EMBEDDINGS_DIM=384
export LOCAL_WHISPER_MODEL=base
export LOCAL_WHISPER_DEVICE=cpu
export LOCAL_WHISPER_COMPUTE_TYPE=int8
export SQLITE_PATH=./omi_local.db
export LOCAL_JWT_SECRET=change-me-in-production
export LOCAL_JWT_TTL_SECONDS=86400
export LOCAL_AUTH_BYPASS=true

uvicorn main_local:app --host 0.0.0.0 --port 8088 --reload
```

> `--host 0.0.0.0` binds to all interfaces — reachable from both localhost and any LAN device (Desktop app, iOS app, pin_bridge on another machine). Use `--host 127.0.0.1` only if you want to explicitly block external access.

Expected startup output:
```
INFO:local_bootstrap:Provider matrix: stt=local, llm=ollama, embeddings=local, vector_db=qdrant, auth=local, db=sqlite, events=websocket, search=disabled, diarization=off
INFO:local_bootstrap:SQLite schema initialized
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8088
```

### 3.3 One-shot start script

`start_local.sh` already exists in the backend directory. It handles Qdrant, Ollama (local or remote via `OLLAMA_HOST`), and uvicorn in one command:

```bash
cd backend
bash start_local.sh
```

Or use the shell functions in `~/.aliases`:
```bash
omi-start   # start everything
omi-stop    # stop everything
```

### 3.4 Background mode (detached)

If you want the server to keep running after you close the terminal:
```bash
nohup uvicorn main_local:app --host 0.0.0.0 --port 8088 \
    > /tmp/omi_local.log 2>&1 &
echo $! > /tmp/omi_local.pid
```
Live-tail logs: `tail -f /tmp/omi_local.log`

---

## 4. Stopping the backend

### 4.1 Foreground (started with `uvicorn ... --reload`)
Press `Ctrl-C` in the terminal that's running it.

### 4.2 Background / detached
```bash
kill "$(cat /tmp/omi_local.pid)" 2>/dev/null
# Or, if the pid file is missing:
pkill -f "uvicorn main_local"
```

### 4.3 Stopping the supporting services

```bash
docker stop omi-qdrant            # Qdrant
pkill -f "ollama serve"           # Ollama (if you started it manually)
```

### 4.4 Full clean shutdown (everything)

```bash
pkill -f "uvicorn main_local"
docker stop omi-qdrant
pkill -f "ollama serve"
```

To wipe local data and start fresh:
```bash
rm -f <PROJECT_ROOT>/backend/omi_local.db
docker rm -f omi-qdrant && docker run -d --name omi-qdrant -p 6333:6333 qdrant/qdrant:latest
```
(That erases all users, conversations, memories, and Qdrant collections.)

---

## 5. Logging in and using the API

There is **no login UI**. The backend exposes a JSON HTTP API; you authenticate by hitting the register/login endpoints and using the returned JWT as a bearer token. Use `curl`, Postman, or the built-in interactive docs (see §7).

### 5.1 Create an account

```bash
curl -sS -X POST http://127.0.0.1:8088/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@omi.dev","password":"choose-a-password"}'
```
Returns:
```json
{"id":"<uuid>", "email":"you@omi.dev"}
```

> **Note on email validation.** `pydantic[email]` rejects `.local` TLDs. Use `.dev`, `.test`, or any normal domain.

### 5.2 Log in to get a JWT

```bash
curl -sS -X POST http://127.0.0.1:8088/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@omi.dev","password":"choose-a-password"}'
```
Returns:
```json
{"access_token":"eyJhbGciOiJIUzI1NiIs...","token_type":"bearer"}
```
The token is valid for `LOCAL_JWT_TTL_SECONDS` (default 24 h). Store it in a shell variable:
```bash
export TOKEN=$(curl -sS -X POST http://127.0.0.1:8088/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@omi.dev","password":"choose-a-password"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
```

### 5.3 Verify the token

```bash
curl -sS http://127.0.0.1:8088/v1/auth/me -H "Authorization: Bearer $TOKEN"
# → {"user_id":"<uuid>"}          # local JWT users
# → {"user_id":"fb_<firebase-uid>"}  # Firebase bypass users (LOCAL_AUTH_BYPASS=true)
```

### 5.4 Day-to-day usage

Every authenticated request needs `Authorization: Bearer $TOKEN`.

| Action | Method + path | Example body |
|--------|---------------|--------------|
| List all users (admin) | `GET /v1/admin/users` | — |
| Get one user | `GET /v1/admin/users/{id}` | — |
| Update user email / display name | `PATCH /v1/admin/users/{id}` | `{"email":"new@omi.dev","display_name":"Alice"}` |
| Reset a user's password (admin) | `POST /v1/admin/users/{id}/password` | `{"new_password":"newpass99"}` |
| Delete a user | `DELETE /v1/admin/users/{id}` | — |
| Change own password | `POST /v1/auth/change-password` | `{"current_password":"old","new_password":"new"}` |
| Create conversation | `POST /v1/conversations` | `{"title":"Morning standup"}` |
| List conversations | `GET /v1/conversations` | — |
| Get one conversation | `GET /v1/conversations/{id}` | — |
| Add message | `POST /v1/conversations/{id}/messages` | `{"role":"user","text":"Hi"}` |
| List messages | `GET /v1/conversations/{id}/messages` | — |
| Create memory | `POST /v1/memories` | `{"content":"buy milk","category":"errand"}` |
| List memories | `GET /v1/memories` | — |
| Semantic memory search | `POST /v1/memories/search` | `{"query":"groceries","limit":5}` |
| Chat with the LLM | `POST /v1/chat` | `{"messages":[{"role":"user","content":"hello"}]}` |
| Stream chat (SSE) | `POST /v1/chat/stream` | same as above |
| Transcribe audio | `POST /v1/transcribe` (multipart) | `audio=@/path/to/file.wav` |
| Provider/health status | `GET /healthz` (no auth) | — |

Example: end-to-end flow.
```bash
# Register & login
curl -sS -X POST http://127.0.0.1:8088/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"alice@omi.dev","password":"hunter2"}'
TOKEN=$(curl -sS -X POST http://127.0.0.1:8088/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"alice@omi.dev","password":"hunter2"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Save a memory
curl -sS -X POST http://127.0.0.1:8088/v1/memories \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"content":"buy oat milk at trader joes","category":"errand"}'

# Search semantically
curl -sS -X POST http://127.0.0.1:8088/v1/memories/search \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"groceries"}'

# Chat
curl -sS -X POST http://127.0.0.1:8088/v1/chat \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"summarize my errands"}]}'

# Transcribe a WAV
curl -sS -X POST http://127.0.0.1:8088/v1/transcribe \
  -H "Authorization: Bearer $TOKEN" -F "audio=@/path/to/clip.wav"
```

### 5.5 Forgot password / lost JWT

There is no password-reset endpoint. To reset, drop the user row directly:
```bash
sqlite3 <PROJECT_ROOT>/backend/omi_local.db \
  "DELETE FROM users WHERE email='you@omi.dev';"
```
Then re-register.

---

## 6. Administering the backend

### 6.1 First-run admin user (optional)

Set these before booting and the user is auto-created on startup if it doesn't exist:
```bash
export BOOTSTRAP_ADMIN_EMAIL=admin@omi.dev
export BOOTSTRAP_ADMIN_PASSWORD=changeme
```
There is no role/RBAC system yet — the "admin" is just a regular user with credentials baked into env.

### 6.2 List users / inspect data directly

The SQLite database is at `backend/omi_local.db`. Use the `sqlite3` CLI:
```bash
cd <PROJECT_ROOT>/backend
sqlite3 omi_local.db
```
Useful one-liners:
```sql
.tables                                          -- list all tables
SELECT id, email, created_at FROM users;         -- all users
SELECT COUNT(*) FROM conversations;
SELECT id, content, category FROM memories LIMIT 20;
SELECT id, conversation_id, role, text FROM messages ORDER BY created_at DESC LIMIT 20;
DELETE FROM users WHERE email='someone@omi.dev'; -- cascades to conversations, memories, etc.
.quit
```

### 6.3 Inspect / clear Qdrant

Qdrant exposes a REST API on `http://localhost:6333`:
```bash
# List collections
curl -s http://localhost:6333/collections | python -m json.tool

# Count points in the memories collection (ns2)
curl -s "http://localhost:6333/collections/ns2/points/count" \
  -X POST -H 'Content-Type: application/json' -d '{}' | python -m json.tool

# Drop a collection (e.g. wipe memory vectors)
curl -s -X DELETE http://localhost:6333/collections/ns2
```
The four collections used by the backend:

| Collection | Contents |
|------------|----------|
| `ns1` | Conversation embeddings |
| `ns2` | Memory embeddings |
| `ns3` | Screen-activity embeddings |
| `ns4` | Action-item embeddings |

### 6.4 Rotate the JWT signing key

Setting `LOCAL_JWT_SECRET` to a new value invalidates **all** outstanding tokens. Any client must log in again.

### 6.5 Change the LLM model

Either edit your env block before launching:
```bash
export OLLAMA_MODEL=qwen2.5:7b
```
…or list available models on Ollama and pick one:
```bash
curl -s http://localhost:11434/api/tags
ollama pull llama3.2:latest                       # pull a new one
```
The new model takes effect on the next server restart.

### 6.6 Logs

- **API logs:** wherever uvicorn was started (foreground), or `/tmp/omi_local.log` (background mode).
- **Live tail:** `tail -f /tmp/omi_local.log`
- **Filter errors:** `grep -i "error\|exception" /tmp/omi_local.log`
- **Qdrant logs:** `docker logs -f omi-qdrant`
- **Ollama logs:** in the terminal where `ollama serve` is running.

### 6.7 Health check / what's wired

Hit the un-authenticated `/healthz` endpoint:
```bash
curl -s http://127.0.0.1:8088/healthz | python -m json.tool
```
Returns the active provider matrix. `local_mode: true` confirms every subsystem is on a local provider.

---

## 7. Is there a UI?

There is **no end-user web UI** packaged with this local backend. Three options for clicking around:

### 7.1 Built-in Swagger UI (recommended)

FastAPI auto-generates an interactive HTTP explorer:
- **Swagger:** http://127.0.0.1:8088/docs
- **ReDoc:** http://127.0.0.1:8088/redoc

To use authenticated endpoints in Swagger:
1. Open `/docs`.
2. Expand `POST /v1/auth/login`, click **Try it out**, paste `{"email":"...","password":"..."}`, click **Execute**.
3. Copy the `access_token` from the response.
4. Click the **Authorize** button in the upper-right of `/docs`.
5. Paste the token (Swagger prepends `Bearer ` for you when you choose the bearer scheme; if it asks for the full header, paste `Bearer <token>`).
6. All authenticated endpoints are now callable from the page.

### 7.1.1 Restricting `/docs` access (optional)

By default Swagger UI is publicly accessible — fine on a trusted LAN. If you expose the backend to a shared or public network, set `DOCS_API_KEY` in your `.env`:

```env
DOCS_API_KEY=choose-a-strong-key
```

Then access the docs at:
```
http://localhost:8088/docs?key=choose-a-strong-key
```

Or pass it as a header: `X-Docs-Key: choose-a-strong-key`.

`/healthz` and all API routes are unaffected. Leave `DOCS_API_KEY` blank (the default) to restore open access.

### 7.2 Mobile / desktop apps in the repo

The repo at `code/omi/` ships first-party clients:

| Client | Path | Status against the local backend |
|--------|------|----------------------------------|
| BLE pin bridge | `code/pin_bridge/` | **Works today** — streams audio directly to the local backend via `pin_bridge.py`. See §10.1. |
| macOS Desktop | `code/desktop/` | **Works today** — configure `LOCAL_MACHINE_HOST` in `desktop/.env.app` and run `./run-local.sh`. No code changes needed. See §10.2. |
| Flutter iOS app | `code/app/` | **Works with a rebuild** — run `sync-local-ip.sh`, set `LOCAL_AUTH_ENABLED=true` in `.dev.env`, run build_runner, deploy with `flutter run --flavor dev`. See §10.3. |
| Web | `code/omi/web/` | Not wired for local mode; no steps documented. |

The key enablers that make the apps work without replacing Firebase auth:
- `LOCAL_AUTH_BYPASS=true` in `.env` — the local backend accepts Firebase ID tokens on both WebSocket and REST endpoints and derives a stable user-ID from the Firebase UID embedded in the token. No firebase-admin SDK needed. **Security note:** this also disables JWT signature verification for *all* tokens — only enable it on a trusted local network.
- `/v4/listen` WebSocket endpoint — production-compatible audio streaming endpoint now implemented locally.

See §10 for step-by-step instructions for each client.

### 7.3 User Admin web UI

A browser-based admin panel is served directly by the backend:

```
http://127.0.0.1:8088/admin/
```

No separate process needed. Single self-contained HTML file (`backend/admin/index.html`) — no external dependencies.

**User management**

| Operation | How |
|-----------|-----|
| Register first account | "Register first account" link on the login screen |
| Sign in | Email + password form |
| List all users | Main table — shows email, display name, ID, created date |
| Create a user | "+ New User" button → modal form |
| Edit email / display name | "Edit" button on each row → modal |
| Admin-reset any user's password | "Reset PW" button on each row → modal |
| Change your own password | "Change My Password" button in the toolbar |
| Delete a user | "Delete" button on each row → confirmation modal (cascades all data) |
| Sign out | "Sign Out" button — clears the session token |

**Settings (⚙ Settings toolbar button)**

Three tabs for editing live `.env` files via the browser. Changes write the file on disk (with a timestamped backup written first to `env_backups/`) and take effect on the next backend restart.

| Tab | File edited |
|-----|-------------|
| Backend | `backend/.env` |
| Desktop App | `Desktop/Backend-Rust/.env` |
| iOS App | `app/.dev.env` |

Each field shows a ℹ️ tooltip populated from `.env.reference` and a "Writes to: `<path>`" label. A "View Backups" button lists timestamped copies in `env_backups/`.

**Docs (📄 Docs toolbar button)**

Browse project markdown files directly in the browser. The catalog is maintained in `routers_local/docs.py` (`_CURATED_DOCS`). Current catalog: RUNBOOK, pin audio setup, cloud dependency audit, backend CLAUDE.md, backend README, .env reference, and several app/firmware guides.

**URLs (🔗 URLs toolbar button)**

Reference page listing all service base URLs — local services, production/cloud services, external dev tools — with descriptions, the env var that controls each, and where the env var lives.

**Notes:**
- Any authenticated user has full admin access (there is no RBAC in local mode).
- The session token lives in `sessionStorage` and is cleared when the tab is closed.
- The "Delete" button on your own row is disabled as a self-delete guard.
- Always use a hard-refresh (`Cmd+Shift+R`) when accessing the admin from a LAN IP after accessing it from localhost — the browser caches the old JS.

**First use (no account exists yet):**
1. Open `http://127.0.0.1:8088/admin/` in a browser.
2. Click "Register first account".
3. Enter an email (avoid `.local` TLD — use `.dev`, `.test`, or any normal domain) and a password of at least 8 characters.
4. You are automatically signed in and the user table loads.

### 7.4 Third-party tools

For day-to-day usage without writing code:
- **HTTPie**, **Postman**, **Insomnia**, **Bruno** — point at `http://127.0.0.1:8088`, set bearer token, hit endpoints.
- **`websocat`** for the WebSockets:
  ```bash
  websocat "ws://127.0.0.1:8088/ws?token=$TOKEN"
  ```

---

## 8. Quick reference card

```
Backend dir:     backend
Conda env:       omilocal
API base URL:    http://127.0.0.1:8088
Swagger UI:      http://127.0.0.1:8088/docs
Admin UI:        http://127.0.0.1:8088/admin/
Health:          http://127.0.0.1:8088/healthz
Database file:   omi_local.db (SQLite)
Vector DB:       http://localhost:6333 (Qdrant in Docker, container name "omi-qdrant")
LLM:             http://localhost:11434 (Ollama, default model qwen3:0.6b)
Logs:            /tmp/omi_local.log (background mode)

Start:           uvicorn main_local:app --host 0.0.0.0 --port 8088 --reload
Stop fg:         Ctrl-C
Stop bg:         pkill -f "uvicorn main_local"
Stop Qdrant:     docker stop omi-qdrant
Tail logs:       tail -f /tmp/omi_local.log
Reset DB:        rm omi_local.db && (next boot recreates schema)

Register:        POST /v1/auth/register   {"email":"...","password":"..."}
Login:           POST /v1/auth/login      {"email":"...","password":"..."}
Whoami:          GET  /v1/auth/me         (Authorization: Bearer <token>)
```

---

## 9. Common problems

| Symptom | Cause / fix |
|---------|-------------|
| `value is not a valid email address` on register | Don't use `.local` TLD. Use `you@omi.dev` or any normal domain. |
| `Internal Server Error` on `/v1/chat` | Ollama isn't running, model isn't pulled, or `OLLAMA_HOST` is empty. Check `curl http://localhost:11434/api/version` and `ollama list`. |
| Chat hangs > 60 s the first time | Cold model load. Keep `OLLAMA_TIMEOUT=300` and use a small model first (`qwen3:0.6b`). |
| `Failed to connect to localhost port 6333` | Qdrant is down. `docker start omi-qdrant`. |
| `database is locked` | Don't run multiple uvicorn workers against the same SQLite file. Use `--workers 1` (the default) or migrate to Postgres. |
| Memories don't appear in `/v1/memories/search` | Qdrant was offline when the memory was created. The SQL row exists; re-create the memory now that Qdrant is up, or write a small re-index script. |
| `email-validator is not installed` | `pip install 'email-validator>=2'` inside `omilocal`. |
| Token returns `Not authenticated` after restart | If you changed `LOCAL_JWT_SECRET`, every existing token is invalidated. Log in again. |
| Server boots but `/healthz` shows `local_mode: false` | One of the `*_PROVIDER` env vars wasn't exported. Re-export the full block in §3.2. |

---

## 10. Connecting the Omi pin to the local backend

This section covers three paths to get the Omi pin recording into the local backend. Execute **§10.0 first** regardless of which client you use.

---

### 10.0 Prerequisites — backend must be LAN-accessible

Every client path below requires the backend to be reachable over the local network, not just on `127.0.0.1`.

**Step 1.** Find your Mac's LAN IP address:
```bash
ipconfig getifaddr en0
```
Example output: `<YOUR_SERVER_IP>`. If `en0` returns nothing (e.g. on Wi-Fi via a different interface), try:
```bash
ipconfig getifaddr en1    # Wi-Fi on some Macs
ifconfig | grep "inet " | grep -v 127
```
Write this IP down — every client step below refers to it as `<LAN-IP>`.

**Step 2.** Start the backend bound to all interfaces:
```bash
omi-start
# OR manually:
cd backend
conda activate omilocal
uvicorn main_local:app --host 0.0.0.0 --port 8088 --reload
```
The `start_local.sh` script already binds `0.0.0.0` by default.

**Step 3.** Confirm health from another terminal or device:
```bash
curl http://<LAN-IP>:8088/healthz
# Expected: {"ok":true,"local_mode":true,"providers":{...}}
```
If this times out from your phone or another Mac, check:
- macOS Firewall: **System Settings → Network → Firewall** — make sure it is off, or add an exception for `uvicorn`
- The backend terminal shows no bind errors
- Both devices are on the same Wi-Fi network

**Step 4.** Confirm `LOCAL_AUTH_BYPASS=true` is set. The iOS and Desktop apps authenticate via Firebase; the bypass allows the local backend to accept Firebase tokens without the firebase-admin SDK:
```bash
grep LOCAL_AUTH_BYPASS ~/Documents/codebase/OMI/code/backend/.env
# Expected: LOCAL_AUTH_BYPASS=true
```
If the line is missing, add it:
```bash
echo "LOCAL_AUTH_BYPASS=true" >> ~/Documents/codebase/OMI/code/backend/.env
```
Restart the backend after adding it.

---

### 10.1 BLE pin bridge (`pin_bridge.py`) — works today, no app required

The pin bridge connects the Omi pin directly to the local backend over BLE without needing the Flutter or Desktop app. This is the simplest path and does not require code changes to any app.

#### Prerequisites
- Omi pin charged and powered on
- Not paired with the official Omi app or any other host (if it is, close the app or toggle BLE off/on on the pin)
- macOS Bluetooth enabled
- `omilocal` conda env active
- `brew install opus` completed (needed by `opuslib`)

**Step 1.** Install pin bridge dependencies (one-time):
```bash
conda activate omilocal
pip install bleak opuslib websockets
```
Verify:
```bash
python -c "import bleak, opuslib, websockets; print('deps OK')"
```
If `opuslib` fails with `libopus not found`:
```bash
brew install opus
pip install opuslib
```

**Step 2.** Register a local account on the backend (one-time):
```bash
curl -sS -X POST http://127.0.0.1:8088/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"pin@omi.dev","password":"hunter2"}'
# Expected: {"id":"<uuid>","email":"pin@omi.dev"}
```

**Step 3.** Log in to get a JWT:
```bash
export TOKEN=$(curl -sS -X POST http://127.0.0.1:8088/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"pin@omi.dev","password":"hunter2"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
echo "Token length: ${#TOKEN}"
# Expected: Token length: ~180
```
The token is valid for 24 hours (`LOCAL_JWT_TTL_SECONDS=86400`).

**Step 4.** Grant Bluetooth permission to Terminal (one-time):
The first time any Python script calls CoreBluetooth, macOS shows a permission dialog. Run a quick scan to trigger it:
```bash
cd ~/Documents/codebase/OMI/code/pin_bridge
conda activate omilocal
python pin_bridge.py --scan-only
```
If the dialog does not appear: **System Settings → Privacy & Security → Bluetooth** — enable the toggle next to your terminal app (Terminal.app, iTerm2, VS Code, etc.). You do not need to reboot.

**Step 5.** Scan to confirm the pin is visible:
```bash
python pin_bridge.py --scan-only
```
Expected output:
```
Scanning for BLE devices (5 s)...
  Omi-XXXX  (XX:XX:XX:XX:XX:XX)  RSSI -65 dBm
```
If the pin does not appear:
- Power-cycle the pin (hold the button for several seconds until it restarts)
- Move within 2 metres of the Mac
- Close the official Omi app if it is open — only one host can be connected at a time

**Step 6.** Run the bridge with the JWT:
```bash
python pin_bridge.py --token "$TOKEN"
```
Expected startup sequence:
```
INFO  pin_bridge: Connecting to backend WS: ws://127.0.0.1:8088/v4/listen?sample_rate=16000&codec=linear16&language=en
INFO  pin_bridge: Connected to Omi-XXXX (XX:XX:XX:XX:XX:XX)
INFO  pin_bridge: audio format characteristic: 01
INFO  pin_bridge: Haptic write OK
INFO  pin_bridge: Subscribed to audio notifications. Speak into the pin. Ctrl-C to stop.
```
The haptic buzz confirms the pin and bridge are connected.

**Step 7.** Speak into the pin. After 5 seconds you should see:
```
INFO  pin_bridge: partial: hello world
```
Partial transcripts arrive every ~5 s as Whisper processes audio chunks. The first partial may take 15–30 s on cold model load; subsequent partials are faster.

**Step 8.** Stop recording:
Press `Ctrl-C`. The bridge closes the WebSocket cleanly. The backend persists the conversation to SQLite + Qdrant and emits a confirmation:
```
INFO  pin_bridge: Conversation saved — id=<hex> title='hello world...'
```

**Step 9.** Verify the conversation was saved:
```bash
curl -sS http://127.0.0.1:8088/v1/conversations \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```
Expected: a JSON array containing one entry with a `title` matching the first ~80 chars of your transcript.

#### Offline drain (automatic)
If the pin was out of BLE range and recorded audio to its SD card, the offline drain runs automatically on the next connect. You will see log lines like:
```
INFO  pin_offline_drain: Found 3 storage file(s) on pin
INFO  pin_offline_drain: Draining file 0 (timestamp=..., size=... bytes)
INFO  pin_bridge: Offline drain pushed 312 frames into the stream
```
This drains all stored audio into the same live transcription stream. No separate action is needed.

#### Re-using the bridge with `run.sh`
`run.sh` in `pin_bridge/` automates register + login + run:
```bash
cd ~/Documents/codebase/OMI/code/pin_bridge
OMI_EMAIL=pin@omi.dev OMI_PASSWORD=hunter2 bash run.sh
```
Set the token in the environment to skip the login step on subsequent runs:
```bash
cd ~/Documents/codebase/OMI/code/pin_bridge
export OMI_LOCAL_JWT="$TOKEN"
bash run.sh
```

---

### 10.2 macOS Desktop app

The Desktop app is pre-configured to use the local backend through `run-local.sh`. No manual env exports needed — everything is driven by `desktop/.env.app`.

#### Prerequisites
- Local backend running (§3) — same-machine or LAN-accessible (§10.0) depending on your setup
- Xcode Command Line Tools: `xcode-select --install`
- `.env.app` exists at `desktop/.env.app` (created as part of this local setup — see below if missing)

**Step 1.** Verify `.env.app` is configured.

If you ran `bash setup-clients.sh` from the project root after completing
`SETUP_FROM_SCRATCH.md`, this file already exists — check it:
```bash
cat desktop/.env.app
```
Expected contents for a same-machine setup:
```
LOCAL_MACHINE_HOST=localhost
DEEPGRAM_API_KEY=
```
If the file is missing, run the setup script from the project root:
```bash
bash setup-clients.sh
```
Or create it manually:
```bash
cat > desktop/.env.app <<'EOF'
LOCAL_MACHINE_HOST=localhost
DEEPGRAM_API_KEY=
EOF
```

**Step 2. (LAN only — skip if backend and desktop are on the same Mac)**

If the backend is on a different machine (or you want the iOS app or `pin_bridge` on another device to reach it), set `LOCAL_MACHINE_HOST` to the backend Mac's LAN IP:
```bash
# Find the LAN IP first (§10.0 Step 1 — run this on the backend Mac):
ipconfig getifaddr en0   # example: <YOUR_SERVER_IP>
```
Then edit `desktop/.env.app` and update:
```
LOCAL_MACHINE_HOST=<YOUR_SERVER_IP>
```
`run-local.sh` derives `OMI_PYTHON_API_URL` and `OMI_DESKTOP_API_URL` from `LOCAL_MACHINE_HOST` automatically when the URL vars are not set explicitly.

**Step 3.** Launch the Desktop app:
```bash
cd desktop
./run-local.sh
```
`run-local.sh` sources `.env.app`, sets `OMI_SKIP_BACKEND=1`, `OMI_SKIP_TUNNEL=1`, and `OMI_ADHOC_SIGN=1` automatically, then delegates to `run.sh` which builds the Swift app and launches it.

> **CommandLineTools-only Mac?** If you get a `#Preview` macro compile error, run `scripts/patch-for-local-build.sh` once before building:
> ```bash
> bash desktop/scripts/patch-for-local-build.sh
> ```

**Step 4.** Sign in to the app.
The Desktop app signs in with Apple or Google via Firebase. This calls Firebase servers directly — it works fine with no changes. Complete the sign-in flow normally.

**Step 5.** Verify the app is using the local backend.
In the backend terminal, HTTP requests should appear immediately after sign-in:
```
INFO:     127.0.0.1:xxxxx - "GET /v1/auth/me HTTP/1.1" 200
INFO:     127.0.0.1:xxxxx - "GET /v1/conversations HTTP/1.1" 200
```
If you see no requests, confirm `.env.app` has `LOCAL_MACHINE_HOST=localhost` and `OMI_PYTHON_API_URL=http://localhost:8088`.

**Step 6.** Pair the Omi pin.
In the Desktop app, go to the device pairing screen and pair your pin over Bluetooth. The pin pairing flow is Bluetooth-only and does not contact the backend.

**Step 7.** Start transcription.
Click the record/start button in the Desktop app. In the backend terminal you should see:
```
INFO:     127.0.0.1:xxxxx - "WebSocket /v4/listen?language=en&sample_rate=16000... 101"
```
The `101` status confirms the WebSocket upgrade succeeded.

**Step 8.** Speak. Transcript segments appear in the app in real time.

**Step 9.** Stop transcription.
Click stop in the Desktop app. The WebSocket closes. The backend creates a Conversation record:
```
INFO:routers_local.listen: Conversation <uuid> created for user fb_<firebase-uid> (N segments)
```

**Step 10.** Verify the conversation was saved:
```bash
sqlite3 ~/Documents/codebase/OMI/code/backend/omi_local.db \
  "SELECT id, title, created_at FROM conversations ORDER BY created_at DESC LIMIT 5;"
```

#### Returning to the production backend
`run-local.sh` sets `OMI_SKIP_BACKEND=1` and `OMI_SKIP_TUNNEL=1`. To use the cloud backend, run `./run.sh` directly (which still reads `.env.app` for `DEEPGRAM_API_KEY` and other keys but does not force local-only flags).

#### Troubleshooting (Desktop)

| Symptom | Cause / fix |
|---------|-------------|
| Backend gets no requests after sign-in | `OMI_PYTHON_API_URL` not set correctly in `.env.app`. Check the file and confirm `LOCAL_MACHINE_HOST=localhost` (or your LAN IP). |
| WebSocket upgrade returns 403 | `LOCAL_AUTH_BYPASS` not set to `true` in `backend/.env`. Add it and restart the backend. |
| App shows "connection error" for conversations | Firewall blocking port 8088. Disable macOS Firewall or add a uvicorn exception. |
| Conversations list is empty in the app | Check backend logs for 200 on `/v1/conversations`. If 401, `LOCAL_AUTH_BYPASS` may not have been loaded — restart the backend. |
| Transcription starts but produces no text | Whisper is loading (30–60 s cold start for the `base` model). Wait and speak again. |
| `#Preview` compile error during build | Run `scripts/patch-for-local-build.sh` once (CommandLineTools-only machines). |

---

### 10.3 iOS Flutter app

> **Transcription limitation:** The iOS app sends audio via Opus. The local `listen.py` only handles PCM — Whisper receives undecoded Opus and produces garbage output. **Recording via the iOS app does not produce working transcripts.** Use the pin_bridge (§10.1) instead: it decodes Opus→PCM before sending to the backend and is the only fully working transcription path.

This path requires pointing the compiled-in API URL at the local backend, then building and deploying the dev flavor to a physical iPhone. No changes to `Info.plist` are needed — local network HTTP is already enabled via `NSAllowsLocalNetworking`.

#### Prerequisites
- macOS with Xcode installed (run `xcode-select --install` if not done)
- Flutter SDK installed and `flutter doctor` shows no errors for the iOS target
- Physical iPhone (the iOS Simulator cannot connect to LAN addresses reliably for BLE + local API)
- iPhone connected to the same Wi-Fi network as the Mac running the backend
- USB cable connecting the iPhone to the Mac (for first deploy; wireless development can be enabled afterward)
- Apple Developer account configured in Xcode (free account works for development builds)
- Local backend running and LAN-accessible (§10.0 done)

**Step 1.** Confirm `desktop/.env.app` and `app/.dev.env` exist and are synced.

If you ran `bash setup-clients.sh` from the project root, both files already
exist and the LAN IP is already synced — skip to Step 2.

Otherwise, from the project root:
```bash
# Set the LAN IP (replace with your backend Mac's actual IP from `ipconfig getifaddr en0`)
echo "LOCAL_MACHINE_HOST=<YOUR_SERVER_IP>" >> desktop/.env.app

# Create .dev.env and sync the IP in one step
bash scripts/sync-local-ip.sh
```

Confirm `LOCAL_AUTH_ENABLED=true` is in `app/.dev.env` (required for email/password sign-in):
```bash
grep LOCAL_AUTH_ENABLED app/.dev.env
# Expected: LOCAL_AUTH_ENABLED=true
```
If not present, add it:
```bash
echo "LOCAL_AUTH_ENABLED=true" >> app/.dev.env
```

The full `.dev.env` for local mode should look like:
```
API_BASE_URL=http://<YOUR_SERVER_IP>:8088
USE_WEB_AUTH=false
USE_AUTH_CUSTOM_TOKEN=true
LOCAL_AUTH_ENABLED=true
OPENAI_API_KEY=
GOOGLE_MAPS_API_KEY=
POSTHOG_API_KEY=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
STAGING_API_URL=
```

**Step 3.** Regenerate the obfuscated environment file.
The `envied` package bakes `API_BASE_URL` and `LOCAL_AUTH_ENABLED` into the compiled Dart code. Any change to `.dev.env` requires regenerating `dev_env.g.dart`:
```bash
cd app
flutter pub get
flutter pub run build_runner build --delete-conflicting-outputs
```
Expected output includes:
```
[INFO] build_runner: Succeeded after ...s with N outputs (0 actions)
```
If it fails with `Could not find .dev.env`:
- Confirm the file is at `app/.dev.env` (not `app/lib/.dev.env`)
- Run from the `app/` directory, not from a subdirectory

**Step 4.** Connect your iPhone via USB cable.

**Step 5.** Trust the Mac on the iPhone (if not previously done).
When you connect, the iPhone shows "Trust This Computer?" — tap Trust and enter your passcode.

**Step 6.** List connected devices to get the device ID:
```bash
flutter devices
```
Expected output includes a line like:
```
iPhone 15 Pro (mobile) • 00008120-001234567890123A • ios • iOS 17.5.1
```
Copy the device ID (the long hex string or UDID).

**Step 7.** Enable Developer Mode on the iPhone (iOS 16+):
On the iPhone: **Settings → Privacy & Security → Developer Mode** → toggle on → restart when prompted. Without this, the app will install but refuse to launch.

**Step 8.** Build and deploy the dev flavor to the device:
```bash
cd app
flutter run --flavor dev -d <device-id>
```
Replace `<device-id>` with the UDID from Step 6. Example:
```bash
flutter run --flavor dev -d 00008120-001234567890123A
```
The first build takes 2–5 minutes. Subsequent builds are faster.

If you see a code-signing error:
```
Xcode couldn't find any provisioning profiles matching...
```
Open Xcode, navigate to `app/ios/Runner.xcworkspace`, select the `dev` target, go to **Signing & Capabilities**, and set your Apple Developer Team. Let Xcode register the device and create a provisioning profile automatically.

**Step 9.** The app launches on the iPhone.
You will see the Omi sign-in screen.

**Step 10.** Sign in with email (local).
On the sign-in screen, tap **"Sign in with email  (local)"** at the bottom. Enter credentials for any account on the local backend — for example, `pin@omi.dev` / `hunter2` for the built-in pin user, or use the Register toggle to create a new account.

This button appears only when `LOCAL_AUTH_ENABLED=true` is compiled into the build. No Firebase auth or internet connection is required.

> **Alternatively**, sign in with Apple or Google if you have internet access and `LOCAL_AUTH_BYPASS=true` is set in `backend/.env`. The email/password path is recommended for development — no external auth dependency.

In the backend terminal, watch for the initial data load:
```
INFO:     192.168.x.x:xxxxx - "GET /v1/conversations HTTP/1.1" 200
INFO:     192.168.x.x:xxxxx - "GET /v1/memories HTTP/1.1" 200
```
If you see 401 responses: using Google/Apple sign-in and `LOCAL_AUTH_BYPASS` is not set, or the backend was not restarted after adding it.

**Step 11.** Pair the Omi pin from within the app.
Go to the device section in the app and tap "Add Device" or "Pair". Follow the on-screen Bluetooth pairing steps. The pin should appear as `Omi-XXXX`. Tap it to pair.

**Step 12.** Start recording.
Tap the record button. The app opens a WebSocket to:
```
ws://<YOUR_SERVER_IP>:8088/v4/listen?language=en&sample_rate=16000&codec=opus&...
```
In the backend terminal you should see:
```
INFO:     192.168.x.x:xxxxx - "WebSocket /v4/listen?language=en... 101"
```

> **Important — iOS transcription limitation.** The Omi pin sends Opus-encoded audio. The iOS app forwards raw Opus bytes with `codec=opus`, but the local `listen.py` only handles PCM. Opus bytes fed to Whisper without decoding produce garbage or empty transcripts. **The `pin_bridge.py` path (§10.1) is the only fully working transcription path today.** It decodes Opus→PCM before sending `codec=linear16`.

**Step 13.** Stop recording.
Tap stop. The backend logs:
```
INFO:routers_local.listen: Conversation <uuid> created for user <uid> (N segments)
```
The conversation appears in the app's conversation list.

**Step 14.** Verify in SQLite:
```bash
sqlite3 ~/Documents/codebase/OMI/code/backend/omi_local.db \
  "SELECT id, title, created_at FROM conversations ORDER BY created_at DESC LIMIT 5;"
```

#### When the LAN IP changes (iOS)
Only one file to edit — the sync script handles everything else:
```bash
# 1. Update the single source of truth
nano ~/Documents/codebase/OMI/code/desktop/.env.app   # set LOCAL_MACHINE_HOST=<new-ip>

# 2. Propagate to .dev.env
bash ~/Documents/codebase/OMI/code/scripts/sync-local-ip.sh

# 3. Regenerate compiled env
cd app
flutter pub run build_runner build --delete-conflicting-outputs

# 4. Rebuild and redeploy
flutter run --flavor dev -d <device-id>
```
No changes to `Info.plist` are needed — `NSAllowsLocalNetworking` covers all RFC-1918 LAN addresses without listing specific IPs.

#### Returning to the production backend (iOS)
1. Edit `app/.dev.env`: restore the prod `API_BASE_URL`, set `LOCAL_AUTH_ENABLED=false`
2. Run `flutter pub run build_runner build --delete-conflicting-outputs`
3. Rebuild and deploy

#### Troubleshooting (iOS)

| Symptom | Cause / fix |
|---------|-------------|
| Build fails: `Could not find .dev.env` | File is not at `app/.dev.env`. Create from: `cp app/.dev.env.example app/.dev.env`. |
| Build fails: conflicts in generated files | Run `flutter pub run build_runner build --delete-conflicting-outputs`. |
| `"Sign in with email  (local)"` button not visible | `LOCAL_AUTH_ENABLED=true` not in `.dev.env`, or build_runner was not re-run after adding it. |
| App shows "Network error" or requests fail after sign-in | `API_BASE_URL` wrong in `.dev.env`. Run `sync-local-ip.sh` and rebuild. Confirm backend is on `0.0.0.0:8088`. |
| `WebSocket /v4/listen` returns 403 in backend logs | Using Google/Apple sign-in: `LOCAL_AUTH_BYPASS` not set in `backend/.env`. Add and restart. |
| Local sign-in fails with "invalid credentials" | Account not registered. Use the Register toggle on the sign-in page, or create via Admin UI. |
| Transcription starts but no text appears | Whisper cold-start (30–60 s). Wait and speak again. Check backend logs for Whisper activity. |
| App connects to `/v4/listen` but immediately disconnects | Backend is running on `127.0.0.1` only. Restart with `start_local.sh` or `--host 0.0.0.0`. |
| Code signing error on deploy | Open `ios/Runner.xcworkspace` in Xcode → select dev target → Signing & Capabilities → set your Developer Team. |
| Developer Mode prompt not appearing (iOS 16+) | Go to **Settings → Privacy & Security → Developer Mode** and enable manually. |
| LAN IP changed (DHCP reassignment) | Run `sync-local-ip.sh`, then rebuild. No `Info.plist` change needed. |

---

### 10.4 Remaining limitations in local mode

Even with all three paths working, the following production features are absent locally:

| Feature | Status | Notes |
|---------|--------|-------|
| Memory extraction | Not automatic | Conversations are saved but LLM memory extraction does not run at end of session. Call `POST /v1/chat` with the transcript to extract manually. |
| Speaker diarization | Disabled | All segments labeled `SPEAKER_00`. Enable requires pyannote (GPU recommended). |
| Real-time memory events | Not emitted | `new_memory_created` WS events are not sent. App shows no memory pop-ups during recording. |
| Conversation timeout / silence detection | WS-close only | A new conversation is started only when the WebSocket closes, not after `conversation_timeout` seconds of silence during a live session. |
| iOS Opus transcription | Not working | iOS app sends raw Opus bytes with `codec=opus`; local `listen.py` only handles PCM. Audio arrives but Whisper produces garbage. Use `pin_bridge.py` (§10.1) for working transcription. |
| iOS offline audio (WAL sync) | Implemented | When the iOS app can't reach the backend, audio is buffered as `.bin` WAL files on the phone. On reconnect, the app uploads them to `POST /v2/sync-local-files`; poll `GET /v2/sync-local-files/{job_id}` for status. WAL files are Opus-encoded so require Opus decode — handled automatically by the sync endpoint. |
| TTS voice responses | 501 stub | ElevenLabs or Piper TTS not wired. |
| Agent proxy (chat agent) | Cloud only | The agent WebSocket (`agent.omi.me`) is not replicated locally. |
| Push notifications | Cloud only | Firebase Cloud Messaging required. |

---

### 10.5 Multi-machine LAN setup — backend on one machine, clients on others

The backend is designed to run on a single dedicated machine and accept connections from any device on the same local network. Clients — the BLE pin bridge, the macOS Desktop app, the iOS app — are fully independent of the machine the backend runs on. Only two things must be true:

1. The backend is bound to `0.0.0.0` (not `127.0.0.1`) — guaranteed by `start_local.sh` and the `--host 0.0.0.0` flag in §3.
2. Every client points its URL at the backend machine's LAN IP instead of `127.0.0.1`.

`§10.0` covers confirming the backend is LAN-accessible. Complete that section first regardless of which client you are setting up on a separate machine.

**The backend machine's LAN IP is set via `LOCAL_MACHINE_HOST` in `desktop/.env.app`.** If the IP changes (DHCP reassignment), update that one variable — `run-local.sh` derives all service URLs from it automatically.

---

#### 10.5.1 pin_bridge on a second Mac

`pin_bridge.py` only needs BLE hardware to reach the pin and a TCP/IP connection to reach the backend. It does not need the backend installed locally at all.

**What the second Mac needs (one-time):**

Copy or clone just the `pin_bridge/` folder from the repo:
```bash
# Option A — clone the full repo (simplest)
git clone <repo-url> ~/Documents/codebase/OMI/code

# Option B — copy only pin_bridge from the backend machine
scp -r <BACKEND_USER>@<YOUR_SERVER_IP>:~/Documents/codebase/OMI/code/pin_bridge \
    ~/Documents/codebase/OMI/code/pin_bridge
```

Install dependencies (no conda env required — plain Python 3.11 or any version ≥3.9 works):
```bash
brew install opus
pip install bleak opuslib websockets PyJWT
```

Bluetooth permission (one-time): run `python pin_bridge.py --scan-only` from your terminal app. macOS will prompt for Bluetooth access. Approve it. If the dialog never appeared: **System Settings → Privacy & Security → Bluetooth** — add your terminal app.

**Get a JWT without running anything on the second machine:**

The easiest way is the Admin UI's Get Token button:
1. Open `http://<YOUR_SERVER_IP>:8088/admin` in any browser on the LAN.
2. Sign in with the admin account.
3. Click **Get Token** next to the `pin@omi.dev` row.
4. Copy the token — it is valid for 24 h.

Alternatively, from any terminal with `curl`:
```bash
export TOKEN=$(curl -sS -X POST http://<YOUR_SERVER_IP>:8088/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"pin@omi.dev","password":"hunter2"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
```

**Run the bridge pointing at the backend machine:**

Set the two env vars that override the default `127.0.0.1` addresses, then run as normal:
```bash
cd ~/Documents/codebase/OMI/code/pin_bridge

export OMI_LOCAL_BACKEND="ws://<YOUR_SERVER_IP>:8088"
export OMI_LOCAL_BACKEND_HTTP="http://<YOUR_SERVER_IP>:8088"

python pin_bridge.py --token "$TOKEN"
```

Using `run.sh` (handles login automatically):
```bash
export OMI_LOCAL_BACKEND="ws://<YOUR_SERVER_IP>:8088"
export OMI_LOCAL_BACKEND_HTTP="http://<YOUR_SERVER_IP>:8088"
OMI_EMAIL=pin@omi.dev OMI_PASSWORD=hunter2 bash run.sh
```

`OMI_LOCAL_BACKEND` is read directly by `pin_bridge.py` as the default for `--backend`.
`OMI_LOCAL_BACKEND_HTTP` is read by `login.sh` when `run.sh` needs to fetch a JWT.
Everything else in §10.1 (scanning, speaking, Ctrl-C, offline drain) is identical.

**What the JWT being "remote" means:** The token is a signed string minted by the backend's `LOCAL_JWT_SECRET`. It doesn't matter which machine or tool generated it — when the WebSocket arrives at the backend, it validates the token the same way. Tokens are portable across machines on the same LAN.

---

#### 10.5.2 macOS Desktop app on a second Mac

On the second Mac, configure `desktop/.env.app` to point at the backend machine's LAN IP, then use `run-local.sh` exactly as in the single-machine setup.

**What the second Mac needs:**

The Desktop repo must be present (cloned from source). The backend itself does **not** need to be installed on the second Mac.

**Step 1.** Create or edit `desktop/.env.app` on the second Mac:
```bash
cat > ~/Documents/codebase/OMI/code/desktop/.env.app <<'EOF'
LOCAL_MACHINE_HOST=<YOUR_SERVER_IP>
DEEPGRAM_API_KEY=
EOF
```
Replace `<YOUR_SERVER_IP>` with the backend machine's actual LAN IP (§10.0 Step 1, run on the backend Mac).

`run-local.sh` will derive `OMI_PYTHON_API_URL=http://<YOUR_SERVER_IP>:8088` and `OMI_DESKTOP_API_URL=http://<YOUR_SERVER_IP>:10201` from `LOCAL_MACHINE_HOST` automatically — no manual URL exports needed.

**Step 2.** Launch:
```bash
cd desktop
./run-local.sh
```

From this point, follow §10.2 Steps 4–10 exactly — sign in, pair the pin, start transcription, verify the conversation. The only observable difference is that backend request logs appear in the backend machine's terminal, not the second Mac's terminal.

---

#### 10.5.3 iOS app on a separate device

The iOS app is always on a separate device by design — this is the standard case already described in §10.3. No additional changes are needed beyond what §10.3 already describes: `sync-local-ip.sh` sets `API_BASE_URL` from `LOCAL_MACHINE_HOST` in `.env.app`, which points directly at the backend machine's LAN IP.

Note the known transcription limitation from §10.4: the iOS app sends raw Opus audio and local `listen.py` only handles PCM, so transcription via the iOS app produces garbage. For working transcription on a separate device, use `pin_bridge.py` on a second Mac (§10.5.1).

---

#### 10.5.4 Summary — what changes per client

| Client | Where it runs | What to change from §10.x single-machine steps |
|--------|---------------|--------------------------------------------------|
| `pin_bridge.py` | Any Mac on the LAN | Set `OMI_LOCAL_BACKEND=ws://<YOUR_SERVER_IP>:8088` and `OMI_LOCAL_BACKEND_HTTP=http://<YOUR_SERVER_IP>:8088`. Get JWT via Admin UI Get Token or curl against the backend machine. |
| macOS Desktop app | Any Mac on the LAN | Set `LOCAL_MACHINE_HOST=<YOUR_SERVER_IP>` in `desktop/.env.app`, then run `./run-local.sh`. Everything else identical to §10.2. |
| iOS app | iPhone on the same Wi-Fi | No change — `sync-local-ip.sh` already sets `API_BASE_URL` from `LOCAL_MACHINE_HOST`. `Info.plist` uses `NSAllowsLocalNetworking` (no IP to update). Transcription limitation still applies. |
| Admin UI | Any browser on the LAN | Open `http://<YOUR_SERVER_IP>:8088/admin`. No setup required. |

The backend machine does not need to know or care which machine a connection comes from. As long as the token is valid and the network path is open (§10.0 firewall check), every client works identically from any machine on the LAN.

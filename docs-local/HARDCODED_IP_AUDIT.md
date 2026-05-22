# Hardcoded IP Audit — `<YOUR_SERVER_IP>`

> **Status: COMPLETED** — All 20 instances identified in this audit have been fixed.
> Backend Python and shell fallbacks use `localhost`. Desktop `run.sh` uses `_LOCAL_HOST="${LOCAL_MACHINE_HOST:-localhost}"`.
> Swift constants use `localhost`. This document is retained as a historical record.

This address is the LAN IP of the development machine. It must not exist in source
code. All code paths should fall back to `localhost` by default and allow override
via a single environment variable so the project stays portable and upstream-merge-safe.

---

## Part 1 — All Instances Found

Files are separated into **code** (must be fixed) and **documentation / backups**
(no action needed — IPs in docs are acceptable as examples).

---

### 1.1 Code Files — Action Required

#### Backend Python

| File | Line | Context |
|------|------|---------|
| `backend/database/vector_db_qdrant.py` | 28 | `QDRANT_URL = os.environ.get("QDRANT_URL", "http://<YOUR_SERVER_IP>:6333")` — env var supported but fallback is wrong |
| `backend/local_bootstrap.py` | 26 | `host = (os.environ.get("OLLAMA_HOST") or "http://<YOUR_SERVER_IP>:11434")` — env var supported but fallback is wrong |
| `backend/local_bootstrap.py` | 35 | `url = (os.environ.get("QDRANT_URL") or "http://<YOUR_SERVER_IP>:6333")` — env var supported but fallback is wrong |

#### Backend Shell Scripts

| File | Line | Context |
|------|------|---------|
| `backend/start_local.sh` | 74 | `${QDRANT_URL:-http://<YOUR_SERVER_IP>:6333}` — env var supported but fallback is wrong |
| `backend/start_local.sh` | 78 | `${QDRANT_URL:-http://<YOUR_SERVER_IP>:6333}` — env var supported but fallback is wrong |
| `backend/start_local.sh` | 175 | `echo "  API → http://<YOUR_SERVER_IP>:$PORT"` — display string, hardcoded |
| `backend/start_local.sh` | 176 | `echo "  Swagger UI → http://<YOUR_SERVER_IP>:$PORT/docs"` — display string, hardcoded |

#### Desktop Shell Script

| File | Line | Context |
|------|------|---------|
| `desktop/run.sh` | 58 | `export OMI_DESKTOP_API_URL="http://<YOUR_SERVER_IP>:10201"` — inside `--yolo` mode |
| `desktop/run.sh` | 59 | `export OMI_PYTHON_API_URL="http://<YOUR_SERVER_IP>:8088"` — inside `--yolo` mode |
| `desktop/run.sh` | 209 | `cloudflared tunnel --url http://<YOUR_SERVER_IP>:${BACKEND_PORT:-10201}` — tunnel origin |
| `desktop/run.sh` | 329 | `curl -s "http://<YOUR_SERVER_IP>:$BACKEND_PORT"` — backend health check |
| `desktop/run.sh` | 503 | `EFFECTIVE_API_URL="http://<YOUR_SERVER_IP>:$BACKEND_PORT"` — fallback URL when no tunnel |
| `desktop/run.sh` | 530 | `PYTHON_API_URL="http://<YOUR_SERVER_IP>:8088"` — fallback Python API URL |
| `desktop/run.sh` | 704 | `echo "Backend: http://<YOUR_SERVER_IP>:$BACKEND_PORT"` — display string |

#### Desktop Swift Source Files

| File | Line | Context |
|------|------|---------|
| `desktop/Desktop/Sources/DesktopBackendEnvironment.swift` | 4 | `static let productionPythonAPIURL = "http://<YOUR_SERVER_IP>:8088/"` — hardcoded production constant |
| `desktop/Desktop/Sources/DesktopBackendEnvironment.swift` | 5 | `static let developmentPythonAPIURL = "http://<YOUR_SERVER_IP>:8088/"` — hardcoded dev constant |
| `desktop/Desktop/Sources/DesktopBackendEnvironment.swift` | 6 | `static let developmentRustBackendURL = "http://<YOUR_SERVER_IP>:10201/"` — hardcoded dev constant |
| `desktop/Desktop/Sources/ProactiveAssistants/Core/GeminiClient.swift` | 170 | `return "http://<YOUR_SERVER_IP>:10201/"` — hardcoded fallback URL in a function |
| `desktop/Desktop/Sources/MainWindow/Pages/SettingsPage.swift` | 7052 | `url.hasPrefix("http://<YOUR_SERVER_IP>:")` — local URL detection pattern |
| `desktop/Desktop/Sources/APIClient.swift` | 367 | `return "http://<YOUR_SERVER_IP>:8088/admin/"` — hardcoded admin panel URL |
| `desktop/Desktop/Sources/MainWindow/Components/ConversationRowView.swift` | 146 | `let link = "http://<YOUR_SERVER_IP>:8088/admin/"` — hardcoded admin link |
| `desktop/Desktop/Sources/MainWindow/Components/ConversationRowView.swift` | 154 | `let link = "http://<YOUR_SERVER_IP>:8088/admin/"` — hardcoded admin link |
| `desktop/Desktop/Sources/OmiApp.swift` | 323 | `urlTag.contains("<YOUR_SERVER_IP>")` — local URL whitelist check |

**Total code instances: 20**

---

### 1.2 Documentation and Backup Files — No Action Required

These files are either backup env files, documentation, or IDE config. The IP
appearing here as an example or historical record is acceptable.

| File | Note |
|------|------|
| `backend/env_backups/20260506-233704-mobileios.env.txt` | Env backup — not loaded at runtime |
| `backend/env_backups/20260512-120423-backend.env.txt` | Env backup — not loaded at runtime |
| `backend/LOCAL_CAPABILITIES.md` | Documentation |
| `backend/LOCAL_IMPLEMENTATION_PLAN.md` | Documentation |
| `backend/PIN_LOCAL_AUDIO_SETUP.md` | Documentation |
| `PIN_LOCAL_GUIDE.md` | Documentation |
| `RUNBOOK.md` | Documentation |
| `UPSTREAM_SYNC_GUIDE.md` | Documentation |
| `web_paths.md` | Documentation |
| `.claude/settings.local.json` | IDE config — not part of the application |

---

## Part 2 — Root Cause Analysis

There are two distinct use cases that got conflated:

**Case A — Same-machine service connections** (backend → Qdrant, backend → Ollama):
These should always default to `localhost` (`127.0.0.1`). The service and its client
are on the same machine. There is never a reason to use a LAN IP here.

**Case B — Cross-device connections** (mobile app or desktop app → backend from
another device on the network):
These legitimately need the LAN IP because the connecting device cannot reach
`localhost` on a different machine. However, the IP should be configured once in
a `.env` or `.env.app` file and never hardcoded in source.

Currently the codebase hardcodes the LAN IP everywhere — even in Case A paths where
`localhost` is correct — because it was set up to work on one specific machine and
the address was pasted in wherever needed.

---

## Part 3 — Fix Plan

### 3.1 Introduce a single env variable for the LAN IP

Add one variable to `backend/env.local.template`:

```
# LAN IP of this machine — used when other devices (mobile, desktop) need to reach
# the backend over the local network. Leave as localhost if everything runs on one machine.
LOCAL_MACHINE_HOST=localhost
```

This is the ONLY place `<YOUR_SERVER_IP>` (or any LAN IP) should ever appear.
All code references use `LOCAL_MACHINE_HOST` (or its per-service port variants)
instead of hardcoding the address.

For the desktop `run.sh`, the equivalent is a `.env.app` override or an exported
shell variable before calling `run-local.sh`.

---

### 3.2 Backend Python fixes

**`backend/database/vector_db_qdrant.py` line 28**

Change:
```python
QDRANT_URL = os.environ.get("QDRANT_URL", "http://<YOUR_SERVER_IP>:6333")
```
To:
```python
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
```
Rationale: Qdrant always runs on the same machine as the backend. `localhost` is
always correct as the fallback.

---

**`backend/local_bootstrap.py` line 26**

Change:
```python
host = (os.environ.get("OLLAMA_HOST") or "http://<YOUR_SERVER_IP>:11434").rstrip("/")
```
To:
```python
host = (os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
```

---

**`backend/local_bootstrap.py` line 35**

Change:
```python
url = (os.environ.get("QDRANT_URL") or "http://<YOUR_SERVER_IP>:6333").rstrip("/")
```
To:
```python
url = (os.environ.get("QDRANT_URL") or "http://localhost:6333").rstrip("/")
```

---

### 3.3 Backend shell script fixes

**`backend/start_local.sh` lines 74, 78**

Both use `${QDRANT_URL:-http://<YOUR_SERVER_IP>:6333}` as a fallback.
Change the fallback to `${QDRANT_URL:-http://localhost:6333}` in both places.

**`backend/start_local.sh` lines 175–176** (display strings)

These print the server address at startup. Replace the hardcoded IP with a variable:
```bash
LOCAL_MACHINE_HOST="${LOCAL_MACHINE_HOST:-localhost}"
echo "  API            →  http://$LOCAL_MACHINE_HOST:$PORT"
echo "  Swagger UI     →  http://$LOCAL_MACHINE_HOST:$PORT/docs"
```
The script should read `LOCAL_MACHINE_HOST` from the loaded `.env` so the displayed
URL is always correct for the current machine.

---

### 3.4 Desktop `run.sh` fixes

This script has the highest concentration of hardcoded IPs. All occurrences fall
into three patterns:

**Pattern 1 — `--yolo` mode (lines 58–59)**

YOLO mode is a local dev shortcut and its URLs should come from a variable, not
be hardcoded. Extract to a variable resolved before the YOLO block executes:

```bash
# Resolved once; used by yolo mode, health checks, and fallback URL.
_LOCAL_HOST="${LOCAL_MACHINE_HOST:-localhost}"

if [ "$1" = "--yolo" ]; then
    export OMI_SKIP_BACKEND=1
    export OMI_SKIP_TUNNEL=1
    export OMI_DESKTOP_API_URL="http://$_LOCAL_HOST:10201"
    export OMI_PYTHON_API_URL="http://$_LOCAL_HOST:8088"
    ...
fi
```

**Pattern 2 — Cloudflare tunnel origin (line 209)**

```bash
cloudflared tunnel --url http://$_LOCAL_HOST:${BACKEND_PORT:-10201} > "$TUNNEL_LOG" 2>&1 &
```
The tunnel connects cloudflared to the Rust backend. The correct host here is
whatever host the Rust backend actually bound to — `localhost` when running
locally, or the LAN IP when bridging from another device.

**Pattern 3 — Health check, fallback URL, Python URL, display (lines 329, 503, 530, 704)**

Replace all four occurrences with `$_LOCAL_HOST`:
- Line 329: `curl -s "http://$_LOCAL_HOST:$BACKEND_PORT"`
- Line 503: `EFFECTIVE_API_URL="http://$_LOCAL_HOST:$BACKEND_PORT"`
- Line 530: `PYTHON_API_URL="http://$_LOCAL_HOST:8088"`
- Line 704: `echo "Backend:  http://$_LOCAL_HOST:$BACKEND_PORT (PID: $BACKEND_PID)"`

`_LOCAL_HOST` is set at the top of the script from the env var with `localhost` as
the default. Users who need LAN access set `LOCAL_MACHINE_HOST=<YOUR_SERVER_IP>` in
their shell or `.env` before running.

---

### 3.5 Desktop Swift source fixes

The Swift app reads its backend URLs from the bundled `.env` file that `run.sh`
injects at build time. The Swift constants in `DesktopBackendEnvironment.swift` are
fallback values used when the `.env` is absent (e.g., in unit tests or CI builds).
They must never point to a machine-specific LAN IP.

**`DesktopBackendEnvironment.swift` lines 4–6**

Change all three constants to `localhost`:
```swift
static let productionPythonAPIURL = "http://localhost:8088/"
static let developmentPythonAPIURL = "http://localhost:8088/"
static let developmentRustBackendURL = "http://localhost:10201/"
```

**`GeminiClient.swift` line 170**

Change the hardcoded fallback return value:
```swift
return "http://localhost:10201/"
```

**`APIClient.swift` line 367**

Change the admin URL fallback:
```swift
return "http://localhost:8088/admin/"
```

**`ConversationRowView.swift` lines 146 and 154**

Change both admin link constants:
```swift
let link = "http://localhost:8088/admin/"
```

**`SettingsPage.swift` line 7052** (local URL whitelist)

This check determines whether a URL is considered "local" for UI routing purposes.
It should use the same `LOCAL_MACHINE_HOST` value read from the app's env bundle
rather than a hardcoded address. Simplest fix that preserves the pattern:
```swift
url.hasPrefix("http://127.0.0.1:") || url.hasPrefix("http://localhost:")
```
The LAN IP check can be removed from this pattern because the app should connect
using URLs from its `.env` bundle — if the bundle says `localhost`, the URLs it
navigates to will say `localhost`. If a user has configured `LOCAL_MACHINE_HOST`
to a LAN IP, the `.env` bundle will carry that IP and the URLs will match the
existing `127.0.0.1` / `localhost` checks only when `localhost` is configured.

Alternatively, read `OMI_PYTHON_API_URL` from the environment at startup and use
its host as the local URL prefix — that way any configured IP works automatically.

**`OmiApp.swift` line 323**

Same fix as SettingsPage — drop the `<YOUR_SERVER_IP>` check:
```swift
|| urlTag.contains("trycloudflare.com")
```
Only the Cloudflare tunnel check needs to remain as-is. The LAN IP check is
unnecessary if the app reads its URLs from the `.env` bundle.

---

### 3.6 `run-local.sh` (the new wrapper script)

The `run-local.sh` wrapper already avoids hardcoding by using:
```bash
export OMI_DESKTOP_API_URL="${OMI_DESKTOP_API_URL:-http://localhost:10201}"
export OMI_PYTHON_API_URL="${OMI_PYTHON_API_URL:-http://localhost:8088}"
```
No change needed here — it is already correct.

---

## Part 4 — Implementation Order

Do these in sequence to avoid breaking the running system:

1. **Backend Python** (`vector_db_qdrant.py`, `local_bootstrap.py`) — change three fallbacks from `<YOUR_SERVER_IP>` to `localhost`. Zero runtime impact because the `.env` file already sets `QDRANT_URL` and `OLLAMA_HOST` to the correct address.

2. **Backend shell** (`start_local.sh`) — change two Qdrant fallbacks and two display strings. Low risk.

3. **Desktop shell** (`run.sh`) — introduce `_LOCAL_HOST` variable at the top of the script. All seven occurrences become one-line changes referencing that variable. Set `LOCAL_MACHINE_HOST` in your shell before running if you need LAN access.

4. **Swift constants** (`DesktopBackendEnvironment.swift`, `GeminiClient.swift`, `APIClient.swift`, `ConversationRowView.swift`) — change six hardcoded strings to `localhost`. These are fallback values only; the running app reads from the `.env` bundle injected by `run.sh`, so these constants are only hit in test/CI contexts.

5. **Swift URL patterns** (`SettingsPage.swift`, `OmiApp.swift`) — remove the `<YOUR_SERVER_IP>` check from both whitelist/detection conditions.

6. **`env.local.template`** — add `LOCAL_MACHINE_HOST=localhost` with a comment explaining how to override to a LAN IP.

---

## Part 5 — Verification After Fix

After making all changes, verify with:

```bash
# Should return zero results in code files
grep -rn "192\.168\.50\.46" \
  backend/*.py backend/**/*.py \
  backend/*.sh \
  desktop/run.sh \
  desktop/Desktop/Sources/ \
  2>/dev/null
```

The only remaining occurrences will be in documentation files and `env_backups/`,
which are acceptable.

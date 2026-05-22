# GAPS — Remaining Work for 100% Local-Only Operation

This document exhaustively lists every known gap between the current state of the codebase and a fully self-contained, zero-cloud-dependency system. Gaps are grouped by severity. Each entry names the affected file(s), describes the failure mode, and proposes the minimal fix.

**Current state summary:** `main_local.py` + `routers_local/` form a working local API (auth, chat, memories, conversations, transcribe, WS). The original `main.py` and its 45 routers are untouched and still require all cloud credentials. The local app is the recommended entrypoint and passes all smoke tests.

---

## Severity legend

| Label | Meaning |
|-------|---------|
| **CRITICAL** | Will crash or produce incorrect results today, even in the recommended local entrypoint |
| **HIGH** | Causes a silent failure or 500 error on a documented feature |
| **MEDIUM** | Missing feature or degraded behavior that is noticeable in normal use |
| **LOW** | Edge case, documentation gap, or quality improvement |

---

## CRITICAL gaps — all resolved

All 8 CRITICAL gaps have been fixed. The changes below document what was done
and the residual notes for future maintainers.

---

### GAP-1 — `main.py` crashes immediately without Firebase credentials ✅ FIXED

**Affected files:** `backend/main.py` (line 1–30 approximately)

**Failure mode:** `firebase_admin.initialize_app()` is called unconditionally at module import time. If a developer or operator runs `uvicorn main:app` (the original entrypoint) without exporting `FIREBASE_*` env vars, the process exits with a `ValueError` or `FileNotFoundError` before any route is registered. There is no feature-flag guard.

**Why it matters:** Anyone who finds the project and follows the original README will hit this immediately. The new `main_local.py` sidesteps it entirely, but the gap remains for contributors who touch the original file.

**Fix:** Wrap the firebase init block:
```python
if get_auth_provider() == "firebase":
    import firebase_admin
    from firebase_admin import credentials
    firebase_admin.initialize_app(credentials.Certificate(...))
```
Move all firebase-dependent imports inside the same guard. This is a lazy-import pattern and does not change any cloud-mode behavior.

---

### GAP-2 — `database/vector_db.py` (Pinecone) imported by 12+ production modules ✅ FIXED

**Affected files:** `backend/database/vector_db.py`, `backend/utils/conversations/`, `backend/utils/retrieval/`

**Failure mode:** The existing `vector_db.py` creates a Pinecone client at import time using `PINECONE_API_KEY`. Any module that does `from database.vector_db import upsert_vector` crashes with `PineconeException` when the key is absent, even if the call site is never reached at runtime.

**Why it matters:** This affects every endpoint that touches conversation processing, memory extraction, or retrieval — which is most of the high-value functionality. In local mode these paths would silently 500.

**Fix:** Rename `database/vector_db.py` → `database/vector_db_pinecone.py`. Create a new `database/vector_db.py` that acts as a thin dispatcher:
```python
from providers import get_vector_db_provider
if get_vector_db_provider() == "qdrant":
    from database.vector_db_qdrant import *
else:
    from database.vector_db_pinecone import *
```
No callers change. The compat shim in `vector_db_qdrant.py` already maps method names.

---

### GAP-3 — Firestore database modules crash on first call in local mode ✅ FIXED (root cause)

**Affected files:** `backend/database/conversations.py` (~1079 LOC), `backend/database/users.py` (~1362 LOC), `backend/database/memories.py`, `backend/database/action_items.py`, `backend/database/apps.py`

**Failure mode:** All of these files import `from database._client import db` which is the Firestore singleton. In local mode `GOOGLE_APPLICATION_CREDENTIALS` is unset, so `db` is `None` or raises immediately. Any endpoint that touches these modules returns 500.

**Why it matters:** The SQL repository (`database/sql/repository.py`) exists and is correct, but nothing in the production path calls it. The local routers bypass the issue by importing from `database.sql.repository` directly. If any production utility is ever called from `main_local.py`, it will crash.

**Fix:** Add provider dispatch at the top of each database module:
```python
from providers import get_db_provider
if get_db_provider() == "sqlite":
    from database.sql import repository as _repo
    def get_conversation(uid, cid): return _repo.get_conversation(uid, cid)
    # ... etc.
```
Or move the local implementations into a `database/local/` package mirroring the same function signatures.

---

### GAP-4 — 60+ LLM call sites bypass the router entirely ✅ FIXED

**Affected files:** `backend/utils/llm/chat.py`, `backend/utils/llm/memories.py`, `backend/utils/llm/conversation_processing.py`, `backend/utils/llm/notifications.py`, `backend/utils/llm/proactive_notification.py`, `backend/utils/llm/goals.py`, `backend/utils/llm/trends.py`, `backend/utils/llm/external_integrations.py`, `backend/utils/llm/fair_use_classifier.py`, `backend/utils/llm/app_generator.py`, `backend/utils/llm/knowledge_graph.py`, `backend/utils/llm/persona.py`, `backend/utils/llm/followup.py`, `backend/utils/llm/openglass.py`

**Failure mode:** Every one of these files does `from utils.llm.clients import llm_mini` or `get_llm()` which resolves to the OpenAI client. `utils/llm/router.py` is the correct local-mode dispatcher but is currently only used by `routers_local/chat.py`. The remaining ~60 call sites silently use OpenAI.

**Why it matters:** Memory extraction, conversation processing, notification generation, and all agent-style reasoning flows use OpenAI. In a local-only system this leaks data to OpenAI and requires `OPENAI_API_KEY`.

**Fix:** Patch `utils/llm/clients.py` to make `llm_mini` and `get_llm()` delegate through the router:
```python
from utils.llm.router import chat as _chat
def llm_mini(messages, **kw): return _chat(messages, **kw)
```
This is a one-file fix that fixes all 60+ call sites simultaneously without touching them.

---

### GAP-5 — Embeddings calls bypass the router ✅ FIXED

**Affected files:** `backend/database/vector_db.py` (Pinecone path), `backend/utils/retrieval/`, `backend/utils/llm/clients.py`

**Failure mode:** `from utils.llm.clients import embeddings` resolves to `openai.Embedding.create()`. In local mode this hits OpenAI for every memory creation and every semantic search. `utils/embeddings/router.py` exists and routes to the local sentence-transformers model but is not called from any production code path.

**Critical dimension mismatch:** OpenAI text-embedding-3-large = 3072 dims; sentence-transformers/all-MiniLM-L6-v2 = 384 dims. If any Qdrant collection was created with 3072 dims and local embeddings produce 384-dim vectors, every upsert and search silently fails or returns wrong results. The local collection setup reads `LOCAL_EMBEDDINGS_DIM` (default 384) which prevents this if a fresh collection is created, but mixing cloud and local embeddings in the same collection is catastrophic.

**Fix:** Same as GAP-4 — patch `utils/llm/clients.py` to make `embeddings` delegate through `utils/embeddings/router.py`. Add a startup check that the Qdrant collection dimension matches the configured embeddings dim.

---

### GAP-6 — STT routing not wired in production `routers/transcribe.py` ✅ FIXED (import guarded)

**Affected files:** `backend/routers/transcribe.py` (~2900 LOC)

**Failure mode:** `routers/transcribe.py` directly imports `from utils.stt.streaming import process_audio_dg` and `from utils.stt.pre_recorded import deepgram_prerecorded`. These call Deepgram. In local mode Deepgram credentials are absent, so any call to the production transcribe endpoints returns 500 or hangs indefinitely.

**Why it matters:** The local transcribe endpoint in `routers_local/transcribe.py` works correctly, but it is a parallel endpoint. If anything in the production app calls the Deepgram path, it fails silently.

**Fix:** In `utils/stt/` add a dispatch layer analogous to the LLM router. The local providers already exist in `utils/stt/providers/`. The `routers_local/transcribe.py` can serve as the reference implementation.

---

### GAP-7 — Firebase auth dependency in `dependencies.py` ✅ FIXED

**Affected files:** `backend/dependencies.py`

**Failure mode:** `get_current_user_id()` calls `firebase_admin.auth.verify_id_token(token)`. Every production router that uses `uid: str = Depends(get_current_user_id)` will raise `firebase_admin.auth.InvalidIdTokenError` in local mode because local JWTs are HS256 (PyJWT) not Firebase ID tokens.

**Why it matters:** This blocks every authenticated endpoint in the production routers from being used in local mode, even if the other cloud dependencies were resolved.

**Fix:** Make `get_current_user_id` dispatch based on provider:
```python
from providers import get_auth_provider
async def get_current_user_id(token=Depends(oauth2_scheme)):
    if get_auth_provider() == "local":
        from auth.router_dep import get_current_user_id_local
        return await get_current_user_id_local(token)
    # existing firebase path
```

---

### GAP-8 — No `/v1/auth/register` or `/v1/auth/login` in `main.py` ✅ FIXED

**Affected files:** `backend/routers/auth.py`

**Failure mode:** The production `routers/auth.py` implements only Google and Apple OAuth callback routes. There is no username/password registration or login endpoint. Users can only authenticate through `main_local.py` + `routers_local/auth.py`.

**Why it matters:** If the local frontend or a third-party client tries to log in via `main.py` (e.g., after a future integration), there is no login route to call. The local auth system is completely invisible to the production entrypoint.

**Fix:** Add `POST /v1/auth/register` and `POST /v1/auth/login` to `routers/auth.py` behind `if get_auth_provider() == "local":` guards, delegating to `auth.local_auth`.

---

## HIGH gaps

---

### GAP-9 — Cloud-only feature imports crash at `main.py` startup ✅ FIXED

**Affected files:** `backend/main.py`, `backend/utils/subscription.py`, `backend/utils/observability.py`

**Failure mode:** `main.py` calls `validate_stripe_price_ids()` and `log_langsmith_status()` at module import level. Without `STRIPE_API_KEY` / `LANGSMITH_API_KEY`, these either raise exceptions or print error logs on every boot. `feature_flags.py` exists but is not checked at these call sites.

**Fix:** Wrap each startup call:
```python
if is_enabled("stripe"):
    validate_stripe_price_ids()
if is_enabled("langsmith"):
    log_langsmith_status()
```

---

### GAP-10 — Pusher publishers have no local replacement in production paths ✅ FIXED

**Affected files:** `backend/pusher/`, `backend/routers/conversations.py`, `backend/utils/conversations/`

**Failure mode:** Post-processing pipelines (memory extraction, action item detection, notifications) send results to the Pusher service via `HOSTED_PUSHER_API_URL`. In local mode this URL is unset, so all real-time events (transcript complete, memory created, notification) are silently dropped. Users never receive feedback that processing completed.

**Why it matters:** This makes the async processing pipeline invisible — the system appears to hang or do nothing after conversation submission.

**Fix:** `events/connection_manager.py` is the local WebSocket broadcast system. Production post-processing code needs to call `events.router.broadcast()` when `get_event_provider() == "websocket"`. A thin `push_event(user_id, event)` function that dispatches to the right backend would fix all call sites.

---

### GAP-11 — Typesense not gated; crashes on missing host ✅ FIXED

**Affected files:** `backend/typesense/`, `backend/routers/search.py` (if included)

**Failure mode:** `typesense.Client()` is instantiated with `TYPESENSE_HOST`. If the host is unreachable, the client constructor may succeed but every search call times out or raises. `search/router.py` with the SQLite FTS5 implementation exists but is not used by any production router.

**Fix:** Guard the Typesense client creation behind `if get_search_provider() == "typesense":`. Wire `search/router.py` into `main_local.py` (already done) and add it to `main.py` behind the same guard.

---

### GAP-12 — Stripe/billing crashes on missing API key ✅ FIXED

**Affected files:** `backend/routers/payment.py`, `backend/utils/subscription.py`

**Failure mode:** `stripe.api_key = os.environ["STRIPE_API_KEY"]` raises `KeyError` at import if the var is absent. This crashes the entire `main.py` process if `routers/payment.py` is imported.

**Fix:** `if not is_enabled("stripe"): raise HTTPException(501)` at the top of every payment route handler. Move the `stripe.api_key` assignment inside that guard.

---

### GAP-13 — Synchronous Ollama chat blocks the event loop ✅ FIXED

**Affected files:** `backend/routers_local/chat.py`, `backend/utils/llm/providers/ollama_client.py`

**Failure mode:** `POST /v1/chat` is defined as a sync function. Inside it, `ollama_client.chat()` calls `httpx.Client.post()` — a blocking HTTP call. FastAPI runs sync endpoints in a thread pool, which is correct, but:
1. Thread pool exhaustion occurs when many concurrent chat requests pile up.
2. Health checks and WebSocket handlers share the same event loop; if the thread pool is full, health probes from Docker or load balancers time out.
3. The Ollama timeout is 300s; 10 simultaneous stuck requests consume 10 threads indefinitely.

**Fix:** Convert `chat()` to `async def` and use `httpx.AsyncClient`:
```python
async def chat(messages, model, **kw):
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(...)
```
`astream()` in `ollama_client.py` already does this correctly — the sync `chat()` should follow the same pattern.

---

### GAP-14 — Qdrant search blocks the event loop ✅ FIXED

**Affected files:** `backend/routers_local/memories.py`, `backend/database/vector_db_qdrant.py`

**Failure mode:** `POST /v1/memories/search` is async but internally calls the synchronous `qdrant_client.QdrantClient` which uses `urllib3` under the hood. The synchronous client blocks the event loop if called from an async context without `asyncio.to_thread()`.

**Fix:** Wrap all synchronous Qdrant calls:
```python
results = await asyncio.to_thread(vdb.search_memories_by_vector, uid, vector, limit)
```
Or switch to `qdrant_client.AsyncQdrantClient` throughout `vector_db_qdrant.py`.

---

### GAP-15 — No health probes for Ollama or Qdrant at startup ✅ FIXED

**Affected files:** `backend/local_bootstrap.py`

**Failure mode:** `bootstrap_local()` initializes SQLite and optionally creates an admin user but never verifies that Ollama (`GET /api/version`) or Qdrant (`GET /healthz`) are reachable. A misconfigured `OLLAMA_HOST` or `QDRANT_URL` produces an opaque 500 or connection-refused error on the first API call, not at startup.

**Why it matters:** In a Docker Compose setup, Qdrant may not be ready when the API starts. A health check probe with a retry loop at startup gives the operator a clear message and prevents confusing per-request errors.

**Fix:**
```python
def _probe_ollama():
    try:
        httpx.get(f"{_ollama_host()}/api/version", timeout=5).raise_for_status()
    except Exception as e:
        log.warning("Ollama not reachable at startup: %s", e)

def _probe_qdrant():
    try:
        httpx.get(f"{os.environ.get('QDRANT_URL','http://localhost:6333')}/healthz", timeout=5)
    except Exception as e:
        log.warning("Qdrant not reachable at startup: %s", e)
```
Call both from `bootstrap_local()`.

---

### GAP-16 — No CORS middleware in `main_local.py` ✅ FIXED

**Affected files:** `backend/main_local.py`

**Failure mode:** Browser-based clients (JavaScript fetch, future local web UI, Swagger UI in some configs) hit CORS preflight (`OPTIONS`) requests that return no `Access-Control-Allow-Origin` header. The browser rejects the response. This affects any client that is not the Omi mobile app (which uses a WebView that bypasses CORS).

**Fix:**
```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
For production deployments, restrict `allow_origins` to known hosts.

---

### GAP-17 — No action items router in local mode ✅ FIXED

**Affected files:** `backend/routers_local/` (missing `action_items.py`)

**Failure mode:** The SQLite `ActionItem` ORM model and repository CRUD helpers exist. But there is no HTTP endpoint to create, list, update, or delete action items locally. Any client that calls `GET /v1/action-items` or `POST /v1/action-items` receives a 404.

**Fix:** Add `routers_local/action_items.py` with standard CRUD routes and register it in `main_local.py`. The implementation is mechanical — mirror `routers_local/memories.py` substituting `action_items` CRUD calls.

---

### GAP-18 — Conversation transcription does not auto-persist ✅ FIXED

**Affected files:** `backend/routers_local/transcribe.py`

**Failure mode:** `POST /v1/transcribe` and `WS /v1/transcribe/stream` return transcript text/segments but do not:
1. Create a `Conversation` row in SQLite.
2. Create `TranscriptSegment` records.
3. Embed the transcript text into Qdrant (ns1 / conversations namespace).
4. Trigger memory extraction via the LLM.

The full loop — audio → transcript → saved conversation → searchable memory — requires 3–4 separate manual API calls after every transcription. In production Omi, this happens automatically.

**Fix:** After a successful transcription in `routers_local/transcribe.py`, call:
```python
conv_id = repo.create_conversation(uid, {"title": ..., "transcript": text})
vdb.upsert_conversation(uid, conv_id, text, embedding)
```
This can be an optional behavior gated on a config flag (`AUTO_PERSIST_TRANSCRIPTS=true`).

---

## MEDIUM gaps

---

### GAP-19 — SQLite data stored in plaintext (security regression vs. cloud) ✅ FIXED (chmod 0o600)

**Affected files:** `backend/database/sql/repository.py`, `backend/database/helpers.py`

**Failure mode:** In cloud mode, `database/helpers.py` applies AES-256-GCM per-user encryption to every Firestore document via a decorator. In local mode, all data (conversations, memories, messages) is stored as plaintext in `omi_local.db`. If the SQLite file is exfiltrated, all user data is readable.

**`ENCRYPTION_SECRET` is set in `.env` but never used by the SQL layer.**

**Fix:** Add an optional encryption layer to `database/sql/repository.py` that encrypts/decrypts `text` and `content` columns using `ENCRYPTION_SECRET`. This can be implemented as a SQLAlchemy `TypeDecorator`. A simpler short-term fix: enable SQLite WAL mode and set file permissions to 600 (`os.chmod("omi_local.db", 0o600)`).

---

### GAP-20 — Knowledge graph (Neo4j) has no local replacement ✅ FIXED (501 stub)

**Affected files:** `backend/database/knowledge_graph.py`, `backend/routers/knowledge_graph.py`

**Failure mode:** `knowledge_graph.py` creates a Neo4j driver at import time using `NEO4J_URI`. Without a running Neo4j instance, the driver creation fails or all queries return errors. There is no local graph database configured. Knowledge graph features (entity extraction, relationship mapping between people/topics/events) are completely absent in local mode.

**Fix options:**
1. **Short term:** Gate all knowledge graph routes behind `if is_enabled("knowledge_graph"):` and return 501 in local mode. Document the gap.
2. **Long term:** Use SQLite self-joins and FTS5 as a poor-man's entity graph, or stand up a lightweight graph DB like Memgraph (Docker image ~500 MB).

---

### GAP-21 — No local TTS (Text-to-Speech) ✅ FIXED (501 stub)

**Affected files:** `backend/routers/tts.py` (cloud only, ElevenLabs)

**Failure mode:** `GET /v1/tts` calls ElevenLabs. In local mode, any client requesting speech synthesis receives a 500 or an error about missing `ELEVEN_LABS_API_KEY`. There is no TTS endpoint in `routers_local/`.

**Fix options:**
1. **Short term:** Return 501 from a stub `routers_local/tts.py`.
2. **Long term:** Integrate [Piper](https://github.com/rhasspy/piper) (fast, runs on CPU, MIT license) or `edge-tts` (Microsoft Edge TTS via CLI, free, no key required). Piper produces natural-sounding speech with ~100 MB models.

---

### GAP-22 — Redis fair-use tracking silently disabled ✅ FIXED (startup warning log)

**Affected files:** `backend/database/redis_db.py`, `backend/utils/fair_use.py`

**Failure mode:** `utils/fair_use.py` tracks rolling speech-hour usage via Redis minute-bucket keys. Without Redis, the `redis_db.py` fail-open wrapper silently swallows every call and returns `None`. Fair-use limits (speech hours per user per month) are completely disabled. This is acceptable for single-user local mode but means there is no abuse protection if the local server is ever exposed to a network.

**Note:** Redis is the only remaining service not replaced. The fail-open behavior means the backend does not crash, but the gap should be documented for operators who expose the API to multiple users.

---

### GAP-23 — `pin_bridge.py` FrameAssembler drops multi-chunk Opus frames ✅ FIXED

**Affected files:** `pin_bridge/pin_bridge.py` — `FrameAssembler` class

**Failure mode:** When the BLE negotiated MTU is smaller than the Opus frame payload (rare at modern MTU ≥ 185 bytes, but possible on older BLE stacks), a single Opus frame is split across multiple notifications: sub_index 0 (first chunk), sub_index 1 (second chunk), etc. The current `FrameAssembler` emits and decodes on the sub_index==0 notification only, then clears the buffer. When sub_index==1 arrives, `current_id` has been reset to `None`, so the chunk is counted as `out_of_order` and discarded. The decoded audio is truncated, producing garbled speech.

**At modern MTUs (185+ bytes) this never triggers** because CODEC_OUTPUT_MAX_BYTES=160, so each frame fits in one notification. The bug is latent.

**Fix:** Only emit and decode when a *new* packet_id arrives (signaling the previous frame is complete):
```python
if sub_index == 0 and self.current_id is not None:
    self._emit(self.current_id, self.current_buf)  # emit previous
    self.current_buf = bytearray()
```
Emit the last accumulated frame on `END`.

---

### GAP-24 — Offline SD card drain not implemented in `pin_bridge.py` ✅ FIXED

**Affected files:** `pin_bridge/pin_bridge.py`, `pin_bridge/pin_offline_drain.py` (new)

**Failure mode:** When `CONFIG_OMI_ENABLE_OFFLINE_STORAGE=y` is set in the firmware and the pin reconnects after being offline, the firmware streams SD card contents over the storage GATT service (UUID `30295780-4301-EABD-2904-2849ADFEAE43`). `pin_bridge.py` did not subscribe to or enumerate this service. Audio recorded while the pin was offline was silently ignored and never transcribed.

**Fix:** Created `pin_offline_drain.py` implementing the full multi-file GATT storage protocol from `omi/firmware/omi/src/lib/core/storage.c`:
- CMD_LIST_FILES (0x10) → file count + per-file (timestamp, size)
- CMD_READ_FILE (0x11, index, offset) → 1-byte ack, data notifications with 4-byte ts prefix, done byte (0x64)
- Firmware auto-deletes successfully transferred files
- `_parse_audio_chunk()` handles `[size:1][opus_data]*` packed SD format
- `drain_offline_storage()` decodes Opus frames and feeds them into the live `send_queue`

Integrated into `stream_session()` in `pin_bridge.py`: called immediately after haptic write, before entering `stop_event.wait()`. Import is guarded so the bridge works without the drain module if missing.

---

### GAP-25 — Haptic/button BLE characteristics not handled in `pin_bridge.py` ✅ FIXED

**Affected files:** `pin_bridge/pin_bridge.py`

**Failure mode:** The pin exposes:
- Button state characteristic (UUID `23BA7924-1234-5678-9ABC-DEF012345678` — verify in firmware `buttons.c`) for detecting single/double/long press.
- Haptic control characteristic (UUID `CAB1AB95-…`) for sending vibration patterns to the pin.

`pin_bridge.py` subscribes to neither. Button presses that could signal start/stop recording, mark a moment, or dismiss a notification are silently ignored. There is no way to give the user tactile confirmation via the bridge.

**Fix:** Subscribe to the button state characteristic in the GATT setup phase. On notification, parse the press type and call the appropriate API (`POST /v1/conversations` to start a new segment, etc.). For haptic, write to the haptic characteristic at key moments (transcription complete, error).

---

## LOW gaps

---

### GAP-26 — `SETUP_FROM_SCRATCH.md` does not mention `brew install opus` for the pin bridge ✅ FIXED

**Affected files:** `code/SETUP_FROM_SCRATCH.md`

**Failure mode:** A user who follows `SETUP_FROM_SCRATCH.md` end-to-end to set up a new Mac will not have `libopus` installed. When they later try `pip install opuslib` or run `pin_bridge.py`, it fails with `ImportError: libopus not found` or a similar ctypes error. The opus brew installation is documented in `pin_bridge/README.md` but not in the main setup guide.

**Fix:** Add to §3 of `SETUP_FROM_SCRATCH.md`:
```bash
brew install git curl wget jq sqlite ffmpeg opus
```
Add a note: "`opus` is required only if you plan to use `pin_bridge`; it provides the native Opus codec library that `opuslib` wraps."

---

### GAP-27 — `.env.template` defaults to cloud providers; copying it as-is breaks local mode ✅ FIXED

**Affected files:** `backend/.env.template`

**Failure mode:** The template was updated to include local provider knobs, but the defaults remain cloud-oriented (`LLM_PROVIDER=openai`, etc., or blank). A developer who copies `.env.template` to `.env` without carefully reading every line will get a mix of local and cloud settings that causes confusing partial failures.

**Fix:** Add a clearly marked local-mode block at the top of `.env.template`:
```bash
# ── LOCAL MODE (copy these 10 lines for a fully local setup) ──────────
LLM_PROVIDER=ollama
STT_PROVIDER=local
EMBEDDINGS_PROVIDER=local
VECTOR_DB_PROVIDER=qdrant
AUTH_PROVIDER=local
DB_PROVIDER=sqlite
EVENT_PROVIDER=websocket
SEARCH_PROVIDER=disabled
# ... etc.
# ─────────────────────────────────────────────────────────────────────
```
Or create a separate `.env.local.example` that contains only the local-mode configuration with all values filled in.

---

### GAP-28 — `routers/oauth.py` not gated; will fail in local mode if included ✅ FIXED

**Affected files:** `backend/routers/oauth.py`

**Failure mode:** `routers/oauth.py` is not included in `main_local.py` (correct), but it is imported by `main.py`. If a future developer adds it to `main_local.py` for any reason, the Google/Apple OAuth credential lookups will fail immediately. More importantly, the existing inclusion in `main.py` means the OAuth routes are live even in a partially-local setup, and they call Firebase auth methods.

**Fix:** Guard the router registration in `main.py`:
```python
if get_auth_provider() != "local":
    from routers import oauth
    app.include_router(oauth.router)
```

---

## Summary table

| # | Gap | Severity | Effort |
|---|-----|----------|--------|
| 1 | `main.py` Firebase init crashes on missing creds | CRITICAL | Small |
| 2 | Pinecone `vector_db.py` imported at module level | CRITICAL | Medium |
| 3 | Firestore database modules crash on call | CRITICAL | Large |
| 4 | 60+ LLM call sites bypass router | CRITICAL | Small (one-file fix) |
| 5 | Embeddings bypass router, dimension mismatch risk | CRITICAL | Small |
| 6 | STT not routed in production `routers/transcribe.py` | CRITICAL | Medium |
| 7 | Firebase auth in `dependencies.py` | CRITICAL | Small |
| 8 | No register/login in `main.py` | CRITICAL | Small |
| 9 | Stripe/Langsmith crash at startup | HIGH | Small |
| 10 | Pusher has no local replacement in prod paths | HIGH | Medium |
| 11 | Typesense not gated | HIGH | Small |
| 12 | Stripe crashes on missing key at import | HIGH | Small |
| 13 | Sync Ollama chat blocks event loop | HIGH | Small |
| 14 | Sync Qdrant search blocks event loop | HIGH | Small |
| 15 | No startup health probes for Ollama/Qdrant | HIGH | Small |
| 16 | No CORS middleware in `main_local.py` | HIGH | Trivial |
| 17 | No action items router in local mode | HIGH | Small |
| 18 | Transcription does not auto-persist conversations | HIGH | Medium |
| 19 | SQLite stored in plaintext | MEDIUM | Medium |
| 20 | Knowledge graph (Neo4j) has no local replacement | MEDIUM | Large |
| 21 | No local TTS | MEDIUM | Medium |
| 22 | Redis fair-use tracking silently disabled | MEDIUM | Small (document only) |
| 23 | FrameAssembler drops multi-chunk Opus frames | MEDIUM | Small |
| 24 | Offline SD card drain not in `pin_bridge.py` | MEDIUM | Large | ✅ FIXED |
| 25 | Haptic/button characteristics not handled | MEDIUM | Small |
| 26 | `SETUP_FROM_SCRATCH.md` missing `brew install opus` | LOW | Trivial |
| 27 | `.env.template` defaults mislead local-mode setup | LOW | Trivial |
| 28 | `routers/oauth.py` not gated | LOW | Trivial |

---

## Recommended sequencing

**Week 1 (unblock the current entrypoint):**
- GAP-16 (CORS) — trivial, do it now
- GAP-15 (startup probes) — prevents confusing first-run errors
- GAP-13, GAP-14 (async Ollama and Qdrant) — correctness under any load
- GAP-17 (action items router) — completes the local CRUD surface

**Week 2 (make `main.py` local-compatible):**
- GAP-1, GAP-7, GAP-8 (Firebase guards in main.py and dependencies.py)
- GAP-4, GAP-5 (LLM and embeddings route through the router — one-file fix)
- GAP-2 (vector_db dispatcher)
- GAP-9, GAP-11, GAP-12 (Stripe, Typesense, Langsmith guards)

**Week 3 (complete the data layer):**
- GAP-3 (Firestore module dispatch to SQL)
- GAP-6 (STT routing in production transcribe.py)
- GAP-10 (Pusher → events/connection_manager.py)
- GAP-18 (auto-persist conversations after transcription)

**Later / as needed:**
- GAP-19 (SQLite encryption)
- GAP-20 (knowledge graph 501 stub or Memgraph)
- GAP-21 (Piper TTS)
- GAP-23 (FrameAssembler multi-chunk fix)
- GAP-25 (haptic/button) — ✅ done
- GAP-26, GAP-27, GAP-28 (documentation and template fixes)

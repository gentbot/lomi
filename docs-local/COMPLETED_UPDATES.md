# Omi Local Backend — Completed Updates & Remaining Work

> **Historical implementation log.** The local backend is operational. This document
> records what was built during the initial implementation. Some items described as
> "remaining work" were superseded by the `main_local.py` approach (a clean separate
> entry point rather than modifying `main.py`). For current status see `LOCAL_CAPABILITIES.md`.

This document tracks every change, addition, and fix applied to the codebase to make
the Omi backend run fully locally (no cloud credentials required). Items are grouped
by area. Checkbox = done; open box = not yet done.

---

## 1. Core Application Bootstrap

- [x] **`main_local.py` created** — standalone FastAPI entrypoint that never imports cloud-dependent routers; loads `.env` on startup via `python-dotenv`
- [x] **`local_bootstrap.py` created** — single startup function that initialises every local subsystem (SQLite schema, Qdrant collection, Whisper model, embeddings model, Ollama reachability probe, Qdrant health probe)
- [x] **`providers.py` created** — single source of truth for all eight provider selectors (`LLM_PROVIDER`, `STT_PROVIDER`, `EMBEDDINGS_PROVIDER`, `VECTOR_DB_PROVIDER`, `AUTH_PROVIDER`, `DB_PROVIDER`, `EVENT_PROVIDER`, `SEARCH_PROVIDER`); unrecognised values silently fall back to cloud defaults
- [x] **`main.py` Firebase crash fixed (GAP-1)** — guarded all Firebase/Pusher/Stripe imports behind provider checks so `main.py` no longer aborts on startup without cloud credentials
- [x] **`main.py` Stripe router gated (GAP-12)** — payment router only loads when `STRIPE_API_KEY` is present
- [x] **`main.py` OAuth router gated (GAP-28)** — `routers/oauth.py` only loads when `AUTH_PROVIDER != local`
- [x] **`main.py` LangSmith / cloud feature guards (GAP-9)** — LangSmith, Stripe, and other cloud-only imports wrapped in `is_enabled()` checks
- [x] **Root redirect** — `GET /` now redirects to `/docs` instead of returning 404; navigating to the server in a browser lands on Swagger automatically
- [x] **CORS middleware** — `allow_origins=["*"]` added to `main_local.py` (GAP-16); all clients including mobile and LAN machines can reach the API

---

## 2. Provider / Routing Layer

- [x] **LLM router created (`utils/llm/router.py`)** — routes `generate`, `chat`, `achat`, `stream`, `astream`, `extract_actions` to either Ollama or OpenAI based on `LLM_PROVIDER`; all local call sites use this router (GAP-4)
- [x] **Embeddings router created (`utils/embeddings/router.py`)** — dispatches to local sentence-transformers or OpenAI based on `EMBEDDINGS_PROVIDER` (GAP-5)
- [x] **STT router wired (`utils/stt/providers/`)** — `local_streaming.py` and `local_whisper_prerecorded.py` added; router dispatches to Deepgram or local Whisper based on `STT_PROVIDER` (GAP-6)
- [x] **Vector DB router created** — dispatches to Qdrant or Pinecone based on `VECTOR_DB_PROVIDER` (GAP-2)
- [x] **Firestore database modules guarded (GAP-3)** — all `database/*.py` modules that import the Firestore client are protected; local paths use `database/sql/repository.py`
- [x] **Search router created (`search/router.py`)** — dispatches to Typesense, local SQLite FTS5, or disabled based on `SEARCH_PROVIDER`
- [x] **Typesense import guard (GAP-11)** — `utils/conversations/search.py` wraps `typesense.Client()` in `try/except (ImportError, Exception)`; raises a clear error if called when disabled

---

## 3. LLM — Ollama Integration

- [x] **`utils/llm/providers/ollama_client.py` created** — full Ollama HTTP client: `generate`, `chat`, `achat`, `stream`, `astream`, `extract_actions`; sync and async paths; `OLLAMA_TIMEOUT` configurable
- [x] **Async Ollama (GAP-13)** — `achat` and `astream` use native `httpx.AsyncClient`; never blocks the FastAPI event loop
- [x] **Ollama startup health probe (GAP-15)** — `local_bootstrap.py` verifies Ollama is reachable at boot; logs the URL and fails fast if unreachable
- [x] **Per-purpose model variables** — `OLLAMA_CHAT_MODEL` (chat/streaming) and `OLLAMA_EXTRACT_MODEL` (generate/action-extraction) added with fallback chain to `OLLAMA_MODEL`; allows different models for different tasks without changing code
- [x] **Remote Ollama support** — `OLLAMA_HOST` can point at any host on the network (e.g. a NAS at `<YOUR_CLIENT_IP>:11434`); start script detects remote vs. local and skips local start/pull accordingly

---

## 4. Speech-to-Text — Local Whisper

- [x] **`utils/stt/providers/local_whisper_prerecorded.py` created** — lazy-loads `faster-whisper` `WhisperModel`; configurable via `LOCAL_WHISPER_MODEL`, `LOCAL_WHISPER_DEVICE`, `LOCAL_WHISPER_COMPUTE_TYPE`
- [x] **`utils/stt/providers/local_streaming.py` created** — accumulates PCM16 chunks over a WebSocket into configurable-length windows then calls Whisper; configurable via `LOCAL_STREAM_CHUNK_SECONDS`, `LOCAL_STREAM_SAMPLE_RATE`, etc.
- [x] **Per-session sample rate support** — `start_stream()` now accepts an optional `sample_rate` kwarg; the session-specific rate propagates through `push_audio_chunk` → `end_stream` → `_write_wav`. Callers that omit the kwarg continue to use the module-level `SAMPLE_RATE` default (16 kHz). Required so `/v4/listen` can receive 8 kHz audio from the BLE pin and write correct WAV headers before Whisper processes each chunk.
- [x] **8 kHz → 16 kHz upsampling in `/v4/listen`** — `listen.py` uses numpy linear interpolation to upsample pin `pcm8` frames (8000 Hz) to 16000 Hz before forwarding to `local_streaming`; Desktop `linear16` (16000 Hz) passes through unchanged
- [x] **`utils/stt/local_vad.py` created** — Voice Activity Detection with two backends: RMS energy heuristic (default, zero deps) and Silero neural VAD (optional, auto-falls-back)
- [x] **Whisper base model downloaded** — `~/.cache/huggingface/hub/models--Systran--faster-whisper-base` (~141 MB); ready to use without a network connection
- [x] **`KMP_DUPLICATE_LIB_OK=TRUE` fix** — macOS abort caused by PyTorch and ctranslate2 each bundling `libiomp5.dylib` is resolved; set in `.env`, `.env.template`, and `start_local.sh`

---

## 5. Embeddings — Local sentence-transformers

- [x] **`utils/embeddings/local_embeddings.py` created** — wraps `sentence-transformers`; configurable via `LOCAL_EMBEDDINGS_MODEL` and `LOCAL_EMBEDDINGS_DIM`; lazy-loads on first call
- [x] **Default model** — `sentence-transformers/all-MiniLM-L6-v2` (384-dim); downloads automatically on first use

---

## 6. Database — SQLite

- [x] **`database/sql/db.py` created** — SQLAlchemy engine + session factory; supports SQLite (default) and PostgreSQL via `SQL_URL` or `SQLITE_PATH`
- [x] **`database/sql/models.py` created** — ORM models for all local entities: users, memories, conversations, messages, action items
- [x] **`database/sql/repository.py` created** — full CRUD for all models; replaces Firestore read/write paths in local mode
- [x] **Schema auto-initialised** — `local_bootstrap.py` calls `init_db()` on startup; tables created automatically if they don't exist
- [x] **SQLite file permissions hardened (GAP-19)** — `local_bootstrap.py` chmods the database file to `0o600` (owner read/write only) after creation
- [x] **Redis absent warning (GAP-22)** — startup logs a clear info message when `REDIS_DB_HOST` is not set, explaining which features are disabled (rate-limiting, fair-use, pub/sub)

---

## 7. Auth — Local JWT

- [x] **`auth/local_auth.py` created** — PBKDF2-SHA256 password hashing; HS256 JWT signing; configurable via `LOCAL_JWT_SECRET`, `LOCAL_JWT_TTL_SECONDS`, `LOCAL_JWT_ALGORITHM`
- [x] **`auth/router_dep.py` created** — FastAPI dependency that validates Bearer tokens from both local JWT and Firebase paths
- [x] **`routers_local/auth.py` created** — `POST /v1/auth/register`, `POST /v1/auth/login`, `GET /v1/auth/me`
- [x] **Bootstrap admin user** — `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` env vars create an admin account on first boot if absent (GAP-8)
- [x] **Firebase auth dependency guarded (GAP-7)** — `dependencies.py` no longer imports Firebase unconditionally; local JWT path used when `AUTH_PROVIDER=local`

---

## 8. Vector DB — Qdrant

- [x] **Qdrant client wired** — `qdrant-client>=1.9` used; compatibility shim handles API differences between versions
- [x] **Qdrant startup health probe (GAP-15)** — `local_bootstrap.py` verifies Qdrant is reachable and creates the memories collection if it doesn't exist
- [x] **Async Qdrant search (GAP-14)** — vector search calls wrapped in `asyncio.to_thread()` to avoid blocking the event loop

---

## 9. Events — WebSocket

- [x] **`events/connection_manager.py` created** — in-process WebSocket connection manager; tracks per-user connections; replaces Pusher in local mode
- [x] **`events/router.py` created** — `push_event()` convenience wrapper dispatches events through the active provider (Pusher or WebSocket); Pusher null guard added (GAP-10)
- [x] **`routers_local/ws.py` created** — `ws://host/ws?token=<jwt>` endpoint; authenticated WebSocket for push events to clients

---

## 10. Search — Local SQLite FTS5

- [x] **`search/local_search.py` created** — SQLite FTS5 full-text search over conversations; zero extra infrastructure
- [x] **`search/router.py` created** — dispatches to Typesense, local FTS5, or returns 501 based on `SEARCH_PROVIDER`

---

## 11. API Routes (local mode)

- [x] **`routers_local/auth.py`** — register, login, me
- [x] **`routers_local/chat.py`** — `POST /v1/chat`, `POST /v1/chat/stream` (streaming SSE)
- [x] **`routers_local/memories.py`** — full CRUD + semantic search via Qdrant
- [x] **`routers_local/conversations.py`** — full CRUD + messages sub-resource
- [x] **`routers_local/action_items.py`** — full CRUD: create, list, get, patch, delete (GAP-17)
- [x] **`routers_local/transcribe.py`** — `POST /v1/transcribe` (file upload) + `ws:///v1/transcribe/stream` (live PCM streaming); `AUTO_PERSIST_TRANSCRIPTS` flag auto-saves completed transcripts as Conversations (GAP-18)
- [x] **`routers_local/ws.py`** — general-purpose push WebSocket
- [x] **`routers_local/knowledge_graph.py`** — 501 stubs for GET/POST/DELETE (no local Neo4j equivalent) (GAP-20)
- [x] **`routers_local/tts.py`** — 501 stub for `POST /v2/tts/synthesize` (no local TTS) (GAP-21)
- [x] **`routers_local/listen.py` created — `/v4/listen` WebSocket** — full production-compatible audio streaming endpoint; accepts the same query parameters (`language`, `sample_rate`, `codec`, `channels`, `uid`, `include_speech_profile`, `source`, `conversation_timeout`, `speaker_auto_assign`) and emits the same JSON event shapes as the production backend: `transcript_segment`, `conversation_processing_started`, `conversation_event`; handles 8 kHz BLE pin audio (upsampled) and 16 kHz Desktop audio; creates a Conversation in SQLite and indexes in Qdrant on WebSocket close; auth accepts local JWT or any Bearer token when `LOCAL_AUTH_BYPASS=true`
- [x] **`GET /healthz`** — returns full provider matrix; useful for verifying configuration

---

## 12. BLE Pin Bridge (`pin_bridge/`)

- [x] **`pin_bridge.py` FrameAssembler rewritten (GAP-23)** — original code emitted a frame on every BLE notification, corrupting multi-chunk Opus frames at low MTU; new implementation holds chunks until the next `sub_index==0` boundary then emits the complete frame; `flush()` handles end-of-stream
- [x] **Haptic and button characteristics added (GAP-25)** — `OMI_HAPTIC_CHAR_UUID` and `OMI_BUTTON_CHAR_UUID` constants defined and lowercased; `write_haptic()` helper added; button notifications subscribed at connect; haptic "ready" pulse sent on connect; cleanup on disconnect
- [x] **`pin_offline_drain.py` created (GAP-24)** — implements the full multi-file GATT storage protocol from the OMI pin firmware (`storage.c`): CMD_LIST_FILES, CMD_READ_FILE, 4-byte timestamp prefix stripping, `[size:1][opus_data]*` SD block parser, done-byte detection; decoded PCM frames are fed into the live `send_queue`; integrated into `stream_session()` automatically on every connect
- [x] **Offline drain integrated into `pin_bridge.py`** — called after haptic write, before `stop_event.wait()`; guarded import so bridge works without the drain module
- [x] **`pin_bridge.py` migrated to `/v4/listen`** — default endpoint changed from `/v1/transcribe/stream` to `/v4/listen?sample_rate=16000&codec=linear16&language=en`; auth changed from first-frame JWT to `Authorization: Bearer` header; reader updated to handle `transcript_segment`, `conversation_processing_started`, `conversation_event` events; `--legacy-endpoint` CLI flag preserves old behaviour; `use_v4_listen` parameter added to `stream_session()`

---

## 13. Developer Experience

- [x] **`start_local.sh` created** — single script starts Docker/Qdrant, Ollama (local or remote), and uvicorn; detects remote Ollama via `OLLAMA_HOST`; polls model availability via `/api/tags` HTTP (works for remote hosts); non-fatal pull with graceful warning for read-only model stores; shows LAN IP in startup banner; `--port` and `--host` flags
- [x] **`stop_local.sh` created** — stops uvicorn, Qdrant container, and Ollama cleanly
- [x] **`omi-start` / `omi-stop` shell functions** — added to `~/.aliases`; callable from any directory; pass arguments through; use `breaker` for consistent output style
- [x] **`.env` file created** — full local-mode configuration pointing at remote Ollama (`<YOUR_CLIENT_IP>:11434`), local Qdrant, local Whisper, local SQLite; all eight providers set to local values
- [x] **`.env.template` LOCAL MODE block (GAP-27)** — commented ready-to-use local mode block at the top; all 14 local-mode variables pre-filled
- [x] **`.env.template` per-purpose Ollama vars** — `OLLAMA_CHAT_MODEL` and `OLLAMA_EXTRACT_MODEL` documented with fallback explanation
- [x] **`.env.template` `KMP_DUPLICATE_LIB_OK`** — macOS OpenMP workaround documented in both LOCAL MODE block and main section
- [x] **`.env.reference` created** — comprehensive 500-line reference documenting every environment variable with all valid values, defaults, trade-offs, and notes; not loaded by the app (documentation only)
- [x] **`web_paths.md` created** — full list of every URL the backend serves with method, auth requirement, and description; includes quick-start `curl` examples
- [x] **`SETUP_FROM_SCRATCH.md` updated (GAP-26)** — `brew install opus` added to Step 3; required by `opuslib` for `pin_bridge.py`
- [x] **`COMPLETED_UPDATES.md` created** — this file
- [x] **`PIN_LOCAL_GUIDE.md` created** — exhaustive guide for connecting the Omi pin to the local backend from both the iOS Flutter app and the macOS Desktop app; covers architecture gap analysis, all required backend changes (with code), app redirection steps, auth options, iOS ATS exception, validation steps, event protocol reference, and known limitations

---

## 14. Configuration & Security

- [x] **Remote Ollama** — `OLLAMA_HOST` accepts any URL; tested against NAS at `<YOUR_CLIENT_IP>:11434`
- [x] **LAN binding** — uvicorn binds `0.0.0.0` by default (was `127.0.0.1`); accessible from any machine on the local network; `--host` flag in `start_local.sh` to revert to localhost-only
- [x] **SQLite file permissions** — database file chmoded to `0o600` on creation
- [x] **Bash 3 compatibility** — `start_local.sh` uses only POSIX/bash-3-compatible syntax; `declare -A` (requires bash 4+) replaced with string-sentinel deduplication
- [x] **`LOCAL_AUTH_BYPASS=true` — full stack coverage** — when set, both `/v4/listen` (WebSocket) and all REST endpoints (`/v1/conversations`, `/v1/memories`, `/v1/chat`, etc.) accept Firebase ID tokens without Firebase Admin SDK validation; `bypass_uid_from_token()` in `auth/local_auth.py` extracts the Firebase UID from the JWT `sub` claim (stable across token refreshes — Firebase tokens rotate hourly but the UID is constant); `router_dep.py` and `listen.py` both use the same helper so the user ID is identical across WebSocket and REST paths; clearly marked dev/LAN-only in `.env` comments

---

## 15. Remaining / Not Yet Done

### High priority

- [ ] **`main.py` cutover (§3.1–§3.13)** — `main.py` still requires cloud credentials at startup; the full 45-router production app has not been migrated to the provider-dispatch pattern; `main_local.py` remains the only supported local entrypoint
- [ ] **iOS Flutter app `.dev.env` update** — `API_BASE_URL` in `app/.dev.env` still points at the cloud backend; must be changed to `http://<lan-ip>:8088/` and the app rebuilt for the pin to stream to the local backend; full instructions in `PIN_LOCAL_GUIDE.md §5`
- [ ] **iOS ATS exception** — plain HTTP connections are blocked by default on iOS via App Transport Security; `NSExceptionAllowsInsecureHTTPLoads` for the local IP must be added to `app/ios/Runner/Info.plist`; see `PIN_LOCAL_GUIDE.md §5.6`
- [ ] **macOS Desktop `OMI_PYTHON_API_URL` env var** — the Desktop app reads `OMI_PYTHON_API_URL` at launch; setting it to `http://<lan-ip>:8088/` is the only change needed; no code changes required; see `PIN_LOCAL_GUIDE.md §4.2`; this env var is not yet persisted in any launch script or system preferences
- [ ] **HTTPS / TLS** — the backend runs plain HTTP; connections over the LAN are unencrypted; a reverse proxy (nginx, Caddy) or self-signed cert would be needed for secure LAN use or to avoid the iOS ATS exception

### Medium priority

- [x] **`pin_bridge.py` `/v4/listen` migration** — `pin_bridge.py` now defaults to `/v4/listen` (full conversation lifecycle: conversations auto-created in SQLite, events emitted, Qdrant indexed); auth uses `Authorization: Bearer` header on WS upgrade; reader logs `transcript_segment`, `conversation_processing_started`, and `conversation_event` events; `--legacy-endpoint` flag falls back to `/v1/transcribe/stream` (first-frame JWT, no conversation lifecycle)
- [x] **`pin_bridge/README.md` updated** — updated to reflect current defaults: `/v4/listen` as default endpoint, conversation lifecycle, header auth; removed all "not yet implemented" claims; updated troubleshooting table and env var table
- [ ] **Knowledge graph** — `routers_local/knowledge_graph.py` returns 501; no local graph DB is wired; would require Memgraph or a SQLite-backed entity store
- [ ] **TTS (Text-to-Speech)** — `routers_local/tts.py` returns 501; no local TTS engine is wired; Piper TTS or Coqui would be candidates
- [ ] **Speaker diarization** — `ENABLE_DIARIZATION=false` in local mode; the diarizer is a separate GPU service (pyannote); no local single-process path exists yet; all segments currently labeled `SPEAKER_00`
- [ ] **Redis** — not running locally; rate-limiting, fair-use tracking, and pub/sub are all disabled (fail-open); a Docker Redis container is all that's needed to enable them
- [x] **Memory extraction from conversations** — `utils/llm/post_process.py` created; `run_post_process()` task launched from `/v4/listen` and `/v2/sync-local-files` after each conversation; extracts title, summary, category, action items, and personal facts via Ollama; creates `Memory` and `ActionItem` rows; upserts to Qdrant; emits `new_memory_created` and `new_action_item` WebSocket events
- [ ] **Postgres support** — `DB_PROVIDER=postgres` is wired in the provider layer and SQLAlchemy but has not been validated end-to-end; `SQL_URL` must be set manually

### Low priority / cloud-only features

The items below are permanently unavailable in local mode because they depend on external cloud infrastructure that cannot be self-hosted. Full explanations are in `UNFIXABLE_FEATURES.md`.

- **Stripe / payments** — requires licensed card-network processor; fails open (all features unlocked locally)
- **Push notifications (iOS / Android)** — requires Apple APNs / Google FCM; WebSocket events cover foreground delivery
- **Twilio phone calls** — requires PSTN carrier interconnect; not applicable on LAN
- **Google/Apple/Notion/Whoop/Twitter OAuth** — requires app registration with each platform's auth server
- **Deepgram STT** — cloud API; already replaced locally by `STT_PROVIDER=local` (faster-whisper)
- **ElevenLabs TTS** — cloud API; local alternative (Piper) is in the implementation backlog
- **Perplexity web search** — cloud API; local alternative (SearXNG) is in the implementation backlog
- **LangSmith tracing** — SaaS-only; disabled by default (`LANGSMITH_TRACING=false`)
- **GCS storage buckets** — Google Cloud project; MinIO re-integration possible but not yet done
- **HuggingFace gated models** — requires accepted usage agreement via HF account
- **iOS app redirect + ATS exception** — requires Apple Developer account + custom Xcode build; see `PIN_LOCAL_GUIDE.md §5` and `IMPLEMENTATION_PLAN.md PLAN-1` (HTTPS/TLS via Caddy eliminates the ATS issue)

Items that are *not yet done but are locally fixable*:
- [ ] **Bootstrap admin user** — uncomment `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` in `.env`
- [ ] **Email notifications** — no SMTP provider configured; could use local mailhog or system Postfix
- [x] **`/docs` access control** — `DOCS_API_KEY` env var added to `main_local.py`; when set, `/docs`, `/redoc`, and `/openapi.json` require `?key=<value>` or `X-Docs-Key` header; documented in `RUNBOOK.md §7.1.1` and `.env.template`

---

## 16. LLM Post-Processing Pipeline

- [x] **`utils/llm/post_process.py` created** — `process_conversation(transcript)` sends the full transcript to Ollama via the LLM router and parses a JSON response with title, overview, category, action_items, and facts; `run_post_process(uid, conv_id, full_text)` is an async orchestrator intended to run as a fire-and-forget `asyncio.create_task()`
- [x] **`repository.update_conversation()` added** — updates title, structured JSON, and status for an existing conversation; used by the post-processing pipeline to replace raw-text truncation placeholders with LLM-generated content
- [x] **`repository.get_memory()` added** — fetch a single memory by ID with user ownership check; mirrors the existing `get_action_item()` pattern
- [x] **Post-processing wired into `/v4/listen`** — `_finalize()` now launches `post_process.run_post_process()` via `asyncio.create_task()` after saving the conversation; action items and memories are extracted in the background without blocking the WebSocket response
- [x] **Post-processing wired into `/v2/sync-local-files`** — same task launched in `_process_job()` after the WAL conversation is created; offline-recorded audio is enriched with the same LLM pipeline
- [x] **`new_memory_created` and `new_action_item` WebSocket events wired** — `routers_local/memories.py` and `routers_local/action_items.py` now call `push_event()` after each row is created; events are silently dropped when `EVENT_PROVIDER != websocket` (non-WebSocket providers raise `NotImplementedError` which is caught)
- [x] **Conversation silence timeout watchdog implemented** — `_silence_watchdog()` task in `listen.py` polls every 5 s; when `conversation_timeout` seconds of silence is detected and segments exist, it ends the STT stream, finalizes and saves the current conversation, clears the segment buffer, and starts a fresh STT stream for the next conversation; disabled when `conversation_timeout=0`

---

## File Index — New Files Added

| File | Purpose |
|------|---------|
| `backend/main_local.py` | Local FastAPI entrypoint |
| `backend/local_bootstrap.py` | Startup initialisation for all local subsystems |
| `backend/providers.py` | Provider selector (all 8 subsystems) |
| `backend/auth/local_auth.py` | PBKDF2 + HS256 JWT auth |
| `backend/auth/router_dep.py` | FastAPI auth dependency (local + Firebase) |
| `backend/database/sql/db.py` | SQLAlchemy engine + session |
| `backend/database/sql/models.py` | ORM models |
| `backend/database/sql/repository.py` | CRUD layer |
| `backend/events/connection_manager.py` | WebSocket connection manager |
| `backend/events/router.py` | Event dispatch + `push_event()` |
| `backend/utils/llm/router.py` | LLM router |
| `backend/utils/llm/providers/ollama_client.py` | Ollama HTTP client |
| `backend/utils/embeddings/router.py` | Embeddings router |
| `backend/utils/embeddings/local_embeddings.py` | sentence-transformers wrapper |
| `backend/utils/stt/providers/local_streaming.py` | Streaming Whisper STT |
| `backend/utils/stt/providers/local_whisper_prerecorded.py` | File-upload Whisper STT |
| `backend/utils/stt/local_vad.py` | Voice activity detection (energy + Silero) |
| `backend/search/local_search.py` | SQLite FTS5 search |
| `backend/search/router.py` | Search provider router |
| `backend/routers_local/auth.py` | Auth endpoints |
| `backend/routers_local/chat.py` | Chat + streaming endpoints |
| `backend/routers_local/memories.py` | Memories CRUD + semantic search |
| `backend/routers_local/conversations.py` | Conversations CRUD + messages |
| `backend/routers_local/action_items.py` | Action items CRUD |
| `backend/routers_local/transcribe.py` | File upload + WebSocket transcription |
| `backend/routers_local/ws.py` | Push events WebSocket |
| `backend/routers_local/knowledge_graph.py` | Knowledge graph 501 stubs |
| `backend/routers_local/tts.py` | TTS 501 stub |
| `backend/routers_local/listen.py` | `/v4/listen` full conversation-lifecycle WebSocket (production-compatible) |
| `backend/utils/llm/post_process.py` | LLM post-processing pipeline (title, summary, memories, action items) |
| `backend/start_local.sh` | Single-command stack startup |
| `backend/stop_local.sh` | Single-command stack shutdown |
| `backend/.env` | Active local configuration |
| `backend/.env.reference` | Full environment variable documentation |
| `pin_bridge/pin_offline_drain.py` | Offline SD card audio drain (GATT storage protocol) |
| `SETUP_FROM_SCRATCH.md` | Full install guide for a new Mac |
| `GAPS.md` | Gap tracker (all 28 gaps resolved) |
| `web_paths.md` | All backend URLs with descriptions |
| `COMPLETED_UPDATES.md` | This file |
| `PIN_LOCAL_GUIDE.md` | Exhaustive LLM-ready guide for connecting pin to local backend (iOS + Desktop) |

## File Index — Modified Files

| File | What changed |
|------|-------------|
| `backend/main.py` | Firebase/Stripe/OAuth imports gated; crash on missing credentials fixed |
| `backend/.env.template` | LOCAL MODE block added; per-purpose Ollama vars; KMP flag; cloud defaults preserved |
| `backend/utils/conversations/search.py` | Typesense import wrapped in `try/except`; null guard in `search_conversations()` |
| `backend/utils/pusher.py` | Null guard at top of `_connect_to_trigger_pusher` |
| `backend/utils/llm/providers/ollama_client.py` | `_model_for(purpose)` helper; per-purpose model selection |
| `backend/local_bootstrap.py` | SQLite chmod; Redis absent warning; Ollama + Qdrant health probes |
| `backend/utils/stt/providers/local_streaming.py` | `start_stream()` gains optional `sample_rate` param; per-session rate propagated through `_write_wav` and `_transcribe_pcm` |
| `backend/main_local.py` | Root redirect to `/docs`; `listen` router imported and registered; `DOCS_API_KEY` middleware added |
| `backend/database/sql/repository.py` | `update_conversation()` and `get_memory()` added |
| `backend/routers_local/listen.py` | Post-processing task launched from `_finalize()`; silence watchdog added; `last_audio_at` tracking |
| `backend/routers_local/sync.py` | Post-processing task launched after WAL conversation creation |
| `backend/routers_local/memories.py` | `push_event()` called after memory creation |
| `backend/routers_local/action_items.py` | `push_event()` called after action item creation |
| `backend/.env` | `LOCAL_AUTH_BYPASS=true` added |
| `pin_bridge/pin_bridge.py` | FrameAssembler rewritten; haptic/button UUIDs and subscription; offline drain integrated |
| `~/.aliases` | `omi-start` and `omi-stop` shell functions added |

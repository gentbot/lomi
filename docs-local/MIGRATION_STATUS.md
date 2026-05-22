Phase 0 — config + resolver                                                                                                                                                                                    
  - backend/.env.template: added *_PROVIDER knobs + local-stack hosts (Ollama, Qdrant, Whisper, SQLite, JWT)                                                                                                     
  - backend/providers.py: env-driven resolver, is_local_mode(), diarization_enabled()                                                                                                                            
                                                                                                                                                                                                                 
  Phase 1 — LLM                                                                                                                                                                                                  
  - backend/utils/llm/providers/{ollama_client,openai_client}.py + backend/utils/llm/router.py (sync + async stream)                                                                                             
                                                                                                                                                                                                                 
  Phase 2 — Embeddings                                                                                                                                                                                           
  - backend/utils/embeddings/{local_embeddings,openai_embeddings,router}.py with langchain-compatible embed_query/embed_documents adapters                                                                       
                                                                                                                                                                                                                 
  Phase 3 — Vector DB                                                                                                                                                                                            
  - backend/database/{vector_db_base,vector_db_qdrant}.py mirroring all four namespaces (conversations / memories / action items / screen activity), with Pinecone-shaped public functions                       
                                                                                                                                                                                                                 
  Phase 4 — STT                                                                                                                                                                                                  
  - backend/utils/stt/providers/{local_whisper_prerecorded,local_streaming,router}.py (faster-whisper, chunked PCM streaming)                                                                                    
                                                                                                                                                                                                                 
  Phase 5 — VAD                                                                                                                                                                                                  
  - backend/utils/stt/local_vad.py (RMS energy default, optional silero backend)                                                                                                                                 
                                                                                                                                                                                                                 
  Phase 6 — SQL persistence                                                                                                                                                                                      
  - backend/database/sql/{db,models,repository}.py (User / Conversation / Message / Memory / ActionItem)                                                                                                         
                                                                                                                                                                                                                 
  Phase 7 — Local auth                                                                                                                                                                                         
  - backend/auth/{local_auth,router_dep}.py (PBKDF2 password hashing, JWT issue/verify, bootstrap admin)                                                                                                         
                                                                                                                                                                                                                 
  Phase 8 — WebSockets                                                                                                                                                                                           
  - backend/events/{connection_manager,router}.py                                                                                                                                                                
                                                                                                                                                                                                                 
  Phase 9 — Search                                                                                                                                                                                               
  - backend/search/{local_search,router}.py (SQLite FTS5, disabled by default)                                                                                                                                   
                                                                                                                                                                                                                 
  Phase 10 — Feature gating                                                                                                                                                                                      
  - backend/feature_flags.py (per-feature ENABLE_* env knobs, FeatureDisabled exception)                                                                                                                         
                                                                                                                                                                                                                 
  Phase 11 — Wiring helpers                                                                                                                                                                                      
  - backend/local_bootstrap.py (logs the provider matrix, runs init_db, creates admin)                                                                                                                           
  - backend/scripts/local_smoke.py (end-to-end smoke test)                                                                                                                                                       
  - requirements.txt: appended optional local-mode deps as commented-out lines                                                                                                                                   
                                                                                                                                                                                                                 
  What's deliberately not done yet (per the spec's "replace one dependency at a time" rule — these are the remaining cutover work, not scaffolding):                                                             
                                                                                                                                                                                                                 
  1. backend/main.py still imports firebase_admin unconditionally; it needs a guarded init driven by get_auth_provider(), plus the /ws endpoint and a call to bootstrap_local().                                 
  2. backend/dependencies.py still does Firebase token verification; needs to dispatch to auth.router_dep.get_current_user_id_local when AUTH_PROVIDER=local.                                                    
  3. The 60+ existing call sites that import from utils.llm.clients, database.vector_db, utils.stt.{pre_recorded,streaming}, database.{conversations,users,memories,action_items}, and backend/pusher/ still need
   to be migrated to the new routers — that's the bulk of the remaining work and is intentionally incremental.                                                                                                   
  4. Stripping modal/, utils/billing/, typesense/, etc. — gating layer is in place; actually removing imports requires touching the routers.                                                                     
                                                                                                                                                                                                                 
  Smoke test path: install qdrant-client sentence-transformers faster-whisper sqlalchemy pyjwt, start Ollama and Qdrant locally, set the env vars, then python -m scripts.local_smoke from backend/. 

---

# Omi Backend — Local-Only Migration Status

> **Historical document.** The local backend is now operational via `main_local.py`.
>
> This document was written during the initial scaffolding phase and assumed the approach
> would be to modify `main.py` to support local providers ("cutover"). The implementation
> took a different path: a clean separate entry point (`main_local.py`) was created that
> never touches upstream cloud routers. The "remaining work" items in this document
> (main.py firebase init, dependencies.py auth, 60+ call site migrations) are **not
> required** because `main_local.py` bypasses all of them.
>
> For current operational status, see `LOCAL_CAPABILITIES.md` and `RUNBOOK.md`.
> For what was actually built, see `COMPLETED_UPDATES.md` and `GAPS.md`.

This document tracks the migration of the Omi backend from a cloud-dependent FastAPI service (Firebase + OpenAI + Pinecone + Deepgram + Pusher + Typesense + Stripe) to a fully local, self-contained system. It captures (1) what has been built so far, (2) what still needs to happen and why, and (3) how to run the project end-to-end.

The work is grounded in `omi_local_backend_merged_final.md`. The guiding rule from that spec is: **replace implementations behind interfaces before changing consumers**. That is why nothing in the existing call sites has been edited yet — the scaffolding above creates the local provider implementations *alongside* the cloud ones so cutover can happen incrementally.

---

## 1. Architecture Overview

The intended local runtime topology, once cutover is complete:

```
HTTP/WebSocket request
   │
   ▼
FastAPI Router  ──►  Provider Resolver (backend/providers.py)
   │                     │
   │                     ├── LLM        → utils/llm/router.py        → ollama_client.py  (HTTP → http://localhost:11434)
   │                     ├── Embeddings → utils/embeddings/router.py → local_embeddings.py (sentence-transformers)
   │                     ├── Vector DB  → database/vector_db.py      → vector_db_qdrant.py (HTTP → http://localhost:6333)
   │                     ├── STT        → utils/stt/providers/router → local_whisper_prerecorded / local_streaming
   │                     ├── VAD        → utils/stt/local_vad.py     (RMS energy / optional silero)
   │                     ├── DB         → database/sql/db.py          (SQLite at ./omi_local.db)
   │                     ├── Auth       → auth/local_auth.py          (PBKDF2 + JWT)
   │                     ├── Events     → events/connection_manager  (FastAPI WebSockets)
   │                     └── Search     → search/local_search.py      (SQLite FTS5; disabled by default)
   ▼
Response
```

The full provider matrix is:

| Subsystem    | Cloud (current default) | Local (target) | Env var               |
|--------------|-------------------------|----------------|-----------------------|
| LLM          | OpenAI                  | Ollama         | `LLM_PROVIDER`        |
| Embeddings   | OpenAI                  | sentence-transformers | `EMBEDDINGS_PROVIDER` |
| Vector DB    | Pinecone                | Qdrant         | `VECTOR_DB_PROVIDER`  |
| STT          | Deepgram (+ Fal WhisperX) | faster-whisper | `STT_PROVIDER`        |
| Auth         | Firebase                | Local JWT      | `AUTH_PROVIDER`       |
| DB           | Firestore               | SQLite         | `DB_PROVIDER`         |
| Events       | Pusher                  | WebSockets     | `EVENT_PROVIDER`      |
| Search       | Typesense               | SQLite FTS5    | `SEARCH_PROVIDER`     |
| Diarization  | Deepgram / pyannote     | Single-speaker | `ENABLE_DIARIZATION`  |

Defaults in `providers.py` keep cloud values active — the migration is opt-in via environment variables.

---

## 2. What Has Been Done (Scaffolding Phases 0–11)

All 25 new modules byte-compile cleanly and the resolver returns the correct provider matrix. None of this code is wired into the runtime path yet — see the "Work That Needs To Be Done" section.

### File inventory (created)

```
backend/
├── providers.py                                 # Phase 0 resolver
├── feature_flags.py                             # Phase 10 gating
├── local_bootstrap.py                           # Phase 11 wiring helper
├── auth/
│   ├── __init__.py
│   ├── local_auth.py                            # PBKDF2 + JWT
│   └── router_dep.py                            # FastAPI dep replacement
├── database/
│   ├── vector_db_base.py                        # Public contract
│   ├── vector_db_qdrant.py                      # 4 namespaces, all public funcs
│   └── sql/
│       ├── __init__.py
│       ├── db.py                                # SQLAlchemy engine/session
│       ├── models.py                            # User / Conv / Msg / Memory / ActionItem
│       └── repository.py                        # CRUD helpers
├── events/
│   ├── __init__.py
│   ├── connection_manager.py                    # async WS registry
│   └── router.py
├── search/
│   ├── __init__.py
│   ├── local_search.py                          # SQLite FTS5
│   └── router.py
├── utils/
│   ├── embeddings/
│   │   ├── __init__.py
│   │   ├── local_embeddings.py                  # sentence-transformers
│   │   ├── openai_embeddings.py                 # cloud adapter
│   │   └── router.py
│   ├── llm/
│   │   ├── router.py                            # Ollama / OpenAI dispatcher
│   │   └── providers/
│   │       ├── __init__.py
│   │       ├── ollama_client.py                 # chat / generate / stream / astream
│   │       └── openai_client.py                 # delegates to existing clients.py
│   └── stt/
│       ├── local_vad.py                         # RMS / silero
│       └── providers/
│           ├── __init__.py
│           ├── local_whisper_prerecorded.py     # faster-whisper
│           ├── local_streaming.py               # chunked PCM
│           └── router.py
└── scripts/
    └── local_smoke.py                           # end-to-end check
```

### File inventory (modified)

- `backend/.env.template` — added the local provider knobs and host configs at the top of the file.
- `backend/requirements.txt` — appended commented-out optional local-mode deps so they are visible but don't break cloud installs.

### Verified

- All 25 new files compile under `py_compile`.
- `providers.is_local_mode()` returns `True` when every `*_PROVIDER` is set to its local value, `False` otherwise.
- Defaults preserve current cloud behavior — nothing in the existing app changes shape until env vars flip.

---

## 3. Work That Needs To Be Done

This is the cutover work that turns the scaffolding into a running local backend. Items are ordered by dependency: do them top-to-bottom unless noted. Each item lists *why* it is necessary and *what specifically* must change.

### 3.1 Make `main.py` boot in local mode

**Why:** `backend/main.py` currently calls `firebase_admin.initialize_app(...)` and imports `utils.observability.log_langsmith_status`, `utils.subscription.validate_stripe_price_ids` at module top-level. In local mode there are no Firebase credentials and no Stripe price IDs, so the app crashes during import before any request is served.

**What to change:**
1. Wrap the `firebase_admin.initialize_app(...)` block in a `if get_auth_provider() == "firebase":` guard.
2. Wrap `log_langsmith_status()` and `validate_stripe_price_ids()` in `if feature_flags.is_enabled("langsmith"):` / `if feature_flags.is_enabled("stripe"):` guards.
3. After `app = FastAPI()`, call `bootstrap_local()` from `backend/local_bootstrap.py`. This logs the provider matrix, calls `init_db()` for SQLite, and creates the bootstrap admin user from env if configured.
4. Add a WebSocket route:
   ```python
   from events.connection_manager import manager
   @app.websocket("/ws")
   async def websocket_endpoint(ws):
       await manager.connect(ws)
       try:
           while True:
               await ws.receive_text()
       except Exception:
           await manager.disconnect(ws)
   ```
5. Optionally suppress import of routers that are wholly cloud-only when their feature flag is off (`payment`, `oauth`, `tts` if it depends on ElevenLabs, etc.).

### 3.2 Replace Firebase token verification in `dependencies.py`

**Why:** `backend/dependencies.py:get_current_user_id` calls `firebase_admin.auth.verify_id_token(...)`. Every authenticated route imports this. In local mode this raises because Firebase is not initialized.

**What to change:**
1. At the top of `dependencies.py`, import `from providers import get_auth_provider`.
2. Inside `get_current_user_id`, branch:
   - if `get_auth_provider() == "local"` → delegate to `auth.router_dep.get_current_user_id_local`
   - else → existing Firebase path
3. Move the `from firebase_admin import auth` import behind a runtime check (lazy import inside the function) so local mode does not need `firebase_admin` initialized.

### 3.3 Convert `database/vector_db.py` into a router

**Why:** The existing 534-line `database/vector_db.py` instantiates Pinecone at import time and is the single import target for ~12 modules across `utils/conversations/`, `utils/retrieval/`, and `routers/`. Currently in local mode they would all hit Pinecone or 500 if `PINECONE_API_KEY` is unset.

**What to change:**
1. Rename the current `vector_db.py` to `vector_db_pinecone.py` (it is already a Pinecone-only implementation).
2. Create a new `database/vector_db.py` whose body re-exports symbols from the implementation chosen by `providers.get_vector_db_provider()`. Pattern:
   ```python
   from providers import get_vector_db_provider
   if get_vector_db_provider() == "qdrant":
       from database.vector_db_qdrant import *  # noqa
   else:
       from database.vector_db_pinecone import *  # noqa
   ```
3. Validate with grep that every public name imported from `database.vector_db` elsewhere is exported from both implementations. Missing names: `update_vector_metadata`, `check_memory_duplicate`, `delete_action_item_vectors_batch` already exist in both — confirm before wiring.

### 3.4 Cut LLM call sites over to `utils/llm/router.py`

**Why:** `utils/llm/clients.py` is imported by `utils/llm/{chat,memories,conversation_processing,proactive_notification,goals,trends,external_integrations,fair_use_classifier,app_generator,knowledge_graph,persona,followup,notifications,openglass}.py`. Those are the LLM call sites. None of them go through the new router yet.

**What to change (incremental — one file at a time, in this order):**
1. Lowest-risk first: `utils/llm/notifications.py`, `utils/llm/proactive_notification.py`, `utils/llm/goals.py`, `utils/llm/trends.py`. These call simple chat/extract patterns — replace `from utils.llm.clients import llm_mini` with `from utils.llm.router import chat`.
2. Streaming sites: `utils/llm/chat.py` and the `routers/chat.py` consumer. Use `astream` from the router for the SSE response.
3. Structured-output sites: `utils/llm/conversation_processing.py`, `utils/llm/memories.py`. These use `with_structured_output`, which Ollama does not support. Either keep them on the cloud router until a JSON-mode wrapper is added, or call `extract_actions`-style helpers and validate with Pydantic.
4. Persona / app generation paths: `utils/llm/persona.py`, `utils/llm/app_generator.py`. Lower priority — gate behind feature flags if cutting them is too disruptive.

**Risk:** Ollama does not implement OpenAI's `tools` / function-calling. Any code using `bind_tools` must add a fallback or be gated.

### 3.5 Cut embeddings call sites over to `utils/embeddings/router.py`

**Why:** `database.vector_db_pinecone` and `database.vector_db_qdrant` both call `from utils.llm.clients import embeddings`. So does `utils/retrieval/`. The local Qdrant module already uses `utils.embeddings.router`, so the work is on the Pinecone path and on retrieval helpers.

**What to change:**
1. In any non-Pinecone module that does `from utils.llm.clients import embeddings`, replace with:
   ```python
   from utils.embeddings.router import get_embeddings_object
   embeddings = get_embeddings_object()
   ```
2. Confirm `LOCAL_EMBEDDINGS_DIM` matches the Qdrant collection dimension. Default `all-MiniLM-L6-v2` = 384; OpenAI `text-embedding-3-large` = 3072. **Mismatch will silently break similarity search** and is the migration's #1 known footgun.

### 3.6 Cut STT call sites over to the local providers

**Why:** `routers/transcribe.py` (the 2900-line core listen pipeline) and `pusher/main.py` import directly from `utils.stt.streaming` and `utils.stt.pre_recorded`. The local providers are not exercised today.

**What to change:**
1. **Prerecorded path first** (lower risk): in any caller of `deepgram_prerecorded(...)`, branch on `get_stt_provider()` to call `utils.stt.providers.local_whisper_prerecorded.transcribe(...)` instead. Normalize the return shape: the Deepgram code expects words-with-speakers; the local Whisper module returns segments-with-words. Add an adapter in `utils/stt/providers/local_whisper_prerecorded.py` that flattens to the existing word-level shape if needed.
2. **Streaming path second**: `routers/transcribe.py` is the hard one. The local streaming session API (`start_stream` / `push_audio_chunk` / `end_stream`) is callback-based and chunked. The existing Deepgram path is event-based. Wire by adding a `provider == "local"` branch in the WS handler that:
   - calls `start_stream(session_id, on_partial=...)` on connect
   - feeds raw PCM into `push_audio_chunk(session_id, chunk)`
   - emits the `on_partial` text via the connection manager's `send_to_user`
   - calls `end_stream(session_id)` on disconnect.
3. Replace `utils/stt/vad.py` callers with `utils/stt/local_vad.detect_speech` when in local mode (or leave the existing VAD if it already works locally).

**Known gap:** local streaming has higher latency than Deepgram (5s chunks by default). The spec explicitly accepts this for v1.

### 3.7 Refactor Firestore-backed database modules to call SQL

**Why:** `database/conversations.py` (1079 LOC), `database/users.py` (1362 LOC), `database/memories.py`, `database/action_items.py`, `database/apps.py`, etc. all call `from database._client import db` (Firestore). In local mode these crash on first use because the Firestore client cannot initialize.

**What to change (per file):**
1. At the top of each module, branch on `get_db_provider()`. The simplest pattern: keep the Firestore code in place and add `if get_db_provider() == "sqlite": return _sqlite_impl(...)` early-returns at the top of each public function. This keeps the surface area small and lets you migrate one function at a time.
2. The SQLite impls call `database.sql.repository` helpers. Add new helpers there as needed — `repository.py` only covers the basics today (User / Conversation / Message / Memory / ActionItem).
3. The Firestore data shape relies heavily on encryption-at-rest via `database/helpers.py` decorators. Decide explicitly whether local mode keeps encryption (recommended: keep the same `ENCRYPTION_SECRET` flow, applied at the SQLAlchemy column level in `models.py`).
4. Order of cutover: `users.py` → `conversations.py` → `memories.py` → `action_items.py` → `apps.py`. Users first because every other table foreign-keys to it.

**Risk:** Firestore's nested-document semantics do not map 1:1. `transcript_segments` and `structured` are stored as JSON columns to preserve flexibility, but anything that relied on Firestore subcollections (e.g. `users/{uid}/memories/{mid}`) needs its query rewritten as SQL joins.

### 3.8 Replace Firebase auth router

**Why:** `routers/auth.py` (658 LOC) implements Google/Apple OAuth callbacks, Firebase session creation, and bootstrapping. It is the entry point for app login. None of those flows work without Firebase credentials.

**What to change:**
1. Add `register` / `login` POST endpoints to `routers/auth.py` that call `auth.local_auth.register/login`. These should be active only when `AUTH_PROVIDER=local`.
2. Gate the existing Google/Apple callback routes behind `get_auth_provider() == "firebase"` — return 501 in local mode.
3. Update mobile/desktop clients (`app/`, `desktop/`) to support the local login flow. **This is out of backend scope** but the auth contract change has to be communicated.

### 3.9 Disable `routers/oauth.py` in local mode

**Why:** `routers/oauth.py` exposes app-level OAuth (Whoop, Notion, Google, Twitter). All require cloud client credentials.

**What to change:** add `@router.middleware` (or per-route guards) that return 501 when `feature_flags.is_enabled("whoop_oauth")` etc. is `False`. Keep the file in place — do not delete the routes.

### 3.10 Replace Pusher publishers with the connection manager

**Why:** `backend/pusher/` is a separate FastAPI service. The main backend talks to it over WebSocket today. In local mode there is no separate pusher process; events should be broadcast directly via `events/connection_manager.py`.

**What to change:**
1. Find every call site that publishes to Pusher (search for `HOSTED_PUSHER_API_URL` and the `pusher/` package). The big ones are in `routers/transcribe.py` and `utils/conversations/`.
2. Replace those calls with `await events.router.broadcast(payload)` or `await events.router.send_to_user(uid, payload)`.
3. Keep the `backend/pusher/` package in place — do not delete. It is still the cloud path; the gating happens in the router.

### 3.11 Disable `typesense/` and route search through the router

**Why:** `backend/typesense/` is imported for conversation search. Without a Typesense host it crashes.

**What to change:** in any router that calls into `backend/typesense/`, branch on `get_search_provider()`. For `disabled` (the local default), return an empty result set with HTTP 200. For `local`, call `search.local_search.search(...)`.

### 3.12 Strip non-core cloud features (Phase 10 cutover)

**Why:** The feature-flag layer exists but is not yet checked in the call sites that import `stripe`, `mixpanel`, `hume`, `perplexity`, `langsmith`, `rapidapi`, `google_maps`. Each of these will crash on `KeyError` when the matching env var is unset.

**What to change:** in each file that imports one of these SDKs, wrap the import + initialization in a `feature_flags.is_enabled("<name>")` check. The exact files:

- Stripe: `routers/payment.py`, `utils/subscription.py`, `utils/billing/`, `database/apps.py`
- Mixpanel: search for `mixpanel` and any analytics tracking
- Hume: `utils/other/hume.py` (per AGENTS.md)
- Perplexity: `utils/retrieval/tools/`
- LangSmith: `utils/observability/`
- RapidAPI: search for `RAPID_API_KEY`
- Google Maps: search for `google_maps`
- Modal: `backend/modal/` — leave the package alone, just stop importing from it

### 3.13 Migrate `backend/utils/llm/clients.py`'s `embeddings` symbol

**Why:** Many modules import the singleton `embeddings` directly: `from utils.llm.clients import embeddings`. The vector_db_pinecone path uses this. To complete embeddings cutover, `utils/llm/clients.py` should expose a proxy that delegates to the embeddings router so cloud and local paths route through the same selector.

**What to change:** replace the module-level `embeddings = _OpenAIEmbeddingsProxy(...)` line with `from utils.embeddings.router import get_embeddings_object; embeddings = get_embeddings_object()`. Test that BYOK still works — the `_OpenAIEmbeddingsProxy` class handles BYOK; the router-returned adapter does not. If BYOK matters, keep the proxy class and have it consult `get_embeddings_provider()` first.

### 3.14 Validate the end-to-end loop

**Why:** Even with all of the above, some integrations will break in subtle ways (transcript shape, encryption, semaphore lifecycles).

**What to do:**
1. Run `python -m scripts.local_smoke` from `backend/`. The smoke test exercises: provider resolver → SQLite init → register/login → embed → Qdrant upsert/search → Ollama chat. It should print "smoke test complete".
2. Start the FastAPI app: `uvicorn main:app --host 0.0.0.0 --port 8080`.
3. POST `/v1/auth/register` then `/v1/auth/login` and capture the JWT.
4. Upload a small WAV to a transcribe endpoint with the JWT bearer.
5. Confirm the transcript is returned, embeddings end up in Qdrant, the conversation is in SQLite, and a WS client connected to `/ws` saw the broadcast.

### 3.15 Optional / deferred (out of scope for first milestone)

- Speaker diarization beyond single-speaker fallback (would require pyannote running locally on CPU).
- Postgres back-end for `database/sql/` (only needed if SQLite concurrency becomes a problem).
- Cross-worker WebSocket fan-out via local Redis Pub/Sub (only if the backend is run with multiple worker processes).
- `routers/payment.py` parity in local mode (stub all subscription gates as "free tier unlimited").
- Cloud-plugin marketplace (`routers/apps.py`) — large surface area; leave on cloud or stub.

---

## 4. How To Run The Project

### 4.1 Prerequisites

- **Python 3.11** (the Dockerfile pins this; 3.12+ breaks per `backend/CLAUDE.md`).
- **FFmpeg** on `PATH` (audio decode).
- **Opus** library (`opuslib`) for the device audio codec.
- **Ollama** running locally on `http://localhost:11434`. Pull the model you want: `ollama pull llama3.1`.
- **Qdrant** running locally on `http://localhost:6333`. Easiest: `docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant:latest`.
- (Optional) **Redis** — the backend caches/rate-limits via Redis but fails open without it.

### 4.2 Install dependencies

The project's `backend/requirements.txt` already has the cloud dependencies. The local-mode deps are listed in a fresh `backend/requirements-local.txt` (see §5 below). Install both:

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-local.txt
```

If you only want local mode and not cloud SDKs, you can install just `requirements-local.txt`, but expect some import-time errors until §3.1–§3.13 cutover work is complete.

### 4.3 Configure environment

Copy the template and edit:

```bash
cp .env.template .env
```

Set the following at minimum for local-only mode:

```env
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
OLLAMA_MODEL=llama3.1
QDRANT_URL=http://localhost:6333
LOCAL_EMBEDDINGS_MODEL=sentence-transformers/all-MiniLM-L6-v2
LOCAL_EMBEDDINGS_DIM=384
LOCAL_WHISPER_MODEL=base
SQLITE_PATH=./omi_local.db
LOCAL_JWT_SECRET=change-me-please
LOCAL_JWT_TTL_SECONDS=86400
BOOTSTRAP_ADMIN_EMAIL=admin@omi.local
BOOTSTRAP_ADMIN_PASSWORD=changeme
ENCRYPTION_SECRET=any-non-empty-string
```

Also set every `ENABLE_<feature>=false` variable for the cloud-only features you want disabled (Stripe, Mixpanel, Hume, Perplexity, LangSmith, RapidAPI, Pusher hosted, Modal, Google Maps, GitHub token, Whoop OAuth, Notion OAuth, Google OAuth, Twitter OAuth, Typesense). The `feature_flags.local_mode_disable_recommended()` helper returns the full list.

### 4.4 Start the supporting services

```bash
# Ollama (in its own terminal)
ollama serve
ollama pull llama3.1

# Qdrant (in another terminal)
docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant:latest
```

### 4.5 Smoke-test the local stack

From `backend/` with the venv active:

```bash
python -m scripts.local_smoke
```

Expected output: provider matrix logged, `local_mode= True`, register/login OK, embed dim printed, Qdrant search results printed, Ollama reply printed, "smoke test complete".

### 4.6 Run the API server

**Note:** until items §3.1–§3.13 are completed, `uvicorn main:app` will still attempt Firebase init at import. After those cutovers:

```bash
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

Hit `http://localhost:8080/docs` for the FastAPI interactive docs. Authenticated endpoints expect `Authorization: Bearer <jwt>` where the JWT comes from the local login endpoint.

### 4.7 Tests

```bash
bash test-preflight.sh    # validates Python version, packages, optional Redis
bash test.sh              # runs the unit + integration test suites
```

These are the existing test runners. New tests for the local providers should be added under `backend/tests/unit/` and registered in `test.sh` (per `backend/CLAUDE.md`: "New test files must be added to test.sh or they won't run in CI").

---

## 5. Local-Mode `requirements-local.txt`

Created at `backend/requirements-local.txt` (see file). Contains every package needed for the local providers, pinned to versions that work with Python 3.11.

```
# Local-only mode dependencies (Python 3.11)
qdrant-client>=1.9,<2
sentence-transformers>=2.7,<3
faster-whisper>=1.0,<2
SQLAlchemy>=2.0,<3
PyJWT>=2.8,<3
torch>=2.2          # optional — only required when LOCAL_VAD_BACKEND=silero
numpy>=1.26         # transitive but pinned to avoid 2.x ABI breakage with torch
httpx>=0.27         # already a transitive dep, pinned here for the Ollama client
```

`torch` is heavy (~2 GB on CPU). It is only needed if you opt into the silero VAD backend; the default RMS energy detector has no extra dependencies. If you skip torch, also skip the silero backend setting.

---

## 6. Known Risks / Footguns

1. **Embedding dimension mismatch.** Pinecone collections use OpenAI's 3072-dim vectors; Qdrant in local mode uses 384-dim. The `vector_db_qdrant._ensure_collection` helper reads `LOCAL_EMBEDDINGS_DIM` to size the collection; if you change the embeddings model, you must drop the Qdrant collection and recreate it.
2. **Ollama has no native function calling.** Any LLM path that uses `bind_tools` (chat agent, action-item extractor, RAG tool dispatcher) will not work against Ollama without a JSON-mode wrapper. Expect to write one or keep those paths on cloud temporarily.
3. **Whisper transcript shape ≠ Deepgram transcript shape.** Deepgram returns word-level timestamps with speaker labels; faster-whisper returns segment-level. The adapter in `local_whisper_prerecorded.py` produces a compatible enough shape for `transcript_segments` in SQLite, but speaker-aware downstream logic (speaker_identification, persona matching) will degrade.
4. **SQLite write contention.** A single FastAPI worker is fine. Multiple workers + the same SQLite file will cause `database is locked` errors. Either run with `--workers 1` or migrate to Postgres.
5. **Firestore encryption.** Conversations are encrypted at rest in Firestore via `database/helpers.py` decorators. The SQL repository does not yet apply that encryption — decide whether local mode preserves the on-disk encryption guarantee before storing any real data.
6. **WebSocket cross-worker fan-out.** Each FastAPI worker has its own `ConnectionManager`. With multiple workers, a broadcast issued in worker A is invisible to a client connected to worker B. Either run with one worker or add a Redis Pub/Sub backplane.

---

## 7. Glossary of New Modules

| Module                                          | Purpose                                                                                  |
|-------------------------------------------------|------------------------------------------------------------------------------------------|
| `backend/providers.py`                          | Single source of truth for provider selection. All routers should import from here.       |
| `backend/feature_flags.py`                      | `ENABLE_<NAME>` env-driven gate for non-core cloud features.                              |
| `backend/local_bootstrap.py`                    | Call from `main.py` startup: logs matrix, runs `init_db`, creates admin.                  |
| `backend/utils/llm/router.py`                   | `chat / generate / stream / astream / extract_actions` dispatcher.                        |
| `backend/utils/llm/providers/ollama_client.py`  | HTTP client for Ollama at `OLLAMA_HOST`.                                                  |
| `backend/utils/llm/providers/openai_client.py`  | Thin adapter that delegates to the existing `utils.llm.clients.llm_mini`.                |
| `backend/utils/embeddings/router.py`            | `embed / embed_batch / get_embeddings_object / dimension`.                                |
| `backend/utils/embeddings/local_embeddings.py`  | sentence-transformers backend with langchain-compatible adapter.                          |
| `backend/utils/embeddings/openai_embeddings.py` | Cloud passthrough preserving the `embed_query` / `embed_documents` shape.                 |
| `backend/database/vector_db_base.py`            | Public protocol for both Pinecone and Qdrant impls.                                       |
| `backend/database/vector_db_qdrant.py`          | Qdrant implementation of every public function in vector_db.py (4 namespaces).            |
| `backend/database/sql/db.py`                    | SQLAlchemy engine + session_scope context manager.                                        |
| `backend/database/sql/models.py`                | ORM: User / Conversation / Message / Memory / ActionItem.                                 |
| `backend/database/sql/repository.py`            | CRUD helpers returning plain dicts, mirroring the Firestore module return shapes.         |
| `backend/utils/stt/local_vad.py`                | Energy-based detect_speech with optional silero backend.                                  |
| `backend/utils/stt/providers/local_whisper_prerecorded.py` | faster-whisper with normalized return shape.                                   |
| `backend/utils/stt/providers/local_streaming.py`| Chunked PCM streaming session API (start/push/end).                                       |
| `backend/utils/stt/providers/router.py`         | STT dispatcher.                                                                           |
| `backend/auth/local_auth.py`                    | PBKDF2 password hashing + JWT issue/verify + bootstrap admin.                             |
| `backend/auth/router_dep.py`                    | Drop-in replacement FastAPI dependency for `get_current_user_id`.                         |
| `backend/events/connection_manager.py`          | Async WebSocket registry with broadcast / send_to_user / publish.                         |
| `backend/events/router.py`                      | Event-system dispatcher.                                                                  |
| `backend/search/local_search.py`                | SQLite FTS5 search.                                                                       |
| `backend/search/router.py`                      | Search dispatcher (disabled by default).                                                  |
| `backend/scripts/local_smoke.py`                | End-to-end local-stack smoke test.                                                        |

---

## 8. Status Summary

- **Scaffolding (Phases 0–11):** complete. 25 new modules, all compile.
- **Cutover (§3.1–§3.13):** not started. This is the work that turns the scaffolding into a running local backend.
- **Validation (§3.14):** blocked on cutover.

Once §3.1 + §3.2 + §3.3 are done, the app should boot in local mode and accept register/login. Each subsequent cutover unlocks more functionality (transcribe, chat, memory search). The migration is intentionally designed so each item can be merged independently and validated in isolation.

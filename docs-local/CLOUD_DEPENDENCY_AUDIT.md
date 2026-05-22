# Cloud Dependency Audit

**Date:** 2026-05-06
**Purpose:** Identify all areas in the Omi project that currently default to or require cloud services. Goal is full local operation with zero cloud dependence.

---

## 1. Backend — Provider Defaults (All Cloud)

All 8 provider-selection variables in `.env.reference` default to cloud services. A fresh install without an explicit `.env` will attempt to reach cloud APIs.

| Variable | Default | Cloud Service | Local Alternative | Switch Mechanism |
|---|---|---|---|---|
| `LLM_PROVIDER` | `openai` | OpenAI API | `ollama` | `LLM_PROVIDER=ollama` |
| `STT_PROVIDER` | `deepgram` | Deepgram | `local` (faster-whisper) | `STT_PROVIDER=local` |
| `EMBEDDINGS_PROVIDER` | `openai` | OpenAI API | `local` (sentence-transformers) | `EMBEDDINGS_PROVIDER=local` |
| `VECTOR_DB_PROVIDER` | `pinecone` | Pinecone | `qdrant` | `VECTOR_DB_PROVIDER=qdrant` |
| `AUTH_PROVIDER` | `firebase` | Google Firebase | `local` (JWT) | `AUTH_PROVIDER=local` |
| `DB_PROVIDER` | `firestore` | Google Firestore | `sqlite` or `postgres` | `DB_PROVIDER=sqlite` |
| `EVENT_PROVIDER` | `pusher` | Pusher | `websocket` | `EVENT_PROVIDER=websocket` |
| `SEARCH_PROVIDER` | `typesense` | Typesense (cloud/self-hosted) | `local` (SQLite FTS5) or `disabled` | `SEARCH_PROVIDER=local` |

### Additional Backend Defaults

- **`ENABLE_DIARIZATION=true`** — requires an external GPU diarizer service. No local diarizer exists. Must be set to `false` for offline operation.
- **`LANGSMITH_TRACING`** — defaults off, but if enabled sends LLM traces to the LangSmith cloud.

---

## 2. Backend — Cloud Services With No Local Alternative

These are silently disabled when the API key is absent. There is no local simulation or fallback.

| Service | Key(s) | Purpose |
|---|---|---|
| Stripe | `STRIPE_API_KEY` | Payments |
| Twilio | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | Phone calls |
| ElevenLabs | `ELEVENLABS_API_KEY` | Text-to-speech |
| Perplexity | `PERPLEXITY_API_KEY` | Web search in RAG pipeline |
| Hume AI | `HUME_API_KEY` | Emotion detection |
| Google Cloud Storage | `BUCKET_SPEECH_PROFILES`, `BUCKET_BACKUPS`, `BUCKET_PLUGINS_LOGOS` | File storage (not used in local mode) |
| Google OAuth | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Calendar / Drive integrations |
| Apple OAuth | Apple sign-in credentials | Apple sign-in |
| Twitter / Whoop / Notion / GitHub | Various OAuth credentials | Third-party integrations |

---

## 3. Backend — `main.py` vs `main_local.py`

`main.py` (the production entrypoint) imports all 45+ routers. Those routers chain into Firebase, OpenAI, Pinecone, Pusher, and Deepgram clients **at import time**. It will crash without cloud credentials. It is not provider-aware.

`main_local.py` is the clean local entrypoint that avoids these imports. `MIGRATION_STATUS.md` tracks the cutover work needed to make `main.py` provider-aware — that work has not been done.

**Until `main.py` is migrated, the only supported local entrypoint is `main_local.py`.**

---

## 4. Desktop App (macOS Swift + Rust)

### Critical — Hardcoded Cloud in Swift Layer

`GeminiClient.swift` and `EmbeddingService.swift` call Google Gemini directly from the Desktop app's Swift layer. This bypasses the provider abstraction in the Python backend entirely. There is no `GEMINI_LLM_PROVIDER` toggle — it is hardcoded to cloud.

### `OMI_PYTHON_API_URL` Default

`Desktop/.env.example` ships with:

```
OMI_PYTHON_API_URL=https://api.omi.me
```

A fresh Desktop setup silently routes to the production cloud API. Must be manually overridden to `http://<LAN-IP>:8088/` (the port `main_local.py` runs on — see RUNBOOK §10.2).

### `run.sh` Cloud Run Fallback

When `OMI_SKIP_BACKEND=1`, `run.sh` exports:

```
OMI_DESKTOP_API_URL="https://desktop-backend-hhibjajaja-uc.a.run.app"
```

This is a hard-coded Google Cloud Run URL. Setting `OMI_SKIP_BACKEND=1` silently routes the Desktop app to a production cloud Rust backend, bypassing any local setup.

### Cloudflare Tunnel

`run.sh` starts a Cloudflare tunnel to expose the local Rust backend publicly so the Omi BLE pin can connect from outside the LAN. This is an external cloud proxy. Can be skipped with `OMI_SKIP_TUNNEL=1` if BLE pin connectivity from outside the LAN is not needed.

### `DEEPGRAM_API_KEY` in Desktop Config

The Desktop app has its own `DEEPGRAM_API_KEY`. If `OMI_PYTHON_API_URL` points to the local backend, STT is handled there (and the backend's `STT_PROVIDER` setting applies). If it points to the cloud API, the Desktop may call Deepgram directly.

### What Is Already Local

- `OMI_DESKTOP_API_URL` defaults to `http://localhost:10201` — Rust backend is local.

---

## 5. iOS App (Flutter)

### Firebase Auth — Resolved via `LOCAL_AUTH_BYPASS=true`

Firebase Auth is baked into the iOS app — the `google_sign_in` and `sign_in_with_apple` packages route through Firebase identity and cannot be swapped for local JWTs without rebuilding the auth system. **However, this is no longer a blocker for local operation.**

With `LOCAL_AUTH_BYPASS=true` in the backend `.env`, the local backend accepts Firebase ID tokens directly — it derives a stable user ID from the Firebase UID embedded in the token without contacting Firebase for validation. iOS sign-in works as-is; the app authenticates with Firebase (one-time network call to Google) and the resulting token is accepted by the local backend for all subsequent requests.

Firebase projects referenced:
- `based-hardware-dev` — Google cloud Firebase (dev flavor)
- `based-hardware-prod` — Google cloud Firebase (prod flavor)

### Remaining Critical iOS Gap — Opus Codec

The iOS app sends raw Opus bytes from the Omi pin to `/v4/listen` with `codec=opus`. The local `listen.py` only handles PCM (`linear16`, `pcm8`). **Opus bytes fed to Whisper produce garbage or empty transcripts.** The WebSocket connection succeeds but transcription does not work.

Workaround: use `pin_bridge.py` (see RUNBOOK §10.1), which decodes Opus→PCM before sending `codec=linear16`.

iOS WAL sync (offline audio buffered when off-network) is implemented and works: `POST /v2/sync-local-files` in `routers_local/sync.py` decodes Opus internally.

### Other iOS Cloud Dependencies

| Item | Key | Notes |
|---|---|---|
| OpenAI | `OPENAI_API_KEY` | Appears in iOS env; suggests direct cloud calls from app |
| Google Maps | `GOOGLE_MAPS_API_KEY` | Cloud maps; no local alternative |
| PostHog Analytics | `POSTHOG_API_KEY` | Cloud analytics; disabled when key absent |
| Google OAuth | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google sign-in |

### What Is Already Configurable

- `API_BASE_URL` in `.dev.env` — can be pointed at the local backend.
- `LOCAL_AUTH_BYPASS=true` — backend accepts Firebase tokens; iOS and Desktop apps authenticate without changes.

---

## 6. Summary — Biggest Gaps for Full Local Operation

Ranked by severity / effort to fix:

| # | Gap | Component | Status |
|---|---|---|---|
| 1 | ~~Firebase Auth structurally embedded~~ | iOS app | **Resolved** — `LOCAL_AUTH_BYPASS=true` makes backend accept Firebase tokens; no iOS rebuild needed for auth |
| 2 | iOS sends Opus; `listen.py` expects PCM | iOS + Backend | **Open** — WebSocket connects, transcription produces garbage. Fix: add Opus decoding to `listen.py`, or use `pin_bridge.py` (workaround) |
| 3 | `GeminiClient.swift` / `EmbeddingService.swift` hardcoded to Google Gemini | Desktop Swift | **Open** — requires rewrite of those clients |
| 4 | `main.py` crashes without cloud credentials | Backend | **Open** — migrate per `MIGRATION_STATUS.md`. Use `main_local.py` (already done) |
| 5 | `OMI_PYTHON_API_URL` defaults to `api.omi.me` | Desktop `.env.example` | **Open** — set `OMI_PYTHON_API_URL=http://<LAN-IP>:8088/` at launch |
| 6 | `run.sh` fallback routes to Google Cloud Run | Desktop `run.sh` | **Open** — use `OMI_SKIP_BACKEND=1 OMI_SKIP_TUNNEL=1` to avoid |
| 7 | No local diarizer; `ENABLE_DIARIZATION=true` by default | Backend | **Open (by design)** — must set `ENABLE_DIARIZATION=false`; no local replacement |
| 8 | All 8 backend provider defaults are cloud | Backend `.env.reference` | **Mitigated** — RUNBOOK §3.2 documents the correct `.env` block; SETUP_FROM_SCRATCH.md creates a correct `.env` |

---

## 7. What Is Already Local-Capable

The backend provider-switching architecture is sound. With the correct `.env` settings, the Python backend runs fully offline:

```env
AUTH_PROVIDER=local
DB_PROVIDER=sqlite
LLM_PROVIDER=ollama
STT_PROVIDER=local
EMBEDDINGS_PROVIDER=local
VECTOR_DB_PROVIDER=qdrant
EVENT_PROVIDER=websocket
SEARCH_PROVIDER=disabled
ENABLE_DIARIZATION=false
LOCAL_AUTH_BYPASS=true
```

See RUNBOOK §3.2 for the full env block including Whisper and Ollama settings.

**Working end-to-end today:**
- Pin → BLE → `pin_bridge.py` → `/v4/listen` → faster-whisper → SQLite + Qdrant ✓
- Desktop app (macOS) → `OMI_PYTHON_API_URL` → local backend ✓
- iOS app → Firebase sign-in → local backend (Firebase token accepted via bypass) ✓ (but transcription broken — see gap #2)
- iOS WAL sync — `POST /v2/sync-local-files` implemented ✓
- Admin UI at `/admin/` — fully local ✓
- Chat — Ollama ✓, memories — sentence-transformers + Qdrant ✓

The Rust Desktop backend (`OMI_DESKTOP_API_URL=http://localhost:10201`) is already local. The remaining gaps are the Desktop Swift Gemini layer (gap #3) and the iOS Opus codec (gap #2).

# Local Capabilities — Omi Backend

This document describes what the Omi platform is designed to do in its full cloud form, what is fully operational in this local-only deployment, what requires manual steps to trigger, and what is unavailable without cloud services.

Use this as the primary reference for understanding what the system can and cannot do before reaching for external tools.

---

## What Omi Is

Omi is a wearable AI that continuously captures audio through a hardware pin, transcribes it in real time, and builds a persistent personal knowledge base from everything said and heard. The core value is not transcription alone — it is the intelligence layer that runs after capture: automatically extracting memories, action items, context, and making all of it searchable and conversational.

The full production system runs on Google Cloud (Firestore, Deepgram, OpenAI, Pinecone, Firebase, Pusher). This local deployment replaces every one of those with self-hosted alternatives so no audio, transcript, or personal data leaves the local network after initial model downloads.

---

## Services Required

These must be running for full local functionality. The backend starts and is usable without Ollama and Qdrant, but those features degrade gracefully.

| Service | Role | How to start |
|---------|------|-------------|
| `uvicorn main_local:app` | The Python backend — required for everything | `omi-start` or see RUNBOOK §3 |
| **Ollama** | Local LLM inference (chat, manual post-processing) | `ollama serve` — start before the backend |
| **Qdrant** | Vector search database | `docker run -p 6333:6333 qdrant/qdrant` |
| **faster-whisper** | Speech-to-text | Auto-loaded on first audio — no separate start needed |

**If Qdrant is not running:** transcription and storage still work, but conversations are not vectorized. Semantic search returns no results. A warning is logged; the session continues.

**If Ollama is not running:** transcription and storage still work. `/v1/chat` returns an error. No LLM-dependent features are available.

**Health check:** `http://<YOUR_SERVER_IP>:8088/healthz` — shows which provider is active for each service.

---

## What the Full Omi Product Does

For context when reading the local status sections below.

| Capability | Cloud implementation |
|-----------|---------------------|
| Audio capture | Pin BLE → iOS app / macOS Desktop app → Deepgram WebSocket |
| Transcription | Deepgram streaming (< 1 s per segment, continuous) |
| Speaker diarization | pyannote (GPU) — identifies and labels each speaker by voice |
| Conversation storage | Firestore, AES-256-GCM encrypted at rest |
| **Post-session LLM processing** | GPT-4 generates title, summary, category, action items for every completed conversation |
| **Memory extraction** | GPT-4 extracts discrete facts ("prefers X", "works on Y", "meeting with Z") as searchable memories |
| Semantic search | Pinecone vector DB, searched in real time during chat |
| Full RAG chat | 18+ tools: memories, conversations, calendar, Gmail, Apple Health, screen activity, files, web search (Perplexity), action items, goals, notifications |
| App integrations | Todoist, Microsoft Tasks |
| Real-time events | WebSocket pushes new memories and facts to the app as they are created |
| Push notifications | Proactive alerts from FCM based on conversation patterns |
| TTS voice responses | ElevenLabs synthesis |
| Agent proxy | Personal VM running a long-running AI agent |
| Goal tracking | LLM extracts and tracks goals from conversation context |
| Daily / weekly summaries | Automated digests via cron (Modal) |
| Private cloud audio | Encrypted audio backup to personal GCS/S3 |
| App marketplace | Custom personas and third-party integrations |

---

## ✅ Fully Working in Local Mode

### Audio Capture

- **Omi pin via `pin_bridge.py`** — BLE connection, Opus decode, real-time PCM stream to `/v4/listen`, partial transcripts printed to terminal every ~5 s.
- **Thin bridge mode (`--thin`)** — bridge machine requires only `pip install bleak websockets PyJWT`. No system Opus library (`brew install opus`) required on the bridge machine; decoding happens on the backend.
- **Multi-machine** — backend runs on one machine; any Mac on the same LAN can run the bridge or Desktop app pointing at `<YOUR_SERVER_IP>:8088`. See RUNBOOK §10.5.
- **Offline SD card drain** — when the pin recorded while out of BLE range, audio is automatically replayed into the live transcription stream on the next connect. No manual action required.
- **iOS WAL sync** — when the iOS app was off-network while recording, `.bin` WAL files are uploaded on reconnect via `POST /v2/sync-local-files`. Opus is decoded on the backend; a conversation record is created automatically.

### Transcription

- **faster-whisper** running entirely on the backend machine — no audio is sent to any external service.
- Configurable model size: `tiny` (fastest, lower accuracy), `base` (default, good for clear speech), `small`, `medium`, `large-v2` / `large-v3`. Set `LOCAL_WHISPER_MODEL` in `.env`.
- Audio from the pin at 8 kHz (`pcm8`) is upsampled to 16 kHz automatically before Whisper receives it.
- Opus audio (`codec=opus`) is now decoded by the backend — this enables thin bridge mode and iOS transcription via the local build.
- First partial on cold Whisper load: 15–30 s. Subsequent partials: every ~5 s.

### Storage

- **SQLite** (`omi_local.db`) — conversations, transcript segments, memories, action items, users, messages. The database file is at `backend/omi_local.db` relative to the repository root.
- **Qdrant** — each conversation is vectorized with a local sentence-transformer model and upserted to Qdrant on save. This is the foundation for semantic search.
- Nothing is written outside the local machine after initial model downloads.

### REST API

All data is accessible through the local API. The full interactive reference is at `http://<YOUR_SERVER_IP>:8088/docs` (Swagger UI — sign in with your JWT token using the Authorize button).

| Method | Endpoint | What it returns |
|--------|----------|----------------|
| `GET` | `/v1/conversations` | Paginated list of all conversations (title, transcript segments, structured data) |
| `GET` | `/v1/conversations/{id}` | Single conversation with full transcript |
| `GET` | `/v3/memories` | Stored memory facts |
| `GET` | `/v1/action-items` | Action items list |
| `POST` | `/v1/chat` | Send messages to Ollama, get a response |
| `POST` | `/v1/chat/stream` | Streaming chat (server-sent events) |
| `GET` | `/healthz` | Backend health and active provider config |
| `POST` | `/v2/sync-local-files` | Upload iOS WAL audio files for transcription |

### Admin UI

Available at `http://<YOUR_SERVER_IP>:8088/admin` from any browser on the LAN.

- **Users** — create, edit, delete accounts; reset passwords; generate a JWT for any user (Get Token button, valid 24 h)
- **Settings** — edit backend `.env`, Desktop app config, iOS app config directly from the browser
- **Docs** — this document and all other project documentation
- **URLs** — quick reference sheet for all API endpoints

### Authentication

- Local JWT — HS256, signed with `LOCAL_JWT_SECRET`, 24 h TTL by default.
- `LOCAL_AUTH_BYPASS=true` — lets the iOS and Desktop apps authenticate with their Firebase-issued tokens without the backend contacting Firebase. After the one-time Firebase sign-in, the backend is fully isolated.

---

## ⚠️ Partially Working — Manual Steps Required

### LLM Post-Processing (Summary, Category, Action Items)

**What the cloud does automatically:** After every conversation ends, GPT-4 processes the full transcript and writes a proper title, summary, inferred category, and extracted action items back to the conversation record. This happens within seconds of the WebSocket closing.

**What the local setup does instead:** When the WebSocket closes, the backend saves:

| Field | Local value |
|-------|------------|
| `title` | First 80 characters of the raw transcript |
| `overview` | First 500 characters of the raw transcript |
| `action_items` | Empty list — always |
| `category` | `"other"` — always |

No LLM is called at session end. The structure is saved immediately but contains no AI-generated content.

**How to run post-processing manually:**

Ollama is fully wired. You can send any conversation's transcript to the chat endpoint:

```bash
# Fetch the transcript text from a conversation
TRANSCRIPT=$(curl -s http://<YOUR_SERVER_IP>:8088/v1/conversations/<id> \
  -H "Authorization: Bearer $TOKEN" \
  | python -c "
import sys, json
c = json.load(sys.stdin)
print(' '.join(s['text'] for s in c.get('transcript_segments', [])))
")

# Ask Ollama to summarize and extract action items
curl -s -X POST http://<YOUR_SERVER_IP>:8088/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"messages\":[{\"role\":\"user\",\"content\":\"Summarize this and list any action items:\\n$TRANSCRIPT\"}]}"
```

For streaming output:
```bash
curl -s -X POST http://<YOUR_SERVER_IP>:8088/v1/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"messages\":[{\"role\":\"user\",\"content\":\"Summarize this conversation:\\n$TRANSCRIPT\"}]}"
```

### Memory Extraction

**What the cloud does:** The LLM extracts discrete facts from each conversation ("prefers morning meetings", "working on project X", "allergic to Y") and stores them as structured memories — the personal knowledge base that powers RAG chat.

**What the local setup has:** The memories system is fully implemented and the endpoints work. `GET` and `POST /v3/memories` read and write memories. Nothing auto-populates them from conversations — you can create memories manually via the API or by pasting a transcript into the chat and asking Ollama to extract facts, then `POST`ing them yourself.

### Semantic Search

**What the cloud does:** Full-text and semantic search over all conversations and memories, surfaced in the app UI.

**What the local setup has:** Every conversation is vectorized on save and stored in Qdrant. The infrastructure is complete. There is no dedicated search endpoint in the local router and no search UI. You can query Qdrant directly at `http://localhost:6333/dashboard` or via the Qdrant REST API.

---

## ❌ Not Available in Local Mode

| Feature | Why it is absent |
|---------|-----------------|
| **Automatic post-session LLM summarization** | No post-session callback is wired to call Ollama at end of WebSocket session. The infrastructure exists — it is a missing background job, not a missing capability. |
| **Automatic memory extraction** | Same reason — Ollama is available but the trigger that calls it after each conversation does not exist yet. |
| **Speaker diarization** | Requires pyannote (GPU-heavy), the separate diarizer Docker service, and a Modal GPU function. `ENABLE_DIARIZATION=false`. All speech is attributed to `SPEAKER_00`. |
| **Full RAG chat (18 tools)** | Production chat uses calendar, Gmail, Apple Health, screen activity, web search, files, memories search, etc. Local `/v1/chat` is a direct pass-through to Ollama with no tool use and no retrieval augmentation. |
| **Real-time memory events** | `new_memory_created` WebSocket events are not emitted. App shows no memory pop-ups during a session. |
| **Push notifications** | Requires Firebase Cloud Messaging. Not wired in local mode. |
| **TTS voice responses** | ElevenLabs and Piper are not configured. `/v1/tts` returns 501. |
| **Agent proxy** | The agent WebSocket bridge (`agent.omi.me`) connects to personal GCE VM instances — cloud infrastructure only. |
| **App marketplace / custom personas** | Third-party integrations and persona management are cloud-only. |
| **Calendar, Gmail, Apple Health integrations** | Require OAuth flows and cloud-side data sync — not implemented in local routers. |
| **Goal tracking** | Not implemented. No router or database model exists yet. Full implementation plan: `LOCAL_IMPLEMENTATION_PLAN.md §A.4`. |
| **Daily and weekly summaries** | Generated by the Modal cron job — cloud only. |
| **Perplexity web search** | No API key; not present in local chat tools. |
| **Conversation silence timeout** | In production, a new conversation auto-starts after N seconds of silence. Locally, a new conversation is created only when the WebSocket closes (Ctrl-C or disconnect). |
| **Private cloud audio backup** | GCS / S3 audio storage is not configured in local mode. |
| **iOS app transcription (stock build)** | The App Store app points at `api.omi.me` and cannot be redirected. A custom build from source is required (see RUNBOOK §10.3). Even with a custom build, transcription via the iOS app has edge cases that are untested locally. Use `pin_bridge.py` for reliable transcription. |

---

## Data Access Reference

### Finding your data

```
backend/omi_local.db      — SQLite: all conversations, memories, users, action items, messages
backend/env_backups/      — Automatic .env snapshots before each settings save
```

Qdrant data lives in the Docker container volume (separate from the SQLite file). It is rebuilt automatically from the next conversation save if the container is recreated; it is not the source of truth for conversation text.

### Querying SQLite directly

```bash
DB=backend/omi_local.db   # run from project root, or adjust path

# Last 10 conversations — title and timestamp
sqlite3 "$DB" "SELECT title, created_at FROM conversations ORDER BY created_at DESC LIMIT 10;"

# Full transcript of the most recent conversation
sqlite3 "$DB" \
  "SELECT json_each.value
   FROM conversations, json_each(conversations.transcript_segments)
   ORDER BY conversations.created_at DESC LIMIT 1;" 2>/dev/null \
  || sqlite3 "$DB" \
  "SELECT transcript_segments FROM conversations ORDER BY created_at DESC LIMIT 1;"

# All stored memories
sqlite3 "$DB" "SELECT content, category, created_at FROM memories ORDER BY created_at DESC;"

# Action items
sqlite3 "$DB" "SELECT text, completed, created_at FROM action_items ORDER BY created_at DESC;"
```

### Via the API

```bash
# Get a token (or use Get Token in the Admin UI)
export TOKEN=$(curl -sS -X POST http://<YOUR_SERVER_IP>:8088/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"pin@omi.dev","password":"hunter2"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# List all conversations
curl -s "http://<YOUR_SERVER_IP>:8088/v1/conversations" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool

# Single conversation (replace <id> with a UUID from the list)
curl -s "http://<YOUR_SERVER_IP>:8088/v1/conversations/<id>" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool

# List memories
curl -s "http://<YOUR_SERVER_IP>:8088/v3/memories" \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

The **Swagger UI** at `http://<YOUR_SERVER_IP>:8088/docs` is the most convenient interactive interface — click Authorize, paste the token, and execute any endpoint from the browser.

---

## Verifying Nothing Leaves the Network

On the backend machine, while audio is actively being transcribed:

```bash
sudo lsof -i -n -P | grep ESTABLISHED | grep -v "127.0.0.1\|192.168.50"
```

If no output appears, no audio-related connections to external addresses exist. The only permitted one-time internet events are:

- **Whisper model download** (Hugging Face) — first backend start with `STT_PROVIDER=local`. Cached locally afterward; never contacted again.
- **Ollama model download** — first use of a new model. Cached locally afterward.
- **Firebase sign-in** (iOS / Desktop app only) — one-time auth handshake. No audio involved. `LOCAL_AUTH_BYPASS=true` means the backend does not contact Firebase to re-validate tokens after the initial sign-in.

---

## Summary — Local vs Cloud

| Category | Cloud Omi | This Local Setup |
|----------|-----------|-----------------|
| Audio capture from pin | ✅ | ✅ |
| Real-time transcription | ✅ Deepgram (< 1 s) | ✅ faster-whisper (~5 s chunks) |
| Conversation storage | ✅ Firestore | ✅ SQLite |
| Semantic search index | ✅ Pinecone | ✅ Qdrant (no UI yet) |
| AI title + summary | ✅ automatic | ❌ raw text truncation only |
| AI category + action items | ✅ automatic | ❌ not automatic (manual via `/v1/chat`) |
| Memory extraction | ✅ automatic | ❌ not automatic (manual via API) |
| Speaker identification | ✅ | ❌ all speech = SPEAKER_00 |
| RAG chat (tools, retrieval) | ✅ 18 tools | ❌ basic Ollama chat only |
| iOS app (full) | ✅ | ⚠️ requires custom build; edge cases untested |
| macOS Desktop app | ✅ | ✅ with `OMI_PYTHON_API_URL` set |
| Push notifications | ✅ | ❌ |
| TTS voice responses | ✅ ElevenLabs | ❌ |
| No audio leaving the network | ❌ (cloud STT/LLM) | ✅ fully local after model downloads |
| No subscription required | ❌ | ✅ |

# Omi Local Backend — Web Paths

All URLs below assume the default host and port. Substitute your LAN IP
(`<YOUR_SERVER_IP>` by default — shown in the startup banner) to reach the
server from another machine on the network.

```
Base URL (this machine):  http://127.0.0.1:8088
Base URL (LAN):           http://<YOUR_SERVER_IP>:8088
```

---

## Developer UI

| URL | Description |
|-----|-------------|
| `http://127.0.0.1:8088/docs` | **Swagger UI** — interactive API explorer. Try every endpoint directly in the browser; handles auth headers, request bodies, and shows response schemas. Start here. |
| `http://127.0.0.1:8088/redoc` | **ReDoc** — read-only API reference in a clean two-panel layout. Better for reading; Swagger is better for testing. |
| `http://127.0.0.1:8088/openapi.json` | Raw OpenAPI 3.0 schema (JSON). Import into Postman, Insomnia, or any API client. |

---

## System

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| GET | `/healthz` | None | Health check. Returns `{"ok": true, "local_mode": true, "providers": {...}}` showing which backend is active for each subsystem (llm, stt, embeddings, etc.). |

---

## Auth  (`/v1/auth`)

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| POST | `/v1/auth/register` | None | Create a new user account. Body: `{"email": "...", "password": "..."}`. Returns a JWT. |
| POST | `/v1/auth/login` | None | Log in. Body: `{"email": "...", "password": "..."}`. Returns `{"access_token": "..."}`. |
| GET | `/v1/auth/me` | Bearer token | Returns the profile of the currently authenticated user. |

> All protected endpoints require `Authorization: Bearer <token>` in the request header.
> Tokens are valid for `LOCAL_JWT_TTL_SECONDS` (default 24 hours).

---

## Chat  (`/v1/chat`)

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| POST | `/v1/chat` | Bearer token | Send a message and receive a complete response. Body: `{"messages": [{"role": "user", "content": "..."}]}`. Routed to Ollama (`OLLAMA_CHAT_MODEL`). |
| POST | `/v1/chat/stream` | Bearer token | Same as above but streams the response back as Server-Sent Events. Use when you want token-by-token output. |

---

## Memories  (`/v1/memories`)

Short-term facts and notes about the user — used by the RAG pipeline to enrich chat responses.

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| POST | `/v1/memories` | Bearer token | Create a memory. Body: `{"content": "...", "category": "..."}`. Stored in SQLite and indexed in Qdrant for semantic search. |
| GET | `/v1/memories` | Bearer token | List all memories for the current user. |
| POST | `/v1/memories/search` | Bearer token | Semantic search over memories. Body: `{"query": "..."}`. Returns ranked results from Qdrant. |

---

## Conversations  (`/v1/conversations`)

Full conversation transcripts — created automatically when `AUTO_PERSIST_TRANSCRIPTS=true` or via the API.

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| POST | `/v1/conversations` | Bearer token | Create a conversation manually. |
| GET | `/v1/conversations` | Bearer token | List all conversations for the current user. |
| GET | `/v1/conversations/{id}` | Bearer token | Fetch a single conversation by ID. |
| POST | `/v1/conversations/{id}/messages` | Bearer token | Append a message to a conversation. |
| GET | `/v1/conversations/{id}/messages` | Bearer token | List all messages in a conversation. |

---

## Action Items  (`/v1/action-items`)

Tasks extracted from conversations or created manually.

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| POST | `/v1/action-items` | Bearer token | Create an action item. Body: `{"text": "...", "due": "2026-05-10"}`. |
| GET | `/v1/action-items` | Bearer token | List all action items for the current user. |
| GET | `/v1/action-items/{id}` | Bearer token | Fetch a single action item. |
| PATCH | `/v1/action-items/{id}` | Bearer token | Update an action item (e.g. mark complete). |
| DELETE | `/v1/action-items/{id}` | Bearer token | Delete an action item. |

---

## Live Audio Streaming — Full Conversation Pipeline  (`/v4/listen`)

Production-compatible WebSocket used by the iOS Flutter app and macOS Desktop app. Transcribes audio in real time, emits transcript segment events, and on close creates a Conversation record in SQLite + Qdrant.

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| WS | `ws://127.0.0.1:8088/v4/listen` | `Authorization: Bearer <token>` header | Full conversation-lifecycle audio stream. Accepts raw PCM16 binary frames. Emits JSON events: `transcript_segment`, `conversation_processing_started`, `conversation_event`. On WebSocket close, persists the conversation to SQLite and indexes in Qdrant. |

**Query parameters** (all optional, same as production):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `language` | `en` | BCP-47 language code |
| `sample_rate` | `16000` | Audio sample rate in Hz. Use `8000` for BLE pin (`codec=pcm8`), `16000` for Desktop (`codec=linear16`) |
| `codec` | `linear16` | `linear16` (16 kHz Desktop) or `pcm8` (8 kHz BLE pin) |
| `uid` | — | User ID hint from client (ignored; auth-derived ID is used) |
| `source` | — | Client identifier string (e.g. `omi`, `desktop`) |
| `include_speech_profile` | `true` | Accepted but ignored in local mode |
| `conversation_timeout` | `120` | Accepted but unused; conversation is finalized on WS close |
| `speaker_auto_assign` | `disabled` | Accepted but ignored; all segments labeled `SPEAKER_00` |

**Auth**: `LOCAL_AUTH_BYPASS=true` (already set in `.env`) makes the endpoint accept any Bearer token including Firebase ID tokens from the mobile/desktop apps. To require validated local JWTs instead, set `LOCAL_AUTH_BYPASS=false` and use a token from `POST /v1/auth/login`.

**Used by**: iOS Flutter app, macOS Desktop app, and `pin_bridge.py` (after updating its WS URL).

---

## Transcription  (`/v1/transcribe`)

Simple audio → text via local faster-whisper. No conversation lifecycle.

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| POST | `/v1/transcribe` | Bearer token | Upload an audio file for transcription. Multipart form: `file=<audio>`. Returns `{"transcript": "..."}`. Supports wav, mp3, opus, and most common formats. |
| WS | `ws://127.0.0.1:8088/v1/transcribe/stream` | First frame = JWT string | Streaming transcription WebSocket. Send raw PCM16 mono 16 kHz audio frames; receive `partial` events in real time. Send the text frame `"END"` to flush the final result. Currently used by `pin_bridge.py`. No conversation persistence — use `/v4/listen` for full conversation lifecycle. |

---

## WebSocket  (`/ws`)

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| WS | `ws://127.0.0.1:8088/ws` | `?token=<jwt>` | General-purpose push channel. The server broadcasts real-time events (transcript updates, memory extractions) to connected clients. |

---

## Stubs (return 501 in local mode)

These endpoints exist so clients don't crash with 404, but the underlying services are not available without cloud credentials.

| URL | Reason |
|-----|--------|
| `POST /v2/tts/synthesize` | ElevenLabs TTS — requires `ELEVENLABS_API_KEY` |
| `GET /v1/knowledge-graph` | Neo4j knowledge graph — not available locally |
| `POST /v1/knowledge-graph/rebuild` | Same |
| `DELETE /v1/knowledge-graph` | Same |

---

## Quick-start with curl

```bash
BASE=http://127.0.0.1:8088

# 1. Register
curl -s -X POST $BASE/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"me@omi.dev","password":"hunter2"}'

# 2. Login → capture token
TOKEN=$(curl -s -X POST $BASE/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"me@omi.dev","password":"hunter2"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 3. Health check
curl -s $BASE/healthz | python3 -m json.tool

# 4. Chat
curl -s -X POST $BASE/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"hello"}]}'

# 5. Create a memory
curl -s -X POST $BASE/v1/memories \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"content":"I prefer concise answers","category":"preference"}'

# 6. Search memories
curl -s -X POST $BASE/v1/memories/search \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"query":"communication style"}'
```

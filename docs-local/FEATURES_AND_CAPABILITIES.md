# Omi Platform — Features & Capabilities

> **Cloud product reference.** This document describes the full Omi platform as built
> for cloud deployment (Firebase, OpenAI, Pinecone, Deepgram). It is useful for
> understanding the complete feature set and data architecture, but does not reflect which
> features are available in local mode.
>
> For what works locally, see `LOCAL_CAPABILITIES.md`.
> For what cannot be made local, see `UNFIXABLE_FEATURES.md`.

This document is a comprehensive reference for every capability across the Omi platform. It covers the Python backend, macOS desktop application, and iOS/Android mobile application, including how each component accesses, processes, and stores user data.

---

## Table of Contents

1. [Platform Overview](#platform-overview)
2. [Data Collection & Privacy](#data-collection--privacy)
3. [Backend (Python)](#backend-python)
4. [macOS Desktop Application](#macos-desktop-application)
5. [iOS / Android Mobile Application](#ios--android-mobile-application)

---

## Platform Overview

Omi is a personal AI memory and productivity platform built around wearable audio capture devices. The platform consists of three main components:

| Component | Language | Entry Point | Primary Role |
|---|---|---|---|
| **Backend** | Python / FastAPI | `main.py` / `main_local.py` | API, transcription, AI processing, data storage |
| **Desktop App** | Swift (macOS) | `OmiApp.swift` | Screen capture, BLE device bridge, local AI, file indexing |
| **Mobile App** | Flutter (Dart) | `main.dart` | Primary user interface, BLE device management, conversations |

The backend operates in two modes:
- **Cloud mode** — Firebase auth, Firestore database, Deepgram STT, OpenAI/Anthropic LLMs, Pinecone vector search
- **Local mode** — JWT auth, SQLite database, local Whisper STT, Ollama LLMs, Qdrant vector search

---

## Data Collection & Privacy

This section documents how the platform accesses user data across device boundaries, particularly data that users may not have explicitly authorized through standard OS permission flows.

### Browser Cookie Access (Chrome, Brave, Arc, Edge)

**Where:** `Desktop/Sources/GmailReaderService.swift`, `Desktop/Sources/CalendarReaderService.swift`

The desktop app directly reads SQLite cookie databases from every installed Chromium-based browser:

| Browser | Cookie Database Path |
|---|---|
| Google Chrome | `~/Library/Application Support/Google/Chrome/Default/Cookies` |
| Brave | `~/Library/Application Support/BraveSoftware/Brave-Browser/Default/Cookies` |
| Arc | `~/Library/Application Support/Arc/User Data/Default/Cookies` |
| Microsoft Edge | `~/Library/Application Support/Microsoft Edge/Default/Cookies` |

All profile folders are scanned (`Default`, `Profile 1`, `Profile 2`, etc.).

**Why this is called "vault" access:** Chromium encrypts cookies on disk using AES-128-CBC. The decryption key is stored in macOS Keychain under entries named `"Chrome Safe Storage"`, `"Brave Safe Storage"`, `"Arc Safe Storage"`, and `"Microsoft Edge Safe Storage"`. The OS permission prompt you saw was the app requesting these keychain entries via:

```
/usr/bin/security find-generic-password -s "Chrome Safe Storage" -w
```

Once retrieved, the app derives the 16-byte AES key using PBKDF2-HMAC-SHA1 with the salt `saltysalt` and 1003 iterations, then decrypts the `encrypted_value` column from the cookies database. The decrypted keychain passwords are cached permanently in `UserDefaults` under `"cachedBrowserKeychainPasswords"` so the OS prompt only appears once.

**What is extracted:** After decryption, the app targets cookies for `gmail.com` and `google.com`, specifically the session auth tokens: `SID`, `HSID`, `SSID`, `APISID`, `SAPISID`, `__Secure-1PSID`, `__Secure-3PSID`. These tokens represent your live authenticated Google session.

### Gmail Email Access

**Where:** `Desktop/Sources/GmailReaderService.swift`

Using the decrypted browser cookies, the app authenticates directly to `mail.google.com` by synthesizing a `SAPISID` bearer token from the extracted cookies, with a spoofed Chrome user-agent string. No Google OAuth consent screen is shown.

Email data is fetched via the Gmail Atom feed (`https://mail.google.com/mail/feed/atom`) for inbox and individual labels. The following fields are extracted per email: sender, subject, snippet, date, thread ID, read status.

**Scope:**
- Onboarding: last 30 days of email, up to 50 messages
- Ongoing: last 24 hours of email per sync

**How emails become memories:** Raw email data is passed to the LLM (via the local backend) which extracts facts, preferences, and profile information. Results are stored via `POST /v3/memories` with tags `["gmail", "onboarding", "profile"]`, `source: "gmail"`, and `visibility: "private"`. Individual emails can also be saved directly as memories in the format `"Email from [sender] — \"[subject]\": [snippet]"`.

### Google Calendar Access

**Where:** `Desktop/Sources/CalendarReaderService.swift`

Uses the same browser cookie extraction and SAPISID synthesis mechanism as Gmail. Fetches events from 90 days in the past to 14 days in the future (up to 200 events). Event data includes: id, summary, start/end time, attendees, location, description, all-day flag.

Events are synthesized into memories and tasks by the LLM, then stored with `source: "calendar"`.

### Apple Notes Access

**Where:** `Desktop/Sources/AppleNotesReaderService.swift`

Reads Apple Notes directly from its SQLite database without any OS-level consent prompt (the file is accessible because the app is not sandboxed):

```
~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite
```

Queries the `ZICCLOUDSYNCINGOBJECT` table for non-deleted notes with titles and summaries. Up to 40 notes (sorted by modification date) are processed through the LLM and saved as memories with tags `["apple_notes", "import", "note"]`.

### Screen Capture & OCR

**Where:** `Desktop/Sources/ScreenCaptureService.swift`, `Desktop/Sources/ScreenActivitySyncService.swift`, `Desktop/Sources/Rewind/`

Uses Apple's ScreenCaptureKit API (macOS 14+) to capture the active window approximately every 3 seconds. Each captured frame is processed through Apple Vision framework OCR to extract all visible text. Screenshots are stored locally in a GRDB SQLite database (`~/Library/Application Support/Omi/users/{userId}/omi.db`) with the fields: timestamp, app name, window title, OCR text, and a vector embedding.

Screenshot metadata and embeddings are synced in batches of 100 to the backend endpoint `POST /v1/screen-activity/sync` every 60 seconds. This enables the AI to search screen activity semantically via the `get_screen_activity_tool` and `search_screen_activity_tool` in the RAG pipeline.

### App Sandbox Status

The desktop app explicitly disables macOS sandboxing:

```xml
<key>com.apple.security.app-sandbox</key>
<false/>
```

This means the app has unrestricted read/write access to the entire filesystem under the user account — there is no OS containment preventing file reads beyond what the above TCC prompts cover. File indexing, browser database access, Apple Notes access, and keychain queries all depend on this.

### File Indexing

**Where:** `Desktop/Sources/FileIndexing/FileIndexerService.swift`

Scans the following directories to build a searchable file index: `~/Downloads`, `~/Documents`, `~/Desktop`, `~/Developer`, `~/Projects`, `~/Code`, `~/src`, `~/repos`, `~/Sites`, `/Applications`, `~/Applications`. Recurses up to 3 levels deep, excludes common build/cache directories. Files up to 500 MB are indexed. Results are stored in GRDB and analyzed by the AI during onboarding.

### Summary of Data Access

| Data Source | Mechanism | Permission Required | What Is Extracted | Stored As |
|---|---|---|---|---|
| Gmail | Browser cookie decryption + Atom feed | Keychain "vault" prompt | Sender, subject, snippet, date | Memories tagged `source:gmail` |
| Google Calendar | Same browser cookies | Keychain "vault" prompt | Events, attendees, location | Memories tagged `source:calendar` |
| Apple Notes | Direct SQLite read | None (unsandboxed) | Title, summary, content | Memories tagged `source:apple_notes` |
| Screen content | ScreenCaptureKit | Screen Recording prompt | Window content, OCR text | Local GRDB + backend embeddings |
| Files | Direct filesystem read | None (unsandboxed) | File names and contents | Local GRDB index |
| Microphone | CoreAudio | Microphone prompt | Audio → transcript → memories | Conversations + memories |

---

## Backend (Python)

The backend is a FastAPI application supporting both cloud (`main.py`) and fully local (`main_local.py`) operation modes. All capabilities below are available in cloud mode; local mode substitutes cloud providers with local alternatives.

### Authentication & User Management

**Auth methods:**
- Firebase OAuth (Google Sign-In, Apple Sign-In) — cloud mode
- Local JWT (HS256, configurable TTL) — local mode
- OAuth code exchange with RFC 8252 compliant redirect URI security
- Custom URL scheme callbacks: `omi://`, `omi-computer://`

**User endpoints:**
- `POST /v1/auth/google/callback` — Google OAuth callback
- `POST /v1/auth/apple/callback` — Apple OAuth callback
- `GET /v1/users/me` — current user profile
- `PUT /v1/users/me` — update profile, preferences, subscriptions
- `GET /v1/users/me/subscription` — subscription status and plan limits
- `GET /v1/users/me/usage` — monthly/daily usage by feature

**Admin endpoints (local mode):**
- `GET /v1/admin/users` — list all users
- `PATCH /v1/admin/users/{id}` — update user
- `POST /v1/admin/users/{id}/set-password` — reset password
- `POST /v1/admin/users/{id}/token` — generate user token

**User data model:** display name, email, timezone, language preferences, subscription tier, chat quota, transcription credits, geolocation cache, personal contacts, speech profiles, BYOK API keys per provider.

---

### Audio & Transcription Pipeline

**Primary WebSocket endpoint:** `GET /v4/listen`

- Protocol: binary PCM16-LE audio frames, JSON event responses
- Sample rates: 8 kHz (BLE codec, upsampled to 16 kHz) or 16 kHz (desktop)
- Multi-language support via `language` query parameter

**STT providers:**
- Deepgram Nova-3 — cloud streaming, multi-language
- Local Whisper — offline transcription (local mode)

**VAD (Voice Activity Detection):**
- Pyannote-based VAD gating
- Energy-based (configurable RMS threshold)
- Silero VAD (optional)
- Shadow mode (log-only) and active gate mode

**Speaker identification:**
- Pyannote speaker diarization (GPU-accelerated, separate diarizer service)
- Speaker embedding extraction (pyannote/embedding, wespeaker-voxceleb-resnet34-LM)
- Speaker matching against enrolled voice profiles
- Automatic segment-to-speaker assignment

**Codecs supported:** PCM16, Opus, AAC, µ-law

**Fair use & quotas:**
- Rolling speech-hour tracking via Redis minute buckets
- Soft-cap with enforcement stages; hard restriction when budget exhausted
- Daily Deepgram millisecond limit configurable
- Per-request quota checks with 402 responses on exhaustion

---

### Conversations

**Endpoints:**
- `POST /v1/conversations` — finalize and trigger processing
- `GET /v1/conversations` — list (paginated, filterable)
- `GET /v1/conversations/{id}` — retrieve with transcript
- `PUT /v1/conversations/{id}` — update metadata
- `DELETE /v1/conversations/{id}` — delete and remove audio
- `POST /v1/conversations/{id}/reprocess` — reprocess with new LLM settings
- `POST /v1/conversations/{id}/merge` — merge multiple conversations
- `POST /v1/conversations/search` — semantic search
- `PATCH /v1/conversations/{id}/segments/{segment_id}` — edit transcript segment
- `POST /v1/conversations/{id}/segments/assign` — bulk speaker assignment
- `POST /v1/conversations/{id}/summary` — generate summary with custom prompt

**Stored data:** encrypted transcript segments (AES-256-GCM), timestamps, language, status, source, photos/images, geolocation, structured results (title, summary, category, emotion, action items, facts).

**Status lifecycle:** `in_progress` → `processing` → `completed` / `discarded` / `failed`

**Processing pipeline (via pusher service):**
- LLM memory extraction
- Action item extraction
- Summary and structured data generation
- Calendar context injection
- Geolocation tagging
- Speaker identification correlation
- Photo description via vision AI

---

### Memories

**Endpoints:**
- `POST /v3/memories` — create single memory
- `POST /v3/memories/batch` — batch create up to 100
- `GET /v3/memories` — list (paginated, filterable by category/date)
- `PATCH /v3/memories/{id}` — update content or visibility
- `DELETE /v3/memories/{id}` — delete
- `DELETE /v3/memories` — delete all for user
- `POST /v3/memories/search` — semantic search

**Categories:** System (auto-extracted facts), Manual (user-authored), Interesting (auto-flagged), Learnings (inferred insights), Preferences, Others.

**Features:**
- Per-user AES-256-GCM encryption at rest
- Visibility control: private, public, shared
- Vector embeddings for semantic search (Pinecone or Qdrant)
- Duplicate detection via embedding similarity
- Auto-extraction from conversations via LLM
- Source tracking (conversation ID, data origin)

---

### AI Chat

**Endpoints:**
- `POST /v2/messages` — send text message
- `POST /v2/messages/voice` — upload voice message (PCM/Opus/AAC)
- `POST /v2/messages/stream` — streaming chat responses
- `GET /v2/messages` — list messages in session
- `PUT /v2/messages/{id}/rate` — rate message quality
- `POST /v2/messages/{id}/share` — generate shareable link

**Features:**
- Multi-turn conversation with managed context window
- Full RAG tool-use integration (18+ tools, see RAG section)
- File attachments and image uploads
- Voice message transcription before LLM processing
- Persona-based responses (per installed app)
- Streaming JSON events with usage reporting
- Chat quota enforcement (monthly limit, 402 on exhaustion)
- Per-app isolated chat sessions

---

### LLM Integration

**Providers and models:**

| Provider | Models | Use Cases |
|---|---|---|
| OpenAI | gpt-4.1, gpt-4.1-mini, gpt-4.1-nano, o4-mini | Chat, extraction, summarization, reasoning |
| Anthropic | claude-sonnet-4-6 | Agentic chat with tool use |
| Google Gemini | gemini-2.5-flash, gemini-2.5-flash-lite | Chat, routing |
| OpenRouter | Gemini proxied | Fallback/cost routing |
| Perplexity | sonar-pro | Web search |
| Ollama | Configurable local models | Fully offline operation |

**QoS profiles:**
- `premium` — cost-optimized (gpt-4.1-mini for core tasks)
- `max` — quality-first (gpt-4.1 + o4-mini for reasoning)
- `byok` — user-paid API keys, same as max profile

**Feature-to-model routing:** Each feature (`conv_action_items`, `conv_structure`, `daily_summary`, `memories`, `learnings`, `chat_responses`, `chat_agent`, `goals`, `notifications`, `persona_chat`, `web_search`) maps to a specific model and provider, configurable per QoS profile.

**Advanced:** Prompt caching for cost reduction, usage callbacks (token counts, cost), BYOK key substitution per request, streaming with usage reporting.

---

### RAG / Retrieval

The agentic RAG system uses Anthropic native tool use with streaming execution. 18+ core tools are available:

**Conversation tools:** `get_conversations_tool`, `search_conversations_tool`

**Memory tools:** `get_memories_tool`, `search_memories_tool`

**Action item tools:** `get_action_items_tool`, `create_action_item_tool`, `update_action_item_tool`

**Calendar tools:** `get_calendar_events_tool`, `create_calendar_event_tool`, `update_calendar_event_tool`, `delete_calendar_event_tool`

**Gmail tools:** `get_gmail_messages_tool` (requires Google OAuth)

**Apple Health tools:** `get_apple_health_steps_tool`, `get_apple_health_sleep_tool`, `get_apple_health_heart_rate_tool`, `get_apple_health_workouts_tool`, `get_apple_health_summary_tool`

**Screen activity tools:** `get_screen_activity_tool`, `search_screen_activity_tool`

**File tools:** `search_files_tool`

**Utility tools:** `get_omi_product_info_tool`, `manage_daily_summary_tool`, `create_chart_tool`, `save_user_preference_tool`

**Dynamic app tools:** Per-user tools from installed custom apps (MCP server integration).

---

### Integrations & External Services

**OAuth-based integrations:** Google Calendar, Gmail, Todoist, Asana, Google Tasks, ClickUp, Twilio (phone calls)

**Developer webhooks:**
- Triggers: `memory_creation`, `transcript_processed`, `audio_bytes`
- Rate limited: 10/hour per app per user
- Batch audio delivery (4-second accumulation)
- Batch transcript delivery (1-second batches)

**MCP (Model Context Protocol):**
- `POST /v1/mcp/keys` — create MCP integration key
- Memory and conversation CRUD via MCP protocol

---

### Action Items & Tasks

**Endpoints:** Full CRUD at `/v1/action-items` with batch operations, semantic search, and sort-order/indentation management.

**Features:** Due dates with calendar integration, completion tracking with timestamp, Apple Reminders sync (bidirectional via `apple_reminder_id`), export tracking to Todoist/Google Tasks/Asana/Microsoft Tasks, sort order and 0–3 indent levels for hierarchy, semantic vector search.

**Extraction:** Automatic extraction from conversations via LLM, with source conversation linking.

---

### Notifications

**Push notification channels:** FCM (Firebase Cloud Messaging), Pusher real-time events, silent notifications.

**Notification types:** Credit limit warnings, action item updates, proactive AI alerts, daily summaries, integration events (calendar, email), training submission confirmations.

**Rate limiting:** 10 notifications/hour per app per user (Redis bucket tracking).

---

### Apps / Plugins Marketplace

**App management:** Full CRUD at `/v1/apps`. Apps can define: custom chat prompts, conversation prompts, REST tool endpoints, MCP server integration, OAuth flows, and Stripe payment links.

**Features:** Installation tracking, usage history, reviews and ratings, developer approval workflow, public/private visibility, tester access lists, persona username registration, Twitter handle linking.

---

### Vector & Semantic Search

**Backends:** Pinecone (cloud, default) or Qdrant (local, self-hosted) — swappable via `VECTOR_DB_PROVIDER`.

**Embedding providers:** OpenAI `text-embedding-3-large` (default) or local Ollama embeddings.

**Indexed collections:** Memories, conversations, action items, screen activity.

**Operations:** Upsert (single/batch), similarity query, metadata-filtered query, delete, duplicate detection.

---

### Real-time Events

**Event types emitted over WebSocket:**
- `transcript_segment` — live transcription
- `conversation_processing_started` / `conversation_processing_finished`
- `memory_event` — extracted memory
- `translation_event` — multi-language output
- `photo_processing_event` — image analysis result
- `freemium_threshold_reached` — quota warning
- `segments_deleted` — deletion notification
- `speaker_label_suggestion` — diarization result

**Distribution:** Pusher service (separate Docker container) handles fan-out to integrations, developer webhooks, and ML services.

---

### Data Sync

**Mobile sync protocol (`POST /v1/sync`):** File upload/download for recorded audio, sync job tracking and status, conversation audio merging, geolocation injection, pre-recorded Deepgram transcription.

---

### Admin & Configuration (Local Mode)

**Config management (`/v1/admin/config`):** Read and write `.env` files for backend, desktop app, and iOS app. Automatic backup on every save. Meta endpoint returns field descriptions from `.env.reference`.

**Docs endpoint (`/v1/admin/docs`):** Serves project markdown documentation with file browsing and content rendering.

**User management:** Full CRUD, password reset, token generation, self-registration control.

---

### Storage Architecture

**Primary databases:**
- Firestore (cloud) — users, conversations, memories, action items, chat sessions, goals, daily summaries, trends, phone calls, notifications, apps, knowledge graph, folders, imports
- SQLite / PostgreSQL (local mode) — same schema via SQLAlchemy ORM

**Cache & rate limiting:** Redis — session state, geolocation cache, webhook status, fair-use tracking (minute-level speech-hour buckets), rate limit counters (Lua scripts), pub/sub events, distributed locks.

**Vector databases:** Pinecone or Qdrant (swappable at runtime via env).

**Search:** Typesense or local full-text search (swappable).

**Knowledge graph:** Neo4j — entity nodes, relationship edges, memory ID linkage.

**Encryption:** AES-256-GCM per-user encryption with HKDF-SHA256 key derivation. Two data protection levels: basic (unencrypted) and enhanced (encrypted). Applied to conversation transcripts, memories.

---

### Speaker Profiles & Diarization

- Speaker sample enrollment from conversation audio
- Pyannote speaker diarization (GPU diarizer microservice)
- Embedding extraction (pyannote/embedding, wespeaker-voxceleb-resnet34-LM)
- Speaker-to-person mapping with configurable similarity threshold
- Automatic segment assignment, bidirectional mapping updates

---

### Knowledge Graph

- `GET /v1/knowledge-graph` — nodes and edges
- `POST /v1/knowledge-graph/rebuild` — LLM-powered rebuild from memories
- `DELETE /v1/knowledge-graph` — clear graph
- Node types: concepts, entities, people, topics; edges: relationships (connected_to, related_to, etc.); alias resolution; source memory linkage

---

### Goals, Trends & Daily Summaries

**Goals:** Full CRUD at `/v1/goals`, AI-powered suggestions, progress tracking with advice generation.

**Trends:** Behavioral analytics at `/v1/trends`, daily/weekly/monthly rollups.

**Daily summaries:** LLM synthesis of conversations, memories, and activities; scheduled generation via Modal cron; proactive push notification delivery.

---

### Additional Features

- **Text-to-Speech:** `POST /v1/tts` — multi-language synthesis (OpenAI or ElevenLabs)
- **Phone Calls:** Twilio PSTN integration, caller ID verification, call quota tracking
- **Focus Sessions:** Distraction tracking, app/website usage monitoring, productivity insights
- **Staged Tasks:** Multi-step task breakdown, sub-task workflow, progress tracking
- **Year in Review / Wrapped:** Annual summary generation (`/v1/wrapped`)
- **Personalized Advice:** AI-generated advice based on goals, trends, and activity
- **Announcements:** In-app product announcements and broadcast notifications

---

### Developer APIs

**API keys:** `GET/POST/DELETE /v1/dev/keys` with per-resource scopes (conversations, memories, action_items, goals — read/write).

**Platform tool endpoints (`/v1/tools/`):** REST access to conversations, memories, and action items — the same data the RAG agent accesses internally, exposed for external callers.

**BYOK (Bring Your Own Key):** Supply OpenAI, Anthropic, Gemini, and Deepgram keys via `X-BYOK-*` request headers to bypass subscription billing. Keys are SHA-256 fingerprinted for rotation detection.

---

### Security

- AES-256-GCM per-user encryption at rest (HKDF-SHA256 derivation)
- Firebase JWT (cloud) or HS256 JWT (local) for all authenticated requests
- Per-endpoint rate limiting via Redis Lua scripts
- Fair-use soft and hard caps on transcription
- PII redaction in logs via `sanitize()` and `sanitize_pii()` — raw response bodies and user text never appear in logs
- BYOK key substitution with transparent proxy pattern

---

## macOS Desktop Application

The macOS desktop app is a Swift application built without sandbox restrictions, enabling deep OS integration. It acts as the primary interface for device management, screen monitoring, local data ingestion, and AI assistance on the desktop.

### Bluetooth & Omi Pin Hardware

**Files:** `Desktop/Sources/Bluetooth/`

**Supported devices:** Omi, OmiGlass, Bee, PLAUD NotePin, Fieldy/Compass, Friend Pendant, Limitless Pendant, Frame (AR glasses)

**Capabilities:**
- BLE scanning with configurable timeout (default 5 seconds)
- Device identification via service UUIDs and manufacturer data
- RSSI signal strength monitoring
- Device information retrieval: model number, firmware revision, hardware revision, manufacturer name
- Audio streaming over BLE: Opus, PCM, µ-law codecs
- Button event handling
- Haptic feedback commands
- Battery status monitoring
- SD card storage drain (offline audio retrieval when out-of-range)
- Firmware version detection with compatibility checks

---

### Screen Capture & Activity Monitoring

**Files:** `ScreenCaptureService.swift`, `ScreenActivitySyncService.swift`, `Rewind/`

**Capture:**
- ScreenCaptureKit (macOS 14+) — native API capture of active window
- Resolution: up to 3000 px, 80% JPEG quality
- Captures: app name, window title, window ID, full screenshot
- Polling interval: approximately every 3 seconds

**OCR:**
- Apple Vision framework — extracts text blocks with bounding boxes and confidence scores
- Full text and structured blocks stored per frame

**Storage:**
- Local GRDB SQLite: `~/Library/Application Support/Omi/users/{userId}/omi.db`
- Schema: id, timestamp, appName, windowTitle, ocrText, embedding (float BLOB)

**Sync to backend:**
- Batches of 100 screenshots synced to `POST /v1/screen-activity/sync` every 60 seconds
- Exponential backoff on failure; cursor-based resume after restart

---

### Audio Capture

**Files:** `AudioCaptureService.swift`, `SystemAudioCaptureService.swift`, `AudioMixer.swift`, `AudioLevelMonitor.swift`

**Microphone:**
- CoreAudio HAL IOProc: direct input at native device sample rate
- Resamples to 16 kHz PCM mono for backend streaming
- Silent-mic watchdog: fires after 2 consecutive 1-second silent windows on Bluetooth mics
- Fallback to built-in mic on A2DP/SCO BLE conflict
- Audio level smoothing: decay rate 0.85/frame, noise floor 0.005

**System audio:**
- Core Audio Taps (macOS 14.4+) for system-wide output capture
- Aggregate device creation
- Same 16 kHz PCM mono target

**Mixing:**
- `AudioMixer.swift` combines mic + system audio streams
- Normalized level monitoring per stream (0.0–1.0)

**Live transcription:**
- `LiveTranscriptMonitor.shared` receives backend transcript segments in real time
- Speaker diarization labels (SPEAKER_00, etc.) + person ID from backend

---

### Gmail Access

**File:** `GmailReaderService.swift`

See [Data Collection & Privacy](#data-collection--privacy) above for the complete technical description.

**Summary:** Cookie extraction from all Chromium browsers → keychain PBKDF2 key derivation → AES-128-CBC cookie decryption → SAPISID token synthesis → unauthenticated Gmail Atom feed access. Emails are LLM-processed into memories stored with `source: "gmail"`.

---

### Google Calendar Access

**File:** `CalendarReaderService.swift`

Uses the identical cookie extraction mechanism as Gmail. Fetches events from 90 days past to 14 days forward (up to 200 events). Event data is LLM-synthesized into 10 memories + 2–3 tasks per sync.

---

### Apple Notes Access

**File:** `AppleNotesReaderService.swift`

Direct SQLite read of `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`. Queries non-deleted notes with filtering to remove attachment noise. Up to 40 notes processed into 8–12 memories via LLM.

---

### File Indexing

**File:** `FileIndexing/FileIndexerService.swift`

Scans standard directories (`~/Downloads`, `~/Documents`, `~/Desktop`, `~/Developer`, `~/Projects`, `~/Code`, `~/src`, `~/repos`, `~/Sites`, `/Applications`, `~/Applications`) up to 3 levels deep. Excludes build artifacts and dependency directories. Files up to 500 MB, batch-inserted into GRDB in sets of 500. Used during onboarding for AI profile synthesis.

---

### Chat & AI Assistant

**Files:** `Chat/`, `FloatingControlBar/`, `Rewind/`

**Conversation modes:**
- **Listening:** WebSocket to `/v4/listen` — full conversation with diarization, memory extraction, persistence
- **Push-to-Talk:** WebSocket to `/v2/voice-message/transcribe-stream` — transcription only, no persistence
- **Text Chat:** REST or streaming via `AgentBridge`
- **Floating Bar Ask AI:** Quick voice/text input from the always-on floating control bar

**Features:**
- TTS responses via backend `/v1/tts/synthesize` (queued playback via `FloatingBarVoicePlaybackService`)
- Persona context sent per request for personalized responses
- Full conversation history in Firestore + local GRDB
- Live speaker diarization display in transcript

---

### Memory Extraction

**File:** `ProactiveAssistants/Assistants/MemoryExtraction/MemoryAssistant.swift`

Triggers: conversation finalization, onboarding data source imports, file indexing analysis, on-demand via chat. Memory fields include: content, visibility, tags, source, headline, window title, input device name, category, confidence, context summary, current activity, read/dismissed flags.

---

### Floating Control Bar

**Files:** `FloatingControlBar/`

An always-on-top floating window providing: record/play/stop controls, AI chat toggle, notifications overlay, draggable repositioning, resize handles, recording state and voice-listening indicators. Includes a usage limiter that tracks free-tier transcription minutes and chat messages, showing an upgrade prompt when limits are reached.

---

### Desktop Automation Bridge

**File:** `DesktopAutomationBridge.swift`

Local TCP listener on port 47777. Provides programmatic control:
- `GET /health` — app state snapshot
- `GET /state` — full state including selected tab, settings section, auth status
- `POST /navigate` — navigate to: memories, conversations, chat, settings, goals, tasks, rewind
- `POST /conversation/open` — open conversation by ID
- `POST /gmail-read` — trigger Gmail sync and save as memories

---

### Agent VM

**Files:** `AgentVMService.swift`, `AgentSyncService.swift`

Provisions a cloud VM on demand via `POST /v2/agent/provision`. The local GRDB database is gzip-compressed and streamed to the VM. Incremental sync every 3 seconds pushes new/changed rows from 9 tables: `transcription_sessions`, `action_items`, `memories`, `staged_tasks`, `live_notes`, `screenshots`, `transcription_segments`, `focus_sessions`, `observations`. Cursor-based (append-only by ID, mutable by updatedAt). The VM executes complex multi-step tool calls using Claude AI.

---

### Authentication

**File:** `AuthService.swift`

Firebase Auth with Apple/Google Sign-In. Desktop OAuth flow via backend `/v1/auth/authorize`. Token persistence in `UserDefaults` (id token, refresh token, expiry). Automatic token refresh on 401. Supports local backend mode via `DesktopBackendEnvironment`.

---

### Proactive Assistants

**Directory:** `ProactiveAssistants/Assistants/`

Background services that run continuously:

- **Memory Extraction** — extracts memories from conversations, screenshots, and imported data sources
- **Task Extraction** — extracts, deduplicates, prioritizes, and promotes action items from conversations; supports recurrence rules (daily, weekdays, weekly, biweekly, monthly)
- **Focus Assistant** — monitors focus sessions via file timestamps and window changes; stores duration and app/file context
- **Goals Assistant** — synthesizes goals from onboarding data, tracks progress, marks completion
- **Insight Assistant** — generates periodic insights from memories and patterns
- **Task Agent** — interactive Claude-powered agent for complex multi-step task execution with tool use

---

### Browser Extension

**File:** `BrowserExtensionSetup.swift`

Playwright MCP Bridge Chrome extension — enables Chrome automation (form filling, web searching, site interaction) from the AI assistant. Authenticated via a one-time token stored in local storage.

---

### BYOK / API Key Management

**Files:** `APIKeyService.swift`, `BYOKValidator.swift`

Fetches Gemini, Firebase, and Google Calendar API keys from backend on startup. Supports user-supplied OpenAI, Anthropic, Gemini, and Deepgram keys — when all four are provided, subscription billing is bypassed. Keys are sent per-request via `X-BYOK-*` headers and SHA-256 fingerprinted for rotation tracking.

---

### Permissions & Entitlements

**Files:** `Omi.entitlements`, `Omi-Release.entitlements`

| Entitlement | Value | Meaning |
|---|---|---|
| `app-sandbox` | `false` | **No sandboxing — unrestricted filesystem access** |
| `automation.apple-events` | `true` | Can send AppleScript to other apps |
| `device.audio-input` | `true` | Microphone recording |
| `device.screen-capture` | `true` | Screen recording via ScreenCaptureKit |
| `developer.applesignin` | `true` | Sign in with Apple |
| `get-task-allow` | `true` | Debugger attachment (dev builds) |

**TCC prompts required at runtime:** Microphone, Screen Recording, Accessibility API, Automation (AppleScript), Full Disk Access (optional, for protected directories).

---

### Analytics

**Files:** `AnalyticsManager.swift`, `PostHogManager.swift`

Platforms: PostHog (primary), Heap (select high-priority events). Analytics are skipped for non-production builds (`isDevBuild = AppBuild.isNonProduction`).

Tracked events include: onboarding progression, authentication, recording start/stop, conversation finalization, chat interactions, memory creation, permission requests, device pairing/disconnection, permission grants/denials.

Onboarding chat messages are tracked in detail (role, text up to 2000 chars, tool calls, model, errors) for product analytics.

---

### Local Database

**File:** `Rewind/Core/RewindDatabase.swift`

Per-user GRDB SQLite at `~/Library/Application Support/Omi/users/{userId}/omi.db`. Tables: screenshots, transcription_sessions, transcription_segments, action_items, memories, staged_tasks, live_notes, focus_sessions, observations.

---

## iOS / Android Mobile Application

The mobile app is a Flutter application supporting both iOS and Android. It serves as the primary user interface for device management, conversation review, memory browsing, AI chat, and task management.

### BLE / Omi Pin Hardware

**Supported device types (9):** Omi, OmiGlass/OpenGlass, Apple Watch, Bee, PLAUD NotePin, Fieldy/Compass, Friend Pendant, Limitless Pendant, Frame (AR glasses)

**Supported audio codecs (8):** PCM 8-bit, PCM 16-bit, Opus, Opus FS320, µ-law 8-bit, µ-law 16-bit, AAC, LC3 (10 ms/30 byte frames)

**Capabilities:**
- BLE scanning with UUID and manufacturer data identification
- RSSI filtering
- Device information retrieval: model, firmware, hardware revision, manufacturer, serial number
- Audio streaming at 16 kHz standard
- Button event handling per device type
- Haptic feedback (Android vibration permission)
- SD card drain with firmware version detection (Bee v0.6.1+)
- Firmware update checks with compatibility warnings
- Multiple simultaneous device management

**Device-specific connection classes:** `OmiDeviceConnection`, `OmiGlassConnection`, `AppleWatchConnection`, `BeeDeviceConnection`, `PlaudDeviceConnection`, `FieldyDeviceConnection`, `FriendPendantConnection`, `LimitlessConnection`, `FrameDeviceConnection`

---

### Audio Capture & Transcription

**Live streaming:** Real-time audio streaming to backend over WebSocket during capture.

**Transcription providers:**
- Premium: Omi backend cloud (high accuracy, Deepgram)
- Free: On-device — Apple Speech Recognition (iOS), local Whisper (Android)

**Post-processing:** WhisperX via FAL Whisper or custom WhisperX endpoint.

**Speaker diarization:** Multi-speaker segmentation with color-coded speaker assignment UI and speaker profile management.

**Language support:** 48 languages.

---

### Conversations

**Display and filtering:** List view with filter by source, time range, category, speaker; full-text and semantic search; sort by date/relevance/duration.

**Conversation sources:** Omi device, Friend pendant, OmiGlass, Screenpipe, SD card sync, phone calls, Apple Watch, desktop app, and 6 additional hardware sources.

**Structured data per conversation:** Title, summary, category, emotion, action items, participants, geolocation, photos with descriptions.

**Transcript features:** Per-segment timestamps, speaker assignment with UI, unassigned segment merging, segment editing.

**Organization:** Star/favorite flagging, folder assignment, private/shared visibility, conversation locking.

**App integration:** Stores results from executed apps; shows suggested summarization apps per conversation.

---

### Memories

**Categories:** System (auto-extracted facts), Manual, Interesting, Learnings, Preferences.

**Features:** Auto-generation from conversations; manual creation; edit/update; soft-delete with recovery; visibility control (private/public); reviewed/locked flags; user review votes (thumbs up/down for ML training); semantic search; category browsing; timeline view.

---

### AI Chat

**Message types:** Text input, voice recording with live transcription, file/photo attachments, context switching (select specific conversation as context).

**Features:** Multi-turn history, streaming responses, typing indicators, markdown rendering with syntax highlighting, persona/app selection, MCP server integration, message reactions and ratings, image/file preview, swipe gestures on messages.

---

### Action Items / Tasks

**Properties:** Description, completion status, due date, completed timestamp, sort order, indent level (0–3 for hierarchy), locked flag.

**Export integrations:** Apple Reminders (bidirectional, `apple_reminder_id`), Todoist, Google Tasks, Asana, Microsoft Tasks — with export platform and date tracking.

**Sharing:** Token-based shareable task lists; accept/decline shared tasks; batch operations.

---

### Apps / Plugins Marketplace

**Discovery:** Browse by category, search, popularity ranking, ratings and reviews.

**App capabilities:** Conversation prompts, chat prompts, webhook triggers (`memory_creation`, `transcript_processed`, `audio_bytes`), REST chat tools, MCP server endpoints, OAuth flows.

**Monetization:** Free, one-time purchase, and monthly subscription pricing. Stripe Connect for developer payouts. Trial period tracking.

**Custom app creation:** Define tools, OAuth flows, webhooks, and MCP endpoints via the UI.

---

### Settings

**Configurable areas:** User profile (name, email, photo), notification types and timing, language/locale (48 options), connected device management, firmware update checks, audio codec selection, integration connections (see Integrations section), permission status display, developer options (custom API URL, staging backend), app version and build info, data export, account deletion.

---

### Onboarding Flow

14-step onboarding: Welcome → Authentication → Device selection → Device pairing → Firmware verification → Speech profile recording → Permission requests → Apple Watch setup → AI consent → Knowledge graph (key people) → Primary language → Name entry → User review → Completion.

---

### Authentication

**Methods:** Apple Sign-In (PKCE with SHA-256 nonce, iOS/macOS), Google Sign-In (OAuth 2.0, iOS/Android), Firebase Auth identity layer.

**Token management:** ID token stored in SharedPreferences with 5-minute refresh buffer, automatic refresh on 401, bearer token on all API requests.

**Request headers:** `X-Request-Start-Time`, `X-App-Platform`, `X-Device-Id-Hash` (anonymized), `X-App-Version`, `Authorization: Bearer {token}`.

---

### Notifications

**Types:** Action item reminders (before due date), important conversation alerts (AI-scored priority), merge completion, fall detection prompt ("Did you fall?").

**Infrastructure:** FCM (Firebase Cloud Messaging) for push, `AwesomeNotifications` for local, isolate-based handlers, deep links in payloads, per-type notification channels with sound/vibration customization.

**iOS background modes for notifications:** Remote Notification, VoIP.

---

### Device Management

**Features:** Multiple simultaneous device support with primary designation, BLE scanning and filtering, firmware update detection and installation, custom device naming, battery monitoring, auto-reconnect on range restore, per-device codec and sample rate configuration.

---

### Speaker Profiles

**Enrollment:** Record 3–5 minutes of voice samples for speaker identification. Quality verification, noise filtering recommendations, retake capability.

**Management:** Color-coded speaker profiles (8 colors), auto-assign transcript segments, manual reassignment UI, unassigned segment detection, speaker deletion.

---

### Calendar & Third-Party Integrations

| Integration | Type | Capabilities |
|---|---|---|
| Google Calendar | OAuth read/write | Event context for conversations, attendee extraction |
| Apple Reminders | Native read/write | Bidirectional sync with action items |
| Google Tasks | OAuth read/write | Task export from action items |
| Todoist | OAuth write | Task creation with due dates and notes |
| Asana | OAuth write | Project task creation |
| ClickUp | OAuth write | Workspace task creation with priority |
| Apple Health | HealthKit read-only | Steps, distance, active energy, heart rate, sleep, workouts (90-day lookback) |

---

### Permissions

**iOS (Info.plist):** Microphone, Bluetooth Always, Bluetooth Peripheral, Location Always+WhenInUse, Location WhenInUse, Contacts, Calendars, Calendars Full Access, Health Share, Health Update (framework only), Reminders, Reminders Full Access, Speech Recognition, Photo Library, Camera.

**iOS background modes:** Audio, Location, Bluetooth Central, Background Fetch, Background Processing, Remote Notification, VoIP.

**Android (AndroidManifest.xml):** BLUETOOTH_SCAN, BLUETOOTH_CONNECT, ACCESS_FINE_LOCATION, ACCESS_COARSE_LOCATION, RECORD_AUDIO, MODIFY_AUDIO_SETTINGS, READ_CONTACTS, READ_CALENDAR, WRITE_CALENDAR, POST_NOTIFICATIONS, VIBRATE, FOREGROUND_SERVICE (microphone + location + connected device), REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, RECEIVE_BOOT_COMPLETED.

---

### Localization

48 languages supported: Arabic, Belarusian, Bulgarian, Bengali, Bosnian, Catalan, Czech, Danish, German, Greek, English, Spanish, Estonian, Persian, Finnish, French, Hebrew, Hindi, Croatian, Hungarian, Indonesian, Italian, Japanese, Kannada, Korean, Lithuanian, Latvian, Macedonian, Marathi, Malay, Dutch, Norwegian, Polish, Portuguese, Romanian, Russian, Slovak, Slovenian, Serbian, Swedish, Tamil, Telugu, Thai, Tagalog, Turkish, Ukrainian, Urdu, Vietnamese, Chinese.

Uses ARB files with `context.l10n` extension, automatic locale detection, manual override in settings, English fallback.

---

### Analytics

**Platforms:** Mixpanel (primary event tracking), GrowthBook (feature flags, A/B testing), Firebase Crashlytics (crash reporting), PostHog (opt-in session replay).

**Tracked events:** App lifecycle, authentication, device pairing/disconnection, conversation capture start/stop/upload, memory creation/review, chat interactions, app installations, integration connections, settings changes, payment/subscription events, onboarding progression, errors/crashes.

---

### Payment & Subscriptions

**Payment processors:** Stripe (primary, with Connect for developer payouts), PayPal.

**Tiers:**
- Free — limited monthly transcription quota, on-device STT
- Premium — unlimited transcription, cloud STT, all features
- App-specific plans — individual apps can have paid tiers with monthly/annual billing

**Features:** Monthly quota display, usage statistics, upgrade paywall, plan comparison, Stripe Connect payout management for app developers.

---

### Additional Features

- **Phone calls:** Recording and transcription of VOIP calls, call history, incoming/outgoing call handling, phone number management, Twilio integration
- **SD card sync:** Import conversations stored on device SD card during offline periods
- **Quick actions / Siri Shortcuts:** Common task shortcuts, voice command support
- **Home screen widget:** iOS home screen widget showing device battery status
- **Referral program:** Shareable referral links with reward tracking
- **Goals:** Goal creation, progress monitoring, goal-related conversation context
- **Custom STT:** Select alternative transcription vendor with codec compatibility configuration
- **Offline mode:** Queue and sync on connectivity restore, network type detection
- **Fall detection:** Accelerometer-based detection with notification prompt
- **App review system:** User reviews, developer responses, rating aggregation

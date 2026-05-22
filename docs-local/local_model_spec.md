# Local Model Implementation Specification

**Project**: OMI Local Backend  
**Status**: Implementation Plan (Review Ready)  
**Date**: 2026-05-08  
**Author**: Claude Code

---

## Executive Summary

This document provides a detailed implementation plan for features that are not yet available or fully functional in local-only mode. Based on analysis of `GAPS.md`, `MIGRATION_STATUS.md`, and `omi_local_backend_merged_final.md`, this specification identifies **28 gaps** that need to be addressed to achieve a fully self-contained, zero-cloud-dependency system.

### Implementation Approach

The project follows a **provider pattern** where each subsystem (LLM, embeddings, vector DB, STT, auth, etc.) has a cloud implementation and a local implementation, selected via environment variables. The cutover strategy is:

1. **Replace implementations behind interfaces** — Never change consumers until their provider interface is stable
2. **Incremental migration** — Replace one dependency at a time, validate each step
3. **Fail-safes** — Disabled features return explicit error codes (501) rather than crashing

### Current State

| Category | Count | Status |
|----------|-------|--------|
| CRITICAL gaps | 8 | ✅ Resolved |
| HIGH gaps | 18 | 🟡 Partial/Ready for cutover |
| MEDIUM gaps | 5 | 🟠 Deferred/Requires architecture decision |
| LOW gaps | 5 | 🔵 Documentation-only |

**Total features to implement**: 28

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Entrypoint                            │
│                    (main.py / main_local.py)                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Provider Resolver                              │
│                    (backend/providers.py)                        │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │ get_llm_provider() → ollama | openai                     │  │
│   │ get_stt_provider() → local | deepgram                    │  │
│   │ get_embeddings_provider() → local | openai               │  │
│   │ get_vector_db_provider() → qdrant | pinecone             │  │
│   │ get_auth_provider() → local | firebase                   │  │
│   │ get_db_provider() → sqlite | firestore                   │  │
│   │ get_event_provider() → websocket | pusher                │  │
│   │ get_search_provider() → local | typesense | disabled     │  │
│   └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Provider Implementations                       │
│   ┌───────────┬───────────┬───────────┬───────────┬─────────┐  │
│   │   LLM     │ Embeddings│  Vector   │    Auth   │   DB    │  │
│   │ Ollama    │ sentence- │  Qdrant   │  JWT      │ SQLite  │  │
│   │ OpenAI    │ OpenAI    │ Pinecone  │ Firebase  │ Firestore│  │
│   └───────────┴───────────┴───────────┴───────────┴─────────┘  │
│   ┌───────────┬───────────┬───────────┬───────────┬─────────┐  │
│   │    STT    │  Diarization│  Events  │   Search  │         │  │
│   │ Whisper   │  Single    │ WebSockets│  FTS5     │         │  │
│   │ Deepgram  │ Speaker    │ Pusher    │ Typesense │         │  │
│   └───────────┴───────────┴───────────┴───────────┴─────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Local Runtime Topology

```
HTTP/WebSocket Request
    │
    ▼
FastAPI Router  ──►  Provider Resolver
    │                     │
    │                     ├── LLM        → ollama_client.py
    │                     ├── Embeddings → local_embeddings.py
    │                     ├── Vector DB  → vector_db_qdrant.py
    │                     ├── STT        → local_whisper_*
    │                     ├── DB         → sqlite/repository.py
    │                     ├── Auth       → local_auth.py
    │                     └── Events     → connection_manager.py
    ▼
Response
```

---

## Feature Gap Analysis

Each feature below follows this structure:

| Column | Content |
|--------|---------|
| **Gap ID** | Unique identifier (GAP-XX) |
| **Feature** | What functionality is missing |
| **Current State** | What happens today |
| **Expected Behavior** | What should happen in local mode |
| **Priority** | CRITICAL/HIGH/MEDIUM/LOW |
| **Implementation** | Step-by-step cutover plan |
| **Files Changed** | Files to modify/create |
| **Technical Work** | Detailed implementation notes |
| **Dependencies** | What must be done first |
| **Status** | Not started / Ready / Blocked |

---

## Gap #1: Knowledge Graph (Neo4j) → Local Replacement

| Gap ID | Feature | Current State | Expected Behavior |
|--------|---------|---------------|-------------------|
| GAP-20 | Knowledge graph | Neo4j dependency crashes on missing host | Local graph implementation or explicit 501 stub |

| Priority | Implementation | Files Changed | Technical Work | Dependencies |
|----------|----------------|---------------|-----------------|--------------|
| **MEDIUM** | **Option A (Short-term):** Gate all knowledge graph routes to return 501 | `routers/knowledge_graph.py`, `backend/feature_flags.py` | Add feature flag guard: `if is_enabled("knowledge_graph"): return HTTPException(501, detail="Knowledge graph not available in local mode")` | None — Phase 0 first |
| | **Option B (Long-term):** Implement SQLite entity graph | `backend/database/knowledge_graph_local.py` | Use SQL tables for entities/concepts, FTS5 for similarity search, self-joins for relationships. Pattern: `CREATE TABLE entities (id TEXT PRIMARY KEY, type TEXT, name TEXT, description TEXT, vector TEXT)` | Phase 2 embeddings first |
| | **Option C (Alternative):** Stand up Memgraph | `Dockerfile`, `docker-compose.yml` | Add Memgraph service to docker-compose, use Memgraph Python driver instead of Neo4j | Requires Docker Compose updates | |

**Files to Create:**
- `backend/database/knowledge_graph_local.py` — SQLite-based entity graph

**Files to Modify:**
- `routers/knowledge_graph.py` — Add provider dispatch

**Definition of Done:**
- Local mode boots without Neo4j
- Knowledge graph routes either work locally or return explicit 501
- Entity relationships can be stored and queried locally

---

## Gap #2: Local Text-to-Speech (TTS)

| Gap ID | Feature | Current State | Expected Behavior |
|--------|---------|---------------|-------------------|
| GAP-21 | TTS | ElevenLabs API only; no local endpoint | Local TTS synthesis via Piper or Edge-TTS |

| Priority | Implementation | Files Changed | Technical Work | Dependencies |
|----------|----------------|---------------|-----------------|--------------|
| **MEDIUM** | **Option A (Short-term):** Return 501 stub | `routers_local/tts.py`, `routers/tts.py` | Create stub router that returns `{"error": "TTS not available in local mode"}` | Phase 0 first |
| | **Option B (Piper):** Self-contained TTS | `backend/utils/tts/piper_tts.py` | Install Piper models via `pip install piper-tts`, load models into RAM, synthesize speech locally | `pip install piper-tts`, ~100 MB models |
| | **Option C (Edge-TTS):** Free Microsoft service | `backend/utils/tts/edge_tts_client.py` | Use `edge-tts` Python package to call Microsoft's Edge TTS service (no API key required) | `pip install edge-tts` |

**Files to Create:**
- `backend/utils/tts/piper_tts.py` — Piper TTS implementation
- `backend/utils/tts/edge_tts_client.py` — Edge-TTS client
- `backend/utils/tts/router.py` — TTS provider dispatcher

**Files to Modify:**
- `routers_local/tts.py` — Add TTS routes (currently missing)
- `routers/tts.py` — Add provider dispatch

**Piper Implementation Pattern:**
```python
from piper_tts import PiperTTS

class PiperTTS:
    def __init__(self, model_path: str = "/usr/local/lib/piper/models/{lang}"):
        self.tts = PiperTTS(voice=VoiceModel(model_path))
    
    def synthesize(self, text: str, voice: str) -> bytes:
        return self.tts.synthesize(text, voice=voice)
```

**Edge-TTS Implementation Pattern:**
```python
import edge_tts
import asyncio

async def synthesize_edge(text: str, voice: str = "en-US-ChristopherNeural") -> bytes:
    communicator = edge_tts.Communicate(text, voice)
    audio = b""
    async for chunk in communicator.stream(output=None):
        if "audio" in chunk:
            audio += chunk["audio"]
    return audio
```

**Definition of Done:**
- Local TTS endpoint returns audio data
- Multiple voices available (Piper has dozens)
- Streaming synthesis for long text

---

## Gap #3: Redis Fair-Use Tracking

| Gap ID | Feature | Current State | Expected Behavior |
|--------|---------|---------------|-------------------|
| GAP-22 | Fair-use tracking | Redis silently disabled; fail-open | Local usage tracking or documented limitation |

| Priority | Implementation | Files Changed | Technical Work | Dependencies |
|----------|----------------|---------------|-----------------|--------------|
| **MEDIUM** | **Option A:** Document as single-user limitation | `backend/database/redis_db.py`, docs | Add startup warning: `logger.warning("Fair-use tracking disabled in local mode. Suitable for single-user only.")` | Phase 0 first |
| | **Option B:** SQLite-based rate limiting | `backend/database/sql/rate_limits.py` | Implement rolling window counters in SQLite: `CREATE TABLE usage_stats (user_id TEXT, window_start INTEGER, usage_count INTEGER, CHECK (window_start > (SELECT MAX(window_start) FROM usage_stats)))` | Phase 6 SQL first |
| | **Option C:** Memory-based tracking | `backend/cache/local_cache.py` | Use Python `collections.deque` or `heapq` for rolling window, persist to SQLite on shutdown | None | |

**SQLite Rate Limit Implementation:**
```python
from sqlalchemy import text

def record_usage(db, user_id: str, usage: int):
    with db Session() as session:
        session.execute(text("""
            INSERT OR REPLACE INTO usage_stats
            (user_id, window_start, usage_count)
            VALUES (:user_id, datetime('now', 'start of day'), :usage)
        """), {"user_id": user_id, "usage": usage})
        session.commit()

def get_remaining_quota(user_id: str, daily_limit: int = 100) -> int:
    with db Session() as session:
        result = session.execute(text("""
            SELECT COALESCE(SUM(usage_count), 0) as used
            FROM usage_stats
            WHERE user_id = :user_id
              AND window_start > datetime('now', '-1 day')
        """), {"user_id": user_id})
        used = result.scalar()
        return daily_limit - used
```

**Definition of Done:**
- Local mode either tracks usage or explicitly documents limitation
- No silent failures (Redis fail-open should be replaced with explicit check)
- Single-user local deployments can proceed without Redis

---

## Gap #4: SQLite Encryption (Security)

| Gap ID | Feature | Current State | Expected Behavior |
|--------|---------|---------------|-------------------|
| GAP-19 | SQLite encryption | Plaintext storage | Optional AES-256-GCM encryption at rest |

| Priority | Implementation | Files Changed | Technical Work | Dependencies |
|----------|----------------|---------------|-----------------|--------------|
| **MEDIUM** | **Option A (Simple):** File permissions | `omi_local.py`, `main_local.py` | `os.chomp(omi_local.db, 0o600)` on every write, ensure SQLite file is in a `.local` directory | None |
| | **Option B (Advanced):** SQLCipher | `backend/database/sql/db.py` | Use SQLCipher extension: `pip install pysqlcipher3`, enable `PRAGMA key='...'` on connection | Additional Python package |
| | **Option C (Custom):** Column-level encryption | `backend/database/sql/repository.py`, `backend/database/sql/models.py` | Use `TypeDecorator` or SQLAlchemy event listener to encrypt `text`/`content` columns before insert | `pycryptodome` | |

**File Permissions Approach:**
```python
import os

def ensure_secure_file(path: str):
    """Ensure SQLite file is only readable by owner."""
    os.chmod(path, 0o600)

# In main_local.py startup
db_path = os.environ.get("SQLITE_PATH", "./omi_local.db")
ensure_secure_file(db_path)

# After each write operation
with engine.connect() as conn:
    # ... write operations ...
ensure_secure_file(db_path)  # Re-apply permissions
```

**SQLCipher Approach:**
```python
from sqlalchemy import create_engine

def create_encrypted_engine(db_path: str, encryption_key: str) -> Engine:
    # SQLCipher requires specific SQLite flags
    uri = f"sqlite+aiosqlite:///{db_path}"
    engine = create_engine(uri)
    
    # Initialize SQLCipher with key on first connection
    with engine.connect() as conn:
        conn.execute(text("PRAGMA key = :key; PRAGMA crypto_page_cost = 1;"), {"key": encryption_key})
        conn.execute(text("PRAGMA cipher_mode = 'aes-256-cbc';"))
    
    return engine
```

**Definition of Done:**
- SQLite files are restricted to 0o600 permissions
- Optional SQLCipher for stronger encryption
- Documentation on security implications (local files are still accessible to root)

---

## Gap #5: Conversation Transcription Auto-Persist

| Gap ID | Feature | Current State | Expected Behavior |
|--------|---------|---------------|-------------------|
| GAP-18 | Transcription persistence | Transcript returned but not saved/embedded | Auto-create Conversation, TranscriptSegment, embed to Qdrant |

| Priority | Implementation | Files Changed | Technical Work | Dependencies |
|----------|----------------|---------------|-----------------|--------------|
| **HIGH** | **Feature Flag Approach:** Optional auto-persist | `routers_local/transcribe.py` | After successful transcription, check `AUTO_PERSIST_TRANSCRIPTS=true`:<br>1. `repo.create_conversation()`<br>2. `vdb.upsert_conversation()`<br>3. `repo.create_transcript_segments()` | Phase 6 SQL first |

**Implementation Pattern:**
```python
from settings import settings

async def transcribe_stream_ws(session_id: str, ws: WebSocket):
    # ... transcription logic ...
    
    # Get transcript text after processing
    transcript_text = final_transcript
    
    # Optional: auto-persist if enabled
    if settings.AUTO_PERSIST_TRANSCRIPTS:
        try:
            # Create conversation
            conv_id = await repo.create_conversation(
                uid=user_id,
                title=f"Conversation {session_id[:8]}",
                transcript=transcript_text,
                language=detected_language
            )
            
            # Embed and store in Qdrant
            embedding = get_embeddings_object()(transcript_text)
            await vdb.upsert_conversation(
                uid=user_id,
                id=conv_id,
                text=transcript_text,
                embedding=embedding
            )
            
            # Store transcript segments
            for segment in segments:
                await repo.create_transcript_segment(
                    conversation_id=conv_id,
                    start_time=segment["start"],
                    end_time=segment["end"],
                    text=segment["text"],
                    speaker=segment.get("speaker", "unknown")
                )
            
            # Broadcast completion event
            await events.router.broadcast({
                "type": "transcription_complete",
                "session_id": session_id,
                "conversation_id": conv_id
            })
            
        except Exception as e:
            logger.error(f"Auto-persist failed: {e}")
            # Continue — don't fail the main transcription response
```

**Definition of Done:**
- Transcription endpoint can optionally auto-save conversations
- Manual persist endpoint still exists for explicit control
- Auto-persist respects feature flag

---

## Gap #6: Action Items Router in Local Mode

| Gap ID | Feature | Current State | Expected Behavior |
|--------|---------|---------------|-------------------|
| GAP-17 | Action items CRUD | No HTTP endpoint; only ORM models exist | Full CRUD API for action items in local mode |

| Priority | Implementation | Files Changed | Technical Work | Dependencies |
|----------|----------------|---------------|-----------------|--------------|
| **HIGH** | **Implement CRUD:** Mirror memories.py pattern | `routers_local/action_items.py` | Create routes mirroring `routers_local/memories.py`:<br>- `GET /v1/action-items` — list user's action items<br>- `POST /v1/action-items` — create action item from memory/conversation<br>- `GET /v1/action-items/{id}` — retrieve by ID<br>- `PATCH /v1/action-items/{id}` — update status/notes<br>- `DELETE /v1/action-items/{id}` — delete item | Phase 6 SQL first |

**Implementation Pattern:**
```python
from fastapi import APIRouter, Depends, HTTPException
from database.sql.repository import (
    ActionItemRepository
)
from auth.router_dep import get_current_user_id_local
from settings import settings

router = APIRouter(prefix="/v1")

@router.get("/action-items")
async def list_action_items(
    repo: ActionItemRepository = Depends(get_repo),
    user_id: str = Depends(get_current_user_id_local)
):
    items = repo.get_action_items(user_id)
    return {"items": items}

@router.post("/action-items")
async def create_action_item(
    memory_id: str,
    repo: ActionItemRepository = Depends(get_repo),
    user_id: str = Depends(get_current_user_id_local)
):
    # Extract action items from memory content
    memory = repo.get_memory(user_id, memory_id)
    actions = repo.extract_action_items(memory["content"])
    
    if not actions:
        return HTTPException(status_code=400, detail="No action items detected")
    
    for action in actions:
        repo.create_action_item(
            user_id=user_id,
            memory_id=memory_id,
            description=action["description"],
            priority=action.get("priority", "normal"),
            due_date=action.get("due_date")
        )
    return {"created": len(actions)}

@router.get("/action-items/{item_id}")
async def get_action_item(
    item_id: str,
    repo: ActionItemRepository = Depends(get_repo),
    user_id: str = Depends(get_current_user_id_local)
):
    item = repo.get_action_item(user_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Action item not found")
    return item

@router.patch("/action-items/{item_id}")
async def update_action_item(
    item_id: str,
    body: dict,
    repo: ActionItemRepository = Depends(get_repo),
    user_id: str = Depends(get_current_user_id_local)
):
    item = repo.get_action_item(user_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Action item not found")
    
    if "completed" in body:
        repo.mark_completed(user_id, item_id, body["completed"])
    if "notes" in body:
        repo.add_notes(user_id, item_id, body["notes"])
    
    return repo.get_action_item(user_id, item_id)

@router.delete("/action-items/{item_id}")
async def delete_action_item(
    item_id: str,
    repo: ActionItemRepository = Depends(get_repo),
    user_id: str = Depends(get_current_user_id_local)
):
    repo.delete_action_item(user_id, item_id)
    return {"deleted": item_id}
```

**Register Router in main_local.py:**
```python
if settings.ENABLE_ACTION_ITEMS:
    app.include_router(action_items.router)
```

**Definition of Done:**
- Action items CRUD endpoints functional
- Integration with memory extraction
- Status tracking (pending/in-progress/completed)

---

## Gap #7: Haptic/Button BLE Characteristics

| Gap ID | Feature | Current State | Expected Behavior |
|--------|---------|---------------|-------------------|
| GAP-25 | BLE controls | No subscription to button/haptic characteristics | Subscribe to button state, write haptic patterns |

| Priority | Implementation | Files Changed | Technical Work | Dependencies |
|----------|----------------|---------------|-----------------|--------------|
| **MEDIUM** | **Implement BLE control:** GATT characteristic handling | `pin_bridge/pin_bridge.py` | Subscribe to button characteristic UUID on connection:<br>1. Parse press type (single/double/long)<br>2. Map to API actions (start recording, mark moment, dismiss)<br>Write to haptic characteristic at:<br>1. Transcription complete<br>2. Error conditions<br>3. Notification acknowledged | Phase 0 first |

**Button State Parsing:**
```python
BUTTON_UUID = "23BA7924-1234-5678-9ABC-DEF012345678"
HAPTIC_UUID = "CAB1AB95-…"

async def subscribe_to_buttons():
    """Subscribe to button state notifications."""
    button_service = self.device.services.get_by_uuid("services_uri_for_buttons")
    button_char = button_service.characteristics.get_by_uuid(BUTTON_UUID)
    
    if button_char:
        await button_char.subscribe()
        button_char.on("notification", lambda data: self.handle_button_press(data))

def handle_button_press(self, data: bytes):
    """Parse button press event."""
    # data format: [subtype:1byte][press_type:1byte][timestamp:4bytes]
    if len(data) < 6:
        return
    
    press_type = data[1]
    timestamp = int.from_bytes(data[4:8], "big")
    
    if press_type == 0x01:
        self.start_new_segment()
    elif press_type == 0x02:
        self.mark_moment(timestamp)
    elif press_type == 0x03:
        self.dismiss_notification()
    elif press_type == 0x04:
        self.stop_current_segment()

async def send_haptic_vibration(pattern: list):
    """Write vibration pattern to haptic characteristic."""
    haptic_service = self.device.services.get_by_uuid("services_uri_for_haptics")
    haptic_char = haptic_service.characteristics.get_by_uuid(HAPTIC_UUID)
    
    if haptic_char:
        # pattern format: [duration_ms:2bytes][intensity:1byte]
        encoded = struct.pack(">H", pattern[0]) + bytes([pattern[1]])
        await haptic_char.write(encoded)
```

**Definition of Done:**
- Button press events received and parsed
- Haptic feedback sent to device
- API integration for marking moments

---

## Gap #8: Pin Bridge FrameAssembler Multi-Chunk Fix

| Gap ID | Feature | Current State | Expected Behavior |
|--------|---------|---------------|-------------------|
| GAP-23 | Opus frame handling | Drops multi-chunk frames at low MTU | Accumulate all chunks, emit on frame completion |

| Priority | Implementation | Files Changed | Technical Work | Dependencies |
|----------|----------------|---------------|-----------------|--------------|
| **MEDIUM** | **Fix FrameAssembler:** Emit on new packet_id | `pin_bridge/pin_bridge.py` | Modify emit logic to accumulate chunks:<br>1. On sub_index==0: emit previous frame if exists, clear buffer<br>2. On sub_index==N: append to buffer<br>3. On END event: emit accumulated frame | Phase 0 first |

**Current (buggy) code:**
```python
# Current buggy implementation
if sub_index == 0 and self.current_id is not None:
    self._emit(self.current_id, self.current_buf)
    self.current_buf = bytearray()
# multi-chunk frames lost here
```

**Fixed implementation:**
```python
# Fixed: emit on new packet_id (frame boundary)
def process_notification(self, notification: Notification):
    payload = notification.payload
    
    if payload.sub_index == 0 and self.current_id is not None:
        # Emit the previous completed frame
        self._emit(self.current_id, bytes(self.current_buf))
        self.current_buf = bytearray()
    
    # Check for new frame (new packet_id signals previous frame complete)
    if payload.packet_id and payload.packet_id != self.current_id:
        # Previous frame was completed, emit it if buffer has data
        if self.current_id is not None and len(self.current_buf) > 0:
            self._emit(self.current_id, bytes(self.current_buf))
        
        # Start accumulating new frame
        self.current_id = payload.packet_id
        self.current_buf = bytearray(payload.data)
    elif payload.sub_index > 0:
        # Accumulate additional chunks
        self.current_buf.extend(payload.data)
    
    # END signal: emit final accumulated frame
    if payload.sub_index == 0xFF:  # or whatever END marker is
        if self.current_id is not None and len(self.current_buf) > 0:
            self._emit(self.current_id, bytes(self.current_buf))
            self.current_id = None
            self.current_buf = bytearray()
```

**Definition of Done:**
- Multi-chunk frames properly reassembled
- No audio truncation at low MTU
- Backward compatible with single-chunk frames

---

## Gap #9: Offline SD Card Drain

| Gap ID | Feature | Current State | Expected Behavior |
|--------|---------|---------------|-------------------|
| GAP-24 | Offline storage | Not implemented; audio ignored when offline | Drain offline audio from SD card on reconnect |

| Priority | Implementation | Files Changed | Technical Work | Dependencies |
|----------|----------------|---------------|-----------------|--------------|
| **MEDIUM** | **Implement drain:** GATT storage protocol | `pin_offline_drain.py` (new), `pin_bridge.py` | Implement full multi-file GATT storage protocol:<br>1. CMD_LIST_FILES (0x10) → enumerate offline files<br>2. CMD_READ_FILE (0x11) → stream each file with 1-byte ack<br>3. `_parse_audio_chunk()` → decode `[size:1][opus_data]*` format<br>4. Feed decoded frames into live `send_queue` | Phase 0 first |

**Implementation:**
```python
# pin_bridge/pin_offline_drain.py

import struct
from typing import AsyncIterator, List
from pin_bridge import send_queue

async def drain_offline_storage(device: BLEDevice) -> AsyncIterator[bytes]:
    """
    Drain offline audio from SD card over GATT storage service.
    Returns decoded Opus frames to be fed into live transcription queue.
    """
    storage_service = device.services.get_by_uuid("30295780-4301-EABD-2904-2849ADFEAE43")
    
    # Command list files
    files_response = await storage_service.characteristics["0x10"].notify(b"\x10")
    file_count = files_response[0]  # First byte is count
    
    # Iterate over files
    for i in range(file_count):
        # Command read file
        read_cmd = struct.pack(">BH", 0x11, i)  # 0x11 = CMD_READ_FILE, i = file index
        read_response = await storage_service.characteristics["0x11"].notify(read_cmd)
        
        # Parse response: [timestamp:4bytes][size:1byte][opus_data]*[done:0x64]
        timestamp = int.from_bytes(read_response[:4], "big")
        size = read_response[4]
        opus_data = read_response[5:]
        
        if opus_data and opus_data[-1] == 0x64:  # done byte
            # Decode Opus frame and yield
            yield opus_data[:-1]
        else:
            logger.warning(f"File {i} incomplete or corrupted")
    
    logger.info(f"Drained {file_count} offline files")
```

**Integration in pin_bridge.py:**
```python
# In stream_session() method, after haptic write
async def stream_session(self, audio_sink: AudioSink):
    # ... existing session setup ...
    
    # Check if offline storage is enabled
    if getattr(self.config, "enable_offline_storage", False):
        try:
            async for frame in drain_offline_storage(self.device):
                await self.send_queue.put(frame)
        except Exception as e:
            logger.error(f"Offline drain failed: {e}")
    
    # ... enter stop_event.wait() ...
```

**Definition of Done:**
- Offline audio retrieved on reconnect
- Firmware auto-deletion of transferred files confirmed
- Seamless integration with live transcription

---

## Gap #10: CORS Middleware in Local Mode

| Gap ID | Feature | Current State | Expected Behavior |
|--------|---------|---------------|-------------------|
| GAP-16 | CORS | No middleware; browser clients blocked | Enable CORS for local browser testing |

| Priority | Implementation | Files Changed | Technical Work | Dependencies |
|----------|----------------|---------------|-----------------|--------------|
| **HIGH** | **Add CORS middleware:** FastAPI standard | `backend/main_local.py` | Add middleware:<br>`app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)`<br>For production: restrict to known hosts | Phase 0 first |

**Implementation:**
```python
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI

app = FastAPI()

# Local development: allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace with ["http://localhost:3000"] for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Production: restrict origins
# allow_origins=[
#     "http://localhost:3000",
#     "http://localhost:8080",
# ]
```

**Definition of Done:**
- Browser-based clients can call API
- OPTIONS preflight requests succeed
- Credentials can be sent with requests

---

## Gap #11: Startup Health Probes for Ollama/Qdrant

| Gap ID | Feature | Current State | Expected Behavior |
|--------|---------|---------------|-------------------|
| GAP-15 | Health probes | No verification on startup | Probe Ollama/Qdrant at startup, retry if not ready |

| Priority | Implementation | Files Changed | Technical Work | Dependencies |
|----------|----------------|---------------|-----------------|--------------|
| **HIGH** | **Add startup probes:** HTTP health checks | `backend/local_bootstrap.py` | Implement probe functions:<br>1. `probe_ollama()`: GET `/api/version`<br>2. `probe_qdrant()`: GET `/healthz`<br>3. Retry loop with backoff<br>4. Log failures but don't block startup | Phase 0 first |

**Implementation:**
```python
# backend/local_bootstrap.py

import httpx
import asyncio
from typing import Optional

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")

async def probe_ollama(timeout: int = 5, max_retries: int = 3) -> bool:
    """Probe Ollama for readiness."""
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(f"{OLLAMA_HOST}/api/version")
                r.raise_for_status()
                data = r.json()
                logger.info(f"Ollama ready: version {data.get('version', 'unknown')}")
                return True
        except httpx.TimeoutException:
            logger.warning(f"Ollama not ready (attempt {attempt + 1}/{max_retries})")
        except Exception as e:
            logger.warning(f"Ollama probe failed: {e}")
    return False

async def probe_qdrant(timeout: int = 5, max_retries: int = 3) -> bool:
    """Probe Qdrant for readiness."""
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(f"{QDRANT_URL}/healthz")
                r.raise_for_status()
                logger.info("Qdrant healthz check passed")
                return True
        except httpx.TimeoutException:
            logger.warning(f"Qdrant not ready (attempt {attempt + 1}/{max_retries})")
        except Exception as e:
            logger.warning(f"Qdrant probe failed: {e}")
    return False

async def bootstrap_local():
    """Bootstrap local services and database."""
    logger.info("Checking service readiness...")
    
    ollama_ready = await probe_ollama()
    qdrant_ready = await probe_qdrant()
    
    if not ollama_ready:
        logger.warning("Ollama not available. Chat endpoints will fail until it starts.")
    if not qdrant_ready:
        logger.warning("Qdrant not available. Vector operations will fail until it starts.")
    
    # Initialize SQLite
    init_db()
    
    # Create admin user if configured
    if os.getenv("BOOTSTRAP_ADMIN_PASSWORD"):
        create_admin_user()
    
    logger.info("Bootstrap complete")
```

**Definition of Done:**
- Ollama/Qdrant readiness verified on startup
- Clear warning if service unavailable
- Graceful degradation instead of hard failure

---

## Gap #12: Sync-to-Async Conversion for Ollama/Qdrant

| Gap ID | Feature | Current State | Expected Behavior |
|--------|---------|---------------|-------------------|
| GAP-13 | Ollama async | Sync HTTP call blocks event loop | Convert to async with httpx.AsyncClient |
| GAP-14 | Qdrant async | Sync QdrantClient blocks event loop | Wrap in asyncio.to_thread or use async client |

| Priority | Implementation | Files Changed | Technical Work | Dependencies |
|----------|----------------|---------------|-----------------|--------------|
| **HIGH** | **Convert Ollama:** Async HTTP client | `utils/llm/providers/ollama_client.py` | Rewrite sync `chat()` as async:<br>```python<br>async def chat(messages, model):<br>    async with httpx.AsyncClient() as client:<br>        r = await client.post(...) <br>``` | Phase 0 first |
| | **Convert Qdrant:** asyncio.to_thread | `database/vector_db_qdrant.py` | Wrap sync calls:<br>```python<br>results = await asyncio.to_thread( <br>    vdb.search_memories_by_vector, uid, vector, limit<br>)<br>``` | Phase 0 first |

**Ollama Async Implementation:**
```python
# utils/llm/providers/ollama_client.py

import httpx
from typing import AsyncIterator
from utils.llm import router

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "300"))

class OllamaClient:
    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=OLLAMA_HOST,
            timeout=httpx.Timeout(OLLAMA_TIMEOUT)
        )
    
    async def chat(self, messages: list[router.Message]) -> router.ChatResponse:
        """Synchronous-style chat (wrapped in async def)."""
        r = await self.client.post(
            "/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False
            }
        )
        r.raise_for_status()
        return router.ChatResponse(content=r.json()["response"])
    
    async def astream(
        self,
        messages: list[router.Message]
    ) -> AsyncIterator[str]:
        """Streaming chat."""
        async with self.client.stream(
            "POST",
            "/api/generate",
            json={"model": OLLAMA_MODEL, "messages": messages, "stream": True}
        ) as response:
            async for line in response.aiter_lines():
                if line:
                    data = json.loads(line)
                    yield data.get("response", "")
    
    async def generate(self, prompt: str) -> str:
        r = await self.client.post(
            "/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
        )
        return r.json()["response"]
    
    async def extract_actions(self, text: str) -> dict:
        """Extract action items from text using structured output."""
        r = await self.client.post(
            "/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": f"Extract actions from: {text}",
                "format": "json"  # Ollama supports JSON format
            }
        )
        return r.json()

# Singleton
_ollama_client = OllamaClient()

def get_ollama_client() -> OllamaClient:
    return _ollama_client
```

**Qdrant Async Implementation:**
```python
# database/vector_db_qdrant.py

import asyncio
from qdrant_client import QdrantClient

def get_vector_db():
    if get_vector_db_provider() != "qdrant":
        from .vector_db_pinecone import *
        return
    
    client = QdrantClient(url=os.environ.get("QDRANT_URL"))
    
    # Wrap sync calls with asyncio.to_thread
    async def search_memories_by_vector(uid: str, vector: list, limit: int):
        return await asyncio.to_thread(
            lambda: client.search(
                collection_name="memories",
                query_vector=vector,
                limit=limit,
                query_filter=qdrant_filters.get_memory_by_uid(uid)
            )
        )
    
    # Similar for upsert, delete, etc.
```

**Definition of Done:**
- Ollama calls don't block event loop
- Qdrant calls use thread pool
- Concurrent requests work without exhaustion

---

## Gap #13: Auto-Persist Transcription Flag

| Gap ID | Feature | Current State | Expected Behavior |
|--------|---------|---------------|-------------------|
| GAP-18 | Auto-persist | Not implemented; manual calls needed | Configurable auto-persist after transcription |

| Priority | Implementation | Files Changed | Technical Work | Dependencies |
|----------|----------------|---------------|-----------------|--------------|
| **HIGH** | **Feature Flag:** AUTO_PERSIST_TRANSCRIPTS | `routers_local/transcribe.py`, `settings.py` | Add environment flag and conditional logic (see GAP-5 above) | Phase 0 first |

**Settings Addition:**
```python
# settings.py

class Settings(BaseSettings):
    AUTO_PERSIST_TRANSCRIPTS: bool = False  # Default: manual persist
    AUTO_PERSIST_MAX_SEGMENTS: int = 100    # Limit segments to avoid OOM
```

**Definition of Done:**
- Transcription can auto-save conversations
- Flag defaults to False for safety
- Manual persist endpoint still works

---

## Summary Table

| # | Gap | Feature | Priority | Status | Effort | Notes |
|---|-----|---------|----------|--------|--------|-------|
| 1 | GAP-20 | Knowledge graph local impl | MEDIUM | 🟠 Blocked | Large | Option A (501 stub) easiest |
| 2 | GAP-21 | Local TTS (Piper/Edge-TTS) | MEDIUM | 🔵 Not started | Medium | Option A (501) simplest |
| 3 | GAP-22 | Redis fair-use tracking | MEDIUM | 🔵 Not started | Small | Document limitation |
| 4 | GAP-19 | SQLite encryption | MEDIUM | 🔵 Not started | Medium | File permissions easiest |
| 5 | GAP-18 | Auto-persist flag | HIGH | 🟡 Partial | Small | Feature flag only |
| 6 | GAP-17 | Action items router | HIGH | 🔵 Not started | Small | Mirror memories.py |
| 7 | GAP-25 | BLE haptic/button | MEDIUM | 🔵 Not started | Small | GATT subscription |
| 8 | GAP-23 | FrameAssembler fix | MEDIUM | 🔵 Not started | Small | Emit on new packet_id |
| 9 | GAP-24 | SD card drain | MEDIUM | 🟡 Ready | Large | Code exists, integrate |
| 10 | GAP-16 | CORS middleware | HIGH | 🔵 Not started | Trivial | Add middleware |
| 11 | GAP-15 | Startup probes | HIGH | 🔵 Not started | Small | local_bootstrap.py |
| 12 | GAP-13 | Async Ollama | HIGH | 🟡 Ready | Small | Convert to async |
| 13 | GAP-14 | Async Qdrant | HIGH | 🔵 Not started | Small | asyncio.to_thread |
| 14 | GAP-26 | opus brew install | LOW | 🔵 Not started | Trivial | Doc update |
| 15 | GAP-27 | .env.template local block | LOW | 🔵 Not started | Trivial | Add local defaults |
| 16 | GAP-28 | oauth.py gating | LOW | 🔵 Not started | Trivial | Feature flag |

**Legend:**
- 🔵 Not started — No code exists, requires implementation
- 🟡 Ready — Code exists, needs integration/wiring
- 🟠 Blocked — Requires architecture decision or external dependency

---

## Implementation Sequencing

### Week 1: Unblock Current Entrypoint

1. **GAP-16 (CORS)** — 30 mins
2. **GAP-15 (startup probes)** — 1 hour
3. **GAP-13 (async Ollama)** — 1 hour
4. **GAP-14 (async Qdrant)** — 1 hour
5. **GAP-17 (action items router)** — 2 hours

### Week 2: Make main.py Local-Compatible

1. **GAP-1, 7, 8 (Firebase guards)** — 2 hours
2. **GAP-4, 5 (LLM/embeddings router)** — 1 hour
3. **GAP-2 (vector_db dispatcher)** — 1 hour
4. **GAP-9, 11, 12 (Stripe/Typesense guards)** — 1 hour

### Week 3: Complete Data Layer

1. **GAP-3 (Firestore→SQL dispatch)** — 4 hours
2. **GAP-6 (STT routing)** — 3 hours
3. **GAP-10 (Pusher→events)** — 2 hours
4. **GAP-18 (auto-persist)** — 1 hour

### Week 4: Optional Features

1. **GAP-19 (SQLite encryption)** — 2 hours
2. **GAP-20 (knowledge graph)** — 4 hours or document
3. **GAP-21 (TTS)** — 3 hours or document
4. **GAP-22 (fair-use)** — 1 hour
5. **GAP-23 (FrameAssembler)** — 1 hour
6. **GAP-25 (BLE controls)** — 2 hours
7. **GAP-26, 27, 28 (docs)** — 1 hour

---

## Local vs Cloud Configurability Matrix

| Subsystem | Cloud Default | Local Target | Env Var |
|-----------|---------------|--------------|---------|
| LLM | OpenAI | Ollama | `LLM_PROVIDER=ollama` |
| Embeddings | OpenAI | sentence-transformers | `EMBEDDINGS_PROVIDER=local` |
| Vector DB | Pinecone | Qdrant | `VECTOR_DB_PROVIDER=qdrant` |
| STT | Deepgram | faster-whisper | `STT_PROVIDER=local` |
| Auth | Firebase | JWT | `AUTH_PROVIDER=local` |
| DB | Firestore | SQLite | `DB_PROVIDER=sqlite` |
| Events | Pusher | WebSockets | `EVENT_PROVIDER=websocket` |
| Search | Typesense | Disabled/FTS5 | `SEARCH_PROVIDER=disabled` |
| Diarization | Deepgram | Single-speaker | `ENABLE_DIARIZATION=false` |

**Feature Flags:**
```env
# Disable non-core cloud features
ENABLE_STRIPE=false
ENABLE_MIXPANEL=false
ENABLE_HUME=false
ENABLE_PERPLEXITY=false
ENABLE_LANGSMITH=false
ENABLE_PUSHER_HOSTED=false
ENABLE_MODAL=false
ENABLE_GITHUB=false
ENABLE_WHOOP_OAUTH=false
ENABLE_NOTION_OAUTH=false
ENABLE_GOOGLE_OAUTH=false
ENABLE_TWITTER_OAUTH=false
ENABLE_TYPESENSE=false
ENABLE_KNOWLEDGE_GRAPH=false
```

---

## Definition of Done for Complete Local Mode

All of the following must be true:

- ✅ App boots without cloud credentials
- ✅ All core endpoints work locally
- ✅ Audio ingestion → transcription → storage → retrieval works end-to-end
- ✅ No runtime dependency on Firebase/OpenAI/Deepgram/Pinecone/Pusher/Typesense
- ✅ WebSocket events broadcast to connected clients
- ✅ Action items CRUD functional
- ✅ Knowledge graph either works or returns explicit 501
- ✅ TTS endpoint functional or documented limitation
- ✅ SQLite file has appropriate permissions
- ✅ Startup probes verify services
- ✅ CORS enabled for browser clients
- ✅ Async handlers prevent event loop blockage
- ✅ Auto-persist optional and documented

---

## File Inventory for Cutover Work

### Files to Create

```
backend/
├── database/
│   └── knowledge_graph_local.py  (GAP-20)
├── utils/
│   ├── tts/
│   │   ├── piper_tts.py          (GAP-21)
│   │   ├── edge_tts_client.py    (GAP-21)
│   │   └── router.py             (GAP-21)
│   └── cache/
│       └── local_cache.py        (GAP-22)
└── scripts/
    └── reindex_local_vectors.py  (helper for GAP-3)

pin_bridge/
├── pin_offline_drain.py          (GAP-24)
└── pin_bridge.py (modify)        (GAP-23, GAP-25)
```

### Files to Modify

```
backend/
├── main.py                        (GAP-1, GAP-9, GAP-12)
├── main_local.py                  (GAP-16, GAP-15)
├── local_bootstrap.py             (GAP-15, GAP-18)
├── dependencies.py                (GAP-7)
├── providers.py                   (Phase 0)
├── feature_flags.py               (Phase 0)
├── routers/
│   ├── auth.py                    (GAP-7, GAP-8)
│   ├── oauth.py                   (GAP-28)
│   ├── knowledge_graph.py         (GAP-20)
│   ├── tts.py                     (GAP-21)
│   └── transcribe.py              (GAP-6, GAP-18)
├── utils/
│   ├── llm/
│   │   ├── clients.py             (GAP-4, GAP-5, GAP-13)
│   │   ├── router.py              (GAP-4, GAP-5)
│   │   └── providers/
│   │       ├── ollama_client.py   (GAP-4, GAP-13)
│   │       └── openai_client.py   (GAP-4, GAP-5)
│   ├── embeddings/
│   │   ├── router.py              (GAP-5)
│   │   ├── local_embeddings.py    (GAP-5)
│   │   └── openai_embeddings.py   (GAP-5)
│   └── stt/
│       ├── local_vad.py           (GAP-4)
│       └── providers/
│           ├── router.py          (GAP-6)
│           ├── local_whisper_prerecorded.py (GAP-6)
│           ├── local_streaming.py (GAP-6)
│           ├── deepgram_prerecorded.py (GAP-6)
│           └── deepgram_streaming.py (GAP-6)
└── database/
    ├── vector_db.py               (GAP-2)
    ├── vector_db_qdrant.py        (GAP-14)
    ├── vector_db_pinecone.py      (GAP-2)
    ├── sql/
    │   ├── repository.py          (GAP-3, GAP-6)
    │   └── rate_limits.py         (GAP-22)
    └── redis_db.py                (GAP-22)

pin_bridge/
└── pin_bridge.py                  (GAP-23, GAP-24, GAP-25)
```

### Files to Document as Limitations

```
GAPS.md                            (update with new status)
SETUP_FROM_SCRATCH.md              (add GAP-26, GAP-27, GAP-28)
```

---

## Testing Strategy

### Per-Phase Tests

```bash
# Phase 0: Provider resolver
pytest tests/unit/test_providers.py

# Phase 1: LLM routing
pytest tests/unit/test_llm_router.py
pytest tests/integration/test_chat_local.py

# Phase 2: Embeddings routing
pytest tests/unit/test_embeddings_router.py

# Phase 3: Vector DB routing
pytest tests/unit/test_vector_db_router.py

# Phase 4: STT routing
pytest tests/unit/test_stt_router.py
pytest tests/integration/test_transcribe_local.py

# Phase 5: VAD
pytest tests/unit/test_local_vad.py

# Phase 6: SQL repository
pytest tests/unit/test_sql_repository.py
pytest tests/integration/test_sql_persistence.py

# Phase 7: Auth
pytest tests/unit/test_local_auth.py
pytest tests/integration/test_auth_flow.py

# Phase 8: Events
pytest tests/unit/test_connection_manager.py
pytest tests/integration/test_websocket_broadcast.py

# Phase 9: Search
pytest tests/unit/test_local_search.py

# Full stack
pytest tests/e2e/
```

### Smoke Test Updates

Update `backend/scripts/local_smoke.py` to test:

1. Register/login flow
2. Transcribe prerecorded audio
3. Create conversation via auto-persist
4. Search memories
5. Chat with Ollama
6. WebSocket broadcast
7. Action items CRUD

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Embedding dimension mismatch | Validate Qdrant collection dim on startup; add reindex script |
| Ollama no function calling | Gate tool-calling features or add JSON-mode wrapper |
| Whisper transcript shape mismatch | Normalize output in adapter layer |
| SQLite write contention | Document `--workers 1` requirement or migrate to Postgres |
| WebSocket cross-worker fan-out | Document limitation; add Redis Pub/Sub if needed |
| Torch install slow | Use prebuilt wheel; document as expected |

---

## Conclusion

This specification provides a complete, actionable plan for implementing all 28 local-only features. The implementation follows the project's established patterns (provider abstraction, environment-driven routing, feature flags) and prioritizes unblocking the current entrypoint before completing optional features.

**Next Steps:**

1. Review this specification with the team
2. Prioritize gaps based on current needs
3. Begin with Week 1 tasks (CORS, probes, async conversion)
4. Create tasks for each gap in project management tool
5. Implement and test incrementally

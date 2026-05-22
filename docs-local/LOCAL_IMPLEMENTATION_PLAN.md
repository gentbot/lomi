# Local Feature Implementation Plan

This document is the authoritative technical specification for implementing every Omi feature that is currently absent or only partially working in local mode. Each feature section includes what it does, how it should behave locally, and a precise technical breakdown of the work required.

Features are grouped by the infrastructure they share, because several groups should be implemented together. The document ends with features that genuinely cannot be implemented locally, with exhaustive explanations of why.

All implementations must follow the existing local/cloud configurability pattern: new capabilities are controlled by env vars read through `providers.py`, live in `routers_local/` or `utils/`, and are wired only through `main_local.py`. Nothing in `main.py` (the cloud entry point) is to be touched.

---

## Infrastructure Baseline (Read Before Implementing Anything)

Before writing any new code, understand what already exists:

| What | Where | Status |
|------|-------|--------|
| WebSocket broadcast to a user | `events/connection_manager.py` → `manager.send_to_user(uid, msg)` | **Built** |
| Push event router (websocket/pusher) | `events/router.py` → `push_event(uid, event)` | **Built** |
| Conversation vector search | `database/vector_db_qdrant.py` → `query_vectors(uid, vector, limit)` | **Built** |
| Memory vector search + dedup | `vector_db_qdrant.py` → `search_memories_by_vector`, `check_memory_duplicate` | **Built** |
| Action item vector search | `vector_db_qdrant.py` → `search_action_items_by_vector` | **Built** |
| Memory creation | `database/sql/repository.py` → `create_memory(user_id, content, category)` | **Built** |
| Action item creation | `repository.py` → `create_action_item(user_id, description, ...)` | **Built** |
| LLM router (Ollama/OpenAI) | `utils/llm/router.py` → `achat(messages)`, `astream(messages)` | **Built** |
| Conversation update | `repository.py` | **Missing — must be added** |
| `TTS_PROVIDER` in providers.py | `providers.py` | **Missing — must be added** |
| Goal, Persona, AgentSession models | `database/sql/models.py` | **Missing — must be added** |

---

## Group A — Post-Processing Pipeline

These four features share a single background job that runs after every conversation ends. Implement them together as one pipeline rather than four separate hooks.

### A.1 Automatic Conversation Summarization and Categorization

**What the cloud does:**
Within seconds of a conversation ending, GPT-4 reads the full transcript and generates a meaningful title (not a text truncation), a 2–3 sentence overview, an inferred category (`meeting`, `learning`, `personal`, `task`, `health`, `finance`, `social`, `other`), and a list of action items. This structured data is written back to the conversation record and is what the mobile app displays in the conversation list.

**What happens locally today:**
`_finalize()` in `listen.py` saves the conversation immediately with `title = transcript[:80]`, `overview = transcript[:500]`, `category = "other"`, `action_items = []`. No LLM is called.

**How it should work locally:**
After the conversation is saved to SQLite, a non-blocking background task is launched that calls Ollama with the full transcript and a structured prompt requesting JSON output. When Ollama responds, the conversation record is updated. If Ollama is unavailable or returns malformed output, the original mechanical values remain — the conversation is never lost due to post-processing failure.

The conversation should carry a `status` field: `completed` immediately (so the API can return it), then `processed` after the LLM step completes.

**Config env var:** `AUTO_PROCESS_CONVERSATIONS` — default `true`. Set to `false` to skip all LLM post-processing (useful if Ollama is not running).

---

**Technical Work:**

**1. Add `update_conversation()` to `database/sql/repository.py`**

```python
def update_conversation(
    conversation_id: str,
    *,
    title: Optional[str] = None,
    structured: Optional[dict] = None,
    status: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    with session_scope() as session:
        conv = session.query(Conversation).filter(
            Conversation.id == conversation_id
        ).first()
        if conv is None:
            return None
        if title is not None:
            conv.title = title
        if structured is not None:
            conv.structured = structured
        if status is not None:
            conv.status = status
        session.flush()
        return _to_dict(conv)
```

**2. Create `utils/llm/post_process.py`** — new file

```python
"""Post-session LLM processing: summarization, categorization, extraction."""

import json
import logging
from typing import Optional

from utils.llm import router as llm_router

logger = logging.getLogger(__name__)

_PROCESS_PROMPT = """You are processing an audio transcript. Respond ONLY with a single valid JSON object — no markdown, no explanation.

Return exactly this structure:
{{
  "title": "concise title under 80 characters",
  "overview": "2-3 sentence summary of what was discussed",
  "category": "<one of: meeting, learning, personal, task, health, finance, social, other>",
  "action_items": [
    {{"text": "action item description", "due_date": null}}
  ],
  "memories": [
    {{"content": "discrete memorable fact", "category": "<one of: personal, professional, health, financial, social, other>"}}
  ]
}}

Transcript:
{transcript}"""


async def process_conversation(transcript: str) -> Optional[dict]:
    """Call Ollama and return structured post-processing result, or None on failure."""
    if not transcript or not transcript.strip():
        return None
    prompt = _PROCESS_PROMPT.format(transcript=transcript[:6000])
    try:
        raw = await llm_router.achat([
            {"role": "system", "content": "You output only valid JSON. No markdown fences, no extra text."},
            {"role": "user", "content": prompt},
        ])
        return json.loads(raw.strip().strip("```json").strip("```").strip())
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("post_process failed: %s", exc)
        return None
```

Key points:
- Truncate transcript to 6000 characters before sending (prevents timeouts on very long sessions with small models)
- System prompt explicitly forbids markdown fences (Ollama models sometimes add them)
- Return `None` on any failure — callers must treat `None` as "keep existing values"
- Single LLM call returns summary + memories + action items together (fewer round-trips)

**3. Update `routers_local/listen.py`**

After `repository.create_conversation(...)` in `_finalize()`, add:

```python
if os.environ.get("AUTO_PROCESS_CONVERSATIONS", "true").lower() in ("1", "true", "yes"):
    asyncio.create_task(
        _post_process(conv["id"], user_id, full_text)
    )
```

Add the `_post_process` coroutine to `listen.py`:

```python
async def _post_process(conv_id: str, uid: str, transcript: str) -> None:
    from utils.llm.post_process import process_conversation
    result = await process_conversation(transcript)
    if result is None:
        return
    structured = {
        "title": result.get("title", transcript[:80]),
        "overview": result.get("overview", transcript[:500]),
        "action_items": result.get("action_items", []),
        "category": result.get("category", "other"),
    }
    await asyncio.to_thread(
        repository.update_conversation,
        conv_id,
        title=structured["title"],
        structured=structured,
        status="processed",
    )
    # Emit updated conversation event so connected clients get the enriched data.
    from events.router import push_event
    await push_event(uid, {
        "type": "conversation_updated",
        "conversation_id": conv_id,
        "structured": structured,
    })
    # Memory and action item extraction runs from the same result.
    await _extract_memories(uid, result.get("memories", []))
    await _extract_action_items(uid, conv_id, result.get("action_items", []))
    logger.info("Post-processed conversation %s", conv_id)
```

**4. Update `routers_local/sync.py`**

Apply the same `asyncio.create_task(_post_process(...))` pattern at the end of `_process_job()` after `repository.create_conversation(...)`.

---

### A.2 Automatic Memory Extraction

**What the cloud does:**
GPT-4 extracts discrete learnable facts from each conversation — not summaries, but specific facts ("prefers async communication", "allergic to penicillin", "working on a Rust compiler"). These are stored as memory records, vectorized, and used as context in RAG chat.

**How it should work locally:**
Memory extraction is part of the same `_post_process` task defined in A.1. The combined LLM prompt already requests a `memories` array. The extracted items are stored via `repository.create_memory()` and vectorized via `vdb.upsert_memory_vector()`. Before inserting, `vdb.check_memory_duplicate()` is called to skip near-duplicate facts (already implemented in `vector_db_qdrant.py`).

**Config env var:** `AUTO_EXTRACT_MEMORIES` — default `true`. Evaluated only when `AUTO_PROCESS_CONVERSATIONS=true`.

**Technical Work:**

Add `_extract_memories` coroutine (called from `_post_process` in A.1):

```python
async def _extract_memories(uid: str, memories: list) -> None:
    if not memories or os.environ.get("AUTO_EXTRACT_MEMORIES", "true").lower() not in ("1", "true", "yes"):
        return
    from events.router import push_event
    for item in memories:
        content = (item.get("content") or "").strip()
        if not content:
            continue
        # Skip near-duplicates (threshold 0.85 cosine similarity)
        try:
            dup = await asyncio.to_thread(vdb.check_memory_duplicate, uid, content)
            if dup:
                continue
        except Exception:
            pass
        mem = await asyncio.to_thread(
            repository.create_memory,
            uid,
            content=content,
            category=item.get("category", "other"),
        )
        try:
            await asyncio.to_thread(vdb.upsert_memory_vector, uid, mem["id"], content)
        except Exception:
            pass
        await push_event(uid, {"type": "new_memory_created", "memory": mem})
```

The `push_event` call is what enables real-time memory pop-ups in connected clients (see Group B). The event system is already built — this is the only call site missing.

---

### A.3 Automatic Action Item Extraction

**What the cloud does:**
The LLM identifies tasks mentioned in conversation ("I need to send the report by Friday", "remind me to call the doctor") and creates structured action item records.

**How it should work locally:**
Action items come from the same combined LLM call in A.1 (the `action_items` array in the response). They are stored via `repository.create_action_item()`.

**Technical Work:**

Add `_extract_action_items` coroutine (called from `_post_process`):

```python
async def _extract_action_items(uid: str, conv_id: str, items: list) -> None:
    for item in items:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        await asyncio.to_thread(
            repository.create_action_item,
            uid,
            description=text,
            conversation_id=conv_id,
        )
```

No deduplication needed here — action items are transient and multiple similar tasks are valid.

---

### A.4 Goal Extraction

**What the cloud does:**
The LLM identifies goals and aspirations ("I want to run a marathon", "planning to learn Spanish") and tracks them over time, linking future conversation mentions back to the original goal.

**How it should work locally:**
Goal extraction is a separate LLM pass (goals are structurally different from memories — they represent intent rather than fact and need progress tracking). Goals require a new database table and endpoints.

Basic implementation: extract and store goals. Progress tracking (matching future mentions to existing goals) is a follow-on enhancement.

**Config env var:** `AUTO_EXTRACT_GOALS` — default `false` (off by default because it requires a second LLM call and not all Ollama models handle it well).

**Technical Work:**

**1. Add `Goal` model to `database/sql/models.py`**

```python
class Goal(Base):
    __tablename__ = "goals"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, default="active", nullable=False)  # active | completed | abandoned
    source_conversation_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    extra = Column(JSON, default=dict, nullable=False)

    user = relationship("User", back_populates="goals")
```

Add `goals = relationship("Goal", back_populates="user", cascade="all, delete-orphan")` to the `User` model.

**2. Add `create_goal()`, `list_goals()`, `update_goal()` to `repository.py`** — following the same pattern as `create_memory()`.

**3. Add a goal extraction prompt to `utils/llm/post_process.py`**

```python
_GOALS_PROMPT = """Extract any goals or intentions from this transcript.
Return only JSON array: [{{"title": "short goal", "description": "context"}}]
Return empty array [] if no goals are mentioned.
Transcript: {transcript}"""

async def extract_goals(transcript: str) -> list:
    try:
        raw = await llm_router.achat([
            {"role": "system", "content": "Output only valid JSON arrays."},
            {"role": "user", "content": _GOALS_PROMPT.format(transcript=transcript[:4000])},
        ])
        return json.loads(raw.strip().strip("```json").strip("```").strip())
    except Exception:
        return []
```

**4. Create `routers_local/goals.py`**

```
GET  /v1/goals           — list all goals for user
POST /v1/goals           — create a goal manually
PATCH /v1/goals/{id}     — update status (complete, abandon)
DELETE /v1/goals/{id}    — delete
```

**5. Register router in `main_local.py`**

**6. Add to `_post_process` in `listen.py`** (only when `AUTO_EXTRACT_GOALS=true`):

```python
if os.environ.get("AUTO_EXTRACT_GOALS", "false").lower() in ("1", "true", "yes"):
    goals = await extract_goals(transcript)
    for g in goals:
        await asyncio.to_thread(
            repository.create_goal, uid,
            title=g.get("title", ""),
            description=g.get("description"),
            source_conversation_id=conv_id,
        )
```

---

### A.5 Daily and Weekly Summaries

**What the cloud does:**
A Modal cron job runs nightly, queries the last 24 hours of conversations for each user, calls GPT-4 to write a digest, and stores the result. A weekly version runs on Sunday.

**How it should work locally:**
APScheduler (a pure-Python async scheduler) runs inside the FastAPI process. At a configurable time each day it queries SQLite for recent conversations, calls Ollama, and stores the summary. Summaries are accessible via a new endpoint.

**Config env vars:**
- `ENABLE_DAILY_SUMMARIES` — default `false`
- `SUMMARY_HOUR` — default `0` (midnight local time)
- `ENABLE_WEEKLY_SUMMARIES` — default `false`

**Technical Work:**

**1. Add dependency:** `pip install apscheduler` (add to `requirements.txt`)

**2. Add `Summary` model to `models.py`**

```python
class Summary(Base):
    __tablename__ = "summaries"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    period = Column(String, nullable=False)  # "daily" | "weekly"
    date = Column(String, nullable=False, index=True)  # "2026-05-07"
    content = Column(Text, nullable=False)
    conversation_ids = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    user = relationship("User", back_populates="summaries")
```

Add `summaries` relationship to `User`.

**3. Create `utils/summary/scheduler.py`**

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

async def run_daily_summary():
    users = repository.list_all_users()
    for user in users:
        convs = repository.list_conversations_since(user["id"], hours=24)
        if not convs:
            continue
        combined = "\n\n".join(
            f"[{c['title']}]: " + " ".join(
                s["text"] for s in (c.get("transcript_segments") or [])
            )
            for c in convs
        )
        result = await llm_router.achat([{
            "role": "user",
            "content": f"Write a brief daily summary of these conversations:\n{combined[:8000]}"
        }])
        repository.create_summary(user["id"], period="daily", content=result,
                                   conversation_ids=[c["id"] for c in convs])
```

**4. Add `list_conversations_since(user_id, hours)` to `repository.py`** — queries conversations with `created_at >= now - timedelta(hours=hours)`.

**5. Add `create_summary()` and `list_summaries()` to `repository.py`**

**6. Create `routers_local/summaries.py`**

```
GET /v1/summaries?period=daily&limit=7  — list recent summaries
```

**7. Wire scheduler into `main_local.py`**

```python
from utils.summary.scheduler import run_daily_summary

if os.environ.get("ENABLE_DAILY_SUMMARIES", "false").lower() in ("1","true","yes"):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(run_daily_summary, 'cron',
                       hour=int(os.environ.get("SUMMARY_HOUR", "0")))
    _scheduler.start()
```

**8. Register `summaries` router in `main_local.py`**

---

## Group B — Real-time WebSocket Events

**Critical finding:** The event infrastructure is fully built. `events/router.py` exports `push_event(user_id, event)` which routes to `ConnectionManager.send_to_user()` when `EVENT_PROVIDER=websocket`. The `/ws` endpoint in `ws.py` is wired to this manager. **All that is missing is calling `push_event` at the right moments.**

### B.1 New Memory Events

**What the cloud does:**
When a memory is created (during or after a session), the mobile app receives a `new_memory_created` WebSocket event and displays a pop-up notification in real time.

**How it should work locally:**
When `repository.create_memory()` is called — whether from the automatic pipeline (A.2) or from a manual `POST /v3/memories` API call — `push_event` is called immediately after.

**Technical Work:**

The automatic path is already handled in `_extract_memories` in A.2. For the manual path:

In `routers_local/memories.py`, find the `POST /v3/memories` handler and add after `repository.create_memory()`:

```python
from events.router import push_event
asyncio.create_task(push_event(user_id, {"type": "new_memory_created", "memory": mem}))
```

**Total new code: ~3 lines.** The rest of the infrastructure was already built.

### B.2 Conversation Updated Events

Already handled in the `_post_process` task in A.1. When post-processing completes, a `conversation_updated` event is sent to the user so any connected client can refresh the conversation display without polling.

### B.3 Action Item Created Events

In `_extract_action_items` (A.3), add after `repository.create_action_item()`:

```python
await push_event(uid, {"type": "new_action_item", "action_item": item})
```

---

## Group C — Semantic Search Endpoint

**What the cloud does:**
Full semantic search over conversations and memories, surfaced in the app UI via a search bar.

**Current local state:**
All conversations are vectorized on save (`vdb.upsert_conversation_text_vector` is called in `_finalize()`). The Qdrant search functions `query_vectors` and `search_memories_by_vector` are fully implemented in `vector_db_qdrant.py`. **There is no HTTP endpoint exposing this.**

**How it should work locally:**
A `POST /v1/search` endpoint accepts a free-text query and returns ranked results from both conversations and memories. The query is embedded using the local embeddings model (same model used for indexing), then Qdrant is queried.

**Technical Work:**

**1. Create `routers_local/search.py`** — new file

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List

from auth.router_dep import get_current_user_id_local
from database import vector_db_qdrant as vdb
from database.sql import repository

router = APIRouter(prefix="/v1/search", tags=["search"])

class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    include_memories: bool = True
    include_conversations: bool = True

class SearchResult(BaseModel):
    type: str           # "conversation" | "memory"
    id: str
    score: float
    title: str
    snippet: str

@router.post("", response_model=List[SearchResult])
async def search(req: SearchRequest, user_id: str = Depends(get_current_user_id_local)):
    results = []

    if req.include_conversations:
        conv_ids = await asyncio.to_thread(
            vdb.query_vectors, user_id, req.query, limit=req.limit
        )
        for entry in conv_ids:
            cid = entry["id"] if isinstance(entry, dict) else entry
            score = entry.get("score", 0.0) if isinstance(entry, dict) else 0.0
            conv = repository.get_conversation(user_id, cid)
            if conv:
                results.append(SearchResult(
                    type="conversation", id=cid, score=score,
                    title=conv.get("title") or "(untitled)",
                    snippet=" ".join(
                        s["text"] for s in (conv.get("transcript_segments") or [])
                    )[:200],
                ))

    if req.include_memories:
        mem_ids = await asyncio.to_thread(
            vdb.search_memories_by_vector, user_id, req.query, limit=req.limit
        )
        for entry in (mem_ids or []):
            mid = entry["id"] if isinstance(entry, dict) else entry
            score = entry.get("score", 0.0) if isinstance(entry, dict) else 0.0
            # fetch memory text from repository
            # (need list_memories or get_memory — verify repository API)
            results.append(SearchResult(
                type="memory", id=mid, score=score,
                title="Memory", snippet=str(mid),
            ))

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:req.limit]
```

**2. Add `get_memory(user_id, memory_id)` to `repository.py`** — needed to fetch memory text for search results.

**3. Verify `query_vectors` signature in `vector_db_qdrant.py`** — it accepts either a query string or a pre-computed vector. If it only accepts a vector, add a `search_conversations_by_text(uid, query, limit)` wrapper that calls `_embed_query(query)` then `query_vectors`.

**4. Register `search` router in `main_local.py`**

**5. Add `SEARCH_PROVIDER=local` to `.env.reference`** — this is already a valid value in `providers.py` (`get_search_provider()` accepts `local`), just not documented.

---

## Group D — Conversation Silence Timeout

**What the cloud does:**
After `conversation_timeout` seconds of silence (no audio arriving), the current conversation is closed and a new one begins. The WebSocket stays open. Long recording sessions are automatically broken into meaningful chunks.

**Current state:**
`conversation_timeout: int = 120` is already a query parameter of the `/v4/listen` WebSocket endpoint. It is accepted but never used.

**How it should work locally:**
A background watchdog task tracks the timestamp of the last received audio frame. When `conversation_timeout` seconds pass without audio, the watchdog finalizes the current conversation, resets session state, and starts a fresh STT session — all without closing the WebSocket.

**Technical Work:**

In `routers_local/listen.py`, inside `local_listen`, after `needs_opus_decode = ...`:

```python
last_audio_at: float = 0.0  # nonlocal, updated on each audio frame
```

Add a watchdog task that starts alongside the main loop:

```python
async def _silence_watchdog() -> None:
    nonlocal session_id, accumulated_segments, last_audio_at
    if conversation_timeout <= 0:
        return
    while True:
        await asyncio.sleep(5)
        if last_audio_at == 0.0:
            continue
        if time.monotonic() - last_audio_at >= conversation_timeout:
            logger.info("Silence timeout (%ds) — finalizing conversation and resetting session", conversation_timeout)
            final = await local_streaming.end_stream(session_id)
            if final and not accumulated_segments:
                await _on_partial(final)
            await _finalize()
            # Reset for the next conversation.
            accumulated_segments = []
            session_id = uuid.uuid4().hex
            last_audio_at = 0.0
            await local_streaming.start_stream(session_id, on_partial=_on_partial, sample_rate=16000)
```

Update the audio receive loop to set `last_audio_at = time.monotonic()` when audio arrives.

Launch the watchdog as a task before the main loop:

```python
watchdog = asyncio.create_task(_silence_watchdog())
try:
    while True:
        # ... existing loop ...
finally:
    watchdog.cancel()
    # ... existing finally block ...
```

**Add `import time` to `listen.py`** — currently missing.

**No new config needed** — `conversation_timeout` is already a WebSocket parameter.

---

## Group E — TTS Voice Responses

**What the cloud does:**
ElevenLabs synthesizes high-quality speech from text at `POST /v1/tts`. Used for AI voice responses in the app.

**Current state:**
`routers_local/tts.py` returns HTTP 501 for all requests.

**How it should work locally:**
Three local TTS options, selectable via env var:

| Option | Quality | Dependencies | Latency |
|--------|---------|-------------|---------|
| `piper` | Good | `pip install piper-tts` + model download (~50 MB) | ~200 ms |
| `macos` | Basic | None (macOS `say` command) | ~500 ms |
| `disabled` | N/A | None | Immediate 501 |

**Config env vars:**
- `TTS_PROVIDER` — `piper` | `macos` | `disabled` (default: `disabled`)
- `PIPER_MODEL` — default `en_US-lessac-medium`
- `PIPER_VOICE_RATE` — speaking rate, default `1.0`

**Technical Work:**

**1. Add `get_tts_provider()` to `providers.py`**

```python
TTSProvider = Literal["elevenlabs", "piper", "macos", "disabled"]

def get_tts_provider() -> TTSProvider:
    val = _read("TTS_PROVIDER", "disabled")
    if val not in ("elevenlabs", "piper", "macos", "disabled"):
        return "disabled"
    return val  # type: ignore[return-value]
```

**2. Create `utils/tts/providers/piper_client.py`**

```python
"""Piper TTS — local neural text-to-speech."""
import asyncio
import io
import subprocess
import tempfile
import os

_MODEL = os.environ.get("PIPER_MODEL", "en_US-lessac-medium")

async def synthesize(text: str) -> bytes:
    """Return WAV bytes for the given text."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _synthesize_sync, text)

def _synthesize_sync(text: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        proc = subprocess.run(
            ["python", "-m", "piper", "--model", _MODEL, "--output_file", tmp_path],
            input=text.encode(), capture_output=True, timeout=30
        )
        if proc.returncode != 0:
            raise RuntimeError(f"piper failed: {proc.stderr.decode()}")
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)
```

**3. Create `utils/tts/providers/macos_client.py`**

```python
import asyncio, subprocess, tempfile, os

async def synthesize(text: str) -> bytes:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _synthesize_sync, text)

def _synthesize_sync(text: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tmp:
        path = tmp.name
    try:
        subprocess.run(["say", "-o", path, text], check=True, timeout=15)
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.unlink(path)
```

**4. Replace the body of `routers_local/tts.py`**

```python
from providers import get_tts_provider

@router.post("/v1/tts")
async def text_to_speech(req: TTSRequest, ...) -> Response:
    provider = get_tts_provider()
    if provider == "piper":
        from utils.tts.providers import piper_client as tts
    elif provider == "macos":
        from utils.tts.providers import macos_client as tts
    else:
        raise HTTPException(status_code=501, detail="TTS_PROVIDER not configured")
    audio = await tts.synthesize(req.text)
    return Response(content=audio, media_type="audio/wav")
```

---

## Group F — Full RAG Chat

**What the cloud does:**
Claude (claude-sonnet-4-6) with tool use handles chat. It has access to 18 tools: search conversations, search memories, get action items, calendar, Gmail, Apple Health, screen activity, files, Perplexity web search, notifications, people/contacts, goals, trends, phone calls, and more. The LLM autonomously decides which tools to call based on the user's query.

**How it should work locally:**
Ollama models with tool-calling support (llama3.1, qwen2.5, qwen3) are wired with a subset of tools over the existing data. The current `/v1/chat` pass-through is replaced with an agentic loop that calls tools and injects results before returning the final answer.

Local tools (all implementable):
- `search_conversations` — Qdrant vector search
- `search_memories` — Qdrant vector search
- `get_action_items` — SQLite query
- `get_goals` — SQLite query (after A.4 is implemented)
- `search_web` — SearXNG if configured (see Group G)

Tools not locally implementable without external accounts:
- Calendar, Gmail, Apple Health, screen activity, files, phone calls

**Model requirement:** Tool/function calling requires a capable model. Recommended: `qwen2.5:7b` or `qwen3:4b`. Not supported by older models (llama2, mistral < 0.3).

**Config env vars:**
- `RAG_ENABLED` — default `false` (off until user confirms their Ollama model supports tool calling)
- `OLLAMA_CHAT_MODEL` — override model for chat specifically (default: `OLLAMA_MODEL`)

**Technical Work:**

**1. Create `utils/llm/rag_chat.py`**

```python
"""Tool-augmented RAG chat loop using Ollama function calling."""
import json
from typing import List, Dict

from utils.llm.providers import ollama_client

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_conversations",
            "description": "Search through past recorded conversations for relevant context",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_memories",
            "description": "Search personal memory facts for relevant information",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_action_items",
            "description": "Retrieve current action items and tasks",
            "parameters": {"type": "object", "properties": {}}
        }
    },
]

async def tool_chat(messages: List[Dict], user_id: str) -> str:
    """Run one turn of the tool-calling loop. Returns final assistant response."""
    from database import vector_db_qdrant as vdb
    from database.sql import repository

    async def execute_tool(name: str, args: dict) -> str:
        if name == "search_conversations":
            ids = await asyncio.to_thread(vdb.query_vectors, user_id, args["query"], limit=5)
            results = []
            for entry in (ids or []):
                cid = entry["id"] if isinstance(entry, dict) else entry
                c = repository.get_conversation(user_id, cid)
                if c:
                    text = " ".join(s["text"] for s in (c.get("transcript_segments") or []))
                    results.append(f"[{c.get('title','')}]: {text[:400]}")
            return "\n\n".join(results) or "No relevant conversations found."

        if name == "search_memories":
            ids = await asyncio.to_thread(vdb.search_memories_by_vector, user_id, args["query"], limit=5)
            # fetch and return memory contents
            return "\n".join(str(i) for i in (ids or [])) or "No relevant memories."

        if name == "get_action_items":
            items = await asyncio.to_thread(repository.list_action_items, user_id)
            return "\n".join(f"- {i['description']}" for i in items) or "No action items."

        return f"Unknown tool: {name}"

    # Agentic loop: max 3 tool-call rounds to prevent infinite loops
    working_messages = list(messages)
    for _ in range(3):
        response = await ollama_client.achat_with_tools(working_messages, tools=TOOLS)
        if not response.get("tool_calls"):
            return response.get("content", "")
        # Execute each tool call and append results
        for call in response["tool_calls"]:
            result = await execute_tool(call["function"]["name"],
                                        call["function"].get("arguments", {}))
            working_messages.append({"role": "tool", "content": result,
                                     "tool_call_id": call.get("id", "")})
    return response.get("content", "")
```

**2. Add `achat_with_tools()` to `utils/llm/providers/ollama_client.py`** — calls Ollama's `/api/chat` endpoint with the `tools` parameter.

**3. Update `routers_local/chat.py`** — add `use_rag: bool = True` to `ChatRequest`. When `RAG_ENABLED=true` and `use_rag=True`, route through `rag_chat.tool_chat()` instead of `llm_router.achat()`.

---

## Group G — Web Search (SearXNG)

**What the cloud does:**
Perplexity API provides web search results as a tool during RAG chat.

**How it should work locally:**
SearXNG is a self-hosted meta-search engine that runs in Docker and proxies queries to multiple search engines (Google, DuckDuckGo, Bing, etc.) without requiring API keys or accounts. It exposes a REST API. The backend queries SearXNG and returns results as a RAG tool.

**Important note on "local":** The SearXNG container itself runs locally (no account, no API key), but the search results are fetched from the public internet. This is "local infrastructure" for web search — not "offline" web search, which is impossible by definition.

**Setup:**
```bash
docker run -d -p 8888:8080 --name searxng \
  -e SEARXNG_SECRET_KEY=local-secret \
  searxng/searxng
```

**Config env vars:**
- `SEARCH_PROVIDER=local` (already a valid value in `providers.py`)
- `SEARXNG_URL` — default `http://localhost:8888`

**Technical Work:**

**1. Create `utils/search/searxng_client.py`**

```python
import httpx
from typing import List, Dict

_URL = os.environ.get("SEARXNG_URL", "http://localhost:8888")

async def search(query: str, num_results: int = 5) -> List[Dict]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_URL}/search",
                                params={"q": query, "format": "json", "language": "en"})
        resp.raise_for_status()
        data = resp.json()
    return [
        {"title": r.get("title",""), "url": r.get("url",""), "snippet": r.get("content","")}
        for r in data.get("results", [])[:num_results]
    ]
```

**2. Add `search_web` to the RAG tool list in `rag_chat.py`** (Group F) — only added when `SEARCH_PROVIDER=local` and SearXNG is reachable.

**3. Add `SEARXNG_URL` to `.env.reference`**

---

## Group H — Local Audio Backup

**What the cloud does:**
The pusher service buffers audio in 60-second batches and uploads them encrypted to personal GCS/S3.

**How it should work locally:**
When `AUDIO_BACKUP_ENABLED=true`, PCM audio is buffered in memory during the session and written to disk as a WAV file when the conversation finalizes. An optional S3-compatible endpoint (MinIO, Backblaze B2, Wasabi) can be configured for off-machine backup.

**Config env vars:**
- `AUDIO_BACKUP_ENABLED` — default `false`
- `AUDIO_BACKUP_DIR` — default `./audio_archive`
- `AUDIO_S3_ENDPOINT` / `AUDIO_S3_BUCKET` / `AUDIO_S3_KEY` / `AUDIO_S3_SECRET` — optional S3 target

**Technical Work:**

**1. In `routers_local/listen.py`**, when `AUDIO_BACKUP_ENABLED=true`:
- Add `audio_buffer: list[bytes] = []` alongside `accumulated_segments`
- Append each audio chunk to the buffer: `audio_buffer.append(audio)`
- In `_finalize()`, after `repository.create_conversation()`, call `_save_audio(conv_id, audio_buffer)`

**2. Add `_save_audio()` helper to `listen.py`**:

```python
def _save_audio(conv_id: str, pcm_chunks: list[bytes]) -> None:
    import wave, os
    backup_dir = os.environ.get("AUDIO_BACKUP_DIR", "./audio_archive")
    os.makedirs(backup_dir, exist_ok=True)
    path = os.path.join(backup_dir, f"{conv_id}.wav")
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"".join(pcm_chunks))
    logger.info("Audio saved to %s", path)
```

**3. Optional S3 upload:** If `AUDIO_S3_BUCKET` is set, use `boto3.client("s3", endpoint_url=AUDIO_S3_ENDPOINT)` to upload after writing to disk. Add `boto3` to optional requirements.

**Memory note:** Buffering full audio in memory increases RAM usage. At 16 kHz mono 16-bit, one hour of audio = ~115 MB. For long sessions, consider streaming to disk incrementally rather than buffering.

---

## Group I — Local Agent

**What the cloud does:**
The agent proxy (`agent-proxy/main.py`) bridges the mobile app's WebSocket to a personal GCE VM running a persistent, long-running AI agent. The agent maintains full conversation history, can run autonomously between messages, and has access to all the user's data.

**How it should work locally:**
A persistent per-user chat session is stored in SQLite. Each user has one agent session that accumulates history. On WebSocket connect, the last N messages are injected as context. New messages are processed through Ollama and appended to the history.

This is not equivalent to a dedicated cloud VM (no autonomous background processing, limited context window), but it provides the same conversational interface with memory across disconnections.

**Config env vars:**
- `AGENT_ENABLED` — default `false`
- `AGENT_HISTORY_MESSAGES` — default `50` (messages to inject on reconnect)
- `AGENT_SYSTEM_PROMPT` — default system prompt for the agent's personality

**Technical Work:**

**1. Add `AgentSession` model to `models.py`**

```python
class AgentSession(Base):
    __tablename__ = "agent_sessions"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"),
                     unique=True, index=True, nullable=False)
    messages = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    user = relationship("User")
```

**2. Add `get_agent_session()` / `save_agent_session()` to `repository.py`**

**3. Create `routers_local/agent.py`**

```python
@router.websocket("/v3/agent/connect")
async def agent_connect(ws: WebSocket, token: str = Query("")):
    # authenticate via local JWT
    # load session history from SQLite
    # inject last AGENT_HISTORY_MESSAGES messages as context
    # process new messages through Ollama (with optional RAG tools)
    # persist updated history
    # WebSocket loop: receive user messages, emit assistant tokens via streaming
```

**4. Register router in `main_local.py`** (only when `AGENT_ENABLED=true`)

---

## Group J — Custom Personas

**What the cloud does:**
The app marketplace hosts third-party personas with custom prompts, tools, and behaviors. Users install them and interact via the chat interface.

**Local equivalent:**
Named system prompt presets stored in SQLite. Users create personas with a name, description, and system prompt. When chatting with a persona, the system prompt is prepended to the message array.

A full marketplace (distribution, review, payment, developer APIs) is not implementable in a single-operator local setup. This is explicitly out of scope.

**Technical Work:**

**1. Add `Persona` model to `models.py`**

```python
class Persona(Base):
    __tablename__ = "personas"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    system_prompt = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    user = relationship("User")
```

**2. Add `create_persona()`, `list_personas()`, `get_persona()`, `delete_persona()` to `repository.py`**

**3. Create `routers_local/personas.py`**

```
GET    /v1/personas           — list user's personas
POST   /v1/personas           — create a persona
GET    /v1/personas/{id}      — get a persona
DELETE /v1/personas/{id}      — delete
```

**4. Update `ChatRequest` in `routers_local/chat.py`**:
- Add `persona_id: Optional[str] = None`
- If `persona_id` provided, look up the persona and prepend `{"role": "system", "content": persona.system_prompt}` to the messages array

---

## Group K — Optional External Integrations

These features require external services. They are configurable per the local/cloud pattern but not fully offline.

### K.1 Calendar via CalDAV

**What it is:** Read access to calendar events for use as RAG context.

**Local implementation:** Connect to a CalDAV server — either a local one (Radicale: `pip install radicale`) or an existing CalDAV endpoint (iCloud, Nextcloud, Fastmail, Google Calendar's CalDAV interface).

**Config env vars:** `CALENDAR_PROVIDER=caldav`, `CALDAV_URL`, `CALDAV_USERNAME`, `CALDAV_PASSWORD`

**Technical work:**
- Add `caldav` Python library to optional requirements
- Create `utils/integrations/calendar.py` → `get_upcoming_events(days=7) -> List[dict]`
- Expose as a RAG tool in Group F when `CALENDAR_PROVIDER=caldav`

### K.2 Email via IMAP

**What it is:** Read access to recent emails for RAG context.

**Local implementation:** IMAP protocol is supported by virtually every email provider including Gmail (via app passwords), without OAuth. The Python stdlib `imaplib` module handles IMAP connections.

**Config env vars:** `EMAIL_PROVIDER=imap`, `IMAP_HOST`, `IMAP_PORT=993`, `IMAP_USER`, `IMAP_PASSWORD`

**Technical work:**
- Create `utils/integrations/email.py` → `get_recent_emails(days=3) -> List[dict]`
- Expose as RAG tool when `EMAIL_PROVIDER=imap`

---

## Group L — Speaker Diarization

**What the cloud does:**
During streaming, pyannote/speaker-diarization (GPU-accelerated) identifies speaker boundaries in real time. Speakers are matched against stored speech profiles and labeled by name.

**Can this be implemented locally?**
Yes — as post-processing, not real-time. The timing and architecture differ from the cloud version but the functional result is the same.

**Constraints and honest expectations:**

| Hardware | Diarization speed | Practical limit |
|----------|------------------|----------------|
| CPU only | 10–20× real-time | Max ~10 min audio before it becomes annoying |
| Apple Silicon (MPS) | 3–5× real-time | 30 min audio takes ~2–10 min |
| NVIDIA GPU (CUDA) | < 1× real-time | Unlimited, comparable to cloud |

Real-time diarization (during streaming) is not implementable on CPU without significant latency. Post-processing diarization (runs after the conversation ends, re-labels segments) is the correct local approach.

**Additional requirement:** pyannote models require a Hugging Face account and accepting the model terms at `hf.co/pyannote/speaker-diarization-3.1`. A `PYANNOTE_AUTH_TOKEN` is required for the initial download.

**Technical work:**

**1. Buffer audio during the session**

In `listen.py`, alongside `accumulated_segments`, maintain `audio_buffer: list[bytes]`. This is shared with the Audio Backup feature (Group H) and should be implemented once.

**2. Build `utils/diarization/local_diarizer.py`**

```python
"""Post-session speaker diarization using pyannote.audio."""
import io, wave, tempfile, os
from typing import List

_DEVICE = os.environ.get("DIARIZATION_DEVICE", "cpu")

def diarize(pcm_bytes: bytes, sample_rate: int = 16000,
            num_speakers: Optional[int] = None) -> List[dict]:
    """Returns [{start, end, speaker}] segments."""
    from pyannote.audio import Pipeline
    import torch
    pipeline = _get_pipeline()
    # Write PCM to temp WAV
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
        with wave.open(f, "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
    try:
        diarization = pipeline(wav_path,
                               num_speakers=num_speakers)
        return [{"start": turn.start, "end": turn.end, "speaker": speaker}
                for turn, _, speaker in diarization.itertracks(yield_label=True)]
    finally:
        os.unlink(wav_path)

def _get_pipeline():
    from pyannote.audio import Pipeline
    import torch
    global _pipeline
    if _pipeline is None:
        token = os.environ.get("PYANNOTE_AUTH_TOKEN")
        _pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=token
        )
        device = torch.device(_DEVICE)
        _pipeline.to(device)
    return _pipeline

_pipeline = None
```

**3. Add post-diarization re-labeling in `_post_process` (after conversation save)**

Map Whisper segments (which have `start`/`end` timestamps) to pyannote speaker turns. Update each segment's `speaker` and `speaker_id` fields. Call `repository.update_conversation()` with the re-labeled segments.

This requires that `transcript_segments` in Whisper output carry accurate timestamps. Verify this with the current faster-whisper integration.

**4. Config env vars:**
- `ENABLE_DIARIZATION=true`
- `DIARIZATION_DEVICE=cpu|mps|cuda`
- `PYANNOTE_AUTH_TOKEN=hf_xxxx`
- `DIARIZATION_MIN_SPEAKERS=1`, `DIARIZATION_MAX_SPEAKERS=6`

**5. Add `pyannote.audio` to optional requirements** — it is large (~1 GB of model weights) and should not be a hard dependency.

---

## Features That Cannot Be Implemented Locally

### Cannot Implement: Push Notifications to Mobile Devices

**What it does:** FCM/APNS delivers notifications to a locked or backgrounded iPhone/Android even when the app is not running.

**Why it is impossible locally:**

Apple Push Notification Service (APNS) and Google Firebase Cloud Messaging (FCM) are the mandatory intermediaries for delivering notifications to mobile devices. This is not a software limitation — it is a hardware and OS security model enforced at the silicon level on every modern smartphone.

When an iPhone is locked or the app is in the background, iOS suspends all app network activity. The only process that remains active is the iOS operating system itself, which maintains a persistent encrypted connection to Apple's APNS servers. Push notifications travel exclusively through this Apple-controlled channel.

To send a push notification to an iPhone, a server must:
1. Hold a valid APNS authentication key (issued only to registered Apple Developer accounts)
2. Connect to `api.push.apple.com` on port 443 or 2197 — Apple's servers, not yours
3. Send an HTTP/2 request signed with that key
4. Apple's infrastructure delivers the notification through its persistent connection to the device

There is no alternative delivery mechanism. Apple does not publish APIs for third-party push infrastructure. VoIP notifications (PushKit) are the one exception — they bypass some background restrictions — but they still go through Apple's servers and require Apple Developer credentials.

**What can be done instead:**
- When the app is open and connected to the local WebSocket (`/ws`), any event (new memory, conversation end) is delivered in real time via `push_event()`. This works for foreground notifications.
- macOS Desktop notifications work without any cloud infrastructure — the Desktop app receives a WebSocket event and calls `UNUserNotificationCenter` to display a native notification. This requires a change to the Desktop Swift app, not the backend.
- A polling endpoint (`GET /v1/notifications/pending`) can serve undelivered events when the app opens — simulating notifications that were "missed" while the app was closed. This doesn't wake the app, but on next launch the user sees pending items.

---

### Cannot Implement: Full App Marketplace

**What it does:** Third-party developers publish integrations, personas, and mini-apps to a hosted marketplace. Users browse, install, and pay for them.

**Why it is impossible locally:**

A marketplace is a multi-party platform, not a feature. It requires: a hosting infrastructure for third-party code, a review and signing process, a payment processor (Stripe integration exists but is cloud-only), a developer portal, and cross-user sharing. None of these concepts apply to a single-operator local backend serving one user.

**What can be done instead:** Custom personas (Group J) and the local integrations (Group K) provide the personalization and extensibility that a single operator needs without marketplace infrastructure.

---

### Cannot Implement: Apple Health Integration (Server-Side)

**What it does:** During chat, the LLM has access to the user's health data (steps, sleep, heart rate, workouts) from Apple Health.

**Why it is impossible to implement as a pure server-side feature:**

HealthKit is an iOS and watchOS framework with no equivalent on macOS or any other platform. It is explicitly not available as a macOS framework — Apple documented this design choice: health data lives on the device and is accessed only through the iOS HealthKit API, which requires an app running on the device to request access.

A Python server running on macOS has no way to query HealthKit. There is no IMAP-equivalent protocol, no CalDAV-equivalent for health data, and no macOS command-line tool that reads HealthKit. The Health app on macOS (added in Ventura) displays data synced from an iPhone but exposes no programmatic API.

**What can be done instead (requires iOS app change):**
The Omi iOS app could be modified to read HealthKit data when the app is foregrounded and POST a snapshot to `POST /v1/health-snapshot` on the local backend. This approach works but:
1. It requires a Flutter app code change
2. It is not real-time (only updates when the app is open)
3. It is outside the scope of backend changes

A second option is the "Health Auto Export" iOS app, which can automatically push health data to a custom HTTP endpoint. The backend could expose a compatible webhook endpoint. This is an external dependency and not a clean integrated solution.

---

### Cannot Implement: Cloud Agent VM Proxy

**What it does:** The cloud agent proxy bridges the mobile app to a personal Google Compute Engine VM. The VM runs a persistent AI agent that can take actions autonomously (browse the web, run code, etc.) between user messages, backed by dedicated cloud compute.

**Why the cloud VM component is impossible locally:**

GCE VM instances are a Google Cloud product. The agent proxy's GCE lifecycle management (`start_vm`, `reset_vm`, `health_check_vm`) calls the Google Compute Engine API, which requires a GCP project, service account credentials, and a running GCE instance in a specific region. This is infrastructure that runs in Google's data centers.

The autonomous agent behavior (running between messages, browsing the web independently) also depends on the VM having its own network egress, outbound compute, and persistent filesystem — capabilities that require a server with a static IP and always-on compute.

**What can be done instead:**
The local agent (Group I) provides the same conversational interface with persistent history. What it cannot provide is autonomous background processing between sessions (the agent can only think when a message is received) or dedicated compute isolated from the backend process. For a single-user local setup where the primary use case is conversational interaction, the local agent covers the practical need.

---

### Cannot Implement: Stock App Store iOS Build

**What it does:** The official Omi app from the App Store is a pre-built binary with `https://api.omi.me` compiled in as the backend URL.

**Why it cannot be redirected to a local backend:**

iOS app binaries are cryptographically signed by Apple at distribution time. Modifying any byte of the binary — including the string `api.omi.me` — breaks the signature and causes iOS to refuse to launch the app. The signing key is held by Anthropic/Omi; changing the binary would require re-signing it, which requires that private key.

There is no runtime mechanism to override a compiled constant. iOS does not support environment variables, launch arguments, or configuration files that could intercept the hardcoded URL. `Info.plist` can be modified in development builds but not in signed App Store binaries.

**The path that works:** Build from source using the Flutter repository with a custom `.dev.env` file that sets `API_BASE_URL=http://<YOUR_SERVER_IP>:8088`. This is fully documented in RUNBOOK §10.3. The resulting binary is signed with your own Apple Developer certificate (free account works for personal use) and is installable on any iPhone you own. This is the correct and supported approach for local use.

---

## Implementation Order Recommendation

Based on dependencies between features and practical impact per effort:

| Priority | Feature(s) | Reason |
|----------|-----------|--------|
| **1** | A.1 + A.2 + A.3 (post-processing pipeline) | Single implementation, highest impact — transforms raw transcripts into useful data |
| **2** | B.1 (real-time memory events) | ~3 lines once A.2 exists; completes the live event loop |
| **3** | C (semantic search endpoint) | Infrastructure fully exists; needs only an HTTP endpoint |
| **4** | G (silence timeout) | Small, self-contained, immediately useful for long recording sessions |
| **5** | E (TTS) | Useful for voice interaction; piper implementation is straightforward |
| **6** | F (RAG chat) | High value but depends on A.1–A.3 for meaningful context |
| **7** | A.5 (daily summaries) | Requires APScheduler; useful once several days of data exist |
| **8** | A.4 (goal tracking) | Requires new DB table; lower urgency |
| **9** | I (local agent) | Requires new DB table; niche use case |
| **10** | J (personas) | Requires new DB table; personalization enhancement |
| **11** | H (audio backup) | Infrastructure safety net; low urgency |
| **12** | L (diarization) | Large dependency, slow on CPU, significant complexity |
| **13** | K (integrations) | Optional, each is independent; implement on demand |

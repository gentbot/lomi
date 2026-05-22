# Omi Backend — Fully Local Migration Spec (Final Merged, LLM-Executable)

## Purpose

This document merges the strengths of two prior versions:

1. the detailed repo-grounded migration checklist with exact files, phases, and replacement targets, and  
2. the cleaner execution-oriented specification with explicit interfaces, definitions of done, testing expectations, and system-level guardrails.

The goal is to produce a single spec that is:

- comprehensive
- concrete
- repo-aware
- phase-ordered
- safe for iterative implementation
- usable by an LLM coding agent without requiring it to invent structure

It is intentionally detailed and should be treated as an implementation specification, not a high-level brainstorm.

---

## Goal

Transform the Omi backend into a fully local, self-contained system that performs:

- audio ingestion
- speech-to-text
- conversation processing
- memory storage + retrieval
- LLM reasoning
- realtime updates

without any external APIs or cloud services.

The intended approach is to preserve the existing architecture as much as possible, especially the FastAPI app structure and modular service boundaries, and replace cloud integrations behind stable interfaces so the rest of the codebase experiences minimal breakage.

---

## Architectural Intent

Do **not** rewrite the backend into a new architecture unless absolutely necessary.

Preserve these high-level characteristics:

- FastAPI entrypoint and router structure
- modular `utils/`, `database/`, `routers/`, and service-specific directories
- existing public module boundaries where practical
- compatibility of upstream call sites wherever possible
- staged replacement of providers behind routers/factories/resolvers

The guiding rule is:

> Replace implementations behind interfaces before changing consumers.

---

## Non-Goals

These are explicitly **not** required for the first successful local-only version:

- perfect diarization
- exact Deepgram streaming parity
- exact Deepgram/Fal WhisperX speaker-label parity
- cloud feature parity across all integrations
- billing parity
- analytics parity
- every OAuth integration
- hosted search parity
- tool-calling parity beyond what is needed for current backend behavior
- peak-performance streaming transcription
- a one-shot rewrite of the whole backend

---

## Scope Boundary

The first successful local-only milestone should support:

- local login
- local prerecorded audio upload
- local transcription
- local conversation save
- local embeddings
- local memory search
- local LLM response generation
- local realtime transcript/chat updates over WebSockets

If those work end-to-end, the core migration is successful even if optional integrations remain disabled.

---

## Assumptions

The spec assumes the following runtime environment for the first implementation:

- Ollama is running locally at `http://localhost:11434`
- Qdrant is running locally at `http://localhost:6333`
- a local Whisper-capable transcription path is available
- SQLite is the primary local database
- Redis may remain locally if existing code strongly assumes it, but it is not the primary system of record
- the repo still contains backend areas corresponding to:
  - `database/`
  - `utils/`
  - `routers/`
  - `main.py`
  - service-specific directories such as `modal/`, `pusher/`, and `typesense/`
- the current backend still has cloud-oriented dependencies such as:
  - Firebase / Google Cloud
  - OpenAI
  - Deepgram
  - Pinecone
  - Typesense
  - Stripe
  - Pusher
  - possibly Redis-based infrastructure
  - additional optional integrations referenced in env config or setup docs

---

## Verified/Assumed Current Backend Hotspots

These are the repo-grounded backend hotspots the migration is designed around:

- `backend/.env.template`
- `backend/main.py`
- `backend/dependencies.py`
- `backend/utils/llm/clients.py`
- `backend/database/vector_db.py`
- `backend/database/redis_db.py`
- `backend/database/conversations.py`
- `backend/database/users.py`
- `backend/utils/stt/streaming.py`
- `backend/utils/stt/pre_recorded.py`
- `backend/utils/stt/vad.py`
- `backend/routers/auth.py`
- `backend/routers/oauth.py`
- `backend/pusher/`
- `backend/typesense/`
- `backend/modal/`
- `backend/utils/billing/`

These areas are explicitly referenced because the earlier repo-grounded migration plan identified them as existing integration points and likely cloud dependency anchors. fileciteturn1file0

---

## System Flow

The target execution flow is:

```text
HTTP Request
→ FastAPI Router
→ Dependency / Provider Resolver
→ Service Layer / Domain Logic
→ Provider Implementation
→ Response
```

For audio/transcript flows, the intended local path is:

```text
Audio Input
→ Local VAD
→ Local Whisper Transcription
→ Local Embeddings
→ Local Vector DB (Qdrant)
→ Local LLM (Ollama)
→ WebSocket Updates
→ SQLite Persistence
```

---

## Migration Guardrails

These rules apply throughout the migration:

1. Replace one dependency at a time.
2. Do not delete the old provider until the new one is wired and tested.
3. Preserve function signatures where practical to avoid breakage in upstream code.
4. If preserving the exact function signature is impossible, add an adapter layer rather than forcing broad upstream refactors.
5. No direct cloud SDK imports outside provider-specific modules after providerization is complete.
6. All provider selection must happen through environment-driven routing/resolver functions.
7. Each phase must produce a runnable intermediate state.
8. Avoid “big bang” branch-wide rewrites.
9. Prefer local-first minimal parity over feature completeness.
10. Document every behavior downgrade explicitly, especially:
   - diarization
   - streaming STT latency
   - search functionality
   - OAuth availability

---

## Version-Control Strategy

Before touching runtime behavior:

1. Fork the repo.
2. Pin a specific upstream commit in your fork.
3. Create a long-lived branch, for example:
   - `local-only-backend`
4. Create a bootstrap branch for initial config/provider work, for example:
   - `local-only-backend-bootstrap`

Reason:
- the upstream repo is active
- backend assumptions likely still depend on cloud credentials and services
- migration should remain attributable to a known upstream state

---

## Runtime Provider Model

All runtime provider selection should become explicit and env-driven.

### Required Environment Variables

Add these to:

- `backend/.env.template`

```env
STT_PROVIDER=local
LLM_PROVIDER=ollama
EMBEDDINGS_PROVIDER=local
VECTOR_DB_PROVIDER=qdrant
AUTH_PROVIDER=local
DB_PROVIDER=sqlite
EVENT_PROVIDER=websocket
SEARCH_PROVIDER=disabled
ENABLE_DIARIZATION=false
```

If Redis remains locally for caches/session use, add a local Redis host config only if required by existing runtime assumptions.

---

## Core Interface Contracts

These types should exist conceptually even if implemented in a different module layout.

### Message Type

```python
from typing import TypedDict, Literal

class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str
```

### Chat Response

```python
from typing import TypedDict

class ChatResponse(TypedDict):
    content: str
    tool_calls: list | None
```

### Vector Match Shape

```python
from typing import TypedDict, Any

class VectorMatch(TypedDict):
    id: str
    score: float
    metadata: dict[str, Any]
```

### Transcription Response Shape

```python
from typing import TypedDict, Any

class TranscriptionResponse(TypedDict):
    text: str
    segments: list[dict[str, Any]]
    language: str
```

### Auth Token Payload Shape

```python
from typing import TypedDict, Any

class TokenPayload(TypedDict):
    user_id: str
    email: str
    exp: int
```

---

## Async / Concurrency Rules

This is a critical part of the spec and should not be left implicit.

### Required Concurrency Model

- FastAPI routers remain `async`
- WebSocket handlers remain `async`
- Any LLM streaming path should be implemented as an async generator if routed through async FastAPI responses
- Streaming STT session handlers must avoid blocking the event loop
- SQLite access must either:
  - remain synchronous but be called safely in a way compatible with FastAPI usage, or
  - be abstracted through a safe session layer
- Long-running local transcription or embedding work must not block WebSocket responsiveness

### Minimum rule

If an implementation is synchronous and expensive, isolate it behind a worker/thread boundary or another safe execution strategy rather than calling it directly in the event loop.

---

## Provider Rules

- All provider implementations must match defined interfaces.
- Providers are selected via environment variables.
- No provider-specific SDK imports should leak into unrelated modules.
- Public router/service code should depend on resolver/factory functions, not concrete cloud clients.
- If a provider must expose richer behavior than the current interface allows, first add a typed adapter layer.

---

# Phase-by-Phase Implementation Plan

---

## Phase 0 — Freeze State + Config + Provider Abstraction (Do First)

### Objective

Create a safe migration base without changing core behavior yet.

### Files to Modify

- `backend/.env.template`
- `backend/main.py`
- `backend/dependencies.py`

### New Files

- `backend/providers.py`

### Step 0.1 — Update env template

Add:

```env
STT_PROVIDER=local
LLM_PROVIDER=ollama
EMBEDDINGS_PROVIDER=local
VECTOR_DB_PROVIDER=qdrant
AUTH_PROVIDER=local
DB_PROVIDER=sqlite
EVENT_PROVIDER=websocket
SEARCH_PROVIDER=disabled
ENABLE_DIARIZATION=false
```

### Step 0.2 — Create provider resolver

Create:

- `backend/providers.py`

Example interface:

```python
from typing import Literal

def get_stt_provider() -> Literal["deepgram", "local"]:
    ...

def get_llm_provider() -> Literal["openai", "ollama"]:
    ...

def get_embeddings_provider() -> Literal["openai", "local"]:
    ...

def get_vector_db_provider() -> Literal["pinecone", "qdrant"]:
    ...

def get_auth_provider() -> Literal["firebase", "local"]:
    ...

def get_event_provider() -> Literal["pusher", "websocket"]:
    ...

def get_search_provider() -> Literal["typesense", "disabled", "local"]:
    ...

def get_db_provider() -> Literal["firestore", "sqlite", "postgres"]:
    ...
```

### Step 0.3 — Wire provider resolver into startup path

Modify:

- `backend/main.py`
- `backend/dependencies.py`

Replace direct runtime imports such as:

```python
from utils.llm.clients import ChatOpenAI
```

with provider-routed imports such as:

```python
from providers import get_llm_provider
```

and route concrete resolution through factory/router modules rather than direct SDK imports.

### Definition of Done

- app boots with the provider resolver present
- env file contains provider selection variables
- no new cloud imports are introduced outside provider modules
- runtime path is prepared for swapping providers without broad structural rewrites

### Required Validation

- app startup still succeeds
- import graph still resolves
- old behavior remains intact before actual provider replacement begins

---

## Phase 1 — LLM Replacement

### Objective

Replace direct OpenAI-based LLM usage with a provider-routed structure that can support Ollama locally while preserving call compatibility.

### Existing File

- `backend/utils/llm/clients.py`

### Files to Create

- `backend/utils/llm/providers/openai_client.py`
- `backend/utils/llm/providers/ollama_client.py`
- `backend/utils/llm/router.py`

### Step 1.1 — Extract OpenAI client

Move direct OpenAI client setup out of:

- `backend/utils/llm/clients.py`

and split it into:

- `backend/utils/llm/providers/openai_client.py`

### Step 1.2 — Create Ollama client

Create:

- `backend/utils/llm/providers/ollama_client.py`

Minimum interface:

```python
from typing import List, Dict

def generate(prompt: str) -> str:
    ...

def chat(messages: List[Dict[str, str]]) -> str:
    ...

def stream(messages: List[Dict[str, str]]):
    yield str

def extract_actions(text: str) -> dict:
    ...
```

Preferred stronger typed interface:

```python
from typing import AsyncIterator

def generate(prompt: str) -> str:
    ...

def chat(messages: list[Message]) -> ChatResponse:
    ...

async def stream(messages: list[Message]) -> AsyncIterator[str]:
    ...

def extract_actions(text: str) -> dict:
    ...
```

If existing code expects a plain string from `chat()`, preserve that behavior via an adapter layer instead of forcing upstream refactors immediately.

### Step 1.3 — Create LLM router

Create:

- `backend/utils/llm/router.py`

Example:

```python
from providers import get_llm_provider

def get_llm():
    if get_llm_provider() == "ollama":
        from .providers.ollama_client import chat
        return chat
    else:
        from .providers.openai_client import chat
        return chat
```

If the repo needs a richer object than a bare function, return an adapter object instead of a callable.

### Wiring Change

Replace direct imports of concrete clients with provider-routed accessors.

### Definition of Done

- `/chat` or equivalent LLM endpoint works with Ollama
- no OpenAI imports remain in the main runtime path outside provider modules
- local inference path returns valid responses
- if streaming is required by the backend, it returns incremental chunks without blocking the event loop

### Minimum Tests

#### Test 1 — Simple chat

Input:

```json
[{"role": "user", "content": "hello"}]
```

Expected:
- non-empty response
- no exception

#### Test 2 — Streaming

Expected:
- incremental chunks returned
- completion occurs cleanly
- no event loop blockage

### Notes / Risks

- message formatting may differ across providers
- tool-call extraction may require a compatibility shim
- token/response streaming behavior may not match OpenAI exactly

---

## Phase 2 — Embeddings Replacement

### Objective

Move embeddings out of OpenAI-specific client code and support local embedding generation with dimension awareness.

### Existing File

- `backend/utils/llm/clients.py`

### Files to Create

- `backend/utils/embeddings/openai_embeddings.py`
- `backend/utils/embeddings/local_embeddings.py`
- `backend/utils/embeddings/router.py`

### Step 2.1 — Create local embeddings provider

Create:

- `backend/utils/embeddings/local_embeddings.py`

Interface:

```python
from typing import List

def embed(text: str) -> List[float]:
    ...

def embed_batch(texts: List[str]) -> List[List[float]]:
    ...
```

Preferred behavior:
- configurable model choice
- dimension exposed/configurable
- batch embedding supported explicitly

### Step 2.2 — Move OpenAI embeddings logic out of LLM client file

Move existing embedding logic from:

- `backend/utils/llm/clients.py`

into:

- `backend/utils/embeddings/openai_embeddings.py`

### Step 2.3 — Add embeddings router

Create:

- `backend/utils/embeddings/router.py`

Example:

```python
from providers import get_embeddings_provider

def get_embedder():
    if get_embeddings_provider() == "local":
        from .local_embeddings import embed
        return embed
    else:
        from .openai_embeddings import embed
        return embed
```

### Definition of Done

- embeddings are generated locally
- dimension is configurable and known
- embedding router isolates provider selection
- vector DB integration can consume local vectors without shape ambiguity

### Minimum Tests

#### Test 1 — Single embedding
- vector returned
- vector is non-empty

#### Test 2 — Batch embedding
- batch returns one vector per input

#### Test 3 — Dimension consistency
- all embeddings for selected local model have identical length

### Notes / Risks

- embedding dimension mismatch is a known migration hazard
- any Pinecone/Qdrant collection config must match the local embedding size
- if similarity logic assumed OpenAI embedding behavior, retrieval tuning may shift

---

## Phase 3 — Vector DB Replacement (Pinecone → Qdrant)

### Objective

Replace Pinecone-backed memory storage/search with a local vector database while preserving public usage patterns.

### Existing File

- `backend/database/vector_db.py`

### Files to Create

- `backend/database/vector_db_base.py`
- `backend/database/vector_db_pinecone.py`
- `backend/database/vector_db_qdrant.py`

### Step 3.1 — Split vector DB code

Refactor:

- `backend/database/vector_db.py`

into:
- `backend/database/vector_db_base.py`
- `backend/database/vector_db_pinecone.py`
- `backend/database/vector_db_qdrant.py`

### Step 3.2 — Create Qdrant client

Create:

- `backend/database/vector_db_qdrant.py`

Interface:

```python
from typing import List, Dict

def upsert(id: str, vector: List[float], metadata: Dict):
    ...

def query(vector: List[float], top_k: int = 5):
    ...

def delete(id: str):
    ...
```

Preferred typed return contract:

```python
def query(vector: list[float], top_k: int = 5) -> list[VectorMatch]:
    ...
```

Return shape must be:

```python
[
  {
    "id": str,
    "score": float,
    "metadata": dict
  }
]
```

### Step 3.3 — Add router / resolver path

Modify or recreate:

- `backend/database/vector_db.py`

Example:

```python
from providers import get_vector_db_provider

def get_vector_db():
    if get_vector_db_provider() == "qdrant":
        from .vector_db_qdrant import upsert, query
    else:
        from .vector_db_pinecone import upsert, query
    return upsert, query
```

If existing code expects richer DB behavior, return an adapter object rather than only functions.

### Required Behavior

- preserve public functions currently used by memory storage/retrieval code
- Qdrant collection creation must use the selected local embedding dimension
- Pinecone namespaces must be mapped either to:
  - separate Qdrant collections, or
  - a metadata namespace field

### Optional but Recommended

Create a migration helper:

- `backend/scripts/reindex_local_vectors.py`

Use it later to:
- re-embed existing stored text
- re-index into Qdrant
- avoid destructive migration assumptions

### Definition of Done

- Qdrant stores vectors locally
- similarity search returns valid structured results
- collection dimension matches local embedding size
- no runtime Pinecone dependency remains in local mode

### Minimum Tests

#### Test 1 — Upsert
- vector stored successfully

#### Test 2 — Query
- semantically similar vector returns expected result shape

#### Test 3 — Delete
- vector removed successfully

### Notes / Risks

- namespace behavior differs between Pinecone and Qdrant
- scoring may not be numerically identical
- embedding dimension mismatch will break collection creation or search

---

## Phase 4 — Speech-to-Text Replacement (Prerecorded + Streaming)

### Objective

Replace Deepgram/cloud-oriented speech-to-text paths with a local-first transcription strategy.

### Existing Files

- `backend/utils/stt/pre_recorded.py`
- `backend/utils/stt/streaming.py`

### Files to Create

- `backend/utils/stt/providers/deepgram_prerecorded.py`
- `backend/utils/stt/providers/local_whisper_prerecorded.py`
- `backend/utils/stt/providers/deepgram_streaming.py`
- `backend/utils/stt/providers/local_streaming.py`

### Step 4.1 — Split prerecorded STT provider logic

Refactor:

- `backend/utils/stt/pre_recorded.py`

into:
- `backend/utils/stt/providers/deepgram_prerecorded.py`
- `backend/utils/stt/providers/local_whisper_prerecorded.py`

### Step 4.2 — Create local Whisper prerecorded transcription provider

Create:

- `backend/utils/stt/providers/local_whisper_prerecorded.py`

Interface:

```python
def transcribe(file_path: str) -> dict:
    return {
        "text": str,
        "segments": list,
        "language": str
    }
```

Preferred type contract:

```python
def transcribe(file_path: str) -> TranscriptionResponse:
    ...
```

### Step 4.3 — Preserve normalized transcript shape

The backend likely expects a normalized transcript/segment structure. Preserve:

- timestamps
- speaker label (even if degraded)
- text

If exact current segment schema exists in the repo, preserve it exactly and adapt provider outputs into it.

### Step 4.4 — Split streaming STT provider logic

Refactor:

- `backend/utils/stt/streaming.py`

into:
- `backend/utils/stt/providers/deepgram_streaming.py`
- `backend/utils/stt/providers/local_streaming.py`

### Step 4.5 — Create local streaming interface

Create:

- `backend/utils/stt/providers/local_streaming.py`

Interface:

```python
def start_stream(session_id: str):
    ...

def push_audio_chunk(session_id: str, chunk: bytes):
    ...

def end_stream(session_id: str) -> str:
    ...
```

Preferred async/session-safe form if integrated directly into FastAPI async flow:

```python
async def start_stream(session_id: str) -> None:
    ...

async def push_audio_chunk(session_id: str, chunk: bytes) -> None:
    ...

async def end_stream(session_id: str) -> str:
    ...
```

### Local Streaming Strategy for v1

Do **not** aim for true token-level realtime STT parity first.

Instead:
- buffer PCM frames locally
- transcribe in chunks every N seconds
- emit partial updates through the event system
- finalize transcript at stream end

### Definition of Done

- uploaded audio can be transcribed locally
- streaming sessions can accept chunks and return partial/final text
- existing consumers can still receive normalized transcript output
- no cloud STT dependency remains in local mode

### Minimum Tests

#### Test 1 — Prerecorded transcription
- valid audio file returns text

#### Test 2 — Segment shape
- output includes text, segments, language
- segment format is compatible with downstream consumers

#### Test 3 — Streaming session
- start session
- push chunks
- receive partial updates
- receive final text

### Notes / Risks

- this is one of the highest-risk migration hotspots
- exact realtime parity with Deepgram/Soniox/Speechmatics is not required initially
- local chunked transcription will have higher latency

---

## Phase 5 — VAD + Diarization Simplification

### Objective

Keep segmentation workable while reducing dependency on cloud/provider-specific speech metadata.

### Existing File

- `backend/utils/stt/vad.py`

### New File

- `backend/utils/stt/local_vad.py`

### Step 5.1 — Replace or isolate VAD

Create:

- `backend/utils/stt/local_vad.py`

Interface:

```python
def detect_speech(audio_chunk: bytes) -> bool:
    ...
```

### Required Strategy

- if existing `utils/stt/vad.py` already works locally enough, it may remain temporarily
- provider-specific STT logic must not remain entangled with VAD decisions
- diarization should be downgraded initially if required

### Required Feature Flag

Add:

```env
ENABLE_DIARIZATION=false
```

### Initial Local Behavior

Use one of:
- single-speaker mode, or
- heuristic speaker labeling for prerecorded audio only

### Definition of Done

- VAD decisions work locally enough for chunking/segmentation
- local mode does not depend on cloud diarization
- downstream transcript consumers do not crash when speaker fidelity is reduced

### Minimum Tests

- silence chunk returns false
- speech chunk returns true
- transcript pipeline functions with diarization disabled

### Notes / Risks

- diarization parity is intentionally deferred
- if current code assumes exact cloud speaker labels, adapters may be needed

---

## Phase 6 — Database Replacement (Firestore → SQL Layer)

### Objective

Replace Firestore-backed persistence with a local SQL-backed storage layer.

### Existing Files / Hotspots

- `backend/database/conversations.py`
- `backend/database/users.py`
- possibly:
  - `backend/database/memories.py`
  - `backend/database/action_items.py`
  - `backend/database/apps.py`

### New Directory

- `backend/database/sql/`

### New Files

- `backend/database/sql/models.py`
- `backend/database/sql/db.py`

### Step 6.1 — Create SQL layer

Create the SQL persistence layer in:

- `backend/database/sql/`

### Step 6.2 — Define models

At minimum, define models for:

- `User`
- `Conversation`
- `Message`

Minimum conceptual model examples:

```python
class User:
    id: str
    email: str
    password_hash: str

class Conversation:
    id: str
    user_id: str
    created_at: datetime

class Message:
    id: str
    conversation_id: str
    text: str
```

Recommended additions for real compatibility:

- `role`
- `created_at`
- `updated_at`
- `metadata`
- ordering/index fields if conversation ordering is implicit today

If current backend stores more entities, also add:

- memories
- action items
- folders/goals if needed for parity
- transcript segments if downstream logic expects them

### Step 6.3 — Refactor conversation storage

Refactor:

- `backend/database/conversations.py`

to call the SQL layer instead of Firestore.

Then progressively refactor:
- `backend/database/users.py`
- `backend/database/memories.py`
- `backend/database/action_items.py`
- `backend/database/apps.py`

### Storage Strategy

- Start with SQLite for local development and first working milestone.
- Consider Postgres later only if concurrency or data volume requires it.

### Redis Strategy

- Keep local Redis only if existing backend assumptions make it hard to remove immediately.
- Do not use Redis as the primary persistence layer.

### Definition of Done

- users, conversations, and messages can be created and retrieved locally
- no Firestore references remain in local mode
- conversation history survives app restarts
- downstream logic works against SQL-backed records

### Minimum Tests

#### Test 1 — User creation
- user row created successfully

#### Test 2 — Conversation creation
- conversation linked to user

#### Test 3 — Message persistence
- message saved with correct conversation linkage and role

#### Test 4 — Retrieval
- conversation history can be loaded in order

### Notes / Risks

- Firestore’s document model may not map 1:1 to SQL tables
- implicit ordering behavior must be made explicit
- timestamps and metadata fields are easy to under-specify; do not omit them if downstream code uses them

---

## Phase 7 — Auth Replacement (Firebase → Local JWT)

### Objective

Replace Firebase auth and token verification with local account management and JWT-based auth.

### Existing Files

- `backend/routers/auth.py`
- `backend/routers/oauth.py`
- likely auth-related logic in `backend/dependencies.py`

### New Files

- `backend/auth/local_auth.py`

Optionally also:
- `backend/database/auth_local.py`

### Step 7.1 — Create local auth provider

Create:

- `backend/auth/local_auth.py`

Interface:

```python
def register(email: str, password: str) -> dict:
    ...

def login(email: str, password: str) -> str:
    ...

def verify_token(token: str) -> dict:
    ...
```

Preferred typed behavior:
- `register()` returns user identity details
- `login()` returns JWT access token or structured auth response
- `verify_token()` returns validated token payload

### Step 7.2 — Replace router logic

Modify:

- `backend/routers/auth.py`

Remove Firebase verification logic and route auth through `local_auth`.

### Step 7.3 — Disable OAuth in local-only mode

Modify:

- `backend/routers/oauth.py`

Choose one:
- disable routes in local mode
- return `501 Not Implemented`

### Step 7.4 — Remove dependency coupling

Modify any dependency guards in:

- `backend/dependencies.py`

so route protection uses local JWT verification rather than Firebase SDK checks.

### Step 7.5 — Add bootstrap admin option

Recommended env bootstrap:

```env
BOOTSTRAP_ADMIN_EMAIL=admin@example.local
BOOTSTRAP_ADMIN_PASSWORD=change-me
```

Use only for local setup convenience if needed.

### Definition of Done

- user can register locally
- user can log in locally
- protected routes accept valid local JWTs
- Firebase is not required in local mode
- OAuth endpoints are explicitly disabled or gated

### Minimum Tests

#### Test 1 — Register
- returns created user

#### Test 2 — Login
- returns token

#### Test 3 — Verify token
- valid token resolves to user identity

#### Test 4 — Protected route
- authorized request succeeds
- invalid token fails

### Notes / Risks

- current code may assume Firebase claim shape
- dependency adapters may be required to preserve existing request user context

---

## Phase 8 — Events Replacement (Pusher → WebSockets)

### Objective

Replace Pusher-based realtime delivery with native local WebSocket-based event broadcasting.

### Existing Directory

- `backend/pusher/`

### New Files

- `backend/events/connection_manager.py`

### Step 8.1 — Create connection manager

Create:

- `backend/events/connection_manager.py`

Interface:

```python
class ConnectionManager:
    def connect(self, websocket):
        ...

    def broadcast(self, message: dict):
        ...
```

Preferred async interface:

```python
class ConnectionManager:
    async def connect(self, websocket) -> None:
        ...

    async def disconnect(self, websocket) -> None:
        ...

    async def broadcast(self, message: dict) -> None:
        ...
```

### Step 8.2 — Replace Pusher usage

Replace references under:

- `backend/pusher/`

with local broadcasting calls such as:

```python
manager.broadcast(...)
```

### Step 8.3 — Add WebSocket route

Modify:

- `backend/main.py`

Add:

```python
@app.websocket("/ws")
async def websocket_endpoint(ws):
    ...
```

### Optional Fallback

If the backend already assumes cross-worker pub/sub:
- local Redis Pub/Sub may be used behind WebSockets
- but the public realtime interface should remain WebSocket-driven

### Definition of Done

- clients can connect locally over WebSockets
- transcript/chat updates are broadcast locally
- no Pusher dependency remains in local mode

### Minimum Tests

#### Test 1 — WebSocket connect
- client connects successfully

#### Test 2 — Broadcast
- connected clients receive event payload

#### Test 3 — Disconnect handling
- stale/disconnected clients are removed without crashing broadcast flow

### Notes / Risks

- connection lifecycle management matters
- blocking broadcast logic will harm realtime UX
- message schema should be preserved if frontend expects an existing event shape

---

## Phase 9 — Search Replacement / Disablement (Typesense)

### Objective

Safely disable hosted search first, then optionally replace with a local search implementation.

### Existing Directory

- `backend/typesense/`

### Step 9.1 — Disable first

For the first local build:
- comment out usage
- gate routes behind provider flags
- or return a clear unsupported response

### Step 9.2 — Optional local replacement

Create if needed later:

- `backend/search/local_search.py`

Interface:

```python
def search(query: str):
    ...
```

Preferred initial local replacement:
- SQLite FTS5 for straightforward local search

Potential later replacement:
- Meilisearch if fuzzy search is needed

### Definition of Done

- local mode does not require Typesense
- app still starts and core flows work without hosted search
- search routes either work locally or fail explicitly and safely

### Minimum Tests

- app boots without Typesense
- disabled search path returns explicit response instead of crashing

### Notes / Risks

- search is optional for first local milestone
- do not block the core migration on search parity

---

## Phase 10 — Remove Non-Core Cloud Features

### Objective

Strip or explicitly disable cloud features that are not required for the first local-only milestone.

### Paths / Areas to Remove or Disable

| Path / Feature | Action |
|---|---|
| `backend/modal/` | remove or disable |
| `backend/utils/billing/` | remove or disable |
| Stripe references | remove or disable |
| Google Maps usage | remove or disable |
| Mixpanel usage | remove or disable |
| Hume integrations | remove or disable |
| Perplexity integrations | remove or disable |
| LangSmith tracing/prompt fetch | remove or disable |
| hosted Pusher URLs | remove or disable |
| RapidAPI integrations | remove or disable |
| optional GitHub token features not needed for local core | disable initially |
| Whoop integration OAuth | disable initially |
| Notion integration OAuth | disable initially |
| Google integration OAuth | disable initially |
| Twitter integration OAuth | disable initially |

These feature areas were identified as non-core for the first local-only milestone and should not block the migration path. fileciteturn1file0

### Definition of Done

- none of these features are required for app startup
- app does not crash if they are absent
- disabled features fail explicitly rather than implicitly

### Minimum Tests

- app boots with these integrations disabled
- core audio/chat/memory/auth/event flows still function

---

## Phase 11 — Final Wiring

### Objective

Ensure all routers and services resolve local providers end-to-end.

### Final Expected Provider Mapping

- STT → `local_whisper`
- LLM → `ollama`
- embeddings → local embeddings implementation
- vector DB → `qdrant`
- DB → `sqlite`
- auth → local JWT auth
- events → WebSockets
- search → disabled initially or local search if implemented

### Final Target Architecture

```text
audio
  ↓
VAD (local)
  ↓
Whisper (local)
  ↓
embeddings (local)
  ↓
Qdrant (local)
  ↓
Ollama (local)
  ↓
WebSocket events
  ↓
SQLite storage
```

### Definition of Done

- all core routes function without external APIs or cloud services
- all provider paths are local
- end-to-end flow works reliably
- disabled cloud features do not break startup or runtime
- all remaining runtime dependencies are local system dependencies only

---

# File-by-File Starting Order

These are the first files to modify, in recommended order:

1. `backend/.env.template`
2. `backend/dependencies.py`
3. `backend/main.py`
4. `backend/utils/llm/clients.py`
5. `backend/database/vector_db.py`
6. `backend/utils/stt/pre_recorded.py`
7. `backend/utils/stt/streaming.py`
8. `backend/database/conversations.py`
9. `backend/database/users.py`
10. `backend/routers/auth.py`
11. `backend/routers/oauth.py`
12. anything under `backend/pusher/`
13. anything under `backend/typesense/`

This starting order was part of the repo-grounded earlier migration checklist and remains the safest practical sequence for minimizing breakage while converting the backend incrementally. fileciteturn1file0

---

# What Not To Do Yet

Do **not** start with any of the following:

- full realtime streaming STT parity
- cloud plugin replacement across the whole ecosystem
- analytics parity
- billing parity
- every OAuth integration
- exact Deepgram diarization parity
- large-scale architectural rewrites
- frontend rewrites unless forced by event schema changes

These are lower priority than proving the backend can complete its core local loop.

---

# Lowest-Risk Initial Stack

Use this stack first:

- Ollama for LLM
- sentence-transformers or equivalent local embeddings provider
- Qdrant for vectors
- SQLite for primary persistence
- local Redis only if the backend strongly assumes it
- local prerecorded Whisper before local streaming STT parity work
- FastAPI WebSockets instead of Pusher

This is the smallest practical path to a working fully local backend while staying close to current module boundaries. fileciteturn1file0

---

# Detailed Testing Plan

## Global Testing Rules

Each phase must include:
- import validation
- startup validation
- one direct provider test
- one integration test
- regression check for upstream callers that depend on preserved interfaces

---

## Phase-by-Phase Minimum Test Matrix

### Phase 0
- app boots
- provider env vars parse correctly
- resolver functions return valid provider values

### Phase 1
- local chat responds
- streaming path produces chunks if required
- no runtime OpenAI dependency in local mode

### Phase 2
- single embed works
- batch embed works
- dimensions are stable

### Phase 3
- vector upsert works
- vector query returns correct shape
- delete works
- namespace mapping strategy does not break retrieval semantics

### Phase 4
- prerecorded audio transcription works
- transcript output shape matches downstream expectations
- local streaming path can produce partial/final text

### Phase 5
- VAD works for basic segmentation
- diarization-disabled mode does not break transcript consumers

### Phase 6
- user creation works
- conversation creation works
- messages persist and load in order
- data survives restart

### Phase 7
- register works
- login works
- verify token works
- protected routes enforce auth

### Phase 8
- websocket connect works
- broadcast works
- disconnect works cleanly

### Phase 9
- search disabled mode does not crash startup
- disabled routes respond explicitly

### Phase 10
- disabled cloud features do not break startup
- no hard dependency remains on stripped features

### Phase 11
- end-to-end local-only flow works with no cloud credentials configured

---

# End-to-End Example

## Input

Audio file uploaded to a transcription endpoint such as `/transcribe`

## Required Flow

1. local prerecorded transcription provider is called
2. transcript text is returned
3. transcript is normalized into backend segment shape
4. text is embedded using the local embeddings provider
5. embeddings are stored in Qdrant
6. LLM receives relevant memory/context and generates a response via Ollama
7. realtime updates are broadcast over WebSockets
8. conversation and/or message records are saved to SQLite

## Success Criteria

- no cloud API call is required
- no cloud credentials are required
- all artifacts are stored/retrieved locally
- the flow completes without unsupported dependency crashes

---

# Compatibility / Adapter Strategy

Where the existing codebase expects legacy behavior, prefer adapters over broad rewrites.

## Use adapters when:

- old code expects plain strings but new provider returns structured responses
- old code expects Firebase-like user context but new auth uses JWT payloads
- old code expects Pinecone-style namespace semantics
- old code expects Deepgram-style transcript shape

## Adapter principle

Normalize provider-specific outputs into the shapes already expected by the rest of the backend whenever possible.

---

# Known Migration Risks

These must be treated as expected implementation hazards, not surprises:

1. **Embedding dimension mismatch**
   - local embeddings may not match OpenAI dimensions
   - Qdrant collection config must match the selected local model

2. **Transcript shape mismatch**
   - local Whisper outputs may not match current Deepgram-normalized segment structure
   - adapter normalization is required

3. **Streaming parity gap**
   - local chunked STT will likely have worse latency than current cloud streaming

4. **Diarization degradation**
   - local mode may need single-speaker fallback initially

5. **Auth payload mismatch**
   - route dependencies may currently assume Firebase claim structure

6. **Event payload drift**
   - frontend/client code may assume an existing Pusher event schema

7. **Firestore → SQL mapping**
   - nested document-style data may require explicit relational modeling

8. **Redis assumptions**
   - some flows may rely on Redis implicitly even if it is not the primary database

---

# Behavior Downgrade Policy

If parity cannot be preserved immediately, degrade behavior in this order:

1. preserve core functionality
2. preserve interface shape
3. preserve data shape
4. preserve latency/performance
5. preserve optional feature richness

Examples:
- accept slower local streaming before chasing parity
- accept reduced diarization before introducing complex local speaker systems
- disable hosted search before blocking on local fuzzy search

---

# Completion Criteria

The migration is complete when all of the following are true:

- all core endpoints function without external APIs or cloud services
- the app can boot without cloud credentials
- the selected providers are all local or explicitly disabled
- audio ingestion, transcription, conversation save, memory retrieval, LLM generation, and realtime updates work end-to-end
- disabled cloud integrations fail explicitly rather than causing hidden runtime breakage
- no runtime path in local mode requires Firebase, OpenAI, Deepgram, Pinecone, Pusher, Typesense, Stripe, or other hosted services

---

# Final Short Operational Summary

If implementing this with an LLM coding agent, the intended execution order is:

1. freeze upstream state
2. add provider env/config + resolver layer
3. split LLM code into provider modules
4. split embeddings into provider modules
5. replace Pinecone with Qdrant
6. replace prerecorded STT first
7. add chunked local streaming STT
8. isolate/simplify VAD and diarization
9. replace Firestore with SQLite-backed SQL layer
10. replace Firebase auth with local JWT auth
11. replace Pusher with WebSockets
12. disable Typesense and optional cloud features
13. perform end-to-end validation
14. only then expand parity for optional features

This order is deliberate. It minimizes breakage, preserves module boundaries, and yields a working local backend as early as possible.


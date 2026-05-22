# ── LOCAL ONLY — this entire file has no upstream equivalent ──
"""Runtime provider resolver.

Single source of truth for which implementation each subsystem should use at
runtime. Every router/service that wants to swap a cloud dependency for a local
one must read selection through one of these getters; never via direct env
lookups elsewhere.

The resolver is intentionally side-effect free: importing this module never
instantiates a client. Callers (router/factory modules) decide when to import
the concrete provider implementation.

See omi_local_backend_merged_final.md for the full migration spec.
"""

import os
from typing import Literal

StrLiteral = str  # alias to keep call sites readable

LLMProvider = Literal["openai", "ollama"]
STTProvider = Literal["deepgram", "local"]
EmbeddingsProvider = Literal["openai", "local"]
VectorDBProvider = Literal["pinecone", "qdrant"]
AuthProvider = Literal["firebase", "local"]
DBProvider = Literal["firestore", "sqlite", "postgres"]
EventProvider = Literal["pusher", "websocket"]
SearchProvider = Literal["typesense", "disabled", "local"]


def _read(name: str, default: str) -> str:
    val = os.getenv(name)
    return val.strip().lower() if val else default


def get_llm_provider() -> LLMProvider:
    val = _read("LLM_PROVIDER", "openai")
    if val not in ("openai", "ollama"):
        return "openai"
    return val  # type: ignore[return-value]


def get_stt_provider() -> STTProvider:
    val = _read("STT_PROVIDER", "deepgram")
    if val not in ("deepgram", "local"):
        return "deepgram"
    return val  # type: ignore[return-value]


def get_embeddings_provider() -> EmbeddingsProvider:
    val = _read("EMBEDDINGS_PROVIDER", "openai")
    if val not in ("openai", "local"):
        return "openai"
    return val  # type: ignore[return-value]


def get_vector_db_provider() -> VectorDBProvider:
    val = _read("VECTOR_DB_PROVIDER", "pinecone")
    if val not in ("pinecone", "qdrant"):
        return "pinecone"
    return val  # type: ignore[return-value]


def get_auth_provider() -> AuthProvider:
    val = _read("AUTH_PROVIDER", "firebase")
    if val not in ("firebase", "local"):
        return "firebase"
    return val  # type: ignore[return-value]


def get_db_provider() -> DBProvider:
    val = _read("DB_PROVIDER", "firestore")
    if val not in ("firestore", "sqlite", "postgres"):
        return "firestore"
    return val  # type: ignore[return-value]


def get_event_provider() -> EventProvider:
    val = _read("EVENT_PROVIDER", "pusher")
    if val not in ("pusher", "websocket"):
        return "pusher"
    return val  # type: ignore[return-value]


def get_search_provider() -> SearchProvider:
    val = _read("SEARCH_PROVIDER", "typesense")
    if val not in ("typesense", "disabled", "local"):
        return "typesense"
    return val  # type: ignore[return-value]


def diarization_enabled() -> bool:
    return _read("ENABLE_DIARIZATION", "true") in ("1", "true", "yes", "on")


def is_local_mode() -> bool:
    """True when every subsystem is configured for local/no-cloud operation."""
    return (
        get_llm_provider() == "ollama"
        and get_stt_provider() == "local"
        and get_embeddings_provider() == "local"
        and get_vector_db_provider() == "qdrant"
        and get_auth_provider() == "local"
        and get_db_provider() == "sqlite"
        and get_event_provider() == "websocket"
    )

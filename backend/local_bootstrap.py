"""Local-mode startup helper.

When the backend boots with the local providers selected (see
``providers.is_local_mode()``), call ``bootstrap_local()`` early in
``main.py`` to:

  - create the SQLite schema
  - register the bootstrap admin user (env-driven)
  - log the active provider matrix so the operator sees what's wired

It's a no-op when any provider is still set to its cloud default — useful so
the helper can be unconditionally imported.
"""

import logging
import os
import stat
from typing import Dict

import httpx

logger = logging.getLogger(__name__)


def _probe_ollama() -> None:
    host = (os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
    try:
        httpx.get(f"{host}/api/version", timeout=5.0).raise_for_status()
        logger.info("Ollama reachable at %s", host)
    except Exception as exc:
        logger.warning("Ollama not reachable at startup (%s): %s — chat endpoints will fail until it is running", host, exc)


def _probe_qdrant() -> None:
    url = (os.environ.get("QDRANT_URL") or "http://localhost:6333").rstrip("/")
    try:
        httpx.get(f"{url}/healthz", timeout=5.0)
        logger.info("Qdrant reachable at %s", url)
    except Exception as exc:
        logger.warning("Qdrant not reachable at startup (%s): %s — vector search will fail until it is running", url, exc)


def _provider_matrix() -> Dict[str, str]:
    from providers import (
        diarization_enabled,
        get_auth_provider,
        get_db_provider,
        get_embeddings_provider,
        get_event_provider,
        get_llm_provider,
        get_search_provider,
        get_stt_provider,
        get_vector_db_provider,
    )

    return {
        "stt": get_stt_provider(),
        "llm": get_llm_provider(),
        "embeddings": get_embeddings_provider(),
        "vector_db": get_vector_db_provider(),
        "auth": get_auth_provider(),
        "db": get_db_provider(),
        "events": get_event_provider(),
        "search": get_search_provider(),
        "diarization": "on" if diarization_enabled() else "off",
    }


def log_provider_matrix() -> None:
    matrix = _provider_matrix()
    rendered = ", ".join(f"{k}={v}" for k, v in matrix.items())
    logger.info("Provider matrix: %s", rendered)


def bootstrap_local() -> None:
    log_provider_matrix()

    from providers import get_auth_provider, get_db_provider, get_llm_provider, get_vector_db_provider

    if get_db_provider() == "sqlite":
        from database.sql.db import init_db

        init_db()
        logger.info("SQLite schema initialized")
        sqlite_path = os.environ.get("SQLITE_PATH", "./omi_local.db")
        if os.path.exists(sqlite_path):
            os.chmod(sqlite_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600

    if get_auth_provider() == "local":
        from auth.local_auth import bootstrap_admin_if_needed

        bootstrap_admin_if_needed()

    if not os.environ.get("REDIS_DB_HOST"):
        logger.info(
            "REDIS_DB_HOST not set — Redis rate-limiting, fair-use tracking, and pub/sub are disabled (fail-open)"
        )

    if get_llm_provider() == "ollama":
        _probe_ollama()

    if get_vector_db_provider() == "qdrant":
        _probe_qdrant()

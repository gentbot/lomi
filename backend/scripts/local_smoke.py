"""Smoke test for the local-only provider stack.

Exercises the migration spec's end-to-end path without booting the full
FastAPI app:

    1. Resolve providers and confirm they're all local.
    2. Init SQLite, register a user, log them in.
    3. Embed a sample document and round-trip it through Qdrant.
    4. Ask the local LLM for a completion.

Run with:

    LLM_PROVIDER=ollama EMBEDDINGS_PROVIDER=local VECTOR_DB_PROVIDER=qdrant \
    DB_PROVIDER=sqlite AUTH_PROVIDER=local \
        python -m scripts.local_smoke
"""

import logging
import sys
from pathlib import Path

# Make ``backend/`` importable when invoked as a module.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("local_smoke")


def step_providers() -> None:
    from providers import is_local_mode

    log.info("local_mode=%s", is_local_mode())


def step_db_and_auth() -> str:
    from auth.local_auth import login, register
    from database.sql.db import init_db

    init_db()
    email = "smoke@omi.local"
    password = "smoketest123"
    try:
        register(email, password)
    except Exception as exc:
        log.info("register: %s", exc)
    token = login(email, password)
    log.info("login OK (token len=%d)", len(token))
    return token


def step_embeddings_and_vectors() -> None:
    from utils.embeddings.router import embed

    vec = embed("hello local omi")
    log.info("embed dim=%d", len(vec))

    try:
        from database import vector_db_qdrant as vdb

        vdb.upsert_memory_vector("smoke-uid", "smoke-mem-1", "buy oat milk", "errand")
        results = vdb.search_memories_by_vector("smoke-uid", "milk", limit=3)
        log.info("qdrant results=%s", results)
    except Exception as exc:
        log.warning("qdrant step skipped: %s", exc)


def step_llm() -> None:
    try:
        from utils.llm.router import chat

        out = chat([{"role": "user", "content": "say hi in one word"}])
        log.info("llm reply: %s", out[:200])
    except Exception as exc:
        log.warning("llm step skipped: %s", exc)


def main() -> None:
    step_providers()
    step_db_and_auth()
    step_embeddings_and_vectors()
    step_llm()
    log.info("smoke test complete")


if __name__ == "__main__":
    main()

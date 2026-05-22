"""Local-only FastAPI entrypoint.

This is the runnable counterpart to the scaffolding created in Phases 0–11 of
the migration spec (see ``MIGRATION_STATUS.md``). It deliberately does **not**
import the existing 45-router production app: those routers chain into
Firebase/OpenAI/Pinecone/Pusher/Deepgram clients at import time, which would
crash without cloud credentials. Once the cutover work in §3.1–§3.13 of
MIGRATION_STATUS.md is done, ``main.py`` can become a guarded version of this
file. Until then this is the supported local entrypoint:

    conda activate omilocal
    uvicorn main_local:app --reload --port 8080
"""

import logging
import os

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from local_bootstrap import bootstrap_local  # noqa: E402
from providers import is_local_mode  # noqa: E402
from routers_local import action_items as local_action_items_router  # noqa: E402
from routers_local import admin as local_admin_router  # noqa: E402
from routers_local import auth as local_auth_router  # noqa: E402
from routers_local import config as local_config_router  # noqa: E402
from routers_local import docs as local_docs_router  # noqa: E402
from routers_local import chat as local_chat_router  # noqa: E402
from routers_local import conversations as local_conversations_router  # noqa: E402
from routers_local import knowledge_graph as local_knowledge_graph_router  # noqa: E402
from routers_local import memories as local_memories_router  # noqa: E402
from routers_local import transcribe as local_transcribe_router  # noqa: E402
from routers_local import listen as local_listen_router  # noqa: E402
from routers_local import sync as local_sync_router  # noqa: E402
from routers_local import tts as local_tts_router  # noqa: E402
from routers_local import ws as local_ws_router  # noqa: E402
from routers_local import apps_local as local_apps_router  # noqa: E402
from routers_local import chat_sessions as local_chat_sessions_router  # noqa: E402
from routers_local import desktop_messages as local_desktop_messages_router  # noqa: E402
from routers_local import staged_tasks as local_staged_tasks_router  # noqa: E402
from routers_local import users_local as local_users_router  # noqa: E402
from routers_local.memories import router_v3 as local_memories_v3_router  # noqa: E402

logger = logging.getLogger(__name__)

app = FastAPI(title="Omi Local Backend", version="0.1.0-local")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional Swagger/ReDoc access control.
# When DOCS_API_KEY is set, GET /docs, /redoc, and /openapi.json require
# the key via ?key=<value> or the X-Docs-Key header.
# Leave DOCS_API_KEY unset (default) to keep /docs publicly accessible.
_DOCS_API_KEY = os.environ.get("DOCS_API_KEY", "").strip()
if _DOCS_API_KEY:
    _DOCS_PATHS = {"/docs", "/redoc", "/openapi.json"}

    @app.middleware("http")
    async def _protect_docs(request: Request, call_next):
        if request.url.path in _DOCS_PATHS:
            key = request.headers.get("x-docs-key") or request.query_params.get("key", "")
            if key != _DOCS_API_KEY:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Unauthorized. Pass ?key=<DOCS_API_KEY> or X-Docs-Key header."},
                )
        return await call_next(request)


@app.on_event("startup")
async def _startup() -> None:
    bootstrap_local()
    if not is_local_mode():
        logger.warning(
            "main_local started but providers.is_local_mode() is False. "
            "Some routes may attempt cloud calls."
        )


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/healthz")
def healthz() -> dict:
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
        "ok": True,
        "local_mode": is_local_mode(),
        "providers": {
            "llm": get_llm_provider(),
            "stt": get_stt_provider(),
            "embeddings": get_embeddings_provider(),
            "vector_db": get_vector_db_provider(),
            "auth": get_auth_provider(),
            "db": get_db_provider(),
            "events": get_event_provider(),
            "search": get_search_provider(),
            "diarization": diarization_enabled(),
        },
    }


app.include_router(local_auth_router.router)
app.include_router(local_admin_router.router)
app.include_router(local_config_router.router)
app.include_router(local_docs_router.router)
app.include_router(local_chat_router.router)
app.include_router(local_conversations_router.router)
app.include_router(local_memories_router.router)
app.include_router(local_action_items_router.router)
app.include_router(local_transcribe_router.router)
app.include_router(local_ws_router.router)
app.include_router(local_knowledge_graph_router.router)
app.include_router(local_tts_router.router)
app.include_router(local_listen_router.router)
app.include_router(local_sync_router.router)
app.include_router(local_desktop_messages_router.router)
app.include_router(local_users_router.router)
app.include_router(local_memories_v3_router)
app.include_router(local_chat_sessions_router.router)
app.include_router(local_apps_router.router)
app.include_router(local_staged_tasks_router.router)

# Serve the local admin UI. Prefer admin_local/ (our modified version) over admin/
# (upstream version) so that admin/index.html can track upstream without conflicts.
_admin_dir = os.path.join(os.path.dirname(__file__), "admin_local")
if not os.path.isdir(_admin_dir):
    _admin_dir = os.path.join(os.path.dirname(__file__), "admin")
if os.path.isdir(_admin_dir):
    app.mount("/admin", StaticFiles(directory=_admin_dir, html=True), name="admin")

# Ensure local upload/scratch dirs exist (mirrors the original main.py).
for path in ("_temp", "_samples", "_segments", "_speech_profiles"):
    if not os.path.exists(path):
        os.makedirs(path)

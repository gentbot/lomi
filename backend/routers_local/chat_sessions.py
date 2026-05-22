"""v2/chat-sessions CRUD + v2/chat helper endpoints (generate-title, initial-message)."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator

from auth.router_dep import get_current_user_id_local
from database.sql import repository
from utils.llm import router as llm_router

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat-sessions"])


class ChatSessionView(BaseModel):
    id: str
    user_id: str
    title: str
    preview: Optional[str] = None
    app_id: Optional[str] = None
    message_count: int = 0
    starred: bool = False
    created_at: datetime
    updated_at: datetime

    @model_validator(mode='before')
    @classmethod
    def _utc_dates(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            for field in ('created_at', 'updated_at'):
                v = data.get(field)
                if isinstance(v, datetime) and v.tzinfo is None:
                    data[field] = v.replace(tzinfo=timezone.utc)
        return data


class CreateSessionRequest(BaseModel):
    title: Optional[str] = None
    app_id: Optional[str] = None


class UpdateSessionRequest(BaseModel):
    title: Optional[str] = None
    starred: Optional[bool] = None


class GenerateTitleRequest(BaseModel):
    session_id: str
    messages: List[dict]


class GenerateTitleResponse(BaseModel):
    title: str


class InitialMessageRequest(BaseModel):
    session_id: str
    app_id: Optional[str] = None


class InitialMessageResponse(BaseModel):
    message: str
    message_id: str


@router.get("/v2/chat-sessions", response_model=List[ChatSessionView])
async def list_sessions(
    app_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    starred: Optional[bool] = None,
    user_id: str = Depends(get_current_user_id_local),
) -> List[ChatSessionView]:
    rows = await asyncio.to_thread(
        repository.list_chat_sessions,
        user_id,
        app_id=app_id,
        starred=starred,
        limit=limit,
        offset=offset,
    )
    return [ChatSessionView(**r) for r in rows]


@router.post("/v2/chat-sessions", response_model=ChatSessionView)
async def create_session(
    req: CreateSessionRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> ChatSessionView:
    row = await asyncio.to_thread(
        repository.create_chat_session,
        user_id,
        title=req.title,
        app_id=req.app_id,
    )
    return ChatSessionView(**row)


@router.patch("/v2/chat-sessions/{session_id}", response_model=ChatSessionView)
async def update_session(
    session_id: str,
    req: UpdateSessionRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> ChatSessionView:
    row = await asyncio.to_thread(
        repository.update_chat_session,
        user_id,
        session_id,
        title=req.title,
        starred=req.starred,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    return ChatSessionView(**row)


@router.delete("/v2/chat-sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id_local),
) -> None:
    deleted = await asyncio.to_thread(repository.delete_chat_session, user_id, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="session not found")


@router.post("/v2/chat/generate-title", response_model=GenerateTitleResponse)
async def generate_title(
    req: GenerateTitleRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> GenerateTitleResponse:
    snippet = " | ".join(
        m.get("text", "")[:80] for m in req.messages[:6] if m.get("text")
    )
    prompt = [
        {"role": "system", "content": "Generate a short 3-6 word title for this chat. Reply with only the title, no punctuation."},
        {"role": "user", "content": snippet or "New conversation"},
    ]
    try:
        title = (await llm_router.achat(prompt)).strip().strip('"').strip("'")
    except Exception:
        title = "New Chat"

    await asyncio.to_thread(
        repository.update_chat_session, user_id, req.session_id, title=title
    )
    return GenerateTitleResponse(title=title)


@router.post("/v2/chat/initial-message", response_model=InitialMessageResponse)
async def initial_message(
    req: InitialMessageRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> InitialMessageResponse:
    prompt = [
        {
            "role": "system",
            "content": "You are Omi, a personal AI assistant. Greet the user briefly and offer to help. 1-2 sentences max.",
        },
        {"role": "user", "content": "Hello"},
    ]
    try:
        text = (await llm_router.achat(prompt)).strip()
    except Exception:
        text = "Hi! I'm Omi, your personal AI assistant. How can I help you today?"

    msg_id = str(uuid4())
    await asyncio.to_thread(
        repository.save_chat_message,
        user_id,
        text,
        "ai",
        session_id=req.session_id,
        app_id=req.app_id,
    )
    return InitialMessageResponse(message=text, message_id=msg_id)

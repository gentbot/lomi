"""Desktop chat messages — standalone messages not tied to a Conversation."""

import asyncio
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator

from auth.router_dep import get_current_user_id_local
from database.sql import repository

router = APIRouter(tags=["desktop-messages"])


class SendMessageRequest(BaseModel):
    text: str
    sender: str
    app_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Optional[str] = None


class ChatMessageView(BaseModel):
    id: str
    user_id: str
    text: str
    sender: str
    app_id: Optional[str] = None
    session_id: Optional[str] = None
    rating: Optional[int] = None
    created_at: Optional[datetime] = None

    @model_validator(mode='before')
    @classmethod
    def _utc_dates(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            v = data.get('created_at')
            if isinstance(v, datetime) and v.tzinfo is None:
                data['created_at'] = v.replace(tzinfo=timezone.utc)
        return data


class RatingRequest(BaseModel):
    rating: int


@router.get("/v2/desktop/messages", response_model=List[ChatMessageView])
async def list_desktop_messages(
    app_id: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user_id: str = Depends(get_current_user_id_local),
) -> List[ChatMessageView]:
    rows = await asyncio.to_thread(
        repository.list_chat_messages,
        user_id,
        app_id=app_id,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )
    return [ChatMessageView(**r) for r in rows]


@router.post("/v2/desktop/messages", response_model=ChatMessageView)
async def save_desktop_message(
    req: SendMessageRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> ChatMessageView:
    row = await asyncio.to_thread(
        repository.save_chat_message,
        user_id,
        req.text,
        req.sender,
        app_id=req.app_id,
        session_id=req.session_id,
        metadata=req.metadata,
    )
    return ChatMessageView(**row)


@router.delete("/v2/desktop/messages")
async def delete_desktop_messages(
    app_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: str = Depends(get_current_user_id_local),
) -> dict:
    count = await asyncio.to_thread(
        repository.delete_chat_messages,
        user_id,
        app_id=app_id,
        session_id=session_id,
    )
    return {"deleted": count}


@router.patch("/v2/desktop/messages/{message_id}/rating", response_model=ChatMessageView)
async def rate_desktop_message(
    message_id: str,
    req: RatingRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> ChatMessageView:
    row = await asyncio.to_thread(repository.update_chat_message_rating, user_id, message_id, req.rating)
    if row is None:
        raise HTTPException(status_code=404, detail="message not found")
    return ChatMessageView(**row)

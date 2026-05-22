"""Local conversation CRUD backed by SQLite (Phase 6 cutover)."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator

from auth.router_dep import get_current_user_id_local
from database.sql import repository

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


class CreateConversationRequest(BaseModel):
    title: Optional[str] = None
    transcript_segments: Optional[list] = None


class ConversationView(BaseModel):
    id: str
    user_id: str
    title: Optional[str] = None
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    transcript_segments: list = []
    structured: dict = {}

    @model_validator(mode='before')
    @classmethod
    def _remap_ended_at(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if 'finished_at' not in data and 'ended_at' in data:
                data['finished_at'] = data.pop('ended_at')
            for field in ('created_at', 'started_at', 'finished_at'):
                v = data.get(field)
                if isinstance(v, datetime) and v.tzinfo is None:
                    data[field] = v.replace(tzinfo=timezone.utc)
        return data


class CreateMessageRequest(BaseModel):
    role: str
    text: str


class MessageView(BaseModel):
    id: str
    conversation_id: str
    role: str
    text: str
    sequence: int


@router.get("/count")
def count_conversations(
    statuses: Optional[str] = Query(None),
    include_discarded: bool = True,
    user_id: str = Depends(get_current_user_id_local),
) -> dict:
    status_list = [s.strip() for s in statuses.split(",")] if statuses else None
    total = repository.count_conversations(user_id, statuses=status_list)
    return {"count": total}


@router.post("", response_model=ConversationView)
def create_conversation(
    req: CreateConversationRequest, user_id: str = Depends(get_current_user_id_local)
) -> ConversationView:
    conv = repository.create_conversation(
        user_id,
        title=req.title,
        transcript_segments=req.transcript_segments or [],
    )
    return ConversationView(**conv)


@router.get("", response_model=List[ConversationView])
def list_conversations(
    user_id: str = Depends(get_current_user_id_local),
    limit: int = 50,
    offset: int = 0,
) -> List[ConversationView]:
    rows = repository.list_conversations(user_id, limit=limit, offset=offset)
    return [ConversationView(**r) for r in rows]


@router.get("/{conversation_id}", response_model=ConversationView)
def get_conversation(
    conversation_id: str, user_id: str = Depends(get_current_user_id_local)
) -> ConversationView:
    conv = repository.get_conversation(user_id, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return ConversationView(**conv)


@router.post("/{conversation_id}/messages", response_model=MessageView)
def add_message(
    conversation_id: str,
    req: CreateMessageRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> MessageView:
    conv = repository.get_conversation(user_id, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    msg = repository.append_message(conversation_id, req.role, req.text)
    return MessageView(**msg)


@router.get("/{conversation_id}/messages", response_model=List[MessageView])
def list_messages(
    conversation_id: str, user_id: str = Depends(get_current_user_id_local)
) -> List[MessageView]:
    conv = repository.get_conversation(user_id, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return [MessageView(**m) for m in repository.list_messages(conversation_id)]


@router.patch("/{conversation_id}")
def update_conversation(
    conversation_id: str,
    title: Optional[str] = None,
    status: Optional[str] = None,
    user_id: str = Depends(get_current_user_id_local),
) -> ConversationView:
    conv = repository.update_conversation(user_id, conversation_id, title=title, status=status)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return ConversationView(**conv)


@router.delete("", status_code=200)
def delete_all_conversations(
    user_id: str = Depends(get_current_user_id_local),
) -> dict:
    count = repository.delete_all_conversations(user_id)
    return {"deleted": count}


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    user_id: str = Depends(get_current_user_id_local),
) -> None:
    deleted = repository.delete_conversation(user_id, conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="conversation not found")


class ConversationSearchRequest(BaseModel):
    query: str
    limit: int = 20


@router.post("/search", response_model=List[ConversationView])
def search_conversations(
    req: ConversationSearchRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> List[ConversationView]:
    rows = repository.search_conversations(user_id, req.query, limit=req.limit)
    return [ConversationView(**r) for r in rows]


class MergeRequest(BaseModel):
    conversation_ids: List[str]
    reprocess: bool = False


@router.post("/merge")
def merge_conversations(
    req: MergeRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> dict:
    # Stub — merging requires complex re-processing; return first conv as the result
    if req.conversation_ids:
        conv = repository.get_conversation(user_id, req.conversation_ids[0])
        if conv:
            return {"conversation": conv}
    return {"conversation": None}


@router.post("/{conversation_id}/reprocess")
def reprocess_conversation(
    conversation_id: str,
    user_id: str = Depends(get_current_user_id_local),
) -> dict:
    conv = repository.get_conversation(user_id, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"conversation": conv}


@router.patch("/{conversation_id}/folder")
def move_to_folder(
    conversation_id: str,
    folder_id: Optional[str] = None,
    user_id: str = Depends(get_current_user_id_local),
) -> dict:
    return {"status": "ok"}


@router.post("/{conversation_id}/starred")
def star_conversation(
    conversation_id: str,
    starred: bool = True,
    user_id: str = Depends(get_current_user_id_local),
) -> dict:
    return {"status": "ok", "starred": starred}


@router.post("/{conversation_id}/visibility")
def set_visibility(
    conversation_id: str,
    value: str = "shared",
    visibility: str = "shared",
    user_id: str = Depends(get_current_user_id_local),
) -> dict:
    return {"status": "ok"}


@router.post("/{conversation_id}/segments/assign-bulk")
def assign_segments_bulk(
    conversation_id: str,
    user_id: str = Depends(get_current_user_id_local),
) -> dict:
    return {"status": "ok"}

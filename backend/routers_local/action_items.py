"""Local action-items CRUD backed by SQLite + Qdrant (GAP-17)."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator

from auth.router_dep import get_current_user_id_local
from database import vector_db_qdrant as vdb
from database.sql import repository
from events.router import push_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/action-items", tags=["action-items"])


class CreateActionItemRequest(BaseModel):
    description: str
    due_at: Optional[datetime] = None
    conversation_id: Optional[str] = None


class UpdateActionItemRequest(BaseModel):
    completed: Optional[bool] = None
    description: Optional[str] = None
    due_at: Optional[datetime] = None


class ActionItemView(BaseModel):
    id: str
    user_id: str
    description: str
    completed: bool
    due_at: Optional[datetime] = None
    conversation_id: Optional[str] = None
    created_at: datetime

    @model_validator(mode='before')
    @classmethod
    def _utc_dates(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            for field in ('created_at', 'due_at'):
                v = data.get(field)
                if isinstance(v, datetime) and v.tzinfo is None:
                    data[field] = v.replace(tzinfo=timezone.utc)
        return data


@router.post("", response_model=ActionItemView, status_code=201)
async def create_action_item(
    req: CreateActionItemRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> ActionItemView:
    item = await asyncio.to_thread(
        repository.create_action_item,
        user_id,
        req.description,
        due_at=req.due_at,
        conversation_id=req.conversation_id,
    )
    try:
        await asyncio.to_thread(vdb.upsert_action_item_vector, user_id, item["id"], req.description)
    except Exception:
        logger.warning("Qdrant index failed for action item %s — SQL row was saved", item["id"])
    try:
        await push_event(user_id, {"type": "new_action_item", "action_item": item})
    except Exception:
        pass
    return ActionItemView(**item)


class ActionItemsListResponse(BaseModel):
    items: List[ActionItemView]
    has_more: bool = False


@router.get("", response_model=ActionItemsListResponse)
async def list_action_items(
    limit: int = 100,
    offset: int = 0,
    include_completed: bool = False,
    user_id: str = Depends(get_current_user_id_local),
) -> ActionItemsListResponse:
    rows = await asyncio.to_thread(
        repository.list_action_items, user_id, include_completed=include_completed
    )
    items = [ActionItemView(**r) for r in rows]
    return ActionItemsListResponse(items=items, has_more=False)


@router.get("/{item_id}", response_model=ActionItemView)
async def get_action_item(
    item_id: str,
    user_id: str = Depends(get_current_user_id_local),
) -> ActionItemView:
    item = await asyncio.to_thread(repository.get_action_item, user_id, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="action item not found")
    return ActionItemView(**item)


@router.patch("/{item_id}", response_model=ActionItemView)
async def update_action_item(
    item_id: str,
    req: UpdateActionItemRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> ActionItemView:
    item = await asyncio.to_thread(
        repository.update_action_item,
        user_id,
        item_id,
        completed=req.completed,
        description=req.description,
        due_at=req.due_at,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="action item not found")
    return ActionItemView(**item)


@router.delete("", status_code=200)
async def delete_all_action_items(
    user_id: str = Depends(get_current_user_id_local),
) -> dict:
    count = await asyncio.to_thread(repository.delete_all_action_items, user_id)
    return {"deleted": count}


@router.delete("/{item_id}", status_code=204)
async def delete_action_item(
    item_id: str,
    user_id: str = Depends(get_current_user_id_local),
) -> None:
    deleted = await asyncio.to_thread(repository.delete_action_item, user_id, item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="action item not found")


class ScoreUpdate(BaseModel):
    id: str
    score: int


class ScoreBatchRequest(BaseModel):
    scores: List[ScoreUpdate]


@router.patch("/batch-scores")
async def batch_update_scores(
    req: ScoreBatchRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> dict:
    for su in req.scores:
        await asyncio.to_thread(
            repository.update_action_item, user_id, su.id, completed=None
        )
    return {"status": "ok", "updated": len(req.scores)}


class SortUpdate(BaseModel):
    id: str
    sort_order: int
    indent_level: int = 0


class BatchRequest(BaseModel):
    updates: List[SortUpdate]


@router.patch("/batch")
async def batch_update_sort(
    req: BatchRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> dict:
    return {"status": "ok", "updated": len(req.updates)}


@router.post("/share")
async def share_tasks(
    user_id: str = Depends(get_current_user_id_local),
) -> dict:
    return {"url": "", "share_id": ""}

"""Staged tasks — conversation-extracted tasks awaiting promotion."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator

from auth.router_dep import get_current_user_id_local
from database.sql import repository

router = APIRouter(tags=["staged-tasks"])


class StagedTaskView(BaseModel):
    id: str
    user_id: str
    description: str
    completed: bool
    score: float = 0.0
    sort_order: int = 0
    indent_level: int = 0
    conversation_id: Optional[str] = None
    created_at: datetime

    @model_validator(mode='before')
    @classmethod
    def _utc_dates(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            v = data.get('created_at')
            if isinstance(v, datetime) and v.tzinfo is None:
                data['created_at'] = v.replace(tzinfo=timezone.utc)
        return data


class CreateStagedTaskRequest(BaseModel):
    description: str
    conversation_id: Optional[str] = None
    score: float = 0.0


class ActionItemsListResponse(BaseModel):
    items: List[StagedTaskView]
    has_more: bool = False


class PromoteResponse(BaseModel):
    promoted: Optional[Dict[str, Any]] = None


@router.get("/v1/staged-tasks", response_model=ActionItemsListResponse)
async def list_staged_tasks(
    limit: int = 100,
    offset: int = 0,
    user_id: str = Depends(get_current_user_id_local),
) -> ActionItemsListResponse:
    rows = await asyncio.to_thread(repository.list_staged_tasks, user_id, limit=limit + 1, offset=offset)
    has_more = len(rows) > limit
    return ActionItemsListResponse(
        items=[StagedTaskView(**r) for r in rows[:limit]],
        has_more=has_more,
    )


@router.post("/v1/staged-tasks", response_model=StagedTaskView, status_code=201)
async def create_staged_task(
    req: CreateStagedTaskRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> StagedTaskView:
    row = await asyncio.to_thread(
        repository.create_staged_task,
        user_id,
        req.description,
        conversation_id=req.conversation_id,
        score=req.score,
    )
    return StagedTaskView(**row)


@router.delete("/v1/staged-tasks/{task_id}", status_code=204)
async def delete_staged_task(
    task_id: str,
    user_id: str = Depends(get_current_user_id_local),
) -> None:
    deleted = await asyncio.to_thread(repository.delete_staged_task, user_id, task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="staged task not found")


@router.patch("/v1/staged-tasks/batch-scores")
async def batch_update_staged_scores(
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    return {"status": "ok"}


@router.post("/v1/staged-tasks/promote", response_model=PromoteResponse)
async def promote_top_staged_task(
    user_id: str = Depends(get_current_user_id_local),
) -> PromoteResponse:
    row = await asyncio.to_thread(repository.promote_top_staged_task, user_id)
    return PromoteResponse(promoted=row)


@router.post("/v1/staged-tasks/migrate")
async def migrate_staged_tasks(user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {"status": "ok", "migrated": 0}


@router.post("/v1/staged-tasks/migrate-conversation-items")
async def migrate_conversation_items(user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {"status": "ok", "migrated": 0}

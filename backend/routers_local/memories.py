"""Local memories: SQLite for primary state + Qdrant for semantic search (Phase 2/3 cutover)."""

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

router = APIRouter(prefix="/v1/memories", tags=["memories"])
router_v3 = APIRouter(prefix="/v3/memories", tags=["memories"])


class CreateMemoryRequest(BaseModel):
    content: str
    category: Optional[str] = None


class MemoryView(BaseModel):
    id: str
    user_id: str
    content: str
    category: Optional[str] = None


class V3MemoryView(BaseModel):
    """Full shape expected by the desktop app's ServerMemory decoder."""

    id: str
    content: str
    category: str = "system"
    created_at: datetime
    updated_at: datetime
    conversation_id: Optional[str] = None
    reviewed: bool = False
    user_review: Optional[bool] = None
    visibility: str = "private"
    manually_added: bool = True
    scoring: Optional[str] = None
    source: Optional[str] = None
    confidence: Optional[float] = None
    source_app: Optional[str] = None
    context_summary: Optional[str] = None

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
    is_read: bool = False
    is_dismissed: bool = False
    tags: List[str] = []
    reasoning: Optional[str] = None
    current_activity: Optional[str] = None
    input_device_name: Optional[str] = None
    window_title: Optional[str] = None
    headline: Optional[str] = None


class MemoryStatusResponse(BaseModel):
    status: str = "ok"


class BatchMemoryItem(BaseModel):
    content: str
    category: Optional[str] = None


class SearchRequest(BaseModel):
    query: str
    limit: int = 10


def _to_v3(row: Dict[str, Any]) -> V3MemoryView:
    return V3MemoryView(
        id=row["id"],
        content=row["content"],
        category=row.get("category") or "system",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        visibility=row.get("visibility") or "private",
    )


# ---------------------------------------------------------------------------
# v1 routes (legacy — used internally)
# ---------------------------------------------------------------------------


@router.post("", response_model=MemoryView)
async def create_memory(
    req: CreateMemoryRequest, user_id: str = Depends(get_current_user_id_local)
) -> MemoryView:
    memo = await asyncio.to_thread(repository.create_memory, user_id, req.content, category=req.category)
    try:
        await asyncio.to_thread(vdb.upsert_memory_vector, user_id, memo["id"], req.content, req.category or "")
    except Exception:
        logger.warning("Qdrant vector index failed for memory %s — SQL row was saved", memo["id"])
    try:
        await push_event(user_id, {"type": "new_memory_created", "memory": memo})
    except Exception:
        pass
    return MemoryView(**memo)


@router.get("", response_model=List[MemoryView])
async def list_memories(user_id: str = Depends(get_current_user_id_local)) -> List[MemoryView]:
    rows = await asyncio.to_thread(repository.list_memories, user_id)
    return [MemoryView(**m) for m in rows]


@router.post("/search")
async def semantic_search(
    req: SearchRequest, user_id: str = Depends(get_current_user_id_local)
) -> dict:
    memory_ids = await asyncio.to_thread(vdb.search_memories_by_vector, user_id, req.query, limit=req.limit)
    return {"memory_ids": memory_ids}


# ---------------------------------------------------------------------------
# v3 routes — used by the desktop app
# ---------------------------------------------------------------------------


@router_v3.get("", response_model=List[V3MemoryView])
async def list_memories_v3(
    limit: int = 100,
    offset: int = 0,
    category: Optional[str] = None,
    tags: Optional[str] = None,
    include_dismissed: Optional[bool] = None,
    user_id: str = Depends(get_current_user_id_local),
) -> List[V3MemoryView]:
    rows = await asyncio.to_thread(repository.list_memories, user_id, limit=limit + offset)
    if category:
        rows = [r for r in rows if r.get("category") == category]
    return [_to_v3(r) for r in rows[offset:]]


@router_v3.post("", response_model=V3MemoryView)
async def create_memory_v3(
    req: CreateMemoryRequest, user_id: str = Depends(get_current_user_id_local)
) -> V3MemoryView:
    memo = await asyncio.to_thread(repository.create_memory, user_id, req.content, category=req.category)
    try:
        await asyncio.to_thread(vdb.upsert_memory_vector, user_id, memo["id"], req.content, req.category or "")
    except Exception:
        logger.warning("Qdrant vector index failed for memory %s — SQL row was saved", memo["id"])
    return _to_v3(memo)


@router_v3.post("/batch")
async def create_memories_batch(
    items: List[BatchMemoryItem],
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    created = []
    for item in items:
        memo = await asyncio.to_thread(repository.create_memory, user_id, item.content, category=item.category)
        try:
            await asyncio.to_thread(vdb.upsert_memory_vector, user_id, memo["id"], item.content, item.category or "")
        except Exception:
            pass
        created.append({"id": memo["id"], "content": memo["content"]})
    return {"memories": created, "count": len(created)}


@router_v3.delete("", status_code=200)
async def delete_all_memories_v3(
    user_id: str = Depends(get_current_user_id_local),
) -> MemoryStatusResponse:
    await asyncio.to_thread(repository.delete_all_memories, user_id)
    return MemoryStatusResponse()


@router_v3.delete("/{memory_id}", status_code=200)
async def delete_memory_v3(
    memory_id: str,
    user_id: str = Depends(get_current_user_id_local),
) -> MemoryStatusResponse:
    deleted = await asyncio.to_thread(repository.delete_memory, user_id, memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="memory not found")
    return MemoryStatusResponse()


class EditMemoryRequest(BaseModel):
    content: str


@router_v3.patch("/{memory_id}", response_model=MemoryStatusResponse)
async def edit_memory_v3(
    memory_id: str,
    req: EditMemoryRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> MemoryStatusResponse:
    row = await asyncio.to_thread(repository.update_memory, user_id, memory_id, content=req.content)
    if row is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return MemoryStatusResponse()


class VisibilityRequest(BaseModel):
    visibility: str


@router_v3.patch("/{memory_id}/visibility", response_model=MemoryStatusResponse)
async def update_memory_visibility_v3(
    memory_id: str,
    req: VisibilityRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> MemoryStatusResponse:
    row = await asyncio.to_thread(repository.update_memory, user_id, memory_id, visibility=req.visibility)
    if row is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return MemoryStatusResponse()


class BulkVisibilityRequest(BaseModel):
    visibility: str


@router_v3.patch("/visibility", response_model=MemoryStatusResponse)
async def update_all_memories_visibility(
    req: BulkVisibilityRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> MemoryStatusResponse:
    rows = await asyncio.to_thread(repository.list_memories, user_id, limit=10000)
    for row in rows:
        await asyncio.to_thread(repository.update_memory, user_id, row["id"], visibility=req.visibility)
    return MemoryStatusResponse()


class ReadRequest(BaseModel):
    is_read: Optional[bool] = None
    is_dismissed: Optional[bool] = None


@router_v3.patch("/{memory_id}/read", response_model=MemoryStatusResponse)
async def update_memory_read_status(
    memory_id: str,
    req: ReadRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> MemoryStatusResponse:
    return MemoryStatusResponse()


@router_v3.post("/mark-all-read", response_model=MemoryStatusResponse)
async def mark_all_memories_read(user_id: str = Depends(get_current_user_id_local)) -> MemoryStatusResponse:
    return MemoryStatusResponse()

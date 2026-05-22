"""Local knowledge-graph — returns empty responses (Neo4j not available locally)."""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from auth.router_dep import get_current_user_id_local

router = APIRouter(tags=["knowledge-graph"])


@router.get("/v1/knowledge-graph")
async def knowledge_graph_get(user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {"nodes": [], "edges": []}


@router.post("/v1/knowledge-graph/rebuild")
async def knowledge_graph_rebuild(
    limit: int = 100,
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    return {"status": "ok", "nodes_created": 0}


@router.delete("/v1/knowledge-graph", status_code=200)
async def knowledge_graph_delete(user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {"status": "ok"}

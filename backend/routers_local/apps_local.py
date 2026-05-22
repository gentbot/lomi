"""Apps, personas, and related stubs for local mode — all return empty/default responses."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth.router_dep import get_current_user_id_local

router = APIRouter(tags=["apps"])


# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------


@router.get("/v1/apps")
async def list_apps_v1(user_id: str = Depends(get_current_user_id_local)) -> List:
    return []


@router.get("/v1/apps/enabled")
async def list_enabled_apps(user_id: str = Depends(get_current_user_id_local)) -> List:
    return []


@router.get("/v1/apps/{app_id}")
async def get_app(app_id: str, user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {"app_id": app_id, "name": app_id, "enabled": False}


@router.get("/v1/apps/{app_id}/reviews")
async def get_app_reviews(app_id: str, user_id: str = Depends(get_current_user_id_local)) -> List:
    return []


@router.post("/v1/apps/enable")
async def enable_app(app_id: str, user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {"enabled": True}


@router.post("/v1/apps/disable")
async def disable_app(app_id: str, user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {"enabled": False}


@router.post("/v1/apps/review")
async def review_app(user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {"status": "ok"}


@router.get("/v2/apps")
async def list_apps_v2(
    offset: int = 0,
    limit: int = 50,
    user_id: str = Depends(get_current_user_id_local),
) -> List:
    return []


@router.get("/v2/apps/search")
async def search_apps(
    q: Optional[str] = None,
    user_id: str = Depends(get_current_user_id_local),
) -> List:
    return []


@router.get("/v1/app-capabilities")
async def get_app_capabilities(user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {}


@router.get("/v1/app-categories")
async def get_app_categories(user_id: str = Depends(get_current_user_id_local)) -> List:
    return []


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------


@router.get("/v1/personas")
async def get_personas(user_id: str = Depends(get_current_user_id_local)) -> List:
    return []


class PersonaRequest(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    username: Optional[str] = None


@router.post("/v1/personas")
async def create_persona(
    req: PersonaRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    return {"id": "local", "name": req.name or "Local", "prompt": req.prompt or ""}


@router.patch("/v1/personas")
async def update_persona(
    req: PersonaRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    return {"id": "local", "name": req.name or "Local", "prompt": req.prompt or ""}


@router.delete("/v1/personas", status_code=204)
async def delete_persona(user_id: str = Depends(get_current_user_id_local)) -> None:
    return None


@router.post("/v1/personas/generate-prompt")
async def generate_persona_prompt(user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {"prompt": ""}


@router.get("/v1/personas/check-username")
async def check_persona_username(
    username: str = "",
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    return {"available": True}


# ---------------------------------------------------------------------------
# Payments (stubs — local mode has no billing)
# ---------------------------------------------------------------------------


@router.get("/v1/users/me/subscription")
async def get_subscription(user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {
        "plan": "operator",
        "status": "active",
        "current_period_end": None,
        "stripe_subscription_id": None,
        "current_price_id": None,
        "features": [],
        "cancel_at_period_end": False,
        "limits": {
            "transcription_seconds": None,
            "words_transcribed": None,
            "insights_gained": None,
            "memories_created": None,
        },
        "deprecated": False,
        "deprecation_message": None,
    }


@router.get("/v1/users/me/usage-quota")
async def get_usage_quota(user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {"used": 0, "limit": -1, "reset_at": None}


@router.get("/v1/payments/available-plans")
async def get_available_plans(user_id: str = Depends(get_current_user_id_local)) -> List:
    return []


@router.get("/v1/payments/overage-info")
async def get_overage_info(user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {}


@router.post("/v1/payments/checkout-session")
async def create_checkout_session(user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {"url": ""}


@router.post("/v1/payments/customer-portal")
async def customer_portal(user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {"url": ""}


@router.post("/v1/payments/upgrade-subscription")
async def upgrade_subscription(user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Scores
# ---------------------------------------------------------------------------


@router.get("/v1/scores")
async def get_scores(user_id: str = Depends(get_current_user_id_local)) -> List:
    return []


# ---------------------------------------------------------------------------
# Tools endpoints (RAG tool wrappers — forward to local data)
# ---------------------------------------------------------------------------


@router.get("/v1/tools/conversations")
async def tools_conversations(
    limit: int = 50,
    offset: int = 0,
    include_transcript: bool = False,
    user_id: str = Depends(get_current_user_id_local),
) -> List:
    return []


@router.post("/v1/tools/conversations/search")
async def tools_conversations_search(user_id: str = Depends(get_current_user_id_local)) -> List:
    return []


@router.post("/v1/tools/memories/search")
async def tools_memories_search(user_id: str = Depends(get_current_user_id_local)) -> List:
    return []


@router.get("/v1/tools/action-items")
async def tools_action_items(
    limit: int = 50,
    offset: int = 0,
    user_id: str = Depends(get_current_user_id_local),
) -> List:
    return []


@router.patch("/v1/tools/action-items/{item_id}")
async def tools_update_action_item(
    item_id: str,
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    return {"status": "ok"}


@router.post("/v1/tools/action-items")
async def tools_create_action_item(user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Share / export stubs
# ---------------------------------------------------------------------------


@router.post("/v2/messages/share")
async def share_messages(user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {"url": ""}

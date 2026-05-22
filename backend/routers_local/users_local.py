"""User settings, profile, preferences, and misc user endpoints."""

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel

from auth.router_dep import get_current_user_id_local
from database.sql import repository

router = APIRouter(tags=["users"])


# ---------------------------------------------------------------------------
# Helper: get/set a sub-key from user_settings.assistant_settings JSON blob
# ---------------------------------------------------------------------------

async def _get_settings_key(user_id: str, key: str, default: Any) -> Any:
    row = await asyncio.to_thread(repository.get_user_settings, user_id)
    return row.get("assistant_settings", {}).get(key, default)


async def _set_settings_key(user_id: str, key: str, value: Any) -> None:
    current = await asyncio.to_thread(repository.get_user_settings, user_id)
    blob = dict(current.get("assistant_settings", {}))
    blob[key] = value
    await asyncio.to_thread(repository.upsert_user_settings, user_id, blob)


# ---------------------------------------------------------------------------
# Assistant settings (complex JSON blob)
# ---------------------------------------------------------------------------


@router.get("/v1/users/assistant-settings")
async def get_assistant_settings(
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    row = await asyncio.to_thread(repository.get_user_settings, user_id)
    return row.get("assistant_settings", {})


@router.patch("/v1/users/assistant-settings")
async def update_assistant_settings(
    body: Dict[str, Any] = Body(default={}),
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    row = await asyncio.to_thread(repository.upsert_user_settings, user_id, body or {})
    return row.get("assistant_settings", {})


# ---------------------------------------------------------------------------
# LLM usage
# ---------------------------------------------------------------------------


@router.get("/v1/users/me/llm-usage/total")
async def get_llm_usage_total(
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    return {"total_cost_usd": 0.0, "total_tokens": 0}


@router.get("/v1/users/me/llm-usage")
async def get_llm_usage(
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    return {"total_cost_usd": 0.0, "total_tokens": 0, "usage": []}


@router.get("/v1/users/me/byok-active")
async def get_byok_active(user_id: str = Depends(get_current_user_id_local)) -> Dict[str, Any]:
    return {"active": False, "fingerprints": []}


class BYOKRequest(BaseModel):
    fingerprints: List[str] = []


@router.post("/v1/users/me/byok-active")
async def set_byok_active(
    req: BYOKRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    return {"active": len(req.fingerprints) > 0, "fingerprints": req.fingerprints}


@router.delete("/v1/users/me/byok-active", status_code=204)
async def delete_byok_active(user_id: str = Depends(get_current_user_id_local)) -> None:
    return None


# ---------------------------------------------------------------------------
# User profile
# ---------------------------------------------------------------------------


class UserProfileResponse(BaseModel):
    uid: str
    email: Optional[str] = None
    name: Optional[str] = None
    time_zone: Optional[str] = None
    created_at: Optional[str] = None
    motivation: Optional[str] = None
    use_case: Optional[str] = None
    job: Optional[str] = None
    company: Optional[str] = None


@router.get("/v1/users/profile", response_model=UserProfileResponse)
async def get_user_profile(
    user_id: str = Depends(get_current_user_id_local),
) -> UserProfileResponse:
    row = await asyncio.to_thread(repository.get_user_settings, user_id)
    blob = row.get("assistant_settings", {}).get("_profile", {})
    return UserProfileResponse(
        uid=user_id,
        email=blob.get("email"),
        name=blob.get("name"),
        time_zone=blob.get("time_zone"),
        created_at=blob.get("created_at"),
        motivation=blob.get("motivation"),
        use_case=blob.get("use_case"),
        job=blob.get("job"),
        company=blob.get("company"),
    )


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    motivation: Optional[str] = None
    use_case: Optional[str] = None
    job: Optional[str] = None
    company: Optional[str] = None


@router.patch("/v1/users/profile")
async def update_user_profile(
    req: UpdateProfileRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    current = await asyncio.to_thread(repository.get_user_settings, user_id)
    blob = dict(current.get("assistant_settings", {}))
    profile = dict(blob.get("_profile", {}))
    for field in ("name", "motivation", "use_case", "job", "company"):
        val = getattr(req, field)
        if val is not None:
            profile[field] = val
    blob["_profile"] = profile
    await asyncio.to_thread(repository.upsert_user_settings, user_id, blob)
    return {"status": "ok"}


class AIProfileRequest(BaseModel):
    ai_profile: Optional[Dict[str, Any]] = None


@router.patch("/v1/users/ai-profile")
async def update_ai_profile(
    req: AIProfileRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    if req.ai_profile:
        await _set_settings_key(user_id, "_ai_profile", req.ai_profile)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------


@router.get("/v1/users/language")
async def get_user_language(
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    lang = await _get_settings_key(user_id, "language", "en")
    return {"language": lang}


class LanguageRequest(BaseModel):
    language: str


@router.patch("/v1/users/language")
async def update_user_language(
    req: LanguageRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    await _set_settings_key(user_id, "language", req.language)
    return {"language": req.language}


# ---------------------------------------------------------------------------
# Transcription preferences
# ---------------------------------------------------------------------------


@router.get("/v1/users/transcription-preferences")
async def get_transcription_preferences(
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    prefs = await _get_settings_key(user_id, "transcription_preferences", {})
    return {
        "single_language_mode": prefs.get("single_language_mode", False),
        "vocabulary": prefs.get("vocabulary", []),
    }


class TranscriptionPrefsRequest(BaseModel):
    single_language_mode: Optional[bool] = None
    vocabulary: Optional[List[str]] = None


@router.patch("/v1/users/transcription-preferences")
async def update_transcription_preferences(
    req: TranscriptionPrefsRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    current = await _get_settings_key(user_id, "transcription_preferences", {})
    prefs = dict(current)
    if req.single_language_mode is not None:
        prefs["single_language_mode"] = req.single_language_mode
    if req.vocabulary is not None:
        prefs["vocabulary"] = req.vocabulary
    await _set_settings_key(user_id, "transcription_preferences", prefs)
    return {"single_language_mode": prefs.get("single_language_mode", False), "vocabulary": prefs.get("vocabulary", [])}


# ---------------------------------------------------------------------------
# Notification settings
# ---------------------------------------------------------------------------


@router.get("/v1/users/notification-settings")
async def get_notification_settings(
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    ns = await _get_settings_key(user_id, "notification_settings", {})
    return {"enabled": ns.get("enabled", True), "frequency": ns.get("frequency", 3)}


class NotificationSettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    frequency: Optional[int] = None


@router.patch("/v1/users/notification-settings")
async def update_notification_settings(
    req: NotificationSettingsRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    current = await _get_settings_key(user_id, "notification_settings", {})
    ns = dict(current)
    if req.enabled is not None:
        ns["enabled"] = req.enabled
    if req.frequency is not None:
        ns["frequency"] = req.frequency
    await _set_settings_key(user_id, "notification_settings", ns)
    return {"enabled": ns.get("enabled", True), "frequency": ns.get("frequency", 3)}


# ---------------------------------------------------------------------------
# Daily summary settings
# ---------------------------------------------------------------------------


@router.get("/v1/users/daily-summary-settings")
async def get_daily_summary_settings(
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    ds = await _get_settings_key(user_id, "daily_summary", {})
    return {"enabled": ds.get("enabled", False), "hour": ds.get("hour", 8)}


class DailySummaryRequest(BaseModel):
    enabled: Optional[bool] = None
    hour: Optional[int] = None


@router.patch("/v1/users/daily-summary-settings")
async def update_daily_summary_settings(
    req: DailySummaryRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    current = await _get_settings_key(user_id, "daily_summary", {})
    ds = dict(current)
    if req.enabled is not None:
        ds["enabled"] = req.enabled
    if req.hour is not None:
        ds["hour"] = req.hour
    await _set_settings_key(user_id, "daily_summary", ds)
    return {"enabled": ds.get("enabled", False), "hour": ds.get("hour", 8)}


# ---------------------------------------------------------------------------
# Recording permission
# ---------------------------------------------------------------------------


@router.get("/v1/users/store-recording-permission")
async def get_recording_permission(
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    enabled = await _get_settings_key(user_id, "store_recording_permission", True)
    return {"store_recording_permission": enabled}


@router.post("/v1/users/store-recording-permission")
async def set_recording_permission(
    value: bool = Query(True),
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    await _set_settings_key(user_id, "store_recording_permission", value)
    return {"store_recording_permission": value}


# ---------------------------------------------------------------------------
# Private cloud sync
# ---------------------------------------------------------------------------


@router.get("/v1/users/private-cloud-sync")
async def get_private_cloud_sync(
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    return {"private_cloud_sync_enabled": False}


@router.post("/v1/users/private-cloud-sync")
async def set_private_cloud_sync(
    value: bool = Query(False),
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    return {"private_cloud_sync_enabled": False}


# ---------------------------------------------------------------------------
# People / contacts
# ---------------------------------------------------------------------------


@router.get("/v1/users/people")
async def get_people(user_id: str = Depends(get_current_user_id_local)) -> List:
    return []


class CreatePersonRequest(BaseModel):
    name: str


@router.post("/v1/users/people")
async def create_person(
    req: CreatePersonRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    return {"id": req.name, "name": req.name}


# ---------------------------------------------------------------------------
# Chat message stats
# ---------------------------------------------------------------------------


@router.get("/v1/users/stats/chat-messages")
async def get_chat_message_count(
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    rows = await asyncio.to_thread(repository.list_chat_messages, user_id, limit=0)
    return {"count": len(rows)}


# ---------------------------------------------------------------------------
# Account deletion
# ---------------------------------------------------------------------------


@router.delete("/v1/users/delete-account", status_code=204)
async def delete_account(user_id: str = Depends(get_current_user_id_local)) -> None:
    await asyncio.to_thread(repository.delete_user, user_id)


# ---------------------------------------------------------------------------
# Goals (basic CRUD + stubs)
# ---------------------------------------------------------------------------


@router.get("/v1/goals/all")
async def list_goals(user_id: str = Depends(get_current_user_id_local)) -> List:
    return []


@router.get("/v1/goals/completed")
async def list_completed_goals(user_id: str = Depends(get_current_user_id_local)) -> List:
    return []


class GoalRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    target_value: Optional[float] = None


@router.post("/v1/goals")
async def create_goal(
    req: GoalRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    return {"id": "local", "title": req.title or "", "description": req.description or ""}


@router.patch("/v1/goals/{goal_id}")
async def update_goal(
    goal_id: str,
    req: GoalRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    return {"id": goal_id, "title": req.title or "", "description": req.description or ""}


@router.post("/v1/goals/{goal_id}/progress")
async def update_goal_progress(
    goal_id: str,
    current_value: float = Query(0),
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    return {"id": goal_id, "current_value": current_value}


@router.delete("/v1/goals/{goal_id}", status_code=204)
async def delete_goal(
    goal_id: str,
    user_id: str = Depends(get_current_user_id_local),
) -> None:
    return None


# ---------------------------------------------------------------------------
# Folders (full CRUD stubs — no local persistence needed)
# ---------------------------------------------------------------------------


@router.get("/v1/folders")
async def list_folders(user_id: str = Depends(get_current_user_id_local)) -> List:
    return []


class FolderRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None


@router.post("/v1/folders")
async def create_folder(
    req: FolderRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    return {"id": "local", "name": req.name or ""}


@router.patch("/v1/folders/{folder_id}")
async def update_folder(
    folder_id: str,
    req: FolderRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> Dict[str, Any]:
    return {"id": folder_id, "name": req.name or ""}


@router.delete("/v1/folders/{folder_id}", status_code=204)
async def delete_folder(
    folder_id: str,
    user_id: str = Depends(get_current_user_id_local),
) -> None:
    return None

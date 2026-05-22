"""Admin endpoints for local user management.

All endpoints require a valid Bearer token (any authenticated local user).
There is no RBAC — intentional for a local-only, single-operator setup.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.exc import IntegrityError

from auth.local_auth import _hash_password, generate_token, JWT_TTL_SECONDS
from auth.router_dep import get_current_user_id_local
from database.sql.db import session_scope
from database.sql import repository
from database.sql.repository import _UNSET

router = APIRouter(prefix="/v1/admin", tags=["admin"])


# ── Pydantic models ───────────────────────────────────────────────────────────


class UserOut(BaseModel):
    id: str
    email: str
    display_name: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None


class UpdateUserRequest(BaseModel):
    email: Optional[EmailStr] = None
    display_name: Optional[str] = None


class SetPasswordRequest(BaseModel):
    new_password: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _safe(user_dict: dict) -> dict:
    """Strip password_hash and stringify datetimes for JSON output."""
    out = dict(user_dict)
    out.pop("password_hash", None)
    out.pop("extra", None)
    for key in ("created_at", "updated_at"):
        val = out.get(key)
        if val is not None and not isinstance(val, str):
            out[key] = val.isoformat()
    return out


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/users", response_model=List[UserOut])
def list_users(_uid: str = Depends(get_current_user_id_local)) -> List[dict]:
    return [_safe(u) for u in repository.list_all_users()]


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(
    user_id: str,
    _uid: str = Depends(get_current_user_id_local),
) -> dict:
    with session_scope() as session:
        user = repository.get_user(session, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found.")
        return _safe(repository._to_dict(user))


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    req: UpdateUserRequest,
    _uid: str = Depends(get_current_user_id_local),
) -> dict:
    if req.email is None and req.display_name is None:
        raise HTTPException(status_code=400, detail="No fields to update.")
    try:
        result = repository.update_user(
            user_id,
            email=str(req.email) if req.email is not None else None,
            # Pass display_name through always (None = clear it, str = set it).
            # The frontend always sends this field from the edit modal.
            display_name=req.display_name,
        )
    except IntegrityError:
        raise HTTPException(
            status_code=400,
            detail="That email is already used by another account.",
        )
    if result is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return _safe(result)


@router.post("/users/{user_id}/password")
def reset_user_password(
    user_id: str,
    req: SetPasswordRequest,
    _uid: str = Depends(get_current_user_id_local),
) -> dict:
    if len(req.new_password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters.",
        )
    ok = repository.update_user_password(user_id, _hash_password(req.new_password))
    if not ok:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"ok": True}


@router.post("/users/{user_id}/token")
def get_user_token(
    user_id: str,
    _uid: str = Depends(get_current_user_id_local),
) -> dict:
    """Generate a fresh JWT for the specified user (no password required)."""
    with session_scope() as session:
        user = repository.get_user(session, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found.")
        user_dict = repository._to_dict(user)
    return {
        "access_token": generate_token(user_dict["id"], user_dict["email"]),
        "token_type": "bearer",
        "expires_in": JWT_TTL_SECONDS,
    }


@router.delete("/users/{user_id}")
def delete_user_endpoint(
    user_id: str,
    current_uid: str = Depends(get_current_user_id_local),
) -> dict:
    if user_id == current_uid:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete your own account while logged in.",
        )
    ok = repository.delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"ok": True}

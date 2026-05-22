"""Local register / login / me endpoints (Phase 7 cutover)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from auth.local_auth import (
    AuthError,
    _hash_password,
    _verify_password,
    login as auth_login,
    register as auth_register,
)
from auth.router_dep import get_current_user_id_local
from database.sql.db import session_scope
from database.sql import repository

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterResponse(BaseModel):
    id: str
    email: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=RegisterResponse)
def register(req: RegisterRequest) -> RegisterResponse:
    try:
        user = auth_register(req.email, req.password)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RegisterResponse(**user)


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest) -> LoginResponse:
    try:
        token = auth_login(req.email, req.password)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return LoginResponse(access_token=token)


@router.get("/me")
def me(user_id: str = Depends(get_current_user_id_local)) -> dict:
    return {"user_id": user_id}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(
    req: ChangePasswordRequest,
    user_id: str = Depends(get_current_user_id_local),
) -> dict:
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    with session_scope() as session:
        user = repository.get_user(session, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found.")
        if not _verify_password(req.current_password, user.password_hash):
            raise HTTPException(status_code=401, detail="Current password is incorrect.")
    ok = repository.update_user_password(user_id, _hash_password(req.new_password))
    if not ok:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"ok": True}

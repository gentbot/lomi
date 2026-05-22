"""Local JWT auth.

Replaces Firebase token verification when ``AUTH_PROVIDER=local``. Uses the
SQL ``users`` table for credentials and signs JWTs with ``LOCAL_JWT_SECRET``.

Public surface:

    register(email, password) -> {"id", "email", ...}
    login(email, password)    -> str (JWT)
    verify_token(token)       -> {"user_id", "email", "exp"}

Existing FastAPI deps in ``backend/dependencies.py`` should be routed through
``providers.get_auth_provider()`` so this implementation is the active one in
local mode without touching every router.
"""

import hashlib
import hmac
import os
import time
from typing import Dict, Optional

import jwt  # PyJWT — already a transitive dep via firebase_admin

from database.sql.repository import create_user, get_user_by_email
from database.sql.db import session_scope
from database.sql.models import User

JWT_SECRET = os.environ.get("LOCAL_JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = os.environ.get("LOCAL_JWT_ALGORITHM", "HS256")
JWT_TTL_SECONDS = int(os.environ.get("LOCAL_JWT_TTL_SECONDS", "86400"))


class AuthError(Exception):
    pass


def _hash_password(password: str, *, salt: Optional[bytes] = None) -> str:
    salt = salt or os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"pbkdf2_sha256${salt.hex()}${derived.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, salt_hex, hash_hex = encoded.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(hash_hex)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return hmac.compare_digest(candidate, expected)


def register(email: str, password: str) -> Dict[str, str]:
    email = email.strip().lower()
    if not email or not password:
        raise AuthError("email and password are required")
    with session_scope() as session:
        if session.query(User).filter(User.email == email).first() is not None:
            raise AuthError("user already exists")
    user = create_user(email=email, password_hash=_hash_password(password))
    return {"id": user["id"], "email": user["email"]}


def generate_token(user_id: str, email: str) -> str:
    """Mint a JWT for a known user without requiring a password."""
    payload = {
        "user_id": user_id,
        "email": email,
        "exp": int(time.time()) + JWT_TTL_SECONDS,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def login(email: str, password: str) -> str:
    email = email.strip().lower()
    with session_scope() as session:
        user = get_user_by_email(session, email)
        if user is None or not _verify_password(password, user.password_hash):
            raise AuthError("invalid email or password")
        user_id, user_email = user.id, user.email
    return generate_token(user_id, user_email)


def verify_token(token: str) -> Dict[str, str]:
    try:
        decoded = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("invalid token") from exc
    if "user_id" not in decoded:
        raise AuthError("token missing user_id")
    return {"user_id": decoded["user_id"], "email": decoded.get("email", ""), "exp": decoded.get("exp", 0)}


def bypass_uid_from_token(token: str) -> str:
    """Derive a stable user-ID from an unverified external JWT (e.g. Firebase).

    Preferred source: the ``sub`` claim inside the JWT payload, which is the
    Firebase UID and is stable across token refreshes.  Falls back to the
    last-16-chars of the raw token string if decoding fails.

    This function intentionally does NOT verify the token signature — it is only
    used when ``LOCAL_AUTH_BYPASS=true``, which is a dev-only escape hatch for
    LAN-local use.  Never call this in production auth paths.
    """
    import base64
    import json

    try:
        parts = token.split(".")
        if len(parts) == 3:
            # JWT payload is the second segment, base64url-encoded (no padding)
            padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded))
            uid = payload.get("sub") or payload.get("user_id") or payload.get("uid")
            if uid:
                return "fb_" + str(uid)
    except Exception:
        pass
    # Last-resort: tail of the raw token (not stable across refreshes, but
    # better than failing)
    return "fb_" + token[-16:]


def bootstrap_admin_if_needed() -> None:
    """Create the bootstrap admin user from env vars when the DB is empty.

    Safe to call on every startup — it does nothing if the user already exists
    or if either env var is missing.
    """
    email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
    if not email or not password:
        return
    with session_scope() as session:
        if get_user_by_email(session, email) is not None:
            return
    create_user(email=email, password_hash=_hash_password(password))

"""FastAPI dependency that resolves the current user via the local auth path.

Wired in by replacing the Firebase-based ``get_current_user_id`` in
``backend/dependencies.py`` with one that calls ``providers.get_auth_provider``
and dispatches to the matching verifier.
"""

import os

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.local_auth import AuthError, bypass_uid_from_token, verify_token

_bearer = HTTPBearer()

_AUTH_BYPASS = os.environ.get("LOCAL_AUTH_BYPASS", "").lower() in ("1", "true", "yes")


async def get_current_user_id_local(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> str:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = credentials.credentials
    # Try the local JWT path first (pin_bridge, curl, direct API clients).
    try:
        payload = verify_token(token)
        return payload["user_id"]
    except AuthError:
        pass
    # When LOCAL_AUTH_BYPASS=true, accept any Bearer token (e.g. Firebase ID
    # tokens from the mobile/desktop apps) and derive a stable local user-ID
    # from the token's ``sub`` claim.  Dev/LAN-only; never enable in prod.
    if _AUTH_BYPASS:
        return bypass_uid_from_token(token)
    raise HTTPException(status_code=401, detail="Invalid or expired token")

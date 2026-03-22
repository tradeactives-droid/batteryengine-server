# battery_engine_pro3/session_auth.py
"""
Single active session validation against Supabase `active_sessions` (PostgREST).

Uses httpx + PyJWT only (no supabase-py), to avoid heavy transitive deps on some platforms.

Enable by setting all of:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
  SUPABASE_JWT_SECRET

If any is missing, session checks are skipped (backward compatible).
"""

from __future__ import annotations

import os
from typing import Annotated, Optional

import httpx
import jwt
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer(auto_error=False)

SESSION_INVALID_DETAIL = {
    "error_code": "SESSION_INVALID",
    "message": "Session expired. You have been logged out.",
}


def session_enforcement_enabled() -> bool:
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    secret = os.getenv("SUPABASE_JWT_SECRET", "").strip()
    return bool(url and key and secret)


def _decode_user_id_from_jwt(token: str) -> str:
    secret = os.getenv("SUPABASE_JWT_SECRET", "").strip()
    aud = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated").strip() or "authenticated"
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=aud,
            options={"verify_exp": True},
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail=SESSION_INVALID_DETAIL.copy())

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail=SESSION_INVALID_DETAIL.copy())
    return str(sub)


def _fetch_stored_session_token(user_id: str) -> Optional[str]:
    base = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    url = f"{base}/rest/v1/active_sessions"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }
    params = {
        "user_id": f"eq.{user_id}",
        "select": "session_token",
        "limit": "1",
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url, headers=headers, params=params)
            r.raise_for_status()
            rows = r.json()
    except Exception:
        raise HTTPException(status_code=401, detail=SESSION_INVALID_DETAIL.copy())

    if not isinstance(rows, list) or not rows:
        return None
    return rows[0].get("session_token")


async def require_valid_session(
    authorization: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
    x_session_token: Annotated[Optional[str], Header(alias="x-session-token")] = None,
) -> Optional[str]:
    """
    Validates Authorization: Bearer <jwt> + x-session-token against active_sessions.
    Returns user_id when enforcement is on; returns None when enforcement is off.
    """
    if not session_enforcement_enabled():
        return None

    if not x_session_token or not str(x_session_token).strip():
        raise HTTPException(status_code=401, detail=SESSION_INVALID_DETAIL.copy())

    if authorization is None or not authorization.credentials:
        raise HTTPException(status_code=401, detail=SESSION_INVALID_DETAIL.copy())

    user_id = _decode_user_id_from_jwt(authorization.credentials)
    stored = _fetch_stored_session_token(user_id)

    if stored is None or stored != str(x_session_token).strip():
        raise HTTPException(status_code=401, detail=SESSION_INVALID_DETAIL.copy())

    return user_id

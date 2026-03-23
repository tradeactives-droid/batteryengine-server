from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from typing import Annotated, Optional

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer(auto_error=False)
logger = logging.getLogger("batteryengine.session_guard")

SESSION_INVALID_CODE = "SESSION_INVALID"
SESSION_INVALID_MESSAGE = "Session invalid or superseded by another device."


@dataclass
class AuthenticatedUser:
    id: str


def _mask_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    token = str(token)
    return f"{token[:6]}..." if len(token) > 6 else f"{token}..."


def raise_session_invalid(msg: str = SESSION_INVALID_MESSAGE) -> None:
    raise HTTPException(
        status_code=401,
        detail={
            "error_code": SESSION_INVALID_CODE,
            "message": msg,
        },
    )


def session_enforcement_enabled() -> bool:
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    secret = os.getenv("SUPABASE_JWT_SECRET", "").strip()
    return bool(url and key and secret)


def _supabase_base_url() -> str:
    return os.getenv("SUPABASE_URL", "").strip().rstrip("/")


def _service_role_key() -> str:
    return os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()


def _rest_headers(prefer: Optional[str] = None) -> dict[str, str]:
    key = _service_role_key()
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


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
        raise_session_invalid("Invalid authentication token.")
    sub = payload.get("sub")
    if not sub:
        raise_session_invalid("Invalid authentication token.")
    return str(sub)


def _log_session_warning(
    request: Request,
    reason: str,
    user_id: Optional[str],
    header_token: Optional[str],
    stored_token: Optional[str],
) -> None:
    req_id = request.headers.get("x-request-id") or request.headers.get("x-correlation-id")
    payload = {
        "event": "session_invalid",
        "reason": reason,
        "user_id": user_id,
        "path": request.url.path,
        "request_id": req_id,
        "header_token": _mask_token(header_token),
        "stored_token": _mask_token(stored_token),
    }
    logger.warning(json.dumps(payload, ensure_ascii=True))


def _fetch_active_session_by_user(user_id: str) -> Optional[dict]:
    base = _supabase_base_url()
    if not base:
        return None
    url = f"{base}/rest/v1/active_sessions"
    params = {
        "user_id": f"eq.{user_id}",
        "select": "user_id,session_token,updated_at",
        "limit": "1",
    }
    with httpx.Client(timeout=10.0) as client:
        r = client.get(url, headers=_rest_headers(), params=params)
        r.raise_for_status()
        rows = r.json()
    if not isinstance(rows, list) or not rows:
        return None
    return rows[0]


def register_active_session(user_id: str, session_token: str) -> bool:
    base = _supabase_base_url()
    if not base:
        return False
    url = f"{base}/rest/v1/active_sessions"
    params = {"on_conflict": "user_id"}
    body = {
        "user_id": user_id,
        "session_token": session_token,
    }
    headers = _rest_headers(prefer="resolution=merge-duplicates,return=representation")
    with httpx.Client(timeout=10.0) as client:
        r = client.post(url, headers=headers, params=params, json=body)
        r.raise_for_status()
        rows = r.json()
    return isinstance(rows, list) and len(rows) > 0


async def get_current_user(
    authorization: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
) -> Optional[AuthenticatedUser]:
    if not session_enforcement_enabled():
        return None
    if authorization is None or not authorization.credentials:
        raise_session_invalid("Missing Authorization token.")
    user_id = _decode_user_id_from_jwt(authorization.credentials)
    return AuthenticatedUser(id=user_id)


async def require_active_session(
    request: Request,
    current_user: Annotated[Optional[AuthenticatedUser], Depends(get_current_user)],
    x_session_token: Annotated[Optional[str], Header(alias="x-session-token")] = None,
) -> Optional[AuthenticatedUser]:
    if not session_enforcement_enabled():
        return current_user
    if current_user is None:
        _log_session_warning(request, "missing_user", None, x_session_token, None)
        raise_session_invalid()

    token = (x_session_token or "").strip()
    if not token:
        _log_session_warning(request, "missing_header", current_user.id, None, None)
        raise_session_invalid()

    row = _fetch_active_session_by_user(current_user.id)
    if not row:
        _log_session_warning(request, "no_row", current_user.id, token, None)
        raise_session_invalid()

    stored = str(row.get("session_token") or "")
    if stored != token:
        _log_session_warning(request, "token_mismatch", current_user.id, token, stored)
        raise_session_invalid()

    return current_user


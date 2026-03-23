# battery_engine_pro3/device_tracking_deps.py
"""FastAPI dependency: register device + set multi-device flags on request.state."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import Depends, Header, Request

from battery_engine_pro3 import device_tracking as dt
from battery_engine_pro3.auth.session_guard import (
    AuthenticatedUser,
    require_active_session,
    session_enforcement_enabled,
)


async def track_user_device(
    request: Request,
    current_user: Annotated[Optional[AuthenticatedUser], Depends(require_active_session)],
    x_device_id: Annotated[Optional[str], Header(alias="x-device-id")] = None,
    x_device_fingerprint: Annotated[Optional[str], Header(alias="x-device-fingerprint")] = None,
    user_agent: Annotated[Optional[str], Header(alias="user-agent")] = None,
) -> None:
    request.state.device_tracking_applied = False

    if not session_enforcement_enabled() or current_user is None:
        return None

    device_id = (x_device_id or "").strip()
    if not device_id:
        return None

    fingerprint = (x_device_fingerprint or "").strip() or None
    ua = (user_agent or "").strip() or None
    ip = dt.client_ip_from_request(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
    )

    try:
        warning, count = dt.run_tracking(current_user.id, device_id, fingerprint, ip, ua)
        request.state.device_warning = warning
        request.state.device_count = count
        request.state.device_tracking_applied = True
    except Exception:
        # Never fail the API on telemetry.
        pass

    return None


# battery_engine_pro3/device_tracking.py
"""
Track devices per user via Supabase PostgREST (service role).
Requires same env as session auth: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY.

Multi-device warning: distinct device_id count with last_seen_at in last N days
(default 7) compared to DEVICE_WARNING_THRESHOLD (default 3 → warn when count > 3).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx


def _supabase_config() -> tuple[str, str]:
    base = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    return base, key


def _rest_headers() -> dict[str, str]:
    _, key = _supabase_config()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def client_ip_from_request(client_host: Optional[str], x_forwarded_for: Optional[str]) -> Optional[str]:
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip() or None
    if client_host:
        return client_host
    return None


def device_warning_threshold() -> int:
    try:
        return max(1, int(os.getenv("DEVICE_WARNING_THRESHOLD", "3")))
    except ValueError:
        return 3


def device_tracking_window_days() -> int:
    try:
        return max(1, int(os.getenv("DEVICE_TRACKING_WINDOW_DAYS", "7")))
    except ValueError:
        return 7


def security_events_enabled() -> bool:
    return os.getenv("SECURITY_EVENTS_ENABLED", "1").strip().lower() not in ("0", "false", "no")


def upsert_user_device(
    user_id: str,
    device_id: str,
    fingerprint: Optional[str],
    ip_address: Optional[str],
    user_agent: Optional[str],
) -> None:
    base, _ = _supabase_config()
    if not base:
        return

    url = f"{base}/rest/v1/user_devices"
    headers = _rest_headers()
    params_sel = {
        "user_id": f"eq.{user_id}",
        "device_id": f"eq.{device_id}",
        "select": "id",
        "limit": "1",
    }
    now_iso = datetime.now(timezone.utc).isoformat()

    with httpx.Client(timeout=10.0) as client:
        r = client.get(url, headers=headers, params=params_sel)
        r.raise_for_status()
        rows = r.json()

        if isinstance(rows, list) and rows:
            row_id = rows[0].get("id")
            if row_id:
                patch_url = f"{base}/rest/v1/user_devices"
                patch_params = {"id": f"eq.{row_id}"}
                body = {
                    "last_seen_at": now_iso,
                    "ip_address": ip_address,
                    "fingerprint": fingerprint,
                    "user_agent": user_agent,
                }
                pr = client.patch(patch_url, headers=headers, params=patch_params, json=body)
                pr.raise_for_status()
            return

        body_insert = {
            "user_id": user_id,
            "device_id": device_id,
            "fingerprint": fingerprint,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "first_seen_at": now_iso,
            "last_seen_at": now_iso,
        }
        ir = client.post(url, headers=headers, json=body_insert)
        ir.raise_for_status()


def count_distinct_devices_recent(user_id: str) -> int:
    base, _ = _supabase_config()
    if not base:
        return 0

    days = device_tracking_window_days()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    url = f"{base}/rest/v1/user_devices"
    headers = _rest_headers()
    params = {
        "user_id": f"eq.{user_id}",
        "last_seen_at": f"gte.{cutoff}",
        "select": "device_id",
        "limit": "500",
    }

    with httpx.Client(timeout=15.0) as client:
        r = client.get(url, headers=headers, params=params)
        r.raise_for_status()
        rows = r.json()

    if not isinstance(rows, list):
        return 0
    seen: set[str] = set()
    for row in rows:
        did = row.get("device_id")
        if did:
            seen.add(str(did))
    return len(seen)


def insert_security_event(user_id: str, event_type: str, metadata: dict[str, Any]) -> None:
    if not security_events_enabled():
        return
    base, _ = _supabase_config()
    if not base:
        return

    url = f"{base}/rest/v1/security_events"
    headers = _rest_headers()
    body = {
        "user_id": user_id,
        "event_type": event_type,
        "metadata": metadata,
    }
    with httpx.Client(timeout=10.0) as client:
        r = client.post(url, headers=headers, json=body)
        r.raise_for_status()


def evaluate_device_risk(user_id: str) -> tuple[bool, int]:
    """
    Returns (device_warning, device_count) using distinct device_id in the sliding window.
    Warning when device_count > threshold (default threshold 3 → 4+ devices).
    """
    count = count_distinct_devices_recent(user_id)
    thr = device_warning_threshold()
    warning = count > thr
    return warning, count


def run_tracking(
    user_id: str,
    device_id: str,
    fingerprint: Optional[str],
    ip_address: Optional[str],
    user_agent: Optional[str],
) -> tuple[bool, int]:
    """
    Upsert device row, then compute warning flag and optionally log security_events.
    """
    upsert_user_device(user_id, device_id, fingerprint, ip_address, user_agent)
    warning, count = evaluate_device_risk(user_id)
    if warning:
        insert_security_event(
            user_id,
            "MULTI_DEVICE_USAGE",
            {
                "device_count": count,
                "threshold": device_warning_threshold(),
                "window_days": device_tracking_window_days(),
            },
        )
    return warning, count

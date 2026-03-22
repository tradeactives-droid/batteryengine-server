"""
Session enforcement tests (requires httpx for TestClient).
Set SUPABASE_* env vars → API requires Authorization + x-session-token.
"""

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from main import app
from tests.test_compute_v3_endpoint import make_request_NL


JWT_SECRET = "test-jwt-secret-session-auth-32bytes!!"  # >=32 chars for HS256
USER_ID = "550e8400-e29b-41d4-a716-446655440000"
SESSION_TOKEN = "660e8400-e29b-41d4-a716-446655440001"


def _bearer() -> str:
    tok = jwt.encode(
        {
            "sub": USER_ID,
            "aud": "authenticated",
            "exp": int(time.time()) + 3600,
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    return f"Bearer {tok}"


@pytest.fixture
def enforce_session(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    yield


def test_session_401_without_x_session_token(enforce_session):
    client = TestClient(app)
    r = client.post(
        "/compute_v3",
        json=make_request_NL(),
        headers={"Authorization": _bearer()},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["error_code"] == "SESSION_INVALID"


def test_session_200_when_token_matches(enforce_session, monkeypatch):
    from battery_engine_pro3 import session_auth

    monkeypatch.setattr(
        session_auth,
        "_fetch_stored_session_token",
        lambda uid: SESSION_TOKEN if uid == USER_ID else None,
    )

    client = TestClient(app)
    r = client.post(
        "/compute_v3",
        json=make_request_NL(),
        headers={
            "Authorization": _bearer(),
            "x-session-token": SESSION_TOKEN,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert "A1" in data

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from main import app
from tests.test_compute_v3_endpoint import make_request_NL


JWT_SECRET = "test-jwt-secret-session-auth-32bytes!!"  # >=32 chars for HS256
USER1 = "550e8400-e29b-41d4-a716-446655440000"
USER2 = "550e8400-e29b-41d4-a716-446655440099"
TOKEN_A = "660e8400-e29b-41d4-a716-446655440001"
TOKEN_B = "660e8400-e29b-41d4-a716-446655440002"


def _bearer(user_id: str) -> str:
    tok = jwt.encode(
        {
            "sub": user_id,
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


@pytest.fixture
def session_store(monkeypatch):
    from battery_engine_pro3.auth import session_guard
    import main

    state = {"by_user": {}}

    def _fetch(user_id: str):
        token = state["by_user"].get(user_id)
        if not token:
            return None
        return {"user_id": user_id, "session_token": token}

    def _upsert(user_id: str, session_token: str):
        state["by_user"][user_id] = session_token
        return True

    monkeypatch.setattr(session_guard, "_fetch_active_session_by_user", _fetch)
    monkeypatch.setattr(session_guard, "register_active_session", _upsert)
    monkeypatch.setattr(main, "register_active_session", _upsert)
    return state


def _assert_flat_session_invalid(body: dict):
    assert body["error_code"] == "SESSION_INVALID"
    assert "message" in body
    assert "detail" not in body


def test_a_valid_active_session(enforce_session, session_store):
    session_store["by_user"][USER1] = TOKEN_A
    client = TestClient(app)
    r = client.post(
        "/compute_v3",
        json=make_request_NL(),
        headers={
            "Authorization": _bearer(USER1),
            "x-session-token": TOKEN_A,
        },
    )
    assert r.status_code == 200
    assert "A1" in r.json()


def test_b_second_login_invalidates_first(enforce_session, session_store):
    client = TestClient(app)

    r1 = client.post(
        "/register-session",
        json={"session_token": TOKEN_A},
        headers={"Authorization": _bearer(USER1)},
    )
    assert r1.status_code == 200

    r2 = client.post(
        "/register-session",
        json={"session_token": TOKEN_B},
        headers={"Authorization": _bearer(USER1)},
    )
    assert r2.status_code == 200

    old_req = client.post(
        "/compute_v3",
        json=make_request_NL(),
        headers={
            "Authorization": _bearer(USER1),
            "x-session-token": TOKEN_A,
        },
    )
    assert old_req.status_code == 401
    _assert_flat_session_invalid(old_req.json())

    new_req = client.post(
        "/compute_v3",
        json=make_request_NL(),
        headers={
            "Authorization": _bearer(USER1),
            "x-session-token": TOKEN_B,
        },
    )
    assert new_req.status_code == 200


def test_c_missing_x_session_token(enforce_session, session_store):
    session_store["by_user"][USER1] = TOKEN_A
    client = TestClient(app)
    r = client.post(
        "/compute_v3",
        json=make_request_NL(),
        headers={"Authorization": _bearer(USER1)},
    )
    assert r.status_code == 401
    _assert_flat_session_invalid(r.json())


def test_d_token_for_another_user(enforce_session, session_store):
    session_store["by_user"][USER1] = TOKEN_A
    session_store["by_user"][USER2] = TOKEN_B
    client = TestClient(app)
    r = client.post(
        "/compute_v3",
        json=make_request_NL(),
        headers={
            "Authorization": _bearer(USER1),
            "x-session-token": TOKEN_B,
        },
    )
    assert r.status_code == 401
    _assert_flat_session_invalid(r.json())


def test_e_validate_session_parity(enforce_session, session_store):
    session_store["by_user"][USER1] = TOKEN_A
    client = TestClient(app)

    ok_resp = client.get(
        "/validate-session",
        headers={
            "Authorization": _bearer(USER1),
            "x-session-token": TOKEN_A,
        },
    )
    assert ok_resp.status_code == 200
    assert ok_resp.json()["ok"] is True

    bad_resp = client.get(
        "/validate-session",
        headers={
            "Authorization": _bearer(USER1),
            "x-session-token": TOKEN_B,
        },
    )
    assert bad_resp.status_code == 401
    _assert_flat_session_invalid(bad_resp.json())

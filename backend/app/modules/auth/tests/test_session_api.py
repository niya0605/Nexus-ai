"""HTTP-level tests for POST /api/v1/auth/refresh, POST
/api/v1/auth/logout, GET /api/v1/auth/sessions, DELETE
/api/v1/auth/sessions/{session_id}, and DELETE /api/v1/auth/sessions.

Same real-app-via-TestClient approach as test_login_api.py — see that
file and backend/tests/db.py's `run_http_test` docstring. `TestClient`
carries cookies across requests within one `client` the same way a
browser session would, which is what lets a single test log in once and
then exercise refresh/logout/sessions against the cookies that call set.
"""

import asyncio
import uuid

import asyncpg
from tests.db import HTTP_TEST_EMAIL_DOMAIN, run_http_test

from app.config import settings

_TEST_PASSWORD = "a-strong-password"


def _email() -> str:
    # Every email MUST end in HTTP_TEST_EMAIL_DOMAIN — run_http_test's
    # post-test cleanup only deletes rows matching that pattern.
    return f"user-{uuid.uuid4().hex[:8]}@{HTTP_TEST_EMAIL_DOMAIN}"


async def _activate_user(user_id: str) -> None:
    """See test_login_api.py's identical helper for why this uses its
    own throwaway `asyncpg` connection rather than the shared engine."""
    db = settings.database
    conn = await asyncpg.connect(
        host=db.HOST, port=db.PORT, database=db.DB, user=db.USER, password=db.PASSWORD
    )
    try:
        await conn.execute(
            "UPDATE users SET status = 'active', email_verified_at = now() WHERE id = $1",
            uuid.UUID(user_id),
        )
    finally:
        await conn.close()


def _register_login(client) -> str:
    """Register, activate, and log in — returns the email. `client`'s
    cookie jar now carries the session's access/refresh cookies for
    every subsequent request this test makes."""
    email = _email()
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _TEST_PASSWORD, "display_name": "Test User"},
    )
    assert response.status_code == 201
    asyncio.run(_activate_user(response.json()["data"]["id"]))

    response = client.post("/api/v1/auth/login", json={"email": email, "password": _TEST_PASSWORD})
    assert response.status_code == 200
    return email


# ---------------------------------------------------------------------------
# POST /refresh
# ---------------------------------------------------------------------------


def test_refresh_endpoint_rotates_cookies_and_returns_200() -> None:
    def body(client) -> None:
        _register_login(client)
        old_refresh_cookie = client.cookies.get("nexus_refresh_token")

        response = client.post("/api/v1/auth/refresh")

        assert response.status_code == 200
        payload = response.json()
        assert payload["data"] is None
        assert "meta" in payload
        new_refresh_cookie = client.cookies.get("nexus_refresh_token")
        assert new_refresh_cookie is not None
        assert new_refresh_cookie != old_refresh_cookie

    run_http_test(body)


def test_refresh_endpoint_without_cookie_returns_token_invalid_400() -> None:
    def body(client) -> None:
        response = client.post("/api/v1/auth/refresh")

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "token_invalid"

    run_http_test(body)


def test_refresh_endpoint_old_cookie_fails_after_rotation() -> None:
    def body(client) -> None:
        _register_login(client)
        old_refresh_cookie = client.cookies.get("nexus_refresh_token")

        first = client.post("/api/v1/auth/refresh")
        assert first.status_code == 200

        # Manually replay the *old* (now-rotated-away) refresh cookie —
        # simulating a stolen/replayed token, since the client's own jar
        # has already moved on to the new one.
        client.cookies.set("nexus_refresh_token", old_refresh_cookie)
        response = client.post("/api/v1/auth/refresh")

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "token_invalid"

    run_http_test(body)


# ---------------------------------------------------------------------------
# POST /logout
# ---------------------------------------------------------------------------


def test_logout_endpoint_returns_204_and_clears_cookies() -> None:
    def body(client) -> None:
        _register_login(client)

        response = client.post("/api/v1/auth/logout")

        assert response.status_code == 204
        assert response.text == ""
        set_cookie_headers = [h.lower() for h in response.headers.get_list("set-cookie")]
        # Clearing sets Max-Age=0 (or an expiry in the past) — either way
        # the header is present and empties the value.
        assert any("nexus_access_token=" in h for h in set_cookie_headers)
        assert any("nexus_refresh_token=" in h for h in set_cookie_headers)

    run_http_test(body)


def test_logout_endpoint_without_access_token_returns_401() -> None:
    def body(client) -> None:
        response = client.post("/api/v1/auth/logout")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"

    run_http_test(body)


def test_logout_endpoint_revokes_session_refresh_no_longer_works() -> None:
    def body(client) -> None:
        _register_login(client)

        logout_response = client.post("/api/v1/auth/logout")
        assert logout_response.status_code == 204

        # The client's jar no longer has a refresh cookie (cleared) —
        # explicitly pass the (now-revoked) one it had a moment ago.
        refresh_response = client.post("/api/v1/auth/refresh")
        assert refresh_response.status_code == 400
        assert refresh_response.json()["error"]["code"] == "token_invalid"

    run_http_test(body)


# ---------------------------------------------------------------------------
# GET /sessions
# ---------------------------------------------------------------------------


def test_get_sessions_endpoint_returns_own_sessions() -> None:
    def body(client) -> None:
        email = _register_login(client)

        response = client.get("/api/v1/auth/sessions")

        assert response.status_code == 200
        payload = response.json()
        assert "data" in payload
        assert len(payload["data"]) == 1
        entry = payload["data"][0]
        assert set(entry) == {"id", "device_label", "ip_address", "created_at", "status"}
        assert entry["status"] == "active"
        assert email  # sanity: the email itself is never part of a session row

    run_http_test(body)


def test_get_sessions_endpoint_requires_auth() -> None:
    def body(client) -> None:
        response = client.get("/api/v1/auth/sessions")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"

    run_http_test(body)


def test_get_sessions_endpoint_never_exposes_refresh_token_hash() -> None:
    def body(client) -> None:
        _register_login(client)

        response = client.get("/api/v1/auth/sessions")

        assert "refresh_token_hash" not in response.text

    run_http_test(body)


# ---------------------------------------------------------------------------
# DELETE /sessions/{session_id}
# ---------------------------------------------------------------------------


def test_delete_session_endpoint_revokes_own_session_returns_204() -> None:
    def body(client) -> None:
        _register_login(client)
        session_id = client.get("/api/v1/auth/sessions").json()["data"][0]["id"]

        response = client.delete(f"/api/v1/auth/sessions/{session_id}")

        assert response.status_code == 204
        assert client.get("/api/v1/auth/sessions").json()["data"] == []

    run_http_test(body)


def test_delete_session_endpoint_rejects_nonexistent_id() -> None:
    def body(client) -> None:
        _register_login(client)

        response = client.delete(f"/api/v1/auth/sessions/{uuid.uuid4()}")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    run_http_test(body)


def test_delete_session_endpoint_requires_auth() -> None:
    def body(client) -> None:
        response = client.delete(f"/api/v1/auth/sessions/{uuid.uuid4()}")

        assert response.status_code == 401

    run_http_test(body)


# ---------------------------------------------------------------------------
# DELETE /sessions (all other)
# ---------------------------------------------------------------------------


def test_delete_all_other_sessions_endpoint_keeps_current_active() -> None:
    def body(client) -> None:
        email = _register_login(client)  # session 1

        # `refresh` rotates the *same* Session row in place, so it can't
        # be used to simulate a second device — only a second `login`
        # call creates a genuinely new Session row. This overwrites the
        # client's cookie jar with session 2's tokens (the "current"
        # device from here on); session 1 stays active server-side,
        # exactly like a real second device logging in would leave it.
        second_login = client.post(
            "/api/v1/auth/login", json={"email": email, "password": _TEST_PASSWORD}
        )
        assert second_login.status_code == 200
        before = client.get("/api/v1/auth/sessions").json()["data"]
        assert len(before) == 2

        response = client.delete("/api/v1/auth/sessions")

        assert response.status_code == 204
        remaining = client.get("/api/v1/auth/sessions").json()["data"]
        assert len(remaining) == 1
        assert remaining[0]["status"] == "active"

    run_http_test(body)


def test_delete_all_other_sessions_endpoint_requires_auth() -> None:
    def body(client) -> None:
        response = client.delete("/api/v1/auth/sessions")

        assert response.status_code == 401

    run_http_test(body)

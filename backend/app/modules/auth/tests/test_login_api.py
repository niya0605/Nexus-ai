"""HTTP-level tests for POST /api/v1/auth/login.

Exercises the full request → response cycle via FastAPI's TestClient,
against the real database (see backend/tests/db.py's `run_http_test`
docstring). Covers exactly what test_login_service.py doesn't: the
actual status codes, the standard envelope shape, cookie attributes,
and that neither `password_hash` nor any token ever appears in the JSON
response body.
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
    """Flip a just-registered user straight to `active` — there is no
    email-verification endpoint yet (a later milestone).

    Uses a throwaway `asyncpg` connection of its own, deliberately NOT
    the shared `app.db.session.engine` — this call happens *mid*
    `with TestClient(...) as client:` block (between the register and
    login requests), while TestClient's own loop may still hold pooled
    connections on that same shared engine. Disposing the shared pool
    from here (as an earlier version of this helper did, mirroring
    `tests.db._cleanup_http_test_users`) is safe for that helper because
    it only ever runs *after* the TestClient block has fully closed —
    here it isn't, and doing so intermittently corrupted TestClient's
    own in-flight connection (`RuntimeError: Event loop is closed`,
    confirmed empirically). A fully independent connection never touches
    the shared pool at all, so there's nothing to corrupt.
    """
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


def _register_and_activate(client, email: str) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _TEST_PASSWORD, "display_name": "Test User"},
    )
    assert response.status_code == 201
    asyncio.run(_activate_user(response.json()["data"]["id"]))


def test_login_endpoint_returns_200_with_user_envelope() -> None:
    def body(client) -> None:
        email = _email()
        _register_and_activate(client, email)

        response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": _TEST_PASSWORD}
        )

        assert response.status_code == 200
        payload = response.json()
        assert "data" in payload and "meta" in payload
        assert "request_id" in payload["meta"]
        assert payload["data"]["email"] == email
        assert payload["data"]["status"] == "active"

    run_http_test(body)


def test_login_endpoint_sets_httponly_samesite_cookies() -> None:
    def body(client) -> None:
        email = _email()
        _register_and_activate(client, email)

        response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": _TEST_PASSWORD}
        )

        assert "nexus_access_token" in response.cookies
        assert "nexus_refresh_token" in response.cookies

        set_cookie_headers = [h.lower() for h in response.headers.get_list("set-cookie")]
        assert any("nexus_access_token" in h and "httponly" in h for h in set_cookie_headers)
        assert any("nexus_refresh_token" in h and "httponly" in h for h in set_cookie_headers)
        assert any("samesite=lax" in h for h in set_cookie_headers)
        # `Secure` is deliberately absent here: APP_ENV=local in this test
        # run, and the endpoint only sets Secure for staging/production
        # (see app/api/v1/endpoints/auth.py — a Secure cookie is silently
        # dropped by the browser over plain HTTP, which is exactly what
        # local dev uses).

    run_http_test(body)


def test_login_endpoint_response_never_contains_password_hash() -> None:
    def body(client) -> None:
        email = _email()
        _register_and_activate(client, email)

        response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": _TEST_PASSWORD}
        )

        assert "password_hash" not in response.text
        assert "password" not in response.json()["data"]

    run_http_test(body)


def test_login_endpoint_response_never_contains_tokens_or_hash() -> None:
    def body(client) -> None:
        email = _email()
        _register_and_activate(client, email)

        response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": _TEST_PASSWORD}
        )

        data = response.json()["data"]
        for forbidden_field in (
            "access_token",
            "refresh_token",
            "token_type",
            "expires_in",
            "refresh_token_hash",
        ):
            assert forbidden_field not in data
        assert "refresh_token_hash" not in response.text

    run_http_test(body)


def test_login_endpoint_wrong_password_returns_401() -> None:
    def body(client) -> None:
        email = _email()
        _register_and_activate(client, email)

        response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": "wrong-password"}
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"

    run_http_test(body)


def test_login_endpoint_nonexistent_email_returns_same_401() -> None:
    def body(client) -> None:
        response = client.post(
            "/api/v1/auth/login", json={"email": _email(), "password": _TEST_PASSWORD}
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"

    run_http_test(body)


def test_login_endpoint_pending_verification_returns_403() -> None:
    def body(client) -> None:
        email = _email()
        response = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": _TEST_PASSWORD, "display_name": "Test User"},
        )
        assert response.status_code == 201
        # Deliberately not activated — stays pending_verification.

        response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": _TEST_PASSWORD}
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "email_not_verified"

    run_http_test(body)

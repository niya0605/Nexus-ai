"""HTTP-level tests for POST /api/v1/auth/verify-email, POST
/api/v1/auth/resend-verification, POST /api/v1/auth/forgot-password, and
POST /api/v1/auth/reset-password.

Same real-app-via-TestClient approach as test_login_api.py/
test_session_api.py. Since the raw token is only ever delivered by
email (never returned by any endpoint — that's the whole point), these
tests reach into `app.modules.auth.token_store` directly to obtain a
real, usable token the same way a user's inbox would hand them one, and
separately confirm (where Mailpit is reachable) that a real email
actually got sent.
"""

import asyncio
import uuid

import asyncpg
import httpx
import pytest
from redis.asyncio import Redis
from tests.db import HTTP_TEST_EMAIL_DOMAIN, run_http_test

from app.config import settings
from app.db.redis import REDIS_URL
from app.modules.auth import token_store

_TEST_PASSWORD = "a-strong-password"
_NEW_PASSWORD = "a-different-strong-password"
_TTL_SECONDS = 3600

MAILPIT_API = f"http://{settings.mail.HOST}:8025/api/v1"


async def _issue_verification_token(user_id: uuid.UUID) -> str:
    """A dedicated, throwaway Redis connection — not the shared
    `app.db.redis.redis_client` singleton — for the same reason
    test_login_api.py's `_activate_user` uses a dedicated asyncpg
    connection rather than the shared engine: this runs in its own
    `asyncio.run()` *while* `TestClient`'s own loop may still be using
    the shared client, and touching the shared one from here corrupts
    it for TestClient's subsequent requests (confirmed empirically, the
    same failure mode `tests.db`'s module docstring documents for
    Postgres)."""
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        return await token_store.issue_verification_token(redis, user_id, _TTL_SECONDS)
    finally:
        await redis.aclose()


async def _issue_reset_token(user_id: uuid.UUID) -> str:
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        return await token_store.issue_reset_token(redis, user_id, _TTL_SECONDS)
    finally:
        await redis.aclose()


def _mailpit_available() -> bool:
    try:
        httpx.get(f"{MAILPIT_API}/messages", timeout=1).raise_for_status()
        return True
    except Exception:  # noqa: BLE001 — any failure means "treat as unavailable, skip"
        return False


def _clear_mailpit() -> None:
    try:
        httpx.delete(f"{MAILPIT_API}/messages", timeout=2)
    except Exception:  # noqa: S110, BLE001 — best-effort cleanup only, see _mailpit_available
        pass


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:8]}@{HTTP_TEST_EMAIL_DOMAIN}"


async def _get_user_id_and_status(email: str) -> tuple[str, str]:
    db = settings.database
    conn = await asyncpg.connect(
        host=db.HOST, port=db.PORT, database=db.DB, user=db.USER, password=db.PASSWORD
    )
    try:
        row = await conn.fetchrow("SELECT id, status FROM users WHERE email = $1", email)
        return str(row["id"]), row["status"]
    finally:
        await conn.close()


async def _activate(email: str) -> None:
    db = settings.database
    conn = await asyncpg.connect(
        host=db.HOST, port=db.PORT, database=db.DB, user=db.USER, password=db.PASSWORD
    )
    try:
        await conn.execute(
            "UPDATE users SET status='active', email_verified_at=now() WHERE email=$1", email
        )
    finally:
        await conn.close()


def _register(client, email: str) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _TEST_PASSWORD, "display_name": "Test User"},
    )
    assert response.status_code == 201
    return response.json()["data"]["id"]


# ---------------------------------------------------------------------------
# POST /verify-email
# ---------------------------------------------------------------------------


def test_verify_email_endpoint_activates_pending_user() -> None:
    def body(client) -> None:
        email = _email()
        user_id = _register(client, email)
        raw_token = asyncio.run(_issue_verification_token(uuid.UUID(user_id)))

        response = client.post("/api/v1/auth/verify-email", json={"token": raw_token})

        assert response.status_code == 200
        payload = response.json()
        assert payload["data"] is None
        assert "meta" in payload

        _, status = asyncio.run(_get_user_id_and_status(email))
        assert status == "active"

    run_http_test(body)


def test_verify_email_endpoint_rejects_bad_token() -> None:
    def body(client) -> None:
        response = client.post("/api/v1/auth/verify-email", json={"token": "not-a-real-token"})

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "token_invalid"

    run_http_test(body)


def test_verify_email_endpoint_response_never_contains_a_token() -> None:
    def body(client) -> None:
        email = _email()
        user_id = _register(client, email)
        raw_token = asyncio.run(_issue_verification_token(uuid.UUID(user_id)))

        response = client.post("/api/v1/auth/verify-email", json={"token": raw_token})

        assert raw_token not in response.text

    run_http_test(body)


# ---------------------------------------------------------------------------
# POST /resend-verification
# ---------------------------------------------------------------------------


def test_resend_verification_endpoint_returns_202_for_pending_user() -> None:
    def body(client) -> None:
        email = _email()
        _register(client, email)

        response = client.post("/api/v1/auth/resend-verification", json={"email": email})

        assert response.status_code == 202
        assert response.json()["data"] is None

    run_http_test(body)


def test_resend_verification_endpoint_returns_identical_202_for_nonexistent_email() -> None:
    def body(client) -> None:
        response = client.post("/api/v1/auth/resend-verification", json={"email": _email()})

        assert response.status_code == 202
        assert response.json()["data"] is None

    run_http_test(body)


def test_resend_verification_endpoint_sends_a_real_email_via_mailpit() -> None:
    if not _mailpit_available():
        pytest.skip("Mailpit not reachable at localhost:8025")

    def body(client) -> None:
        email = _email()
        _register(client, email)
        _clear_mailpit()

        response = client.post("/api/v1/auth/resend-verification", json={"email": email})
        assert response.status_code == 202

        messages = httpx.get(f"{MAILPIT_API}/messages", timeout=2).json()
        assert messages["total"] >= 1
        assert messages["messages"][0]["To"][0]["Address"] == email
        assert "verify" in messages["messages"][0]["Subject"].lower()

        _clear_mailpit()

    run_http_test(body)


# ---------------------------------------------------------------------------
# POST /forgot-password
# ---------------------------------------------------------------------------


def test_forgot_password_endpoint_returns_202_for_existing_email() -> None:
    def body(client) -> None:
        email = _email()
        _register(client, email)
        asyncio.run(_activate(email))

        response = client.post("/api/v1/auth/forgot-password", json={"email": email})

        assert response.status_code == 202
        assert response.json()["data"] is None

    run_http_test(body)


def test_forgot_password_endpoint_returns_identical_202_for_nonexistent_email() -> None:
    def body(client) -> None:
        response = client.post("/api/v1/auth/forgot-password", json={"email": _email()})

        assert response.status_code == 202
        assert response.json()["data"] is None

    run_http_test(body)


def test_forgot_password_endpoint_response_never_contains_a_token() -> None:
    def body(client) -> None:
        email = _email()
        _register(client, email)
        asyncio.run(_activate(email))

        response = client.post("/api/v1/auth/forgot-password", json={"email": email})

        # Nothing token-shaped (a long opaque string) belongs in this
        # body at all — the response is `{"data": null, "meta": {...}}`.
        assert response.json()["data"] is None

    run_http_test(body)


# ---------------------------------------------------------------------------
# POST /reset-password
# ---------------------------------------------------------------------------


def test_reset_password_endpoint_succeeds_and_new_password_works_for_login() -> None:
    def body(client) -> None:
        email = _email()
        user_id = _register(client, email)
        asyncio.run(_activate(email))
        raw_token = asyncio.run(_issue_reset_token(uuid.UUID(user_id)))

        response = client.post(
            "/api/v1/auth/reset-password", json={"token": raw_token, "new_password": _NEW_PASSWORD}
        )

        assert response.status_code == 200
        assert response.json()["data"] is None

        login_response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": _NEW_PASSWORD}
        )
        assert login_response.status_code == 200

    run_http_test(body)


def test_reset_password_endpoint_rejects_bad_token() -> None:
    def body(client) -> None:
        response = client.post(
            "/api/v1/auth/reset-password",
            json={"token": "not-a-real-token", "new_password": _NEW_PASSWORD},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "token_invalid"

    run_http_test(body)


def test_reset_password_endpoint_rejects_weak_password() -> None:
    def body(client) -> None:
        email = _email()
        user_id = _register(client, email)
        asyncio.run(_activate(email))
        raw_token = asyncio.run(_issue_reset_token(uuid.UUID(user_id)))

        response = client.post(
            "/api/v1/auth/reset-password", json={"token": raw_token, "new_password": "short"}
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "password_too_weak"

    run_http_test(body)


def test_reset_password_endpoint_revokes_active_sessions() -> None:
    def body(client) -> None:
        email = _email()
        user_id = _register(client, email)
        asyncio.run(_activate(email))

        login_response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": _TEST_PASSWORD}
        )
        assert login_response.status_code == 200
        old_refresh_cookie = client.cookies.get("nexus_refresh_token")

        raw_token = asyncio.run(_issue_reset_token(uuid.UUID(user_id)))
        reset_response = client.post(
            "/api/v1/auth/reset-password", json={"token": raw_token, "new_password": _NEW_PASSWORD}
        )
        assert reset_response.status_code == 200

        # The session that was active before the reset must no longer
        # refresh — proving Session revocation actually took effect.
        client.cookies.set("nexus_refresh_token", old_refresh_cookie)
        refresh_response = client.post("/api/v1/auth/refresh")
        assert refresh_response.status_code == 400
        assert refresh_response.json()["error"]["code"] == "token_invalid"

    run_http_test(body)


def test_reset_password_endpoint_response_never_contains_password_or_hash() -> None:
    def body(client) -> None:
        email = _email()
        user_id = _register(client, email)
        asyncio.run(_activate(email))
        raw_token = asyncio.run(_issue_reset_token(uuid.UUID(user_id)))

        response = client.post(
            "/api/v1/auth/reset-password", json={"token": raw_token, "new_password": _NEW_PASSWORD}
        )

        assert _NEW_PASSWORD not in response.text
        assert "password_hash" not in response.text
        assert "refresh_token_hash" not in response.text

    run_http_test(body)

"""HTTP-level tests for POST /api/v1/auth/register.

Exercises the full request → response cycle (route, service, real
database) via FastAPI's TestClient, against the real `engine`/`get_db`
(see backend/tests/db.py's `run_http_test` docstring for why this
doesn't use the same transactional-rollback pattern as the
service-level tests). Covers exactly what the schema/service tests
don't: the actual status codes, the standard success/error envelope
shapes, and that `password_hash` never appears in a response.
"""

import uuid

from tests.db import HTTP_TEST_EMAIL_DOMAIN, run_http_test


def _payload(**overrides: object) -> dict:
    # Every email MUST end in HTTP_TEST_EMAIL_DOMAIN — run_http_test's
    # post-test cleanup only deletes rows matching that pattern.
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4().hex[:8]}@{HTTP_TEST_EMAIL_DOMAIN}",
        "password": "a-strong-password",
        "display_name": "Test User",
    }
    defaults.update(overrides)
    return defaults


def test_register_endpoint_returns_201_with_envelope() -> None:
    def body(client) -> None:
        response = client.post("/api/v1/auth/register", json=_payload())

        assert response.status_code == 201
        payload = response.json()
        assert "data" in payload and "meta" in payload
        assert "request_id" in payload["meta"]

        data = payload["data"]
        assert data["status"] == "pending_verification"
        assert "id" in data
        assert "email" in data
        assert "display_name" in data

    run_http_test(body)


def test_register_endpoint_never_returns_password_hash() -> None:
    def body(client) -> None:
        response = client.post("/api/v1/auth/register", json=_payload())
        raw_body = response.text

        assert "password_hash" not in raw_body
        assert "password" not in response.json()["data"]

    run_http_test(body)


def test_register_endpoint_duplicate_email_returns_409() -> None:
    def body(client) -> None:
        payload = _payload()
        first = client.post("/api/v1/auth/register", json=payload)
        assert first.status_code == 201

        second = client.post("/api/v1/auth/register", json=payload)
        assert second.status_code == 409

        error = second.json()["error"]
        assert error["code"] == "email_already_registered"
        assert "request_id" in error

    run_http_test(body)


def test_register_endpoint_invalid_email_returns_422() -> None:
    def body(client) -> None:
        response = client.post("/api/v1/auth/register", json=_payload(email="not-an-email"))

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "validation_error"
        assert any(d["field"] == "body.email" for d in error["details"])

    run_http_test(body)


def test_register_endpoint_invalid_password_returns_422() -> None:
    def body(client) -> None:
        response = client.post("/api/v1/auth/register", json=_payload(password="short"))

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "validation_error"
        assert any(d["field"] == "body.password" for d in error["details"])

    run_http_test(body)


def test_register_endpoint_invalid_display_name_returns_422() -> None:
    def body(client) -> None:
        response = client.post("/api/v1/auth/register", json=_payload(display_name="a" * 101))

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "validation_error"
        assert any(d["field"] == "body.display_name" for d in error["details"])

    run_http_test(body)

"""Tests for app/core/mailer.py — real SMTP against local Mailpit
(docker-compose.yml's `mailpit` service), per S1E's own instruction to
verify "development SMTP/Mailpit integration works if available" rather
than mocking it away entirely.

Uses Mailpit's own REST API (`GET/DELETE /api/v1/messages`) to assert
what actually arrived — not a mock of `smtplib`.
"""

import httpx
import pytest

from app.config import settings
from app.core.mailer import send_email

MAILPIT_API = f"http://{settings.mail.HOST}:8025/api/v1"


def _mailpit_available() -> bool:
    try:
        httpx.get(f"{MAILPIT_API}/messages", timeout=1).raise_for_status()
        return True
    except Exception:  # noqa: BLE001 — any failure means "treat as unavailable, skip"
        return False


pytestmark = pytest.mark.skipif(
    not _mailpit_available(),
    reason="Mailpit not reachable at localhost:8025 — skipping real SMTP test",
)


def _clear_mailpit() -> None:
    httpx.delete(f"{MAILPIT_API}/messages", timeout=2)


def test_send_email_is_actually_captured_by_mailpit() -> None:
    _clear_mailpit()

    import asyncio

    asyncio.run(
        send_email(
            to="mailer-test@example.com",
            subject="S1E mailer test subject",
            body="S1E mailer test body content",
        )
    )

    response = httpx.get(f"{MAILPIT_API}/messages", timeout=2)
    data = response.json()

    assert data["total"] >= 1
    latest = data["messages"][0]
    assert latest["Subject"] == "S1E mailer test subject"
    assert latest["To"][0]["Address"] == "mailer-test@example.com"

    _clear_mailpit()

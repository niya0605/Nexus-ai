"""Generic outbound email sending — stdlib SMTP only, no new dependency.

The one place any code sends an email. Domain modules (e.g.
`app.modules.auth.mail`) build the subject/body and call `send_email`
here; they never construct an `smtplib.SMTP` connection themselves —
per S1E's own instruction that "the authentication service should not
contain low-level SMTP code."

Named `mailer`, not `mail`, specifically to avoid reading like
`settings.mail` (the connection *parameters*, `app.config.settings`) —
this module is the thing that actually *uses* those parameters to send
something.

Development routes through Mailpit (`docker-compose.yml`'s `mailpit`
service — captured mail, no auth, no TLS, viewable at its web UI) via
`settings.mail`. No production email provider is wired in — S1E's own
scope explicitly says not to introduce one unless a frozen
configuration names it, and none does.
"""

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)


def _send_sync(*, to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.mail.FROM
    message["To"] = to
    message.set_content(body)

    with smtplib.SMTP(settings.mail.HOST, settings.mail.PORT) as smtp:
        # Mailpit (local dev) needs neither TLS nor auth — matching
        # .env.example's blank-by-default MAIL_USERNAME/MAIL_PASSWORD.
        # No STARTTLS call: a real provider in staging/production would
        # need one, but wiring that up is exactly the "production email
        # provider" this milestone's scope says not to introduce.
        if settings.mail.USERNAME and settings.mail.PASSWORD:
            smtp.login(settings.mail.USERNAME, settings.mail.PASSWORD)
        smtp.send_message(message)


async def send_email(*, to: str, subject: str, body: str) -> None:
    """Send one plain-text email. Blocking SMTP I/O runs off the event
    loop via `asyncio.to_thread` — this is an async application
    end-to-end (per app/db/session.py's own rationale for `AsyncEngine`),
    and stdlib `smtplib` has no async form.

    Raises on failure (a genuine SMTP/connection error) — callers in
    the auth service layer are responsible for deciding whether a
    failed send should be fatal to the request or merely logged; this
    function itself never silently swallows one.
    """
    await asyncio.to_thread(_send_sync, to=to, subject=subject, body=body)

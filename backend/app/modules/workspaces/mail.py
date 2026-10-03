"""Invitation email content — the workspaces module's own mail layer,
same architecture `app/modules/auth/mail.py` already established: build
the subject/body here, call `app.core.mailer.send_email` to actually
send it, never touch SMTP directly.

**IMPLEMENTATION CHOICE, not a frozen requirement:** exact copy/subject
lines are not specified by any frozen document (none exists — see
`app/modules/auth/mail.py`'s identical note). Minimal, functional
plain-text templates, same standard this codebase already holds every
other transactional email to.

**No frontend base URL exists** (`app/modules/auth/mail.py`'s exact same
gap, unchanged by this sprint — S1G's own scope explicitly excludes
frontend UI) — the email includes the raw invitation token as a value
the recipient copies into `GET /api/v1/invitations/{token}`, not a
clickable `https://.../invitations/accept?token=...` link. A future
frontend milestone turns this into a real link once that setting exists.
"""

from app.core.mailer import send_email


async def send_invitation_email(
    *, to: str, workspace_name: str, inviter_display_name: str, role_name: str, raw_token: str
) -> None:
    await send_email(
        to=to,
        subject=f"You've been invited to join {workspace_name} on Nexus AI",
        body=(
            f"{inviter_display_name} has invited you to join the {workspace_name} "
            f"workspace on Nexus AI as {role_name}.\n\n"
            "Use the invitation token below to view and accept the invitation. "
            "This token expires and can only be used once.\n\n"
            f"{raw_token}\n\n"
            "If you weren't expecting this invitation, you can safely ignore this email."
        ),
    )

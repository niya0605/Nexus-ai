"""Auth-specific email content — verification and password-reset emails.

Builds the subject/body and calls `app.core.mailer.send_email`; never
touches SMTP directly (that stays behind `app.core.mailer`).

**IMPLEMENTATION CHOICE, not a frozen requirement:** the frozen
documents this was built from don't specify exact email copy, subject
lines, or branding (docs/product/, docs/ux/ describe no such template).
These are minimal, functional plain-text templates — a link the user
clicks, nothing more — explicitly not a claim of frozen copy.

Neither template embeds a clickable frontend URL from a settings value,
because no such "frontend base URL" setting exists yet in
`app.config.settings` and inventing one is outside S1E's explicit scope
(no frontend UI). The email body includes the raw token itself with a
short instruction, which a future frontend milestone can turn into a
real link (`https://.../verify-email?token=...`) once that setting
exists — see the sprint report for this exact gap.
"""

from app.core.mailer import send_email


async def send_verification_email(*, to: str, raw_token: str) -> None:
    await send_email(
        to=to,
        subject="Verify your Nexus AI email address",
        body=(
            "Welcome to Nexus AI.\n\n"
            "Use the code below to verify your email address. This code "
            "expires soon and can only be used once.\n\n"
            f"{raw_token}\n\n"
            "If you didn't create a Nexus AI account, you can ignore this email."
        ),
    )


async def send_password_reset_email(*, to: str, raw_token: str) -> None:
    await send_email(
        to=to,
        subject="Reset your Nexus AI password",
        body=(
            "We received a request to reset your Nexus AI password.\n\n"
            "Use the code below to set a new password. This code expires "
            "soon and can only be used once.\n\n"
            f"{raw_token}\n\n"
            "If you didn't request this, you can safely ignore this email — "
            "your password will not be changed."
        ),
    )

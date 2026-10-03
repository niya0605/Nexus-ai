"""Centralized field-level validation and normalization rules.

Implements the frozen Data Dictionary's Shared Validation Standards
(Section 15) — one function per field type, reused by every schema that
needs it rather than reimplemented per module. Sprint 1B is the first
consumer (app/modules/auth/schemas.py); future modules (workspace name,
document title, collection name, tag name, …) reuse these same
functions or add siblings here as they're needed, per that same
centralized-standards document.

Pydantic's `EmailStr` (via the `email-validator` package) already
enforces RFC 5322 format at the type-coercion step, before
`normalize_email` below ever runs — so this module only does the
transformation and length check the frozen standard adds on top of
"is it a valid email."
"""

import unicodedata

MAX_EMAIL_LENGTH = 255
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
MAX_DISPLAY_NAME_LENGTH = 100
MAX_WORKSPACE_NAME_LENGTH = 100
MAX_DOCUMENT_TITLE_LENGTH = 255


def normalize_email(value: str) -> str:
    """Trim and lowercase — matches the database's case-insensitive uniqueness."""
    normalized = value.strip().lower()
    if len(normalized) > MAX_EMAIL_LENGTH:
        raise ValueError(f"Email must be at most {MAX_EMAIL_LENGTH} characters")
    return normalized


def validate_password(value: str) -> str:
    """Length-only policy (NIST 800-63B): no mandated composition rules.

    Never trimmed, never case-folded — passwords are compared exactly.
    """
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(value) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_LENGTH} characters")
    return value


def normalize_display_name(value: str) -> str:
    """Trim, collapse internal whitespace runs, reject control characters."""
    normalized = " ".join(value.strip().split())
    if not normalized:
        raise ValueError("Display name is required")
    if len(normalized) > MAX_DISPLAY_NAME_LENGTH:
        raise ValueError(f"Display name must be at most {MAX_DISPLAY_NAME_LENGTH} characters")
    if any(unicodedata.category(ch) == "Cc" for ch in normalized):
        raise ValueError("Display name cannot contain control characters")
    return normalized


def normalize_workspace_name(value: str) -> str:
    """S1F — Workspace.name: trim, collapse internal whitespace runs, NFC
    normalize, reject control characters, ≤100 chars. Deliberately the
    same shape as `normalize_display_name` (this is exactly what "max
    100 characters, printable Unicode, no control characters, trim
    surrounding whitespace, collapse internal whitespace runs" already
    means) plus one addition the frozen spec names explicitly for this
    field and not for display names: NFC normalization, so two visually
    identical names that differ only in Unicode composition never both
    exist as "different" workspace names.
    """
    normalized = unicodedata.normalize("NFC", " ".join(value.strip().split()))
    if not normalized:
        raise ValueError("Workspace name is required")
    if len(normalized) > MAX_WORKSPACE_NAME_LENGTH:
        raise ValueError(f"Workspace name must be at most {MAX_WORKSPACE_NAME_LENGTH} characters")
    if any(unicodedata.category(ch) == "Cc" for ch in normalized):
        raise ValueError("Workspace name cannot contain control characters")
    return normalized


def normalize_document_title(value: str) -> str:
    """S2A — Document.title: same shape as `normalize_workspace_name`
    (trim, collapse internal whitespace runs, NFC normalize, reject
    control characters) — no frozen Data Dictionary length/format spec
    exists for this field (the document itself isn't present in this
    repository), so this reuses the identical, already-established
    normalization rule for "a short, human-entered display name," with
    its own **IMPLEMENTATION CHOICE** length ceiling
    (`MAX_DOCUMENT_TITLE_LENGTH` = 255, matching `original_filename`'s
    own chosen column width in `app.modules.documents.models` — a
    document title is plausibly longer than a workspace name, but still
    a single-line display string, not free-form text).
    """
    normalized = unicodedata.normalize("NFC", " ".join(value.strip().split()))
    if not normalized:
        raise ValueError("Document title is required")
    if len(normalized) > MAX_DOCUMENT_TITLE_LENGTH:
        raise ValueError(f"Document title must be at most {MAX_DOCUMENT_TITLE_LENGTH} characters")
    if any(unicodedata.category(ch) == "Cc" for ch in normalized):
        raise ValueError("Document title cannot contain control characters")
    return normalized

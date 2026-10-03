"""Workspace slug generation.

**IMPLEMENTATION CHOICE — no frozen slug algorithm exists to copy.**
`slugify()` here is the pure "name → candidate slug" transformation
only (lowercase ASCII letters/numbers/hyphens, no leading/trailing or
consecutive hyphens, ≤100 chars, matching S1F's stated slug
constraints exactly). It never touches the database — collision
resolution against the `workspaces.slug` unique constraint needs a
session, so that loop lives in `app.modules.workspaces.service`
instead, right next to the insert it's protecting.
"""

import re
import unicodedata

MAX_SLUG_LENGTH = 100
_NON_SLUG_CHARS = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Derive a candidate slug from a workspace name.

    Transliterates to ASCII (accented/non-Latin characters are dropped,
    not preserved — e.g. "Café Team" → "caf-team"), lowercases,
    collapses every run of non-alphanumeric characters to a single
    hyphen, and trims leading/trailing hyphens. A name with no
    ASCII-transliterable characters at all (e.g. purely CJK or emoji)
    falls back to the literal string `"workspace"` — never an empty
    string, which the unique constraint would treat as one single
    contested value for every such workspace.
    """
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    candidate = _NON_SLUG_CHARS.sub("-", ascii_name.lower()).strip("-")
    if not candidate:
        candidate = "workspace"
    return candidate[:MAX_SLUG_LENGTH].strip("-") or "workspace"

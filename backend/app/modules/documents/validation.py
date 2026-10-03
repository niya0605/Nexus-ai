"""File-type derivation and content validation for uploaded documents.

**Documented validation boundary — not full MIME/content-type
sniffing.** S2A's own instructions permit this explicitly: "if MIME/
content sniffing is required by the frozen specifications, implement
it; otherwise document the current validation boundary." No frozen
specification (Product/UX/TDD/Data Dictionary) exists in this
repository to require a specific sniffing depth, so this implements a
lightweight, best-effort magic-byte check for the two binary formats
that have a reliable one (`pdf`, `docx`) and explicitly does *not*
attempt content sniffing for `txt`/`md` — arbitrary plain text has no
magic number to check. This is a real, if partial, defense against
"never trust filename extensions alone": a `.pdf` upload whose first
bytes aren't `%PDF-` is rejected before ever reaching storage; a
`.txt` upload is accepted based on extension + declared allowed-types
membership alone, same as every other API on the public internet that
accepts plain text.
"""

import pathlib

# The frozen four supported formats — same vocabulary
# `app.modules.workspaces.schemas.ALLOWED_FILE_TYPES` (S1F) already
# established for `WorkspaceSettings.allowed_file_types`; not
# re-imported from there to avoid a documents→workspaces schema-module
# coupling for one constant, but the values themselves must always
# match — enforced by `test_validation.py::test_supported_file_types_matches_workspace_settings_vocabulary`.
SUPPORTED_FILE_TYPES = ("pdf", "docx", "txt", "md")

# Magic-byte signatures for the binary formats above — absent entries
# (txt, md) mean "no check possible, always passes" (see module
# docstring).
_MAGIC_BYTES: dict[str, bytes] = {
    "pdf": b"%PDF-",
    "docx": b"PK\x03\x04",  # DOCX is a ZIP archive (OOXML) — the ZIP local-file-header signature.
}

# Read this many leading bytes to check against `_MAGIC_BYTES` — longer
# than the longest signature above, deliberately small so callers can
# cheaply peek at a stream's start without a second full read.
MAGIC_BYTES_PEEK_LENGTH = 8


def derive_file_type(filename: str) -> str | None:
    """Extract the lowercase extension (without the leading dot) from a
    filename, or `None` if it has none. A pure string operation — the
    filename itself is never used to build a storage path (see
    `app.modules.documents.service._generate_storage_key`), only to
    classify the upload and for display (`Document.original_filename`).
    """
    suffix = pathlib.PurePosixPath(filename).suffix
    if not suffix:
        return None
    return suffix.removeprefix(".").lower()


def content_matches_declared_type(file_type: str, header_bytes: bytes) -> bool:
    """Best-effort magic-byte check — see this module's own docstring
    for the documented boundary. Always `True` for a file type with no
    known signature (`txt`, `md`, or any type not in `_MAGIC_BYTES`)."""
    expected = _MAGIC_BYTES.get(file_type)
    if expected is None:
        return True
    return header_bytes.startswith(expected)

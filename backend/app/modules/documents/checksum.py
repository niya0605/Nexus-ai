"""Streaming checksum + size computation for uploaded document content.

**IMPLEMENTATION CHOICE — algorithm:** SHA-256, matching every other
content hash already in this codebase (`app.core.security.hash_refresh_token`,
the email-verification/password-reset tokens it backs) — no frozen
document names a specific checksum algorithm for `DocumentVersion.checksum`
("the frozen checksum strategy" is referenced but never spelled out with
an exact algorithm), so this reuses the project's one existing hashing
convention rather than introducing a second.

**Streaming, not whole-file buffering:** `compute_checksum_and_size`
reads `UploadFile` in fixed-size chunks (`_CHUNK_SIZE`, 1 MiB), updating
a running `hashlib.sha256()` instance per chunk — the hash state itself
is small and constant-size regardless of file size; nothing here ever
holds the full file content in a second, separate buffer. FastAPI's
`UploadFile` already backs itself with Starlette's `SpooledTemporaryFile`
(small uploads stay in memory up to a threshold, large ones spill to
disk automatically) — this function reads through that same underlying
stream once, then the caller (`app.modules.documents.service`) seeks it
back to the start (`await file.seek(0)`) and hands the *same* file
object to `app.core.storage.put_object` for the actual upload, which
reads it a second time. Two logical passes over the data, but only one
copy of it ever exists on disk/in Starlette's own buffer — this module
never allocates a second full-file buffer of its own.
"""

import hashlib

from fastapi import UploadFile

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


async def compute_checksum_and_size(
    file: UploadFile, *, max_bytes: int | None = None
) -> tuple[str, int]:
    """Read `file` once, from its current position to EOF, returning
    `(sha256_hex_digest, total_bytes_read)`.

    If `max_bytes` is given and the running total exceeds it, reading
    stops immediately (rather than continuing to hash/count an
    obviously-oversized file to completion) — the returned size is only
    guaranteed accurate (not merely ">max_bytes") when reading completed
    normally; callers passing `max_bytes` are expected to treat a
    returned size `> max_bytes` purely as a "reject" signal, never as
    the file's true length.

    Leaves the stream positioned at EOF (or wherever reading stopped) —
    the caller is responsible for `await file.seek(0)` before any
    further read (e.g. the actual storage upload).
    """
    hasher = hashlib.sha256()
    total = 0
    while True:
        chunk = await file.read(_CHUNK_SIZE)
        if not chunk:
            break
        hasher.update(chunk)
        total += len(chunk)
        if max_bytes is not None and total > max_bytes:
            break
    return hasher.hexdigest(), total

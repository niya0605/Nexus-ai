"""Object-storage abstraction — the one place any code talks to MinIO.

Endpoint/service code never constructs a `minio.Minio` client or touches
its API directly, per S2A's own instruction ("do not let endpoint code
directly manipulate MinIO clients") — the exact same architectural rule
`app/core/mailer.py` already established for SMTP, and this module
mirrors it deliberately: a lazily-constructed shared client, every
blocking call wrapped in `asyncio.to_thread` (the official `minio`
package is sync-only — there is no async-native MinIO/S3 client this
project already depends on, and introducing one now would be a second,
inconsistent I/O pattern next to `mailer.py`'s own sync-library-via-
`to_thread` precedent).

**IMPLEMENTATION CHOICE — library selection:** the official `minio`
Python SDK (PyPI: `minio`) was added as a new dependency this sprint —
purpose-built for MinIO specifically (vs. a general S3 SDK like
`boto3`), matching `app.config.settings.MinIOSettings`'s existing
`ENDPOINT`/`ROOT_USER`/`ROOT_PASSWORD`/`BUCKET` shape with no extra
translation needed.

**IMPLEMENTATION CHOICE — TLS:** `secure=False` (plain HTTP) — local
development's MinIO (docker-compose.yml / this sprint's Homebrew
equivalent) speaks plain HTTP on port 9000, and `MinIOSettings.ENDPOINT`
is validated as a bare `host:port` with no scheme, so there is no
signal in configuration to decide this from. No frozen document
specifies production TLS behavior for this connection; a production
deployment would need this to become configurable, flagged here and in
the sprint report as an UNRESOLVED CONTRACT GAP.

Credentials/bucket/endpoint are read only from `app.config.settings` —
never hardcoded, never logged, never returned to a caller.
"""

import asyncio
import logging

from minio import Minio
from minio.error import S3Error

from app.config import settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Raised for any object-storage failure — a PUT that fails, a
    bucket that can't be created/reached, or any other MinIO-level
    error. Deliberately generic and deliberately never carries the
    underlying MinIO exception's raw message in a way that could leak
    connection details — callers (the documents service layer) decide
    how a storage failure maps to an API-level error (S2A:
    `upload_storage_failure`, 502); this exception only signals "the
    storage operation did not succeed."
    """


_client: Minio | None = None
_bucket_ensured = False


def _get_client() -> Minio:
    """Lazily construct the shared MinIO client — mirrors
    `app.db.session`/`app.db.redis`'s "build once from settings, reuse"
    pattern. Never opens a network connection at import time; the
    `minio` SDK itself is lazy (a real HTTP call only happens on the
    first actual operation)."""
    global _client
    if _client is None:
        m = settings.minio
        _client = Minio(m.ENDPOINT, access_key=m.ROOT_USER, secret_key=m.ROOT_PASSWORD, secure=False)
    return _client


def _ensure_bucket_sync() -> None:
    client = _get_client()
    try:
        if not client.bucket_exists(settings.minio.BUCKET):
            client.make_bucket(settings.minio.BUCKET)
    except S3Error as exc:
        logger.error(f"Failed to ensure storage bucket exists: {exc.code}")
        raise StorageError("Could not verify or create the storage bucket.") from exc


async def _ensure_bucket() -> None:
    """Idempotent, memoized per-process — the bucket-existence check
    only needs to actually hit MinIO once; every subsequent call in this
    process is a no-op. Not a startup hook (no frozen requirement calls
    for one) — the first real upload pays this cost once."""
    global _bucket_ensured
    if _bucket_ensured:
        return
    await asyncio.to_thread(_ensure_bucket_sync)
    _bucket_ensured = True


def _put_object_sync(key: str, file_obj, length: int, content_type: str) -> None:
    client = _get_client()
    try:
        client.put_object(
            settings.minio.BUCKET, key, file_obj, length=length, content_type=content_type
        )
    except S3Error as exc:
        # Never logs `exc` verbatim — a MinIO S3Error's string form can
        # include request/response internals; only the stable `.code`
        # (e.g. "NoSuchBucket") is safe to log, matching this codebase's
        # "no secrets in exceptions/logs" standard everywhere else.
        logger.error(f"Object storage PUT failed for key={key}: {exc.code}")
        raise StorageError("Object storage upload failed.") from exc
    except Exception as exc:  # noqa: BLE001 — any other failure (connection refused, etc.)
        logger.error(f"Object storage PUT failed for key={key}: {type(exc).__name__}")
        raise StorageError("Object storage upload failed.") from exc


async def put_object(*, key: str, file_obj, length: int, content_type: str) -> None:
    """Upload `file_obj` (any file-like object supporting `.read()`,
    positioned at the start) to `key` under the configured bucket.

    `length` must be the exact byte count (the `minio` SDK requires a
    known content length for a single-shot `put_object` call — see
    `app.modules.documents.service` for how this is obtained via the
    same streaming read that computes the version's checksum, without
    ever buffering the whole file a second time).

    Raises `StorageError` on any failure — callers are responsible for
    the S2A-specific compensating-update behavior (mark the Document
    `failed`, return `upload_storage_failure`); this function itself
    never touches the database.
    """
    await _ensure_bucket()
    await asyncio.to_thread(_put_object_sync, key, file_obj, length, content_type)


def _object_exists_sync(key: str) -> bool:
    client = _get_client()
    try:
        client.stat_object(settings.minio.BUCKET, key)
        return True
    except S3Error as exc:
        if exc.code in ("NoSuchKey", "NoSuchObject"):
            return False
        logger.error(f"Object storage existence check failed for key={key}: {exc.code}")
        raise StorageError("Object storage existence check failed.") from exc


async def object_exists(key: str) -> bool:
    """Check whether `key` currently exists in the configured bucket.
    Not on S2A's own critical path (no endpoint currently needs it) —
    provided because S2A's own scope names "existence check if required"
    as part of the abstraction's required shape, and a later sprint
    (e.g. a repair/reconciliation job) is a plausible near-term consumer.
    """
    await _ensure_bucket()
    return await asyncio.to_thread(_object_exists_sync, key)


def _delete_object_sync(key: str) -> None:
    client = _get_client()
    try:
        client.remove_object(settings.minio.BUCKET, key)
    except S3Error as exc:
        logger.error(f"Object storage delete failed for key={key}: {exc.code}")
        raise StorageError("Object storage delete failed.") from exc


async def delete_object(key: str) -> None:
    """Delete `key` from the configured bucket.

    **Not called anywhere in S2A's own endpoints.** The frozen lifecycle
    this sprint implements never physically destroys object-storage
    content — soft-delete, archive, and superseding a version all
    explicitly preserve the underlying object. Provided so the
    abstraction's documented required shape ("delete only where the
    frozen lifecycle requires it") is complete and available the moment
    a future sprint's lifecycle (e.g. a real retention/purge worker)
    needs it, without a second storage module being written then.
    """
    await _ensure_bucket()
    await asyncio.to_thread(_delete_object_sync, key)

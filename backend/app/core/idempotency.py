"""Generic `Idempotency-Key` replay cache — Redis-backed, reusable by any
state-changing endpoint the frozen contract marks idempotency-required.

**Fills a previously-documented gap, does not duplicate anything.**
No shared idempotency-key store existed anywhere in this codebase before
S1G: `app/api/v1/endpoints/auth.py`'s own module docstring records that
registration's `Idempotency-Key` requirement was deliberately left
unenforced because "enforcing it needs the Redis-backed key store
described in the Technical Design Document (Section 30)... Still
deferred." S1G's own scope is the first to explicitly require building
that store ("Reuse the shared idempotency mechanism if it already
exists. Do NOT create invitation-specific idempotency logic if a shared
mechanism exists.") — since none existed, this module *is* that shared
mechanism now, deliberately generic (no `invitation` in any name here)
so a later sprint that finally wires it into registration, or any other
idempotency-required endpoint, reuses this instead of writing a second
one.

**IMPLEMENTATION CHOICE — the exact mechanics below are this module's
own design, not a contract quote:** no frozen document specifies a key
format, TTL, or concurrency behavior for "Section 30"'s store (the
Technical Design Document itself isn't a file in this repository — see
docs/architecture/README.md). What *is* implemented: a finished
response (status code + JSON body) is cached under
`(scope, actor, Idempotency-Key)` and replayed verbatim on a repeat —
enough to satisfy "a retried request returns the same result instead of
creating a second resource" for the ordinary case (a client retrying
after a timeout/dropped connection, once the first attempt already
finished).

**UNRESOLVED GAP, explicitly not implemented:** this does not implement
request *coalescing* or a distributed lock for two literally-concurrent
requests bearing the same key, both arriving before either has stored a
result — S1G's own text names the reason this is an acceptable gap for
now: "Database uniqueness remains the final duplicate-prevention
backstop." That backstop (the invitations table's partial unique index
on pending invitations; the memberships table's partial unique index on
active membership) is what actually protects correctness in that rare
race, not this cache. A future sprint building true request coalescing
(e.g. a short-lived `SET NX` reservation) can extend this module without
changing its public interface.

**S2A extension — payload fingerprinting.** S2A's own contract adds a
requirement S1G's two call sites never needed: distinguishing "the same
Idempotency-Key, retried with the identical payload" (replay the cached
result) from "the same key, reused for a *different* payload" (409
`idempotency_key_reused_different_payload` — a client bug, most often a
UUID generator that isn't actually random, or a genuinely different
upload mistakenly reusing a stale key). `store_response` now accepts an
optional `payload_fingerprint`; `check_idempotency` (new) compares it on
lookup and raises `IdempotencyPayloadMismatchError` on a mismatch,
instead of silently replaying the wrong file's result or silently
proceeding to create a second resource. Callers that never pass a
fingerprint (S1G's own two call sites, `get_cached_response` unchanged)
keep their exact prior behavior — this is a strictly additive extension
of the *shared* mechanism, not a second implementation.
"""

import hashlib
import json
import logging
from datetime import timedelta
from typing import NamedTuple

from fastapi import status
from redis.asyncio import Redis

from app.core.exceptions import AppException

logger = logging.getLogger(__name__)


class IdempotencyPayloadMismatchError(AppException):
    """Raised when an `Idempotency-Key` is reused with a payload whose
    fingerprint doesn't match the one stored for that key's first use.

    Deliberately lives here, not in any document-specific module — this
    is a property of the shared idempotency mechanism itself, reusable
    by any future idempotency-required endpoint, exactly the same
    reasoning that keeps this whole module generic.
    """

    status_code = status.HTTP_409_CONFLICT
    error_code = "idempotency_key_reused_different_payload"

    def __init__(self) -> None:
        super().__init__("This Idempotency-Key was already used with a different request body.")


def fingerprint_bytes(data: bytes) -> str:
    """SHA-256 hex digest of raw bytes — used as a payload fingerprint
    for multipart/file-bearing idempotent requests. Not a security
    checksum in its own right (see `app.modules.documents.checksum` for
    that); this is purely "did the client send the same bytes as last
    time," reusing the same hash the content-checksum computation
    already produces for a file upload, so the fingerprint costs nothing
    extra to compute at the one call site that has both.
    """
    return hashlib.sha256(data).hexdigest()


def fingerprint_text(*parts: str) -> str:
    """SHA-256 hex digest of one or more string parts, joined by a
    separator byte that can't appear in a UUID/simple identifier — used
    as a payload fingerprint for idempotent requests with no file body
    (e.g. version restore, fingerprinted by its path parameters)."""
    joined = "\x1f".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()

_KEY_PREFIX = "idempotency:"

# IMPLEMENTATION CHOICE — no frozen TTL exists for how long a replayed
# response should remain available; 24 hours is a generous "the client's
# own retry window has surely elapsed by then" default, named here
# rather than hardcoded at each call site.
DEFAULT_TTL = timedelta(hours=24)


def _redis_key(*, scope: str, actor: str, idempotency_key: str) -> str:
    return f"{_KEY_PREFIX}{scope}:{actor}:{idempotency_key}"


async def get_cached_response(
    redis: Redis, *, scope: str, actor: str, idempotency_key: str
) -> tuple[int, dict] | None:
    """Return the `(status_code, body)` of a previous identical request,
    or `None` if this `(scope, actor, idempotency_key)` combination
    hasn't completed before (or its entry has since expired).

    `scope` names the endpoint/operation (e.g. `"workspace_invitation_create"`)
    and `actor` scopes the key to whoever is calling — two different
    callers who coincidentally send the same literal `Idempotency-Key`
    string must never collide. Unchanged since S1G — never checks a
    payload fingerprint; see `check_idempotency` for the S2A extension
    that does.
    """
    raw = await redis.get(_redis_key(scope=scope, actor=actor, idempotency_key=idempotency_key))
    if raw is None:
        return None
    payload = json.loads(raw)
    return payload["status_code"], payload["body"]


class IdempotencyReplay(NamedTuple):
    status_code: int
    body: dict


async def check_idempotency(
    redis: Redis, *, scope: str, actor: str, idempotency_key: str, payload_fingerprint: str
) -> IdempotencyReplay | None:
    """S2A extension of `get_cached_response`: also validates that a
    reused key carries the *same* payload fingerprint as its first use.

    Returns `None` if this key hasn't been seen before (caller should
    proceed with the operation). Returns the cached response if the key
    *and* fingerprint both match (replay). Raises
    `IdempotencyPayloadMismatchError` if the key matches but the
    fingerprint doesn't (409 `idempotency_key_reused_different_payload`).
    """
    raw = await redis.get(_redis_key(scope=scope, actor=actor, idempotency_key=idempotency_key))
    if raw is None:
        return None
    payload = json.loads(raw)
    if payload.get("payload_fingerprint") != payload_fingerprint:
        raise IdempotencyPayloadMismatchError()
    return IdempotencyReplay(payload["status_code"], payload["body"])


async def store_response(
    redis: Redis,
    *,
    scope: str,
    actor: str,
    idempotency_key: str,
    status_code: int,
    body: dict,
    payload_fingerprint: str | None = None,
    ttl: timedelta = DEFAULT_TTL,
) -> None:
    """Persist a finished response so a retried request bearing the same
    key replays it instead of repeating the underlying operation.

    Called only *after* the operation's own durable write (e.g. the
    Postgres commit) has already succeeded — this cache is a replay
    convenience, never the record of whether something happened.
    `payload_fingerprint` is optional (`None` — S1G's own two call sites
    never set it) and, when provided, is what `check_idempotency`
    compares against on a later reuse of the same key.
    """
    payload = json.dumps(
        {"status_code": status_code, "body": body, "payload_fingerprint": payload_fingerprint}
    )
    await redis.set(
        _redis_key(scope=scope, actor=actor, idempotency_key=idempotency_key),
        payload,
        ex=ttl,
    )

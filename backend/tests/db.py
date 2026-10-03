"""Shared test database helpers.

Provides `run_db_test` (service/model-level) and `run_http_test`
(endpoint-level), used across every module's tests to run against a
real, transactionally-isolated database session — without needing
`pytest-asyncio` (not a project dependency). Each call does its own full
setup/teardown within a single `asyncio.run()`, since an
`AsyncSession`/asyncpg connection created in one event loop cannot be
reused in another.

Requires a real, reachable PostgreSQL matching the backend's `.env`
configuration (`app.config.settings`) — these are integration tests, per
the Technical Design Document's Testing Strategy (Section 24): "the
ingestion pipeline exercised end-to-end against real Postgres... not
mocks." The same principle applies here to the schema itself.

Each test's data changes are rolled back at the end. Table creation is
idempotent (`checkfirst=True` is the default for `create_all`) and left
in place, so repeated test runs never leave garbage behind and never
depend on run order.

The shared `engine` from app.db.session is a module-level singleton —
by design, so the whole app shares one pool at runtime. Tests reuse that
same engine (deliberately: it's the real connection configuration, not
a separate test-only one) but each test runs in its own fresh
`asyncio.run()` event loop, and a pooled asyncpg connection cannot
outlive the event loop it was created in. `engine.dispose()` at the end
of every call empties the pool so the *next* test's event loop always
starts with fresh connections, rather than reusing one bound to a
now-closed loop.

**`join_transaction_mode="create_savepoint"` (added Sprint 1B):** as of
Sprint 1B, service-layer code under test (e.g. `register_user`) owns its
own transaction boundary and calls `session.commit()` for real (per the
Technical Design Document, Section 18). Without this option, that
`commit()` would commit the *outer* connection-level transaction
`run_db_test` uses for isolation, permanently persisting test data. With
it, the session's `commit()`/`rollback()` calls only affect a SAVEPOINT
nested inside the outer transaction — the code under test observes
normal commit/rollback semantics, while the outer transaction (and
therefore everything it did) is still fully undone by this helper's
final rollback. This is SQLAlchemy's own documented pattern for
"joining a session to an external transaction, such as for test suites."

**`run_http_test` does NOT use that same shared-connection pattern**,
deliberately: FastAPI's `TestClient` manages its own internal event loop
to actually execute the async application, separate from whatever loop
called it — a connection/session created in `run_db_test`'s outer
`asyncio.run()` loop is unusable once control passes into `TestClient`
(confirmed empirically: it raises "attached to a different loop").
`run_http_test` instead lets the request hit the real `get_db`/`engine`
exactly as production would, and cleans up afterward by deleting rows
created under a distinctive test-only email pattern — see its own
docstring below.

**Redis (added S1D):** `app.db.redis.redis_client` is exactly the same
kind of module-level singleton as `engine`, and hits the exact same
cross-event-loop hazard confirmed empirically while building S1D
(`RuntimeError: ... got Future attached to a different loop`) —
`login_user`/`refresh_session`/etc. now touch Redis inside these same
per-test event loops. `redis_client.aclose()` (confirmed empirically to
let the shared client be reused safely across subsequent, separate
`asyncio.run()` calls — the connection pool reconnects lazily) is
called at exactly the same points `engine.dispose()` already is, for
the same reason.
"""

import asyncio
from collections.abc import Awaitable, Callable

# Ensures every ORM model is registered on Base.metadata before
# create_all() runs — see app/db/model_registry.py.
import app.db.model_registry  # noqa: F401
import asyncpg
from app.core.application import create_application
from app.db.base import Base
from app.db.redis import redis_client
from app.db.session import build_database_url, engine
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

TestBody = Callable[[AsyncSession], Awaitable[None]]
HttpTestBody = Callable[[TestClient], None]

# Every email used by an HTTP-level test must match this pattern — see
# run_http_test's docstring for why, and each test file's payload
# helper for where it's applied.
HTTP_TEST_EMAIL_DOMAIN = "s1b-http-test.example.com"


async def _safe_redis_aclose() -> None:
    """Best-effort `redis_client.aclose()` — swallows the failure mode
    confirmed empirically when this is called from a *different* loop
    than the one that actually used the client: `aclose()` tries a
    graceful round trip (a QUIT-style handshake) over the pooled
    connection's socket, which raises `RuntimeError: Event loop is
    closed` if that socket belongs to a loop that's already gone (e.g.
    `TestClient`'s, after its `with` block has exited). This is purely
    disposal, not a business operation (contrast every real
    `refresh_store` call, which never swallows an error this way): the
    goal is just "don't hand the next loop a stale connection", and a
    connection that fails to close gracefully is, for that purpose,
    already exactly as good as one that closed cleanly — either way the
    pool creates a fresh one on next use.
    """
    try:
        await redis_client.aclose()
    except Exception:  # noqa: S110, BLE001 — deliberately broad and silent, see docstring
        pass


async def _dispose_stale_pool() -> None:
    """Discard any pooled connections left over from a *different*
    event loop before this loop touches the shared `engine`/`redis_client`
    at all.

    `pool_pre_ping=True` (app/db/session.py) pings a pooled connection
    before handing it out — and that ping itself raises immediately if
    the connection belongs to a dead loop, before `dispose()` would ever
    normally get a chance to clear it. So dispose is called defensively,
    first, rather than only at the end of a call as `run_db_test` does —
    `run_http_test` can't rely on the same "only I ever touch this pool"
    assumption, since `TestClient` also touches it, in a loop of its own
    that this module has no hook into disposing at the right moment.
    """
    await engine.dispose()
    await _safe_redis_aclose()


async def _ensure_schema() -> None:
    await _dispose_stale_pool()
    try:
        async with engine.begin() as setup_conn:
            await setup_conn.run_sync(Base.metadata.create_all)
    finally:
        # Disposing only *before* use isn't enough on its own: the
        # connection this call itself creates would otherwise be the
        # thing left dangling for the *next* loop (TestClient's) to trip
        # over — exactly the bug this line fixes. Every standalone
        # asyncio.run() boundary that touches `engine` must leave the
        # pool empty when it returns, not just find it empty on entry.
        await engine.dispose()


def run_db_test(test_body: TestBody) -> None:
    """Run one async test body against a real, rolled-back-after session.

    `test_body` may also freely use `app.db.redis.redis_client` directly
    (it's already loop-safe within this call — see module docstring);
    there is no Redis equivalent of the Postgres rollback-on-exit here,
    so a test that writes to Redis is responsible for its own cleanup
    (`app.modules.auth.refresh_store.invalidate`, or simply relying on
    the TTL every refresh-token record already carries).
    """

    async def _run() -> None:
        await _ensure_schema()

        try:
            async with engine.connect() as conn:
                trans = await conn.begin()
                session = AsyncSession(
                    bind=conn,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                )
                try:
                    await test_body(session)
                finally:
                    await session.close()
                    if trans.is_active:
                        await trans.rollback()
        finally:
            # See module docstring: without this, the next test's fresh
            # event loop would try to reuse a connection bound to this
            # (about to be closed) one.
            await engine.dispose()
            await _safe_redis_aclose()

    asyncio.run(_run())


def run_http_test(test_body: HttpTestBody) -> None:
    """Run one synchronous test body against a real app + TestClient.

    `test_body` receives a plain `TestClient` and makes requests against
    it synchronously — `TestClient` manages the async application (and
    its own event loop) internally, so the test body itself needs no
    `await`, and this helper does not wrap the `TestClient` call in its
    own `asyncio.run()` either (see module docstring for why that
    combination doesn't work).

    Requests hit the real `get_db`/`engine` exactly as production would
    — there is no per-test transaction rollback here. Instead, every
    email a test creates **must** end in `@{HTTP_TEST_EMAIL_DOMAIN}`;
    this helper deletes every row matching that pattern after the test
    runs, regardless of whether it passed or failed.
    """
    asyncio.run(_ensure_schema())

    app = create_application()
    try:
        with TestClient(app) as client:
            test_body(client)
    finally:
        asyncio.run(_cleanup_http_test_users())


async def _cleanup_http_test_users() -> None:
    """Delete every row an HTTP-level test created (matched by email
    pattern), via a throwaway `asyncpg` connection of its own —
    deliberately NOT the shared `engine`.

    This used the shared engine (dispose-before/after, like everywhere
    else in this module) until S1D, when it started intermittently
    raising `RuntimeError: Event loop is closed` while closing a stale
    pooled connection — confirmed empirically to be a GC-timing race
    between this call's fresh loop and finalization of a connection
    object from `TestClient`'s just-closed loop, made newly likely to
    surface once S1D's extra per-request queries (Session upsert, and
    Redis) changed the shared pool's checkout pattern during the
    request the finalizer belongs to. A connection this function never
    shares with anything else can't race with anything else's cleanup.
    """
    dsn = build_database_url().replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        # S1G: `invitations.invited_by_user_id` and `audit_logs.actor_user_id`
        # are both ON DELETE RESTRICT (an invitation/audit entry's actor
        # is never optional — see app/modules/workspaces/models.py) —
        # deleting an HTTP-test user who sent an invitation or triggered
        # an audit event would otherwise fail the DELETE below outright.
        # Both child tables are cleared first, scoped to exactly the same
        # email-pattern-matched user set this function already targets;
        # Membership/Session rows need no equivalent handling (CASCADE).
        await conn.execute(
            "DELETE FROM invitations WHERE invited_by_user_id IN "
            "(SELECT id FROM users WHERE email LIKE $1)",
            f"%@{HTTP_TEST_EMAIL_DOMAIN}",
        )
        await conn.execute(
            "DELETE FROM audit_logs WHERE actor_user_id IN "
            "(SELECT id FROM users WHERE email LIKE $1)",
            f"%@{HTTP_TEST_EMAIL_DOMAIN}",
        )
        await conn.execute("DELETE FROM users WHERE email LIKE $1", f"%@{HTTP_TEST_EMAIL_DOMAIN}")
    finally:
        await conn.close()
        await _safe_redis_aclose()

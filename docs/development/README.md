# Development

**Purpose:** Practical, operational guidance for working in this
repository day to day — local environment setup, running the app,
coding standards, and contribution notes.

**Expected files:** `SETUP.md`, `CODING_STANDARDS.md` (not yet added),
expanded alongside `scripts/setup.sh` and the local Docker services as
those become functional.

**Relationship to other documentation:** Distinct from the specification
folders (`docs/product/` through `docs/api/`), which describe *what* to
build and *why*. This folder explains *how* to actually run and
contribute to the project — it should never redefine a decision made in
those other folders, only describe the mechanics of working within them.

---

## Configuration (Milestone M0.2B)

### Why centralized configuration

Every setting the backend needs — database host, secret key, AI model
names, and so on — is defined in exactly one place:
`backend/app/config/settings.py`. No module reads `os.environ` (or
anything equivalent) directly. This matters for a few concrete reasons:

- **Fail fast, not mysteriously.** `Settings` is a `pydantic-settings`
  model, so a missing required value or an invalid one (a bad port
  number, an unrecognized `APP_ENV`) raises a clear validation error the
  moment the app starts — never a confusing failure three requests
  later, deep inside some unrelated module.
- **One typed source of truth.** Every field has a real Python type
  (`int`, `bool`, a `Literal` enum, …), so a module using
  `settings.database.PORT` gets an actual `int` it can trust, not a raw
  string it has to parse and hope is correct.
- **Nothing here connects to anything yet.** This milestone only
  *describes* configuration — it does not open a database connection,
  construct a Redis client, or call any external service. That begins
  in later milestones, once there's a module that actually needs the
  connection.

### Why environment variables

Environment variables are the standard mechanism for anything that
differs between local development, staging, and production — and,
critically, for anything secret. A `.env` file is never committed (see
the root `.gitignore`); only `backend/.env.example` — a template with
every variable name and a safe placeholder or sensible default — is
checked in.

### Creating your local `.env`

```bash
cd backend
cp .env.example .env
```

Then fill in every value marked `required — no default` in the file
(`SECRET_KEY`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `MINIO_ROOT_USER`,
`MINIO_ROOT_PASSWORD`). Everything else already defaults to values that
match the local services defined in the root `docker-compose.yml`.

### How future modules access configuration

Always the same way, from anywhere in the backend:

```python
from app.config import settings

settings.APP_NAME
settings.database.HOST
settings.redis.PORT
```

Never `Settings()` directly (that constructs a new, separate instance),
and never a raw environment variable lookup — `settings` is the single,
already-validated instance every module shares.

---

## Application Foundation (Milestone M0.2D)

### Application lifecycle

`backend/app/main.py` imports `create_application()` from
`app/core/application.py` — the one place a `FastAPI` instance is built.
Metadata (title, docs URLs) comes from `Settings`; middleware, exception
handlers, and routers are wired in one clearly-ordered place so `main.py`
stays a single import.

Startup/shutdown is handled by `app/core/lifespan.py`. For this
milestone it does exactly two things: configure logging, and log a
startup/shutdown line. **No connection to Postgres, Redis, Qdrant,
MinIO, or mail is opened at startup** — that's deliberate; a startup
check belongs to the module that actually owns that connection, once it
exists, not to the application shell.

### Middleware

Registered in `app/core/middleware.py`, in this order (Starlette applies
the *last*-added middleware as the *outermost* layer):

1. **Request ID** — every request gets an ID: the incoming
   `X-Request-ID` header if the client sent one, otherwise a generated
   UUID4. Attached to `request.state.request_id` and echoed back as a
   response header. Also set on a context variable so every log line
   emitted while handling that request is automatically tagged with it.
2. **Request timing** — measures duration and returns it as
   `X-Process-Time-Ms`. Purely observational.
3. **CORS** — added last (outermost), so it wraps every response
   including errors. Allowed origins are currently hardcoded per
   environment (`http://localhost:3000` for `local`/`development`, none
   for `staging`/`production`) since `Settings` has no dedicated
   `CORS_ORIGINS` field yet — a natural addition once real
   staging/production origins are known.

### Logging

`app/core/logging.py` configures the standard library's `logging` module
only — no third-party logging library. One JSON formatter, one line per
log record, `INFO` by default and `DEBUG` when `APP_DEBUG=true`. Every
line includes a `request_id` field, `null` outside of a request (e.g.
startup/shutdown) and the actual ID whenever one exists — enabling
`grep`/log-search correlation of every line touched by a single request
without passing the ID through every function call by hand.

### Health endpoint

```
GET /api/v1/health
```

Returns a flat body — `status`, `application`, `version`, `environment`,
`timestamp` — deliberately **not** wrapped in the standard
`{"data": ...}` envelope, since health endpoints conventionally return a
predictable, unwrapped shape for load balancers and uptime monitors.
Checks only that the application process itself is up and configured —
it does **not** check Postgres, Redis, Qdrant, or MinIO connectivity.
(For a manual database connectivity check, see
`backend/scripts/verify_db_connection.py` from M0.2C.)

### API routing

```
app/api/router.py          "/api"        — aggregates versioned routers
  app/api/v1/router.py       "/v1"       — aggregates v1 endpoint modules
    app/api/v1/endpoints/health.py         — GET /health
```

A future resource (e.g. `documents`) is added as its own
`app/api/v1/endpoints/documents.py`, included in `app/api/v1/router.py`
exactly like `health` — never by editing an existing endpoint module. A
future `v2` is added as a sibling `app/api/v2/` package, included
alongside (not instead of) `v1` in `app/api/router.py`, per the REST API
Contract's Versioning Strategy (Section 29).

### Error responses

Every error — a 404 for an unmatched route, a validation failure, or a
genuinely unexpected exception — returns the same envelope shape defined
in the REST API Contract (Section 5):

```json
{
  "error": {
    "code": "not_found",
    "message": "...",
    "request_id": "...",
    "details": [...]
  }
}
```

Handlers are registered in `app/core/exceptions.py` against Starlette's
base `HTTPException` (not FastAPI's subclass) specifically so routing-
level failures — like an unmatched path — are caught too, not just
exceptions raised from inside a route body. Unhandled exceptions are
logged with full detail server-side and never expose their message or
stack trace to the client, in any environment.

---

## Registration (Sprint 1B)

### Flow

```
POST /api/v1/auth/register
  → RegisterRequest (Pydantic) validates + normalizes email/password/display_name
  → register_user() (app/modules/auth/service.py)
      → hash_password() (Argon2, app/core/security.py)
      → INSERT, then commit — owns its own transaction boundary
      → IntegrityError on the email constraint → EmailAlreadyRegisteredError
  → UserPublic, wrapped in the standard success envelope
```

Registration does **not** log the user in — no token, no session, is
issued. It creates exactly one row, in `pending_verification` status,
and returns it.

### Validation

Centralized in `app/core/validation.py` (per the Data Dictionary's
Shared Validation Standards) rather than inline in the schema:
`normalize_email` (trim, lowercase, ≤255 chars — format itself is
checked first by Pydantic's `EmailStr`), `validate_password` (8–128
chars, no composition rules — NIST 800-63B), `normalize_display_name`
(trim, collapse whitespace, ≤100 chars, no control characters). Any
future field needing the same rules imports these same functions.

### Password hashing

Argon2 via `argon2-cffi` (`app/core/security.py`), using the library's
own default parameters — no hand-tuned cryptography. Only `hash_password`
exists so far; `verify_password` is added with the login flow. The raw
password and the resulting hash are never logged, and `password_hash`
never appears in any schema that can be returned from an endpoint
(`UserPublic` deliberately omits it).

### Duplicate email

Registration does **not** pre-check for an existing email with a
`SELECT` before inserting — that check would be race-prone and only
ever advisory. It attempts the insert, and PostgreSQL's own
`uq_users_email_lower` constraint (Sprint 1A) is authoritative; a
violation is caught, mapped to `EmailAlreadyRegisteredError`, and
translated to the frozen contract's `409 email_already_registered`
response — never a raw database error.

### Transactions

`register_user` owns its transaction boundary — it commits on success
and rolls back on a constraint violation — per the Technical Design
Document's Transaction Management strategy (Section 18).
`app/db/dependencies.py`'s `get_db` never commits; it only yields a
session and closes it when the request ends.

### Domain exceptions

Sprint 1B introduces `AppException` (`app/core/exceptions.py`), the base
class every module's own exceptions inherit from — `EmailAlreadyRegisteredError`
(`app/modules/auth/exceptions.py`) is the first concrete one. Each
subclass declares its own HTTP status and error code; the global handler
translates any of them into the standard envelope automatically.

### Success envelope

Also new in Sprint 1B: `app/core/responses.py`'s `SuccessEnvelope`,
implementing the REST API Contract's `{"data": ..., "meta": {"request_id": ...}}`
shape (Section 4) — `GET /api/v1/health` remains the one documented flat-body
exception to it; registration is the first endpoint to use the real envelope.

### Known deviation: idempotency

The frozen REST API Contract marks `POST /auth/register` as requiring an
`Idempotency-Key` header. Enforcing it needs the Redis-backed key store
described in the Technical Design Document (Section 30) — explicitly
out of scope for this sprint ("No Redis"). The header is currently
accepted but not checked; a retried request with the same key does
**not** yet replay the original response. This is deferred to the
sprint that introduces Redis, not silently dropped — see
`app/api/v1/endpoints/auth.py`'s module docstring.

### Testing note: `run_http_test`

`backend/tests/db.py` gained a second helper this sprint,
`run_http_test`, for true HTTP-level tests via `TestClient`. It
deliberately does **not** use the same transaction-rollback isolation as
`run_db_test` — `TestClient` manages its own internal event loop to run
the async application, and a connection/session created in a different
loop cannot be reused inside it (confirmed empirically while building
this sprint's tests). Instead, `run_http_test` hits the real
`get_db`/`engine` exactly as production would, and cleans up afterward
by deleting rows whose email matches a distinctive test-only domain
(`HTTP_TEST_EMAIL_DOMAIN`). Any future HTTP-level test must use that
domain for the same reason.

---

## Login (Sprint S1C.2)

### Flow

```
POST /api/v1/auth/login
  → LoginRequest (Pydantic) normalizes email only — password passed through unmodified
  → login_user() (app/modules/auth/service.py)
      → look up User by lower(email) — the only index on that column
      → verify_password() (Argon2, app/core/security.py)
      → status must be `active` (`pending_verification` / `deactivated` rejected)
      → create_access_token() + create_refresh_token() + hash_refresh_token()
      → INSERT Session, UPDATE User (failed_login_count=0, last_login_at) — one commit
      → (S1D) store the refresh token's hash in Redis too — see below
  → UserPublic, wrapped in the standard success envelope; tokens go only in cookies
```

Nonexistent email and wrong password both raise the same
`InvalidCredentialsError` (401 `invalid_credentials`) — the frozen
contract requires these to be indistinguishable. A `deactivated`
account also currently maps to this same error: **the frozen contract
excerpt this was built from defines no dedicated code for that case**,
and reusing the existing generic one was a deliberate choice, not a
confirmed spec — flagged here and in the Sprint S1C.2 report.

### Cookies

`nexus_access_token` / `nexus_refresh_token`, both `httpOnly`,
`SameSite=lax`, `Secure` only outside `local`/`development` (a literal
`Secure` cookie is silently dropped by the browser over plain HTTP,
which local dev uses). Names and the SameSite choice aren't specified
verbatim in the frozen contract excerpt either — a flagged, minimal,
easily-revised choice (`app/modules/auth/cookies.py`).

---

## Refresh Tokens, Rotation, Logout, and Session Management (Sprint S1D)

### Redis — now required

`app/db/redis.py` builds one `redis.asyncio.Redis` client from
`settings.redis` (host/port only — no password/TLS field exists on
`RedisSettings` yet, matching the unauthenticated local Redis in
`docker-compose.yml`), mirroring `app/db/session.py`'s engine-
construction pattern exactly. `get_redis()` is the FastAPI dependency;
unlike `get_db` it hands back the *same* shared client every time —
Redis's async client manages its own connection pool and is meant to be
reused, unlike a per-request `AsyncSession`.

Every Redis command lives behind `app/modules/auth/refresh_store.py` —
no route, and no other service function, issues one directly. Key
scheme: `refresh_token:{sha256_hex_hash}` → the owning `Session.id`
(string), TTL matching `refresh_token_expires_at()`.

### Refresh flow

```
POST /api/v1/auth/refresh
  → extract raw refresh token from the nexus_refresh_token cookie
  → hash it; look it up in Redis (fast path — TTL'd, existence = validity)
  → cross-check the Session row by that same hash (Postgres — authoritative
    for the token_expired vs token_invalid distinction Redis alone can't make)
  → issue a new access token + a new opaque refresh token
  → UPDATE the *same* Session row in place (refresh_token_hash, expires_at)
      — refresh extends an existing session, only login_user creates new rows
  → commit Postgres first; only then rotate Redis (delete old key, set new
    key, one pipelined round trip) — a Redis failure here is never swallowed,
    so a client never receives tokens whose server state only half-persisted
  → set new cookies, return 200 with `data: null`
```

A token that was already rotated away simply no longer matches any
`Session.refresh_token_hash` (rotation updates that column), so
presenting it again naturally raises `token_invalid` the same way a
garbage token would — **this is the only behavior implemented for
"reuse of an already-rotated refresh token"**. The frozen documents this
was built from don't specify any additional response (e.g. revoking
every session for that user, alerting); none is invented.

`data: null` in the response body is also a flagged choice — the frozen
contract doesn't specify `/refresh`'s response shape beyond "no tokens
in the body," so nothing is invented there either.

### Logout

`POST /api/v1/auth/logout` requires a valid access token (`Auth: Yes`,
via `get_current_user_id` — see below) *and* reads the refresh-token
cookie to identify which specific session is "current" (an access token
alone doesn't carry a session identifier by design — S1C.1 kept its
claims deliberately minimal). Deletes the Redis record, marks the
Session `revoked`/`revoked_at`, clears both cookies, returns 204. Per
the frozen Technical Design Document: the access JWT itself is **never**
server-side revoked — no blacklist exists; the ~15-minute access-token
lifetime is the accepted blast radius. A missing/foreign/already-revoked
cookie is a silent no-op success, not an error.

### Session management

`GET /sessions` — the caller's own `active` sessions only, most recent
first, exposing exactly `id`, `device_label`, `ip_address`,
`created_at`, `status` (never `refresh_token_hash` — Restricted, per the
Data Dictionary). `id` isn't explicitly named in the contract excerpt
this was built from, but is included anyway: `DELETE
/sessions/{session_id}` (also frozen, also S1D) is unusable unless the
client can learn a session's ID somewhere.

`DELETE /sessions/{session_id}` — revokes one session if (and only if)
it belongs to the caller. A session that doesn't exist and one that
belongs to someone else both return the same 404 `not_found` — the
frozen contract says to follow "existing authorization/not-found
behavior" without saying which of the two; 404 for both is the common
security convention of not confirming a resource's existence to a
non-owner, and reuses an already-existing generic code rather than
inventing `forbidden`-vs-`not_found` disambiguation.

`DELETE /sessions` — revokes every other active session, identifying
"current" the same way logout does (refresh-token cookie → hash →
Session row). If no current session can be identified, every active
session is revoked (there's nothing to exclude).

### Current-session identification

The refresh-token cookie's hash is the one identifier used everywhere a
"current session" needs identifying (logout, revoke-all-others) — the
same value that already ties the cookie, the Redis record, and the
Session row together for `/refresh`. No second, unrelated mechanism
(e.g. a session-ID claim on the access JWT) was introduced.

### The access-token auth dependency

`app/modules/auth/dependencies.py`'s `get_current_user_id` — reads
`nexus_access_token`, calls `decode_access_token()`, returns the
`sub` claim as a UUID. Not `/auth/me` (still out of scope): this is the
underlying gate `Auth: Yes` endpoints need, pulled out because it's
required infrastructure regardless of whether a dedicated "who am I"
endpoint exists yet. Missing/malformed/expired/wrong-type access tokens
all raise `AuthenticationRequiredError` (401 `unauthorized`) — the
frozen contract's `token_expired`/`token_invalid` codes are scoped
explicitly to `/refresh`'s *refresh* token in the same document, not a
general "any bad token" code; `unauthorized` reuses an already-existing
generic `_STATUS_CODES` entry rather than inventing a new one.

### Testing note: Redis needs the same cross-loop treatment as Postgres

`app/db/redis.py`'s `redis_client` is a module-level singleton exactly
like `engine`, and hit the identical cross-event-loop hazard
`run_db_test`/`run_http_test` already existed to solve for Postgres
once S1D's service functions started touching it inside those same
per-test loops (confirmed empirically: `RuntimeError: ... attached to a
different loop`). `tests/db.py` now disposes `redis_client` at exactly
the same points it already disposed `engine`, via a `_safe_redis_aclose()`
helper — "safe" because `aclose()` called from a loop other than the one
that actually used the client raises trying to gracefully close a
socket whose loop is already gone; that's fine for pure disposal (the
pool reconnects fresh on next use regardless), so the failure is
swallowed there specifically, never in a real `refresh_store` call.

Two more, closely related fixes landed alongside this: `test_login_api.py`'s
`_activate_user` helper and `tests/db.py`'s `_cleanup_http_test_users`
both switched from the shared `engine` to a throwaway `asyncpg`
connection of their own, for operations that run *while* `TestClient`'s
own loop may still hold pooled connections on that same shared engine —
disposing the shared pool from a different loop at that specific moment
intermittently corrupted TestClient's in-flight connection. A connection
these functions never share with anything else can't race with anything
else's cleanup.

---

## Email Verification and Password Recovery (Sprint S1E)

Four endpoints: `POST /verify-email`, `POST /resend-verification`,
`POST /forgot-password`, `POST /reset-password`. As with every prior
sprint's notes here, each item below is labeled so a reader never has
to guess which category it falls into.

### Token lifecycle — IMPLEMENTATION CHOICE

**FROZEN REQUIREMENT:** verification and reset tokens are single-use
and time-boxed; `verify-email`/`reset-password`'s `token` (and
`reset-password`'s `new_password`) field names are frozen exactly.

**UNRESOLVED CONTRACT GAP:** no frozen Technical Design Document value
exists for either token's TTL (`docs/architecture/README.md` marks that
document "not yet added"). `Settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS`
(default 24) and `Settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES` (default
60) are implementation defaults, named and centralized exactly as S1E's
own instructions ask for this situation, not magic numbers in service
code.

**IMPLEMENTATION CHOICE:** storage is Redis
(`app.modules.auth.token_store`), reusing the architecture S1D already
established for refresh tokens, rather than a new SQL table — no frozen
Database Design exists to specify one (`docs/database/README.md` marks
`DATABASE_DESIGN.md` "not yet added" too). One deliberate difference
from `refresh_store`: a refresh token's expiry could be checked against
an independent Postgres `Session.expires_at`; these tokens have no such
row, so the real expiry decision is made against an `expires_at` stored
*inside* the Redis hash itself (Redis's own TTL is just cleanup, set
with a grace period past that) — otherwise `token_expired` and
`token_invalid` would be indistinguishable once a key is gone, and the
frozen error catalog requires them distinguishable. Both token kinds
reuse `app.core.security`'s existing `create_refresh_token`/
`hash_refresh_token` primitives rather than duplicating that
cryptography under new names.

**IMPLEMENTATION CHOICE:** issuing a new token for a user invalidates
whatever previous token (of the same kind) they held, via a small
reverse index (`email_verification_by_user:{user_id}` /
`password_reset_by_user:{user_id}` → current token hash).

### Verification flow

```
POST /api/v1/auth/verify-email
  → token_store.consume_verification_token() — single-use lookup (Redis),
    raises token_expired / token_invalid as appropriate
  → User.status: pending_verification → active
  → User.email_verified_at = now() (UTC)
  → 200, data: null
```

**UNRESOLVED CONTRACT GAP:** the frozen contract doesn't specify a
response body shape for `verify-email` — `data: null` is the smallest
consistent envelope, matching the same choice already made for S1D's
`/refresh`.

Registration (S1B) still does not send a verification email itself —
that was already frozen S1B behavior ("does not send a verification
email"), not something S1E changed. `resend-verification` is therefore
the only way a user receives their *first* verification email in this
implementation, not merely a resend — worth knowing, not a gap, since
it follows directly from what S1B already froze.

### Resend verification — anti-enumeration

**UNRESOLVED CONTRACT GAP:** the frozen documents available for this
were silent on anti-enumeration for this specific endpoint (only
`forgot-password`'s was explicit). `resend_email_verification` applies
the identical policy anyway: always 202, identical response, regardless
of whether the account exists, is `pending_verification`, is already
`active`, or is `deactivated` — flagged as an inference (same attack
surface as the sibling endpoint the frozen contract *was* explicit
about), not a confirmed quote.

### Password recovery flow

```
POST /api/v1/auth/forgot-password
  → always 202, identical response, whether or not `email` exists
    (FROZEN — explicit anti-enumeration requirement)
  → if it does (and the account isn't `deactivated`): issue a reset
    token, email it

POST /api/v1/auth/reset-password
  → password strength checked FIRST (see below), then the token
  → token_store.consume_reset_token() — single-use, token_expired /
    token_invalid as appropriate
  → password hashed (Argon2, existing primitive) and stored
  → EVERY active Session for this user revoked — Postgres commit first
    (password change + all revocations, one atomic unit), Redis
    cleanup after (same ordering S1D's revoke_session/
    revoke_other_sessions already established)
  → no access-token blacklist (FROZEN — same ~15-minute accepted blast
    radius as logout)
  → 200, data: null
```

**IMPLEMENTATION CHOICE:** `new_password` strength is validated
*before* the reset token is looked up — a `password_too_weak` response
must never consume a token the user could still use once they resubmit
a valid password. `ResetPasswordRequest.new_password` deliberately
carries no Pydantic-level validator (unlike registration's), since
`password_too_weak` is a distinct error code from the generic
Pydantic-driven `validation_error` register uses for the same
underlying length rule (`app.core.validation.validate_password`,
reused as-is — 8–128 chars, no composition rules).

**UNRESOLVED CONTRACT GAP:** `deactivated` accounts get no
special-cased response anywhere reached through these public endpoints
(same treatment as login's own flagged `deactivated` gap) — a password
reset request for one is a silent no-op, and a reset token that somehow
named one is rejected as `token_invalid`.

### Email delivery architecture

**FROZEN REQUIREMENT:** an email-delivery abstraction exists; the auth
service contains no low-level SMTP code; development routes through
Mailpit via the existing `MailSettings`.

**IMPLEMENTATION CHOICE:** `app.core.mailer` — stdlib `smtplib` only
(no new dependency), blocking SMTP I/O moved off the event loop via
`asyncio.to_thread`. `app.modules.auth.mail` builds the actual
verification/reset subject+body and calls it; the service layer never
touches SMTP. No STARTTLS, no production provider — Mailpit needs
neither, and S1E's own scope says not to introduce one without a frozen
configuration naming it.

**IMPLEMENTATION CHOICE, explicitly not a contract requirement:** email
copy (subject lines, wording) is a minimal functional template — no
frozen product/UX document specifies exact copy or branding.

**UNRESOLVED CONTRACT GAP:** no "frontend base URL" setting exists yet
(no frontend UI is in scope), so verification/reset emails contain the
raw token as a code to enter, not a clickable link. A future frontend
milestone turning this into `https://.../verify-email?token=...` needs
that setting added first.

### Email side effects vs. transaction safety — IMPLEMENTATION CHOICE

**FROZEN REQUIREMENT (the property, not the mechanism):** "the business
fact must not be lost simply because an email delivery attempt fails,"
and a database transaction must not depend on an SMTP call succeeding.

**UNRESOLVED CONTRACT GAP / DESIGN GAP:** no Outbox table or background
worker exists anywhere in this repository (`app/tasks/` is empty; no
Celery app is configured anywhere) — searched before deciding, per S1E's
own instruction to check before adding one. Building a full Outbox +
worker system from nothing is judged to be well beyond "the minimum
supporting infrastructure required for these flows." Instead: the
token is generated and durably stored in Redis *first*; the email send
is attempted *after*, wrapped so a failure is logged (never the token)
and swallowed rather than raised — the request still returns
202/200 successfully, since the durable fact (a valid token now exists)
already holds regardless of what SMTP does next. This satisfies the
stated property without the mechanism a true Outbox implies; if a real
Outbox is built in a later sprint, this is the code that should route
through it instead.

### Regression

Full existing suite re-run after S1E — S1C.2 and S1D behavior
unchanged; see the sprint report for the exact command and result

---

## Workspace, Membership, and RBAC Foundation (Sprint S1F)

Every item below is labeled **FROZEN REQUIREMENT** (quoted or directly
restated from S1F's own specification — the closest thing to a written
contract this milestone had, since `DATABASE_DESIGN.md`,
`TECHNICAL_DESIGN_DOCUMENT.md`, and `API_CONTRACT.md` are all still "not
yet added" — see docs/database/, docs/architecture/, docs/api/),
**IMPLEMENTATION CHOICE** (a reasonable, minimal, documented decision
where those documents are silent), or **UNRESOLVED CONTRACT GAP** (a
choice that's genuinely ambiguous and should be confirmed before being
treated as settled).

### The Workspace aggregate

**FROZEN REQUIREMENT:** Workspace is the tenant boundary; lifecycle
`active → archived → deleted`, archive reversible, delete a soft-delete
grace-window state; a Workspace must always have at least one
Owner-role Membership; `Workspace`/`Membership`/`WorkspaceSettings`
are created atomically together, never observably partial.

`app/modules/workspaces/service.py`'s `create_workspace`: one
`session.add_all([workspace, membership, settings])` + one
`session.commit()`. If the commit fails (including a slug collision
that survives resolution — see below), none of the three rows exist;
there is no code path that persists one or two without the third.

### Founding-membership transaction

**FROZEN REQUIREMENT:** creation is one Postgres transaction; all three
rows commit or all roll back together.

Verified directly (not just asserted) in
`test_workspace_service.py::test_create_workspace_creates_workspace_membership_and_settings_atomically`
— fetches the Workspace, its Membership, and its WorkspaceSettings
independently after `create_workspace` returns and confirms all three
exist with consistent foreign keys.

### Slug generation

**FROZEN REQUIREMENT:** slug is server-derived, never client-supplied;
lowercase letters/numbers/hyphens, no leading/trailing/consecutive
hyphens, ≤100 chars, globally unique.

**IMPLEMENTATION CHOICE:** the transliteration algorithm itself
(`app/modules/workspaces/slug.py`'s `slugify`) and the collision-
resolution strategy (`service.py`'s `_generate_unique_slug`: try the
bare candidate, then `-2`, `-3`, ... up to 50 attempts before raising
`SlugUnavailableError`) are both this implementation's own design — no
frozen slug algorithm exists to copy. `SlugUnavailableError` (409
`slug_unavailable`, in S1F's own given error catalog) should be
unreachable in normal operation, since the client never supplies a
slug to collide in the first place; it exists as a last-resort
fallback, not a code path any test exercises directly (50 real
collisions in a row is impractical to construct deliberately).

### RBAC architecture

**FROZEN REQUIREMENT:** centralized authorization; no per-route ad hoc
role checks; routes/services must be able to express "Viewer+",
"Member+", "Admin+", "Owner"; a Member from Workspace A must never
access Workspace B; a Viewer must not modify settings; an Admin cannot
archive/delete; an Owner has the highest permissions.

Two-module split:
- `app/modules/workspaces/rbac.py` — resolves "does this user have an
  active Membership in this workspace, and what Role" (cache-first,
  Postgres on miss), plus cache invalidation.
- `app/modules/workspaces/dependencies.py` — `RequireRole`, the one
  FastAPI dependency every workspace-scoped route depends on
  (`require_viewer`/`require_member`/`require_admin`/`require_owner`).
  No route function in `app/api/v1/endpoints/workspaces.py` contains a
  role check of its own.

**IMPLEMENTATION CHOICE — role hierarchy:** `VIEWER(1) < MEMBER(2) <
ADMIN(3) < OWNER(4)`, a plain rank comparison. No frozen document ranks
the four `RoleName` values numerically. Since `OWNER` is already the
top rank, "Owner" (no "+") and "Owner+" are mathematically identical,
so one comparison correctly expresses all four tiers.

### Capability evaluation

**FROZEN REQUIREMENT:** "the capability_set is the source evaluated by
the centralized RBAC dependency... inspect the frozen product/TDD
capability definitions before assigning capabilities."

**UNRESOLVED CONTRACT GAP:** no frozen capability list exists to
inspect (same missing-TDD reason as above). `Role.capability_set` is
seeded (the S1F migration) with a capability list this implementation
designed itself — `workspace:read`, `workspace:update`,
`workspace:archive`, `workspace:delete`, `workspace:settings:read`,
`workspace:settings:update`, `membership:read`, `membership:manage`,
distributed across the four roles by the obvious reading of what each
tier should be able to do. **The RBAC dependency layer this sprint
actually built evaluates *role rank*, not `capability_set` string
membership** — the column is populated and available for a future,
finer-grained capability check, but no code path reads it yet. This is
the most significant unresolved gap in this sprint: the data exists,
the enforcement mechanism it's meant to back doesn't yet.

### Tenant isolation

**FROZEN REQUIREMENT:** every workspace-scoped query must be properly
scoped; a workspace_id/membership_id/role_id supplied by the client
must never imply authorization on its own.

Enforced at exactly one point per request: `RequireRole.__call__`
resolves the caller's *own* active Membership for the path's
workspace_id via `rbac.get_active_membership` — every service function
downstream assumes this has already happened and never re-derives
authorization from a client-supplied ID itself (see `service.py`'s own
module docstring). `test_workspace_api.py::test_cross_workspace_attack_sweep`
is the literal scenario S1F's own spec describes (User A belonging to
Workspace A attempting all seven operations against Workspace B) run
as one test, plus per-endpoint variants throughout the same file.

**IMPLEMENTATION CHOICE — 404 over 403 for non-members:** a workspace
that doesn't exist and one that exists but the caller has no active
Membership in are deliberately indistinguishable (`WorkspaceNotFoundError`,
404, for both) — distinguishing them would itself leak existence to a
non-member. `InsufficientPermissionError` (403) is reserved for a
caller with a *confirmed* active Membership whose Role rank is simply
too low for the specific action. Same reasoning applied to
`MembershipNotFoundError` for a membership_id belonging to a different
workspace.

### RBAC cache

**FROZEN REQUIREMENT:** role changes require immediate invalidation of
the affected user's cached authorization state; reuse the existing
Redis client if S1D already established one (it did); cache
correctness must never override authorization correctness.

Reuses `app.db.redis.redis_client` directly — no second client.
**IMPLEMENTATION CHOICE — key format and TTL:** no frozen cache key
format or TTL exists to follow. Key: `rbac:membership:{user_id}:{workspace_id}`
→ `"{membership_id}:{role_name}"`. TTL: 5 minutes
(`rbac._CACHE_TTL_SECONDS`) — a safety net for staleness in paths that
aren't one of the explicit-invalidation events, not the actual
correctness guarantee. Only a *positive* result is ever cached ("not a
member" is never cached, so there's no negative-cache entry that would
itself need invalidating when someone is later added).

Every event that changes an authorization outcome calls
`rbac.invalidate_membership_cache` immediately after its Postgres
commit succeeds:
- a role change (one user's outcome changes)
- a membership removal (one user's outcome changes)
- **found and fixed while testing this milestone:** workspace deletion
  — changes *every* active member's outcome at once, and the first
  implementation of `soft_delete_workspace` didn't invalidate anything,
  so a just-deleted workspace remained readable to its former members
  for up to the cache TTL. Fixed by invalidating every active member's
  cache entry, not just the actor's, in the same function.

Archiving/restoring a workspace does **not** invalidate anything —
archived workspaces remain readable (only `DELETED` is excluded by
`rbac.get_active_membership`'s own Postgres query), so neither
operation actually changes any cached authorization decision.

### Owner invariant

**FROZEN REQUIREMENT:** a Workspace must always have at least one
active Owner-role Membership; cannot remove or demote the final Owner;
error code `cannot_remove_last_owner`, HTTP 409, for both role-change
and removal attempts that would violate this.

`service._count_active_owners` — both `change_member_role` and
`remove_member` check it before applying their respective change,
inside the same transaction as the change itself (so the check and the
write are never observably inconsistent with each other). Proven with
multiple owners too:
`test_workspace_service.py::test_one_owner_can_be_demoted_when_another_owner_remains`
— demoting one of two Owners succeeds; the workspace still has exactly
one Owner afterward, not zero.

### Self-action on Membership

**UNRESOLVED CONTRACT GAP, explicitly flagged per S1F's own
instruction** ("if the frozen documents do not specify self-role-change
behavior, choose the safest minimal interpretation and FLAG it"): a
caller cannot change their own role or remove themselves through the
Admin-scoped role-change/removal endpoints (`InsufficientPermissionError`,
403). Neither self-role-change nor self-removal-through-this-specific-
endpoint is addressed by any frozen document; disallowing both is the
safest minimal choice, not a confirmed spec. A dedicated "leave
workspace" self-service flow, if wanted, would be a different,
Self-permission endpoint — not built this sprint.

### Audit requirements

**FROZEN REQUIREMENT:** role changes and WorkspaceSettings
retention-policy changes are audit-required; capture actor_user_id,
workspace_id, action, target_type, target_id, metadata, created_at;
never log Restricted values.

**UNRESOLVED CONTRACT GAP — the `AuditLog` entity itself:** "inspect
the existing AuditLog entity/model and follow it" — no such model, and
no Data Dictionary entry, existed anywhere in this repository before
this sprint. `app/modules/workspaces/models.py`'s `AuditLog` class is
built directly from the field list S1F's own specification gives, not
copied from a frozen document.

Membership *removal* is **not** audit-logged — S1F's audit-requirement
list names role changes and retention changes specifically, not
removal; this is a deliberate literal-scope reading, not an oversight.
`metadata` (mapped as `metadata_` — SQLAlchemy reserves the bare name
on every declarative model) only ever holds the specific before/after
business fields each call site names explicitly (role names, a
retention-day count) — never a raw request body, never a credential.

### Endpoints implemented

`POST /workspaces`, `GET /workspaces`, `GET /workspaces/{id}`,
`PATCH /workspaces/{id}`, `POST /workspaces/{id}/archive`,
`POST /workspaces/{id}/restore`, `DELETE /workspaces/{id}`,
`GET /workspaces/{id}/settings`, `PATCH /workspaces/{id}/settings`,
`GET /workspaces/{id}/members`, `PATCH /workspaces/{id}/members/{id}`,
`DELETE /workspaces/{id}/members/{id}` — twelve, exactly S1F's list.

**IMPLEMENTATION CHOICE — response shapes:** `POST /workspaces`'s
`data` is `{"workspace": ..., "membership": ...}`; cursor pagination
(`GET /workspaces`, `GET .../members`) extends the existing
`{"data": ..., "meta": {"request_id"}}` envelope with `meta.next_cursor`
(opaque base64 of the last row's UUIDv7 id — ordering by `id` doubles
as chronological order for free); `MemberEntry.role` is a plain string,
not a nested object. None of these shapes are quoted from a frozen
contract — see `app/modules/workspaces/schemas.py`'s module docstring
for each, flagged individually.

**IMPLEMENTATION CHOICE — `SessionPublic`-style inference carried
forward:** `MembershipPublic`/`MemberEntry` include the membership's own
`id` even though S1F's field list for the members endpoint doesn't name
it explicitly — `DELETE .../members/{membership_id}` (also frozen, also
S1F) is unusable unless a client can learn a membership's ID somewhere,
the same reasoning S1D applied to `SessionPublic.id`.

**IMPLEMENTATION CHOICE — idempotency deferred, not implemented:**
`POST /workspaces` is marked `Idempotency: Yes` in S1F's contract. Same
deferral already established for `POST /auth/register` (S1B) and never
revisited since: enforcing it needs a Redis-backed idempotency-key
store, which is a different piece of infrastructure than anything S1F's
own scope list asks for building. The header is accepted (ignored).

### Deviations from frozen specifications

- **`Invitation.workspace_id`'s FK, resolved** — exactly what Sprint
  1A's own migration docstring said would happen "once `workspaces`
  exists." Required updating that sprint's own model tests (they
  inserted Invitations against a random, non-existent workspace_id,
  which the new FK now correctly rejects) — a necessary, anticipated
  consequence of resolving the deviation, not a regression of Sprint
  1A's actual behavior.
- **`Membership.user` needed `foreign_keys=` disambiguation** — two
  columns on `memberships` reference `users.id` (`user_id`,
  `invited_by_user_id`); SQLAlchemy can't infer which one a bare
  `relationship("User")` means. Found via `AmbiguousForeignKeysError`
  cascading into unrelated tests (any mapper-configuration failure
  breaks the whole shared registry, not just the model that caused it),
  fixed with an explicit `foreign_keys=[user_id]`.

### Testing infrastructure notes

- **`create_all()` doesn't alter existing tables.** The local test
  Postgres already had an `invitations` table from earlier sprints;
  adding the FK to the model didn't retroactively add it to that
  already-existing table (`Base.metadata.create_all`'s `checkfirst=True`
  skips tables that already exist). The real Alembic migration (below)
  is what actually applies it — confirmed by inspecting
  `pg_constraint` directly before and after running it.
- **Test-created workspaces accumulate slug collisions across repeated
  runs**, unlike test users (cleaned up by the existing
  `HTTP_TEST_EMAIL_DOMAIN` pattern) — nothing analogous exists for
  workspaces. A fixed test workspace name (e.g. "Acme Corp") reused
  across many manual re-runs of this sprint's test file eventually
  exhausted `_generate_unique_slug`'s 50-attempt collision-resolution
  cap for real, surfacing as a genuine `slug_unavailable` in tests that
  had nothing to do with slug collision. Fixed by giving every HTTP-
  level test workspace a unique, UUID-suffixed name by default.

### Migration

`alembic/versions/20260814_create_workspace_tables.py` — `workspaces`,
`memberships`, `workspace_settings`, `audit_logs`; the `invitations`
FK; and seeds the four system roles with fixed, stable UUIDv7 ids
(`op.bulk_insert` against an `sa.table()` reflection, not the ORM model
directly). Verified directly against a clean database: `alembic upgrade
head` (both this migration and Sprint 1A's chain together), inspected
`pg_constraint`/`roles` directly via raw SQL, `alembic downgrade -1`
(confirmed all four new tables and the FK are gone, `roles` empty
again), then `alembic upgrade head` again to leave the database ready
for the rest of the suite.

### Regression

Full existing suite (S1A through S1E) re-run after every stage of S1F
— see the sprint report for exact commands and results; run three
times consecutively with no flakiness observed.

---

## Invitations & Membership Onboarding (Sprint S1G)

Implements the six invitation endpoints S1G's own specification lists,
plus the minimum supporting infrastructure it names explicitly: token
generation/hashing, email delivery, acceptance, the shared
`Idempotency-Key` mechanism, and lifecycle/expiry handling. Uses the
`Invitation` model exactly as Sprint 1A defined it and S1F's migration
already fully migrated (`token_hash`, `status`, `expires_at`,
`resolved_at`, the workspace FK, the pending-uniqueness partial index)
— **no schema migration was needed for S1G at all**, the table shape
already supported every behavior this sprint asked for.

### The Invitation lifecycle

**FROZEN REQUIREMENT** — `pending → accepted`, `pending → revoked`,
`pending → expired`; every one of the three terminal states is final
("accepted/revoked/expired invitations cannot be accepted again").
`app/modules/workspaces/service.py`'s `_settle_or_raise` is the one
place every endpoint that touches a specific invitation (resend,
revoke, the public token lookup, accept) funnels through: a still-valid
`pending` row passes through untouched; a `pending` row whose
`expires_at` has passed is lazily flipped to `expired` (committed
immediately, its own small transaction — see "Expiration" below) and
raises `invitation_expired`; anything else (`accepted`/`revoked`)
raises `invitation_already_resolved` without touching the row —
"already-resolved invitations must not be silently mutated."

### Token architecture

**IMPLEMENTATION CHOICE, but not new cryptography.** Invitation tokens
reuse `app.core.security.create_refresh_token`/`hash_refresh_token`
outright — the same opaque-random-value-plus-SHA-256-hash primitives
S1C.1 built and S1E's `token_store.py` already reused for verification/
reset tokens — rather than a third hand-rolled implementation. The one
architectural difference from S1E's tokens: **Postgres, not Redis, is
authoritative.** `Invitation.token_hash`/`expires_at`/`status` live
directly on the row itself; there is no Redis storage for invitation
tokens at all. This directly satisfies S1G's own instruction ("do not
rely solely on a Redis TTL if the database remains the authoritative
invitation state") and is possible only because — unlike a verification
token — an Invitation already has a durable Postgres row to be
authoritative *on*.

The raw token is generated, hashed, and handed to the mail layer inside
`create_invitation`/`resend_invitation`; it is never stored, logged, or
returned by any API response body — `InvitationPublic` and
`PublicInvitationDetails` (`app/modules/workspaces/schemas.py`) simply
have no `token_hash`/token field to leak, rather than a field that's
merely nulled out.

### Invitation replacement — "replace, not duplicate"

**FROZEN REQUIREMENT:** at most one pending invitation may exist for
`(workspace_id, invited_email)` — the same partial unique index Sprint
1A already created — and re-inviting the same address replaces the
existing pending offer instead of running two side by side.
**IMPLEMENTATION CHOICE** for *how*: the previous pending row (if any)
is transitioned `pending → revoked` in the same transaction as the new
row's insert, reusing the lifecycle transition Invitation already has
rather than inventing a `superseded` status this entity doesn't define.
History is preserved (the old row still exists, queryable, just no
longer pending) — the same "soft transition, never delete" convention
Workspace/Membership already established in S1F. A genuine concurrent
create/create race for the identical `(workspace, email)` pair is
handled with a single retry (`_MAX_INVITATION_CREATE_ATTEMPTS = 2`);
see `create_invitation`'s own docstring for why an unhandled failure on
the (very unlikely) second attempt is accepted as reasonable.

### Email delivery — reuses S1E's architecture exactly

**FROZEN REQUIREMENT, carried forward from S1E unchanged:** the
business fact (the invitation row) must not be lost because email
delivery fails. `app/modules/workspaces/mail.py` is new (invitation-
specific subject/body), but calls the exact same
`app.core.mailer.send_email` every other transactional email in this
codebase already goes through — **no second SMTP implementation**.
`create_invitation`/`resend_invitation` both commit the Invitation row
*first*, then attempt delivery in a `try`/`except Exception` that logs
a warning (never the token) and never raises — the identical pattern
S1E's `_issue_and_send_verification_email` already established. Mailpit
(local dev, `docker-compose.yml`) captures every invitation email sent
during this sprint's own tests; `test_create_invitation_sends_email_via_mailpit`
(service- and HTTP-level) both assert against Mailpit's real REST API,
skipped automatically if Mailpit isn't reachable — same convention as
`app/core/tests/test_mailer.py`.

**UNRESOLVED CONTRACT GAP, unchanged from S1E:** true durable
Outbox-table-plus-worker delivery remains deferred — no Outbox/Celery
infrastructure exists anywhere in this repository to build on yet. The
try/except-log pattern above is the smallest mechanism that still
satisfies the frozen durability requirement, not a claim that delivery
is guaranteed-eventually.

**IMPLEMENTATION CHOICE, unchanged from S1E:** no frontend base URL
setting exists (`app.config.settings`), and inventing one is outside
S1G's own scope (no frontend UI) — the email includes the raw token as
a value to paste into `GET /api/v1/invitations/{token}`, not a
clickable link.

### Acceptance — the atomic transaction

**FROZEN REQUIREMENT, quoted directly:** "invitation acceptance
atomically closes the Invitation and creates the Membership... if
Membership creation fails, the transaction rolls back and the
Invitation remains pending." `service.accept_invitation` sets
`Membership` (new or reused — see below) and the Invitation's
`status = accepted` / `resolved_at = now()` in memory, then issues
**one** `session.commit()` for both. Verification order matches S1G's
own numbered flow exactly: token lookup → pending/not-expired
(`_settle_or_raise`, reused from the public-lookup path) → email match
→ workspace still usable (not `deleted`) → role still a valid system
role → existing-Membership check → commit.

**IMPLEMENTATION CHOICE — the "already an active member" gap:** S1G
explicitly leaves this unresolved for both creation (`AlreadyMemberError`,
409, reused generic `conflict` code) and acceptance. At accept-time,
rather than inventing a new public error code, acceptance still closes
the Invitation as `accepted` (the offer's purpose — "let this email
holder join" — is already satisfied) and returns the caller's
*existing* Membership unchanged, signaled via an internal `created`
flag the route layer doesn't currently surface in the response shape
(no frozen field for it exists).

**Race handling (frozen requirement, mechanically approximated):** if
the commit above raises `IntegrityError` — the partial unique index on
`(workspace_id, user_id) WHERE status='active'` caught a concurrent
winner — the transaction rolls back (undoing the in-memory `accepted`
mutation too, by construction), then re-queries for the now-committed
winning Membership and closes the Invitation out against *that* row
instead, in a fresh follow-up transaction. The Invitation is never left
`pending` after a successful response, and never `accepted` without a
real persisted Membership backing it. **Testing note:** this exact
branch is reasoned through in code comments but not independently
exercised by a real concurrent-thread test (the project's stated
philosophy is real Postgres/Redis, not mocks, and this codebase writes
no multi-threaded tests anywhere); `test_accept_invitation_when_already_active_member_does_not_duplicate`
deterministically reproduces the *outcome* the frozen requirement cares
about (no duplicate Membership, invitation not falsely left pending) by
pre-seeding the competing row rather than racing two real requests.

### Membership creation

**FROZEN REQUIREMENT:** `user_id` = the authenticated caller,
`workspace_id`/`role_id` = the invitation's own (never client-supplied
— the accept endpoint's only input is the opaque token), `status =
active`. The existing S1F partial unique index
(`workspace_id, user_id) WHERE status='active'`) is never bypassed —
acceptance goes through the identical `Membership` model S1F defined,
no parallel code path.

### Owner invariant

**FROZEN REQUIREMENT, confirmed unaffected:** S1F's invariant is a
*minimum* (a workspace must always have ≥1 active Owner) — it places no
ceiling on how many Owners may exist. Accepting an Owner-role
invitation is not specially restricted; `test_accept_invitation_owner_role_creates_additional_owner_no_cap`
confirms a second Owner is created without incident. **Per S1G's own
instruction, no maximum is invented** where the frozen model doesn't
impose one.

### Idempotency

**IMPLEMENTATION CHOICE — the first shared idempotency mechanism this
codebase has.** `app/core/idempotency.py` is new: a small, generic,
Redis-backed replay cache keyed by `(scope, actor, Idempotency-Key)`,
deliberately not invitation-specific in any name, so a later sprint
that finally enforces `POST /auth/register`'s own long-deferred
`Idempotency-Key` requirement (see "Known deviation: idempotency"
above, still unresolved for that endpoint) reuses this instead of
writing a second one. It caches a *finished* response (status code +
JSON body) and replays it verbatim on a retried request with the same
key from the same actor — enough to satisfy "a retry doesn't create a
second resource" for the ordinary case. Wired into the two endpoints
S1G marks `Idempotency-Key: REQUIRED`: `POST .../invitations` (scope
`workspace_invitation_create`, actor = `{user_id}:{workspace_id}`) and
`POST /invitations/{token}/accept` (scope `invitation_accept`, actor =
`user_id`). A missing header is a plain FastAPI-required-header 422,
using the existing generic validation envelope, not a new error code.

**UNRESOLVED GAP, explicitly not implemented:** no request-coalescing/
locking for two literally-concurrent requests bearing the identical key
before either has stored a result. S1G's own text says why this is an
acceptable gap for now: "database uniqueness remains the final
duplicate-prevention backstop" — the invitations table's partial unique
index and the memberships table's partial unique index are what
actually protect correctness in that narrow window, not this cache.
**`POST /workspaces` (S1F) and `POST /auth/register` (S1B) are
deliberately NOT retrofitted** to use this new mechanism — both are
frozen, out of S1G's explicit scope, and adding a newly-enforced
required header to an already-shipped endpoint is a contract change
this sprint wasn't asked to make.

### Tenant isolation

**FROZEN REQUIREMENT, same anti-enumeration design S1F already
established:** every workspace-scoped invitation route resolves
`workspace_id` exclusively through `RequireRole`'s existing RBAC
dependency (`require_admin`) — no route trusts a client-supplied
workspace_id/invitation_id to imply authorization. A non-member gets
`workspace_not_found` (404); an under-ranked member gets
`insufficient_permission` (403); an invitation_id that exists but
belongs to a *different* workspace than the URL's own is
indistinguishable from "doesn't exist" (`InvitationNotFoundError`, 404,
generic `not_found` — the same gap-fill precedent `SessionNotFoundError`
set in S1D). `test_cross_workspace_invitation_attack_sweep` exercises
create/list/resend/revoke against a foreign workspace, all rejected.
The public token-based endpoints need no such check at all by
construction: `GET /invitations/{token}` and `POST /invitations/{token}/accept`
take no `workspace_id` in the URL, only the opaque token — the
Membership `accept_invitation` creates is always scoped to the
*invitation's own* `workspace_id`, never anything a caller supplies
(`test_accept_invitation_membership_always_bound_to_invitations_own_workspace`).

### Anti-enumeration / privacy

**FROZEN REQUIREMENT:** `token_hash` and the raw token are never
returned by any endpoint — `InvitationPublic`/`PublicInvitationDetails`
simply have no such field, not a redacted one.
`PublicInvitationDetails` (the public, unauthenticated `GET
/invitations/{token}` response) is deliberately narrower than the
Admin-facing `InvitationPublic`: it omits `invited_by_user_id` (an
internal actor ID with no use to an unauthenticated caller) — an
**IMPLEMENTATION CHOICE**, since no frozen response shape exists for
either projection.

### Expiration

**IMPLEMENTATION CHOICE / UNRESOLVED CONTRACT GAP:** no frozen
Technical Design Document value exists for invitation token TTL (the
document itself isn't a file in this repository — same situation
S1E's own two token TTLs already documented). `settings.INVITATION_TOKEN_EXPIRE_DAYS`
(default 7) is a named configuration value, not a magic number, exactly
matching S1E's own precedent for the identical kind of gap.

**FROZEN REQUIREMENT, satisfied without any background worker:**
"expired invitations should transition to expired consistently... do
not rely solely on a Redis TTL." Since retention/background workers are
explicitly out of S1G's scope, expiry is enforced *lazily*: the first
endpoint to touch a `pending` invitation past its `expires_at`
(`_settle_or_raise`) flips it to `expired` and commits immediately. `GET
.../invitations` (the pending-list endpoint) additionally filters
`expires_at > now()` in its own query — an **IMPLEMENTATION CHOICE** so
a technically-expired-but-not-yet-lazily-touched row is never shown as
misleadingly still pending, without that hot list path itself
performing a write.

### Audit requirements

**FROZEN REQUIREMENT, honored by omission:** S1F's own audit-required
list names exactly two actions — Membership role changes, WorkspaceSettings
retention changes — and says nothing about invitations. Per S1G's own
instruction ("if the frozen audit requirements are silent for an
invitation action, document that fact instead of inventing a new audit
contract"), **no `AuditLog` row is written anywhere in this sprint's
code** — not on create, resend, revoke, or accept. This is a deliberate
literal-scope reading, the same one S1F itself already applied to
Membership *removal*.

### Endpoints implemented

`POST /workspaces/{id}/invitations`, `GET /workspaces/{id}/invitations`,
`POST /workspaces/{id}/invitations/{id}/resend`,
`DELETE /workspaces/{id}/invitations/{id}` (all four in
`app/api/v1/endpoints/workspaces.py`, alongside S1F's own routes) —
plus `GET /invitations/{token}` and `POST /invitations/{token}/accept`
(`app/api/v1/endpoints/invitations.py`, a new top-level router — these
two take no `workspace_id` at all, matching the frozen route shapes
exactly). `InvitationPublic` is reused as the response projection for
create/list/resend — an **IMPLEMENTATION CHOICE**, no frozen response
shape exists for any of the three, so one consistent projection is used
rather than three slightly different ones.

### Deviations from frozen specifications

None from S1G's own prompt text — every exact field name, endpoint,
status code, and named error code (`invitation_expired`,
`invitation_already_resolved`, `email_mismatch`) was implemented as
given.

### Testing infrastructure notes

**Real bug found and fixed: `invitations.invited_by_user_id` and
`audit_logs.actor_user_id` are both `ON DELETE RESTRICT`** (S1A's own
deliberate choice — an invitation/audit entry's actor is never
optional). `tests/db.py`'s `_cleanup_http_test_users` deletes HTTP-test
users by email pattern at the end of every `run_http_test` call; once
this sprint's tests started actually creating Invitation rows whose
`invited_by_user_id` points at those same test users, that DELETE
started failing the FK constraint outright, breaking cleanup for every
HTTP test in the suite, not just this sprint's own. Fixed by deleting
`invitations`/`audit_logs` rows scoped to the same about-to-be-deleted
user set *before* the `users` DELETE — shared test infrastructure, not
invitation-specific, so every future sprint's HTTP tests benefit from
the fix automatically. `Membership.invited_by_user_id`
(`ON DELETE SET NULL`) needed no equivalent fix.

### Regression

Full existing suite (S1A through S1F) re-run after S1G — see the
sprint report for the exact command and result.

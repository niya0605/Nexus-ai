# Database

**Purpose:** This folder contains the frozen **Data Dictionary** and
**PostgreSQL Database Design** for Nexus AI — every field's business
meaning and validation rules, plus the complete table inventory,
relationships, constraints, indexing strategy, and cascade rules.

**Expected files:** `DATA_DICTIONARY.md`, `DATABASE_DESIGN.md` (not yet
added), and migration history notes as the schema evolves via Alembic.

**Relationship to other documentation:** Implements the Entity & Domain
Model (`docs/architecture/`) as a concrete relational schema. The REST
API Contract's (`docs/api/`) request and response schemas map directly
to the field definitions and tables recorded here.

---

## Database Layer (Milestone M0.2C)

### Architecture

The database layer lives entirely in `backend/app/db/`, split into three
small, single-purpose modules — deliberately kept separate so each has
exactly one job and none of them import each other except in one
direction:

| Module | Responsibility |
|---|---|
| `base.py` | The single shared `DeclarativeBase` every future ORM model inherits from. Nothing else — no models, no metadata customization. |
| `session.py` | Builds the `AsyncEngine` (from `app.config.settings`, never a duplicated connection string) and the `async_sessionmaker`. |
| `dependencies.py` | The `get_db()` FastAPI dependency, which yields a request-scoped session from the factory in `session.py`. |

No model, table, migration, repository, or route exists yet — this
milestone provides only the infrastructure those will be built on.

### Why `AsyncEngine`

The backend is built async-first (FastAPI routes, `asyncpg` driver) so
that I/O-bound work — including database queries — never blocks the
event loop, per the Technical Design Document's Performance Strategy
(Section 22). Using SQLAlchemy's async engine end-to-end (rather than a
sync engine wrapped in a thread pool) keeps the connection pool, the
session, and every query on the same execution model as the rest of the
application, with no bridging layer to reason about.

### Session lifecycle

1. A request declares `db: AsyncSession = Depends(get_db)`.
2. `get_db()` opens a session from `AsyncSessionFactory`, scoped to that
   one request.
3. The route/service uses the session to read or write.
4. When the request ends, the `async with` block in `get_db()` closes
   the session — which implicitly rolls back anything left uncommitted.

**Committing is deliberately not this dependency's job.** Per the
Technical Design Document's Transaction Management strategy (Section
18), the transaction boundary belongs to the service layer — a service
method commits (or lets an exception propagate and roll back) at the
end of its own unit of work, not `get_db()`.

### Alembic workflow

Alembic is configured for SQLAlchemy 2.x's async engine (`alembic/env.py`
uses `async_engine_from_config` + `run_sync`, matching `app/db/session.py`'s
driver) and is wired to the same `Settings` object — the connection URL
is built once, in `app/db/session.py`, and reused by both the
application and Alembic; it is never duplicated as a static value in
`alembic.ini`.

`target_metadata` points at `Base.metadata` from `app/db/base.py`, so
`alembic revision --autogenerate` will pick up future models
automatically once they exist. `alembic/versions/` is intentionally
empty — no migration has been generated yet.

Once real models exist, the day-to-day workflow will be:

```bash
cd backend
alembic revision --autogenerate -m "create documents"
alembic upgrade head
```

Migration filenames follow the date-based convention already frozen in
the PostgreSQL Database Design (Section 15) — e.g.
`20260803_create_documents.py` — via `alembic.ini`'s `file_template`.

### Verifying the connection

`backend/scripts/verify_db_connection.py` is a standalone, manually-run
diagnostic — never imported by the application, never run automatically.
It builds its own short-lived engine, attempts one trivial query, prints
success or failure, and disposes of the engine cleanly either way:

```bash
cd backend
python -m scripts.verify_db_connection
```

### Future model organization

Each domain module under `backend/app/modules/<name>/` defines its own
`models.py` inheriting from `Base` — per the module template already
frozen in the Technical Design Document (Section 31). No model lives in
`app/db/` itself; that folder remains infrastructure only. Because
SQLAlchemy only knows about a model once its module has been imported,
`app/db/model_registry.py` is the one place every module's `models.py`
is imported centrally — `alembic/env.py` and the test suite both import
it, so nothing has to remember to list model modules in more than one
place.

---

## Authentication Schema (Sprint 1A)

The first real tables, implementing the Authentication domain models
(`app/modules/auth/models.py`, `app/modules/workspaces/models.py`) per
the frozen Data Dictionary — data shape only, no business logic:

| Table | Purpose |
|---|---|
| `users` | Authenticatable identity — the anchor table every other table's `user_id` reference ultimately resolves to. |
| `sessions` | Per-device authenticated state; one user has many. Cascades on user deletion. |
| `roles` | Named, system-defined capability tiers (`owner`, `admin`, `member`, `viewer`) — seed/reference data, not user-editable in MVP. |
| `invitations` | Pending offers for an email address to join a workspace at a role. At most one *pending* invitation per (workspace, email) pair, enforced by a partial unique index. |

**Two deliberate deviations from the frozen specification, documented in code:**
- `invitations.workspace_id` has no foreign key constraint yet — `workspaces` doesn't exist until the sprint that implements the Workspace domain. The column's shape matches the Data Dictionary exactly; only the constraint is deferred.
- `invitations.invited_by_user_id` uses `ON DELETE RESTRICT` rather than the Database Design's originally-specified `SET NULL` — resolving a genuine inconsistency between two frozen documents (the Data Dictionary marks this column `NOT NULL`, which `SET NULL` cannot satisfy). See `app/modules/workspaces/models.py`'s docstring for the full reasoning.

Enum-shaped columns (`status`, `name`) are `VARCHAR` + `CHECK`, not native PostgreSQL `ENUM` types — matching the Database Design's normalization strategy exactly. `Role` and `Invitation` are code-owned by the `workspaces` module, not `auth`, per the Technical Design Document's Ownership Matrix — even though the Entity & Domain Model groups all four tables under one conceptual "Authentication Domain."

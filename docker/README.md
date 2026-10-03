# Local Infrastructure (Docker Compose)

This folder documents the local infrastructure stack defined in
`docker-compose.yml` at the repository root. As of Milestone M0.2A, this
provisions the **stateful services only** — no application containers
(backend, frontend, Celery workers) exist yet; those are added in
M0.2B and beyond, once the application has configuration to run against.

---

## Services

### `postgres` (`nexus-postgres`)
**Purpose:** Primary relational datastore — the source of truth for
users, workspaces, RBAC, document metadata, chat history, and every
other entity defined in the frozen Data Dictionary and Database Design.
**Port:** `5432` (default PostgreSQL port), mapped `5432:5432`.
**Volume:** `postgres-data`, mounted at `/var/lib/postgresql/data` —
survives container restarts and recreation.
**Credentials:** read from `${POSTGRES_USER}`, `${POSTGRES_PASSWORD}`,
`${POSTGRES_DB}` — not yet defined anywhere in this repository.
`docker compose up` will warn about these until M0.2B introduces
`.env.example`.

### `redis` (`nexus-redis`)
**Purpose:** Cache, session/refresh-token store, rate limiting, and the
Celery message broker/result backend, per the Technical Design
Document's Redis Usage Strategy.
**Port:** `6379` (default Redis port), mapped `6379:6379`.
**Volume:** `redis-data`, mounted at `/data`.

### `qdrant` (`nexus-qdrant`)
**Purpose:** Vector database storing document chunk embeddings for
semantic retrieval — the data layer behind RAG chat.
**Ports:** `6333` (REST API) and `6334` (gRPC API), both mapped 1:1.
**Volume:** `qdrant-data`, mounted at `/qdrant/storage`.

### `minio` (`nexus-minio`)
**Purpose:** S3-compatible object storage standing in locally for the
production cloud storage backend behind the storage abstraction
described in the Technical Design Document — this is where uploaded
document files live in development.
**Ports:** `9000` (S3 API) and `9001` (web console), both mapped 1:1.
**Volume:** `minio-data`, mounted at `/data`.
**Credentials:** read from `${MINIO_ROOT_USER}`, `${MINIO_ROOT_PASSWORD}`
— not yet defined anywhere in this repository. `docker compose up` will
warn about these until M0.2B introduces `.env.example`.

### `mailpit` (`nexus-mailpit`)
**Purpose:** Captures outgoing email locally instead of sending it, so
verification and password-reset emails can be inspected during
development without a real email provider.
**Ports:** `1025` (SMTP, what the backend will eventually send to) and
`8025` (web UI, for reading captured mail in a browser).
**Volume:** none — captured mail is disposable by design.

---

## Network

All five services share a single dedicated bridge network,
`nexus-network`, so they can resolve each other by service name once
application containers join the same network in a later milestone.
Nothing outside this Compose file's services is attached to it yet.

---

## Usage

**Start the full stack** (foreground):
```bash
docker compose up
```

**Start in the background:**
```bash
docker compose up -d
```

**Stop the stack** (containers removed, volumes and data preserved):
```bash
docker compose down
```

**Stop the stack and permanently delete all data** (drops every named
volume — Postgres, Redis, Qdrant, and MinIO data are all lost):
```bash
docker compose down -v
```

**View logs for a single service:**
```bash
docker compose logs -f postgres
```

---

## Intentionally Not Included Yet

Per Milestone M0.2A's scope, this stack deliberately has no `.env` file,
no health checks, no `depends_on` ordering, no application services, and
no reverse proxy or observability stack (Traefik, NGINX, Prometheus,
Grafana). These are addressed in later milestones as the application
itself is built — see the root `README.md`'s roadmap and
`docs/development/` for what's next.

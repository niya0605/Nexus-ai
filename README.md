# Nexus AI

An AI-powered Knowledge Workspace — upload your team's documents, chat
with them using retrieval-augmented generation, and get answers with
real, verifiable citations back to the source.

Nexus AI is built as a production-grade modular monolith, designed to be
operable end-to-end by a single developer while holding to the
engineering standards of a real, funded SaaS product.

---

## Project Overview

Nexus AI lets a team:

- Create a workspace and invite teammates with role-based access control
- Upload PDF, DOCX, TXT, and Markdown documents
- Chat across one or many documents, with every answer grounded in a
  cited source passage — never an ungrounded guess
- Get AI-generated summaries, tags, and document insights automatically
- Track workspace activity, usage, and content gaps through built-in
  analytics


The full specification — vision, requirements, UX design, architecture,
and API contract — is frozen and lives under `docs/`. This repository
implements that specification directly; nothing here should diverge
from it without an accompanying decision record (`docs/adr/`).

---

## Tech Stack

**Frontend** — Next.js 15 (App Router, TypeScript), Tailwind CSS,
shadcn/ui, TanStack Query, React Hook Form, Zod

**Backend** — FastAPI (modular monolith), SQLAlchemy + Alembic,
Pydantic, self-built JWT authentication, Redis, Celery, Qdrant,
PostgreSQL 17

**Infrastructure** — Docker Compose (local dev), GitHub Actions (CI/CD),
Vercel (frontend), Railway or Render (backend + data services)

Deliberately **not** used: Kubernetes, Terraform, an API gateway, a
microservices split, or any AWS-specific service — see `docs/adr/` for
the reasoning once recorded.

---

## Repository Layout

```
nexus-ai/
├── frontend/     Next.js application (TypeScript, App Router, Tailwind)
├── backend/      FastAPI application (modular monolith)
├── docs/         Frozen specifications and supporting documentation
├── docker/       Local service configuration (Postgres, Redis, Qdrant, MinIO, Mailpit)
├── infra/        Deployment configuration (Vercel, Railway/Render)
├── scripts/      setup / format / lint / test / dev helper scripts
└── .github/      CI/CD workflows
```

---

## Documentation Index

| Folder | Contents |
|---|---|
| [`docs/product/`](docs/product/README.md) | Product Specification — vision, requirements, roadmap |
| [`docs/ux/`](docs/ux/README.md) | UX Specification — IA, journeys, screens, design system |
| [`docs/architecture/`](docs/architecture/README.md) | Technical Design Document, Entity & Domain Model |
| [`docs/database/`](docs/database/README.md) | Data Dictionary, PostgreSQL Database Design |
| [`docs/api/`](docs/api/README.md) | REST API Contract |
| [`docs/adr/`](docs/adr/README.md) | Architecture Decision Records |
| [`docs/development/`](docs/development/README.md) | Local setup and contribution guide |

---

## Development Roadmap

Per the frozen Technical Design Document's milestone plan, at a solo
developer's pace:

| Phase | Focus |
|---|---|
| **0. Foundations** | Repo scaffolding, CI pipeline, DB schema baseline |
| 1. Auth | Registration, login, JWT + refresh, RBAC |
| 2. Workspaces & Documents | Workspace CRUD, upload flow, metadata |
| 3. Ingestion Pipeline | Parse → chunk → embed → index |
| 4. RAG Chat | Retrieval, citations, multi-document chat |
| 5. AI Workspace Layer | Summaries, AI tags, document insights |
| 6. Analytics & Polish | Usage analytics, UI polish, shortcuts |
| 7. Deployment & Demo Readiness | Production deploy, MVP complete |
| 8. Phase 1.5 Enhancements | Streaming chat, workspace memory |

### Current Milestone — **M0.1 Complete**
Repository scaffolding: frontend and backend skeletons, folder
structure, no business logic, no dependencies beyond the scaffolds
themselves.

### Upcoming Milestone — **M0.2: Infrastructure**
Docker Compose (Postgres, Redis, Qdrant, MinIO, Mailpit), backend
configuration (`core/config`), and local environment wiring — still no
business logic.

---

## License

*Placeholder — license to be determined.*

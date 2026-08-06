# API

**Purpose:** This folder contains the frozen **REST API Contract** for
Nexus AI — every endpoint's method, URL, authentication and permission
requirements, request/response schemas, error behavior, pagination and
idempotency rules — plus the auto-generated OpenAPI/Swagger reference
once the API routers exist.

**Expected files:** `API_CONTRACT.md` (not yet added); the live OpenAPI
spec is generated from the running backend, not hand-authored here.

**Relationship to other documentation:** The contract between frontend
and backend. It implements the database design (`docs/database/`) and
the data needs described by the UX Specification (`docs/ux/`) as
concrete HTTP endpoints — this is what `backend/app/api` and the
frontend's API client are built against.

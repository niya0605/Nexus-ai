# Architecture

**Purpose:** This folder contains the frozen **Technical Design
Document** and **Entity & Domain Model** for Nexus AI — the modular
monolith's engineering blueprint (module responsibilities, request
lifecycle, authentication and authorization flows, background job
architecture, security architecture) and the business domain model
(entities, aggregates, invariants) underneath it.

**Expected files:** `TECHNICAL_DESIGN_DOCUMENT.md`,
`ENTITY_DOMAIN_MODEL.md` (not yet added).

**Relationship to other documentation:** Translates the Product and UX
Specifications into an implementable system design. The database schema
(`docs/database/`) and REST API contract (`docs/api/`) are direct,
faithful implementations of what is defined here — neither should
introduce a concept, entity, or relationship this folder doesn't already
describe.

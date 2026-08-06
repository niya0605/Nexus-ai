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

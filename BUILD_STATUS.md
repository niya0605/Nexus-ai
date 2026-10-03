# Nexus AI Build Status & Roadmap

## What's Done ✅ (Oct 2, 2026)

### Latest Additions (This Session)
- [x] Chunks table with pgvector support (migration created)
- [x] Document parser for PDF/DOCX/TXT/MD files
- [x] Text chunking with 800-token chunks, 100-token overlap
- [x] Document service for sync processing (MVP)
- [x] Document upload endpoints (needs python-multipart)
- [x] Database migrations complete (Chunk model registered)

### Backend Infrastructure
- [x] FastAPI scaffolding with middleware, error handling, logging
- [x] PostgreSQL with SQLAlchemy ORM and Alembic migrations
- [x] Pydantic configuration management (`app/config/settings.py`)
- [x] Request ID tracking and structured logging

### Database Models & Migrations
- [x] Users, Sessions (auth)
- [x] Workspaces, Memberships, WorkspaceSettings, AuditLog
- [x] Invitations with token lifecycle
- [x] Documents, DocumentVersions, ProcessingJobs
- [x] All migrations up to 20260815

### API Endpoints (27 total)
- [x] Auth: signup, login, refresh, logout, sessions (GET/DELETE)
- [x] Workspaces: CRUD, archive, restore, delete
- [x] Members: list, change role, remove
- [x] Invitations: create, list, resend, revoke, accept, details
- [x] Health check

### Frontend Pages
- [x] Landing page
- [x] Login page
- [x] Register page
- [x] Dashboard (shell)
- [x] Component library started (auth, layout, ui, visual, icons, gamification)

### Security & Auth
- [x] JWT access tokens + opaque refresh tokens
- [x] Argon2 password hashing
- [x] Refresh token rotation with Redis backing
- [x] RBAC with four roles (Viewer, Member, Admin, Owner)
- [x] Email verification and password reset (via Mailpit)
- [x] Idempotency key support for POST endpoints

---

## What's Needed (MVP First) 🚀

### Phase 1: Document Ingestion & Storage
**Duration:** Week 1-2

1. **Chunk & Embedding Models** (PostgreSQL)
   - `chunks` table: document_id, page_start, page_end, content, embedding (pgvector), tsv (tsvector for full-text)
   - Migration: add pgvector extension, create table
   - Add HNSW index on embedding, GIN on tsvector

2. **Document Upload Endpoint**
   ```
   POST /documents/{workspace_id}/upload
   - Accept PDF/DOCX/TXT/MD
   - Store to MinIO via app/core/storage.py
   - Create Document + DocumentVersion rows
   - Enqueue ProcessingJob
   - Return document_id + job_id for progress tracking
   ```

3. **Worker Infrastructure** (arq + Redis)
   - Set up arq Redis queue
   - Worker entrypoint: `backend/worker.py`
   - Job type: `ingest_document`
   - Stages: parse → chunk → embed → store chunks

4. **Parser & Chunker** (`app/tasks/ingestion.py`)
   - **Parsers:** PyMuPDF (PDF, TXT), python-docx (DOCX), markdown (MD)
   - **Chunker:** 800-token chunks, 100-token overlap, track page numbers
   - **Embeddings:** use OpenAI API (or Ollama for local dev)
   - **Batch embed:** 100-item batches to API
   - Emit progress: parsing 40% → chunking 70% → embedding 95% → storing

5. **Progress WebSocket** (optional for MVP, but on resume)
   ```
   WS /ws/documents/{document_id}/progress
   - Client connects, server sends progress updates every ~2s
   - {"status": "parsing", "progress": 40, "message": "..."}
   - Closes when status = "ready" or "failed"
   ```

### Phase 2: Retrieval & Q&A
**Duration:** Week 2-3

1. **Hybrid Retrieval** (`app/modules/documents/retrieval.py`)
   - Vector search: `pgvector` cosine similarity (top-k, e.g., 15)
   - Full-text: PostgreSQL tsvector with weighted ranking
   - **RRF (Reciprocal Rank Fusion):** merge results, sort by combined score
   - Return: [(chunk, score, page_range), ...]

2. **Q&A Endpoint**
   ```
   POST /documents/{document_id}/chat
   Request:  {"message": "What is ...?", "session_id": "..."}
   Response: stream chunks of the LLM response, each with citations
   
   - Look up or create chat_session
   - Retrieve hybrid chunks
   - Build system prompt with chunks + instructions for citations
   - Stream via WebSocket or SSE with chunked transfer encoding
   - Save message + citations to DB
   ```

3. **Citations & Jump-to-Page**
   - Store `citations: List[{chunk_id, page_start, page_end}]` in messages
   - Frontend highlights retrieved chunks on PDF viewer

4. **Chat History**
   ```
   GET /documents/{document_id}/chat-sessions
   GET /documents/{document_id}/chat-sessions/{session_id}
   ```

### Phase 3: Quiz & Explanation
**Duration:** Week 3-4

1. **Explain Selection Endpoint**
   ```
   POST /documents/{document_id}/explain
   Request: {"text": "...", "page": 5, "depth": "simple|standard|deep"}
   
   - Find chunk containing text
   - Retrieve context chunks
   - Prompt LLM with "explain at [depth] level"
   - Stream response with citations
   ```

2. **Quiz Generation**
   ```
   POST /documents/{document_id}/quizzes
   Request: {"page_range": [1, 10], "difficulty": "easy|medium|hard", "count": 5}
   Response: quiz_id + questions
   
   - Retrieve chunks from page range
   - Prompt: "Generate 5 [difficulty] [type] questions"
   - Types: MCQ, T/F, short answer
   - Parse JSON response, validate vs Pydantic models
   - Retry on validation failure (max 3 attempts)
   ```

3. **Quiz Submission & Grading**
   ```
   POST /quizzes/{quiz_id}/attempts/{question_id}/submit
   
   - MCQ/T/F: deterministic grading
   - Short answer: call LLM grader with rubric
   - Save attempt_answers with score + feedback
   ```

4. **Weak Topic Tracking**
   - Add `topic` field to questions
   - GET `/users/me/progress`: accuracy per topic
   - Button to generate remedial quiz on weak topics

### Phase 4: Frontend UI & Polish
**Duration:** Week 4-5

1. **PDF Viewer Component**
   - `react-pdf` or `pdfjs-dist`
   - Display current page + page selector
   - Highlight cited chunks (yellow box + page jump on click)
   - Zoom controls

2. **Document Dashboard**
   ```
   GET /documents → list with:
   - Title, upload date, page count
   - Status badge (uploading/processing/ready/failed)
   - Progress bar during ingestion
   - Delete button
   ```

3. **Q&A Interface**
   - Input box + send button
   - Chat history on left
   - Streaming response with citations on right
   - Copy/export message button

4. **Quiz Interface**
   - MCQ: radio buttons per option
   - T/F: two buttons
   - Short answer: text input
   - Submit button, shows feedback immediately

5. **Explain Panel**
   - Text selection highlight
   - Depth selector (radio: Simple / Standard / Deep)
   - Streaming explanation response

### Phase 5: Caching & V1 Polish
**Duration:** Week 5-6

1. **Redis Caching**
   - Cache summaries: `summary:{document_id}` TTL 24h
   - Cache frequent Q&A pairs: `qa:{hash(question)}` TTL 1h
   - Rate limiting: 100 requests/hour per user

2. **Error Handling & Edge Cases**
   - Graceful degradation if embedding API fails
   - Retry logic for failed chunks
   - User feedback for LLM refusal / token overflow

3. **Testing (70% backend coverage)**
   - Unit: chunker (boundaries, overlap), hybrid retrieval RRF
   - Integration: upload → chunks stored, Q&A retrieves & cites
   - Retrieval eval: 30 questions over 2–3 test PDFs, track hit@5, citation accuracy

4. **Documentation**
   - Architecture diagram (flow: upload → ingestion → retrieval → generation)
   - Retrieval eval results in README
   - Deployment: Vercel (frontend), Render/Railway (backend + worker)

---

## V2 Features (Post-MVP)
- [ ] OCR fallback for scanned pages (Tesseract)
- [ ] Spaced repetition flashcards (SM-2 algorithm)
- [ ] Document summaries (by chapter / page range)
- [ ] Notes and highlights per page
- [ ] Multi-document search
- [ ] Export quizzes as PDF / Anki CSV
- [ ] Streaming with Server-Sent Events (SSE) instead of WebSocket
- [ ] LLM API caching / latency optimization
- [ ] Advanced analytics (time spent, common questions)

---

## Build Order Summary

| Priority | Week | What | Why |
|---|---|---|---|
| 1 | 1-2 | Chunks, Parser, Chunker, Worker | Need this to process documents |
| 2 | 2-3 | Hybrid Retrieval, Q&A Streaming | Core feature - answering with citations |
| 3 | 3-4 | Explain, Quiz Gen, Quiz Grading | Differentiation in resume |
| 4 | 4-5 | PDF Viewer, Dashboard UIs | Makes it usable, shows visual design |
| 5 | 5-6 | Caching, Tests, Docs, Deploy | Polish + interview-ready |

---

## Current Environment Status

```
Frontend:  http://localhost:3001 ✓ (Next.js dev server)
Backend:   http://localhost:8000 ✓ (FastAPI)
PostgreSQL: Not running (Docker not available)
Redis:     Not running (Docker not available)
MinIO:     Not running (Docker not available)
```

**Note:** Full development requires Docker. Consider:
- Option A: Use PostgreSQL.app + Redis via Homebrew (local dev only)
- Option B: Spin up a Render.com or Railway.com PostgreSQL instance for development
- Option C: Use GitHub Codespaces (has Docker built-in)


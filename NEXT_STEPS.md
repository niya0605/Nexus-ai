# Next Steps - Nexus AI

## Right Now (1 pip install away from working uploads)

```bash
pip install python-multipart
# Then test POST /documents/{workspace_id}/upload
```

## This Hour: Retrieval + Q&A (Core MVP)

### 1. Create `app/modules/documents/retrieval.py`
```python
async def hybrid_search(
    db: AsyncSession,
    document_id: uuid.UUID,
    query: str,
    limit: int = 10,
) -> list[Chunk]:
    """Full-text search on tsvector, fallback to content substring match."""
    # SELECT * FROM chunks WHERE document_id = ? AND tsv @@ plainto_tsquery(?)
    # ORDER BY ts_rank(tsv, query) DESC
    # LIMIT ?
```

### 2. Create `app/modules/chat/service.py`
```python
async def answer_question(
    db: AsyncSession,
    document_id: uuid.UUID,
    question: str,
    session_id: uuid.UUID | None = None,
) -> AsyncGenerator[str, None]:
    """Retrieve chunks, call LLM, stream response."""
    # chunks = await hybrid_search(...)
    # async for token in llm.stream_chat(...):
    #     yield token
```

### 3. Add WebSocket endpoint (optional for MVP, nice-to-have)
```python
@router.websocket("/ws/chat/{document_id}")
async def chat_websocket(ws: WebSocket, document_id: uuid.UUID):
    """Stream Q&A responses."""
```

### 4. Add tests
- Upload → chunks stored
- Retrieval returns correct chunks
- Q&A streaming works

---

## Tonight: Quiz System

### 1. Create quiz generation prompt + Pydantic models
```python
# Questions: MCQ, T/F, short answer
# Grade short answers with LLM rubric
```

### 2. Add endpoints
```
POST /documents/{document_id}/quizzes
POST /quizzes/{quiz_id}/attempts/{question_id}/submit
```

---

## Tomorrow: Frontend

### 1. PDF viewer with citations
```bash
npm install react-pdf
# Component: PDFViewer with click-to-highlight
```

### 2. Q&A interface
- Input box
- Chat history
- Streaming display
- Citation links

### 3. Dashboard
- Document list
- Upload button
- Status badges (uploading/ready/failed)

---

## Key Files to Edit

| When | File | What |
|---|---|---|
| Now | `app/modules/documents/retrieval.py` | Hybrid search |
| Now | `app/modules/chat/schemas.py` | ChatMessage, ChatSession |
| Now | `app/modules/chat/service.py` | Q&A generation |
| Now | `app/api/v1/endpoints/chat.py` | Chat endpoints |
| Tonight | `app/modules/quiz/...` | Quiz generation + grading |
| Tomorrow | `frontend/src/components/PDFViewer.tsx` | PDF rendering |
| Tomorrow | `frontend/src/app/documents/[id]/page.tsx` | Document detail page |

---

## Database Queries You'll Need

```sql
-- Full-text search
SELECT * FROM chunks 
WHERE document_id = '...' 
AND tsv @@ plainto_tsquery('english', ?) 
ORDER BY ts_rank(tsv, plainto_tsquery('english', ?)) DESC;

-- Substring fallback
SELECT * FROM chunks 
WHERE document_id = '...' 
AND content ILIKE '%' || ? || '%'
LIMIT 10;

-- Create chat session
INSERT INTO chat_sessions (id, user_id, document_id) 
VALUES (gen_random_uuid(), '...', '...');

-- Store message
INSERT INTO messages (id, session_id, role, content, citations) 
VALUES ('...', '...', 'assistant', '...', '["chunk_id", ...]'::jsonb);
```

---

## Test Scenario

1. Upload a PDF (document upload endpoint)
2. Check chunks in DB (psql)
3. Ask a question (chat endpoint)
4. Verify retrieval works (chunks contain relevant text)
5. Check response (streamed token by token)
6. Create a quiz
7. Answer quiz questions
8. Check grading

---

## Commit Messages When Done

```
feat(documents): add document upload and chunking

- Parse PDF/DOCX/TXT/MD files
- Split into 800-token chunks with 100-token overlap
- Store in PostgreSQL chunks table
- Create document version tracking

feat(chat): implement hybrid search and Q&A streaming

- Combine full-text search (tsvector) + embedding fallback
- Stream LLM responses over WebSocket
- Track chat history with citations

feat(quiz): generate and grade quizzes

- Generate MCQ, T/F, short-answer questions from document
- Grade with deterministic or LLM rubric
- Track weak topics for remedial quizzes
```

---

## When You're Stuck

1. **Imports failing?** → Check `app/db/model_registry.py`
2. **Migration error?** → `alembic current` then check revision IDs
3. **Type errors?** → Verify Pydantic model matches DB schema
4. **Endpoint 404?** → Check router registration in `app/api/v1/router.py`
5. **WebSocket issues?** → Use JSON messages, handle disconnects

---

## Performance Notes for Later

- **Embedding computation:** Move to worker (arq + Redis)
- **Search optimization:** Add HNSW index when pgvector deployed
- **Caching:** Redis for common Q&A + summaries
- **Rate limiting:** 100 requests/hour per user


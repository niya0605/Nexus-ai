"""Split page-aware document text into overlapping chunks that remember their page."""

from typing import NamedTuple

from app.modules.documents.parsers import PageText

# ~800 tokens per chunk with ~100 tokens of overlap, at ≈4 characters per token.
CHUNK_CHARS = 3200
OVERLAP_CHARS = 400
# How far back from a window's end to look for whitespace, so words aren't cut.
_BOUNDARY_SEARCH_CHARS = 200


class PagedChunk(NamedTuple):
    content: str
    page_start: int
    page_end: int


def split_pages_into_chunks(
    pages: list[PageText], chunk_chars: int = CHUNK_CHARS, overlap_chars: int = OVERLAP_CHARS
) -> list[PagedChunk]:
    """Chunk each page on its own, so every chunk cites exactly one page.

    Chunks never cross a page boundary: precise citations matter more than
    filling every chunk to capacity. `page_end` mirrors `page_start` and is kept
    so a future strategy can span pages without a schema change.
    """
    chunks: list[PagedChunk] = []
    for page in pages:
        for content in _split_text(page.text, chunk_chars, overlap_chars):
            chunks.append(PagedChunk(content, page.page, page.page))
    return chunks


def _split_text(text: str, chunk_chars: int, overlap_chars: int) -> list[str]:
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_chars, len(text))
        if end < len(text):
            boundary = max(
                text.rfind(" ", end - _BOUNDARY_SEARCH_CHARS, end),
                text.rfind("\n", end - _BOUNDARY_SEARCH_CHARS, end),
            )
            if boundary > start:
                end = boundary

        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)

        if end >= len(text):
            break
        next_start = max(end - overlap_chars, start + 1)
        word_start = text.find(" ", next_start, end)
        start = word_start + 1 if word_start != -1 else next_start
    return pieces


def estimate_tokens(text: str) -> int:
    """Rough estimate of token count (1 token ≈ 4 chars)."""
    return len(text) // 4

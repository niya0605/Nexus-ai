"""Document chunking logic - split documents into overlapping chunks."""

from typing import NamedTuple


class ChunkSpec(NamedTuple):
    """Specification for how to chunk documents."""
    chunk_size: int = 800  # tokens per chunk
    overlap: int = 100  # tokens of overlap between chunks
    separator: str = "\n"  # prefer splitting on paragraphs


class PagedChunk(NamedTuple):
    """A chunk of document text with page information."""
    content: str
    page_start: int
    page_end: int


def split_text_into_chunks(text: str, spec: ChunkSpec = ChunkSpec()) -> list[PagedChunk]:
    """Split document text into overlapping chunks, preserving page boundaries.

    For now, without OCR/page-aware parsing, all chunks are assigned page_start=0.
    Future versions with PyMuPDF will track actual page numbers.
    """
    # Simple token counting: approximate 1 token ≈ 4 characters
    TOKEN_CHARS_RATIO = 4

    chunk_chars = spec.chunk_size * TOKEN_CHARS_RATIO
    overlap_chars = spec.overlap * TOKEN_CHARS_RATIO
    stride = chunk_chars - overlap_chars

    # Split on paragraphs (double newline) first, then by fixed size
    paragraphs = text.split(spec.separator)

    chunks: list[PagedChunk] = []
    current_pos = 0
    chunk_idx = 0

    while current_pos < len(text):
        # Extract chunk
        end_pos = min(current_pos + chunk_chars, len(text))
        chunk_text = text[current_pos:end_pos]

        if chunk_text.strip():
            chunks.append(PagedChunk(
                content=chunk_text.strip(),
                page_start=0,  # TODO: track actual pages with PyMuPDF
                page_end=0
            ))

        # Move to next chunk with overlap
        current_pos += stride
        chunk_idx += 1

    return chunks


def estimate_tokens(text: str) -> int:
    """Rough estimate of token count (1 token ≈ 4 chars)."""
    return len(text) // 4


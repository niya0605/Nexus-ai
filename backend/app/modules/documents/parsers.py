"""Document parsers - extract text from PDF, DOCX, TXT, MD files, page by page."""

from pathlib import Path
from typing import NamedTuple

# Formats without real pages (DOCX, TXT, MD) report their whole text as page 0.
NO_PAGE = 0


class PageText(NamedTuple):
    page: int
    text: str


def _parse_pdf(file_path: str) -> list[PageText]:
    import pymupdf

    with pymupdf.open(file_path) as doc:
        return [PageText(number, page.get_text()) for number, page in enumerate(doc, 1)]


def _parse_docx(file_path: str) -> list[PageText]:
    from docx import Document

    paragraphs = [p.text for p in Document(file_path).paragraphs if p.text.strip()]
    return [PageText(NO_PAGE, "\n".join(paragraphs))]


def _parse_plain_text(file_path: str) -> list[PageText]:
    return [PageText(NO_PAGE, Path(file_path).read_text(encoding="utf-8"))]


PARSERS = {
    "pdf": _parse_pdf,
    "docx": _parse_docx,
    "txt": _parse_plain_text,
    "md": _parse_plain_text,
}


def parse_document_pages(file_path: str, file_type: str) -> list[PageText]:
    """Extract text per page. Pages with no text (e.g. scanned images) are kept
    as empty strings so page numbering stays aligned with the original file."""
    parser = PARSERS.get(file_type.lower())
    if not parser:
        raise ValueError(f"Unsupported file type: {file_type}")
    return parser(file_path)


def pages_to_display_text(pages: list[PageText]) -> str:
    """Full text for the viewer — PDFs get a "--- Page N ---" header per page."""
    if all(p.page == NO_PAGE for p in pages):
        return "\n".join(p.text for p in pages)
    return "".join(f"\n--- Page {p.page} ---\n{p.text}" for p in pages if p.text.strip())

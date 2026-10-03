"""Document parsers - extract text from PDF, DOCX, TXT, MD files."""

from pathlib import Path


def parse_text_file(file_path: str) -> str:
    """Parse plain text file."""
    return Path(file_path).read_text(encoding="utf-8")


def parse_markdown_file(file_path: str) -> str:
    """Parse Markdown file (just read as text for now)."""
    return Path(file_path).read_text(encoding="utf-8")


def parse_pdf_file(file_path: str) -> str:
    """Parse PDF using PyMuPDF (fitz).

    Requires: pip install pymupdf
    """
    import pymupdf

    doc = pymupdf.open(file_path)
    text_parts = []

    for page_num, page in enumerate(doc, 1):
        text = page.get_text()
        if text.strip():
            text_parts.append(f"\n--- Page {page_num} ---\n{text}")

    return "".join(text_parts)


def parse_docx_file(file_path: str) -> str:
    """Parse DOCX file using python-docx.

    Requires: pip install python-docx
    """
    try:
        from docx import Document
    except ImportError:
        raise ImportError("python-docx not installed. Run: pip install python-docx")

    doc = Document(file_path)
    text_parts = []

    for para in doc.paragraphs:
        if para.text.strip():
            text_parts.append(para.text)

    return "\n".join(text_parts)


# Map file extensions to parsers
PARSERS = {
    "pdf": parse_pdf_file,
    "txt": parse_text_file,
    "md": parse_markdown_file,
    "docx": parse_docx_file,
}


def parse_document(file_path: str, file_type: str) -> str:
    """Parse document based on file type."""
    parser = PARSERS.get(file_type.lower())
    if not parser:
        raise ValueError(f"Unsupported file type: {file_type}")

    return parser(file_path)


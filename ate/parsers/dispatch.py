"""Format detection and dispatch.

Detection is by magic bytes first, extension second. We never trust the
extension alone — a .pdf with HTML inside should fail UnsupportedFormatError,
not crash deep in pdfplumber.
"""
from __future__ import annotations

from pathlib import Path

from ate.errors import UnsupportedFormatError
from ate.ir import Document

PDF_MAGIC = b"%PDF-"
DOCX_MAGIC = b"PK\x03\x04"  # zip; further checked via Content_Types


def detect_format(path: Path) -> str:
    """Return one of {'pdf', 'docx', 'txt'} or raise UnsupportedFormatError."""
    if not path.exists():
        raise UnsupportedFormatError(f"file not found: {path}")
    if not path.is_file():
        raise UnsupportedFormatError(f"not a regular file: {path}")

    with path.open("rb") as f:
        head = f.read(4096)

    if head.startswith(PDF_MAGIC):
        return "pdf"

    if head.startswith(DOCX_MAGIC):
        # Could be any zip; verify it's an Office Open XML document.
        # python-docx will raise if it's not.
        if b"word/document.xml" in head or path.suffix.lower() == ".docx":
            return "docx"
        raise UnsupportedFormatError(
            f"{path}: zip archive but not a DOCX (no word/document.xml in header)"
        )

    # Treat as text ONLY when extension explicitly says so AND content is
    # plain text (or empty — let the parser raise EmptyDocumentError).
    # Implicit text-detection on unknown extensions (.html, .md, binary
    # blobs) is a foot-gun: it lets unsupported files silently parse.
    suffix = path.suffix.lower()
    if suffix in {".txt", ".text"}:
        if head and not _looks_like_text(head):
            raise UnsupportedFormatError(
                f"{path}: extension is text but content is binary "
                f"(head={head[:8]!r})"
            )
        return "txt"

    raise UnsupportedFormatError(
        f"{path}: unsupported file format "
        f"(suffix={suffix!r}, head={head[:8]!r})"
    )


def _looks_like_text(head: bytes) -> bool:
    if not head:
        return False
    # Reject binary-ish content quickly.
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError:
        try:
            head.decode("latin-1")
            return True
        except UnicodeDecodeError:
            return False


def parse(path: str | Path) -> Document:
    """Parse any supported document into a Document IR."""
    path = Path(path)
    fmt = detect_format(path)
    if fmt == "pdf":
        from ate.parsers.pdf_parser import parse_pdf
        return parse_pdf(path)
    if fmt == "docx":
        from ate.parsers.docx_parser import parse_docx
        return parse_docx(path)
    if fmt == "txt":
        from ate.parsers.txt_parser import parse_txt
        return parse_txt(path)
    raise UnsupportedFormatError(f"{path}: detected format {fmt!r} has no parser")

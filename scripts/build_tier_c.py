#!/usr/bin/env python3
"""Generate Tier-C edge case files for parser robustness testing.

Each file maps to an expected typed error class. The scorecard's edge_cases
section asserts that each file produces exactly the expected error class.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIER_C = ROOT / "tests" / "corpus" / "tier_c"
TIER_C.mkdir(parents=True, exist_ok=True)


def empty_txt() -> tuple[Path, str]:
    path = TIER_C / "empty.txt"
    path.write_bytes(b"")
    return path, "EmptyDocumentError"


def whitespace_only_txt() -> tuple[Path, str]:
    path = TIER_C / "whitespace_only.txt"
    path.write_bytes(b"   \n\n  \t\n")
    return path, "EmptyDocumentError"


def broken_encoding_txt() -> tuple[Path, str]:
    path = TIER_C / "broken_encoding.txt"
    # Random bytes that don't decode as UTF-8 or latin-1 with text content.
    # latin-1 will accept anything, so we cause a different failure: empty doc
    # after decoding. We pick bytes that decode but produce only control chars.
    # To force EncodingError specifically, we construct bytes that fail latin-1
    # too — which is impossible (latin-1 is total). So we use an invalid UTF-8
    # sequence with binary-ish content; dispatch will reject it as not text
    # (contains \x00) and we'll see UnsupportedFormatError.
    path.write_bytes(b"\xff\xfe\xfd\xfc\x00\x01\x02\x03binary\x00garbage")
    return path, "UnsupportedFormatError"


def malformed_docx() -> tuple[Path, str]:
    path = TIER_C / "malformed.docx"
    # A zip file (correct magic) but missing word/document.xml
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("hello.txt", "this is not a docx")
    return path, "CorruptDocumentError"


def truncated_pdf() -> tuple[Path, str]:
    path = TIER_C / "truncated.pdf"
    # PDF magic but file truncated after header
    path.write_bytes(b"%PDF-1.4\n%binary garbage and stop")
    return path, "CorruptDocumentError"


def scanned_pdf_no_text_layer() -> tuple[Path, str]:
    """Minimal PDF with a single image-only page (no text operators).

    pdfplumber will read it but page.chars will be empty, triggering
    UnsupportedScannedPDFError.
    """
    path = TIER_C / "scanned.pdf"
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Resources << >> /Contents 4 0 R >> endobj\n"
        b"4 0 obj << /Length 0 >> stream\n\nendstream endobj\n"
        b"xref\n0 5\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000054 00000 n \n"
        b"0000000103 00000 n \n"
        b"0000000196 00000 n \n"
        b"trailer << /Size 5 /Root 1 0 R >>\n"
        b"startxref\n240\n%%EOF\n"
    )
    path.write_bytes(pdf)
    return path, "UnsupportedScannedPDFError"


def unsupported_format_html() -> tuple[Path, str]:
    path = TIER_C / "unsupported.html"
    path.write_bytes(b"<html><body>not a supported format</body></html>")
    return path, "UnsupportedFormatError"


def small_valid_txt() -> tuple[Path, str]:
    """A small but valid TXT — should parse cleanly, no error."""
    path = TIER_C / "small_valid.txt"
    path.write_text(
        "1.  Introduction\n"
        "\n"
        "    This is a paragraph.\n"
        "\n"
        "2.  Code Sample\n"
        "\n"
        "    foo = bar\n"
        "    baz = qux\n",
        encoding="utf-8",
    )
    return path, "OK"


def main() -> None:
    cases = [
        empty_txt(),
        whitespace_only_txt(),
        broken_encoding_txt(),
        malformed_docx(),
        truncated_pdf(),
        scanned_pdf_no_text_layer(),
        unsupported_format_html(),
        small_valid_txt(),
    ]
    print(f"Wrote {len(cases)} edge-case files to {TIER_C}:")
    manifest_lines = []
    for path, expected in cases:
        size = path.stat().st_size
        rel = path.relative_to(ROOT)
        print(f"  {rel}  ({size} bytes)  -> {expected}")
        manifest_lines.append(f"{path.name}\t{expected}")
    (TIER_C / "MANIFEST.tsv").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    print(f"\nManifest written: {TIER_C / 'MANIFEST.tsv'}")


if __name__ == "__main__":
    main()

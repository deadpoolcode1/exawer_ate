"""Format detection / dispatch tests."""
from pathlib import Path

import pytest

from ate.errors import UnsupportedFormatError
from ate.parsers.dispatch import detect_format


def test_detect_docx(corpus: Path) -> None:
    p = corpus / "tier_a" / "rfc9785.docx"
    assert detect_format(p) == "docx"


def test_detect_pdf(corpus: Path) -> None:
    p = corpus / "tier_a" / "rfc9785.pdf"
    assert detect_format(p) == "pdf"


def test_detect_txt(corpus: Path) -> None:
    p = corpus / "tier_a" / "rfc9785.txt"
    assert detect_format(p) == "txt"


def test_detect_empty_txt(corpus: Path) -> None:
    p = corpus / "tier_c" / "empty.txt"
    # Suffix is authoritative for .txt — content is dispatched, parser rejects.
    assert detect_format(p) == "txt"


def test_detect_html_rejected(corpus: Path) -> None:
    p = corpus / "tier_c" / "unsupported.html"
    with pytest.raises(UnsupportedFormatError):
        detect_format(p)


def test_detect_missing_file(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedFormatError):
        detect_format(tmp_path / "does_not_exist.txt")

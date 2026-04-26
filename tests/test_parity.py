"""Format parity: same content in 3 formats produces equivalent IRs (to a threshold)."""
import re
from pathlib import Path

from ate.parsers import parse

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "corpus"

PARITY_THRESHOLD = 0.90  # word-Jaccard, matches scorecard threshold


def _word_set(d) -> set[str]:
    parts = [d.full_text]
    parts.extend(c.text for c in d.code_blocks)
    text = " ".join(parts)
    return {w.lower() for w in re.findall(r"[A-Za-z]{3,}", text)}


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def test_rfc9785_word_parity_across_formats() -> None:
    """Word-level Jaccard ≥ 0.90 on RFC 9785 across DOCX/TXT/PDF."""
    base = CORPUS / "tier_a"
    sets = {fmt: _word_set(parse(base / f"rfc9785.{fmt}"))
            for fmt in ("docx", "txt", "pdf")}
    pairs = {
        "docx-txt": _jaccard(sets["docx"], sets["txt"]),
        "docx-pdf": _jaccard(sets["docx"], sets["pdf"]),
        "txt-pdf": _jaccard(sets["txt"], sets["pdf"]),
    }
    failures = {k: v for k, v in pairs.items() if v < PARITY_THRESHOLD}
    assert not failures, f"format parity below {PARITY_THRESHOLD}: {pairs}"

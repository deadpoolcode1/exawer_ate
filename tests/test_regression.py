"""Regression: parser output must not drift from committed golden IR.

Goldens live in tests/golden/ir/<doc>.json and are written by
scripts/build_goldens.py. When the parser changes, this test will fail
until either:
  (a) the change is reverted, or
  (b) the golden is regenerated AND the diff has been reviewed.

Running `python scripts/build_goldens.py diff` shows what would change.
Running `python scripts/build_goldens.py build` overwrites goldens.
"""
import json
from pathlib import Path

import pytest

from ate.normalize import normalize
from ate.parsers import parse

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "corpus"
GOLDEN_IR = ROOT / "tests" / "golden" / "ir"

TRACKED = [
    "tier_a/rfc9785.docx",
    "tier_a/rfc9785.txt",
    "tier_a/rfc9785.pdf",
    "tier_a/EVPN System Specification 1.00.docx",
    "tier_a/EVPN CLI 1.00.docx",
    "tier_b/rfc7432bis-13.docx",
    "tier_b/rfc7432bis-13.txt",
]


def _golden_path(rel: str) -> Path:
    safe = rel.replace("/", "__").replace(" ", "_") + ".json"
    return GOLDEN_IR / safe


@pytest.mark.parametrize("rel", TRACKED)
def test_normalized_ir_matches_golden(rel: str) -> None:
    src = CORPUS / rel
    if not src.exists():
        pytest.skip(f"corpus file missing: {rel}")
    golden = _golden_path(rel)
    if not golden.exists():
        pytest.fail(
            f"missing golden for {rel}: run `python scripts/build_goldens.py build`"
        )
    expected = json.loads(golden.read_text())
    actual = normalize(parse(src))
    assert actual == expected, (
        f"normalized IR drift for {rel}; "
        f"run `python scripts/build_goldens.py diff` to inspect, "
        f"then `... build` to accept after review"
    )

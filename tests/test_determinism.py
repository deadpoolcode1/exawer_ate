"""Parsing must be deterministic — three runs produce byte-identical IR."""
import hashlib
from pathlib import Path

import pytest

from ate.parsers import parse

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "corpus"


@pytest.mark.parametrize("rel", [
    "tier_a/EVPN System Specification 1.00.docx",
    "tier_a/EVPN CLI 1.00.docx",
    "tier_a/rfc9785.docx",
    "tier_a/rfc9785.txt",
    "tier_a/rfc9785.pdf",
    "tier_b/rfc7432bis-13.docx",
    "tier_b/rfc7432bis-13.txt",
])
def test_three_runs_byte_identical(rel: str) -> None:
    p = CORPUS / rel
    if not p.exists():
        pytest.skip(f"missing: {rel}")
    hashes = []
    for _ in range(3):
        d = parse(p)
        h = hashlib.sha256(d.model_dump_json().encode("utf-8")).hexdigest()
        hashes.append(h)
    assert len(set(hashes)) == 1, (
        f"non-deterministic parse for {rel}: hashes={hashes}"
    )

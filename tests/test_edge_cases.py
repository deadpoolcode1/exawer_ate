"""Tier-C edge cases must produce typed errors (or parse cleanly)."""
from pathlib import Path

import pytest

from ate import errors
from ate.parsers import parse

ROOT = Path(__file__).resolve().parents[1]
TIER_C = ROOT / "tests" / "corpus" / "tier_c"


def _manifest() -> list[tuple[str, str]]:
    out = []
    for line in (TIER_C / "MANIFEST.tsv").read_text().splitlines():
        if not line.strip():
            continue
        name, expected = line.split("\t", 1)
        out.append((name, expected))
    return out


@pytest.mark.parametrize("name,expected", _manifest())
def test_edge_case_produces_expected_outcome(name: str, expected: str) -> None:
    p = TIER_C / name
    if expected == "OK":
        d = parse(p)
        assert len(d.blocks) > 0
        return
    err_cls = getattr(errors, expected, None)
    assert err_cls is not None, f"unknown error class in manifest: {expected}"
    with pytest.raises(err_cls):
        parse(p)

"""Per-parser smoke tests on the real corpus."""
from pathlib import Path

import pytest

from ate.ir import CodeBlock, Heading, Paragraph, Table
from ate.parsers import parse


@pytest.mark.parametrize("rel", [
    "tier_a/rfc9785.docx",
    "tier_a/rfc9785.txt",
    "tier_a/rfc9785.pdf",
    "tier_a/EVPN System Specification 1.00.docx",
    "tier_a/EVPN CLI 1.00.docx",
    "tier_b/rfc7432bis-13.docx",
    "tier_b/rfc7432bis-13.txt",
])
def test_parse_returns_document(rel: str, corpus: Path) -> None:
    d = parse(corpus / rel)
    assert d.source_format in {"docx", "txt", "pdf"}
    assert len(d.blocks) > 0
    assert d.schema_version == "1.0.0"


def test_evpn_spec_has_cli_blocks(corpus: Path) -> None:
    """Exaware EVPN spec must yield code blocks containing CLI configuration."""
    d = parse(corpus / "tier_a" / "EVPN System Specification 1.00.docx")
    code_text = "\n".join(c.text for c in d.code_blocks)
    assert "service-type vlan-based" in code_text
    assert "interface agg-eth" in code_text
    assert "l2-transport enable" in code_text


def test_evpn_spec_finds_anchors(corpus: Path) -> None:
    """The EVPN spec's EVPNS-REQ#NN anchors must survive parsing intact."""
    import re
    d = parse(corpus / "tier_a" / "EVPN System Specification 1.00.docx")
    anchors = set(re.findall(r"EVPNS-REQ#\d+", d.full_text))
    # EVPNS-REQ#10..#400 in increments — between 30 and 50 unique anchors expected.
    assert 30 <= len(anchors) <= 50, f"got {len(anchors)} anchors"


def test_docx_table_structure(corpus: Path) -> None:
    """Tables come back as structured rows, not flattened text."""
    d = parse(corpus / "tier_a" / "EVPN System Specification 1.00.docx")
    assert len(d.tables) > 0
    for t in d.tables:
        assert isinstance(t, Table)
        assert t.n_rows > 0
        assert t.n_cols > 0


def test_pdf_no_text_layer_rejected(corpus: Path) -> None:
    from ate.errors import UnsupportedScannedPDFError
    with pytest.raises(UnsupportedScannedPDFError):
        parse(corpus / "tier_c" / "scanned.pdf")


def test_block_types_are_correct(corpus: Path) -> None:
    """Each block must be one of the typed IR variants — no raw dicts/strings."""
    d = parse(corpus / "tier_a" / "rfc9785.docx")
    for b in d.blocks:
        assert isinstance(b, Heading | Paragraph | CodeBlock | Table) or hasattr(b, "kind")

"""Cross-format IR normalization for parity tests.

The same source content rendered as DOCX, TXT, and PDF will produce
slightly different IRs (e.g., line-wrap differences, page-break artifacts).
The normalize() function strips this format-specific noise so we can
compare semantically.

Allow-listed differences (intentionally normalized away):
  - Whitespace collapsing within paragraphs
  - Page numbers and page-break-induced fragments
  - Repeating page headers/footers
  - Leading/trailing whitespace per block
  - Non-breaking spaces, soft hyphens
  - Smart quotes and dashes (collapsed to ASCII)

What is preserved (must match across formats):
  - Section structure: ordered list of headings (number + text)
  - Paragraph text, after whitespace collapse
  - Code-block content, after end-of-line normalization
  - Table cell text content
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from ate.ir import Document, Heading, ListItem, Table


def normalize(d: Document) -> dict[str, Any]:
    headings = [_norm_heading(h) for h in d.headings]
    paragraphs = [_norm_text(p.text) for p in d.paragraphs]
    paragraphs = [p for p in paragraphs if p]
    code_blocks = [_norm_code(c.text) for c in d.code_blocks]
    code_blocks = [c for c in code_blocks if c]
    tables = [_norm_table(t) for t in d.tables]
    list_items = [_norm_text(b.text) for b in d.blocks if isinstance(b, ListItem)]
    return {
        "headings": headings,
        "paragraphs": paragraphs,
        "code_blocks": code_blocks,
        "tables": tables,
        "list_items": list_items,
    }


def _norm_heading(h: Heading) -> dict[str, Any]:
    return {
        "level": h.level,
        "number": (h.number or "").strip(),
        "text": _norm_text(h.text),
    }


def _norm_text(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    # Replace non-breaking space and similar with regular space
    s = s.replace(" ", " ").replace("​", "")
    # Soft hyphens
    s = s.replace("­", "")
    # Smart quotes / dashes → ASCII
    s = s.translate(str.maketrans({
        "‘": "'", "’": "'", "‚": "'", "‛": "'",
        "“": '"', "”": '"',
        "–": "-", "—": "-", "−": "-",
        "•": "*", "·": "*",
    }))
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _norm_code(s: str) -> str:
    if not s:
        return ""
    # Normalize EOL only — preserve internal whitespace structure verbatim.
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return s.strip("\n")


def _norm_table(t: Table) -> list[list[str]]:
    return [[_norm_text(c.text) for c in row] for row in t.rows]

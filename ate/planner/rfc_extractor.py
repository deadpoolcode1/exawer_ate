"""Extract normative requirements (MUST/SHALL/REQUIRED clauses) from an
IETF RFC text file.

RFCs use a stable plaintext layout: section headings start at column 1
with the form `N[.N]*.  Title`, body paragraphs are indented 3 spaces,
and page breaks repeat author/title/page banners every ~58 lines.

Each RFC section that contains at least one MUST/SHALL/REQUIRED sentence
becomes a Requirement with `req_id = "<short>-§<section>"` (e.g.
`RFC7432bis-§7.2.1`). These slot into the same plan generator the spec
requirements use, so RFC-derived rows appear alongside spec rows in the
xlsx — addressing the M1 review ask to "refer to RFC requirements too".
"""
from __future__ import annotations

import re
from pathlib import Path

from ate.planner.extractor import MUST_RE, _compute_tags
from ate.planner.model import Requirement

# Body section heading: starts at column 1, number + ". " + title.
# RFC text has at least 2 spaces between the trailing dot and the title.
SECTION_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)*)\.\s\s+(\S.*?)\s*$")

# Boilerplate / structural section titles to skip. The BCP14 "Requirements
# Language" section will always match MUST_RE because it quotes the keywords
# verbatim — that's not a testable requirement, so drop it. Same for IANA
# considerations, Security considerations, Terminology, References, etc.
#
# We also skip narrative-only sections that describe what the document is
# *about* but don't impose a behavior the implementation must satisfy:
# Problem Statement, Use Cases, Solution Overview. These typically quote
# MUST/SHALL keywords incidentally (e.g. "the operator MUST be able to…")
# but are not verifiable test targets — they belong in the design rationale,
# not the test plan.
_BOILERPLATE_TITLES = {
    "requirements language",
    "requirements language and terminology",
    "terminology",
    "introduction",
    "iana considerations",
    "security considerations",
    "acknowledgments",
    "acknowledgements",
    "contributors",
    "references",
    "normative references",
    "informative references",
    "authors' addresses",
    "abstract",
    "status of this memo",
    "copyright notice",
    # Narrative / scoping sections — present in modern IETF RFCs.
    "problem statement",
    "solution requirements",
    "solution overview",
    "background",
    "motivation",
    "use cases",
    "use case",
    "conventions",
    "conventions used in this document",
}

# Page banner / running header lines we strip before parsing.
PAGE_FOOTER_RE = re.compile(r"\[Page\s+\d+\]")
RFC_RUNNING_HEADER_RE = re.compile(
    r"^(Internet-Draft|Request for Comments:|RFC\s+\d+)\b"
)


def _short_name(rfc_path: Path) -> str:
    """Map filename → short reference label used in req_id and rfc_refs.

    `rfc9785.txt` → `RFC9785`
    `draft-ietf-bess-rfc7432bis-13.txt` → `RFC7432bis`
    """
    stem = rfc_path.stem.lower()
    m = re.search(r"rfc(\d+\w*?)(?:-\d+)?$", stem)
    if m:
        return f"RFC{m.group(1)}"
    m = re.search(r"rfc(\d+\w*)", stem)
    if m:
        return f"RFC{m.group(1)}"
    return rfc_path.stem


def _strip_page_breaks(text: str) -> str:
    """Drop RFC page footers and running headers so paragraphs reflow cleanly.

    A typical page break is ~10 lines: blanks, footer ("Sajassi ... [Page 4]"),
    blank, header ("Internet-Draft ... June 2025"), blanks. We drop any line
    containing [Page N] or matching the running-header prefix; remaining blanks
    collapse during paragraph join.
    """
    out = []
    for line in text.splitlines():
        if PAGE_FOOTER_RE.search(line):
            continue
        if RFC_RUNNING_HEADER_RE.match(line):
            continue
        out.append(line)
    return "\n".join(out)


def _split_sections(text: str) -> list[tuple[str, str, str]]:
    """Walk lines and yield (section_number, title, body) tuples.

    Body is the verbatim text between this heading and the next.
    """
    cleaned = _strip_page_breaks(text)
    lines = cleaned.splitlines()

    sections: list[tuple[str, str, list[str]]] = []
    current: tuple[str, str, list[str]] | None = None
    for line in lines:
        m = SECTION_RE.match(line)
        if m:
            if current is not None:
                sections.append(current)
            current = (m.group(1), m.group(2).strip(), [])
            continue
        if current is not None:
            current[2].append(line)
    if current is not None:
        sections.append(current)
    return [(num, title, "\n".join(body)) for num, title, body in sections]


def _has_subsection(section_num: str, all_nums: set[str]) -> bool:
    """True if any other section in the RFC starts with `<section_num>.`.

    Such sections are umbrella chapters whose own body is typically a short
    intro before the real normative content begins in the children. Emitting
    a row for the parent and rows for each child would mean the same MUST
    statement gets tested twice under different labels.
    """
    prefix = section_num + "."
    return any(n != section_num and n.startswith(prefix) for n in all_nums)


def extract_rfc_requirements(rfc_path: str | Path) -> list[Requirement]:
    """Return one Requirement per RFC leaf section with a normative clause.

    Skipped:
      - Sections whose title is in `_BOILERPLATE_TITLES` (Problem Statement,
        Requirements Language, IANA Considerations, etc.).
      - Sections that have child subsections — emit only leaves so each
        normative clause is tested in exactly one row.
      - Sections without any MUST/SHALL/REQUIRED sentence in their body.
    """
    rfc_path = Path(rfc_path)
    text = rfc_path.read_text(encoding="utf-8", errors="replace")
    short = _short_name(rfc_path)

    sections = _split_sections(text)
    all_nums = {num for num, _t, _b in sections}

    out: list[Requirement] = []
    seen: set[str] = set()
    for section_num, title, body in sections:
        if title.strip().lower() in _BOILERPLATE_TITLES:
            continue
        if _has_subsection(section_num, all_nums):
            continue
        body_flat = re.sub(r"\s+", " ", body).strip()
        if not body_flat:
            continue
        normative = [m.group(0).strip() for m in MUST_RE.finditer(body_flat)]
        if not normative:
            continue
        req_id = f"{short}-§{section_num}"
        if req_id in seen:
            continue
        seen.add(req_id)

        tags = _compute_tags(title, body_flat)
        if not tags:
            tags = {"PROTOCOL"}

        out.append(Requirement(
            req_id=req_id,
            title=title,
            section_number=section_num,
            description=body_flat[:1000],
            must_statements=normative[:3],
            rfc_refs=[f"{short} ch.{section_num}"],
            tags=sorted(tags),
            source="rfc",
        ))
    return out

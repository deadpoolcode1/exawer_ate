"""PDF parser via pdfplumber.

Strategy:
  - Extract per-page text with layout preserved.
  - Detect tables with pdfplumber.find_tables() (lattice + stream heuristics).
  - Detect code blocks by font name (monospace) on extracted chars.
  - Heading detection: numbered "1.2.3 Title" pattern + larger-than-body
    font size on the heading line.
  - Strip page headers/footers heuristically (lines that repeat across pages
    in the same vertical band).
  - Empty text layer → UnsupportedScannedPDFError (no OCR in M1).
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pdfplumber

from ate.errors import (
    CorruptDocumentError,
    EmptyDocumentError,
    PasswordProtectedError,
    UnsupportedScannedPDFError,
)
from ate.ir import (
    Block,
    CodeBlock,
    Document,
    Heading,
    Paragraph,
    Table,
    TableCell,
)

MONO_FONT_SUBSTRINGS = (
    "courier",
    "consolas",
    "mono",
    "menlo",
    "monaco",
    "sourcecodepro",
)

HEADING_NUMBER_RE = re.compile(r"^\s*(\d+(?:\.\d+){0,7})\s+(\S.+)$")


def parse_pdf(path: Path) -> Document:
    try:
        pdf = pdfplumber.open(str(path))
    except Exception as e:
        msg = str(e).lower()
        if "encrypted" in msg or "password" in msg:
            raise PasswordProtectedError(f"{path}: {e}") from e
        raise CorruptDocumentError(f"{path}: {e}") from e

    blocks: list[Block] = []

    with pdf:
        if not pdf.pages:
            raise EmptyDocumentError(f"{path}: no pages")

        # Detect scanned PDF (no text layer at all)
        sample_chars = sum(len(p.chars or []) for p in pdf.pages[:5])
        if sample_chars == 0:
            raise UnsupportedScannedPDFError(
                f"{path}: PDF has no text layer (likely scanned). "
                "OCR is out of M1 scope."
            )

        # Compute body font size as the most common rounded size of all chars
        # — anything larger is a candidate heading.
        size_counter: Counter[int] = Counter()
        for page in pdf.pages:
            for ch in page.chars or []:
                size_counter[round(ch.get("size", 0))] += 1
        body_size = max(size_counter, key=size_counter.get) if size_counter else 10

        # Detect repeating header/footer lines
        repeated_lines = _detect_repeating_lines(pdf)

        # Detect tables across pages
        tables_by_page: dict[int, list] = {}
        for i, page in enumerate(pdf.pages):
            try:
                tables_by_page[i] = page.find_tables() or []
            except Exception:
                tables_by_page[i] = []

        pending_code: list[str] = []
        pending_para: list[str] = []

        def flush_code() -> None:
            nonlocal pending_code
            if pending_code:
                text = "\n".join(pending_code).rstrip("\n")
                if text.strip():
                    blocks.append(CodeBlock(text=text))
                pending_code = []

        def flush_para() -> None:
            nonlocal pending_para
            if pending_para:
                text = " ".join(pending_para).strip()
                if text:
                    blocks.append(Paragraph(text=text))
                pending_para = []

        for page_idx, page in enumerate(pdf.pages):
            page_tables = tables_by_page.get(page_idx, [])
            table_bboxes = [t.bbox for t in page_tables]

            # Extract lines with their bboxes via extract_text_lines if available.
            text_lines = _extract_lines_with_meta(page, body_size)

            for line in text_lines:
                line_text = line["text"]
                line_bbox = line["bbox"]
                if not line_text.strip():
                    flush_para()
                    if pending_code:
                        pending_code.append("")
                    continue

                # Skip repeating headers/footers
                if line_text.strip() in repeated_lines:
                    continue

                # Skip page numbers (just a number)
                if re.fullmatch(r"\s*\d{1,4}\s*", line_text):
                    continue

                # Skip lines inside table bboxes — they'll be emitted as the
                # Table block, separately.
                if _bbox_overlaps_any(line_bbox, table_bboxes):
                    continue

                if line["mono"]:
                    flush_para()
                    pending_code.append(line_text.rstrip())
                    continue

                # Heading?
                if line["heading_candidate"] and line["size"] > body_size + 0.5:
                    flush_code()
                    flush_para()
                    blocks.append(_heading_from_text(line_text, line["size"], body_size))
                    continue

                m = HEADING_NUMBER_RE.match(line_text)
                if (
                    m
                    and len(line_text) < 120
                    and not line_text.endswith(".")
                    and line["size"] >= body_size
                ):
                    flush_code()
                    flush_para()
                    depth = m.group(1).count(".") + 1
                    blocks.append(Heading(level=min(depth, 9), text=m.group(2).strip(),
                                          number=m.group(1)))
                    continue

                # Regular paragraph line — accumulate, hoping line-wrap re-joins
                flush_code()
                pending_para.append(line_text.strip())

            # Flush at page boundary
            flush_code()
            flush_para()

            # Emit tables for this page
            for t in page_tables:
                rows_raw = t.extract() or []
                if not rows_raw:
                    continue
                rows: list[list[TableCell]] = []
                for r in rows_raw:
                    rows.append([TableCell(text=(c or "").strip()) for c in r])
                blocks.append(Table(rows=rows))

    if not blocks:
        raise EmptyDocumentError(f"{path}: no extractable content")

    return Document(
        source_path=str(path),
        source_format="pdf",
        blocks=blocks,
        metadata={},
    )


def _extract_lines_with_meta(page, body_size: int) -> list[dict]:
    """Group page chars into visual lines with metadata."""
    chars = page.chars or []
    if not chars:
        return []
    # Bucket by rounded y-top (PDF coords increase downward via top)
    buckets: dict[int, list] = {}
    for ch in chars:
        key = round(ch["top"])
        buckets.setdefault(key, []).append(ch)

    lines: list[dict] = []
    for key in sorted(buckets):
        chs = sorted(buckets[key], key=lambda c: c["x0"])
        text = "".join(c["text"] for c in chs)
        font_names = [c.get("fontname", "") for c in chs]
        sizes = [c.get("size", body_size) for c in chs]
        avg_size = sum(sizes) / len(sizes)
        mono_share = sum(
            1 for fn in font_names
            if any(s in fn.lower() for s in MONO_FONT_SUBSTRINGS)
        ) / max(len(font_names), 1)
        x0 = min(c["x0"] for c in chs)
        x1 = max(c["x1"] for c in chs)
        top = min(c["top"] for c in chs)
        bottom = max(c["bottom"] for c in chs)
        lines.append({
            "text": text,
            "size": avg_size,
            "mono": mono_share > 0.5,
            "heading_candidate": avg_size > body_size,
            "bbox": (x0, top, x1, bottom),
        })
    return lines


def _bbox_overlaps_any(bbox, bboxes) -> bool:
    x0, t0, x1, b0 = bbox
    for bx0, bt0, bx1, bb0 in bboxes:
        if x0 < bx1 and x1 > bx0 and t0 < bb0 and b0 > bt0:
            return True
    return False


def _heading_from_text(text: str, size: float, body_size: int) -> Heading:
    text = text.strip()
    m = HEADING_NUMBER_RE.match(text)
    # Approximate level from size delta: each +1 unit ≈ one level shallower
    delta = max(0, size - body_size)
    if delta >= 6:
        level = 1
    elif delta >= 4:
        level = 2
    elif delta >= 2:
        level = 3
    else:
        level = 4
    if m:
        depth = m.group(1).count(".") + 1
        return Heading(level=min(depth, 9), text=m.group(2).strip(), number=m.group(1))
    return Heading(level=level, text=text)


def _detect_repeating_lines(pdf) -> set[str]:
    """Lines that appear in roughly the same vertical band on >50% of pages."""
    if len(pdf.pages) < 3:
        return set()
    counter: Counter[str] = Counter()
    for page in pdf.pages:
        seen_on_page: set[str] = set()
        for line in (page.extract_text() or "").splitlines():
            line = line.strip()
            if not line or len(line) > 200:
                continue
            seen_on_page.add(line)
        for line in seen_on_page:
            counter[line] += 1
    threshold = max(3, len(pdf.pages) // 2)
    return {line for line, n in counter.items() if n >= threshold}

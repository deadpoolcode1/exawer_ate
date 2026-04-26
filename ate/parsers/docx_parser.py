"""DOCX parser via python-docx.

Strategy:
  - Iterate body elements in document order (paragraphs + tables together,
    using underlying XML so we don't lose ordering).
  - Heading detection: prefer Word style ("Heading 1".."Heading 9").
    Fallback: numbered prefix like "2.3.1 Title".
  - Code blocks: contiguous runs of paragraphs styled with monospace fonts
    (Consolas, Courier, Courier New, Source Code Pro, Menlo, Monaco) OR
    paragraphs whose lines start with leading whitespace and contain
    CLI-shape tokens (e.g., trailing "!", "exaware#", "(config)#").
  - Tables: emit as Table with rowspan/colspan from grid spans.
"""
from __future__ import annotations

import re
from pathlib import Path

import docx
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph

from ate.errors import CorruptDocumentError, EmptyDocumentError, PasswordProtectedError
from ate.ir import (
    Block,
    CodeBlock,
    Document,
    Heading,
    ListItem,
    Paragraph,
    Table,
    TableCell,
)

MONO_FONTS = {
    "consolas",
    "courier",
    "courier new",
    "source code pro",
    "menlo",
    "monaco",
    "lucida console",
    "dejavu sans mono",
}

HEADING_NUMBER_RE = re.compile(r"^\s*(\d+(?:\.\d+){0,7})\s+(.+)$")

# Lines that look like CLI / config session content.
CLI_HINTS = (
    re.compile(r"^\s*exaware[#>(]"),
    re.compile(r"^\s*[a-zA-Z][\w\-]*\([^)]*\)#"),
    re.compile(r"^\s*!\s*$"),
    re.compile(r"^\s*config\s*$"),
)


def parse_docx(path: Path) -> Document:
    try:
        d: DocxDocument = docx.Document(str(path))
    except Exception as e:  # pragma: no cover - depends on python-docx internals
        msg = str(e).lower()
        if "encrypted" in msg or "password" in msg:
            raise PasswordProtectedError(f"{path}: {e}") from e
        raise CorruptDocumentError(f"{path}: {e}") from e

    blocks: list[Block] = []

    # Iterate body in order, getting Paragraph and Table objects with proper parents.
    items = list(d.iter_inner_content())

    pending_code: list[str] = []

    def flush_code() -> None:
        nonlocal pending_code
        if pending_code:
            text = "\n".join(pending_code).rstrip("\n")
            if text.strip():
                blocks.append(CodeBlock(text=text))
            pending_code = []

    for item in items:
        if isinstance(item, DocxTable):
            flush_code()
            blocks.append(_table_to_ir(item))
            continue
        # paragraph
        para: DocxParagraph = item  # type: ignore[assignment]
        text = para.text
        if not text.strip():
            # Blank line — keep code-block runs alive across blanks
            if pending_code:
                pending_code.append("")
            continue

        if _is_code_paragraph(para):
            pending_code.append(text)
            continue

        flush_code()

        h = _heading_from_para(para)
        if h is not None:
            blocks.append(h)
            continue

        if _is_list_item(para):
            blocks.append(ListItem(text=text.strip(), level=_list_level(para)))
            continue

        blocks.append(Paragraph(text=text.strip()))

    flush_code()

    if not blocks:
        raise EmptyDocumentError(f"{path}: no extractable content")

    return Document(
        source_path=str(path),
        source_format="docx",
        blocks=blocks,
        metadata={"core_title": d.core_properties.title or ""},
    )


def _heading_from_para(para: DocxParagraph) -> Heading | None:
    style = (para.style.name if para.style else "") or ""
    text = para.text.strip()
    if not text:
        return None
    # Reject Table-of-Contents entries — they share heading text with the
    # real headings but are styled "TOC 1".."TOC 9". Counting them inflates
    # heading recovery and produces duplicate sections.
    if style.lower().startswith("toc "):
        return None
    if style.startswith("Heading "):
        try:
            level = int(style.split(" ", 1)[1])
            level = max(1, min(9, level))
        except ValueError:
            level = 1
        m = HEADING_NUMBER_RE.match(text)
        if m:
            return Heading(level=level, text=m.group(2).strip(), number=m.group(1))
        return Heading(level=level, text=text)
    if style in {"Title"}:
        return Heading(level=1, text=text)
    # Fallback heuristic: numbered top-line style "1.2.3 Foo" with no other
    # styling — only treat as heading if reasonably short to avoid false positives.
    m = HEADING_NUMBER_RE.match(text)
    if m and len(text) < 120 and not text.endswith("."):
        depth = m.group(1).count(".") + 1
        return Heading(level=min(depth, 9), text=m.group(2).strip(), number=m.group(1))
    return None


def _is_code_paragraph(para: DocxParagraph) -> bool:
    text = para.text
    if not text:
        return False
    # 1. style name
    style = (para.style.name if para.style else "") or ""
    if "code" in style.lower() or "preformatted" in style.lower():
        return True
    # 2. font of any run
    for run in para.runs:
        font_name = (run.font.name or "").lower()
        if font_name in MONO_FONTS:
            return True
        rpr = run.element.find(qn("w:rPr"))
        if rpr is not None:
            r_fonts = rpr.find(qn("w:rFonts"))
            if r_fonts is not None:
                ascii_font = (r_fonts.get(qn("w:ascii")) or "").lower()
                if ascii_font in MONO_FONTS:
                    return True
    # 3. content shape (CLI hints)
    for pat in CLI_HINTS:
        if pat.search(text):
            return True
    return False


def _is_list_item(para: DocxParagraph) -> bool:
    pPr = para._p.find(qn("w:pPr"))
    if pPr is None:
        return False
    return pPr.find(qn("w:numPr")) is not None


def _list_level(para: DocxParagraph) -> int:
    pPr = para._p.find(qn("w:pPr"))
    if pPr is None:
        return 1
    numPr = pPr.find(qn("w:numPr"))
    if numPr is None:
        return 1
    ilvl = numPr.find(qn("w:ilvl"))
    if ilvl is None:
        return 1
    val = ilvl.get(qn("w:val"))
    try:
        return int(val) + 1 if val is not None else 1
    except ValueError:
        return 1


def _table_to_ir(t: DocxTable) -> Table:
    """Walk the underlying <w:tbl> XML directly.

    Avoids python-docx's r.cells, which repeats merged cells across grid
    positions and forces dedup by id() — non-deterministic between runs.
    Each <w:tc> in document order is exactly one cell.
    """
    rows: list[list[TableCell]] = []
    tbl = t._tbl
    for tr in tbl.findall(qn("w:tr")):
        out_row: list[TableCell] = []
        for tc in tr.findall(qn("w:tc")):
            out_row.append(_tc_to_ir(tc))
        if out_row:
            rows.append(out_row)
    return Table(rows=rows)


def _tc_to_ir(tc) -> TableCell:
    # Concatenate all text in cell-level paragraphs in document order.
    parts: list[str] = []
    for p in tc.findall(qn("w:p")):
        runs = []
        for t in p.iter(qn("w:t")):
            runs.append(t.text or "")
        if runs:
            parts.append("".join(runs))
    text = "\n".join(parts).strip()

    colspan = 1
    rowspan = 1
    tcPr = tc.find(qn("w:tcPr"))
    if tcPr is not None:
        gs = tcPr.find(qn("w:gridSpan"))
        if gs is not None:
            try:
                colspan = int(gs.get(qn("w:val")) or 1)
            except ValueError:
                pass
        # vMerge spans require walking rows downward; we record rowspan=1
        # in M1 and defer accurate row-merge accounting to M2 if needed.
    return TableCell(text=text, rowspan=rowspan, colspan=colspan)

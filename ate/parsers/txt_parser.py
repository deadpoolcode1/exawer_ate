"""Plain-text parser.

Strategy:
  - Decode as UTF-8 (BOM-aware), fall back to latin-1.
  - Heading detection in this priority order:
      1. RFC-style numbered headings ("2.3.1.  Title" or "2.3.1 Title")
         where the line contains no trailing punctuation typical of body text.
      2. Setext-style underline ("====" or "----" under a title line).
      3. Markdown-style "## Title" with hashes.
      4. ALL-CAPS short lines (≥3 words, ≤80 chars).
  - Code blocks: contiguous indented runs (≥4 spaces) OR fenced ```...```.
  - Tables: not parsed in M1 for plain text — RFCs use ASCII art that
    requires custom heuristics; deferred.
"""
from __future__ import annotations

import re
from pathlib import Path

from ate.errors import EmptyDocumentError, EncodingError
from ate.ir import Block, CodeBlock, Document, Heading, ListItem, Paragraph

RFC_HEADING_RE = re.compile(r"^(\d+(?:\.\d+){0,7})\.?\s+(\S.+)$")
MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(\S.+)$")
LIST_ITEM_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+(\S.*)$")
ALLCAPS_RE = re.compile(r"^[A-Z][A-Z0-9 \-:_/]{2,79}$")


def parse_txt(path: Path) -> Document:
    raw = path.read_bytes()
    if not raw:
        raise EmptyDocumentError(f"{path}: file is empty")

    text: str | None = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise EncodingError(f"{path}: cannot decode bytes as utf-8 or latin-1")

    lines = text.splitlines()
    if not any(line.strip() for line in lines):
        raise EmptyDocumentError(f"{path}: only whitespace")

    blocks: list[Block] = []
    pending_code: list[str] = []
    pending_para: list[str] = []
    in_fenced_code = False

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
            t = " ".join(pending_para).strip()
            if t:
                blocks.append(Paragraph(text=t))
            pending_para = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Fenced code block
        if stripped.startswith("```"):
            if in_fenced_code:
                flush_code()
                in_fenced_code = False
            else:
                flush_para()
                in_fenced_code = True
            i += 1
            continue
        if in_fenced_code:
            pending_code.append(line)
            i += 1
            continue

        # Blank line
        if not stripped:
            flush_para()
            if pending_code:
                pending_code.append("")
            i += 1
            continue

        # Setext heading: a non-blank line followed by ===/--- of similar length
        if i + 1 < len(lines):
            next_line = lines[i + 1].rstrip()
            if (
                next_line
                and len(next_line) >= 3
                and (set(next_line) == {"="} or set(next_line) == {"-"})
                and len(stripped) <= len(next_line) + 4
            ):
                flush_code()
                flush_para()
                level = 1 if "=" in next_line else 2
                blocks.append(Heading(level=level, text=stripped))
                i += 2
                continue

        # Markdown heading
        m = MD_HEADING_RE.match(stripped)
        if m:
            flush_code()
            flush_para()
            blocks.append(Heading(level=len(m.group(1)), text=m.group(2).strip()))
            i += 1
            continue

        # RFC numbered heading — must be left-aligned (no leading space)
        if not line.startswith(" ") and not line.startswith("\t"):
            m = RFC_HEADING_RE.match(line)
            if (
                m
                and len(stripped) < 120
                and not stripped.endswith(".")
                and not stripped.endswith(",")
            ):
                flush_code()
                flush_para()
                depth = m.group(1).count(".") + 1
                blocks.append(Heading(level=min(depth, 9),
                                       text=m.group(2).strip(),
                                       number=m.group(1)))
                i += 1
                continue

        # ALL-CAPS heading (RFC-style major sections)
        if (
            not line.startswith(" ")
            and not line.startswith("\t")
            and ALLCAPS_RE.match(stripped)
            and len(stripped.split()) >= 2
        ):
            flush_code()
            flush_para()
            blocks.append(Heading(level=1, text=stripped))
            i += 1
            continue

        # Indented code block (4+ spaces leading)
        if line.startswith("    ") or line.startswith("\t"):
            flush_para()
            pending_code.append(line.rstrip())
            i += 1
            continue

        # List item
        m = LIST_ITEM_RE.match(line)
        if m:
            flush_code()
            flush_para()
            blocks.append(ListItem(text=m.group(2).strip()))
            i += 1
            continue

        # Body paragraph line
        flush_code()
        pending_para.append(stripped)
        i += 1

    flush_code()
    flush_para()

    if not blocks:
        raise EmptyDocumentError(f"{path}: no extractable content after parse")

    return Document(
        source_path=str(path),
        source_format="txt",
        blocks=blocks,
        metadata={},
    )

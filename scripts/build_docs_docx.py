#!/usr/bin/env python3
"""Build .docx versions of docs/*.md for client delivery.

Replaces the two ASCII schematics in docs/TDD.md with rendered Graphviz PNGs
(pre-built in docs/diagrams/), then runs pandoc to produce .docx in docs/word/.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pypandoc

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DIAGRAMS = DOCS / "diagrams"
OUT = DOCS / "word"

# Markdown sources to convert. TDD has ASCII schematics that get swapped for images.
SOURCES = [
    DOCS / "TDD.md",
    DOCS / "M1_acceptance.md",
    DOCS / "exaware-acceptance.md",
]

# Signature substrings that uniquely identify each ASCII schematic in TDD.md.
# Pandoc fenced-block replacements are content-based so the script is resilient
# to surrounding edits.
TDD_PATCHES = [
    # Pipeline (Executive summary §1)
    {
        "signature": "PDF/DOCX/TXT  →  parser",
        "replacement": (
            "![Figure 1 — End-to-end pipeline (M1).]"
            "(diagrams/pipeline.png){width=6.5in}\n"
        ),
    },
    # Architecture (§2)
    {
        "signature": "ate.parsers",
        "replacement": (
            "![Figure 2 — ATE component architecture. Inputs flow through "
            "the parser dispatcher into a single Pydantic IR; the planner "
            "branch (extractor → generator → AI enricher → "
            "xlsx writer) produces the M1 deliverable.]"
            "(diagrams/architecture.png){width=5.0in}\n"
        ),
    },
]

FENCED_BLOCK = re.compile(r"```[^\n]*\n(.*?)\n```", re.DOTALL)


def patch_tdd(md: str) -> str:
    """Swap the two ASCII schematics in TDD.md for image refs."""
    def replace_block(match: re.Match) -> str:
        body = match.group(1)
        for patch in TDD_PATCHES:
            if patch["signature"] in body:
                return patch["replacement"]
        return match.group(0)

    patched = FENCED_BLOCK.sub(replace_block, md)
    # Sanity: every patch must have fired exactly once.
    for patch in TDD_PATCHES:
        if patch["replacement"] not in patched:
            raise SystemExit(
                f"build_docs_docx: failed to match ASCII block with signature "
                f"{patch['signature']!r} in TDD.md"
            )
    return patched


def convert(src: Path, out_dir: Path) -> Path:
    md = src.read_text(encoding="utf-8")
    if src.name == "TDD.md":
        md = patch_tdd(md)

    with tempfile.NamedTemporaryFile(
        suffix=".md", dir=src.parent, delete=False, mode="w", encoding="utf-8"
    ) as tmp:
        tmp.write(md)
        tmp_path = Path(tmp.name)

    target = out_dir / (src.stem + ".docx")
    try:
        pypandoc.convert_file(
            str(tmp_path),
            "docx",
            format="gfm+pipe_tables+yaml_metadata_block",
            outputfile=str(target),
            extra_args=[
                f"--resource-path={src.parent}",
                "--toc",
                "--toc-depth=3",
                "--standalone",
                "-V", "geometry:a4paper",
                "-V", "geometry:margin=2cm",
            ],
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    return target


def main() -> int:
    if not DIAGRAMS.exists():
        print(f"missing diagrams dir: {DIAGRAMS}", file=sys.stderr)
        return 1
    for png in ("pipeline.png", "architecture.png"):
        if not (DIAGRAMS / png).exists():
            print(f"missing rendered diagram: {DIAGRAMS / png}", file=sys.stderr)
            return 1

    OUT.mkdir(parents=True, exist_ok=True)
    # Copy diagrams next to the docx so the embedded images resolve when the
    # client extracts the folder.
    out_diagrams = OUT / "diagrams"
    out_diagrams.mkdir(exist_ok=True)
    for png in DIAGRAMS.glob("*.png"):
        shutil.copy2(png, out_diagrams / png.name)

    for src in SOURCES:
        if not src.exists():
            print(f"skip: {src} (missing)", file=sys.stderr)
            continue
        target = convert(src, OUT)
        print(f"wrote {target.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

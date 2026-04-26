"""Command-line entrypoint: `ate parse <file> [-o out.json]`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ate import __version__
from ate.errors import ATEParseError
from ate.parsers import parse


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="ate",
        description="AI-Assisted Test Plan tool — M1: document parser",
    )
    p.add_argument("--version", action="version", version=f"ate {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_parse = sub.add_parser("parse", help="Parse a document into IR JSON")
    p_parse.add_argument("path", help="Path to PDF, DOCX, or TXT")
    p_parse.add_argument("-o", "--out", default=None,
                         help="Output JSON file (default: stdout)")
    p_parse.add_argument("--indent", type=int, default=2)
    p_parse.add_argument("--summary", action="store_true",
                         help="Print summary instead of full IR")

    args = p.parse_args(argv)

    if args.cmd == "parse":
        return _cmd_parse(args)
    return 2


def _cmd_parse(args) -> int:
    src = Path(args.path)
    try:
        doc = parse(src)
    except ATEParseError as e:
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    if args.summary:
        print(f"path:        {doc.source_path}")
        print(f"format:      {doc.source_format}")
        print(f"schema:      {doc.schema_version}")
        print(f"blocks:      {len(doc.blocks)}")
        print(f"headings:    {len(doc.headings)}")
        print(f"paragraphs:  {len(doc.paragraphs)}")
        print(f"code blocks: {len(doc.code_blocks)}")
        print(f"tables:      {len(doc.tables)}")
        return 0

    payload = doc.model_dump(mode="json")
    text = json.dumps(payload, indent=args.indent, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

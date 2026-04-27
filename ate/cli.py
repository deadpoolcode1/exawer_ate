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

    p_plan = sub.add_parser("plan",
                            help="Generate a test plan xlsx from an input document (M1)")
    p_plan.add_argument("path", help="Path to input PDF/DOCX/TXT (single source)")
    p_plan.add_argument("-o", "--out", required=True,
                        help="Output xlsx path")
    p_plan.add_argument("--feature-name", default=None,
                        help="Override feature name (default: auto-detected)")
    p_plan.add_argument("--summary", action="store_true",
                        help="Print summary instead of writing xlsx")
    p_plan.add_argument("--no-ai", action="store_true",
                        help="Disable AI enrichment (force rule-based templates only)")
    p_plan.add_argument("--ai", action="store_true",
                        help="Force AI enrichment: call Anthropic API for any "
                             "row not in ai_cache.json. Requires ANTHROPIC_API_KEY.")

    args = p.parse_args(argv)

    if args.cmd == "parse":
        return _cmd_parse(args)
    if args.cmd == "plan":
        return _cmd_plan(args)
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


def _cmd_plan(args) -> int:
    from ate.planner import generate_plan, generate_plan_to_xlsx
    src = Path(args.path)
    # use_ai: True = force API; False = rule-based; None = cache-only (default)
    if args.no_ai:
        use_ai: bool | None = False
    elif args.ai:
        use_ai = True
    else:
        use_ai = None  # cache-only by default
    try:
        if args.summary:
            plan = generate_plan(src, feature_name=args.feature_name, use_ai=use_ai)
        else:
            plan = generate_plan_to_xlsx(src, args.out,
                                         feature_name=args.feature_name,
                                         use_ai=use_ai)
    except ATEParseError as e:
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(f"feature:        {plan.feature_name}")
    print(f"source:         {plan.source_path}")
    print(f"requirements:   {plan.n_requirements}")
    print(f"plan rows:      {plan.n_rows}")
    if not args.summary:
        print(f"xlsx written:   {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

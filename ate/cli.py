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
                        help="Force AI enrichment for any row not in ai_cache.json. "
                             "Routes through the backend chosen by --ai-backend.")
    p_plan.add_argument("--ai-backend", choices=("cli", "sdk"), default=None,
                        help="AI transport for enrichment. 'cli' (default) shells "
                             "out to `claude -p` using your local Claude Code "
                             "auth — no API key needed. 'sdk' uses the Anthropic "
                             "Python SDK and requires ANTHROPIC_API_KEY. Env var "
                             "ATE_AI_BACKEND overrides the default if this flag "
                             "is omitted.")
    p_plan.add_argument("--rfc", action="append", default=None, metavar="PATH",
                        help="Additional RFC source whose normative (MUST/SHALL) "
                             "clauses are extracted as requirements alongside the "
                             "spec anchors. Repeatable, e.g. "
                             "--rfc references/EVPN/rfc9785.txt --rfc references/EVPN/draft-...txt")
    p_plan.add_argument("--cli-doc", default=None, metavar="PATH",
                        help="EVPN CLI doc (DOCX). When provided, every config "
                             "command in the doc generates its own CLI Configuration "
                             "row family (happy-path / range / mutex / default / `no` "
                             "/ persistence / prerequisite). Replaces the generic CLI "
                             "templates and feeds the AI prompt with command evidence. "
                             "E.g. --cli-doc 'references/EVPN/EVPN CLI 1.00.docx'")

    p_pf = sub.add_parser("plan-feature",
                          help="Auto-discover SFS/CLI/RFCs under references/<NAME>/ "
                               "and generate the test plan xlsx for that feature")
    p_pf.add_argument("name", help="Feature folder name under references/ (e.g. EVPN)")
    p_pf.add_argument("-o", "--out", default=None,
                      help="Output xlsx path (default: plans/<NAME>_test_plan_with_RFCs.xlsx)")
    p_pf.add_argument("--root", default="references",
                      help="Root directory containing feature folders (default: references)")
    p_pf.add_argument("--feature-name", default=None,
                      help="Override the auto-detected feature display name")
    p_pf.add_argument("--summary", action="store_true",
                      help="Print summary instead of writing xlsx")
    p_pf.add_argument("--no-ai", action="store_true",
                      help="Disable AI enrichment (rule-based templates only)")
    p_pf.add_argument("--ai", action="store_true",
                      help="Force AI enrichment for rows not in ai_cache.json")
    p_pf.add_argument("--ai-backend", choices=("cli", "sdk"), default=None,
                      help="AI transport (cli = local Claude Code auth; sdk = ANTHROPIC_API_KEY)")
    p_pf.add_argument("--dry-run", action="store_true",
                      help="Print the resolved SFS/CLI/RFCs without running the planner")

    args = p.parse_args(argv)

    if args.cmd == "parse":
        return _cmd_parse(args)
    if args.cmd == "plan":
        return _cmd_plan(args)
    if args.cmd == "plan-feature":
        return _cmd_plan_feature(args)
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
    rfc_paths = args.rfc if args.rfc else None
    cli_doc_path = args.cli_doc if args.cli_doc else None
    try:
        if args.summary:
            plan = generate_plan(src, feature_name=args.feature_name,
                                 use_ai=use_ai, rfc_paths=rfc_paths,
                                 cli_doc_path=cli_doc_path,
                                 ai_backend=args.ai_backend)
        else:
            plan = generate_plan_to_xlsx(src, args.out,
                                         feature_name=args.feature_name,
                                         use_ai=use_ai, rfc_paths=rfc_paths,
                                         cli_doc_path=cli_doc_path,
                                         ai_backend=args.ai_backend)
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


def discover_feature_inputs(folder: Path) -> dict:
    """Classify files under a feature folder into SFS / CLI doc / RFCs.

    Heuristics (case-insensitive on the basename):
      * `*[Tt]emplate*` xlsx → ignored (output templates).
      * Name starts with `rfc` or contains `draft-` → RFC.
        For RFCs we prefer the `.txt` form (the planner expects plain text).
        Sibling `.docx`/`.pdf` copies of the same RFC are silently dropped
        from the planner input (kept on disk for the parser parity tests).
      * Name contains "CLI" and ends in `.docx` → CLI doc.
      * Remaining `.docx` → SFS. Exactly one must remain.

    Returns: {"sfs": Path, "cli_doc": Path | None, "rfcs": list[Path]}.
    Raises FileNotFoundError / ValueError on misconfigured folders so the
    caller can print a helpful message.
    """
    if not folder.is_dir():
        raise FileNotFoundError(f"feature folder not found: {folder}")

    docx_files: list[Path] = []
    cli_docs: list[Path] = []
    rfc_by_stem: dict[str, dict[str, Path]] = {}

    for f in sorted(folder.iterdir()):
        if not f.is_file():
            continue
        name = f.name
        lname = name.lower()
        if lname.endswith(".xlsx") and "template" in lname:
            continue
        is_rfc = lname.startswith("rfc") or "draft-" in lname
        if is_rfc and f.suffix.lower() in {".txt", ".docx", ".pdf"}:
            rfc_by_stem.setdefault(f.stem, {})[f.suffix.lower()] = f
            continue
        if f.suffix.lower() == ".docx":
            if "cli" in lname:
                cli_docs.append(f)
            else:
                docx_files.append(f)

    # Prefer .txt for each RFC; fall back to .docx then .pdf.
    rfcs: list[Path] = []
    for stem, by_ext in sorted(rfc_by_stem.items()):
        rfcs.append(by_ext.get(".txt") or by_ext.get(".docx") or by_ext[".pdf"])

    if len(cli_docs) > 1:
        raise ValueError(
            f"multiple CLI docs found in {folder}: {[p.name for p in cli_docs]}. "
            f"Only one is supported per feature."
        )
    if not docx_files:
        raise ValueError(
            f"no SFS .docx found in {folder} "
            f"(expected exactly one non-CLI, non-RFC .docx)"
        )
    if len(docx_files) > 1:
        raise ValueError(
            f"multiple SFS candidates in {folder}: {[p.name for p in docx_files]}. "
            f"Rename the CLI doc to contain 'CLI', or move extra .docx files out."
        )

    return {
        "sfs": docx_files[0],
        "cli_doc": cli_docs[0] if cli_docs else None,
        "rfcs": rfcs,
    }


def _cmd_plan_feature(args) -> int:
    from ate.planner import generate_plan, generate_plan_to_xlsx

    folder = Path(args.root) / args.name
    try:
        inputs = discover_feature_inputs(folder)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    sfs: Path = inputs["sfs"]
    cli_doc: Path | None = inputs["cli_doc"]
    rfcs: list[Path] = inputs["rfcs"]

    print(f"feature folder: {folder}")
    print(f"  SFS:        {sfs.name}")
    print(f"  CLI doc:    {cli_doc.name if cli_doc else '(none)'}")
    print(f"  RFCs:       {', '.join(p.name for p in rfcs) if rfcs else '(none)'}")

    if args.dry_run:
        return 0

    out_path = args.out or f"plans/{args.name}_test_plan_with_RFCs.xlsx"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    if args.no_ai:
        use_ai: bool | None = False
    elif args.ai:
        use_ai = True
    else:
        use_ai = None

    rfc_paths = [str(p) for p in rfcs] if rfcs else None
    cli_doc_path = str(cli_doc) if cli_doc else None

    try:
        if args.summary:
            plan = generate_plan(sfs, feature_name=args.feature_name,
                                 use_ai=use_ai, rfc_paths=rfc_paths,
                                 cli_doc_path=cli_doc_path,
                                 ai_backend=args.ai_backend)
        else:
            plan = generate_plan_to_xlsx(sfs, out_path,
                                         feature_name=args.feature_name,
                                         use_ai=use_ai, rfc_paths=rfc_paths,
                                         cli_doc_path=cli_doc_path,
                                         ai_backend=args.ai_backend)
    except ATEParseError as e:
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(f"feature:        {plan.feature_name}")
    print(f"requirements:   {plan.n_requirements}")
    print(f"plan rows:      {plan.n_rows}")
    if not args.summary:
        print(f"xlsx written:   {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

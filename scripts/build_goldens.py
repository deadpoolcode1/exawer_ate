#!/usr/bin/env python3
"""Build / refresh golden files from current parser output.

This is the "regenerate goldens" workflow. Two modes:

  build    - produce candidate goldens from current parser, write to
             tests/golden/*.json. ALWAYS REVIEW THE DIFF before committing.
  diff     - show what would change vs. current goldens (no writes).
  ir       - dump full IR JSON per Tier-A/B doc to tests/golden/ir/*.json
             for regression tracking.

Goldens are the regression contract. Once committed, the scorecard fails
when current output drifts from them. Updating a golden = an explicit
decision to redefine "correct."
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ate.normalize import normalize  # noqa: E402
from ate.parsers import parse  # noqa: E402

CORPUS = ROOT / "tests" / "corpus"
GOLDEN = ROOT / "tests" / "golden"
GOLDEN.mkdir(parents=True, exist_ok=True)

# Documents to track for goldens (relative to tests/corpus/).
TRACKED_DOCS = [
    "tier_a/rfc9785.docx",
    "tier_a/rfc9785.txt",
    "tier_a/rfc9785.pdf",
    "tier_a/EVPN System Specification 1.00.docx",
    "tier_a/EVPN CLI 1.00.docx",
    "tier_b/rfc7432bis-13.docx",
    "tier_b/rfc7432bis-13.txt",
]

# CLI block signatures we expect to find verbatim in the EVPN spec output.
# These are short, distinctive substrings — not full blocks — chosen so a
# single bad whitespace fix doesn't kill them, but a missed block does.
EVPN_CLI_SIGNATURES = [
    "service-type vlan-based",
    "service-type vlan-aware-bundle",
    "service-type port-based",
    "service-type vlan-bundle",
    "interface agg-eth 1.4",
    "interface x-eth 0/0/1.4",
    "l2-transport enable",
    "vlan-id 1-4",
]

# Minimum table count expected per file.
TABLE_MINIMA = {
    "tier_a/EVPN System Specification 1.00.docx": 5,
    "tier_a/EVPN CLI 1.00.docx": 30,  # CLI reference is table-heavy
    "tier_a/rfc9785.docx": 1,
    "tier_a/rfc9785.pdf": 1,
    "tier_b/rfc7432bis-13.docx": 3,
}


def _ir_relpath(rel: str) -> Path:
    safe = rel.replace("/", "__").replace(" ", "_")
    return GOLDEN / "ir" / (safe + ".json")


def build_headings() -> dict:
    """Headings golden = the heading list our current parser produces.

    Stored as the manual ground truth — a human should review and prune
    false positives before committing as the "correct" set.
    """
    spec: dict[str, list[str]] = {}
    for rel in TRACKED_DOCS:
        path = CORPUS / rel
        if not path.exists():
            continue
        d = parse(path)
        n = normalize(d)
        spec[rel] = [h["text"] for h in n["headings"]]
    return spec


def build_cli_blocks() -> dict:
    return {
        "tier_a/EVPN System Specification 1.00.docx": EVPN_CLI_SIGNATURES,
    }


def build_tables() -> dict:
    return TABLE_MINIMA


def build_ir() -> dict[str, str]:
    """Dump full normalized IR per tracked doc as a regression baseline."""
    (GOLDEN / "ir").mkdir(exist_ok=True)
    written: dict[str, str] = {}
    for rel in TRACKED_DOCS:
        path = CORPUS / rel
        if not path.exists():
            continue
        d = parse(path)
        n = normalize(d)
        out = _ir_relpath(rel)
        out.write_text(
            json.dumps(n, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        written[rel] = str(out.relative_to(ROOT))
    return written


def write(spec_path: Path, data: dict) -> None:
    spec_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {spec_path.relative_to(ROOT)}")


def diff_one(spec_path: Path, new_data: dict) -> bool:
    if not spec_path.exists():
        print(f"[NEW] {spec_path.relative_to(ROOT)}")
        return True
    old = spec_path.read_text()
    new = json.dumps(new_data, indent=2, ensure_ascii=False) + "\n"
    if old == new:
        print(f"[OK ] {spec_path.relative_to(ROOT)} unchanged")
        return False
    print(f"[DIFF] {spec_path.relative_to(ROOT)}")
    diff = difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile="committed", tofile="current",
        lineterm="",
    )
    for line in list(diff)[:50]:
        print("    " + line)
    return True


def cmd_build() -> int:
    write(GOLDEN / "headings.json", build_headings())
    write(GOLDEN / "cli_blocks.json", build_cli_blocks())
    write(GOLDEN / "tables.json", build_tables())
    written = build_ir()
    print(f"wrote {len(written)} normalized IR files under tests/golden/ir/")
    return 0


def cmd_diff() -> int:
    changed = 0
    if diff_one(GOLDEN / "headings.json", build_headings()):
        changed += 1
    if diff_one(GOLDEN / "cli_blocks.json", build_cli_blocks()):
        changed += 1
    if diff_one(GOLDEN / "tables.json", build_tables()):
        changed += 1
    return 0 if changed == 0 else 1


def cmd_ir() -> int:
    written = build_ir()
    print(f"wrote {len(written)} normalized IR files")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["build", "diff", "ir"], default="build", nargs="?")
    args = p.parse_args()
    if args.cmd == "build":
        return cmd_build()
    if args.cmd == "diff":
        return cmd_diff()
    if args.cmd == "ir":
        return cmd_ir()
    return 2


if __name__ == "__main__":
    sys.exit(main())

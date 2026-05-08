#!/usr/bin/env python3
"""Bake AI-enriched rows into ate/planner/ai_cache.json (v2 prompt shape).

The v1 script was a hand-curated dictionary of enriched rows mapped to
(req_id, category, sub_index) tuples (kept for reference at
scripts/build_ai_cache_v1_archive.py). The M1 respin moved the cache
key salt to v2 and changed the row shape (Setup/Action/Verify +
Pass/Fail-on + Equipment), so cache entries are now produced by
running the live `enrich_plan` against the planner's row set rather
than maintained by hand.

Strategy:
  - Default mode runs against a curated subset that exercises Yossi's
    M1-respin gaps end-to-end: CLI configuration happy-paths and one
    validation row per command, RFC route-type Packet validation,
    DF election, MAC mobility, and one Basic Functionality row per
    spec requirement. ~120 rows. Demonstrates AI quality where Yossi
    looks first.
  - `--full` runs the full 800+ row plan. Plan for ~30 minutes via the
    SDK backend or 2-3 hours via the CLI backend.

Usage:
    python scripts/build_ai_cache.py                 # curated subset, CLI backend
    python scripts/build_ai_cache.py --full          # everything, CLI backend
    python scripts/build_ai_cache.py --full --sdk    # everything via SDK
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ate.planner.ai_enricher import enrich_plan  # noqa: E402
from ate.planner.generator import generate_plan  # noqa: E402
from ate.planner.model import Plan  # noqa: E402

EVPN_SPEC = ROOT / "references" / "EVPN System Specification 1.00.docx"
RFC7432BIS = ROOT / "references" / "draft-ietf-bess-rfc7432bis-13.txt"
RFC9785 = ROOT / "references" / "rfc9785.txt"
CLI_DOC = ROOT / "references" / "EVPN CLI 1.00.docx"


def _curate_rows(plan: Plan) -> Plan:
    """Pick a representative subset that exercises every M1-respin gap fix.

    For each CLI command: take the happy-path row + the first validation
    row + the prerequisite row.
    For each spec requirement: take Basic Functionality + one Packet
    validation row when present.
    For each RFC requirement: take the content-aware Packet validation
    rows (route type N, DF election, MAC mobility, ESI label, …).
    """
    keep: list = []
    cli_count: dict[str, int] = defaultdict(int)
    spec_basic: set[str] = set()
    spec_packet: set[str] = set()

    for row in plan.rows:
        rid = row.sfs_requirement_id
        cat = row.category
        if rid.startswith("CLI:"):
            # First 3 rows per command (happy-path, first validation, prereq)
            if cli_count[rid] < 3:
                cli_count[rid] += 1
                keep.append(row)
            continue
        if rid.startswith("RFC") and cat == "Packet validation":
            content_keywords = ("route type", "df election", "mac mobility",
                                "esi label", "split horizon", "bum", "aliasing")
            if any(kw in row.action_steps.lower() for kw in content_keywords):
                keep.append(row)
            continue
        if rid.startswith("EVPNS-REQ#"):
            if cat == "Basic Functionality" and rid not in spec_basic:
                spec_basic.add(rid)
                keep.append(row)
                continue
            if cat == "Packet validation" and rid not in spec_packet:
                spec_packet.add(rid)
                keep.append(row)
                continue
    return plan.model_copy(update={"rows": keep})


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--full", action="store_true",
                   help="Bake every row in the plan, not just the curated subset")
    p.add_argument("--sdk", action="store_true",
                   help="Use Anthropic SDK backend (requires ANTHROPIC_API_KEY). "
                        "Faster than CLI backend for bulk; bills the API account.")
    p.add_argument("--limit", type=int, default=None,
                   help="Process only the first N rows of the (curated|full) set. "
                        "Useful for time-bounded pilot runs. Each row is "
                        "~75 s via the CLI backend.")
    args = p.parse_args()

    plan = generate_plan(
        EVPN_SPEC,
        use_ai=False,
        rfc_paths=[RFC7432BIS, RFC9785],
        cli_doc_path=CLI_DOC,
    )
    print(f"Generated baseline plan: {plan.n_rows} rows, "
          f"{plan.n_requirements} requirements")

    target = plan if args.full else _curate_rows(plan)
    if args.limit is not None:
        target = target.model_copy(update={"rows": target.rows[: args.limit]})
    label = "full plan" if args.full else "curated subset"
    if args.limit is not None:
        label += f" (capped to {args.limit})"
    print(f"Baking AI rows: {target.n_rows} ({label})")

    backend = "sdk" if args.sdk else "cli"
    # CLI backend → retry_forever so a 5-hour Pro window doesn't drop
    # rows; the bake pauses until the window recovers, then continues.
    retry_forever = (backend == "cli")
    started = time.time()
    _, stats = enrich_plan(
        target, use_api=True, backend=backend, cli_doc_path=CLI_DOC,
        retry_forever=retry_forever,
    )
    elapsed = time.time() - started
    print(f"Done in {elapsed:.0f}s.")
    print(f"  cache_hit:  {stats['cache_hit']}")
    print(f"  api_call:   {stats['api_call']}")
    print(f"  rule_based: {stats['rule_based']}")
    print("Cache file: ate/planner/ai_cache.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

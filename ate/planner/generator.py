"""Plan generator — IR → Plan model → xlsx.

For each requirement we:
  1. Determine which Categories apply (via domain tags + ALWAYS list).
  2. For each applicable Category, instantiate the action template using
     requirement-specific signals: title, RFC refs, CLI hint, MUST hint.

For each RFC requirement we additionally dispatch on title/body content
to emit RFC-mechanism-specific rows (route types 1-4, DF election, MAC
mobility, label allocation, …) — closes Yossi's "RFC Support" gap.

When a CLI doc is provided we also walk every config command (lacp-key,
identifier, service-carving, …) and emit a row family per command:
happy-path / range validation / mutual exclusion / default / `no` form
/ persistence / prerequisite. These rows replace the generic CLI
configuration template — closes Yossi's "missing validations, defaults"
gap.

Each row carries an explicit `equipment` tag (DUT-only, IXIA, neighbor
PE, …) so QA knows the test rig before reading the row — closes Yossi's
"missing IXIA indications" gap.

This is rule-based / template-driven (M1). M3 will replace the per-row
template instantiation with prompt-driven AI generation, producing the
same Plan model.
"""
from __future__ import annotations

import re
from pathlib import Path

from ate.ir import Document
from ate.parsers import parse
from ate.planner.categories import (
    CATEGORY_ACTIONS,
    categories_for_tags,
    rfc_actions_for,
)
from ate.planner.cli_extractor import config_commands
from ate.planner.cli_rows import cli_command_rows
from ate.planner.equipment import equipment_for_row
from ate.planner.extractor import extract_requirements
from ate.planner.model import Plan, PlanRow, Requirement
from ate.planner.xlsx_writer import write_xlsx


def _cli_hint(req: Requirement) -> str:
    """One-line excerpt from the first CLI block in this section, if any."""
    if not req.code_blocks:
        return ""
    block = req.code_blocks[0]
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    if not lines:
        return ""
    sample = lines[0] if len(lines) == 1 else " / ".join(lines[:2])
    return f" (e.g. `{sample[:80]}`)"


def _rfc_refs_or(req: Requirement, fallback: str = "RFC 7432bis") -> str:
    return ", ".join(req.rfc_refs) if req.rfc_refs else fallback


def _must_hint(req: Requirement) -> str:
    """Short-form MUST hint for inclusion in expectation."""
    if not req.must_statements:
        return ""
    s = req.must_statements[0]
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > 140:
        s = s[:137] + "…"
    label = "RFC MUST" if req.source == "rfc" else "spec MUST"
    return f"; {label}: \"{s}\""


def _rfc_hint(req: Requirement) -> str:
    if not req.rfc_refs:
        return ""
    return f" (per {', '.join(req.rfc_refs)})"


def _format_template(tpl: str, req: Requirement, feature_name: str) -> str:
    section = req.section_number if req.section_number else f'"{req.title}"'
    section_phrase = f"§{section}" if req.section_number else "as documented"
    return tpl.format(
        title=req.title or feature_name,
        req_id=req.req_id,
        section=section_phrase,
        cli_hint=_cli_hint(req),
        rfc_hint=_rfc_hint(req),
        rfc_refs_or_rfc7432bis=_rfc_refs_or(req),
        must_hint=_must_hint(req),
        neighbor_feature=_neighbor_feature(req, feature_name),
    )


# Map domain tags → suggested neighboring features for "Feature interaction".
# We pick something that's NOT the requirement's own primary subject.
_NEIGHBORS_BY_TAG: dict[str, list[str]] = {
    "CONFIG": ["BGP", "MPLS encapsulation", "QoS"],
    "PACKET": ["multi-homing", "BGP attributes", "QoS"],
    "HA": ["BGP convergence", "MPLS encapsulation", "Q-in-Q"],
    "SCALE": ["per-EVI scale", "MAC table aging", "QoS marking"],
    "PROTOCOL": ["multi-homing", "BGP route reflector", "MAC mobility"],
    "MONITORING": ["BGP", "interface flap", "high-load traffic"],
    "META": ["BGP", "MPLS encapsulation"],
}


def _neighbor_feature(req: Requirement, feature_name: str) -> str:
    """Pick a neighboring feature for Feature-interaction tests."""
    title_lc = (req.title or feature_name).lower()
    for t in req.tags:
        for n in _NEIGHBORS_BY_TAG.get(t, []):
            if n.lower() not in title_lc:
                return n
    return "BGP"


def _action_pairs_for(req: Requirement, cat: str) -> list[tuple[str, str]]:
    """Return list of (action, expectation) template pairs to emit for
    requirement `req` in category `cat`.

    For RFC requirements we first try the content-aware patterns (route
    type N, DF election, …); generic templates only run when no
    content-aware row applies.
    """
    if req.source == "rfc":
        rfc_pairs = rfc_actions_for(req.title, req.description, cat)
        if rfc_pairs:
            return rfc_pairs
    return CATEGORY_ACTIONS.get(cat, [])


def generate_plan(doc: Document | str | Path,
                  feature_name: str | None = None,
                  anchor_re: re.Pattern[str] | None = None,
                  use_ai: bool | None = None,
                  rfc_paths: list[str | Path] | None = None,
                  cli_doc_path: str | Path | None = None,
                  ai_backend: str | None = None,
                  ) -> Plan:
    if not isinstance(doc, Document):
        doc = parse(doc)

    if feature_name is None:
        title = (doc.metadata.get("core_title", "").strip()
                 if doc.metadata else "")
        GENERIC = {"introduction", "scope", "overview", "purpose",
                   "abstract", "table of contents", "modification history"}
        if title:
            feature_name = title
        else:
            for b in doc.blocks:
                if (hasattr(b, "level") and b.level == 1
                        and getattr(b, "text", "").strip()
                        and b.text.strip().lower() not in GENERIC):
                    feature_name = b.text.strip()
                    break
        if feature_name is None:
            feature_name = Path(doc.source_path).stem

    reqs = extract_requirements(doc, anchor_re=anchor_re)

    if rfc_paths:
        from ate.planner.rfc_extractor import extract_rfc_requirements  # noqa: PLC0415
        seen_ids = {r.req_id for r in reqs}
        for rp in rfc_paths:
            for r in extract_rfc_requirements(rp):
                if r.req_id in seen_ids:
                    continue
                seen_ids.add(r.req_id)
                reqs.append(r)

    rows: list[PlanRow] = []
    if not reqs:
        # Synthetic placeholder so empty input produces a non-empty plan
        reqs = [Requirement(
            req_id="(no-anchor)",
            title=feature_name,
            section_number=None,
            description="No requirement anchors detected in source.",
            tags=["CONFIG"],
        )]

    # ── CLI doc-driven rows ──────────────────────────────────────────────
    # When a CLI doc is provided, every config command produces its own
    # row family (happy-path / range / mutex / default / `no` / persistence
    # / prerequisite). When a CLI doc is provided, we DROP "CLI configuration"
    # from the per-spec-requirement category set — the per-command rows are
    # the authoritative CLI Configuration coverage.
    cli_rows: list[PlanRow] = []
    cli_cmd_anchors: list[Requirement] = []
    if cli_doc_path is not None:
        cmds = config_commands(cli_doc_path)
        cli_rows = cli_command_rows(cmds)
        # Synthetic Requirement entries for traceability sheet — one per
        # command. Tag them CONFIG so they never accidentally pick up
        # protocol-only categories.
        for cmd in cmds:
            cli_cmd_anchors.append(Requirement(
                req_id=f"CLI:{cmd.name}",
                title=cmd.name,
                section_number=None,
                description=(cmd.description or "")[:600],
                tags=["CONFIG"],
                source="cli",
            ))
    drop_cli_category = bool(cli_rows)

    # ── Per-requirement rows ─────────────────────────────────────────────
    for r in reqs:
        cats = categories_for_tags(r.tags, source=r.source)
        for cat in cats:
            if drop_cli_category and cat == "CLI configuration":
                continue
            pairs = _action_pairs_for(r, cat)
            for action_tpl, exp_tpl in pairs:
                rows.append(PlanRow(
                    category=cat,
                    sub_category="",
                    equipment=equipment_for_row(cat, r.tags, source=r.source),
                    action_steps=_format_template(action_tpl, r, feature_name),
                    sfs_requirement_id=r.req_id,
                    expectation=_format_template(exp_tpl, r, feature_name),
                ))

    # CLI rows are emitted as a leading section so QA reads the
    # CLI configuration block first (it's the most concrete material
    # in the plan and what Yossi reviewed against most directly).
    rows = cli_rows + rows

    plan = Plan(
        feature_name=feature_name,
        source_path=str(doc.source_path),
        requirements=cli_cmd_anchors + reqs,
        rows=rows,
    )

    # AI enrichment: replaces template-based rows with feature-specific ones
    # when the row appears in ai_cache.json (committed) OR when ANTHROPIC_API_KEY
    # is set (live API call). use_ai=False forces rule-based output.
    if use_ai is not False:
        from ate.planner.ai_enricher import enrich_plan  # noqa: PLC0415
        plan, _stats = enrich_plan(plan, use_api=use_ai, backend=ai_backend,
                                   cli_doc_path=cli_doc_path)
    return plan


def generate_plan_to_xlsx(input_path: str | Path,
                          output_path: str | Path,
                          feature_name: str | None = None,
                          use_ai: bool | None = None,
                          rfc_paths: list[str | Path] | None = None,
                          cli_doc_path: str | Path | None = None,
                          ai_backend: str | None = None,
                          ) -> Plan:
    plan = generate_plan(input_path, feature_name=feature_name, use_ai=use_ai,
                         rfc_paths=rfc_paths, cli_doc_path=cli_doc_path,
                         ai_backend=ai_backend)
    write_xlsx(plan, output_path, cli_doc_path=cli_doc_path)
    return plan

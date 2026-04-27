"""Plan generator — IR → Plan model → xlsx.

For each requirement we:
  1. Determine which Categories apply (via domain tags + ALWAYS list).
  2. For each applicable Category, instantiate the action template using
     requirement-specific signals: title, RFC refs, CLI hint, MUST hint.

This is rule-based / template-driven (M1). M3 will replace the per-requirement
template instantiation with prompt-driven AI generation, producing the same
Plan model.
"""
from __future__ import annotations

import re
from pathlib import Path

from ate.ir import Document
from ate.parsers import parse
from ate.planner.categories import CATEGORY_ACTIONS, categories_for_tags
from ate.planner.extractor import extract_requirements
from ate.planner.model import Plan, PlanRow, Requirement
from ate.planner.xlsx_writer import write_xlsx


def _cli_hint(req: Requirement) -> str:
    """One-line excerpt from the first CLI block in this section, if any."""
    if not req.code_blocks:
        return ""
    block = req.code_blocks[0]
    # Pull out the first 2 non-empty lines as a hint
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
    return f"; spec MUST: \"{s}\""


def _rfc_hint(req: Requirement) -> str:
    if not req.rfc_refs:
        return ""
    return f" (per {', '.join(req.rfc_refs)})"


def _format_template(tpl: str, req: Requirement, feature_name: str) -> str:
    section = req.section_number if req.section_number else f'"{req.title}"'
    # If the template references {section} but we don't have a numbered
    # section, swap "in §X" for "as documented" to read naturally.
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
    """Pick a neighboring feature for Feature-interaction tests.

    Avoid recommending the requirement combine with itself.
    """
    title_lc = (req.title or feature_name).lower()
    for t in req.tags:
        for n in _NEIGHBORS_BY_TAG.get(t, []):
            if n.lower() not in title_lc:
                return n
    return "BGP"


def generate_plan(doc: Document | str | Path,
                  feature_name: str | None = None,
                  anchor_re: re.Pattern[str] | None = None,
                  use_ai: bool | None = None,
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

    for r in reqs:
        cats = categories_for_tags(r.tags)
        for cat in cats:
            for action_tpl, exp_tpl in CATEGORY_ACTIONS[cat]:
                rows.append(PlanRow(
                    category=cat,
                    sub_category="",
                    action_steps=_format_template(action_tpl, r, feature_name),
                    sfs_requirement_id=r.req_id,
                    expectation=_format_template(exp_tpl, r, feature_name),
                ))

    plan = Plan(
        feature_name=feature_name,
        source_path=str(doc.source_path),
        requirements=reqs,
        rows=rows,
    )

    # AI enrichment: replaces template-based rows with feature-specific ones
    # when the row appears in ai_cache.json (committed) OR when ANTHROPIC_API_KEY
    # is set (live API call). use_ai=False forces rule-based output.
    if use_ai is not False:
        from ate.planner.ai_enricher import enrich_plan  # noqa: PLC0415
        plan, _stats = enrich_plan(plan, use_api=use_ai)
    return plan


def generate_plan_to_xlsx(input_path: str | Path,
                          output_path: str | Path,
                          feature_name: str | None = None,
                          use_ai: bool | None = None,
                          ) -> Plan:
    plan = generate_plan(input_path, feature_name=feature_name, use_ai=use_ai)
    write_xlsx(plan, output_path)
    return plan

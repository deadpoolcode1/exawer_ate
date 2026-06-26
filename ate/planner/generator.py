"""Plan generator — IR → Plan model → xlsx (flow-driven, M1 QA respin).

Closes the QA review gap that the previous M1 pass left open: rows used
to be "one row per (requirement × applicable category)", which made the
plan a 800-row checklist of per-requirement boilerplate. QA pointed out
that this is too shallow to validate the *flow* / use case behind a
requirement, and that it does not feed the automation-codegen PoC in
later milestones.

The new pipeline:

  1. **Extract requirements** (existing): pull EVPNS-REQ#NN anchors out
     of the spec, and (optionally) RFC-MUST clauses from the referenced
     RFCs. Each requirement carries tags + RFC refs + must statements.

  2. **Extract CLI commands** (existing): when an EVPN CLI doc is
     provided, every config command produces its own command-validation
     row family (happy-path / range / mutex / default / `no` /
     persistence / prerequisite). These rows validate the *commands
     themselves* (structure, options, values, persistency) and are
     **not** setup steps for other tests — that's the QA point about
     CLI Configuration's purpose.

  3. **Synthesize flows** (new): from `flows.EVPN_FLOWS`, claim each
     requirement that matches a flow's selector. Each flow then emits
     one row per applicable category (Basic Functionality, Packet
     validation, On-the-fly, …). Categories that do not apply to the
     flow are skipped — the QA point about "categories aggregate by
     functional aspect, not every category for every requirement".

  4. **Compute coverage** (new): which requirements does each flow
     claim, and which requirements does no flow claim ("orphans")?
     This map is rendered as a Coverage sheet in the xlsx so reviewers
     can see traceability without scanning the body.

The generator is rule-based; M3 will swap the per-(flow, category)
rendering for AI prompt-driven generation, producing the same Plan
model shape.
"""
from __future__ import annotations

import re
from pathlib import Path

from ate.ir import Document
from ate.parsers import parse
from ate.planner.categories import (
    RFC_EXCLUDED_CATEGORIES,
    overlay_for_category,
)
from ate.planner.cli_rows import cli_command_rows
from ate.planner.flows import EVPN_FLOWS, Flow, build_coverage, reqs_for_flow
from ate.planner.model import Plan, PlanRow, Requirement
from ate.planner.requirements_builder import build_catalog, mark_claimed
from ate.planner.xlsx_writer import write_xlsx


def _planrow_for_rfc_orphan(req: Requirement) -> PlanRow:
    """Render an RFC mandate (no flow claims it) as a PlanRow so it flows
    through the enricher pipeline and lands on the main sheet as a
    first-class row.

    Client direction (Yossi, 2026-05-21): the SFS deliberately omits
    requirements defined in the RFC standard; the TP must test those
    with the same rigour as flow rows — not as placeholder "synthesized
    — review" entries on a separate sheet. The Setup/Action/Verify
    scaffold below is replaced by AI-generated content during enrichment.
    """
    short = req.req_id.split("-§")[0] if "-§" in req.req_id else "RFC"
    section = req.section_number or ""
    section_ref = f" §{section}" if section else ""
    must = (req.must_statements[0] if req.must_statements
            else req.description[:240])
    sub = (f"{short}{section_ref} — {req.title}"
           if section else f"{short} — {req.title}")
    return PlanRow(
        flow_id="",
        flow_name="",
        category="Protocol behaviour (RFC mandate)",
        sub_category=sub,
        equipment="DUT only (RFC-mandated)",
        action_steps=(
            "Setup:  Configure the feature so the RFC clause is exercisable.\n"
            f"Action: Exercise the behaviour the clause mandates — "
            f"{must[:240]}.\n"
            f"Verify: Device behaviour conforms to {short}{section_ref}."
        ),
        covered_req_ids=[req.req_id],
        sfs_requirement_id=req.req_id,
        expectation=(
            f"Pass:    Device implements {short}{section_ref} as specified.\n"
            "Fail-on: Observable behaviour deviates from the RFC clause."
        ),
    )


def _row_for_flow_category(flow: Flow, category: str,
                           covered_reqs: list[Requirement]) -> PlanRow:
    """Render one flow-row for a category. Covered req-ids are joined into
    sfs_requirement_id (back-compat with the existing template column)
    and also kept in the structured `covered_req_ids` list.

    For coverage-driven flows with no requirement match, the Coverage
    cell is rendered as "<flow_id> (coverage-driven)" so reviewers can
    still cite the row.
    """
    action_steps, expectation = overlay_for_category(flow, category)
    covered_ids = [r.req_id for r in covered_reqs]
    if not covered_ids and flow.coverage_driven:
        sfs = f"{flow.id} (coverage-driven)"
    else:
        sfs = ", ".join(covered_ids)
    return PlanRow(
        flow_id=flow.id,
        flow_name=flow.name,
        category=category,
        sub_category="",
        equipment=flow.equipment,
        action_steps=action_steps,
        covered_req_ids=covered_ids,
        sfs_requirement_id=sfs,
        expectation=expectation,
    )


def _detect_feature_name(doc: Document) -> str:
    """Title resolution unchanged from the previous generator."""
    title = (doc.metadata.get("core_title", "").strip()
             if doc.metadata else "")
    GENERIC = {"introduction", "scope", "overview", "purpose",
               "abstract", "table of contents", "modification history"}
    if title:
        return title
    for b in doc.blocks:
        if (hasattr(b, "level") and b.level == 1
                and getattr(b, "text", "").strip()
                and b.text.strip().lower() not in GENERIC):
            return b.text.strip()
    return Path(doc.source_path).stem


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
        feature_name = _detect_feature_name(doc)

    # ── Requirements Builder (M1 client respin 2026-05-17) ────────────
    # Three independent sources merged before the flow generator runs:
    #   • SFS extractor   (vendor spec; defines CLI / NETCONF / upgrade)
    #   • RFC extractor   (protocol mandates; promoted to first-class)
    #   • CLI inheritance (BGP-neighbor sub-configs under `af-l2vpn evpn`
    #                      not present in the EVPN CLI doc)
    # See ate/planner/requirements_builder.py for the unified catalog
    # shape and ate/planner/cli_inheritance.py for the inheritance table.
    catalog = build_catalog(
        doc, rfc_paths=rfc_paths, cli_doc_path=cli_doc_path,
        anchor_re=anchor_re,
    )

    # Separate CLI-anchor requirements from spec/RFC requirements for the
    # flow loop below — flow selectors should match spec/RFC content, not
    # the `CLI:<name>` synthetic anchors.
    reqs = [r for r in catalog.requirements if r.source != "cli"]
    cli_cmd_anchors = [r for r in catalog.requirements if r.source == "cli"]

    if not reqs and not cli_cmd_anchors:
        # Synthetic placeholder so empty input still produces a non-empty plan
        reqs = [Requirement(
            req_id="(no-anchor)",
            title=feature_name,
            section_number=None,
            description="No requirement anchors detected in source.",
            tags=["CONFIG"],
        )]

    # ── CLI command-validation rows ───────────────────────────────────
    # `catalog.cli_commands` already includes inherited sub-configs
    # (e.g. allow-as-in, capability, …) when their parent appears in the
    # EVPN CLI doc. cli_rows.py renders the same per-command row family
    # for extracted and inherited commands uniformly.
    cli_rows: list[PlanRow] = cli_command_rows(catalog.cli_commands)
    normalized: list[PlanRow] = []
    for r in cli_rows:
        if not r.covered_req_ids and r.sfs_requirement_id:
            r = r.model_copy(update={
                "covered_req_ids": [r.sfs_requirement_id],
            })
        normalized.append(r)
    cli_rows = normalized

    # ── Flow-driven rows ───────────────────────────────────────────────
    # Two kinds of flows emit body rows:
    #   1. Requirement-anchored: at least one requirement matches the
    #      flow's selector. Coverage cell lists the matched req-IDs.
    #   2. Coverage-driven (flow.coverage_driven=True): scale / upgrade /
    #      NETCONF / on-the-fly / 24-h soak. These are test techniques
    #      applied broadly. They emit rows so reviewers see the actual
    #      test steps; the Coverage cell is rendered as the flow's own
    #      ID since no spec requirement anchors them.
    flow_rows: list[PlanRow] = []
    flows_with_reqs: list[tuple[Flow, list[Requirement]]] = []
    # Eyal Ozeri 2026-06-21: "Tech-support test is not needed in every flow."
    # Emit a single representative tech-support / diagnostic-bundle test (the
    # first flow that carries the category) instead of one per flow.
    tech_support_done = False
    for flow in EVPN_FLOWS:
        covered = reqs_for_flow(flow, reqs)
        if not covered and not flow.coverage_driven:
            continue
        flows_with_reqs.append((flow, covered))
        # If every covered requirement is RFC-sourced, the row describes
        # protocol behaviour only — vendor-platform categories (CLI,
        # On-the-fly config, Upgrade, Management) do not apply.
        all_rfc = bool(covered) and all(r.source == "rfc" for r in covered)
        for cat in flow.categories:
            if all_rfc and cat in RFC_EXCLUDED_CATEGORIES:
                continue
            if cat == "Tech-support":
                if tech_support_done:
                    continue
                tech_support_done = True
            flow_rows.append(_row_for_flow_category(flow, cat, covered))

    # Fallback: if no flow matched (e.g. doc with no requirement anchors,
    # or a non-EVPN spec the catalog does not cover), emit one minimal
    # row per extracted requirement so the deliverable is not empty.
    if not flow_rows and not cli_rows:
        for r in reqs:
            flow_rows.append(PlanRow(
                flow_id="",
                flow_name="",
                category="Basic Functionality",
                sub_category="",
                equipment="DUT only (no flow catalog match)",
                action_steps=(
                    f"Setup:  Bring up the feature described by {r.req_id} "
                    f"({r.title}).\n"
                    "Action: Exercise the documented behaviour as written "
                    "in the source spec.\n"
                    "Verify: Behaviour matches the spec; no spurious errors."
                ),
                covered_req_ids=[r.req_id],
                sfs_requirement_id=r.req_id,
                expectation=(
                    "Pass:    Behaviour matches the spec.\n"
                    "Fail-on: Behaviour deviates from the spec or feature "
                    "fails to come up."
                ),
            ))

    # ── RFC orphan promotion (Yossi push-back, 2026-05-21) ───────────
    # The SFS deliberately omits RFC-defined requirements; the TP must
    # test them with the same rigour as flow rows. RFC mandates no flow
    # claims are emitted as PlanRows here, so they flow through the
    # enricher and land on the main sheet as first-class rows — not as
    # placeholders on a separate "Synthesized — Review" sheet.
    claimed: set[str] = set()
    for fl, covered in flows_with_reqs:
        for r in covered:
            claimed.add(r.req_id)
    mark_claimed(catalog, claimed)
    synth_rfc_rows: list[PlanRow] = [
        _planrow_for_rfc_orphan(req) for req in catalog.synth_anchors
    ]

    # Hand-curated constructs the auto-extractors miss — e.g. the Default
    # Gateway Extended Community (Yossi 2026-06-21), defined in 7432bis §7.8
    # but typed by RFC 4360 §3.3 and dropped by rfc_extractor because §7.8
    # has no MUST keyword. Deterministic (not AI-enriched). See curated.py.
    from ate.planner.curated import (  # noqa: PLC0415
        curated_requirements_and_rows,
    )
    curated_reqs, curated_rows = curated_requirements_and_rows()

    # ── Compose ────────────────────────────────────────────────────────
    # CLI rows render first (most concrete material; QA reads CLI block
    # first), then flow rows in the EVPN_FLOWS order, then RFC-orphan
    # rows so the deliverable ends with every RFC mandate the TP covers.
    rows = cli_rows + flow_rows + synth_rfc_rows + curated_rows

    # Coverage assertion: every RFC MUST extracted by rfc_extractor must
    # appear in ≥ 1 PlanRow's covered_req_ids — either via a flow that
    # claimed it or via the synth-PlanRow path above. A miss here is a
    # bug in the synth promotion logic.
    rfc_ids = {r.req_id for r in catalog.requirements if r.source == "rfc"}
    covered_ids = {rid for row in rows for rid in row.covered_req_ids}
    missing = rfc_ids - covered_ids
    if missing:
        raise ValueError(
            "RFC requirements not covered by any row "
            f"(synth promotion failed): {sorted(missing)}"
        )

    plan = Plan(
        feature_name=feature_name,
        source_path=str(doc.source_path),
        requirements=cli_cmd_anchors + reqs + curated_reqs,
        rows=rows,
    )

    # Stash coverage info on the plan via an attached attribute. This is
    # not part of the persisted model (Plan.model_dump won't include it),
    # but xlsx_writer reads it off the in-memory object to emit the
    # Coverage sheet.
    coverage_map, orphans = build_coverage(EVPN_FLOWS, reqs)
    plan.__dict__["_coverage"] = coverage_map
    plan.__dict__["_orphans"] = orphans
    plan.__dict__["_flows_with_reqs"] = flows_with_reqs
    plan.__dict__["_catalog"] = catalog

    if use_ai is not False:
        from ate.planner.ai_enricher import enrich_plan  # noqa: PLC0415
        plan, _stats = enrich_plan(plan, use_api=use_ai, backend=ai_backend,
                                   cli_doc_path=cli_doc_path)
        # Re-attach coverage after the model_copy in enrich_plan
        plan.__dict__["_coverage"] = coverage_map
        plan.__dict__["_orphans"] = orphans
        plan.__dict__["_flows_with_reqs"] = flows_with_reqs
        plan.__dict__["_catalog"] = catalog

    # Command grounding (Ron/Yossi 2026-06-24; scope confirmed by Ilan
    # 2026-06-25): on the *final* plan — post-enrichment, the worst case for an
    # invented command — strip every command that traces to no source doc so
    # the deliverable carries no non-existing command, then re-check (the
    # remaining buckets should show zero unknown). See cli_crosscheck.py.
    from ate.planner.cli_crosscheck import (  # noqa: PLC0415
        reconcile_commands,
        scrub_ungrounded,
    )
    plan.__dict__["_cli_removed"] = scrub_ungrounded(
        plan, catalog.cli_commands, catalog.requirements,
    )
    plan.__dict__["_cli_crosscheck"] = reconcile_commands(
        plan, catalog.cli_commands, catalog.requirements,
    )
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

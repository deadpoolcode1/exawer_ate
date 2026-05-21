"""Requirements Builder — pre-agent stage that unifies SFS, RFC, and CLI
inheritance into one catalog.

Client review (2026-05-14, Eyal Ozeri) flagged that the previous pipeline
treated the SFS as the single source of truth and silently dropped:
  - RFC MUST clauses that no flow happened to claim
  - CLI sub-configs that aren't documented in the EVPN CLI doc but are
    inherited from the parent protocol (e.g. BGP-neighbor sub-configs
    under `af-l2vpn evpn`)

This module is the "process before the agent kicks in" that Eyal
requested. It produces a `RequirementCatalog` from three independent
sources, with provenance tracking so the xlsx writer can tint inherited
rows for QA attention. RFC mandates no flow claims are promoted to
first-class PlanRows by `generator._planrow_for_rfc_orphan()` (Yossi
2026-05-21: SFS omits RFC-defined requirements; TP must test them
with the same rigour as flow rows).

Pipeline shape:

    SFS .docx ──┐
    RFC(s) ─────┼──► requirements_builder.build_catalog
    CLI .docx ──┘             │
                              ▼
                       RequirementCatalog
                      (requirements, cli_commands,
                       synth_anchors, provenance)
                              │
                              ▼
                      generator → atomic_rows → xlsx_writer
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from ate.ir import Document
from ate.parsers import parse
from ate.planner.cli_extractor import CliCommand, extract_commands
from ate.planner.cli_inheritance import expand as expand_inherited
from ate.planner.extractor import extract_requirements
from ate.planner.model import Requirement
from ate.planner.req_classifier import classify_all


@dataclass
class RequirementCatalog:
    """Unified output of the Requirements Builder.

    - `requirements`: SFS + RFC requirements, deduped by req_id.
    - `cli_commands`: extracted EVPN commands + inherited sub-configs.
    - `synth_anchors`: RFC requirements that no flow claims;
      `generator._planrow_for_rfc_orphan` emits a first-class PlanRow
      for each so the enricher writes concrete Setup/Action/Verify.
    - `provenance`: req_id → "sfs" | "rfc" | "cli-inherit". The xlsx
      writer uses this for row tinting on the main sheet.
    - `inherited_cmd_names`: just the names of inherited CliCommand
      objects, for fast "is this row inherited?" lookups at render time.
    """
    requirements: list[Requirement] = field(default_factory=list)
    cli_commands: list[CliCommand] = field(default_factory=list)
    synth_anchors: list[Requirement] = field(default_factory=list)
    provenance: dict[str, str] = field(default_factory=dict)
    inherited_cmd_names: set[str] = field(default_factory=set)


def _merge_requirements(spec_reqs: list[Requirement],
                         rfc_reqs: list[Requirement],
                         provenance: dict[str, str]) -> list[Requirement]:
    """Concatenate spec + RFC reqs, dedup by req_id. SFS wins on collision."""
    out: list[Requirement] = []
    seen: set[str] = set()
    for r in spec_reqs:
        if r.req_id in seen:
            continue
        seen.add(r.req_id)
        provenance[r.req_id] = "sfs"
        out.append(r)
    for r in rfc_reqs:
        if r.req_id in seen:
            continue
        seen.add(r.req_id)
        provenance[r.req_id] = "rfc"
        out.append(r)
    return out


def _identify_synth_anchors(reqs: list[Requirement],
                              claimed_ids: set[str]) -> list[Requirement]:
    """Return the RFC requirements that no flow claims —
    `generator._planrow_for_rfc_orphan` then emits a first-class PlanRow
    per orphan so the RFC mandate becomes a real test row (not a
    placeholder).

    Only RFC requirements become synth anchors. SFS orphans are a
    different signal (flow catalog gap) and stay surfaced in the
    Coverage sheet as before.
    """
    return [r for r in reqs
            if r.source == "rfc"
            and r.req_id not in claimed_ids]


def _make_cli_anchors(extracted: list[CliCommand],
                       inherited: list[CliCommand],
                       provenance: dict[str, str]) -> list[Requirement]:
    """Each CliCommand gets a synthetic Requirement (`CLI:<name>`) so
    coverage tracking can cite it. The existing pipeline already used
    this convention; we add provenance tagging for inherited commands.
    """
    out: list[Requirement] = []
    for cmd in extracted:
        rid = f"CLI:{cmd.name}"
        provenance[rid] = "sfs"  # extracted from a customer doc = sfs-equivalent
        out.append(Requirement(
            req_id=rid,
            title=cmd.name,
            section_number=None,
            description=(cmd.description or "")[:600],
            tags=["CONFIG"],
            source="cli",
        ))
    for cmd in inherited:
        rid = f"CLI:{cmd.name}"
        provenance[rid] = "cli-inherit"
        out.append(Requirement(
            req_id=rid,
            title=cmd.name,
            section_number=None,
            description=(cmd.description or "")[:600],
            tags=["CONFIG"],
            source="cli",
        ))
    return out


def build_catalog(doc: Document | str | Path,
                   *,
                   rfc_paths: list[str | Path] | None = None,
                   cli_doc_path: str | Path | None = None,
                   anchor_re: re.Pattern[str] | None = None,
                   ) -> RequirementCatalog:
    """Build the unified requirements catalog from three sources.

    SFS extraction is required; RFC and CLI doc are optional. The caller
    is responsible for matching `catalog.requirements` against the flow
    catalog and passing the matched req IDs back via `mark_claimed()` so
    the synth-anchor list is correct.
    """
    if not isinstance(doc, Document):
        doc = parse(doc)

    provenance: dict[str, str] = {}

    # ── SFS requirements ──────────────────────────────────────────────
    spec_reqs = extract_requirements(doc, anchor_re=anchor_re)

    # ── RFC requirements (promoted to first-class) ────────────────────
    rfc_reqs: list[Requirement] = []
    if rfc_paths:
        from ate.planner.rfc_extractor import extract_rfc_requirements  # noqa: PLC0415
        for rp in rfc_paths:
            rfc_reqs.extend(extract_rfc_requirements(rp))

    requirements = _merge_requirements(spec_reqs, rfc_reqs, provenance)

    # ── CLI commands: extracted + inherited ───────────────────────────
    extracted_cmds: list[CliCommand] = []
    inherited_cmds: list[CliCommand] = []
    if cli_doc_path is not None:
        extracted_cmds = extract_commands(cli_doc_path)
        inherited_cmds = expand_inherited(extracted_cmds)
    cli_commands = extracted_cmds + inherited_cmds
    inherited_names = {c.name for c in inherited_cmds}

    # CLI commands also become synthetic requirements (`CLI:<name>`) so
    # downstream coverage tracking treats them uniformly.
    cli_anchors = _make_cli_anchors(extracted_cmds, inherited_cmds, provenance)
    requirements = cli_anchors + requirements  # CLI anchors first for stable order

    # ── Classify each req by SFS-vs-RFC relationship ──────────────────
    # Sets r.kind ∈ {base_sfs, delta, overlay, pointer,
    # sfs_with_rfc_context, rfc, cli} and r.rfc_links (RFC req_ids the
    # SFS req points at, resolved against the extracted RFC catalog).
    # Yossi 2026-05-21 follow-up: the AI enricher uses this to write
    # rows that contrast SFS-vs-RFC behaviour explicitly instead of
    # treating each req as a flat sibling.
    classify_all(requirements)

    return RequirementCatalog(
        requirements=requirements,
        cli_commands=cli_commands,
        synth_anchors=[],  # filled by mark_claimed()
        provenance=provenance,
        inherited_cmd_names=inherited_names,
    )


def mark_claimed(catalog: RequirementCatalog,
                  claimed_req_ids: set[str]) -> None:
    """After the generator has run flows against `catalog.requirements`,
    call this with the set of req IDs that ≥1 flow claimed. Populates
    `catalog.synth_anchors` with RFC requirements still unclaimed —
    those are the ones that will get auto-synthesized rows.
    """
    catalog.synth_anchors = _identify_synth_anchors(
        catalog.requirements, claimed_req_ids,
    )

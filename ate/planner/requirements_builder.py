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

import re
from dataclasses import dataclass, field
from pathlib import Path

from ate.ir import Document
from ate.parsers import parse
from ate.planner.cli_extractor import (
    CliCommand,
    extract_commands,
    mark_containers,
)
from ate.planner.cli_inheritance import expand as expand_inherited
from ate.planner.extractor import extract_requirements
from ate.planner.model import Requirement
from ate.planner.req_classifier import classify_all
from ate.planner.rfc_crosscheck import RfcCrossCheck
from ate.planner.rfc_crosscheck import reconcile as reconcile_rfcs


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
    # RFCs the SFS cites vs. the RFCs actually ingested. Surfaces the gap
    # Aleksey Burger flagged (2026-06-04): the SFS pointed at RFC 4364 et al.
    # that were never provided as inputs. `None` when no SFS text is available.
    rfc_crosscheck: RfcCrossCheck | None = None


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
        # Expand the inheritance table. There is no de-invention step any
        # more: `cli_inheritance` now reads the knobs' grammar off Exaware's
        # Command Reference Guide v8.X.0 instead of hand-curating it, so
        # there is nothing fabricated left to strip. `deinvent()` was the
        # right answer while the base manual was missing (Eyal Ozeri
        # 2026-07-06) and the wrong one once it arrived — stripping now would
        # discard the real ranges and defaults he then asked to have back
        # (2026-07-07: "removed, not corrected").
        inherited_cmds = expand_inherited(extracted_cmds)
    cli_commands = _scope_cli_to_evpn(extracted_cmds) + inherited_cmds
    # Re-run container marking over the combined set so a container's
    # child attributes include inherited sub-configs (e.g. `af-l2vpn evpn`
    # → allow-as-in, capability, …) — those arrive only after expansion.
    mark_containers(cli_commands)
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

    # ── RFC cross-check (Aleksey Burger, 2026-06-04) ──────────────────
    # Scan the SFS prose for every RFC it cites and reconcile against the
    # RFCs actually passed in via `rfc_paths`. A non-empty `.missing` means
    # the SFS points at RFCs the engine never ingested (e.g. RFC 4364).
    crosscheck = reconcile_rfcs(doc.full_text, rfc_paths or [])

    return RequirementCatalog(
        requirements=requirements,
        cli_commands=cli_commands,
        synth_anchors=[],  # filled by mark_claimed()
        provenance=provenance,
        inherited_cmd_names=inherited_names,
        rfc_crosscheck=crosscheck,
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


# ---------------------------------------------------------------------------
# Plan scoping — this is an EVPN test plan, not a VPLS one
# ---------------------------------------------------------------------------

#: Commands the EVPN CLI doc documents under BOTH `l2-services vpls` and
#: `l2-services evpn`, because one doc section serves both services.
#:
#: Eyal Ozeri, 2026-07-07: "the TP is for evpn" — VPLS rows do not belong in
#: it. The commands themselves do: `mac-limit` is a real EVPN knob. What has
#: to go is the VPLS *mode path*, which is what put
#: `configuration l2-services {vpls|evpn}` into the action text and gave the
#: plan a whole "CLI CONFIGURATION — L2-SERVICES VPLS" section.
_VPLS_MODE_HEAD = ("l2-services", "vpls")


def _is_vpls_path(path: list[str]) -> bool:
    """Whether a mode path descends through `l2-services vpls`."""
    for i in range(len(path) - 1):
        if tuple(path[i:i + 2]) == _VPLS_MODE_HEAD:
            return True
    return False


def _scope_cli_to_evpn(commands: list[CliCommand]) -> list[CliCommand]:
    """Drop VPLS from an EVPN plan, without dropping shared EVPN commands.

    A **plan step**, deliberately, not an extractor change: the extracted IR
    stays a faithful record of what the CLI doc says, including the VPLS modes,
    and only the deliverable is scoped. That keeps the golden IR stable and
    keeps the same extraction reusable for a VPLS plan later.

    Two cases, and conflating them is what made the first attempt at this
    wrong — it stripped the parameters off shared commands instead of stripping
    the mode:

    * **dual-mode** (`mac-limit`, `mac-aging-time`, `interface (VPLS/EVPN)`,
      `auto-discovery`, `export-rt`, `import-rt`) — keep the command, keep
      every parameter, and keep only its `…evpn` mode paths. The name's
      `(VPLS/EVPN)` marker is rewritten to `(EVPN)` so the banner does not
      advertise a service the plan does not cover.
    * **VPLS-only** (`mac-address-static (VPLS)`) — drop the command entirely.
      It has no EVPN mode path, so scoping it leaves nothing to test.
    """
    scoped: list[CliCommand] = []
    for cmd in commands:
        paths = cmd.mode_paths or ([cmd.mode_path] if cmd.mode_path else [])
        if not paths:
            scoped.append(cmd)
            continue
        evpn_paths = [p for p in paths if not _is_vpls_path(p)]
        if not evpn_paths:
            # VPLS-only: nothing of it belongs in an EVPN test plan.
            continue
        if len(evpn_paths) == len(paths):
            scoped.append(cmd)
            continue
        cmd.mode_paths = evpn_paths
        cmd.mode_path = evpn_paths[0]
        cmd.mode = "\n".join(" ".join(p) for p in evpn_paths)
        cmd.name = cmd.name.replace("(VPLS/EVPN)", "(EVPN)")
        scoped.append(cmd)
    return scoped

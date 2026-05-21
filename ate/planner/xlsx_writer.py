"""Write a Plan to xlsx — DHCP-snoopy 9-column shape (M1 client respin).

Layout (matches references/DHCP-snoopy_TP_with_PW.xlsx):

  - **Topic / Action / Req ID / Expectation / Monitor / Equipment /
    Build / Results / Comment** — 9 columns, atomic-row-under-topic-banner.
  - The generator still produces multi-line Setup/Action/Verify PlanRow
    blobs (so the AI-enrichment cache survives the shape change);
    `atomic_rows.rows_for_plan_row()` decomposes each blob into a banner
    row + N atomic action rows at render time.
  - RFC mandates that no flow claims are emitted by `generator.py` as
    first-class PlanRows (Yossi push-back 2026-05-21) — they flow
    through the enricher and render on the main sheet alongside flow
    rows, tinted green as "RFC mandate" so QA still sees the source.
  - **Coverage sheet** unchanged from the previous respin; reports
    requirement → flow coverage with the same orphan-highlight semantics
    as before.
  - **Feature Concept Catalog** stays at the top of the main sheet.

We do not modify the customer's original template file.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ate.planner.atomic_rows import AtomicRow, rows_for_plan_row
from ate.planner.feature_catalog import build_catalog
from ate.planner.flows import EVPN_FLOWS
from ate.planner.model import Plan, PlanRow, Requirement

# DHCP-snoopy 9-column schema. Headers chosen to match the reference TP
# exactly where possible (Topic / Action / Expectation / Monitor / Build /
# Results / Comment); Req ID and Equipment are added so traceability
# survives the shape change.
HEADER_ROW = [
    "Topic",
    "Action",
    "SFS / RFC Req ID",
    "Expectation",
    "Monitor (show / verify command)",
    "Test Equipment",
    "Build number",
    "Results (Pass\\Fail)",
    "Comment \\ Bug number",
]

FLOW_FILL = PatternFill("solid", fgColor="D7E4F4")
CAT_FILL = PatternFill("solid", fgColor="E9ECEF")
SUBCAT_FILL = PatternFill("solid", fgColor="F8F9FA")
HEADER_FILL = PatternFill("solid", fgColor="343A40")
CATALOG_FILL = PatternFill("solid", fgColor="DCE9F1")
CATALOG_GROUP_FILL = PatternFill("solid", fgColor="B6CCDC")
ORPHAN_FILL = PatternFill("solid", fgColor="F9E2D6")
HEADER_FONT = Font(color="FFFFFF", bold=True)
META_FONT = Font(bold=True)
WRAP = Alignment(wrap_text=True, vertical="top")
WRAP_LEFT = Alignment(wrap_text=True, vertical="top", horizontal="left")
THIN_BORDER = Border(
    left=Side(style="thin", color="CCCCCC"),
    right=Side(style="thin", color="CCCCCC"),
    top=Side(style="thin", color="CCCCCC"),
    bottom=Side(style="thin", color="CCCCCC"),
)


def _row_height_for(text: str) -> float:
    if not text:
        return 18
    lines = text.count("\n") + 1
    extra = sum(max(0, len(ln) // 70) for ln in text.split("\n"))
    return min(18 + 14 * (lines + extra - 1), 120)


def _write_catalog(ws, catalog: list, start_row: int) -> int:
    row = start_row
    cell = ws.cell(row=row, column=1, value="Feature Concept Catalog")
    cell.font = Font(bold=True, size=12, color="1F3A5F")
    row += 1
    cell = ws.cell(
        row=row, column=1,
        value=("EVPN concepts the plan covers — values sourced from the "
               "EVPN CLI doc and RFC 7432bis. Reviewers can map any plan "
               "row to its concept here."),
    )
    cell.alignment = WRAP_LEFT
    cell.font = Font(italic=True, color="555555")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
    row += 1
    for c, label in enumerate(("Concept", "Value", "Description / Source"), 1):
        cell = ws.cell(row=row, column=c, value=label)
        cell.font = HEADER_FONT
        cell.fill = CATALOG_GROUP_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.border = THIN_BORDER
    ws.row_dimensions[row].height = 22
    row += 1
    for entry in catalog:
        cell = ws.cell(row=row, column=1, value=entry.name)
        cell.font = META_FONT
        cell.fill = CATALOG_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.border = THIN_BORDER
        cell2 = ws.cell(row=row, column=2, value="(source)")
        cell2.fill = CATALOG_FILL
        cell2.font = Font(italic=True, color="555555")
        cell2.border = THIN_BORDER
        cell3 = ws.cell(row=row, column=3, value=entry.source)
        cell3.fill = CATALOG_FILL
        cell3.alignment = WRAP_LEFT
        cell3.font = Font(italic=True, color="555555")
        cell3.border = THIN_BORDER
        ws.row_dimensions[row].height = 20
        row += 1
        for value, description in entry.values:
            ws.cell(row=row, column=1).border = THIN_BORDER
            ws.cell(row=row, column=2, value=value).alignment = WRAP_LEFT
            ws.cell(row=row, column=2).border = THIN_BORDER
            ws.cell(row=row, column=3, value=description).alignment = WRAP_LEFT
            ws.cell(row=row, column=3).border = THIN_BORDER
            ws.row_dimensions[row].height = _row_height_for(description)
            row += 1
        if entry.notes:
            cell = ws.cell(row=row, column=1, value="(notes)")
            cell.font = Font(italic=True, color="555555")
            cell.border = THIN_BORDER
            ws.cell(row=row, column=2).border = THIN_BORDER
            cell3 = ws.cell(row=row, column=3, value=entry.notes)
            cell3.alignment = WRAP_LEFT
            cell3.font = Font(italic=True, color="555555")
            cell3.border = THIN_BORDER
            ws.row_dimensions[row].height = _row_height_for(entry.notes)
            row += 1
    return row


RFC_FILL = PatternFill("solid", fgColor="D4EDDA")      # RFC mandate row (normative)
INHERIT_FILL = PatternFill("solid", fgColor="E2D9F3")  # CLI-inheritance row


# Kind-priority for picking the most informative marker when a flow row
# aggregates multiple SFS reqs of different kinds. delta wins because a
# vendor-modified clause is the most surprising thing a QA engineer can
# encounter; overlay next; pointer last (it adds the least signal).
_KIND_PRIORITY = ("delta", "overlay", "pointer",
                  "sfs_with_rfc_context", "base_sfs")


def _provenance_for_row(r: PlanRow,
                        req_by_id: dict[str, Requirement],
                        inherited_names: set[str]) -> str:
    """Compute the provenance / kind-marker string for a PlanRow.

    Returns one of:
      "rfc-orphan"          — RFC mandate row (generator-emitted synth)
      "cli-inherit"         — BGP sub-config row
      "delta:<rfc_link>"    — SFS req that modifies an RFC clause
      "overlay:<rfc_link>"  — SFS req that adds beyond an RFC clause
      "pointer:<rfc_link>"  — SFS req that just points at an RFC clause
      ""                    — default (flow row anchored by base SFS)

    The kind markers carry the linked RFC req_id (when known) so the
    Comment column can read "delta from RFC7432bis-§8.5" — a QA engineer
    sees the SFS-vs-RFC relationship without opening the source docs.
    """
    # Source markers first — they win over kind markers because rfc-
    # orphan / cli-inherit rows have their own dedicated visual tier.
    is_inherited = bool(r.sub_category and r.sub_category in inherited_names)
    is_rfc_orphan = (not r.flow_id) and r.sfs_requirement_id.startswith("RFC")
    if is_rfc_orphan:
        return "rfc-orphan"
    if is_inherited:
        return "cli-inherit"

    # Walk covered_req_ids → pick the SFS req with the highest-priority
    # kind. RFC reqs in covered_req_ids are skipped (their relationship
    # is already implicit — "rfc"). Multi-req flow rows often mix SFS
    # and RFC; we want the SFS relationship marker.
    best_kind = ""
    best_link = ""
    best_priority = len(_KIND_PRIORITY)
    for rid in r.covered_req_ids:
        req = req_by_id.get(rid)
        if req is None or req.source != "spec":
            continue
        if req.kind not in _KIND_PRIORITY:
            continue
        priority = _KIND_PRIORITY.index(req.kind)
        if priority < best_priority:
            best_priority = priority
            best_kind = req.kind
            best_link = req.rfc_links[0] if req.rfc_links else ""

    if best_kind in ("delta", "overlay", "pointer"):
        return f"{best_kind}:{best_link}"
    return ""


def _comment_for_provenance(provenance: str) -> str:
    """Map provenance string → human-readable Comment-column marker.

    Yossi 2026-05-21 follow-up: SFS reqs classified as delta / overlay /
    pointer carry the linked RFC req_id in the provenance string
    ("delta:RFC7432bis-§8.5") so a QA engineer can see the SFS-vs-RFC
    relationship at a glance. The two source markers (rfc-orphan,
    cli-inherit) take the same column but never co-occur with kind
    markers since RFC-orphan reqs have kind="rfc" and inherited CLI
    rows have kind="cli".
    """
    if provenance == "rfc-orphan":
        return "RFC mandate"
    if provenance == "cli-inherit":
        return "CLI inheritance"
    if provenance.startswith("delta:"):
        link = provenance.split(":", 1)[1]
        return f"delta from {link}" if link else "delta from RFC base"
    if provenance.startswith("overlay:"):
        link = provenance.split(":", 1)[1]
        return f"overlay on {link}" if link else "overlay on RFC base"
    if provenance.startswith("pointer:"):
        link = provenance.split(":", 1)[1]
        return f"pointer to {link}" if link else "pointer to RFC"
    return ""


def _fill_for_provenance(provenance: str) -> PatternFill | None:
    """Banner / row tint per provenance. Returns None for default (flow)."""
    if provenance == "rfc-orphan":
        return RFC_FILL
    if provenance == "cli-inherit":
        return INHERIT_FILL
    # delta / overlay / pointer rows keep the flow tint — the kind
    # marker in col 9 carries the relationship info without piling on
    # visual noise.
    return None


def _write_atomic_row(ws, ar: AtomicRow, row: int) -> int:
    """Render one AtomicRow into the 9-column schema. Banner rows merge
    A→F so the topic reads like a section header (matches DHCP-snoopy).
    """
    comment = _comment_for_provenance(ar.provenance)
    tint = _fill_for_provenance(ar.provenance)

    if ar.is_banner:
        cell = ws.cell(row=row, column=1, value=ar.topic)
        cell.font = META_FONT
        fill = tint or FLOW_FILL
        cell.fill = fill
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        for c in range(2, len(HEADER_ROW) + 1):
            ws.cell(row=row, column=c).fill = fill
        ws.merge_cells(start_row=row, start_column=1,
                        end_row=row, end_column=6)
        if comment:
            ws.cell(row=row, column=9, value=comment)
        ws.row_dimensions[row].height = 22
        return row + 1

    # Continuation row: col A intentionally empty (inherits topic above).
    ws.cell(row=row, column=1, value="").alignment = WRAP_LEFT
    ws.cell(row=row, column=2, value=ar.action).alignment = WRAP_LEFT
    ws.cell(row=row, column=3,
            value=", ".join(ar.req_ids) if ar.req_ids else "")\
        .alignment = WRAP_LEFT
    ws.cell(row=row, column=4, value=ar.expectation).alignment = WRAP_LEFT
    ws.cell(row=row, column=5,
            value=", ".join(ar.monitor) if ar.monitor else "")\
        .alignment = WRAP_LEFT
    ws.cell(row=row, column=6, value=ar.equipment).alignment = WRAP_LEFT
    ws.cell(row=row, column=9, value=comment).alignment = WRAP_LEFT
    # Subtle row tint for source-marker rows (RFC / inherit). Delta /
    # overlay / pointer rows do not tint — the comment marker suffices.
    if tint is not None:
        for c in range(1, len(HEADER_ROW) + 1):
            ws.cell(row=row, column=c).fill = tint
    ws.row_dimensions[row].height = _row_height_for(ar.action)
    return row + 1


def _write_flow_banner(ws, flow_id: str, flow_name: str, summary: str,
                       covered_ids: list[str], row: int) -> int:
    """Render a Flow banner row spanning the data columns. The banner
    states the flow ID + name, a short summary, and the covered req-IDs
    so reviewers can see scope before reading per-category rows.
    """
    label = f"{flow_id} — {flow_name}"
    cell = ws.cell(row=row, column=1, value=label)
    cell.font = META_FONT
    cell.fill = FLOW_FILL
    cell.alignment = Alignment(wrap_text=True, vertical="center")
    for c in range(2, len(HEADER_ROW) + 1):
        ws.cell(row=row, column=c).fill = FLOW_FILL
    ws.merge_cells(start_row=row, start_column=2, end_row=row,
                    end_column=len(HEADER_ROW))
    body = summary
    if covered_ids:
        body += f"\nCovers: {', '.join(covered_ids)}"
    cell2 = ws.cell(row=row, column=2, value=body)
    cell2.alignment = WRAP_LEFT
    cell2.fill = FLOW_FILL
    ws.row_dimensions[row].height = _row_height_for(body)
    return row + 1


# Known orphan requirements that are deliberately out of M1 scope.
# Reviewers see these in the Coverage sheet annotated with the reason
# rather than a bare "(orphan)" — so a 100% strict reading still
# returns a defensible answer.
#
# Yossi 2026-05-21: RFC mandates do not get out-of-scope exemptions any
# more — every RFC clause is promoted to a first-class row by the synth
# path in generator.py. Only SFS-side meta-requirements stay here.
_INTENTIONAL_ORPHANS: dict[str, str] = {
    "EVPNS-REQ#10": (
        "(orphan: META — lists supported RFCs; not a runnable use case)"
    ),
}


def _write_coverage_sheet(wb, plan: Plan) -> None:
    """Render the Coverage sheet: req-id → flows-that-cover-it.

    Orphans (req-IDs no flow claims) are highlighted at the top so the
    reviewer can extend the flow catalog or accept that some
    requirements are covered exclusively by the per-command CLI rows.
    """
    coverage: dict[str, list[str]] = plan.__dict__.get("_coverage", {})
    orphans: list[str] = plan.__dict__.get("_orphans", [])
    ws = wb.create_sheet("Coverage")
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 60
    ws.column_dimensions["D"].width = 50

    row = 1
    ws.cell(row=row, column=1, value="Requirement → Flow coverage").font = (
        Font(bold=True, size=12, color="1F3A5F")
    )
    row += 1
    cell = ws.cell(
        row=row, column=1,
        value=("Each spec / RFC requirement listed below maps to the flows "
               "(use cases) that exercise it. Requirements highlighted in "
               "orange are not claimed by any flow — the flow catalog "
               "should be extended to cover them, or they are covered "
               "exclusively by the per-command CLI Configuration rows."),
    )
    cell.alignment = WRAP_LEFT
    cell.font = Font(italic=True, color="555555")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    ws.row_dimensions[row].height = _row_height_for(cell.value)
    row += 2

    for c, label in enumerate(
        ("Req ID", "Section", "Title", "Covering Flow IDs"), 1
    ):
        cell = ws.cell(row=row, column=c, value=label)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[row].height = 24
    row += 1

    # Stable order: spec reqs first (EVPNS-REQ#NN by numeric N), RFC reqs after.
    reqs_in_order = [r for r in plan.requirements if not r.req_id.startswith("CLI:")]
    for r in reqs_in_order:
        flow_ids = coverage.get(r.req_id, [])
        if flow_ids:
            cov_cell = ", ".join(flow_ids)
        else:
            cov_cell = _INTENTIONAL_ORPHANS.get(r.req_id, "(orphan)")
        cells_row = [
            r.req_id,
            r.section_number or "",
            r.title,
            cov_cell,
        ]
        for c, val in enumerate(cells_row, 1):
            cell = ws.cell(row=row, column=c, value=val)
            cell.alignment = WRAP_LEFT
        if r.req_id in orphans:
            for c in range(1, 5):
                ws.cell(row=row, column=c).fill = ORPHAN_FILL
        ws.row_dimensions[row].height = _row_height_for(r.title)
        row += 1

    # Summary block
    row += 1
    n_total = len(reqs_in_order)
    n_orphans = len(orphans)
    n_covered = n_total - n_orphans
    pct = (100.0 * n_covered / n_total) if n_total else 0.0
    summary = (
        f"Coverage summary: {n_covered}/{n_total} "
        f"requirements claimed by ≥ 1 flow ({pct:.1f}%); "
        f"{n_orphans} orphan requirement(s)."
    )
    cell = ws.cell(row=row, column=1, value=summary)
    cell.font = Font(bold=True, color="1F3A5F")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)


def _write_flows_sheet(wb, plan: Plan) -> None:
    """A second auxiliary sheet: one row per flow with its scope, equipment,
    categories, and covered req-IDs. Useful for QA leads selecting which
    flows to schedule for a given test cycle.
    """
    flows_with_reqs = plan.__dict__.get("_flows_with_reqs", [])
    ws = wb.create_sheet("Flows")
    widths = [14, 40, 60, 30, 30, 50]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    headers = ["Flow ID", "Flow Name", "Summary", "Equipment",
               "Categories Tested", "Covered Req IDs"]
    for c, label in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=label)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[1].height = 28

    row = 2
    # Always render the full catalog so reviewers can also see flows
    # that produced no rows (e.g. because no req matched the selector).
    # Coverage-driven flows (scale, upgrade, NETCONF, OTF, soak, access-
    # interface variants) intentionally have no requirement anchor —
    # they are test techniques applied broadly. Render them with a
    # distinct marker so reviewers don't read the empty cell as a gap.
    coverage_fill = PatternFill("solid", fgColor="DCE9F1")  # neutral blue
    active_ids = {f.id for f, _ in flows_with_reqs}
    for flow in EVPN_FLOWS:
        covered = next((c for f, c in flows_with_reqs if f.id == flow.id), [])
        if covered:
            ids = ", ".join(r.req_id for r in covered)
        elif flow.coverage_driven:
            ids = (
                "(coverage-driven flow — test technique applied broadly; "
                "no single requirement anchor)"
            )
        else:
            ids = "(no req matched — flow catalog gap)"
        cells_row = [
            flow.id, flow.name, flow.summary, flow.equipment,
            ", ".join(flow.categories), ids,
        ]
        for c, val in enumerate(cells_row, 1):
            cell = ws.cell(row=row, column=c, value=val)
            cell.alignment = WRAP_LEFT
        if flow.id not in active_ids:
            # Genuinely inactive — flag orange.
            for c in range(1, len(headers) + 1):
                ws.cell(row=row, column=c).fill = ORPHAN_FILL
        elif not covered and flow.coverage_driven:
            # Active but coverage-driven — neutral blue, not alarming.
            for c in range(1, len(headers) + 1):
                ws.cell(row=row, column=c).fill = coverage_fill
        ws.row_dimensions[row].height = _row_height_for(flow.summary)
        row += 1


def write_xlsx(plan: Plan, output_path: str | Path,
               cli_doc_path: str | Path | None = None) -> Path:
    output_path = Path(output_path)
    wb = Workbook()
    ws = wb.active
    ws.title = "Test Plan Topics"

    # 9-column widths matched to DHCP-snoopy reference TP.
    # Topic | Action | Req ID | Expectation | Monitor | Equipment | Build | Results | Comment
    widths = [32, 60, 22, 60, 36, 28, 12, 14, 28]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    row = 1
    ws.cell(row=row, column=1, value=f"Feature: {plan.feature_name}").font = META_FONT
    row += 1
    ws.cell(row=row, column=1, value=f"Source: {plan.source_path}")
    row += 1
    ws.cell(row=row, column=1, value="Machine vendors").font = META_FONT
    ws.cell(row=row, column=2, value=plan.machine_vendor)
    row += 1
    ws.cell(row=row, column=1, value="Machine types").font = META_FONT
    ws.cell(row=row, column=2, value=plan.machine_types)
    row += 1
    ws.cell(row=row, column=1, value="IP versions").font = META_FONT
    ws.cell(row=row, column=2, value=plan.ip_versions)
    row += 1
    ws.cell(row=row, column=1, value="Interfaces").font = META_FONT
    ws.cell(row=row, column=2, value=plan.interfaces)
    row += 1
    ws.cell(row=row, column=1, value=f"Requirements found: {plan.n_requirements}").font = META_FONT
    row += 1
    flows_with_reqs = plan.__dict__.get("_flows_with_reqs", [])
    n_anchored = sum(1 for f, c in flows_with_reqs if c)
    n_coverage = sum(1 for f, c in flows_with_reqs
                     if not c and f.coverage_driven)
    n_dormant = len(EVPN_FLOWS) - len(flows_with_reqs)
    flow_summary = (
        f"Flows: {n_anchored} requirement-anchored + "
        f"{n_coverage} coverage-driven (test technique, applies broadly) "
        f"= {n_anchored + n_coverage} active of {len(EVPN_FLOWS)} "
        f"catalogued"
    )
    if n_dormant:
        flow_summary += f"; {n_dormant} catalogued but inactive in this run"
    ws.cell(row=row, column=1, value=flow_summary).font = META_FONT
    row += 2

    catalog = build_catalog(cli_doc_path)
    if catalog:
        row = _write_catalog(ws, catalog, row)
        row += 1

    for c, label in enumerate(HEADER_ROW, 1):
        cell = ws.cell(row=row, column=c, value=label)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[row].height = 36
    row += 1
    ws.freeze_panes = ws.cell(row=row, column=1).coordinate

    # ── Body: PlanRow blobs → AtomicRow stream (DHCP-snoopy shape) ────
    # The generator still emits multi-line Setup/Action/Verify PlanRow
    # blobs (so the AI-enrichment cache survives the shape change);
    # atomic_rows decomposes each blob into a banner + atomic action
    # rows that match the reference TP's per-action layout.
    flow_lookup = {f.id: f for f in EVPN_FLOWS}
    inherited_names = set()
    catalog = plan.__dict__.get("_catalog")
    if catalog is not None:
        inherited_names = set(catalog.inherited_cmd_names)

    # Build a req_by_id lookup so we can read each PlanRow's anchor
    # req kind (delta / overlay / pointer) — Yossi 2026-05-21 follow-up.
    req_by_id = {r.req_id: r for r in plan.requirements}

    # Build the atomic-row stream. Order: CLI command rows (per
    # command), then flow rows (per flow + category), then RFC-mandate
    # rows (Yossi 2026-05-21: first-class, on the main sheet).
    # `generator.py` already emitted RFC orphans as PlanRows so they
    # flow through the enricher; the only thing we do here is stamp
    # provenance for tinting + Comment-column marker.
    atomic_stream: list[AtomicRow] = []
    last_topic: str | None = None
    for r in plan.rows:
        provenance = _provenance_for_row(r, req_by_id, inherited_names)
        # Suppress banner if it would repeat the previous banner (e.g.
        # multiple PlanRows for the same CLI command).
        topic_now = (f"{r.flow_id} — {r.flow_name}" if r.flow_id
                      else (r.sub_category or r.category or ""))
        atomic_stream.extend(rows_for_plan_row(
            r, flow_lookup=flow_lookup,
            emit_banner=(topic_now != last_topic),
            provenance=provenance,
        ))
        last_topic = topic_now

    for ar in atomic_stream:
        row = _write_atomic_row(ws, ar, row)

    # ── Requirements traceability sheet ────────────────────────────────
    ws2 = wb.create_sheet("Requirements")
    ws2.append(["Req ID", "Section", "Title", "Description (truncated)"])
    for c in range(1, 5):
        cell = ws2.cell(row=1, column=c)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
    ws2.column_dimensions["A"].width = 18
    ws2.column_dimensions["B"].width = 12
    ws2.column_dimensions["C"].width = 50
    ws2.column_dimensions["D"].width = 80
    for r in plan.requirements:
        ws2.append([r.req_id, r.section_number or "", r.title,
                    (r.description[:300] + "…")
                    if len(r.description) > 300 else r.description])

    _write_flows_sheet(wb, plan)
    _write_coverage_sheet(wb, plan)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path

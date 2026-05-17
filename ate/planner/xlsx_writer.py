"""Write a Plan to xlsx — DHCP-snoopy 9-column shape (M1 client respin).

Layout (matches references/DHCP-snoopy_TP_with_PW.xlsx):

  - **Topic / Action / Req ID / Expectation / Monitor / Equipment /
    Build / Results / Comment** — 9 columns, atomic-row-under-topic-banner.
  - The generator still produces multi-line Setup/Action/Verify PlanRow
    blobs (so the AI-enrichment cache survives the shape change);
    `atomic_rows.rows_for_plan_row()` decomposes each blob into a banner
    row + N atomic action rows at render time.
  - **Synthesized — Review** sheet lists every row whose provenance is
    `synth` (auto-generated for an unclaimed RFC MUST) or `cli-inherit`
    (BGP-neighbor sub-config from the inheritance table, not in the EVPN
    CLI doc). Closes Eyal's "RFC must drive the TP" feedback by giving
    QA an explicit list of what was mechanically produced.
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

from ate.planner.atomic_rows import (
    AtomicRow,
    rows_for_cli_inherited,
    rows_for_plan_row,
    rows_for_synth_rfc,
)
from ate.planner.cli_inheritance import inheritance_source_for
from ate.planner.feature_catalog import build_catalog
from ate.planner.flows import EVPN_FLOWS
from ate.planner.model import Plan

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


SYNTH_FILL = PatternFill("solid", fgColor="FFF3CD")    # auto-synthesized RFC row
INHERIT_FILL = PatternFill("solid", fgColor="E2D9F3")  # CLI-inheritance row


def _write_atomic_row(ws, ar: AtomicRow, row: int) -> int:
    """Render one AtomicRow into the 9-column schema. Banner rows merge
    A→F so the topic reads like a section header (matches DHCP-snoopy)."""
    if ar.is_banner:
        cell = ws.cell(row=row, column=1, value=ar.topic)
        cell.font = META_FONT
        fill = FLOW_FILL
        if ar.provenance == "synth":
            fill = SYNTH_FILL
        elif ar.provenance == "cli-inherit":
            fill = INHERIT_FILL
        cell.fill = fill
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        for c in range(2, len(HEADER_ROW) + 1):
            ws.cell(row=row, column=c).fill = fill
        ws.merge_cells(start_row=row, start_column=1,
                        end_row=row, end_column=6)
        if ar.provenance == "synth":
            ws.cell(row=row, column=9, value="synthesized — review")
        elif ar.provenance == "cli-inherit":
            ws.cell(row=row, column=9,
                    value="CLI inheritance — review")
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
    # Build / Results / Comment columns left blank for QA fill-in. Synth
    # / inherit provenance bubbles up to col 9 so the Comment column
    # makes the row's auto-generated nature visible alongside the data.
    comment = ""
    if ar.provenance == "synth":
        comment = "synthesized — review"
    elif ar.provenance == "cli-inherit":
        comment = "CLI inheritance — review"
    ws.cell(row=row, column=9, value=comment).alignment = WRAP_LEFT
    # Subtle row tint so synth/inherit rows still stand out.
    if ar.provenance == "synth":
        for c in range(1, len(HEADER_ROW) + 1):
            ws.cell(row=row, column=c).fill = SYNTH_FILL
    elif ar.provenance == "cli-inherit":
        for c in range(1, len(HEADER_ROW) + 1):
            ws.cell(row=row, column=c).fill = INHERIT_FILL
    ws.row_dimensions[row].height = _row_height_for(ar.action)
    return row + 1


def _write_synth_review_sheet(wb, atomic_rows: list[AtomicRow]) -> None:
    """List every banner-row whose provenance ∈ {synth, cli-inherit} on
    a dedicated sheet so QA can see exactly which rows are mechanical /
    inherited vs. hand-designed. Format:

        Source                | Anchor              | Why synthesized                              | Recommended QA action
        RFC mandate (synth)   | RFC7432bis-§10.1.1  | No flow claims this RFC MUST                  | Refine action steps + monitor; promote to a flow if generalisable
        CLI inheritance       | CLI:allow-as-in      | BGP sub-config inherited from parent protocol | Validate against device behaviour; replace when BGP CLI doc lands
    """
    ws = wb.create_sheet("Synthesized — Review")
    widths = [22, 36, 70, 70]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    headers = ["Source", "Anchor",
                "Why this row is here",
                "Recommended QA action"]
    for c, label in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=label)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[1].height = 28

    intro = (
        "Rows on this sheet were produced mechanically by the Requirements "
        "Builder, not by a hand-designed flow. Review each one before "
        "executing — auto-generated content is correct-by-construction in "
        "intent but coarse in detail. The main 'Test Plan Topics' sheet "
        "tints these rows yellow (RFC-synth) or violet (CLI-inherit) "
        "so they are recognisable in context."
    )
    cell = ws.cell(row=2, column=1, value=intro)
    cell.alignment = WRAP_LEFT
    cell.font = Font(italic=True, color="555555")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=4)
    ws.row_dimensions[2].height = _row_height_for(intro)

    row = 4
    seen: set[str] = set()
    for ar in atomic_rows:
        if not ar.is_banner or ar.provenance not in ("synth", "cli-inherit"):
            continue
        topic = ar.topic
        if topic in seen:
            continue
        seen.add(topic)
        if ar.provenance == "synth":
            source = "RFC mandate (synth)"
            why = ("No flow in EVPN_FLOWS claimed this RFC MUST clause. "
                   "Auto-synthesised so the mandate isn't silently dropped.")
            action = ("Refine the action / monitor / expectation against "
                      "the actual device behaviour; if the use case applies "
                      "broadly, promote to a named Flow.")
        else:
            source = "CLI inheritance"
            inherit_source = inheritance_source_for(
                topic.split(":")[-1].strip())
            why = ("Sub-config inherited from the parent protocol's CLI "
                   "(e.g. BGP). Not documented in the EVPN CLI doc.")
            if inherit_source:
                why += f"  Source: {inherit_source}"
            action = ("Validate the syntax + defaults against the actual "
                      "device behaviour. Replace this entry once the "
                      "Exaware BGP CLI manual is integrated.")
        for c, val in enumerate([source, topic, why, action], 1):
            cell = ws.cell(row=row, column=c, value=val)
            cell.alignment = WRAP_LEFT
        ws.row_dimensions[row].height = _row_height_for(why)
        row += 1


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
_INTENTIONAL_ORPHANS: dict[str, str] = {
    "EVPNS-REQ#10": (
        "(orphan: META — lists supported RFCs; not a runnable use case)"
    ),
    "RFC7432bis-§10.1.1": (
        "(orphan: IRB / L3 EVPN scope — out of M1 single-router L2 plan)"
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

    # Build the full atomic-row stream so the Synthesized — Review sheet
    # can scan it too. Order: CLI command rows (per command), then flow
    # rows (per flow + category), then auto-synthesized RFC rows.
    atomic_stream: list[AtomicRow] = []
    last_topic: str | None = None
    for r in plan.rows:
        # Detect inherited CLI rows by sub-category (CLI command name);
        # those rows get an "cli-inherit" provenance stamp so the
        # Synthesized — Review sheet surfaces them.
        is_inherited = bool(
            r.sub_category and r.sub_category in inherited_names
        )
        # Suppress banner if it would repeat the previous banner (e.g.
        # multiple PlanRows for the same CLI command).
        topic_now = (f"{r.flow_id} — {r.flow_name}" if r.flow_id
                      else (r.sub_category or r.category or ""))
        atomic_stream.extend(rows_for_plan_row(
            r, flow_lookup=flow_lookup,
            emit_banner=(topic_now != last_topic),
            provenance=("cli-inherit" if is_inherited else ""),
        ))
        last_topic = topic_now

    # Auto-synthesized RFC rows last (Eyal-respin requirement).
    if catalog is not None:
        for req in catalog.synth_anchors:
            atomic_stream.extend(rows_for_synth_rfc(req))

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
    # Synthesized — Review must come after the body so atomic_stream is
    # populated. The sheet itself reads the stream and emits one summary
    # row per provenance-tagged banner.
    _write_synth_review_sheet(wb, atomic_stream)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path

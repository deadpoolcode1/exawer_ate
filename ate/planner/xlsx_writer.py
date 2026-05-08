"""Write a Plan to xlsx matching Exaware's template structure (M1 respin).

Original template columns (per Feature Name Test Plan Template.xlsx):
  Category / Action\\Steps / SFS Requirement id / Expectation /
  Build / Results / Comment

M1 respin adds one column — **Test Equipment** — between Expectation
and Build, addressing Yossi's "missing IXIA indications" review gap.
The column tells QA which test rig the row needs (DUT only, IXIA traffic
gen, neighbor PE, scale rig, etc.) without scanning prose. Action\\Steps
also use the Setup → Action → Verify scaffolding so QA can follow each
row without inferring procedure from generic statements.

The xlsx now also opens with a **Feature Concept Catalog** table at
the top — service types, ESI types, route types, DF algorithms, BUM
modes, control word — addressing Yossi's "feature understanding"
review gap at the document level (not just per-row). The catalog is
sourced from the CLI doc + RFC 7432bis where applicable.

We do NOT modify the customer's original template file.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ate.planner.feature_catalog import build_catalog
from ate.planner.model import Plan

# Column order — adds Test Equipment between Expectation and Build.
# Sub-Category appears as a softened secondary header column for the
# CLI section, where rows are grouped by command.
HEADER_ROW = [
    "Category",
    "Sub-Category",
    "Action\\Steps",
    "SFS Requirement id\n(For Traceability)",
    "Expectation",
    "Test Equipment",
    "Build number",
    "Results (Pass\\Fail)",
    "Comment \\ Bug number if failed",
]

CAT_FILL = PatternFill("solid", fgColor="E9ECEF")
SUBCAT_FILL = PatternFill("solid", fgColor="F8F9FA")
HEADER_FILL = PatternFill("solid", fgColor="343A40")
CATALOG_FILL = PatternFill("solid", fgColor="DCE9F1")
CATALOG_GROUP_FILL = PatternFill("solid", fgColor="B6CCDC")
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
    """Pick a row height that fits a multi-line Setup/Action/Verify cell.

    openpyxl autosize is unreliable across viewers; we set heights
    explicitly so Setup/Action/Verify renders without manual click-to-
    expand on first open. ~14 px per visual line, capped at 90 px.
    """
    if not text:
        return 18
    lines = text.count("\n") + 1
    # Long lines wrap once or twice in the ~64-wide Action column
    extra = sum(max(0, len(ln) // 70) for ln in text.split("\n"))
    return min(18 + 14 * (lines + extra - 1), 96)


def _write_catalog(ws, catalog: list, start_row: int) -> int:
    """Render the Feature Concept Catalog as a labelled table block.

    Layout: one banner row per group, then one row per (value, description)
    pair, then a notes row. Uses columns 1-3: Concept | Value | Description.
    """
    row = start_row
    # Section title
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
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
    row += 1
    # Catalog table header
    for c, label in enumerate(("Concept", "Value", "Description / Source"), 1):
        cell = ws.cell(row=row, column=c, value=label)
        cell.font = HEADER_FONT
        cell.fill = CATALOG_GROUP_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.border = THIN_BORDER
    ws.row_dimensions[row].height = 22
    row += 1

    for entry in catalog:
        # Group banner row
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


def write_xlsx(plan: Plan, output_path: str | Path,
               cli_doc_path: str | Path | None = None) -> Path:
    output_path = Path(output_path)
    wb = Workbook()
    ws = wb.active
    ws.title = "Test Plan Topics"

    # Column widths — tuned for the new layout; Action+Expectation
    # carry multi-line Setup/Action/Verify scaffolding so they need width.
    widths = [22, 24, 64, 22, 50, 30, 14, 14, 28]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # Header — feature metadata block
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
    row += 2  # blank line

    # ── Feature Concept Catalog ─────────────────────────────────────────
    catalog = build_catalog(cli_doc_path)
    if catalog:
        row = _write_catalog(ws, catalog, row)
        row += 1  # blank line before column header

    # Column header row
    for c, label in enumerate(HEADER_ROW, 1):
        cell = ws.cell(row=row, column=c, value=label)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[row].height = 36
    row += 1
    # Freeze the metadata block + catalog + column header so they
    # stay visible while QA scrolls through the row body.
    ws.freeze_panes = ws.cell(row=row, column=1).coordinate

    # Group rows by Category preserving order; emit each Category as a
    # banner row followed by its action rows. Inside CLI configuration
    # we further group by sub_category (one banner per command name).
    last_category: str | None = None
    last_subcategory: str | None = None
    for r in plan.rows:
        if r.category != last_category:
            cell = ws.cell(row=row, column=1, value=r.category)
            cell.font = META_FONT
            cell.fill = CAT_FILL
            for c in range(2, len(HEADER_ROW) + 1):
                ws.cell(row=row, column=c).fill = CAT_FILL
            row += 1
            last_category = r.category
            last_subcategory = None
        if r.sub_category and r.sub_category != last_subcategory:
            cell = ws.cell(row=row, column=2,
                           value=f"command: {r.sub_category}")
            cell.font = META_FONT
            cell.fill = SUBCAT_FILL
            for c in (1, 3, 4, 5, 6, 7, 8, 9):
                ws.cell(row=row, column=c).fill = SUBCAT_FILL
            row += 1
            last_subcategory = r.sub_category

        # Data row — column order matches HEADER_ROW
        ws.cell(row=row, column=1, value="")
        ws.cell(row=row, column=2, value=r.sub_category or "")
        ws.cell(row=row, column=3, value=r.action_steps).alignment = WRAP
        ws.cell(row=row, column=4, value=r.sfs_requirement_id)
        ws.cell(row=row, column=5, value=r.expectation).alignment = WRAP
        ws.cell(row=row, column=6, value=r.equipment).alignment = WRAP
        # Columns 7/8/9 (Build / Results / Comment) — left blank for QA
        ws.row_dimensions[row].height = _row_height_for(r.action_steps)
        row += 1

    # Second sheet: requirements traceability summary (unchanged column shape).
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
                    (r.description[:300] + "…") if len(r.description) > 300 else r.description])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path

"""Write a Plan to xlsx matching Exaware's template structure.

Columns (per Feature Name Test Plan Template.xlsx, sheet "Test Plan Topics"):
  A: Category
  B: Action\\Steps
  C: SFS Requirement id (For Traceability)
  D: Expectation
  E: Build number
  F: Results (Pass\\Fail)
  G: Comment \\ Bug number if failed

We do NOT modify the customer's original template file. We write a new xlsx
that mirrors its shape — header rows + per-Category sections.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ate.planner.model import Plan

HEADER_ROW = ["Category", "Action\\Steps",
              "SFS Requirement id\n(For Traceability)",
              "Expectation", "Build number",
              "Results (Pass\\Fail)",
              "Comment \\ Bug number if failed"]

CAT_FILL = PatternFill("solid", fgColor="E9ECEF")
HEADER_FILL = PatternFill("solid", fgColor="343A40")
HEADER_FONT = Font(color="FFFFFF", bold=True)
META_FONT = Font(bold=True)


def write_xlsx(plan: Plan, output_path: str | Path) -> Path:
    output_path = Path(output_path)
    wb = Workbook()
    ws = wb.active
    ws.title = "Test Plan Topics"

    # Column widths
    widths = [22, 60, 22, 50, 14, 14, 28]
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

    # Column header row
    for c, label in enumerate(HEADER_ROW, 1):
        cell = ws.cell(row=row, column=c, value=label)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[row].height = 36
    row += 1

    # Group rows by Category preserving order, then emit each Category
    # as a header row followed by its action rows.
    seen_categories: set[str] = set()
    last_category: str | None = None
    for r in plan.rows:
        if r.category != last_category:
            # Category header row
            cell = ws.cell(row=row, column=1, value=r.category)
            cell.font = META_FONT
            cell.fill = CAT_FILL
            for c in range(2, 8):
                ws.cell(row=row, column=c).fill = CAT_FILL
            row += 1
            last_category = r.category
            seen_categories.add(r.category)
        ws.cell(row=row, column=1, value="")
        ws.cell(row=row, column=2, value=r.action_steps).alignment = Alignment(wrap_text=True)
        ws.cell(row=row, column=3, value=r.sfs_requirement_id)
        ws.cell(row=row, column=4, value=r.expectation).alignment = Alignment(wrap_text=True)
        # Columns E/F/G left blank — filled by the QA engineer at runtime.
        row += 1

    # A second sheet: requirements traceability summary
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

"""Planner tests — IR → Plan → xlsx (M1 deliverable verification)."""
from __future__ import annotations

from pathlib import Path

import openpyxl

from ate.parsers import parse
from ate.planner import generate_plan, generate_plan_to_xlsx
from ate.planner.categories import ALL_CATEGORIES
from ate.planner.extractor import extract_requirements

ROOT = Path(__file__).resolve().parents[1]
EVPN_SPEC = ROOT / "tests/corpus/tier_a/EVPN System Specification 1.00.docx"


# ─── Requirement extraction ─────────────────────────────────────────────────

def test_extracts_evpn_anchors_from_evpn_spec() -> None:
    d = parse(EVPN_SPEC)
    reqs = extract_requirements(d)
    assert len(reqs) >= 30, f"expected ≥30 requirements, got {len(reqs)}"
    # First anchor should be EVPNS-REQ#10
    assert reqs[0].req_id == "EVPNS-REQ#10"
    # Each requirement has a non-empty title
    assert all(r.title for r in reqs), "some requirements lack titles"


def test_extractor_dedupes_repeated_anchors() -> None:
    d = parse(EVPN_SPEC)
    reqs = extract_requirements(d)
    ids = [r.req_id for r in reqs]
    assert len(ids) == len(set(ids)), "extractor returned duplicate req_ids"


# ─── Plan model ─────────────────────────────────────────────────────────────

def test_plan_from_evpn_spec_uses_template_categories() -> None:
    plan = generate_plan(EVPN_SPEC)
    assert plan.feature_name, "feature_name must be set"
    assert plan.n_requirements >= 30
    # Every category referenced in plan rows must be one of the template's
    rows_categories = {r.category for r in plan.rows}
    for cat in rows_categories:
        assert cat in ALL_CATEGORIES, f"unexpected category {cat!r} in plan"
    # Tech-support always applies (in ALWAYS_CATEGORIES)
    assert "Tech-support" in rows_categories


def test_plan_rows_are_traced_to_a_requirement() -> None:
    plan = generate_plan(EVPN_SPEC)
    for r in plan.rows:
        assert r.sfs_requirement_id, f"row missing requirement_id: {r}"
        assert r.action_steps, f"row missing action_steps: {r}"
        assert r.expectation, f"row missing expectation: {r}"


def test_plan_applies_categories_per_tag_not_uniformly() -> None:
    """Each requirement gets only the categories applicable to its tags
    — not all 17. v1 produced 24 rows per req; v3 should be variable."""
    plan = generate_plan(EVPN_SPEC)
    # Group rows by req
    rows_per_req: dict[str, list[str]] = {}
    for r in plan.rows:
        rows_per_req.setdefault(r.sfs_requirement_id, []).append(r.category)
    # Some requirements have far fewer rows than the max — not every
    # category applies to every requirement.
    counts = sorted(len(v) for v in rows_per_req.values())
    assert counts[0] < counts[-1], "all requirements got the same row count — applicability filter is not working"


# ─── xlsx writer ────────────────────────────────────────────────────────────

def test_xlsx_is_written_and_readable(tmp_path: Path) -> None:
    out = tmp_path / "plan.xlsx"
    plan = generate_plan_to_xlsx(EVPN_SPEC, out)
    assert out.exists() and out.stat().st_size > 0
    wb = openpyxl.load_workbook(out)
    assert "Test Plan Topics" in wb.sheetnames
    assert "Requirements" in wb.sheetnames
    # Requirements sheet header + at least one data row per requirement
    ws = wb["Requirements"]
    assert ws.max_row >= plan.n_requirements + 1


def test_xlsx_columns_match_template_schema(tmp_path: Path) -> None:
    """The xlsx column header must match the Exaware template's columns."""
    out = tmp_path / "plan.xlsx"
    generate_plan_to_xlsx(EVPN_SPEC, out)
    wb = openpyxl.load_workbook(out)
    ws = wb["Test Plan Topics"]
    # Column header row may not be row 1 (we have metadata above); find it.
    header_row = None
    for r in range(1, ws.max_row + 1):
        if ws.cell(row=r, column=1).value == "Category":
            header_row = r
            break
    assert header_row is not None, "Could not find 'Category' header row"
    expected = ["Category", "Action\\Steps",
                "SFS Requirement id\n(For Traceability)",
                "Expectation", "Build number",
                "Results (Pass\\Fail)", "Comment \\ Bug number if failed"]
    for c, exp in enumerate(expected, 1):
        assert ws.cell(row=header_row, column=c).value == exp


def test_xlsx_contains_evpn_anchors(tmp_path: Path) -> None:
    out = tmp_path / "plan.xlsx"
    generate_plan_to_xlsx(EVPN_SPEC, out)
    wb = openpyxl.load_workbook(out)
    ws = wb["Test Plan Topics"]
    seen_anchors: set[str] = set()
    for r in range(1, ws.max_row + 1):
        v = ws.cell(row=r, column=3).value
        if isinstance(v, str) and v.startswith("EVPNS-REQ#"):
            seen_anchors.add(v)
    assert len(seen_anchors) >= 30, f"only {len(seen_anchors)} anchors in xlsx"


def test_plan_handles_doc_without_anchors(tmp_path: Path) -> None:
    """A doc with no EVPNS-REQ# anchors should still produce a non-empty plan."""
    txt = tmp_path / "no_anchors.txt"
    txt.write_text(
        "1.  Test Feature\n\n    This is a feature with no requirement IDs.\n"
    )
    plan = generate_plan(txt)
    assert plan.n_rows > 0
    # Synthetic placeholder requirement
    assert any(r.req_id == "(no-anchor)" for r in plan.requirements)


# ─── Determinism ────────────────────────────────────────────────────────────

def test_planner_is_deterministic() -> None:
    p1 = generate_plan(EVPN_SPEC)
    p2 = generate_plan(EVPN_SPEC)
    assert p1.model_dump_json() == p2.model_dump_json()


# ─── CLI integration ────────────────────────────────────────────────────────

def test_cli_plan_command_works(tmp_path: Path) -> None:
    from ate.cli import main as cli_main
    out = tmp_path / "plan.xlsx"
    rc = cli_main(["plan", str(EVPN_SPEC), "-o", str(out), "--summary"])
    assert rc == 0
    rc = cli_main(["plan", str(EVPN_SPEC), "-o", str(out)])
    assert rc == 0
    assert out.exists() and out.stat().st_size > 0


def test_cli_plan_handles_bad_input(tmp_path: Path, capsys) -> None:
    from ate.cli import main as cli_main
    bad = tmp_path / "nope.html"
    bad.write_bytes(b"<html>not supported</html>")
    rc = cli_main(["plan", str(bad), "-o", str(tmp_path / "x.xlsx")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "UnsupportedFormatError" in err

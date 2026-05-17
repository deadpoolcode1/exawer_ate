#!/usr/bin/env python3
"""Generate a single-file HTML test report for ATE.

Sections (in order they appear in the HTML):
  1. SOW Requirements Coverage   — per-milestone deliverables, traced to tests
  2. M1 Acceptance Scorecard     — 9 numeric metrics with thresholds
  3. Pytest Suite                — every test grouped by file
  4. Code Coverage               — pytest-cov per module
  5. Code Quality                — ruff lint issues
  6. Performance                 — parse-time per corpus file
  7. Corpus Inventory            — references/ files and their parse status
  8. Output Files                — out/ JSON files (if present)

Output: results/test-report-YYYYMMDD_HHMMSS.html — one self-contained HTML.
Exit code 0 if every gated row is PASS or SKIP, non-zero if any FAIL.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)
JUNIT_XML = RESULTS / "pytest-junit.xml"
COVERAGE_JSON = ROOT / "coverage.json"


@dataclass
class Row:
    test_id: str
    description: str  # may contain HTML (e.g. <br>, <small>)
    result: str  # PASS / FAIL / SKIP / INFO
    description_is_html: bool = False


@dataclass
class Section:
    title: str
    rows: list[Row] = field(default_factory=list)


# ════════════════════════════════════════════════════════════════════════════
# Data collection — run pytest + scorecard once, cache results
# ════════════════════════════════════════════════════════════════════════════

_PYTEST_CACHE: dict[str, str] | None = None
_COV_CACHE: dict[str, Any] | None = None
_SCORECARD_CACHE: dict[str, Any] | None = None


def run_pytest_and_coverage() -> tuple[dict[str, str], dict[str, Any]]:
    """Run pytest with junit + coverage, return:
       - results: { "test_module::test_name": "PASS" | "FAIL" | "SKIP" }
       - cov_data: parsed coverage.json
    """
    global _PYTEST_CACHE, _COV_CACHE
    if _PYTEST_CACHE is not None and _COV_CACHE is not None:
        return _PYTEST_CACHE, _COV_CACHE

    # PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 keeps host ROS2 / system pytest
    # plugins from leaking in. We re-enable pytest-cov explicitly via -p.
    cmd = [
        sys.executable, "-m", "pytest",
        "-p", "pytest_cov",
        "--cov=ate",
        "--cov-report=json:" + str(COVERAGE_JSON),
        "--cov-report=term-missing:skip-covered",
        "--junit-xml=" + str(JUNIT_XML),
        "-q",
    ]
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=ROOT)

    results: dict[str, str] = {}
    if JUNIT_XML.exists():
        for c in ET.parse(JUNIT_XML).getroot().findall(".//testcase"):
            cls = c.get("classname", "")
            name = c.get("name", "")
            m = re.search(r"tests\.([\w_]+)", cls)
            stem = m.group(1) if m else cls
            key = f"{stem}::{name}"
            if c.find("failure") is not None or c.find("error") is not None:
                results[key] = "FAIL"
            elif c.find("skipped") is not None:
                results[key] = "SKIP"
            else:
                results[key] = "PASS"

    cov: dict[str, Any] = {}
    if COVERAGE_JSON.exists():
        try:
            cov = json.loads(COVERAGE_JSON.read_text())
        except json.JSONDecodeError:
            cov = {}
    _PYTEST_CACHE = results
    _COV_CACHE = cov
    return results, cov


def run_scorecard() -> dict[str, Any]:
    """Run scripts/score.py --json, return parsed payload."""
    global _SCORECARD_CACHE
    if _SCORECARD_CACHE is not None:
        return _SCORECARD_CACHE
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "score.py"), "--json"],
        capture_output=True, text=True,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        cwd=ROOT,
    )
    try:
        _SCORECARD_CACHE = json.loads(proc.stdout)
    except json.JSONDecodeError:
        _SCORECARD_CACHE = {"all_passed": False, "elapsed_s": 0.0, "results": []}
    return _SCORECARD_CACHE


# ════════════════════════════════════════════════════════════════════════════
# Section 1 — SOW Requirements Coverage with traceability
# ════════════════════════════════════════════════════════════════════════════

# Each requirement has:
#   id, milestone, description, evidence list
# Evidence kinds:
#   ("pytest_prefix", "stem::test_name")  matches every parametrized variant
#   ("scorecard",      "metric_name")     matches a scorecard metric
#   ("file_exists",    "relative/path")   passes if file exists and is non-empty
#
# Aggregation:
#   - if there's no evidence wired (later milestones), result = SKIP
#   - else: PASS only if every evidence item passes; FAIL if any fails

# Requirements aligned to SOW PQ4476E (current).
# Milestone names: M1 "Test Plan Generation" (15%), M2 "Dirty Queue & Code Gen" (15%),
# M3 "AI Test Plan Generation" (30%), M4 "Code Generation" (20%), M5 "Web UI & Deployment" (20%).

REQUIREMENTS: list[dict[str, Any]] = [
    # ─── M1 — Test Plan Generation (Weeks 1-2, 15%) ────────────────────────
    {
        "id": "R-M1.1",
        "milestone": "M1",
        "description": "Development environment (Docker / venv / Makefile / modular_tools.sh)",
        "evidence": [
            ("file_exists", "Dockerfile"),
            ("file_exists", "docker-compose.yml"),
            ("file_exists", "Makefile"),
            ("file_exists", "modular_tools.sh"),
            ("file_exists", "pyproject.toml"),
            ("pytest_prefix", "test_cli::test_cli_inprocess_summary"),
        ],
    },
    {
        "id": "R-M1.2",
        "milestone": "M1",
        "description": "Document parser supporting PDF, DOCX, and TXT formats (SOW §3 Requirements Processing)",
        "evidence": [
            ("pytest_prefix", "test_dispatch::test_detect_pdf"),
            ("pytest_prefix", "test_dispatch::test_detect_docx"),
            ("pytest_prefix", "test_dispatch::test_detect_txt"),
            ("pytest_prefix", "test_dispatch::test_detect_html_rejected"),
            ("pytest_prefix", "test_parsers::test_parse_returns_document"),
            ("pytest_prefix", "test_parsers::test_pdf_no_text_layer_rejected"),
            ("pytest_prefix", "test_edge_cases::test_edge_case_produces_expected_outcome"),
            ("scorecard", "no_unhandled_exceptions"),
            ("scorecard", "edge_cases"),
        ],
    },
    {
        "id": "R-M1.3",
        "milestone": "M1",
        "description": "Basic text extraction working — headings, paragraphs, code blocks, tables",
        "evidence": [
            ("pytest_prefix", "test_parsers::test_evpn_spec_has_cli_blocks"),
            ("pytest_prefix", "test_parsers::test_evpn_spec_finds_anchors"),
            ("pytest_prefix", "test_parsers::test_docx_table_structure"),
            ("pytest_prefix", "test_parsers::test_block_types_are_correct"),
            ("pytest_prefix", "test_parity::test_rfc9785_word_parity_across_formats"),
            ("pytest_prefix", "test_determinism::test_three_runs_byte_identical"),
            ("pytest_prefix", "test_regression::test_normalized_ir_matches_golden"),
            ("scorecard", "heading_recovery"),
            ("scorecard", "cli_block_preservation"),
            ("scorecard", "table_preservation"),
            ("scorecard", "format_parity"),
            ("scorecard", "determinism"),
            ("scorecard", "performance"),
        ],
    },
    {
        "id": "R-M1.4",
        "milestone": "M1",
        "description": "Test plan generation from input documents (2 Word files + RFC) — AI-enriched (Claude) with rule-based fallback, single router",
        "evidence": [
            ("pytest_prefix", "test_planner::test_extracts_evpn_anchors_from_evpn_spec"),
            ("pytest_prefix", "test_planner::test_extractor_dedupes_repeated_anchors"),
            ("pytest_prefix", "test_planner::test_plan_from_evpn_spec_uses_template_categories"),
            ("pytest_prefix", "test_planner::test_plan_rows_are_traced_to_a_requirement"),
            ("pytest_prefix", "test_planner::test_plan_applies_categories_per_tag_not_uniformly"),
            ("pytest_prefix", "test_planner::test_xlsx_is_written_and_readable"),
            ("pytest_prefix", "test_planner::test_xlsx_columns_match_template_schema"),
            ("pytest_prefix", "test_planner::test_xlsx_contains_evpn_anchors"),
            ("pytest_prefix", "test_planner::test_plan_handles_doc_without_anchors"),
            ("pytest_prefix", "test_planner::test_planner_is_deterministic"),
            ("pytest_prefix", "test_planner::test_cli_plan_command_works"),
            ("pytest_prefix", "test_planner::test_cli_plan_handles_bad_input"),
            ("pytest_prefix", "test_ai_enricher::test_cache_loads_committed_baked_entries"),
            ("pytest_prefix", "test_ai_enricher::test_enrich_uses_cache_without_api_key"),
            ("pytest_prefix", "test_ai_enricher::test_enrich_swaps_action_steps_for_cached_rows"),
            ("pytest_prefix", "test_ai_enricher::test_enrich_calls_api_with_key_and_writes_cache"),
            ("pytest_prefix", "test_ai_enricher::test_enrich_falls_back_on_api_failure"),
            ("pytest_prefix", "test_ai_enricher::test_save_load_cache_roundtrip"),
            ("pytest_prefix", "test_ai_enricher::test_row_key_is_stable"),
            ("file_exists", "ate/planner/__init__.py"),
            ("file_exists", "ate/planner/generator.py"),
            ("file_exists", "ate/planner/categories.py"),
            ("file_exists", "ate/planner/extractor.py"),
            ("file_exists", "ate/planner/xlsx_writer.py"),
            ("file_exists", "ate/planner/ai_enricher.py"),
            ("file_exists", "ate/planner/ai_cache.json"),
        ],
    },
    {
        "id": "R-M1.5",
        "milestone": "M1",
        "description": "Deliverable artifact: Test Plan (single router) xlsx for Exaware review/approval",
        "evidence": [
            ("file_exists", "plans/EVPN_System_Specification_1.00.xlsx"),
        ],
    },
    {
        "id": "R-M1.6",
        "milestone": "M1",
        "description": "Technical Design Document + acceptance docs",
        "evidence": [
            ("file_exists", "docs/TDD.md"),
            ("file_exists", "docs/M1_acceptance.md"),
            ("file_exists", "docs/exaware-acceptance.md"),
        ],
    },
    # ─── M2 — Dirty Queue & Code Generation (Weeks 3-4, 15%) ───────────────
    {"id": "R-M2.1", "milestone": "M2",
     "description": "Pattern matching implementation (cross-style requirement IDs)",
     "evidence": []},
    {"id": "R-M2.2", "milestone": "M2",
     "description": "Code generation based on tests selected by Exaware (dirty queue)",
     "evidence": []},
    {"id": "R-M2.3", "milestone": "M2",
     "description": "Up to 3 integration-ready test plans",
     "evidence": []},
    {"id": "R-M2.4", "milestone": "M2",
     "description": "Demo: extract requirements from sample SFS",
     "evidence": []},
    # ─── M3 — AI Test Plan Generation (Weeks 5-6, 30%) ──────────────────────
    {"id": "R-M3.1", "milestone": "M3",
     "description": "OpenAI / Anthropic Claude API integration",
     "evidence": []},
    {"id": "R-M3.2", "milestone": "M3",
     "description": "Prompt engineering for test plan generation",
     "evidence": []},
    {"id": "R-M3.3", "milestone": "M3",
     "description": "Test plan generation engine — multi-router topologies",
     "evidence": []},
    {"id": "R-M3.4", "milestone": "M3",
     "description": "Test prioritization (critical / high / medium / low)",
     "evidence": []},
    {"id": "R-M3.5", "milestone": "M3",
     "description": "Coverage tracking — which requirements have generated tests",
     "evidence": []},
    {"id": "R-M3.6", "milestone": "M3",
     "description": "Multi load / router functionality",
     "evidence": []},
    {"id": "R-M3.7", "milestone": "M3",
     "description": "Deliverable: full single + multi-router test plan",
     "evidence": []},
    # ─── M4 — Code Generation (Weeks 7-8, 20%) ──────────────────────────────
    {"id": "R-M4.1", "milestone": "M4",
     "description": "Code templates (Java + JSystem framework — NOT Python pytest)",
     "evidence": []},
    {"id": "R-M4.2", "milestone": "M4",
     "description": "Code generation engine producing Java/JSystem-compatible test code",
     "evidence": []},
    {"id": "R-M4.3", "milestone": "M4",
     "description": "Syntax validation on generated Java code (Checkstyle / JUnit)",
     "evidence": []},
    {"id": "R-M4.4", "milestone": "M4",
     "description": "Test file structure generation following JSystem conventions",
     "evidence": []},
    {"id": "R-M4.5", "milestone": "M4",
     "description": "Queue implementation for test selection",
     "evidence": []},
    {"id": "R-M4.6", "milestone": "M4",
     "description": "Test infrastructure hooks: IXIA Router Simulator + Neighboring Routers + JSystem",
     "evidence": []},
    {"id": "R-M4.7", "milestone": "M4",
     "description": "Up to 10 test plan use cases delivered as runnable Java code",
     "evidence": []},
    # ─── M5 — Web UI & Deployment (Weeks 9-10, 20%) ─────────────────────────
    {"id": "R-M5.1", "milestone": "M5",
     "description": "Web application: document upload UI",
     "evidence": []},
    {"id": "R-M5.2", "milestone": "M5",
     "description": "Web UI: requirements + plan view + plan editor",
     "evidence": []},
    {"id": "R-M5.3", "milestone": "M5",
     "description": "Web UI: generated Java/JSystem code viewer with syntax highlighting",
     "evidence": []},
    {"id": "R-M5.4", "milestone": "M5",
     "description": "Download functionality (xlsx test plans + Java code)",
     "evidence": []},
    {"id": "R-M5.5", "milestone": "M5",
     "description": "On-premises deployment via Docker + docker-compose; AI calls remain cloud (Claude API)",
     "evidence": []},
    {"id": "R-M5.6", "milestone": "M5",
     "description": "User documentation, training (2-hr session), 60-day post-delivery support",
     "evidence": []},
]


def _evidence_matches(kind: str, ref: str,
                      pytest_results: dict[str, str],
                      scorecard: dict[str, Any]) -> list[tuple[str, str]]:
    """Resolve one evidence item to a list of (label, status) pairs."""
    matches: list[tuple[str, str]] = []
    if kind == "pytest_prefix":
        for k, v in sorted(pytest_results.items()):
            if k.startswith(ref):
                matches.append((f"pytest:{k}", v))
        if not matches:
            matches.append((f"pytest:{ref}", "FAIL"))  # missing test = FAIL
    elif kind == "scorecard":
        for r in scorecard.get("results", []):
            if ref in r["name"]:
                status = "PASS" if r["passed"] else "FAIL"
                matches.append((f"scorecard:{r['name']}", status))
        if not matches:
            matches.append((f"scorecard:{ref}", "FAIL"))
    elif kind == "file_exists":
        path = ROOT / ref
        ok = path.exists() and path.stat().st_size > 0
        matches.append((f"file:{ref}", "PASS" if ok else "FAIL"))
    return matches


def _section_requirements_per_milestone(
    pytest_results: dict[str, str],
    scorecard: dict[str, Any],
) -> list[Section]:
    sections: list[Section] = []
    for ms in ("M1", "M2", "M3", "M4", "M5"):
        s = Section(f"SOW Requirements Coverage — {ms}")
        for req in REQUIREMENTS:
            if req["milestone"] != ms:
                continue
            evidence = req["evidence"]
            if not evidence:
                # Later milestone — not yet in scope
                desc = (f"<b>{html.escape(req['description'])}</b><br>"
                        f"<small style='color:#888'>"
                        f"not yet in scope — planned for {ms}</small>")
                s.rows.append(Row(req["id"], desc, "SKIP", description_is_html=True))
                continue

            all_resolved: list[tuple[str, str]] = []
            for kind, ref in evidence:
                all_resolved.extend(
                    _evidence_matches(kind, ref, pytest_results, scorecard)
                )
            n_pass = sum(1 for _, st in all_resolved if st == "PASS")
            n_fail = sum(1 for _, st in all_resolved if st == "FAIL")
            n_skip = sum(1 for _, st in all_resolved if st == "SKIP")

            if n_fail > 0:
                req_status = "FAIL"
            elif n_pass > 0:
                req_status = "PASS"
            else:
                req_status = "SKIP"

            cov_lines = []
            for label, st in all_resolved:
                tag_color = {"PASS": "#28a745", "FAIL": "#dc3545",
                             "SKIP": "#ffc107"}.get(st, "#888")
                cov_lines.append(
                    f"<span style='color:{tag_color}'>[{st}]</span> "
                    f"<code>{html.escape(label)}</code>"
                )
            cov_html = "<br>".join(cov_lines)
            desc = (
                f"<b>{html.escape(req['description'])}</b><br>"
                f"<small><b>Covered by</b> "
                f"({n_pass} pass / {n_fail} fail / {n_skip} skip):</small><br>"
                f"<small style='font-family: monospace'>{cov_html}</small>"
            )
            s.rows.append(Row(req["id"], desc, req_status,
                               description_is_html=True))
        sections.append(s)
    return sections


# ════════════════════════════════════════════════════════════════════════════
# Section 2 — M1 Acceptance Scorecard
# ════════════════════════════════════════════════════════════════════════════

def _section_scorecard(scorecard: dict[str, Any]) -> Section:
    section = Section("M1 Acceptance Scorecard")
    for i, r in enumerate(scorecard.get("results", []), 1):
        result = "PASS" if r["passed"] else "FAIL"
        desc = f'{r["name"]} = {r["value"]} ({r["threshold"]})'
        if r.get("detail") and not r["passed"]:
            desc += f' — {r["detail"]}'
        section.rows.append(Row(f"M1.{i:02d}", desc, result))
    return section


# ════════════════════════════════════════════════════════════════════════════
# Section 3 — Pytest Suite (rendered from cached results)
# ════════════════════════════════════════════════════════════════════════════

def _section_pytest(pytest_results: dict[str, str]) -> Section:
    section = Section("Pytest Suite")
    for i, (key, status) in enumerate(sorted(pytest_results.items()), 1):
        section.rows.append(Row(f"P.{i:03d}", key, status))
    return section


# ════════════════════════════════════════════════════════════════════════════
# Section 4 — Code Coverage
# ════════════════════════════════════════════════════════════════════════════

def _section_coverage(cov_data: dict[str, Any]) -> Section:
    section = Section("Code Coverage (pytest-cov)")
    if not cov_data or "files" not in cov_data:
        section.rows.append(Row("CC.??", "coverage.json not produced", "FAIL"))
        return section
    files = sorted(cov_data["files"].items(), key=lambda kv: kv[0])
    threshold = 70.0
    for i, (path, info) in enumerate(files, 1):
        pct = info.get("summary", {}).get("percent_covered", 0)
        n_lines = info.get("summary", {}).get("num_statements", 0)
        n_missing = info.get("summary", {}).get("missing_lines", 0)
        result = "PASS" if pct >= threshold else "FAIL"
        desc = f"{path} — {pct:.1f}% covered ({n_lines} stmts, {n_missing} missing)"
        section.rows.append(Row(f"CC.{i:02d}", desc, result))
    overall = cov_data.get("totals", {}).get("percent_covered", 0)
    section.rows.append(Row("CC.TOTAL", f"OVERALL coverage = {overall:.1f}%",
                            "PASS" if overall >= threshold else "FAIL"))
    return section


# ════════════════════════════════════════════════════════════════════════════
# Section 5 — Code Quality (ruff)
# ════════════════════════════════════════════════════════════════════════════

def _section_lint() -> Section:
    section = Section("Code Quality (ruff lint)")
    cmd = [sys.executable, "-m", "ruff", "check",
           "ate", "scripts", "tests", "--output-format=json"]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    try:
        issues = json.loads(proc.stdout) if proc.stdout.strip() else []
    except json.JSONDecodeError:
        section.rows.append(Row("L.??", "ruff failed to produce JSON", "FAIL"))
        return section
    if not issues:
        section.rows.append(Row("L.OK", "ruff: 0 issues across ate/, scripts/, tests/", "PASS"))
        return section
    by_file: dict[str, int] = {}
    for it in issues:
        by_file[it.get("filename", "?")] = by_file.get(it.get("filename", "?"), 0) + 1
    for i, (f, n) in enumerate(sorted(by_file.items()), 1):
        rel = Path(f).relative_to(ROOT) if f.startswith(str(ROOT)) else f
        section.rows.append(Row(f"L.{i:02d}",
                                 f"{rel} — {n} lint issue(s)", "FAIL"))
    section.rows.append(Row("L.TOTAL", f"ruff: {len(issues)} total issue(s)", "FAIL"))
    return section


# ════════════════════════════════════════════════════════════════════════════
# Section 6 — Performance
# ════════════════════════════════════════════════════════════════════════════

def _section_performance() -> Section:
    section = Section("Performance (parse-time per corpus file)")
    sys.path.insert(0, str(ROOT))
    from ate.parsers import parse  # noqa: PLC0415

    targets = [
        "tier_a/rfc9785.docx",
        "tier_a/rfc9785.txt",
        "tier_a/rfc9785.pdf",
        "tier_a/EVPN System Specification 1.00.docx",
        "tier_a/EVPN CLI 1.00.docx",
        "tier_b/rfc7432bis-13.docx",
        "tier_b/rfc7432bis-13.txt",
    ]
    BUDGET_S = 30.0
    for i, rel in enumerate(targets, 1):
        p = ROOT / "tests" / "corpus" / rel
        if not p.exists():
            section.rows.append(Row(f"PF.{i:02d}", f"{rel} — file missing", "SKIP"))
            continue
        size_kb = p.stat().st_size / 1024
        t0 = time.perf_counter()
        try:
            d = parse(p)
            dt = time.perf_counter() - t0
            ok = dt < BUDGET_S
            desc = (f"{rel} ({size_kb:.0f} KB) — parsed in {dt*1000:.0f} ms "
                    f"({len(d.blocks)} blocks)")
            section.rows.append(Row(f"PF.{i:02d}", desc, "PASS" if ok else "FAIL"))
        except Exception as e:
            section.rows.append(Row(f"PF.{i:02d}",
                                     f"{rel} — error: {type(e).__name__}: {e}",
                                     "FAIL"))
    return section


# ════════════════════════════════════════════════════════════════════════════
# Section 7 — Corpus Inventory (references/)
# ════════════════════════════════════════════════════════════════════════════

def _section_corpus() -> Section:
    section = Section("Corpus Inventory (references/)")
    refs = ROOT / "references"
    files = sorted(p for p in refs.rglob("*") if p.is_file()) if refs.exists() else []
    sys.path.insert(0, str(ROOT))
    from ate.parsers import parse  # noqa: PLC0415

    for i, p in enumerate(files, 1):
        rel = p.relative_to(refs)
        ext = p.suffix.lower()
        size_kb = p.stat().st_size / 1024
        if ext in {".pdf", ".docx", ".txt"}:
            try:
                d = parse(p)
                desc = (f"{rel} ({size_kb:.0f} KB) — "
                        f"{d.source_format}, {len(d.blocks)} blocks, "
                        f"{len(d.headings)} headings, {len(d.tables)} tables, "
                        f"{len(d.code_blocks)} code blocks")
                result = "PASS"
            except Exception as e:
                desc = f"{rel} — parse failed: {type(e).__name__}: {e}"
                result = "FAIL"
        else:
            desc = f"{rel} ({size_kb:.0f} KB) — skipped (format {ext})"
            result = "SKIP"
        section.rows.append(Row(f"C.{i:02d}", desc, result))
    return section


# ════════════════════════════════════════════════════════════════════════════
# Section 8 — Output files
# ════════════════════════════════════════════════════════════════════════════

def _section_outputs() -> Section:
    section = Section("Output Files (out/)")
    out_dir = ROOT / "out"
    if not out_dir.exists() or not any(out_dir.iterdir()):
        section.rows.append(Row("O.--",
                                 "out/ is empty — run `./modular_tools.sh parse_all`",
                                 "INFO"))
        return section
    files = sorted(out_dir.iterdir())
    for i, p in enumerate(files, 1):
        size_kb = p.stat().st_size / 1024
        section.rows.append(Row(f"O.{i:02d}", f"{p.name} — {size_kb:.0f} KB", "PASS"))
    return section


# ════════════════════════════════════════════════════════════════════════════
# HTML rendering
# ════════════════════════════════════════════════════════════════════════════

def _git_short() -> str:
    if not shutil.which("git"):
        return "n/a"
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, cwd=ROOT, timeout=2)
        if r.returncode == 0:
            return r.stdout.strip() or "uncommitted"
        return "no-repo (git init not run)"
    except Exception:
        return "n/a"


def _platform_line() -> str:
    return f"{platform.system()} {platform.release()} / Python {platform.python_version()}"


def _render_html(sections: list[Section], elapsed_s: float) -> str:
    total = sum(len(s.rows) for s in sections)
    n_pass = sum(1 for s in sections for r in s.rows if r.result == "PASS")
    n_fail = sum(1 for s in sections for r in s.rows if r.result == "FAIL")
    n_skip = sum(1 for s in sections for r in s.rows if r.result == "SKIP")
    n_info = sum(1 for s in sections for r in s.rows if r.result == "INFO")
    overall_pass = n_fail == 0

    rows_html: list[str] = []
    for s in sections:
        n_p = sum(1 for r in s.rows if r.result == "PASS")
        n_f = sum(1 for r in s.rows if r.result == "FAIL")
        n_s = sum(1 for r in s.rows if r.result == "SKIP")
        section_label = (f"{html.escape(s.title)} "
                         f"({n_p} pass / {n_f} fail / {n_s} skip)")
        rows_html.append(
            f"<tr class='group'><td colspan='3'><b>{section_label}</b></td></tr>"
        )
        for r in s.rows:
            cls = r.result.lower()
            desc = r.description if r.description_is_html else html.escape(r.description)
            rows_html.append(
                f"<tr class='{cls}'>"
                f"<td>{html.escape(r.test_id)}</td>"
                f"<td>{desc}</td>"
                f"<td>{r.result}</td></tr>"
            )

    summary_class = "pass" if overall_pass else "fail"
    summary_label = "ALL TESTS PASSED" if overall_pass else "SOME TESTS FAILED"

    css = """
  body { font-family: -apple-system, Arial, sans-serif; margin: 20px; background: #f5f5f5; }
  h1 { color: #333; } h2 { color: #555; margin-top: 20px; }
  .meta { color: #666; margin-bottom: 20px; }
  .summary { font-size: 1.3em; padding: 15px; border-radius: 8px; margin: 15px 0; }
  .summary.pass { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
  .summary.fail { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
  table { border-collapse: collapse; width: 100%; background: white; box-shadow: 0 1px 3px rgba(0,0,0,.12); margin-bottom: 20px; }
  th { background: #343a40; color: white; padding: 10px 12px; text-align: left; }
  td { padding: 8px 12px; border-bottom: 1px solid #dee2e6; vertical-align: top; }
  tr.group td { background: #e9ecef; font-weight: bold; padding: 10px 12px; }
  tr.pass td:last-child { color: #28a745; font-weight: bold; }
  tr.fail td:last-child { color: #dc3545; font-weight: bold; }
  tr.skip td:last-child { color: #ffc107; font-weight: bold; }
  tr.info td:last-child { color: #17a2b8; font-weight: bold; }
  code { background: #f1f3f5; padding: 1px 4px; border-radius: 3px; font-size: 0.85em; }
  .footer { color: #999; margin-top: 30px; font-size: 0.9em; }
  .legend { font-size: 0.9em; color: #666; margin: 8px 0; }
"""

    when = time.strftime("%Y-%m-%d %H:%M:%S")
    git = _git_short()
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>ATE M1 Test Report</title>
<style>{css}</style></head><body>
<h1>ATE — Document Parser (M1) Test Report</h1>
<div class="meta">
  <b>Date:</b> {when}<br>
  <b>Project:</b> Codevalue PQ 4476 — Exaware AI Test-Plan Generator (POC)<br>
  <b>Milestone:</b> M1 — Document parser (PDF / DOCX / TXT) → unified IR JSON<br>
  <b>Platform:</b> {html.escape(_platform_line())}<br>
  <b>Git:</b> {html.escape(git)}<br>
  <b>Runtime:</b> {elapsed_s:.1f} seconds
</div>
<div class="summary {summary_class}">
  <b>Result:</b> {summary_label}
  &nbsp;—&nbsp; Total: {total} &nbsp;|&nbsp; Pass: {n_pass} &nbsp;|&nbsp; Fail: {n_fail} &nbsp;|&nbsp; Skip: {n_skip}{
  f' &nbsp;|&nbsp; Info: {n_info}' if n_info else ''}
</div>
<div class="legend"><b>Legend:</b>
  <span style="color:#28a745">PASS</span> — meets gate •
  <span style="color:#dc3545">FAIL</span> — below threshold •
  <span style="color:#ffc107">SKIP</span> — not in scope (later milestone) •
  <span style="color:#17a2b8">INFO</span> — informational, not gated
</div>
<table>
<tr><th style="width:10%">Test ID</th><th style="width:75%">Description</th><th style="width:15%">Result</th></tr>
{chr(10).join(rows_html)}
</table>
<div class="footer">Generated by <code>modular_tools.sh run-tests</code> — Codevalue / ATE</div>
</body></html>
"""


# ════════════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════════════

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=None)
    args = p.parse_args()

    t0 = time.perf_counter()
    sections: list[Section] = []

    print("[report] 1/8  Pytest + coverage (slow)...")
    pytest_results, cov_data = run_pytest_and_coverage()

    print("[report] 2/8  Scorecard...")
    scorecard = run_scorecard()

    print("[report] 3/8  SOW requirements coverage (per milestone, with traceability)...")
    sections.extend(_section_requirements_per_milestone(pytest_results, scorecard))

    print("[report] 4/8  M1 acceptance scorecard section...")
    sections.append(_section_scorecard(scorecard))

    print("[report] 5/8  Pytest suite section...")
    sections.append(_section_pytest(pytest_results))

    print("[report] 6/8  Code coverage...")
    sections.append(_section_coverage(cov_data))

    print("[report] 7/8  Code quality (ruff)...")
    sections.append(_section_lint())

    print("[report] 8/8  Performance + corpus + outputs...")
    sections.append(_section_performance())
    sections.append(_section_corpus())
    sections.append(_section_outputs())

    elapsed_s = time.perf_counter() - t0

    out = (Path(args.out) if args.out else
           RESULTS / f"test-report-{time.strftime('%Y%m%d_%H%M%S')}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_render_html(sections, elapsed_s), encoding="utf-8")

    n_total = sum(len(s.rows) for s in sections)
    n_pass = sum(1 for s in sections for r in s.rows if r.result == "PASS")
    n_fail = sum(1 for s in sections for r in s.rows if r.result == "FAIL")
    n_skip = sum(1 for s in sections for r in s.rows if r.result == "SKIP")
    print(f"\n[report] Wrote {out}")
    print(f"[report] {n_total} rows: {n_pass} pass / {n_fail} fail / {n_skip} skip")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Sanity-check that the dev environment is healthy.

Pure pass/fail, exit 0 = healthy, exit 1 = something missing.
"""
from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path

REQUIRED_MODULES = ["pdfplumber", "docx", "pydantic", "pytest", "openpyxl"]
REQUIRED_FILES = [
    "pyproject.toml",
    "Dockerfile",
    "Makefile",
    "ate/__init__.py",
    "ate/ir.py",
    "ate/cli.py",
    "ate/parsers/dispatch.py",
    "ate/parsers/docx_parser.py",
    "ate/parsers/pdf_parser.py",
    "ate/parsers/txt_parser.py",
    "ate/normalize.py",
    "tests/corpus/tier_a/rfc9785.docx",
    "tests/corpus/tier_a/rfc9785.txt",
    "tests/corpus/tier_a/rfc9785.pdf",
    "tests/corpus/tier_a/EVPN System Specification 1.00.docx",
    "tests/corpus/tier_a/EVPN CLI 1.00.docx",
    "tests/corpus/tier_b/rfc7432bis-13.docx",
    "tests/corpus/tier_b/rfc7432bis-13.txt",
    "tests/corpus/tier_c/MANIFEST.tsv",
]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    fails: list[str] = []
    checks: list[tuple[str, str]] = []

    # Python
    pyver = f"{sys.version_info.major}.{sys.version_info.minor}"
    ok = sys.version_info >= (3, 10)
    checks.append((f"Python ≥ 3.10 (have {pyver})", "OK" if ok else "FAIL"))
    if not ok:
        fails.append("python-version")

    # Modules
    for mod in REQUIRED_MODULES:
        try:
            importlib.import_module(mod)
            checks.append((f"import {mod}", "OK"))
        except ImportError as e:
            checks.append((f"import {mod}", f"FAIL: {e}"))
            fails.append(mod)

    # Files
    for rel in REQUIRED_FILES:
        p = root / rel
        if p.exists():
            checks.append((f"file {rel}", "OK"))
        else:
            checks.append((f"file {rel}", "FAIL: missing"))
            fails.append(rel)

    # ate CLI on PATH (or in venv bin)
    ate_bin = root / ".venv" / "bin" / "ate"
    if ate_bin.exists() or shutil.which("ate"):
        checks.append(("ate CLI installed", "OK"))
    else:
        checks.append(("ate CLI installed", "FAIL: run `make install`"))
        fails.append("ate-cli")

    # Render
    width = max(len(c[0]) for c in checks) + 2
    print("Environment check")
    print("=" * (width + 8))
    for label, status in checks:
        marker = "[OK]" if status == "OK" else "[FAIL]"
        print(f"  {marker} {label.ljust(width)} {status if status != 'OK' else ''}")
    print()
    if fails:
        print(f"Result: {len(fails)} check(s) FAILED")
        return 1
    print(f"Result: {len(checks)}/{len(checks)} OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

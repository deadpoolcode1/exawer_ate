#!/usr/bin/env python3
"""Refuse a hand-over document that does not describe the run it ships with.

M2_Handover.docx is written by hand on purpose (see build_handover_docx.py),
and that is how it went stale: the 2026-09-16 package shipped the 9 Sep text,
"all three TCs FAIL" and "EVPN not negotiated", next to a report where all
three passed. Nothing read it. This gate does: the document must name the
date of the newest test in the automation report, and must not say FAIL for
a suite that report shows as passed.

    verify_handover_docx.py <package_dir>
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import zipfile
from pathlib import Path


def docx_text(path: Path) -> str:
    xml = zipfile.ZipFile(path).read("word/document.xml").decode()
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", xml))


def report_tests(report: Path) -> list[dict]:
    js = (report / "execution.js").read_text()
    data = json.loads(js[js.index("{"):js.rindex("}") + 1])
    out = []

    def walk(node):
        if node.get("type") == "test":
            out.append(node)
        for child in node.get("children", []) or []:
            walk(child)

    for m in data["machines"]:
        walk(m)
    return out


def main(pkg: Path) -> int:
    text = docx_text(pkg / "M2_Handover.docx")
    tests = report_tests(pkg / "06_automation_report")
    newest = max(dt.datetime.strptime(t["date"], "%Y/%m/%d").date() for t in tests)
    want = f"{newest.day} {newest:%B %Y}"
    problems = []
    if want not in text:
        problems.append(f"does not name the run date '{want}' of the report it ships with")
    for t in tests:
        tc = t["className"].rsplit(".", 1)[-1].split("_")[0]
        if t["status"] == "success" and re.search(rf"{tc}\b[^.]{{0,80}}\bFAIL\b", text):
            problems.append(f"says {tc} FAILs; the report shows it passed")
    if problems:
        print("REFUSED - M2_Handover.docx is stale:")
        for p in problems:
            print("  -", p)
        print("Update scripts/build_handover_docx.py and rebuild.")
        return 1
    print(f"OK - the hand-over document describes the {want} run.")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))

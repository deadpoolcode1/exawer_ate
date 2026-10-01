#!/usr/bin/env python3
"""Write, per shipped TC, the test-plan flow it was generated from.

Exaware, 2026-09-30 (Eyal Ozeri): "I guess these TCs scripts are the ones I
detailed in the mail I sent on July 12th ... But I can't be sure... it would
have helped if the scripts you fed to the engine be attached as well."

They are: TC01/TC02/TC03 come from FLOW-010/030/031, the flows he chose on
2026-07-12. This puts each flow's rows from the shipped test plan next to the
steps the generator made of them, so a reviewer can read one against the other
without opening the xlsx and the Java side by side.

    ./scripts/build_tc_sources.py <plan.xlsx> <suite dir> <out.md> [<flow.txt>]

`flow.txt` is Exaware's own automated flow (deliverables/M2/inputs/), quoted
verbatim at the top: the curated steps follow it more closely than the plan.

The plan rows and the steps are read from the files that ship: the plan
workbook and the TC Java. Nothing is re-generated here, so the document cannot
describe a build other than the one in the package.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ate.planner.plan_reader import read_plan  # noqa: E402

#: `* FLOW-010 - EVPN VLAN-based bring-up ...` in the class Javadoc.
_FLOW = re.compile(r"^\s*\*\s*(FLOW-\d{3})\s+-\s+(.*)$", re.M)
#: `// FLOW-010.S03 - covers ...` above each step.
_STEP_ID = re.compile(r"//\s*(FLOW-\d{3}\.S\w+)\s+-")
_TITLE = re.compile(
    r'stopAndStartLevel\(\+\+level \+ "\. ((?:[^"\\]|\\.)*)"\)')


#: A flow's first case ends where the plan starts restating it for another
#: test category (packet validation, hitless change, counters, ...).
_NEXT_CASE = "ALREADY established by the first test of this flow"


def _cell(text: str) -> str:
    """One markdown table cell: no pipes, no line breaks, no long dashes."""
    text = (text or "").replace("|", "/").replace("\u2014", "-")
    text = text.replace("\u2013", " to ")
    return " ".join(text.split())


def _steps(java: str) -> list[tuple[str, str, str]]:
    """(step id, title, the call that does the work), in order."""
    out: list[tuple[str, str, str]] = []
    lines = java.splitlines()
    step_id = ""
    for i, line in enumerate(lines):
        m = _STEP_ID.search(line)
        if m:
            step_id = m.group(1)
            continue
        t = _TITLE.search(line)
        if not t:
            continue
        call = ""
        for nxt in lines[i + 1:]:
            if nxt.strip() and not nxt.strip().startswith("//"):
                call = nxt.strip()
                break
        out.append((step_id, t.group(1).replace('\\"', '"'), call))
        step_id = ""
    return out


def main(argv: list[str]) -> int:
    if len(argv) not in (4, 5):
        print(__doc__)
        return 2
    plan_path, suite, out = Path(argv[1]), Path(argv[2]), Path(argv[3])
    flow_mail = Path(argv[4]) if len(argv) == 5 else None
    plan = read_plan(plan_path)

    parts = [
        "# TC sources",
        "",
        "Each TC below was generated from one flow of the shipped test plan "
        f"(`{plan_path.name}`). The flows are the three chosen on 2026-07-12: "
        "FLOW-010, FLOW-030 and FLOW-031.",
        "",
        "For each TC: the flow's base case as the plan states it, then the "
        "steps the generator made of it.",
    ]
    if flow_mail is not None:
        parts += ["", "## Input: Exaware's automated flow, 2026-07-12", "",
                  "TC02 and TC03 follow this flow step by step. Quoted "
                  "verbatim.", "", "```",
                  flow_mail.read_text(encoding="utf-8").rstrip(), "```"]
    for java_path in sorted(suite.rglob("TC*.java")):
        java = java_path.read_text(encoding="utf-8", errors="replace")
        m = _FLOW.search(java)
        if not m:
            print(f"error: {java_path.name} names no FLOW in its header")
            return 1
        flow_id, flow_title = m.group(1), m.group(2).strip()
        topics = [t for t in plan.topics if t.key == flow_id]
        if not topics:
            print(f"error: {flow_id} ({java_path.name}) is not in {plan_path}")
            return 1
        # A flow can render under several section bands; the first is the
        # primary one and the rest repeat it from another angle.
        topic = topics[0]

        parts += ["", f"## {java_path.stem}", "",
                  f"Source: **{_cell(topic.label)}**",
                  f"(plan section: {topic.section or 'none'}). "
                  f"Generated as: {flow_title}.", ""]
        if topic.summary:
            parts += [_cell(topic.summary), ""]

        base = []
        for a in topic.actions:
            if base and _NEXT_CASE in a.action:
                break
            base.append(a)
        rest = len(topic.actions) - len(base)
        parts += ["### Plan rows (base case)", "",
                  "| # | Action | Expectation | Monitor |",
                  "|---|---|---|---|"]
        for n, a in enumerate(base, 1):
            parts.append(f"| {n} | {_cell(a.action)} | "
                         f"{_cell(a.expectation)} | {_cell(a.monitor)} |")

        if rest:
            parts += ["", f"The plan has {rest} more row(s) under this flow "
                      "for other test categories. They are not automated."]
        parts += ["", "### Generated steps", "",
                  "| # | Step ID | Title | Call |",
                  "|---|---|---|---|"]
        for n, (sid, title, call) in enumerate(_steps(java), 1):
            parts.append(f"| {n} | {sid} | {_cell(title)} | "
                         f"`{_cell(call)}` |")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

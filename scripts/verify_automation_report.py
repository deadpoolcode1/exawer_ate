#!/usr/bin/env python3
"""Refuse to ship an automation report that says less than the mail claims.

Written on 2026-09-16, after Oded Engel opened the report we had just asked him
to open and found, in order: one `index.html` covering one test where the mail
promised three, and warnings on six of the steps. He was right on every count,
and none of it had been read by us before the package went out.

The package gate next door (`verify_handover_package.py`) reads the emitted
`.cfg` and `.java`. It reads nothing at all under `06_automation_report`, which
was a straight `cp -r` guarded by a test for the folder existing. So we shipped
12 MB of report without opening it and validated the run on the JUnit exit
code, which counts failures and not JSystem warnings. The mail said "OK
(1 test), 0 failures"; the last line of the report we attached said
"Final test status is : Warning". Both were true. That is the whole problem.

    ./scripts/verify_automation_report.py <package>/06_automation_report \
                                          <package>/01_generated_suite

Exit 0 = the report backs what the package claims. Exit 1 = do not send it.

What it enforces:

  1. Every TC class shipped in the suite appears in the report's execution
     tree. The difido reporter rewrites `execution.js` on each JVM start, so
     three tests run as three `JUnitCore` invocations leave a report naming
     only the last one. Nothing warned us; the folder looked full.

  2. No test folder that the execution tree does not name. The shipped report
     carried 66 of them, 12 MB, most from runs in May and June that the index
     never listed. A reviewer clicking through finds evidence from a build
     nobody is claiming anything about.

  3. No step in a listed test carries a `warning`, `failure` or `error`
     status, unless that exact warning is declared in KNOWN_WARNINGS below
     with an owner and a reason. A declared warning is printed for pasting
     into the delivery mail, which is the point: the choice is to fix it or to
     say it out loud, never to let the client find it.

  4. The test's own final verdict is Pass. This is the check that would have
     caught the 9 September package on its own, whose verdict was Warning
     while the mail said "0 failures".
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

#: Warnings we have decided to ship, each with the owner who has to clear it.
#:
#: A pattern here is a promise that the warning is understood, not that it is
#: harmless. The gate prints every one it matches so the delivery mail carries
#: the same list the reviewer is about to read. Anything not listed refuses the
#: package outright.
#:
#: Nothing in a step we generate belongs here. A configuration step that
#: commits nothing, or a chassis call that errors, is our defect to fix; see
#: the entries that were deliberately NOT added on 2026-09-16.
KNOWN_WARNINGS: tuple[tuple[str, str, str], ...] = (
    # (regex, owner, why it is shippable)
)


def _js_object(path: Path) -> dict:
    """Parse a difido `var x = {...};` file into a dict."""
    text = path.read_text(encoding="utf-8", errors="replace")
    start = text.find("{")
    end = text.rstrip().rstrip(";").rfind("}") + 1
    if start < 0 or end <= start:
        raise ValueError(f"{path} does not contain a JSON object")
    return json.loads(text[start:end])


def _richest_per_class(report: Path, tests: list[dict]) -> list[dict]:
    """One entry per test class: the one whose page actually has content.

    The difido reporter writes a placeholder entry when a test starts and
    another when it ends, so one run of three suites produces six entries and
    six folders. Judging all six would report the same test twice and score
    an empty placeholder as clean.

    The entry kept is the one with the most report elements, which is the
    page a reviewer would actually read.
    """
    best: dict[str, tuple[int, dict]] = {}
    for test in tests:
        name = (test.get("className") or test.get("name") or "").rsplit(".", 1)[-1]
        page = report / "tests" / f"test_{test.get('uid')}" / "test.js"
        try:
            size = len(_js_object(page).get("reportElements") or ())
        except (OSError, ValueError):
            size = 0
        if name not in best or size > best[name][0]:
            best[name] = (size, test)
    return [entry for _, entry in best.values()]


def _tests_in_execution(execution: dict) -> list[dict]:
    """Flatten the machine/scenario/test tree into the tests it names."""
    found: list[dict] = []

    def walk(node: dict) -> None:
        if node.get("type") == "test":
            found.append(node)
        for child in node.get("children") or ():
            walk(child)

    for machine in execution.get("machines") or ():
        walk(machine)
    return found


def _shipped_test_classes(suite: Path) -> set[str]:
    """The TC classes that are actually in the package, by simple name."""
    return {p.stem for p in suite.rglob("TC*.java")}


def _strip_html(text: str | None) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _first_lines(text: str, keep: int = 3, width: int = 300) -> str:
    """Enough of a message to identify it, without its stack trace."""
    lines = [ln for ln in text.splitlines() if ln.strip()][:keep]
    out = " ".join(lines)
    return out if len(out) <= width else out[:width] + " ..."


def _declared(message: str) -> tuple[str, str] | None:
    for pattern, owner, why in KNOWN_WARNINGS:
        if re.search(pattern, message, re.I | re.S):
            return owner, why
    return None


def _check_one_test(report: Path, test: dict) -> tuple[list[str], list[str]]:
    """Problems and declared warnings for a single test in the report."""
    problems: list[str] = []
    declared: list[str] = []

    uid = test.get("uid") or ""
    name = test.get("className") or test.get("name") or uid
    test_js = report / "tests" / f"test_{uid}" / "test.js"
    if not test_js.is_file():
        return [f"{name}: the execution tree names it but {test_js.name} is "
                f"missing, so there is no page to open"], []

    elements = _js_object(test_js).get("reportElements") or ()

    # A step banner is a `startLevel`; the lines beneath it inherit its
    # heading. Tracking the current banner makes the message name the step the
    # reviewer will see rather than a bare sentence.
    step = "(before the first step)"
    for element in elements:
        title = _strip_html(element.get("title"))
        if element.get("type") == "startLevel" and title:
            step = title
        if step.startswith("Final test status is"):
            # Everything under this banner is the report's own recap of the
            # findings above. Repeating it would name each warning twice; the
            # verdict itself is checked below.
            continue
        status = element.get("status")
        if status not in ("warning", "failure", "error"):
            continue
        if element.get("type") == "startLevel":
            # The banner repeats the status of a line below it; report the
            # line, which carries the text, not the banner.
            continue
        detail = " ".join((title, _strip_html(element.get("message")))).strip()
        if not detail:
            continue
        # A framework failure carries its whole Java stack trace. The first
        # lines say what broke; the rest buries every other finding.
        detail = _first_lines(detail)
        seen = _declared(detail)
        if seen:
            owner, why = seen
            declared.append(f"{name} / {step}\n        {detail}\n"
                            f"        owner: {owner} - {why}")
        else:
            problems.append(
                f"{name}: undeclared {status} in step \"{step}\":\n"
                f"      {detail}\n"
                f"      Fix it, or declare it in KNOWN_WARNINGS with an owner. "
                f"Shipping it unmentioned is how the reviewer finds it first.")

    final = [_strip_html(e.get("title")) for e in elements
             if _strip_html(e.get("title")).startswith("Final test status is")]
    for verdict in final:
        # JSystem writes "Pass" for a clean run and "Warning" / "Fail"
        # otherwise. Both spellings of success are accepted because the
        # reporter is not ours and has used each.
        if verdict.rsplit(":", 1)[-1].strip() not in ("Pass", "Success"):
            problems.append(
                f"{name}: the report's own verdict is \"{verdict}\". "
                f"Whatever the JUnit exit code said, this is the line the "
                f"reviewer reads first, and it may not disagree with the mail.")

    return problems, declared


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    report, suite = Path(argv[1]), Path(argv[2])
    for path in (report, suite):
        if not path.is_dir():
            print(f"error: {path} is not a directory")
            return 2

    execution_js = report / "execution.js"
    if not execution_js.is_file():
        print(f"REFUSED - {execution_js} is missing, so the report has no "
              f"index and index.html will render an empty dashboard.")
        return 1

    listed = _tests_in_execution(_js_object(execution_js))
    tests = _richest_per_class(report, listed)
    shipped = _shipped_test_classes(suite)
    print(f"verifying {len(tests)} test(s) in {report.name} "
          f"against {len(shipped)} shipped suite(s)")

    problems: list[str] = []
    declared: list[str] = []

    reported = {(t.get("className") or "").rsplit(".", 1)[-1] for t in tests}
    for missing in sorted(shipped - reported):
        problems.append(
            f"{missing} ships in the package but does not appear in the "
            f"report. The difido reporter rewrites execution.js on every JVM "
            f"start, so running the suites one at a time leaves a report "
            f"naming only the last. Run them in one JVM, or do not claim it.")

    # Orphan folders: evidence from runs nobody is claiming anything about.
    tests_dir = report / "tests"
    if tests_dir.is_dir():
        known = {f"test_{t.get('uid')}" for t in listed}
        orphans = sorted(p.name for p in tests_dir.iterdir()
                         if p.is_dir() and p.name not in known)
        if orphans:
            size_mb = sum(f.stat().st_size for f in tests_dir.rglob("*")
                          if f.is_file()) / 1e6
            problems.append(
                f"{len(orphans)} test folder(s) in tests/ are not named by "
                f"execution.js ({size_mb:.0f} MB in total). They are earlier "
                f"runs the reporter never cleaned up, and a reviewer who "
                f"opens one is reading a build we are not claiming anything "
                f"about. Clear the report directory before the run.\n"
                f"      first few: {', '.join(orphans[:5])}")

    for test in tests:
        test_problems, test_declared = _check_one_test(report, test)
        problems += test_problems
        declared += test_declared
        name = (test.get("className") or "").rsplit(".", 1)[-1] or "?"
        print(f"  [{'FAIL' if test_problems else 'ok':4}] {name}")

    if declared:
        print("\nDeclared warnings - put this list in the delivery mail:\n")
        for entry in declared:
            print(f"  * {entry}\n")

    if problems:
        print(f"\nREFUSED - {len(problems)} problem(s). "
              f"This report must not go to a client.\n")
        for problem in problems:
            print(f"  * {problem}\n")
        return 1

    print("\nOK - the report shows every suite the package ships, "
          "and every step in it passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

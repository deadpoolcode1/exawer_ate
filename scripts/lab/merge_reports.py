#!/usr/bin/env python3
"""Merge several difido run reports into one index.

Exaware, 2026-09-15 (Oded Engel): "I could only find a single index.html which
only for tc02, I could not find one per TC."

The straightforward answer is to run all three suites in one JVM, and that does
produce one index naming three tests. It also runs TC02 and TC03 on a device
the previous test has already poisoned: deleting an EVI aborts `bgpd`
(`assert(!dbl_link_on_list(...))`, bgp_node.c:43) and, on 8.7.0 LAB 938,
`rpki_mo` as well (`assert(0)`, cmi_subsc.c:1376, on a commit-delete). Exaware's
own bring-up deletes the EVI when it loads the base config, so the second test
in a shared JVM starts on a box where every commit answers "Aborted:
application communication failure".

So the two requirements pull apart: ONE REPORT wants one JVM, a CLEAN DEVICE
wants a reboot between tests. Until the delete stops crashing, this tool
resolves it the other way round - each test runs from its own reboot, and the
reports are merged afterwards:

    run TC01 (reboot) -> report A
    run TC02 (reboot) -> report B         merge_reports.py A B C -o merged
    run TC03 (reboot) -> report C

    ./scripts/lab/merge_reports.py <src>... -o <dest>

What it does NOT do is invent anything. Each test folder is copied verbatim
with its own uid, so every page in the merged report is the page that run
actually produced, and the merged index names exactly the tests that ran.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

#: Everything a difido report needs besides execution.js and tests/. Taken
#: from the first source, because these are the reporter's own static assets
#: and are identical across runs of the same framework build.
_STATIC = ("css", "js", "controllers", "images",
           "index.html", "tree.html", "table.html", "charts.html", "test.html")


def _js_object(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    start = text.find("{")
    end = text.rstrip().rstrip(";").rfind("}") + 1
    if start < 0 or end <= start:
        raise ValueError(f"{path} does not hold a JSON object")
    return json.loads(text[start:end])


def _tests(execution: dict) -> list[dict]:
    found: list[dict] = []

    def walk(node: dict) -> None:
        if node.get("type") == "test":
            found.append(node)
        for child in node.get("children") or ():
            walk(child)

    for machine in execution.get("machines") or ():
        walk(machine)
    return found


def _page_size(report: Path, test: dict) -> int:
    """How many report elements this test's page actually holds."""
    page = report / "tests" / f"test_{test.get('uid')}" / "test.js"
    try:
        return len(_js_object(page).get("reportElements") or ())
    except (OSError, ValueError):
        return 0


def _richest_per_class(report: Path, tests: list[dict]) -> list[dict]:
    """One entry per class: the page a reviewer would actually read.

    difido writes a placeholder entry when a test starts and a full one when
    it ends, so a run of three suites leaves six entries and six folders.
    Carrying the placeholders into the merged index would list each test twice
    and offer an empty page as one of the two.
    """
    best: dict[str, tuple[int, dict]] = {}
    for test in tests:
        name = (test.get("className") or test.get("name") or "")
        size = _page_size(report, test)
        if name not in best or size > best[name][0]:
            best[name] = (size, test)
    return [t for _, t in best.values()]


def merge(sources: list[Path], dest: Path) -> list[dict]:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    # The reporter's static assets, from the first source that actually has
    # them. Without index.html the merged directory is a set of pages with no
    # way in, which is worse than the report it replaces and would be found by
    # whoever opens it - so it is refused here rather than produced.
    assets = next((s for s in sources if (s / "index.html").is_file()), None)
    if assets is None:
        raise SystemExit(
            "none of the source reports carries index.html, so there is "
            "nothing to open the merged report with. Pass a report directory "
            "as difido wrote it, not just its tests/ folder.")
    for name in _STATIC:
        src = assets / name
        if src.is_dir():
            shutil.copytree(src, dest / name)
        elif src.is_file():
            shutil.copy2(src, dest / name)

    (dest / "tests").mkdir()

    # Collect first, refuse second, copy last: a merged report that silently
    # dropped one of two runs of the same test would be the same class of
    # defect as the report this tool exists to replace.
    chosen: list[tuple[Path, dict]] = []
    for report in sources:
        execution_js = report / "execution.js"
        if not execution_js.is_file():
            raise SystemExit(f"{report} has no execution.js")
        for test in _richest_per_class(report, _tests(_js_object(execution_js))):
            chosen.append((report, test))

    by_class: dict[str, list[Path]] = {}
    for report, test in chosen:
        by_class.setdefault(test.get("className") or "?", []).append(report)
    clashes = {cls: rs for cls, rs in by_class.items() if len(rs) > 1}
    if clashes:
        lines = [f"  {cls.rsplit('.', 1)[-1]}: "
                 + ", ".join(r.name for r in rs)
                 for cls, rs in sorted(clashes.items())]
        raise SystemExit(
            "refusing to merge: these test classes appear in more than one "
            "source report, so the merged index would either list the same "
            "test twice or hide one run behind the other.\n"
            + "\n".join(lines)
            + "\n\nPass one report per test - the run you mean to ship.")

    # TC01, TC02, TC03, whatever order the reports were produced in. A
    # reviewer reads the index in test order, not in run order.
    chosen.sort(key=lambda rt: rt[1].get("className") or "")

    kept: list[dict] = []
    for report, test in chosen:
        uid = str(test.get("uid"))
        folder = report / "tests" / f"test_{uid}"
        if not folder.is_dir():
            raise SystemExit(
                f"{report.name} lists test_{uid} but has no folder for it")
        shutil.copytree(folder, dest / "tests" / f"test_{uid}")
        kept.append({**test, "index": len(kept) + 1})

    machine = sources[0].joinpath("execution.js")
    template = _js_object(machine)
    host = (template.get("machines") or [{}])[0].get("name", "merged")

    execution = {"machines": [{
        "type": "machine",
        "name": host,
        "plannedTests": len(kept),
        "status": _worst(kept),
        "children": [{
            "type": "scenario",
            "scenarioProperties": None,
            "name": "default",
            "status": _worst(kept),
            "children": kept,
        }],
    }]}
    (dest / "execution.js").write_text(
        "var execution = " + json.dumps(execution) + ";", encoding="utf-8")
    return kept


#: difido's own ordering, worst last.
_RANK = ("success", "warning", "failure", "error")


def _worst(tests: list[dict]) -> str:
    return max((t.get("status", "success") for t in tests),
               key=lambda s: _RANK.index(s) if s in _RANK else len(_RANK),
               default="success")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sources", nargs="+", type=Path,
                    help="difido report directories, in the order to list them")
    ap.add_argument("-o", "--out", required=True, type=Path,
                    help="destination directory (replaced if it exists)")
    args = ap.parse_args(argv[1:])

    kept = merge(args.sources, args.out)
    print(f"merged {len(args.sources)} report(s) -> {args.out}")
    for test in kept:
        name = (test.get("className") or "?").rsplit(".", 1)[-1]
        print(f"  {test['index']}. {name:38} {test.get('status')}")
    print(f"open {args.out / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

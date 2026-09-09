#!/usr/bin/env python3
"""Refuse to ship a client package that is weaker than what we have proven.

The last line of defence, and the only one with no escape hatch.

`ate codegen` already refuses to drop a capability proven on hardware, but it
can be overridden with `--accept-regression` because the 3-AC spec topology is
a legitimate thing to generate locally. This gate exists because "legitimate to
generate" and "legitimate to ship" are different questions, and on 2026-08-14
they were answered by the same command.

It reads the files that are actually inside the package — not the profile that
was meant to produce them, not the pipeline's exit code, not what a README
says. That is the point. The regression it was written for had a healthy
pipeline that exited zero, three green tests, and a `.cfg` with no control
plane in it.

    ./scripts/verify_handover_package.py <package>/01_generated_suite

Exit 0 = shippable. Exit 1 = do not send this to a client, with the reason.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ate.codegen.capabilities import CAPABILITIES, regressions  # noqa: E402

#: Caveats that must never reach a client inside a step title.
#:
#: A step whose own name apologises for the rig is a step asserting something
#: it cannot assert. TC01 shipped with "Verify the Type-3 IMET route ... (no
#: BGP peer on this rig)" — accurate, visible in the source, and read by
#: everyone who saw it as a known limitation rather than as the defect it was.
_CAVEAT_PATTERNS = (
    re.compile(r"no .{0,40}on this rig", re.I),
    re.compile(r"\bnot wired\b", re.I),
    re.compile(r"\bnot yet (?:wired|validated|implemented)\b", re.I),
    re.compile(r"\bwithout a (?:real |BGP )?peer\b", re.I),
)


def _load(root: Path) -> dict[str, str]:
    """Every text artifact in the package, keyed by path relative to root."""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix in {".java", ".cfg", ".crt", ".tcl"}:
            out[str(p.relative_to(root))] = p.read_text(
                encoding="utf-8", errors="replace")
    return out


def _caveats_in_step_titles(files: dict[str, str]) -> list[str]:
    """Caveat text inside a CompassReporter step title in a shipped test."""
    found = []
    for path, content in files.items():
        if not Path(path).name.startswith("TC"):
            continue
        for n, line in enumerate(content.splitlines(), 1):
            if "stopAndStartLevel" not in line:
                continue
            for pat in _CAVEAT_PATTERNS:
                if pat.search(line):
                    found.append(f"{path}:{n}: {line.strip()}")
                    break
    return found


def _structural_checks(files: dict[str, str]) -> list[str]:
    """Things that must be true of any shippable suite, capability or not."""
    problems = []
    if not any(p.endswith("EVPN_Base.cfg") for p in files):
        problems.append("no DUT configuration (.cfg) in the package")
    if not any(p.endswith("bringUpParams.crt") for p in files):
        problems.append("no bringUpParams.crt in the package")
    if not any(Path(p).name.startswith("TC") for p in files):
        problems.append("no test classes in the package")

    # An underlay on one side only is the defect Exaware reported by eye. The
    # capability detectors already require both ends, but this names the
    # asymmetry directly so the message is actionable rather than abstract.
    cfg = next((c for p, c in files.items()
                if p.endswith("EVPN_Base.cfg")), "")
    has_dut_underlay = bool(re.search(r"^routing (ospf|isis|bgp)\b", cfg, re.M))
    has_tester = any(p.endswith("evpn_tester_setup.tcl") for p in files)
    if has_dut_underlay and not has_tester:
        problems.append(
            "the DUT runs routing protocols but the package contains no "
            "configurations/ixia/ tester setup - the DUT would be speaking "
            "into a port configured for nothing, which shows up only as an "
            "adjacency that never forms")

    # Exaware, 2026-09-08 (E1/E8): "The ixia config file is not in TCL
    # format, which I cannot open" and "it is expected that a traffic item
    # will be 'human readable'". The 2026-08-24 package carried exactly one
    # IXIA file, evpn_tester_setup.tcl, which is a raw `ixNet setAtt` dump of
    # the CORE link and says nothing about traffic. A package that offers
    # traffic assertions must also carry the file that says, in their own
    # library's idiom, what traffic is being built.
    has_traffic_tcl = any(p.endswith("EVPN_traffic.tcl") for p in files)
    asserts_traffic = any(
        "verifyTrafficItemStatistics" in c or "tagTrafficItemsWithAcVlan" in c
        for c in files.values())
    if asserts_traffic and not has_traffic_tcl:
        problems.append(
            "the suite asserts traffic statistics but the package contains "
            "no configurations/ixia/EVPN_traffic.tcl - the reviewer would "
            "have to read the traffic definition out of Java argument lists, "
            "which is the review comment of 2026-09-08")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    root = Path(argv[1])
    if not root.is_dir():
        print(f"error: {root} is not a directory")
        return 2

    files = _load(root)
    print(f"verifying {len(files)} artifact(s) under {root}")

    problems = _structural_checks(files)

    regs = regressions(files)
    for r in regs:
        problems.append(f"REGRESSION - {r}")

    for c in CAPABILITIES:
        if c.is_ratcheted:
            mark = "FAIL" if any(r.capability.id == c.id for r in regs) else "ok"
            print(f"  [{mark:4}] {c.id}")

    for caveat in _caveats_in_step_titles(files):
        problems.append(
            "a shipped step title admits the rig cannot support it - fix the "
            f"rig or drop the step, do not ship the apology:\n      {caveat}")

    if problems:
        print(f"\nREFUSED - {len(problems)} problem(s). "
              "This package must not go to a client.\n")
        for p in problems:
            print(f"  * {p}\n")
        return 1

    print("\nOK - every capability proven on hardware survives in these files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

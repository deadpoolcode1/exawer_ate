"""M2 code generation — test plan → JSystem/Java test suite.

Entry point: `generate_evpn_suite(...)`. The pipeline is

    SFS + CLI doc ──► requirements/CLI catalog (M1, unchanged)
                              │
                              ├─ grounding check on EvpnCommands
                              │
    curated TestScript IR ────┴──► java_emitter ──► .java files

Grounding is enforced, not advisory: if a command in the registry does not
trace to a command extracted from the CLI doc, generation raises rather than
emitting Java that would type a non-existent command at a DUT.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ate.codegen.commands import UngroundedCommandError, validate_grounding
from ate.codegen.evpn_scripts import evpn_scripts
from ate.codegen.java_emitter import JavaFile, emit_all
from ate.codegen.lab import (
    SINGLE_DUT_3AC,
    LabProfile,
    underlay_symmetry_violations,
)
from ate.codegen.script_ir import TestScript

__all__ = ["GenerationResult", "generate_evpn_suite"]


@dataclass
class GenerationResult:
    files: list[JavaFile] = field(default_factory=list)
    scripts: list[TestScript] = field(default_factory=list)
    #: `doc_suspect` notes from the command registry (CLI-doc typos etc).
    warnings: list[str] = field(default_factory=list)
    #: Steps that still need real device output, as "STEP-ID: reason".
    open_todos: list[str] = field(default_factory=list)

    @property
    def n_steps(self) -> int:
        return sum(len(s.steps) for s in self.scripts)

    def write(self, out_dir: str | Path) -> list[Path]:
        root = Path(out_dir)
        written: list[Path] = []
        for f in self.files:
            target = root / f.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f.content, encoding="utf-8")
            written.append(target)
        return written


def generate_evpn_suite(sfs_path: str | Path,
                        cli_doc_path: str | Path,
                        lab: LabProfile = SINGLE_DUT_3AC,
                        plan_xlsx: str | Path | None = None,
                        plan_flows: list[str] | None = None,
                        captures_path: str | Path | None = None,
                        ) -> GenerationResult:
    """Generate the EVPN JSystem suite for the three M2 flows.

    `plan_xlsx` + `plan_flows` additionally emit *mechanically* derived suites
    for flows nobody curated, straight from the generated test plan (see
    `plan_scripts.py`). They share the emitted EvpnCommands/EvpnParams/
    EvpnUtils with the curated suites, so the whole package compiles as one.
    """
    from ate.parsers import parse  # noqa: PLC0415  (heavy import)
    from ate.planner.requirements_builder import build_catalog  # noqa: PLC0415

    doc = parse(sfs_path)
    catalog = build_catalog(doc, cli_doc_path=cli_doc_path)

    # Derive the rest of the registry from the CLI doc before validating, so
    # generated code can bind commands the curated 18 never covered. Curated
    # entries stay authoritative on any conflict.
    from ate.codegen.command_deriver import derive_commands  # noqa: PLC0415
    from ate.codegen.commands import set_derived_commands  # noqa: PLC0415

    derived, derive_notes = derive_commands(catalog.cli_commands)
    set_derived_commands(derived)

    # Raises UngroundedCommandError if any template has no CLI-doc origin.
    warnings = validate_grounding(catalog.cli_commands)

    scripts = evpn_scripts(lab)
    if plan_xlsx and plan_flows:
        from ate.codegen.plan_scripts import scripts_from_plan  # noqa: PLC0415
        scripts = scripts + scripts_from_plan(plan_xlsx, plan_flows, lab)
    # Expectations captured from a real device, if any have been. Without
    # this the device loop stops one step short: `ate capture` writes a file
    # and nothing reads it, so every expectation ships empty and every verify
    # step warns instead of asserting.
    captures, capture_notes = _load_captures(captures_path)

    # PIPELINE RULE: nothing may fake a pass. A verification step that cannot
    # fail is worse than a missing one - a red test gets fixed, a green test
    # that checks nothing gets trusted. Fatal, like an ungrounded command.
    from ate.codegen.fake_pass import (  # noqa: PLC0415
        FakePassError,
        assertion_census,
        audit,
    )

    violations = audit(scripts, captures)
    if violations:
        raise FakePassError(
            "generated steps would report a pass without checking anything:\n  "
            + "\n  ".join(str(v) for v in violations))

    census = assertion_census(scripts, captures)
    capture_notes.append(
        f"assertions: {len(census.falsifiable)} of {census.total} verification "
        f"steps can actually fail; {len(census.warns_only)} only warn")

    files = emit_all(scripts, lab, captures)
    # Per-scenario device configuration, in the house format (modelled on
    # cmp/tests/vpls/): the bring-up table plus the DUT .cfg it loads.
    from ate.codegen.device_config import (  # noqa: PLC0415
        emit_bringup_params,
        emit_dut_config,
        emit_tester_config,
    )
    # A one-sided underlay is invisible until an adjacency quietly fails to
    # form, so refuse it here rather than ship it.
    asymmetric = underlay_symmetry_violations(lab)
    if asymmetric:
        raise UngroundedCommandError(
            "the generated underlay is one-sided: "
            + "; ".join(asymmetric))
    files += [emit_bringup_params(scripts, lab), emit_dut_config(scripts, lab)]
    tester = emit_tester_config(lab)
    if tester is not None:
        files.append(tester)
    todos = [f"{s.id}: {s.todo}" for sc in scripts for s in sc.open_todos]

    return GenerationResult(files=files, scripts=scripts,
                            warnings=warnings + capture_notes,
                            open_todos=todos)


def _load_captures(path: str | Path | None) -> tuple[dict, list[str]]:
    """Usable captures keyed by expect_key, plus notes for the caller to print.

    Only `ok` results are returned. An empty or rejected capture is not an
    expectation, and silently promoting one would defeat the whole point of
    the capture stage.
    """
    if not path:
        return {}, []
    p = Path(path)
    if not p.exists():
        return {}, [f"no captured expectations at {p} - expectations stay empty"]

    from ate.codegen.capture import CaptureSession  # noqa: PLC0415

    session = CaptureSession.load(p)
    out = {}
    for c in session.results:
        if c.usable:
            out[c.expect_key] = {
                "lines": c.lines,
                "command": c.command,
                "host": session.host,
                "build": session.build,
                "captured_at": session.captured_at,
            }
    notes = [f"captured expectations: {len(out)} of {len(session.results)} "
             f"usable, from {session.host} ({session.build}) "
             f"at {session.captured_at}"]
    return out, notes

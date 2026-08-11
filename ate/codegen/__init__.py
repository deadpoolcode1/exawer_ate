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

from ate.codegen.commands import validate_grounding
from ate.codegen.evpn_scripts import evpn_scripts
from ate.codegen.java_emitter import JavaFile, emit_all
from ate.codegen.lab import SINGLE_DUT_3AC, LabProfile
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

    # Raises UngroundedCommandError if any template has no CLI-doc origin.
    warnings = validate_grounding(catalog.cli_commands)

    scripts = evpn_scripts(lab)
    if plan_xlsx and plan_flows:
        from ate.codegen.plan_scripts import scripts_from_plan  # noqa: PLC0415
        scripts = scripts + scripts_from_plan(plan_xlsx, plan_flows, lab)
    files = emit_all(scripts, lab)
    # Per-scenario device configuration, in the house format (modelled on
    # cmp/tests/vpls/): the bring-up table plus the DUT .cfg it loads.
    from ate.codegen.device_config import (  # noqa: PLC0415
        emit_bringup_params,
        emit_dut_config,
    )
    files += [emit_bringup_params(scripts, lab), emit_dut_config(scripts, lab)]
    todos = [f"{s.id}: {s.todo}" for sc in scripts for s in sc.open_todos]

    return GenerationResult(files=files, scripts=scripts,
                            warnings=warnings, open_todos=todos)

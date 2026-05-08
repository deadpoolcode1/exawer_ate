"""Generate concrete CLI Configuration rows from the parsed CLI doc.

Closes Yossi's M1 review gap: "CLI Configuration — missing aspects of
CLI commands: validations, defaults, etc.". For each configuration
command (lacp-key, identifier, service-carving, …) we emit a focused
row family that names the actual command, its parameters, ranges,
defaults, and the negative cases:

    Configure              — happy path with the documented example
    Validate range/type    — one row per parameter that has a typed value
    Default behavior       — only emitted if the doc names a default
    Mutual exclusion       — only emitted for choice-type parameters
    `no` form              — only if the syntax shows it
    Persistence            — reload survives the configuration

Each row carries:
  - category = "CLI configuration"
  - sfs_requirement_id = "CLI:<command_name>" (synthetic anchor for traceability)
  - equipment = "DUT only (CLI session via console / SSH)"
  - action_steps = Setup/Action/Verify scaffolded multi-line
  - expectation = Pass / Fail-on multi-line

These rows replace the generic CLI Configuration template rows for any
spec requirement whose CLI surface is actually documented in the CLI doc.
"""
from __future__ import annotations

from ate.planner.cli_extractor import CliCommand, CliParameter
from ate.planner.equipment import equipment_for_cli_row
from ate.planner.model import PlanRow

EQUIPMENT = equipment_for_cli_row()


def _scaffold(setup: str, action: str, verify: str) -> str:
    return f"Setup:  {setup}\nAction: {action}\nVerify: {verify}"


def _expect(pass_: str, fail_on: str = "") -> str:
    if fail_on:
        return f"Pass:    {pass_}\nFail-on: {fail_on}"
    return f"Pass:    {pass_}"


def _mode_path_str(cmd: CliCommand) -> str:
    """Render the configuration mode entry sequence as a CLI path,
    e.g. `config / interface agg-eth 1 / ethernet-segment`.
    """
    if not cmd.mode_path:
        return "config"
    return " / ".join(cmd.mode_path)


def _example_invocation(cmd: CliCommand) -> str:
    """Pick a canonical example invocation. Prefer the first non-`no` syntax
    line; if it has placeholders, leave them so QA fills in real values.
    """
    for ln in cmd.syntax_lines:
        if not ln.lower().startswith("no "):
            return ln
    return cmd.syntax_lines[0] if cmd.syntax_lines else cmd.name


def _no_form(cmd: CliCommand) -> str:
    for ln in cmd.syntax_lines:
        if ln.lower().startswith("no "):
            return ln
    return f"no {cmd.name}"


def _typed_params(cmd: CliCommand) -> list[CliParameter]:
    """Parameters that have a concrete value spec we can validate (ranges,
    MAC formats, integers, hex octets). Choice members and untyped params
    are handled by the mutual-exclusion / happy-path rows instead.
    """
    return [p for p in cmd.parameters if p.value_spec and not p.is_choice]


def _choice_params(cmd: CliCommand) -> list[CliParameter]:
    return [p for p in cmd.parameters if p.is_choice]


def _value_spec_one_line(p: CliParameter) -> str:
    """Compress a value_spec cell (often multi-line in the doc) for the row."""
    return " ".join(p.value_spec.split())[:120]


def _negative_value_hint(p: CliParameter) -> str:
    """Pick an obviously-invalid example value from the param's value spec.
    Used in the negative-validation row.
    """
    spec = p.value_spec.lower()
    if "0..65535" in spec:
        return "65536 (above range), -1 (below range), abc (non-integer)"
    if "0..4095" in spec:
        return "4096 (above range), -1 (below range)"
    if "ipv4" in spec or "ipv6" in spec:
        return "999.999.999.999 (malformed), an unrouted address"
    if "xx:xx:xx" in spec or "mac" in spec:
        return "not-a-mac, ZZ:ZZ:ZZ:ZZ:ZZ:ZZ, 11:22:33 (truncated)"
    if "octet" in spec or "hex-decimal" in spec:
        return "non-hex characters, truncated octet count, length-mismatched value"
    if "integer" in spec:
        return "non-integer string, negative number, value above documented bound"
    return "a value clearly outside the documented spec"


def rows_for_command(cmd: CliCommand) -> list[PlanRow]:
    """Build the row family for one CLI command. Returns [] for show/clear
    commands — those don't populate the CLI Configuration section.
    """
    if not cmd.is_config:
        return []

    rows: list[PlanRow] = []
    req_anchor = f"CLI:{cmd.name}"
    cat = "CLI configuration"
    mode = _mode_path_str(cmd)
    invocation = _example_invocation(cmd)
    related = (", ".join(cmd.related_features)
               if cmd.related_features else "general EVPN config")

    # ── Row 1: Happy-path configure ──────────────────────────────────────
    rows.append(PlanRow(
        category=cat,
        sub_category=cmd.name,
        equipment=EQUIPMENT,
        sfs_requirement_id=req_anchor,
        action_steps=_scaffold(
            f"DUT booted; no prior `{cmd.name}` configuration; "
            f"prerequisite mode reachable: {mode}.",
            f"Enter the documented mode and issue: `{invocation}`. "
            f"Commit the candidate config.",
            f"`show running-config` includes `{cmd.name}` under {mode}; "
            f"feature ({related}) reads back as expected via its `show` command.",
        ),
        expectation=_expect(
            f"`{cmd.name}` accepted, persists in running-config, "
            f"feature operates per documented behaviour",
            "Commit error, parse rejection, or feature fails to come up "
            "with the new config",
        ),
    ))

    # ── Row 2..N: Range / type validation per typed parameter ────────────
    for p in _typed_params(cmd):
        spec = _value_spec_one_line(p)
        bad = _negative_value_hint(p)
        rows.append(PlanRow(
            category=cat,
            sub_category=cmd.name,
            equipment=EQUIPMENT,
            sfs_requirement_id=req_anchor,
            action_steps=_scaffold(
                f"DUT in mode `{mode}`.",
                f"Issue `{cmd.name} <{p.name}>` with values: "
                f"(a) a valid in-spec value (per {spec!r}); "
                f"(b) invalid values: {bad}.",
                "Valid value commits and is read back with the "
                "correct type/format; each invalid value is rejected "
                "at parse time with a CLI error message naming the "
                "parameter; running-config does NOT contain the bad value.",
            ),
            expectation=_expect(
                f"Valid `<{p.name}>` accepted; each invalid value rejected "
                f"with a parse error; running-config remains clean",
                f"Invalid value silently accepted, feature crashes, or "
                f"running-config retains a partial/invalid `{cmd.name}` line",
            ),
        ))

    # ── Mutual exclusion row for choice parameters ───────────────────────
    choices = _choice_params(cmd)
    if len(choices) >= 2:
        choice_names = " | ".join(p.name for p in choices)
        rows.append(PlanRow(
            category=cat,
            sub_category=cmd.name,
            equipment=EQUIPMENT,
            sfs_requirement_id=req_anchor,
            action_steps=_scaffold(
                f"DUT in mode `{mode}`.",
                f"Configure `{cmd.name}` with one choice "
                f"(e.g. `{choices[0].name}`); commit; then reconfigure with "
                f"a different choice ({choice_names}); commit.",
                "Only one choice is active at a time in running-config; "
                "second commit replaces the first cleanly; feature reflects "
                "the latest choice in its `show` output.",
            ),
            expectation=_expect(
                "Mutually-exclusive choices replace each other on commit",
                "Both choices appear in running-config simultaneously, or "
                "feature retains old behaviour after switch",
            ),
        ))

    # ── Default-behavior row, only if doc names a default ────────────────
    if cmd.default_behavior:
        rows.append(PlanRow(
            category=cat,
            sub_category=cmd.name,
            equipment=EQUIPMENT,
            sfs_requirement_id=req_anchor,
            action_steps=_scaffold(
                f"DUT booted with no `{cmd.name}` configuration in "
                f"mode `{mode}`.",
                f"Bring the parent feature up without configuring "
                f"`{cmd.name}`; observe the default behaviour.",
                f"Feature operates with the documented default "
                f"(\"{cmd.default_behavior}\"); `show running-config` "
                f"omits the line; subsequent explicit configuration "
                f"of the documented default value is a no-op (idempotent).",
            ),
            expectation=_expect(
                f"Default behaviour matches doc: \"{cmd.default_behavior}\"",
                "Default differs from doc, or explicit config of default "
                "value changes running-config (non-idempotent)",
            ),
        ))

    # ── `no` form row, if syntax shows it ────────────────────────────────
    if cmd.has_no_form:
        rows.append(PlanRow(
            category=cat,
            sub_category=cmd.name,
            equipment=EQUIPMENT,
            sfs_requirement_id=req_anchor,
            action_steps=_scaffold(
                f"`{cmd.name}` configured (Row 1 happy-path).",
                f"Issue `{_no_form(cmd)}`; commit.",
                f"`show running-config` no longer contains `{cmd.name}`; "
                f"feature reverts to default behaviour; no stale state in "
                f"`show` outputs or kernel forwarding tables.",
            ),
            expectation=_expect(
                f"`{cmd.name}` removed cleanly; feature reverts to default",
                "Stale config in running-config, feature stuck in old state, "
                "or kernel state inconsistent with control plane",
            ),
        ))

    # ── Persistence row ──────────────────────────────────────────────────
    rows.append(PlanRow(
        category=cat,
        sub_category=cmd.name,
        equipment=EQUIPMENT,
        sfs_requirement_id=req_anchor,
        action_steps=_scaffold(
            f"`{cmd.name}` configured and committed under {mode}.",
            "Save running-config; reload the DUT.",
            f"After full boot, `show running-config` contains the same "
            f"`{cmd.name}` line; feature comes up automatically with the "
            f"saved configuration.",
        ),
        expectation=_expect(
            f"`{cmd.name}` survives reload byte-identical; feature auto-resumes",
            "Config lost on reload, partial-restore, or feature requires "
            "manual re-config after reload",
        ),
    ))

    # ── Notes-driven prerequisite row ────────────────────────────────────
    # Many EVPN commands document hard preconditions in Notes
    # ("can be configured only if the interface is L2", "cannot be
    # configured if interface is already attached to EVPN"). Validate
    # these explicitly — Yossi's "feature understanding" gap.
    if cmd.notes:
        notes_short = " ".join(cmd.notes.split())
        if len(notes_short) > 220:
            notes_short = notes_short[:217] + "…"
        rows.append(PlanRow(
            category=cat,
            sub_category=cmd.name,
            equipment=EQUIPMENT,
            sfs_requirement_id=req_anchor,
            action_steps=_scaffold(
                f"DUT in mode `{mode}` with the prerequisite NOT met "
                f"(see Notes: \"{notes_short}\").",
                f"Attempt to issue `{cmd.name}` while the prerequisite is "
                f"unmet; commit.",
                "CLI rejects the command with a precondition error that "
                "identifies which Note was violated; running-config "
                "unchanged; satisfying the prerequisite then permits the "
                "command on retry.",
            ),
            expectation=_expect(
                "Precondition enforced at parse/commit time with a clear error",
                "Command silently accepted, feature half-configured, or "
                "error message does not identify the violated precondition",
            ),
        ))

    return rows


def cli_command_rows(commands: list[CliCommand]) -> list[PlanRow]:
    """Concatenate all CLI configuration rows in stable order.

    Group order: commands appear in the order they were extracted from
    the doc (which is doc order), so QA can read the section linearly
    against the CLI manual.
    """
    out: list[PlanRow] = []
    for cmd in commands:
        out.extend(rows_for_command(cmd))
    return out

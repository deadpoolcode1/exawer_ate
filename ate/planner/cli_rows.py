"""Generate concrete CLI Configuration rows from the parsed CLI doc.

Closes the QA review gap: "CLI tests are aimed to test the commands
required by the feature (structure, allowed options, allowed values,
**filters, help**, persistency)." For each configuration command
(lacp-key, identifier, service-carving, …) we emit a focused row
family that names the actual command, its parameters, ranges,
defaults, and the negative cases:

    Configure              — happy path with the documented example
    Validate range/type    — one row per parameter that has a typed value
    Default behavior       — only emitted if the doc names a default
    Mutual exclusion       — only emitted for choice-type parameters
    `no` form              — only if the syntax shows it
    Persistence            — reload survives the configuration
    Help & completion      — `?` lists allowed tokens, TAB completes
    Output filter          — `show running-config | include <cmd>`
                             returns only matching lines

For documented show commands (`show evpn …`, `show running-config`,
`show alarms`, …) we emit a separate per-show-command family:

    Show invocation        — happy path with the documented example
    Show output filter     — `… | include`, `… | exclude` filter pipes
    Show help              — `?` after the show command lists sub-tokens

Each row carries:
  - category = "CLI configuration"
  - sfs_requirement_id = "CLI:<command_name>" (synthetic anchor)
  - equipment = "DUT only (CLI session via console / SSH)"
  - action_steps = numbered Setup/Action/Verify steps
  - expectation = Pass / Fail-on multi-line

These rows replace the generic CLI Configuration template rows for any
spec requirement whose CLI surface is actually documented in the CLI doc.
"""
from __future__ import annotations

from ate.planner.cli_extractor import CliCommand, CliParameter
from ate.planner.equipment import equipment_for_cli_row
from ate.planner.model import PlanRow

EQUIPMENT = equipment_for_cli_row()


def _numbered(items: list[str]) -> str:
    """Render `items` as numbered steps "1. … 2. … 3. …".

    Numbered steps make rows directly translatable to test code: each
    step maps to one assertion / command invocation in the generated
    runner. Closes the QA pushback that prose-form steps were too
    template-shaped to feed automation codegen.
    """
    return "\n".join(f"  {i}. {s}" for i, s in enumerate(items, 1))


def _scaffold(setup: list[str] | str, action: list[str] | str,
              verify: list[str] | str) -> str:
    """Render Setup / Action / Verify with numbered sub-steps.

    Each section accepts either a single sentence (legacy callers) or a
    list of step strings — list inputs render as numbered steps so
    codegen can iterate.
    """
    def _block(label: str, body: list[str] | str) -> str:
        if isinstance(body, list):
            return f"{label}:\n{_numbered(body)}"
        return f"{label}:  {body}"
    return "\n".join([
        _block("Setup", setup),
        _block("Action", action),
        _block("Verify", verify),
    ])


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

    # ── Help & completion row ─────────────────────────────────────────────
    # QA explicitly listed "help" + "filters" as required CLI-test
    # aspects. This row validates that interactive help (`?`) and TAB
    # completion expose the documented sub-tokens / parameters and
    # carry non-empty descriptions — without this, an operator can't
    # discover the command from the prompt.
    rows.append(PlanRow(
        category=cat,
        sub_category=cmd.name,
        equipment=EQUIPMENT,
        sfs_requirement_id=req_anchor,
        action_steps=_scaffold(
            [
                f"DUT in mode `{mode}` (no `{cmd.name}` configured yet).",
            ],
            [
                f"At the prompt, type `{cmd.name.split()[0]} ?` and inspect "
                "the help listing.",
                f"At the prompt, type the first letters of `{cmd.name.split()[0]}` "
                "and press TAB; observe completion behaviour.",
                f"After entering `{cmd.name.split()[0]} `, type `?` again to "
                "list the next-token completions for this command.",
            ],
            [
                f"Help (`?`) lists `{cmd.name.split()[0]}` with a non-empty "
                "one-line description.",
                "TAB completes uniquely (or offers the documented set when "
                "ambiguous); zero tokens outside the CLI doc's Parameters "
                "Table.",
                "Sub-token help shows every documented parameter from the "
                "CLI doc's Parameters Table (no missing token, no extra).",
            ],
        ),
        expectation=_expect(
            f"`{cmd.name}` is discoverable from `?` and TAB; sub-token help "
            "lists exactly the documented parameters.",
            "Command absent from `?` listing, TAB does not complete, or "
            "sub-token help drops / invents parameters vs. the CLI doc.",
        ),
    ))

    # ── Output-filter / running-config introspection row ────────────────
    # QA explicitly listed "filters" as required. `show running-config |
    # include <token>` is the standard way an operator inspects a
    # configured command in isolation; it must work for every config
    # command and must return only matching lines.
    rows.append(PlanRow(
        category=cat,
        sub_category=cmd.name,
        equipment=EQUIPMENT,
        sfs_requirement_id=req_anchor,
        action_steps=_scaffold(
            [
                f"`{cmd.name}` configured and committed under {mode}.",
            ],
            [
                f"Run `show running-config | include {cmd.name.split()[0]}` "
                "and inspect the output.",
                f"Run `show running-config | exclude {cmd.name.split()[0]}` "
                "and inspect the output.",
                "Run `show running-config | begin <parent-mode>` to scope "
                f"output to the {mode} block.",
            ],
            [
                f"`| include` returns only lines that contain `{cmd.name.split()[0]}` "
                "(no false positives, no missing matches).",
                f"`| exclude` omits all `{cmd.name.split()[0]}` lines but "
                "keeps the rest of the running-config intact.",
                f"`| begin` correctly scopes output to the parent mode "
                f"({mode}) and preserves indentation.",
            ],
        ),
        expectation=_expect(
            "All three filter forms behave per documented semantics; "
            "filtered output matches the unfiltered grep equivalent.",
            "Filter pipe rejects the command, returns wrong subset, "
            "drops the matching command line, or breaks indentation.",
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


def rows_for_show_command(cmd: CliCommand) -> list[PlanRow]:
    """Row family for a `show` / `clear` command.

    Three rows:
      - Invocation: command runs without a parent feature; output
        structurally well-formed (header, columns, no parser error).
      - Output filter: `| include`, `| exclude`, `| begin` filter the
        output as documented; field counts are sane.
      - Help & completion: `?` lists the command's sub-tokens; TAB
        completes; help text is non-empty.

    Empty list for a command without a recognizable name.
    """
    if cmd.kind not in ("show", "clear"):
        return []

    rows: list[PlanRow] = []
    req_anchor = f"CLI:{cmd.name}"
    cat = "CLI configuration"
    invocation = (
        cmd.syntax_lines[0] if cmd.syntax_lines else cmd.name
    )
    head_token = cmd.name.split()[0] if cmd.name else "show"

    # ── Show invocation ─────────────────────────────────────────────────
    rows.append(PlanRow(
        category=cat,
        sub_category=cmd.name,
        equipment=EQUIPMENT,
        sfs_requirement_id=req_anchor,
        action_steps=_scaffold(
            [
                "DUT booted; CLI session via console / SSH; no parent "
                "feature required for the show command itself.",
            ],
            [
                f"Issue `{invocation}` at the operational prompt.",
                "Issue the command twice in succession to confirm "
                "idempotence on a stable system.",
            ],
            [
                "Output rendered without a parser error; header / column "
                "labels match the documented format.",
                "Subsequent invocations produce identical output for an "
                "unchanged system state.",
            ],
        ),
        expectation=_expect(
            f"`{cmd.name}` produces well-formed output, idempotent on "
            "stable state.",
            "Parser error, missing columns, or output drift on a stable "
            "system.",
        ),
    ))

    # ── Output filter ───────────────────────────────────────────────────
    rows.append(PlanRow(
        category=cat,
        sub_category=cmd.name,
        equipment=EQUIPMENT,
        sfs_requirement_id=req_anchor,
        action_steps=_scaffold(
            [
                f"DUT booted; `{cmd.name}` returns multi-line output.",
            ],
            [
                f"Run `{cmd.name} | include <known-token>` for a token that "
                "appears in the unfiltered output.",
                f"Run `{cmd.name} | exclude <known-token>`.",
                f"Run `{cmd.name} | begin <known-section-header>`.",
                f"Run `{cmd.name} | count` (if supported by the platform).",
            ],
            [
                "`| include` returns only lines containing the token.",
                "`| exclude` returns the unfiltered output minus those lines.",
                "`| begin` skips lines until the named section.",
                "`| count` returns an integer matching the unfiltered line "
                "count (or `| count` reported as unsupported with a clear "
                "message).",
            ],
        ),
        expectation=_expect(
            "All four filter pipes behave per documented semantics.",
            "Filter rejects, returns wrong subset, or breaks output structure.",
        ),
    ))

    # ── Help & completion for the show command ─────────────────────────
    rows.append(PlanRow(
        category=cat,
        sub_category=cmd.name,
        equipment=EQUIPMENT,
        sfs_requirement_id=req_anchor,
        action_steps=_scaffold(
            [
                "DUT booted; CLI session attached.",
            ],
            [
                f"At the operational prompt type `{head_token} ?`.",
                f"Type the first letters of `{head_token}` and press TAB.",
                f"After typing `{cmd.name} `, type `?` to list sub-token "
                "completions.",
            ],
            [
                f"Help (`?`) lists `{head_token}` with a non-empty "
                "description.",
                "TAB completes uniquely or offers the documented set; "
                "zero tokens outside the CLI doc's Parameters Table.",
                f"Sub-token help under `{cmd.name}` lists each documented "
                "argument / filter (matches the CLI doc).",
            ],
        ),
        expectation=_expect(
            f"`{cmd.name}` is discoverable via `?` and TAB; sub-token help "
            "lists every documented argument.",
            "Command absent from help, TAB does not complete, or "
            "sub-token help diverges from the CLI doc.",
        ),
    ))

    return rows


def cli_command_rows(commands: list[CliCommand]) -> list[PlanRow]:
    """Concatenate all CLI configuration rows in stable order.

    Group order: config commands first (in doc order), then show /
    clear commands. Within each command, the row family is emitted in
    a fixed order so QA reads the section linearly against the CLI
    manual.
    """
    out: list[PlanRow] = []
    for cmd in commands:
        if cmd.is_config:
            out.extend(rows_for_command(cmd))
    for cmd in commands:
        if cmd.kind in ("show", "clear"):
            out.extend(rows_for_show_command(cmd))
    return out

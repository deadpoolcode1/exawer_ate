"""Generate concrete CLI Configuration rows from the parsed CLI doc.

Closes the QA review gap: "CLI tests are aimed to test the commands
required by the feature (structure, allowed options, allowed values,
help, persistency)." For each configuration command (lacp-key,
identifier, service-carving, …) we emit a focused row family that names
the actual command, its parameters, ranges, defaults, the documented
value set, and the documented preconditions.

Client review (2026-06-01, "TP — Test Plan Topics") reshaped this
section:
  - **Monitor is Exaware-CLI-exact** — `show configuration` (Exaware has
    no `show running-config`) plus the precise feature `show`
    (`show evpn ethernet-segments`, `show bgp l2vpn evpn neighbors`, …),
    never a generic placeholder. See `_feature_show_for`.
  - **The mode-entry action is concrete** — "At the
    `configuration interface agg-eth ethernet-segment` level, configure
    `identifier 0 <type0-value>`" instead of the old obscure "Enter the
    documented mode".
  - **Pipe (`|`) modifier rows are gone** — they were emitted for every
    command and added no feature signal.
  - **Preconditions are tested one-per-row** with a descriptive-error
    expectation, parsed out of the command's Notes cell (e.g.
    ethernet-segment "only on an L2 interface" / "not when already
    attached to an EVPN instance").
  - **The documented value set is tested** (e.g. ESI `identifier`
    types 0 / 1 / 4) via `_syntax_variants`.
  - **Commands are ordered by command mode**, not alphabetically — all
    `… interface agg-eth ethernet-segment` commands together, then the
    `… l2-services evpn` group, etc. See `cli_command_rows`.
  - **Show commands expand their grammar** into the specific cases
    (`{advertised-routes | received-routes} … [brief | detail]` →
    enumerated invocations) and **clear commands verify the cleared
    state**, not "well-formed output".

Each row carries:
  - category = "CLI configuration"
  - sfs_requirement_id = "CLI:<command_name>" (synthetic anchor)
  - equipment = "DUT only (CLI session via console / SSH)"
  - action_steps = numbered Setup/Action/Verify steps
  - expectation = Pass / Fail-on multi-line

These rows are authored deterministically and are NOT sent through the
AI enricher (ai_enricher skips `source == "cli"`), so the wording stays
precise and Exaware-CLI-aligned.
"""
from __future__ import annotations

import re

from ate.planner.cli_extractor import CliCommand, CliParameter
from ate.planner.cli_inheritance import sub_config_names_for
from ate.planner.equipment import equipment_for_cli_row
from ate.planner.model import PlanRow

EQUIPMENT = equipment_for_cli_row()


def _numbered(items: list[str]) -> str:
    """Render `items` as numbered steps "1. … 2. … 3. …"."""
    return "\n".join(f"  {i}. {s}" for i, s in enumerate(items, 1))


def _scaffold(setup: list[str] | str, action: list[str] | str,
              verify: list[str] | str) -> str:
    """Render Setup / Action / Verify with numbered sub-steps."""
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
    e.g. `configuration interface agg-eth ethernet-segment`.
    """
    if not cmd.mode_path:
        return "configuration"
    return " ".join(cmd.mode_path)


# Argument tokens carry a value the operator substitutes. We render them
# as `<token>` placeholders so a row never reads like a literal command
# (client 2026-06-01: "there's no `identifier 0 type0-value` command —
# type0 should be a value").
_PLACEHOLDER_SUFFIX_RE = re.compile(
    r"^[a-z][a-z0-9-]*-(ip|id|name|prefix|addr|address|if|value|key)$",
    re.IGNORECASE,
)


def _wrap_placeholders(text: str, param_names: set[str]) -> str:
    """Wrap bare value tokens in angle brackets.

    A token is a placeholder if it matches a documented parameter name or
    looks like an argument (ends in -ip / -id / -name / -prefix / -value …).
    Tokens already bracketed (`<x>`, `{a|b}`) are left alone.
    """
    out: list[str] = []
    for tok in text.split(" "):
        bare = tok
        if (bare and bare[0] not in "<{[|" and bare[-1] not in ">}]"
                and (bare in param_names or _PLACEHOLDER_SUFFIX_RE.match(bare))):
            out.append(f"<{bare}>")
        else:
            out.append(tok)
    return " ".join(out)


def _example_invocation(cmd: CliCommand) -> str:
    """Pick a canonical example invocation (first non-`no` syntax line),
    with value tokens rendered as `<placeholders>`.
    """
    raw = ""
    for ln in cmd.syntax_lines:
        if not ln.lower().startswith("no "):
            raw = ln
            break
    if not raw:
        raw = cmd.syntax_lines[0] if cmd.syntax_lines else cmd.name
    param_names = {p.name for p in cmd.parameters if p.name}
    return _wrap_placeholders(raw, param_names)


def _syntax_variants(cmd: CliCommand) -> list[str]:
    """Non-`no` syntax lines — the documented invocation variants. A
    command with ≥2 (e.g. ESI `identifier 0|1|4`) defines a value set we
    test explicitly.
    """
    return [ln for ln in cmd.syntax_lines if not ln.lower().startswith("no ")]


def _variant_values(cmd: CliCommand) -> list[str]:
    """For a multi-variant command, the discriminating value token of each
    variant (e.g. identifier 0 / 1 / 4 → ['0', '1', '4'])."""
    base = cmd.name.split()[0] if cmd.name else ""
    base_len = len(base.split())
    values: list[str] = []
    for ln in _syntax_variants(cmd):
        toks = ln.split()
        if len(toks) > base_len:
            values.append(toks[base_len])
    return values


def _no_form(cmd: CliCommand) -> str:
    for ln in cmd.syntax_lines:
        if ln.lower().startswith("no "):
            return ln
    return f"no {cmd.name}"


def _typed_params(cmd: CliCommand) -> list[CliParameter]:
    return [p for p in cmd.parameters if p.value_spec and not p.is_choice]


def _choice_params(cmd: CliCommand) -> list[CliParameter]:
    return [p for p in cmd.parameters if p.is_choice]


def _value_spec_one_line(p: CliParameter) -> str:
    return " ".join(p.value_spec.split())[:120]


def _negative_value_hint(p: CliParameter) -> str:
    spec = p.value_spec.lower()
    if "0..65535" in spec:
        return "65536 (above range), -1 (below range), abc (non-integer)"
    if "0..4095" in spec:
        return "4096 (above range), -1 (below range)"
    if "ipv4" in spec or "ipv6" in spec:
        return "999.999.999.999 (malformed), an unrouted address"
    if "xx:xx:xx" in spec or "mac" in spec:
        return "not-a-mac, ZZ:ZZ:ZZ:ZZ:ZZ:ZZ, 11:22:33 (truncated)"
    if "octet" in spec or "hex-decimal" in spec or "hexadecimal" in spec:
        return "non-hex characters, truncated octet count, length-mismatched value"
    if "integer" in spec:
        return "non-integer string, negative number, value above documented bound"
    return "a value clearly outside the documented spec"


# ── Monitor: the exact Exaware `show` for each command ───────────────────
# Client 2026-06-01: the Monitor column must be Exaware-CLI-exact —
# `show configuration` (NOT `show running-config`, which Exaware does not
# have) plus the precise feature show. Keyed off the command's
# configuration mode and name; values are the real commands from the EVPN
# CLI doc's show section.
def _feature_show_for(cmd: CliCommand) -> list[str]:
    """The feature-specific `show` command(s) that read back `cmd`'s effect.

    Always paired with `show configuration` by the callers (which is the
    persistence/read-back check). Returns [] when the EVPN CLI doc has no
    matching operational show (VPLS-context commands), in which case the
    monitor is `show configuration` alone.
    """
    name = cmd.name.lower()
    mode = cmd.mode_path
    if "ethernet-segment" in mode or name in (
            "ethernet-segment", "identifier", "lacp-key", "lacp-system-mac",
            "load-balancing-mode", "service-carving"):
        return ["show evpn ethernet-segments [esi <es-id>]",
                "show interface agg-eth <agg-id> detail"]
    if name == "af-l2vpn evpn" or "af-l2vpn" in mode:
        return ["show bgp neighbors <neighbor-ip> detail",
                "show bgp l2vpn evpn neighbors received-routes <neighbor-ip> detail"]
    if name == "evpn":
        return ["show evpn global [name <evpn-name>]",
                "show evpn summary [name <evpn-name>]"]
    # l2-services/evpn knobs (MAC, control-word, advertise-mac, timers …)
    if mode and mode[-1] == "evpn":
        return ["show evpn global [name <evpn-name>]",
                "show evpn mac-address-table [name <evpn-name>]"]
    if "interface" in name and "vpls" in name:
        # AC binding under VPLS/EVPN — the FIB shows the attachment circuit.
        return ["show fib evpn-ac"]
    # VPLS-context knobs: EVPN CLI doc has no VPLS show — read back via
    # `show configuration` only (callers add it).
    return []


def _monitor_list(cmd: CliCommand, include_feature: bool = True) -> list[str]:
    """`show configuration` + feature show(s)."""
    mons = ["show configuration"]
    if include_feature:
        mons.extend(_feature_show_for(cmd))
    return mons


def _verify_with_monitors(lines: list[str], monitors: list[str]) -> list[str]:
    """Append a backticked read-back step per monitor so atomic_rows lifts
    them into the Monitor column."""
    out = list(lines)
    for m in monitors:
        out.append(f"Read back via `{m}`.")
    return out


# ── Precondition (Notes) parsing — one row per documented constraint ─────
_CUE_CANNOT = re.compile(
    r"can\s*not be configured|cannot be configured", re.IGNORECASE)
_CUE_ONLY_IF = re.compile(r"only if\s*:?\s*$", re.IGNORECASE)
_AND_SPLIT = re.compile(r"\s+AND\s*$|\s+AND\s+")


def _clean_clause(text: str) -> str:
    return " ".join(text.split()).strip().rstrip(".").strip("`").strip()


def _prerequisite_clauses(cmd: CliCommand) -> list[tuple[str, str]]:
    """Parse the Notes cell into (kind, condition) precondition tuples.

    kind ∈ {"only-if", "cannot", "only", "must"}. Informational prose
    (no constraint cue) is dropped so we don't emit a bogus
    "rejected with an error" row for it. The result drives one focused
    precondition row each (client 2026-06-01, item 10).
    """
    notes = cmd.notes or ""
    if not notes.strip():
        return []
    lines = [ln.strip() for ln in notes.splitlines() if ln.strip()]
    clauses: list[tuple[str, str]] = []
    collecting_only_if = False
    for ln in lines:
        low = ln.lower()
        if _CUE_ONLY_IF.search(ln):
            collecting_only_if = True
            continue
        if collecting_only_if:
            if (low.startswith("the command cannot") or low.startswith("it means")
                    or low.startswith("if ")):
                collecting_only_if = False
                # fall through to normal handling below
            else:
                for part in _AND_SPLIT.split(ln):
                    cond = _clean_clause(part)
                    if cond:
                        clauses.append(("only-if", cond))
                continue
        for sent in re.split(r"(?<=[.])\s+", ln):
            s = _clean_clause(sent)
            sl = s.lower()
            if not s:
                continue
            if "cannot change the evpn parameters" in sl:
                continue  # redundant restatement of "already attached"
            if _CUE_CANNOT.search(s):
                cond = re.sub(
                    r"^.*?can\s*not be configured\s*(if|when)?\s*", "", s,
                    flags=re.IGNORECASE).strip()
                clauses.append(("cannot", _clean_clause(cond)))
            elif "supported only" in sl or "only in vrf" in sl:
                clauses.append(("only", s))
            elif (sl.startswith("only interfaces")
                  or "can be configured as an attachment circuit" in sl
                  or "can be configured on interface types" in sl):
                clauses.append(("only", s))
            elif sl.startswith("you must") or sl.startswith("must "):
                clauses.append(("must", s))
            elif "mandatory" in sl and "cannot be deleted" in sl:
                clauses.append(("must", s))
    # De-duplicate by condition text, cap to keep the row family readable.
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for kind, cond in clauses:
        key = cond.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((kind, cond))
    return out[:4]


def _prereq_action(cmd: CliCommand, kind: str, cond: str) -> str:
    """Phrase the precondition test as a single Verify-style instruction
    mirroring the client's own wording."""
    if kind == "only-if":
        return (f"Verify `{cmd.name}` can be configured **only if** {cond}; "
                f"with the precondition unmet, commit is rejected with a "
                f"descriptive error naming it.")
    if kind == "cannot":
        return (f"Verify `{cmd.name}` **cannot** be configured when {cond}; "
                f"commit is rejected with a descriptive error message.")
    # "only" / "must"
    return (f"Verify `{cmd.name}`: {cond}; a violation is rejected at commit "
            f"time with a descriptive error message.")


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
               if cmd.related_features else "the feature")
    monitors = _monitor_list(cmd)
    primary_show = (_feature_show_for(cmd) or ["show configuration"])[0]

    def _mk(action_steps: str, expectation: str) -> PlanRow:
        return PlanRow(
            category=cat, sub_category=cmd.name, equipment=EQUIPMENT,
            sfs_requirement_id=req_anchor,
            action_steps=action_steps, expectation=expectation,
        )

    # ── Row 1: Happy-path configure ──────────────────────────────────────
    rows.append(_mk(
        _scaffold(
            f"DUT booted; no prior `{cmd.name}` configuration.",
            f"At the `{mode}` configuration level, configure "
            f"`{invocation}` and commit the candidate config.",
            _verify_with_monitors(
                [f"`show configuration` shows the `{cmd.name}` line under "
                 f"the `{mode}` level."],
                _feature_show_for(cmd)),
        ),
        _expect(
            f"`{cmd.name}` is accepted and present in `show configuration`; "
            f"{related} reads back via `{primary_show}`",
            "Commit is rejected, or the configured line is absent from "
            "`show configuration` after commit",
        ),
    ))

    # ── Documented value-set row (multi-variant commands, e.g. ESI types)─
    variants = _syntax_variants(cmd)
    values = _variant_values(cmd)
    if len(variants) >= 2 and len(values) >= 2:
        param_names = {p.name for p in cmd.parameters if p.name}
        shown = ", ".join(
            f"`{_wrap_placeholders(v, param_names)}`" for v in variants)
        default_note = (f"; documented default is `{cmd.default_behavior}`"
                        if cmd.default_behavior else "")
        rows.append(_mk(
            _scaffold(
                f"DUT at the `{mode}` configuration level.",
                f"Configure `{cmd.name}` with each documented value "
                f"({', '.join('`'+v+'`' for v in values)}): {shown}. Then "
                f"attempt an undocumented value (e.g. `{cmd.name} 2`).",
                _verify_with_monitors(
                    ["Each documented value is accepted; the undocumented "
                     "value is rejected at parse time with a descriptive "
                     "error."],
                    monitors),
            ),
            _expect(
                f"Only the documented `{cmd.name}` values "
                f"({', '.join(values)}) are accepted{default_note}",
                "An undocumented value is accepted, or a documented value "
                "is rejected",
            ),
        ))

    # ── Row 2..N: Range / type validation per typed parameter ────────────
    for p in _typed_params(cmd):
        spec = _value_spec_one_line(p)
        bad = _negative_value_hint(p)
        rows.append(_mk(
            _scaffold(
                f"DUT at the `{mode}` configuration level.",
                f"Issue `{cmd.name} <{p.name}>` with values: "
                f"(a) a valid in-spec value (per {spec!r}); "
                f"(b) invalid values: {bad}.",
                _verify_with_monitors(
                    ["Valid value commits and is read back with the correct "
                     "type/format; each invalid value is rejected at parse "
                     "time with a CLI error naming the parameter; the "
                     "configuration does NOT contain the bad value."],
                    monitors),
            ),
            _expect(
                f"Valid `<{p.name}>` accepted; each invalid value rejected "
                f"with a parse error; the configuration remains clean",
                f"Invalid value silently accepted, feature crashes, or the "
                f"configuration retains a partial/invalid `{cmd.name}` line",
            ),
        ))

    # ── Mutual exclusion row for choice parameters ───────────────────────
    choices = _choice_params(cmd)
    if len(choices) >= 2:
        choice_names = " | ".join(p.name for p in choices)
        rows.append(_mk(
            _scaffold(
                f"DUT at the `{mode}` configuration level.",
                f"Configure `{cmd.name}` with one choice "
                f"(e.g. `{choices[0].name}`); commit; then reconfigure with "
                f"a different choice ({choice_names}); commit.",
                _verify_with_monitors(
                    ["Only one choice is active at a time in the "
                     "configuration; the second commit replaces the first "
                     "cleanly; the feature reflects the latest choice."],
                    monitors),
            ),
            _expect(
                "Mutually-exclusive choices replace each other on commit",
                "Both choices appear in the configuration simultaneously, or "
                "the feature retains old behaviour after the switch",
            ),
        ))

    # ── Default-behavior row, only if doc names a default ────────────────
    if cmd.default_behavior:
        rows.append(_mk(
            _scaffold(
                f"DUT booted with no `{cmd.name}` configuration at the "
                f"`{mode}` level.",
                f"Bring the parent feature up without configuring "
                f"`{cmd.name}`; observe the default behaviour.",
                _verify_with_monitors(
                    [f"Feature operates with the documented default "
                     f"(\"{cmd.default_behavior}\"); `show configuration` "
                     f"omits the line; explicit configuration of the default "
                     f"value is a no-op (idempotent)."],
                    monitors),
            ),
            _expect(
                f"Default behaviour matches doc: \"{cmd.default_behavior}\"",
                "Default differs from doc, or explicit config of the default "
                "value changes the configuration (non-idempotent)",
            ),
        ))

    # ── `no` form row, if syntax shows it ────────────────────────────────
    if cmd.has_no_form:
        rows.append(_mk(
            _scaffold(
                f"`{cmd.name}` configured (Row 1 happy-path).",
                f"Issue `{_no_form(cmd)}`; commit.",
                _verify_with_monitors(
                    [f"`show configuration` no longer contains `{cmd.name}`; "
                     f"the feature reverts to default behaviour; no stale "
                     f"state in operational show outputs or kernel "
                     f"forwarding tables."],
                    monitors),
            ),
            _expect(
                f"`{cmd.name}` removed cleanly; feature reverts to default",
                "Stale config remains, feature stuck in old state, or kernel "
                "state inconsistent with the control plane",
            ),
        ))

    # ── Persistence row ──────────────────────────────────────────────────
    rows.append(_mk(
        _scaffold(
            f"`{cmd.name}` configured and committed under the `{mode}` level.",
            "Save the configuration; reload the DUT.",
            _verify_with_monitors(
                [f"After full boot, `show configuration` contains the same "
                 f"`{cmd.name}` line; the feature comes up automatically with "
                 f"the saved configuration."],
                _feature_show_for(cmd)),
        ),
        _expect(
            f"`{cmd.name}` survives reload byte-identical; feature auto-resumes",
            "Config lost on reload, partial-restore, or feature requires "
            "manual re-config after reload",
        ),
    ))

    # ── Help & completion row ─────────────────────────────────────────────
    # `?` lists the documented sub-tokens and TAB completes — an operator
    # must be able to discover the command from the prompt.
    head = cmd.name.split()[0]
    rows.append(_mk(
        _scaffold(
            [f"DUT at the `{mode}` configuration level (no `{cmd.name}` "
             f"configured yet)."],
            [f"At the prompt, type `{head} ?` and inspect the help listing.",
             f"Type the first letters of `{head}` and press TAB; observe "
             "completion.",
             f"After entering `{head} `, type `?` to list the next-token "
             "completions."],
            ["Help (`?`) lists the command with a non-empty one-line "
             "description.",
             "TAB completes uniquely (or offers the documented set when "
             "ambiguous); no tokens outside the CLI doc.",
             "Sub-token help shows every documented parameter (no missing, "
             "no extra)."],
        ),
        _expect(
            f"`{cmd.name}` is discoverable from `?` and TAB; sub-token help "
            "lists exactly the documented parameters",
            "Command absent from `?`, TAB does not complete, or sub-token "
            "help drops / invents parameters vs. the CLI doc",
        ),
    ))

    # ── Available-options enumeration under a sub-mode parent ────────────
    # `af-l2vpn evpn` opens the EVPN SAFI sub-mode; its options are the
    # inherited BGP sub-configs (client 2026-06-01, item 17).
    sub_opts = sub_config_names_for(cmd.name)
    if sub_opts:
        rows.append(_mk(
            _scaffold(
                f"DUT at the `{mode}` level with `{cmd.name}` entered.",
                f"Under `{cmd.name}`, type `?` to list the available options "
                f"of the evpn SAFI sub-mode.",
                ["Help lists exactly the documented sub-config options: "
                 + ", ".join(f"`{o}`" for o in sub_opts) + "."],
            ),
            _expect(
                f"The evpn SAFI exposes exactly the documented options "
                f"({len(sub_opts)}): {', '.join(sub_opts)}",
                "An option is missing from `?`, or an undocumented option "
                "appears",
            ),
        ))

    # ── Precondition rows — one per documented constraint ────────────────
    for kind, cond in _prerequisite_clauses(cmd):
        rows.append(_mk(
            _scaffold(
                f"DUT able to reach the `{mode}` level.",
                _prereq_action(cmd, kind, cond),
                _verify_with_monitors(
                    ["The CLI rejects the command at parse/commit time with a "
                     "clear, descriptive error; the configuration is "
                     "unchanged; satisfying the precondition then permits the "
                     "command on retry."],
                    ["show configuration"]),
            ),
            _expect(
                "Precondition enforced at parse/commit time with a "
                "descriptive error message",
                "Command silently accepted, feature half-configured, or the "
                "error does not identify the violated precondition",
            ),
        ))

    # ── VPLS-not-harmed regression (AC binding under VPLS/EVPN) ───────────
    # Client 2026-06-01, item 15: verify the shared VPLS path is not
    # regressed (CLI-wise) by the EVPN attachment-circuit binding.
    if "interface" in cmd.name.lower() and "vpls" in cmd.name.lower():
        rows.append(_mk(
            _scaffold(
                "A working VPLS service with an attachment circuit is "
                "configured on the DUT.",
                f"Configure / remove the EVPN AC via `{cmd.name}` alongside "
                f"the existing VPLS service.",
                _verify_with_monitors(
                    ["The existing VPLS AC binding, MAC learning and "
                     "forwarding are unaffected by the EVPN command; no VPLS "
                     "config is dropped or altered."],
                    ["show configuration", "show fib evpn-ac"]),
            ),
            _expect(
                "VPLS service continues forwarding; no VPLS CLI/config "
                "regression introduced by the EVPN AC binding",
                "VPLS AC, MAC table, or forwarding disrupted by the EVPN "
                "command",
            ),
        ))

    return rows


# ── Show / clear grammar expansion ───────────────────────────────────────
def _has_top_level_pipe(s: str) -> bool:
    depth = 0
    for ch in s:
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        elif ch == "|" and depth == 0:
            return True
    return False


def _split_choices(inner: str) -> list[str]:
    alts: list[str] = []
    depth = 0
    cur = ""
    for ch in inner:
        if ch in "{[":
            depth += 1
            cur += ch
        elif ch in "}]":
            depth -= 1
            cur += ch
        elif ch == "|" and depth == 0:
            alts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        alts.append(cur.strip())
    return alts


def _split_top_level(s: str) -> list[tuple[str, object]]:
    segs: list[tuple[str, object]] = []
    buf = ""
    i, n = 0, len(s)

    def _flush() -> None:
        nonlocal buf
        for w in buf.split():
            segs.append(("lit", w))
        buf = ""

    while i < n:
        ch = s[i]
        if ch in "{[":
            _flush()
            close_depth = 1
            j = i + 1
            while j < n and close_depth > 0:
                if s[j] in "{[":
                    close_depth += 1
                elif s[j] in "}]":
                    close_depth -= 1
                j += 1
            inner = s[i + 1:j - 1].strip()
            if ch == "{":
                segs.append(("choice", _split_choices(inner)))
            else:
                segs.append(("opt", inner))
            i = j
        else:
            buf += ch
            i += 1
    _flush()
    return segs


def _expand_grammar(s: str) -> list[str]:
    """Expand a CLI syntax line ({a|b} mandatory choice, [opt] optional,
    bare `a | b` choice) into the concrete invocation variants."""
    s = s.strip()
    if not s:
        return [""]
    if _has_top_level_pipe(s):
        out: list[str] = []
        for alt in _split_choices(s):
            out.extend(_expand_grammar(alt))
        return out
    variants = [""]
    for kind, val in _split_top_level(s):
        new: list[str] = []
        if kind == "lit":
            for v in variants:
                new.append((v + " " + str(val)).strip())
        elif kind == "choice":
            for v in variants:
                for alt in val:  # type: ignore[union-attr]
                    for sub in _expand_grammar(alt):
                        new.append((v + " " + sub).strip())
        elif kind == "opt":
            for v in variants:
                new.append(v)
                for sub in _expand_grammar(str(val)):
                    new.append((v + " " + sub).strip())
        variants = new
    return variants


def _expanded_invocations(cmd: CliCommand, limit: int = 6) -> list[str]:
    """Concrete, placeholder-wrapped invocations for a show/clear command."""
    syntax = cmd.syntax_lines[0] if cmd.syntax_lines else cmd.name
    param_names = {p.name for p in cmd.parameters if p.name}
    seen: list[str] = []
    for inv in _expand_grammar(syntax):
        inv = _wrap_placeholders(" ".join(inv.split()), param_names)
        if inv and inv not in seen:
            seen.append(inv)
    if not seen:
        return [_wrap_placeholders(syntax, param_names)]
    # Sort by token count then text so the base form of EACH mandatory
    # branch (e.g. advertised-routes AND received-routes) and the
    # brief/detail variants surface before the deeply-optional forms —
    # a representative spread rather than every variant of one branch.
    seen.sort(key=lambda s: (len(s.split()), s))
    return seen[:limit]


def _paired_show_for_clear(cmd: CliCommand) -> str:
    """The `show` that confirms a `clear` took effect (clear → show)."""
    syntax = cmd.syntax_lines[0] if cmd.syntax_lines else cmd.name
    base = re.split(r"[\[{]", syntax, maxsplit=1)[0].strip()
    if base.lower().startswith("clear "):
        return "show " + base[len("clear "):].strip()
    return "show " + base


def rows_for_show_command(cmd: CliCommand) -> list[PlanRow]:
    """Row family for a `show` / `clear` command.

    Show commands expand their grammar into the specific documented cases
    and verify EVPN-relevant content (client 2026-06-01, items 18-20).
    Clear commands verify the *cleared state* via the paired show, not
    "well-formed output" (item 21). The per-command pipe-filter row is
    gone (item 4).
    """
    if cmd.kind not in ("show", "clear"):
        return []

    req_anchor = f"CLI:{cmd.name}"
    cat = "CLI configuration"
    name = cmd.name.lower()

    def _mk(action_steps: str, expectation: str) -> PlanRow:
        return PlanRow(
            category=cat, sub_category=cmd.name, equipment=EQUIPMENT,
            sfs_requirement_id=req_anchor,
            action_steps=action_steps, expectation=expectation,
        )

    # ── Clear commands: verify the effect, not the output shape ──────────
    if cmd.kind == "clear":
        invs = _expanded_invocations(cmd, limit=4)
        paired = _paired_show_for_clear(cmd)
        inv_full = invs[-1]  # most-qualified form (scoped clear)
        return [_mk(
            _scaffold(
                "Populate the target state on the DUT (e.g. frozen / "
                "duplicate MAC entries present; MAC table populated).",
                [f"Issue the unscoped form `{invs[0]}`.",
                 f"Issue a scoped form `{inv_full}` to clear a single "
                 "target.",
                 f"Re-issue the clear to confirm it is a no-op."],
                [f"`{paired}` confirms the targeted entries are removed.",
                 "Unrelated entries are left untouched (scope respected).",
                 "Re-issuing the clear neither errors nor changes state "
                 "(idempotent)."],
            ),
            _expect(
                f"Targeted state is cleared (confirmed by `{paired}`); scope "
                f"is respected; the clear is idempotent",
                "Entries persist after the clear, unrelated state is cleared, "
                "or the command errors / prints a malformed message",
            ),
        )]

    # ── Show commands: expand the grammar into specific cases ────────────
    # `show interface …` — the only EVPN-relevant addition is the agg-eth
    # variant (ES membership under agg-eth); don't over-generate the
    # loopback / x-eth / mgmt variants (client item 18).
    if name.startswith("show interface"):
        invs = ["show interface agg-eth <agg-id> detail"]
        verify = ["Output is well-formed; the agg-eth detail block shows the "
                  "Ethernet-Segment membership / ESI added for EVPN."]
        expect_pass = ("`show interface agg-eth <agg-id> detail` renders the "
                       "EVPN Ethernet-Segment fields for the agg-eth")
    else:
        invs = _expanded_invocations(cmd)
        verify = ["Each invocation renders without a parser error; the "
                  "header / columns match the documented format.",
                  "Optional arguments (name / esi / vlan-id / neighbor / "
                  "prefix) scope the output correctly."]
        expect_pass = (f"every documented form of `{cmd.name}` produces "
                       f"well-formed, correctly-scoped output")

    # `show bgp neighbors … detail` — call out the new EVPN additions
    # (l2vpn evpn AF block, EVPN capability) the client wants flagged
    # (item 19).
    if name.startswith("show bgp neighbors"):
        verify.append("`detail` now includes the new EVPN additions: the "
                      "l2vpn evpn address-family block and EVPN capability "
                      "negotiation state.")
        expect_pass += ("; `detail` surfaces the new l2vpn evpn AF / EVPN "
                        "capability additions")

    action_steps = _scaffold(
        "DUT booted; CLI session via console / SSH; relevant EVPN state "
        "present so the command has content to render.",
        [f"Issue `{inv}`." for inv in invs],
        verify,
    )
    return [_mk(action_steps, _expect(
        expect_pass,
        "Parser error, missing/extra columns, an optional argument that "
        "does not scope the output, or a documented case that is rejected",
    ))]


# ── Ordering: by command mode, not alphabetically ───────────────────────
def cli_command_rows(commands: list[CliCommand]) -> list[PlanRow]:
    """Concatenate all CLI rows, ordered by **command mode**.

    Client 2026-06-01 (item 3): the CLI doc lists commands alphabetically,
    but QA reads them per command mode. Config commands are grouped by
    `mode_path` (all `… interface agg-eth ethernet-segment` together, then
    the `… l2-services evpn` group, etc.), preserving doc order within a
    mode. Show / clear commands follow, grouped the same way by their
    leading tokens so related views sit together.
    """
    config = [c for c in commands if c.is_config]
    shows = [c for c in commands if c.kind in ("show", "clear")]

    def _config_key(item: tuple[int, CliCommand]) -> tuple:
        idx, c = item
        return (tuple(c.mode_path), idx)

    def _show_key(item: tuple[int, CliCommand]) -> tuple:
        idx, c = item
        # group by the command stem (show evpn / show bgp / clear evpn …)
        stem = " ".join(c.name.lower().split()[:2])
        return (stem, idx)

    out: list[PlanRow] = []
    for _idx, c in sorted(enumerate(config), key=_config_key):
        out.extend(rows_for_command(c))
    for _idx, c in sorted(enumerate(shows), key=_show_key):
        out.extend(rows_for_show_command(c))
    return out

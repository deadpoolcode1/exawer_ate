"""Mechanical path: generated test plan → `TestScript` IR → Java.

`evpn_scripts.py` is the *curated* path — 33 steps a human wrote for the three
flows Exaware runs first. This module is the *mechanical* one: it takes the
generated test plan, runs `patterns.py` over its rows, and assembles the
matched steps into `TestScript`s that the existing emitter compiles. No human
authors a step here.

That makes it the answer to a fair question about M2: "did the tool write these
tests, or did you?" For a suite produced by this module the answer is the tool,
end to end — documents → plan → typed steps → compiling Java.

Two things it must get right, because both are ways to look better than you are:

**Commands must be grounded.** `patterns.py` recognises the *shape* of a row
and puts any backticked CLI text into `Step.args` — it never sets
`Step.command`, because recognising "this row runs a command" is not the same
as knowing which `EvpnCommands` constant that is. The emitter renders
`EvpnCommands.<command>`, so an unresolved command would emit code that does
not compile, and an *invented* one would emit code that types a command no CLI
doc describes. So `resolve_command` matches the row's CLI text against the
registry's own templates, recovering the argument values as a side effect. A
row that does not resolve degrades to `TODO_STUB`.

**Degrading must be visible.** Every step this module produces carries a
`todo`, so the emitter renders `CompassReporter.warning(...)` and `EvpnUtils`
treats the empty expectation as "not validated" rather than a pass. A
mechanically derived suite therefore *cannot* show a green run until a human
fills the expectations in. Recall is reported (`ate match`), never implied.
"""
from __future__ import annotations

import re
from pathlib import Path

from ate.codegen.commands import EVPN_COMMANDS, EvpnCommand
from ate.codegen.lab import SINGLE_DUT_3AC, LabProfile
from ate.codegen.patterns import match_text
from ate.codegen.script_ir import Step, StepKind, TestScript

__all__ = ["flow_rows_from_xlsx", "resolve_command", "scripts_from_plan"]

#: Banner rows look like "FLOW-020 — All-active multi-homing bring-up".
_BANNER = re.compile(r"^(FLOW-\d+)\s*[—–-]\s*(.+)$")

#: Kinds whose emitted Java dereferences `EvpnCommands.<command>`. A step of
#: one of these kinds is only safe to emit once the command resolves.
_NEEDS_COMMAND = {StepKind.CONFIG, StepKind.VERIFY_CLI, StepKind.VERIFY_ROUTE}

#: `VERIFY_NO_EVENT` is emitted as a comparison against a `routesBefore` local
#: that `emit_test` only declares for a paired "Snapshot ..." step. Plan prose
#: does not reliably give us that pairing, so these always degrade.
_ALWAYS_DEGRADE = {StepKind.VERIFY_NO_EVENT}

_DERIVED = ("Derived mechanically from the test plan by pattern matching. "
            "The command binding and every expected value still need review "
            "against real device output.")


def _template_regex(cmd: EvpnCommand) -> re.Pattern[str] | None:
    """A regex that matches `cmd`'s CLI text and captures its `%s` arguments."""
    if not cmd.template:
        return None
    parts = [re.escape(p) for p in cmd.template.split("%s")]
    # `\S+` rather than `.+` so a greedy argument cannot swallow the next
    # literal chunk of the template.
    return re.compile(r"\b" + r"(\S+)".join(parts), re.IGNORECASE)


def _tail_templates(cmd: EvpnCommand) -> list[str]:
    """Progressively shorter tails of a config command's template.

    The plan quotes a config command *relative to the mode you are in* — a row
    reads "`evpn evi-1 service-type vlan-based` under `configuration
    l2-services`", so the literal `l2-services` prefix never appears inside the
    backticks. Matching a tail recovers those without inventing anything: the
    text still has to match a template this registry already contains.

    Only leading *literal* tokens are dropped, never a `%s`, and at least two
    literal tokens must remain so a tail stays distinctive enough to identify
    one command.
    """
    toks = cmd.template.split()
    out: list[str] = []
    for i in range(1, len(toks)):
        if toks[i - 1] == "%s":          # never start a tail at an argument
            break
        tail = toks[i:]
        if sum(1 for t in tail if t != "%s") < 2:
            break
        out.append(" ".join(tail))
    return out


_TEMPLATES: list[tuple[EvpnCommand, re.Pattern[str]]] = []
for _c in EVPN_COMMANDS:
    if (_rx := _template_regex(_c)) is not None:
        _TEMPLATES.append((_c, _rx))
    if _c.mode.endswith("CLI_CONFIGURE"):
        for _tail in _tail_templates(_c):
            _TEMPLATES.append(
                (_c, _template_regex(EvpnCommand(key=_c.key, template=_tail))))
# Longest template first: `show evpn global name %s` must win over a
# hypothetical `show evpn global`, or the more specific command never matches.
_TEMPLATES.sort(key=lambda pair: len(pair[1].pattern), reverse=True)


def resolve_command(text: str) -> tuple[EvpnCommand, list[str]] | None:
    """Ground a row's CLI text in the `EvpnCommands` registry.

    Returns the registry entry and the argument values recovered from the
    text, or None when nothing in the registry matches — which is the common
    case, since the plan spans ~30 flows while the registry covers the
    commands the three curated flows needed.
    """
    if not text:
        return None
    hay = " ".join(text.split())
    for cmd, rx in _TEMPLATES:
        m = rx.search(hay)
        if m:
            return cmd, [g for g in m.groups()]
    return None


def _camel(title: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", title)
    return "".join(w[:1].upper() + w[1:].lower() for w in words) or "Flow"


def flow_rows_from_xlsx(
    xlsx_path: str | Path,
) -> dict[str, tuple[str, list[tuple[str, list[str]]]]]:
    """Read the plan's main sheet into `{flow_id: (title, [(action, reqs)])}`.

    Rows are attributed to the flow whose banner most recently preceded them;
    a non-flow banner (an RFC or CLI section) clears the attribution, so only
    genuine flow rows are collected.
    """
    import openpyxl  # noqa: PLC0415  (heavy import)

    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    ws = wb["Test Plan Topics"]
    out: dict[str, tuple[str, list[tuple[str, list[str]]]]] = {}
    current: str | None = None
    for row in list(ws.iter_rows(values_only=True))[1:]:
        topic = (row[0] or "").strip()
        action = (row[1] or "").strip()
        if topic:
            m = _BANNER.match(topic)
            if m:
                current = m.group(1)
                out.setdefault(current, (m.group(2).strip(), []))
            else:
                current = None
        if action and current:
            reqs = [x.strip() for x in (row[2] or "").split(",") if x.strip()]
            out[current][1].append((action, reqs))
    wb.close()
    return out


def _step_for(row_id: str, action: str, reqs: list[str]) -> Step | None:
    """One plan row → one emittable step, or None if it is not a step at all."""
    res = match_text(action, row_id, reqs)
    if res.skipped:                      # cross-reference line, not executable
        return None

    stub = Step(id=row_id, kind=StepKind.TODO_STUB, text=action[:200],
                req_ids=list(reqs), todo=_DERIVED)
    if res.step is None:                 # no rule recognised the row
        return stub.model_copy(update={
            "todo": "No pattern rule recognised this row; it is carried "
                    "through verbatim so the step is not silently lost."})

    step = res.step
    if step.kind in _ALWAYS_DEGRADE:
        return stub.model_copy(update={
            "todo": f"{_DERIVED} Recognised as {step.kind.value}, which needs "
                    "a paired snapshot step that plan prose does not give."})

    if step.kind not in _NEEDS_COMMAND:
        # WAIT / VERIFY_IXIA / TRAFFIC_* emit no `EvpnCommands` reference, so
        # they are safe as-is. They already carry the matcher's own todo.
        return step

    resolved = resolve_command(step.args[0] if step.args else "")
    if resolved is None:
        return stub.model_copy(update={
            "todo": f"{_DERIVED} No command in EvpnCommands matches this row, "
                    "so no CLI is emitted rather than inventing one."})

    cmd, args = resolved
    # Trust the registry over the rule for CONFIG-vs-SHOW: the rule reads
    # English, the registry knows the command's real session mode.
    kind = step.kind
    is_config = cmd.mode.endswith("CLI_CONFIGURE")
    if is_config and kind is not StepKind.CONFIG:
        kind = StepKind.CONFIG
    elif not is_config and kind is StepKind.CONFIG:
        kind = StepKind.VERIFY_CLI

    return step.model_copy(update={
        "kind": kind, "command": cmd.key, "args": args, "todo": _DERIVED})


def scripts_from_plan(xlsx_path: str | Path,
                      flow_ids: list[str],
                      lab: LabProfile = SINGLE_DUT_3AC,
                      ) -> list[TestScript]:
    """Build a `TestScript` per requested flow, mechanically, from the plan.

    Class names are prefixed `TCM` — *matcher*-derived — so a reviewer can
    never confuse one of these with a curated `TCnn` suite.
    """
    by_flow = flow_rows_from_xlsx(xlsx_path)
    scripts: list[TestScript] = []
    for flow_id in flow_ids:
        if flow_id not in by_flow:
            raise KeyError(
                f"{flow_id} has no rows in {xlsx_path}. "
                f"Known flows: {', '.join(sorted(by_flow))}")
        title, rows = by_flow[flow_id]
        num = flow_id.split("-")[-1]
        steps: list[Step] = []
        for i, (action, reqs) in enumerate(rows, start=1):
            step = _step_for(f"{flow_id}.M{i:03d}", action, reqs)
            if step is not None:
                steps.append(step)
        camel = _camel(title)
        scripts.append(TestScript(
            flow_id=flow_id,
            class_name=f"TCM{num}_Evpn{camel}"[:120],
            method_name=f"evpn{camel}",
            title=title,
            summary=(
                f"{flow_id} - {title}. Generated MECHANICALLY from the test "
                "plan: every step below was derived by pattern matching over "
                "the plan's own rows, with commands grounded in the EVPN CLI "
                "doc via EvpnCommands. No step was hand-written. Expectations "
                "are empty pending real device output, so every step reports a "
                "warning rather than a pass."),
            steps=steps,
        ))
    return scripts

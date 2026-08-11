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

from ate.codegen.commands import EvpnCommand, all_commands
from ate.codegen.lab import SINGLE_DUT_3AC, LabProfile
from ate.codegen.patterns import commands_in, match_text
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

#: A config-command tail must carry at least this many characters of literal
#: text to be accepted as identifying one command. Keeps `load-balancing-mode
#: %s` while rejecting `enable` / `detail`.
_MIN_TAIL_CHARS = 8

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

    A tail never *starts* at an argument — `%s ethernet-segment ...` would
    match any word. Distinctiveness is measured in literal characters rather
    than token count: `load-balancing-mode %s` is one literal token but
    unmistakable, while `enable` or `detail` are not, so the bar is
    `_MIN_TAIL_CHARS` characters of literal text.
    """
    toks = cmd.template.split()
    out: list[str] = []
    for i in range(1, len(toks)):
        tail = toks[i:]
        if tail[0] == "%s":
            continue
        literal = "".join(t for t in tail if t != "%s")
        if len(literal) < _MIN_TAIL_CHARS:
            continue
        out.append(" ".join(tail))
    return out


_TEMPLATE_CACHE: tuple[int, list[tuple[EvpnCommand, re.Pattern[str]]]] = (-1, [])
_PREFIX_CACHE: tuple[int, list[re.Pattern[str]]] = (-1, [])


def _prefixes() -> list[re.Pattern[str]]:
    """Regexes matching every *leading portion* of every registry template.

    Used to recognise a mode-entry fragment: a plan row writes `interface
    agg-eth 0` before the commands typed inside that mode, and that fragment is
    not a command in its own right — it is the prefix of several.
    """
    global _PREFIX_CACHE
    n = len(all_commands())
    if _PREFIX_CACHE[0] == n:
        return _PREFIX_CACHE[1]
    out: list[re.Pattern[str]] = []
    seen: set[str] = set()
    for c in all_commands():
        toks = c.template.split()
        for k in range(1, len(toks)):
            head = " ".join(toks[:k])
            if head in seen:
                continue
            seen.add(head)
            parts = [re.escape(p) for p in head.split("%s")]
            out.append(re.compile(r"(?i)" + r"(\S+)".join(parts) + r"\Z"))
    _PREFIX_CACHE = (n, out)
    return out


def _is_mode_prefix(text: str) -> bool:
    hay = " ".join(text.split())
    return any(rx.match(hay) for rx in _prefixes())


def _templates() -> list[tuple[EvpnCommand, re.Pattern[str]]]:
    """Match table over the whole registry, curated and derived.

    Built per call rather than at import: the derived entries are installed at
    generation time, so a table frozen at import would only ever see the
    curated 18 — which is exactly the gap this path was blocked on.
    """
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE[0] == len(all_commands()):
        return _TEMPLATE_CACHE[1]
    out: list[tuple[EvpnCommand, re.Pattern[str]]] = []
    for c in all_commands():
        if (rx := _template_regex(c)) is not None:
            out.append((c, rx))
        if c.mode.endswith("CLI_CONFIGURE"):
            for tail in _tail_templates(c):
                rx = _template_regex(EvpnCommand(key=c.key, template=tail))
                if rx is not None:
                    out.append((c, rx))
    # Longest template first: `show evpn global name %s` must win over
    # `show evpn global`, or the more specific command never matches.
    out.sort(key=lambda pair: len(pair[1].pattern), reverse=True)
    _TEMPLATE_CACHE = (len(all_commands()), out)
    return out


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
    for cmd, rx in _templates():
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


def _grounded_steps(row_id: str, action: str, reqs: list[str]) -> list[Step]:
    """One step per command in the row that grounds in the registry.

    A plan row is rarely one command. A bring-up row reads "PE1:
    `interface agg-eth 0`, `ethernet-segment`, `identifier 1`,
    `load-balancing-mode all-active`" — four commands in one sentence, and
    `patterns.py` keeps only the first because its job is to classify the row's
    *shape*. Emitting one step per grounded command is what turns such a row
    into executable configuration instead of a single stub.

    A command is only emitted when the row supplies every argument its
    documented template needs; anything else is left to the caller to degrade.
    """
    steps: list[Step] = []
    mode_ctx = ""
    for snippet in commands_in(action):
        # A row types a mode entry once and then several commands inside it:
        # "`interface agg-eth 0`, `ethernet-segment`, `identifier 1`". Only the
        # combination carries the selector the template needs, so resolve
        # against the accumulated mode context first.
        combined = f"{mode_ctx} {snippet}".strip()
        resolved = resolve_command(combined)
        if resolved is None or resolved[0].template.count("%s") != len(resolved[1]):
            alone = resolve_command(snippet)
            if alone is not None and alone[0].template.count("%s") == len(alone[1]):
                resolved, combined = alone, snippet
        if _is_mode_prefix(combined):
            mode_ctx = combined
        elif _is_mode_prefix(snippet):
            mode_ctx = snippet
        if resolved is None:
            continue
        cmd, args = resolved
        if cmd.template.count("%s") != len(args):
            continue
        kind = (StepKind.CONFIG if cmd.mode.endswith("CLI_CONFIGURE")
                else StepKind.VERIFY_CLI)
        verb = "Configure" if kind is StepKind.CONFIG else "Run"
        steps.append(Step(
            id=f"{row_id}.{len(steps) + 1}",
            kind=kind,
            text=f"{verb} `{snippet}`"[:200],
            command=cmd.key,
            args=args,
            req_ids=list(reqs),
            todo=_DERIVED,
        ))
    return steps


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
    # A tail match can identify the command while recovering fewer arguments
    # than its template needs — `af-l2vpn evpn` matches inside
    # `routing bgp %s vrf %s neighbor %s af-l2vpn evpn`. Emitting that would
    # put a literal `%s` into the CLI typed at a device, so degrade instead.
    if cmd.template.count("%s") != len(args):
        return stub.model_copy(update={
            "todo": f"{_DERIVED} Row matches {cmd.key}, but the plan text "
                    f"supplies {len(args)} of the "
                    f"{cmd.template.count('%s')} argument(s) the documented "
                    "command needs, so no CLI is emitted."})
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
            row_id = f"{flow_id}.M{i:03d}"
            grounded = _grounded_steps(row_id, action, reqs)
            if grounded:
                steps.extend(grounded)
                continue
            step = _step_for(row_id, action, reqs)
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

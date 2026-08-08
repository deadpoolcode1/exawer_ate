"""Pattern matching — test-plan prose → executable steps.

The SOW's other M2 line item. The three scoped flows have hand-curated step
lists (`evpn_scripts.py`) because quality mattered more than reach on the
flows Exaware will actually run first. This module is the reach: it maps the
*rest* of the generated test plan — 1745 atomic rows across ~30 flows — onto
the same `Step` IR mechanically, so codegen is not limited to what someone sat
down and curated.

Two honest properties:

  * **Recall is reported, never faked.** `match_plan` returns the fraction of
    rows that produced a typed step. An unmatched row becomes an `UNMATCHED`
    result carrying the original sentence, which the emitter renders as a
    compiling `// TODO` with that sentence in a comment. Nobody is told the
    plan is 100% automatable when it isn't.
  * **Matched ≠ correct.** A rule recognises *shape* ("this is a config step
    naming command X"), not intent. Every matched step still lands with an
    empty expectation, so it warns rather than passes until a human fills it
    in. The matcher's job is to remove typing, not review.

Rules are ordered and first-match-wins; the specific ones come before the
generic ones. Each rule states which `StepKind` it produces and why the cue is
reliable, because a mis-shaped rule silently mislabels steps and that is the
failure mode worth guarding against.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ate.codegen.script_ir import Step, StepKind

#: Anything inside backticks that looks like a CLI invocation. The plan writes
#: commands in backticks throughout (enforced by cli_crosscheck), which makes
#: this the single most reliable cue in the whole document.
_BACKTICK_CMD = re.compile(r"`([^`]+)`")

#: A leading step number the atomic-row decomposer may have left behind.
_LEADING_NUM = re.compile(r"^\s*\d+[.)]\s*")

#: Rows that are not steps at all. `generator._slim_setup_for_continuation`
#: replaces a repeated flow body with a cross-reference line so the plan does
#: not restate the same setup on every category (Eyal, 2026-06-21). Those lines
#: are navigation for a human reader; there is nothing to execute. They are
#: excluded from the recall denominator rather than counted as failures --
#: inflating the denominator with rows that could never be automated would
#: understate reach just as dishonestly as skipping hard rows would overstate
#: it.
NON_STEP = re.compile(
    r"\bALREADY established\b|\bAS IN THE FIRST CASE\b|"
    r"\bdo not restate\b|\bverify only the category-specific\b",
    re.I,
)


@dataclass(frozen=True)
class Rule:
    kind: StepKind
    pattern: re.Pattern[str]
    why: str

    def matches(self, text: str) -> bool:
        return bool(self.pattern.search(text))


RULES: list[Rule] = [
    # ── negative assertions first: they contain verify verbs too, and a
    # "verify no X was triggered" row misclassified as a plain check would
    # silently invert the test's meaning.
    Rule(
        StepKind.VERIFY_NO_EVENT,
        re.compile(r"\b(no|not|never|without)\b[^.]{0,60}\b"
                   r"(triggered|advertis\w+|re-?advertis\w+|withdraw\w+|"
                   r"generated|emitted|sent|change[ds]?|update[ds]?)\b",
                   re.I),
        "explicit negative about a protocol event",
    ),
    Rule(
        StepKind.VERIFY_NO_EVENT,
        re.compile(r"\b(unchanged|intact|remains?|still)\b[^.]{0,40}"
                   r"\b(table|entry|entries|route|mac)", re.I),
        "'unchanged / intact / still present' is a no-change assertion",
    ),

    # ── traffic control ────────────────────────────────────────────────────
    Rule(
        StepKind.TRAFFIC_STOP,
        re.compile(r"\b(stop|suspend|cease|halt)\b[^.]{0,40}\btraffic\b", re.I),
        "traffic verbs are unambiguous in this corpus",
    ),
    Rule(
        StepKind.TRAFFIC_STATE,
        re.compile(r"\b(send|start|transmit|offer|unsuspend|inject"
                   r"|drive|apply|generate|replay)\b"
                   r"[^.]{0,60}\b(traffic|frames?|packets?|unicast|"
                   r"broadcast|bum|load)\b", re.I),
        "traffic generation verbs, incl. the plan's 'send N Gbps ...' idiom",
    ),

    # ── waiting ────────────────────────────────────────────────────────────
    Rule(
        StepKind.WAIT,
        re.compile(r"\b(wait|sleep|allow|after)\b[^.]{0,40}"
                   r"(\d+\s*(s|sec|second|min|minute|h|hour)|aging|"
                   r"timer|expiry|expire)", re.I),
        "an explicit duration or a named timer",
    ),

    # ── IXIA / counter checks before generic verify: they mention 'verify'
    # but must not become CLI show assertions.
    Rule(
        StepKind.VERIFY_IXIA,
        re.compile(r"\b(ixia|port counters?|rx|tx|frame rate|line rate|"
                   r"packet loss|drops?|flood(ing|ed)?)\b", re.I),
        "data-plane observation lives on the tester, not in a show command",
    ),

    # ── route-table checks before generic verify, same reason.
    Rule(
        StepKind.VERIFY_ROUTE,
        re.compile(r"\b(type[- ]?[1-5]|imet|nlri|route target|rt|"
                   r"advertis\w+|withdraw\w+|bgp\s+update|evpn\s+route)\b",
                   re.I),
        "control-plane route assertions read a BGP/EVPN table",
    ),

    # ── CLI-grammar probes ────────────────────────────────────────────────
    # The CLI row families (cli_rows.py) generate a very regular vocabulary for
    # exploring command syntax. Classified as VERIFY_CLI rather than CONFIG:
    # these rows assert what the parser accepts/offers, they do not configure
    # anything, and treating them as config would make codegen emit commits.
    Rule(
        StepKind.VERIFY_CLI,
        re.compile(r"\btype\s+`?\?|next-token completions?|"
                   r"\bcompletions?\b|\bsyntax help\b", re.I),
        "'?' completion probes assert the parser's grammar",
    ),
    Rule(
        StepKind.VERIFY_CLI,
        re.compile(r"\b(reject|rejected|accepts?|accepted|error|invalid|"
                   r"out-of-range|out of range)\b", re.I),
        "accept/reject rows assert parser behaviour, not device state",
    ),

    # ── configuration ──────────────────────────────────────────────────────
    Rule(
        StepKind.CONFIG,
        re.compile(r"^\s*(configure|config|set|create|enable|disable|bind|"
                   r"apply|commit|attach|assign|add|remove|delete|clear|"
                   r"on\s+PE\d)\b", re.I),
        "imperative config verb in first position",
    ),
    Rule(
        StepKind.CONFIG,
        re.compile(r"^\s*(issue|enter|descend|navigate|re-?enter|exit)\b",
                   re.I),
        "CLI-row navigation/issue idioms from cli_rows.py",
    ),
    Rule(
        StepKind.CONFIG,
        re.compile(r"^\s*(at|from|under|within)\s+the\b[^.]{0,120}"
                   r"\b(level|mode|container|context)\b", re.I),
        "'At the <path> configuration level, ...' — a config-mode row",
    ),
    Rule(
        StepKind.CONFIG,
        re.compile(r"\bcommit\b", re.I),
        "any row that commits is changing configuration",
    ),
    Rule(
        StepKind.CONFIG,
        re.compile(r"^\s*`(no\s+)?[a-z][\w-]*(\s|`)", re.I),
        "row opens with a bare CLI command in backticks",
    ),

    Rule(
        StepKind.CONFIG,
        re.compile(r"^\s*(read back|populate|save|reload|restart|reboot|"
                   r"load|restore|provision)\b", re.I),
        "default-probe and device-state idioms from the CLI row families",
    ),
    Rule(
        StepKind.CONFIG,
        re.compile(r"^[^.]{0,140}\b(is|are|with)\s+(configured|defined|"
                   r"present|established|up|running|attached|applied|bound)"
                   r"\b|^[A-Z][^.]{0,60}\b(attached|defined|bundled)\b",
                   re.I),
        "a declarative precondition row ('X is configured on the DUT')",
    ),

    # ── the catch-all verify, last ─────────────────────────────────────────
    Rule(
        StepKind.VERIFY_CLI,
        re.compile(r"\b(verify|confirm|check|ensure|validate|observe|"
                   r"inspect|show)\b", re.I),
        "generic verification verb; falls through to a show assertion",
    ),
]


@dataclass
class MatchResult:
    """One row's outcome."""

    row_index: int
    text: str
    step: Step | None = None
    rule_why: str = ""
    #: True for rows that are cross-references, not executable steps.
    skipped: bool = False

    @property
    def matched(self) -> bool:
        return self.step is not None


@dataclass
class MatchReport:
    results: list[MatchResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Rows that are candidates for automation (cross-reference lines
        excluded -- see NON_STEP)."""
        return sum(1 for r in self.results if not r.skipped)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.skipped)

    @property
    def matched(self) -> int:
        return sum(1 for r in self.results if r.matched)

    @property
    def recall(self) -> float:
        """Fraction of automatable rows that produced a typed step. Reported,
        not spun -- this is the number that says how far codegen reaches
        beyond the curated flows."""
        return (self.matched / self.total) if self.total else 0.0

    def by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.results:
            if r.step is not None:
                counts[r.step.kind.value] = counts.get(r.step.kind.value, 0) + 1
        return counts

    def unmatched(self) -> list[MatchResult]:
        return [r for r in self.results if not r.matched and not r.skipped]


def commands_in(text: str) -> list[str]:
    """CLI commands quoted in a row, in order of appearance."""
    return [m.group(1).strip() for m in _BACKTICK_CMD.finditer(text)]


def match_text(text: str, step_id: str,
               req_ids: list[str] | None = None) -> MatchResult:
    """Classify one atomic-row action sentence into a typed step."""
    clean = _LEADING_NUM.sub("", (text or "").strip())
    result = MatchResult(row_index=-1, text=clean)
    if not clean:
        result.skipped = True
        return result
    if NON_STEP.search(clean):
        result.skipped = True
        return result

    for rule in RULES:
        if not rule.matches(clean):
            continue
        cmds = commands_in(clean)
        step = Step(
            id=step_id,
            kind=rule.kind,
            text=clean[:200],
            req_ids=list(req_ids or []),
            # Matching recognises shape, not values: the step is emitted with
            # no expectation, so it warns rather than asserts until reviewed.
            todo=("Derived by pattern matching from plan prose; the command "
                  "binding and expected values still need review."),
        )
        if cmds:
            step = step.model_copy(update={"args": cmds[:1]})
        result.step = step
        result.rule_why = rule.why
        return result

    return result


def match_plan(rows: list[tuple[str, list[str]]],
               flow_id: str = "PLAN") -> MatchReport:
    """Run the rule library over a plan's atomic rows.

    `rows` is a list of `(action_text, req_ids)` — deliberately not the
    `AtomicRow` model, so this stays usable from a notebook, a diff tool or a
    future non-EVPN plan without importing the planner.
    """
    report = MatchReport()
    for i, (text, req_ids) in enumerate(rows, start=1):
        res = match_text(text, f"{flow_id}.M{i:04d}", req_ids)
        res.row_index = i
        report.results.append(res)
    return report


def rows_from_plan(plan) -> list[tuple[str, list[str]]]:
    """Extract `(action, req_ids)` pairs from a generated Plan.

    Banner rows carry no action and are skipped — they are layout, not steps.
    """
    from ate.planner.atomic_rows import rows_for_plan_row  # noqa: PLC0415

    flow_lookup = {f.id: f for f, _ in
                   plan.__dict__.get("_flows_with_reqs", [])}
    out: list[tuple[str, list[str]]] = []
    for pr in plan.rows:
        for ar in rows_for_plan_row(pr, flow_lookup):
            if ar.is_banner or not ar.action.strip():
                continue
            out.append((ar.action, list(ar.req_ids)))
    return out

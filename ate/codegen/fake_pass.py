"""Pipeline rule: a generated test may never report success without earning it.

This exists because it happened, three separate ways, on real hardware:

  * three configuration commands were REJECTED by the device and the suite
    still reported `OK (1 test)` — nothing was staged, so the commit had
    nothing to do, so the framework logged a warning;
  * five "captured expectations" were the MAC table's legend with no MAC
    address in it — an assertion that passes on a working device and a broken
    one alike;
  * a negative assertion ("no new Type-2 route after a local MAC move")
    compared an empty route table with an empty route table.

Each of those is worse than having no test at all: a red test gets fixed, a
green one that checks nothing gets trusted. So "can this step actually fail?"
is now a question the pipeline asks before it emits anything, and generation
STOPS when the answer is no — the same posture `validate_grounding` takes
towards an invented command.

The audit is deliberately conservative. It reports a step as unfalsifiable
only when that is a property of the generated artifact itself, never when it
depends on the state of a device the generator cannot see. Emptiness that only
shows up at run time (an empty snapshot, a table with no rows) cannot be
decided here, so it is enforced in the emitted Java instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ate.codegen.script_ir import StepKind, TestScript

__all__ = ["FakePassError", "Violation", "audit", "assertion_census"]

#: Steps that claim to verify something. These are the ones that must be able
#: to fail; a CONFIG or WAIT step asserts nothing by design.
_ASSERTING = (
    StepKind.VERIFY_CLI,
    StepKind.VERIFY_IXIA,
    StepKind.VERIFY_ROUTE,
    StepKind.VERIFY_NO_EVENT,
)

#: A line that is printed by the device whatever the feature is doing: table
#: rules, column headers, and the legends these CLIs put above a table. An
#: expectation made only of these cannot distinguish working from broken.
_RULE = re.compile(r"^[-=_+\s|]*$")
_LEGEND = re.compile(r"^[A-Z][A-Z0-9 _-]{0,7}:\s")
_ALL_CAPS_HEADER = re.compile(r"^[A-Z][A-Z0-9 _()/-]*$")


def _is_structural(line: str) -> bool:
    """Is this line printed regardless of what the device is doing?"""
    s = line.strip()
    if not s:
        return True
    if _RULE.match(s):
        return True
    if _LEGEND.match(s):        # "LOC:  L - local, R - remote"
        return True
    return bool(_ALL_CAPS_HEADER.match(s))   # "INTERFACE  ESI  ES LABEL"


@dataclass
class Violation:
    step_id: str
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.step_id} [{self.rule}] {self.detail}"


@dataclass
class Census:
    """How much of a suite can actually fail."""

    falsifiable: list[str] = field(default_factory=list)
    warns_only: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.falsifiable) + len(self.warns_only)


class FakePassError(RuntimeError):
    """A generated step would report success without checking anything."""


def audit(scripts: list[TestScript],
          captures: dict | None = None) -> list[Violation]:
    """Every way the generated suite could report a pass it has not earned.

    Only two things are decidable here, and only these are reported:

    * an expectation whose content cannot distinguish a working device from a
      broken one;
    * a no-change assertion, whose baseline emptiness is a RUN-TIME property -
      so the generator cannot judge it and the emitted code must, which is why
      `EvpnUtils.verifyOutputUnchanged` refuses to pass on an empty baseline.

    A verification step with an EMPTY expectation is deliberately NOT reported:
    `verifyShowLines` and `verifyIxiaStatistics` both warn rather than assert
    in that case, which is honest. It is counted in the census as "warns only",
    and a suite in which nothing can fail is failed on the device by
    `assertSomethingWasVerified`.
    """
    captures = captures or {}
    out: list[Violation] = []

    for sc in scripts:
        for st in sc.steps:
            if st.kind not in _ASSERTING:
                continue
            cap = captures.get(st.expect_key) if st.expect_key else None
            lines = (cap or {}).get("lines") or []
            if lines and all(_is_structural(ln) for ln in lines):
                out.append(Violation(
                    st.id, "unfalsifiable-expectation",
                    f"every captured line is a header, rule or legend "
                    f"({len(lines)} line(s)) - it would match on a device "
                    f"where the feature does nothing"))
    return out


def assertion_census(scripts: list[TestScript],
                     captures: dict | None = None) -> Census:
    """Split verification steps into "can fail" and "only warns".

    Reported at generation time so the headline number is never just the
    step count. A suite of thirty steps that asserts nothing should look like
    what it is.
    """
    captures = captures or {}
    census = Census()
    for sc in scripts:
        for st in sc.steps:
            if st.kind not in _ASSERTING:
                continue
            cap = captures.get(st.expect_key) if st.expect_key else None
            if cap and cap.get("lines"):
                census.falsifiable.append(st.id)
            else:
                census.warns_only.append(st.id)
    return census

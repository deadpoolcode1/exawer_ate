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

#: A glossary pair as these CLIs print above a table: "s - suppressed",
#: "i - IGP", "L – local". Two or more on one line means the line is the key
#: to the table rather than a row of it.
#:
#: The narrow `_LEGEND` above only caught SHORT ALL-CAPS labels ("LOC:",
#: "R-FL:"), which is how the BGP table's legend slipped through for weeks:
#: `Flags:` and `Origin:` are mixed case, and the continuation line starts
#: lowercase. Four such lines were captured as a "usable" expectation for
#: `show bgp l2vpn evpn table evi detail` and asserted on by TC01 and TC03 —
#: an assertion that passes on any device with an EVI of that name, working or
#: broken. Match the SHAPE of a glossary, not a spelling of one label.
_GLOSSARY_PAIR = re.compile(r"[^\s,]{1,8}\s+[-–]\s+\w")

#: A line that only restates the scope the command was already asked about,
#: e.g. "EVI Name = evi-1". It confirms the object exists and nothing about
#: whether the feature works.
_SCOPE_ECHO = re.compile(r"^[A-Za-z][\w /-]*\bnames?\b\s*[=:]", re.IGNORECASE)


def is_structural(line: str) -> bool:
    """Is this line printed regardless of what the device is doing?

    Structural lines are the furniture around the data: rules, column
    headers, legends, and echoes of the query. An expectation built only from
    these cannot tell a working device from a broken one, which is the whole
    thing this module exists to refuse.
    """
    s = line.strip()
    if not s:
        return True
    if _RULE.match(s):
        return True
    if _LEGEND.match(s):        # "LOC:  L - local, R - remote"
        return True
    if len(_GLOSSARY_PAIR.findall(s)) >= 2:   # "Flags: s - suppressed, ..."
        return True
    if _SCOPE_ECHO.match(s):    # "EVI Name = evi-1"
        return True
    return bool(_ALL_CAPS_HEADER.match(s))   # "INTERFACE  ESI  ES LABEL"


#: Kept for callers that predate the rename.
_is_structural = is_structural


def is_furniture(line: str) -> bool:
    """A line that is positively table furniture: rule, legend, or scope echo.

    Narrower than `is_structural`, which also treats a bare all-caps token as
    a column header. Used to STRIP furniture out of captured expectations,
    because asserting on it buys nothing and costs reliability twice over:

      * the legend is written with EN-DASHES (`L - local` is really
        `L – local`), and the emitter ASCII-folds expectations, so the
        assertion could never match the device it was captured from;
      * the separator rule's width tracks the widest row, so the same table
        prints 97 dashes one run and 98 the next.

    Both produce a test that fails for reasons having nothing to do with the
    feature - the mirror image of a legend that always passes.
    """
    s = line.strip()
    if not s:
        return True
    return bool(_RULE.match(s) or _LEGEND.match(s) or _SCOPE_ECHO.match(s)
                or len(_GLOSSARY_PAIR.findall(s)) >= 2)


def has_furniture_marker(lines: list[str]) -> bool:
    """Does this output carry a POSITIVE sign of being a table's furniture?

    `is_structural` also treats a bare all-caps word as a column header, which
    is right inside a table and too eager on its own: a one-line answer like
    "GOOD" or "ESTABLISHED" is a value, not a header. So declaring a whole
    output to be furniture needs a strong marker as well - a rule, a legend, a
    glossary, or an echo of the scope asked about. The BGP table's legend has
    three of them; a lone all-caps token has none.
    """
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if (_RULE.match(s) or _LEGEND.match(s) or _SCOPE_ECHO.match(s)
                or len(_GLOSSARY_PAIR.findall(s)) >= 2):
            return True
    return False


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

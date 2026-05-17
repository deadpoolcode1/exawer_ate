"""PlanRow → AtomicRow decomposer for the DHCP-snoopy 9-column xlsx shape.

Background: client review (2026-05-14, Eyal Ozeri) shared
`references/DHCP-snoopy_TP_with_PW.xlsx` as the visual target the
generator must match. That TP layout is **atomic-row-under-topic-banner**:
col A holds a short topic banner (Trusted / Option-82 / …), col B is one
sentence Action, col D one sentence Expectation, col E the `show` /
monitor command. Multi-step procedures are multiple rows, not multi-line
cells.

The generator pipeline still produces `PlanRow` objects with multi-line
Setup/Action/Verify blobs (so the AI-enrichment cache and rule-based
templates keep working). This module is the render-time projection: it
parses each blob into atomic action lines and emits a banner row + N
atomic action rows in the new shape.

Three entry points:

  - `rows_for_plan_row(row, flow_lookup)` — generic decomposer. Used for
    every existing PlanRow (flow rows, CLI rows, fallback rows).
  - `rows_for_synth_rfc(req)` — synthesized rows for RFC requirements
    no flow claims. Produces a banner + one action row per MUST clause.
  - `rows_for_cli_inherited(cmd)` — same as `rows_for_plan_row` for
    CLI rows that came from `cli_inheritance.expand()`, but flags
    `provenance="cli-inherit"` so xlsx_writer surfaces them on the
    Synthesized — Review sheet.

The decomposer is intentionally lossless wrt the underlying PlanRow's
intent: every numbered Setup/Action/Verify step becomes its own row, and
the row's monitor column carries the show-command names extracted from
the Verify section.
"""
from __future__ import annotations

import re

from ate.planner.flows import Flow
from ate.planner.model import AtomicRow, PlanRow, Requirement

# Match "  N. text" or "  - text" inside a Setup/Action/Verify body.
_NUMBERED_STEP_RE = re.compile(r"^\s*(?:\d+\.|-)\s+(.*\S)\s*$")
# Match a section header line like "Setup:" / "Action:" / "Verify:".
_SECTION_RE = re.compile(r"^\s*(Setup|Action|Verify)\s*:\s*(.*)$",
                          re.IGNORECASE)
# Extract show-command names from a Verify line (anything between backticks
# that starts with show / clear / debug / tcpdump etc).
_SHOW_CMD_RE = re.compile(
    r"`((?:show|clear|debug|tcpdump|wireshark|onie-install|"
    r"tech-support)[^`]*)`",
    re.IGNORECASE,
)


def _parse_blob(action_steps: str) -> tuple[list[str], list[str], list[str]]:
    """Split a Setup/Action/Verify multi-line cell into three step lists.

    Tolerates the two shapes the generator produces today:
      - "Setup:  one sentence\nAction: one sentence\nVerify: one sentence"
      - "Setup:\n  1. step\n  2. step\nAction:\n  1. step\nVerify:\n  1. step"
    A section that contains no enumerated steps becomes a single-element list.
    Returns (setup_steps, action_steps, verify_steps).
    """
    if not action_steps:
        return [], [], []

    setup: list[str] = []
    action: list[str] = []
    verify: list[str] = []
    bucket = setup
    inline_after_label = ""

    for raw in action_steps.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m_sec = _SECTION_RE.match(line)
        if m_sec:
            section = m_sec.group(1).lower()
            inline_after_label = m_sec.group(2).strip()
            bucket = {"setup": setup, "action": action,
                      "verify": verify}[section]
            if inline_after_label:
                bucket.append(inline_after_label)
            continue
        m_step = _NUMBERED_STEP_RE.match(line)
        if m_step:
            bucket.append(m_step.group(1).strip())
            continue
        # Stray continuation line — append to the last item if any, else
        # push a new step.
        text = line.strip()
        if bucket and not text.startswith("("):
            bucket[-1] = bucket[-1].rstrip() + " " + text
        else:
            bucket.append(text)

    return setup, action, verify


def _split_expectation(expectation: str) -> tuple[str, str]:
    """Pull (pass_line, fail_line) from a "Pass: …\nFail-on: …" blob."""
    if not expectation:
        return "", ""
    pass_line = ""
    fail_line = ""
    for ln in expectation.splitlines():
        s = ln.strip()
        low = s.lower()
        if low.startswith("pass:"):
            pass_line = s.split(":", 1)[1].strip()
        elif low.startswith("fail-on:") or low.startswith("fail on:"):
            fail_line = s.split(":", 1)[1].strip()
    return pass_line, fail_line


def _monitors_from_verify(verify_steps: list[str]) -> list[str]:
    """Extract every backtick-quoted show/clear/debug command from the
    Verify steps. Used as the row's Monitor column. Dedup preserving order."""
    seen: list[str] = []
    for step in verify_steps:
        for cmd in _SHOW_CMD_RE.findall(step):
            cmd = cmd.strip()
            if cmd and cmd not in seen:
                seen.append(cmd)
    return seen


def _atomic_action_line(step: str) -> str:
    """Trim a Setup/Action step to a single-sentence action verb. Strips
    trailing parentheticals so DHCP-snoopy-shape rows stay one line."""
    s = step.strip().rstrip(".")
    # Compress whitespace.
    s = re.sub(r"\s+", " ", s)
    return s


# Setup-step phrases that describe generic plumbing the operator doesn't
# need a row for ("DUT booted", "DUT in mode X", "feature configured per
# row 1", etc.). When the Setup step matches one of these, we skip the
# row entirely — DHCP-snoopy never has rows for these prerequisites.
_GENERIC_SETUP_PREFIXES = (
    "dut booted",
    "dut in mode",
    "dut bare",
    "no prior",
    "prerequisite",
    "two-pe topology",
    "two pe topology",
    "single-router topology",
    "cli session attached",
    "cli session via",
    "documented",
)
_GENERIC_SETUP_CONTAINS = (
    "configured (row 1",
    "configured per the canonical",
    "configured per spec",
    "configured and committed",
)


def _is_generic_setup(step: str) -> bool:
    s = step.strip().lower()
    if not s:
        return True
    for p in _GENERIC_SETUP_PREFIXES:
        if s.startswith(p):
            return True
    for c in _GENERIC_SETUP_CONTAINS:
        if c in s:
            return True
    return False


def _short_pass(pass_line: str, action: str) -> str:
    """Pick a one-sentence expectation for an atomic row.

    Strategy: use the first sentence of the Pass: line. If that's empty,
    fall back to a generic "action successful per documented behaviour"
    (the phrase the DHCP-snoopy TP uses)."""
    if not pass_line:
        return "Action successful per documented behaviour"
    # Take the first sentence (split on '; ' or '. ').
    head = re.split(r"(?<=[.;])\s+", pass_line, maxsplit=1)[0].strip()
    return head or "Action successful per documented behaviour"


def _topic_for_plan_row(row: PlanRow, flow_lookup: dict[str, Flow]) -> str:
    """Compose the banner topic for a PlanRow group.

    For flow rows: `FLOW-NNN — Flow Name`. For CLI rows: the command name
    (col A in DHCP-snoopy shows the sub-config noun). For everything else:
    the category."""
    if row.flow_id:
        flow = flow_lookup.get(row.flow_id)
        name = flow.name if flow else row.flow_name
        return f"{row.flow_id} — {name}" if name else row.flow_id
    if row.sub_category:
        return row.sub_category
    return row.category or ""


def rows_for_plan_row(row: PlanRow,
                       flow_lookup: dict[str, Flow] | None = None,
                       emit_banner: bool = True,
                       provenance: str = "",
                       ) -> list[AtomicRow]:
    """Decompose one PlanRow into a banner + atomic action rows.

    `emit_banner=False` skips the banner (used when the caller is already
    rendering a wider banner for a flow / category group). `provenance`
    flows to the Comment column so xlsx_writer can surface synth / inherit
    rows on the Synthesized — Review sheet.
    """
    flow_lookup = flow_lookup or {}
    setup, action, verify = _parse_blob(row.action_steps)
    pass_line, fail_line = _split_expectation(row.expectation)
    monitors = _monitors_from_verify(verify)
    req_ids = list(row.covered_req_ids)
    if not req_ids and row.sfs_requirement_id:
        # PlanRow stores comma-joined IDs in this field for legacy callers.
        req_ids = [s.strip() for s in row.sfs_requirement_id.split(",")
                   if s.strip()]

    out: list[AtomicRow] = []
    if emit_banner:
        topic = _topic_for_plan_row(row, flow_lookup)
        if topic:
            out.append(AtomicRow(topic=topic, is_banner=True,
                                  provenance=provenance))

    # Setup steps: skip generic plumbing ("DUT booted", "DUT in mode X").
    # Emit only Setup steps that describe non-obvious state (IXIA primed,
    # specific traffic loaded, fault injection script). The DHCP-snoopy
    # reference TP never has rows for boilerplate setup — it's implicit
    # under the topic banner. Drop the "Setup: " prefix when we do keep
    # the row: the action column reads as the prerequisite verb-phrase
    # directly (matches DHCP-snoopy convention).
    kept_setup = [s for s in setup if not _is_generic_setup(s)]
    for s in kept_setup:
        out.append(AtomicRow(
            topic="",
            action=_atomic_action_line(s),
            req_ids=req_ids,
            expectation="Prerequisite established",
            monitor=[],
            equipment=row.equipment,
            provenance=provenance,
        ))

    # Verify-only steps without a backticked show command often duplicate
    # the Expectation column (e.g. "Help (`?`) lists `cmd` with non-empty
    # description"). Fold them into the last action's expectation rather
    # than emitting separate rows — DHCP-snoopy keeps verifies inside
    # the Expectation cell, not as their own rows.
    verify_extras = [v for v in verify if not _SHOW_CMD_RE.search(v)]
    extra_expectation_text = "; ".join(_atomic_action_line(v)
                                         for v in verify_extras)

    # Action steps: each becomes its own row. Monitor commands extracted
    # from the Verify section are attached to every action row (the QA
    # engineer sees the same show-command set on each line, matching
    # DHCP-snoopy convention — see references TP cols E across R32-R37).
    if action:
        for i, a in enumerate(action):
            is_last = i == len(action) - 1
            # Last action carries the full Pass / Fail-on expectation,
            # plus any verify-extras folded in. Earlier actions carry
            # the short one-sentence pass.
            if is_last and fail_line:
                exp = (f"Pass: {pass_line}" if pass_line
                        else "Action successful")
                exp += f". Fail-on: {fail_line}"
            else:
                exp = _short_pass(pass_line, a)
            if is_last and extra_expectation_text:
                exp = exp + ". Verify: " + extra_expectation_text
            out.append(AtomicRow(
                topic="",
                action=_atomic_action_line(a),
                req_ids=req_ids,
                expectation=exp,
                monitor=monitors,
                equipment=row.equipment,
                provenance=provenance,
            ))
    else:
        # No action body — emit one summary row so the PlanRow isn't lost.
        out.append(AtomicRow(
            topic="",
            action=(row.flow_name
                    or row.sub_category
                    or row.category
                    or "(no action documented)"),
            req_ids=req_ids,
            expectation=row.expectation or "Behaves per spec",
            monitor=monitors,
            equipment=row.equipment,
            provenance=provenance,
        ))

    return out


# ── Synthesized RFC orphan rows ────────────────────────────────────────

def rows_for_synth_rfc(req: Requirement) -> list[AtomicRow]:
    """Auto-synthesize a banner + atomic rows for an RFC requirement that
    no flow claims.

    Banner: `RFC <short> §<num> — <title>`. Then one atomic row per MUST
    clause: Action = the MUST sentence; Expectation = "behaviour conforms
    to RFC <short> §<num>"; Monitor = "(define after first run — RFC-synth)".
    """
    short = req.req_id.split("-§")[0] if "-§" in req.req_id else "RFC"
    section = req.section_number or req.req_id.split("§")[-1] if "§" in req.req_id else ""
    topic = f"{short} §{section} — {req.title}" if section else f"{short} — {req.title}"

    out: list[AtomicRow] = [
        AtomicRow(topic=topic, is_banner=True, provenance="synth"),
    ]

    if not req.must_statements:
        out.append(AtomicRow(
            topic="",
            action=(req.description[:200] or req.title).strip().rstrip("."),
            req_ids=[req.req_id],
            expectation=f"Behaviour conforms to {short}"
                        + (f" §{section}" if section else ""),
            monitor=["(define after first run — RFC-synth row)"],
            equipment="DUT only (RFC-mandated; refine when use case clear)",
            provenance="synth",
        ))
        return out

    for must in req.must_statements[:5]:
        # Trim "[STD] " kind of prefixes; strip surrounding quotes.
        clause = re.sub(r"\s+", " ", must.strip())
        if len(clause) > 240:
            clause = clause[:237] + "…"
        out.append(AtomicRow(
            topic="",
            action=clause,
            req_ids=[req.req_id],
            expectation=f"Behaviour conforms to {short}"
                        + (f" §{section}" if section else ""),
            monitor=["(define after first run — RFC-synth row)"],
            equipment="DUT only (RFC-mandated; refine when use case clear)",
            provenance="synth",
        ))
    return out


def rows_for_cli_inherited(plan_row: PlanRow,
                            flow_lookup: dict[str, Flow] | None = None,
                            ) -> list[AtomicRow]:
    """Same shape as `rows_for_plan_row` but stamps `provenance="cli-inherit"`
    so the Synthesized — Review sheet surfaces the row.

    The caller (xlsx_writer) decides which CLI rows are inherited by
    checking `cli_inheritance.inheritance_source_for(name)`.
    """
    return rows_for_plan_row(plan_row, flow_lookup=flow_lookup,
                              emit_banner=True, provenance="cli-inherit")

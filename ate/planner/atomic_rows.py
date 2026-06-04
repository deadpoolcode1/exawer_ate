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

Single entry point: `rows_for_plan_row(row, flow_lookup, provenance)` —
decomposes any PlanRow (flow row, CLI row, fallback row, RFC-mandate row
emitted by generator._planrow_for_rfc_orphan) into banner + atomic
action rows. The `provenance` argument flags RFC-orphan / CLI-inherit
rows for xlsx-writer tinting.

The decomposer is intentionally lossless wrt the underlying PlanRow's
intent: every numbered Setup/Action/Verify step becomes its own row, and
the row's monitor column carries the show-command names extracted from
the Verify section.
"""
from __future__ import annotations

import re

from ate.planner.flows import Flow
from ate.planner.model import AtomicRow, PlanRow

# Match "  N. text" or "  - text" inside a Setup/Action/Verify body.
_NUMBERED_STEP_RE = re.compile(r"^\s*(?:\d+\.|-)\s+(.*\S)\s*$")
# Match a section header line like "Setup:" / "Action:" / "Verify:".
_SECTION_RE = re.compile(r"^\s*(Setup|Action|Verify)\s*:\s*(.*)$",
                          re.IGNORECASE)
# Match the per-test-case framing lines the AI now leads with (Aleksey
# Burger SW review 2026-06-04: every test case must state the problem under
# test + the method used). These precede Setup/Action/Verify in the blob.
_LEAD_RE = re.compile(r"^\s*(Problem|Method)\s*:\s*(.*)$", re.IGNORECASE)
# Extract show-command names from a Verify line (anything between backticks
# that starts with show / clear / debug / tcpdump etc).
_SHOW_CMD_RE = re.compile(
    r"`((?:show|clear|debug|tcpdump|wireshark|onie-install|"
    r"tech-support)[^`]*)`",
    re.IGNORECASE,
)


def _parse_blob(
    action_steps: str,
) -> tuple[str, str, list[str], list[str], list[str]]:
    """Split a Problem/Method/Setup/Action/Verify cell into its parts.

    Tolerates the shapes the generator produces today:
      - "Setup:  one sentence\nAction: one sentence\nVerify: one sentence"
      - "Setup:\n  1. step\n  2. step\nAction:\n  1. step\nVerify:\n  1. step"
      - the same prefixed with "Problem: …\nMethod: …" framing lines
        (Aleksey 2026-06-04). Problem/Method are single sentences, not step
        buckets, and may wrap across continuation lines.
    A section that contains no enumerated steps becomes a single-element list.
    Returns (problem, method, setup_steps, action_steps, verify_steps).
    """
    if not action_steps:
        return "", "", [], [], []

    problem = ""
    method = ""
    setup: list[str] = []
    action: list[str] = []
    verify: list[str] = []
    bucket = setup
    lead: str | None = None  # None | "problem" | "method"
    inline_after_label = ""

    for raw in action_steps.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m_lead = _LEAD_RE.match(line)
        if m_lead:
            lead = m_lead.group(1).lower()
            text = m_lead.group(2).strip()
            if lead == "problem":
                problem = text
            else:
                method = text
            continue
        m_sec = _SECTION_RE.match(line)
        if m_sec:
            lead = None
            section = m_sec.group(1).lower()
            inline_after_label = m_sec.group(2).strip()
            bucket = {"setup": setup, "action": action,
                      "verify": verify}[section]
            if inline_after_label:
                bucket.append(inline_after_label)
            continue
        m_step = _NUMBERED_STEP_RE.match(line)
        if m_step:
            lead = None
            bucket.append(m_step.group(1).strip())
            continue
        # Stray continuation line — extend the active Problem/Method framing
        # if we're inside one, else append to the last step / push a new one.
        text = line.strip()
        if lead == "problem":
            problem = (problem + " " + text).strip()
            continue
        if lead == "method":
            method = (method + " " + text).strip()
            continue
        if bucket and not text.startswith("("):
            bucket[-1] = bucket[-1].rstrip() + " " + text
        else:
            bucket.append(text)

    return problem, method, setup, action, verify


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
    "dut able to reach",
    "dut at the",
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


def _split_clauses(text: str) -> list[str]:
    """Break a Pass line into its constituent expectations — one per cell.

    Splits on `; ` and sentence boundaries so a packed
    "X is accepted; Y reads back via `show …`" expectation becomes two
    rows (client 2026-06-02, item: each cell represents one expectation).
    """
    if not text:
        return []
    parts = re.split(r"\s*;\s+|(?<=[.])\s+", text)
    return [p.strip().rstrip(".") for p in parts if p.strip()]


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
    problem, method, setup, action, verify = _parse_blob(row.action_steps)
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

    # Problem / Method framing rows (Aleksey Burger SW review 2026-06-04:
    # "describe the problem to be tested and the method used"). They lead
    # the atomic rows directly under the banner — col B carries the
    # `Problem:` / `Method:` sentence, no req-id / expectation / monitor
    # noise (they document the test case, they aren't an executable step).
    for label, text in (("Problem", problem), ("Method", method)):
        if text:
            out.append(AtomicRow(
                topic="",
                action=f"{label}: {text}",
                req_ids=[],
                expectation="",
                monitor=[],
                equipment=row.equipment,
                provenance=provenance,
            ))

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

    # Verify-only steps without a backticked show command (e.g. "Help (`?`)
    # lists `cmd` with a non-empty description") are distinct expectations.
    verify_extras = [v for v in verify if not _SHOW_CMD_RE.search(v)]

    # Each expectation gets its OWN cell/row rather than being concatenated
    # into one long Expectation cell (client 2026-06-02, Eyal Ozeri, item:
    # "the expectation cell is too long — break it to separate cells, each
    # representing an expectation"). The last action carries the first Pass
    # clause; the remaining Pass clauses, the Fail-on, and any verify-only
    # expectations follow as their own continuation rows (col A/B empty).
    pass_clauses = _split_clauses(pass_line)

    # Action steps: each becomes its own row. Monitor commands extracted
    # from the Verify section are attached to every action row (the QA
    # engineer sees the same show-command set on each line, matching
    # DHCP-snoopy convention — see references TP cols E across R32-R37).
    if action:
        for i, a in enumerate(action):
            is_last = i == len(action) - 1
            if is_last:
                exp = (f"Pass: {pass_clauses[0]}" if pass_clauses
                       else _short_pass(pass_line, a))
            else:
                exp = _short_pass(pass_line, a)
            out.append(AtomicRow(
                topic="",
                action=_atomic_action_line(a),
                req_ids=req_ids,
                expectation=exp,
                monitor=monitors,
                equipment=row.equipment,
                provenance=provenance,
            ))
        # Trailing expectation-only rows — one expectation per cell.
        trailing: list[str] = [f"Pass: {c}" for c in pass_clauses[1:]]
        if fail_line:
            trailing.append(f"Fail-on: {fail_line.rstrip('.')}")
        trailing.extend(_atomic_action_line(v) for v in verify_extras)
        for exp in trailing:
            out.append(AtomicRow(
                topic="",
                action="",
                req_ids=req_ids,
                expectation=exp,
                monitor=[],
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



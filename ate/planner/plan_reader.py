"""Read a generated test-plan xlsx back into structured, ID-keyed rows.

The pipeline could write a plan and never read one. That one-way street is why
every review round was hand-triage: Eyal Ozeri's 53 annotations on
``EVPN_test_plan_with_RFCs (3).xlsx`` were transcribed by eye, a later file of
his came back with no recoverable annotations at all and a whole batch had to
be reconstructed from WhatsApp messages, and his standing request — "send a
diff file with every version, I'm getting lost" — had no tool behind it.

This module is that missing half. It parses the ``Test Plan Topics`` sheet
back into :class:`PlanTopic` / :class:`PlanAction` objects keyed by the
identifiers the writer already emits and never renumbers:

* ``FLOW-030`` — a flow banner (flow IDs are stable by project rule)
* ``CLI:mac-limit`` — a CLI command topic
* ``RFC7432bis-§7.2`` — an RFC mandate topic
* ``SEC:Scale`` — a section band

Everything downstream — ``plan-diff``, ``review-ingest`` — is a thin layer on
these keys. Nothing here depends on row numbers, because row numbers move on
every regeneration and are exactly what a reviewer cannot cite reliably.

Deliberately tolerant
---------------------
The reader accepts files this pipeline did not write: a reviewer's copy that
has been re-saved by Excel, had columns widened, rows deleted, or notes typed
directly into cells. It keys off the header text rather than column position,
and treats an unparseable row as an anonymous action under the current topic
rather than raising. A review tool that refuses the reviewer's actual file is
of no use.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

#: The sheet the plan body lives on. Older generations, and the sheet Eyal
#: typed his 53 annotations onto, call it "Test Plan Phase 1".
BODY_SHEETS = ("Test Plan Topics", "Test Plan Phase 1")

#: Column header -> canonical field name. Matched case-insensitively on a
#: prefix, because the writer's headers carry parentheticals ("Monitor (show /
#: verify command)") that have changed wording between versions while the
#: leading word has not.
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("topic", "topic"),
    ("action", "action"),
    ("sfs", "req_ids"),
    ("expectation", "expectation"),
    ("monitor", "monitor"),
    ("test equipment", "equipment"),
    ("build", "build"),
    ("results", "results"),
    ("comment", "comment"),
)

# Topic-key shapes the writer emits. Order matters: a flow banner reads
# "FLOW-030 — name", and an RFC topic "RFC7432bis-§7.2 — name".
_FLOW_RE = re.compile(r"^(FLOW-\d+)\b")
# `RFC7432bis §7.2` and `RFC7432bis-§7.2` are both in circulation — the
# writer spells it with a space, the req-id column with a hyphen. Accept
# either, and normalise to the hyphenated form so a topic keeps one key
# across versions that changed the spelling.
_RFC_RE = re.compile(r"^(RFC[\w.]*?)[\s-]*(\u00a7[\d.]+)")
# A CLI topic banner is "<command name> — <purpose phrase>". The command
# name is whatever the CLI doc's heading said, which includes spaces,
# parentheses and slashes: `control-word (evpn)`, `interface (VPLS/EVPN)`,
# `show bgp l2vpn evpn neighbors advertised/received routes`, and the
# `| output modifiers` pseudo-command. An earlier `[a-z0-9 -]` charset
# rejected all of those, and they silently became section bands — which
# detached their 19-37 action rows from any topic.
_CLI_RE = re.compile(r"^(?:CLI:)?(\S[^—]*?)\s+—\s")


@dataclass
class PlanAction:
    """One atomic action row beneath a topic banner."""

    action: str = ""
    req_ids: str = ""
    expectation: str = ""
    monitor: str = ""
    equipment: str = ""
    build: str = ""
    results: str = ""
    comment: str = ""
    #: 1-based row in the sheet it was read from. For pointing a human at it —
    #: never for identity, because it changes on every regeneration.
    source_row: int = 0

    @property
    def key(self) -> str:
        """Identity of this action *within* its topic.

        The action text itself, normalised. Actions have no IDs of their own,
        and adding one would change the client-facing schema, so the text is
        the key — which means a reworded action reads as a remove plus an add.
        `plan_diff` softens that with similarity matching rather than the
        reader pretending to an identity it does not have.
        """
        return _norm(self.action)

    def cells(self) -> dict[str, str]:
        return {
            "Action": self.action,
            "Req ID": self.req_ids,
            "Expectation": self.expectation,
            "Monitor": self.monitor,
            "Test Equipment": self.equipment,
            "Comment": self.comment,
        }


@dataclass
class PlanTopic:
    """A banner row plus the atomic action rows under it."""

    key: str                    # FLOW-030 / CLI:mac-limit / RFC7432bis-§7.2
    label: str                  # the banner's full text
    kind: str                   # flow | cli | rfc | section | other
    section: str = ""           # the section band it sits in
    summary: str = ""           # banner body (col B)
    actions: list[PlanAction] = field(default_factory=list)
    source_row: int = 0

    @property
    def uid(self) -> str:
        """Identity for diffing — the citable key, qualified by section.

        A flow legitimately appears under several section bands, each time
        rendered from that category's angle (FLOW-133 runs under Feature
        Functionality, Packet Validation, Feature Interaction and
        Performance). Those are four different topics that share one citable
        ID, so `key` alone would collapse them and the diff would report
        phantom churn as they permuted.

        Reviewers still cite `key` — "FLOW-030 step 2" — which is why both
        exist.
        """
        return f"{self.key}@{self.section}" if self.section else self.key

    @property
    def req_ids(self) -> set[str]:
        out: set[str] = set()
        for a in self.actions:
            out |= {t.strip() for t in re.split(r"[,\n]", a.req_ids) if t.strip()}
        return out


@dataclass
class PlanDocument:
    """A whole plan, as read back from a workbook."""

    path: Path
    sheet: str
    topics: list[PlanTopic] = field(default_factory=list)

    @property
    def by_key(self) -> dict[str, PlanTopic]:
        return {t.key: t for t in self.topics}

    @property
    def action_count(self) -> int:
        return sum(len(t.actions) for t in self.topics)

    def topic(self, key: str) -> PlanTopic | None:
        return self.by_key.get(key)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def read_plan(path: Path | str) -> PlanDocument:
    """Parse a generated (or reviewer-annotated) plan workbook."""
    path = Path(path)
    wb = load_workbook(path, data_only=True)
    ws, sheet_name = _body_sheet(wb)
    header_row, colmap = _find_header(ws)

    doc = PlanDocument(path=path, sheet=sheet_name)
    section = ""
    current: PlanTopic | None = None

    for r in range(header_row + 1, ws.max_row + 1):
        cells = {name: _text(ws.cell(row=r, column=idx).value)
                 for name, idx in colmap.items()}
        topic_text = cells.get("topic", "")
        rest = [v for k, v in cells.items() if k != "topic" and v]

        if not topic_text and not rest:
            continue

        if _is_section_band(topic_text, rest):
            section = _norm_label(topic_text)
            current = None
            continue

        if topic_text:
            current = _topic_from(topic_text, cells, section, r)
            doc.topics.append(current)
            continue

        # A row with no Action text continues the action above it: the writer
        # splits a Pass / Fail-on expectation across consecutive rows, leaving
        # column B empty on all but the first. Those rows have no identity of
        # their own, and treating them as separate actions was actively
        # harmful — they all key on "" and so paired positionally, turning one
        # inserted row into a cascade of dozens of phantom "edits" down the
        # rest of the topic. Fold them into their parent instead.
        if (not cells.get("action") and current is not None
                and current.actions and _is_continuation(cells)):
            _absorb(current.actions[-1], cells)
            continue

        if current is None:
            # Action rows before any banner — a reviewer's edit, or a file
            # whose first banner was deleted. Keep them under a synthetic
            # topic rather than dropping data the reviewer may have annotated.
            # Keyed by the section it sits in, so the "(left empty — the
            # source documents carry no information for this section)" notes
            # under MALFORMED / ROBUSTNESS / ALARMS / HA stay four distinct
            # topics instead of collapsing onto one key in `by_key`.
            current = PlanTopic(key=f"SEC:{section or sheet_name}",
                                label=section or "(rows before the first topic banner)",
                                kind="section", section=section, source_row=r)
            doc.topics.append(current)
        current.actions.append(_action_from(cells, r))

    return doc


def _body_sheet(wb):
    for name in BODY_SHEETS:
        if name in wb.sheetnames:
            return wb[name], name
    # Fall back to the first sheet that has our header, then to the active one.
    for name in wb.sheetnames:
        try:
            _find_header(wb[name])
            return wb[name], name
        except LookupError:
            continue
    return wb.active, wb.active.title


def _find_header(ws) -> tuple[int, dict[str, int]]:
    """Locate the 9-column header and map canonical names onto columns.

    Scans the first rows rather than assuming row 1: the header sat below a
    feature-meta block until 2026-06-14, and reviewer copies sometimes carry an
    extra title row.
    """
    for r in range(1, min(ws.max_row, 12) + 1):
        colmap: dict[str, int] = {}
        for c in range(1, min(ws.max_column, 20) + 1):
            label = _text(ws.cell(row=r, column=c).value).lower()
            if not label:
                continue
            for prefix, name in _COLUMNS:
                if label.startswith(prefix) and name not in colmap:
                    colmap[name] = c
        if {"topic", "action"} <= set(colmap):
            return r, colmap
    raise LookupError("no 9-column plan header found in this sheet")


def _is_section_band(topic: str, rest: list[str]) -> bool:
    """A dark section band, as opposed to a topic banner.

    Both occupy column A alone, so emptiness cannot tell them apart. The
    writer's own distinction is that section bands are the template's
    taxonomy labels and are rendered in upper case (`SCALE`,
    `ALARMS/LOGS/SYSLOG`, `CLI CONFIGURATION — L2-SERVICES EVPN`), while
    topic banners carry a command name, a `FLOW-NNN` or an RFC section, all
    of which are mixed case.

    Getting this backwards is not cosmetic: a banner misread as a section
    orphans every action row beneath it, so the topic vanishes from the diff
    and a reviewer's comment on it has nothing to attach to.
    """
    if not topic or rest:
        return False
    stripped = _norm_label(topic)
    if not stripped:
        return False
    # A FLOW or RFC banner is always a topic, whatever its casing.
    if _FLOW_RE.match(stripped) or _RFC_RE.match(stripped):
        return False
    return _is_shouted(stripped)


def _is_shouted(text: str) -> bool:
    """Whether a label is written in upper case, ignoring non-letters."""
    letters = [ch for ch in text if ch.isalpha()]
    return bool(letters) and all(ch.isupper() for ch in letters)


def _classify(label: str) -> tuple[str, str]:
    """(key, kind) for a banner label, or ("", "") if it is not one."""
    if m := _FLOW_RE.match(label):
        return m.group(1), "flow"
    if m := _RFC_RE.match(label):
        return f"{m.group(1)}-{m.group(2)}", "rfc"
    if label.startswith("CLI:"):
        return label.split("—")[0].strip(), "cli"
    if m := _CLI_RE.match(label):
        return f"CLI:{m.group(1).strip()}", "cli"
    return "", ""


def _topic_from(topic_text: str, cells: dict[str, str],
                section: str, row: int) -> PlanTopic:
    label = _norm_label(topic_text)
    key, kind = _classify(label)
    if not key:
        key, kind = f"TOPIC:{_norm(label)}", "other"
    topic = PlanTopic(key=key, label=label, kind=kind, section=section,
                      summary=cells.get("action", ""), source_row=row)
    # A banner that also carries action-column content is a plain topic row
    # (the CLI families render this way), so keep the row as an action too.
    if any(cells.get(f) for f in ("expectation", "monitor", "req_ids")):
        topic.actions.append(_action_from(cells, row))
        topic.summary = ""
    return topic


def _action_from(cells: dict[str, str], row: int) -> PlanAction:
    return PlanAction(
        action=cells.get("action", ""),
        req_ids=cells.get("req_ids", ""),
        expectation=cells.get("expectation", ""),
        monitor=cells.get("monitor", ""),
        equipment=cells.get("equipment", ""),
        build=cells.get("build", ""),
        results=cells.get("results", ""),
        comment=cells.get("comment", ""),
        source_row=row,
    )


def _is_continuation(cells: dict[str, str]) -> bool:
    """Whether a row carries only trailing detail for the action above."""
    return not any(cells.get(f) for f in ("topic", "action"))


def _absorb(action: PlanAction, cells: dict[str, str]) -> None:
    """Append a continuation row's cells onto the action it belongs to."""
    for field_name, key in (("expectation", "expectation"),
                            ("monitor", "monitor"),
                            ("equipment", "equipment"),
                            ("req_ids", "req_ids"),
                            ("comment", "comment")):
        extra = cells.get(key, "")
        if not extra:
            continue
        existing = getattr(action, field_name)
        if not existing:
            setattr(action, field_name, extra)
            continue
        # Continuation rows repeat the constant columns — Test Equipment and
        # Comment carry the same value on every row of an action. Joining
        # them blindly makes the folded cell's length depend on how many
        # expectation lines the action happens to have, so adding one line
        # showed up in the diff as an edit to Test Equipment. Only append
        # genuinely new content.
        if extra in existing.split("\n"):
            continue
        setattr(action, field_name, f"{existing}\n{extra}")


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").strip()


def _norm_label(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _norm(text: str) -> str:
    """Whitespace- and case-insensitive form, for comparing cell content."""
    return re.sub(r"\s+", " ", text or "").strip().lower()

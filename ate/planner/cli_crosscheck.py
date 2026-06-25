"""Cross-check every CLI / ``show`` command emitted in a test plan against the
commands that are actually *grounded in an ingested source document*.

Yossi Fridman (SW review, 2026-06-24) flagged ``show mpls lsp`` (cell E1588 of
"Test Plan Topics") as "an AI hallucination ... no such command in the SFS" and
asked us to check its origin. The origin turned out **not** to be the AI
enricher at all: ``show mpls lsp`` is hard-coded in our own hand-curated
monitor vocabulary — ``categories._FLOW_SHOW_CMDS['FLOW-13']`` and the
``flows.py`` EVI-to-EVI RFC 4364 transport flows. The enricher is already
fenced off from inventing commands (see ``ai_enricher.py`` GROUNDING RULE and
the CLI-row exemption), so no AI token leaked. But the underlying concern is
real and worth a standing guard: a command can reach the plan without being
traceable to any document Exaware handed us.

This module is that guard. It collects every command token that appears in the
generated plan and buckets each by provenance:

  - ``doc_grounded`` — the command head appears in the ingested CLI doc / SFS /
    RFC text. Fully traceable; trusted.
  - ``generic``      — a universal operator verb (``show running-config``,
    ``commit``, ``configure``, ``ping`` ...) that needs no feature doc to
    justify. Trusted.
  - ``curated``      — present in our hand-maintained monitor vocabulary
    (``categories.py`` / ``flows.py``) but NOT in any ingested doc. Legitimate
    engineering judgement, but unverified against Exaware's real CLI — a
    reviewer should confirm or delete it. ``show mpls lsp`` lands here.
  - ``unknown``      — none of the above: a token nobody curated and no
    document backs. This is the only true "hallucinated command" bucket and
    should always be empty.

``curated`` is surfaced for SME review (mirroring the existing
``synthesized — review`` provenance markers); ``unknown`` is a hard alert.

The same dual-output philosophy as ``rfc_crosscheck.py``: detect and surface
the gap so a human decides — never silently drop or silently trust.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Backtick-quoted operator commands in prose. Mirrors the monitor extractor in
# ``atomic_rows._SHOW_CMD_RE`` so the cross-check sees exactly the tokens that
# become the plan's Monitor column, plus any the enricher slips into Verify
# prose.
_CMD_RE = re.compile(
    r"`((?:show|clear|debug|tcpdump|wireshark|onie-install|"
    r"tech-support|monitor)[^`]*)`",
    re.IGNORECASE,
)

# A command "head" stops at the first argument-like token: a value (digits),
# a placeholder (``<name>``, ``ALL-CAPS``), or grammar punctuation. So
# ``show evpn evi 10`` and ``show evpn evi <id>`` both normalise to the head
# ``show evpn evi`` for inventory comparison.
_KEYWORD_TOK = re.compile(r"^[a-z][a-z0-9-]*$")


def command_head(cmd: str) -> str:
    """Canonical head of a CLI command for inventory comparison.

    Lower-cases, collapses whitespace, drops a leading ``no``/``do``, and keeps
    the leading run of keyword tokens up to the first argument-like token.

        ``show evpn evi 10``   -> ``show evpn evi``
        ``show mpls lsp``      -> ``show mpls lsp``
        ``clear evpn mac <m>`` -> ``clear evpn mac``
    """
    toks = re.sub(r"\s+", " ", cmd.strip().lower()).split()
    while toks and toks[0] in ("no", "do"):
        toks = toks[1:]
    head: list[str] = []
    for t in toks:
        if _KEYWORD_TOK.match(t):
            head.append(t)
        else:
            break
    return " ".join(head) if head else " ".join(toks[:1])


# Universal operator verbs that are valid on any router regardless of feature
# docs. Kept deliberately small and head-normalised; extends the inline list
# the enricher prompt already trusts (``ai_enricher.py`` "No invented
# commands" rule).
_GENERIC_VERBS: set[str] = {
    command_head(c)
    for c in (
        "show running-config", "show configuration", "show version",
        "show log", "show logging", "show alarms", "show interfaces",
        "show interface", "show route", "show route table", "show bgp",
        "show platform process", "show platform process memory",
        "show platform process cpu", "show system", "show chassis",
        "show tech-support", "tech-support", "onie-install",
        "commit", "configure", "ping", "traceroute", "telnet", "ssh",
        "clear log", "clear logging", "clear counters",
        "tcpdump", "wireshark", "monitor",
    )
}

# Bare operator verbs that mean nothing without an object — a lone ``show`` or
# ``clear`` head is a prose/regex artifact ("inspect the `show` output"), not a
# command. Dropped from the emitted set so they don't pollute the alert.
_BARE_VERB_NOISE: frozenset[str] = frozenset(
    {"show", "clear", "debug", "monitor", "tcpdump", "wireshark"}
)


def _prefix_in(head: str, vocab: set[str]) -> bool:
    """True if ``head`` equals, or extends (token-wise), any entry in ``vocab``.

    ``show evpn evi evi-1`` is grounded by the base ``show evpn evi``; a value
    or sub-qualifier appended to a known command is that command with an
    argument, not a new/invented one.
    """
    toks = head.split()
    for i in range(len(toks), 0, -1):
        if " ".join(toks[:i]) in vocab:
            return True
    return False


@dataclass
class EmittedCommand:
    """One command head as it appears in the plan, with where it was seen."""
    head: str
    raw: str                       # first raw form encountered
    locations: list[str] = field(default_factory=list)  # e.g. ["FLOW-130"]


@dataclass
class CliCommandCrossCheck:
    """Result of bucketing every emitted command by provenance.

    Each bucket maps command-head -> :class:`EmittedCommand`.
    """
    doc_grounded: dict[str, EmittedCommand]
    generic: dict[str, EmittedCommand]
    curated: dict[str, EmittedCommand]
    unknown: dict[str, EmittedCommand]

    @property
    def has_unknown(self) -> bool:
        return bool(self.unknown)

    @property
    def has_review(self) -> bool:
        """True when something needs a human eye (curated-but-unverified or a
        genuine unknown)."""
        return bool(self.curated) or bool(self.unknown)

    @property
    def total(self) -> int:
        return (len(self.doc_grounded) + len(self.generic)
                + len(self.curated) + len(self.unknown))


def commands_in_text(text: str) -> list[str]:
    """Every backtick-quoted operator command in ``text`` (raw forms, in order)."""
    if not text:
        return []
    return [m.strip() for m in _CMD_RE.findall(text)]


def emitted_commands(plan) -> dict[str, EmittedCommand]:
    """Collect every command head emitted across the plan's rows.

    Scans each ``PlanRow``'s ``action_steps`` + ``expectation`` prose — the
    same text the Monitor column is distilled from — so the cross-check sees
    exactly what reaches a cell. Keyed by head; ``locations`` records the
    flow ids (or sub-category for CLI rows) the command appeared under.
    """
    out: dict[str, EmittedCommand] = {}
    for row in getattr(plan, "rows", []) or []:
        where = getattr(row, "flow_id", "") or getattr(row, "sub_category", "") \
            or getattr(row, "category", "")
        blob = "\n".join(
            t for t in (getattr(row, "action_steps", ""),
                        getattr(row, "expectation", "")) if t
        )
        for raw in commands_in_text(blob):
            head = command_head(raw)
            if not head or head in _BARE_VERB_NOISE:
                continue
            ec = out.get(head)
            if ec is None:
                out[head] = EmittedCommand(head=head, raw=raw,
                                           locations=[where] if where else [])
            elif where and where not in ec.locations:
                ec.locations.append(where)
    return out


def doc_command_heads(cli_commands, requirements) -> set[str]:
    """Heads of every command grounded in an ingested document.

    Sources:
      - extracted CLI-doc commands (``catalog.cli_commands``) — every syntax
        line, so ``show``/``clear`` variants documented alongside a config
        command are captured, not just the config head.
      - backtick commands appearing in SFS / RFC requirement ``code_blocks``.
    """
    heads: set[str] = set()
    for c in cli_commands or []:
        name = getattr(c, "name", "")
        if name:
            heads.add(command_head(name))
        for line in getattr(c, "syntax_lines", []) or []:
            h = command_head(line)
            if h:
                heads.add(h)
    for req in requirements or []:
        for block in getattr(req, "code_blocks", []) or []:
            for raw in commands_in_text(block):
                heads.add(command_head(raw))
    heads.discard("")
    return heads


def curated_command_heads() -> set[str]:
    """Heads of our hand-maintained monitor vocabulary.

    Pulled live from the source of truth so the set can never drift from what
    the generator actually emits: ``categories._FLOW_SHOW_CMDS`` (per-flow
    ``show`` lists) and each ``flows.EVPN_FLOWS`` entry's ``related_cli_cmds``.
    Imported lazily to avoid an import cycle (both modules import ``model``).
    """
    heads: set[str] = set()
    try:
        from ate.planner.categories import _FLOW_SHOW_CMDS  # noqa: PLC0415
        for cmds in _FLOW_SHOW_CMDS.values():
            for c in cmds:
                heads.add(command_head(c))
    except Exception:  # pragma: no cover - defensive: source moved/renamed
        pass
    try:
        from ate.planner.flows import EVPN_FLOWS  # noqa: PLC0415
        for flow in EVPN_FLOWS:
            for c in getattr(flow, "related_cli_cmds", []) or []:
                heads.add(command_head(c))
    except Exception:  # pragma: no cover
        pass
    heads.discard("")
    return heads


def reconcile_commands(plan, cli_commands, requirements) -> CliCommandCrossCheck:
    """Bucket every command emitted in ``plan`` by provenance.

    A head is grounded by its longest matching *prefix* (see ``_prefix_in``):
    ``show evpn evi evi-1`` inherits the bucket of ``show evpn evi``.
    Precedence when prefixes match in more than one vocabulary:
    ``doc_grounded`` > ``generic`` > ``curated`` > ``unknown``. A documented
    command is reported as documented even if it also happens to be curated.
    """
    emitted = emitted_commands(plan)
    doc = doc_command_heads(cli_commands, requirements)
    curated = curated_command_heads()

    buckets: dict[str, dict[str, EmittedCommand]] = {
        "doc_grounded": {}, "generic": {}, "curated": {}, "unknown": {},
    }
    for head, ec in emitted.items():
        if _prefix_in(head, doc):
            buckets["doc_grounded"][head] = ec
        elif _prefix_in(head, _GENERIC_VERBS):
            buckets["generic"][head] = ec
        elif _prefix_in(head, curated):
            buckets["curated"][head] = ec
        else:
            buckets["unknown"][head] = ec
    return CliCommandCrossCheck(**buckets)


# Connector words that introduce a command in prose ("verify via `cmd`",
# "run `cmd`", "confirm with `cmd`"). Used to remove the lead-in along with the
# command so the scrubbed sentence reads cleanly.
_CONNECTOR = (
    r"(?:run|runs|running|use|uses|using|via|with|from|per|by|see|check|"
    r"checks|checking|confirm|confirms|confirming|inspect|inspects|"
    r"inspecting|observe|observing|validate|validating|and|then|on|in|"
    r"capture|capturing)"
)


def _scrub_text(text: str, ungrounded_raw: set[str],
                where: str, removed: dict[str, EmittedCommand]) -> str:
    """Remove every backtick command in ``ungrounded_raw`` from ``text`` and
    tidy the surrounding filler. Records each removal in ``removed``."""
    for raw in ungrounded_raw:
        esc = re.escape(raw)
        head = command_head(raw)
        if head:
            ec = removed.get(head)
            if ec is None:
                removed[head] = EmittedCommand(
                    head=head, raw=raw, locations=[where] if where else [])
            elif where and where not in ec.locations:
                ec.locations.append(where)
        # Order matters: strip the richest pattern (parenthetical / connector)
        # before the bare token.
        for pat in (
            rf"\s*\(\s*(?:{_CONNECTOR}\s+)?`{esc}`\s*\)",   # "(`cmd`)" / "(via `cmd`)"
            rf"\s*(?:,|;|—|–|-)?\s*{_CONNECTOR}\s+`{esc}`",  # "… via `cmd`"
            rf"\s*`{esc}`",                                  # bare "`cmd`"
        ):
            text = re.sub(pat, "", text, flags=re.IGNORECASE)
    # Tidy artefacts left behind.
    text = re.sub(r"\(\s*\)", "", text)            # empty parens
    text = re.sub(r"\s+([,.;:])", r"\1", text)     # space before punctuation
    text = re.sub(r"([,;])\s*([,;])", r"\1", text)  # doubled separators
    text = re.sub(r",\s*\.", ".", text)            # ", ." -> "."
    text = re.sub(r"\.\s*\.+", ".", text)          # ".." -> "."
    text = re.sub(rf"\s+{_CONNECTOR}\s*([.;,])", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(rf"\s+{_CONNECTOR}\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Removing a command that was a sentence's subject ("`show …` shows a POP")
    # leaves a lowercase clause start. Re-capitalise sentence/line starts
    # (after string start, newline + optional "N.", or ". ") so the prose reads
    # as deliberate. Semicolon continuations are left lowercase intentionally.
    text = re.sub(r"(^|\n[ \t]*(?:\d+\.[ \t]*)?|\.[ \t]+)([a-z])",
                  lambda m: m.group(1) + m.group(2).upper(), text)
    return text.strip()


def scrub_ungrounded(plan, cli_commands, requirements) -> dict[str, EmittedCommand]:
    """Strip every ungrounded command from the plan **in place** so the output
    carries no non-existing command (Ron/Yossi 2026-06-24; scope confirmed by
    Ilan 2026-06-25: unknown + the MPLS-transport monitors).

    A command is ungrounded when no prefix of its head is doc-grounded, a
    generic verb, or in the curated vocabulary — i.e. it would land in the
    ``unknown`` bucket of :func:`reconcile_commands`. Mutates each ``PlanRow``'s
    ``action_steps`` / ``expectation`` (the Monitor column is distilled from
    that prose, so it cleans up automatically). Returns the removed commands
    keyed by head for the audit sheet.
    """
    doc = doc_command_heads(cli_commands, requirements)
    curated = curated_command_heads()

    def _grounded(head: str) -> bool:
        return (_prefix_in(head, doc) or _prefix_in(head, _GENERIC_VERBS)
                or _prefix_in(head, curated))

    removed: dict[str, EmittedCommand] = {}
    for row in getattr(plan, "rows", []) or []:
        where = getattr(row, "flow_id", "") or getattr(row, "sub_category", "") \
            or getattr(row, "category", "")
        for attr in ("action_steps", "expectation"):
            text = getattr(row, attr, "") or ""
            if not text:
                continue
            ungrounded = {
                raw for raw in commands_in_text(text)
                if command_head(raw) not in _BARE_VERB_NOISE
                and not _grounded(command_head(raw))
            }
            if ungrounded:
                setattr(row, attr, _scrub_text(text, ungrounded, where, removed))
    return removed


def format_removal_summary(removed: dict[str, EmittedCommand]) -> str:
    """One-line-per-command summary of what the scrubber stripped, or '' when
    nothing was removed. Printed to stderr so the operator sees the engine kept
    the output clean."""
    if not removed:
        return ""
    lines = [
        f"command grounding: removed {len(removed)} ungrounded command(s) "
        "from the plan (see the 'Command Cross-Check' sheet):"
    ]
    for head in sorted(removed):
        ec = removed[head]
        loc = f"  [{', '.join(ec.locations)}]" if ec.locations else ""
        lines.append(f"  − `{ec.raw}`{loc}")
    return "\n".join(lines)


def format_warning(cc: CliCommandCrossCheck) -> str:
    """Hard alert if any ungrounded command survived the scrubber (should never
    happen — the scrubber removes the whole ``unknown`` bucket). '' otherwise."""
    if not cc.unknown:
        return ""
    lines = [
        f"warning: {len(cc.unknown)} ungrounded command(s) survived scrubbing "
        "— this is a bug, please report:"
    ]
    for head in sorted(cc.unknown):
        ec = cc.unknown[head]
        loc = f"  [{', '.join(ec.locations)}]" if ec.locations else ""
        lines.append(f"  ✗ `{ec.raw}`{loc}")
    return "\n".join(lines)

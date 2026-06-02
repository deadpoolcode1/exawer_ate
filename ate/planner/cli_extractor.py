"""Mine the EVPN CLI doc into structured Command objects.

Closes Yossi's M1 review gap: "CLI Configuration — missing aspects of CLI
commands: validations, defaults, etc.". The previous generator used a
single CLI excerpt as a "hint" appended to a generic template; QA had no
way to know which command, which parameter, what range, what default,
or what validation to perform.

This extractor walks the parsed CLI document's tables. Each command is
documented in a single 6-row table with a stable shape:

    Description     | <prose describing purpose, mentioning default behavior>
    CommandSyntax   | <command-line syntax, possibly multi-line / `no` form>
    Command Mode    | <mode hierarchy, e.g. "configuration interface agg-eth ethernet-segment">
    Parameters      | <header row: Name | Value | Description>
    <param rows...> | <one row per parameter: name, value/range, description>
    Examples        | <CLI session illustrating the command>
    Notes           | <constraints, defaults, mutex rules, prerequisites>

We classify each command as `config` (configuration mode), `show`
(operational read-only), or `clear` (operational state-resetting).
Show/clear commands aren't useful for the CLI configuration test plan
section — they get filtered out.

Defaults are extracted from two sources:
  1. The Description / Notes prose ("default = single-active",
     "the default is 37237", "the default is the agg-eth interface number")
  2. Parameter rows whose `value` cell is "(Default = X)" or "Default: X".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ate.ir import Document, Heading, Table
from ate.parsers import parse


@dataclass
class CliParameter:
    """One parameter of a CLI command."""
    name: str               # e.g. "key-value", "single-active", "evi-name"
    value_spec: str = ""    # e.g. "Integer into range 0..65535", "xx:xx:xx:xx:xx:xx"
    description: str = ""   # human description from the doc
    default: str | None = None  # extracted from value_spec or notes
    is_choice: bool = False     # True for enum members (e.g. "single-active")


@dataclass
class CliCommand:
    """A single CLI command parsed from the EVPN CLI doc."""
    name: str               # heading text, e.g. "lacp-key", "service-carving"
    kind: str               # "config" | "show" | "clear"
    syntax: str             # full CommandSyntax cell
    syntax_lines: list[str] = field(default_factory=list)  # split, stripped
    mode: str = ""          # full Command Mode cell
    mode_path: list[str] = field(default_factory=list)     # tokenized hierarchy
    # All alternative parent paths the Mode cell lists (the cell may name
    # several, e.g. `… interface agg-eth` AND `… interface x-eth`). The old
    # code kept only the first, so the second mode was silently dropped from
    # the action text (client 2026-06-02, Eyal Ozeri: "when the command mode
    # is more than one, the second is ignored"). `mode_path` stays the first
    # alternative for back-compat; `mode_paths` carries them all.
    mode_paths: list[list[str]] = field(default_factory=list)
    # A *pure container* node: its only syntax is the bare command name (no
    # value/argument) and it opens a sub-mode whose attributes are configured
    # beneath it. Such a node "cannot be committed" on its own (client
    # 2026-06-02, Eyal Ozeri: "ethernet-segment is a container. It cannot be
    # committed"). Set by `_mark_containers` once the full command set is known.
    is_container: bool = False
    container_attrs: list[str] = field(default_factory=list)  # child command names
    description: str = ""   # prose from the Description cell
    parameters: list[CliParameter] = field(default_factory=list)
    examples: str = ""      # raw example block
    notes: str = ""         # full Notes cell (constraints, defaults)
    has_no_form: bool = False  # supports `no <command>` to delete/restore
    default_behavior: str = ""  # extracted default phrase if mentioned in prose
    related_features: list[str] = field(default_factory=list)
    # heading text of the parent L2 section, e.g. "L2 Services Configuration Commands"
    section: str = ""

    @property
    def is_config(self) -> bool:
        return self.kind == "config"

    @property
    def base_command(self) -> str:
        """First token of syntax — the command's own name (without sub-args)."""
        if not self.syntax_lines:
            return self.name
        first = self.syntax_lines[0].strip()
        # Drop a leading "no " for the syntax fingerprint
        if first.lower().startswith("no "):
            first = first[3:]
        return first.split()[0] if first else self.name


# Default-extraction patterns. Order matters — earliest match wins per param.
_DEFAULT_PATTERNS = [
    # "(Default = all)" / "(default: 37237)" / "Default = brief"
    re.compile(r"\bdefault\s*[:=]\s*([^\.\n,)]+?)(?=[,\.\)\n]|$)", re.IGNORECASE),
    # "the default value is 37237"
    re.compile(r"the default value is ([^\.\n,]+)", re.IGNORECASE),
    # "restore the default configuration (the agg-eth interface number)"
    re.compile(r"restore the default configuration\s*\(([^)]+)\)", re.IGNORECASE),
    # "(single-active)" or "(default)" appended to a `no` description
    re.compile(r"use the no form[^\.]*?\(([^)]+)\)", re.IGNORECASE),
]


_RANGE_RE = re.compile(r"\brange\s+([0-9]+)\.\.([0-9]+)", re.IGNORECASE)
_INTEGER_RE = re.compile(r"integer", re.IGNORECASE)
_MAC_RE = re.compile(r"xx[:.]xx[:.]xx[:.]xx[:.]xx[:.]xx", re.IGNORECASE)
_OCTETS_RE = re.compile(r"(\d+)\s+octets?", re.IGNORECASE)


def _extract_default_from_text(text: str) -> str | None:
    """Look for an explicit default phrase in prose."""
    if not text:
        return None
    for pat in _DEFAULT_PATTERNS:
        m = pat.search(text)
        if m:
            d = m.group(1).strip().rstrip(".,")
            # Heuristic noise filter — discard obvious non-default text
            if len(d) > 60 or d.lower() in ("",):
                continue
            return d
    return None


def _is_command_table(table: Table) -> bool:
    """A command table starts with a row whose first cell is 'Description'."""
    if not table.rows:
        return False
    first = table.rows[0][0].text.strip().lower() if table.rows[0] else ""
    return first == "description"


def _classify_kind(name: str, syntax: str, mode: str) -> str:
    n = name.lower().strip()
    s = syntax.lower().strip()
    m = mode.lower().strip()
    # Operational / show / clear are clearly not config rows.
    if n.startswith(("show ", "clear ")) or s.startswith(("show ", "clear ")):
        return "show" if "show" in n or "show" in s else "clear"
    # Operational-only mode → not configuration
    if "operational" in m and "configuration" not in m:
        return "show"
    return "config"


def _row_label(row: list) -> str:
    return row[0].text.strip().lower() if row else ""


def _row_text(row: list, col: int = 1) -> str:
    if len(row) <= col:
        return ""
    return row[col].text


def _split_mode_all(mode_cell: str) -> list[list[str]]:
    """Every alternative parent path the Mode cell lists, each tokenized.

    The cell separates alternatives by newlines (e.g. `… interface agg-eth`
    on one line, `… interface x-eth` on the next). We keep them all so the
    row generator can name each mode instead of silently dropping the
    second (client 2026-06-02). Duplicate / `operational` lines are dropped.
    """
    out: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for line in mode_cell.splitlines():
        line = line.strip()
        if not line or line.lower() == "operational":
            continue
        toks = tuple(tok for tok in line.split() if tok)
        if toks and toks not in seen:
            seen.add(toks)
            out.append(list(toks))
    return out


def _split_mode(mode_cell: str) -> list[str]:
    """The first alternative parent path (back-compat). See `_split_mode_all`
    for the full list, which the row generator uses to name every mode."""
    alts = _split_mode_all(mode_cell)
    return alts[0] if alts else []


def _parse_parameters(rows: list[list], params_header_idx: int,
                      params_end_idx: int) -> list[CliParameter]:
    """Param rows live between the 'Parameters Table' header and the next
    labelled row (Examples or Notes). Each param row has the shape:

        ["", <name>, <value_spec>, <description>]

    For enum-style commands (load-balancing-mode, service-carving), the
    "name" column lists each enumerated choice as its own row, and the
    value_spec column is empty.
    """
    out: list[CliParameter] = []
    for r in rows[params_header_idx + 1: params_end_idx]:
        # row format: [empty/blank, name, value, description]
        name = _row_text(r, 1).strip()
        value_spec = _row_text(r, 2).strip()
        description = _row_text(r, 3).strip()
        if not name and not value_spec and not description:
            continue
        # Skip residual header rows
        if name.lower() in ("name",) and value_spec.lower() in ("value",):
            continue
        # A choice has empty value_spec but non-empty name (enum members)
        is_choice = bool(name) and not value_spec

        # Extract default: try value_spec first (sometimes "(Default = all)"
        # is appended there), then description.
        default = (_extract_default_from_text(value_spec)
                   or _extract_default_from_text(description))

        out.append(CliParameter(
            name=name,
            value_spec=value_spec,
            description=description,
            default=default,
            is_choice=is_choice,
        ))
    return out


def _related_features(name: str, mode: str, syntax: str, notes: str) -> list[str]:
    """Map a command back to the feature areas it touches.

    Used by row generators (CLI configuration rows, AI prompt context
    retrieval) to know that e.g. lacp-key relates to multi-homing/LACP,
    while service-carving relates to DF election + RFC8584.
    """
    blob = " ".join([name, mode, syntax, notes]).lower()
    feats: list[str] = []
    if "lacp" in blob:
        feats.append("LACP")
    if "ethernet-segment" in blob or "ethernet segment" in blob or "esi" in blob:
        feats.append("Ethernet Segment")
    if "service-carving" in blob or "df " in blob or "designated forwarder" in blob:
        feats.append("DF election")
    if "load-balancing" in blob or "all-active" in blob or "single-active" in blob:
        feats.append("multi-homing")
    if "service-type" in blob or "vlan-based" in blob or "vlan-aware" in blob \
            or "port-based" in blob or "vlan-bundle" in blob:
        feats.append("EVPN service types")
    if "auto-discovery" in blob or "import-rt" in blob or "export-rt" in blob:
        feats.append("BGP route-target")
    if "mac-limit" in blob or "mac mobility" in blob \
            or "mac-address-static" in blob or "mac-aging-time" in blob \
            or "duplication-detection" in blob or "duplicate-detection" in blob:
        feats.append("MAC table")
    if "control-word" in blob:
        feats.append("control-word")
    if "advertise-mac" in blob:
        feats.append("MAC advertisement")
    if "af-l2vpn" in blob or "evpn" in blob and "neighbor" in blob:
        feats.append("BGP EVPN address-family")
    if "interface" in blob and "evpn" in blob:
        feats.append("AC binding")
    if "es-waiting-time" in blob:
        feats.append("ES timers")
    if "unknown-mac-flooding" in blob:
        feats.append("BUM forwarding")
    if "evpn evpn-name" in syntax.lower() or name == "evpn":
        feats.append("EVPN instance")
    return sorted(set(feats))


def _parse_command_table(name: str, table: Table, parent_section: str
                         ) -> CliCommand | None:
    """Build a CliCommand from one Description/Syntax/Mode/... table.

    Returns None if the table doesn't look like a real command (no
    syntax row, or syntax cell is empty).
    """
    rows = table.rows

    description = ""
    syntax = ""
    mode = ""
    examples = ""
    notes = ""
    params_header_idx = -1
    params_end_idx = len(rows)

    for i, r in enumerate(rows):
        label = _row_label(r)
        if label == "description":
            description = _row_text(r, 1)
        elif label.startswith("commandsyntax") or label == "command syntax":
            syntax = _row_text(r, 1)
        elif label == "command mode":
            mode = _row_text(r, 1)
        elif label.startswith("parameters table"):
            params_header_idx = i
        elif label == "examples":
            examples = _row_text(r, 1)
            if params_header_idx >= 0 and params_end_idx == len(rows):
                params_end_idx = i
        elif label == "notes":
            notes = _row_text(r, 1)
            if params_header_idx >= 0 and params_end_idx == len(rows):
                params_end_idx = i

    if not syntax.strip():
        return None

    syntax_lines = [ln.strip() for ln in syntax.splitlines() if ln.strip()]
    has_no_form = any(ln.lower().startswith("no ") for ln in syntax_lines)

    parameters = (_parse_parameters(rows, params_header_idx, params_end_idx)
                  if params_header_idx >= 0 else [])

    # Default behavior — pull from Description, then Notes
    default_behavior = (_extract_default_from_text(description)
                        or _extract_default_from_text(notes)
                        or "")

    kind = _classify_kind(name, syntax, mode)

    return CliCommand(
        name=name,
        kind=kind,
        syntax=syntax,
        syntax_lines=syntax_lines,
        mode=mode,
        mode_path=_split_mode(mode),
        mode_paths=_split_mode_all(mode),
        description=description,
        parameters=parameters,
        examples=examples,
        notes=notes,
        has_no_form=has_no_form,
        default_behavior=default_behavior,
        related_features=_related_features(name, mode, syntax, notes),
        section=parent_section,
    )


def _is_bare_container_syntax(cmd: CliCommand) -> bool:
    """True when the command's only positive syntax is its bare name — i.e.
    it takes no value and merely opens a sub-mode (e.g. `ethernet-segment`,
    `af-l2vpn evpn`, `auto-discovery`). `evpn evpn-name …` and
    `interface if-name` are excluded — those carry an argument."""
    positive = [ln.strip() for ln in cmd.syntax_lines
                if not ln.lower().startswith("no ")]
    if not positive:
        return False
    return all(ln == cmd.name for ln in positive)


def mark_containers(commands: list[CliCommand]) -> list[CliCommand]:
    """Flag pure-container commands and record their child attribute names.

    A command is a container when (a) its only syntax is the bare command
    name (it takes no value of its own — so it "cannot be committed", client
    2026-06-02) AND (b) at least one other command is configured directly
    beneath it. "Beneath it" means the child's mode path ends with this
    command's name tokens, with the tokens before that equal to one of this
    command's own mode paths — so a multi-word container like `af-l2vpn evpn`
    matches children whose mode path ends `… af-l2vpn evpn`, and a bare BGP
    toggle (`route-reflector-client`) with no children is NOT a container.
    Operates in place and returns the list.
    """
    for c in commands:
        c.is_container = False
        c.container_attrs = []
        if not c.is_config or not _is_bare_container_syntax(c):
            continue
        ctoks = c.name.split()
        n = len(ctoks)
        parent_modes = c.mode_paths or ([c.mode_path] if c.mode_path else [])
        children: list[str] = []
        for d in commands:
            if d is c or not d.is_config or len(d.mode_path) <= n:
                continue
            if d.mode_path[-n:] != ctoks:
                continue
            prefix = d.mode_path[:-n]
            if parent_modes and prefix not in parent_modes:
                continue
            if d.name not in children:
                children.append(d.name)
        if children:
            c.is_container = True
            c.container_attrs = children
    return commands


def extract_commands(doc: Document | str | Path) -> list[CliCommand]:
    """Walk the parsed CLI document and return all command tables found.

    Each command is associated with the heading immediately preceding
    its table (commands live under L3 or L4 headings depending on doc
    section). The closest L2 heading is captured as the `section` so
    callers can group by Configuration vs. Operational vs. Show.
    """
    if not isinstance(doc, Document):
        doc = parse(doc)

    blocks = list(doc.blocks)
    out: list[CliCommand] = []

    for i, b in enumerate(blocks):
        if not isinstance(b, Table):
            continue
        if not _is_command_table(b):
            continue
        # Walk back for the nearest heading (L3/L4 = command name)
        cmd_name = ""
        section = ""
        for j in range(i - 1, -1, -1):
            blk = blocks[j]
            if isinstance(blk, Heading):
                if not cmd_name and blk.level >= 3:
                    cmd_name = blk.text.strip()
                if not section and blk.level == 2:
                    section = blk.text.strip()
                if cmd_name and section:
                    break
                if cmd_name and blk.level <= 2:
                    section = blk.text.strip()
                    break
        if not cmd_name:
            continue

        cmd = _parse_command_table(cmd_name, b, parent_section=section)
        if cmd is not None:
            out.append(cmd)

    mark_containers(out)
    return out


def config_commands(doc: Document | str | Path) -> list[CliCommand]:
    """Convenience: return only the configuration-mode commands.

    Used by `cli_rows.py` which generates the CLI configuration test
    section — show/clear commands belong under Tech-support / PM.
    """
    return [c for c in extract_commands(doc) if c.is_config]

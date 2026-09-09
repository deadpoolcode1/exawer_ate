"""Scoped ingest of Exaware's **Command Reference Guide v8.X.0** — the *base*
CLI manual — for the handful of BGP-neighbor sub-configs the EVPN CLI doc
references but does not document.

Why this module exists
----------------------
The EVPN CLI doc treats ``af-l2vpn evpn`` as a single command with no
parameters. The SFS (``EVPN System Specification 1.00``, §2.2 "BGP Common CLI
in Context L2VPN EVPN", EVPNS-REQ#20) then names eight knobs that the sub-mode
inherits from base BGP — and documents the grammar of none of them.

For three months ``cli_inheritance.py`` filled that gap by hand, from "standard
BGP convention". Every one of those entries was wrong in at least one element.
The Command Reference Guide is the document that closes it, so the grammar is
now *read*, not *reasoned to*:

============================== ===================================== =====================================
Knob                           Hand-curated (invented)               Command Reference Guide
============================== ===================================== =====================================
``allow-as-in``                ``allow-as-in [<count>]``             ``allow-as-in number``, 1-10
``capability``                 one flat option list                  **sub-mode scoped** — see below
``inbound-soft-reconfiguration`` bare command                        ``[enable | disable]``, default disable
``maximum-prefix``             ``<max> [<pct> [warning-only|…]]``    ``number max threshold percent action
                                                                     [warn | terminate]``, 2097152/75/warn
``policy``                     ``policy <name> {in | out}``          ``policy {in | out} policy-name``
                                                                     — **the operands are the other way round**
``private-as``                 ``{remove | replace}``                ``[remove | leave]``, default leave
``route-reflector-client``     bare command                          ``[enable | disable]``, default disable
``weight``                     *absent*                              ``weight weight-value``
============================== ===================================== =====================================

Two findings that are not just grammar, and that a human has to rule on:

* ``allow-as-in`` carries the Notes line *"This command is only available under
  unicast SAFI, VRF default, and VPN SAFI."* The SFS lists it as an
  ``af-l2vpn evpn`` knob. Those two documents disagree, and this module
  reports the disagreement rather than picking a winner — see
  :func:`safi_applicability`.
* ``capability``'s options depend on the sub-mode it is typed in: at the
  neighbor level ``dynamic`` / ``route-refresh``; at the address-family level
  ``graceful-restart`` / ``orf``. A single flat option list, which is what we
  had, is wrong at both levels.

Scope
-----
Deliberately narrow. The CRG is 1577 pages of full-platform CLI; ingesting it
whole would swamp the EVPN plan with commands nobody asked about. This module
extracts **only the sections named in** :data:`INHERITED_BGP_KNOBS`, and every
command it returns is tagged ``section="…(Command Reference Guide v8.X.0)"`` so
the provenance survives into the xlsx Comment column.

The base+extension model this implements is written up in ``docs/TDD.md`` §11.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ate.planner.cli_extractor import CliCommand, CliParameter

#: Provenance tag carried by every command this module produces.
CRG_PROVENANCE = "cli-base"

#: Human-readable source, reproduced into the plan's Comment column.
CRG_SOURCE = "Command Reference Guide v8.X.0"

#: The BGP-neighbor sub-configs EVPNS-REQ#20 says `af-l2vpn evpn` inherits.
#:
#: `group` is in the SFS list but has no `10.2.1.x` section of its own in the
#: CRG — it is the neighbor-group *binding*, not an address-family knob. It is
#: kept out of this table on purpose; :func:`missing_from_crg` reports it so
#: the gap is visible rather than silently dropped.
INHERITED_BGP_KNOBS: tuple[str, ...] = (
    "allow-as-in",
    "capability",
    "inbound-soft-reconfiguration",
    "maximum-prefix",
    "policy",
    "private-as",
    "route-reflector-client",
    "weight",
)

#: Named in EVPNS-REQ#20 but with no command section in the CRG.
NOT_IN_CRG: tuple[str, ...] = ("group",)

# The guide numbers every routing command `10.2.1.<n>. <name>`.
_HEADING = re.compile(r"^\s*(\d+(?:\.\d+)+)\.\s+(\S.*?)\s*$")

# Field labels down the left column of each command table. The label may wrap
# onto a second line ("Command\nSyntax", "Parameters\nTable"), so the
# continuation word is matched too and folded into the field above.
_FIELDS = ("Description", "Command Syntax", "Command Mode",
           "Parameters Table", "Examples", "Notes")
_FIELD_START = re.compile(
    r"^\s*(Description|Command|Parameters|Examples|Notes)\b\s*(.*)$")
_FIELD_CONT = re.compile(r"^\s*(Syntax|Mode|Table)\b\s*(.*)$")

# Page furniture that pdftotext interleaves into the body.
_FURNITURE = re.compile(
    r"^\s*(Routing Commands|Confidential Information|Page \d+|"
    r"Exaware\b.*|.*\bPage \d+\s*$)\s*$")


@dataclass(frozen=True)
class CrgSection:
    """One parsed `10.2.1.<n>` command section, before it becomes a command."""

    number: str
    name: str
    fields: dict[str, str]

    @property
    def notes(self) -> str:
        return self.fields.get("Notes", "")


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def crg_text(source: Path | str) -> str:
    """Return the guide's text layer.

    Accepts either the PDF (converted with ``pdftotext -layout``, which is what
    preserves the two-column label/value table shape this parser depends on) or
    an already-converted ``.txt``.
    """
    path = Path(source)
    if path.suffix.lower() == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")
    if shutil.which("pdftotext") is None:
        raise RuntimeError(
            "pdftotext is required to read the Command Reference Guide PDF "
            "(apt install poppler-utils), or pass a pre-converted .txt")
    out = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        check=True, capture_output=True)
    return out.stdout.decode("utf-8", errors="replace")


def _sections(text: str) -> list[CrgSection]:
    lines = text.splitlines()
    heads = [(i, m.group(1), m.group(2))
             for i, ln in enumerate(lines) if (m := _HEADING.match(ln))]
    sections: list[CrgSection] = []
    for n, (start, number, name) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        body = [ln for ln in lines[start + 1:end] if not _FURNITURE.match(ln)]
        sections.append(CrgSection(number, name, _split_fields(body)))
    return sections


def _split_fields(body: list[str]) -> dict[str, str]:
    """Split a section body into its Description/Syntax/Mode/… fields.

    The guide lays each section out as a two-column table whose left column
    holds the field label. `pdftotext -layout` renders that as the label at the
    start of the line and the value indented after it, with continuation lines
    carrying only the value. A label may itself wrap ("Command" / "Syntax" on
    consecutive lines), which is why `_FIELD_CONT` exists — without it every
    Command Syntax cell lost its first line.
    """
    fields: dict[str, list[str]] = {}
    current: str | None = None
    for ln in body:
        if not ln.strip():
            if current:
                fields[current].append("")
            continue
        m = _FIELD_START.match(ln)
        if m and _resolve_label(m.group(1), ln):
            current = _resolve_label(m.group(1), ln)
            fields.setdefault(current, [])
            if m.group(2).strip():
                fields[current].append(m.group(2))
            continue
        c = _FIELD_CONT.match(ln)
        if c and current in ("Command", "Parameters"):
            # The label wrapped: "Command" / "Syntax" on consecutive lines, and
            # the FIRST line of the value sits alongside the "Command" half.
            #
            # Getting this wrong silently truncated every syntax and mode cell
            # to its continuation lines: `allow-as-in` came back with only
            # `no allow-as-in`, and its `… neighbor afi safi` mode vanished.
            # So carry the buffered value across into the combined key rather
            # than starting a fresh one.
            carried = fields.pop(current, [])
            current = f"{current} {c.group(1)}"
            fields.setdefault(current, [])
            fields[current].extend(carried)
            if c.group(2).strip():
                fields[current].append(c.group(2))
            continue
        if current:
            fields[current].append(ln)
    return {k: _clean("\n".join(v)) for k, v in fields.items()}


def _resolve_label(word: str, line: str) -> str | None:
    """Map a leading label word onto one of `_FIELDS`."""
    if word in ("Description", "Examples", "Notes"):
        return word
    # "Command Syntax" / "Command Mode" / "Parameters Table" may appear on one
    # line when the layout did not wrap them.
    for field in _FIELDS:
        if line.strip().startswith(field):
            return field
    # A bare "Command" / "Parameters" — the qualifier is on the next line.
    return word if word in ("Command", "Parameters") else None


def _clean(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Section -> CliCommand
# ---------------------------------------------------------------------------

_SUBMODE_RE = re.compile(r"^configuration\s+.*$", re.MULTILINE)
_DEFAULT_RE = re.compile(r"\(?\s*Default\s*=\s*([^)\n]+?)\s*\)?\s*$",
                         re.IGNORECASE)

#: Sentinel for a bare "(Default)" marker, resolved to the row's own value.
_SELF_DEFAULT = "\x00self"


def _mode_paths(mode_cell: str) -> list[list[str]]:
    """Every alternative parent mode the Mode cell lists.

    The cell names several — `… neighbor afi safi` and `… neighbor-group afi
    safi`. `afi safi` is the generic placeholder the guide uses for "whichever
    address family you are in"; for our purposes that address family is
    `af-l2vpn evpn`, and the substitution happens in `cli_inheritance`, not
    here. This function stays faithful to the document.
    """
    paths = []
    for line in mode_cell.splitlines():
        line = line.strip()
        if not line.startswith("configuration"):
            continue
        toks = line.split()
        if toks not in paths:
            paths.append(toks)
    return paths


def _parameters(param_cell: str) -> list[CliParameter]:
    """Parse the Parameters Table into `CliParameter`s.

    The table is `Name | Value | Description`, laid out by column position, and
    a row's Description routinely wraps over several lines. Rather than guess
    at column offsets (which shift between sections because the guide's tables
    are not a fixed width), rows are recognised by the leading Name/Value
    tokens and everything else is treated as continuation of the description.

    An enum member has an empty Name and only a Value — `warn`, `terminate`,
    `remove`, `leave`. Those become `is_choice=True` parameters, which is what
    `cli_rows` needs to emit one row per alternative.
    """
    params: list[CliParameter] = []
    lines = [ln for ln in param_cell.splitlines() if ln.strip()]
    if lines and re.match(r"^\s*(Table\s+)?Name\b", lines[0]):
        lines = lines[1:]
    for ln in lines:
        if not ln.split():
            continue
        name, value, desc = _row_columns(ln)
        # Only treat the line as a NEW row when its lead-in really is a name or
        # a value spec. The first cut here keyed off indentation, which folded
        # every enum member after the first into its predecessor's description
        # ("Enable local storage… disable Disable local storage…") and so lost
        # `disable`, `leave` and `terminate` as testable alternatives.
        if not _starts_a_row(name, value) :
            if params:
                _append_description(params[-1], ln.strip())
            continue
        params.append(CliParameter(
            name=name or value,
            value_spec=value,
            description=desc,
            default=_default_of(desc),
            is_choice=not name and bool(value),
        ))
    for p in params:
        if p.default is None:
            p.default = _default_of(p.description)
        if p.default == _SELF_DEFAULT:
            # A bare "(Default)" in the guide marks *this* alternative as the
            # default one, so name it rather than leaking the marker.
            p.default = p.value_spec or p.name
        if p.is_choice and not _is_own_sentence(p.description):
            # A multi-line Value column (ORF's both/disable/receive/send) puts
            # its four alternatives beside ONE wrapped description, so the
            # 2nd..4th choices pick up whichever fragment landed on their line:
            # `disable` came out described as "either on transmission or
            # reception, or both". A wrong description in a client deliverable
            # is worse than none, and inventing a right one is not available to
            # us — so the fragment is dropped and the choice stands on its name.
            p.description = ""
    return params


def _is_own_sentence(text: str) -> bool:
    text = text.strip()
    return bool(text) and text[:1].isupper()


def _starts_a_row(name: str, value: str) -> bool:
    """Whether a parsed line opens a new parameter row rather than continuing one."""
    if name and _looks_like_token(name):
        return True
    return bool(value) and _is_value_spec(value)


def _looks_like_token(word: str) -> bool:
    return bool(re.fullmatch(r"[a-z][a-z0-9-]*", word))


def _row_columns(line: str) -> tuple[str, str, str]:
    """Split one Parameters-Table row into (name, value, description).

    Columns are separated by runs of two or more spaces, which survives
    `pdftotext -layout` reliably; single spaces inside a description do not.
    """
    cells = [c.strip() for c in re.split(r"\s{2,}", line.strip()) if c.strip()]
    if len(cells) >= 3:
        return cells[0], cells[1], " ".join(cells[2:])
    if len(cells) == 2:
        # Either name+value or value+description. A value spec looks like a
        # range or an enum member; a description is a sentence.
        if _is_value_spec(cells[1]):
            return cells[0], cells[1], ""
        return ("", cells[0], cells[1]) if _is_value_spec(cells[0]) \
            else (cells[0], "", cells[1])
    if len(cells) == 1:
        return ("", cells[0], "") if _is_value_spec(cells[0]) else ("", "", cells[0])
    return "", "", ""


def _is_value_spec(cell: str) -> bool:
    return bool(re.fullmatch(r"[\d\-\s]+|[a-z][a-z0-9-]*", cell))


def _append_description(param: CliParameter, extra: str) -> None:
    param.description = f"{param.description} {extra}".strip()
    if param.default is None:
        param.default = _default_of(param.description)


def _default_of(text: str) -> str | None:
    m = _DEFAULT_RE.search(text.strip())
    if m:
        return m.group(1).strip().rstrip(".")
    m = re.search(r"\(([^)]*\bdefault\b[^)]*)\)", text, re.IGNORECASE)
    if m:
        inner = m.group(1).strip()
        if re.fullmatch(r"(?i)default", inner):
            # "(Default)" marks the preceding value as the default one.
            return _SELF_DEFAULT
        return inner
    return None


def to_command(section: CrgSection) -> CliCommand:
    """Turn one parsed CRG section into a `CliCommand`.

    Everything here comes off the page. Nothing is inferred, and in particular
    no range, default or option is supplied when the guide omits it — that was
    the failure mode this module replaces.
    """
    syntax = section.fields.get("Command Syntax", "")
    syntax_lines = _join_wrapped_syntax(
        [ln.strip() for ln in syntax.splitlines() if ln.strip()], section.name)
    syntax = "\n".join(syntax_lines)
    mode_cell = section.fields.get("Command Mode", "")
    paths = _mode_paths(mode_cell)
    return CliCommand(
        name=section.name,
        kind="config",
        syntax=syntax,
        syntax_lines=syntax_lines,
        mode=mode_cell,
        mode_path=paths[0] if paths else [],
        mode_paths=paths,
        description=section.fields.get("Description", ""),
        parameters=_parameters(section.fields.get("Parameters Table", "")),
        examples=section.fields.get("Examples", ""),
        notes=section.notes,
        has_no_form=bool(re.search(r"^\s*no\s+" + re.escape(section.name),
                                   syntax, re.MULTILINE)),
        default_behavior=_default_behavior(section),
        related_features=["BGP EVPN address-family"],
        section=f"BGP neighbor sub-configs ({CRG_SOURCE} §{section.number})",
    )


def _join_wrapped_syntax(lines: list[str], name: str) -> list[str]:
    """Rejoin a syntax form the PDF column wrapped across two lines.

    The guide's Command Syntax cell is narrow, so a long form breaks mid-token:

        maximum-prefix number max threshold percent action [warn |
        terminate]

    Reading those as two forms produces ``action [warn |`` — a dangling
    alternation that `cli_rows` would render as a command with an empty
    operand. A line is a continuation when it does not begin a form of its own,
    i.e. it starts with neither the command name nor ``no <name>``.
    """
    out: list[str] = []
    for ln in lines:
        starts_form = ln.startswith(name) or ln.startswith(f"no {name}")
        if out and not starts_form:
            out[-1] = f"{out[-1].rstrip()} {ln.lstrip()}".replace("| |", "|")
        else:
            out.append(ln)
    return out


def _default_behavior(section: CrgSection) -> str:
    """The `no`-form's stated effect, quoted from the Description cell."""
    desc = section.fields.get("Description", "")
    m = re.search(r"Use the no form of the command to ([^.]+)\.", desc)
    return f"no {section.name} — {m.group(1).strip()}" if m else ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

#: Section number prefix of the BGP command chapter.
#:
#: Scoping is not an optimisation, it is a correctness requirement: the guide
#: covers the whole platform, and several of these names exist more than once.
#: `policy` is a BGP neighbor knob at §10.2.1.54 **and** a QoS attachment
#: (`policy {in | out | out-port-pcp-marking} policy-name`) elsewhere; an
#: unscoped search picked the QoS one and would have put its grammar into the
#: EVPN test plan. `weight` collides the same way.
BGP_SECTION_PREFIX = "10.2.1."


def extract(source: Path | str,
            names: tuple[str, ...] = INHERITED_BGP_KNOBS,
            section_prefix: str = BGP_SECTION_PREFIX,
            ) -> dict[str, CliCommand]:
    """Extract the named command sections from the Command Reference Guide.

    Returns a name -> command mapping. A name the guide does not document is
    simply absent; callers report that rather than substituting a guess.
    """
    wanted = set(names)
    found: dict[str, CliCommand] = {}
    for section in _sections(crg_text(source)):
        if section.name not in wanted or section.name in found:
            continue
        if not section.number.startswith(section_prefix):
            continue
        if "Command Syntax" not in section.fields:
            continue
        found[section.name] = to_command(section)
    return found


def missing_from_crg(found: dict[str, CliCommand],
                     names: tuple[str, ...] = INHERITED_BGP_KNOBS
                     ) -> list[str]:
    """Knobs EVPNS-REQ#20 names that the base guide does not document."""
    return [n for n in (*names, *NOT_IN_CRG) if n not in found]


# A knob whose Notes cell restricts it to particular SAFIs is a *sourced*
# question about EVPN applicability, not a fact either way: the SFS says the
# EVPN address family inherits it, the base guide says the command is only
# available elsewhere. Both are Exaware documents.
_SAFI_NOTE = re.compile(
    r"only available under\s+(?P<safis>[^.]+?)\s*\.", re.IGNORECASE)


def safi_applicability(command: CliCommand) -> str | None:
    """The SAFI restriction the guide states, if it states one.

    ``allow-as-in`` is the live case: *"This command is only available under
    unicast SAFI, VRF default, and VPN SAFI."* — which does not include
    ``l2vpn evpn``, while EVPNS-REQ#20 lists the knob as inherited by
    ``af-l2vpn evpn``.

    Returning the sentence rather than a boolean is deliberate. The plan row
    carries the conflict to QA in the document's own words; nobody downstream
    gets to resolve it by inference.
    """
    m = _SAFI_NOTE.search(command.notes or "")
    return m.group("safis").strip() if m else None


def evpn_conflicts(found: dict[str, CliCommand]) -> dict[str, str]:
    """Knobs the base guide scopes to SAFIs that exclude ``l2vpn evpn``."""
    out: dict[str, str] = {}
    for name, cmd in found.items():
        restriction = safi_applicability(cmd)
        if restriction and not re.search(r"\bevpn\b|\bl2vpn\b", restriction,
                                         re.IGNORECASE):
            out[name] = restriction
    return out

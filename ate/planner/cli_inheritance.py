"""BGP-neighbor sub-configs that ``af-l2vpn evpn`` inherits, read from the
base CLI manual.

The EVPN CLI doc treats ``af-l2vpn evpn`` as a single command with no
parameters. The SFS (``EVPN System Specification 1.00`` §2.2, "BGP Common CLI
in Context L2VPN EVPN", **EVPNS-REQ#20**) then names the knobs the sub-mode
inherits from base BGP, and documents the grammar of none of them. Client
review (2026-05-14, Eyal Ozeri) required those knobs in the test plan anyway.

**base + extension.** The Command Reference Guide v8.X.0 is the *base* — it
owns the grammar, ranges, defaults and command modes of the generic BGP
knobs. The EVPN CLI doc and the SFS are the *extension* — they own which
knobs the ``af-l2vpn evpn`` sub-mode pulls in, and the EVPN-specific commands.
This module is the join, and it reads both rather than reasoning about either.

What changed, and why it matters
--------------------------------
For three months this file hand-curated the knobs "from standard BGP
convention (RFC 4271/4760) and common vendor practice". Eyal flagged the
result as invented on 2026-07-06, and he was right: cross-checked against the
guide, **every one of the seven entries had at least one fabricated element**.
The worst were not the missing ranges but the confidently wrong ones —
``private-as {remove | replace}`` (the guide says ``remove | leave``) and
``policy <policy-name> {in | out}`` (the guide has the operands the other way
round). A reviewer cannot tell an invented default from a read one, which is
exactly why the table had to stop being hand-written.

Nothing here is now written by us. :mod:`ate.planner.crg_extractor` reads the
sections off the guide; this module only re-homes them into the EVPN sub-mode
and records the one conflict the two documents genuinely have.

The ``allow-as-in`` conflict
----------------------------
The guide's Notes cell for ``allow-as-in`` reads *"This command is only
available under unicast SAFI, VRF default, and VPN SAFI."* — which does not
include ``l2vpn evpn``. EVPNS-REQ#20 lists it as an ``af-l2vpn evpn`` knob.
Two Exaware documents, flatly disagreeing.

We do not resolve it. The row is emitted with the conflict stated in the
Comment column so QA types the command on a device and settles it, which is
the only thing that can. See :data:`SAFI_CONFLICT_NOTE`.
"""
from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ate.planner import crg_extractor
from ate.planner.cli_extractor import CliCommand

log = logging.getLogger(__name__)


@dataclass
class InheritanceEntry:
    """One parent command in the EVPN CLI whose sub-mode commands come
    from a different doc."""
    parent_command: str          # e.g. "af-l2vpn evpn"
    parent_mode_path: list[str]  # e.g. ["configuration","routing","bgp","vrf","neighbor"]
    source: str                  # human-readable provenance
    sub_configs: list[CliCommand] = field(default_factory=list)


#: The address-family sub-mode the inherited knobs are re-homed into.
#:
#: The guide states each knob's mode as ``… neighbor afi safi``, where
#: ``afi safi`` is its placeholder for whichever address family you are in.
#: For this plan that family is ``af-l2vpn evpn``, so the placeholder is
#: substituted — token-aligned with the parent's own mode path so that
#: `cli_rows`' mode-path sort puts ``af-l2vpn evpn`` *before* its children.
#: Using ``<asn>``/``<vrf>`` placeholders here sorted the children first
#: (``<`` sorts before ``v``), which surfaced the SAFI options above the
#: ``af-l2vpn evpn`` row (client 2026-06-02, Eyal Ozeri: "the safi options
#: appear before the af-l2vpn evpn").
_BGP_NEIGHBOR_AF_MODE_PATH = [
    "configuration", "routing", "bgp", "vrf", "neighbor", "af-l2vpn", "evpn",
]
_BGP_NEIGHBOR_AF_MODE = " ".join(_BGP_NEIGHBOR_AF_MODE_PATH)

#: Where the guide lives. Overridable so a caller with a different checkout
#: layout, or a pre-converted `.txt`, can point at it.
DEFAULT_CRG_PATH = Path("references/EVPN/Command Reference Guide v8.X.0.pdf")

#: Provenance sentence carried into the plan's Comment column.
CRG_SOURCE = (
    f"Base BGP grammar read from Exaware's {crg_extractor.CRG_SOURCE}; "
    "inherited into the af-l2vpn evpn sub-mode per SFS EVPNS-REQ#20."
)

#: Attached to a knob the base guide scopes to SAFIs that exclude EVPN.
SAFI_CONFLICT_NOTE = (
    "DOCUMENT CONFLICT — confirm on a device. SFS EVPNS-REQ#20 lists this "
    "knob as inherited by `af-l2vpn evpn`, but {source} states the command is "
    "only available under {safis}, which does not include l2vpn evpn. This "
    "row is emitted because the SFS asks for it; the expectation is that the "
    "device either accepts it under the EVPN address family or rejects it, "
    "and QA records which."
)

#: Knobs EVPNS-REQ#20 names that the base guide has no command section for.
#:
#: Reported, never filled in. `group` is the neighbor-group binding rather
#: than an address-family knob, so its absence from the BGP command chapter is
#: expected — but it is stated here rather than left as a silent gap, because
#: a silent gap is indistinguishable from an oversight.
UNDOCUMENTED_NOTE = (
    "Named by SFS EVPNS-REQ#20 but has no command section in "
    f"{crg_extractor.CRG_SOURCE}; no grammar is asserted for it here."
)


def _rehome(cmd: CliCommand, conflict: str | None) -> CliCommand:
    """Re-home a base-BGP command into the ``af-l2vpn evpn`` sub-mode.

    The grammar, parameters, ranges, defaults and `no` form are carried
    through untouched — they are the guide's, not ours. Only the mode path is
    rewritten, and only because the guide states it generically.
    """
    notes = cmd.notes or ""
    if conflict:
        notes = (notes + " " if notes else "") + SAFI_CONFLICT_NOTE.format(
            source=crg_extractor.CRG_SOURCE,
            safis=" ".join(conflict.split()),
        )
    return CliCommand(
        name=cmd.name,
        kind=cmd.kind,
        syntax=cmd.syntax,
        syntax_lines=list(cmd.syntax_lines),
        mode=_BGP_NEIGHBOR_AF_MODE,
        mode_path=list(_BGP_NEIGHBOR_AF_MODE_PATH),
        mode_paths=[list(_BGP_NEIGHBOR_AF_MODE_PATH)],
        description=cmd.description,
        parameters=list(cmd.parameters),
        examples=cmd.examples,
        notes=notes,
        has_no_form=cmd.has_no_form,
        default_behavior=cmd.default_behavior,
        # Names the knob itself rather than a generic "BGP EVPN
        # address-family" for all eight. The read-back expectation is
        # rendered from this, so a constant made all eight rows say the same
        # uninformative thing. The hand-curated table used to put a nicer
        # phrase here ("BGP AS_PATH loop check") — but that phrase was
        # written by us, not read from a document, and this is the same
        # class of invention the module exists to remove.
        related_features=[f"`{cmd.name}` under af-l2vpn evpn"],
        section=cmd.section,
    )


@functools.lru_cache(maxsize=4)
def _load(crg_path: str) -> tuple[CliCommand, ...]:
    """Read and re-home the inherited knobs. Cached — the PDF costs ~3 s."""
    path = Path(crg_path)
    if not path.exists():
        # Emitting nothing is the correct failure. The alternative — falling
        # back to a hand-written table — is what produced three months of
        # invented grammar, so there is deliberately no fallback.
        log.warning(
            "Command Reference Guide not found at %s — the af-l2vpn evpn "
            "sub-config rows will be omitted rather than invented.", path)
        return ()
    found = crg_extractor.extract(path)
    conflicts = crg_extractor.evpn_conflicts(found)
    missing = crg_extractor.missing_from_crg(found)
    if missing:
        log.info("EVPNS-REQ#20 knobs absent from the base guide: %s",
                 ", ".join(missing))
    return tuple(
        _rehome(found[name], conflicts.get(name))
        for name in crg_extractor.INHERITED_BGP_KNOBS
        if name in found
    )


def inherited_commands(crg_path: Path | str = DEFAULT_CRG_PATH
                       ) -> list[CliCommand]:
    """The ``af-l2vpn evpn`` sub-configs, as the base guide documents them."""
    return list(_load(str(crg_path)))


def _entry(crg_path: Path | str = DEFAULT_CRG_PATH) -> InheritanceEntry:
    return InheritanceEntry(
        parent_command="af-l2vpn evpn",
        parent_mode_path=["configuration", "routing", "bgp", "vrf", "neighbor"],
        source=CRG_SOURCE,
        sub_configs=inherited_commands(crg_path),
    )


class _TableProxy(list):
    """``INHERITANCE_TABLE`` as a lazily-populated list.

    Kept a module-level name because `cli_rows`, `xlsx_writer` and the tests
    all read it that way, but the guide is not parsed until something actually
    asks — importing this module used to be free and should stay that way.
    """

    def _ensure(self) -> None:
        if not list.__len__(self):
            entry = _entry()
            if entry.sub_configs:
                self.append(entry)

    def __iter__(self):
        self._ensure()
        return list.__iter__(self)

    def __len__(self):
        self._ensure()
        return list.__len__(self)

    def __getitem__(self, item):
        self._ensure()
        return list.__getitem__(self, item)

    def __bool__(self):
        self._ensure()
        return list.__len__(self) > 0


INHERITANCE_TABLE: list[InheritanceEntry] = _TableProxy()


def expand(extracted: list[CliCommand]) -> list[CliCommand]:
    """Produce inherited sub-config commands for parents present in `extracted`.

    For each entry in `INHERITANCE_TABLE` whose ``parent_command`` appears
    among the extracted commands, the entry's sub-configs are appended —
    skipping any whose name is already there, so the step is idempotent and
    stays safe if the EVPN CLI doc ever documents one of them itself.

    There is no longer a de-invention step after this. ``deinvent()`` existed
    to strip fabricated grammar before the deliverable was built; with the
    grammar now read off the base guide there is nothing to strip, and
    stripping it would throw away the ranges and defaults Eyal asked to have
    restored (2026-07-07: "removed, not corrected").
    """
    extracted_names = {c.name for c in extracted}
    out: list[CliCommand] = []
    for entry in INHERITANCE_TABLE:
        if entry.parent_command not in extracted_names:
            continue
        for sub in entry.sub_configs:
            if sub.name in extracted_names:
                continue
            out.append(sub)
            extracted_names.add(sub.name)
    return out


def sub_config_names_for(parent_command: str) -> list[str]:
    """Names of the sub-configs available under `parent_command`'s sub-mode.

    Used by cli_rows to emit an "available options under the evpn SAFI"
    enumeration row (client 2026-06-01, item 17) so QA can verify `?` under
    `af-l2vpn evpn` lists exactly the inherited option set.
    """
    for entry in INHERITANCE_TABLE:
        if entry.parent_command == parent_command:
            return [s.name for s in entry.sub_configs]
    return []


def af_enable_parents() -> set[str]:
    """Parent commands whose bare form IS committable on its own.

    ``af-l2vpn evpn`` enables the address family by itself; its child knobs
    are optional. That distinguishes it from a *structural* container such as
    ``ethernet-segment`` or ``auto-discovery``, which cannot be committed
    empty. Eyal Ozeri, 2026-07-07 (annotation [13], row 203): the AF enable is
    committable standalone, and FLOW-015 agrees.
    """
    return {entry.parent_command for entry in INHERITANCE_TABLE}


def inheritance_source_for(name: str) -> str | None:
    """The provenance string for a sub-config name, or None if unknown.

    Used by xlsx_writer's "Synthesized — Review" sheet.
    """
    for entry in INHERITANCE_TABLE:
        for sub in entry.sub_configs:
            if sub.name == name:
                return entry.source
    return None


def document_conflicts(crg_path: Path | str = DEFAULT_CRG_PATH
                       ) -> dict[str, str]:
    """Knobs the SFS and the base guide disagree about.

    Surfaced by the CLI so a respin states the conflict out loud rather than
    burying it in one Comment cell.
    """
    found = crg_extractor.extract(Path(crg_path)) \
        if Path(crg_path).exists() else {}
    return crg_extractor.evpn_conflicts(found)


def undocumented_knobs(crg_path: Path | str = DEFAULT_CRG_PATH) -> list[str]:
    """EVPNS-REQ#20 knobs with no command section in the base guide."""
    found = crg_extractor.extract(Path(crg_path)) \
        if Path(crg_path).exists() else {}
    return crg_extractor.missing_from_crg(found)

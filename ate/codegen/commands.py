"""EVPN command registry for generated Java — grounded in the CLI doc.

`cmp.tests.common.Commands` is Exaware's shared enum of CLI templates
(1220 lines) and it contains **zero EVPN entries** — only VPLS / VPWS /
xconnect under `l2-services`. The generated suite needs its own.

Two decisions worth stating:

1. **A separate `EvpnCommands` enum, not additions to `Commands`.**
   `CmpRouter.configAndValidate` and every `runCommandAndSwitch*` overload take
   the `ICmpCliCmd` *interface*, so a standalone enum is a drop-in. Appending
   to the shared 1220-line file would be a merge conflict against every other
   branch for no benefit.

2. **Every entry declares the CLI-doc command it comes from**, and
   `validate_grounding()` refuses to emit if that command is absent from the
   extracted catalog. This is `cli_crosscheck.py`'s posture carried into code
   generation: the plan already guarantees it asserts no non-existent command,
   and generated Java must clear the same bar.

Where the CLI doc's own syntax looks like a typo (`unknow-mac-flooding`,
`Advertise-mac`), the entry is flagged `doc_suspect` rather than silently
"corrected" — a guessed spelling fails at run time on the DUT and is exactly
the class of error this project has been burned by.
"""
from __future__ import annotations

from dataclasses import dataclass

from ate.planner.cli_extractor import CliCommand

#: JSystem `SessionMode` constant names, mirrored so the emitter can render
#: them without importing anything Java-side.
CLI = "SessionMode.CLI"
CLI_CONFIGURE = "SessionMode.CLI_CONFIGURE"


@dataclass(frozen=True)
class EvpnCommand:
    """One entry of the generated `EvpnCommands` enum."""

    key: str            # enum constant, e.g. "SHOW_EVPN_GLOBAL_NAME_$"
    template: str = ""  # printf template, e.g. "show evpn global name %s"
    mode: str = CLI
    #: Heading of the CLI-doc command this derives from. Checked against the
    #: extracted catalog by `validate_grounding`.
    source: str = ""
    #: Documented syntax line, carried into a Javadoc comment so a reviewer can
    #: see what the template was derived from without opening the CLI doc.
    doc_syntax: str = ""
    #: True when the documented syntax looks like a doc typo. Emitted with a
    #: visible warning comment instead of a silent fix.
    doc_suspect: str = ""


EVPN_COMMANDS: list[EvpnCommand] = [
    # ── service configuration ────────────────────────────────────────────
    EvpnCommand(
        key="CONFIGURE_L2_SERVICES_EVPN_$_SERVICE_TYPE_$",
        template="l2-services evpn %s service-type %s",
        mode=CLI_CONFIGURE,
        source="evpn",
        doc_syntax=("evpn evpn-name [service-type {vlan-based | vlan-bundle | "
                    "vlan-aware-bundle | port-based}]"),
    ),
    EvpnCommand(
        key="CONFIGURE_NO_L2_SERVICES_EVPN_$",
        template="no l2-services evpn %s",
        mode=CLI_CONFIGURE,
        source="evpn",
        doc_syntax="no evpn",
    ),
    EvpnCommand(
        key="CONFIGURE_L2_SERVICES_EVPN_$_AUTO_DISCOVERY",
        template="l2-services evpn %s auto-discovery",
        mode=CLI_CONFIGURE,
        source="auto-discovery",
        doc_syntax="auto-discovery",
    ),
    # DEVICE-VERIFIED 2026-08-11: `l2-services evpn <name> ?` offers only
    # auto-discovery / interface / mac-aging-time / mac-limit / service-type,
    # and import-rt/export-rt sit one level down under auto-discovery.
    EvpnCommand(
        key="CONFIGURE_L2_SERVICES_EVPN_$_IMPORT_RT_$",
        template="l2-services evpn %s auto-discovery import-rt %s",
        mode=CLI_CONFIGURE,
        source="import-rt",
        doc_syntax="import-rt route-target",
    ),
    EvpnCommand(
        key="CONFIGURE_L2_SERVICES_EVPN_$_EXPORT_RT_$",
        template="l2-services evpn %s auto-discovery export-rt %s",
        mode=CLI_CONFIGURE,
        source="export-rt",
        doc_syntax="export-rt route-target",
    ),
    EvpnCommand(
        key="CONFIGURE_L2_SERVICES_EVPN_$_INTERFACE_$",
        template="l2-services evpn %s interface %s",
        mode=CLI_CONFIGURE,
        source="interface (VPLS/EVPN)",
        doc_syntax="interface if-name",
    ),
    EvpnCommand(
        key="CONFIGURE_L2_SERVICES_EVPN_$_MAC_AGING_TIME_$",
        template="l2-services evpn %s mac-aging-time %s",
        mode=CLI_CONFIGURE,
        source="mac-aging-time",
        doc_syntax="mac-aging-time seconds",
    ),
    EvpnCommand(
        key="CONFIGURE_NO_L2_SERVICES_EVPN_$_MAC_AGING_TIME",
        template="no l2-services evpn %s mac-aging-time",
        mode=CLI_CONFIGURE,
        source="mac-aging-time",
        doc_syntax="no mac-aging-time",
    ),
    EvpnCommand(
        key="CONFIGURE_L2_SERVICES_EVPN_$_UNKNOWN_MAC_FLOODING_$",
        template="l2-services evpn %s unknow-mac-flooding %s",
        mode=CLI_CONFIGURE,
        source="unknown-mac-flooding",
        doc_syntax="unknow-mac-flooding enable | disable",
        doc_suspect=("CLI doc spells this 'unknow-mac-flooding' (missing 'n') "
                     "in the syntax AND in both parameter descriptions, while "
                     "the heading says 'unknown-mac-flooding'. Consistent "
                     "misspelling usually means the product itself has it, so "
                     "the template follows the SYNTAX verbatim. Not exercised "
                     "by any current step, so it blocks nothing; confirm "
                     "before a step starts using it."),
    ),

    # ── EVPN show / clear ────────────────────────────────────────────────
    EvpnCommand(
        key="SHOW_EVPN_SUMMARY",
        template="show evpn summary",
        source="show evpn global",
        doc_syntax="show evpn global [name evpn-name]",
    ),
    EvpnCommand(
        key="SHOW_EVPN_DETAIL",
        template="show evpn detail",
        source="show evpn global",
        doc_syntax="show evpn global [name evpn-name]",
    ),
    EvpnCommand(
        key="SHOW_EVPN_SUMMARY_NAME_$",
        template="show evpn summary name %s",
        source="show evpn summary",
        doc_syntax="show evpn summary [name evpn-name]",
    ),
    # DEVICE-VERIFIED 2026-08-11/12 against exa-il01-ec-3021 running 8.7.0 LAB 22.
    #
    # The product uses BOTH spellings, for different commands:
    #     show  evpn mac-address-table   (hyphen)   `show evpn ?`
    #     clear evpn mac address-table   (space)    `clear evpn ?` -> mac
    #                                               -> address-table
    # So the CLI doc was never self-contradictory - the two commands genuinely
    # differ, and each cell was right about its own command. We were wrong
    # twice: first by "resolving" the show form to the space, then by
    # propagating that fix onto the clear form, which had been correct all
    # along. Both are now taken from the device.
    #
    # We previously resolved this in favour of the SPACE form, reasoning from
    # three documents: the `clear` syntax in the same CLI doc, the VPLS family
    # in the Command Reference Guide, and Exaware's own production `Commands`
    # enum. That reasoning was sound and it was WRONG. The device answers
    #     show evpn mac address-table  ->  syntax error: unknown argument
    # and `show evpn ?` lists `mac-address-table`. The CLI doc's SYNTAX cell,
    # the outlier we overrode, was right.
    #
    # Keep this as the standing example of why device output outranks any
    # number of agreeing documents.
    EvpnCommand(
        key="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$",
        template="show evpn mac-address-table name %s",
        source="show evpn mac address-table",
        doc_syntax=("show evpn mac-address-table [name evpn-name "
                    "[source interface | mac mac-address]]"),
    ),
    EvpnCommand(
        key="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$_SOURCE_$",
        template="show evpn mac-address-table name %s source %s",
        source="show evpn mac address-table",
        doc_syntax=("show evpn mac-address-table [name evpn-name "
                    "[source interface | mac mac-address]]"),
    ),
    # DEVICE-VERIFIED: `show evpn bum routing-table` does NOT exist on LAB 22
    # (`show evpn ?` offers broadcast-domains / detail / mac-address-table /
    # summary). `show evpn broadcast-domains` is the command that carries the
    # BUM information — with an EVI configured it prints "Local BUM Label" —
    # so the BUM assertion binds to that instead of to a documented command
    # the product does not have.
    EvpnCommand(
        key="SHOW_EVPN_BROADCAST_DOMAINS_NAME_$",
        template="show evpn broadcast-domains name %s",
        source="show evpn broadcast-domains",
        doc_syntax="show evpn broadcast-domains [name evpn-name [vlan-id vlan-id]]",
    ),
    EvpnCommand(
        key="SHOW_EVPN_DETAIL_NAME_$",
        template="show evpn detail name %s",
        source="show evpn global",
        doc_syntax="show evpn detail [name evpn-name]  (device: `show evpn detail ?` -> name)",
    ),
    EvpnCommand(
        key="CLEAR_EVPN_MAC_ADDRESS_TABLE_NAME_$",
        template="clear evpn mac address-table name %s",
        source="clear evpn mac address-table",
        doc_syntax=("clear evpn mac address-table [name evpn-name "
                    "[source interface | mac mac-address]]"),
    ),

    # ── BGP EVPN tables ──────────────────────────────────────────────────
    # DEVICE-VERIFIED: `show bgp l2vpn evpn table evi evi-name <name>` answers
    # "syntax error: incomplete path" even with the EVI configured — the
    # evi-name completion is populated from EVIs that already have BGP EVPN
    # table entries, and on a rig with no peer there are none. The bare
    # `detail` form works and is the right one here anyway: the assertion is
    # that the PE ORIGINATED the route into its local EVI table.
    EvpnCommand(
        key="SHOW_BGP_L2VPN_EVPN_TABLE_EVI_DETAIL",
        template="show bgp l2vpn evpn table evi detail",
        source="show bgp l2vpn evpn table evi",
        doc_syntax=("show bgp l2vpn evpn table evi [evi-name evi-name "
                    "[evpn-prefix]] [brief | detail]"),
    ),
    EvpnCommand(
        key="SHOW_BGP_L2VPN_EVPN_NEIGHBORS_ADVERTISED_ROUTES_$_DETAIL",
        template="show bgp l2vpn evpn neighbors advertised-routes %s detail",
        source="show bgp l2vpn evpn neighbors advertised/received routes",
        doc_syntax=("show bgp l2vpn evpn neighbors {advertised-routes | "
                    "received-routes} [neighbor-ip [evpn-prefix]] "
                    "[brief | detail]"),
    ),
]


#: Entries derived from the CLI doc at generation time by `command_deriver`.
#: Kept separate from the curated list above so the curated 18 stay
#: authoritative and reviewable: they encode decisions the document alone
#: cannot settle, chiefly that `show evpn mac address-table` takes a space
#: where one CLI-doc syntax line uses a hyphen.
DERIVED_COMMANDS: list[EvpnCommand] = []


def set_derived_commands(commands: list[EvpnCommand]) -> None:
    """Install the derived entries. Replaces any previous derivation."""
    DERIVED_COMMANDS[:] = list(commands)


def all_commands() -> list[EvpnCommand]:
    """Curated entries first, then derived ones."""
    return list(EVPN_COMMANDS) + list(DERIVED_COMMANDS)


class UngroundedCommandError(RuntimeError):
    """Raised when a registry entry names a CLI command the catalog lacks."""


def validate_grounding(cli_commands: list[CliCommand]) -> list[str]:
    """Assert every registry entry traces to an extracted CLI-doc command.

    Returns the list of `doc_suspect` warnings so the caller can surface them;
    raises `UngroundedCommandError` if any entry is ungrounded, because an
    ungrounded command in generated code is the same defect class the plan's
    command cross-check was built to eliminate.
    """
    known = {c.name for c in cli_commands}
    missing = sorted({c.source for c in all_commands()
                      if c.source and c.source not in known})
    if missing:
        raise UngroundedCommandError(
            "EvpnCommands entries reference CLI commands absent from the "
            f"extracted catalog: {missing}"
        )
    return [f"{c.key}: {c.doc_suspect}" for c in all_commands() if c.doc_suspect]


def command_keys() -> set[str]:
    return {c.key for c in all_commands()}

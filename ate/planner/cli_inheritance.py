"""Protocol-inheritance table for CLI sub-modes the EVPN CLI doc references
but does not document.

Background: the EVPN CLI doc treats `af-l2vpn evpn` as a single command
with no parameters. In reality `af-l2vpn evpn` opens a BGP-neighbor
sub-mode whose 7 sub-configs (allow-as-in, capability,
inbound-soft-reconfiguration, maximum-prefix, policy, private-as,
route-reflector-client) are documented in Exaware's BGP CLI manual —
which we do not currently have. Client review (2026-05-14, Eyal Ozeri)
flagged that those 7 sub-configs must appear in the test plan even though
the EVPN doc is silent on them, because they are inherited from the
parent BGP protocol per RFC 4271/4760 conventions.

This module hand-curates the 7 sub-configs as `CliCommand` objects so
the existing `cli_rows.cli_command_rows()` row generator produces the
same family (happy-path / range / mutex / default / `no` / persistence /
help / filter / precondition) without any changes to `cli_rows.py`.

Future work: once the Exaware BGP CLI manual is available, run
`extract_commands(bgp_cli_doc)` and replace these hand-curated entries
with the real ones. `expand()` is idempotent on name — if the BGP doc
extraction already produced the command, the inheritance entry is
skipped.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ate.planner.cli_extractor import CliCommand, CliParameter


@dataclass
class InheritanceEntry:
    """One parent command in the EVPN CLI whose sub-mode commands come
    from a different doc."""
    parent_command: str          # e.g. "af-l2vpn evpn"
    parent_mode_path: list[str]  # e.g. ["configuration","routing","bgp","vrf","neighbor"]
    source: str                  # human-readable provenance
    sub_configs: list[CliCommand] = field(default_factory=list)


# Hand-curated until the Exaware BGP CLI doc lands. Syntax, ranges, and
# defaults follow standard BGP convention (RFC 4271 / RFC 4760 / RFC 7432)
# and common vendor (Cisco IOS-XR, FRR) practice. QA should validate each
# row against the actual device behaviour and edit the table in place when
# the real doc is available.
_BGP_NEIGHBOR_AF_MODE = (
    "configuration routing bgp <asn> vrf <vrf> neighbor <neighbor-ip> "
    "af-l2vpn evpn"
)
_BGP_NEIGHBOR_AF_MODE_PATH = [
    "configuration", "routing", "bgp", "<asn>", "vrf", "<vrf>",
    "neighbor", "<neighbor-ip>", "af-l2vpn", "evpn",
]


def _sub(name: str, syntax: str, description: str,
         parameters: list[CliParameter] | None = None,
         default_behavior: str = "",
         has_no_form: bool = True,
         notes: str = "",
         related_features: list[str] | None = None) -> CliCommand:
    """Helper — produce a CliCommand for a BGP-neighbor sub-config."""
    syntax_lines = [ln.strip() for ln in syntax.splitlines() if ln.strip()]
    return CliCommand(
        name=name,
        kind="config",
        syntax=syntax,
        syntax_lines=syntax_lines,
        mode=_BGP_NEIGHBOR_AF_MODE,
        mode_path=_BGP_NEIGHBOR_AF_MODE_PATH,
        description=description,
        parameters=parameters or [],
        examples="",
        notes=notes,
        has_no_form=has_no_form,
        default_behavior=default_behavior,
        related_features=related_features or ["BGP EVPN address-family"],
        section="BGP EVPN address-family sub-configs (inherited from BGP CLI)",
    )


BGP_NEIGHBOR_AF_L2VPN_EVPN = InheritanceEntry(
    parent_command="af-l2vpn evpn",
    parent_mode_path=["configuration", "routing", "bgp", "vrf", "neighbor"],
    source=(
        "Hand-curated from standard BGP behaviour (RFC 4271/4760/7432) and "
        "common vendor convention; replace when Exaware's BGP CLI manual lands."
    ),
    sub_configs=[
        _sub(
            name="allow-as-in",
            syntax="allow-as-in [<count>]\nno allow-as-in",
            description=(
                "Accept up to <count> occurrences of the local AS in the "
                "received AS_PATH. Standard BGP AS_PATH loop check is "
                "bypassed for the configured count."
            ),
            parameters=[CliParameter(
                name="count", value_spec="Integer 1..10",
                description="Maximum allowed occurrences of own ASN.",
                default="3",
            )],
            default_behavior="disabled (no AS_PATH loops allowed)",
            notes=("Enabling this knob disables the AS loop check for this "
                   "neighbor and AF; use only in confederation/route-server "
                   "scenarios where loops are intentional."),
            related_features=["BGP AS_PATH loop check"],
        ),
        _sub(
            name="capability",
            syntax=(
                "capability {orf-prefix-list send | orf-prefix-list receive | "
                "orf-prefix-list both | route-refresh}\n"
                "no capability {orf-prefix-list ... | route-refresh}"
            ),
            description=(
                "Negotiate optional BGP capabilities with this neighbor for "
                "the L2VPN EVPN AF. ORF Prefix-List per RFC 5291; "
                "Route Refresh per RFC 2918."
            ),
            parameters=[
                CliParameter(name="orf-prefix-list send", description=(
                    "Advertise willingness to send ORF prefix-list to peer."),
                    is_choice=True),
                CliParameter(name="orf-prefix-list receive", description=(
                    "Advertise willingness to receive ORF prefix-list from peer."),
                    is_choice=True),
                CliParameter(name="orf-prefix-list both", description=(
                    "Both send and receive ORF prefix-list."), is_choice=True),
                CliParameter(name="route-refresh", description=(
                    "Advertise Route Refresh capability (RFC 2918)."),
                    is_choice=True),
            ],
            default_behavior="route-refresh advertised; ORF off",
            notes=("Negotiated in OPEN; capability mismatch is silent — the "
                   "feature simply doesn't activate. Verify via "
                   "`show bgp neighbor <ip> | include Capability`."),
            related_features=["BGP capability negotiation",
                              "RFC 5291 ORF", "RFC 2918 Route Refresh"],
        ),
        _sub(
            name="inbound-soft-reconfiguration",
            syntax=(
                "inbound-soft-reconfiguration\n"
                "no inbound-soft-reconfiguration"
            ),
            description=(
                "Cache all received NLRIs from this neighbor so inbound "
                "policy can be re-applied without a hard session reset. "
                "Memory-intensive; prefer Route Refresh (RFC 2918) when "
                "the peer supports it."
            ),
            default_behavior="disabled (rely on Route Refresh)",
            notes=("Enable only when the peer does NOT support the "
                   "route-refresh capability. Combined with `capability "
                   "route-refresh`, route-refresh wins."),
            related_features=["BGP soft reconfiguration"],
        ),
        _sub(
            name="maximum-prefix",
            syntax=(
                "maximum-prefix <max> [<threshold-pct> [warning-only | "
                "restart <interval>]]\n"
                "no maximum-prefix"
            ),
            description=(
                "Cap the number of L2VPN EVPN prefixes accepted from this "
                "neighbor. When exceeded, the session is torn down with "
                "NOTIFICATION code 6 sub-code 1 unless `warning-only` "
                "(syslog only, session preserved) or `restart` "
                "(auto-restart after <interval> minutes)."
            ),
            parameters=[
                CliParameter(name="max", value_spec="Integer 1..4294967295",
                             description="Maximum accepted prefix count."),
                CliParameter(name="threshold-pct",
                             value_spec="Integer 1..100",
                             description=("Percentage of <max> at which a "
                                          "warning is logged."),
                             default="75"),
                CliParameter(name="warning-only", is_choice=True,
                             description="Log only; do not tear down."),
                CliParameter(name="restart", is_choice=True,
                             description=("Auto-restart after <interval> "
                                          "minutes.")),
                CliParameter(name="interval", value_spec="Integer 1..65535",
                             description="Minutes before auto-restart."),
            ],
            default_behavior="no limit",
            notes=("Tearing down on cap is the default action — choose "
                   "`warning-only` for monitoring-only deployments. "
                   "`warning-only` and `restart` are mutually exclusive."),
            related_features=["BGP prefix-limit",
                              "RFC 4271 NOTIFICATION code 6"],
        ),
        _sub(
            name="policy",
            syntax=(
                "policy <policy-name> {in | out}\n"
                "no policy <policy-name> {in | out}"
            ),
            description=(
                "Attach a route-policy / route-map to the inbound or "
                "outbound L2VPN EVPN update direction for this neighbor. "
                "Policy is evaluated before MAC/IP route installation (in) "
                "or before NLRI advertisement (out)."
            ),
            parameters=[
                CliParameter(name="policy-name",
                             value_spec="String 1..63 chars",
                             description=("Name of a previously defined "
                                          "routing-policy.")),
                CliParameter(name="in", is_choice=True,
                             description="Apply on inbound updates."),
                CliParameter(name="out", is_choice=True,
                             description="Apply on outbound updates."),
            ],
            default_behavior="no policy (all routes pass)",
            notes=("A non-existent <policy-name> is a config error at commit "
                   "time. Edits to an attached policy take effect on the "
                   "next refresh / soft-reset."),
            related_features=["BGP routing-policy", "EVPN route filtering"],
        ),
        _sub(
            name="private-as",
            syntax=(
                "private-as {remove | replace}\n"
                "no private-as"
            ),
            description=(
                "Strip or replace private AS numbers (64512..65534, "
                "4200000000..4294967294) from the AS_PATH on outbound "
                "L2VPN EVPN updates to this neighbor."
            ),
            parameters=[
                CliParameter(name="remove", is_choice=True,
                             description=("Delete private ASNs from "
                                          "AS_PATH.")),
                CliParameter(name="replace", is_choice=True,
                             description=("Replace each private ASN with "
                                          "the local ASN.")),
            ],
            default_behavior="disabled (private ASNs sent verbatim)",
            notes=("Use on eBGP toward upstream transit; mutually exclusive "
                   "with itself — second commit replaces the first."),
            related_features=["BGP AS_PATH manipulation"],
        ),
        _sub(
            name="route-reflector-client",
            syntax=(
                "route-reflector-client\n"
                "no route-reflector-client"
            ),
            description=(
                "Mark this neighbor as an iBGP route-reflector client for "
                "the L2VPN EVPN AF. Reflected L2VPN EVPN routes carry the "
                "ORIGINATOR_ID and CLUSTER_LIST attributes per RFC 4456."
            ),
            default_behavior="disabled (neighbor is a regular iBGP peer)",
            notes=("Valid only on iBGP sessions. Enabling on an eBGP "
                   "neighbor is rejected at commit time."),
            related_features=["BGP route reflection",
                              "RFC 4456 ORIGINATOR_ID / CLUSTER_LIST"],
        ),
    ],
)


INHERITANCE_TABLE: list[InheritanceEntry] = [BGP_NEIGHBOR_AF_L2VPN_EVPN]


def expand(extracted: list[CliCommand]) -> list[CliCommand]:
    """Produce inherited sub-config CliCommand objects for parents that
    appear in `extracted`.

    For each entry in `INHERITANCE_TABLE`, if the parent_command name
    appears among the extracted commands, the entry's sub_configs are
    appended to the output — skipping any sub-config whose name is
    already present in `extracted` (idempotent under repeated runs and
    safe to call when the real BGP CLI doc is later integrated).
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


def inheritance_source_for(name: str) -> str | None:
    """Return the human-readable source string for a sub-config name, or
    None if the name isn't in any inheritance entry. Used by
    xlsx_writer's Synthesized — Review sheet to show provenance."""
    for entry in INHERITANCE_TABLE:
        for sub in entry.sub_configs:
            if sub.name == name:
                return entry.source
    return None

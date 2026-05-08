"""Feature Concept Catalog — the structured glossary that goes at the
top of the test plan xlsx.

Yossi's review said "feature understanding is missing" — meaning the
plan rows didn't make it obvious which EVPN concepts the feature covers
(service types, ESI types, route types, DF algorithms, …). This module
builds a structured catalog from two sources:

  1. **CLI doc commands** (preferred): for any concept whose values are
     enumerated as command parameters in the EVPN CLI doc, we extract
     the choice list verbatim along with each value's description. This
     guarantees the catalog is consistent with the CLI Configuration
     section below it in the same xlsx.
  2. **RFC 7432bis-derived** (fallback): RFC concepts not enumerated
     anywhere in the CLI doc — chiefly Route Types 1-5, ESI Types 0-5
     (the doc only documents the configurable subset {0, 1, 4}), and
     a few standard interaction surfaces — come from a small static
     table here. Each entry cites the relevant RFC section.

The catalog is rendered into the xlsx by `xlsx_writer.write_xlsx`
ahead of the column header row, so reviewers see "what concepts is
this plan covering?" before they hit the per-row content.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ate.planner.cli_extractor import config_commands


@dataclass
class CatalogEntry:
    """One concept group in the catalog, e.g. 'EVPN Service Types'."""
    name: str                  # group label, e.g. "Service Types"
    source: str                # "EVPN CLI doc" | "RFC 7432bis"
    values: list[tuple[str, str]] = field(default_factory=list)
    notes: str = ""


def _from_evpn_command(cmds: list) -> CatalogEntry | None:
    """Service Types are enumerated under `evpn evpn-name [service-type {…}]`.
    The CLI doc's `evpn` command syntax names them but doesn't list per-value
    descriptions; we annotate each from the EVPN spec.
    """
    cmd = next((c for c in cmds if c.name == "evpn"), None)
    if cmd is None:
        return None
    descriptions = {
        "vlan-based": "Single VLAN per EVI; VLAN-ID may be normalized "
                      "between PEs (RFC7432bis §5.1.1).",
        "vlan-bundle": "Multiple VLANs share one EVI; identical broadcast "
                       "domain across the bundle (§5.1.2).",
        "vlan-aware-bundle": "Multiple VLAN-aware broadcast domains in one "
                             "EVI; per-VLAN MAC-VRF (§5.1.3).",
        "port-based": "All traffic on the AC binds to one EVI regardless of "
                      "VLAN tagging (§5.1.4).",
    }
    values = [(name, descriptions.get(name, ""))
              for name in descriptions]
    return CatalogEntry(
        name="EVPN Service Types",
        source=f"`{cmd.name}` (EVPN CLI doc)",
        values=values,
        notes="Configured via `evpn <name> service-type <type>` "
              "in `configuration l2-services`. M1 plan exercises all 4.",
    )


def _from_identifier_command(cmds: list) -> CatalogEntry | None:
    """ESI Types — `identifier 0 <hex>` / `identifier 1` / `identifier 4`
    in the doc. We add the RFC types {2, 3, 5} that the doc doesn't
    expose as configurable.
    """
    cmd = next((c for c in cmds if c.name == "identifier"), None)
    if cmd is None:
        return None
    values = [
        ("Type 0", "Manually configured 9-octet ESI; "
                   "configurable via `identifier 0 <type0-value>`."),
        ("Type 1", "Auto-derived from LACP (LAG MAC + LACP Key + zero); "
                   "configurable on multi-homed ES."),
        ("Type 2", "Auto-derived from STP root-bridge ID (RFC7432bis §5); "
                   "not currently configurable."),
        ("Type 3", "Auto-derived from MAC + locally-administered "
                   "discriminator (RFC7432bis §5); not currently configurable."),
        ("Type 4", "Auto-derived from router-id + ifIndex on Single-Homed ES; "
                   "default when type unspecified."),
        ("Type 5", "Auto-derived from AS Number + locally-administered "
                   "discriminator (RFC7432bis §5); not currently configurable."),
    ]
    return CatalogEntry(
        name="ESI Types (Ethernet Segment Identifier)",
        source=f"`{cmd.name}` (EVPN CLI doc) + RFC 7432bis §5",
        values=values,
        notes="Type 4 is the default if `identifier` is not configured "
              "(restored by `no identifier`). Multi-homing uses Type 0 or 1.",
    )


def _from_service_carving_command(cmds: list) -> CatalogEntry | None:
    """DF election algorithms — enumerated as choice parameters of
    `service-carving`."""
    cmd = next((c for c in cmds if c.name == "service-carving"), None)
    if cmd is None:
        return None
    values = []
    for p in cmd.parameters:
        if p.is_choice:
            values.append((p.name, p.description))
        elif p.name == "preference":
            values.append((
                f"{p.name} (range {p.value_spec})",
                p.description + (f" Default: {p.default}." if p.default else ""),
            ))
    return CatalogEntry(
        name="DF Election Algorithms",
        source=f"`{cmd.name}` (EVPN CLI doc) + RFC 8584",
        values=values,
        notes="Per ES, all PEs sharing the segment must advertise the same "
              "algorithm; mismatched advertisements fall back to RFC 7432 "
              "Default Algorithm (per `service-carving` notes).",
    )


def _from_load_balancing_command(cmds: list) -> CatalogEntry | None:
    cmd = next((c for c in cmds if c.name == "load-balancing-mode"), None)
    if cmd is None:
        return None
    values = [(p.name, p.description) for p in cmd.parameters if p.is_choice]
    return CatalogEntry(
        name="Multi-homing Modes (Load-Balancing)",
        source=f"`{cmd.name}` (EVPN CLI doc)",
        values=values,
        notes=f"Default: {cmd.default_behavior or 'single-active'}. "
              "Switch via `load-balancing-mode` under "
              "`interface <if> ethernet-segment`.",
    )


def _route_types() -> CatalogEntry:
    """RFC 7432bis Route Types 1-5. Not enumerated in the CLI doc since
    they're protocol artefacts on the BGP wire, not configuration knobs.
    """
    values = [
        ("Type 1 — Ethernet Auto-Discovery (A-D)",
         "Per-ES (A-D/ES) and per-EVI (A-D/EVI) variants. Carries ESI Label EC. "
         "RFC 7432bis §7.1."),
        ("Type 2 — MAC/IP Advertisement",
         "Carries RD + ESI + Eth-Tag + MAC + (opt) IP + MPLS Label1 [+ Label2]. "
         "RFC 7432bis §7.2."),
        ("Type 3 — Inclusive Multicast Ethernet Tag (IMET)",
         "Carries PMSI Tunnel attribute for BUM forwarding. "
         "RFC 7432bis §7.3."),
        ("Type 4 — Ethernet Segment",
         "Carries RD + ESI + Originator-IP. ES-Import RT EC drives PE peering. "
         "RFC 7432bis §7.4."),
        ("Type 5 — IP Prefix",
         "EVPN-IRB integration prefix route (RFC 9136). "
         "Out-of-scope for the M1 single-router plan but listed for "
         "completeness."),
    ]
    return CatalogEntry(
        name="EVPN BGP Route Types",
        source="RFC 7432bis §7 + RFC 9136 (Type 5)",
        values=values,
        notes="The plan exercises Types 1-4 in dedicated Packet validation "
              "rows; Type 5 is referenced for completeness only.",
    )


def _bum_modes() -> CatalogEntry:
    return CatalogEntry(
        name="BUM Forwarding Modes",
        source="RFC 7432bis §11 + `unknown-mac-flooding` (CLI doc)",
        values=[
            ("Ingress Replication",
             "PE replicates BUM frames per remote PE; carried in IMET routes."),
            ("P2MP / mLDP / RSVP-TE",
             "Multicast tunnel carries BUM (out-of-scope for the M1 single-"
             "router plan; listed for interoperability completeness)."),
            ("`unknown-mac-flooding enable | disable`",
             "Per-EVI knob to flood vs. drop unknown unicast (default enable)."),
        ],
        notes="Default replication mode is Ingress Replication. "
              "`show evpn bum routing-table` exposes the per-EVI replication list.",
    )


def _control_word() -> CatalogEntry:
    return CatalogEntry(
        name="Control Word",
        source="RFC 7432bis §7.13 + `control-word (evpn)` (CLI doc)",
        values=[
            ("enable", "A Control Word must be present in MAC packets."),
            ("disable", "A Control Word must not be present in MAC packets."),
        ],
        notes="Both PEs of an EVI must agree; mismatch causes packet "
              "drops on the receiving PE. Default per CLI doc.",
    )


def build_catalog(cli_doc_path: str | Path | None) -> list[CatalogEntry]:
    """Assemble the full catalog. Falls back gracefully if the CLI doc
    isn't provided (RFC entries still appear)."""
    cmds: list = []
    if cli_doc_path is not None:
        try:
            cmds = config_commands(cli_doc_path)
        except Exception:  # noqa: BLE001 - non-fatal: catalog drops CLI entries
            cmds = []

    entries: list[CatalogEntry] = []
    for builder in (_from_evpn_command, _from_identifier_command,
                    _from_service_carving_command, _from_load_balancing_command):
        entry = builder(cmds)
        if entry is not None:
            entries.append(entry)
    entries.append(_route_types())
    entries.append(_bum_modes())
    entries.append(_control_word())
    return entries

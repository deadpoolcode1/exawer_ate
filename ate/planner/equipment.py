"""Test equipment classification per row.

Yossi's M1 review flagged: "Missing indication of which test should use
IXIA and to do what." This module centralizes the mapping so every row
the generator emits carries an explicit equipment tag in its own xlsx
column — QA doesn't have to infer the rig from prose.

Tags use Exaware's house language:
  - "DUT only"                       — single router, no traffic gen needed
  - "DUT + IXIA traffic gen"         — IXIA on access-side, generates Ethernet frames
  - "DUT + IXIA + neighbor PE"       — full leaf-spine hop, plus 3rd-party / Exaware PE
  - "DUT + 3rd-party PE"             — interop partner, IXIA optional
  - "DUT + power-cycle harness"      — robustness rig (PDU / smart-PSU)
  - "DUT + JSystem framework"        — automated test runner only
  - "Two routers + IXIA scale rig"   — performance / scale lab

Per SOW PQ4476E §3 the IXIA Router Simulator + neighboring-router rig
are explicit POC test infrastructure. Code generation in M4 will key
off the same tags, so keep the vocabulary stable.
"""
from __future__ import annotations

# Category → equipment tag. Some categories are "almost always X" — for
# the few that depend on the requirement (e.g. Basic Functionality of a
# config-only requirement vs. a packet-handling requirement) we override
# from `equipment_for_row` based on tags.
CATEGORY_TO_EQUIPMENT: dict[str, str] = {
    "CLI configuration":             "DUT only",
    "Basic Functionality":           "DUT + IXIA traffic gen",
    "On The Fly changes":            "DUT + IXIA traffic gen",
    "Packet validation":             "DUT + IXIA + neighbor PE",
    "Malformed/unsupported packets": "DUT + IXIA traffic gen",
    "Feature interaction":           "DUT + IXIA + neighbor PE",
    "3rd Party Interoperability":    "DUT + 3rd-party PE (Cisco/Juniper) + IXIA",
    "Scale":                         "Two routers + IXIA scale rig",
    "Performance":                   "Two routers + IXIA scale rig",
    "Robustness":                    "DUT + IXIA traffic gen + power-cycle harness",
    "PM":                            "DUT only",
    "Alarms/Logs/Syslog":            "DUT + syslog collector",
    "Upgrade":                       "DUT + ONIE image server",
    "HA":                            "DUT + IXIA traffic gen (process-kill harness)",
    "Long run":                      "DUT + IXIA continuous traffic (≥ 24 h)",
    "Management":                    "DUT + NETCONF client (e.g. ncclient)",
    "Tech-support":                  "DUT only",
}


def equipment_for_row(category: str, tags: list[str], source: str = "spec",
                      ) -> str:
    """Return the equipment tag for a row of the given category.

    `tags` are the requirement's domain tags (CONFIG, PACKET, HA, SCALE,
    PROTOCOL, MONITORING, META). For Basic Functionality, packet-bearing
    requirements upgrade from "DUT + IXIA traffic gen" to include a
    neighbor PE. For pure-CONFIG requirements with no packet/protocol
    surface, Basic Functionality drops IXIA.

    `source="rfc"` upgrades 3rd-Party Interoperability and Packet
    validation rows to require an actual interop partner — RFC
    conformance is meaningless against your own stack.
    """
    base = CATEGORY_TO_EQUIPMENT.get(category, "DUT only")

    is_packet = "PACKET" in tags or "PROTOCOL" in tags
    is_config_only = (set(tags) <= {"CONFIG", "META", "MONITORING"})

    if category == "Basic Functionality":
        if is_packet:
            return "DUT + IXIA + neighbor PE"
        if is_config_only:
            return "DUT only (read-back via show / running-config)"

    if category == "Feature interaction" and "HA" in tags:
        return "DUT + IXIA + neighbor PE + LACP partner"

    if category == "Scale" and source == "rfc":
        return "Two routers + IXIA scale rig (RFC conformance scale)"

    if category == "3rd Party Interoperability" and source == "rfc":
        return "DUT + 3rd-party PE (Cisco/Juniper) — RFC conformance test"

    return base


def equipment_for_cli_row() -> str:
    """All CLI-mined configuration rows share the same equipment tag."""
    return "DUT only (CLI session via console / SSH)"

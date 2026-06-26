"""Hand-curated TP rows for protocol constructs the auto-extractors miss.

Yossi Fridman 2026-06-21: the **Default Gateway Extended Community** is defined
in draft-ietf-bess-rfc7432bis §7.8, but its wire type is an *Opaque Extended
Community* defined outside the EVPN RFCs — RFC 4360 §3.3. §7.8 (and the §10.1
procedures) carry no MUST/SHALL keyword, so `rfc_extractor` — which emits a row
only per normative *leaf* section — drops the construct and the TP carries no
reference to it.

These curated rows fill the gap deterministically: they are NOT sent through the
AI enricher (source ``rfc-curated``), so the exact encoding (Type 0x03 /
Sub-Type 0x0d) stays precise and stable across regenerations. The same hook is
where future "defined-in-a-non-EVPN-RFC" constructs land until the dependency
RFCs themselves are ingested (Yossi-3).
"""
from __future__ import annotations

from ate.planner.model import PlanRow, Requirement

# Source marker that tells the AI enricher to leave the row verbatim (mirrors
# how `source == "cli"` rows are kept deterministic).
CURATED_SOURCE = "rfc-curated"


def curated_requirements_and_rows() -> tuple[list[Requirement], list[PlanRow]]:
    """Return (requirements, rows) for the hand-curated protocol constructs.

    The requirements are added to ``plan.requirements`` so the enricher resolves
    and then skips them; the rows are appended to the plan body. Both use
    ``source = CURATED_SOURCE`` and an ``RFC...`` req-id so they render under the
    "RFC Protocol Mandates" section.
    """
    rid = "RFC7432bis-§7.8"
    req = Requirement(
        req_id=rid,
        title="Default Gateway Extended Community",
        section_number="7.8",
        description=(
            "Default Gateway Extended Community (RFC7432bis §7.8): an Opaque "
            "Extended Community defined in RFC 4360 §3.3 — Type 0x03 "
            "(transitive opaque), Sub-Type 0x0d, Value reserved (0). Tags the "
            "MAC/IP (Type-2) route of an EVPN default gateway; receivers apply "
            "the best-path procedures of §10.1."
        ),
        rfc_refs=["RFC7432bis ch.7.8", "RFC7432bis ch.10.1", "RFC4360 ch.3.3"],
        tags=["PACKET", "PROTOCOL"],
        source=CURATED_SOURCE,
    )
    row = PlanRow(
        flow_id="",
        flow_name="",
        category="Packet validation",
        sub_category="RFC7432bis §7.8 — Default Gateway Extended Community",
        equipment="DUT + IXIA + neighbor PE",
        covered_req_ids=[rid],
        sfs_requirement_id=rid,
        action_steps=(
            "Problem: the Default Gateway Extended Community (RFC7432bis §7.8) "
            "is carried as an Opaque Extended Community whose type is defined "
            "outside the EVPN RFCs (RFC 4360 §3.3); the DUT must encode and "
            "honour it exactly.\n"
            "Method: bring up an EVPN default gateway (IRB) and inspect both the "
            "advertised Type-2 route and the receiver's best-path choice.\n"
            "Setup: Two-PE VLAN-based EVPN in one EVI; PE1 configured as the "
            "default gateway (IRB) for the tenant subnet; PE2 a remote PE; IXIA "
            "emulates a host behind PE2 addressed to the gateway MAC.\n"
            "Action: On PE1, configure the subnet's default-gateway IP/MAC so "
            "PE1 advertises the gateway as a MAC/IP (Type-2) route.\n"
            "Action: On the receiving PE, read the imported route and its "
            "extended communities with `show bgp l2vpn evpn table evi`.\n"
            "Verify: the gateway's Type-2 route carries the Default Gateway "
            "Extended Community encoded as an Opaque EC (RFC 4360 §3.3) — "
            "Type=0x03, Sub-Type=0x0d, Value=0 (RFC7432bis §7.8).\n"
            "Verify: PE2 applies the §10.1 best-path rule — among routes for the "
            "same MAC/IP it prefers the one carrying the Default Gateway EC and "
            "installs the gateway function; host traffic to the gateway MAC is "
            "routed, not bridged."
        ),
        expectation=(
            "Pass: the default-gateway Type-2 route carries the Default Gateway "
            "Extended Community encoded exactly as Type 0x03 / Sub-Type 0x0d / "
            "Value 0 (RFC7432bis §7.8 over the Opaque EC of RFC 4360 §3.3), and "
            "the receiving PE applies the §10.1 default-gateway best-path and "
            "forwarding.\n"
            "Fail-on: the community is absent, encoded with a wrong Type / "
            "Sub-Type / non-zero Value, or the receiver ignores it and does not "
            "apply the default-gateway semantics of §10.1."
        ),
    )
    return [req], [row]

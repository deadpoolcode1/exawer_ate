"""Hand-curated TP rows for protocol constructs the auto-extractors miss, plus
the dependency-RFC relevance map (Yossi Fridman 2026-06-21).

Two related gaps from Yossi's review:

1. **Default Gateway Extended Community** (7432bis §7.8) had no TP reference — it
   is an *Opaque Extended Community* defined outside the EVPN RFCs (RFC 4360
   §3.3), and §7.8/§10.1 carry no MUST keyword, so `rfc_extractor` (one row per
   normative *leaf* section) dropped it.

2. **Non-EVPN RFCs are not ingested.** The SFS cites RFC 4761/4762/6514/7209/8584
   but only 7432bis + 9785 were provided. Per `docs/rfc_relevance_design.md` the
   right move is a *relevance filter*, not blanket ingestion: most cited RFCs are
   predecessor/framework context, while a few carry EVPN-relevant constructs
   (8584 DF election, 6514 BUM/PMSI). The relevant ones get curated reference
   tests here; the rest are recorded as reference-only in `DEPENDENCY_RFC_ROLE`
   so the cross-check states *why* each is or isn't ingested.

These rows are deterministic — NOT sent through the AI enricher (source
``rfc-curated``), so the exact encodings stay precise and stable.
"""
from __future__ import annotations

from ate.planner.model import PlanRow, Requirement

# Source marker that tells the AI enricher to leave the row verbatim (mirrors
# how `source == "cli"` rows are kept deterministic).
CURATED_SOURCE = "rfc-curated"

# Role / relevance verdict for every non-EVPN RFC the SFS cites (Yossi-3).
# verdict ∈ {"curated", "reference-only"}: "curated" → an EVPN-relevant section
# is captured as a curated test below; "reference-only" → predecessor or
# framework context that carries no EVPN-specific test mandate. rfc_crosscheck
# folds these verdicts into its missing-RFC report so a reviewer sees the
# reasoning rather than a bare "not ingested" warning.
DEPENDENCY_RFC_ROLE: dict[str, tuple[str, str, str]] = {
    # rfc#:  (role, verdict, note)
    "4360": ("BGP Extended Communities base", "curated",
             "Opaque EC type underpinning the Default Gateway EC — "
             "tested via RFC7432bis-§7.8."),
    "8584": ("DF election framework", "curated",
             "DF Election Extended Community + algorithms — "
             "tested via RFC8584-§2.2."),
    "6514": ("BUM transport (PMSI)", "curated",
             "PMSI Tunnel attribute on EVPN IMET routes — "
             "tested via RFC6514-§5."),
    "4364": ("Inter-AS / PHP transport (§10)", "flow",
             "BGP/MPLS IP-VPN transport; §10 inter-AS exercised by the "
             "EVI-to-EVI flows FLOW-130..135."),
    "4761": ("VPLS predecessor", "reference-only",
             "L2VPN/VPLS context; no EVPN-specific test mandate."),
    "4762": ("VPLS predecessor", "reference-only",
             "L2VPN/VPLS context; no EVPN-specific test mandate."),
    "7209": ("EVPN requirements framework", "reference-only",
             "Motivational requirements, realised by 7432bis; "
             "no standalone test."),
    "8340": ("YANG tree-diagram notation", "reference-only",
             "Notation only (RFC 8340); carries no test mandate."),
}


def _req(req_id: str, title: str, section: str, desc: str,
         rfc_refs: list[str]) -> Requirement:
    return Requirement(
        req_id=req_id, title=title, section_number=section,
        description=desc, rfc_refs=rfc_refs,
        tags=["PACKET", "PROTOCOL"], source=CURATED_SOURCE,
    )


def _row(req_id: str, sub_category: str, equipment: str,
         action_steps: str, expectation: str) -> PlanRow:
    return PlanRow(
        flow_id="", flow_name="", category="Packet validation",
        sub_category=sub_category, equipment=equipment,
        covered_req_ids=[req_id], sfs_requirement_id=req_id,
        action_steps=action_steps, expectation=expectation,
    )


def _default_gateway_ec() -> tuple[Requirement, PlanRow]:
    rid = "RFC7432bis-§7.8"
    req = _req(
        rid, "Default Gateway Extended Community", "7.8",
        ("Default Gateway Extended Community (RFC7432bis §7.8): an Opaque "
         "Extended Community defined in RFC 4360 §3.3 — Type 0x03 (transitive "
         "opaque), Sub-Type 0x0d, Value reserved (0). Tags the MAC/IP (Type-2) "
         "route of an EVPN default gateway; receivers apply §10.1 best-path."),
        ["RFC7432bis ch.7.8", "RFC7432bis ch.10.1", "RFC4360 ch.3.3"],
    )
    row = _row(
        rid, "RFC7432bis §7.8 — Default Gateway Extended Community",
        "DUT + IXIA + neighbor PE",
        ("Problem: the Default Gateway Extended Community (RFC7432bis §7.8) is "
         "carried as an Opaque Extended Community whose type is defined outside "
         "the EVPN RFCs (RFC 4360 §3.3); the DUT must encode and honour it "
         "exactly.\n"
         "Method: bring up an EVPN default gateway (IRB) and inspect both the "
         "advertised Type-2 route and the receiver's best-path choice.\n"
         "Setup: Two-PE VLAN-based EVPN in one EVI; PE1 configured as the "
         "default gateway (IRB) for the tenant subnet; PE2 a remote PE; IXIA "
         "emulates a host behind PE2 addressed to the gateway MAC.\n"
         "Action: On PE1, configure the subnet's default-gateway IP/MAC so PE1 "
         "advertises the gateway as a MAC/IP (Type-2) route.\n"
         "Action: On the receiving PE, read the imported route and its extended "
         "communities with `show bgp l2vpn evpn table evi`.\n"
         "Verify: the gateway's Type-2 route carries the Default Gateway "
         "Extended Community encoded as an Opaque EC (RFC 4360 §3.3) — "
         "Type=0x03, Sub-Type=0x0d, Value=0 (RFC7432bis §7.8).\n"
         "Verify: PE2 applies the §10.1 best-path rule — among routes for the "
         "same MAC/IP it prefers the one carrying the Default Gateway EC and "
         "installs the gateway function; host traffic to the gateway MAC is "
         "routed, not bridged."),
        ("Pass: the default-gateway Type-2 route carries the Default Gateway "
         "Extended Community encoded exactly as Type 0x03 / Sub-Type 0x0d / "
         "Value 0 (RFC7432bis §7.8 over the Opaque EC of RFC 4360 §3.3), and the "
         "receiving PE applies the §10.1 default-gateway best-path and "
         "forwarding.\n"
         "Fail-on: the community is absent, encoded with a wrong Type / Sub-Type "
         "/ non-zero Value, or the receiver ignores it and does not apply the "
         "default-gateway semantics of §10.1."),
    )
    return req, row


def _df_election_ec() -> tuple[Requirement, PlanRow]:
    rid = "RFC8584-§2.2"
    req = _req(
        rid, "DF Election Extended Community", "2.2",
        ("DF Election Extended Community (RFC 8584 §2.2): EVPN Extended "
         "Community Type 0x06, Sub-Type 0x06, carried on the Ethernet Segment "
         "(Type-4) route. The DF Alg field (5 bits) signals the elected "
         "algorithm — 0 = Default/modulus 'service-carving', 1 = HRW (Highest "
         "Random Weight) — and a 2-octet capability Bitmap (bit 1 = AC-DF). "
         "Cited by the SFS for the extended/Default DF behaviour (ch.8.5)."),
        ["RFC8584 ch.2.2", "RFC8584 ch.3.2", "RFC7432bis ch.8.5"],
    )
    row = _row(
        rid, "RFC8584 §2.2 — DF Election Extended Community",
        "DUT + IXIA + neighbor PE (dual-homed ES)",
        ("Problem: EVPN DF election advertises its algorithm/capabilities in the "
         "DF Election Extended Community (RFC 8584 §2.2), defined outside the "
         "core EVPN spec; the DUT must advertise and honour it.\n"
         "Method: bring up a dual-homed Ethernet Segment across two PEs and "
         "inspect the Type-4 route's DF Election EC and the resulting DF.\n"
         "Setup: ES esi-X multi-homed to PE1+PE2 in one EVI; IXIA dual-homed to "
         "the ES; a remote PE3 sources BUM toward the ES.\n"
         "Action: configure the DF election algorithm on the ES — default "
         "service-carving, then HRW — and commit on both PEs.\n"
         "Action: read the ES (Type-4) route and its extended communities with "
         "`show bgp l2vpn evpn table ethernet-segment`.\n"
         "Verify: the ES route carries the DF Election Extended Community "
         "(Type 0x06 / Sub-Type 0x06) with the DF Alg field = 0 (Default) or "
         "1 (HRW) matching the configuration, and the AC-DF capability bit set "
         "as configured.\n"
         "Verify: the elected DF matches the advertised algorithm; only the DF "
         "forwards BUM onto the ES while the non-DF applies split-horizon — "
         "confirm via `show evpn ethernet-segments`."),
        ("Pass: the Type-4 route carries the DF Election EC (Type 0x06 / "
         "Sub-Type 0x06) with the DF Alg and AC-DF bit matching configuration, "
         "and the elected DF follows that algorithm — exactly one DF forwards "
         "BUM to the ES.\n"
         "Fail-on: the EC is absent or mis-encoded (wrong Type/Sub-Type/DF Alg), "
         "two PEs or none act as DF, or BUM is duplicated onto the ES."),
    )
    return req, row


def _pmsi_tunnel() -> tuple[Requirement, PlanRow]:
    rid = "RFC6514-§5"
    req = _req(
        rid, "PMSI Tunnel attribute (EVPN BUM)", "5",
        ("PMSI Tunnel attribute (RFC 6514 §5): optional-transitive BGP "
         "attribute carried on the EVPN Inclusive Multicast Ethernet Tag "
         "(Type-3 / IMET) route to set up BUM forwarding. Fields: Flags "
         "(Leaf-Info-Required), Tunnel Type (6 = Ingress Replication for EVPN), "
         "3-octet MPLS Label, and a Tunnel Identifier (originating PE address). "
         "Cited by the SFS for the PMSI Tunnel attribute (ch.…)."),
        ["RFC6514 ch.5", "RFC7432bis ch.11"],
    )
    row = _row(
        rid, "RFC6514 §5 — PMSI Tunnel attribute (EVPN BUM)",
        "DUT + IXIA + 2 neighbor PEs",
        ("Problem: EVPN BUM forwarding is set up by the PMSI Tunnel attribute "
         "(RFC 6514 §5) on the Inclusive Multicast (Type-3) route, defined "
         "outside the core EVPN spec; the DUT must originate and act on it.\n"
         "Method: bring up an EVI across three PEs and drive BUM traffic; "
         "inspect the IMET route's PMSI Tunnel attribute and the replication.\n"
         "Setup: EVI on PE1/PE2/PE3 with ingress replication; IXIA injects "
         "broadcast, unknown-unicast and multicast into PE1.\n"
         "Action: read the IMET (Type-3) route each PE advertises with "
         "`show bgp l2vpn evpn table evi`.\n"
         "Verify: the IMET route carries a PMSI Tunnel attribute (RFC 6514 §5) "
         "with Tunnel Type = 6 (Ingress Replication), a non-zero downstream "
         "MPLS Label, and the originating PE address in the Tunnel Identifier.\n"
         "Verify: BUM frames from PE1 are ingress-replicated to PE2 and PE3 "
         "using the signalled labels, delivered exactly once, with split-horizon "
         "preventing loop-back to the source — confirm via "
         "`show evpn bum routing-table`."),
        ("Pass: every IMET route carries a PMSI Tunnel attribute with Ingress "
         "Replication (Type 6) and a valid label, and BUM traffic is delivered "
         "to all EVI PEs exactly once with no loops.\n"
         "Fail-on: the PMSI Tunnel attribute is absent or mis-encoded (wrong "
         "type/label), or BUM is dropped, duplicated, or looped."),
    )
    return req, row


def curated_requirements_and_rows() -> tuple[list[Requirement], list[PlanRow]]:
    """Return (requirements, rows) for every hand-curated construct.

    The requirements are added to ``plan.requirements`` so the enricher resolves
    and then skips them; the rows are appended to the plan body and render under
    "RFC Protocol Mandates" (their req-ids start with ``RFC``).
    """
    entries = [_default_gateway_ec(), _df_election_ec(), _pmsi_tunnel()]
    reqs = [e[0] for e in entries]
    rows = [e[1] for e in entries]
    return reqs, rows

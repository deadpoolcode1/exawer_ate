"""Functional flows for the EVPN test plan.

Closes the QA review gap that the previous pass left open: rows were
ordered by requirement number and each row tested a single requirement
in isolation, which made the plan a checklist rather than a test plan.
QA wants flows / use cases — each row is a runnable scenario that
exercises multiple requirements, with CLI commands + IXIA traffic
combined, in a shape that a downstream automation-codegen step can
consume.

A `Flow` is a use case (e.g. "All-active multi-homing bring-up"). Each
flow declares:

  - A canonical Setup → Action → Verify scaffold (the happy path).
  - A measurable Pass / Fail-on pair.
  - The categories that are meaningful to test under this flow
    (Basic Functionality, Packet validation, On-the-fly, Robustness,
    Scale, …). Categories that do not apply are skipped — that's the
    "categories aggregate by functional aspect" point in the QA
    feedback.
  - A selector that maps requirements onto the flow by title/keyword
    and tag. Requirements with no flow appear in the Coverage sheet's
    orphan list, which is the signal that more flows are needed.

The flows below cover the EVPN System Specification's primary use
cases. They are deliberately rule-based so the generator stays
deterministic; M3's AI enrichment refines per-flow row content
without changing the flow catalog.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ate.planner.model import Requirement


@dataclass
class FlowSelector:
    """How a flow claims requirements.

    A requirement matches when EITHER:
      - its title matches any `title_keywords` (case-insensitive substring), OR
      - its description matches any `desc_keywords` AND any tag in
        `required_tags` is present (the desc-only path is gated on tags
        because keyword bleed in descriptions is the main false-positive
        source).

    `explicit_req_ids` always match (used to pin specific requirements
    that don't surface via keywords, e.g. cross-cutting MUSTs).
    """
    title_keywords: list[str] = field(default_factory=list)
    desc_keywords: list[str] = field(default_factory=list)
    required_tags: list[str] = field(default_factory=list)
    explicit_req_ids: list[str] = field(default_factory=list)


@dataclass
class Flow:
    id: str
    name: str
    summary: str
    setup: str
    action: str
    verify: str
    pass_: str
    fail_on: str
    equipment: str
    categories: list[str]
    selector: FlowSelector
    related_cli_cmds: list[str] = field(default_factory=list)
    rfc_refs: list[str] = field(default_factory=list)
    # When True the flow is a *test technique* applied broadly (scale,
    # upgrade, NETCONF management, on-the-fly changes, 24 h soak) and is
    # not anchored to a single requirement. Renders body rows + a clear
    # marker in the Flows sheet so reviewers do not read an empty
    # "Covered Req IDs" cell as a coverage gap.
    coverage_driven: bool = False


# ── EVPN flow catalog ──────────────────────────────────────────────────
# Naming: FLOW-NNN where NNN is stable so xlsx Flow-ID columns survive
# across regenerations and reviewers can cite "FLOW-040 step 2".

EVPN_FLOWS: list[Flow] = [
    Flow(
        id="FLOW-010",
        name="Single-homed VLAN-Based EVPN bring-up",
        summary=(
            "Configure a vlan-based EVPN instance on one PE; bring it up; "
            "forward known and unknown unicast through the access port."
        ),
        setup=(
            "Two-PE topology over MPLS; BGP EVPN session up. CE attached "
            "single-homed to PE1 access port; access port carries one VLAN."
        ),
        action=(
            "On PE1: `evpn evi-1 service-type vlan-based` under "
            "`configuration l2-services`; set `auto-discovery enable`, "
            "`import-rt 65000:1`/`export-rt 65000:1`; bind the access AC "
            "with `interface agg-eth-1 evpn evi-1`; commit. From IXIA, "
            "send 1 Gbps known-unicast (then unknown-unicast) frames "
            "PE1→PE2 and PE2→PE1 for ≥ 60 s."
        ),
        # Eyal Ozeri 2026-07-06 (row 549, "type-3 ?"): make bring-up assert
        # BOTH route types — the remote PE installs the Type 2 MAC/IP for known
        # unicast AND installs the Type 3 IMET and uses it to flood BUM — not
        # just Type 2.
        verify=(
            "`show evpn evi evi-1` reports the EVI up; access AC bound; "
            "MAC table populates from data-plane learning; tcpdump on PE↔PE "
            "shows MAC/IP (Type 2) and IMET (Type 3) routes; the remote PE "
            "installs the Type 2 MAC/IP (known-unicast forwarding) and the "
            "Type 3 IMET (BUM flooding tunnel) and forwards on each "
            "accordingly; IXIA receives frames on the far port at line rate "
            "(≥ 0.99 Gbps for a 1 Gbps offered load)."
        ),
        pass_=(
            "EVI up within ≤ 10 s of commit; both Type 2 and Type 3 routes "
            "installed and used (unicast on Type 2, BUM on the Type 3 IMET); "
            "bidirectional unicast forwarded; MAC table reflects learned MACs; "
            "≤ 0 packet drops over the 60 s steady-state window."
        ),
        fail_on=(
            "EVI never reaches up state, MAC not learned, frames "
            "black-holed, or commit rejected."
        ),
        equipment="DUT + IXIA + neighbor PE",
        categories=[
            "Basic Functionality",
            "Packet validation",
            "On The Fly changes",
            "Feature interaction",
            "PM",
            "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=[
                "vlan-based", "vlan based", "service interface type",
                "service type", "router distinguisher",
                "import-rt", "export-rt", "auto-discovery",
                "remote mac learning", "mac learning",
                "route distinguisher", "rd assignment",
                "evpn configuration",
                # Eyal Ozeri 2026-07-06: "bgp common cli" (EVPNS-REQ#20) used
                # to attach here, so every one of FLOW-010's category overlays
                # regenerated a near-duplicate "BGP common commands accepted"
                # test — the repetition Eyal flagged ("I'd expect a separate
                # BGP bring-up phase"). REQ#20 now lives on the dedicated
                # FLOW-015 (BGP af-l2vpn evpn bring-up) instead.
                "auto-derivation from the ethernet tag",
            ],
            explicit_req_ids=["EVPNS-REQ#380"],  # generic "Configuration"
            required_tags=["CONFIG", "PROTOCOL"],
        ),
        related_cli_cmds=[
            "evpn", "auto-discovery", "import-rt", "export-rt",
            "interface (evpn binding)",
        ],
        rfc_refs=["RFC 7432bis §5.1.1", "RFC 7432bis §7.2"],
    ),
    Flow(
        id="FLOW-011",
        name="VLAN-Aware Bundle EVPN bring-up",
        summary=(
            "Configure a vlan-aware-bundle EVI; verify per-VLAN MAC-VRF "
            "isolation across the bundle."
        ),
        setup=(
            "Two-PE topology over MPLS; BGP EVPN up. CE access bundles "
            "≥ 2 VLANs into the same EVI."
        ),
        action=(
            "On PE1: `evpn evi-2 service-type vlan-aware-bundle`; bind "
            "VLANs 100..103 to the bundle; commit. From IXIA, send 100 "
            "Mbps unicast on each VLAN; force a MAC collision (identical "
            "source MAC) across VLAN 100 and VLAN 101."
        ),
        verify=(
            "`show evpn evi evi-2` lists each VLAN's MAC-VRF separately; "
            "the colliding MAC is learned twice (once per VLAN); cross-VLAN "
            "leakage does not occur on data plane (IXIA receives the frame "
            "only on the VLAN it was sent on)."
        ),
        pass_=(
            "Per-VLAN MAC-VRF isolation holds; same MAC may appear in "
            "multiple VLAN tables without conflict."
        ),
        fail_on=(
            "Cross-VLAN MAC leakage, VLAN-aware MAC-VRF collapses to a "
            "single table, or commit rejects valid VLAN binding."
        ),
        equipment="DUT + IXIA + neighbor PE",
        categories=[
            "Basic Functionality", "Packet validation", "Feature interaction",
            "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=["vlan-aware", "vlan aware"],
            required_tags=["CONFIG", "PROTOCOL"],
        ),
        related_cli_cmds=["evpn", "auto-discovery"],
        rfc_refs=["RFC 7432bis §5.1.3"],
    ),
    Flow(
        id="FLOW-012",
        name="VLAN-Based Bundle service-type EVPN bring-up",
        summary=(
            "Configure a vlan-bundle EVI sharing one broadcast domain "
            "across multiple VLANs."
        ),
        setup="Two-PE topology over MPLS; BGP EVPN up; CE attaches multiple VLANs.",
        action=(
            "On PE1: `evpn evi-3 service-type vlan-bundle`; bind VLANs "
            "200..203 to the bundle; commit. From IXIA, send 100 Mbps "
            "broadcast on VLAN 200 of the bundle."
        ),
        verify=(
            "Broadcast received on all bundle VLANs at the remote PE; MAC "
            "learned in a single shared MAC-VRF."
        ),
        pass_="Broadcast spans the full bundle; one MAC-VRF per EVI.",
        fail_on=(
            "Broadcast confined to source VLAN, or per-VLAN MAC-VRFs created "
            "for a vlan-bundle EVI."
        ),
        equipment="DUT + IXIA + neighbor PE",
        categories=[
            "Basic Functionality", "Packet validation", "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=["vlan-bundle", "vlan bundle",
                            "vlan-based bundle", "vlan based bundle"],
            explicit_req_ids=["EVPNS-REQ#40"],
            required_tags=["CONFIG", "PROTOCOL"],
        ),
        related_cli_cmds=["evpn"],
        rfc_refs=["RFC 7432bis §5.1.2"],
    ),
    Flow(
        id="FLOW-013",
        name="Port-based EVPN bring-up",
        summary=(
            "Bind an entire access port (regardless of VLAN tagging) into "
            "one EVI."
        ),
        setup="Two-PE topology over MPLS; BGP EVPN up; CE access port carries mixed-VLAN traffic.",
        action=(
            "On PE1: `evpn evi-4 service-type port-based`; bind the access "
            "port `agg-eth-2` without VLAN filter; commit. IXIA sends "
            "mixed-tag traffic at 1 Gbps (untagged, VLAN 10 tagged, VLAN "
            "20 tagged in equal shares)."
        ),
        verify=(
            "All ingress frames (any VLAN) bind to the EVI; remote PE "
            "receives the same; no VLAN-based steering at access."
        ),
        pass_="All traffic on the AC binds to the same EVI.",
        fail_on="Only tagged or only untagged frames are bound; VLAN steering occurs.",
        equipment="DUT + IXIA + neighbor PE",
        categories=[
            "Basic Functionality", "Packet validation", "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=["port-based", "port based"],
            required_tags=["CONFIG"],
        ),
        related_cli_cmds=["evpn"],
        rfc_refs=["RFC 7432bis §5.1.4"],
    ),
    Flow(
        id="FLOW-014",
        name="Access-interface variants on EVPN AC (Q-in-Q, Sub-if, agg-eth, x-eth)",
        # Eyal Ozeri 2026-06-29: drop vlan-range from the access-interface
        # matrix — vlan-range support is being removed, so it must not appear
        # as an exercised AC form here or on the cover page (model.interfaces).
        summary=(
            "Bind the EVPN AC to each documented access-interface form — "
            "x-eth, Sub-if (single-tagged), Q-in-Q (double-tagged), and "
            "agg-eth (LACP LAG) — and verify each forwards correctly. "
            "Exercises the full interface matrix the cover page advertises."
        ),
        setup=(
            "Two-PE EVPN service up (FLOW-010 baseline). Four access "
            "ports on PE1 cabled to IXIA: x-eth-1 (untagged), "
            "sub-if x-eth-2.100 (single-tag VLAN 100), x-eth-3 "
            "(Q-in-Q outer 200 inner 10..20), and agg-eth-1 (LACP LAG of "
            "two x-eth members)."
        ),
        # Eyal Ozeri 2026-07-06: (row 666) add the VLAN-ID manipulation the
        # SFS mandates for tagged ACs (§2.3.1.1 — the system replaces the
        # ingress VLAN-ID with the configured normalized VLAN-ID); (row 661)
        # the untagged (port-based) and tagged (sub-interface) forms live on
        # SEPARATE physical ports on purpose — they cannot co-exist on one
        # port, so the flow now asserts that a mixed binding is rejected.
        action=(
            "Bind each access-interface form to a dedicated EVI via "
            "`interface <form> evpn evi-N` in turn. On the sub-if AC, "
            "configure a normalized VLAN-ID (map ingress VLAN 100 → "
            "normalized VLAN 4) to exercise VLAN-ID manipulation "
            "(SFS §2.3.1.1). From IXIA, send 100 Mbps unicast through each "
            "form simultaneously: untagged on x-eth-1, VLAN 100 on "
            "x-eth-2.100, S-Tag 200 + C-Tag 15 on x-eth-3, and LACP-balanced "
            "on agg-eth-1. Finally, attempt to bind BOTH an untagged "
            "(port-based) AC and a VLAN sub-interface AC on the same physical "
            "port to confirm the two cannot co-exist."
        ),
        verify=(
            "`show evpn evi` lists each EVI up with its bound AC. "
            "`show interface detail` confirms each access form: x-eth "
            "untagged, sub-if dot1q 100, Q-in-Q outer 200 / inner 10..20 "
            "stack, and agg-eth lacp Up. The DUT rewrites the ingress "
            "VLAN-ID to the configured normalized VLAN-ID on egress (VLAN-op "
            "applied). IXIA receives every offered frame on the far PE at the "
            "offered rate (≥ 0.99× line rate). Binding an untagged AC and a "
            "tagged sub-if AC on one physical port is rejected at commit."
        ),
        pass_=(
            "All four access-interface forms bind to EVPN cleanly; ≤ 0 "
            "packet drops over 60 s steady state on each form; tag "
            "stack preserved (Q-in-Q frames egress with both tags; "
            "sub-if frames egress with single tag; untagged remains "
            "untagged); the ingress VLAN-ID is normalized to the configured "
            "value; untagged and tagged ACs are rejected on the same port."
        ),
        fail_on=(
            "Any form rejects a valid EVPN binding, Q-in-Q outer/inner tag "
            "drift, LACP LAG fails to bring up with EVPN, VLAN-ID "
            "normalization is not applied, or an untagged and a tagged AC are "
            "both accepted on the same physical interface."
        ),
        equipment=(
            "DUT + IXIA (4 ports: untagged, single-tag, double-tag, "
            "LACP partner) + neighbor PE"
        ),
        categories=[
            "Basic Functionality", "Packet validation", "Feature interaction",
            "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=[
                "q-in-q", "qinq", "sub-if", "sub interface", "subinterface",
                "agg-eth", "lag",
            ],
            required_tags=["CONFIG"],
        ),
        related_cli_cmds=["interface (VPLS/EVPN)", "evpn"],
        rfc_refs=["RFC 7432bis §6"],
        coverage_driven=True,
    ),
    Flow(
        # Eyal Ozeri 2026-07-06: dedicated "BGP bring-up phase" for the
        # af-l2vpn evpn common-command knobs (EVPNS-REQ#20). Previously REQ#20
        # attached to FLOW-010 and every category overlay there regenerated a
        # near-duplicate "BGP common commands accepted" row. Those knobs are
        # now exercised ONCE, end-to-end, in this flow. Per-knob CLI-acceptance
        # is covered separately by the CLI Configuration section (the
        # af-l2vpn evpn inherited sub-configs, de-invented pending the BGP CLI
        # manual). Single category on purpose — no overlay multiplication.
        id="FLOW-015",
        name="BGP L2VPN EVPN address-family (af-l2vpn evpn) bring-up",
        summary=(
            "Bring a BGP EVPN neighbor up under `af-l2vpn evpn` and verify the "
            "common BGP neighbor-policy knobs (EVPNS-REQ#20: allow-as-in, "
            "capability, inbound-soft-reconfiguration, maximum-prefix, "
            "private-as, route-reflector-client, weight, group) are accepted "
            "in the L2VPN EVPN context and operate without disrupting the "
            "session. Exact per-knob argument grammar is validated in the CLI "
            "Configuration section; this flow proves they function end-to-end."
        ),
        setup=(
            "PE1 and PE2 over MPLS transport. A base BGP session between the "
            "PEs is configured but the L2VPN EVPN address-family is not yet "
            "enabled on the neighbor."
        ),
        action=(
            "On PE1, under `configuration routing bgp vrf neighbor <PE2-ip>`, "
            "enter `af-l2vpn evpn` and configure the common neighbor-policy "
            "knobs one commit at a time: `route-reflector-client` (iBGP), "
            "`allow-as-in`, `inbound-soft-reconfiguration`, `maximum-prefix` "
            "(with a limit sized above the expected route count), "
            "`private-as`, `weight`, and any `capability`/`group` the BGP "
            "manual documents. Commit after each; then bring the EVPN service "
            "up and exchange Type 2/3 routes across the session."
        ),
        verify=(
            "Each knob commits without CLI error and reads back under "
            "`af-l2vpn evpn` in `show configuration`. The BGP EVPN session "
            "establishes and stays up (no hard reset); `show bgp l2vpn evpn "
            "summary` shows the neighbor Established; reflected routes carry "
            "ORIGINATOR_ID/CLUSTER_LIST when route-reflector-client is set; "
            "the maximum-prefix limit tears the session down only when the "
            "documented threshold is exceeded."
        ),
        pass_=(
            "All EVPNS-REQ#20 knobs are accepted under `af-l2vpn evpn`, persist "
            "in `show configuration`, and are operational (route reflection, "
            "AS handling, soft-reconfiguration, prefix-limit) without "
            "disrupting the active EVPN service."
        ),
        fail_on=(
            "Any knob is rejected under `af-l2vpn evpn`, silently ignored, "
            "forces a hard session reset when it should be non-disruptive, or "
            "the maximum-prefix limit fails to act at the documented threshold."
        ),
        equipment="DUT + neighbor PE",
        categories=["Basic Functionality"],
        selector=FlowSelector(
            explicit_req_ids=["EVPNS-REQ#20"],
        ),
        related_cli_cmds=[
            "allow-as-in", "capability", "inbound-soft-reconfiguration",
            "maximum-prefix", "private-as", "route-reflector-client",
        ],
        rfc_refs=["RFC 4271", "RFC 4456", "RFC 7432bis §9"],
    ),
    Flow(
        id="FLOW-020",
        name="All-active multi-homing bring-up + DF election",
        summary=(
            "Two PEs share an Ethernet Segment to one CE in all-active "
            "mode; DF elects; both PEs forward known unicast; only the DF "
            "forwards BUM."
        ),
        setup=(
            "Two PEs (PE1, PE2) connect to the same CE via an LACP LAG "
            "(shared ESI). EVI up on both PEs."
        ),
        action=(
            "Configure ES on both PEs: `interface agg-eth-1 "
            "ethernet-segment` with matching `identifier 1` (LACP); "
            "`load-balancing-mode all-active`; `service-carving "
            "preference 40000` on PE1 (PE2 keeps default 37237). Bring "
            "the ES up; advertise Type 1 and Type 4 routes; observe DF "
            "election."
        ),
        verify=(
            "Both PEs derive identical ESI; both advertise Type 4 (ES) "
            "routes carrying ES-Import RT EC; DF election converges; "
            "`show evpn ethernet-segment` reports exactly one DF per ES "
            "per VLAN; non-DF blocks BUM at access."
        ),
        pass_=(
            "Identical ESI on both PEs; one DF per ES per VLAN; known-"
            "unicast load-shared; BUM only forwarded by DF."
        ),
        fail_on=(
            "Two DFs (split-brain), DF never elected, mismatched ESI, or "
            "non-DF leaks BUM onto access."
        ),
        equipment="DUT + IXIA + neighbor PE + LACP partner",
        categories=[
            "Basic Functionality", "Packet validation", "Feature interaction",
            "On The Fly changes", "Robustness", "HA", "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=[
                "all-active", "all active", "designated forwarder",
                "df election", "ethernet segment", "service-carving",
                "service carving", "load balancing", "multi-homing",
                "multi homed", "lacp", "es-import",
                "highest-preference", "lowest-preference",
                "preference algorithm", "df algorithm",
                "non-revertive", "bgp attribute extension",
            ],
            required_tags=["HA", "CONFIG", "PROTOCOL"],
        ),
        related_cli_cmds=[
            "ethernet-segment", "identifier", "service-carving",
            "load-balancing-mode", "es-waiting-time", "lacp-key",
            "lacp-system-mac",
        ],
        rfc_refs=["RFC 7432bis §8", "RFC 8584"],
    ),
    Flow(
        id="FLOW-021",
        name="Single-active multi-homing + primary/backup signalling",
        summary=(
            "Two PEs share an ES in single-active mode; DF forwards; non-DF "
            "is backup; failover to backup on DF failure."
        ),
        setup="Two PEs share ESI to one CE; load-balancing-mode single-active.",
        action=(
            "Configure single-active ES with explicit `service-carving "
            "preference` on each PE (highest wins). Bring up; force DF "
            "withdrawal (interface flap on DF); observe backup PE take over."
        ),
        verify=(
            "Type 1 (per-EVI A-D) advertises primary/backup signalling per "
            "RFC 7432bis §8.5; failover converges within fast-convergence "
            "bound; IXIA traffic flow continues on the backup path."
        ),
        pass_=(
            "Primary→backup failover within ≤ 1 s (RFC 7432bis §8 fast-"
            "convergence target); no traffic after recovery is forwarded "
            "by both PEs simultaneously."
        ),
        fail_on=(
            "Both PEs forward simultaneously, traffic black-holed during "
            "failover, or convergence > 1 s."
        ),
        equipment="DUT + IXIA + neighbor PE + LACP partner",
        categories=[
            "Basic Functionality", "Packet validation", "Robustness", "HA",
            "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=[
                "single-active", "single active", "primary", "backup",
                "signaling primary", "aliasing path",
            ],
            required_tags=["HA"],
        ),
        related_cli_cmds=[
            "ethernet-segment", "load-balancing-mode", "service-carving",
        ],
        rfc_refs=["RFC 7432bis §8.5"],
    ),
    Flow(
        id="FLOW-022",
        name="ESI types coverage (Type 0 manual, Type 1 LACP, Type 4 default)",
        summary=(
            "Configure each supported ESI type on a multi-homed ES; verify "
            "both PEs derive identical ESI."
        ),
        setup="Two PEs share an access LAG to one CE; EVI up on both.",
        action=(
            "On both PEs configure each ESI type in turn under `interface "
            "agg-eth-1 ethernet-segment`: (a) `identifier 0 "
            "00:11:22:33:44:55:66:77:88` Type 0 (manual 9-octet hex); "
            "(b) `identifier 1` Type 1 (LACP-derived); (c) no identifier "
            "Type 4 (router-id + ifIndex default)."
        ),
        verify=(
            "`show evpn ethernet-segment` on both PEs shows the same ESI "
            "for each type; ES route advertised; access LAG converges."
        ),
        pass_="Identical ESI on both PEs for each tested type; ES route advertised.",
        fail_on="ESI mismatch between PEs, ES route absent, or LAG fails to come up.",
        equipment="DUT + IXIA + neighbor PE + LACP partner",
        categories=[
            "Basic Functionality", "Packet validation", "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=[
                "esi type", "ethernet segment identifier", "identifier",
                "type 0", "type 1", "type 4",
                "esi and es types", "es types",
            ],
            required_tags=["HA", "CONFIG"],
        ),
        related_cli_cmds=["identifier", "ethernet-segment"],
        rfc_refs=["RFC 7432bis §5"],
    ),
    Flow(
        id="FLOW-030",
        name="Route Type 2 MAC/IP advertisement and learning",
        summary=(
            "MAC learned on access; Type 2 route advertised PE↔PE; remote "
            "PE installs and uses it."
        ),
        # Eyal Ozeri 2026-07-06 (row 768): broaden the Type-2 matrix — MAC-only
        # vs MAC+IP encodings; community / extended-community handling incl.
        # reserved communities; the BUM→unicast label switch once a MAC is
        # learned; and confirming that a MAC moving between two LOCAL ACs on
        # the same PE does NOT trigger a new advertisement.
        setup="Two-PE EVPN up; CE attached to PE1; clean MAC table.",
        action=(
            "(1) Send a known-unicast frame from CE-A (behind PE1) to CE-B "
            "(behind PE2) in three encodings: MAC-only (no IP), IPv4 host "
            "(10.0.0.1 → 10.0.0.2), and IPv6 host (2001:db8::1 → "
            "2001:db8::2); capture the BGP UPDATE on PE↔PE for each. "
            "(2) Re-advertise MAC+IP carrying (a) a standard community, (b) a "
            "non-reserved extended community, and (c) a reserved community, "
            "and once with none. "
            "(3) Before CE-B's MAC is learned, send a frame to it and observe "
            "BUM flooding; then let PE2 learn CE-B via Type 2 and confirm "
            "subsequent frames switch from the BUM/IMET label to the unicast "
            "Type-2 label. "
            "(4) Move CE-A's MAC from one local AC to another local AC on PE1 "
            "and watch the PE↔PE session."
        ),
        verify=(
            "Type 2 NLRI carries: RD + ESI (zero for single-homed) + "
            "Eth-Tag + MAC (length=48) + (optional) IP (0 for MAC-only, "
            "4-byte for IPv4, 16-byte for IPv6 — IP Address Length field "
            "reflects which) + MPLS Label1 [+ Label2] per RFC 7432bis §7.2; "
            "remote PE installs MAC (+ label) for the MAC-only, v4 and v6 "
            "entries; reverse traffic forwards on the learned label. Standard "
            "and extended communities (including reserved ones) are carried / "
            "handled per policy without corrupting the route. Once the MAC is "
            "learned via Type 2, forwarding switches from the BUM/IMET label "
            "to the unicast label. A MAC moving between two LOCAL ACs on PE1 "
            "updates the local forwarding entry but does NOT emit a new Type 2 "
            "advertisement or a MAC-mobility event."
        ),
        pass_=(
            "Type 2 encoded per §7.2 for MAC-only, IPv4 and IPv6; remote "
            "install + bidirectional flow for each; communities (incl. "
            "reserved) handled cleanly; forwarding switches BUM→unicast on "
            "learn; a purely-local interface move triggers no re-advertisement."
        ),
        fail_on=(
            "MAC length ≠ 48, IP Address Length field ≠ 0/32/128, missing "
            "label, malformed RD/ESI, IPv6 host IP not carried, a community "
            "mishandled/corrupted, forwarding stuck on the BUM label after "
            "learning, a local interface move spuriously re-advertising the "
            "MAC, or remote PE drops the route."
        ),
        equipment="DUT + IXIA + neighbor PE",
        categories=[
            "Basic Functionality", "Packet validation",
            "Malformed/unsupported packets", "Feature interaction",
            "PM", "Tech-support",
        ],
        # Eyal Ozeri 2026-07-06 (row 773, "That's type-1"): the L2-Attr /
        # ESI-Label Extended-Community requirements (RFC7432bis §7.5, §7.11;
        # EVPNS-REQ#240) are carried on the Ethernet A-D (Type 1) routes, not
        # Type 2 — those keywords moved to FLOW-032 so the Type-1 content stops
        # landing in this Type-2 flow.
        selector=FlowSelector(
            title_keywords=[
                "mac/ip", "mac advertisement", "type 2", "type-2",
                "address advertisement",
                "lt1", "lt2", "lt3", "lt4", "label type",
                "mac unicast forwarding table", "mac forwarding table",
                "local learning",
                "attribute processing", "nlri processing",
                "forwarding packets received",
                "flow label",
                "domain-wide common block",
            ],
            required_tags=["PROTOCOL", "PACKET"],
        ),
        related_cli_cmds=["advertise-mac", "control-word (evpn)"],
        rfc_refs=["RFC 7432bis §7.2"],
    ),
    Flow(
        id="FLOW-031",
        name="Route Type 3 IMET + ingress-replication BUM",
        summary=(
            "IMET advertises tunnel info; ingress replication delivers "
            "BUM frames to all remote PEs in the EVI."
        ),
        # Eyal Ozeri 2026-07-06: (row 809) show the full IMET lifecycle across
        # all three PEs — each PE that joins the EVI advertises its own Type 3
        # IMET and the others receive and install it, building the
        # ingress-replication flood list; (row 806) be explicit that an
        # unknown-unicast is flooded via that list and the source MAC is
        # learned from the returning/again-seen frame, after which forwarding
        # goes unicast (Type 2) rather than continuing to flood.
        setup=(
            "Three-PE EVPN (PE1, PE2, PE3) all in the same EVI; "
            "ingress-replication PMSI; a BUM source on access at PE1."
        ),
        action=(
            "(1) On EVI join, confirm each PE installs and advertises its own "
            "Type 3 IMET route; verify PE1 installs its own and receives + "
            "installs PE2's and PE3's, building the ingress-replication flood "
            "list. (2) Send a broadcast from PE1's access port; trace "
            "replication on PE1→PE2 and PE1→PE3. (3) Send an unknown-unicast "
            "from PE1; confirm it is flooded to PE2 and PE3 over the IR list, "
            "the destination's MAC is then learned (Type 2), and subsequent "
            "frames to it forward unicast without further flooding."
        ),
        verify=(
            "Each PE's Type 3 NLRI is encoded per §7.3; the PMSI Tunnel "
            "attribute encodes the tunnel type (ingress replication), label, "
            "and tunnel ID; every PE installs every other PE's IMET; broadcast "
            "and unknown-unicast reach each remote PE exactly once (no "
            "duplication); after MAC learning, unknown-unicast to that MAC "
            "stops flooding and forwards on the unicast label."
        ),
        pass_=(
            "All three PEs advertise + install each other's IMET; one copy per "
            "remote PE for BUM; correct PMSI encoding; unknown-unicast "
            "transitions from flooded to unicast once the MAC is learned."
        ),
        fail_on=(
            "A PE fails to advertise or install an IMET, duplicate "
            "replication, missing PMSI Tunnel attribute, wrong tunnel type, "
            "BUM delivered to a non-EVI PE, or unknown-unicast keeps flooding "
            "after the MAC is learned."
        ),
        equipment="DUT + IXIA + neighbor PE",
        categories=[
            "Basic Functionality", "Packet validation",
            "Malformed/unsupported packets", "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=[
                "inclusive multicast", "imet", "type 3", "type-3",
                "bum", "ingress replication", "broadcast",
                "unknown-unicast", "unknown unicast",
                "forwarding unicast", "flooding",
                "pmsi tunnel", "pmsi", "p2mp", "mp2mp",
                "p-tunnel", "forwarding rules",
            ],
            required_tags=["PROTOCOL", "PACKET"],
        ),
        related_cli_cmds=["unknown-mac-flooding"],
        rfc_refs=["RFC 7432bis §7.3", "RFC 7432bis §11"],
    ),
    Flow(
        id="FLOW-032",
        name="Route Type 1 Ethernet A-D (per-ES + per-EVI)",
        summary=(
            "Multi-homed ES advertises Type 1 A-D/ES and A-D/EVI; ESI "
            "Label EC carries split-horizon + signalling bits."
        ),
        setup="Two PEs share a multi-homed CE; ES configured.",
        action=(
            "Bring the ES up; capture BGP UPDATE on PE↔PE for both A-D "
            "variants; inspect ESI Label extended community."
        ),
        verify=(
            "Type 1 NLRI per §7.1; ESI Label EC present and correctly "
            "encoded (split-horizon flag, primary/backup flag, label)."
        ),
        pass_="Type 1 encoded per §7.1 with valid ESI Label EC.",
        fail_on=(
            "Missing ESI Label EC, wrong split-horizon bit, or per-EVI "
            "A-D not advertised."
        ),
        equipment="DUT + IXIA + neighbor PE + LACP partner",
        categories=[
            "Basic Functionality", "Packet validation", "Tech-support",
        ],
        # Eyal Ozeri 2026-07-06 (row 773): L2-Attr / ESI-Label Extended
        # Communities ride on the Ethernet A-D (Type 1) routes — pick up those
        # requirements here (moved off the Type-2 FLOW-030).
        selector=FlowSelector(
            title_keywords=[
                "ethernet a-d", "auto-discovery route",
                "type 1", "type-1", "ad route",
                "l2-attr", "l2 attr", "layer 2 attributes",
                "esi label extended community",
            ],
            required_tags=["PROTOCOL"],
        ),
        rfc_refs=["RFC 7432bis §7.1", "RFC 7432bis §7.5", "RFC 7432bis §7.11"],
    ),
    Flow(
        id="FLOW-033",
        name="Route Type 4 Ethernet Segment route + ES-Import RT",
        summary=(
            "ES route published on each PE that shares the segment; "
            "ES-Import RT EC drives PE→PE auto-peering for that ES."
        ),
        setup="Two PEs share a multi-homed CE.",
        action=(
            "Configure the ES on both PEs; capture the Type 4 NLRI on "
            "PE↔PE; verify ES-Import RT EC presence."
        ),
        verify=(
            "Type 4 NLRI carries RD + ESI + Originator-IP per §7.4; "
            "ES-Import RT EC matches both PEs' import policy; DF election "
            "converges."
        ),
        pass_="Type 4 encoded per §7.4; ES-Import RT EC present; DF converges.",
        fail_on="Missing ES-Import RT EC, malformed Originator-IP, or DF stuck.",
        equipment="DUT + IXIA + neighbor PE",
        categories=[
            "Basic Functionality", "Packet validation", "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=[
                "ethernet segment route", "type 4", "type-4", "es route",
                "es-import",
            ],
            required_tags=["PROTOCOL"],
        ),
        rfc_refs=["RFC 7432bis §7.4"],
    ),
    Flow(
        id="FLOW-040",
        name="MAC Mobility (host moves between PEs)",
        # Eyal Ozeri 2026-07-06 (row 867): the base case is a LOCAL MAC (learned
        # on the DUT's own access) being superseded by a remote Type 2. Add the
        # remote→remote case: from the DUT's viewpoint a MAC first learned via
        # PE1's Type 2 moves and is superseded by PE2's Type 2 — both
        # advertisements are remote to the DUT. Requires a third PE as observer.
        summary=(
            "A MAC moves between PEs; the MAC Mobility EC sequence increments "
            "and the superseded advertisement is withdrawn. Covers both a "
            "local→remote move and a remote(PE1)→remote(PE2) move observed by "
            "a third PE."
        ),
        setup=(
            "Three-PE EVPN (PE1, PE2, and the DUT as observer). Host H1 is "
            "attached to PE1 and learned by all PEs."
        ),
        action=(
            "Case A (local→remote): learn H1 locally on the DUT's access, then "
            "move H1 to PE2; capture PE2's Type 2 and the DUT's local "
            "withdrawal. Case B (remote→remote): with H1 learned by the DUT "
            "via PE1's Type 2, move H1 from PE1 to PE2 (detach from PE1's "
            "access, attach to PE2's; or source from PE2); capture PE2's new "
            "Type 2 advertisement."
        ),
        verify=(
            "In both cases the MAC Mobility EC carries an incremented sequence "
            "number and the superseded advertisement is withdrawn. Case A: the "
            "DUT withdraws its local entry and installs the remote path. "
            "Case B: the DUT replaces PE1's remote route with PE2's remote "
            "route (higher sequence) and its FIB points to PE2 within the "
            "fast-convergence bound; no traffic is sent toward the stale PE1 "
            "path."
        ),
        pass_=(
            "Sequence increments and the older advertisement is withdrawn in "
            "both the local→remote and remote→remote moves; FIB updates "
            "promptly to the new PE."
        ),
        fail_on=(
            "Sequence does not increment, no withdrawal, the DUT keeps the "
            "stale (local or PE1) entry, traffic sent to the old path, or "
            "sticky-MAC flag misapplied."
        ),
        equipment="DUT + IXIA + 2 neighbor PEs",
        categories=[
            "Basic Functionality", "Packet validation", "Robustness",
            "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=[
                "mac mobility", "sticky mac", "mass withdrawal",
                "fast convergence",
            ],
            required_tags=["HA", "PROTOCOL"],
        ),
        related_cli_cmds=[
            "host mac-address-duplication-detection",
            "mac-address-static (EVPN)",
        ],
        rfc_refs=["RFC 7432bis §15", "RFC 7432bis §8"],
    ),
    Flow(
        id="FLOW-041",
        name="MAC duplication detection",
        summary=(
            "Same MAC oscillates between two PEs faster than the "
            "documented threshold; duplication detection raises an alarm "
            "and freezes the entry."
        ),
        setup=(
            "Two-PE EVPN; configure `host mac-address-duplication-detection` "
            "with documented threshold/window."
        ),
        action=(
            "Force a host with the same MAC to oscillate between PE1 and "
            "PE2 access ports faster than the configured threshold."
        ),
        verify=(
            "Detection triggers within the configured window; alarm "
            "raised; MAC frozen at the last-known PE; further moves do "
            "not advertise."
        ),
        pass_="Detection raises alarm; MAC frozen; no further mobility advertisements.",
        fail_on=(
            "No detection, alarm wrong severity, or MAC keeps oscillating "
            "in BGP UPDATEs."
        ),
        equipment="DUT + IXIA + neighbor PE + syslog collector",
        categories=[
            "Basic Functionality", "Packet validation", "Alarms/Logs/Syslog",
            "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=[
                "duplication detection", "duplicate detection",
                "mac duplication", "mac-duplication",
            ],
            required_tags=["MONITORING", "HA"],
        ),
        related_cli_cmds=["host mac-address-duplication-detection"],
        rfc_refs=["RFC 7432bis §15.1"],
    ),
    Flow(
        id="FLOW-050",
        name="Static MAC binding behind EVPN",
        summary=(
            "Static MAC entry advertised across BGP EVPN with the "
            "appropriate sticky flag."
        ),
        setup="Two-PE EVPN; configure a static MAC entry on PE1.",
        action=(
            "On PE1 issue `mac-address-static` for the test MAC bound to "
            "an AC; commit. Observe PE2's MAC table."
        ),
        verify=(
            "Type 2 advertisement carries the static-MAC sticky flag; "
            "remote PE installs as static; mobility for that MAC is "
            "rejected."
        ),
        pass_="Static-MAC sticky flag carried; remote install as static; mobility rejected.",
        fail_on=(
            "Sticky flag missing, mobility accepted for static MAC, or "
            "static entry not advertised."
        ),
        equipment="DUT + IXIA + neighbor PE",
        categories=[
            "Basic Functionality", "Packet validation", "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=["static mac", "mac-address-static"],
            required_tags=["CONFIG"],
        ),
        related_cli_cmds=["mac-address-static (EVPN)"],
        rfc_refs=["RFC 7432bis §15.2"],
    ),
    Flow(
        id="FLOW-060",
        name="Split-horizon enforcement on shared ES",
        summary=(
            "BUM frames carrying an ESI Label that matches the receiver's "
            "own ES are dropped; non-shared-ES BUM is forwarded normally."
        ),
        setup=(
            "Two PEs share an ES to one CE; ESI Label allocated; "
            "ingress-replication tunnel up."
        ),
        action=(
            "Send BUM PE1→PE2 carrying the shared-ES ESI Label; observe "
            "PE2's egress to the access on the shared ES; then send BUM "
            "carrying a different ESI Label."
        ),
        verify=(
            "Shared-ES BUM is dropped on the access (split-horizon); "
            "different-ESI BUM forwards normally."
        ),
        pass_="Split-horizon enforced for shared-ES BUM; non-shared BUM forwarded.",
        fail_on="Shared-ES BUM looped on the LAG, or non-shared BUM dropped.",
        equipment="DUT + IXIA + neighbor PE + LACP partner",
        categories=[
            "Basic Functionality", "Packet validation",
            "Malformed/unsupported packets", "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=[
                "split horizon", "split-horizon", "esi label", "per-es label",
            ],
            required_tags=["PROTOCOL", "PACKET"],
        ),
        rfc_refs=["RFC 7432bis §8.3"],
    ),
    Flow(
        id="FLOW-061",
        name="Aliasing / backup-path on multi-homed CE",
        summary=(
            "Known-unicast load-shares to the multi-homed MAC across both "
            "PEs (all-active) or follows DF (single-active); failover "
            "uses backup path within ≤ 1 s (RFC 7432bis §8 fast-"
            "convergence target)."
        ),
        setup=(
            "Multi-homed CE on PE1 and PE2; remote PE3 has known-unicast "
            "to a MAC behind both PEs."
        ),
        action=(
            "From PE3, send known-unicast to the multi-homed MAC; observe "
            "load-share or single-path. Flap PE1; observe failover."
        ),
        verify=(
            "Traffic load-shared per documented mode (all-active) or "
            "carried by DF only (single-active); on flap, backup path "
            "takes over within ≤ 1 s (RFC 7432bis §8 fast-convergence "
            "target)."
        ),
        pass_=(
            "Load-share or backup-path per spec; failover within ≤ 1 s; "
            "no duplicated frames on the access during the failover window."
        ),
        fail_on=(
            "Black-hole during failover, no load-share, wrong PE receives, "
            "or convergence > 1 s."
        ),
        equipment="DUT + IXIA + neighbor PE",
        categories=[
            "Basic Functionality", "Packet validation", "Robustness", "HA",
            "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=[
                "aliasing", "backup path", "backup-path",
                "route prioritization",
                "best path selection for mac/ip",
                "best path selection for ethernet a-d",
                "best path selection for inclusive multicast",
            ],
            explicit_req_ids=["EVPNS-REQ#200"],  # bare "Best Path Selection"
            required_tags=["HA"],
        ),
        rfc_refs=["RFC 7432bis §8.4"],
    ),
    Flow(
        id="FLOW-070",
        name="3rd-party BGP EVPN interop (capability + route exchange)",
        summary=(
            "Bring up a BGP EVPN session against a 3rd-party PE "
            "(Cisco/Juniper); both sides exchange L2VPN-EVPN AFI/SAFI."
        ),
        setup=(
            "Exaware DUT + 3rd-party PE physically connected; routing-policy "
            "permits L2VPN-EVPN."
        ),
        # Eyal Ozeri 2026-07-06 (row 991): also drive the DUT with unsupported
        # / possibly-proprietary content — unknown BGP capabilities in OPEN,
        # unknown/vendor extended communities and unknown attributes on EVPN
        # routes, and unknown EVPN route types — and confirm the DUT degrades
        # gracefully (RFC 7606 attribute handling; unknown-capability
        # negotiation) rather than resetting the session or corrupting state.
        action=(
            "Configure `af-l2vpn evpn` neighbor on DUT and the symmetric "
            "config on the 3rd party. Bring the session up; capture OPEN "
            "messages on both sides; advertise routes from each side. Then "
            "have the 3rd party (or IXIA) send: (1) an OPEN advertising an "
            "unknown/optional capability; (2) EVPN routes carrying an unknown "
            "extended community and an unknown optional-transitive attribute; "
            "(3) an unknown/unsupported EVPN route type."
        ),
        verify=(
            "Both sides advertise the L2VPN-EVPN AFI/SAFI capability; session "
            "reaches Established; routes from each side install into the "
            "other's RIB; encapsulation is interoperable. Unknown optional "
            "capabilities are ignored without tearing the session; unknown "
            "optional-transitive attributes are preserved and passed through, "
            "malformed ones are handled per RFC 7606 (attribute-discard / "
            "treat-as-withdraw, not session reset); an unknown EVPN route type "
            "is ignored without dropping the known routes."
        ),
        pass_=(
            "Capability exchanged; session up; known routes installed "
            "bidirectionally; unknown capabilities/communities/attributes/"
            "route-types handled gracefully with no session reset or state "
            "corruption."
        ),
        fail_on=(
            "Missing capability, NOTIFICATION on OPEN, a valid route rejected, "
            "encoding mismatch on the wire, or the DUT resets the session / "
            "corrupts state on an unknown capability, attribute, community, or "
            "route type."
        ),
        equipment="DUT + 3rd-party PE (Cisco/Juniper) + IXIA",
        categories=[
            "Basic Functionality", "3rd Party Interoperability",
            "Packet validation", "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=[
                "interoperability", "interop", "capability",
                "open message", "negotiat",
            ],
            required_tags=["PROTOCOL"],
        ),
        related_cli_cmds=["af-l2vpn evpn"],
        rfc_refs=["RFC 7432bis §6"],
    ),
    Flow(
        id="FLOW-080",
        name="Scale to the configured mac-limit ceiling",
        # Eyal Ozeri 2026-07-06 ("Where are these values taken from?"): the
        # only scale figure the source docs actually give is `mac-limit` (EVPN
        # CLI doc: default 65520 ≈ 64K, configurable 1..250000). That is the
        # ceiling this test drives. EVI and multi-homed-ES counts are NOT in
        # the SFS/CLI — they are platform-datasheet numbers, so they are called
        # out as placeholders to confirm per platform, not asserted as
        # documented limits.
        summary=(
            "Advertise/install MACs up to the configured `mac-limit` ceiling "
            "(EVPN CLI doc: default 65520, max 250000) — driven here at the "
            "65520 default; hold for ≥ 5 min; verify CPU < 70%, memory growth "
            "< 5%, and per-route convergence ≤ 2× baseline. (EVI / multi-homed-"
            "ES scale counts are platform-datasheet placeholders — confirm per "
            "platform.)"
        ),
        setup=(
            "Two-PE topology + IXIA scale rig. `mac-limit 65520` (the "
            "documented default) configured on the EVI under test; the same "
            "test re-run at `mac-limit 250000` (documented max) where the "
            "platform datasheet permits. Baseline CPU and memory snapshot "
            "taken at idle."
        ),
        action=(
            "Use IXIA to advertise unique MACs up to the configured "
            "`mac-limit` into the EVI at a rate of 1K MACs/s; hold the table "
            "at ceiling for ≥ 5 min; while at scale, advertise one additional "
            "MAC then withdraw it to measure incremental convergence."
        ),
        verify=(
            "`show evpn mac address-table count` reaches the configured "
            "`mac-limit` without rejecting entries below it; `show platform "
            "process cpu` stays ≤ 70% 5-min average; `show platform process "
            "memory` grows by ≤ 5% over the run; incremental advertise/"
            "withdraw converges in ≤ 2× the idle baseline (measured by IXIA's "
            "first-packet-with-new-MAC timestamp)."
        ),
        pass_=(
            "The configured `mac-limit` ceiling is reached; CPU ≤ 70%; memory "
            "growth ≤ 5%; incremental convergence ≤ 2× baseline; zero entries "
            "rejected below the ceiling; the (limit+1)th MAC is rejected per "
            "the documented mac-limit behaviour."
        ),
        fail_on=(
            "Crash, OOM, entries rejected below the configured `mac-limit`, "
            "CPU > 70% sustained, memory growth > 5%, or per-route convergence "
            "> 2× baseline at scale."
        ),
        equipment="Two routers + IXIA scale rig (≥ 250K MAC generation)",
        # Eyal Ozeri 2026-06-21: rows 1463-66 (Performance / Long-run overlays)
        # were unclear and redundant with the Scale test itself and with the
        # dedicated FLOW-120 (Long-run / Performance). Keep this flow to its
        # actual purpose — Scale.
        categories=["Scale"],
        selector=FlowSelector(
            title_keywords=[
                "mac-limit", "mac limit", "scale", " limit ", "max ",
                "long run",
            ],
            desc_keywords=["scale", "limit"],
            required_tags=["SCALE"],
        ),
        related_cli_cmds=["mac-limit", "mac-aging-time"],
        rfc_refs=[],
        coverage_driven=True,
    ),
    Flow(
        id="FLOW-090",
        name="Control-plane recovery under load",
        summary=(
            "Kill the EVPN control-plane process while the feature is "
            "active under traffic; verify auto-recovery (process restart "
            "≤ 5 s, BGP re-establish ≤ 30 s) and ≤ 1 s data-plane outage."
        ),
        # Eyal Ozeri 2026-07-06 (row 1014, "Where is the 'load'?"): make the
        # traffic load explicit and central — the whole point of this flow is
        # recovery *under load*, so a steady IXIA rate runs throughout and the
        # data-plane outage is measured against it.
        setup=(
            "Single-router topology with EVPN service active. IXIA drives a "
            "steady bidirectional load of ≥ 500 Mbps known-unicast across the "
            "EVPN service for ≥ 1 min to establish steady state; this load "
            "keeps running for the whole test."
        ),
        action=(
            "With the IXIA load still running, kill the EVPN-related "
            "control-plane process via the platform debug command; let the "
            "supervisor restart it. Do not stop or pause the offered load at "
            "any point."
        ),
        verify=(
            "Process restarts within ≤ 5 s of SIGKILL; BGP EVPN session "
            "re-establishes within ≤ 30 s; under the sustained IXIA load the "
            "data-plane keeps forwarding (IXIA measures ≤ 1 s of zero-bps "
            "outage on the access port, and no reordering/duplication of the "
            "in-flight load)."
        ),
        pass_=(
            "Process restarts in ≤ 5 s; data-plane outage ≤ 1 s; BGP EVPN "
            "session re-establishes in ≤ 30 s."
        ),
        fail_on=(
            "Full outage > 1 s, no auto-recovery, BGP session not "
            "re-established within 30 s, or feature stuck after recovery."
        ),
        equipment="DUT + IXIA traffic gen (process-kill harness)",
        categories=[
            "Robustness", "HA", "Long run", "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=[
                "robustness", "high availability", "process kill",
                "pe-to-ce network failure", "network failure",
                "route resolution",
            ],
            desc_keywords=["robustness", "process kill", "recover"],
            required_tags=["HA"],
        ),
        rfc_refs=[],
    ),
    Flow(
        id="FLOW-091",
        name="Configuration persistence across reload + upgrade",
        summary=(
            "Saved EVPN configuration (incl. ES, EVI, route-targets) "
            "survives a full reload and a software upgrade."
        ),
        setup=(
            "DUT with the canonical EVPN service configured; configuration "
            "saved; upgrade image staged on ONIE server."
        ),
        action=(
            "Reload the DUT; verify replay. Then run onie-install to the "
            "next image; reload onto the new image."
        ),
        verify=(
            "After reload (and upgrade) the EVPN configuration replays "
            "byte-identically; service comes up; BGP session re-establishes; "
            "MAC learning resumes."
        ),
        pass_="Configuration persists across reload + upgrade; service auto-resumes.",
        fail_on=(
            "Config lost on reload, image-upgrade rolls back, or feature "
            "regression on the new image."
        ),
        equipment="DUT + ONIE image server",
        categories=[
            "Upgrade", "Basic Functionality", "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=["upgrade", "reload", "persistence"],
            desc_keywords=["upgrade", "reload"],
            required_tags=[],
            explicit_req_ids=[],
        ),
        rfc_refs=[],
        coverage_driven=True,
    ),
    Flow(
        id="FLOW-092",
        name="Manage EVPN over NETCONF/YANG",
        summary=(
            "Configure the EVPN feature entirely via NETCONF; verify "
            "CLI/NETCONF view consistency."
        ),
        setup="DUT bare; NETCONF client (e.g. ncclient) authenticated.",
        action=(
            "Push the canonical EVPN configuration via NETCONF using the "
            "vendor YANG model; commit. Issue equivalent CLI `show` and "
            "compare with NETCONF `<get-config>`."
        ),
        verify=(
            "NETCONF configuration matches CLI behaviour; both transports "
            "show the same running-config; capability advertised in hello."
        ),
        pass_="NETCONF and CLI consistent; capability advertised.",
        fail_on=(
            "Schema gap, NETCONF rejects valid config, or CLI/NETCONF view "
            "diverges."
        ),
        equipment="DUT + NETCONF client (e.g. ncclient)",
        categories=[
            "Management", "Basic Functionality",
        ],
        selector=FlowSelector(
            title_keywords=["netconf", "yang", "management"],
            desc_keywords=["netconf", "yang"],
            required_tags=[],
        ),
        rfc_refs=[],
        coverage_driven=True,
    ),
    Flow(
        id="FLOW-100",
        name="Alarm / syslog generation on EVPN error conditions",
        summary=(
            "Each documented EVPN alarm condition (e.g. MAC duplication, "
            "ES inconsistency, peer down) raises the right severity, "
            "syslog entry, and clears on resolution."
        ),
        setup=(
            "EVPN running; syslog collector configured; documented alarm "
            "conditions primed."
        ),
        action=(
            "Trigger each alarm-bearing event in turn (e.g. force MAC "
            "duplication, peer flap, mismatched DF algorithm)."
        ),
        verify=(
            "Each event raises an alarm at the right severity; structured "
            "syslog entry emitted; alarm clears when condition is resolved."
        ),
        pass_="Per-event: correct severity + syslog entry; clears on resolution.",
        fail_on=(
            "No alarm, wrong severity, missing syslog entry, or stuck "
            "alarm after resolution."
        ),
        equipment="DUT + syslog collector",
        categories=[
            "Alarms/Logs/Syslog", "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=["alarm", "syslog", "log "],
            desc_keywords=["alarm", "syslog"],
            required_tags=["MONITORING"],
        ),
        rfc_refs=[],
    ),
    Flow(
        id="FLOW-110",
        name="On-the-fly EVPN parameter change under traffic",
        summary=(
            "Modify EVPN parameters (RT, service-type, load-balancing, DF "
            "preference) while traffic flows; verify zero loss and "
            "reconvergence."
        ),
        setup=(
            "Steady IXIA traffic for ≥ 1 minute through the canonical EVPN "
            "service."
        ),
        # Eyal Ozeri 2026-07-06: (row 1064) spell the live-modification
        # examples out concretely; (row 1065) adding an import-rt must pull in
        # the now-matching remote routes — verify the Type 2 (MAC/IP) and
        # Type 3 (IMET) routes carrying that RT are imported and installed,
        # and withdrawn again when the import-rt is removed.
        action=(
            "Modify a parameter live, one change at a time, committing each: "
            "(1) add a second `import-rt 65000:2` to the EVI; "
            "(2) switch `load-balancing-mode` all-active ↔ single-active; "
            "(3) change DF `preference`; (4) change `es-waiting-time`. After "
            "each, revert it. For the import-rt case, a remote PE is "
            "advertising Type 2/3 routes tagged with `65000:2`."
        ),
        verify=(
            "IXIA reports zero or near-zero loss during each change; "
            "`show configuration` reflects the new value within ≤ 1 s; "
            "feature reconverges without service flap. When `import-rt "
            "65000:2` is added, the matching remote Type 2 (MAC/IP) and "
            "Type 3 (IMET) routes are imported and installed "
            "(`show bgp l2vpn evpn`, `show evpn mac address-table`); when it "
            "is removed, those routes are withdrawn from the EVI."
        ),
        pass_=(
            "Each modification applies without service interruption; adding "
            "the import-rt installs the matching remote Type 2/3 routes and "
            "removing it withdraws them."
        ),
        fail_on=(
            "Traffic loss > 0 packets on a documented hitless change, new "
            "config not active within 1 s, or adding/removing the import-rt "
            "fails to install/withdraw the matching Type 2/3 routes."
        ),
        equipment="DUT + IXIA + neighbor PE",
        categories=[
            "On The Fly changes", "Basic Functionality", "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=["on the fly", "on-the-fly"],
            required_tags=["CONFIG"],
        ),
        rfc_refs=[],
        coverage_driven=True,
    ),
    Flow(
        id="FLOW-120",
        name="Long-run stability under steady traffic",
        summary=(
            "Run the canonical EVPN service for ≥ 24 hours under steady "
            "traffic; verify no leaks, no functional regression, monotonic "
            "counters."
        ),
        setup=(
            "Two-PE EVPN service configured; IXIA generating mixed steady "
            "traffic profile."
        ),
        action=(
            "Hold the run for ≥ 24 hours. Sample `show platform process "
            "memory` hourly."
        ),
        verify=(
            "No memory growth (`show platform process memory` flat); no "
            "functional regression; counters monotonic; alarm log clean."
        ),
        pass_="No leaks; no regression; counters monotonic over 24 h.",
        fail_on=(
            "Memory growth, counter freeze, alarm-spam, or functional "
            "drift over the run."
        ),
        equipment="DUT + IXIA continuous traffic (≥ 24 h)",
        categories=[
            "Long run", "Performance", "PM", "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=["long run", "24 hour", "stability"],
            desc_keywords=["long-run", "long run", "stability"],
            required_tags=[],
        ),
        rfc_refs=[],
        coverage_driven=True,
    ),

    # ── EVI-to-EVI MPLS transport / tunnel interconnect ────────────────
    # Aleksey Burger (SW review, 2026-06-04) flagged that the TP exercised
    # EVPN service/route behaviour but never the *transport* underneath it:
    # how one EVI reaches a remote EVI across the MPLS backbone. These six
    # flows are derived from RFC 4364 (BGP/MPLS IP VPNs) §10 transport and
    # inter-AS procedures, which the EVPN SFS cites but the engine never
    # ingested (surfaced by the RFC cross-check, see rfc_crosscheck.py).
    # They are coverage-driven: RFC 4364 is not in the ingested catalog, so
    # no req-ID anchors them, but the transport behaviour must be tested.
    # Each summary states the problem tested + the method, per Aleksey's
    # "describe what the test case is" ask.
    Flow(
        id="FLOW-130",
        name="EVI-to-EVI Direct Path (PHP) connection",
        summary=(
            "Problem: validate that EVI-to-EVI traffic forwards correctly "
            "when the penultimate LSR pops the transport label (penultimate-"
            "hop popping), so the egress PE receives the frame carrying only "
            "the EVPN service label. Method: build a 3-node PE1–P–PE2 MPLS "
            "path, advertise implicit-null from PE2, drive EVPN unicast/BUM "
            "across it, and confirm the P node pops the transport label and "
            "the egress PE forwards on the service label alone."
        ),
        # Eyal Ozeri 2026-07-06 (row 1075): also exercise explicit-null.
        # implicit-null (label 3) → P node POPs the transport label (true PHP);
        # explicit-null (label 0) → P node SWAPs to label 0, so the egress PE
        # receives a two-label stack (explicit-null over the service label),
        # preserving the transport EXP/QoS to the egress. Both are valid
        # signalling choices and must be tested.
        setup=(
            "Three-node MPLS path PE1–P–PE2; LDP or RSVP-TE LSPs up; BGP "
            "EVPN session PE1↔PE2. One EVI (`evi-1`) up on both PEs with a "
            "single-homed CE on each side. The test is run twice: (A) PE2 "
            "advertises implicit-null (label 3) for its loopback so the P node "
            "performs PHP; (B) PE2 advertises explicit-null (label 0) so the P "
            "node swaps to the explicit-null label."
        ),
        action=(
            "For each variant, confirm the label PE2 signals for its loopback "
            "FEC. From IXIA, send known-unicast then BUM EVPN traffic CE1→CE2 "
            "for ≥ 60 s. On the P node, inspect the label operation for PE2's "
            "FEC; on PE2, capture the received frame's label stack."
        ),
        verify=(
            "Variant A (implicit-null): the P node shows a POP (not SWAP) for "
            "PE2's loopback FEC and the frame arriving at PE2 carries exactly "
            "one label (the EVPN service/VPN label). Variant B (explicit-"
            "null): the P node SWAPs to label 0 and the frame arriving at PE2 "
            "carries a two-label stack — explicit-null (0) over the service "
            "label — with the transport EXP preserved. In both variants "
            "`show evpn evi evi-1` on PE2 learns the remote MAC and IXIA "
            "receives frames on the far port at line rate."
        ),
        pass_=(
            "implicit-null → penultimate P node pops the transport label and "
            "the egress PE forwards on the single service label; explicit-null "
            "→ P node swaps to label 0 and the egress PE forwards the "
            "explicit-null-over-service stack; bidirectional EVPN traffic "
            "passes with ≤ 0 drops over the steady-state window in both."
        ),
        fail_on=(
            "For implicit-null: P node swaps instead of pops, or egress PE "
            "receives a two-label stack. For explicit-null: P node pops or "
            "swaps to the wrong label, or EXP is not preserved. Either "
            "variant: frames black-holed or service label mis-bound."
        ),
        equipment="DUT (PE) + P router + neighbor PE + IXIA",
        categories=[
            "Basic Functionality", "Packet validation",
            "Feature interaction", "Tech-support",
        ],
        selector=FlowSelector(),
        related_cli_cmds=["show evpn evi"],
        rfc_refs=["RFC 4364 §10", "RFC 7432bis §5.1.3 (transport)"],
        coverage_driven=True,
    ),
    Flow(
        id="FLOW-131",
        name="EVI-to-EVI connection over Single MPLS Tunnel",
        summary=(
            "Problem: validate the baseline case where a remote EVI is "
            "reached over exactly one MPLS tunnel (single LSP) between the "
            "two PEs — EVPN routes must resolve their next-hop over that "
            "tunnel and forward end to end. Method: pin a single LSP PE1→PE2, "
            "bring up the EVI, confirm MAC/IP (Type 2) and IMET (Type 3) "
            "routes resolve over the tunnel, and drive traffic across it."
        ),
        setup=(
            "Two-PE topology with exactly one MPLS tunnel (LDP or single "
            "RSVP-TE LSP) PE1→PE2 and its reverse; BGP EVPN up; `evi-1` up "
            "on both PEs with single-homed CEs."
        ),
        action=(
            "Confirm a single LSP exists to PE2's loopback (`show mpls lsp`). "
            "Bring the EVI up; from IXIA send bidirectional known-unicast and "
            "BUM EVPN traffic for ≥ 60 s. Inspect how each EVPN route "
            "resolves its forwarding next-hop."
        ),
        verify=(
            "`show bgp l2vpn evpn` shows Type 2/Type 3 routes resolving over "
            "the single tunnel; `show route table inet.3` shows one entry to "
            "PE2's loopback; `show mpls forwarding-table` binds the EVPN "
            "service label onto that LSP. IXIA receives all offered frames "
            "on the far port."
        ),
        pass_=(
            "EVPN routes resolve over the single tunnel; bidirectional "
            "traffic forwarded with ≤ 0 drops; service label correctly "
            "stacked over the transport label."
        ),
        fail_on=(
            "Route fails to resolve next-hop, traffic black-holed, label "
            "stack malformed, or EVI never reaches up over the tunnel."
        ),
        equipment="DUT + IXIA + neighbor PE over a single MPLS LSP",
        categories=[
            "Basic Functionality", "Packet validation",
            "Performance", "Tech-support",
        ],
        selector=FlowSelector(),
        related_cli_cmds=["show bgp l2vpn evpn",
                          "show route table inet.3"],
        rfc_refs=["RFC 4364 §10"],
        coverage_driven=True,
    ),
    Flow(
        id="FLOW-132",
        name="EVI-to-EVI connection over Backup MPLS Tunnel Failover",
        summary=(
            "Problem: validate that EVI-to-EVI traffic survives a primary "
            "MPLS tunnel failure by failing over to a pre-signalled backup "
            "tunnel with sub-second loss. Method: configure a primary and a "
            "backup LSP (FRR / secondary path) PE1→PE2, run steady traffic, "
            "fail the primary (link/LSP down), and measure failover time and "
            "loss while the EVPN service stays up."
        ),
        # Eyal Ozeri 2026-07-06 (row 1092): run the failover across the four
        # transport-protection variants — LDP with FRR (IGP LFA / remote-LFA)
        # and without FRR (bare LDP, relying on IGP reconvergence); RSVP-TE
        # with protection (facility / one-to-one backup) and without. The
        # EVPN service must survive all four; only the outage bound differs.
        setup=(
            "Two-PE topology with redundant MPLS core paths to PE2's loopback; "
            "BGP EVPN up; `evi-1` up on both PEs; IXIA traffic running on the "
            "data path for ≥ 1 minute. The test is repeated for four transport "
            "protection variants: (1) LDP with FRR (IGP LFA / remote-LFA); "
            "(2) LDP without FRR; (3) RSVP-TE with FRR/protection (facility or "
            "one-to-one backup); (4) RSVP-TE without protection."
        ),
        action=(
            "For each protection variant, while IXIA traffic flows, fail the "
            "primary tunnel (down the primary core link or the primary LSP). "
            "Watch the IXIA loss histogram. Restore the primary and observe "
            "revert behaviour."
        ),
        verify=(
            "On failure, traffic moves onto the backup path — the protected "
            "variants (LDP FRR, RSVP protection) cut over locally; the "
            "unprotected variants converge via IGP/RSVP re-signalling. In all "
            "four the EVPN service does not flap (`show evpn evi evi-1` stays "
            "up, remote MAC retained). IXIA loss histogram records the outage "
            "window per variant. On primary restore, traffic reverts (or "
            "holds, per policy) without a second outage."
        ),
        pass_=(
            "Failover completes in every variant with the EVPN service up and "
            "no MAC re-learn storm; data-path outage ≤ 50 ms for the protected "
            "variants (LDP FRR / RSVP protection) and within the IGP/RSVP "
            "reconvergence bound (≤ a few seconds) for the unprotected "
            "variants; clean revert on restore."
        ),
        fail_on=(
            "Traffic black-holed after primary failure in any variant, a "
            "protected variant exceeds its sub-50 ms bound, the EVPN service "
            "flaps, or revert causes a second outage."
        ),
        equipment="DUT + IXIA + neighbor PE + redundant MPLS core paths",
        # Eyal Ozeri 2026-06-21/29: the HA overlay here generated a control-
        # plane process kill/restart (the "Identify the relevant control-plane
        # process" / "Kill the process" rows Eyal flagged) — that belongs in
        # dedicated control-plane-recovery testing, not in a topology/protection
        # (tunnel-failover) flow. Tunnel failover IS the HA aspect of this flow,
        # and the process-kill case is already covered by FLOW-090 (Control-
        # plane recovery). Drop the HA overlay entirely; keep Basic Functionality.
        categories=["Basic Functionality"],
        selector=FlowSelector(),
        related_cli_cmds=["show evpn evi"],
        rfc_refs=["RFC 4364 §10"],
        coverage_driven=True,
    ),
    Flow(
        id="FLOW-133",
        name="EVI-to-EVI connection over ECMP Tunnel-Set",
        summary=(
            "Problem: validate that EVI-to-EVI traffic load-balances across "
            "an equal-cost set of MPLS tunnels without reordering within a "
            "flow, and rebalances when a member is added or removed. Method: "
            "build N equal-cost LSPs PE1→PE2 as a tunnel-set, send many "
            "distinct IXIA flows, and verify per-flow hashing spreads load "
            "across members while keeping each flow on one member."
        ),
        setup=(
            "Two-PE topology with N (≥ 2) equal-cost MPLS tunnels PE1→PE2 "
            "forming an ECMP tunnel-set; BGP EVPN up; `evi-1` up on both "
            "PEs; IXIA configured to emit many distinct 5-tuple flows."
        ),
        action=(
            "From IXIA, emit ≥ 256 distinct EVPN-encapsulated flows across "
            "the EVI for ≥ 60 s. Sample per-tunnel byte counters. Then "
            "remove one tunnel-set member and re-sample; re-add it and "
            "re-sample."
        ),
        verify=(
            "`show mpls forwarding-table` shows the EVPN service label load-"
            "balanced across the tunnel-set members; per-member counters are "
            "non-zero and roughly even (within ±20%). Each individual flow "
            "stays pinned to one member (no intra-flow reordering observed "
            "at IXIA). On member removal, its flows redistribute over the "
            "survivors with only transient loss; on re-add, load rebalances."
        ),
        pass_=(
            "Load spread across all members (±20%); no intra-flow "
            "reordering; member add/remove rebalances with only transient "
            "loss; no black-hole."
        ),
        fail_on=(
            "All traffic pinned to one member, intra-flow reordering, "
            "persistent loss after member change, or polarised hashing."
        ),
        equipment="Two routers + IXIA scale rig + ECMP MPLS core",
        categories=[
            "Basic Functionality", "Packet validation",
            "Performance", "Feature interaction", "Tech-support",
        ],
        selector=FlowSelector(),
        related_cli_cmds=["show evpn evi"],
        rfc_refs=["RFC 4364 §10"],
        coverage_driven=True,
    ),
    Flow(
        id="FLOW-134",
        name="EVI-to-EVI over Multi-AS Backbone — Case B (ASBR VPN-route exchange)",
        summary=(
            "Problem: validate EVI-to-EVI connectivity across two ASes using "
            "RFC 4364 §10 inter-AS Option B, where ASBRs exchange EVPN/VPN "
            "routes over MP-eBGP, rewrite next-hop to themselves, and "
            "swap the VPN label hop-by-hop (no end-to-end inter-AS LSP). "
            "Method: connect ASBR1↔ASBR2 with MP-eBGP for L2VPN-EVPN, bring "
            "up an EVI spanning PE(AS1) and PE(AS2), and verify routes and "
            "labels are rewritten at the ASBR and traffic crosses the AS "
            "boundary."
        ),
        setup=(
            "Two ASes: PE1–ASBR1 in AS1, PE2–ASBR2 in AS2; ASBR1↔ASBR2 "
            "back-to-back MP-eBGP session carrying the L2VPN-EVPN AFI/SAFI "
            "(Option B). Intra-AS LSPs up on each side; `evi-1` up on PE1 "
            "and PE2 with single-homed CEs."
        ),
        action=(
            "Verify the ASBR↔ASBR eBGP EVPN session is up. From IXIA, send "
            "bidirectional EVPN unicast CE1→CE2 for ≥ 60 s. On each ASBR, "
            "inspect the received vs. re-advertised EVPN routes and the "
            "label rewrite."
        ),
        verify=(
            "On ASBR1, `show bgp l2vpn evpn` shows PE2's routes received "
            "from ASBR2 with ASBR2 as next-hop; ASBR1 re-advertises them to "
            "PE1 with itself as next-hop and a locally-allocated VPN label. "
            "`show mpls forwarding-table` on the ASBR shows a per-prefix "
            "label SWAP at the AS boundary. End-to-end EVPN unicast "
            "forwards; IXIA receives frames on the far port."
        ),
        pass_=(
            "ASBRs exchange EVPN routes over MP-eBGP, rewrite next-hop and "
            "swap the VPN label per Option B; end-to-end EVI traffic "
            "forwards across the AS boundary with ≤ 0 drops."
        ),
        fail_on=(
            "ASBR fails to re-advertise EVPN routes, next-hop/label not "
            "rewritten, route rejected at the AS boundary, or traffic "
            "black-holed inter-AS."
        ),
        equipment="DUT + 2nd PE + two ASBRs (MP-eBGP back-to-back) + IXIA",
        categories=[
            "Basic Functionality", "Packet validation",
            "3rd Party Interoperability", "Tech-support",
        ],
        selector=FlowSelector(),
        related_cli_cmds=["show bgp l2vpn evpn"],
        rfc_refs=["RFC 4364 §10 (Option B)"],
        coverage_driven=True,
    ),
    Flow(
        id="FLOW-135",
        name="EVI-to-EVI over Multi-AS Backbone — Case C (multihop eBGP + labeled-unicast)",
        summary=(
            "Problem: validate EVI-to-EVI connectivity across two ASes using "
            "RFC 4364 §10 inter-AS Option C, where PE loopbacks are made "
            "reachable across ASes via labeled BGP IPv4 unicast (RFC 8277 / "
            "BGP-LU) at the ASBRs, and EVPN routes are exchanged directly "
            "between PEs/RRs over multihop eBGP — yielding an end-to-end LSP. "
            "Method: distribute PE loopbacks as labeled-unicast across the "
            "ASBRs, run multihop MP-eBGP for EVPN between the ASes, bring up "
            "a cross-AS EVI, and verify an end-to-end LSP carries the traffic."
        ),
        setup=(
            "Two ASes with PE1 (AS1) and PE2 (AS2); ASBR1↔ASBR2 exchange "
            "labeled IPv4 unicast (BGP-LU) for the PE loopbacks; a multihop "
            "MP-eBGP session (PE/RR-to-PE/RR) carries L2VPN-EVPN (Option C). "
            "`evi-1` up on PE1 and PE2 with single-homed CEs."
        ),
        action=(
            "Verify PE2's loopback is reachable from PE1 over a labeled-"
            "unicast LSP and the multihop EVPN session is up. From IXIA, "
            "send bidirectional EVPN unicast CE1→CE2 for ≥ 60 s. Inspect the "
            "end-to-end label stack at PE1."
        ),
        verify=(
            "`show route table inet.3` on PE1 shows PE2's loopback resolved "
            "via the BGP-LU LSP across the ASBRs; `show bgp l2vpn evpn` "
            "shows PE2's EVPN routes received over multihop eBGP with PE2 "
            "(not the ASBR) as next-hop. The frame leaving PE1 carries a "
            "transport (BGP-LU) label plus the EVPN service label "
            "(two-label stack). End-to-end EVPN unicast forwards; IXIA "
            "receives frames on the far port."
        ),
        pass_=(
            "PE loopbacks reachable via labeled-unicast across ASBRs; EVPN "
            "routes exchanged PE-to-PE over multihop eBGP; end-to-end LSP "
            "carries the EVI traffic across the AS boundary with ≤ 0 drops."
        ),
        fail_on=(
            "PE loopback unreachable inter-AS, multihop EVPN session fails, "
            "next-hop incorrectly rewritten at the ASBR, end-to-end LSP not "
            "formed, or traffic black-holed."
        ),
        equipment="DUT + 2nd PE + two ASBRs (BGP-LU) + multihop eBGP + IXIA",
        categories=[
            "Basic Functionality", "Packet validation",
            "3rd Party Interoperability", "Tech-support",
        ],
        selector=FlowSelector(),
        related_cli_cmds=["show route table inet.3", "show bgp l2vpn evpn"],
        rfc_refs=["RFC 4364 §10 (Option C)", "RFC 8277"],
        coverage_driven=True,
    ),
]


# ─── Selection ─────────────────────────────────────────────────────────

_NORMALIZE_RE = re.compile(r"[^\w\s/-]+")


def _normalize(text: str) -> str:
    return _NORMALIZE_RE.sub(" ", (text or "").lower())


def reqs_for_flow(flow: Flow, reqs: list[Requirement]) -> list[Requirement]:
    """Return the subset of `reqs` that this flow exercises.

    Matching rules:
      - explicit_req_ids always match.
      - title_keywords match if any keyword is a substring of req.title.
      - desc_keywords match only when at least one of required_tags is
        present on the requirement (gates desc-only matches against
        keyword bleed).
    """
    sel = flow.selector
    out: list[Requirement] = []
    for r in reqs:
        if r.req_id in sel.explicit_req_ids:
            out.append(r)
            continue
        title_lc = _normalize(r.title)
        desc_lc = _normalize(r.description)
        if any(kw.lower() in title_lc for kw in sel.title_keywords):
            out.append(r)
            continue
        if sel.desc_keywords and sel.required_tags:
            tag_match = any(t in r.tags for t in sel.required_tags)
            if tag_match and any(kw.lower() in desc_lc
                                 for kw in sel.desc_keywords):
                out.append(r)
                continue
    return out


def build_coverage(flows: list[Flow], reqs: list[Requirement]
                   ) -> tuple[dict[str, list[str]], list[str]]:
    """Compute (req_id → covering flow_ids, orphan_req_ids).

    Orphans are spec/RFC requirements that no flow claims; the Coverage
    sheet flags them so the user can extend the catalog.
    """
    cov: dict[str, list[str]] = {r.req_id: [] for r in reqs}
    for flow in flows:
        for r in reqs_for_flow(flow, reqs):
            cov[r.req_id].append(flow.id)
    orphans = [rid for rid, fids in cov.items() if not fids]
    return cov, orphans

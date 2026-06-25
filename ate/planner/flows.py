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
        verify=(
            "`show evpn evi evi-1` reports the EVI up; access AC bound; "
            "MAC table populates from data-plane learning; tcpdump on PE↔PE "
            "shows MAC/IP (Type 2) and IMET (Type 3) routes; IXIA receives "
            "frames on the far port at line rate (≥ 0.99 Gbps for a 1 Gbps "
            "offered load)."
        ),
        pass_=(
            "EVI up within ≤ 10 s of commit; routes installed; bidirectional "
            "unicast forwarded; MAC table reflects learned MACs; ≤ 0 packet "
            "drops over the 60 s steady-state window."
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
                "bgp common cli",
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
        name="Access-interface variants on EVPN AC (Q-in-Q, Sub-if, vlan-range, agg-eth, x-eth)",
        summary=(
            "Bind the EVPN AC to each documented access-interface form — "
            "x-eth, Sub-if (single-tagged), Q-in-Q (double-tagged), "
            "agg-eth (LACP LAG), and vlan-range — and verify each "
            "forwards correctly. Exercises the full interface matrix the "
            "cover page advertises."
        ),
        setup=(
            "Two-PE EVPN service up (FLOW-010 baseline). Five access "
            "ports on PE1 cabled to IXIA: x-eth-1 (untagged), "
            "sub-if x-eth-2.100 (single-tag VLAN 100), x-eth-3 "
            "(Q-in-Q outer 200 inner 10..20), agg-eth-1 (LACP LAG of "
            "two x-eth members), and vlan-range x-eth-4 vlan-range "
            "300..309."
        ),
        action=(
            "Bind each access-interface form to a dedicated EVI via "
            "`interface <form> evpn evi-N` in turn. From IXIA, send "
            "100 Mbps unicast through each form simultaneously: untagged "
            "on x-eth-1, VLAN 100 on x-eth-2.100, S-Tag 200 + C-Tag 15 "
            "on x-eth-3, LACP-balanced on agg-eth-1, and VLAN 305 on the "
            "vlan-range AC."
        ),
        verify=(
            "`show evpn evi` lists each EVI up with its bound AC. "
            "`show interface detail` confirms each access form: x-eth "
            "untagged, sub-if dot1q 100, Q-in-Q outer 200 / inner 10..20 "
            "stack, agg-eth lacp Up, vlan-range 300..309 active. IXIA "
            "receives every offered frame on the far PE at the offered "
            "rate (≥ 0.99× line rate)."
        ),
        pass_=(
            "All five access-interface forms bind to EVPN cleanly; ≤ 0 "
            "packet drops over 60 s steady state on each form; tag "
            "stack preserved (Q-in-Q frames egress with both tags; "
            "sub-if frames egress with single tag; untagged remains "
            "untagged)."
        ),
        fail_on=(
            "Any form rejects the EVPN binding, Q-in-Q outer/inner tag "
            "drift, vlan-range filter leaks frames outside the range, "
            "or LACP LAG fails to bring up with EVPN."
        ),
        equipment=(
            "DUT + IXIA (5 ports: untagged, single-tag, double-tag, "
            "LACP partner, vlan-range) + neighbor PE"
        ),
        categories=[
            "Basic Functionality", "Packet validation", "Feature interaction",
            "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=[
                "q-in-q", "qinq", "sub-if", "sub interface", "subinterface",
                "vlan-range", "vlan range", "agg-eth", "lag",
            ],
            required_tags=["CONFIG"],
        ),
        related_cli_cmds=["interface (VPLS/EVPN)", "evpn"],
        rfc_refs=["RFC 7432bis §6"],
        coverage_driven=True,
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
        setup="Two-PE EVPN up; CE attached to PE1; clean MAC table.",
        action=(
            "Send a known-unicast frame from CE-A (behind PE1) to CE-B "
            "(behind PE2) twice: (1) IPv4 host (e.g. 10.0.0.1 → 10.0.0.2), "
            "(2) IPv6 host (e.g. 2001:db8::1 → 2001:db8::2). Capture the "
            "BGP UPDATE on PE↔PE for each."
        ),
        verify=(
            "Type 2 NLRI carries: RD + ESI (zero for single-homed) + "
            "Eth-Tag + MAC (length=48) + (optional) IP (4-byte for IPv4, "
            "16-byte for IPv6 — IP Address Length field reflects which) "
            "+ MPLS Label1 [+ Label2] per RFC 7432bis §7.2; remote PE "
            "installs MAC + label for both v4 and v6 entries; reverse "
            "traffic forwards on the learned label in both directions."
        ),
        pass_=(
            "Type 2 encoded per §7.2 for both IPv4 and IPv6 host IPs; "
            "remote install + bidirectional flow for each address family."
        ),
        fail_on=(
            "MAC length ≠ 48, IP Address Length field ≠ 0/32/128, "
            "missing label, malformed RD/ESI, IPv6 host IP not carried, "
            "or remote PE drops the route."
        ),
        equipment="DUT + IXIA + neighbor PE",
        categories=[
            "Basic Functionality", "Packet validation",
            "Malformed/unsupported packets", "Feature interaction",
            "PM", "Tech-support",
        ],
        selector=FlowSelector(
            title_keywords=[
                "mac/ip", "mac advertisement", "type 2", "type-2",
                "address advertisement",
                "lt1", "lt2", "lt3", "lt4", "label type",
                "mac unicast forwarding table", "mac forwarding table",
                "local learning", "l2-attr", "l2 attr",
                "layer 2 attributes",
                "attribute processing", "nlri processing",
                "forwarding packets received",
                "esi label extended community",
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
        setup="Three-PE EVPN; ingress-replication tunnel; BUM source on access at PE1.",
        action=(
            "Send a broadcast and an unknown-unicast frame from PE1's "
            "access port; trace replication on PE1→PE2 and PE1→PE3 links."
        ),
        verify=(
            "Type 3 NLRI per §7.3; PMSI Tunnel attribute encodes the "
            "tunnel type, label, and tunnel ID; each remote PE receives "
            "exactly one copy; no duplication."
        ),
        pass_="One copy per remote PE; correct PMSI encoding.",
        fail_on=(
            "Duplicate replication, missing PMSI Tunnel attribute, wrong "
            "tunnel type, or BUM delivered to a non-EVI PE."
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
        selector=FlowSelector(
            title_keywords=[
                "ethernet a-d", "auto-discovery route",
                "type 1", "type-1", "ad route",
            ],
            required_tags=["PROTOCOL"],
        ),
        rfc_refs=["RFC 7432bis §7.1"],
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
        summary=(
            "A MAC learned behind PE1 reappears behind PE2; MAC Mobility "
            "EC sequence increments and the old advertisement is withdrawn."
        ),
        setup="Two-PE EVPN; host H1 attached to PE1, learned by both PEs.",
        action=(
            "Move H1's frames to PE2 (e.g. detach LAN cable from PE1's "
            "access, attach to PE2's access; or send from a different MAC "
            "on PE2). Capture PE2's new Type 2 advertisement."
        ),
        verify=(
            "MAC Mobility EC carries an incremented sequence number; PE1 "
            "withdraws its older advertisement; FIB on remote PE installs "
            "PE2 as the new path within the fast-convergence bound."
        ),
        pass_="Sequence increments; old advertisement withdrawn; FIB updates promptly.",
        fail_on=(
            "Sequence does not increment, no withdrawal, stale MAC entry, "
            "or sticky-MAC flag misapplied."
        ),
        equipment="DUT + IXIA + neighbor PE",
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
        action=(
            "Configure `af-l2vpn evpn` neighbor on DUT and the symmetric "
            "config on the 3rd party. Bring the session up; capture OPEN "
            "messages on both sides; advertise routes from each side."
        ),
        verify=(
            "Both sides advertise the L2VPN-EVPN AFI/SAFI capability; "
            "session reaches Established; routes from each side install "
            "into the other's RIB; encapsulation is interoperable."
        ),
        pass_="Capability exchanged; session up; routes installed bidirectionally.",
        fail_on=(
            "Missing capability, NOTIFICATION on OPEN, route rejected, or "
            "encoding mismatch on the wire."
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
        name="Scale to documented MAC table limit (64K MACs)",
        summary=(
            "Advertise/install MACs up to the documented system limit "
            "(64K MACs per PE; 32 EVIs; 16 multi-homed ESs); hold for "
            "≥ 5 min; verify CPU < 70%, memory growth < 5%, and per-"
            "route convergence ≤ 2× baseline."
        ),
        setup=(
            "Two-PE topology + IXIA scale rig. `mac-limit 65536` "
            "configured on the EVI under test. Baseline CPU and memory "
            "snapshot taken at idle."
        ),
        action=(
            "Use IXIA to advertise 64K unique MACs into the EVI at a "
            "rate of 1K MACs/s (total ramp-up 64 s); hold the table at "
            "ceiling for ≥ 5 min; while at scale, advertise one "
            "additional MAC then withdraw it to measure incremental "
            "convergence."
        ),
        verify=(
            "`show evpn mac address-table count` reaches 65536 entries "
            "without rejection; `show platform process cpu` stays ≤ 70% "
            "5-min average; `show platform process memory` grows by "
            "≤ 5% over the run; incremental advertise/withdraw "
            "converges in ≤ 2× the idle baseline (measured by IXIA's "
            "first-packet-with-new-MAC timestamp)."
        ),
        pass_=(
            "65536 MAC ceiling reached; CPU ≤ 70%; memory growth ≤ 5%; "
            "incremental convergence ≤ 2× baseline; zero entries "
            "rejected below the ceiling."
        ),
        fail_on=(
            "Crash, OOM, entries rejected below 65536, CPU > 70% "
            "sustained, memory growth > 5%, or per-route convergence > 2× "
            "baseline at scale."
        ),
        equipment="Two routers + IXIA scale rig (≥ 64K MAC generation)",
        categories=[
            "Scale", "Performance", "Long run", "Tech-support",
        ],
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
        setup=(
            "Single-router topology with EVPN service active; IXIA traffic "
            "flowing for ≥ 1 min."
        ),
        action=(
            "Kill the EVPN-related control-plane process via the platform "
            "debug command; let the supervisor restart it."
        ),
        verify=(
            "Process restarts within ≤ 5 s of SIGKILL; BGP EVPN session "
            "re-establishes within ≤ 30 s; data-plane remains forwarding "
            "(IXIA measures ≤ 1 s of zero-bps outage on the access port)."
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
        action=(
            "Modify a parameter live (e.g. add an import-rt, switch "
            "load-balancing-mode, change DF preference, change "
            "es-waiting-time); commit. Then change it back."
        ),
        verify=(
            "IXIA reports zero or near-zero loss during the change; "
            "`show running-config` reflects the new value within ≤ 1 s; "
            "feature reconverges without service flap."
        ),
        pass_="Modification applied without service interruption.",
        fail_on=(
            "Traffic loss > 0 packets on a documented hitless change, or "
            "new config not active within 1 s."
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
        setup=(
            "Three-node MPLS path PE1–P–PE2; LDP or RSVP-TE LSPs up; BGP "
            "EVPN session PE1↔PE2. One EVI (`evi-1`) up on both PEs with a "
            "single-homed CE on each side. PE2 advertises implicit-null "
            "(label 3) for its loopback so the P node performs PHP."
        ),
        action=(
            "Confirm PE2 signals implicit-null for its loopback FEC. From "
            "IXIA, send known-unicast then BUM EVPN traffic CE1→CE2 for "
            "≥ 60 s. On the P node, inspect the label operation for PE2's "
            "FEC; on PE2, capture the received frame's label stack."
        ),
        verify=(
            "`show mpls forwarding-table` on the P node shows a POP (not "
            "SWAP) operation for PE2's loopback FEC. The frame arriving at "
            "PE2 carries exactly one label (the EVPN service/VPN label) — "
            "the transport label has been removed upstream. `show evpn evi "
            "evi-1` on PE2 learns the remote MAC; IXIA receives frames on "
            "the far port at line rate."
        ),
        pass_=(
            "Penultimate P node pops the transport label; egress PE forwards "
            "on the single service label; bidirectional EVPN traffic passes "
            "with ≤ 0 drops over the steady-state window."
        ),
        fail_on=(
            "P node swaps instead of pops, egress PE receives a two-label "
            "stack, frames black-holed, or service label mis-bound."
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
        setup=(
            "Two-PE topology with a primary LSP and a pre-signalled backup "
            "LSP (RSVP-TE FRR or a secondary path) to PE2's loopback; BGP "
            "EVPN up; `evi-1` up on both PEs; IXIA traffic running on the "
            "data path for ≥ 1 minute."
        ),
        action=(
            "While IXIA traffic flows, fail the primary tunnel (down the "
            "primary core link or the primary LSP). Watch the IXIA loss "
            "histogram. Restore the primary and observe revert behaviour."
        ),
        verify=(
            "On failure, traffic moves onto the backup LSP — `show mpls lsp` "
            "shows the backup active; the EVPN service does not flap (`show "
            "evpn evi evi-1` stays up, remote MAC retained). IXIA loss "
            "histogram records the outage window. On primary restore, "
            "traffic reverts (or holds, per policy) without a second outage."
        ),
        pass_=(
            "Failover to the backup tunnel completes with data-path outage "
            "≤ 50 ms (FRR) / ≤ 1 s (secondary path); EVPN service stays up; "
            "no MAC re-learn storm; clean revert on restore."
        ),
        fail_on=(
            "Traffic black-holed after primary failure, outage exceeds the "
            "documented bound, EVPN service flaps, or revert causes a second "
            "outage."
        ),
        equipment="DUT + IXIA + neighbor PE + redundant MPLS core paths",
        categories=[
            "Basic Functionality", "HA", "Robustness", "Tech-support",
        ],
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

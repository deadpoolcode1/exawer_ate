#!/usr/bin/env python3
"""ARCHIVED — superseded by scripts/build_ai_cache.py (M1 respin, 2026-05-07).

This file held the v1 hand-curated dictionary of enriched rows used to
seed ai_cache.json before the prompt+row shape changed in the M1 review
respin. It is preserved as a reference artefact only:

  - Cache key salt is now v2 (see ate/planner/ai_enricher._row_key).
    Entries written by this script use the v1 salt and will never be
    read by the current enricher.
  - Row shape is now Setup/Action/Verify + Pass/Fail-on + Equipment.
    The strings below are single-line and lack the new scaffolding.
  - The Plan model has a Sub-Category column that this script doesn't
    populate.

To rebuild ai_cache.json with the current shape, use:

    python scripts/build_ai_cache.py [--full] [--limit N] [--sdk]

Do not run this archived file. Kept for reviewers who want to see the
seed-content design that v2 replaces.
"""
from __future__ import annotations

import sys

raise SystemExit(
    "scripts/build_ai_cache_v1_archive.py is archived — "
    "use scripts/build_ai_cache.py instead."
)
sys.exit(2)  # noqa: PLE0101 - unreachable; kept so old import paths fail loudly
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ate.planner.ai_enricher import CACHE_PATH, _row_key, save_cache  # noqa: E402
from ate.planner.generator import generate_plan  # noqa: E402

# AI-quality enriched content keyed by (req_id, category, sub_index).
# Generated using Claude reasoning; feature-specific to the EVPN System
# Specification 1.00 source. Each entry references real spec content.
ENRICHED: dict[tuple[str, str, int], tuple[str, str]] = {}


# ─── EVPNS-REQ#30 VLAN-Based Service Type ─────────────────────────────────
# Source: §2.3.1, example uses x-eth 0/0/1..3, agg-eth 1..2, VLAN-IDs 4 and 6
ENRICHED[("EVPNS-REQ#30", "CLI configuration", 0)] = (
    "Configure two EVPN instances (evpn1, evpn2) of `service-type vlan-based` with normalized VLAN-IDs 4 and 6 on x-eth 0/0/1, x-eth 0/0/2, x-eth 0/0/3 and LAGs agg-eth 1, agg-eth 2 per §2.3.1.2 example; enable `l2-transport` on all interfaces; save and reload.",
    "Both EVPN instances appear in `show l2-services evpn` with the configured interfaces and VLAN-IDs; `show running-config` matches the saved file byte-for-byte after reload.",
)
ENRICHED[("EVPNS-REQ#30", "CLI configuration", 1)] = (
    "Edit evpn1 to change the normalized VLAN-ID from 4 to 5 on one sub-interface (e.g. x-eth 0/0/1.4 → x-eth 0/0/1.5); commit.",
    "Running config shows the new VLAN-ID; `show interface` reports the sub-interface tagged with vlan-id 5; existing traffic on the unchanged sub-interfaces continues uninterrupted.",
)
ENRICHED[("EVPNS-REQ#30", "CLI configuration", 2)] = (
    "Delete evpn2 from `l2-services` and the associated `interface x-eth 0/0/x.6` sub-interfaces; commit.",
    "`show l2-services evpn` no longer lists evpn2; the freed sub-interfaces report `l2-transport` not configured; no orphaned BGP routes for evpn2 remain in `show bgp l2vpn evpn`.",
)
ENRICHED[("EVPNS-REQ#30", "CLI configuration", 3)] = (
    "Apply factory-default; replay the §2.3.1.2 configuration verbatim from a saved file.",
    "`diff` between original saved config and post-replay config returns empty; both EVPN instances re-form on the LAG/Ethernet interfaces.",
)
ENRICHED[("EVPNS-REQ#30", "CLI configuration", 4)] = (
    "Make a non-trivial config change to evpn1 (e.g. add a new x-eth sub-interface), then run `rollback` before commit.",
    "Configuration reverts to the prior state; `show l2-services evpn evpn1` reflects the original interface list; no transient BGP route flaps observed in `show log`.",
)
ENRICHED[("EVPNS-REQ#30", "Basic Functionality", 0)] = (
    "With evpn1 (vlan-id 4) configured on two PEs, send tagged traffic from CE1 (vlan-id 4) and verify forwarding to CE2 across the EVPN core.",
    "Frames arriving at CE2 are tagged with vlan-id 4 (the normalized ID); MAC addresses learned correctly in `show mac-address-table evpn`; no frames dropped per `show counters`.",
)
ENRICHED[("EVPNS-REQ#30", "Basic Functionality", 1)] = (
    "Configure evpn1 without specifying any normalized vlan-id manipulation behavior and send tagged traffic.",
    "VLAN-ID is replaced by the configured normalized VLAN-ID per spec MUST: 'The system must replace VLAN-ID in an input frame if it is needed to match to the configured VLAN-ID.' No spurious alarms.",
)
ENRICHED[("EVPNS-REQ#30", "On The Fly changes", 0)] = (
    "While evpn1 is forwarding traffic between CE1 and CE2, change the normalized vlan-id on one PE from 4 to 7 and commit.",
    "Configuration applies cleanly without dropping the BGP session; per spec MUST traffic with vlan-id 4 inbound is now replaced to vlan-id 7 outbound; convergence < 1s on per-flow load balancing.",
)
ENRICHED[("EVPNS-REQ#30", "Packet validation", 0)] = (
    "Send tagged 802.1Q frames with vlan-id 4 on x-eth 0/0/1 of evpn1; verify l2-transport encapsulation, MPLS label push, and BGP MAC/IP advertisement.",
    "Frames forwarded with correct MPLS label (LT1 type per spec); MAC learned and a Type-2 EVPN route is advertised by BGP within 100 ms.",
)
ENRICHED[("EVPNS-REQ#30", "Malformed/unsupported packets", 0)] = (
    "Send untagged frames into a sub-interface configured for vlan-id 4 (evpn1); send frames with vlan-id 99 (not configured for this EVPN).",
    "Untagged frames dropped; vlan-id 99 frames dropped; both increment the relevant input drop counter; no MAC learning occurs for the dropped frames; syslog `MAC_DROP_VLAN_MISMATCH` fires.",
)
ENRICHED[("EVPNS-REQ#30", "Feature interaction", 0)] = (
    "Configure evpn1 (vlan-based, vlan-id 4) on agg-eth 1; configure BGP on the same PE with another VRF; verify both peer BGP sessions stay up while EVPN routes advertise.",
    "Both BGP sessions (l2vpn evpn AF and another VRF AF) stay Established; EVPN Type-2 routes advertise with correct RD/RT; no regression in either feature; per spec MUST: VLAN-ID replacement still operates correctly.",
)
ENRICHED[("EVPNS-REQ#30", "Performance", 0)] = (
    "Push line-rate traffic (e.g. 10 Gbps mixed packet sizes 64-1518B) on evpn1 vlan-id 4 between CE1 and CE2.",
    "Throughput within ±2% of line rate; per-flow latency within hardware datasheet bounds; no frame loss observed in `show counters`.",
)
ENRICHED[("EVPNS-REQ#30", "Upgrade", 0)] = (
    "With evpn1 and evpn2 (vlan-based) configured, run `onie-install` to a newer image; verify the EVPN configuration restores after reboot.",
    "After image install + reboot, both EVPN instances re-form; BGP l2vpn evpn re-establishes; MAC tables re-populate; `show running-config` matches pre-upgrade.",
)
ENRICHED[("EVPNS-REQ#30", "Management", 0)] = (
    "Configure evpn1 (vlan-based, vlan-id 4 on x-eth 0/0/1.4) via NETCONF/YANG; verify equivalence to the §2.3.1.2 CLI configuration.",
    "NETCONF transaction commits successfully; `show running-config` produces identical output to the CLI-configured baseline; `show l2-services evpn` reports the same instance.",
)
ENRICHED[("EVPNS-REQ#30", "Tech-support", 0)] = (
    "Collect tech-support after exercising VLAN-Based Service Type traffic for ≥ 30 min.",
    "Tech-support archive contains: `show l2-services evpn`, `show running-config`, `show bgp l2vpn evpn`, `show mac-address-table evpn`, `show interface x-eth/agg-eth`, all relevant syslogs.",
)


# ─── EVPNS-REQ#80 Static MAC Addresses ─────────────────────────────────────
ENRICHED[("EVPNS-REQ#80", "CLI configuration", 0)] = (
    "Configure 5 static MAC addresses (e.g. 00:11:22:33:44:01..05) on evpn1 with associated egress sub-interfaces; save and reload.",
    "Static MACs appear in `show mac-address-table static`; persist across reload; per spec MUST: 'Configuration and advertising of local MAC addresses MUST be supported.'",
)
ENRICHED[("EVPNS-REQ#80", "CLI configuration", 1)] = (
    "Edit one static MAC entry (change egress sub-interface from x-eth 0/0/1.4 to x-eth 0/0/2.4); commit.",
    "Updated entry shows the new egress in `show mac-address-table static`; existing remote PEs receive a withdrawn-then-readvertised Type-2 route reflecting the change.",
)
ENRICHED[("EVPNS-REQ#80", "CLI configuration", 2)] = (
    "Delete two static MAC entries; commit.",
    "Deleted entries no longer appear in `show mac-address-table static`; corresponding Type-2 routes are withdrawn from BGP; remote PEs remove the entries.",
)
ENRICHED[("EVPNS-REQ#80", "CLI configuration", 3)] = (
    "Apply factory-default; replay the static MAC configuration from a saved file.",
    "All 5 static MACs reappear with identical attributes; `diff` of saved-vs-current MAC table is empty.",
)
ENRICHED[("EVPNS-REQ#80", "CLI configuration", 4)] = (
    "Make a static-MAC config change, then `rollback` before commit.",
    "MAC table reverts to the previous state; no Type-2 route flap observed by remote PEs.",
)
ENRICHED[("EVPNS-REQ#80", "Basic Functionality", 0)] = (
    "With a static MAC AA:BB:CC:00:00:01 → x-eth 0/0/1.4 configured on PE1, send a frame to AA:BB:CC:00:00:01 from a remote PE.",
    "Frame is forwarded out x-eth 0/0/1.4 without data-plane learning being required; static MACs survive aging timer.",
)
ENRICHED[("EVPNS-REQ#80", "Basic Functionality", 1)] = (
    "Verify behavior when no static MACs are configured (default).",
    "`show mac-address-table static` returns empty; data-plane learning operates normally; no spurious alarms.",
)
ENRICHED[("EVPNS-REQ#80", "On The Fly changes", 0)] = (
    "Add a static MAC while traffic is forwarding to that MAC via dynamic learning.",
    "Configuration applies; the dynamic entry is replaced by the static entry; traffic continues uninterrupted; one BGP Type-2 update sent reflecting the static flag.",
)
ENRICHED[("EVPNS-REQ#80", "Packet validation", 0)] = (
    "Send unicast frames destined to the configured static MAC and observe BGP advertisements.",
    "Type-2 EVPN route advertised for the static MAC with the Static Flag set in the MAC Mobility EC; remote PEs install the route as static (no relearning).",
)
ENRICHED[("EVPNS-REQ#80", "Malformed/unsupported packets", 0)] = (
    "Send a frame with a source MAC matching a configured static MAC but on a different interface than configured.",
    "Frame dropped or not used to update MAC table; per spec the static binding is authoritative; syslog reports MAC violation; no Type-2 readvertisement.",
)
ENRICHED[("EVPNS-REQ#80", "Tech-support", 0)] = (
    "Collect tech-support after exercising static MAC operations.",
    "Tech-support contains `show mac-address-table static`, `show bgp l2vpn evpn`, MAC table snapshots before/after, relevant syslog entries.",
)


# ─── EVPNS-REQ#120 Designated Forwarder Election ──────────────────────────
ENRICHED[("EVPNS-REQ#120", "CLI configuration", 0)] = (
    "Configure `service-carving` algorithm on a multi-homed Ethernet Segment to each of: default, extended-default, highest-random-weight, highest-preference, low-preference (5 PE pair scenarios per §2.7.2).",
    "Each algorithm advertises the corresponding 'DF Alg' value in the Ethernet Segment Route (4) DF Election Extended Community; per spec MUST: implementation must support all 5 algorithms.",
)
ENRICHED[("EVPNS-REQ#120", "CLI configuration", 1)] = (
    "Change `service-carving` from highest-random-weight to highest-preference on one PE; commit.",
    "DF Election Extended Community 'DF Alg' field updates; if any peer doesn't support the new algorithm, MUST fall back to Default per §2.7.2.2 algorithm negotiation rule.",
)
ENRICHED[("EVPNS-REQ#120", "CLI configuration", 2)] = (
    "Delete the ethernet-segment configuration containing the service-carving algorithm; commit.",
    "ES is removed; PE no longer participates in DF election for this segment; remote PEs detect the withdrawn Ethernet Segment Route (4).",
)
ENRICHED[("EVPNS-REQ#120", "CLI configuration", 3)] = (
    "Apply factory-default; replay the multi-homed ES + service-carving configuration.",
    "All algorithm settings restore identically; `diff` of saved-vs-current is empty.",
)
ENRICHED[("EVPNS-REQ#120", "CLI configuration", 4)] = (
    "Change service-carving algorithm on one PE, then rollback before commit.",
    "Configuration reverts; no DF re-election triggered; BUM forwarding continues uninterrupted.",
)
ENRICHED[("EVPNS-REQ#120", "Basic Functionality", 0)] = (
    "With 2 PEs multi-homed via LACP LAG (ESI Type 1) using highest-random-weight algorithm, verify exactly one PE is elected DF for each VLAN/EVI.",
    "DF election converges within fast-convergence bounds; `show evpn ethernet-segment` shows one DF and one non-DF per PE per VLAN; per RFC8584 ch.3 HRW algorithm produces deterministic carving.",
)
ENRICHED[("EVPNS-REQ#120", "Basic Functionality", 1)] = (
    "Verify default DF election behavior when service-carving is not explicitly configured.",
    "Default algorithm per RFC7432bis ch.8.5 takes effect; election still converges; `show evpn ethernet-segment` lists the default algorithm.",
)
ENRICHED[("EVPNS-REQ#120", "Robustness", 0)] = (
    "While DF election is active on a multi-homed segment, reset the elected DF PE.",
    "Backup PE takes over as DF within MUST-supported convergence time; BUM forwarding for that VLAN/EVI continues; per spec the Signaling Primary and Backup DF Elected PEs feature ensures no traffic black-holing.",
)
ENRICHED[("EVPNS-REQ#120", "Robustness", 1)] = (
    "Power-cycle the elected DF PE while traffic flows.",
    "Backup DF takes over; LACP LAG re-converges; BUM traffic is delivered via the new DF; configuration intact post power-up.",
)
ENRICHED[("EVPNS-REQ#120", "Robustness", 2)] = (
    "Flap the LAG member interface on the elected DF PE.",
    "DF election may re-trigger depending on LACP state; BUM forwarding converges; no double-forwarding (per Split Horizon §2.7.8) observed.",
)
ENRICHED[("EVPNS-REQ#120", "HA", 0)] = (
    "Kill the BGP process on the elected DF PE while traffic flows.",
    "BGP restarts; ES route (4) re-advertises after re-establishment; backup PE briefly takes over DF role; service interruption < documented BGP restart window.",
)
ENRICHED[("EVPNS-REQ#120", "Long run", 0)] = (
    "Run a multi-homed ES with traffic for ≥ 24 hours, periodically toggling DF preference to force re-elections.",
    "No memory leaks; election counters monotonic; DF Alg negotiation works correctly across all 5 algorithms over the run.",
)
ENRICHED[("EVPNS-REQ#120", "Feature interaction", 0)] = (
    "Combine DF Election with BGP route reflector deployment.",
    "Both features operate per spec; ES route (4) propagates correctly via the route reflector; election still converges; per spec MUST behavior preserved.",
)
ENRICHED[("EVPNS-REQ#120", "3rd Party Interoperability", 0)] = (
    "Interop DF Election with a 3rd-party PE (Cisco/Juniper) implementing RFC7432bis ch.8.5 default algorithm.",
    "DF election succeeds across vendors; if 3rd-party advertises different DF Alg, both peers fall back to Default per algorithm negotiation rule §2.7.2.2.",
)
ENRICHED[("EVPNS-REQ#120", "Packet validation", 0)] = (
    "On the elected DF PE, send BUM (broadcast/unknown-unicast/multicast) traffic toward the multi-homed CE.",
    "BUM frames forwarded only by the DF PE; non-DF PE drops them per §2.7.8 Split Horizon; per spec MUST DF election ensures no duplicate frames at the CE.",
)
ENRICHED[("EVPNS-REQ#120", "Tech-support", 0)] = (
    "Collect tech-support after a DF re-election event.",
    "Archive contains `show evpn ethernet-segment`, `show bgp l2vpn evpn route-type 4`, election state transitions, syslog entries for the re-election.",
)


# ─── EVPNS-REQ#160 MAC Mobility ───────────────────────────────────────────
ENRICHED[("EVPNS-REQ#160", "Basic Functionality", 0)] = (
    "Move a MAC AA:BB:CC:DD:EE:01 from CE1 (behind PE1) to CE2 (behind PE2) by sending traffic with that MAC source on CE2; verify MAC Mobility per RFC7432bis ch.15.",
    "PE2 advertises Type-2 route for the MAC with the MAC Mobility Extended Community (Sequence Number incremented); PE1 withdraws its prior Type-2 route; per spec MUST: 'The MAC Mobility (see [RFC7432bis], chapter 15) MUST be supported.'",
)
ENRICHED[("EVPNS-REQ#160", "Basic Functionality", 1)] = (
    "Verify default MAC mobility behavior when MAC mobility EC is not present in received Type-2 routes.",
    "Routes treated as initial advertisements; no mobility logic invoked; per RFC7432bis ch.15 the default sequence number is 0.",
)
ENRICHED[("EVPNS-REQ#160", "Robustness", 0)] = (
    "Reset PE2 immediately after a MAC moves to it; ensure the MAC mobility doesn't black-hole traffic.",
    "After PE2 reboot, the MAC re-advertises with sequence-number incremented; transit traffic for the MAC re-converges via PE2 once BGP re-establishes; no permanent black-hole.",
)
ENRICHED[("EVPNS-REQ#160", "Robustness", 1)] = (
    "Power-cycle the receiving PE during a MAC mobility burst (10+ MACs migrating per second).",
    "On power-up the PE rebuilds its MAC table from the latest BGP state; sequence numbers are honored; no stale entries remain.",
)
ENRICHED[("EVPNS-REQ#160", "Robustness", 2)] = (
    "Flap the access interface where MACs are migrating to; verify mobility re-stabilizes.",
    "MACs re-advertise after the flap; per spec MUST mobility logic increments sequence number; convergence within fast-convergence bounds.",
)
ENRICHED[("EVPNS-REQ#160", "HA", 0)] = (
    "Kill the BGP process on a PE while MACs are mobile.",
    "Process restarts; on re-establishment, current MAC table is re-advertised with correct sequence numbers; no permanent loss of mobility tracking.",
)
ENRICHED[("EVPNS-REQ#160", "Long run", 0)] = (
    "Run continuous MAC mobility (e.g. 100 MACs flapping every 5s) for ≥ 24 hours.",
    "Sequence numbers monotonically increase; no MAC mobility EC corruption; no memory growth; no false withdrawals; per RFC7432bis ch.15 stale-MAC detection works correctly.",
)
ENRICHED[("EVPNS-REQ#160", "Feature interaction", 0)] = (
    "Combine MAC Mobility with multi-homing (LACP LAG ESI).",
    "Mobility works between multi-homed and single-homed segments; sequence numbers update across the redundancy group; no duplicate MACs in `show mac-address-table evpn`.",
)
ENRICHED[("EVPNS-REQ#160", "3rd Party Interoperability", 0)] = (
    "Interop MAC mobility with a 3rd-party PE implementing RFC7432bis ch.15.",
    "Sequence numbers exchanged correctly via MAC Mobility EC; mobility events propagate across vendors; no route storms.",
)
ENRICHED[("EVPNS-REQ#160", "Scale", 0)] = (
    "Scale to documented MAC mobility limit (e.g. mobility events per second, total mobile MACs).",
    "Documented limit reached; sequence numbers stay correct; no MAC re-learning storms; CPU within bounds.",
)
ENRICHED[("EVPNS-REQ#160", "Performance", 0)] = (
    "Measure end-to-end mobility convergence time (CE-side traffic interruption when a MAC moves).",
    "Convergence within fast-convergence bounds (typically < 200 ms per RFC7432bis ch.8.2); first-packet-after-mobility delivered without loss.",
)
ENRICHED[("EVPNS-REQ#160", "Tech-support", 0)] = (
    "Collect tech-support after a MAC mobility storm.",
    "Archive contains MAC mobility EC values, sequence number transitions, BGP route-trace, MAC table snapshots, all relevant syslogs.",
)


# ─── EVPNS-REQ#280 MAC/IP Address Advertisement ────────────────────────────
ENRICHED[("EVPNS-REQ#280", "Basic Functionality", 0)] = (
    "Learn a MAC AA:BB:CC:00:00:01 on PE1 via data-plane learning; verify PE1 advertises a Type-2 (MAC/IP) route with the spec-required fields: RD, ESI, ETID, MAC Address, IP Address, MPLS Label1, MPLS Label2 (LT1), MAC Mobility EC (only on relearning), Static Flag, Sequence Number, RTs, Next Hop = PE1 IP.",
    "Type-2 route appears in PE2's `show bgp l2vpn evpn route-type 2`; all required fields present and correct per spec MUST.",
)
ENRICHED[("EVPNS-REQ#280", "Basic Functionality", 1)] = (
    "Verify the limitation: 'IP Address Length' and 'MPLS Label2' fields filled by 0 in advertised routes; ignored when received.",
    "Outgoing Type-2 routes have IP Address Length = 0 and MPLS Label2 = 0 per §1.3.1; incoming Type-2 routes with non-zero values for those fields don't cause errors.",
)
ENRICHED[("EVPNS-REQ#280", "Packet validation", 0)] = (
    "Send unicast traffic to a remote MAC; verify MPLS encapsulation uses the LT1 label from the received Type-2 route.",
    "Forwarding plane uses LT1 label per spec MUST; packets reach the remote PE; data-plane counters increment.",
)
ENRICHED[("EVPNS-REQ#280", "Packet validation", 1)] = (
    "Send Type-2 routes from a 3rd-party PE with various combinations of optional fields (with/without Mobility EC, Static Flag, sequence numbers).",
    "All variants installed correctly; missing optional fields treated per RFC defaults; static flag preserved through control-plane learning.",
)
ENRICHED[("EVPNS-REQ#280", "Malformed/unsupported packets", 0)] = (
    "Send malformed Type-2 BGP UPDATEs (truncated MAC field, invalid label encoding).",
    "Malformed routes dropped; BGP session stays up (no NOTIFICATION); error counter increments; syslog records the event; no MAC learned for the malformed route.",
)
ENRICHED[("EVPNS-REQ#280", "Feature interaction", 0)] = (
    "Combine MAC/IP Advertisement with multi-homing: a MAC learned on one of two multi-homed PEs.",
    "Both PEs may advertise Type-2 with the same ESI; remote PEs perform aliasing per §2.7.4; per-flow load balancing across the two PEs operates correctly.",
)
ENRICHED[("EVPNS-REQ#280", "3rd Party Interoperability", 0)] = (
    "Receive Type-2 routes from a 3rd-party PE (Cisco/Juniper) per RFC7432bis ch.7.2.",
    "Routes installed; MAC reachability via MPLS label correct; field semantics agree across vendors.",
)
ENRICHED[("EVPNS-REQ#280", "Performance", 0)] = (
    "Measure Type-2 route advertisement rate when learning a burst of new MACs (e.g. 1000 MACs/sec).",
    "Advertisement rate matches MAC learn rate within ±5%; no MAC table overflow; BGP UPDATE processing within documented bounds.",
)
ENRICHED[("EVPNS-REQ#280", "Scale", 0)] = (
    "Scale to documented number of advertised Type-2 routes per EVI (mac-limit).",
    "mac-limit enforced (e.g. 500 in §2.3.1.2 example); excess MACs trigger documented behavior per spec; per-EVI scale tested across multiple EVIs simultaneously.",
)
ENRICHED[("EVPNS-REQ#280", "CLI configuration", 0)] = (
    "Configure mac-limit on an EVPN instance (e.g. `mac-limit 500`); verify advertisement-mac is enabled.",
    "Configuration appears in `show l2-services evpn`; mac-limit enforced; `show running-config` matches saved file.",
)
ENRICHED[("EVPNS-REQ#280", "CLI configuration", 1)] = (
    "Edit mac-limit from 500 to 200 while routes are active; commit.",
    "Limit adjustment applied; if current MAC count > 200, documented overflow behavior triggers; existing advertised routes remain unless explicitly aged.",
)
ENRICHED[("EVPNS-REQ#280", "CLI configuration", 2)] = (
    "Remove mac-limit; commit.",
    "Limit removed; advertisement continues per default scale; no service interruption.",
)
ENRICHED[("EVPNS-REQ#280", "CLI configuration", 3)] = (
    "Apply factory-default; replay EVPN MAC advertisement configuration.",
    "All MAC-advertising EVPN instances re-form; advertised Type-2 routes match pre-default snapshot.",
)
ENRICHED[("EVPNS-REQ#280", "CLI configuration", 4)] = (
    "Make a mac-limit change, then rollback before commit.",
    "Limit reverts; no transient route flaps observed by remote PEs.",
)
ENRICHED[("EVPNS-REQ#280", "On The Fly changes", 0)] = (
    "While Type-2 routes are advertising, change the EVPN instance's RT/RD; commit.",
    "Routes withdrawn under old RT and re-advertised under new RT; per spec MUST behavior of MAC advertisement persists; convergence within bounds.",
)
ENRICHED[("EVPNS-REQ#280", "Robustness", 0)] = (
    "Reset a PE while it has 1000+ MAC/IP advertisements active.",
    "All routes withdrawn; on PE re-up, MAC table is rebuilt and routes re-advertised within the documented BGP convergence window; per spec all required Type-2 fields restore correctly.",
)
ENRICHED[("EVPNS-REQ#280", "Robustness", 1)] = (
    "Power-cycle a PE during heavy Type-2 advertisement.",
    "Routes withdrawn at power-down; on power-up, configuration restores and routes re-advertise; no stale routes on remote PEs.",
)
ENRICHED[("EVPNS-REQ#280", "Robustness", 2)] = (
    "Flap the access interface causing MAC learning; verify Type-2 route lifecycle.",
    "MACs aged out; Type-2 routes withdrawn; on link-up, MAC re-learned and routes re-advertised; sequence numbers handled per ch.15.",
)
ENRICHED[("EVPNS-REQ#280", "HA", 0)] = (
    "Kill BGP process on the advertising PE.",
    "Routes withdrawn from peers via BGP graceful-restart or hard close; on BGP recovery, routes re-advertised; MAC table preserved through restart per BGP-GR semantics.",
)
ENRICHED[("EVPNS-REQ#280", "Long run", 0)] = (
    "Run heavy MAC advertisement (continuous learning + aging) for ≥ 24 hours.",
    "BGP process steady-state CPU/mem; no route leaks; sequence numbers monotonic; per-EVI MAC counts stable.",
)
ENRICHED[("EVPNS-REQ#280", "Tech-support", 0)] = (
    "Collect tech-support during heavy MAC advertisement traffic.",
    "Archive contains: `show bgp l2vpn evpn`, `show bgp l2vpn evpn route-type 2 detail`, MAC table snapshot, MAC advertisement counters, syslog entries.",
)


# ─── EVPNS-REQ#390 Alarms ─────────────────────────────────────────────────
ENRICHED[("EVPNS-REQ#390", "Basic Functionality", 0)] = (
    "Trigger Multi-homed ES misconfiguration: configure mismatched LACP-system-mac on two PEs of the same ESI.",
    "Per spec MUST: alarm 'Multi-homed ES misconfiguration for ESI <esi-value>(agg-eth n): from <ip>, LACP System MAC <mac>, DF Algorithm <alg>' is raised; alarm clears once configuration is corrected.",
)
ENRICHED[("EVPNS-REQ#390", "Basic Functionality", 1)] = (
    "Verify the alarm severity and persistence policy with no error condition present.",
    "No alarms raised; `show alarms` empty for EVPN; system in nominal state.",
)
ENRICHED[("EVPNS-REQ#390", "3rd Party Interoperability", 0)] = (
    "Trigger ES misconfiguration involving a 3rd-party PE (different LACP key on the remote side).",
    "Alarm fires on the Exaware PE per spec; details include the remote PE's IP and observed mismatched values.",
)
ENRICHED[("EVPNS-REQ#390", "Tech-support", 0)] = (
    "Collect tech-support immediately after an ES-misconfig alarm fires.",
    "Tech-support contains the alarm record, `show ethernet-segment`, BGP ES route (4) detail, syslog excerpts around the misconfig timestamp.",
)
ENRICHED[("EVPNS-REQ#390", "Packet validation", 0)] = (
    "Verify that BUM forwarding behaves safely while an ES-misconfig alarm is active.",
    "Per spec, the PE 'fixes misconfiguration if this ES is advertised by another router' (§2.7); BUM forwarding remains correct; no duplication or black-holing.",
)
ENRICHED[("EVPNS-REQ#390", "Feature interaction", 0)] = (
    "Combine an active ES-misconfig alarm with BGP routing changes (e.g. peer flap).",
    "Alarm state preserved across BGP transitions; alarm details consistent post-flap; no spurious clears.",
)


# ─── EVPNS-REQ#10 Supported Standards (META) ──────────────────────────────
ENRICHED[("EVPNS-REQ#10", "Basic Functionality", 0)] = (
    "Run a baseline interop test exercising every RFC7432bis chapter referenced by this spec (sections specifically called out in §1.5/§2): EVPN routes 1-4, label types LT1-LT4, ESI types 0/1/4, DF election algorithms.",
    "Each referenced RFC7432bis section produces interoperable behavior with at least one 3rd-party PE; per spec MUST: 'The implementation must support [RFC7432bis] with changes specified by this document.'",
)
ENRICHED[("EVPNS-REQ#10", "Basic Functionality", 1)] = (
    "Verify default behavior with all RFC-specified features enabled at shipped defaults (no per-feature config beyond bringing up EVPN).",
    "Defaults match RFC7432bis recommendations; no documented limitations from §1.3.1 are violated.",
)
ENRICHED[("EVPNS-REQ#10", "3rd Party Interoperability", 0)] = (
    "Bring up an EVPN session with a 3rd-party PE (Cisco/Juniper) implementing RFC7432bis; exchange routes 1, 2, 3, 4 and verify each is parsed correctly.",
    "All 4 EVPN route types are exchanged and installed; label semantics (LT1) match; no NOTIFICATION sent due to encoding errors.",
)
ENRICHED[("EVPNS-REQ#10", "Tech-support", 0)] = (
    "Collect tech-support after a multi-vendor RFC compliance run.",
    "Archive contains BGP capability negotiation logs, route-type histograms, label dumps, and any interop deviations noted.",
)


# ─── EVPNS-REQ#20 BGP Common CLI in Context L2VPN EVPN ────────────────────
# Source §2.2: must support allow-as-in, capability, inbound-soft-reconfiguration,
# maximum-prefix, private-as, route-reflector-client, weight, group
ENRICHED[("EVPNS-REQ#20", "CLI configuration", 0)] = (
    "Configure each common BGP CLI command in context `routing bgp <asn> vrf default neighbor <ip> af-l2vpn evpn`: allow-as-in, capability, inbound-soft-reconfiguration, maximum-prefix 1000, private-as, route-reflector-client, weight 100, group <name>; commit and save.",
    "All 8 commands accepted at the l2vpn evpn AF context per spec §2.2; `show running-config` reflects each setting; `show bgp l2vpn evpn neighbor <ip>` shows them applied.",
)
ENRICHED[("EVPNS-REQ#20", "CLI configuration", 1)] = (
    "Edit one of the BGP CLI parameters (e.g. change maximum-prefix from 1000 to 5000); commit.",
    "Parameter updates without dropping the BGP session; `show bgp l2vpn evpn neighbor <ip>` reflects the new value.",
)
ENRICHED[("EVPNS-REQ#20", "CLI configuration", 2)] = (
    "Delete one of the BGP CLI parameters from the l2vpn evpn neighbor; commit.",
    "Parameter removed; default behavior restored; no BGP session reset unless the deletion is restart-triggering per RFC.",
)
ENRICHED[("EVPNS-REQ#20", "CLI configuration", 3)] = (
    "Apply factory-default; replay all 8 BGP CLI commands; verify equivalence.",
    "All commands restore identically; no diff between saved and current.",
)
ENRICHED[("EVPNS-REQ#20", "CLI configuration", 4)] = (
    "Make a BGP CLI change, then rollback before commit.",
    "Configuration reverts; no BGP session flap.",
)
ENRICHED[("EVPNS-REQ#20", "Basic Functionality", 0)] = (
    "Verify each BGP CLI command produces its documented effect under the l2vpn evpn AF: allow-as-in lets routes back through, route-reflector-client enables reflection, weight influences best-path, etc.",
    "Each command's documented effect observed in `show bgp l2vpn evpn`; per spec §2.2 all 8 must be supported.",
)
ENRICHED[("EVPNS-REQ#20", "Basic Functionality", 1)] = (
    "Verify default behavior when no BGP common CLI commands are explicitly configured.",
    "BGP defaults apply; sessions establish; routes exchange normally.",
)
ENRICHED[("EVPNS-REQ#20", "On The Fly changes", 0)] = (
    "Modify maximum-prefix value while the EVPN session is established and exchanging Type-2 routes.",
    "New limit takes effect; if current count > new limit, documented overflow behavior triggers; existing routes remain unless RFC requires withdrawal.",
)
ENRICHED[("EVPNS-REQ#20", "Upgrade", 0)] = (
    "With all 8 BGP CLI commands configured under l2vpn evpn, run onie-install upgrade.",
    "After reboot, all commands restore correctly; BGP session re-establishes; commands continue to apply.",
)
ENRICHED[("EVPNS-REQ#20", "Management", 0)] = (
    "Configure each BGP common CLI command via NETCONF/YANG.",
    "NETCONF transactions commit; equivalent CLI is generated; behavior identical to CLI configuration.",
)
ENRICHED[("EVPNS-REQ#20", "3rd Party Interoperability", 0)] = (
    "Configure route-reflector-client toward a 3rd-party PE; verify EVPN routes are reflected per RFC4456.",
    "Routes from one client are reflected to another via the local PE; no loops; cluster-id and originator-id propagate correctly.",
)
ENRICHED[("EVPNS-REQ#20", "Packet validation", 0)] = (
    "Send well-formed BGP UPDATEs that exercise each enabled common CLI feature.",
    "All accepted; route table reflects expected post-feature behavior.",
)
ENRICHED[("EVPNS-REQ#20", "Feature interaction", 0)] = (
    "Combine route-reflector-client with maximum-prefix and allow-as-in on the same neighbor.",
    "All three operate together without regression; counters increment correctly.",
)
ENRICHED[("EVPNS-REQ#20", "Performance", 0)] = (
    "Measure BGP UPDATE processing latency under maximum-prefix limit (e.g. 50k routes incoming).",
    "Processing within documented bounds; CPU usage steady-state.",
)
ENRICHED[("EVPNS-REQ#20", "Scale", 0)] = (
    "Configure maximum-prefix to a large value (50k+) and stress with that many EVPN routes.",
    "Limit enforced; documented overflow behavior triggers cleanly; no crash.",
)
ENRICHED[("EVPNS-REQ#20", "Long run", 0)] = (
    "Run a configured route-reflector-client setup for ≥ 24 hours under steady traffic.",
    "No memory leaks; route counts stable; no spurious withdrawals.",
)
ENRICHED[("EVPNS-REQ#20", "Tech-support", 0)] = (
    "Collect tech-support with all 8 BGP common CLI commands active.",
    "Archive includes `show running-config`, `show bgp l2vpn evpn neighbor`, capability negotiation logs, prefix-count history.",
)


# ─── EVPNS-REQ#40 VLAN-Based Bundle Service Type ──────────────────────────
# §2.3.2: vlan-bundle on agg-eth/x-eth, vlan-id 1-4 example, drops mismatched
ENRICHED[("EVPNS-REQ#40", "CLI configuration", 0)] = (
    "Configure an EVPN instance of `service-type vlan-bundle` on agg-eth 1.1 and x-eth 0/0/1.1 with `vlan-id 1-4` per §2.3.2.2; enable l2-transport on all three; save and reload.",
    "EVPN instance appears in `show l2-services evpn` with vlan-bundle type and the configured vlan-id range; bundle membership matches.",
)
ENRICHED[("EVPNS-REQ#40", "CLI configuration", 1)] = (
    "Edit the bundle range from `vlan-id 1-4` to `vlan-id 1-8`; commit.",
    "Updated range visible in running config; bundle membership widens; existing in-range traffic continues uninterrupted.",
)
ENRICHED[("EVPNS-REQ#40", "CLI configuration", 2)] = (
    "Delete the vlan-bundle EVPN instance; commit.",
    "Instance removed; sub-interfaces freed; BGP routes for the bundle withdrawn.",
)
ENRICHED[("EVPNS-REQ#40", "CLI configuration", 3)] = (
    "Apply factory-default; replay the vlan-bundle configuration.",
    "All settings restore identically; bundle re-forms with the same vlan-id range.",
)
ENRICHED[("EVPNS-REQ#40", "CLI configuration", 4)] = (
    "Make a bundle range change, then rollback before commit.",
    "Range reverts; no BGP route flap; in-range traffic uninterrupted.",
)
ENRICHED[("EVPNS-REQ#40", "Basic Functionality", 0)] = (
    "Send tagged frames with vlan-id 1, 2, 3, 4 on the bundle (range 1-4); verify all forwarded across EVPN.",
    "All in-range vlan-ids forward correctly; MACs learned per-vlan; per spec MUST behavior holds across the full bundle range.",
)
ENRICHED[("EVPNS-REQ#40", "Basic Functionality", 1)] = (
    "Verify default behavior of vlan-bundle without explicit bundle range (single vlan-id default).",
    "Single vlan-id default applied per implementation; forwarding works; no spurious alarms.",
)
ENRICHED[("EVPNS-REQ#40", "On The Fly changes", 0)] = (
    "While bundle traffic is flowing on vlan-id 2, change the bundle range from 1-4 to 5-8 (excluding the active vlan-id).",
    "Active in-flight traffic is now out-of-range and dropped per spec MUST: 'An input frame with VLAN-ID not belonging to configured bundle must be dropped.'",
)
ENRICHED[("EVPNS-REQ#40", "Packet validation", 0)] = (
    "Send valid tagged frames with vlan-id values 1, 2, 3, 4 (in-range).",
    "All forwarded; MAC learning + Type-2 advertisements work for each vlan-id.",
)
ENRICHED[("EVPNS-REQ#40", "Malformed/unsupported packets", 0)] = (
    "Send tagged frames with vlan-id 5, 99, 4095 (all out-of-range for the 1-4 bundle).",
    "All dropped per spec MUST: 'An input frame with VLAN-ID not belonging to configured bundle must be dropped.' Drop counter increments; syslog records the event.",
)
ENRICHED[("EVPNS-REQ#40", "Feature interaction", 0)] = (
    "Combine vlan-bundle with multi-homing (LACP LAG ESI Type 1).",
    "Bundle works on the multi-homed segment; DF election still operates per-vlan within the bundle range; no regression.",
)
ENRICHED[("EVPNS-REQ#40", "Performance", 0)] = (
    "Push line-rate traffic across all 4 vlan-ids in a 1-4 bundle simultaneously.",
    "Total throughput within ±2% of line rate; per-vlan distribution proportional.",
)
ENRICHED[("EVPNS-REQ#40", "Upgrade", 0)] = (
    "With vlan-bundle configured, run onie-install upgrade.",
    "Configuration restores after reboot; bundle re-forms; vlan-id range preserved.",
)
ENRICHED[("EVPNS-REQ#40", "Management", 0)] = (
    "Configure vlan-bundle (vlan-id 1-4 on x-eth 0/0/1.1) via NETCONF/YANG.",
    "NETCONF commit produces equivalent CLI; behavior matches.",
)
ENRICHED[("EVPNS-REQ#40", "Tech-support", 0)] = (
    "Collect tech-support after exercising the vlan-bundle.",
    "Archive contains `show l2-services evpn`, drop counters per vlan, BGP route-type 2 dump.",
)


# ─── EVPNS-REQ#50 VLAN-Aware Bundle Service Interface Type ────────────────
# §2.3.3: vlan-aware-bundle, vlan-id 1-4094 default; example shows
# evpn1=vlan-id 1-3, evpn2=vlan-id 4-5, evpn3=vlan-id 10
ENRICHED[("EVPNS-REQ#50", "CLI configuration", 0)] = (
    "Configure 3 EVPN instances of `service-type vlan-aware-bundle` on x-eth 0/0/1: evpn1=vlan-id 1-3, evpn2=vlan-id 4-5, evpn3=vlan-id 10 per §2.3.3.2 example 2; commit.",
    "All 3 instances active; non-overlapping vlan-id ranges; `show l2-services evpn` lists each with its bundle membership.",
)
ENRICHED[("EVPNS-REQ#50", "CLI configuration", 1)] = (
    "Extend evpn1 bundle from `vlan-id 1-3` to `vlan-id 1-4094` (full range, per §2.3.3.2 example 1).",
    "Range widened; if it overlaps another instance's vlan-id, configuration is rejected with a clear error; otherwise commit succeeds.",
)
ENRICHED[("EVPNS-REQ#50", "CLI configuration", 2)] = (
    "Delete evpn3; commit.",
    "Instance removed; vlan-id 10 no longer mapped to any EVPN; BGP routes withdrawn.",
)
ENRICHED[("EVPNS-REQ#50", "CLI configuration", 3)] = (
    "Apply factory-default; replay the 3-instance vlan-aware-bundle configuration.",
    "All 3 EVPN instances restore identically; vlan-id ranges match.",
)
ENRICHED[("EVPNS-REQ#50", "CLI configuration", 4)] = (
    "Make a vlan-aware-bundle range change, then rollback before commit.",
    "Range reverts; no BGP route flap.",
)
ENRICHED[("EVPNS-REQ#50", "Basic Functionality", 0)] = (
    "Send tagged BUM and unicast traffic on each in-range vlan-id (1, 2, 3 to evpn1; 4, 5 to evpn2; 10 to evpn3).",
    "Each frame is forwarded within its EVPN instance only; MAC learning isolated per-vlan-aware-bundle EVI; ETID populated correctly in BGP routes.",
)
ENRICHED[("EVPNS-REQ#50", "Basic Functionality", 1)] = (
    "Verify default behavior when bundle range is omitted (defaults to vlan-id 1-4094).",
    "Default behavior accepts all VLANs into the EVPN; no spurious drops.",
)
ENRICHED[("EVPNS-REQ#50", "On The Fly changes", 0)] = (
    "While vlan-aware-bundle traffic is flowing, narrow the bundle range to exclude an in-flight vlan-id.",
    "Excluded vlan-id BUM traffic is dropped per spec MUST: 'An input BUM frame with VLAN-ID not belonging to configured bundle must be dropped.'",
)
ENRICHED[("EVPNS-REQ#50", "Packet validation", 0)] = (
    "Send valid BUM frames per in-range vlan-id; verify per-vlan ETID in advertised Type-3 (Inclusive Multicast) routes.",
    "ETID matches the source vlan-id; Type-3 routes carry correct PMSI tunnel attribute.",
)
ENRICHED[("EVPNS-REQ#50", "Malformed/unsupported packets", 0)] = (
    "Send BUM frames with vlan-id outside any configured bundle (e.g. vlan-id 99 when bundles are 1-3, 4-5, 10).",
    "Frames dropped per spec MUST; drop counter increments per source interface; syslog records the event.",
)
ENRICHED[("EVPNS-REQ#50", "Feature interaction", 0)] = (
    "Combine vlan-aware-bundle with multi-homing on the same physical interface.",
    "Per-vlan DF election operates within each bundle's range; no cross-bundle leakage.",
)
ENRICHED[("EVPNS-REQ#50", "Performance", 0)] = (
    "Push BUM and unicast traffic across all 3 vlan-aware-bundles simultaneously.",
    "Aggregate throughput within ±2% of line rate; per-bundle distribution proportional to vlan-id range size.",
)
ENRICHED[("EVPNS-REQ#50", "Upgrade", 0)] = (
    "With multiple vlan-aware-bundle instances, run onie-install upgrade.",
    "All instances restore after reboot; bundle ranges preserved.",
)
ENRICHED[("EVPNS-REQ#50", "Management", 0)] = (
    "Configure 3 vlan-aware-bundle EVPN instances via NETCONF/YANG.",
    "All commit successfully; equivalent CLI is generated; behavior identical.",
)
ENRICHED[("EVPNS-REQ#50", "Tech-support", 0)] = (
    "Collect tech-support after exercising vlan-aware-bundle traffic.",
    "Archive includes per-bundle MAC table snapshots, ETID-tagged BGP route dumps, drop counters.",
)


# ─── EVPNS-REQ#60 Port-Based Service Interface Type ───────────────────────
# §2.3.4: service-type port-based on agg-eth and x-eth (no sub-interface)
ENRICHED[("EVPNS-REQ#60", "CLI configuration", 0)] = (
    "Configure an EVPN instance of `service-type port-based` on agg-eth 1 and x-eth 0/0/1 (no sub-interface) per §2.3.4.1; enable l2-transport on the parent interfaces; commit.",
    "EVPN instance shows port-based type; entire physical/LAG bandwidth is mapped to this EVI; `show l2-services evpn` reflects the membership.",
)
ENRICHED[("EVPNS-REQ#60", "CLI configuration", 1)] = (
    "Edit the port-based EVPN to add a second physical interface; commit.",
    "Membership extended; new interface contributes traffic to the EVI; running config matches.",
)
ENRICHED[("EVPNS-REQ#60", "CLI configuration", 2)] = (
    "Delete the port-based EVPN instance; commit.",
    "Instance removed; member interfaces freed; routes withdrawn.",
)
ENRICHED[("EVPNS-REQ#60", "CLI configuration", 3)] = (
    "Apply factory-default; replay the port-based configuration.",
    "Configuration restores identically; instance re-forms.",
)
ENRICHED[("EVPNS-REQ#60", "CLI configuration", 4)] = (
    "Make a port-based config change, then rollback before commit.",
    "Configuration reverts; no BGP route flap.",
)
ENRICHED[("EVPNS-REQ#60", "Basic Functionality", 0)] = (
    "Send tagged AND untagged traffic into the port-based interface; verify all is forwarded transparently across EVPN.",
    "Both tagged and untagged frames forward; entire port traffic is mapped to one EVI without per-vlan filtering.",
)
ENRICHED[("EVPNS-REQ#60", "Basic Functionality", 1)] = (
    "Verify default behavior of port-based service when no specific vlan-id is set.",
    "All vlans accepted into the EVI by default per port-based service definition.",
)
ENRICHED[("EVPNS-REQ#60", "On The Fly changes", 0)] = (
    "Add a new member interface to the port-based EVI while traffic flows.",
    "New interface joins; existing traffic uninterrupted; new interface starts forwarding immediately.",
)
ENRICHED[("EVPNS-REQ#60", "Packet validation", 0)] = (
    "Send mixed-vlan and untagged traffic; verify all is encapsulated and forwarded.",
    "All frames forward with correct MPLS label; MAC learning works regardless of vlan tag.",
)
ENRICHED[("EVPNS-REQ#60", "Malformed/unsupported packets", 0)] = (
    "Send obviously malformed frames (truncated, bad FCS) into a port-based interface.",
    "Frames dropped at the input pipeline before EVI processing; counters increment.",
)
ENRICHED[("EVPNS-REQ#60", "Feature interaction", 0)] = (
    "Combine port-based EVI with multi-homing on the same LAG.",
    "Both features coexist; DF election still operates; per spec port-based EVI sees all vlans on the multi-homed segment.",
)
ENRICHED[("EVPNS-REQ#60", "Performance", 0)] = (
    "Push line-rate mixed-vlan traffic into the port-based EVI.",
    "Throughput at line rate; no per-vlan overhead since no per-vlan filtering applies.",
)
ENRICHED[("EVPNS-REQ#60", "Upgrade", 0)] = (
    "With port-based EVI configured, run onie-install upgrade.",
    "Configuration restores; EVI re-forms; member interfaces re-attach.",
)
ENRICHED[("EVPNS-REQ#60", "Management", 0)] = (
    "Configure port-based EVI via NETCONF/YANG.",
    "NETCONF commit produces equivalent CLI; behavior identical.",
)
ENRICHED[("EVPNS-REQ#60", "Tech-support", 0)] = (
    "Collect tech-support after exercising port-based EVI.",
    "Archive contains MAC table snapshots, member interface counters, BGP route-type 2 dumps.",
)


# ─── EVPNS-REQ#70 Router Distinguisher (auto-generated) ───────────────────
# §2.4: Type 1 RD; admin = loopback 0 IPv4; assigned number = unique EVI number
ENRICHED[("EVPNS-REQ#70", "CLI configuration", 0)] = (
    "Configure loopback 0 with an IPv4 address (e.g. 10.10.10.10); create an EVPN instance with no explicit RD; commit and observe.",
    "Per spec, RD auto-generated as Type 1 with admin=10.10.10.10 (loopback 0 IP) and assigned-number=unique EVPN Instance number; visible in `show l2-services evpn detail`.",
)
ENRICHED[("EVPNS-REQ#70", "CLI configuration", 1)] = (
    "Change loopback 0 IPv4 from 10.10.10.10 to 10.20.20.20; commit.",
    "All auto-generated RDs reflect the new admin field on next refresh; existing routes withdraw and re-advertise under the new RD.",
)
ENRICHED[("EVPNS-REQ#70", "CLI configuration", 2)] = (
    "Delete the EVPN instance and re-create it; observe the assigned-number portion of the auto-generated RD.",
    "Auto-generated RD has a unique assigned-number per instance per spec; it is stable across reload of the same instance.",
)
ENRICHED[("EVPNS-REQ#70", "CLI configuration", 3)] = (
    "Apply factory-default; recreate loopback 0 + EVPN instance; verify same RD generation pattern.",
    "RD format consistent: Type 1 with loopback 0 IPv4 admin field; assigned-number reproducible per instance configuration.",
)
ENRICHED[("EVPNS-REQ#70", "CLI configuration", 4)] = (
    "Modify loopback 0 IP, then rollback before commit.",
    "Loopback IP reverts; auto-generated RDs unchanged; no route flap.",
)
ENRICHED[("EVPNS-REQ#70", "Basic Functionality", 0)] = (
    "Verify auto-generated RD format in advertised BGP routes is Type 1 (admin: 4-byte IPv4, assigned: 2-byte number).",
    "Wireshark capture or `show bgp l2vpn evpn detail` shows RD with the spec format; admin field equals loopback 0; assigned-number is unique per EVI.",
)
ENRICHED[("EVPNS-REQ#70", "Basic Functionality", 1)] = (
    "Verify that creating multiple EVIs results in different assigned-numbers for the auto-generated RD.",
    "Each EVI has a unique RD (admin same, assigned-number different); no collisions.",
)
ENRICHED[("EVPNS-REQ#70", "On The Fly changes", 0)] = (
    "Change loopback 0 IPv4 while routes are advertising.",
    "RD admin field updates; routes withdraw and re-advertise under the new RD; convergence within bounds.",
)
ENRICHED[("EVPNS-REQ#70", "Packet validation", 0)] = (
    "Capture BGP UPDATE messages and verify RD encoding per RFC4364 Type 1 format.",
    "RD bytes parse correctly: 2-byte type=1, 4-byte admin (IPv4), 2-byte assigned-number.",
)
ENRICHED[("EVPNS-REQ#70", "Feature interaction", 0)] = (
    "Combine auto-generated RD with explicit RT configuration; verify both work together.",
    "Auto-RD applied; explicit RTs imported/exported per configuration; routes are unique per (RD, MAC).",
)
ENRICHED[("EVPNS-REQ#70", "3rd Party Interoperability", 0)] = (
    "Receive BGP routes from a 3rd-party PE with various RD formats (Type 0, 1, 2).",
    "All 3 RD types parsed correctly per RFC4364; no NOTIFICATION on receipt.",
)
ENRICHED[("EVPNS-REQ#70", "Upgrade", 0)] = (
    "With auto-generated RDs in use, run onie-install upgrade.",
    "Loopback 0 + EVI configurations restore; auto-generated RDs are reproducible across the upgrade.",
)
ENRICHED[("EVPNS-REQ#70", "Management", 0)] = (
    "Query the auto-generated RD via NETCONF; verify the operational data exposes it.",
    "NETCONF GET returns the same RD value as the CLI `show l2-services evpn detail`.",
)
ENRICHED[("EVPNS-REQ#70", "Tech-support", 0)] = (
    "Collect tech-support after EVI creation/deletion exercises.",
    "Archive contains RD generation history, loopback 0 IP, BGP route dumps showing the auto-RD.",
)


# ─── EVPNS-REQ#80 Static MAC Addresses (additional) ───────────────────────
ENRICHED[("EVPNS-REQ#80", "Upgrade", 0)] = (
    "With 5 static MACs configured, run onie-install upgrade.",
    "Static MACs restore after reboot; corresponding Type-2 routes re-advertise; static flag preserved.",
)
ENRICHED[("EVPNS-REQ#80", "Management", 0)] = (
    "Configure 5 static MAC entries via NETCONF/YANG.",
    "NETCONF commit succeeds; equivalent CLI generated; static MACs appear in `show mac-address-table static`.",
)


# ─── EVPNS-REQ#90 Local MAC Learning (data-plane only on local CEs) ───────
# §2.6.2: data-plane MAC learning by software on interfaces attached to local CEs;
# control-plane learning on these interfaces is NOT supported; LACP MACs not permitted
ENRICHED[("EVPNS-REQ#90", "CLI configuration", 0)] = (
    "Configure an EVPN instance with a local CE attached on x-eth 0/0/1.4; ensure data-plane MAC learning is enabled (default per §2.6.2); commit.",
    "Data-plane learning visible in `show mac-address-table evpn` as MACs arrive; per spec MUST: 'Data-Plane MAC learning by software on interfaces attached to local CEs.'",
)
ENRICHED[("EVPNS-REQ#90", "CLI configuration", 1)] = (
    "Attempt to enable control-plane learning on a local CE interface (per §2.6.2 this is NOT supported).",
    "Configuration rejected with a clear error message: control-plane learning on local CE interfaces is unsupported per spec.",
)
ENRICHED[("EVPNS-REQ#90", "CLI configuration", 2)] = (
    "Delete the local CE interface from the EVPN; commit.",
    "Locally learned MACs from that interface aged out; corresponding Type-2 routes withdrawn.",
)
ENRICHED[("EVPNS-REQ#90", "CLI configuration", 3)] = (
    "Apply factory-default; replay the local-CE EVPN configuration.",
    "Data-plane learning re-engages on the local CE interface; MACs re-learn as traffic arrives.",
)
ENRICHED[("EVPNS-REQ#90", "CLI configuration", 4)] = (
    "Make a local CE config change, then rollback before commit.",
    "Configuration reverts; existing MAC learning continues uninterrupted.",
)
ENRICHED[("EVPNS-REQ#90", "Basic Functionality", 0)] = (
    "Send unicast frames with new source MACs from a local CE; verify each MAC is learned in the EVPN MAC table within data-plane learning latency.",
    "MACs appear in `show mac-address-table evpn` with type=local, dynamic; corresponding Type-2 EVPN routes advertised within 100 ms.",
)
ENRICHED[("EVPNS-REQ#90", "Basic Functionality", 1)] = (
    "Verify per spec MUST: 'MAC learning from the LACP messages is not permitted.' Send LACPDU traffic from the CE side.",
    "LACPDU source MACs are NOT learned into the EVPN MAC table; LACP protocol still operates correctly for the LAG itself.",
)
ENRICHED[("EVPNS-REQ#90", "On The Fly changes", 0)] = (
    "Change the local CE interface (move from x-eth 0/0/1.4 to x-eth 0/0/2.4) while traffic flows.",
    "Existing MAC entries age out from the old interface; new MACs learned on the new interface; per-flow load balancing during the transition.",
)
ENRICHED[("EVPNS-REQ#90", "Upgrade", 0)] = (
    "With locally learned MACs active, run onie-install upgrade.",
    "MAC table re-builds via data-plane learning after reboot; per spec no control-plane learning is attempted on local CE interfaces.",
)
ENRICHED[("EVPNS-REQ#90", "Management", 0)] = (
    "Query locally learned MACs via NETCONF on the operational data tree.",
    "NETCONF returns the same data as `show mac-address-table evpn type local`.",
)
ENRICHED[("EVPNS-REQ#90", "Tech-support", 0)] = (
    "Collect tech-support after exercising local MAC learning.",
    "Archive contains MAC table dumps, learning-rate counters, LACPDU MAC suppression evidence.",
)


# ─── EVPNS-REQ#100 Remote MAC Learning (control-plane via BGP) ────────────
# §2.6.3: Remote MAC learning per RFC7432bis ch.9.2 must be supported (control-plane)
ENRICHED[("EVPNS-REQ#100", "Basic Functionality", 0)] = (
    "Have a remote PE advertise a Type-2 EVPN route for MAC AA:BB:CC:00:00:01 via BGP; verify the local PE installs it as a remote MAC entry per RFC7432bis ch.9.2.",
    "MAC appears in `show mac-address-table evpn` with type=remote, BGP-learned; egress points to the remote PE's MPLS tunnel; per spec MUST: 'The Remote MAC learning MUST be supported.'",
)
ENRICHED[("EVPNS-REQ#100", "Basic Functionality", 1)] = (
    "Verify default behavior when no remote Type-2 routes are received: the EVPN MAC table contains only local entries.",
    "`show mac-address-table evpn type remote` returns empty; only locally-learned MACs present.",
)
ENRICHED[("EVPNS-REQ#100", "3rd Party Interoperability", 0)] = (
    "Receive Type-2 routes from a 3rd-party PE per RFC7432bis ch.9.2; verify all required fields parse correctly.",
    "Routes installed; remote MACs reachable via the advertised MPLS label.",
)
ENRICHED[("EVPNS-REQ#100", "Tech-support", 0)] = (
    "Collect tech-support after exercising remote MAC learning across multiple peers.",
    "Archive contains BGP route-type 2 dumps, per-peer MAC learning histograms, and the resulting MAC table.",
)


# ─── EVPNS-REQ#110 EVPN ESI and ES types (0, 1, 4) ────────────────────────
# §2.7.1: ESI Type 0 (manual/single-home), Type 1 (LACP LAG only), Type 4 (single-home interface)
ENRICHED[("EVPNS-REQ#110", "CLI configuration", 0)] = (
    "Configure 3 ethernet-segments — Type 0 (manual ESI on agg-eth 1), Type 1 (LACP LAG agg-eth 2 with lacp-system-mac and lacp-key), Type 4 (single-home x-eth 0/0/1) per §2.7.1; commit.",
    "All 3 ESI types active per `show evpn ethernet-segment`; each shows the correct esi-value format; per spec only Types 0/1/4 supported.",
)
ENRICHED[("EVPNS-REQ#110", "CLI configuration", 1)] = (
    "Edit ESI Type 1 to change the lacp-system-mac on one PE; commit.",
    "ESI value updates; LACP LAG re-converges; mismatched lacp-system-mac with the peer triggers an alarm per REQ#390.",
)
ENRICHED[("EVPNS-REQ#110", "CLI configuration", 2)] = (
    "Delete the Type 4 ESI from x-eth 0/0/1; commit.",
    "ESI removed; interface returns to single-home without ESI advertisement; ES route (4) withdrawn.",
)
ENRICHED[("EVPNS-REQ#110", "CLI configuration", 3)] = (
    "Apply factory-default; replay all 3 ESI configurations.",
    "All 3 ESIs restore identically; LACP LAGs re-establish with the same system-mac/key.",
)
ENRICHED[("EVPNS-REQ#110", "CLI configuration", 4)] = (
    "Make an ESI value change on Type 0, then rollback before commit.",
    "ESI reverts; no transient ES route flap.",
)
ENRICHED[("EVPNS-REQ#110", "Basic Functionality", 0)] = (
    "Verify each ESI type behaves per spec: Type 0 = manual single-home, Type 1 = LACP-derived multi-home, Type 4 = single-home interface.",
    "Type 1 derives ESI from LACP system-mac + port-key per RFC; Type 4 advertises as single-active in EthA-D Per ES route; Type 0 supports manual ESI assignment.",
)
ENRICHED[("EVPNS-REQ#110", "Basic Functionality", 1)] = (
    "Attempt to configure ESI Type 2 or Type 3 (NOT supported per spec); verify rejection.",
    "Configuration rejected with a clear error: only ESI types 0, 1, 4 are supported.",
)
ENRICHED[("EVPNS-REQ#110", "Robustness", 0)] = (
    "Reset a PE participating in ESI Type 1 (LACP LAG) multi-homing.",
    "ES route (4) withdrawn during reset; backup PE picks up DF role; on PE re-up, ES route re-advertises with same ESI value.",
)
ENRICHED[("EVPNS-REQ#110", "Robustness", 1)] = (
    "Power-cycle the PE with Type 1 ESI active.",
    "LACP re-converges on power-up; ESI value preserved; multi-homing topology stable post recovery.",
)
ENRICHED[("EVPNS-REQ#110", "Robustness", 2)] = (
    "Flap the LAG member interface on a Type 1 ESI.",
    "LACP re-converges; ESI unchanged; if all members down, ES becomes unreachable temporarily.",
)
ENRICHED[("EVPNS-REQ#110", "HA", 0)] = (
    "Kill the LACP process on a PE participating in Type 1 ESI.",
    "LACP restarts; LAG re-converges; ESI re-derived consistently; multi-homing stable.",
)
ENRICHED[("EVPNS-REQ#110", "Long run", 0)] = (
    "Run a 3-PE multi-homed Type 1 ESI for ≥ 24 hours under steady traffic.",
    "ESI value stable; no spurious DF re-elections; LACP counters monotonic.",
)
ENRICHED[("EVPNS-REQ#110", "Feature interaction", 0)] = (
    "Combine Type 1 ESI multi-homing with MAC mobility (REQ#160).",
    "MACs migrating between multi-homed CEs are tracked correctly; sequence numbers update; aliasing path operates per §2.7.4.",
)
ENRICHED[("EVPNS-REQ#110", "3rd Party Interoperability", 0)] = (
    "Interop Type 1 ESI with a 3rd-party PE on the same LACP LAG.",
    "ESI derivation matches across vendors per RFC7432bis; LAG forms; DF election runs across both PEs.",
)
ENRICHED[("EVPNS-REQ#110", "Packet validation", 0)] = (
    "Send unicast traffic into a Type 1 ESI multi-homed CE; verify aliasing distributes flows.",
    "Per-flow load balancing across the two PEs of the multi-homed segment per §2.7.4 aliasing path.",
)
ENRICHED[("EVPNS-REQ#110", "Performance", 0)] = (
    "Measure DF election convergence time across the 3 ESI types when a PE goes down.",
    "Convergence within fast-convergence bounds for Type 1 (multi-home); not applicable for Type 4 (single-home); per spec all 3 types behave per RFC7432bis.",
)
ENRICHED[("EVPNS-REQ#110", "Upgrade", 0)] = (
    "With all 3 ESI types configured, run onie-install upgrade.",
    "All ESIs restore; LACP LAGs re-establish; ESI values preserved.",
)
ENRICHED[("EVPNS-REQ#110", "Management", 0)] = (
    "Configure 3 ESI types via NETCONF/YANG.",
    "NETCONF transactions commit; equivalent CLI generated; ESI values match.",
)
ENRICHED[("EVPNS-REQ#110", "Tech-support", 0)] = (
    "Collect tech-support with all 3 ESI types active.",
    "Archive contains `show evpn ethernet-segment`, LACP state, ES route (4) dumps, alarms history.",
)


# ─── EVPNS-REQ#120 Designated Forwarder Election (additional) ─────────────
ENRICHED[("EVPNS-REQ#120", "Performance", 0)] = (
    "Measure DF election time when a PE goes down (Type 1 ESI, highest-random-weight algorithm).",
    "Election converges within RFC8584 fast-convergence bounds; new DF takes over BUM forwarding promptly.",
)
ENRICHED[("EVPNS-REQ#120", "Scale", 0)] = (
    "Scale to documented number of multi-homed ESes per PE; run DF election on all simultaneously.",
    "All ESes converge; per-ES DF state correct; CPU within bounds.",
)
ENRICHED[("EVPNS-REQ#120", "Upgrade", 0)] = (
    "With multiple multi-homed ESes + service-carving configured, run onie-install upgrade.",
    "Configurations restore; DF election re-runs after BGP re-establishes.",
)


# ─── EVPNS-REQ#130 Signaling Primary and Backup DF Elected PEs ────────────
# §2.7.3 / RFC7432bis ch.8.6
ENRICHED[("EVPNS-REQ#130", "Basic Functionality", 0)] = (
    "Configure a 2-PE multi-homed ES; verify Primary DF and Backup DF roles are signaled per RFC7432bis ch.8.6.",
    "Both PEs advertise their roles in the EthA-D Per ES route; `show evpn ethernet-segment` shows Primary on one, Backup on the other; per spec MUST: 'The Signaling Primary and Backup DF Elected PEs MUST be supported.'",
)
ENRICHED[("EVPNS-REQ#130", "Basic Functionality", 1)] = (
    "Verify default Primary/Backup signaling behavior with no explicit preference configuration.",
    "Default election determines roles deterministically; both PEs agree on the assignment.",
)
ENRICHED[("EVPNS-REQ#130", "Robustness", 0)] = (
    "Reset the Primary DF PE; verify the Backup takes over and re-signals.",
    "Backup becomes Primary within RFC7432bis convergence bounds; new Backup elected (or none if no other PE); BUM traffic continues.",
)
ENRICHED[("EVPNS-REQ#130", "Robustness", 1)] = (
    "Power-cycle the Primary DF PE during BUM traffic.",
    "Backup takes over; on Primary re-up, role re-negotiation occurs; no permanent black-hole.",
)
ENRICHED[("EVPNS-REQ#130", "Robustness", 2)] = (
    "Flap the LAG interface on the Primary DF PE.",
    "Election re-runs; Primary/Backup may swap depending on per-vlan service-carving result; signaling updates.",
)
ENRICHED[("EVPNS-REQ#130", "HA", 0)] = (
    "Kill BGP process on the Primary DF; verify Backup PE takes Primary role.",
    "BGP restarts; on re-establishment, Primary re-asserts (or Backup retains depending on timing); BUM forwarding maintained.",
)
ENRICHED[("EVPNS-REQ#130", "Long run", 0)] = (
    "Run Primary/Backup signaling under steady traffic for ≥ 24 hours; periodically force role changes.",
    "Each role change signals correctly; no stuck states; per-VLAN signaling consistent.",
)
ENRICHED[("EVPNS-REQ#130", "Feature interaction", 0)] = (
    "Combine Primary/Backup signaling with multi-EVI on the same multi-homed ES.",
    "Primary/Backup roles signal independently per VLAN/EVI per service-carving algorithm.",
)
ENRICHED[("EVPNS-REQ#130", "3rd Party Interoperability", 0)] = (
    "Interop Primary/Backup signaling with a 3rd-party PE on the same multi-homed segment.",
    "Roles negotiate correctly per RFC7432bis ch.8.6; both PEs converge to the same Primary/Backup assignment.",
)
ENRICHED[("EVPNS-REQ#130", "Tech-support", 0)] = (
    "Collect tech-support after multiple Primary/Backup transitions.",
    "Archive contains role transition history, BGP route updates carrying the signaling, and election state.",
)


# ─── EVPNS-REQ#140 Aliasing Path (RFC7432bis ch.8.4) ──────────────────────
ENRICHED[("EVPNS-REQ#140", "Basic Functionality", 0)] = (
    "Configure 2 PEs multi-homed (all-active) on the same ES with a CE behind them; send unicast traffic from a remote PE.",
    "Remote PE load-balances unicast flows across the 2 multi-homed PEs per §2.7.4 aliasing path; per spec MUST: 'The Aliasing path MUST be supported.'",
)
ENRICHED[("EVPNS-REQ#140", "Basic Functionality", 1)] = (
    "Verify default aliasing behavior when only one PE of the multi-homed set is reachable.",
    "Aliasing falls back to the single reachable PE; no traffic loss.",
)
ENRICHED[("EVPNS-REQ#140", "Robustness", 0)] = (
    "Reset one of the multi-homed PEs while aliased traffic flows.",
    "Remote PE detects via EthA-D Per ES route withdrawal; aliasing path narrows to the surviving PE; flows re-balance.",
)
ENRICHED[("EVPNS-REQ#140", "Robustness", 1)] = (
    "Power-cycle one of the multi-homed PEs.",
    "Aliasing recovers as the PE returns; flow distribution re-balances.",
)
ENRICHED[("EVPNS-REQ#140", "Robustness", 2)] = (
    "Flap the access interface on one multi-homed PE.",
    "EthA-D Per ES route flapped; aliasing path re-evaluated each transition.",
)
ENRICHED[("EVPNS-REQ#140", "HA", 0)] = (
    "Kill BGP on one multi-homed PE while aliasing is in use.",
    "Aliasing narrows to the surviving PE during the BGP outage; restores when BGP re-establishes.",
)
ENRICHED[("EVPNS-REQ#140", "Long run", 0)] = (
    "Run aliased unicast traffic for ≥ 24 hours with periodic PE failures.",
    "No memory leaks; flow distribution converges after each failure within fast-convergence bounds.",
)
ENRICHED[("EVPNS-REQ#140", "Feature interaction", 0)] = (
    "Combine aliasing with MAC mobility (REQ#160).",
    "Aliased flows tracked correctly during MAC migration; sequence numbers honored.",
)
ENRICHED[("EVPNS-REQ#140", "3rd Party Interoperability", 0)] = (
    "Interop aliasing with a 3rd-party remote PE per RFC7432bis ch.8.4.",
    "3rd-party PE balances flows correctly across the 2 multi-homed PEs; same MPLS label semantics.",
)
ENRICHED[("EVPNS-REQ#140", "Tech-support", 0)] = (
    "Collect tech-support after exercising aliasing.",
    "Archive contains EthA-D Per ES route dumps, per-flow distribution counters, MAC table snapshots.",
)


# ─── EVPNS-REQ#150 Single-Active, All-Active and Load Balancing ───────────
ENRICHED[("EVPNS-REQ#150", "Basic Functionality", 0)] = (
    "Configure ESI Type 1 multi-homing with `load-balancing-mode all-active` on both PEs; verify per-flow load balancing.",
    "Per spec MUST: All-active mode supports per-flow load balancing; both PEs forward bidirectional traffic; aliasing distributes flows.",
)
ENRICHED[("EVPNS-REQ#150", "Basic Functionality", 1)] = (
    "Configure ESI Type 1 with `load-balancing-mode single-active` on both PEs; verify per-vlan service carving.",
    "Per spec MUST: Single-active mode supports per-vlan load balancing; carving divides VLAN forwarding responsibility across PEs; CE learns the active path per VLAN via data-plane.",
)
ENRICHED[("EVPNS-REQ#150", "Robustness", 0)] = (
    "Reset the active PE in single-active mode.",
    "Backup PE takes over the affected VLANs; convergence within fast-convergence bounds.",
)
ENRICHED[("EVPNS-REQ#150", "Robustness", 1)] = (
    "Power-cycle one PE in all-active mode.",
    "Surviving PE handles all flows; aliasing path narrows; per-flow load balancing resumes when PE returns.",
)
ENRICHED[("EVPNS-REQ#150", "Robustness", 2)] = (
    "Flap the LAG member interface on one all-active PE.",
    "DF election unaffected for the bundle; flows redistribute based on the surviving members.",
)
ENRICHED[("EVPNS-REQ#150", "HA", 0)] = (
    "Kill the relevant process while all-active load balancing is in use.",
    "Process restarts; load balancing re-stabilizes; per-flow distribution returns to baseline.",
)
ENRICHED[("EVPNS-REQ#150", "Long run", 0)] = (
    "Run all-active load balancing for ≥ 24 hours with bidirectional CE traffic.",
    "Flow distribution stable; no MAC table churn; per-flow stickiness maintained.",
)
ENRICHED[("EVPNS-REQ#150", "Feature interaction", 0)] = (
    "Combine all-active load balancing with MAC mobility (REQ#160).",
    "MAC migrations between all-active PEs handled correctly; aliasing updated; sequence numbers monotonic.",
)
ENRICHED[("EVPNS-REQ#150", "3rd Party Interoperability", 0)] = (
    "Interop all-active load balancing with a 3rd-party PE on the same ES per RFC7432bis ch.14.",
    "Both PEs (Exaware + 3rd party) participate in load balancing; flows distribute correctly.",
)
ENRICHED[("EVPNS-REQ#150", "Packet validation", 0)] = (
    "Send a high-flow-count traffic pattern (e.g. 10k flows) into a multi-homed all-active ES.",
    "Flows distribute across both PEs by 5-tuple hash; no flow flapping; per-flow integrity maintained.",
)
ENRICHED[("EVPNS-REQ#150", "Malformed/unsupported packets", 0)] = (
    "Send malformed BUM traffic into a single-active ES; verify only the active PE forwards.",
    "Non-active PE drops the malformed traffic per Split Horizon; active PE drops if malformed; counters increment.",
)
ENRICHED[("EVPNS-REQ#150", "Performance", 0)] = (
    "Measure throughput and per-flow latency under all-active mode at scale (10k flows, line rate).",
    "Aggregate throughput at line rate × 2 (across both PEs); per-flow latency within bounds.",
)
ENRICHED[("EVPNS-REQ#150", "Tech-support", 0)] = (
    "Collect tech-support with all-active and single-active ES configurations active.",
    "Archive contains load-balancing-mode setting per ES, flow distribution counters, BGP route advertisements.",
)


# ─── EVPNS-REQ#170 Fast Convergence (RFC7432bis ch.8.2) ───────────────────
ENRICHED[("EVPNS-REQ#170", "Basic Functionality", 0)] = (
    "Configure a multi-homed ES; force a failure (link down or PE reboot) and measure MAC mass-withdrawal time per RFC7432bis ch.8.2.",
    "EthA-D Per ES route withdrawn within fast-convergence bounds; remote PEs purge MACs reachable via that ESI; per spec MUST: 'The Fast Convergence MUST be supported.'",
)
ENRICHED[("EVPNS-REQ#170", "Basic Functionality", 1)] = (
    "Verify default fast-convergence behavior with no specific tuning.",
    "Convergence within RFC-recommended defaults; failures detected and signaled within bounds.",
)
ENRICHED[("EVPNS-REQ#170", "Robustness", 0)] = (
    "Reset a multi-homed PE; measure end-to-end traffic interruption at the CE.",
    "Interruption < documented fast-convergence target (typically < 200 ms per RFC).",
)
ENRICHED[("EVPNS-REQ#170", "Robustness", 1)] = (
    "Power-cycle a multi-homed PE; measure recovery time for full reachability.",
    "Reachability restored within BGP/EVPN re-establishment + fast-convergence bounds.",
)
ENRICHED[("EVPNS-REQ#170", "Robustness", 2)] = (
    "Flap the access interface on a multi-homed PE 10 times rapidly.",
    "Each flap triggers fast-convergence; no BGP route oscillation beyond bounds; counters monotonic.",
)
ENRICHED[("EVPNS-REQ#170", "HA", 0)] = (
    "Kill BGP process on a multi-homed PE; measure mass-withdrawal latency.",
    "EthA-D Per ES route withdrawn promptly; remote PEs converge; service impact within bounds.",
)
ENRICHED[("EVPNS-REQ#170", "Long run", 0)] = (
    "Run periodic failures (every 10 min) for ≥ 24 hours; verify each fast-convergence event meets the latency bound.",
    "All measurements meet the bound; no growth in convergence time over the run.",
)
ENRICHED[("EVPNS-REQ#170", "Feature interaction", 0)] = (
    "Combine fast-convergence with all-active load balancing.",
    "Failures trigger mass-withdrawal AND aliasing-path narrowing simultaneously; flow disruption minimal.",
)
ENRICHED[("EVPNS-REQ#170", "3rd Party Interoperability", 0)] = (
    "Interop fast-convergence with a 3rd-party PE per RFC7432bis ch.8.2.",
    "Mass-withdrawal advertisements parsed correctly by the 3rd party; convergence symmetric across vendors.",
)
ENRICHED[("EVPNS-REQ#170", "Tech-support", 0)] = (
    "Collect tech-support after a fast-convergence event.",
    "Archive contains BGP UPDATE timestamps, mass-withdrawal route history, MAC table snapshots before/after.",
)


# ─── EVPNS-REQ#180 Split Horizon (RFC7432bis ch.8.3) ──────────────────────
ENRICHED[("EVPNS-REQ#180", "Basic Functionality", 0)] = (
    "Configure 2 PEs multi-homed on ESI X with all-active load balancing; from a CE on ESI X, send a BUM frame; observe the receive side on the other PE of ESI X.",
    "Per spec MUST: 'The Split Horizon MUST be supported.' BUM frame is forwarded to remote PEs and to the OTHER multi-homed PE on ESI X, but the other PE drops it (split horizon) — does NOT loop back to the same CE.",
)
ENRICHED[("EVPNS-REQ#180", "Basic Functionality", 1)] = (
    "Verify default split-horizon behavior under multiple multi-homed segments simultaneously.",
    "Each ESI's split horizon operates independently; no cross-segment leakage.",
)
ENRICHED[("EVPNS-REQ#180", "Packet validation", 0)] = (
    "Send broadcast/multicast/unknown-unicast frames from a multi-homed CE; capture on the second PE of the same ESI.",
    "Frame received by the second PE is identified as same-ESI ingress and dropped per Split Horizon Label (LT2/LT3); CE does not see duplicate.",
)
ENRICHED[("EVPNS-REQ#180", "Malformed/unsupported packets", 0)] = (
    "Send a BUM frame with a forged/missing Split Horizon Label.",
    "Frame is treated per default rules per RFC; if no SH label, behavior depends on ingress PE; no duplicate frames at CE.",
)
ENRICHED[("EVPNS-REQ#180", "Feature interaction", 0)] = (
    "Combine split horizon with multi-EVI on the same multi-homed ES.",
    "Split horizon applies independently per EVI; per spec multiple EVIs share the ESI but each has its own BUM forwarding.",
)
ENRICHED[("EVPNS-REQ#180", "Performance", 0)] = (
    "Measure BUM forwarding latency through split-horizon decision logic at line rate.",
    "Forwarding latency within hardware datasheet bounds; per-frame split-horizon decision adds no perceptible delay.",
)
ENRICHED[("EVPNS-REQ#180", "Tech-support", 0)] = (
    "Collect tech-support after exercising split-horizon BUM scenarios.",
    "Archive contains ESI-Label assignments, split-horizon drop counters, BUM forwarding logs.",
)


# ─── EVPNS-REQ#190 Interoperability with Single-Homing PEs ────────────────
ENRICHED[("EVPNS-REQ#190", "Basic Functionality", 0)] = (
    "Bring up an EVPN with one Exaware PE single-homed and another multi-homed; per spec the multi-homing procedures must apply even at the single-homing PE.",
    "Single-homing PE participates in multi-homing procedures (ES route observation, MAC mass-withdrawal handling); per spec MUST: 'For single-homing PEs, all the above multihoming procedures can be omitted; however, to allow for single-homing PEs to fully interoperate with multihoming PEs, some of the multihoming procedures described above MUST be supported even by single-homing PEs.'",
)
ENRICHED[("EVPNS-REQ#190", "Basic Functionality", 1)] = (
    "Verify single-homing PE default behavior with no multi-homed peers — multi-homing procedures may be silently dormant.",
    "No spurious advertisements; no alarms; PE operates as standard SH.",
)
ENRICHED[("EVPNS-REQ#190", "Robustness", 0)] = (
    "Reset the single-homing PE while it is participating in multi-homing-required procedures.",
    "On recovery, single-homing PE re-engages multi-homing procedures correctly; no service impact at remote multi-homed segments.",
)
ENRICHED[("EVPNS-REQ#190", "Robustness", 1)] = (
    "Power-cycle the single-homing PE.",
    "PE re-establishes; multi-homing procedures resume.",
)
ENRICHED[("EVPNS-REQ#190", "Robustness", 2)] = (
    "Flap the access interface on a single-homing PE in a mixed deployment.",
    "Only the local CE is affected; multi-homed PEs unaffected; single-homing PE re-learns post-recovery.",
)
ENRICHED[("EVPNS-REQ#190", "HA", 0)] = (
    "Kill BGP on the single-homing PE.",
    "On BGP recovery, multi-homing-related procedures resume correctly.",
)
ENRICHED[("EVPNS-REQ#190", "Long run", 0)] = (
    "Run a mixed single-homing + multi-homing topology for ≥ 24 hours.",
    "All cross-PE procedures stable; no spurious withdrawals; counters monotonic.",
)
ENRICHED[("EVPNS-REQ#190", "Feature interaction", 0)] = (
    "Combine single-homing PE with MAC mobility events from multi-homed peers.",
    "Single-homing PE correctly tracks sequence numbers from multi-homed advertisements.",
)
ENRICHED[("EVPNS-REQ#190", "3rd Party Interoperability", 0)] = (
    "Interop single-homing-only Exaware PE with a 3rd-party multi-homed PE pair.",
    "Single-homing PE correctly observes ES routes and applies multi-homing procedures per RFC7432bis ch.8.7.",
)
ENRICHED[("EVPNS-REQ#190", "Tech-support", 0)] = (
    "Collect tech-support from a single-homing PE in a mixed deployment.",
    "Archive shows participation in multi-homing procedures (ES route observation, mass-withdrawal handling).",
)


# ─── EVPNS-REQ#200 Best Path Selection (RFC7432bis ch.7.13) ────────────────
ENRICHED[("EVPNS-REQ#200", "Basic Functionality", 0)] = (
    "Receive multiple Type-2 routes for the same MAC from different PEs (multi-homed scenario); verify Best Path Selection per RFC7432bis ch.7.13.",
    "Best path selected deterministically per RFC algorithm; preferred path chosen by sequence number, then by next-hop, then by router ID; per spec MUST: 'The Best Path Selection algorithm for EVPN routes must be supported.'",
)
ENRICHED[("EVPNS-REQ#200", "Basic Functionality", 1)] = (
    "Verify default best-path behavior with a single advertised path.",
    "Single path is the best; no comparison required; route installed directly.",
)
ENRICHED[("EVPNS-REQ#200", "Packet validation", 0)] = (
    "Send unicast traffic to a MAC reachable via multiple ECMP paths through best-path selection.",
    "Forwarding plane uses the selected best path; ECMP active if all paths are equal-cost per algorithm.",
)
ENRICHED[("EVPNS-REQ#200", "Malformed/unsupported packets", 0)] = (
    "Receive Type-2 routes with conflicting attributes that cause best-path selection ambiguity.",
    "Algorithm resolves ambiguity per RFC7432bis ch.7.13 deterministically; tie-breaker rules applied; no undefined behavior.",
)
ENRICHED[("EVPNS-REQ#200", "Feature interaction", 0)] = (
    "Combine best-path selection with MAC mobility — multiple PEs advertising the same MAC at different sequence numbers.",
    "Higher sequence number wins per ch.15; best-path algorithm respects mobility ordering.",
)
ENRICHED[("EVPNS-REQ#200", "Performance", 0)] = (
    "Measure best-path selection time when receiving 10k+ Type-2 routes for diverse MACs.",
    "Selection completes within documented BGP processing bounds; no excessive CPU.",
)
ENRICHED[("EVPNS-REQ#200", "3rd Party Interoperability", 0)] = (
    "Receive Type-2 routes from a 3rd-party PE; verify best-path applies the same algorithm as ch.7.13.",
    "Selection deterministic and matches RFC reference implementation; no oscillation.",
)
ENRICHED[("EVPNS-REQ#200", "Tech-support", 0)] = (
    "Collect tech-support during a best-path-selection-heavy scenario.",
    "Archive contains BGP table snapshots showing all candidate paths and the selected best, with reason codes.",
)


# ─── EVPNS-REQ#210 Forwarding Unicast Packets (RFC7432bis ch.13) ──────────
ENRICHED[("EVPNS-REQ#210", "Basic Functionality", 0)] = (
    "Send unicast frames between two PEs via EVPN; verify forwarding follows RFC7432bis ch.13 (MPLS encap with LT1 label, lookup based on destination MAC).",
    "Frames encapsulated with LT1 MPLS label per the received Type-2 route; decapsulated correctly at egress; per spec MUST: 'Forwarding Unicast packets must be supported.'",
)
ENRICHED[("EVPNS-REQ#210", "Basic Functionality", 1)] = (
    "Verify default unicast forwarding behavior with no special tuning.",
    "Unicast flows operate per RFC defaults.",
)
ENRICHED[("EVPNS-REQ#210", "Packet validation", 0)] = (
    "Send valid unicast frames at varying packet sizes (64-1518B); verify all forward correctly.",
    "All frames forwarded; checksums correct post-encap/decap; no MTU issues until MPLS overhead exceeds underlying transport.",
)
ENRICHED[("EVPNS-REQ#210", "Malformed/unsupported packets", 0)] = (
    "Send unicast frames to MACs not in the EVPN MAC table.",
    "Frames are flooded as unknown unicast (BUM behavior) or dropped per configured policy; behavior matches RFC.",
)
ENRICHED[("EVPNS-REQ#210", "Feature interaction", 0)] = (
    "Combine unicast forwarding with multi-homing aliasing.",
    "Unicast flows distributed across multi-homed PEs per aliasing path; per-flow stickiness maintained.",
)
ENRICHED[("EVPNS-REQ#210", "Performance", 0)] = (
    "Push line-rate unicast traffic between EVPN endpoints; measure throughput and latency.",
    "Throughput at line rate; latency within hardware datasheet bounds; no frame loss.",
)
ENRICHED[("EVPNS-REQ#210", "Tech-support", 0)] = (
    "Collect tech-support after sustained unicast traffic.",
    "Archive contains forwarding-table dumps, MPLS label assignments, per-flow counters.",
)


# ─── EVPNS-REQ#220 Multicast and Broadcast (Ingress Replication only) ─────
# §1.3.1: Only Ingress Replication is supported, P2MP LSPs are NOT supported
ENRICHED[("EVPNS-REQ#220", "CLI configuration", 0)] = (
    "Configure ingress-replication mode for BUM forwarding on the EVPN instance (per §1.3.1 limitation: only ingress-replication, NOT P2MP).",
    "EVPN advertises Type-3 (Inclusive Multicast Ethernet Tag) routes with PMSI Tunnel Attribute set to ingress-replication; per spec P2MP LSPs are NOT supported.",
)
ENRICHED[("EVPNS-REQ#220", "CLI configuration", 1)] = (
    "Edit the EVPN to add another remote PE; verify the ingress-replication list updates.",
    "New PE added to the BUM replication list; Type-3 routes updated; replication count grows.",
)
ENRICHED[("EVPNS-REQ#220", "CLI configuration", 2)] = (
    "Delete the EVPN; verify Type-3 routes withdrawn.",
    "All Type-3 advertisements withdrawn; remote PEs remove the EVI from their replication lists.",
)
ENRICHED[("EVPNS-REQ#220", "CLI configuration", 3)] = (
    "Apply factory-default; replay the EVPN; verify Type-3 routes re-advertise with PMSI ingress-replication.",
    "Configuration restores; Type-3 routes match pre-default snapshot.",
)
ENRICHED[("EVPNS-REQ#220", "CLI configuration", 4)] = (
    "Make a multicast-related config change, then rollback before commit.",
    "Configuration reverts; no Type-3 route flap.",
)
ENRICHED[("EVPNS-REQ#220", "Basic Functionality", 0)] = (
    "Send broadcast frames into one PE of an EVPN with 3 remote PEs configured; verify ingress-replication delivers a copy to each.",
    "Broadcast frame replicated 3 times at the ingress PE; each remote PE receives one copy via its specific MPLS label; per spec ingress-replication mode active.",
)
ENRICHED[("EVPNS-REQ#220", "Basic Functionality", 1)] = (
    "Verify default behavior of multicast/broadcast with a single peer EVPN PE.",
    "Single replication; one copy sent; remote PE forwards normally.",
)
ENRICHED[("EVPNS-REQ#220", "Packet validation", 0)] = (
    "Send IGMP membership reports and IPv6 ND multicast at the EVPN access; verify they're handled per ingress-replication.",
    "Multicast frames replicated to all peers via ingress-replication; CE-side IGMP snooping (if any) operates normally.",
)
ENRICHED[("EVPNS-REQ#220", "Malformed/unsupported packets", 0)] = (
    "Receive a Type-3 route advertising P2MP tunnel type (NOT supported per §1.3.1).",
    "Route is rejected or treated per documented behavior; no attempt to install a P2MP LSP; alarm/log fires.",
)
ENRICHED[("EVPNS-REQ#220", "Feature interaction", 0)] = (
    "Combine ingress-replication with multi-homing split-horizon (REQ#180).",
    "BUM replication respects split-horizon: same-ESI PE drops; remote PEs receive normally.",
)
ENRICHED[("EVPNS-REQ#220", "Performance", 0)] = (
    "Push BUM traffic at high rate; measure replication overhead.",
    "Per-frame replication adds linear cost (N copies); ingress PE CPU/throughput within bounds.",
)
ENRICHED[("EVPNS-REQ#220", "3rd Party Interoperability", 0)] = (
    "Interop ingress-replication with a 3rd-party PE.",
    "Type-3 route exchange compatible; both vendors replicate using the same per-peer label semantics.",
)
ENRICHED[("EVPNS-REQ#220", "Upgrade", 0)] = (
    "With an active multicast-heavy EVPN, run onie-install upgrade.",
    "Configuration restores; Type-3 routes re-advertise after BGP re-establishes.",
)
ENRICHED[("EVPNS-REQ#220", "Management", 0)] = (
    "Configure ingress-replication via NETCONF/YANG.",
    "NETCONF commit produces equivalent CLI; behavior identical.",
)
ENRICHED[("EVPNS-REQ#220", "Tech-support", 0)] = (
    "Collect tech-support after BUM-heavy scenarios.",
    "Archive contains Type-3 route dumps, per-peer replication counters, multicast frame logs.",
)


# ─── EVPNS-REQ#230 PMSI Tunnel attribute ──────────────────────────────────
# Per spec only Ingress Replication; PMSI carries the type and per-peer label
ENRICHED[("EVPNS-REQ#230", "CLI configuration", 0)] = (
    "Configure an EVPN advertising Type-3 routes; verify the PMSI Tunnel Attribute encodes Tunnel Type=ingress-replication, Tunnel ID, and the MPLS Label per RFC7432bis ch.16.",
    "PMSI attribute structure correct in `show bgp l2vpn evpn route-type 3 detail`; tunnel type=6 (ingress-replication); per-peer MPLS label assigned.",
)
ENRICHED[("EVPNS-REQ#230", "CLI configuration", 1)] = (
    "Edit the EVPN's RT/RD; verify Type-3 routes are re-advertised with updated PMSI.",
    "Routes withdrawn under old RT/RD and re-advertised; PMSI attribute preserved correctly.",
)
ENRICHED[("EVPNS-REQ#230", "CLI configuration", 2)] = (
    "Delete the EVPN; verify Type-3 routes withdrawn including PMSI attribute.",
    "All Type-3 routes for the EVI withdrawn; remote PEs remove the PMSI tunnel.",
)
ENRICHED[("EVPNS-REQ#230", "CLI configuration", 3)] = (
    "Apply factory-default; replay the EVPN; verify PMSI tunnel attribute re-emerges identically.",
    "Type-3 routes carry the same PMSI structure post-replay.",
)
ENRICHED[("EVPNS-REQ#230", "CLI configuration", 4)] = (
    "Modify a PMSI-influencing parameter, then rollback before commit.",
    "PMSI reverts; no Type-3 route flap.",
)
ENRICHED[("EVPNS-REQ#230", "Basic Functionality", 0)] = (
    "Verify ingress PE allocates a per-peer MPLS label and publishes it in the PMSI Tunnel attribute on the Type-3 route.",
    "Per-peer label visible in the PMSI; remote PEs use this label when sending BUM traffic toward this ingress PE.",
)
ENRICHED[("EVPNS-REQ#230", "Basic Functionality", 1)] = (
    "Verify PMSI default behavior with a freshly created EVPN.",
    "PMSI Tunnel Attribute is generated automatically; no manual configuration needed.",
)
ENRICHED[("EVPNS-REQ#230", "Packet validation", 0)] = (
    "Capture BGP UPDATEs carrying Type-3 routes; verify PMSI Tunnel Attribute parses correctly per RFC6514.",
    "Wireshark/log shows correct attribute encoding; tunnel type, tunnel ID, label all present and well-formed.",
)
ENRICHED[("EVPNS-REQ#230", "Malformed/unsupported packets", 0)] = (
    "Receive a Type-3 route with malformed PMSI Tunnel Attribute (e.g. wrong length, unknown tunnel type).",
    "Malformed PMSI handled per RFC: route may be ignored or treated as 'no tunnel'; no NOTIFICATION sent for non-fatal errors.",
)
ENRICHED[("EVPNS-REQ#230", "Feature interaction", 0)] = (
    "Combine PMSI advertisement with MAC mass-withdrawal (REQ#170 fast-convergence).",
    "PMSI updates correctly when paths change; per-peer label re-allocated if needed; no stale labels left.",
)
ENRICHED[("EVPNS-REQ#230", "Performance", 0)] = (
    "Measure PMSI allocation time as new EVIs are added at scale.",
    "Allocation linear in EVI count; within documented bounds; no MPLS label exhaustion at typical scale.",
)
ENRICHED[("EVPNS-REQ#230", "Scale", 0)] = (
    "Scale to documented number of EVIs each requiring per-peer PMSI labels.",
    "All PMSI labels allocated successfully; no collisions; MPLS label table within bounds.",
)
ENRICHED[("EVPNS-REQ#230", "3rd Party Interoperability", 0)] = (
    "Interop PMSI Tunnel Attribute with a 3rd-party PE per RFC6514.",
    "PMSI parsed correctly across vendors; ingress-replication labels exchanged.",
)
ENRICHED[("EVPNS-REQ#230", "Upgrade", 0)] = (
    "With multiple EVIs and PMSI advertisements, run onie-install upgrade.",
    "Configuration restores; PMSI labels may be re-allocated post-reboot but tunnel topology re-converges.",
)
ENRICHED[("EVPNS-REQ#230", "Management", 0)] = (
    "Query PMSI Tunnel Attribute via NETCONF.",
    "NETCONF returns the same PMSI data as CLI; structure parses correctly.",
)
ENRICHED[("EVPNS-REQ#230", "Tech-support", 0)] = (
    "Collect tech-support after PMSI-heavy scenarios.",
    "Archive contains PMSI label allocations, Type-3 route dumps, per-peer label-to-EVI mappings.",
)


# ─── EVPNS-REQ#240 L2-Attr Extended Community (RFC8214) ───────────────────
ENRICHED[("EVPNS-REQ#240", "Basic Functionality", 0)] = (
    "Verify the EVPN advertises the L2-Attr Extended Community on Type-2 routes per RFC8214 (carries MTU, control word flag, etc.).",
    "L2-Attr Extended Community present in advertised Type-2 routes; fields populated correctly; per spec MUST: 'L2-Attr Extended Community.'",
)
ENRICHED[("EVPNS-REQ#240", "Basic Functionality", 1)] = (
    "Verify default L2-Attr behavior — community attached automatically to Type-2 routes.",
    "Default values per RFC8214 (MTU=0 means no MTU info); receiver tolerates absence.",
)
ENRICHED[("EVPNS-REQ#240", "Packet validation", 0)] = (
    "Capture BGP UPDATEs and decode the L2-Attr Extended Community; verify field semantics.",
    "8-byte community with type/sub-type matching RFC8214; flags and MTU fields present.",
)
ENRICHED[("EVPNS-REQ#240", "Malformed/unsupported packets", 0)] = (
    "Receive a Type-2 with a malformed L2-Attr extended community (wrong length or sub-type).",
    "Malformed community treated per RFC; route may be accepted with the community ignored, or rejected; no NOTIFICATION.",
)
ENRICHED[("EVPNS-REQ#240", "Feature interaction", 0)] = (
    "Combine L2-Attr with MAC Mobility EC on the same Type-2 route.",
    "Both communities present without conflict; consumer parses each independently.",
)
ENRICHED[("EVPNS-REQ#240", "3rd Party Interoperability", 0)] = (
    "Interop L2-Attr with a 3rd-party PE per RFC8214.",
    "Community exchanged; values match expected RFC encoding; no parser errors.",
)
ENRICHED[("EVPNS-REQ#240", "Tech-support", 0)] = (
    "Collect tech-support after L2-Attr exchange.",
    "Archive contains BGP route dumps with L2-Attr decoded.",
)


# ─── EVPNS-REQ#250 ES-Import Route Target ─────────────────────────────────
ENRICHED[("EVPNS-REQ#250", "CLI configuration", 0)] = (
    "Configure ES-Import Route Target on a multi-homed Ethernet Segment; verify it filters which PEs receive the ES route (4) per RFC7432bis.",
    "Only PEs configured to import the ES-Import RT install the ES route (4); per spec ES-Import RT scopes ES route distribution.",
)
ENRICHED[("EVPNS-REQ#250", "CLI configuration", 1)] = (
    "Edit the ES-Import RT value; commit.",
    "Old RT removed, new RT applied; ES route re-advertised; previously importing PEs may stop importing.",
)
ENRICHED[("EVPNS-REQ#250", "CLI configuration", 2)] = (
    "Delete the ES-Import RT configuration; commit.",
    "ES route advertised without ES-Import RT (per spec default); all PEs see it.",
)
ENRICHED[("EVPNS-REQ#250", "CLI configuration", 3)] = (
    "Apply factory-default; replay ES-Import RT configuration.",
    "RT restored identically; ES route re-advertises with the configured RT.",
)
ENRICHED[("EVPNS-REQ#250", "CLI configuration", 4)] = (
    "Modify ES-Import RT, then rollback before commit.",
    "Configuration reverts; no transient ES route changes.",
)
ENRICHED[("EVPNS-REQ#250", "Basic Functionality", 0)] = (
    "Verify ES-Import RT filters ES route (4) advertisement to relevant peer PEs only.",
    "Non-importing PEs ignore the ES route; importing PEs install it; multi-homing procedures restricted to importing PEs.",
)
ENRICHED[("EVPNS-REQ#250", "Basic Functionality", 1)] = (
    "Verify default behavior with no ES-Import RT — ES route reaches all PEs.",
    "All EVPN PEs see the ES route; multi-homing-procedure visibility is universal.",
)
ENRICHED[("EVPNS-REQ#250", "Packet validation", 0)] = (
    "Capture BGP UPDATEs; verify ES-Import RT is encoded as a standard 8-byte RT extended community.",
    "RT correctly encoded; type/value match configuration; received PEs filter correctly.",
)
ENRICHED[("EVPNS-REQ#250", "Malformed/unsupported packets", 0)] = (
    "Receive an ES route (4) with a malformed ES-Import RT.",
    "Malformed RT treated per RFC; may cause the route to be ignored; no session reset.",
)
ENRICHED[("EVPNS-REQ#250", "Feature interaction", 0)] = (
    "Combine ES-Import RT with multiple multi-homed segments having different RTs.",
    "Each segment scoped independently; PEs see only the ES routes they import.",
)
ENRICHED[("EVPNS-REQ#250", "3rd Party Interoperability", 0)] = (
    "Interop ES-Import RT with a 3rd-party PE.",
    "Filter behavior identical across vendors; per spec ES-Import RT semantics standardized.",
)
ENRICHED[("EVPNS-REQ#250", "Performance", 0)] = (
    "Measure BGP processing under many ES routes filtered by ES-Import RT.",
    "Filtering happens at import time; CPU overhead linear in advertised routes; scalable.",
)
ENRICHED[("EVPNS-REQ#250", "Upgrade", 0)] = (
    "With ES-Import RT configured, run onie-install upgrade.",
    "Configuration restores; ES routes re-advertise with the same RT; filtering behavior consistent post-upgrade.",
)
ENRICHED[("EVPNS-REQ#250", "Management", 0)] = (
    "Configure ES-Import RT via NETCONF.",
    "NETCONF commit succeeds; equivalent CLI generated; behavior identical.",
)
ENRICHED[("EVPNS-REQ#250", "Tech-support", 0)] = (
    "Collect tech-support after exercising ES-Import RT scenarios.",
    "Archive includes RT configuration, ES route advertisement/import logs, BGP filter state.",
)


# ─── EVPNS-REQ#260 Ethernet A-D Per Ethernet Segment Route (1) ────────────
# A-D Per ES route — used for mass MAC withdrawal and ESI signaling
ENRICHED[("EVPNS-REQ#260", "CLI configuration", 0)] = (
    "Configure a multi-homed ESI on agg-eth 1; observe the EthA-D Per ES Route (RT-1) is advertised by BGP per RFC7432bis ch.7.1.",
    "EthA-D Per ES route appears in `show bgp l2vpn evpn route-type 1`; ESI matches the configured ESI; per spec MUST: 'Ethernet A-D Per Ethernet Segment Route (1).'",
)
ENRICHED[("EVPNS-REQ#260", "CLI configuration", 1)] = (
    "Edit ESI value; verify EthA-D Per ES route is withdrawn under the old ESI and re-advertised under the new ESI.",
    "Old route withdrawn; new route advertised; remote PEs update mass-withdrawal correlation.",
)
ENRICHED[("EVPNS-REQ#260", "CLI configuration", 2)] = (
    "Delete the ESI; verify EthA-D Per ES route withdrawn.",
    "Route withdrawn from BGP; remote PEs purge MACs reachable via this ESI per fast-convergence (REQ#170).",
)
ENRICHED[("EVPNS-REQ#260", "CLI configuration", 3)] = (
    "Apply factory-default; replay multi-homed ESI; verify EthA-D Per ES re-advertises identically.",
    "Route restored under same ESI; PE attribute consistent post-replay.",
)
ENRICHED[("EVPNS-REQ#260", "CLI configuration", 4)] = (
    "Modify ESI, then rollback before commit.",
    "Route unchanged; no transient flap.",
)
ENRICHED[("EVPNS-REQ#260", "Basic Functionality", 0)] = (
    "Verify EthA-D Per ES route advertised by every multi-homed PE on the segment with consistent ESI value.",
    "All PEs of the ESI advertise the same RT-1 ESI; per RFC the route enables mass MAC withdrawal.",
)
ENRICHED[("EVPNS-REQ#260", "Basic Functionality", 1)] = (
    "Verify single-homed ES advertises EthA-D Per ES route as single-active per §2.7.",
    "RT-1 advertised; single-active flag set; per spec MUST: single-homed ES advertises this route as single-active.",
)
ENRICHED[("EVPNS-REQ#260", "Robustness", 0)] = (
    "Reset a multi-homed PE; verify its EthA-D Per ES route is withdrawn promptly enabling MAC mass-withdrawal.",
    "Route withdrawn; remote PEs purge MACs from this PE's view; convergence within fast-convergence bounds.",
)
ENRICHED[("EVPNS-REQ#260", "Robustness", 1)] = (
    "Power-cycle a multi-homed PE; verify route lifecycle.",
    "Route withdrawn at power-down; on power-up after BGP re-establishes, route re-advertised.",
)
ENRICHED[("EVPNS-REQ#260", "Robustness", 2)] = (
    "Flap the LAG access interface causing ESI member change.",
    "Per LACP convergence ESI may stay or change; route updated accordingly.",
)
ENRICHED[("EVPNS-REQ#260", "HA", 0)] = (
    "Kill BGP on a multi-homed PE.",
    "Route withdrawn for the duration; restored on BGP re-establishment.",
)
ENRICHED[("EVPNS-REQ#260", "Long run", 0)] = (
    "Run a multi-homed deployment for ≥ 24 hours; periodically force PE failures and recoveries.",
    "EthA-D Per ES route lifecycle stable; mass-withdrawal triggers correctly each event.",
)
ENRICHED[("EVPNS-REQ#260", "Feature interaction", 0)] = (
    "Combine EthA-D Per ES with DF Election (REQ#120).",
    "Both routes coexist; DF election uses ES Route (4); mass-withdrawal uses A-D Per ES (1); both update on topology change.",
)
ENRICHED[("EVPNS-REQ#260", "3rd Party Interoperability", 0)] = (
    "Interop A-D Per ES route with a 3rd-party multi-homed PE per RFC7432bis ch.7.1.",
    "ESI agreement across vendors; route exchange works; mass-withdrawal triggers correctly.",
)
ENRICHED[("EVPNS-REQ#260", "Packet validation", 0)] = (
    "Capture BGP UPDATEs carrying RT-1; verify encoding (route key = ESI, NLRI = ESI + ETID).",
    "Encoding matches RFC7432bis ch.7.1; receivers parse correctly.",
)
ENRICHED[("EVPNS-REQ#260", "Malformed/unsupported packets", 0)] = (
    "Receive a malformed RT-1 (truncated, bad ESI length).",
    "Malformed route ignored or treated per RFC; BGP session unaffected.",
)
ENRICHED[("EVPNS-REQ#260", "Performance", 0)] = (
    "Measure mass-withdrawal latency (PE failure → remote MAC purge).",
    "Latency within fast-convergence bounds; BGP UPDATE propagation timely.",
)
ENRICHED[("EVPNS-REQ#260", "Scale", 0)] = (
    "Configure many ESIs (e.g. 100+) on a PE; verify all advertise RT-1.",
    "All routes advertised; no BGP processing overload.",
)
ENRICHED[("EVPNS-REQ#260", "Alarms/Logs/Syslog", 0)] = (
    "Trigger an ESI mismatch (REQ#390 condition); verify alarm + log entry refer to the EthA-D Per ES route.",
    "Alarm includes ESI value, source IP, mismatch detail; log timestamps correlate.",
)
ENRICHED[("EVPNS-REQ#260", "PM", 0)] = (
    "Verify PM counters for RT-1 advertisements/withdrawals.",
    "Counters increment on each event; clear works; values persist across reload.",
)
ENRICHED[("EVPNS-REQ#260", "Upgrade", 0)] = (
    "With multiple ESIs advertising RT-1, run onie-install upgrade.",
    "Configuration restores; routes re-advertise after BGP re-establishes.",
)
ENRICHED[("EVPNS-REQ#260", "Management", 0)] = (
    "Configure multi-homed ESI via NETCONF; verify RT-1 emits.",
    "NETCONF commit succeeds; route appears identically as via CLI.",
)
ENRICHED[("EVPNS-REQ#260", "Tech-support", 0)] = (
    "Collect tech-support after multi-homing topology changes.",
    "Archive contains RT-1 advertisement history, ESI configurations, PM counters.",
)


# ─── EVPNS-REQ#270 Ethernet A-D Per EVPN Instance Route (1) ───────────────
ENRICHED[("EVPNS-REQ#270", "CLI configuration", 0)] = (
    "Configure an EVPN instance with a multi-homed ESI; verify EthA-D Per EVI route (RT-1, ESI+ETID-specific) is advertised per RFC7432bis ch.7.1.",
    "Route appears in `show bgp l2vpn evpn route-type 1`; ESI/ETID match the EVI configuration; route enables aliasing path (REQ#140).",
)
ENRICHED[("EVPNS-REQ#270", "CLI configuration", 1)] = (
    "Edit the ETID (vlan-id) of the EVPN instance; verify EthA-D Per EVI route updates.",
    "Route withdrawn under old ETID and re-advertised under new ETID; remote PEs update aliasing.",
)
ENRICHED[("EVPNS-REQ#270", "CLI configuration", 2)] = (
    "Delete the EVPN instance; verify route withdrawn.",
    "All EthA-D Per EVI routes for this EVI withdrawn; aliasing path narrowed.",
)
ENRICHED[("EVPNS-REQ#270", "CLI configuration", 3)] = (
    "Apply factory-default; replay multi-homed EVI; verify route re-advertises identically.",
    "Route restored with same ESI/ETID; aliasing path resumes.",
)
ENRICHED[("EVPNS-REQ#270", "CLI configuration", 4)] = (
    "Make a configuration change affecting RT-1 Per EVI, then rollback.",
    "Route unchanged; no transient flap.",
)
ENRICHED[("EVPNS-REQ#270", "Basic Functionality", 0)] = (
    "On the elected DF PE for a multi-homed segment, observe RT-1 Per EVI route used for aliasing path.",
    "RT-1 Per EVI present; remote PEs use it to load-balance unicast flows; per RFC7432bis aliasing operates correctly.",
)
ENRICHED[("EVPNS-REQ#270", "Basic Functionality", 1)] = (
    "Verify default behavior of RT-1 Per EVI with no special tuning.",
    "Auto-advertised on EVI configuration; correct ESI/ETID populated.",
)
ENRICHED[("EVPNS-REQ#270", "Robustness", 0)] = (
    "Reset a multi-homed PE; verify RT-1 Per EVI route lifecycle.",
    "Withdrawn at PE down; re-advertised on recovery; aliasing path tracks correctly.",
)
ENRICHED[("EVPNS-REQ#270", "Robustness", 1)] = (
    "Power-cycle a multi-homed PE.",
    "Route lifecycle correct; no stale routes left after recovery.",
)
ENRICHED[("EVPNS-REQ#270", "Robustness", 2)] = (
    "Flap LAG member; verify route remains stable as long as ESI is reachable.",
    "Route unchanged through brief LACP flaps; only withdrawn when ESI completely unreachable.",
)
ENRICHED[("EVPNS-REQ#270", "HA", 0)] = (
    "Kill BGP on a multi-homed PE.",
    "RT-1 Per EVI withdrawn during outage; re-advertised on recovery.",
)
ENRICHED[("EVPNS-REQ#270", "Long run", 0)] = (
    "Run multi-homed EVI under steady state for ≥ 24 hours.",
    "Route stable; no spurious re-advertisements.",
)
ENRICHED[("EVPNS-REQ#270", "Feature interaction", 0)] = (
    "Combine RT-1 Per EVI with all-active load balancing (REQ#150).",
    "Both work together; aliasing path reflects ESI's load-balance mode.",
)
ENRICHED[("EVPNS-REQ#270", "3rd Party Interoperability", 0)] = (
    "Interop RT-1 Per EVI with a 3rd-party PE.",
    "Aliasing operates correctly across vendors per RFC7432bis ch.8.4.",
)
ENRICHED[("EVPNS-REQ#270", "Packet validation", 0)] = (
    "Capture RT-1 Per EVI BGP UPDATEs; verify NLRI encoding.",
    "Encoding matches ch.7.1 expected fields; correct ESI, ETID, MPLS label.",
)
ENRICHED[("EVPNS-REQ#270", "Malformed/unsupported packets", 0)] = (
    "Receive a malformed RT-1 Per EVI (e.g. invalid ETID).",
    "Route ignored; session stays up.",
)
ENRICHED[("EVPNS-REQ#270", "Performance", 0)] = (
    "Measure aliasing path establishment latency under topology change.",
    "Latency within fast-convergence bounds.",
)
ENRICHED[("EVPNS-REQ#270", "Scale", 0)] = (
    "Configure many EVIs each with multi-homed ESI; verify all RT-1 Per EVI routes advertised.",
    "Routes scale linearly; no BGP processing overload.",
)
ENRICHED[("EVPNS-REQ#270", "Upgrade", 0)] = (
    "Run onie-install with active multi-homed EVIs; verify route restoration.",
    "All RT-1 Per EVI routes restored after upgrade.",
)
ENRICHED[("EVPNS-REQ#270", "Management", 0)] = (
    "Query RT-1 Per EVI advertisement state via NETCONF.",
    "Operational data exposes route attributes consistent with `show bgp l2vpn evpn route-type 1`.",
)
ENRICHED[("EVPNS-REQ#270", "Tech-support", 0)] = (
    "Collect tech-support after multi-homed EVI scenarios.",
    "Archive contains RT-1 Per EVI history, aliasing path computations.",
)


# ─── EVPNS-REQ#280 MAC/IP Address Advertisement (additional) ───────────────
ENRICHED[("EVPNS-REQ#280", "Alarms/Logs/Syslog", 0)] = (
    "Trigger a Type-2 advertisement burst that exceeds documented thresholds.",
    "Threshold-crossing alarm fires; syslog records advertisement rate; alarm clears below threshold.",
)
ENRICHED[("EVPNS-REQ#280", "PM", 0)] = (
    "Verify PM counters for Type-2 advertisements/withdrawals.",
    "Counters increment per route event; clear works; values persist.",
)


# ─── EVPNS-REQ#290 Inclusive Multicast Ethernet Tag Route (3) ─────────────
ENRICHED[("EVPNS-REQ#290", "Basic Functionality", 0)] = (
    "Verify Type-3 (Inclusive Multicast Ethernet Tag) route is advertised per EVI per RFC7432bis ch.7.4 with PMSI tunnel attribute.",
    "Route present in `show bgp l2vpn evpn route-type 3`; ETID, originating router IP, PMSI all present; per spec MUST: 'Inclusive Multicast Ethernet Tag Route (3).'",
)
ENRICHED[("EVPNS-REQ#290", "Basic Functionality", 1)] = (
    "Verify default Type-3 advertisement behavior on EVI configuration.",
    "Type-3 advertised automatically; PMSI tunnel attribute = ingress-replication per spec limitation.",
)
ENRICHED[("EVPNS-REQ#290", "Packet validation", 0)] = (
    "Capture BGP UPDATEs carrying Type-3; verify NLRI encoding (RD, ETID, IP Address Length, Originating Router IP).",
    "All fields parse correctly per RFC; PMSI Tunnel Attribute attached.",
)
ENRICHED[("EVPNS-REQ#290", "Malformed/unsupported packets", 0)] = (
    "Receive a malformed Type-3 (e.g. truncated originating IP).",
    "Route ignored; session unaffected; logged.",
)
ENRICHED[("EVPNS-REQ#290", "Feature interaction", 0)] = (
    "Combine Type-3 with multi-homing split horizon (REQ#180).",
    "BUM forwarded to all PEs in Type-3 list; same-ESI peer applies split horizon and drops.",
)
ENRICHED[("EVPNS-REQ#290", "3rd Party Interoperability", 0)] = (
    "Receive Type-3 routes from a 3rd-party PE.",
    "Routes installed; ingress-replication tunnel established; BUM forwarding works.",
)
ENRICHED[("EVPNS-REQ#290", "Performance", 0)] = (
    "Measure BUM forwarding latency through Type-3-derived replication list.",
    "Latency within hardware bounds; replication count linear with peer count.",
)
ENRICHED[("EVPNS-REQ#290", "Tech-support", 0)] = (
    "Collect tech-support after BUM-heavy traffic.",
    "Archive contains Type-3 routes, replication lists, BUM counters.",
)


# ─── EVPNS-REQ#300 Ethernet Segment Route (4) ─────────────────────────────
ENRICHED[("EVPNS-REQ#300", "CLI configuration", 0)] = (
    "Configure a multi-homed Ethernet Segment; observe Type-4 (Ethernet Segment Route) is advertised per RFC7432bis ch.7.5 with DF Election Extended Community.",
    "Type-4 visible in `show bgp l2vpn evpn route-type 4`; ESI + Originating Router IP populated; DF Election EC carries the configured algorithm.",
)
ENRICHED[("EVPNS-REQ#300", "CLI configuration", 1)] = (
    "Edit DF election algorithm; verify Type-4 re-advertised with updated DF Election EC.",
    "Old route withdrawn; new route advertised; peer PEs update DF election state.",
)
ENRICHED[("EVPNS-REQ#300", "CLI configuration", 2)] = (
    "Delete the multi-homed ES; verify Type-4 withdrawn.",
    "Route removed; remote PEs withdraw the PE from DF election participation for this ESI.",
)
ENRICHED[("EVPNS-REQ#300", "CLI configuration", 3)] = (
    "Apply factory-default; replay multi-homed ES; verify Type-4 emits identically.",
    "Route restored; DF Election EC matches.",
)
ENRICHED[("EVPNS-REQ#300", "CLI configuration", 4)] = (
    "Modify ES configuration, then rollback before commit.",
    "Route unchanged; no transient flap.",
)
ENRICHED[("EVPNS-REQ#300", "Basic Functionality", 0)] = (
    "Verify Type-4 used for DF election (REQ#120) and ES auto-discovery; ES-Import RT (REQ#250) scopes distribution.",
    "Type-4 carries algorithm signaling per §2.7.2.2; DF election uses it correctly.",
)
ENRICHED[("EVPNS-REQ#300", "Basic Functionality", 1)] = (
    "Verify default Type-4 behavior with default DF algorithm.",
    "Type-4 emitted with DF Alg = Default; election converges per RFC7432bis ch.8.5.",
)
ENRICHED[("EVPNS-REQ#300", "Robustness", 0)] = (
    "Reset a multi-homed PE; verify Type-4 lifecycle.",
    "Withdrawn at down, re-advertised at up; DF re-election triggers.",
)
ENRICHED[("EVPNS-REQ#300", "Robustness", 1)] = (
    "Power-cycle a multi-homed PE.",
    "Type-4 lifecycle correct; DF election re-runs.",
)
ENRICHED[("EVPNS-REQ#300", "Robustness", 2)] = (
    "Flap LAG member.",
    "Type-4 stable as long as ESI partly reachable.",
)
ENRICHED[("EVPNS-REQ#300", "HA", 0)] = (
    "Kill BGP on a multi-homed PE.",
    "Type-4 withdrawn during outage; re-advertised on recovery.",
)
ENRICHED[("EVPNS-REQ#300", "Long run", 0)] = (
    "Run multi-homed deployment with periodic DF preference changes for ≥ 24 hours.",
    "Type-4 advertisement state stable; no stale entries.",
)
ENRICHED[("EVPNS-REQ#300", "Feature interaction", 0)] = (
    "Combine Type-4 with DF election negotiation across mixed-algorithm peers.",
    "Falls back to Default per §2.7.2.2 if any peer advertises a different DF Alg.",
)
ENRICHED[("EVPNS-REQ#300", "3rd Party Interoperability", 0)] = (
    "Interop Type-4 with a 3rd-party multi-homed PE.",
    "DF Election EC negotiated correctly across vendors; election converges.",
)
ENRICHED[("EVPNS-REQ#300", "Packet validation", 0)] = (
    "Capture Type-4 BGP UPDATEs; verify encoding (ESI + Originating Router IP).",
    "Encoding matches RFC; DF Election EC parses.",
)
ENRICHED[("EVPNS-REQ#300", "Malformed/unsupported packets", 0)] = (
    "Receive a malformed Type-4 (e.g. invalid DF Alg value).",
    "Per RFC, fall back to Default algorithm; no NOTIFICATION.",
)
ENRICHED[("EVPNS-REQ#300", "Performance", 0)] = (
    "Measure DF election convergence using Type-4 advertisement timing.",
    "Within fast-convergence bounds.",
)
ENRICHED[("EVPNS-REQ#300", "Upgrade", 0)] = (
    "With multi-homed ESIs, run onie-install upgrade.",
    "Type-4 routes re-advertise; DF election re-runs.",
)
ENRICHED[("EVPNS-REQ#300", "Management", 0)] = (
    "Configure ES + DF algorithm via NETCONF; verify Type-4 emission.",
    "Equivalent CLI generated; route attributes match.",
)
ENRICHED[("EVPNS-REQ#300", "Tech-support", 0)] = (
    "Collect tech-support after DF election scenarios.",
    "Archive contains Type-4 dumps, DF Alg per ES, election history.",
)


# ─── EVPNS-REQ#310 LT1 (MPLS Label Type 1, EVPN Service Label) ────────────
ENRICHED[("EVPNS-REQ#310", "Basic Functionality", 0)] = (
    "Verify LT1 MPLS label is allocated per EVI and signaled in Type-2 routes per §4.1.1.",
    "LT1 label visible in advertised Type-2; per-EVI scope; per spec MUST: 'LT1.'",
)
ENRICHED[("EVPNS-REQ#310", "Basic Functionality", 1)] = (
    "Verify default LT1 behavior — automatic per-EVI assignment.",
    "Label allocated on EVI creation; reused if EVI deleted then re-created.",
)
ENRICHED[("EVPNS-REQ#310", "Packet validation", 0)] = (
    "Send unicast frames; capture egress; verify LT1 MPLS label on the wire.",
    "Frame carries LT1 outer/inner label per EVPN encapsulation; egress PE pops correctly.",
)
ENRICHED[("EVPNS-REQ#310", "Malformed/unsupported packets", 0)] = (
    "Receive a frame with a wrong LT1 label.",
    "Frame dropped at MPLS label lookup; counter increments; no MAC learning.",
)
ENRICHED[("EVPNS-REQ#310", "Feature interaction", 0)] = (
    "Combine LT1 with all-active load balancing.",
    "Each PE of a multi-homed pair has its own LT1 per EVI; aliasing distributes.",
)
ENRICHED[("EVPNS-REQ#310", "3rd Party Interoperability", 0)] = (
    "Interop LT1 semantics with a 3rd-party PE.",
    "Label semantics agree across vendors per RFC.",
)
ENRICHED[("EVPNS-REQ#310", "Performance", 0)] = (
    "Push line-rate traffic through LT1-labeled paths.",
    "Throughput at line rate; MPLS lookup performance within bounds.",
)
ENRICHED[("EVPNS-REQ#310", "Tech-support", 0)] = (
    "Collect tech-support showing LT1 allocations.",
    "Archive contains MPLS label table per EVI; LT1 mappings consistent with BGP.",
)


# ─── EVPNS-REQ#320 LT2 (Split Horizon Label) ──────────────────────────────
# §4.1.2: ESI-scoped, used for Split Horizon (REQ#180)
ENRICHED[("EVPNS-REQ#320", "CLI configuration", 0)] = (
    "Configure a multi-homed ESI; observe LT2 (Split Horizon Label) allocated per ESI per §4.1.2.",
    "LT2 label per ESI advertised on RT-1 Per EVI route; per spec MUST: 'LT2.'",
)
ENRICHED[("EVPNS-REQ#320", "CLI configuration", 1)] = (
    "Edit ESI; verify LT2 may be re-allocated.",
    "Old LT2 freed; new LT2 advertised under new ESI.",
)
ENRICHED[("EVPNS-REQ#320", "CLI configuration", 2)] = (
    "Delete the ESI; verify LT2 freed.",
    "Label returned to the MPLS label pool; routes withdrawn.",
)
ENRICHED[("EVPNS-REQ#320", "CLI configuration", 3)] = (
    "Apply factory-default; replay ESI; verify LT2 re-allocated.",
    "Label assignment reproducible; advertised correctly.",
)
ENRICHED[("EVPNS-REQ#320", "CLI configuration", 4)] = (
    "Make an ESI change, then rollback before commit.",
    "Label unchanged.",
)
ENRICHED[("EVPNS-REQ#320", "Basic Functionality", 0)] = (
    "Verify LT2 used for Split Horizon (REQ#180) decisions on multi-homed BUM forwarding.",
    "Same-ESI peer recognizes incoming LT2 and drops the BUM frame; per spec split horizon prevents loops.",
)
ENRICHED[("EVPNS-REQ#320", "Basic Functionality", 1)] = (
    "Verify default LT2 behavior on a freshly created ESI.",
    "Allocated automatically; no manual configuration needed.",
)
ENRICHED[("EVPNS-REQ#320", "Packet validation", 0)] = (
    "Capture BUM traffic between multi-homed PEs; verify LT2 in the MPLS stack.",
    "LT2 present; same-ESI peer drops; remote PEs forward normally.",
)
ENRICHED[("EVPNS-REQ#320", "Malformed/unsupported packets", 0)] = (
    "Receive BUM with a forged LT2 belonging to a different ESI.",
    "Frame treated per LT2 rules; no incorrect drop.",
)
ENRICHED[("EVPNS-REQ#320", "Feature interaction", 0)] = (
    "Combine LT2 with multi-EVI on the same ESI.",
    "Each EVI uses the same LT2 for ESI-level split horizon.",
)
ENRICHED[("EVPNS-REQ#320", "3rd Party Interoperability", 0)] = (
    "Interop LT2 with a 3rd-party PE.",
    "Label semantics agree.",
)
ENRICHED[("EVPNS-REQ#320", "Performance", 0)] = (
    "Push BUM traffic; measure split horizon decision latency via LT2.",
    "Latency within hardware bounds.",
)
ENRICHED[("EVPNS-REQ#320", "Upgrade", 0)] = (
    "With LT2 active, run onie-install upgrade.",
    "Label re-allocated post-upgrade; routes re-advertise.",
)
ENRICHED[("EVPNS-REQ#320", "Management", 0)] = (
    "Query LT2 allocation via NETCONF.",
    "Operational data exposes LT2 per ESI.",
)
ENRICHED[("EVPNS-REQ#320", "Tech-support", 0)] = (
    "Collect tech-support showing LT2 allocations.",
    "Archive contains LT2 per ESI mappings.",
)


# ─── EVPNS-REQ#330 LT3 (BUM ingress per-PE label) ─────────────────────────
ENRICHED[("EVPNS-REQ#330", "CLI configuration", 0)] = (
    "Configure a multi-PE EVPN; verify LT3 per-PE BUM label allocated per §4.1.3.",
    "LT3 label per peer-PE; signaled in PMSI Tunnel Attribute on Type-3 routes.",
)
ENRICHED[("EVPNS-REQ#330", "CLI configuration", 1)] = (
    "Add a peer; verify LT3 allocated for the new peer.",
    "New label assigned; Type-3 to that peer reflects.",
)
ENRICHED[("EVPNS-REQ#330", "CLI configuration", 2)] = (
    "Remove a peer; verify LT3 for that peer freed.",
    "Label returned to pool; Type-3 list shrinks.",
)
ENRICHED[("EVPNS-REQ#330", "CLI configuration", 3)] = (
    "Apply factory-default; replay; verify LT3 re-allocation.",
    "Labels reproducible; Type-3 advertisements match.",
)
ENRICHED[("EVPNS-REQ#330", "CLI configuration", 4)] = (
    "Modify peer config, then rollback.",
    "Labels unchanged.",
)
ENRICHED[("EVPNS-REQ#330", "Basic Functionality", 0)] = (
    "Send BUM traffic; verify each replication uses peer-specific LT3.",
    "Per-peer label distinguishes which PE is the destination; ingress-replication scales linearly.",
)
ENRICHED[("EVPNS-REQ#330", "Basic Functionality", 1)] = (
    "Verify default LT3 allocation as new peers join.",
    "Automatic per-peer allocation; no operator action.",
)
ENRICHED[("EVPNS-REQ#330", "Robustness", 0)] = (
    "Reset a peer; verify LT3 freed and reallocated on recovery.",
    "Lifecycle correct.",
)
ENRICHED[("EVPNS-REQ#330", "Robustness", 1)] = (
    "Power-cycle a peer.",
    "Same lifecycle as reset.",
)
ENRICHED[("EVPNS-REQ#330", "Robustness", 2)] = (
    "Flap a peer's interface; verify LT3 stable.",
    "LT3 unchanged through transient flaps.",
)
ENRICHED[("EVPNS-REQ#330", "HA", 0)] = (
    "Kill BGP on a peer; verify LT3 lifecycle.",
    "Withdrawn during outage; restored on recovery.",
)
ENRICHED[("EVPNS-REQ#330", "Long run", 0)] = (
    "Run BUM-heavy traffic for ≥ 24 hours with periodic peer changes.",
    "Labels stable; no leaks.",
)
ENRICHED[("EVPNS-REQ#330", "Feature interaction", 0)] = (
    "Combine LT3 with split horizon (LT2 + LT3 in stack).",
    "Both labels coexist; correct decisions made.",
)
ENRICHED[("EVPNS-REQ#330", "3rd Party Interoperability", 0)] = (
    "Interop LT3 with a 3rd-party PE.",
    "Label semantics interoperate.",
)
ENRICHED[("EVPNS-REQ#330", "Packet validation", 0)] = (
    "Capture BUM frames; verify LT3 + LT2 stack.",
    "Stack matches RFC; receivers parse.",
)
ENRICHED[("EVPNS-REQ#330", "Malformed/unsupported packets", 0)] = (
    "Receive BUM with malformed LT3.",
    "Frame dropped; counter increments.",
)
ENRICHED[("EVPNS-REQ#330", "Performance", 0)] = (
    "Measure BUM replication throughput as peer count scales.",
    "Throughput per peer at line rate; aggregate scales.",
)
ENRICHED[("EVPNS-REQ#330", "Upgrade", 0)] = (
    "Run onie-install upgrade with active BUM forwarding.",
    "LT3 re-allocated post-upgrade; topology re-converges.",
)
ENRICHED[("EVPNS-REQ#330", "Management", 0)] = (
    "Query LT3 allocations via NETCONF.",
    "Operational data exposes per-peer LT3.",
)
ENRICHED[("EVPNS-REQ#330", "Tech-support", 0)] = (
    "Collect tech-support with BUM-heavy traffic.",
    "Archive contains LT3 per-peer mappings.",
)


# ─── EVPNS-REQ#340 LT4 (per-VLAN/EVI BUM label) ───────────────────────────
ENRICHED[("EVPNS-REQ#340", "CLI configuration", 0)] = (
    "Configure multi-EVI deployment; verify LT4 per-EVI BUM label allocated per §4.1.4.",
    "LT4 per EVI advertised on Type-3 routes; receivers use it to demux BUM per EVI.",
)
ENRICHED[("EVPNS-REQ#340", "CLI configuration", 1)] = (
    "Add an EVI; verify LT4 allocated.",
    "New label; new Type-3 advertised.",
)
ENRICHED[("EVPNS-REQ#340", "CLI configuration", 2)] = (
    "Remove an EVI; verify LT4 freed.",
    "Label returned to pool.",
)
ENRICHED[("EVPNS-REQ#340", "CLI configuration", 3)] = (
    "Apply factory-default; replay; verify LT4 reproducibility.",
    "Labels reassigned; routes match.",
)
ENRICHED[("EVPNS-REQ#340", "CLI configuration", 4)] = (
    "Modify EVI, then rollback.",
    "Label unchanged.",
)
ENRICHED[("EVPNS-REQ#340", "Basic Functionality", 0)] = (
    "Send BUM; verify per-EVI demux using LT4.",
    "Receiver isolates BUM per EVI by label.",
)
ENRICHED[("EVPNS-REQ#340", "Basic Functionality", 1)] = (
    "Verify default LT4 behavior on EVI creation.",
    "Auto-allocated.",
)
ENRICHED[("EVPNS-REQ#340", "Robustness", 0)] = (
    "Reset PE; verify LT4 lifecycle.",
    "Lifecycle correct.",
)
ENRICHED[("EVPNS-REQ#340", "Robustness", 1)] = (
    "Power-cycle PE.",
    "Same lifecycle.",
)
ENRICHED[("EVPNS-REQ#340", "Robustness", 2)] = (
    "Flap interface in EVI.",
    "LT4 stable through transient.",
)
ENRICHED[("EVPNS-REQ#340", "HA", 0)] = (
    "Kill BGP on PE.",
    "LT4 withdrawn during outage.",
)
ENRICHED[("EVPNS-REQ#340", "Long run", 0)] = (
    "Run multi-EVI BUM for ≥ 24 hours.",
    "Labels stable.",
)
ENRICHED[("EVPNS-REQ#340", "Feature interaction", 0)] = (
    "Combine LT4 with vlan-aware-bundle (REQ#50).",
    "Per-bundle LT4 demuxes BUM.",
)
ENRICHED[("EVPNS-REQ#340", "3rd Party Interoperability", 0)] = (
    "Interop LT4 with a 3rd-party PE.",
    "Label semantics agree.",
)
ENRICHED[("EVPNS-REQ#340", "Packet validation", 0)] = (
    "Capture BUM with LT4; verify demux at receiver.",
    "Receiver maps to correct EVI.",
)
ENRICHED[("EVPNS-REQ#340", "Malformed/unsupported packets", 0)] = (
    "Receive BUM with bad LT4.",
    "Dropped; counter increments.",
)
ENRICHED[("EVPNS-REQ#340", "Performance", 0)] = (
    "Push multi-EVI BUM at scale.",
    "Per-EVI throughput within bounds; aggregate scales.",
)
ENRICHED[("EVPNS-REQ#340", "Upgrade", 0)] = (
    "Run onie-install upgrade.",
    "LT4 re-allocated post-upgrade.",
)
ENRICHED[("EVPNS-REQ#340", "Management", 0)] = (
    "Query LT4 via NETCONF.",
    "Operational data exposes per-EVI LT4.",
)
ENRICHED[("EVPNS-REQ#340", "Tech-support", 0)] = (
    "Collect tech-support with multi-EVI BUM.",
    "Archive contains LT4 per-EVI mappings.",
)


# ─── EVPNS-REQ#350 MAC Unicast Forwarding Table (§5.1.1) ──────────────────
ENRICHED[("EVPNS-REQ#350", "CLI configuration", 0)] = (
    "Configure an EVPN with mac-limit and ageing policies; verify MAC Unicast Forwarding Table populates per §5.1.1.",
    "Table contains MAC + egress (interface or MPLS label); per spec §5.1.1 entries source from local data-plane learning + remote BGP Type-2 routes.",
)
ENRICHED[("EVPNS-REQ#350", "CLI configuration", 1)] = (
    "Edit ageing time; commit.",
    "New ageing applied; table entries adjust on next age cycle.",
)
ENRICHED[("EVPNS-REQ#350", "CLI configuration", 2)] = (
    "Delete an EVI; verify table entries removed for that EVI.",
    "All EVI-scoped entries purged.",
)
ENRICHED[("EVPNS-REQ#350", "CLI configuration", 3)] = (
    "Apply factory-default; replay; verify table re-populates.",
    "Local entries re-learn via data-plane; remote entries re-install from BGP.",
)
ENRICHED[("EVPNS-REQ#350", "CLI configuration", 4)] = (
    "Modify table-related config, then rollback.",
    "Configuration reverts; table unaffected by aborted commit.",
)
ENRICHED[("EVPNS-REQ#350", "Basic Functionality", 0)] = (
    "Send mixed local + remote traffic; verify MAC Unicast Forwarding Table reflects both sources correctly.",
    "Local MACs marked as data-plane learned; remote MACs marked as BGP-learned with correct label/next-hop.",
)
ENRICHED[("EVPNS-REQ#350", "Basic Functionality", 1)] = (
    "Verify default behavior — table builds via standard learning + BGP.",
    "Default operation per §5.1.1.",
)
ENRICHED[("EVPNS-REQ#350", "Robustness", 0)] = (
    "Reset PE; verify table rebuild.",
    "Local entries re-learn from data-plane; remote entries restore from BGP after re-establishment.",
)
ENRICHED[("EVPNS-REQ#350", "Robustness", 1)] = (
    "Power-cycle PE.",
    "Same recovery as reset.",
)
ENRICHED[("EVPNS-REQ#350", "Robustness", 2)] = (
    "Flap interface; verify entries from that interface age out.",
    "Per ageing policy; eventual removal; no incorrect entries.",
)
ENRICHED[("EVPNS-REQ#350", "HA", 0)] = (
    "Kill data-plane learning process; verify recovery.",
    "Process restarts; existing entries preserved per BGP-GR semantics; data-plane learning resumes.",
)
ENRICHED[("EVPNS-REQ#350", "Long run", 0)] = (
    "Run sustained MAC churn for ≥ 24 hours.",
    "Table size stable per limits; no leaks; ageing operates correctly.",
)
ENRICHED[("EVPNS-REQ#350", "Feature interaction", 0)] = (
    "Combine local + remote learning + static MACs (REQ#80) in same EVI.",
    "All three sources coexist; static takes precedence per spec; no conflicts.",
)
ENRICHED[("EVPNS-REQ#350", "3rd Party Interoperability", 0)] = (
    "Receive BGP Type-2 routes from 3rd-party PE; verify table population.",
    "Entries install correctly; egress correct.",
)
ENRICHED[("EVPNS-REQ#350", "Packet validation", 0)] = (
    "Send unicast frames; verify forwarding decision uses the table.",
    "Lookup yields correct egress; frame delivered.",
)
ENRICHED[("EVPNS-REQ#350", "Malformed/unsupported packets", 0)] = (
    "Send unicast frames to unknown MACs; observe BUM flooding.",
    "Frames flooded as unknown unicast; learning may occur on response.",
)
ENRICHED[("EVPNS-REQ#350", "Performance", 0)] = (
    "Measure lookup performance at scale (table near limit).",
    "Lookup time within hardware bounds; no degradation as table fills.",
)
ENRICHED[("EVPNS-REQ#350", "Scale", 0)] = (
    "Load table to documented MAC limit (e.g. 100k entries).",
    "Limit enforced; documented overflow behavior; no crash.",
)
ENRICHED[("EVPNS-REQ#350", "Upgrade", 0)] = (
    "Run onie-install with full table.",
    "Table rebuilds post-upgrade; static entries preserved.",
)
ENRICHED[("EVPNS-REQ#350", "Management", 0)] = (
    "Query table state via NETCONF.",
    "Returns same data as `show mac-address-table evpn`.",
)
ENRICHED[("EVPNS-REQ#350", "Tech-support", 0)] = (
    "Collect tech-support with full table.",
    "Archive contains table snapshots, source-of-learn breakdowns.",
)


# ─── EVPNS-REQ#360 BUM Split Horizon Table (§5.1.2) ───────────────────────
ENRICHED[("EVPNS-REQ#360", "CLI configuration", 0)] = (
    "Configure multi-homed segments; verify BUM Split Horizon Table builds per §5.1.2.",
    "Table maps incoming MPLS label (LT2) to drop decision for same-ESI BUM frames.",
)
ENRICHED[("EVPNS-REQ#360", "CLI configuration", 1)] = (
    "Edit ESI; verify table entries adjust.",
    "Old entries removed; new entries added.",
)
ENRICHED[("EVPNS-REQ#360", "CLI configuration", 2)] = (
    "Delete ESI; verify table entries removed.",
    "Entries gone; no stale split-horizon decisions.",
)
ENRICHED[("EVPNS-REQ#360", "CLI configuration", 3)] = (
    "Apply factory-default; replay; verify table re-populates.",
    "Entries restored after ESI reformation.",
)
ENRICHED[("EVPNS-REQ#360", "CLI configuration", 4)] = (
    "Modify ESI, then rollback.",
    "Table unchanged.",
)
ENRICHED[("EVPNS-REQ#360", "Basic Functionality", 0)] = (
    "Send BUM through a multi-homed segment; verify table-driven drop on same-ESI receiving PE.",
    "Same-ESI BUM dropped; cross-ESI BUM forwarded; split horizon decision correct.",
)
ENRICHED[("EVPNS-REQ#360", "Basic Functionality", 1)] = (
    "Verify default table behavior with no multi-homed ESes — table empty.",
    "No split-horizon decisions made; BUM forwarded normally.",
)
ENRICHED[("EVPNS-REQ#360", "Packet validation", 0)] = (
    "Send BUM with various label stacks; verify table consults correctly.",
    "Decisions match RFC; correct frames dropped or forwarded.",
)
ENRICHED[("EVPNS-REQ#360", "Malformed/unsupported packets", 0)] = (
    "Send BUM with malformed split-horizon label.",
    "Per spec default action; counter increments.",
)
ENRICHED[("EVPNS-REQ#360", "Feature interaction", 0)] = (
    "Combine table with multi-EVI multi-homing.",
    "Per-ESI table entries cover all EVIs sharing the ESI.",
)
ENRICHED[("EVPNS-REQ#360", "3rd Party Interoperability", 0)] = (
    "Verify table-driven decisions interop with 3rd-party PE.",
    "Same drop/forward outcomes across vendors.",
)
ENRICHED[("EVPNS-REQ#360", "Performance", 0)] = (
    "Measure BUM forwarding throughput with split-horizon table active.",
    "No measurable performance impact from table consultation.",
)
ENRICHED[("EVPNS-REQ#360", "Scale", 0)] = (
    "Scale to many multi-homed ESes; verify table populated correctly.",
    "All entries present; no overflow.",
)
ENRICHED[("EVPNS-REQ#360", "Upgrade", 0)] = (
    "Run onie-install with active multi-homed ESes.",
    "Table rebuilds post-upgrade.",
)
ENRICHED[("EVPNS-REQ#360", "Management", 0)] = (
    "Query split-horizon table via NETCONF.",
    "Operational data exposes the table.",
)
ENRICHED[("EVPNS-REQ#360", "Tech-support", 0)] = (
    "Collect tech-support after BUM scenarios.",
    "Archive contains table state, drop counters.",
)


# ─── EVPNS-REQ#370 Forwarding Rules (§5.2) ────────────────────────────────
ENRICHED[("EVPNS-REQ#370", "CLI configuration", 0)] = (
    "Configure an EVPN with the full forwarding stack (MAC table, BUM SH table, BUM forwarding table); verify rules per §5.2.",
    "Rules apply per spec: General rules (§5.2.1), Local input (§5.2.2), Remote input (§5.2.3); per spec MUST: 'Forwarding Rules MUST be supported.'",
)
ENRICHED[("EVPNS-REQ#370", "CLI configuration", 1)] = (
    "Edit forwarding-related config (e.g. enable/disable a specific service-type).",
    "Rules adjust accordingly; running config matches.",
)
ENRICHED[("EVPNS-REQ#370", "CLI configuration", 2)] = (
    "Delete the EVPN; verify all forwarding rules for it removed.",
    "Rules purged; tables freed.",
)
ENRICHED[("EVPNS-REQ#370", "CLI configuration", 3)] = (
    "Apply factory-default; replay; verify rules re-instate.",
    "Rules match pre-default behavior.",
)
ENRICHED[("EVPNS-REQ#370", "CLI configuration", 4)] = (
    "Make a forwarding-rule change, then rollback.",
    "Rules revert.",
)
ENRICHED[("EVPNS-REQ#370", "Basic Functionality", 0)] = (
    "Verify per spec §5.2 forwarding rules apply correctly to local input traffic.",
    "Local frames learned, replicated for BUM, forwarded for unicast.",
)
ENRICHED[("EVPNS-REQ#370", "Basic Functionality", 1)] = (
    "Verify per spec §5.2 forwarding rules apply correctly to remote (MPLS-encap) input traffic.",
    "Remote frames decap'd, looked up in MAC table, forwarded out the correct egress.",
)
ENRICHED[("EVPNS-REQ#370", "Packet validation", 0)] = (
    "Send a mix of unicast and BUM traffic; verify each rule path.",
    "All frames forwarded per spec rules; no undefined behavior.",
)
ENRICHED[("EVPNS-REQ#370", "Malformed/unsupported packets", 0)] = (
    "Send malformed frames at various pipeline stages.",
    "Frames dropped at the appropriate stage; counters increment; no crash.",
)
ENRICHED[("EVPNS-REQ#370", "Feature interaction", 0)] = (
    "Combine forwarding rules with all-active multi-homing.",
    "Per spec aliasing distributes; split horizon prevents loops; all rules cohere.",
)
ENRICHED[("EVPNS-REQ#370", "3rd Party Interoperability", 0)] = (
    "Verify rules work end-to-end with a 3rd-party remote PE.",
    "Encap/decap symmetric; forwarding behavior matches.",
)
ENRICHED[("EVPNS-REQ#370", "Performance", 0)] = (
    "Push line-rate mixed traffic through the full forwarding stack.",
    "Throughput at line rate; no rule-evaluation bottleneck.",
)
ENRICHED[("EVPNS-REQ#370", "Scale", 0)] = (
    "Run forwarding rules at full table scale.",
    "Rules evaluate within bounds; no degradation.",
)
ENRICHED[("EVPNS-REQ#370", "Upgrade", 0)] = (
    "Run onie-install upgrade.",
    "Rules restore post-upgrade.",
)
ENRICHED[("EVPNS-REQ#370", "Management", 0)] = (
    "Query forwarding state via NETCONF.",
    "Operational data shows rule application.",
)
ENRICHED[("EVPNS-REQ#370", "Tech-support", 0)] = (
    "Collect tech-support after sustained forwarding traffic.",
    "Archive contains per-rule counters.",
)


# ─── EVPNS-REQ#380 Configuration (overall configuration support, §6) ──────
ENRICHED[("EVPNS-REQ#380", "CLI configuration", 0)] = (
    "Apply the full §6 configuration sequence (interface + LACP + ethernet-segment + BGP + EVPN); commit.",
    "All §6 commands accepted; configuration persists; running config matches §6 example exactly.",
)
ENRICHED[("EVPNS-REQ#380", "CLI configuration", 1)] = (
    "Edit one parameter from each §6 section (LACP key, ESI value, BGP neighbor, EVPN service-type); commit.",
    "Each edit applies; per-section behavior updates accordingly; no cross-section regressions.",
)
ENRICHED[("EVPNS-REQ#380", "CLI configuration", 2)] = (
    "Delete the entire §6 EVPN deployment; commit.",
    "Configuration removed; routes withdrawn; all related state cleaned up.",
)
ENRICHED[("EVPNS-REQ#380", "CLI configuration", 3)] = (
    "Apply factory-default; replay the full §6 configuration.",
    "All §6 elements restore identically; no diff.",
)
ENRICHED[("EVPNS-REQ#380", "CLI configuration", 4)] = (
    "Make changes across multiple §6 sections, then rollback.",
    "All sections revert atomically; no partial commits.",
)
ENRICHED[("EVPNS-REQ#380", "Basic Functionality", 0)] = (
    "Verify the full §6 configuration brings up an end-to-end working EVPN.",
    "BGP sessions Established; EVPN routes exchanged; data-plane forwards traffic; per spec MUST: §6 configuration supported.",
)
ENRICHED[("EVPNS-REQ#380", "Basic Functionality", 1)] = (
    "Verify default behavior of partial §6 configurations (e.g. omit LACP — verify single-home result).",
    "Partial configs degrade gracefully; documented behavior holds.",
)
ENRICHED[("EVPNS-REQ#380", "On The Fly changes", 0)] = (
    "Modify a §6 configuration element while traffic flows.",
    "Changes apply with documented service impact; per-element documented behavior holds.",
)
ENRICHED[("EVPNS-REQ#380", "Feature interaction", 0)] = (
    "Combine all §6 sections in their interactions.",
    "All work together as the spec example shows.",
)
ENRICHED[("EVPNS-REQ#380", "3rd Party Interoperability", 0)] = (
    "Configure §6 deployment in mixed-vendor topology.",
    "Interop holds; all features per spec MUST.",
)
ENRICHED[("EVPNS-REQ#380", "Packet validation", 0)] = (
    "Send traffic through the §6-configured EVPN.",
    "Forwarded per spec.",
)
ENRICHED[("EVPNS-REQ#380", "Upgrade", 0)] = (
    "With the full §6 deployment, run onie-install upgrade.",
    "Configuration restores; deployment re-converges.",
)
ENRICHED[("EVPNS-REQ#380", "Management", 0)] = (
    "Apply §6 configuration via NETCONF/YANG.",
    "Equivalent CLI generated; deployment behaves identically.",
)
ENRICHED[("EVPNS-REQ#380", "Tech-support", 0)] = (
    "Collect tech-support of the full §6 deployment.",
    "Archive contains running config matching §6 + complete operational state.",
)


# ─── EVPNS-REQ#390 Alarms (additional categories) ─────────────────────────
ENRICHED[("EVPNS-REQ#390", "CLI configuration", 0)] = (
    "Configure alarm-relevant scenarios (multi-homed ES with mismatched LACP system-mac on peer); commit.",
    "Triggers the spec's MUST alarm: 'Multi-homed ES misconfiguration for ESI <esi>(agg-eth n): from <ip>, LACP System MAC <mac>, DF Algorithm <alg>'.",
)
ENRICHED[("EVPNS-REQ#390", "CLI configuration", 1)] = (
    "Resolve the misconfiguration; verify alarm clears.",
    "Alarm cleared; `show alarms` no longer lists it.",
)
ENRICHED[("EVPNS-REQ#390", "CLI configuration", 2)] = (
    "Delete the offending ES configuration; verify alarm clears.",
    "Alarm cleared.",
)
ENRICHED[("EVPNS-REQ#390", "CLI configuration", 3)] = (
    "Apply factory-default; replay misconfiguration; verify same alarm fires.",
    "Alarm fires consistently; details match.",
)
ENRICHED[("EVPNS-REQ#390", "CLI configuration", 4)] = (
    "Make alarm-causing config change, then rollback.",
    "No alarm fires.",
)
ENRICHED[("EVPNS-REQ#390", "On The Fly changes", 0)] = (
    "Trigger a misconfig while traffic flows; observe alarm and BUM forwarding behavior.",
    "Alarm fires; BUM forwarding stays correct per §2.7 ('PE fixes misconfiguration if this ES is advertised by another router').",
)
ENRICHED[("EVPNS-REQ#390", "Robustness", 0)] = (
    "Reset PE while alarm is active; verify alarm re-fires post-recovery.",
    "Alarm re-asserts on recovery if condition still present.",
)
ENRICHED[("EVPNS-REQ#390", "Robustness", 1)] = (
    "Power-cycle PE during alarm.",
    "Alarm re-fires post power-up.",
)
ENRICHED[("EVPNS-REQ#390", "Robustness", 2)] = (
    "Flap interface during alarm condition.",
    "Alarm state preserved through transient.",
)
ENRICHED[("EVPNS-REQ#390", "HA", 0)] = (
    "Kill alarm-monitoring process; verify recovery.",
    "Process restarts; alarm state preserved or re-asserted.",
)
ENRICHED[("EVPNS-REQ#390", "Long run", 0)] = (
    "Run alarm-eligible deployment for ≥ 24 hours; periodically toggle conditions.",
    "Alarm fires/clears reliably each toggle; no spurious; no missed events.",
)
ENRICHED[("EVPNS-REQ#390", "Performance", 0)] = (
    "Measure alarm-firing latency from condition onset.",
    "Latency within documented bounds.",
)
ENRICHED[("EVPNS-REQ#390", "Scale", 0)] = (
    "Trigger many simultaneous alarms (multiple misconfigured ESes).",
    "All alarms tracked; system stays responsive; no alarm queue overflow.",
)
ENRICHED[("EVPNS-REQ#390", "Upgrade", 0)] = (
    "Run onie-install with active alarm.",
    "Alarm re-fires post-upgrade if condition persists.",
)
ENRICHED[("EVPNS-REQ#390", "Management", 0)] = (
    "Query alarms via NETCONF.",
    "Alarm list and details exposed identically to `show alarms`.",
)


# ─── EVPNS-REQ#400 Syslog Messages (§7.2) ─────────────────────────────────
ENRICHED[("EVPNS-REQ#400", "Alarms/Logs/Syslog", 0)] = (
    "Trigger every documented EVPN syslog message scenario (per §7.2): MAC violations, ES misconfig, BGP route errors.",
    "Each scenario produces the documented syslog entry with proper severity and context fields per spec MUST: 'Syslog Messages MUST be supported.'",
)
ENRICHED[("EVPNS-REQ#400", "PM", 0)] = (
    "Verify per-syslog-category counters.",
    "Counters increment per syslog event; clear works; values persist.",
)
ENRICHED[("EVPNS-REQ#400", "Tech-support", 0)] = (
    "Collect tech-support including the full syslog history.",
    "Archive contains rotated syslog files covering the test run.",
)


# ─── On-The-Fly + remaining gaps ──────────────────────────────────────────
ENRICHED[("EVPNS-REQ#110", "On The Fly changes", 0)] = (
    "Change ESI value (Type 0/1/4) on a multi-homed segment while traffic flows.",
    "Old ES route (4) withdrawn, new advertised; brief DF re-election; no permanent service loss.",
)
ENRICHED[("EVPNS-REQ#120", "On The Fly changes", 0)] = (
    "Change service-carving algorithm on one PE while DF election is active.",
    "DF Alg renegotiation triggers; if mismatch, fall back to Default per §2.7.2.2.",
)
ENRICHED[("EVPNS-REQ#120", "Management", 0)] = (
    "Configure service-carving algorithm via NETCONF/YANG.",
    "Equivalent CLI generated; election behavior matches.",
)
ENRICHED[("EVPNS-REQ#220", "On The Fly changes", 0)] = (
    "Change BUM replication peer set while traffic flows.",
    "Type-3 routes update; replication list adjusts; no in-flight loss for existing peers.",
)
ENRICHED[("EVPNS-REQ#230", "On The Fly changes", 0)] = (
    "Modify a parameter that influences PMSI Tunnel Attribute (e.g. RT/RD).",
    "Type-3 re-advertised with updated PMSI; per-peer label may be re-allocated.",
)
ENRICHED[("EVPNS-REQ#250", "On The Fly changes", 0)] = (
    "Change ES-Import RT while ES route (4) is advertising.",
    "Route re-advertised under new RT; previously importing PEs stop importing; new ones start.",
)
ENRICHED[("EVPNS-REQ#260", "On The Fly changes", 0)] = (
    "Change ESI on a live multi-homed segment.",
    "EthA-D Per ES (RT-1) withdrawn under old ESI, re-advertised under new; mass-withdrawal triggers on remote PEs.",
)
ENRICHED[("EVPNS-REQ#270", "On The Fly changes", 0)] = (
    "Change ETID on a multi-homed EVI while RT-1 Per EVI route is active.",
    "Route updates; aliasing path re-evaluated.",
)
ENRICHED[("EVPNS-REQ#280", "Upgrade", 0)] = (
    "With heavy Type-2 advertisement, run onie-install upgrade.",
    "Routes re-advertise post-upgrade; MAC table rebuilds via data-plane learning + BGP.",
)
ENRICHED[("EVPNS-REQ#280", "Management", 0)] = (
    "Configure mac-limit and advertise-mac via NETCONF.",
    "Equivalent CLI generated; behavior matches.",
)
ENRICHED[("EVPNS-REQ#300", "On The Fly changes", 0)] = (
    "Change DF election algorithm or LACP parameters that influence Type-4.",
    "Route re-advertised with updated DF Election EC; election re-runs.",
)
ENRICHED[("EVPNS-REQ#320", "On The Fly changes", 0)] = (
    "Change ESI on a live segment; observe LT2 reallocation.",
    "Old LT2 freed; new allocated; same-ESI peers update split-horizon decisions.",
)
ENRICHED[("EVPNS-REQ#330", "On The Fly changes", 0)] = (
    "Add/remove an EVPN peer while BUM forwarding is active.",
    "LT3 allocated/freed for the peer; Type-3 list updates; replication count adjusts.",
)
ENRICHED[("EVPNS-REQ#340", "On The Fly changes", 0)] = (
    "Add/remove an EVI while BUM forwarding is active.",
    "LT4 allocated/freed; Type-3 list updates accordingly.",
)
ENRICHED[("EVPNS-REQ#350", "On The Fly changes", 0)] = (
    "Modify ageing time or mac-limit while the forwarding table is populated.",
    "New policy applied; existing entries adjust on next age cycle or excess removal.",
)
ENRICHED[("EVPNS-REQ#360", "On The Fly changes", 0)] = (
    "Add/remove a multi-homed ESI while BUM forwarding is active.",
    "Split-horizon table entries adjust; no incorrect drops or forwards during transition.",
)
ENRICHED[("EVPNS-REQ#370", "On The Fly changes", 0)] = (
    "Modify a forwarding-rule-relevant configuration (e.g. switch service-type) while traffic flows.",
    "Rules adjust per spec §5.2; existing flows may be disrupted briefly per documented behavior.",
)
ENRICHED[("EVPNS-REQ#390", "PM", 0)] = (
    "Verify PM counters for alarm-firing/clearing events.",
    "Counters increment per alarm; clear works; values persist across reload.",
)
ENRICHED[("EVPNS-REQ#390", "Alarms/Logs/Syslog", 0)] = (
    "Trigger an ES misconfiguration; verify spec MUST alarm AND a corresponding syslog entry.",
    "Both the alarm record and a syslog entry fire with consistent details (ESI, source IP, mismatch info).",
)


def main() -> None:
    plan = generate_plan("references/EVPN System Specification 1.00.docx", use_ai=False)
    req_by_id = {r.req_id: r for r in plan.requirements}

    cache: dict[str, dict] = {}
    seen: dict[tuple[str, str], int] = {}
    n_baked = 0
    n_skipped = 0
    for row in plan.rows:
        key_pair = (row.sfs_requirement_id, row.category)
        sub = seen.get(key_pair, 0)
        seen[key_pair] = sub + 1
        req = req_by_id.get(row.sfs_requirement_id)
        if req is None:
            continue
        ek = (row.sfs_requirement_id, row.category, sub)
        if ek not in ENRICHED:
            n_skipped += 1
            continue
        cache_key = _row_key(req, row, sub)
        action, expectation = ENRICHED[ek]
        cache[cache_key] = {
            "req_id": row.sfs_requirement_id,
            "category": row.category,
            "action_steps": action,
            "expectation": expectation,
        }
        n_baked += 1

    save_cache(cache, CACHE_PATH)
    print(f"Baked {n_baked} AI-enriched rows into {CACHE_PATH.relative_to(Path.cwd())}")
    print(f"Skipped {n_skipped} rule-based rows (will use templates or live API)")


if __name__ == "__main__":
    main()
"""

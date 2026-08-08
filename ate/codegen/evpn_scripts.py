"""Curated step lists for the three M2 automation flows.

Scope comes straight from Exaware (Eyal, 2026-08): of the M1 flow catalog,
FLOW-010 / FLOW-030 / FLOW-031 are the ones the single-DUT + 3-IXIA-port rig
can actually run. FLOW-010 is the prerequisite for the other two.

These step lists are **hand-curated, not AI-generated**. Two reasons:

  * The M1 TDD already flags this as the right M2 move ("consider hand-curating
    per-flow atomic_steps lists on each Flow for higher-quality decomposition")
    — the mechanical prose splitter in `atomic_rows.py` produces rows for a
    human reader, not executable steps.
  * Curating costs nothing at run time and skips a ~10 h AI re-bake
    (`memory/project_m1_full_bake_cost.md`). Nothing here changes a flow's
    cache key.

The prose flows in `planner/flows.py` stay the source of intent — every step
below carries the requirement IDs its parent flow claims, so the generated Java
traces back to the same SFS/RFC anchors the reviewed test plan cites.

Steps whose expected values cannot be known from the documents alone (real
`show` output, the EVPN MAC-aging default) carry `todo=` and are emitted as
compiling TODO stubs. That is deliberate: a guessed assertion that silently
passes is worse than an explicit gap.
"""
from __future__ import annotations

from ate.codegen.lab import SINGLE_DUT_3AC, LabProfile
from ate.codegen.script_ir import Step, StepKind, TestScript

# Requirement anchors, mirrored from the flow selectors in planner/flows.py so
# the generated code cites the same IDs as the reviewed xlsx.
_R_BRINGUP = ["EVPNS-REQ#30", "EVPNS-REQ#40", "EVPNS-REQ#50", "EVPNS-REQ#380"]
_R_TYPE2 = ["RFC7432bis-§7.2"]
_R_TYPE3 = ["RFC7432bis-§7.3", "RFC7432bis-§11"]


def _bring_up(lab: LabProfile) -> TestScript:
    """FLOW-010 — VLAN-based EVPN bring-up with three local ACs.

    Differs from the M1 FLOW-010 in one way that matters: the reviewed flow
    binds a single AC on a two-PE topology; the automatable version binds all
    three IXIA ports as local ACs on one EVI, which is what makes the
    flooding and MAC-move assertions in FLOW-030/031 possible at all.
    """
    evi = lab.evi_name
    steps: list[Step] = [
        Step(
            id="FLOW-010.S01",
            kind=StepKind.CONFIG,
            text=f"Create EVPN instance {evi} with service-type vlan-based",
            command="CONFIGURE_L2_SERVICES_EVPN_$_SERVICE_TYPE_$",
            args=[evi, "vlan-based"],
            req_ids=_R_BRINGUP,
        ),
        Step(
            id="FLOW-010.S02",
            kind=StepKind.CONFIG,
            text=f"Enable auto-discovery on {evi}",
            command="CONFIGURE_L2_SERVICES_EVPN_$_AUTO_DISCOVERY",
            args=[evi],
            req_ids=_R_BRINGUP,
        ),
        Step(
            id="FLOW-010.S03",
            kind=StepKind.CONFIG,
            text=f"Set import-rt / export-rt on {evi}",
            command="CONFIGURE_L2_SERVICES_EVPN_$_IMPORT_RT_$",
            args=[evi, "65000:1"],
            req_ids=_R_BRINGUP,
        ),
        Step(
            id="FLOW-010.S04",
            kind=StepKind.CONFIG,
            text=f"Set export-rt on {evi}",
            command="CONFIGURE_L2_SERVICES_EVPN_$_EXPORT_RT_$",
            args=[evi, "65000:1"],
            req_ids=_R_BRINGUP,
        ),
    ]
    for i, ac in enumerate(lab.acs, start=5):
        steps.append(Step(
            id=f"FLOW-010.S{i:02d}",
            kind=StepKind.CONFIG,
            text=f"Bind access circuit {ac.name} ({ac.interface}) to {evi}",
            command="CONFIGURE_L2_SERVICES_EVPN_$_INTERFACE_$",
            args=[evi, ac.interface],
            req_ids=_R_BRINGUP,
        ))
    steps += [
        Step(
            id="FLOW-010.S08",
            kind=StepKind.VERIFY_CLI,
            text=f"Verify {evi} is up and all three ACs are bound",
            command="SHOW_EVPN_GLOBAL_NAME_$",
            args=[evi],
            expect_key="FLOW010_S08_EVPN_GLOBAL_LINES",
            req_ids=_R_BRINGUP,
            todo=("Expected lines need real `show evpn global` output from the "
                  "DUT — the CLI doc documents the syntax, not the layout."),
        ),
        Step(
            id="FLOW-010.S09",
            kind=StepKind.VERIFY_CLI,
            text="Verify the EVPN MAC address-table starts empty",
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$",
            args=[evi],
            expect_key="FLOW010_S09_MAC_TABLE_EMPTY_LINES",
            req_ids=_R_BRINGUP,
            todo="Needs real `show evpn mac-address-table` output.",
        ),
        Step(
            id="FLOW-010.S10",
            kind=StepKind.VERIFY_ROUTE,
            text=("Verify the Type-3 IMET route for this EVI is advertised to "
                  f"{lab.bgp_neighbor}"),
            command="SHOW_BGP_L2VPN_EVPN_NEIGHBORS_ADVERTISED_ROUTES_$_DETAIL",
            args=[lab.bgp_neighbor],
            expect_key="FLOW010_S10_TYPE3_ADVERTISED_LINES",
            req_ids=_R_TYPE3,
            todo=("Needs real `show bgp l2vpn evpn neighbors advertised-routes` "
                  "output, and depends on how the BGP EVPN peer is provided "
                  "(see LabProfile.notes)."),
        ),
    ]
    return TestScript(
        flow_id="FLOW-010",
        class_name="TC01_EvpnVlanBasedBringUp",
        method_name="evpnVlanBasedBringUp",
        title="EVPN VLAN-based bring-up with three local ACs",
        summary=(
            "Configure a vlan-based EVI on the DUT, bind all three IXIA-backed "
            "access circuits, and confirm the service comes up and advertises "
            "its Type-3 IMET route. Prerequisite for TC02 and TC03."
        ),
        steps=steps,
    )


def _type2(lab: LabProfile) -> TestScript:
    """FLOW-030 — Type-2 MAC/IP advertisement, local learning, local MAC move.

    Implements Exaware's sequence up to the MAC shift: flood-then-learn on
    AC1, learn on AC2, confirm forwarding stops flooding, then move the MACs
    to AC3 and assert **no** new Type-2 is emitted. That last assertion is not
    invented for M2 — it is Eyal's own 2026-07-06 annotation on FLOW-030: a MAC
    moving between two LOCAL ACs on the same PE must not re-advertise.
    """
    evi = lab.evi_name
    ac1, ac2, ac3 = lab.acs
    steps = [
        Step(
            id="FLOW-030.S01",
            kind=StepKind.CONFIG,
            text="Clear the EVPN MAC address-table so learning starts clean",
            command="CLEAR_EVPN_MAC_ADDRESS_TABLE_NAME_$",
            args=[evi],
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S02",
            kind=StepKind.TRAFFIC_STATE,
            text="Start traffic AC1 → AC2",
            traffic_items=["TI_AC1_TO_AC2"],
            enabled=True,
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S03",
            kind=StepKind.VERIFY_IXIA,
            text=("Verify the unknown-unicast from AC1 floods to BOTH AC2 and "
                  "AC3 (IXIA rx counters)"),
            expect_key="FLOW030_S03_FLOOD_TO_AC2_AC3_ROWS",
            req_ids=_R_TYPE3,
            todo=("Expected per-port rx rows depend on the .ixncfg port naming "
                  "and offered rate."),
        ),
        Step(
            id="FLOW-030.S04",
            kind=StepKind.VERIFY_CLI,
            text=f"Verify AC1 source MACs are learnt on {ac1.interface}",
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$_SOURCE_$",
            args=[evi, ac1.interface],
            expect_key="FLOW030_S04_AC1_MACS_LEARNT_LINES",
            req_ids=_R_TYPE2,
            todo="Needs real MAC-table output plus the AC1 source-MAC range.",
        ),
        Step(
            id="FLOW-030.S05",
            kind=StepKind.VERIFY_ROUTE,
            text="Verify AC1 source MACs are advertised as Type-2 routes",
            command="SHOW_BGP_L2VPN_EVPN_NEIGHBORS_ADVERTISED_ROUTES_$_DETAIL",
            args=[lab.bgp_neighbor],
            expect_key="FLOW030_S05_AC1_TYPE2_ADVERTISED_LINES",
            req_ids=_R_TYPE2,
            todo="Needs real advertised-routes output.",
        ),
        Step(
            id="FLOW-030.S06",
            kind=StepKind.TRAFFIC_STATE,
            text="Start traffic AC2 → AC1",
            traffic_items=["TI_AC2_TO_AC1"],
            enabled=True,
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S07",
            kind=StepKind.VERIFY_IXIA,
            text=("Verify flooding to AC3 ceases once AC2's MACs are known "
                  "(AC3 rx returns to zero)"),
            expect_key="FLOW030_S07_NO_FLOOD_TO_AC3_ROWS",
            req_ids=_R_TYPE3,
            todo="Expected rows depend on .ixncfg port naming.",
        ),
        Step(
            id="FLOW-030.S08",
            kind=StepKind.VERIFY_CLI,
            text="Verify AC1 source MACs are still intact in the MAC table",
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$_SOURCE_$",
            args=[evi, ac1.interface],
            expect_key="FLOW030_S04_AC1_MACS_LEARNT_LINES",
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S09",
            kind=StepKind.VERIFY_CLI,
            text=f"Verify AC2 source MACs are learnt on {ac2.interface}",
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$_SOURCE_$",
            args=[evi, ac2.interface],
            expect_key="FLOW030_S09_AC2_MACS_LEARNT_LINES",
            req_ids=_R_TYPE2,
            todo="Needs real MAC-table output plus the AC2 source-MAC range.",
        ),
        Step(
            id="FLOW-030.S10",
            kind=StepKind.VERIFY_ROUTE,
            text="Verify AC2 source MACs are also advertised as Type-2 routes",
            command="SHOW_BGP_L2VPN_EVPN_NEIGHBORS_ADVERTISED_ROUTES_$_DETAIL",
            args=[lab.bgp_neighbor],
            expect_key="FLOW030_S10_AC2_TYPE2_ADVERTISED_LINES",
            req_ids=_R_TYPE2,
            todo="Needs real advertised-routes output.",
        ),
        Step(
            id="FLOW-030.S11",
            kind=StepKind.TRAFFIC_STATE,
            text="Stop traffic AC2 → AC1",
            traffic_items=["TI_AC2_TO_AC1"],
            enabled=False,
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S12",
            kind=StepKind.VERIFY_IXIA,
            text="Verify AC1 → AC2 traffic still forwards to AC2 (no flooding)",
            expect_key="FLOW030_S12_UNICAST_TO_AC2_ROWS",
            req_ids=_R_TYPE2,
            todo="Expected rows depend on .ixncfg port naming.",
        ),
        Step(
            id="FLOW-030.S13",
            kind=StepKind.VERIFY_NO_EVENT,
            text=("Snapshot the advertised Type-2 routes before moving the "
                  "MACs to AC3"),
            command="SHOW_BGP_L2VPN_EVPN_NEIGHBORS_ADVERTISED_ROUTES_$_DETAIL",
            args=[lab.bgp_neighbor],
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S14",
            kind=StepKind.TRAFFIC_STATE,
            text=("Start traffic AC3 → AC1 (AC3 sources the same MACs as AC2, "
                  "so this is a local MAC move)"),
            traffic_items=["TI_AC3_TO_AC1"],
            enabled=True,
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S15",
            kind=StepKind.VERIFY_CLI,
            text=f"Verify the AC2 MACs have shifted to {ac3.interface}",
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$_SOURCE_$",
            args=[evi, ac3.interface],
            expect_key="FLOW030_S15_MACS_MOVED_TO_AC3_LINES",
            req_ids=_R_TYPE2,
            todo="Needs real MAC-table output.",
        ),
        Step(
            id="FLOW-030.S16",
            kind=StepKind.VERIFY_NO_EVENT,
            text=("Verify NO new Type-2 was triggered by the local AC2 → AC3 "
                  "move (advertised routes unchanged vs the snapshot)"),
            command="SHOW_BGP_L2VPN_EVPN_NEIGHBORS_ADVERTISED_ROUTES_$_DETAIL",
            args=[lab.bgp_neighbor],
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S17",
            kind=StepKind.VERIFY_IXIA,
            text="Verify AC1 → AC2 traffic now forwards out AC3",
            expect_key="FLOW030_S17_UNICAST_TO_AC3_ROWS",
            req_ids=_R_TYPE2,
            todo="Expected rows depend on .ixncfg port naming.",
        ),
    ]
    return TestScript(
        flow_id="FLOW-030",
        class_name="TC02_EvpnType2MacIpAdvertisement",
        method_name="evpnType2MacIpAdvertisement",
        title="EVPN Route Type-2 MAC/IP advertisement, learning and local move",
        summary=(
            "Learn MACs on AC1 and AC2, confirm each is advertised as a Type-2 "
            "route, then move the AC2 MACs to AC3 and confirm a purely local "
            "interface move updates forwarding WITHOUT re-advertising."
        ),
        steps=steps,
        depends_on=["FLOW-010"],
    )


def _type3(lab: LabProfile) -> TestScript:
    """FLOW-031 — BUM flooding and Type-2 withdrawal after MAC aging."""
    evi = lab.evi_name
    steps = [
        Step(
            id="FLOW-031.S01",
            kind=StepKind.TRAFFIC_STATE,
            text="Stop traffic AC3 → AC1",
            traffic_items=["TI_AC3_TO_AC1"],
            enabled=False,
            req_ids=_R_TYPE3,
        ),
        Step(
            id="FLOW-031.S02",
            kind=StepKind.WAIT,
            text="Wait for the MAC aging time to expire",
            seconds=lab.mac_aging_seconds,
            req_ids=_R_TYPE2,
            todo=("EVPN MAC-aging default is not stated in the CLI doc. The "
                  "VPLS suite treats aging as a tuned per-platform value with "
                  "a wide deviation window (TC05_VplsMacAgingTime); EVPN will "
                  "need the same. Confirm the default with Exaware."),
        ),
        Step(
            id="FLOW-031.S03",
            kind=StepKind.VERIFY_IXIA,
            text=("Verify AC1 → AC2 traffic floods to BOTH AC2 and AC3 again "
                  "now the MACs have aged out"),
            expect_key="FLOW030_S03_FLOOD_TO_AC2_AC3_ROWS",
            req_ids=_R_TYPE3,
        ),
        Step(
            id="FLOW-031.S04",
            kind=StepKind.VERIFY_CLI,
            text="Verify the AC2 MACs are removed from the EVPN MAC table",
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$",
            args=[evi],
            expect_key="FLOW031_S04_MACS_AGED_OUT_LINES",
            req_ids=_R_TYPE2,
            todo="Needs real MAC-table output.",
        ),
        Step(
            id="FLOW-031.S05",
            kind=StepKind.VERIFY_ROUTE,
            text=("Verify the AC2 MACs' Type-2 routes are withdrawn from the "
                  "BGP table"),
            command="SHOW_BGP_L2VPN_EVPN_TABLE_EVI_NAME_$_DETAIL",
            args=[evi],
            expect_key="FLOW031_S05_TYPE2_WITHDRAWN_LINES",
            req_ids=_R_TYPE2,
            todo="Needs real BGP EVPN table output.",
        ),
        Step(
            id="FLOW-031.S06",
            kind=StepKind.VERIFY_CLI,
            text="Verify the BUM routing table still lists the flood list",
            command="SHOW_EVPN_BUM_ROUTING_TABLE_NAME_$",
            args=[evi],
            expect_key="FLOW031_S06_BUM_ROUTING_LINES",
            req_ids=_R_TYPE3,
            todo="Needs real `show evpn bum routing-table` output.",
        ),
    ]
    return TestScript(
        flow_id="FLOW-031",
        class_name="TC03_EvpnType3ImetFlooding",
        method_name="evpnType3ImetFlooding",
        title="EVPN Route Type-3 IMET flooding and Type-2 withdrawal on aging",
        summary=(
            "After the AC3 source stops, wait out MAC aging and confirm the "
            "service reverts to flooding, the MAC table drops the aged "
            "entries, and their Type-2 routes are withdrawn."
        ),
        steps=steps,
        depends_on=["FLOW-010", "FLOW-030"],
    )


def evpn_scripts(lab: LabProfile = SINGLE_DUT_3AC) -> list[TestScript]:
    """The three M2 scripts, in dependency order."""
    return [_bring_up(lab), _type2(lab), _type3(lab)]

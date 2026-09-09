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

from ate.codegen.lab import (
    SINGLE_DUT_3AC,
    LabProfile,
    PeerSource,
    TrafficItem,
)
from ate.codegen.script_ir import Step, StepKind, TestScript

# Requirement anchors, mirrored from the flow selectors in planner/flows.py so
# the generated code cites the same IDs as the reviewed xlsx.
_R_BRINGUP = ["EVPNS-REQ#30", "EVPNS-REQ#40", "EVPNS-REQ#50", "EVPNS-REQ#380"]
_R_TYPE2 = ["RFC7432bis-§7.2"]
_R_TYPE3 = ["RFC7432bis-§7.3", "RFC7432bis-§11"]


def _advertised(lab: LabProfile) -> tuple[str, list[str], str]:
    """How to assert "this route is advertised", given the rig.

    With a BGP EVPN peer we can read what was actually sent to it. Without one
    we read the local EVI table, which lists the routes this PE originates.
    Weaker (origination, not transmission) but a real assertion that needs no
    lab change, and it keeps every other step identical.

    Returns (command key, args, a phrase for the step text).

    The phrase states WHAT IS ASSERTED and nothing else. It used to end
    "(no BGP peer on this rig)", which was carried verbatim into the
    CompassReporter level title and so into the QA run report — a step whose
    own name apologises for the testbed. Worse, it was emitted for
    `PeerSource.IXIA` too, where a BGP session genuinely does exist and reaches
    Established, so the shipped suite told a reader the opposite of the truth.
    Why a given command was chosen belongs in `_peer_note`, which lands in the
    class Javadoc where a reader can act on it.
    """
    if lab.peer_source is PeerSource.NEIGHBOUR:
        return ("SHOW_BGP_L2VPN_EVPN_NEIGHBORS_ADVERTISED_ROUTES_$_DETAIL",
                [lab.bgp_neighbor],
                f"advertised to {lab.bgp_neighbor}")
    return ("SHOW_BGP_L2VPN_EVPN_TABLE_EVI_DETAIL",
            [],
            "originated into the local EVI table")


def _peer_note(lab: LabProfile) -> str:
    """Why this suite asserts origination rather than transmission.

    One sentence, into the generated class Javadoc. A reader who wants
    transmission asserted learns exactly what has to change.
    """
    if lab.peer_source is PeerSource.NEIGHBOUR:
        return (f"Advertisement is asserted against what was actually sent to "
                f"{lab.bgp_neighbor}, so these steps prove transmission.")
    if lab.peer_source is PeerSource.IXIA:
        return ("Advertisement is asserted against the local EVI table, which "
                "proves ORIGINATION but not transmission. A BGP session to "
                "the IXIA-emulated peer does exist and reaches Established; "
                "what it cannot carry is the EVPN address family, because "
                "chassis 10.1.70.108 answers ERROR-1005 'no license available "
                "for BGP EVPN'. Adding that licence is what upgrades these "
                "steps to transmission.")
    return ("Advertisement is asserted against the local EVI table, which "
            "proves ORIGINATION but not transmission, because this profile "
            "has no BGP peer at all. See LabProfile.core.")


def _bring_up(lab: LabProfile) -> TestScript:
    """FLOW-010 — VLAN-based EVPN bring-up with three local ACs.

    Differs from the M1 FLOW-010 in one way that matters: the reviewed flow
    binds a single AC on a two-PE topology; the automatable version binds all
    three IXIA ports as local ACs on one EVI, which is what makes the
    flooding and MAC-move assertions in FLOW-030/031 possible at all.
    """
    evi = lab.evi_name
    _adv_cmd, _adv_args, _adv_phrase = _advertised(lab)
    steps: list[Step] = [
        Step(
            id="FLOW-010.S00A",
            kind=StepKind.VERIFY_CLI,
            text=f"Verify {evi} does not exist before this test creates it",
            # Exaware, 2026-09-08 (Eyal Ozeri): "TC01 seems to configure an
            # already existing evpn service." It did. EVPN_Base.cfg created
            # the EVI and the .crt loads it at bring-up, so every create step
            # below re-typed configuration the device already held: nothing
            # was staged, the commit had nothing to do, and the steps could
            # not fail. The service is now created here and nowhere else, and
            # this step is what proves the starting point.
            #
            # The expectation is a generation-time literal rather than a
            # capture: the EVI's name is not device output, and an empty
            # expectation array would make this assertion pass on any output
            # at all - including output showing the EVI already there.
            command="SHOW_EVPN_SUMMARY",
            args=[],
            expect_key="FLOW010_S00A_EVI_ABSENT_LINES",
            expect_literal=[evi],
            expect_absent=True,
            req_ids=_R_BRINGUP,
        ),
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
            text=f"Bind access circuit {ac.name} ({ac.ac_interface}) to {evi}",
            command="CONFIGURE_L2_SERVICES_EVPN_$_INTERFACE_$",
            args=[evi, ac.ac_interface],
            req_ids=_R_BRINGUP,
        ))
    steps += [
        Step(
            id="FLOW-010.S08",
            kind=StepKind.VERIFY_CLI,
            text=(f"Verify {evi} is up and all {len(lab.acs)} attachment "
                  "circuits are bound"),
            # `show evpn global` does not exist on the device: verified
            # 2026-08-11 against 8.7.0 LAB 22, which answers "syntax error:
            # unknown argument" and lists summary/detail/mac-address-table/
            # broadcast-domains under `show evpn ?`.
            command="SHOW_EVPN_DETAIL",
            args=[],
            expect_key="FLOW010_S08_EVPN_DETAIL_LINES",
            req_ids=_R_BRINGUP,
            todo=("Expected lines need real `show evpn detail` output with an "
                  "EVI configured; on an empty device it answers "
                  "\"No entries found\"."),
        ),
        Step(
            id="FLOW-010.S09",
            kind=StepKind.VERIFY_CLI,
            text="Verify the EVPN MAC address-table starts empty",
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$",
            args=[evi],
            expect_key="FLOW010_S09_MAC_TABLE_EMPTY_LINES",
            expect_absent=True,
            req_ids=_R_BRINGUP,
            todo="Needs real `show evpn mac-address-table` output.",
        ),
        Step(
            id="FLOW-010.S10",
            kind=StepKind.VERIFY_ROUTE,
            text=f"Verify the Type-3 IMET route for this EVI is {_adv_phrase}",
            command=_adv_cmd,
            args=list(_adv_args),
            expect_key="FLOW010_S10_TYPE3_ADVERTISED_LINES",
            # The route table is not scoped to one route, and a capture is a
            # snapshot. This step is about the Type-3 IMET; freezing whatever
            # Type-2s were present when the capture was taken asserts MACs
            # this test never sources.
            expect_subject="Type=3",
            req_ids=_R_TYPE3,
            todo="Needs real output of the route table above.",
        ),
    ]
    if (core := lab.core_link) is not None:
        steps.append(Step(
            id="FLOW-010.S11",
            kind=StepKind.VERIFY_CLI,
            text=("Verify the BGP session to the peer carries the L2VPN EVPN "
                  "address family in its negotiated capabilities"),
            command="SHOW_BGP_NEIGHBOR_$_EVPN_CAPABILITY",
            args=[core.peer_ipv4],
            expect_key="FLOW010_S11_EVPN_CAPABILITY_LINES",
            req_ids=_R_BRINGUP,
            todo=("Needs a BGP session in Established state; the capabilities "
                  "block is absent while the peer is down."),
        ))
    return TestScript(
        flow_id="FLOW-010",
        class_name="TC01_EvpnVlanBasedBringUp",
        method_name="evpnVlanBasedBringUp",
        title="EVPN VLAN-based bring-up with three local ACs",
        summary=(
            "Configure a vlan-based EVI on the DUT, bind all three IXIA-backed "
            "access circuits, and confirm the service comes up and advertises "
            "its Type-3 IMET route. Prerequisite for TC02 and TC03. "
            + _peer_note(lab)
        ),
        steps=steps,
    )


def _requires_evi(flow: str, lab: LabProfile) -> list[Step]:
    """Create the EVI this test needs, rather than assume another test did.

    History, because the shape of this function is a correction of a
    correction.

    The service used to arrive with the bring-up configuration file, so no
    test had to think about it. Exaware rejected that on 2026-09-08 (E3,
    "TC01 seems to configure an already existing evpn service"), so it moved
    into TC01 - and TC02/TC03 were left asserting that TC01 had run.

    That assumption is false under their own framework, and the device said
    so on 2026-09-09: `CmpTestCase.initCmpTestCase` is an `@Before`, and
    `BringUp.bringUpSetupAndVerify` calls `loadConf()` unconditionally, so
    EVPN_Base.cfg is reloaded before EVERY test - in one JVM or three. TC02
    run after a green TC01 therefore failed with "The output of show evpn
    summary is not as expected. Missing lines: [evi-1]": bring-up had wiped
    the EVI that TC01 created, exactly as designed.

    So each test creates what it needs. That satisfies E3 (nothing the test
    claims to create is pre-loaded) and it makes each TC independently
    runnable, which is what a per-test bring-up requires. The steps are the
    same ones TC01 uses, from the same source, so the three cannot drift.
    """
    evi = lab.evi_name
    steps = [
        Step(
            id=f"{flow}.S00P",
            kind=StepKind.VERIFY_CLI,
            text=(f"Verify {evi} does not exist before this test creates it "
                  "(bring-up reloads the .cfg before every test)"),
            command="SHOW_EVPN_SUMMARY",
            args=[],
            expect_key=f"{flow.replace('-', '')}_S00P_EVI_ABSENT_LINES",
            expect_literal=[evi],
            expect_absent=True,
            req_ids=_R_BRINGUP,
        ),
        Step(
            id=f"{flow}.S00Q",
            kind=StepKind.CONFIG,
            text=f"Create EVPN instance {evi} with service-type vlan-based",
            command="CONFIGURE_L2_SERVICES_EVPN_$_SERVICE_TYPE_$",
            args=[evi, "vlan-based"],
            req_ids=_R_BRINGUP,
        ),
        Step(
            id=f"{flow}.S00R",
            kind=StepKind.CONFIG,
            text=f"Enable auto-discovery on {evi}",
            command="CONFIGURE_L2_SERVICES_EVPN_$_AUTO_DISCOVERY",
            args=[evi],
            req_ids=_R_BRINGUP,
        ),
        Step(
            id=f"{flow}.S00S",
            kind=StepKind.CONFIG,
            text=f"Set import-rt on {evi}",
            command="CONFIGURE_L2_SERVICES_EVPN_$_IMPORT_RT_$",
            args=[evi, "65000:1"],
            req_ids=_R_BRINGUP,
        ),
        Step(
            id=f"{flow}.S00T",
            kind=StepKind.CONFIG,
            text=f"Set export-rt on {evi}",
            command="CONFIGURE_L2_SERVICES_EVPN_$_EXPORT_RT_$",
            args=[evi, "65000:1"],
            req_ids=_R_BRINGUP,
        ),
    ]
    for i, ac in enumerate(lab.acs, start=1):
        steps.append(Step(
            id=f"{flow}.S00U{i}",
            kind=StepKind.CONFIG,
            text=f"Bind access circuit {ac.name} ({ac.ac_interface}) to {evi}",
            command="CONFIGURE_L2_SERVICES_EVPN_$_INTERFACE_$",
            args=[evi, ac.ac_interface],
            req_ids=_R_BRINGUP,
        ))
    steps.append(Step(
        id=f"{flow}.S00V",
        kind=StepKind.VERIFY_CLI,
        text=(f"Verify {evi} is up and all {len(lab.acs)} attachment "
              "circuits are bound before the test proper begins"),
        command="SHOW_EVPN_DETAIL",
        args=[],
        # Resolved on the device, not here: `ac.ac_interface` is the
        # profile's PLACEHOLDER, and the SUT rebinds it during bring-up.
        expect_expr=f'evpnUtils.eviBoundLines("{evi}")',
        req_ids=_R_BRINGUP,
    ))
    return steps


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
    _adv_cmd, _adv_args, _adv_phrase = _advertised(lab)
    steps = [
        *_requires_evi("FLOW-030", lab),
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
            # DEVICE-MEASURED, pc-3099 / chassis 10.1.70.108, 2026-09-09.
            #
            # The title says BROADCAST, not unknown-unicast, and that is not a
            # softening: this build reports "Unknown MAC Flooding: Disabled"
            # and offers no CLI to enable it, so an unknown-unicast frame is
            # taken by the port and dropped before the bridge domain. The
            # traffic items therefore carry a broadcast destination, and what
            # this step proves is BUM flooding, which is what _R_TYPE3 is
            # about.
            #
            # Rx = 2 x Tx is the assertion. AC2 and AC3 are two sub-interfaces
            # of the same vport, so a frame flooded to both is received twice
            # on the destination port. If the EVI stopped flooding to one of
            # them, this reads 1000 and the step fails.
            text=("Verify the broadcast from AC1 is flooded to BOTH AC2 and "
                  "AC3 (rx = 2x tx on the shared destination port)"),
            expect_key="FLOW030_S03_FLOOD_TO_AC2_AC3_ROWS",
            expect_rows=[
                ("TI_AC1_TO_AC2", "1000", "2000"),
                ("TI_AC2_TO_AC1", "0", "0"),
                ("TI_AC3_TO_AC1", "0", "0"),
            ],
            req_ids=_R_TYPE3,
        ),
        Step(
            id="FLOW-030.S04",
            kind=StepKind.VERIFY_CLI,
            text=f"Verify AC1 source MACs are learnt on {ac1.ac_interface}",
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$_SOURCE_$",
            args=[evi, ac1.ac_interface],
            expect_key="FLOW030_S04_AC1_MACS_LEARNT_LINES",
            req_ids=_R_TYPE2,
            todo="Needs real MAC-table output plus the AC1 source-MAC range.",
        ),
        Step(
            id="FLOW-030.S05",
            kind=StepKind.VERIFY_ROUTE,
            text=("Verify AC1 source MACs are emitted as Type-2 routes, "
                  f"{_adv_phrase}"),
            command=_adv_cmd,
            args=list(_adv_args),
            expect_key="FLOW030_S05_AC1_TYPE2_ADVERTISED_LINES",
            # AC1's MAC ONLY. At this step AC2 has not transmitted, so its
            # route is legitimately absent - pc-3099, 2026-09-09:
            #   Missing lines: [Type=2: VLAN-ID=0, MAC=00:00:02:00:00:01]
            expect_subject=lab.traffic_item("TI_AC1_TO_AC2").src_mac,
            req_ids=_R_TYPE2,
            todo="Needs real output of the route table above.",
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
            # This step used to claim "flooding to AC3 ceases once AC2's MACs
            # are known". It cannot: the frames are broadcast (see S03) and
            # broadcast is flooded whatever the MAC table says. The device was
            # unambiguous - AC1's rx stayed at 2000 through every later step.
            # Rather than leave a title that describes something the rig
            # cannot do, the step asserts what it genuinely establishes: AC2
            # now forwards to AC1, and AC1's flooding is unchanged.
            #
            # That the MAC was LEARNT is asserted, on the DUT, by S04/S09
            # (show evpn mac-address-table ... source) and S05/S10 (the Type-2
            # advertisement). Those are the right place for it.
            text=("Verify AC2 -> AC1 forwards once AC2's MACs are learnt, "
                  "while AC1's broadcast still reaches both ACs"),
            expect_key="FLOW030_S07_AC2_FORWARDS_ROWS",
            expect_rows=[
                ("TI_AC1_TO_AC2", "1000", "2000"),
                ("TI_AC2_TO_AC1", "1000", "1000"),
                ("TI_AC3_TO_AC1", "0", "0"),
            ],
            req_ids=_R_TYPE3,
        ),
        Step(
            id="FLOW-030.S08",
            kind=StepKind.VERIFY_CLI,
            text="Verify AC1 source MACs are still intact in the MAC table",
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$_SOURCE_$",
            args=[evi, ac1.ac_interface],
            expect_key="FLOW030_S04_AC1_MACS_LEARNT_LINES",
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S09",
            kind=StepKind.VERIFY_CLI,
            text=f"Verify AC2 source MACs are learnt on {ac2.ac_interface}",
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$_SOURCE_$",
            args=[evi, ac2.ac_interface],
            expect_key="FLOW030_S09_AC2_MACS_LEARNT_LINES",
            req_ids=_R_TYPE2,
            todo="Needs real MAC-table output plus the AC2 source-MAC range.",
        ),
        Step(
            id="FLOW-030.S10",
            kind=StepKind.VERIFY_ROUTE,
            text=("Verify AC2 source MACs are also emitted as Type-2 routes, "
                  f"{_adv_phrase}"),
            command=_adv_cmd,
            args=list(_adv_args),
            expect_key="FLOW030_S10_AC2_TYPE2_ADVERTISED_LINES",
            expect_subject=lab.traffic_item("TI_AC2_TO_AC1").src_mac,
            req_ids=_R_TYPE2,
            todo="Needs real output of the route table above.",
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
            # "still forwards to AC2 (no flooding)" was not observable either,
            # for the same reason as S07. What IS observable, and worth
            # asserting, is that stopping AC2's stream does not disturb AC1's:
            # a broken EVI would show AC1's rx collapsing here.
            text=("Verify AC1's traffic is unaffected by AC2's stream "
                  "stopping, and AC2 has indeed stopped"),
            expect_key="FLOW030_S12_AC1_UNAFFECTED_ROWS",
            expect_rows=[
                ("TI_AC1_TO_AC2", "1000", "2000"),
                ("TI_AC2_TO_AC1", "0", "0"),
                ("TI_AC3_TO_AC1", "0", "0"),
            ],
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S13",
            kind=StepKind.VERIFY_NO_EVENT,
            text=("Snapshot the advertised Type-2 routes before moving the "
                  "MACs to AC3"),
            command=_adv_cmd,
            args=list(_adv_args),
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
            text=f"Verify the AC2 MACs have shifted to {ac3.ac_interface}",
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$_SOURCE_$",
            args=[evi, ac3.ac_interface],
            expect_key="FLOW030_S15_MACS_MOVED_TO_AC3_LINES",
            req_ids=_R_TYPE2,
            todo="Needs real MAC-table output.",
        ),
        Step(
            id="FLOW-030.S16",
            kind=StepKind.VERIFY_NO_EVENT,
            text=("Verify NO new Type-2 was triggered by the local AC2 → AC3 "
                  "move (route table unchanged vs the snapshot)"),
            command=_adv_cmd,
            args=list(_adv_args),
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S17",
            kind=StepKind.VERIFY_IXIA,
            # "AC1 -> AC2 now forwards out AC3" is invisible to these
            # counters: AC2 and AC3 share a vport, so traffic leaving by
            # either lands in the same rx bucket. The MOVE is asserted on the
            # DUT by S15 (the MACs now show against AC3's sub-interface) and
            # S16 (no new Type-2 was triggered), which is where the evidence
            # actually is. Here we assert that AC3 is now the one sourcing,
            # and that the EVI kept forwarding throughout.
            text=("Verify AC3 now sources the moved MACs and AC1's traffic "
                  "keeps flowing throughout the move"),
            expect_key="FLOW030_S17_AC3_SOURCES_ROWS",
            expect_rows=[
                ("TI_AC1_TO_AC2", "1000", "2000"),
                ("TI_AC2_TO_AC1", "0", "0"),
                ("TI_AC3_TO_AC1", "1000", "1000"),
            ],
            req_ids=_R_TYPE2,
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
            "interface move updates forwarding WITHOUT re-advertising. "
            + _peer_note(lab)
        ),
        steps=steps,
        depends_on=["FLOW-010"],
    )


def _aging_source(lab: LabProfile) -> TrafficItem:
    """The traffic item whose MACs must age out for FLOW-031 to mean anything.

    FLOW-031 stops the traffic that is keeping MACs alive, waits out the aging
    time and asserts the entries leave. Which item that is depends on the rig,
    so it is resolved from the profile rather than named: the last item feeding
    AC1 is TI_AC3_TO_AC1 on the three-circuit topology and TI_AC2_TO_AC1 where
    one link has been spent on the EVPN core. Hard-coding it made the flow fail
    to compile against any profile but the first.
    """
    feeding_ac1 = [t for t in lab.traffic_items if t.dst == "AC1"]
    if not feeding_ac1:
        raise ValueError(
            f"lab profile {lab.id!r} has no traffic item terminating on AC1, "
            "so FLOW-031 has nothing whose MACs could age out")
    return feeding_ac1[-1]


def _type3(lab: LabProfile) -> TestScript:
    """FLOW-031 — BUM flooding and Type-2 withdrawal after MAC aging."""
    evi = lab.evi_name
    aging = _aging_source(lab)
    steps = [
        *_requires_evi("FLOW-031", lab),
        # Learn something before asserting it ages out.
        #
        # This flow used to go straight to "stop the traffic, wait, assert the
        # MACs are gone" from a prep that starts every item SUSPENDED. So
        # nothing was ever learnt, and every assertion below passed on an
        # empty MAC table: the aged-out check, the withdrawn-route check and
        # the flooding check were all trivially true. That is the fake-pass
        # rule (ate/codegen/fake_pass.py) in the one place it was not being
        # applied - a test that "passes" against a device doing nothing.
        #
        # NOT named S00*: _with_traffic_setup inserts the TRAFFIC_CREATE step
        # after the whole ".S00" block, so an S00 name here would use traffic
        # items before they exist.
        Step(
            id="FLOW-031.S01P",
            kind=StepKind.TRAFFIC_STATE,
            text=("Start AC1 and " + aging.src + " traffic so there are MACs "
                  "to age out"),
            traffic_items=["TI_AC1_TO_AC2", aging.name],
            enabled=True,
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-031.S01Q",
            kind=StepKind.VERIFY_CLI,
            text=(f"Verify the {aging.src} MACs ARE learnt before the aging "
                  "test begins"),
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$_SOURCE_$",
            args=[evi, lab.ac(aging.src).ac_interface],
            expect_key="FLOW031_S01Q_MACS_LEARNT_LINES",
            req_ids=_R_TYPE2,
            todo="Needs real MAC-table output for the aging source circuit.",
        ),
        Step(
            id="FLOW-031.S01",
            kind=StepKind.TRAFFIC_STATE,
            text=f"Stop traffic {aging.src} → {aging.dst}",
            traffic_items=[aging.name],
            enabled=False,
            req_ids=_R_TYPE3,
        ),
        Step(
            id="FLOW-031.S02",
            kind=StepKind.WAIT,
            text=(f"Wait out the {lab.mac_aging_seconds}s MAC aging time "
                  "(CLI doc default; range 0, 40-2400)"),
            seconds=lab.mac_aging_seconds,
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-031.S03",
            kind=StepKind.VERIFY_IXIA,
            # AC1's broadcast is still flooded to both circuits (rx = 2x tx)
            # while the aged circuit is silent. Measured on pc-3099,
            # 2026-09-09; see FLOW-030.S03 for why the traffic is broadcast
            # and why the shared destination port doubles the rx count.
            text=("Verify AC1's traffic still floods to BOTH AC2 and AC3 "
                  f"while {aging.src} stays silent after aging"),
            expect_key="FLOW031_S03_FLOOD_AFTER_AGING_ROWS",
            expect_rows=[
                ("TI_AC1_TO_AC2", "1000", "2000"),
                ("TI_AC2_TO_AC1", "0", "0"),
                ("TI_AC3_TO_AC1", "0", "0"),
            ],
            req_ids=_R_TYPE3,
        ),
        Step(
            id="FLOW-031.S04",
            kind=StepKind.VERIFY_CLI,
            text=(f"Verify the {aging.src} MACs are removed from the EVPN "
                  "MAC table once their traffic stopped and they aged out"),
            # Scoped to the circuit whose traffic was stopped, NOT the whole
            # table. Only one traffic item stops here; the others keep
            # refreshing their own MACs, so asserting the entire table empties
            # asserts something the flow never asked for and that the device
            # is right to refuse.
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$_SOURCE_$",
            args=[evi, lab.ac(aging.src).ac_interface],
            expect_key="FLOW031_S04_MACS_AGED_OUT_LINES",
            expect_absent=True,
            poll_key="AGING_VERIFY_TIMEOUT_IN_MSEC",
            req_ids=_R_TYPE2,
            todo="Needs real MAC-table output.",
        ),
        Step(
            id="FLOW-031.S05",
            kind=StepKind.VERIFY_ROUTE,
            text=("Verify the AC2 MACs' Type-2 routes are withdrawn from the "
                  "BGP table"),
            command="SHOW_BGP_L2VPN_EVPN_TABLE_EVI_DETAIL",
            args=[],
            expect_key="FLOW031_S05_TYPE2_WITHDRAWN_LINES",
            expect_absent=True,
            poll_key="AGING_VERIFY_TIMEOUT_IN_MSEC",
            # `show bgp l2vpn evpn table evi detail` is not scoped to a
            # circuit, and only THIS item's MACs stop being refreshed. AC1
            # keeps transmitting, so its Type-2 stays advertised and must.
            expect_subject=aging.src_mac,
            req_ids=_R_TYPE2,
            todo="Needs real BGP EVPN table output.",
        ),
        Step(
            id="FLOW-031.S06",
            kind=StepKind.VERIFY_CLI,
            text="Verify the BUM routing table still lists the flood list",
            command="SHOW_EVPN_BROADCAST_DOMAINS_NAME_$",
            args=[evi],
            expect_key="FLOW031_S06_BUM_BROADCAST_DOMAIN_LINES",
            req_ids=_R_TYPE3,
            todo=("Needs real `show evpn broadcast-domains` output with an EVI "
                  "configured; `show evpn bum routing-table` does not exist "
                  "on this build."),
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
            "entries, and their Type-2 routes are withdrawn. "
            + _peer_note(lab)
        ),
        steps=steps,
        depends_on=["FLOW-010", "FLOW-030"],
    )


def _with_traffic_setup(script: TestScript,
                        lab: LabProfile | None = None) -> TestScript:
    """Prepend a traffic-item build step to any script that uses traffic.

    `setTrafficItemState` unsuspends an item that must already exist. Their
    suites get those from a prebuilt .ixncfg; we build them over TCL, so the
    build has to happen before the first use or every traffic step is a no-op
    and every MAC-learning assertion silently sees zero.
    """
    uses_traffic = any(
        st.kind in (StepKind.TRAFFIC_STATE, StepKind.TRAFFIC_START,
                    StepKind.TRAFFIC_STOP, StepKind.VERIFY_IXIA)
        for st in script.steps)
    if not uses_traffic:
        return script
    setup = Step(
        id=f"{script.flow_id}.S00",
        kind=StepKind.TRAFFIC_CREATE,
        text=("Load the IXIA traffic items this test drives"
              if lab is not None and lab.ixncfg
              else "Build the IXIA traffic items this test drives"),
        req_ids=[],
        # No `todo` any more, and the two reasons it used to carry are both
        # closed:
        #
        #   * "the SOURCE MAC cannot be set from that library" - it can. The
        #     field is ethernet.header.sourceAddress-2, not -1; the suffix is
        #     a position in the stack, not a name. EvpnUtils sets it and reads
        #     it back, and TC02 passed on pc-3080 on 2026-08-14 because of it.
        #   * "built over TCL rather than loaded from an .ixncfg" - the items
        #     are still built in code by default, but the same build is now
        #     also emitted as a readable script
        #     (configurations/ixia/EVPN_traffic.tcl) which SAVES an .ixncfg.
        #     Run it once, name the file with --ixncfg, and this step loads
        #     rather than builds.
    )
    # After the prerequisite check, not before it. Building traffic items
    # takes chassis time, and if the EVI this test needs is not there the
    # honest answer is one failed assertion at the top rather than a minute
    # of setup followed by a table full of zeros.
    steps = list(script.steps)
    # After the whole EVI prerequisite block, not in the middle of it: the
    # circuits must be bound before any traffic item is built against them.
    at = 0
    while at < len(steps) and ".S00" in steps[at].id:
        at += 1
    steps.insert(at, setup)
    return script.model_copy(update={"steps": steps})


def _with_tester_protocols(script: TestScript, lab: LabProfile) -> TestScript:
    """Start the tester's emulated protocols before anything asserts on them.

    Only where there is a core link to run them on. On a profile with no core
    (`NoCore`) there are no tester protocols, and emitting the step would be a
    call that always finds nothing running - a red test for the rig's shape
    rather than for a defect.

    DEVICE-VERIFIED 2026-09-09: loading the `.ixncfg` restores OSPF, LDP and
    BGP but leaves them stopped, so without this step the DUT's neighbour
    stays in Active for the whole run and every control-plane expectation is
    captured against a session that never came up.
    """
    if lab.core_link is None:
        return script
    step = Step(
        id=f"{script.flow_id}.S00X",
        kind=StepKind.TESTER_PROTOCOLS,
        text=("Start the tester's OSPF, LDP and BGP and verify they are "
              "running"),
        req_ids=_R_BRINGUP,
    )
    steps = list(script.steps)
    at = 0
    while at < len(steps) and ".S00" in steps[at].id:
        at += 1
    steps.insert(at, step)
    return script.model_copy(update={"steps": steps})


def evpn_scripts(lab: LabProfile = SINGLE_DUT_3AC) -> list[TestScript]:
    """The M2 scripts, in dependency order.

    FLOW-030 is emitted only where the rig can carry it. Its whole premise is
    that AC2 and AC3 source identical MACs so traffic shifting between them is
    a purely local MAC move, and that needs a third attachment circuit. A
    profile that spends one of its three DUT<->IXIA links on the core (so that
    EVPN has a BGP session at all) has two, and the flow would otherwise fail
    at generation with a tuple-unpacking error.

    Dropping it is reported rather than silent: a suite that quietly generates
    fewer tests than the plan says is the same class of problem as a test that
    quietly asserts nothing.
    """
    scripts = [_bring_up(lab)]
    if len(lab.acs) >= 3:
        scripts.append(_type2(lab))
    scripts.append(_type3(lab))
    return [_with_tester_protocols(_with_traffic_setup(sc, lab), lab)
            for sc in scripts]


def skipped_flows(lab: LabProfile) -> list[str]:
    """Flows the plan defines that this rig cannot run, and why."""
    if len(lab.acs) >= 3:
        return []
    return [
        f"FLOW-030 (Type-2 MAC move): needs 3 attachment circuits, profile "
        f"{lab.id!r} has {len(lab.acs)} because one link is the EVPN core."
    ]

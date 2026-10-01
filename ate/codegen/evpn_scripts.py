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
    core = lab.core_link
    if (lab.peer_source is PeerSource.IXIA and core is not None
            and core.tester_evpn_capability):
        # What was SENT to the tester, read off the DUT. Possible since the
        # tester negotiates L2VPN EVPN (Eyal, 2026-10-01). Device-verified on
        # pc-3080 the same day: `show bgp l2vpn evpn neighbors advertised-routes
        # 29.31.31.31 detail` lists each Type-2 with its MAC Mobility SeqNum,
        # and the Type-3. Exaware, 2026-09-30, TC02 step 23: "the output is
        # not the advertised MAC, only the EVI MACs" - this is the advertised
        # MAC.
        return ("SHOW_BGP_L2VPN_EVPN_NEIGHBORS_ADVERTISED_ROUTES_$_DETAIL",
                [core.peer_loopback_ipv4],
                f"advertised to the tester {core.peer_loopback_ipv4}")
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
        if lab.core_link is not None and lab.core_link.tester_evpn_capability:
            return ("Advertisement is asserted against what the DUT SENT to "
                    "the IXIA peer, which negotiates L2VPN EVPN over a "
                    "loopback-to-loopback session carried by an LDP LSP. The "
                    "peer advertises no EVPN routes of its own: emulating "
                    "them needs a BGP EVPN licence chassis 10.1.70.108 does "
                    "not have (ERROR-1005).")
        return ("Advertisement is asserted against the local EVI table, which "
                "proves ORIGINATION but not transmission, because the tester "
                "does not negotiate L2VPN EVPN on this profile.")
    return ("Advertisement is asserted against the local EVI table, which "
            "proves ORIGINATION but not transmission, because this profile "
            "has no BGP peer at all. See LabProfile.core.")


def _rx(fps: int, copies: int) -> str:
    return str(fps * copies)


def _underlay_checks(flow: str, lab: LabProfile) -> list[Step]:
    """The DUT's own view of the control plane, before anything relies on it.

    Exaware, 2026-09-30 (Eyal Ozeri), TC01 "Step 2.5: Missing protocol
    verification on the DuT (show ospf nei, show ldp nei, show bgp nei)".
    The suite used to read the TESTER's running state and call that the
    underlay. A tester can report `started` into a link the DUT never formed
    an adjacency on - which is what happened for hours on 2026-08-13.

    Starting the tester's protocols is no longer a test step at all: it is
    `startProtocols` in the .crt's before-table, the VPLS suite's own idiom
    (Eyal: "Protocols should start at the 'do before' phase").

    The expected lines are generation-time literals, not captures: the peer's
    address and the state word are the whole assertion, and both are known
    here. Shapes device-verified on pc-3080, 2026-10-01:
        29.31.31.31  Full/ -  x-eth0/0/8  default/3029  29.60.0.2  0  37s
        29.60.0.2  Auto  Passive  Operational  27s
        29.31.31.31  up  3029  4  7  43s  IPv4u  0  0
    """
    core = lab.core_link
    if core is None:
        return []
    tag = flow.replace("-", "")
    peer_lo = core.peer_loopback_ipv4.replace(".", r"\.")
    peer_if = core.peer_ipv4.replace(".", r"\.")
    return [
        Step(
            id=f"{flow}.S00B",
            kind=StepKind.VERIFY_CLI,
            text=f"Verify OSPF adjacency to the tester ({core.peer_loopback_ipv4}) is Full",
            command="SHOW_OSPF_NEIGHBORS",
            expect_key=f"{tag}_S00B_OSPF_FULL_LINES",
            expect_literal=[peer_lo + r"\s+Full"],
            req_ids=_R_BRINGUP,
        ),
        Step(
            id=f"{flow}.S00C",
            kind=StepKind.VERIFY_CLI,
            text=f"Verify the LDP session to the tester ({core.peer_ipv4}) is Operational",
            command="SHOW_LDP_NEIGHBORS",
            expect_key=f"{tag}_S00C_LDP_OPERATIONAL_LINES",
            expect_literal=[peer_if + r"\s+.*Operational"],
            req_ids=_R_BRINGUP,
        ),
        Step(
            id=f"{flow}.S00D",
            kind=StepKind.VERIFY_CLI,
            text=(f"Verify the BGP session loopback to loopback "
                  f"({core.loopback_ipv4} - {core.peer_loopback_ipv4}) is up"),
            command="SHOW_BGP_NEIGHBORS",
            expect_key=f"{tag}_S00D_BGP_UP_LINES",
            expect_literal=[peer_lo + r"\s+up\s+" + str(lab.bgp_asn)],
            req_ids=_R_BRINGUP,
        ),
    ]


def _bring_up(lab: LabProfile) -> TestScript:
    """FLOW-010 - VLAN-based EVPN bring-up with three local ACs.

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
            # already existing evpn service." The service is created here and
            # nowhere else, and this step is what proves the starting point.
            command="SHOW_EVPN_SUMMARY",
            args=[],
            expect_key="FLOW010_S00A_EVI_ABSENT_LINES",
            expect_literal=[evi],
            expect_absent=True,
            req_ids=_R_BRINGUP,
        ),
        *_underlay_checks("FLOW-010", lab),
        Step(
            id="FLOW-010.S01",
            kind=StepKind.CONFIG,
            # ONE step and ONE commit for the whole service. Exaware,
            # 2026-09-30 (Eyal Ozeri), TC01 steps 3-8: "No need with 6 commits
            # to configure a service." Every line is still checked for
            # rejection, and the single commit must report a modification.
            text=(f"Create {evi} (vlan-based, import-rt and export-rt 65000:1, "
                  f"{len(lab.acs)} attachment circuits) in one commit"),
            command="CONFIGURE_L2_SERVICES_EVPN_$_SERVICE_TYPE_$",
            args=[evi, "vlan-based"],
            more=[
                ("CONFIGURE_L2_SERVICES_EVPN_$_IMPORT_RT_$", [evi, "65000:1"]),
                ("CONFIGURE_L2_SERVICES_EVPN_$_EXPORT_RT_$", [evi, "65000:1"]),
                *[("CONFIGURE_L2_SERVICES_EVPN_$_INTERFACE_$",
                   [evi, ac.ac_interface]) for ac in lab.acs],
            ],
            req_ids=_R_BRINGUP,
        ),
        Step(
            id="FLOW-010.S08",
            kind=StepKind.VERIFY_CLI,
            text=(f"Verify {evi} is up and all {len(lab.acs)} attachment "
                  "circuits are bound"),
            # Was a capture, and Eyal could not tell what it checked (TC01
            # step 9: "What is actually validated?"). Now the EVI name and
            # every circuit, resolved on the device, so the expected-vs-output
            # table names each one.
            command="SHOW_EVPN_DETAIL",
            args=[],
            expect_expr=f'evpnUtils.eviBoundLines("{evi}")',
            req_ids=_R_BRINGUP,
        ),
        Step(
            id="FLOW-010.S09",
            kind=StepKind.VERIFY_CLI,
            text="Verify the EVPN MAC address-table has no learnt MAC yet",
            # Absence of a MAC ROW, not of the table. Any learnt entry is a
            # line carrying a MAC address and a source circuit.
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$",
            args=[evi],
            expect_key="FLOW010_S09_MAC_TABLE_EMPTY_LINES",
            expect_literal=[r"([0-9a-f]{2}:){5}[0-9a-f]{2}\s+L\s"],
            expect_absent=True,
            req_ids=_R_BRINGUP,
        ),
        Step(
            id="FLOW-010.S10",
            kind=StepKind.VERIFY_ROUTE,
            text=f"Verify the DUT originates the Type-3 IMET route for {evi} ({_adv_phrase})",
            command=_adv_cmd,
            args=list(_adv_args),
            expect_key="FLOW010_S10_TYPE3_ADVERTISED_LINES",
            expect_literal=[r"Type=3:.*Originating Router's IP="
                            + (lab.core_link.loopback_ipv4.replace(".", r"\.")
                               if lab.core_link else "")],
            req_ids=_R_TYPE3,
        ),
    ]
    if (core := lab.core_link) is not None and core.tester_evpn_capability:
        # Both halves of the exchange. The old step passed on "L2VPN EVPN:
        # advertised", the DUT's half alone (Eyal, 2026-09-30, TC01 step 12:
        # "We only see that the DuT advertises, need to set evpn capability at
        # the Ixia"). The tester now advertises it, so the line must read
        # "advertised and received", and a peer without it fails this step.
        steps.append(Step(
            id="FLOW-010.S11",
            kind=StepKind.VERIFY_CLI,
            text=("Verify the BGP session to the tester negotiated L2VPN EVPN "
                  "(advertised and received)"),
            command="SHOW_BGP_NEIGHBOR_$_EVPN_CAPABILITY",
            args=[core.peer_loopback_ipv4],
            expect_key="FLOW010_S11_EVPN_CAPABILITY_LINES",
            expect_literal=[r"L2VPN EVPN:\s+advertised and received"],
            req_ids=_R_BRINGUP,
        ))
    return TestScript(
        flow_id="FLOW-010",
        class_name="TC01_EvpnVlanBasedBringUp",
        method_name="evpnVlanBasedBringUp",
        title="EVPN VLAN-based bring-up with three local ACs",
        summary=(
            "Check the underlay from the DUT, configure a vlan-based EVI with "
            "all three IXIA-backed access circuits in one commit, and confirm "
            "the service comes up and originates its Type-3 IMET route. "
            + _peer_note(lab)
        ),
        steps=steps,
    )


def _service_present(flow: str, lab: LabProfile) -> list[Step]:
    """Assert the EVI the bring-up configuration loaded is there and bound.

    Exaware, 2026-09-30 (Eyal Ozeri), TC02: "No need to load w/o evpn config.
    It is covered by TC01." TC02 and TC03 used to start from a device without
    the service and build it again, step by step - TC01's subject, repeated.
    They now load `EVPN_Service.cfg` at bring-up (per-test rows in
    bringUpParams.crt) and only check the result.
    """
    evi = lab.evi_name
    return [Step(
        id=f"{flow}.S00V",
        kind=StepKind.VERIFY_CLI,
        text=(f"Verify {evi} from the bring-up configuration is up with all "
              f"{len(lab.acs)} attachment circuits bound"),
        command="SHOW_EVPN_DETAIL",
        args=[],
        expect_expr=f'evpnUtils.eviBoundLines("{evi}")',
        req_ids=_R_BRINGUP,
    )]


def _traffic_check(sid: str, text: str, key: str,
                   rows: list[tuple[str, str, str]],
                   on: list[str], silent: list[str],
                   req: list[str]) -> Step:
    return Step(id=sid, kind=StepKind.VERIFY_IXIA, text=text, expect_key=key,
                expect_rows=rows, egress_on=on, egress_silent=silent,
                req_ids=req)


def _type2(lab: LabProfile) -> TestScript:
    """FLOW-030 - Type-2 MAC/IP origination, learning, known-unicast, local move.

    Rebuilt on 2026-10-01 for Exaware's TC02 review of 2026-09-30. The items
    are now KNOWN UNICAST (addressed to the other side's MAC) instead of
    broadcast, so forwarding can be seen to change when a MAC is learnt:
    flooded to AC2 and AC3 while AC2's MAC is unknown, delivered to AC2 alone
    once it is learnt, and to AC3 alone after the move. Which circuit the DUT
    sent it out of is read off the DUT's own sub-interface counters, because
    AC2 and AC3 share one IXIA port.

    Every expected rate below was measured on pc-3080 on 2026-10-01 with
    these exact items (evidence_loopback_and_unicast_pc3080.txt).
    """
    evi = lab.evi_name
    ac1, ac2, ac3 = lab.acs
    f = lab.traffic_rate_fps
    one, two = _rx(f, 1), _rx(f, 2)
    _adv_cmd, _adv_args, _adv_phrase = _advertised(lab)
    mac1 = lab.traffic_item("TI_AC1_TO_AC2").src_mac
    mac2 = lab.traffic_item("TI_AC2_TO_AC1").src_mac
    steps = [
        *_service_present("FLOW-030", lab),
        *_underlay_checks("FLOW-030", lab),
        Step(
            id="FLOW-030.S01",
            kind=StepKind.EXEC,
            text="Clear the EVPN MAC address-table so learning starts clean",
            command="CLEAR_EVPN_MAC_ADDRESS_TABLE_NAME_$",
            args=[evi],
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S02",
            kind=StepKind.TRAFFIC_STATE,
            text=f"Start traffic AC1 -> AC2 (unicast to {mac2}, not yet learnt)",
            traffic_items=["TI_AC1_TO_AC2"],
            enabled=True,
            req_ids=_R_TYPE2,
        ),
        _traffic_check(
            "FLOW-030.S03",
            ("Verify unknown unicast from AC1 is flooded to BOTH AC2 and AC3 "
             f"(rx {two} = 2 x tx; DUT transmits on both)"),
            "FLOW030_S03_UNKNOWN_UNICAST_FLOODED_ROWS",
            [("TI_AC1_TO_AC2", one, two), ("TI_AC2_TO_AC1", "0", "0"),
             ("TI_AC3_TO_AC1", "0", "0")],
            on=["AC2", "AC3"], silent=[], req=_R_TYPE3),
        Step(
            id="FLOW-030.S04",
            kind=StepKind.VERIFY_CLI,
            text=f"Verify {mac1} is learnt on AC1 (VLAN {lab.vlan_of(ac1)})",
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$_SOURCE_$",
            args=[evi, ac1.ac_interface],
            expect_key="FLOW030_S04_AC1_MACS_LEARNT_LINES",
            expect_literal=[mac1 + r"\s+L\s"],
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S05",
            kind=StepKind.VERIFY_ROUTE,
            text=f"Verify the DUT originates a Type-2 route for {mac1} ({_adv_phrase})",
            command=_adv_cmd,
            args=list(_adv_args),
            expect_key="FLOW030_S05_AC1_TYPE2_ADVERTISED_LINES",
            expect_literal=[r"Type=2:.*MAC=" + mac1],
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S06",
            kind=StepKind.TRAFFIC_STATE,
            text=f"Start traffic AC2 -> AC1 (AC2 sources {mac2})",
            traffic_items=["TI_AC2_TO_AC1"],
            enabled=True,
            req_ids=_R_TYPE2,
        ),
        _traffic_check(
            "FLOW-030.S07",
            (f"Verify AC1 -> AC2 is now KNOWN unicast: rx {one}, out of AC2 "
             "only, nothing to AC3"),
            # Eyal, 2026-09-30, TC02 step 17: "Tx==RX only because the
            # destination port has a single AC ... we're not really in a
            # 'known-unicast' traffic mode." Both halves are now asserted: the
            # rate drops from 2x to 1x, and the DUT's counters say WHICH
            # circuit carried it.
            "FLOW030_S07_KNOWN_UNICAST_ROWS",
            [("TI_AC1_TO_AC2", one, one), ("TI_AC2_TO_AC1", one, one),
             ("TI_AC3_TO_AC1", "0", "0")],
            on=["AC2"], silent=["AC3"], req=_R_TYPE2),
        Step(
            id="FLOW-030.S09",
            kind=StepKind.VERIFY_CLI,
            text=f"Verify {mac2} is learnt on AC2 (VLAN {lab.vlan_of(ac2)})",
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$_SOURCE_$",
            args=[evi, ac2.ac_interface],
            expect_key="FLOW030_S09_AC2_MACS_LEARNT_LINES",
            expect_literal=[mac2 + r"\s+L\s"],
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S10",
            kind=StepKind.VERIFY_ROUTE,
            text=f"Verify the DUT originates a Type-2 route for {mac2} ({_adv_phrase})",
            command=_adv_cmd,
            args=list(_adv_args),
            expect_key="FLOW030_S10_AC2_TYPE2_ADVERTISED_LINES",
            expect_literal=[r"Type=2:.*MAC=" + mac2],
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S13",
            kind=StepKind.VERIFY_NO_EVENT,
            text=(f"Snapshot the DUT's Type-2 route for {mac2} before moving "
                  "it to AC3"),
            command=_adv_cmd,
            args=list(_adv_args),
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S11",
            kind=StepKind.TRAFFIC_STATE,
            text="Stop traffic AC2 -> AC1",
            traffic_items=["TI_AC2_TO_AC1"],
            enabled=False,
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S14",
            kind=StepKind.TRAFFIC_STATE,
            text=(f"Start traffic AC3 -> AC1 (AC3 sources {mac2}, the same MAC "
                  "as AC2: a local MAC move)"),
            traffic_items=["TI_AC3_TO_AC1"],
            enabled=True,
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S15",
            kind=StepKind.VERIFY_CLI,
            text=f"Verify {mac2} has moved to AC3 (VLAN {lab.vlan_of(ac3)})",
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$_SOURCE_$",
            args=[evi, ac3.ac_interface],
            expect_key="FLOW030_S15_MACS_MOVED_TO_AC3_LINES",
            expect_literal=[mac2 + r"\s+L\s"],
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S16",
            kind=StepKind.VERIFY_NO_EVENT,
            text=(f"Verify the local AC2 -> AC3 move did not re-originate the "
                  f"Type-2 route for {mac2} (route unchanged vs the snapshot)"),
            command=_adv_cmd,
            args=list(_adv_args),
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-030.S16B",
            kind=StepKind.VERIFY_ROUTE,
            text=(f"Verify the Type-2 for {mac2} still carries MAC Mobility "
                  f"SeqNum=0 after the local move ({_adv_phrase})"),
            # A move between two circuits of the SAME PE is not mobility in
            # the RFC 7432 sense: the sequence number must not be bumped.
            # Read off the advertised route itself, so a re-advertisement with
            # SeqNum=1 fails here even if the snapshot compare were blind to it.
            command=_adv_cmd,
            args=list(_adv_args),
            expect_key="FLOW030_S16B_SEQNUM_UNCHANGED_LINES",
            # Within THIS route's block only: never across the next "Type=".
            expect_literal=[r"MAC=" + mac2 + r"(?:(?!Type=)[\s\S])*?SeqNum=0\b"]
            if "ADVERTISED" in _adv_cmd
            else [r"MAC=" + mac2 + r"(?:(?!Type=)[\s\S])*?Sequence Number: 0\b"],
            req_ids=_R_TYPE2,
        ),
        _traffic_check(
            "FLOW-030.S17",
            (f"Verify AC1 -> AC2 now follows the MAC: rx {one}, out of AC3 "
             "only, nothing to AC2"),
            # Eyal, 2026-09-30, TC02 step 27: "Traffic is flooded although it
            # shouldn't be ... wrongfully expects 2000 pps instead of 1000.
            # Also, there's no validation that the traffic is directed to the
            # correct AC." Both fixed: 1000, and AC3 transmits while AC2 is
            # silent.
            "FLOW030_S17_FOLLOWS_MOVE_ROWS",
            [("TI_AC1_TO_AC2", one, one), ("TI_AC2_TO_AC1", "0", "0"),
             ("TI_AC3_TO_AC1", one, one)],
            on=["AC3"], silent=["AC2"], req=_R_TYPE2),
    ]
    return TestScript(
        flow_id="FLOW-030",
        class_name="TC02_EvpnType2MacIpAdvertisement",
        method_name="evpnType2MacIpAdvertisement",
        title="EVPN Type-2 MAC learning, known-unicast forwarding and local MAC move",
        summary=(
            "Unknown unicast from AC1 floods to AC2 and AC3; once AC2's MAC is "
            "learnt the same traffic goes to AC2 alone; after AC3 takes over "
            "the MAC it goes to AC3 alone, and the purely local move does not "
            "re-originate the Type-2 route. "
            + _peer_note(lab)
        ),
        steps=steps,
        depends_on=["FLOW-010"],
    )


def _type3(lab: LabProfile) -> TestScript:
    """FLOW-031 - MAC aging: the learnt MAC leaves, and forwarding goes back to flooding.

    Exaware, 2026-09-30 (Eyal Ozeri), TC03: "As it uses the same settings
    which doesn't support learned traffic forwarding, there's no meaning to an
    ageing test." True of broadcast items: nothing about forwarding changed
    when a MAC aged. With known-unicast items it does, and that is what this
    test now asserts - unicast to AC2's MAC reaches AC2 alone while it is
    learnt, and is flooded to AC2 AND AC3 again once it has aged out.

    And "Step 17: AC2 traffic didn't start ... What exist in the table is
    AC1's MAC." The aging subject was resolved to AC3 while the titles said
    AC2. It is AC2 now, by name, everywhere.

    Aging is shortened to 60 s by the test itself (a real configuration step
    that can fail); measured on pc-3080 on 2026-10-01 the entry left the table
    50 to 70 s after the last frame.
    """
    evi = lab.evi_name
    ac2 = lab.ac("AC2")
    f = lab.traffic_rate_fps
    one, two = _rx(f, 1), _rx(f, 2)
    mac2 = lab.traffic_item("TI_AC2_TO_AC1").src_mac
    aging = lab.mac_aging_seconds
    _adv_cmd, _adv_args, _adv_phrase = _advertised(lab)
    steps = [
        *_service_present("FLOW-031", lab),
        *_underlay_checks("FLOW-031", lab),
        Step(
            id="FLOW-031.S01A",
            kind=StepKind.CONFIG,
            text=f"Set mac-aging-time {aging} on {evi}",
            command="CONFIGURE_L2_SERVICES_EVPN_$_MAC_AGING_TIME_$",
            args=[evi, str(aging)],
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-031.S01P",
            kind=StepKind.TRAFFIC_STATE,
            text=f"Start traffic AC1 -> AC2 and AC2 -> AC1 so {mac2} is learnt on AC2",
            traffic_items=["TI_AC1_TO_AC2", "TI_AC2_TO_AC1"],
            enabled=True,
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-031.S01Q",
            kind=StepKind.VERIFY_CLI,
            text=f"Verify {mac2} is learnt on AC2 before the aging test begins",
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$_SOURCE_$",
            args=[evi, ac2.ac_interface],
            expect_key="FLOW031_S01Q_MACS_LEARNT_LINES",
            expect_literal=[mac2 + r"\s+L\s"],
            req_ids=_R_TYPE2,
        ),
        _traffic_check(
            "FLOW-031.S01R",
            f"Verify AC1 -> AC2 is known unicast while {mac2} is learnt: rx {one}, AC2 only",
            "FLOW031_S01R_KNOWN_UNICAST_ROWS",
            [("TI_AC1_TO_AC2", one, one), ("TI_AC2_TO_AC1", one, one),
             ("TI_AC3_TO_AC1", "0", "0")],
            on=["AC2"], silent=["AC3"], req=_R_TYPE2),
        Step(
            id="FLOW-031.S01S",
            kind=StepKind.VERIFY_ROUTE,
            # S05 asserts this route withdrawn. Without proving it was there
            # first, S05 also passes on a DUT that never originated it
            # (domain_review: absence-without-prior-presence).
            text=f"Verify the DUT originates a Type-2 route for {mac2} before it ages ({_adv_phrase})",
            command=_adv_cmd,
            args=list(_adv_args),
            expect_key="FLOW031_S01S_TYPE2_ADVERTISED_LINES",
            expect_literal=[r"Type=2:.*MAC=" + mac2],
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-031.S01",
            kind=StepKind.TRAFFIC_STATE,
            text="Stop traffic AC2 -> AC1, so nothing refreshes its MAC",
            traffic_items=["TI_AC2_TO_AC1"],
            enabled=False,
            req_ids=_R_TYPE3,
        ),
        Step(
            id="FLOW-031.S02",
            kind=StepKind.WAIT,
            text=f"Wait out the {aging} s MAC aging time",
            seconds=aging,
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-031.S04",
            kind=StepKind.VERIFY_CLI,
            text=f"Verify {mac2} has aged out of the EVPN MAC table",
            command="SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$",
            args=[evi],
            expect_key="FLOW031_S04_MACS_AGED_OUT_LINES",
            expect_literal=[mac2],
            expect_absent=True,
            poll_key="AGING_VERIFY_TIMEOUT_IN_MSEC",
            req_ids=_R_TYPE2,
        ),
        Step(
            id="FLOW-031.S05",
            kind=StepKind.VERIFY_ROUTE,
            text=f"Verify the Type-2 route for {mac2} is withdrawn ({_adv_phrase})",
            command=_adv_cmd,
            args=list(_adv_args),
            expect_key="FLOW031_S05_TYPE2_WITHDRAWN_LINES",
            expect_literal=[r"Type=2:.*MAC=" + mac2],
            expect_absent=True,
            poll_key="AGING_VERIFY_TIMEOUT_IN_MSEC",
            req_ids=_R_TYPE2,
        ),
        _traffic_check(
            "FLOW-031.S03",
            (f"Verify AC1 -> AC2 is flooded again now {mac2} is unknown: "
             f"rx {two}, out of AC2 AND AC3"),
            "FLOW031_S03_FLOODED_AFTER_AGING_ROWS",
            [("TI_AC1_TO_AC2", one, two), ("TI_AC2_TO_AC1", "0", "0"),
             ("TI_AC3_TO_AC1", "0", "0")],
            on=["AC2", "AC3"], silent=[], req=_R_TYPE3),
        Step(
            id="FLOW-031.S06",
            kind=StepKind.VERIFY_CLI,
            text=f"Verify the broadcast domain still lists all {len(lab.acs)} circuits as flood targets",
            command="SHOW_EVPN_BROADCAST_DOMAINS_NAME_$",
            args=[evi],
            expect_expr=f'evpnUtils.eviBoundLines("{evi}")',
            req_ids=_R_TYPE3,
        ),
    ]
    return TestScript(
        flow_id="FLOW-031",
        class_name="TC03_EvpnType3ImetFlooding",
        method_name="evpnType3ImetFlooding",
        title="EVPN MAC aging: Type-2 withdrawal and return to flooding",
        summary=(
            "Learn AC2's MAC and show AC1's unicast to it reaches AC2 alone; "
            "stop AC2, let the MAC age out, and confirm the entry and its "
            "Type-2 route are gone and the same unicast is flooded to AC2 and "
            "AC3 again. "
            + _peer_note(lab)
        ),
        steps=steps,
        depends_on=["FLOW-010"],
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
        # TC03 now asserts that unicast to AC2's MAC is delivered to AC2 alone
        # and flooded to AC2 AND AC3 once it ages out, so it needs the same
        # third circuit TC02 does.
        scripts.append(_type2(lab))
        scripts.append(_type3(lab))
    return [_with_traffic_setup(sc, lab) for sc in scripts]


def skipped_flows(lab: LabProfile) -> list[str]:
    """Flows the plan defines that this rig cannot run, and why."""
    if len(lab.acs) >= 3:
        return []
    return [
        f"FLOW-030 (Type-2 MAC move): needs 3 attachment circuits, profile "
        f"{lab.id!r} has {len(lab.acs)} because one link is the EVPN core.",
        f"FLOW-031 (MAC aging): asserts the return to flooding across two "
        f"other circuits, so it needs 3 as well; {lab.id!r} has {len(lab.acs)}.",
    ]

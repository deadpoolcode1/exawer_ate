"""Lab topology profile — one DUT, three IXIA-attached ACs.

The M1 flow catalog assumes rigs the Exaware lab does not have: FLOW-010's
setup says "Two-PE topology over MPLS", FLOW-031 says "Three-PE EVPN (PE1, PE2,
PE3)". The M2 automation target (Eyal, 2026-08) is a **single DUT with three
IXIA ports**, all three attached as local ACs on the same EVI:

      ┌─────────── IXIA (ixia1) ───────────┐
      │  vport1        vport2      vport3  │
      └────┬─────────────┬───────────┬─────┘
           │ AC1         │ AC2       │ AC3          AC2 and AC3 deliberately
      ┌────┴─────────────┴───────────┴─────┐        source the SAME MACs, so
      │            DUT (cmp1)              │        moving traffic AC2→AC3 is
      │        l2-services evpn EVI        │        a pure local MAC move.
      └──────────────┬─────────────────────┘
                     │ BGP EVPN session
                  remote PE

Keeping this in one place matters because the same three flows must still be
renderable against the spec-complete two/three-PE topology for the reviewed
test plan. The lab profile is a *binding*, not a rewrite of the flow.

Every value here is a placeholder that the JSystem SUT file overrides at run
time (`ISuiteParams.getSuiteParamsTableToUpdate()` exists precisely to swap
interface names and VLAN IDs in from the SUT). They are named, not inlined,
so a lab change is a one-line edit rather than a regeneration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class AccessCircuit:
    """One IXIA port attached to the DUT as an EVPN attachment circuit."""

    name: str          # logical name used in step text and Java constants
    interface: str     # DUT PORT the circuit lives on (physical or aggregate)
    vport: str         # IXIA vport backing it
    #: Sub-interface number the attachment circuit is created as.
    #:
    #: A VLAN-based EVPN service will NOT accept a physical port. The device
    #: says so in as many words, on 8.7.0 LAB 22 (pc-3080), when the bring-up
    #: config is committed:
    #:
    #:     Aborted: 'l2-services evpn evi-1 interface x-eth 0/0/8': failed,
    #:     interface x-eth/agg-eth 0/0/8 is not a sub-interface, but the EVPN
    #:     service-type is vlan-based.
    #:
    #: Neither the SFS nor the CLI doc says this; the commit does. `100`
    #: follows the numbering Exaware's own VPLS suite uses for l2-transport
    #: circuits (`int2.100`, `int2.101`, ... in VPLS_N1.cfg).
    subinterface: int = 100
    #: Which `intN` placeholder and SUT intPool index this circuit takes.
    #:
    #: `None` means "position in `LabProfile.acs`", which is what every profile
    #: did while all three ports were attachment circuits. A rig that spends a
    #: port on the core link needs the ACs to start at the next index instead,
    #: so it sets this explicitly rather than relying on list order.
    int_index: int | None = None

    @property
    def ac_interface(self) -> str:
        """What the EVI actually binds — always the sub-interface."""
        return f"{self.interface}.{self.subinterface}"


@dataclass(frozen=True)
class TrafficItem:
    """A named IXIA traffic item.

    Their suites load traffic items from a prebuilt `.ixncfg` and only
    suspend/unsuspend them. We cannot synthesise that binary, so the generator
    **builds the items over TCL instead**, via
    `IxiaFunctions.CONFIGURE_NEW_TRAFFIC_ITEM` and friends. Same objects on the
    chassis, no binary required, and the suite no longer depends on a file
    somebody has to hand us.

    `src_mac` is the point of the whole exercise for FLOW-030: AC2 and AC3
    deliberately source the SAME MACs, so moving traffic from one to the other
    is a pure local MAC move on one PE — which per Eyal's 2026-07-06
    annotation must NOT re-advertise a Type-2 route.
    """

    name: str
    src: str           # AccessCircuit.name
    dst: str
    src_mac: str = "00:00:01:00:00:01"


class PeerSource(str, Enum):
    """Where the BGP EVPN session that carries Type-2/Type-3 routes comes from.

    All three IXIA ports are attachment circuits, so the peer cannot be one of
    them. Rather than block on the answer, the generator supports every option
    and adjusts *how* it asserts advertisement:

      * `NEIGHBOUR` — a peer exists (emulated, a fourth port, a real PE, or a
        software speaker on `DevicesSut.LINUX1`). Advertisement is asserted
        with `show bgp l2vpn evpn neighbors advertised-routes <peer> detail`.
      * `NONE` — no peer is wired. Advertisement is asserted against the
        local EVI table instead, with `show bgp l2vpn evpn table evi <name>
        detail`, which lists the routes this PE originates without needing
        anybody to receive them.

    The `NONE` path is weaker — it proves origination, not transmission — but
    it is a real assertion, it needs no lab change, and every other step in the
    suite is unaffected. Default is `NONE` so the suite runs on the rig as
    described; flip to `NEIGHBOUR` the moment a peer exists.
    """

    NEIGHBOUR = "neighbour"
    NONE = "none"
    #: The peer is an IXIA-emulated BGP EVPN speaker on a dedicated vport.
    #:
    #: This was long recorded as impossible here on two counts, and BOTH were
    #: wrong. The rig was believed to have no peer available, and IxNetwork was
    #: believed too old to emulate one. Read off the chassis on 2026-08-13:
    #:
    #:   * the IxNetwork API server answers `getVersion` = **9.00.1915.16**.
    #:     Only the *client* TCL library is pinned at 6.30 in the SUT file, and
    #:     that is what the "6.30 is too old for EVPN" reading came from;
    #:   * `/vport/protocols/bgp/neighborRange` carries `-evpn` and
    #:     `-evpnNextHopCount`, with a full object tree beneath it:
    #:     `ethernetSegments` -> `evi` -> `broadcastDomains` -> `cMacRange`,
    #:     plus `-eVpnAfi` / `-eVpnSafi` and the MAC-mobility extended
    #:     community on the parent `bgp` node.
    #:
    #: So Type-2 and Type-3 advertisement and withdrawal are testable on this
    #: testbed, with no dependency on Exaware and no `.ixncfg` from anybody.
    IXIA = "ixia"


@dataclass(frozen=True)
class CoreLink:
    """The DUT<->IXIA link that carries the overlay, not client traffic.

    Ilan, 2026-08-13: "we use ixia as end point as client traffic and also as
    remote router". Those are two different jobs on two different ports, and
    nothing in the generator modelled the second one — every vport was wired as
    an attachment circuit, so the suite had no core side at all.

    A vport cannot do both. A raw traffic item's endpoint is only accepted in
    the `/vport:N/protocols` form when the vport has EXACTLY ONE interface with
    a VLAN on it; giving a vport a second, L3 interface for BGP breaks that and
    the chassis answers ERROR-6301. So the core takes a port of its own.
    """

    #: Placeholder written into the `.cfg`, bound by `bringUpParams.crt`.
    interface: str = "int1"
    vport: str = "vport1"
    #: Index into the SUT intPool backing the link.
    pool_index: int = 0
    #: DUT side of the point-to-point link, and the IXIA side facing it.
    dut_ipv4: str = "29.60.0.1"
    peer_ipv4: str = "29.60.0.2"
    prefix_len: int = 24
    #: The DUT's own router ID / LDP transport address.
    loopback_ipv4: str = "29.30.30.30"
    loopback_id: int = 0
    #: Routed protocols the DUT runs ACROSS this link.
    #:
    #: Every one of these needs something at the other end to talk to. Naming
    #: them here is what lets `underlay_symmetry_violations` check that the
    #: tester side was configured to match, instead of the mismatch showing up
    #: as an adjacency that silently never forms.
    #:
    #: This list is the fix for a real miss: the generator emitted OSPF, LDP
    #: and BGP on the DUT and nothing at all for the IXIA, so the DUT was
    #: speaking three protocols into a port configured for none of them.
    #: `show ospf neighbor` answered "No entries found" for hours and that
    #: read as "not wired up yet" rather than as a defect (Exaware, 2026-08-14:
    #: "you configured ospf on the device, but not on the Ixia").
    dut_protocols: tuple[str, ...] = ("ospf", "ldp", "bgp")
    #: Protocols the tester emulates back. Generation fails if this does not
    #: cover `dut_protocols`.
    tester_protocols: tuple[str, ...] = ("ospf", "ldp", "bgp")


@dataclass(frozen=True)
class LabProfile:
    id: str
    description: str
    dut: str                              # DevicesSut constant
    ixia: str                             # DevicesSut constant
    evi_name: str
    acs: list[AccessCircuit]
    traffic_items: list[TrafficItem]
    bgp_neighbor: str
    peer_source: PeerSource = PeerSource.NONE
    #: intPool in the SUT file that backs the attachment circuits. The `.cfg`
    #: binds its `int1`/`int2`/`int3` placeholders to it through
    #: `bringUpParams.crt`, and the Java resolves interface names from it at
    #: run time, so one suite runs on any testbed rather than on the one whose
    #: interface names happened to be written into the profile.
    ac_pool: str = "data1"
    #: Index into the SUT's `general/vlans` list for the VLAN the attachment
    #: circuits carry. The DUT sub-interface and the IXIA vport are both bound
    #: to it, from the SUT, so the two sides cannot drift apart.
    ac_vlan_index: int = 0
    #: The core link, when this rig has one. `None` means every vport is an
    #: attachment circuit and the suite has no overlay side — which is the
    #: state that made EVPN unable to come up at all.
    core: CoreLink | None = None
    #: Autonomous system for the IGP and BGP processes. 3029 follows the
    #: number Exaware's own VPLS suite uses on this testbed (`routing ospf
    #: 3029` / `routing bgp 3029` in VPLS_N1.cfg), so the config reads the
    #: same as the ones their QA already runs.
    bgp_asn: int = 3029
    #: OSPF area for the core link and the loopback.
    igp_area: str = "0.0.0.0"
    #: Seconds to wait for MAC aging.
    #:
    #: Grounded, not guessed: the EVPN CLI doc's `mac-aging-time` parameter
    #: table gives range `0, 40-2400` (0 disables aging) and states "The
    #: default value is 300 second". Its Notes cell adds that Jerico1 devices
    #: support only the subset `0, 100-600` — so a Jerico1 rig must override
    #: this, and `MAC_AGING_MAX_JERICHO1` below is the ceiling to stay under.
    mac_aging_seconds: int = 300
    #: Documented aging bounds, carried through so a reviewer sees why the
    #: value above is legal and what a platform override may not exceed.
    mac_aging_min: int = 40
    mac_aging_max: int = 2400
    mac_aging_max_jericho1: int = 600
    #: Poll budget for "show" assertions, mirroring ShowVplsDetail's 30 s / 5 s.
    verify_timeout_ms: int = 30000
    verify_interval_ms: int = 5000
    notes: list[str] = field(default_factory=list)

    @property
    def asserts_advertisement_via_peer(self) -> bool:
        return self.peer_source is PeerSource.NEIGHBOUR

    def ac(self, name: str) -> AccessCircuit:
        for a in self.acs:
            if a.name == name:
                return a
        raise KeyError(f"no AC named {name!r} in lab profile {self.id}")

    def traffic_item(self, name: str) -> TrafficItem:
        for t in self.traffic_items:
            if t.name == name:
                return t
        raise KeyError(f"no traffic item {name!r} in lab profile {self.id}")


AC1 = AccessCircuit(name="AC1", interface="agg-eth-1", vport="vport1")
AC2 = AccessCircuit(name="AC2", interface="agg-eth-2", vport="vport2")
AC3 = AccessCircuit(name="AC3", interface="agg-eth-3", vport="vport3")

TI_AC1_TO_AC2 = TrafficItem(name="TI_AC1_TO_AC2", src="AC1", dst="AC2",
                            src_mac="00:00:01:00:00:01")
# AC2 and AC3 share a source MAC on purpose — that is what makes
# AC2 -> AC3 a local move rather than two distinct hosts.
TI_AC2_TO_AC1 = TrafficItem(name="TI_AC2_TO_AC1", src="AC2", dst="AC1",
                            src_mac="00:00:02:00:00:01")
TI_AC3_TO_AC1 = TrafficItem(name="TI_AC3_TO_AC1", src="AC3", dst="AC1",
                            src_mac="00:00:02:00:00:01")

SINGLE_DUT_3AC = LabProfile(
    id="lab-1dut-3ac",
    description=(
        "Single DUT, three IXIA ports as local ACs on one EVI, plus a BGP "
        "EVPN session to a remote PE. AC2 and AC3 source identical MACs so "
        "that shifting traffic from AC2 to AC3 is a purely local MAC move."
    ),
    dut="CMP1",
    ixia="IXIA1",
    evi_name="evi-1",
    acs=[AC1, AC2, AC3],
    traffic_items=[TI_AC1_TO_AC2, TI_AC2_TO_AC1, TI_AC3_TO_AC1],
    bgp_neighbor="PE2",
    notes=[
        "AC2 and AC3 must source identical MAC addresses — the whole MAC-move "
        "half of FLOW-030 depends on it. Items are referenced by name, so "
        "either a prebuilt .ixncfg or a code-built set via "
        "IxiaFunctions.CONFIGURE_NEW_TRAFFIC_ITEM satisfies the suite.",
        "peer_source defaults to NONE: no BGP EVPN peer is assumed, and "
        "advertisement is asserted against the local EVI table. Set "
        "PeerSource.NEIGHBOUR once a peer exists (fourth port, emulated peer, "
        "real PE, or a software speaker on DevicesSut.LINUX1) to assert "
        "transmission rather than origination.",
    ],
)

def underlay_symmetry_violations(lab: LabProfile) -> list[str]:
    """Protocols the DUT runs across the core link with nobody to talk to.

    A one-sided underlay is invisible at generation time and nearly invisible
    at run time: the DUT comes up, the config commits, every `show` command
    answers, and the only symptom is an adjacency that never forms — which
    reads as "not wired up yet" rather than as a defect. This is the same
    class as a test that asserts nothing: it looks like it works.

    So the asymmetry is made a generation-time error, where it is cheap.
    """
    if lab.core is None:
        return []
    missing = [p for p in lab.core.dut_protocols
               if p not in lab.core.tester_protocols]
    return [
        f"the DUT runs {p!r} across the core link but the tester emulates no "
        f"{p!r} peer, so that adjacency can never form"
        for p in missing
    ]


# ---------------------------------------------------------------------------
# The rig as it is actually cabled, as opposed to the topology the flows assume.
# ---------------------------------------------------------------------------

CORE_AC1 = AccessCircuit(name="AC1", interface="agg-eth-2", vport="vport2",
                         int_index=2)
CORE_AC2 = AccessCircuit(name="AC2", interface="agg-eth-3", vport="vport3",
                         int_index=3)

TI_CORE_AC1_TO_AC2 = TrafficItem(name="TI_AC1_TO_AC2", src="AC1", dst="AC2",
                                 src_mac="00:00:01:00:00:01")
TI_CORE_AC2_TO_AC1 = TrafficItem(name="TI_AC2_TO_AC1", src="AC2", dst="AC1",
                                 src_mac="00:00:02:00:00:01")

SINGLE_DUT_2AC_CORE = LabProfile(
    id="lab-1dut-2ac-core",
    description=(
        "Single DUT on pc-3080. IXIA vport1 is the core: an emulated BGP EVPN "
        "peer over a point-to-point L3 link. vport2 and vport3 stay client "
        "attachment circuits on the EVI. This is the testbed as cabled."
    ),
    dut="CMP1",
    ixia="IXIA1",
    evi_name="evi-1",
    acs=[CORE_AC1, CORE_AC2],
    traffic_items=[TI_CORE_AC1_TO_AC2, TI_CORE_AC2_TO_AC1],
    bgp_neighbor="PE2",
    peer_source=PeerSource.IXIA,
    core=CoreLink(),
    notes=[
        "TWO attachment circuits, not three, and that is a property of the "
        "rig rather than a simplification. pc-3080's data1 pool has exactly "
        "three DUT<->IXIA links (x-eth 0/0/8, 0/0/18, 0/0/26). Spending one "
        "on the core leaves two. Verified 2026-08-13 that there is no fourth: "
        "the SUT's IXIA pool lists a vport4 on card 1/1, but of the DUT ports "
        "that could face it only x-eth 0/0/4 comes up, and it receives "
        "multicast only at ~840 bps - a lab switch on the control network, "
        "not an IXIA port.",
        "FLOW-030's MAC move needs a third AC and so cannot run against this "
        "profile. SINGLE_DUT_3AC keeps the spec topology for the reviewed "
        "test plan; this profile is the binding for what actually runs.",
        "The peer is IXIA itself (PeerSource.IXIA), so Type-2/Type-3 "
        "advertisement and withdrawal are assertable here without a second "
        "physical PE.",
    ],
)

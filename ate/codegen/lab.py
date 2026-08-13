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

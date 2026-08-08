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


@dataclass(frozen=True)
class AccessCircuit:
    """One IXIA port attached to the DUT as an EVPN attachment circuit."""

    name: str          # logical name used in step text and Java constants
    interface: str     # DUT interface the AC binds to
    vport: str         # IXIA vport backing it


@dataclass(frozen=True)
class TrafficItem:
    """A named IXIA traffic item.

    Traffic items are **pre-built in the `.ixncfg`** loaded onto the chassis
    (this is how `cmp/tests/vpls` works — tests suspend/unsuspend items rather
    than constructing them). The generated code therefore references items by
    name; it does not create them. `IxiaFunctions.CONFIGURE_NEW_TRAFFIC_ITEM`
    does exist if Exaware would rather have them built in code.
    """

    name: str
    src: str           # AccessCircuit.name
    dst: str


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
    #: Seconds to wait for MAC aging. Placeholder until Exaware confirm the
    #: EVPN default — the VPLS suite treats this as a tuned per-platform value
    #: with a large deviation window, and EVPN will need the same.
    mac_aging_seconds: int = 300
    #: Poll budget for "show" assertions, mirroring ShowVplsDetail's 30 s / 5 s.
    verify_timeout_ms: int = 30000
    verify_interval_ms: int = 5000
    notes: list[str] = field(default_factory=list)

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

TI_AC1_TO_AC2 = TrafficItem(name="TI_AC1_TO_AC2", src="AC1", dst="AC2")
TI_AC2_TO_AC1 = TrafficItem(name="TI_AC2_TO_AC1", src="AC2", dst="AC1")
TI_AC3_TO_AC1 = TrafficItem(name="TI_AC3_TO_AC1", src="AC3", dst="AC1")

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
        "AC2 and AC3 MUST be configured in the .ixncfg with identical source "
        "MAC addresses — the whole MAC-move half of FLOW-030 depends on it.",
        "The BGP EVPN neighbor is NOT one of the three IXIA ports. It needs "
        "either a fourth port, an IXIA-emulated peer, or a real remote PE; "
        "'verify Type-2 advertised' reads "
        "`show bgp l2vpn evpn neighbors advertised-routes`, which requires a "
        "peer to exist. OPEN QUESTION for Exaware.",
    ],
)

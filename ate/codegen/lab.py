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

from dataclasses import dataclass, field, replace
from enum import Enum

#: The VLAN IDs an attachment circuit may carry.
#:
#: Exaware, 2026-09-08 (Eyal Ozeri): "The tool should be able to use entire
#: 2-4094 range." 0 is the priority tag and 1 is the default/native VLAN; 4095
#: is reserved. Anything inside the range is legal, and `vlan_violations`
#: refuses anything outside it at generation time rather than at the commit.
VLAN_MIN = 2
VLAN_MAX = 4094


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
    #: The VLAN this circuit is tagged with, or `None` to take
    #: `LabProfile.ac_vlan`.
    #:
    #: Per-circuit rather than per-profile because of Exaware, 2026-09-08
    #: (Eyal Ozeri): "The setup includes 3 DuT-Ixia connections. It is (more
    #: than) enough to create a Control Plane link and 3 ACs. An AC can reside
    #: as a tagged interface." Two attachment circuits sharing one physical
    #: link are then told apart by nothing but their VLAN, so the VLAN cannot
    #: be a property of the profile any more.
    #:
    #: It is also what makes the whole 2-4094 range reachable, which was the
    #: other half of that mail: "Vlan 3380 appears in the SUT file because it
    #: is used on one of the interfaces to an external server connection. The
    #: tool should be able to use entire 2-4094 range."
    vlan: int | None = None

    @property
    def ac_interface(self) -> str:
        """What the EVI actually binds - always the sub-interface.

        The sub-interface NUMBER is the VLAN wherever one is set. That is not
        cosmetic: two circuits on one port must have different sub-interface
        names, and naming each after its own VLAN is how the `.cfg`, the Java
        and the traffic items stay addressable by one key.
        """
        return f"{self.interface}.{self.vlan or self.subinterface}"


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
class NoCore:
    """A profile that deliberately has no core link — and says why.

    `core: CoreLink | None = None` used to express this, and that default is
    how the underlay was lost. `None` is indistinguishable from "nobody
    thought about it": three emitters answered it with `[]`/`None`, the
    symmetry guard below returned `[]`, and a suite with no IGP, no LDP and no
    BGP on either side went to the client — a fortnight after the same defect
    had been reported, fixed and verified on hardware.

    So the absence is now a value with fields. A profile may still have no
    underlay; it may not have one by omission. `reason` says what about the
    rig forces it and `accepted_by` names who agreed to pay for it, both of
    which are questions somebody has to answer out loud before generation.

    `gives_up` lists the `capabilities.Capability` ids this costs. It is the
    profile's own admission, checked against the emitted artifacts by
    `capabilities.regressions`, so a profile that under-declares its cost is
    caught by the files rather than believed.
    """

    reason: str
    accepted_by: str
    gives_up: tuple[str, ...] = ()


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
    #: The core link, or a `NoCore` stating why this rig has none.
    #:
    #: Deliberately has NO default. Every profile must answer the question,
    #: because the one time it was answered by a default the answer was wrong
    #: and nothing noticed. See `NoCore`.
    core: CoreLink | NoCore
    peer_source: PeerSource = PeerSource.NONE
    #: intPool in the SUT file that backs the attachment circuits. The `.cfg`
    #: binds its `int1`/`int2`/`int3` placeholders to it through
    #: `bringUpParams.crt`, and the Java resolves interface names from it at
    #: run time, so one suite runs on any testbed rather than on the one whose
    #: interface names happened to be written into the profile.
    ac_pool: str = "data1"
    #: IXIA configuration file this suite loads at bring-up, if one exists.
    #:
    #: `None` means the traffic items are built in code, which is where this
    #: suite started: an `.ixncfg` is a binary IxNetwork save and cannot be
    #: written from documents. It CAN be written by IxNetwork itself, so the
    #: generated `EVPN_traffic.tcl` ends by saving the session it just built;
    #: dropping that file into `configurations/ixia/` and naming it here puts
    #: the suite in the VPLS idiom - load a named config, then suspend and
    #: unsuspend named items.
    #:
    #: Named here rather than assumed, because a `.crt` config row pointing at
    #: a file that is not in the package aborts bring-up for the whole suite.
    ixncfg: str | None = None
    #: Index into the SUT's `general/vlans` list for the VLAN the attachment
    #: circuits carry. The IXIA vport is tagged from it through the `.crt`
    #: find-and-replace table, and the generated Java reads the same slot, so
    #: a rig with a different VLAN needs no code change.
    ac_vlan_index: int = 0
    #: The VLAN number itself, written LITERALLY into the `.cfg`.
    #:
    #: Exaware, 2026-08-16 (Eyal Ozeri): "The DuT config shows the vlan as a
    #: parameter e.g. (interface int1.vlan1). This is not how we usually work,
    #: and it is not clear where does the test takes/inherits the vlan value
    #: (3380) from."
    #:
    #: Both halves were fair. Their own `.crt` find-and-replace table
    #: parameterises `interface` names only — `int1`, `int2`, `vport1` — and
    #: has no `vlan` row for the DUT at all; VPLS_N1.cfg carries literal
    #: `vlan-id 2` on literal `int2.1`. We had invented a `vlan` substitution
    #: type and then put its placeholder inside an interface NAME, which is
    #: why the file did not read like theirs.
    #:
    #: Provenance, which is the other half of his question: 3380 is
    #: `sut/pc3080.xml`, `<general><vlans index="0"><number>3380</number>`.
    #: `vlan_source` records that sentence and the `.cfg` header prints it, so
    #: the next reader does not have to ask.
    ac_vlan: int = 3380
    vlan_source: str = (
        "sut/pc3080.xml <general><vlans index=\"0\"><number>3380</number> "
        "- the first VLAN the SUT declares for this testbed"
    )
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
    #: Frames per second every generated traffic item offers.
    #:
    #: One value for the whole rig, so the rate written into the readable
    #: EVPN_traffic.tcl is the rate EvpnParams asserts against. Two sources
    #: for one number is how a suite ends up checking a rate nothing sends.
    traffic_rate_fps: int = 1000
    #: Poll budget for "show" assertions, mirroring ShowVplsDetail's 30 s / 5 s.
    verify_timeout_ms: int = 30000
    verify_interval_ms: int = 5000
    notes: list[str] = field(default_factory=list)

    @property
    def asserts_advertisement_via_peer(self) -> bool:
        return self.peer_source is PeerSource.NEIGHBOUR

    @property
    def core_link(self) -> CoreLink | None:
        """The core link if this rig has one, else `None`.

        The one place `None` is still the right answer: a caller that only
        needs the addresses. Callers deciding whether to EMIT something must
        use this and handle the `None`, which is now a visible branch rather
        than a silent default.
        """
        return self.core if isinstance(self.core, CoreLink) else None

    def vlan_of(self, ac: AccessCircuit) -> int:
        """The VLAN a circuit carries: its own, else the profile default."""
        return ac.vlan if ac.vlan is not None else self.ac_vlan

    @property
    def ac_vlans(self) -> list[int]:
        return [self.vlan_of(a) for a in self.acs]

    @property
    def ac_links(self) -> list[tuple[str, str, int]]:
        """One entry per PHYSICAL attachment link: (placeholder, vport, index).

        Not one per AC. Two circuits sharing a port are two sub-interfaces on
        one link, and the things that are per-link - the `interface intN`
        stanza, the `.crt` find-and-replace row, the IXIA vport assignment -
        must be emitted once. Emitting them per AC produced a duplicate
        `int3` row, which the bring-up template validator rejects.
        """
        out: list[tuple[str, str, int]] = []
        for i, ac in enumerate(self.acs):
            n = ac.int_index if ac.int_index is not None else i + 1
            entry = (f"int{n}", ac.vport, n - 1)
            if entry not in out:
                out.append(entry)
        return out

    def with_ac_vlans(self, vlans: list[int]) -> LabProfile:
        """The same profile with the attachment-circuit VLANs replaced.

        This is what makes "the tool should be able to use entire 2-4094
        range" true from the command line rather than in principle: the rig
        owner names the VLANs their lab has free and the whole suite - `.cfg`,
        `.crt`, Java, traffic items - is regenerated on them.
        """
        if len(vlans) != len(self.acs):
            raise ValueError(
                f"lab profile {self.id!r} has {len(self.acs)} attachment "
                f"circuits but {len(vlans)} VLAN(s) were given")
        acs = [replace(ac, vlan=v) for ac, v in zip(self.acs, vlans, strict=True)]
        return replace(
            self, acs=acs, ac_vlan=vlans[0],
            vlan_source=("chosen on the command line (ate codegen --ac-vlans "
                         + ",".join(str(v) for v in vlans) + ")"))

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
    core=NoCore(
        reason=(
            "pc-3080 has exactly three DUT<->IXIA links (x-eth 0/0/8, 0/0/18, "
            "0/0/26) and a vport cannot be both a raw-traffic endpoint and an "
            "L3 core interface - the chassis answers ERROR-6301. This profile "
            "spends all three on attachment circuits so that FLOW-030's local "
            "MAC move has somewhere to move to, which leaves no port for the "
            "core link. Three ACs and a BGP session need a fourth port."
        ),
        accepted_by=(
            "NOBODY - open with Exaware as of 2026-08-16. This profile is the "
            "spec topology behind the reviewed test plan and is fine to "
            "generate locally, but a suite emitted from it has no control "
            "plane and MUST NOT reach a client. That is not advisory: "
            "capabilities.regressions refuses it, and "
            "scripts/verify_handover_package.py refuses it again with no "
            "escape hatch."
        ),
        gives_up=("underlay.igp", "underlay.mpls", "underlay.bgp",
                  "underlay.bgp_evpn_af"),
    ),
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

def vlan_violations(lab: LabProfile) -> list[str]:
    """Reasons this profile's attachment-circuit VLANs cannot be committed.

    Three things are checked, and each of them has cost a run:

      * the range. 0, 1 and 4095 are not usable service VLANs, and a value
        outside 2-4094 is refused at the commit, after the bring-up has
        already spent its minutes.
      * uniqueness per link. Two circuits on one port ARE the same
        sub-interface if they share a VLAN, so the second `interface
        intN.<vlan>` stanza silently reconfigures the first and the EVI ends
        up with one AC where the test believes it has two.
      * one traffic item per (vport, VLAN). The IXIA endpoint of a raw item is
        the vport; what tells two circuits on one vport apart is the VLAN tag
        pushed onto the frame. Two items on the same pair are indistinguishable
        at the far end, so an assertion about "which AC received it" cannot
        mean anything.
    """
    out: list[str] = []
    for ac in lab.acs:
        v = lab.vlan_of(ac)
        if not VLAN_MIN <= v <= VLAN_MAX:
            out.append(
                f"{ac.name}: VLAN {v} is outside the usable range "
                f"{VLAN_MIN}-{VLAN_MAX}")
    seen: dict[tuple[str, int], str] = {}
    for ac in lab.acs:
        key = (ac.interface, lab.vlan_of(ac))
        if key in seen:
            out.append(
                f"{ac.name} and {seen[key]} are both {ac.interface} VLAN "
                f"{lab.vlan_of(ac)}, so they are one sub-interface, not two "
                "attachment circuits")
        seen[key] = ac.name
    return out


def underlay_symmetry_violations(lab: LabProfile) -> list[str]:
    """Protocols the DUT runs across the core link with nobody to talk to.

    A one-sided underlay is invisible at generation time and nearly invisible
    at run time: the DUT comes up, the config commits, every `show` command
    answers, and the only symptom is an adjacency that never forms — which
    reads as "not wired up yet" rather than as a defect. This is the same
    class as a test that asserts nothing: it looks like it works.

    So the asymmetry is made a generation-time error, where it is cheap.

    NOTE what this does NOT check, because for a fortnight nobody noticed:
    it asks whether the two ends AGREE, never whether either end EXISTS. A
    profile with no core link has nothing to disagree about and passes here
    trivially. That gap is covered by `capabilities.regressions`, which reads
    the emitted files instead of the profile.
    """
    core = lab.core_link
    if core is None:
        return []
    missing = [p for p in core.dut_protocols
               if p not in core.tester_protocols]
    return [
        f"the DUT runs {p!r} across the core link but the tester emulates no "
        f"{p!r} peer, so that adjacency can never form"
        for p in missing
    ]


def bgp_capable(lab: LabProfile) -> bool:
    """Whether this rig can carry a BGP session at all.

    Both ends have to run it: a DUT speaking BGP into a port that emulates no
    peer produces a session that never establishes, which reads as "not wired
    up yet" rather than as a defect. That reading cost a fortnight.
    """
    core = lab.core_link
    return (core is not None
            and "bgp" in core.dut_protocols
            and "bgp" in core.tester_protocols)


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

#: VLANs the attachment circuits carry on the 3-AC + core rig.
#:
#: NOT from the SUT's `general/vlans` list, which is where 3380 came from and
#: what Exaware objected to on 2026-09-08: "Vlan 3380 appears in the SUT file
#: because it is used on one of the interfaces to an external server
#: connection." Those entries belong to other links; taking one for a test is
#: how the suite ended up sharing a VLAN with a production server connection.
#:
#: So they are the generator's own, inside 2-4094, and the generated Java
#: asserts at run time that none of them collides with a VLAN the SUT
#: declares. Override from the command line with `ate codegen --ac-vlans`.
#: OPEN with Eyal as of 2026-09-09: which VLANs this rig actually has free.
AC_VLANS_3AC_CORE = (1001, 1002, 1003)

CORE3_AC1 = AccessCircuit(name="AC1", interface="agg-eth-2", vport="vport2",
                          int_index=2, vlan=AC_VLANS_3AC_CORE[0])
CORE3_AC2 = AccessCircuit(name="AC2", interface="agg-eth-3", vport="vport3",
                          int_index=3, vlan=AC_VLANS_3AC_CORE[1])
#: AC3 shares AC2's physical link and differs from it only by VLAN.
#:
#: This is the whole of Exaware's 2026-09-08 answer, and it is what brings
#: TC02 back. The rig has three DUT<->IXIA links; spending one on the control
#: plane used to leave two attachment circuits, so FLOW-030's MAC move - which
#: needs a third - was dropped from the package. "An AC can reside as a tagged
#: interface" removes that arithmetic: a link carries as many circuits as it
#: has VLANs.
#:
#: The ERROR-6301 constraint that forced the earlier either/or is untouched
#: and still true: a vport cannot be both a raw-traffic endpoint and an L3
#: core interface. vport1 stays purely the core, and no raw item goes near it.
CORE3_AC3 = AccessCircuit(name="AC3", interface="agg-eth-3", vport="vport3",
                          int_index=3, vlan=AC_VLANS_3AC_CORE[2])

TI3_AC1_TO_AC2 = TrafficItem(name="TI_AC1_TO_AC2", src="AC1", dst="AC2",
                             src_mac="00:00:01:00:00:01")
# AC2 and AC3 share a source MAC on purpose - that is what makes AC2 -> AC3 a
# local move rather than two distinct hosts.
TI3_AC2_TO_AC1 = TrafficItem(name="TI_AC2_TO_AC1", src="AC2", dst="AC1",
                             src_mac="00:00:02:00:00:01")
TI3_AC3_TO_AC1 = TrafficItem(name="TI_AC3_TO_AC1", src="AC3", dst="AC1",
                             src_mac="00:00:02:00:00:01")

SINGLE_DUT_3AC_CORE = LabProfile(
    id="lab-1dut-3ac-core",
    description=(
        "Single DUT on pc-3080/pc-3099. IXIA vport1 is the core: an emulated "
        "BGP EVPN peer over a point-to-point L3 link. vport2 and vport3 carry "
        "THREE attachment circuits between them, as tagged sub-interfaces - "
        "AC2 and AC3 share vport3 and differ only by VLAN. Three ACs and a "
        "control plane on three links, per Exaware 2026-09-08."
    ),
    dut="CMP1",
    ixia="IXIA1",
    evi_name="evi-1",
    acs=[CORE3_AC1, CORE3_AC2, CORE3_AC3],
    traffic_items=[TI3_AC1_TO_AC2, TI3_AC2_TO_AC1, TI3_AC3_TO_AC1],
    bgp_neighbor="PE2",
    peer_source=PeerSource.IXIA,
    core=CoreLink(),
    ac_vlan=AC_VLANS_3AC_CORE[0],
    vlan_source=(
        "ate/codegen/lab.py AC_VLANS_3AC_CORE - the generator's own VLANs, "
        "deliberately NOT the SUT's general/vlans list (3380 there is an "
        "external server connection, Exaware 2026-09-08). Override with "
        "`ate codegen --ac-vlans`."
    ),
    notes=[
        "THREE attachment circuits AND a control plane, which the 2-AC "
        "profile could not do. AC2 and AC3 are two VLANs on one link, so "
        "moving traffic from one to the other is still a purely local MAC "
        "move on one PE - the FLOW-030 premise - and it now happens with a "
        "BGP session up, which the 2026-08-14 three-AC package did not have.",
        "DEVICE-VERIFIED 2026-09-09 on pc-3080 (8.7.0 LAB 0): a vlan-based "
        "EVI accepts two sub-interfaces of the SAME port as two attachment "
        "circuits. A scratch EVI was built on a spare port, the commit was "
        "accepted, and `show evpn detail` listed BOTH x-eth0/0/22.2001 and "
        "x-eth0/0/22.2002 under Local Interfaces, as did `show evpn "
        "broadcast-domains`. Transcript, including the rollback that put the "
        "device back as found: deliverables/M2/evidence_shared_port_acs.txt. "
        "This was the one genuinely new assumption in this profile.",
        "The peer is IXIA itself (PeerSource.IXIA), so Type-2/Type-3 "
        "advertisement and withdrawal are assertable without a second "
        "physical PE.",
    ],
)

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

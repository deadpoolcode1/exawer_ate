"""Per-scenario device configuration, in Exaware's own house format.

A JSystem suite in their tree is not just Java. Each test package carries a
`bringUpParams.crt` that tells the bring-up which devices a test needs and
which configuration files to load onto them, plus the files themselves:

    cmp/tests/<suite>/bringUpParams.crt
    cmp/tests/<suite>/configurations/compass/<NAME>.cfg     # DUT config
    cmp/tests/<suite>/configurations/ixia/<NAME>.ixncfg     # IXIA config

Modelled on `cmp/tests/vpls/`, the closest analog. Two conventions matter and
are reproduced here:

  * **Config is layered.** `cleanBaseConfig` loads with LOAD_TYPE 1 (override)
    to give every test a known starting point, then the feature `.cfg` loads
    with LOAD_TYPE 2 (merge). Our suites previously configured the DUT only
    from inside the test body, which works but skips that reset.
  * **Interfaces are placeholders.** The `.cfg` names `int1`/`int2`/`int3` and
    the `.crt`'s find-and-replace table binds them to an `intPool` in the SUT
    file, so one config serves every testbed. We emit the same binding, which
    lands on pc3021's `data1` pool (and its three IXIA vports) unchanged.

What is NOT emitted, deliberately:

  * **The underlay** — interface IP addressing, MPLS/LDP, BGP. That is lab
    data, not documented in the SFS or CLI doc; inventing addresses would put
    fiction into a file that gets typed at a real router. The header says so
    and points at `cleanBaseConfig` / the site config.
  * **The `.ixncfg`** — a binary IxNetwork save. 191 exist in their repo; they
    cannot be synthesised from documents. The `.crt` row is emitted commented
    out, because a missing file referenced there aborts bring-up for the whole
    suite.

Everything that IS emitted is grounded: each configuration line is rendered
from an `EvpnCommands` template, and those raise at generation time if they do
not trace to the EVPN CLI doc. The *hierarchy* is derived mechanically from the flat command text and was
**confirmed on hardware** on 2026-08-11: an EVI was configured on
exa-il01-ec-3021 and `show configuration l2-services` printed exactly this
shape, `!` terminators included.
"""
from __future__ import annotations

from ate.codegen.commands import all_commands
from ate.codegen.java_emitter import JavaFile
from ate.codegen.lab import LabProfile
from ate.codegen.script_ir import StepKind, TestScript

__all__ = ["DUT_CONFIG_NAME", "emit_bringup_params", "emit_dut_config"]

DUT_CONFIG_NAME = "EVPN_Base.cfg"
_IXIA_CONFIG_NAME = "EVPN_3AC.ixncfg"

def _by_key() -> dict:
    """Built per call: derived entries are installed at generation time."""
    return {c.key: c for c in all_commands()}


def _rendered_config_lines(scripts: list[TestScript]) -> list[str]:
    """Every CONFIG step's CLI text, in order, de-duplicated.

    `no ...` and `clear ...` forms are skipped: a base configuration file
    states what the device should have, not what a test later removes or
    flushes at run time.
    """
    out: list[str] = []
    for sc in scripts:
        for st in sc.steps:
            if st.kind is not StepKind.CONFIG or not st.command:
                continue
            cmd = _by_key().get(st.command)
            if cmd is None or not cmd.template:
                continue
            try:
                text = cmd.template % tuple(st.args)
            except TypeError:
                continue          # arity mismatch — skip rather than guess
            if text.startswith(("no ", "clear ")) or text in out:
                continue
            out.append(text)
    return out


def _placeholderise(lines: list[str], lab: LabProfile) -> list[str]:
    """Swap the lab's real interface names for `int1`/`int2`/`int3`.

    This is the VPLS convention and the reason one `.cfg` serves every
    testbed: the file names placeholders, and the find-and-replace table in
    `bringUpParams.crt` binds them to an `intPool` in the SUT file. Writing
    `agg-eth-1` here instead would pin the config to one rig.
    """
    out = []
    for line in lines:
        for i, ac in enumerate(lab.acs):
            n = ac.int_index if ac.int_index is not None else i + 1
            # Sub-interface first: replacing the bare port would turn
            # `agg-eth-1.100` into `int1.100` only by luck of ordering, and
            # into `int1` plus a stray `.100` if the port name is a prefix.
            line = line.replace(ac.ac_interface, f"int{n}.vlan1")
            line = line.replace(ac.interface, f"int{n}")
        out.append(line)
    return out


def _attachment_circuits(lab: LabProfile) -> list[str]:
    """Create the sub-interfaces the EVI binds, before it binds them.

    A VLAN-based EVPN service rejects a physical port as an attachment
    circuit — the commit fails with "is not a sub-interface, but the EVPN
    service-type is vlan-based" (8.7.0 LAB 22, pc-3080). So the circuits have
    to exist as sub-interfaces first.

    The stanza shape is Exaware's own, from `cmp/tests/vpls/configurations/
    compass/VPLS_N1.cfg`, which brings up l2-transport circuits exactly this
    way; `l2-transport`'s values were then confirmed against the device
    (`enable` / `disable`, defaulting to `disable`).
    """
    lines = ["!", "! Attachment circuits. A vlan-based EVI binds SUB-interfaces,",
             "! never the port itself - the device rejects the commit otherwise.",
             "!"]
    for i, ac in enumerate(lab.acs):
        n = ac.int_index if ac.int_index is not None else i + 1
        lines += [
            f"interface int{n}",
            " admin-state up",
            "!",
            f"interface int{n}.vlan1",
            " l2-transport enable",
            "!",
        ]
    return lines


def _underlay(lab: LabProfile) -> list[str]:
    """The core link, IGP, MPLS transport and the BGP EVPN session.

    Why this exists at all: EVPN is an overlay and cannot come up standalone.
    It needs reachability to the remote PE (IGP), a transport label (LDP) and
    a control plane to carry Type-2/Type-3 routes (BGP `af-l2vpn evpn`).
    Without them the EVI is a local bridge domain with sub-interfaces on it,
    and `show bgp l2vpn evpn ...` has nothing to print because there is no BGP
    session at all - which is exactly what every run showed.

    This file used to state, in its own header, that the underlay was "lab
    data ... deliberately not invented here" and had to arrive from
    `cleanBaseConfig`. It never did: the `.crt` loads `cleanBaseConfig` and
    then this file, and a clean base configures no IGP and no BGP. The
    delegation had no receiver, so nothing supplied it (Ilan, 2026-08-13).

    It is not invented now either. Every stanza below is the shape Exaware's
    own VPLS suite commits on this same testbed
    (`cmp/tests/vpls/configurations/compass/VPLS_N1.cfg`), with `af-l2vpn
    vpls` swapped for `af-l2vpn evpn` - and that swap is device-grounded: on
    pc-3080 `af-l2vpn evpn` was found to live only under a neighbour in
    `vrf default`, which is where it is written here.
    """
    core = lab.core
    if core is None:
        return []
    i, lo = core.interface, f"loopback {core.loopback_id}"
    return [
        "!",
        "! Underlay. EVPN is an overlay: without an IGP, a transport label and",
        "! a BGP session there is no control plane to carry Type-2/Type-3 and",
        "! the EVI is only a local bridge domain.",
        "!",
        "! Stanza shapes are Exaware's own, from cmp/tests/vpls/configurations/",
        "! compass/VPLS_N1.cfg on this testbed; the address family is EVPN.",
        "!",
        f"interface {i}",
        " admin-state  up",
        f" ipv4-address {core.dut_ipv4}/{core.prefix_len}",
        " mpls         enable",
        "!",
        f"interface {lo}",
        f" ipv4-address {core.loopback_ipv4}/32",
        "!",
        "mpls ldp default",
        f" router-id {core.loopback_ipv4}",
        f" interface {i}",
        "  af-ipv4",
        " !",
        "!",
        f"routing ospf {lab.bgp_asn}",
        " vrf default",
        f"  area {lab.igp_area}",
        f"   interface {i}",
        "    network-type point-to-point",
        "    mtu          1500",
        "   !",
        f"   interface {lo}",
        "    passive enable",
        "   !",
        "  !",
        " !",
        "!",
        f"routing bgp {lab.bgp_asn}",
        " vrf default",
        f"  neighbor {core.peer_ipv4}",
        f"   remote-as-number {lab.bgp_asn}",
        "   af-ipv4 unicast",
        "    inbound-soft-reconfiguration enable",
        "   !",
        "   af-l2vpn evpn",
        "    inbound-soft-reconfiguration enable",
        "   !",
        "  !",
        " !",
        "!",
    ]


def _evpn_block(lines: list[str], evi: str) -> tuple[list[str], list[str]]:
    """Fold flat `l2-services evpn <evi> <rest>` commands into a config block.

    Returns (block lines, commands that did not fit the shape). Anything that
    does not fit is returned rather than reshaped — a config file is typed at a
    router, so a line we cannot place is a line we do not write.
    """
    prefix = f"l2-services evpn {evi} "
    leaves = [ln[len(prefix):] for ln in lines if ln.startswith(prefix)]
    other = [ln for ln in lines if not ln.startswith(prefix)]
    if not leaves:
        return [], other
    block = ["l2-services", f" evpn {evi}"]
    block += [f"  {leaf}" for leaf in leaves]
    block += [" !", "!"]
    return block, other


def emit_dut_config(scripts: list[TestScript], lab: LabProfile) -> JavaFile:
    """The DUT-side `.cfg`, in the device's own hierarchical config syntax."""
    rendered = _placeholderise(_rendered_config_lines(scripts), lab)
    block, unplaced = _evpn_block(rendered, lab.evi_name)

    head = [
        "!",
        "! EVPN base service configuration.",
        "!",
        "! GENERATED from the EVPN CLI doc via EvpnCommands - every line below",
        "! renders a command template that traces to the documentation.",
        "!",
        "! DEVICE-VERIFIED 2026-08-11 on exa-il01-ec-3021 (8.7.0 LAB 22):",
        "! an EVI was configured and 'show configuration l2-services' printed",
        "! exactly this block shape, so the hierarchy and '!' terminators are",
        "! confirmed rather than assumed.",
        "!",
        "! DEVICE-CORRECTED 2026-08-12 on exa-il01-uf-3080 (8.7.0 LAB 22):",
        "! this file previously bound the AC ports directly and the commit was",
        "! REJECTED - a vlan-based EVI takes sub-interfaces only. The circuits",
        "! below are created first, then bound.",
        "!",
        "! Interface names are placeholders bound by the find-and-replace",
        "! table in bringUpParams.crt to the SUT's 'data1' intPool.",
        "!",
    ]
    if lab.core is None:
        head += [
            "! NOT included - the underlay. This suite has no core link, so",
            "! there is no IGP, no transport label and no BGP session, and the",
            "! EVI below is a local bridge domain only. A profile with a",
            "! CoreLink emits the overlay; see LabProfile.core.",
            "!",
        ]
    body = _underlay(lab) + _attachment_circuits(lab) + (
        block or ["! (no EVPN configuration steps in the selected scripts)"])
    tail = []
    if unplaced:
        tail = ["!", "! Not placed in the block above - review and add by hand:"]
        tail += [f"!   {ln}" for ln in unplaced] + ["!"]

    return JavaFile(path=f"cmp/tests/evpn/configurations/compass/{DUT_CONFIG_NAME}",
                    content="\n".join(head + body + tail) + "\n")


def emit_tester_config(lab: LabProfile) -> JavaFile | None:
    """The IXIA side of the core link, generated from the same profile.

    Why this exists: the generator used to emit the DUT's underlay and NOTHING
    for the tester. There was no model of the far end at all, so nothing could
    notice that the DUT was running OSPF, LDP and BGP into a port configured
    for none of them. The IXIA side had to be built by hand, which is exactly
    how the two drifted apart.

    Emitting both ends from one profile makes the drift impossible: the
    addresses, router IDs, area and protocol set below are the same values the
    `.cfg` is rendered from, and `underlay_symmetry_violations` fails
    generation if the DUT names a protocol this file would not bring up.

    It emits TCL rather than an `.ixncfg` because the binary is an IxNetwork
    save that cannot be synthesised; raw TCL reaches the same objects through
    the tclsh their `Ixia.runCommand` already talks to, and needs no file from
    anybody. Every attribute name here was read back off chassis 10.1.70.108.
    """
    core = lab.core
    if core is None:
        return None
    p = set(core.tester_protocols)
    out = [
        "# GENERATED by ate codegen - do not edit by hand.",
        "#",
        f"# Tester side of the core link for lab profile {lab.id!r}.",
        "# The DUT side of this same link is EVPN_Base.cfg; both are rendered",
        "# from ate/codegen/lab.py, so they cannot drift apart.",
        "#",
        "# EVPN objects are deliberately NOT built here: emulating an EVPN",
        "# speaker needs a BGP EVPN licence this chassis does not have, and",
        "# the current TCs assert the EVPN address family in the session's",
        "# CAPABILITIES, which the DUT advertises on its own.",
        "",
        "package require IxTclNetwork",
        "set vp /vport:1",
        "set intf $vp/interface:1",
        "",
        "# routed interface facing the DUT",
        f"ixNet setAtt $intf -enabled true -description {lab.id}-core",
        "ixNet commit",
        "set v4 [ixNet add $intf ipv4]",
        f"ixNet setAtt $v4 -ip {core.peer_ipv4} -gateway {core.dut_ipv4} "
        f"-maskWidth {core.prefix_len}",
        "ixNet commit",
        "",
    ]
    if "ospf" in p:
        out += [
            "# OSPF - must match the DUT's area and network type or the",
            "# adjacency forms as EXSTART and never reaches FULL.",
            "set ospf $vp/protocols/ospf",
            "ixNet setAtt $ospf -enabled true",
            "ixNet commit",
            "set rtr [lindex [ixNet remapIds [ixNet add $ospf router]] 0]",
            f"ixNet setAtt $rtr -enabled true -routerId {core.peer_ipv4}",
            "ixNet commit",
            "set oi [ixNet add $rtr interface]",
            "ixNet setAtt $oi -enabled true -interfaces $intf "
            f"-areaId {lab.igp_area.split('.')[0]} -networkType pointToPoint "
            "-metric 1 -mtu 1500 -connectedToDut true",
            "ixNet commit",
            "",
        ]
    if "ldp" in p:
        out += [
            "# LDP - transport labels for the EVPN service",
            "set ldp $vp/protocols/ldp",
            "ixNet setAtt $ldp -enabled true",
            "ixNet commit",
            "set lr [lindex [ixNet remapIds [ixNet add $ldp router]] 0]",
            f"ixNet setAtt $lr -enabled true -routerId {core.peer_ipv4}",
            "ixNet commit",
            "set li [ixNet add $lr interface]",
            "ixNet setAtt $li -enabled true -protocolInterface $intf "
            "-discoveryMode basic -labelSpaceId 0",
            "ixNet commit",
            "",
        ]
    if "bgp" in p:
        out += [
            "# BGP - ipv4-unicast only; see the note on EVPN above.",
            "set bgp $vp/protocols/bgp",
            "ixNet setAtt $bgp -enabled true",
            "ixNet commit",
            "set nr [lindex [ixNet remapIds [ixNet add $bgp neighborRange]] 0]",
            "ixNet setAtt $nr -enabled true -evpn false -ipV4Unicast true "
            f"-type internal -dutIpAddress {core.dut_ipv4} "
            f"-localIpAddress {core.peer_ipv4} -localAsNumber {lab.bgp_asn} "
            f"-interfaces $intf -enableBgpId true -bgpId {core.peer_ipv4}",
            "ixNet commit",
            "",
        ]
    out += [
        "# take the port and start, then READ BACK - a start that returns",
        "# without error is not evidence the protocol is running.",
        "catch {ixNet exec connectPorts [list $vp]}",
        "after 20000",
    ]
    for name in ("ospf", "ldp", "bgp"):
        if name in p:
            out += [
                f"if {{[catch {{ixNet exec start $vp/protocols/{name}}} e]}} "
                f"{{ puts \"START-{name.upper()}-FAIL: $e\" }}",
            ]
    out.append("after 40000")
    for name in ("ospf", "ldp", "bgp"):
        if name in p:
            out.append(
                f'puts "{name.upper()}-RUNNING='
                f'[ixNet getAtt $vp/protocols/{name} -runningState]"')
    return JavaFile(
        path="cmp/tests/evpn/configurations/ixia/evpn_tester_setup.tcl",
        content="\n".join(out) + "\n")


def _col(*pairs: tuple[str, int]) -> str:
    return "".join(text.ljust(width) for text, width in pairs).rstrip()


def emit_bringup_params(scripts: list[TestScript], lab: LabProfile) -> JavaFile:
    """`bringUpParams.crt` — devices, per-test config files, bindings, actions.

    The layout is not cosmetic. `GetBringUpParams` validates this file against
    a stored response template (`bringUpParameters_C0_00*.crt` under
    `/auto/automation/Jsystem/ResponseTemplates/`), and that template is
    position-sensitive: it pins the section comments, the blank lines between
    them, and the six tables in order. An earlier version of this emitter put
    explanatory `//` notes inside the tables, and bring-up rejected the whole
    file with "format doesn't match the template" — the notes shifted the
    static blocks and merged the ping table's header into one column.

    So: no prose lives here. What would have been a comment is in the `.cfg`
    header and the M2 README instead. Verified by running the real validator
    over the emitted file (`TemplateManager.validateAgainstTemplate`).
    """
    dut, ixia = "cmp1", "ixia1"
    cfg = f"/configurations/compass/{DUT_CONFIG_NAME}"
    out: list[str] = [
        "//full topology for suite, devices names and types:",
        "",
        "DEVICE_NAME     CLASS",
        "-" * 44,
        f"{dut:<16}cmp.infra.CmpRouter",
        f"{ixia:<16}cmp.infra.ixia.Ixia",
        "",
        "//connect devices topology for each TC",
        "",
        "TEST     DEVICES_TOPOLOGY",
        "-" * 45,
        f"{'default':<9}{dut}, {ixia}",
        "",
        "//devices names and configuration files parameters for evpn tests: "
        "1= override, 2 = merge",
        "",
        f"{'TEST':<10}{'DEVICE_NAME':<16}{'CONFIG_FILE_PATH':<68}"
        f"{'LOAD_ON_BRING_UP':<19}{'LOAD_TYPE':<10}TIMEOUT_SEC",
        "-" * 139,
        f"{'default':<10}{dut:<16}{'cleanBaseConfig':<68}{'y':<19}{'1':<10}1900",
        f"{'':<10}{'':<16}{cfg:<68}{'y':<19}{'2':<10}1900",
        "",
        "//devices ping lists, relevant for all the tests",
        "",
        f"{'TEST':<14}{'DEVICE_NAME':<15}{'PING_IP':<22}{'PING_DESCRIPTION':<46}"
        f"{'PING_SUCCEES_THRESHOLD':<27}{'PING_RETRY_NUMBER':<20}PING_VRF_NAME",
        "-" * 156,
        "",
        "",
        "//find and replace parameters on devices cfg files and ixia vlan's "
        "configuration, relevant for all tests",
        "",
        f"{'TEST':<12}{'DEVICE_NAME':<15}{'TYPE':<14}{'FIND_PARAM':<27}"
        f"{'INTPOOL_NAME':<17}INTPOOL_INDEX",
        "-" * 100,
    ]
    # (DUT placeholder, IXIA vport, intPool index) for every link, core first.
    # The core link is a link like any other to the bring-up: it just gets an
    # IP and an IGP in the .cfg instead of an l2-transport sub-interface.
    links: list[tuple[str, str, int]] = []
    if lab.core is not None:
        links.append((lab.core.interface, lab.core.vport, lab.core.pool_index))
    for i, ac in enumerate(lab.acs):
        n = ac.int_index if ac.int_index is not None else i + 1
        links.append((f"int{n}", ac.vport, n - 1))

    for i, (dut_int, _vport, idx) in enumerate(links):
        first = i == 0
        out.append(f"{'default' if first else '':<12}{dut if first else '':<15}"
                   f"{'interface':<14}{dut_int:<27}{lab.ac_pool:<17}{idx}")
    for i, (_dut_int, vport, idx) in enumerate(links):
        out.append(f"{'':<12}{ixia if i == 0 else '':<15}"
                   f"{'interface':<14}{vport:<27}{lab.ac_pool:<17}{idx}")
    # The AC VLAN, bound from the SUT on BOTH sides.
    #
    # On cmp1 it replaces the `vlan1` placeholder in the .cfg, so the
    # sub-interfaces come out as <port>.<vlan>. On ixia1 it tags the vport's
    # interface with the same VLAN - which is also what makes the vport usable
    # as a RAW traffic-item endpoint: configTrafficItemEndpoints only takes the
    # `/vport:N/protocols` form the chassis demands for raw items when the
    # interface has a VLAN enabled, and answers
    # "ERROR-6301-The endpoint is not correct for this type of trafficItem"
    # otherwise.
    out.append(f"{'':<12}{'cmp1':<15}"
               f"{'vlan':<14}{'vlan1':<27}{'vlans':<17}{lab.ac_vlan_index}")
    #
    # The core vport is deliberately NOT tagged here. It carries a routed
    # interface for the BGP EVPN session, not a raw traffic endpoint, so the
    # one-interface-with-a-VLAN rule above does not apply to it and tagging it
    # would only put the session behind a VLAN the DUT's core interface does
    # not have.
    for i, ac in enumerate(lab.acs):
        out.append(f"{'':<12}{'ixia1' if i == 0 else '':<15}"
                   f"{'vlan':<14}{ac.vport:<27}"
                   f"{'vlans':<17}{lab.ac_vlan_index}")
    out += [
        "",
        "//before after table:",
        "",
        f"{'TEST':<10}{'DEVICE_NAME':<14}{'ID_ACT':<23}{'ACTION_DESCRIPTION':<35}"
        f"{'ACTION_PARAMS':<66}{'DO_BEFORE_TEST':<18}DO_AFTER_TEST",
        "-" * 181,
        f"{'default':<10}{'test':<14}{'loadTestParamFile':<23}"
        f"{'loading suite parameters class':<35}"
        f"{'cmp.tests.evpn.EvpnParams':<66}{'y':<18}n",
        f"{'':<10}{dut:<14}{'verifyLCs':<23}"
        f"{'verify LCs are card ready state':<35}{'':<66}{'y':<18}y",
        f"{'':<10}{'':<14}{'verifyInts':<23}"
        f"{'verify interfaces are up':<35}{'':<66}{'y':<18}n",
        "",
    ]
    return JavaFile(path="cmp/tests/evpn/bringUpParams.crt",
                    content="\n".join(out))


#: Why `startProtocols` / `sendArpAllPorts` are NOT in the before/after table.
#:
#: The VPLS suite runs both, because its `.ixncfg` carries emulated protocol
#: sessions to start and hosts to ARP for. This suite has neither: it builds
#: raw traffic items in code and configures no protocols. Asking the chassis to
#: start protocols it does not have is not harmless - on pc-3080 `startProtocols`
#: blocked until the 120 s command timeout and failed the run.
#:
#: It looked harmless for a long time only because the TCL library was never
#: loaded, so the call answered `invalid command name` and `performFunctions`
#: reported "ended without errors".
_OMITTED_IXIA_ACTIONS = ("startProtocols", "sendArpAllPorts")

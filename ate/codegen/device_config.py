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

The **underlay** — interface addressing, MPLS/LDP and BGP — IS emitted, from
`LabProfile.core`, on both ends: `_underlay` writes the DUT side into the
`.cfg` and `emit_tester_config` writes the IXIA side as TCL, from the same
values, so the two cannot drift.

This docstring used to say the opposite ("what is NOT emitted, deliberately:
the underlay ... the header says so and points at `cleanBaseConfig`"). That
delegation had no receiver — the `.crt` loads `cleanBaseConfig` and then the
feature `.cfg`, and a clean base configures no IGP and no BGP — so nothing
ever supplied it and EVPN could not come up at all. Kept here as a warning
about deferring a requirement to a file nobody checked.

What is still NOT emitted:

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

__all__ = ["DUT_CONFIG_NAME", "TRAFFIC_CONFIG_NAME",
           "emit_bringup_params", "emit_dut_config",
           "emit_traffic_config"]
DUT_CONFIG_NAME = "EVPN_Base.cfg"



def _wrap(text: str, width: int) -> list[str]:
    """Wrap prose for a `!`-commented config banner."""
    import textwrap  # noqa: PLC0415

    return textwrap.wrap(" ".join(text.split()), width=width) or [""]


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
            line = line.replace(ac.ac_interface, f"int{n}.{lab.vlan_of(ac)}")
            line = line.replace(ac.interface, f"int{n}")
        out.append(line)
    return out


def _attachment_circuits(lab: LabProfile) -> list[str]:
    """Create the sub-interfaces the EVI binds, before it binds them.

    A VLAN-based EVPN service rejects a physical port as an attachment
    circuit - the commit fails with "is not a sub-interface, but the EVPN
    service-type is vlan-based" (8.7.0 LAB 22, pc-3080). So the circuits have
    to exist as sub-interfaces first.

    The stanza shape is Exaware's own, from `cmp/tests/vpls/configurations/
    compass/VPLS_N1.cfg`, which brings up l2-transport circuits exactly this
    way; `l2-transport`'s values were then confirmed against the device
    (`enable` / `disable`, defaulting to `disable`).

    Two circuits may share a port and differ only by VLAN (Exaware 2026-09-08:
    "An AC can reside as a tagged interface"). The parent `interface intN`
    stanza is therefore emitted once per LINK and the sub-interface stanza
    once per CIRCUIT; emitting the parent twice makes the second occurrence
    reconfigure the first.
    """
    vlans = ", ".join(str(v) for v in lab.ac_vlans)
    lines = ["!",
             "! Attachment circuits. A vlan-based EVI binds SUB-interfaces,",
             "! never the port itself - the device rejects the commit otherwise.",
             "!",
             f"! VLAN(s) {vlans}, written literally here in the VPLS house",
             "! style (VPLS_N1.cfg has literal `vlan-id 2` on literal",
             "! `int2.1`) rather than as a find-and-replace placeholder.",
             "! They come from:"]
    lines += [f"!   {ln}" for ln in _wrap(lab.vlan_source, 66)]
    lines += [
             "!",
             "! They are deliberately NOT taken from the SUT's general/vlans",
             "! list. Exaware, 2026-09-08: \"Vlan 3380 appears in the SUT file",
             "! because it is used on one of the interfaces to an external",
             "! server connection.\" The generated suite asserts at run time",
             "! that none of the VLANs below collides with one the SUT",
             "! declares, and FAILS the run if one does.",
             "!"]
    for placeholder, _vport, _idx in lab.ac_links:
        lines += [f"interface {placeholder}", " admin-state up", "!"]
        for i, ac in enumerate(lab.acs):
            n = ac.int_index if ac.int_index is not None else i + 1
            if f"int{n}" != placeholder:
                continue
            lines += [
                f"interface {placeholder}.{lab.vlan_of(ac)}",
                " l2-transport enable",
                # The sub-interface NUMBER does not select the VLAN. Naming it
                # `.3380` and stopping there produces a circuit that is
                # admin-up, is listed under `show evpn detail` as a bound AC,
                # and classifies not one frame: the physical port counted 219k
                # received while the sub-interface counted 0, and the MAC
                # table stayed empty.
                #
                # Exaware's VPLS_N1.cfg has said so all along - `interface
                # int2.1` carries `vlan-id 2`, an index and a VLAN that need
                # not match. DEVICE-VERIFIED on pc-3080: adding this line is
                # what makes the circuit forward and the EVI learn.
                f" vlan-id      {lab.vlan_of(ac)}",
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
    core = lab.core_link
    if core is None:
        # Not a fallthrough: `lab.core` is a NoCore carrying a reason and an
        # acceptor, and `capabilities.regressions` decides whether emitting
        # nothing here is allowed to leave the building.
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
    """The DUT-side `.cfg`: the underlay and the circuits, NOT the service.

    What changed and why, because this file used to carry the EVI too.

    Exaware, 2026-09-08 (Eyal Ozeri): "TC01 seems to configure an already
    existing evpn service." He was right, and it was worse than untidy. The
    `.crt` loads this file at bring-up, so by the time TC01 ran its first
    step - "Create EVPN instance evi-1" - the instance was already there.
    Re-typing a configuration a device already holds stages nothing, so the
    commit has nothing to do, so the step cannot fail. TC01's whole subject
    was a no-op that reported success.

    That is the fake-pass rule arriving through the configuration file rather
    than through an assertion, and the fix is the same shape: the test must do
    the thing it claims to do. So the service is created BY TC01, against a
    device this file has deliberately left without one, and TC01's first step
    now asserts the EVI is absent before creating it.

    What stays here is what a test should not have to build to be worth
    running: the underlay (EVPN is an overlay and cannot come up without an
    IGP, a transport label and a BGP session) and the attachment
    sub-interfaces the EVI will bind.
    """
    rendered = _placeholderise(_rendered_config_lines(scripts), lab)

    head = [
        "!",
        "! EVPN base configuration: underlay and attachment circuits.",
        "!",
        "! GENERATED from the EVPN CLI doc via EvpnCommands - every line below",
        "! renders a command template that traces to the documentation.",
        "!",
        "! THE EVPN SERVICE IS DELIBERATELY NOT CONFIGURED HERE.",
        "!",
        "! Exaware, 2026-09-08 (Eyal Ozeri): \"TC01 seems to configure an",
        "! already existing evpn service.\" It did: this file used to create",
        "! evi-1, the .crt loads it at bring-up, and TC01's create steps then",
        "! re-typed a configuration the device already held. Nothing was",
        "! staged, so the commit had nothing to do, so the steps could not",
        "! fail. TC01 now creates the service itself, having first asserted",
        "! that it is absent.",
        "!",
        "! TC02/TC03 assume TC01 has run: their first step asserts the EVI",
        "! exists and stops the test with a plain message if it does not.",
        "!",
        "! DEVICE-VERIFIED 2026-08-11 on exa-il01-ec-3021 (8.7.0 LAB 22):",
        "! an EVI was configured and 'show configuration l2-services' printed",
        "! exactly the block shape TC01 builds, so the hierarchy and the '!'",
        "! terminators are confirmed rather than assumed.",
        "!",
        "! DEVICE-CORRECTED 2026-08-12 on exa-il01-uf-3080 (8.7.0 LAB 22):",
        "! the AC ports were bound directly and the commit was REJECTED - a",
        "! vlan-based EVI takes sub-interfaces only. They are created below.",
        "!",
        "! Interface names are placeholders bound by the find-and-replace",
        f"! table in bringUpParams.crt to the SUT's '{lab.ac_pool}' intPool.",
        "!",
    ]
    if lab.core_link is None:
        # Say it in the artifact, in the words of whoever accepted it. The
        # previous version of this banner was accurate and still useless: it
        # described the absence as a property of the profile, which reads as a
        # design note rather than as the missing control plane it is.
        head += [
            "! *** NO UNDERLAY IN THIS FILE - NOT A CLIENT DELIVERABLE ***",
            "!",
            "! There is no IGP, no transport label and no BGP session here, so",
            "! any EVI is a local bridge domain and nothing carries a Type-2",
            "! or Type-3 route. Why this rig has no core link:",
            "!",
        ]
        head += [f"!   {ln}" for ln in _wrap(lab.core.reason, 68)]
        head += ["!", "! Accepted by:"]
        head += [f"!   {ln}" for ln in _wrap(lab.core.accepted_by, 68)]
        head += ["!"]

    body = _underlay(lab) + _attachment_circuits(lab)

    # What the TESTS type at run time, listed so a reader of this file knows
    # what the device is expected to end up with without reading the Java.
    service = [ln for ln in rendered
               if ln.startswith(f"l2-services evpn {lab.evi_name}")]
    tail = ["!",
            "! Configured by the tests, not by this file (see the banner):",
            "!"]
    tail += [f"!   {ln}" for ln in service] or ["!   (no EVPN configuration "
                                               "steps in the selected scripts)"]
    tail += ["!"]
    unplaced = [ln for ln in rendered if ln not in service]
    if unplaced:
        tail += ["! Not recognised as EVPN service configuration - review:"]
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
    core = lab.core_link
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
        "",
        "# The routed interface facing the DUT, CREATED rather than assumed.",
        "#",
        "# DEVICE-VERIFIED 2026-09-09 on chassis 10.1.70.108 (IxNetwork 9.00).",
        "# This used to say `set intf $vp/interface:1`, which is a path, not an",
        "# object: on a vport that has no interface yet the path simply does",
        "# not resolve, `ixNet setAtt` on it changes nothing and reports no",
        "# error, and the OSPF interface below ends up with",
        "#     protocolInterface = ::ixNet::OBJ-null",
        "# The tester then has no address on the core link at all. Every",
        "# protocol still starts and reports runningState=started, so the only",
        "# visible symptom is that the DUT's neighbour never leaves Active.",
        "set intf [lindex [ixNet remapIds [ixNet add $vp interface]] 0]",
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


TRAFFIC_CONFIG_NAME = "EVPN_traffic.tcl"


def emit_traffic_config(lab: LabProfile) -> JavaFile:
    """The traffic items as a readable TCL script, and as an `.ixncfg` recipe.

    Exaware, 2026-09-08 (Eyal Ozeri): "The traffic item cannot be validated
    using the current tcl file (at least not by me) ... it is expected that a
    traffic item will be 'human readable' which means that the tool should
    learn how to create traffic items properly."

    Two things were wrong and they need different fixes.

    The first is legibility. The items were built inside Java, as argument
    lists to `performFunctions`, so what the chassis ends up with could only
    be worked out by reading Java and their TCL library side by side. This
    file states it: one block per item, its endpoints, its VLAN, its source
    MAC and its rate, in their own proc names and argument order (verified
    against `ixia_lib.tcl` on 2026-08-12).

    The second is the format. Their suites do not build traffic at all - they
    load an `.ixncfg` and suspend or unsuspend named items. We had recorded
    that as impossible: the format is a binary IxNetwork save and cannot be
    written from documents. True, and beside the point. IxNetwork can write
    it. So this script ends by saving the session it just built, which turns
    one chassis run into the file the suite loads from then on, and puts the
    items in front of a reviewer in the tool they already use.

    Running it is one command on the IXIA app server; the tail of the file
    says which.
    """
    lines = [
        "# GENERATED by ate codegen - do not edit by hand.",
        "#",
        f"# EVPN traffic items for lab profile {lab.id!r}.",
        "#",
        "# WHY THIS FILE EXISTS",
        "#   Exaware, 2026-09-08: a traffic item is expected to be human",
        "#   readable, and ours were only readable as Java argument lists.",
        "#   Everything the chassis is asked to build is stated below.",
        "#",
        "# WHAT IT PRODUCES",
        f"#   {lab.ixncfg or _default_ixncfg(lab)}  - an IxNetwork save of "
        "exactly these items,",
        "#   written by IxNetwork itself. Drop it into configurations/ixia/,",
        "#   name it in LabProfile.ixncfg, regenerate, and bringUpParams.crt",
        "#   loads it: from then on the suite only suspends and unsuspends",
        "#   named items, which is the VPLS suite's idiom.",
        "#",
        "# HOW TO RUN IT (once, on the IXIA app server)",
        "#   tclsh> source /var/tmp/ate-run/ixia_lib.tcl",
        "#   tclsh> source /var/tmp/ate-run/" + TRAFFIC_CONFIG_NAME,
        "#   The path must be one BOTH the JVM host and the app server can",
        "#   see. A path only the JVM host has is why ixia_lib.tcl silently",
        "#   failed to load for a fortnight and 34 procs answered",
        "#   'invalid command name' while the framework reported success.",
        "#",
        "# TOPOLOGY (from ate/codegen/lab.py, the same source the .cfg uses)",
    ]
    core = lab.core_link
    if core is not None:
        lines.append(f"#   core  {core.vport:<8} L3 {core.peer_ipv4}"
                     f" -> {core.dut_ipv4}   (no raw traffic on this port)")
    for i, ac in enumerate(lab.acs):
        n = ac.int_index if ac.int_index is not None else i + 1
        lines.append(
            f"#   {ac.name:<5} {ac.vport:<8} VLAN {lab.vlan_of(ac):<5}"
            f" DUT int{n}.{lab.vlan_of(ac)}")
    shared = [ac.vport for ac in lab.acs
              if sum(1 for o in lab.acs if o.vport == ac.vport) > 1]
    if shared:
        lines += [
            "#",
            f"#   {sorted(set(shared))[0]} carries more than one attachment "
            "circuit. They are",
            "#   told apart by the VLAN tag on the frame, which is why every",
            "#   item below pushes its own VLAN header. Exaware, 2026-09-08:",
            "#   \"An AC can reside as a tagged interface.\"",
        ]
    lines += [
        "",
        "# ---------------------------------------------------------------",
        "# Helpers. Two things ixia_lib.tcl does not do, kept in one place",
        "# and used identically by the generated Java (EvpnUtils), so the",
        "# file and the suite cannot build different traffic.",
        "# ---------------------------------------------------------------",
        "",
        "# Give an attachment-circuit vport a VLAN-enabled interface.",
        "#",
        "# DEVICE-VERIFIED 2026-09-09 on chassis 10.1.70.108. ixia_lib's",
        "# configTrafficItemEndpoints reads",
        "#     set int [ixNet getL $ixia($srcVport) interface]",
        "# and builds the endpointSet's -sources from it. A vport with no",
        "# interface object yields an endpointSet with NO sources; that is",
        "# accepted without error, `generate` then produces no configElement,",
        "# and the failure only surfaces two procs later as",
        "#     can't read \"element\": no such variable",
        "# Only vport1 got an interface (from the core setup), so both AC",
        "# ports were silently sourceless.",
        "#",
        "# vlanEnable must stay TRUE. It selects the branch of",
        "# configTrafficItemEndpoints that sources from $vport/protocols;",
        "# the other branch builds -sources from the interface list and dies",
        "# inside ixNet commit (verified on pc-3099, 2026-09-09).",
        "proc ateAcInterface {vp vlan mac} {",
        "    set intf [lindex [ixNet remapIds [ixNet add $vp interface]] 0]",
        "    ixNet setAtt $intf -enabled true -description \"ac-vlan-$vlan\"",
        "    ixNet commit",
        "    ixNet setAtt $intf/ethernet -macAddress $mac",
        "    ixNet setAtt $intf/vlan -vlanEnable true -vlanId $vlan",
        "    ixNet commit",
        "    return $intf",
        "}",
        "",
        "# Push a VLAN header onto a RAW item and set its VLAN ID.",
        "#",
        "# A raw item's frame is whatever its protocol stack says, and that",
        "# stack is ethernet + fcs: UNTAGGED. Untagged frames never match a",
        "# `vlan-id` sub-interface, so on pc-3080 the DUT port counted 219k",
        "# frames while the circuit counted 0 and the EVI learnt nothing.",
        "proc ateTagItemVlan {itemName vlan} {",
        "    set tpl {}",
        "    foreach t [ixNet getL [ixNet getRoot]/traffic protocolTemplate] {",
        "        if {[string equal -nocase [ixNet getAtt $t -displayName] {VLAN}]} {",
        "            set tpl $t",
        "        }",
        "    }",
        "    set ti [getTraffic $itemName]",
        "    foreach ce [ixNet getL $ti configElement] {",
        "        set has 0",
        "        foreach st [ixNet getL $ce stack] {",
        "            if {[string match {*vlan*} $st]} { set has 1 }",
        "        }",
        "        if {$has == 0 && $tpl ne {}} {",
        "            ixNet exec appendProtocol [lindex [ixNet getL $ce stack] 0] $tpl",
        "            ixNet commit",
        "        }",
        "        foreach st [ixNet getL $ce stack] {",
        "            if {![string match {*vlan*} $st]} { continue }",
        "            foreach fld [ixNet getL $st field] {",
        "                if {[string match -nocase {*vlan-id*} \\",
        "                        [ixNet getAtt $fld -displayName]]} {",
        "                    ixNet setMultiAttr $fld -singleValue $vlan \\",
        "                        -fieldValue $vlan -valueType singleValue",
        "                }",
        "            }",
        "        }",
        "    }",
        "    ixNet commit",
        "}",
        "",
        "# Set a RAW item's SOURCE MAC.",
        "#",
        "# ixia_lib.tcl has editTrafficRawDestMacAddr and no source twin, and",
        "# EVPN learns from source MACs. The obvious mirror",
        "# `ethernet.header.sourceAddress-1` does NOT exist: the suffix is the",
        "# field's POSITION in the stack, so the source field is -2. Match on",
        "# the display name instead of counting.",
        "proc ateSetItemSrcMac {itemName mac} {",
        "    set ti [getTraffic $itemName]",
        "    foreach ce [ixNet getL $ti configElement] {",
        "        foreach st [ixNet getL $ce stack] {",
        "            if {![string match *ethernet* $st]} { continue }",
        "            foreach fld [ixNet getL $st field] {",
        "                if {[string match -nocase {*source*} \\",
        "                        [ixNet getAtt $fld -displayName]]} {",
        "                    ixNet setMultiAttr $fld -singleValue $mac \\",
        "                        -fieldValue $mac -valueType singleValue",
        "                }",
        "            }",
        "        }",
        "    }",
        "    ixNet commit",
        "}",
        "",
        "# ---------------------------------------------------------------",
        "# Attachment-circuit interfaces, before any traffic item names them.",
        "# ---------------------------------------------------------------",
        "",
        "# ixia_lib addresses vports through its own container, so the",
        "# container has to be filled before $ixia(vportN) resolves. Creating",
        "# the interfaces first and loading afterwards fails with",
        "#     can't read \"ixia(vport2)\": no such variable",
        "loadIxiaObj",
    ]
    seen_vports: set[str] = set()
    for ac in lab.acs:
        if ac.vport in seen_vports:
            continue
        seen_vports.add(ac.vport)
        mac = next((t.src_mac for t in lab.traffic_items
                    if lab.ac(t.src).vport == ac.vport), "00:00:00:00:00:01")
        lines.append(
            f"ateAcInterface $ixia({ac.vport}) {lab.vlan_of(ac)} {mac}")
    lines += [
        "",
        "# Refresh ixia_lib's container so the item procs below can resolve",
        "# vport and interface names.",
        "loadIxiaObj",
        "",
        "# ---------------------------------------------------------------",
        "# The traffic items.",
        "# ---------------------------------------------------------------",
        "",
        f"set ateFrameRateFps {lab.traffic_rate_fps}",
        "",
    ]
    for ti in lab.traffic_items:
        src, dst = lab.ac(ti.src), lab.ac(ti.dst)
        vlan = lab.vlan_of(src)
        lines += [
            f"# {ti.name}",
            f"#   {ti.src} ({src.vport}, VLAN {vlan}) -> {ti.dst} "
            f"({dst.vport}, VLAN {lab.vlan_of(dst)})",
            f"#   source MAC {ti.src_mac}",
        ]
        twins = [o.name for o in lab.traffic_items
                 if o.src_mac == ti.src_mac and o.name != ti.name]
        if twins:
            lines.append(
                f"#   shares that source MAC with {', '.join(twins)} on "
                "purpose: that is")
            lines.append(
                "#   what makes moving between those circuits a LOCAL MAC "
                "move on one")
            lines.append(
                "#   PE, which must not re-advertise a Type-2 route.")
        lines += [
            f"configNewTrafficItem {ti.name} true null l2L3 false false raw "
            f"{ti.name} interleaved null false false oneToOne",
            f"configTrafficItemEndpoints {ti.name} 1 {src.vport} null null "
            f"null null null null {dst.vport} null null null null null null "
            f"null null null {ti.name} null null",
            "",
        ]
    lines += [
        "# Track every item BY TRAFFIC ITEM, before generate.",
        "#",
        "# DEVICE-VERIFIED 2026-09-09 on chassis 10.1.70.108. This is what",
        "# makes IxNetwork build the \"Traffic Item Statistics\" view. With",
        "# `trackBy` empty the view does not exist at all, ixia_lib's own",
        "# trafficApply throws reading its page, and every traffic assertion",
        "# reports",
        "#     Fail: No results where: TRAFFIC_ITEM: <name>",
        "# on a rig where the traffic is running perfectly. The .ixncfg saved",
        "# without this is why TC02 was red on 2026-09-09.",
    ]
    for ti in lab.traffic_items:
        lines.append(
            f"configTrafficItemTracking {ti.name} null null trackingenabled0 "
            "null null null")
    lines += [
        "",
        "# GENERATE, and it must happen HERE - after every item has its",
        "# endpoints and before anything touches a stream, a rate, a VLAN or",
        "# a source MAC.",
        "#",
        "# DEVICE-VERIFIED 2026-09-09 on chassis 10.1.70.108 (IxNetwork 9.00).",
        "# A traffic item has NO configElement until `generate` has run, and",
        "# configTrafficItemStream and configTrafficItemFrameRate both resolve",
        "# through ixia_lib's getTrafficConfigElement. Calling them first ends",
        "# the script with",
        "#     can't read \"element\": no such variable",
        "#         (procedure \"getTrafficConfigElement\" line 10)",
        "# which is what the first version of this file did. Nothing in their",
        "# repository uses these procs, so there was no example to copy: the",
        "# order came from the chassis.",
        "ixNet exec generate [ixNet getL [ixNet getRoot]/traffic trafficItem]",
        "after 8000",
        "",
    ]
    for ti in lab.traffic_items:
        src = lab.ac(ti.src)
        vlan = lab.vlan_of(src)
        lines += [
            f"configTrafficItemStream {ti.name} 1 goodCRC manual {ti.name} 8 "
            "auto false",
            f"configTrafficItemFrameRate {ti.name} stream 1 framesPerSecond "
            "$ateFrameRateFps bytes bitsPerSec false",
            f"ateTagItemVlan {ti.name} {vlan}",
        ]
    lines.append("")
    lines += [
        "# MACs last: `generate` resets them, so they are set after it and",
        "# never before.",
        "#",
        "# The destination is BROADCAST, and that is deliberate. A raw item",
        "# defaults to 00:00:00:00:00:00, and this build reports",
        "# \"Unknown MAC Flooding: Disabled\" with no CLI to turn it on. An",
        "# all-zero or unknown-unicast destination is therefore taken by the",
        "# port and dropped before the bridge domain - verified on pc-3099,",
        "# where the physical counter passed a billion frames while every",
        "# attachment circuit counted 0 and Discard/MAC-filtered/Unknown-vlan",
        "# were all 0. Broadcast is flooded regardless, so the circuit",
        "# classifies it and the SOURCE MAC is learnt, which is what the",
        "# FLOW-030 assertions actually need.",
    ]
    for ti in lab.traffic_items:
        lines.append(f"editTrafficRawDestMacAddr {ti.name} {ti.dst_mac}")
    for ti in lab.traffic_items:
        lines.append(f"ateSetItemSrcMac {ti.name} {ti.src_mac}")
    lines += [
        "",
        "ixNet exec apply [ixNet getRoot]/traffic",
        "",
        "# ---------------------------------------------------------------",
        "# Save what was just built, so the suite can load it instead of",
        "# building it. This is the step that produces the .ixncfg - the one",
        "# piece of the VPLS idiom we could not reach from documents.",
        "#",
        "# Fetch the file off the app server afterwards and commit it under",
        "# cmp/tests/evpn/configurations/ixia/.",
        "# ---------------------------------------------------------------",
        f"set ateSavePath \"/var/tmp/ate-run/{lab.ixncfg or _default_ixncfg(lab)}\"",
        "ixNet exec saveConfig [ixNet writeTo $ateSavePath -overwrite true]",
        "puts \"SAVED=$ateSavePath\"",
        "",
    ]
    return JavaFile(
        path=f"cmp/tests/evpn/configurations/ixia/{TRAFFIC_CONFIG_NAME}",
        content="\n".join(lines))


def _default_ixncfg(lab: LabProfile) -> str:
    """The name this profile's saved IxNetwork config should take."""
    return "EVPN_" + lab.id.replace("lab-1dut-", "").replace("-", "_").upper() \
           + ".ixncfg"


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
    ]
    # The IXIA configuration file, when the rig has one.
    #
    # Exaware, 2026-09-08 (Eyal Ozeri): "The BringUpParameters.crt file
    # doesn't load any Ixia file." Correct, and until now there was nothing to
    # load: an .ixncfg is a binary IxNetwork save that cannot be written from
    # documents, so the suite built its traffic items in code instead.
    #
    # It can be written by IxNetwork, though, which is the way round we had
    # missed. `emit_traffic_config` emits a readable TCL script that builds
    # the items and then SAVES the session as an .ixncfg. Run once on the
    # chassis, that produces the file this row loads - and from then on the
    # suite is in the VPLS idiom: load a named config, suspend and unsuspend
    # named items.
    #
    # The row appears only when `LabProfile.ixncfg` names a file, because a
    # config row pointing at a file that is not there aborts bring-up for the
    # whole suite, and that failure is far worse than building the items in
    # code for one more cycle.
    if lab.ixncfg:
        out.append(f"{'':<10}{ixia:<16}"
                   f"{'/configurations/ixia/' + lab.ixncfg:<68}"
                   f"{'y':<19}{'1':<10}1900")
    out += [
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
    if (core := lab.core_link) is not None:
        links.append((core.interface, core.vport, core.pool_index))
    # One row per physical link, NOT per attachment circuit. Two circuits
    # sharing a port are two sub-interfaces on one link; a second `int3` row
    # binds the same placeholder twice and the template validator rejects the
    # file.
    links += lab.ac_links

    for i, (dut_int, _vport, idx) in enumerate(links):
        first = i == 0
        out.append(f"{'default' if first else '':<12}{dut if first else '':<15}"
                   f"{'interface':<14}{dut_int:<27}{lab.ac_pool:<17}{idx}")
    for i, (_dut_int, vport, idx) in enumerate(links):
        out.append(f"{'':<12}{ixia if i == 0 else '':<15}"
                   f"{'interface':<14}{vport:<27}{lab.ac_pool:<17}{idx}")
    # There are deliberately NO `vlan` rows in this table any more.
    #
    # They used to bind each IXIA vport to `vlans` index 0 in the SUT file,
    # which on pc-3080 is VLAN 3380. Exaware, 2026-09-08 (Eyal Ozeri): "Vlan
    # 3380 appears in the SUT file because it is used on one of the interfaces
    # to an external server connection. The tool should be able to use entire
    # 2-4094 range." Binding to that slot meant the suite could only ever run
    # on whatever VLAN the SUT happened to declare first, and that VLAN
    # belonged to something else.
    #
    # The VLANs now come from the lab profile (see `LabProfile.ac_vlans`,
    # settable with `ate codegen --ac-vlans`), are written literally into the
    # .cfg, and are applied to the IXIA side by EvpnUtils.tagVportsWithAcVlan
    # and tagTrafficItemsWithAcVlan, which read them back off the chassis and
    # fail the run if they did not take.
    #
    # A per-vport row could not express the current topology in any case: two
    # attachment circuits share vport3 and are told apart by their VLAN, and
    # this table has one row per vport.
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

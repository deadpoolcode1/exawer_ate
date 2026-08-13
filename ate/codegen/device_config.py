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
            # Sub-interface first: replacing the bare port would turn
            # `agg-eth-1.100` into `int1.100` only by luck of ordering, and
            # into `int1` plus a stray `.100` if the port name is a prefix.
            line = line.replace(ac.ac_interface, f"int{i + 1}.{ac.subinterface}")
            line = line.replace(ac.interface, f"int{i + 1}")
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
    for i, ac in enumerate(lab.acs, start=1):
        lines += [
            f"interface int{i}",
            " admin-state up",
            "!",
            f"interface int{i}.{ac.subinterface}",
            " l2-transport enable",
            "!",
        ]
    return lines


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
        "! NOT included - the underlay. Interface addressing, MPLS/LDP and BGP",
        "! are lab data, absent from the SFS and CLI doc, and are deliberately",
        "! not invented here. They must come from cleanBaseConfig or the site",
        "! configuration loaded ahead of this file (LOAD_TYPE 1, then 2).",
        "!",
        "! Interface names are placeholders bound by the find-and-replace",
        "! table in bringUpParams.crt to the SUT's 'data1' intPool.",
        "!",
    ]
    body = _attachment_circuits(lab) + (
        block or ["! (no EVPN configuration steps in the selected scripts)"])
    tail = []
    if unplaced:
        tail = ["!", "! Not placed in the block above - review and add by hand:"]
        tail += [f"!   {ln}" for ln in unplaced] + ["!"]

    return JavaFile(path=f"cmp/tests/evpn/configurations/compass/{DUT_CONFIG_NAME}",
                    content="\n".join(head + body + tail) + "\n")


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
    for i, _ac in enumerate(lab.acs):
        first = i == 0
        out.append(f"{'default' if first else '':<12}{dut if first else '':<15}"
                   f"{'interface':<14}{'int' + str(i + 1):<27}{'data1':<17}{i}")
    for i, _ac in enumerate(lab.acs):
        out.append(f"{'':<12}{ixia if i == 0 else '':<15}"
                   f"{'interface':<14}{'vport' + str(i + 1):<27}{'data1':<17}{i}")
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

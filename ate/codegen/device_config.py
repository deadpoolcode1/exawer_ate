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
not trace to the EVPN CLI doc. The *hierarchy* is derived mechanically from the
flat command text, and is marked unverified — we have never seen `show
configuration` from a device that runs EVPN, so its exact block structure and
terminators are unconfirmed.
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
            line = line.replace(ac.interface, f"int{i + 1}")
        out.append(line)
    return out


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
        "! UNVERIFIED: the block structure and '!' terminators are derived",
        "! mechanically from flat command syntax. No device that implements",
        "! EVPN has been available to confirm them against real 'show",
        "! configuration' output, so review before first use.",
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
    body = block or ["! (no EVPN configuration steps in the selected scripts)"]
    tail = []
    if unplaced:
        tail = ["!", "! Not placed in the block above - review and add by hand:"]
        tail += [f"!   {ln}" for ln in unplaced] + ["!"]

    return JavaFile(path=f"cmp/tests/evpn/configurations/compass/{DUT_CONFIG_NAME}",
                    content="\n".join(head + body + tail) + "\n")


def _col(*pairs: tuple[str, int]) -> str:
    return "".join(text.ljust(width) for text, width in pairs).rstrip()


def emit_bringup_params(scripts: list[TestScript], lab: LabProfile) -> JavaFile:
    """`bringUpParams.crt` — devices, per-test config files, ping and actions."""
    dut, ixia = "cmp1", "ixia1"
    cfg = f"/configurations/compass/{DUT_CONFIG_NAME}"

    out: list[str] = [
        "//full topology for suite, devices names and types:",
        "",
        _col(("DEVICE_NAME", 16), ("CLASS", 40)),
        "-" * 56,
        _col((dut, 16), ("cmp.infra.CmpRouter", 40)),
        _col((ixia, 16), ("cmp.infra.ixia.Ixia", 40)),
        "",
        "//connect devices topology for each TC",
        "",
        _col(("TEST", 9), ("DEVICES_TOPOLOGY", 40)),
        "-" * 49,
        _col(("default", 9), (f"{dut}, {ixia}", 40)),
        "",
        "//devices names and configuration files parameters: 1= override, 2 = merge",
        "",
        _col(("TEST", 10), ("DEVICE_NAME", 16), ("CONFIG_FILE_PATH", 68),
             ("LOAD_ON_BRING_UP", 19), ("LOAD_TYPE", 14), ("TIMEOUT_SEC", 12)),
        "-" * 139,
        _col(("default", 10), (dut, 16), ("cleanBaseConfig", 68),
             ("y", 19), ("1", 14), ("1900", 12)),
        _col(("", 10), ("", 16), (cfg, 68), ("y", 19), ("2", 14), ("1900", 12)),
        "",
        "// The IXIA configuration is COMMENTED OUT on purpose. A .ixncfg is a",
        "// binary IxNetwork save and cannot be generated from documents; the",
        "// three traffic items this suite needs (AC2 and AC3 sourcing the same",
        "// MACs, so AC2->AC3 is a pure local MAC move) must come from Exaware.",
        "// A row here pointing at a file that does not exist aborts bring-up",
        "// for the whole suite, so it stays commented until the file lands.",
        f"//        {ixia}           /configurations/ixia/{_IXIA_CONFIG_NAME}",
        "",
        "//devices ping lists, relevant for all the tests",
        "",
        _col(("TEST", 14), ("DEVICE_NAME", 15), ("PING_IP", 22),
             ("PING_DESCRIPTION", 46), ("PING_SUCCEES_THRESHOLD", 27),
             ("PING_RETRY_NUMBER", 20), ("PING_VRF_NAME", 14)),
        "-" * 158,
        "// Left empty: the AC-side addressing is lab data we do not have.",
        "// VPLS's equivalent table pings the IXIA vport addresses from the DUT.",
        "",
        "//find and replace parameters on devices cfg files and ixia vlan's "
        "configuration, relevant for all tests",
        "",
        _col(("TEST", 12), ("DEVICE_NAME", 15), ("TYPE", 14),
             ("FIND_PARAM", 27), ("INTPOOL_NAME", 17), ("INTPOOL_INDEX", 14)),
        "-" * 100,
    ]

    first = True
    for i, _ac in enumerate(lab.acs):
        out.append(_col(("default" if first else "", 12), (dut if first else "", 15),
                        ("interface", 14), (f"int{i + 1}", 27),
                        ("data1", 17), (str(i), 14)))
        first = False
    for i, _ac in enumerate(lab.acs):
        out.append(_col(("", 12), (ixia if i == 0 else "", 15),
                        ("interface", 14), (f"vport{i + 1}", 27),
                        ("data1", 17), (str(i), 14)))

    out += [
        "",
        "//before after table:",
        "",
        _col(("TEST", 10), ("DEVICE_NAME", 14), ("ID_ACT", 23),
             ("ACTION_DESCRIPTION", 35), ("ACTION_PARAMS", 66),
             ("DO_BEFORE_TEST", 18), ("DO_AFTER_TEST", 14)),
        "-" * 180,
        _col(("default", 10), ("test", 14), ("loadTestParamFile", 23),
             ("loading suite parameters class", 35),
             ("cmp.tests.evpn.EvpnParams", 66), ("y", 18), ("n", 14)),
        _col(("", 10), (dut, 14), ("verifyLCs", 23),
             ("verify LCs are card ready state", 35), ("", 66),
             ("y", 18), ("y", 14)),
        _col(("", 10), ("", 14), ("verifyInts", 23),
             ("verify interfaces are up", 35), ("", 66), ("y", 18), ("n", 14)),
        _col(("", 10), (ixia, 14), ("startProtocols", 23),
             ("start protocols", 35), ("", 66), ("y", 18), ("n", 14)),
        _col(("", 10), ("", 14), ("sendArpAllPorts", 23),
             ("send arp for all ports", 35), ("", 66), ("y", 18), ("n", 14)),
        "",
    ]
    return JavaFile(path="cmp/tests/evpn/bringUpParams.crt",
                    content="\n".join(out))

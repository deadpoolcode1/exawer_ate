"""Capabilities proven on hardware — and the ratchet that stops them regressing.

Why this module exists, stated plainly, because it is a rule with a cost and
nobody should have to guess what it is buying.

On 2026-08-13 Exaware reported: *"you configured ospf on the device, but not on
the Ixia."* That was fixed properly. `CoreLink` was added, both ends of the core
link were rendered from one profile, and the result was verified on pc-3080 —
OSPF reached FULL with the IXIA-emulated router, LDP came up, and the BGP
session reached `Established`.

On 2026-08-14 the hand-over suite was generated with `--lab 3ac`, so that a
third attachment circuit existed and FLOW-030's local MAC move could run. That
profile has no core link. Three emitters answered the absence with `[]` or
`None`, the symmetry guard in `lab.underlay_symmetry_violations` returned `[]`
because it only checks that two ends *agree* and never that either exists, and
the package shipped with no IGP, no LDP and no BGP on either side.

The client reported the same defect twice. The second time it was a capability
we had already built, already proven on hardware, and then silently dropped.

So: a capability, once proven on real hardware, may not disappear from a
generated artifact without somebody saying so out loud. This is the
generation-side twin of the fake-pass rule in `fake_pass.py` — there, "the call
returned without error" is not evidence it did anything; here, **an emitter
returning nothing is a claim that must be justified, not a fallthrough.**

## How it works

Every capability carries a `detector` that reads the *emitted artifacts* — not
the lab profile, not a flag, not the pipeline's exit code. That matters: the
2026-08-14 regression had a perfectly healthy pipeline that exited zero. Only
the files were wrong, so the files are what get checked.

A capability with a `Proof` is a ratchet. If its detector fails, generation
raises. The escape hatch is deliberate and narrow: `--accept-regression <id>`
names each capability being given up, one at a time, in the command line. It
exists because the 3-AC spec topology is still a legitimate thing to generate
locally — the rig has three DUT<->IXIA links and cannot serve three attachment
circuits *and* a core link, so somebody has to choose.

What it must never do is choose silently. `scripts/verify_handover_package.py`
re-runs these same detectors against the files actually inside a client package
and has **no** escape hatch, so an accepted regression can be generated but
cannot be shipped.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

__all__ = [
    "CAPABILITIES",
    "Capability",
    "CapabilityRegressionError",
    "Proof",
    "Regression",
    "capability",
    "control_plane_violations",
    "regressions",
]


@dataclass(frozen=True)
class Proof:
    """Where and when a capability was observed working on real hardware.

    Not decoration. The date and build are what make a later regression
    arguable rather than a matter of memory, and `evidence` names the file a
    reviewer opens to check the claim rather than trusting this table.
    """

    host: str
    build: str
    date: str          # ISO, the day it was observed
    evidence: str      # path under deliverables/, relative to the repo root
    observed: str      # the actual line that was read off the device


@dataclass(frozen=True)
class Capability:
    """One thing the generated suite is able to do.

    `detector` is given a {path: content} view of every emitted artifact and
    answers whether the capability survives in *those files*.
    """

    id: str
    description: str
    detector: Callable[[Mapping[str, str]], bool]
    #: `None` means "never proven on hardware" — aspirational, not ratcheted.
    proof: Proof | None = None

    @property
    def is_ratcheted(self) -> bool:
        return self.proof is not None


@dataclass(frozen=True)
class Regression:
    """A proven capability that the emitted artifacts no longer deliver."""

    capability: Capability

    def __str__(self) -> str:
        p = self.capability.proof
        assert p is not None
        return (f"{self.capability.id}: {self.capability.description}\n"
                f"      proven {p.date} on {p.host} ({p.build}): {p.observed}\n"
                f"      evidence: {p.evidence}")


class CapabilityRegressionError(RuntimeError):
    """Raised when generation would drop something already proven to work."""


# ---------------------------------------------------------------------------
# Artifact accessors. Detectors read files by suffix rather than by full path
# so they keep working if the emitter's output root moves.
# ---------------------------------------------------------------------------

def _file(files: Mapping[str, str], suffix: str) -> str:
    for path, content in files.items():
        if path.endswith(suffix):
            return content
    return ""


def _dut_cfg(files: Mapping[str, str]) -> str:
    return _file(files, "EVPN_Base.cfg")


def _tester_tcl(files: Mapping[str, str]) -> str:
    return _file(files, "evpn_tester_setup.tcl")


def _utils(files: Mapping[str, str]) -> str:
    return _file(files, "EvpnUtils.java")


# ---------------------------------------------------------------------------
# Detectors
#
# Each asserts BOTH ends where both ends exist. A DUT-only check would have
# passed happily on 2026-08-13, which is the exact defect Exaware reported.
# ---------------------------------------------------------------------------

def _has_igp(files: Mapping[str, str]) -> bool:
    dut = re.search(r"^routing (ospf|isis)\b", _dut_cfg(files), re.M)
    tcl = _tester_tcl(files)
    tester = "protocols/ospf" in tcl or "protocols/isis" in tcl
    return bool(dut) and tester


def _has_mpls_transport(files: Mapping[str, str]) -> bool:
    dut = re.search(r"^mpls ldp\b", _dut_cfg(files), re.M)
    return bool(dut) and "protocols/ldp" in _tester_tcl(files)


def _has_bgp_session(files: Mapping[str, str]) -> bool:
    cfg = _dut_cfg(files)
    dut = (re.search(r"^routing bgp\b", cfg, re.M)
           and re.search(r"^\s+neighbor\s+\d", cfg, re.M))
    return bool(dut) and "protocols/bgp" in _tester_tcl(files)


def _has_evpn_address_family(files: Mapping[str, str]) -> bool:
    # DUT side only, deliberately. The tester half cannot be built: chassis
    # 10.1.70.108 answers ERROR-1005 "no license available for BGP EVPN".
    return bool(re.search(r"^\s+af-l2vpn evpn\b", _dut_cfg(files), re.M))


def _has_vlan_classified_acs(files: Mapping[str, str]) -> bool:
    """Both halves of the 2026-08-14 fix, which had two independent causes.

    A sub-interface without `vlan-id` is admin-up, is listed by `show evpn
    detail` as a bound AC, and classifies nothing; and a raw traffic item's
    frame is its protocol stack, which is untagged unless a VLAN header is
    pushed onto it. Either one alone leaves the circuit counting zero while
    the port counts hundreds of thousands of frames.

    The `vlan-id` match is deliberately loose about its argument so that
    switching between a SUT-bound placeholder and a literal VLAN — an open
    question with Exaware as of 2026-08-16 — does not read as a regression.
    """
    dut = re.search(r"^\s+vlan-id\s+\S+", _dut_cfg(files), re.M)
    return bool(dut) and "tagTrafficItemsWithAcVlan" in _utils(files)


def _has_source_mac_control(files: Mapping[str, str]) -> bool:
    return "setTrafficItemSourceMac" in _utils(files)


def _has_three_acs(files: Mapping[str, str]) -> bool:
    """Three attachment circuits are bound to the EVI.

    This is Exaware's E4 of 2026-09-08 - "TC02 which is declared as a passed
    TC is missing" - expressed as a ratchet. TC02 is FLOW-030's MAC move and
    it needs a third circuit; the suite lost it when the topology went to
    `2ac-core`, because one of the rig's three links was spent on the core.

    Counted from the `.cfg`'s own EVI binding lines rather than from the lab
    profile, for the reason the whole module exists: the profile is an input,
    and the 2026-08-14 regression was three emitters agreeing with a profile
    that had quietly lost its core link.
    """
    cfg = _dut_cfg(files)
    bound = re.findall(r"^!?\s*l2-services evpn \S+ interface (\S+)", cfg, re.M)
    return len(set(bound)) >= 3


# ---------------------------------------------------------------------------
# The register. Adding an entry with a Proof is how a hardware win gets locked
# in; adding one without is how a target gets recorded before it is met.
# ---------------------------------------------------------------------------

_UNDERLAY_EVIDENCE = "deliverables/M2/evidence_underlay_and_ixia_peer.txt"
_GREEN_EVIDENCE = "deliverables/M2/evidence_three_suites_green.txt"
_SHARED_PORT_EVIDENCE = "deliverables/M2/evidence_shared_port_acs.txt"

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        id="underlay.igp",
        description=("the DUT runs an IGP across the core link and the tester "
                     "answers it, so the remote PE loopback is reachable"),
        detector=_has_igp,
        proof=Proof(host="pc-3080", build="8.7.0 LAB 22", date="2026-08-13",
                    evidence=_GREEN_EVIDENCE,
                    observed="OSPF reaches FULL with the IXIA-emulated router"),
    ),
    Capability(
        id="underlay.mpls",
        description=("LDP is up across the core link, so the EVPN service has "
                     "a transport label"),
        detector=_has_mpls_transport,
        proof=Proof(host="pc-3080", build="8.7.0 LAB 22", date="2026-08-13",
                    evidence=_UNDERLAY_EVIDENCE,
                    observed="mpls ldp default, router-id 29.30.30.30"),
    ),
    Capability(
        id="underlay.bgp",
        description=("a BGP session exists between the DUT and the tester, so "
                     "there is a control plane to carry Type-2/Type-3 routes"),
        detector=_has_bgp_session,
        proof=Proof(host="pc-3080", build="8.7.0 LAB 22", date="2026-08-13",
                    evidence=_UNDERLAY_EVIDENCE,
                    observed=("BGP peer: 29.60.0.2 ... BGP state: Established "
                              "(up for: 56s)")),
    ),
    Capability(
        id="underlay.bgp_evpn_af",
        description=("the BGP neighbour carries the EVPN address family on the "
                     "DUT side (the tester side needs a chassis licence)"),
        detector=_has_evpn_address_family,
        proof=Proof(host="pc-3080", build="8.7.0 LAB 22", date="2026-08-13",
                    evidence=_UNDERLAY_EVIDENCE,
                    observed="L2VPN EVPN table listed for neighbor 29.60.0.2"),
    ),
    Capability(
        id="traffic.vlan_classified",
        description=("attachment circuits carry `vlan-id` and traffic items "
                     "carry a VLAN header, so offered frames are classified "
                     "onto the circuit instead of counted only by the port"),
        detector=_has_vlan_classified_acs,
        proof=Proof(host="pc-3080", build="8.7.0 LAB 22", date="2026-08-14",
                    evidence=_GREEN_EVIDENCE,
                    observed="ACVLAN=3380/true, VLANTAGGED=30 / 33"),
    ),
    Capability(
        id="traffic.source_mac",
        description=("a traffic item's source MAC can be set, which is what "
                     "makes AC2 -> AC3 a local MAC move rather than two hosts"),
        detector=_has_source_mac_control,
        proof=Proof(host="pc-3080", build="8.7.0 LAB 22", date="2026-08-14",
                    evidence=_GREEN_EVIDENCE,
                    observed="SRCMAC=00:00:02:00:00:01 SET=2"),
    ),
    Capability(
        id="topology.three_acs",
        description=("three attachment circuits are bound to the EVI, so "
                     "FLOW-030's MAC move - TC02 - can be generated at all"),
        detector=_has_three_acs,
        proof=Proof(host="pc-3080", build="8.7.0 LAB 0", date="2026-09-09",
                    evidence=_SHARED_PORT_EVIDENCE,
                    observed=("Local Interfaces: x-eth0/0/22.2001 and "
                              "x-eth0/0/22.2002 - two sub-interfaces of ONE "
                              "port accepted as two ACs of one vlan-based "
                              "EVI, so three ACs fit on the rig's two "
                              "non-core links")),
    ),
)


def capability(cap_id: str) -> Capability:
    for c in CAPABILITIES:
        if c.id == cap_id:
            return c
    raise KeyError(f"no capability {cap_id!r}; known: "
                   + ", ".join(c.id for c in CAPABILITIES))


def regressions(files: Mapping[str, str]) -> list[Regression]:
    """Proven capabilities these artifacts no longer deliver.

    `files` is {path: content} over everything generation emitted.
    """
    return [Regression(c) for c in CAPABILITIES
            if c.is_ratcheted and not c.detector(files)]


def control_plane_violations(scripts, lab) -> list[str]:
    """Steps that assert a BGP-carried route on a rig with no BGP session.

    A `VERIFY_ROUTE` step reads a Type-2 or Type-3 route out of a BGP table.
    Run against a profile with no core link there is no BGP session at all, so
    the command answers with an empty table or a bare legend — and an
    expectation built from that passes on a working device and a broken one
    alike. That is the fake-pass rule arriving through the topology rather than
    through a capture, and it is why TC01 shipped asserting origination into
    the local EVI table while its own step title read "(no BGP peer on this
    rig)".

    Kept separate from the capability ratchet on purpose: the ratchet asks
    "did we lose something we had", this asks "does this suite make a claim
    this rig cannot support". A brand-new flow with no history trips this one.
    """
    from ate.codegen.lab import bgp_capable  # noqa: PLC0415

    if bgp_capable(lab):
        return []
    from ate.codegen.script_ir import StepKind  # noqa: PLC0415

    return [
        f"{s.id} ({s.text}) asserts a BGP-carried route, but lab profile "
        f"{lab.id!r} has no BGP session for it to arrive on"
        for script in scripts for s in script.steps
        if s.kind is StepKind.VERIFY_ROUTE
    ]

"""Which testbed the lab helpers talk to.

Every script here was written against pc-3099 and carried its addresses as
literals. On 2026-09-16 the reserved rig was pc-3080 and six files had to be
edited to move, which is how a rig change turns into a source change and
eventually into a package generated for the wrong testbed.

The addresses follow the site's own pattern: rig NNNN is `10.3.NN.1` for the
DUT and `10.3.NN.10` for its ONL host, and the SUT file Exaware ships is
`pcNNNN.xml`. Selected with:

    export ATE_RIG=3080        # or 3099

There is deliberately no default. A helper that reboots a router should never
guess which router.
"""
from __future__ import annotations

import os


def rig() -> str:
    name = os.environ.get("ATE_RIG", "").strip()
    if not name:
        raise SystemExit(
            "ATE_RIG is not set. Export the reserved rig first, e.g.\n"
            "    export ATE_RIG=3080\n"
            "There is no default: these scripts reboot a router.")
    if not (name.isdigit() and len(name) == 4):
        raise SystemExit(f"ATE_RIG={name!r} is not a 4-digit rig number")
    return name


def dut_ip() -> str:
    """The DUT's management address, e.g. 10.3.80.1 for rig 3080."""
    return f"10.3.{int(rig()[2:])}.1"


def onl_ip() -> str:
    """The ONL host behind the DUT, e.g. 10.3.80.10 for rig 3080."""
    return f"10.3.{int(rig()[2:])}.10"


def sut_file() -> str:
    """Exaware's SUT file for this rig, e.g. pc3080.xml."""
    return f"pc{rig()}.xml"

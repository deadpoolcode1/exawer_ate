# Lab validation: pc-3099, 2026-09-09

What was run on hardware, what it proved, and what it did not.

| | |
|---|---|
| DUT | `exa-il01-ec-3099`, 10.3.99.1 |
| Build | `8.7.0: LAB 935` |
| SUT file | `pc3099.xml` (Exaware's own) |
| Lab profile | `lab-1dut-3ac-core` (`ate codegen --lab 3ac-core`) |
| Runner | JUnitCore, Exaware `cmp-infra` + `cmp-tests` classes, JDK 17 `--release 8` |
| Chassis | 10.1.70.108, IxNetwork app server 10.1.90.108 |

## The rig, read out of Exaware's own SUT file

The DUT and IXIA `data1` pools pair index by index. No guesswork and no
question to the lab owner was needed:

| | DUT port | IXIA vport |
|---|---|---|
| Core (L3, OSPF, LDP, BGP) | `x-eth 0/0/18` | vport1 |
| AC1 | `x-eth 0/0/32` | vport2 |
| AC2 and AC3 | `x-eth 0/0/40` | vport3 |

pc-3080 pairs `0/0/8, 0/0/18, 0/0/26` onto the same three vports. The two rigs
are cabled differently, which is why `bringUpParams.crt` binds by intPool
index and never by port name. The generated package ran unchanged on a rig it
had never seen.

## What the device confirmed

TC01: **`OK (1 test)`**, no failures.

Read back from the device immediately afterwards:

```
EVPN name: evi-1                  Service Type: vlan-based
Export-rt: 65000:1                Import-rt: 65000:1
Local Interfaces:
INTERFACE         ESI    ES LABEL
x-eth0/0/32.1001  -      -
x-eth0/0/40.1002  -      -
x-eth0/0/40.1003  -      -
```

Four review points from 2026-09-08 close on that one output:

1. **The service is created by the test, not by the configuration file.**
   `EVPN_Base.cfg` no longer contains the EVI; TC01 asserts it absent, creates
   it, and asserts it present.
2. **Three attachment circuits.** So FLOW-030 (TC02) exists again.
3. **Two circuits share one physical port**, `x-eth 0/0/40`, separated only by
   VLAN tag. Three circuits and a control plane fit on three links.
4. **The VLANs are 1001-1003**, chosen by the generator. pc-3099's SUT
   declares `general/vlans` index 0 = **3399**, the same shape as pc-3080's
   3380, and the run asserts it does not touch it:
   `Pass: AC1: VLAN 1001 is not claimed by the SUT.`

All interfaces came up: `x-eth0/0/18`, `x-eth0/0/32`, `x-eth0/0/32.1001`,
`x-eth0/0/40`, `x-eth0/0/40.1002`, `x-eth0/0/40.1003`.

## What it did not prove

**The control plane is configured but not established.** The DUT holds the
neighbour and both address families:

```
NEIGHBOR   STATE  PEER AS  AFI/SAFI    STATE
29.60.0.2  down   3029     IPv4u       Active
                           L2VPNevpn   Active
```

It is down because nothing answers on the far end: bring-up loads no IXIA
configuration, so the tester side of the core link was never built. That is
the open review point about `bringUpParams.crt` not loading an IXIA file, and
it is also why TC02 stops at

```
vport2: VLAN 1001 was NOT enabled
(chassis said can't read "ixia(vport2)": no such variable)
```

Every DUT-side step of TC02 passes. One run of
`configurations/ixia/EVPN_traffic.tcl` on the chassis produces the `.ixncfg`
that closes it.

Until then, 16 of 23 verification steps warn rather than assert, and the
suite says so in its own output rather than passing quietly.

## Two defects the run found

Neither was findable by reading code, which is the argument for running on
hardware in two sentences.

**1. A test relied on another test's leftovers.** TC02 failed with `Missing
lines: [evi-1]` straight after a green TC01. `CmpTestCase.initCmpTestCase` is
an `@Before` and `BringUp.bringUpSetupAndVerify` calls `loadConf()`
unconditionally, so `EVPN_Base.cfg` is reloaded before every test method. The
EVI TC01 created was gone before TC02's first assertion. Each test now creates
the EVI it uses, after asserting it absent.

**2. An expectation contained a placeholder interface name.** The next run
failed with `Missing lines: [agg-eth-2.1001, agg-eth-3.1002, agg-eth-3.1003]`
against a device that had all three circuits bound correctly. `agg-eth-2` is
the lab profile's placeholder, which the SUT rebinds at bring-up, so that
assertion could never pass on any testbed. Expected lines that name a circuit
are now resolved on the device.

## A finding for Exaware, unrelated to this suite

**pc-3080 cannot complete Exaware's own bring-up on its current image.** It
was re-imaged to `8.7.0: LAB 0` and bring-up ends at:

```
Failed to enter specific session mode. Wanted mode: ONL, Current mode: CLI
```

`CmpCliSession.java:69` matches the ONL shell by the literal string
`"@localhost"`. On this image the ONL prompt is `root@router`. The same test
on the same box on 2026-08-13 logged `root@localhost` 78 times; on 2026-09-09
it logged it zero times. `checkCoresAndAlarms()` is called unconditionally
from `bringUpSetupAndVerify()`, so no parameter skips it.

This affects any suite run on that image, not only this one. pc-3099 (LAB 935)
is unaffected.

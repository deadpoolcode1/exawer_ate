# ATE — Project Status

**SOW:** PQ4476E — AI-Assisted Test Plan & Automation Skeleton Generator (10 weeks, 5 milestones)
**Updated:** 2026-08-13

## Milestones

| MS | Topic | Weeks | Pay | Status |
|---|---|---|---|---|
| M1 | Test Plan Generation | 1–2 | 15% | ✅ Delivered — plan reviewed across 6 client rounds |
| M2 | Dirty Queue & Code Generation | 3–4 | 15% | ✅ Complete — tagged `m2-delivery`, not yet invoiced |
| M3 | AI Test Plan Generation (multi-router) | 5–6 | 30% | ⬜ Not started |
| M4 | Code Generation (10 use cases) | 7–8 | 20% | ⬜ Not started |
| M5 | Web UI & Deployment | 9–10 | 20% | ⬜ Not started |

## The pipeline, end to end

```
documents → requirements → test plan (xlsx)          ← M1
          → typed steps → Java + DUT config          ← M2
          → run on a real device → fix → regenerate  ← M2, the device loop
```

Every stage is automated and has a command. Full architecture in `docs/TDD.md` §10.

| Stage | Command | Status |
|---|---|---|
| Parse documents → requirements | `ate plan-feature EVPN` | ✅ 133 reqs |
| Requirements → test plan | (same) | ✅ 269 plan rows / 698 action rows |
| Plan rows → typed steps | `ate match` | ✅ 537/612 = 87.7% |
| Steps → Java suite | `ate codegen` | ✅ compiles, `-Werror -Xlint:all` |
| Steps → DUT config | (same) | ✅ `.crt` passes their own validator |
| Test selection | `ate queue` | ✅ dirty queue |
| **Verify commands on a device** | `ate verify-commands` | ✅ 123 templates; **both halves now trustworthy** |
| **Capture real expectations** | `ate capture` | ✅ 2 usable, 9 empty, 0 unsupported — **not yet fed back into the code** |
| **Run the suite on the DUT** | `javac` + JUnit/JSystem | ✅ **TC01/02/03 all run green on pc-3080** (assert little — see limits) |
| Build IXIA traffic items | `ate codegen` | ✅ in code, no `.ixncfg` (src MAC still blocked) |

## M2 — SOW bullets

| SOW bullet | Status |
|---|---|
| Code generation from selected tests | ✅ TC01/TC02/TC03 via the dirty queue |
| Pattern matching | ✅ 537/612 rows (87.7%) typed |
| Demo: extract requirements from docs | ✅ 133 reqs → 269 plan rows |
| Up to 3 integration-ready test plans | ✅ compile against the real framework |

Gates: 953 sources → 1454 classes, 0 errors; generated files pass `-Werror -Xlint:all`;
`bringUpParams.crt` passes `TemplateManager.validateAgainstTemplate`. 275 ATE tests pass.

## The device loop — why it exists

"Grounded in the documents" is necessary and **not sufficient**. Two SUTs have
now overturned decisions we had reasoned to from the specs.

| We had | The device says |
|---|---|
| `show evpn mac address-table` | **`mac-address-table`** (hyphen) |
| `clear evpn mac-address-table` | **`mac address-table`** (space) — the product uses *both*, per command |
| `show evpn global` | no such command — `summary` / `detail` |
| `l2-services evpn <n> import-rt` | lives under `auto-discovery` |
| A vlan-based EVI binds the AC port | **it refuses** — the AC must be a sub-interface |
| `l2-services evpn <n>` has ~9 knobs | **five**: `auto-discovery`, `interface`, `mac-aging-time`, `mac-limit`, `service-type` |
| `interface … ethernet-segment …` | no `ethernet-segment` node at all on LAB 22 |
| `mac-limit` default 250000 | range `<1-250000>`, **default 65520** |

**Device output outranks any number of agreeing documents.** Detail in
`deliverables/M2/evidence_device_verified.txt` and `lab_validation_pc3080.md`.

Any claim about the build must name the build: pc-3021 was re-imaged mid-session
(LAB 904 → LAB 22), and pc-3080 runs LAB 22 / `feature/dev64_evpn_23Jul2026`.

## The suites run on hardware — and what that is worth

On **pc-3080** (`exa-il01-uf-3080`), **all three** suites complete under
JUnit + JSystem: `OK (1 test)` each, exit 0, full bring-up and tear-down
included. Afterwards the DUT shows `evi-1` with its three attachment circuits
bound.

That proves the pipeline emits code a real device **accepts and executes**. It
does not yet prove the code **verifies EVPN behaviour** — see "Honest limits"
below for the assertion tally, which is the number that matters.

Two defects that run exposed matter more than the pass:

1. A vlan-based EVI rejects a port as an attachment circuit. Now generated as
   sub-interfaces, following the stanza Exaware's own VPLS suite uses.
2. **Three configuration commands were rejected by the device and the test
   still passed** — nothing was staged, so the commit had nothing to do, so the
   framework logged a warning. Generated config steps now assert acceptance
   themselves; a negative control (out-of-range sub-interface) turns the run red.

`deliverables/M2/evidence_tc01_run_pc3080.txt`.

## Honest limits

- **The suites no longer fake a pass, and the rule earned its keep twice.**
  A generated test that verified nothing used to report `OK (1 test)`.

  | Suite | Before the rule | On `--lab 2ac-core` |
  |---|---|---|
  | TC01 bring-up | `OK` — 0 assertions | **`OK`** — 4 falsifiable assertions |
  | TC02 Type-2 | `OK` — 0 assertions | not generated: needs a 3rd AC |
  | TC03 Type-3 IMET | `OK` — 0 assertions | **`OK`** — same expectations |

  Both greens were earned twice over: generated with no captures, TC01 failed
  `INCONCLUSIVE` exactly as designed, and only went green once real device
  output backed it. Red is the correct colour for a test that checks nothing.
  See `CLAUDE.md` and `deliverables/M2/evidence_what_the_suites_assert.txt`.
- **No IXIA traffic was ever created, in any run — their framework hid it.**
  `Ixia.connect()` sources `ixia_lib.tcl` on the IXIA app server using a path
  resolved on the JVM host. tate mounts a different `/home`, so the `source`
  failed and **every** proc was undefined: 34 `invalid command name` answers in
  one run (`configNewTrafficItem`, `trafficApply`, `startProtocols`, …) — while
  `performFunctions` reported "ended without errors" for all of them. Running
  from a path both hosts can see (`/var/tmp/ate-run`) brings that to **0**, and
  the traffic items now build without `wrong # args`. Found only because the
  generated code reads a value back instead of assuming.
- **Captures are topology-specific, and silently so.** Expectations taken on
  the three-AC rig name `.100` sub-interfaces on what is now the L3 core port,
  so replaying them against `--lab 2ac-core` fails on lines the device is right
  not to print. Re-capture after any topology change; nothing warns you.
- **5 of 11 expectations are still empty, all of them MAC-table reads.** The
  MAC table prints its legend and no addresses because nothing has been learnt:
  no traffic has run through the EVI. `capture` refuses legend-only output
  rather than recording an assertion that passes on any device.
- **The 3 delivered suites are hand-curated at step level.** The tool emits the
  Java; a human wrote the 33 steps. Mechanically generated suites are prefixed
  `TCM<nnn>` so the two can never be confused.
- **The mechanical path grounds ~10% of its steps.** Registry auto-derived from
  the CLI doc (18 curated → 124). The residue quotes base-CLI commands
  documented in the **Command Reference Guide, not the EVPN CLI doc** —
  extracting the CRG is the next lever. Ungrounded rows degrade to compiling
  TODO stubs; nothing is invented.
- **Traffic items are built in code — the source MAC still cannot be set.**
  `ixia_lib.tcl` has `editTrafficRawDestMacAddr` and no source equivalent, and
  EVPN learns from source MACs, so FLOW-030's premise that AC2 and AC3 share a
  source MAC cannot be expressed. With no traffic there is nothing to learn,
  which is why the MAC-table expectations stay empty.
- **`verify-commands` is now trustworthy in both halves, after a real bug.** A
  `?` on a leaf drops the CLI into an interactive *value* prompt; the reader
  waited out its timeout and the answer was collected by the *next* probe, so
  later verdicts described the wrong command. Fixed by recognising the value
  prompt, escaping it with Ctrl-C (never answering — that would be a write), and
  proving the channel is resynced after every probe. Verdicts were then
  spot-checked by hand against the device.

## EVPN could not come up standalone — the underlay was missing

Raised by Ilan on 2026-08-13 against Exaware's "nothing is missing", and
confirmed in our own generated files.

EVPN is an overlay. It needs an IGP for reachability, MPLS transport for the
service label, and BGP `af-l2vpn evpn` for the control plane. `EVPN_Base.cfg`
stated in its own header that the underlay was "lab data ... deliberately not
invented here" and had to arrive from `cleanBaseConfig` — and it never did:
the `.crt` loads `cleanBaseConfig` then the feature file, and a clean base
configures no IGP and no BGP. **The delegation had no receiver.**

That is also why the four `show bgp l2vpn evpn table evi detail` expectations
were always empty. Not because no peer answered — because there was no BGP
session at all.

`ate codegen --lab 2ac-core` now emits the underlay, and every stanza of it
**committed on pc-3080**: `routing bgp 3029` with `af-l2vpn evpn`, `routing
ospf 3029` area 0.0.0.0, `mpls ldp default`, loopback 29.30.30.30/32.

## IXIA is the peer, and the rig proves it

The lab profile used to record "all three IXIA ports are attachment circuits,
so the peer cannot be one of them". IXIA is used as client traffic endpoints
**and** as the remote router; nothing modelled the second job. `LabProfile`
now carries a `CoreLink`, and `--lab 2ac-core` binds vport1 as the core with
vport2/vport3 left as ACs.

Verified against chassis 10.1.70.108:

| | |
|---|---|
| IxNetwork version | **9.00.1915.16** — the SUT pins only the *client* TCL lib at 6.30. Do not read capability off `tclFolder` |
| EVPN object tree | `bgp` (`eVpnAfi=25 eVpnSafi=70`) → `neighborRange -evpn true` → `ethernetSegments` → `evi` (RT 65000:1) → `broadcastDomains` → `cMacRange`, all committed |
| Core link | vport1 (card 5/1) ↔ x-eth 0/0/8: `state=up connected=true` |
| BGP session | DUT reports **`BGP state: Established`** with `29.60.0.2`, and lists an `L2VPN EVPN table` for the neighbour |

The verified sequence is committed as `scripts/ixia_evpn_peer.tcl`.

**The EVPN emulation will not start**, and only at the start step:
`ERROR-1005 ... There is no license available for BGP EVPN`. Isolated to the
EVPN feature by a controlled test — same session, same port, only the
`ethernetSegments` object differing: plain ipv4-unicast starts and the session
establishes, EVPN does not. `licensingServers`/`mode`/`tier` were all populated
and the server was demonstrably granting BGP licences, so this is the feature,
not a misconfigured client.

**But the current TCs do not need it** (Exaware, 2026-08-14): they check EVPN
in the BGP **capabilities**, which the DUT advertises on its own. Verified on
the session:

    L2VPN EVPN:    advertised

That is falsifiable where the empty EVI route table was not — drop
`af-l2vpn evpn` from the neighbour and it reads `none`. TC01 asserts it via
`show bgp neighbor <peer> | include EVPN`, filtered because the unfiltered
output carries uptime and counters that would make the test flaky.

## The underlay was one-sided, and nothing could have caught it

Exaware, 2026-08-14: *"you configured ospf on the device, but not on the Ixia."*
Correct, and it was visible for hours as `show ospf neighbor` → *No entries
found*, which read as "not wired up yet" rather than as a defect.

The root cause is a pipeline gap, not an oversight in one config: **the
generator emitted the DUT side and nothing for the tester**, so there was no
model of the far end and nothing that could notice the DUT was speaking OSPF,
LDP and BGP into a port configured for none of them. The IXIA side had to be
hand-built in TCL, which is exactly how the two drifted.

Fixed structurally:

* `CoreLink` now declares `dut_protocols` and `tester_protocols`;
* `underlay_symmetry_violations` **fails generation** when the DUT runs a
  protocol the tester cannot answer;
* `ate codegen` emits `configurations/ixia/evpn_tester_setup.tcl` from the same
  profile the `.cfg` is rendered from, so both ends cannot disagree.

On hardware after this: OSPF **Full** with 29.60.0.2 on x-eth 0/0/8, LDP and
BGP started, session Established.

Cost of the core link: two attachment circuits instead of three, so FLOW-030's
MAC move cannot run on this rig. `ate codegen` says so rather than quietly
emitting fewer tests. `SINGLE_DUT_3AC` keeps the spec topology.

## All three suites pass on hardware, with real assertions

`--lab 3ac` on pc-3080, 2026-08-14:

| Suite | Verdict | Real assertions |
|---|---|---|
| TC01 bring-up | **`OK (1 test)`** | 2 |
| TC02 Type-2 MAC/IP + local move | **`OK (1 test)`** | 3 |
| TC03 Type-3 IMET + aging | **`OK (1 test)`** | 2 |

**TC02 had never passed before.** What was blocking it was not the topology
and not Exaware — it was three defects that each made the rig look like it was
working:

1. **The source MAC could be set all along.** The field is
   `ethernet.header.sourceAddress-`**`2`**, not `-1`: the suffix is the
   field's POSITION in the stack (destination is 1, source is 2). The
   by-display-name lookup committed at `4b01557` finds it, and the chassis
   confirms `SRCMAC=... SET=2`. AC2 and AC3 can now share a source MAC, which
   is FLOW-030's entire premise. The "blocked on a src-MAC proc in
   `ixia_lib.tcl`" item is dissolved.
2. **AC sub-interfaces had no `vlan-id`.** `interface x-eth 0/0/18.3380` with
   only `l2-transport enable` is admin-up, is listed by `show evpn detail` as
   a bound AC — and classifies nothing. The port counted 219k frames received
   while the circuit counted 0. The sub-interface NUMBER does not select the
   VLAN; VPLS_N1.cfg has said so all along (`interface int2.1` / `vlan-id 2`).
3. **Raw traffic items were untagged.** A raw item's frame is its protocol
   stack, and that stack was ethernet + fcs. Tagging the vport's interface
   governs protocol emulation, not raw frame content, so every frame arrived
   untagged and matched no circuit.

With all three fixed the DUT learns MACs, and the MAC move is observable:
`00:00:02:00:00:01` moves from `x-eth0/0/18.3380` to `x-eth0/0/26.3380` when
traffic shifts from AC2 to AC3.

Two assertion bugs the greens exposed, both the "looks right, means the
opposite" kind:

* **`setTrafficItemState(x, true)` never transmitted.** Enabling an item and
  applying leaves the chassis configured and silent. It now issues an explicit
  `START_TRAFFIC` and reads `TRAFFICSTATE` back before anything depends on
  frames having moved.
* **Absence steps were asserting presence.** "Verify the MACs aged out",
  "verify the Type-2 was withdrawn" and "verify the table starts empty" are
  claims about something being GONE. `ate capture` records state while it
  exists and refuses empty output, so those steps were filled with exactly the
  rows that ought to disappear — asserting that aging never happened. They now
  carry `expect_absent` and emit `verifyShowLinesAbsent`, scoped to the
  circuit whose traffic stopped rather than the whole table.

## Earlier: the 2ac-core profile

Run on pc-3080 on 2026-08-13 with `--lab 2ac-core`, after the underlay landed:

| Suite | Verdict | Assertions |
|---|---|---|
| TC01 bring-up | **`OK (1 test)`** | 4 of 7 verification steps can fail |
| TC03 Type-3 IMET | **`OK (1 test)`** | same generated expectations |

`VPORTS=3`, `ACVLAN=3380/true`, and raw endpoints bound to
`/vport:2/protocols|/vport:3/protocols` — vport1 correctly left as the core.

**Usable expectations: 3 of 7 on this profile** — and an earlier claim here of
"2 → 6 of 11" was wrong and is withdrawn. Four of those six were
`show bgp l2vpn evpn table evi detail` returning nothing but a flags legend and
`EVI Name = evi-1`. That is an assertion which passes on any device with an EVI
of that name, working or broken, and TC01 and TC03 were resting on it.

The guard that should have refused them only recognised SHORT ALL-CAPS legend
labels (`LOC:`, `R-FL:`), so the BGP table's mixed-case `Flags:` / `Origin:`
walked straight past it — the same defect as the MAC-table legend arriving
through a different command. `fake_pass.is_structural` now matches the *shape*
of a glossary rather than one spelling of a label, and `capture` applies it to
every command instead of only `mac-address-table`.

Three bugs the run exposed, all ours, all fixed:

1. **The EVI was bound to the core port.** The Java resolved AC interfaces by
   position in `lab.acs` while the `.cfg` used the intPool index; once a link
   became the core those differ. Commit came back *"Interface must be
   l2-transport enabled"*. Fixed with `AC_POOL_OFFSET`.
2. **Only two vports were created while three were named**, so the chassis
   answered *"can't read ixia(vport3): no such element in array"*.
3. **Stale captures.** Expectations recorded on the three-AC topology name
   `.100` sub-interfaces on a port that is now L3, so they fail against the
   rig they were not taken on. Re-captured; `out/captures_2ac.json`.

## In progress — resume point

Making the suites assert real EVPN behaviour, which needs real traffic. Device
iterations are ~8 minutes. Workspace: `/var/tmp/ate-run` on the dev box — a
path tate can also see, which is why the TCL library finally loads.

**Verified on hardware, in order of discovery:**

| | |
|---|---|
| capture → codegen loop closed | `ate codegen --captures`; TC01 asserts 20 live lines and goes red if one is wrong |
| fake-pass rule enforced | TC02/TC03 now fail `INCONCLUSIVE` instead of falsely passing |
| TCL library loads | `invalid command name` **34 → 0** (workspace path visible to tate) |
| traffic item arguments | `wrong # args` **→ 0** (unset args are `null`, not `""`) |
| `generateAllTrafficItems` | added — binds physical MACs onto raw items |
| traffic actually started | `startTraffic()` — unsuspending an item does not transmit |
| IXIA vports created | `VPORTS=3` — `loadIxiaObj` only names vports that already exist |
| IXIA VLAN tagging | `ACVLAN=3380/true` on all three vports, from the SUT's `vlans[0]` |
| raw endpoints bound | `ENDPOINTS=/vport:1/protocols\|/vport:2/protocols` |

**Next, precisely — this is the resume point.**

The source MAC is the only thing between here and traffic. The chassis
rejected the obvious mirror of their destination-MAC write:

    ixia_lib.tcl : field:"ethernet.header.destinationAddress-1"   (works)
    mirrored     : field:"ethernet.header.sourceAddress-1"
    chassis      : ERROR-7009-Could not find the requested item,
                   ethernet.header.sourceAddress-1
                   NullReferenceException in StackFieldHandler.InsertMissingField

The `-1` is a POSITION in the stack, not part of a name, so the source field
sits at a different index. `EvpnUtils.setTrafficItemSourceMac` now enumerates
the ethernet stack's fields and matches on `-displayName` containing "source"
instead of guessing an index, and prints `FIELDS=<names>` so the real naming is
recorded on the next run.

**That change is written, unit-tested and compiling, but NOT yet run against
the chassis.** Re-running TC02 is the next action:

```bash
# from the repo, after `ate codegen` + the compile gate
cd <scratch> && tar czf classes.tgz -C build classes && tar czf gen.tgz -C gen cmp
scp classes.tgz gen.tgz axawear:/var/tmp/
ssh axawear 'W=/var/tmp/ate-run; cd $W; rm -rf classes; tar xzf /var/tmp/classes.tgz;
  tar xzf /var/tmp/gen.tgz -C cmp-tests-project/src; chmod -R a+rX $W;
  cd $W/run; CP=$(find $W/libs $W/extlibs -name "*.jar" | tr "\n" ":")$W/classes;
  $W/jdk17/bin/java -cp "$CP" org.junit.runner.JUnitCore \
    cmp.tests.evpn.TC02_EvpnType2MacIpAdvertisement > $W/run/TC02.log 2>&1'
grep -oE "SRCMAC=[^ ]* SET=[0-9]+ FIELDS=.*" $W/run/TC02.log
```

After that: confirm the IXIA tx/rx counters actually move, then `ate capture`
with traffic present, then write the count-based assertions.

**Ceiling on this rig — SUPERSEDED 2026-08-13.** This used to read "roughly 7
of 11; the other four need a BGP EVPN peer this testbed does not have". Both
halves were wrong. IXIA is the peer, and those four
`show bgp l2vpn evpn table evi detail` expectations capture successfully now
that the DUT has a BGP EVPN control plane at all. The real remaining ceiling
is the five MAC-table reads, which need traffic through the EVI, and the
Type-2/Type-3 exchange, which needs the IXIA **BGP EVPN licence**.

Note: the six `ERROR-6301` answers in the log are their own
`configTrafficItemEndpoints` failing; our explicit bind corrects it afterwards.
Harmless, but it is why that error still appears.

## Blocked on Exaware

| # | Item | Impact |
|---|---|---|
| 1 | **A BGP EVPN licence on IXIA chassis 10.1.70.108** — *not needed for the current TCs* | Only blocks IXIA **emulating** an EVPN speaker, i.e. real Type-2/Type-3 exchange. Per Exaware 2026-08-14 the current TCs check EVPN in the session **capabilities**, which needs no licence and is now asserted |
| 2 | **A src-MAC proc in `ixia_lib.tcl`** (their infra file) *or* the `.ixncfg` | Blocks only FLOW-030's MAC-move premise, not MAC learning generally |
| 3 | **Ticket ID** for the branch (`AUT-nnn` / `EM-nnnn`) | Blocks handover under its real name; push path solved via tate (10.1.70.200) |
| 4 | **Confirmation on the EVI knobs and multi-homing config absent from LAB 22** | Either the CLI doc is ahead of the build or the build lacks them — we report, we do not guess |

## Next

1. Extract the Command Reference Guide v8.X.0 → grounds the base-CLI commands (the remaining ~90% of mechanical rows)
2. Push the branch once a ticket ID exists
3. Start M3 (multi-router plan generation)

# ATE — Project Status

**SOW:** PQ4476E — AI-Assisted Test Plan & Automation Skeleton Generator (10 weeks, 5 milestones)
**Updated:** 2026-09-09

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
| Parse documents → requirements | `ate plan-feature EVPN` | ✅ 134 reqs |
| Requirements → test plan | (same) | ✅ 286 plan rows / 717 action rows |
| Plan rows → typed steps | `ate match` | ✅ 537/612 = 87.7% |
| Steps → Java suite | `ate codegen` | ✅ compiles, `-Werror -Xlint:all` |
| Steps → DUT config | (same) | ✅ `.crt` passes their own validator |
| Test selection | `ate queue` | ✅ dirty queue |
| **Read a plan back / diff two versions** | `ate plan-diff` | ✅ ID-keyed change file, ships with every respin |
| **Verify commands on a device** | `ate verify-commands` | ✅ 123 templates; **both halves now trustworthy** |
| **Capture real expectations** | `ate capture` | ✅ 2 usable, 9 empty, 0 unsupported — **not yet fed back into the code** |
| **Run the suite on the DUT** | `javac` + JUnit/JSystem | ✅ **TC01/02/03 all run green on pc-3080** (assert little — see limits) |
| Build IXIA traffic items | `ate codegen` | ✅ in code **and** as a readable `EVPN_traffic.tcl` that saves an `.ixncfg` — one chassis run away from their load-and-suspend idiom |

## M2 — SOW bullets

| SOW bullet | Status |
|---|---|
| Code generation from selected tests | ✅ TC01/TC02/TC03 via the dirty queue |
| Pattern matching | ✅ 537/612 rows (87.7%) typed |
| Demo: extract requirements from docs | ✅ 134 reqs → 286 plan rows |
| Up to 3 integration-ready test plans | ✅ compile against the real framework |

Gates: 953 sources → 1454 classes, 0 errors; generated files pass `-Werror -Xlint:all`;
`bringUpParams.crt` passes `TemplateManager.validateAgainstTemplate`. 349 ATE tests pass.

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

- **The 2026-08-14 hand-over shipped with no control plane, and it was a
  regression of a fix we had already made.** Exaware reported the underlay
  missing on 2026-08-13; it was built, and verified on pc-3080 (OSPF FULL, BGP
  Established). The final package was then generated with `--lab 3ac` so a
  third AC existed for FLOW-030's MAC move. That profile has no core link,
  three emitters answered the absence with `[]`/`None`, and the suite went out
  with no IGP, no LDP and no BGP on either side. **The client reported the same
  defect twice.** Every gate we had passed it: it compiled, the `.crt`
  validated, three suites ran green, the pipeline exited zero. Nothing checked
  the artifacts.

  Fixed structurally, not by resolving to be more careful
  (`ate/codegen/capabilities.py`, `scripts/verify_handover_package.py`):

  | Layer | Effect |
  |---|---|
  | Capability ratchet | six capabilities carry a hardware `Proof`; `ate codegen` **raises** if the emitted files drop one |
  | Detectors read artifacts | not the profile, not the exit code — the regression had a healthy pipeline |
  | `--lab` is required | no default, because the default is what chose the weaker rig |
  | `LabProfile.core` has no default | absence is a `NoCore` with a `reason` and an `accepted_by`, both printed into the `.cfg` |
  | Hand-over gate | re-checks the same capabilities inside the package, **no escape hatch**, runs under `set -e` |

  Run against the shipped package it names all four lost capabilities, and
  three step titles that admitted the rig could not support them.

  **Consequence: `ate codegen --lab 3ac` refuses**, because four of its steps
  assert BGP-carried routes on a rig with no BGP session. That is not waivable
  — it is the fake-pass rule.

  **The follow-on claim was wrong and is withdrawn (2026-09-08).** This said
  "three ACs *and* a control plane need a fourth DUT↔IXIA port", and Exaware
  corrected it: *"The setup includes 3 DuT-Ixia connections. It is (more than)
  enough to create a Control Plane link and 3 ACs. An AC can reside as a
  tagged interface."* A circuit is a port **and a VLAN**, so two circuits fit
  on one port. `--lab 3ac-core` is the shippable profile now, it emits all
  three suites, and the client lost TC02 for a fortnight over arithmetic that
  was ours, not the rig's.
- **TC02 is green on hardware (2026-09-09): `OK (1 test)`, 0 failures,
  170 passes.** It asserts the EVI absent, then created; MACs learnt on each
  of three circuits including the moved one; the Type-2 advertisement; that
  the local AC2 to AC3 move triggers NO new Type-2; and the traffic rates at
  every step. That closes Exaware's E4, "TC02 which is declared as a passed
  TC is missing". Evidence: `deliverables/M2/evidence_tc02_green_pc3099.txt`.

- **The IXIA traffic assertions could never have passed, on any rig
  (found 2026-09-09).** TC02 failed every traffic step with `No results where:
  TRAFFIC_ITEM: ...` while the traffic was running perfectly. Three separate
  causes, each hidden behind the one before it:

  | | |
  |---|---|
  | The statistics view did not exist | IxNetwork builds "Traffic Item Statistics" only for items that carry tracking; ours had `trackBy=''`, and the `.ixncfg` we ship was saved without it. `ixia_lib`'s own `trafficApply` throws reading that view, which is where the misleading `ERROR-7008 Could not apply traffic` came from |
  | Every step asserted "all three running" | the emitter discarded the expectation each step declared; at most steps exactly one item is unsuspended |
  | Expected Rx assumed Rx = Tx | AC2 and AC3 share a vport, so a broadcast flooded to both is counted twice: `TI_AC1_TO_AC2` reads Tx 1000 / **Rx 2000**. That 2x *is* the flooding assertion |

  TC01 was green throughout, because it is the one suite that reads no traffic
  statistics. Fixed in the emitter, ratcheted as `traffic.statistics_view`,
  and locked by two tests. Evidence:
  `deliverables/M2/evidence_traffic_item_tracking.txt` and
  `evidence_traffic_expectations.txt`.

  Three step titles claimed things the rig cannot show (a broadcast cannot
  stop being flooded; a MAC move between two circuits on one vport is
  invisible to a per-port counter). They now state what they actually
  establish, and the MAC move is asserted where the evidence is, on the DUT.

- **TC03 aged out MACs it had never learnt.** FLOW-031 stopped traffic, waited
  out the aging time and asserted the entries were gone, from a prep that
  starts every traffic item *suspended*. Nothing was ever learnt, so all three
  of its assertions were trivially true on an empty MAC table. It now starts
  traffic and asserts the MACs **are** learnt before testing that they age.

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

## The 2026-09-08 review: Eyal's four remarks

His mail, and where each one stands. **Verified on hardware on 2026-09-09**,
pc-3099 (8.7.0 LAB 935), except where the row says otherwise.

| # | His remark | State |
|---|---|---|
| 1 | "The ixia config file is not in TCL format, which I cannot open" | ✅ `configurations/ixia/EVPN_traffic.tcl`: one readable block per item, their proc names, and it **saves an `.ixncfg`** |
| 2 | "The BringUpParameters.crt file doesn't load any Ixia file" | ✅ the row is emitted as soon as `--ixncfg` names a file, needs one chassis run to produce it |
| 3 | "TC01 seems to configure an already existing evpn service" | ✅ **on hardware**: the `.cfg` no longer creates the EVI, the test does, after asserting it absent |
| 4 | "TC02 which is declared as a passed TC is missing" | ✅ **on hardware**: three circuits bound; and now a ratchet, `topology.three_acs`, so it cannot vanish again |
| 5 | 3 links are enough for a control plane and 3 ACs | ✅ **on hardware**: `x-eth0/0/40.1002` and `.1003` are two ACs on ONE port |
| 6 | "Vlan 3380 ... The tool should be able to use entire 2-4094 range" | ✅ **on hardware**: 1001-1003 bound; pc-3099's own SUT VLAN (3399) untouched |
| 7 | "except for the DuT config file I didn't see it working or established" | 🟡 TC01 **OK (1 test)** on pc-3099 with full logs. A TATE report still needs the ticket ID |

### What the VLAN work actually changed

The `.crt` used to bind each IXIA vport to `vlans` index 0 in the SUT file,
which on pc-3080 is 3380, a VLAN that belongs to an external server link. The
suite could therefore only ever run on whatever VLAN the SUT happened to
declare first, and it was not ours.

VLANs are now the lab profile's, per circuit, written literally into the
`.cfg`, carried on each traffic item, and settable with
`ate codegen --ac-vlans 1001,1002,1003`. The old run-time check (does the SUT
agree with the `.cfg`?) is replaced by its opposite, which is the useful one:
**`assertAcVlansAreFree()` fails the run if a VLAN we are about to use appears
in the SUT's `general/vlans` list**, because those belong to other links.

Which VLANs this rig actually has free is still Eyal's to say. Until he does,
1001-1003 are the defaults and one flag changes them.

### A defect this found in the shipped package

Captured expectations are topology-specific, which STATUS has listed as an
honest limit for weeks. Moving off 3380 turned it from possible to certain, so
it is now checked: `capture.topology_mismatches` drops a capture whose lines
name a sub-interface this profile does not have, and says so.

Run against what shipped on 24 August, it finds two expectations asserting
`x-eth0/0/18.100` and `x-eth0/0/26.100` in a package whose own `.cfg` creates
`.3380` circuits, on a rig where `0/0/8` is the core link. **Those two
assertions could never have matched.** They are dropped rather than asserted,
which is why the falsifiable tally reads 3 of 23 rather than 5. The two that
went away were never real.

Re-capturing on the rig is what recovers them, and it was done on 2026-09-09.

**The re-capture happened, and it more than doubled the assertions.** Nine
expectations had shipped empty because they are about MAC-table and BGP-route
*content*, which does not exist on an idle device: an empty expectation warns
and never passes, so those steps asserted nothing. The chassis was driven to
the state the flow describes (EVI up, three circuits bound, all three traffic
items transmitting, MACs learnt on AC1 and moved onto AC3) and `ate capture`
run against it: **16 of 16 usable, 0 dropped**.

| | Falsifiable | Warn only |
|---|---|---|
| Before | 7 of 26 | 19 |
| After | **17 of 26** | 9 |

The nine that still warn need output this rig cannot produce (a second PE, a
remote Type-2), and they are listed by `ate codegen`.

Filling absence steps from a capture needed two guards, because
`verifyShowLinesAbsent` demands its lines be *gone*: column headers are
printed whether or not a row remains, and an unscoped command's capture also
holds rows that are still present and should be. Both are stripped now, and
`deliverables/M2/evidence_traffic_expectations.txt` shows what changed.

### Lab session 2026-09-09: what the hardware settled

| | |
|---|---|
| A vlan-based EVI accepting two sub-interfaces of the SAME port as two ACs | ✅ proven, `deliverables/M2/evidence_shared_port_acs.txt`, device restored as found |
| The suite compiles | ✅ 953 sources → 1455 classes, 0 errors |
| TC01 on hardware | ✅ `OK (1 test)` on pc-3099 |
| `EVPN_traffic.tcl` runs and saves the `.ixncfg` | ⬜ **the one remaining blocker.** TC02 now fails on nothing else |
| Fresh captures on VLANs 1001-1003 | ⬜ 16 steps still warn instead of asserting |
| A TATE report | ⬜ needs the ticket ID, outstanding since 24 August |

Two defects only a real run could find, both fixed and both locked by a test:

1. **TC02 depended on TC01's leftovers.** Bring-up calls `loadConf()` before
   every test method, so the EVI TC01 created was wiped before TC02's first
   assertion. Each test now creates the EVI it uses, having first asserted it
   absent. That satisfies remark 3 and makes each TC runnable on its own.
2. **An expectation held a placeholder interface name.** `agg-eth-2.1001` is
   the profile's placeholder; the SUT rebinds it, so the assertion could never
   pass on any rig. Circuit names in expectations are now resolved on the
   device (`EvpnUtils.eviBoundLines`).

### pc-3080 cannot run Exaware's own bring-up

Not our defect, and worth telling them: pc-3080 was re-imaged to `8.7.0: LAB
0`, and bring-up dies at "Failed to enter specific session mode. Wanted mode:
ONL". `CmpCliSession.java:69` matches the ONL shell by the literal
`"@localhost"`; this image answers `root@router`. The same test on the same
box in August logged `root@localhost` 78 times, today zero. Any suite fails
there. pc-3099 (LAB 935) is unaffected.

## The 2026-08-16 review — what is closed

Eyal Ozeri sent four points on the M2 suite; Ron asked us to answer three
review mails together. State as of 2026-08-19:

| # | His point | State |
|---|---|---|
| 1 | No BGP session between DUT and IXIA | ✅ was a **regression** of the 08-13 underlay fix; ratchet + hand-over gate now make it unrepeatable |
| 2 | Both configs lack OSPF/ISIS, LDP, BGP | ✅ same regression, same fix — `--lab 2ac-core` emits both ends |
| 3 | VLAN shown as a parameter; 3380 untraceable | ✅ `.cfg` now emits `interface int2.3380` / `vlan-id 3380` **literally**, and names its source |
| 4 | IXIA traffic items built in an unfriendly raw manner | ✅ VPLS idiom adopted after reading their suite — see below |

### Point 3 — the VLAN, and where it comes from

Their own `bringUpParams.crt` find-and-replace table parameterises `interface`
names and **nothing else**; `VPLS_N1.cfg` carries literal `vlan-id 2` on
literal `int2.1`. We had invented a `vlan` substitution type and then put its
placeholder inside an interface name, producing `interface int1.vlan1`.

Now literal, in their style, with the provenance printed into the `.cfg`:

    sut/pc3080.xml <general><vlans index="0"><number>3380</number>

Two sources for one value can disagree, so the generated Java re-reads that SUT
slot and **throws** if it does not match the number baked into the `.cfg`. A
silent mismatch would create the DUT sub-interface on one VLAN and tag IXIA
frames with another — every command succeeding, nothing ever learnt. That is
the same shape as the one-sided underlay, and it is now checked rather than
trusted.

### Point 4 — the traffic idiom, read from their suite

`VplsUtils.java`, `VplsParams.java`, `VPLS_N1.cfg`, the VPLS `.crt` and
`ixia_lib.tcl` were read directly off the dev box. Their idiom has three parts,
and the one we were missing was the third:

1. traffic items referred to **by name** — we already did that;
2. a test **suspends and unsuspends** named items rather than rebuilding them;
3. **every traffic step asserts the Traffic Item Statistics table**, with
   expected Tx/Rx frame rates as `RowDataTable` rows and a tolerance.

Point 3 is what makes their suites investigable. `EvpnUtils` now carries their
five methods under their own names — `changeSuspendStatus`,
`enableTrafficItemsAndStart`, `enableTrafficItemsAndStartSuspended`,
`verifyTrafficItemsAreSuspended`, `verifyTrafficItemStatistics` — and
`EvpnParams` carries the `trafficTable` in the VplsParams shape.

`verifyIxiaStatistics` used to be a stub that could only call
`CompassReporter.warning()`. It is now a real assertion and counts toward the
falsifiable-assertion tally, which is why that tally moved from 3 paths to 4.

**What still cannot be done in their idiom:** the `.ixncfg` is a proprietary
binary (a zip around an opaque payload) and cannot be authored from documents,
so the items are still *built* in code. That construction is confined to one
`createTrafficItems()` call and an `.ixncfg` for the EVPN rig would replace it
outright. Worth asking Exaware for.

## The BGP knobs are no longer invented

`cli_inheritance.py` hand-curated the `af-l2vpn evpn` sub-configs "from
standard BGP convention" for three months. Eyal flagged them as invented on
2026-07-06 and he was right: cross-checked against the Command Reference Guide
v8.X.0, **every one of the seven entries had at least one fabricated element.**

| Knob | We had (invented) | The guide |
|---|---|---|
| `private-as` | `{remove \| replace}` | `[remove \| leave]` |
| `policy` | `policy <name> {in \| out}` | `policy {in \| out} policy-name` — operands reversed |
| `maximum-prefix` | `<max> [<pct> [warning-only]]` | `number max threshold percent action [warn \| terminate]`, 2097152/75/warn |
| `allow-as-in` | `[<count>]` | `number`, range 1-10 |
| `capability` | one flat option list | sub-mode scoped: neighbor = dynamic/route-refresh, AF = graceful-restart/orf |
| `inbound-soft-reconfiguration` | bare | `[enable \| disable]`, default disable |
| `route-reflector-client` | bare | `[enable \| disable]`, default disable |
| `weight` | **missing** | `weight weight-value`, 0-65535, default 0 |

The worst were not the missing ranges but the confidently wrong ones — a
reviewer cannot tell an invented default from a read one.

New `ate/planner/crg_extractor.py` reads the sections off the guide;
`cli_inheritance.py` only re-homes them into the EVPN sub-mode. The
`deinvent()` pipeline step is gone: it was the right answer while the base
manual was missing and the wrong one once it arrived, because stripping now
would discard the ranges Eyal asked to have back ("removed, not corrected").

**One conflict we will not resolve.** The guide's Notes for `allow-as-in` read
*"This command is only available under unicast SAFI, VRF default, and VPN
SAFI"* — which excludes `l2vpn evpn`. SFS EVPNS-REQ#20 lists it as an
`af-l2vpn evpn` knob. Two Exaware documents, flatly disagreeing. The row is
emitted with the conflict stated in the Comment column so a device settles it.
**This needs Eyal or Yossi to rule.**

## The plan can now be read back, not only written

The pipeline could write an xlsx and never read one. That one-way street is
why every review round was hand-triage, and why one of Eyal's files came back
with no recoverable annotations and a whole batch had to be reconstructed from
WhatsApp messages.

`ate/planner/plan_reader.py` parses a generated (or reviewer-annotated) plan
back into topics and actions keyed by the stable IDs the writer already emits —
`FLOW-030`, `CLI:mac-limit`, `RFC7432bis-§7.2`. It reads the current
deliverable as 105 topics / 717 action rows, which matches what the generator
reports.

On top of it, **`ate plan-diff`** — Eyal's first ask on 2026-07-07, "send a
diff file with every version, I'm getting lost":

    ate plan-diff plans/EVPN_test_plan_with_RFCs.xlsx        # vs git HEAD
    ate plan-diff <new.xlsx> <old.xlsx> -o CHANGES.md

Diffed by ID, never by row number, so a plan whose rows all shifted reports
zero churn; a reworded action is one rewording, not a delete plus an add.
**Send `plans/*_CHANGES.md` with every version.**

Building it immediately paid for itself: the first run surfaced three defects
in the plan it was diffing — grammar punctuation leaking into client-facing
action text (`` `[dynamic` ``), continuation rows being counted as separate
actions, and a lost per-knob phrase in the read-back expectation.

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

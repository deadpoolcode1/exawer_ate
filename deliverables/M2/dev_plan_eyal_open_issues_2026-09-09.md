# Development plan: closing Eyal's open issues

Date: 2026-09-09
Scope: every open item from Eyal Ozeri, M2 (8 Sep and 16 Aug) plus his still
open M1 test plan items.

## 1. The open list

| # | Eyal's words | Date | Verified in our files? |
|---|---|---|---|
| E1 | "The ixia config file is not in TCL format, which I cannot open" | 8 Sep | The only IXIA file we ship is `configurations/ixia/evpn_tester_setup.tcl`, a raw `ixNet setAtt` dump. DETERMINED 2026-09-09: it is the only IXIA file in the zip he reviewed, so it is the file he opened. It is TCL, but not openable in IxNetwork and not in the `ixia_lib.tcl` idiom, and it describes the core link, not traffic. No question left for him. |
| E2 | "The BringUpParameters.crt file doesn't load any Ixia file" | 8 Sep | Correct. The `.crt` config table has one device row, `cmp1`. There is no `ixia1` config row at all. |
| E3 | "TC01 seems to configure an already existing evpn service" | 8 Sep | Correct. `EVPN_Base.cfg` already contains `evpn evi-1` with both ACs bound, and it is loaded at bring-up. TC01 then "creates" it. Those steps cannot fail. |
| E4 | "TC02 which is declared as a passed TC is missing" | 8 Sep | Correct. It was dropped when we moved to `--lab 2ac-core`, because that profile has only 2 ACs. |
| E5 | "except for the DuT config file I didn't see it working or established" | 8 Sep | Fair. Our evidence is console logs from a JUnit run on our dev box, not a TATE report he can open and re-run. |
| E6 | "3 DuT-Ixia connections ... enough for a Control Plane link and 3 ACs. An AC can reside as a tagged interface" | 8 Sep | This answers the topology question and removes our blocker. We assumed one link = one AC. |
| E7 | "Vlan 3380 ... is used ... to an external server connection. The tool should be able to use entire 2-4094 range" | 8 Sep | Correct. The `.crt` maps `vlan vport2/vport3` to SUT `vlans` index 0, which is 3380, and the `.cfg` writes 3380 literally. |
| E8 | "a traffic item will be 'human readable' ... the tool should learn how to create traffic items properly" | 8 Sep | Items are built in code over TCL. Nothing on the chassis can be opened and inspected afterwards. |
| M1a | Deprecated show commands in the test plan | Jul | Open, needs his exact list |
| M1b | Tech-support command text | Jul | Open, needs his exact text |
| M1c | Setup repetition, split the catch-all into template sections, missing sections | Jun 21 | Open, content is AI baked so it needs one re-bake |
| M1d | `allow-as-in` SAFI conflict between the CRG and the EVPN doc | Aug | Open, needs Eyal or Yossi to rule |

## 1b. Lab session of 2026-09-09 (afternoon) - what the hardware said

Access was restored at 10:20 (the jump host `codevalue` had been rebooted).
Both rigs were reserved for us. What the session established:

**The one genuinely new assumption is now device-verified.** A vlan-based EVI
accepts two sub-interfaces of the SAME port as two attachment circuits. Built
on pc-3080 (8.7.0 LAB 0) on a spare port, commit accepted, and both
`show evpn detail` and `show evpn broadcast-domains` list
`x-eth0/0/22.2001` and `x-eth0/0/22.2002` under Local Interfaces. The device
was put back exactly as found; the whole transcript, rollback included, is
`evidence_shared_port_acs.txt`. This is what E6 promised and it is what brings
TC02 back, so it is now a ratcheted capability (`topology.three_acs`) rather
than a note in a profile.

**The cabling question (our item 1 to Eyal) is answered from Exaware's own SUT
files** and does not need his reply. The DUT and IXIA `data1` pools pair index
by index. On pc-3099 that is:

| | DUT port | IXIA |
|---|---|---|
| core | x-eth 0/0/18 | vport1 |
| AC1 | x-eth 0/0/32 | vport2 |
| AC2, AC3 | x-eth 0/0/40 | vport3 |

pc-3080 pairs `x-eth 0/0/8, 0/0/18, 0/0/26` onto the same three vports, which
matches the core link we verified on 2026-08-13 and is why the `.crt` binds by
intPool index rather than by port name. The two rigs are cabled differently and
the generated package is already indifferent to that.

**E7 is confirmed twice over.** `pc3099.xml` declares `general/vlans` index 0 =
**3399**, exactly as `pc3080.xml` declares 3380. Per rig, that slot is a
different external link. It was never a VLAN pool, and nothing may take a test
VLAN from it.

**E1 is now determined, not guessed.** The package Eyal reviewed
(`Exaware_M2_handover_2026-08-24.zip`) contains exactly one IXIA file,
`configurations/ixia/evpn_tester_setup.tcl`, 2702 bytes, a raw `ixNet setAtt`
dump of the core link. That is the file he opened. It is TCL, but it is not
openable in IxNetwork and not in the `ixia_lib.tcl` idiom, and it says nothing
about traffic. No further question to him is needed.

**pc-3080 cannot complete Exaware's own bring-up on its current image.** It was
re-imaged to `8.7.0: LAB 0`. Bring-up ends at
`BringUp.checkCoresAndAlarms` with *"Failed to enter specific session mode.
Wanted mode: ONL, Current mode: CLI"*. The cause is exact and is in their
framework, not in generated code: `CmpCliSession.java:69` matches the ONL shell
by the literal string `"@localhost"`, and on this image the ONL prompt is
`root@router`. Counting the serial transcripts of the same test on the same
box:

| | 2026-08-13 (LAB 22) | 2026-09-09 (LAB 0) |
|---|---|---|
| `root@localhost` seen | 78 times | **0** |
| ONL prompt | `root@localhost` | `root@router` |

`checkCoresAndAlarms()` is called unconditionally from
`bringUpSetupAndVerify()`, so there is no parameter that skips it. The fix
belongs to Exaware: either the image sets the ONL hostname, or the regex stops
assuming it. **This is worth reporting to them on its own** - any suite, not
just ours, fails bring-up on that image.

pc-3099 was re-imaged during the session (LAB 934 at 10:27, LAB 935 at 11:25),
which is why it dropped off the network for ten minutes.

## 1c. Hardware results, pc-3099 (8.7.0 LAB 935), 2026-09-09

The suite was regenerated, compiled (953 sources to 1455 classes, 0 errors)
and run through JUnit/JSystem on the dev box against pc-3099.

| | Result |
|---|---|
| TC01 | **OK (1 test)**, 0 failures |
| TC02 | fails on ONE thing: the IXIA side, which is E2 |
| DUT-side steps of TC02 | all pass |

What the device held after TC01, read back directly:

```
EVPN name: evi-1                       Service Type: vlan-based
Local Interfaces:
  x-eth0/0/32.1001
  x-eth0/0/40.1002
  x-eth0/0/40.1003
```

That single output closes four review items at once. The service was created
by the test and not by the `.cfg` (E3). There are three attachment circuits,
so TC02 exists again (E4). Two of them share `x-eth0/0/40` and differ only by
VLAN (E6). The VLANs are 1001-1003 and not the SUT's 3399 (E7). Every
interface came up, and the placeholder-to-SUT binding resolved correctly on a
rig the generator had never seen.

### Two defects the hardware found, both now fixed

**1. A test may not depend on another test's leftovers.** TC02 failed with
"Missing lines: [evi-1]" straight after a green TC01. Nothing was wrong with
TC01: `CmpTestCase.initCmpTestCase` is an `@Before` and
`BringUp.bringUpSetupAndVerify` calls `loadConf()` unconditionally, so
`EVPN_Base.cfg` is reloaded before every test method, in one JVM or three.
Moving the EVI out of the `.cfg` for E3 therefore broke the "TC02 assumes TC01
has run" premise. Each TC now creates the EVI itself, having first asserted it
absent - which satisfies E3 and makes each TC independently runnable.
Locked by `test_every_test_case_creates_the_evi_it_uses`.

**2. An expectation may not contain a placeholder interface name.** The
follow-up run failed with "Missing lines: [agg-eth-2.1001, agg-eth-3.1002,
agg-eth-3.1003]" against a device that had all three circuits bound correctly.
`agg-eth-2` is the lab profile's placeholder; the SUT rebinds it at bring-up.
An expectation built from it can never pass on any real rig. Expected lines
that name a circuit are now resolved on the device
(`EvpnUtils.eviBoundLines`), via a new `Step.expect_expr`.

Both were only findable by running on hardware, which is the argument for the
device loop in one paragraph.

## 1a. Status after 2026-09-09

WP1 to WP4 are implemented, tested and regenerated. WP5 and WP6 need the rig
or Eyal's text.

| WP | What | State |
|---|---|---|
| WP1 | Three ACs plus a control plane (`--lab 3ac-core`) | **Done and device-verified on pc-3099** |
| WP2 | VLANs from the profile, `--ac-vlans`, 2 to 4094 | **Done and device-verified** (1001-1003 bound, SUT's 3399 untouched) |
| WP3 | Readable `EVPN_traffic.tcl`, `.ixncfg` recipe, `.crt` row | Code done; **one chassis run still owed** - the only thing TC02 now fails on |
| WP4 | The service is created by the test, not by the `.cfg` | **Done and device-verified**; corrected once on hardware, see 1c |
| WP5 | Evidence Eyal can re-run (TATE report) | Partly: TC01 green + full logs. A TATE report still needs a ticket ID |
| WP6 | M1 test plan leftovers | Blocked: his exact text |

318 tests pass, no golden drift, and the hand-over gate reports all seven
hardware-proven capabilities intact in the regenerated files. The gate now
refuses the 2026-08-24 package on both of Eyal's grounds: the lost third
circuit (E4) and the missing readable traffic definition (E1/E8).

Of the four things that were unverified this morning:

1. ~~that a vlan-based EVI accepts two sub-interfaces of the SAME port~~ -
   **verified**, pc-3080, `evidence_shared_port_acs.txt`, and again in anger
   on pc-3099 where the real EVI came up with exactly that shape;
2. ~~that the suite compiles~~ - **verified**, 953 sources to 1455 classes,
   0 errors, and it then ran;
3. one run of `EVPN_traffic.tcl` to produce the `.ixncfg` - **still owed**.
   This is the single remaining blocker and it is now precisely bounded: TC02
   fails only at `vport2: VLAN 1001 was NOT enabled (chassis said can't read
   "ixia(vport2)": no such variable)`, because bring-up loads no IXIA file.
   That is E2, stated by the device;
4. fresh captures on the new VLANs - **still owed**, and cheap once a rig is
   free: 16 of 23 verification steps warn rather than assert until then.

### Not our defect, but it will stop them too

pc-3080 cannot complete Exaware's own bring-up on its current image. See 1b:
`CmpCliSession.java:69` matches the ONL shell by the literal `"@localhost"`
and the image answers `root@router`. Any suite fails there, not just this
one. Worth a separate note to them.

One thing the work found on its own: the package shipped on 24 August asserts
`x-eth0/0/18.100` and `x-eth0/0/26.100` while its own `.cfg` creates `.3380`
circuits, on a rig where `0/0/8` is the core link. Those two assertions could
never have matched. Captures are now checked against the topology they will be
asserted on, and a stale one is dropped with a reason rather than shipped.

## 2. Plan

Five work packages. WP1 unblocks WP2 to WP4. Lab time is only needed in WP1,
WP3 and WP5.

### WP1 - Rebuild the topology on Eyal's answer (E6, E4)

New lab profile `lab-1dut-3ac-core`:

- vport1 stays the control plane: L3 point to point, OSPF, LDP, BGP EVPN.
- The three ACs become tagged sub-interfaces, two of them sharing one physical
  link with different VLAN tags. This is what E6 unlocks: `ERROR-6301` was
  about one vport being both a raw endpoint and an L3 interface, and it does
  not apply to two tagged ACs on the same vport.
- FLOW-030's MAC move gets its third AC back, so TC02 is generated again, and
  now with a live BGP session behind it, which the 14 August TC02 never had.
- `--lab 3ac` (no core) stays refused. The capability ratchet is unchanged.

Output: TC01, TC02, TC03 all generated against one profile that has a control
plane. Proof is `verify_handover_package.py` listing 8 of 8 capabilities plus
the three TCs run on hardware.

Effort: 1.5 days plus one night lab slot.

### WP2 - VLANs (E7)

- Stop reading the SUT `vlans` slot. The VLAN comes from a per profile pool
  declared in `lab.py` and validated as 2 to 4094.
- Every AC gets its own VLAN, so the tagged sub-interface scheme above is
  addressable.
- One source, three consumers: the `.cfg` stanza, `EvpnParams`, and the IXIA
  VLAN header. The run still fails if they disagree.
- Regression test generates at 2, at 4094, and at a random VLAN in between.

Blocked on: which VLANs Eyal wants us to own on the rig. Until he says, we use
a declared pool and print it in the `.cfg` header.

Effort: 1 day, no lab time.

### WP3 - The IXIA side becomes a real, readable artifact (E1, E2, E8)

Three parts, in order:

1. Emit `EVPN_traffic.tcl` in the `ixia_lib.tcl` idiom, using their procs and
   named items, instead of a raw `ixNet` dump. Readable and diffable.
2. Build the items once on the chassis, then `saveConfig` to
   `EVPN_<profile>.ixncfg` and ship that file. This is the piece we said we
   could not author from documents. We cannot write the binary by hand, but we
   can have IxNetwork write it for us from a verified session, which gets us
   into their VPLS idiom: load the file, then suspend and unsuspend named
   items.
3. Add the `ixia1` rows to `bringUpParams.crt` so the file is loaded at bring
   up, which is E2 directly.

Every traffic step keeps the `verifyTrafficItemStatistics` assertion with
expected Tx and Rx rates and a tolerance.

Effort: 2 days plus one night lab slot.

### WP4 - A test must create what it claims to create (E3)

- `EVPN_Base.cfg` is reduced to the underlay and the sub-interfaces. It no
  longer creates the EVI.
- TC01 asserts the EVI is absent, creates it, asserts it exists and that the
  ACs are bound, and removes it in teardown.
- TC02 and TC03 declare the EVI as an explicit prerequisite step, so the same
  rule holds for them.
- Negative control stays: one out of range value must turn the run red.

Effort: 1 day, verified in the WP5 run.

### WP5 - Evidence Eyal can reproduce (E5)

- Run the three suites through the JSystem runner on tate, not JUnit on our
  box, so there is a TATE report and DB records.
- Ship a one page recipe: which SUT, which `.crt`, the exact command, and what
  each TC asserts.
- Ship the report plus the console log per TC.

Blocked on: ticket ID (AUT-nnn / EM-nnnn) to push the branch, and the tate run
slot. Both were asked for on 24 August and are still open.

Effort: 1 day plus one night lab slot.

### WP6 - M1 test plan leftovers (M1a to M1d)

- M1a and M1b need his exact text. One mail from him closes both.
- M1c is content that the AI bakes, so it is one 10 hour re-bake. Batch it
  with any other wording change so we bake once.
- M1d is a ruling, not work: the CRG and the EVPN CLI doc disagree about the
  `allow-as-in` address family. We follow whichever he and Yossi pick.

Effort: 0.5 day plus one overnight bake, once his text arrives.

## 3. Order and dates

| Slot | Work | Needs |
|---|---|---|
| Day 1 | WP1 profile, WP2 VLAN pool | pc-3099 details, free VLAN list |
| Night 1 | WP1 on hardware: underlay up, three ACs bound | lab slot |
| Day 2 | WP4 config split, WP3 part 1 TCL emitter | - |
| Night 2 | WP3 part 2: build items, save `.ixncfg` | lab slot |
| Day 3 | WP3 part 3 `.crt` rows, regenerate all three TCs | - |
| Night 3 | WP5: full run through the tate runner, TATE report | ticket ID |
| Day 4 | Package, diff file, hand-over, reply | - |

Four working days and three night slots, from the day the two blockers below
clear.

## 4. What I need from Eyal

1. pc-3099 access details and its cabling: which DUT ports face which vports.
2. The VLAN range we may use on that rig.
3. Ticket ID, so the branch can be pushed and the suites can run on tate.
4. Which file he opened for E1, so I fix the right thing.
5. His exact text for the deprecated show commands and the tech support
   command, and the `allow-as-in` ruling.

Items 1 to 3 are what set the start date. The rest can arrive later without
holding up the work.

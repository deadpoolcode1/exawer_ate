---
title: "ATE — Command-line walkthrough"
subtitle: "AI-Assisted Test Plan & Automation Skeleton Generator · SOW PQ4476E"
date: "2026-08-19"
---

# What this is

A five-command walkthrough of the ATE tool as it stands today, on the EVPN
feature. Every transcript below is real output, captured on 2026-08-19 from
the working tree — nothing here is illustrative.

**There is no web interface yet.** The UI is milestone M5 (weeks 9–10) and has
not been started. Everything the tool does today it does from a terminal, and
that is what this document shows.

The pipeline, end to end:

```
documents  →  requirements  →  test plan (xlsx)          ← M1
           →  typed steps   →  Java suite + DUT config   ← M2
           →  run on a real device  →  fix  →  regenerate
```

Working directory for every command is the repository root.

\newpage

# 1. Documents in, test plan out

One command reads the feature folder, discovers the System Functional Spec,
the CLI document and the RFCs, and writes the test plan.

```
$ ate plan-feature EVPN

feature folder: references/EVPN
  SFS:        EVPN System Specification 1.00.docx
  CLI doc:    EVPN CLI 1.00.docx
  RFCs:       draft-ietf-bess-rfc7432bis-13.txt, rfc9785.txt
feature:        Ethernet VPN (EVPN)
requirements:   134
plan rows:      286
xlsx written:   plans/EVPN_test_plan_with_RFCs.xlsx
```

134 requirements become 286 plan rows and 717 atomic action rows, in the
9-column layout of `references/DHCP-snoopy_TP_with_PW.xlsx`.

## The same run reports what it could not do

Two of the messages it prints are more useful than the counts.

**Un-ingested RFCs.** The spec cites nine RFCs; two are in `references/` and
seven are not. The tool says so by name rather than quietly covering only what
it has:

```
warning: SFS cites 9 RFC(s); 7 referenced but NOT ingested into the engine:
  • RFC4364  • RFC4761  • RFC4762  • RFC6514
  • RFC7209  • RFC8340  • RFC8584
  (ingested & matched: RFC7432, RFC9785)
```

**Commands removed for want of grounding.** Any `show` command that cannot be
traced to an ingested document is stripped from the plan, and the removal is
listed and audited on a sheet:

```
command grounding: removed 2 ungrounded command(s) from the plan
  − `show mpls forwarding-table`  [FLOW-131, FLOW-133, FLOW-134]
  − `show mpls lsp`               [FLOW-131]
```

This is the anti-hallucination rule in operation: a command the documents do
not contain does not reach QA, and the audit sheet records what was taken out
and why.

\newpage

# 2. What changed since the last version

Requested by Eyal Ozeri, 2026-07-07 — each respin arrived as a fresh
1,600-row workbook with no statement of what had moved.

```
$ ate plan-diff plans/EVPN_test_plan_with_RFCs.xlsx

1 topics added, 0 removed, 8 changed (18 action rows edited)
rows: 698 -> 717
wrote plans/EVPN_test_plan_with_RFCs_CHANGES.md
```

With one argument it diffs against the copy committed in git; with two it
diffs any pair of workbooks.

The diff is keyed on the **stable identifiers the plan already carries** —
`FLOW-030`, `CLI:mac-limit`, `RFC7432bis-§7.2` — never on row numbers. A plan
whose rows all shifted by forty reports zero churn. A reworded action is
reported as one rewording rather than as a deletion plus an unrelated
addition.

Extract from the generated change file:

```markdown
## Topics added

- **CLI:weight** — weight — Sets the default weight for routes advertised
  by the neighbor or neighbor group
  _CLI CONFIGURATION — BGP EVPN ADDRESS-FAMILY_ · 9 action rows

## Topics changed

### CLI:allow-as-in — allow-as-in — Accepts routes up to the specified
### number of instances of the local AS number in the AS-Path attribute

- **~** ... configure `allow-as-in <value>` and commit the candidate config
  → ... configure `allow-as-in <number>` and commit the candidate config
- **+** Issue `allow-as-in <number>` with values: (a) the documented boundary
  values (1, 10) — valid per '1-10'; (b) invalid values: 0 (below range);
  11 (above range)
```

**Send this file with every version of the plan.**

\newpage

# 3. Test plan in, automation out

The same plan drives code generation. `--lab` names the testbed the suite is
being generated for and has no default, deliberately.

```
$ ate codegen --lab 2ac-core

wrote 8 file(s) under out/codegen/
  out/codegen/cmp/tests/evpn/EvpnCommands.java
  out/codegen/cmp/tests/evpn/EvpnParams.java
  out/codegen/cmp/tests/evpn/EvpnUtils.java
  out/codegen/cmp/tests/evpn/TC01_EvpnVlanBasedBringUp.java
  out/codegen/cmp/tests/evpn/TC03_EvpnType3ImetFlooding.java
  out/codegen/cmp/tests/evpn/bringUpParams.crt
  out/codegen/cmp/tests/evpn/configurations/compass/EVPN_Base.cfg
  out/codegen/cmp/tests/evpn/configurations/ixia/evpn_tester_setup.tcl
```

Four artifacts, not one: the JSystem test classes, the expected-value params
class, the device configuration, and the IXIA-side setup. The suite compiles
unmodified against `cmp-infra-project` and `cmp-tests-project` under
`javac -Werror -Xlint:all`.

## It also lists what it cannot yet assert

```
8 step(s) need real device output before their assertions mean anything:
  - FLOW-010.S09: Needs real `show evpn mac-address-table` output.
  - FLOW-010.S11: Needs a BGP session in Established state; the capabilities
                  block is absent while the peer is down.
  - FLOW-031.S06: Needs real `show evpn broadcast-domains` output with an EVI
                  configured; `show evpn bum routing-table` does not exist on
                  this build.
  ...
```

A step whose expectation has never been captured from a device is emitted as
a step that **warns and does not pass**. Every generated test ends with
`assertSomethingWasVerified()`, which fails the run if no falsifiable
assertion was made.

\newpage

# 4. The generated device configuration

`configurations/compass/EVPN_Base.cfg`, generated, not hand-written:

```
! Attachment circuits. A vlan-based EVI binds SUB-interfaces,
! never the port itself - the device rejects the commit otherwise.
!
! VLAN 3380 is written literally here, in the VPLS house
! style (VPLS_N1.cfg has literal `vlan-id 2` on literal `int2.1`),
! rather than as a find-and-replace placeholder. It comes from:
!   sut/pc3080.xml <general><vlans index="0"><number>3380</number>
!   - the first VLAN the SUT declares for this testbed
! The generated suite re-reads that same SUT slot at run time and
! FAILS if it does not match this number, so the literal cannot
! silently disagree with the rig it runs on.
!
interface int2
 admin-state up
!
interface int2.3380
 l2-transport enable
 vlan-id      3380
!
interface int3
 admin-state up
!
interface int3.3380
 l2-transport enable
 vlan-id      3380
```

Three things to note, all of them responses to review comments:

* the VLAN is a **literal number**, in the VPLS house style, not a
  find-and-replace placeholder inside an interface name;
* the file states **where the number came from**, so nobody has to ask;
* interface names stay placeholders (`int2`, `int3`) bound by
  `bringUpParams.crt` to the SUT's `data1` pool — which is exactly what
  Exaware's own `bringUpParams.crt` parameterises, and all it parameterises.

\newpage

# 5. The generator refuses to emit a test that cannot fail

This is the part worth dwelling on. Asking for the three-attachment-circuit
profile is refused, with the reasoning and the remedy:

```
$ ate codegen --lab 3ac

error: the suite asserts BGP-carried routes on a rig with no BGP session:
  FLOW-010.S10 (Verify the Type-3 IMET route for this EVI is originated into
    the local EVI table) asserts a BGP-carried route, but lab profile
    'lab-1dut-3ac' has no BGP session for it to arrive on
  FLOW-030.S05 ... FLOW-030.S10 ... FLOW-031.S05 ...

Those steps would read an empty table and pass. Profile 'lab-1dut-3ac'
cannot support them. Either:
  - generate against a profile with a core link (--lab 2ac-core), or
  - give this profile a CoreLink, which on pc-3080 needs a fourth
    DUT<->IXIA port.
Accepting the regression is not offered: the problem is not a missing
capability, it is an assertion that cannot fail.

$ echo $?
1
```

The rig has three DUT↔IXIA links. Spending one on the EVPN core link leaves
two attachment circuits; keeping three leaves no control plane. The tool will
not paper over the second case, because four of its steps would read an empty
table and report success.

## And a second gate on the package itself

Six capabilities that were proven on hardware are recorded with the host,
build, date and the line actually read off the device. The gate re-checks them
against the **emitted files** — not the profile, not the exit code:

```
$ python scripts/verify_handover_package.py out/codegen

verifying 8 artifact(s) under out/codegen
  [ok  ] underlay.igp
  [ok  ] underlay.mpls
  [ok  ] underlay.bgp
  [ok  ] underlay.bgp_evpn_af
  [ok  ] traffic.vlan_classified
  [ok  ] traffic.source_mac

OK - every capability proven on hardware survives in these files.
```

This exists because a hand-over once shipped with no IGP, no LDP and no BGP —
a regression of a fix already made and verified. It compiled, the `.crt`
validated, three suites ran green and the pipeline exited zero. Nothing
checked the artifacts. Now something does, and the hand-over script runs it
with no escape hatch.

\newpage

# 6. Talking to the device

Both commands are read-only and need the lab network.

```
$ ate verify-commands --host 10.3.80.1 --jump ilan@192.168.31.226
$ ate capture         --host 10.3.80.1 --jump ilan@192.168.31.226
```

`verify-commands` asks the device, by CLI completion rather than by execution,
whether each command in the registry exists. `capture` records what a
command's output actually looks like and turns it into an expectation —
refusing to record a rejection, an empty table, or output that is nothing but
a header or a legend.

**Device output outranks the documents.** Corrections the hardware has made to
document-derived decisions include:

| We had, from the documents | The device says |
|---|---|
| `show evpn mac address-table` | `mac-address-table` — with a hyphen |
| `clear evpn mac-address-table` | `mac address-table` — with a space |
| `show evpn global` | no such command; `summary` / `detail` |
| `l2-services evpn <n> import-rt` | lives under `auto-discovery` |
| a vlan-based EVI binds the AC port | it refuses; the AC must be a sub-interface |
| `mac-limit` default 250000 | range `<1-250000>`, default **65520** |

Each is recorded with the build it was observed on. The same DUT was re-imaged
mid-session once and the two images disagreed about whether EVPN existed at
all, so a claim without a build number is not a claim.

\newpage

# 7. Command reference

| Command | What it does |
|---|---|
| `ate plan-feature EVPN` | documents → requirements → test plan xlsx |
| `ate plan-diff <new.xlsx> [old.xlsx]` | ID-keyed change file for a respin |
| `ate codegen --lab 2ac-core` | plan → Java suite, `.crt`, `.cfg`, IXIA setup |
| `ate queue status` | which generated tests are selected, stale or approved |
| `ate match <plan.xlsx>` | how much of the plan maps to executable steps |
| `ate verify-commands --host … --jump …` | does the device offer this command? |
| `ate capture --host … --jump …` | what does its output actually look like? |
| `scripts/verify_handover_package.py <dir>` | re-check a client package's capabilities |
| `./modular_tools.sh regression` | pytest plus golden-output drift |

## Where the outputs land

| Path | Contents |
|---|---|
| `plans/EVPN_test_plan_with_RFCs.xlsx` | the test plan — the M1 deliverable |
| `plans/*_CHANGES.md` | the per-version change file |
| `out/codegen/` | the generated Java suite and device configuration |
| `deliverables/M2/` | the packaged hand-over with its evidence files |

## Honest status

| Milestone | State |
|---|---|
| M1 — Test plan generation | delivered, reviewed across six client rounds |
| M2 — Dirty queue & code generation | complete; three suites run on hardware |
| M3 — Multi-router plan generation | not started |
| M4 — Code generation, 10 use cases | not started |
| **M5 — Web UI & deployment** | **not started — there is no UI today** |

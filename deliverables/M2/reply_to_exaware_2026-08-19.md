**To:** Ron Auster; Oded Engel; Eyal Ozeri
**Cc:** Yossi Fridman; Yuval Hoffman; David Zelig; Shlomi Maman; Oded Ades; Shany Levy; Magen Margalit; Orly Aharon
**Subject:** ATE — answers to all three M2 review mails, and what changed

---

Hi all,

Ron asked me to refer to the three review mails together (Oded 16/8, Eyal 16/8,
Ron 12/8). This answers all three. Where something was our defect I say so
plainly, and where I need a decision from you it is marked.

Attached / in the package:

* `ATE_CLI_demo.docx` — a walkthrough of the tool, every transcript real
* `EVPN_test_plan_with_RFCs.xlsx` — regenerated
* `EVPN_test_plan_with_RFCs_CHANGES.md` — **the diff file Eyal asked for**

---

## 1. Eyal — the four points from 16 August

**(1) and (2) — no BGP session, and both configs lack OSPF/ISIS, LDP, BGP.**

You were right, and the important part is that this was a **regression, not an
omission**. The underlay was built and verified on hardware on 13 August (OSPF
Full, BGP Established). The 14 August package was then generated with a
three-attachment-circuit profile so that FLOW-030's MAC move had somewhere to
move to. That profile has no core link, three parts of the generator answered
its absence with "nothing", and the suite shipped with no IGP, no LDP and no
BGP on either side. **You reported the same defect twice, and you should not
have had to.**

Every gate we had passed it: it compiled, the `.crt` validated against your own
TemplateManager, three suites ran green, the pipeline exited zero. Nothing
checked the artifacts themselves.

That is fixed structurally rather than by intending to be more careful. Six
capabilities that were proven on hardware now carry the host, build, date and
the line actually read off the device; the checks read the **emitted files**,
not the profile and not the exit code; and a second gate re-checks them inside
a client package with no override. `ate codegen --lab 3ac` now **refuses**,
naming the four steps that would assert BGP-carried routes on a rig with no
BGP session.

**(3) — the VLAN shown as a parameter, and where 3380 comes from.**

Both halves of this were fair, and reading your VPLS suite showed why. Your own
`bringUpParams.crt` find-and-replace table parameterises `interface` names and
nothing else, and `VPLS_N1.cfg` carries a literal `vlan-id 2` on a literal
`int2.1`. We had invented a `vlan` substitution type that you do not use, and
then put its placeholder inside an interface name.

It is now literal, in your style:

```
interface int2.3380
 l2-transport enable
 vlan-id      3380
```

And the file states its own provenance, so nobody has to ask again:

```
! VLAN 3380 ... comes from:
!   sut/pc3080.xml <general><vlans index="0"><number>3380</number>
!   - the first VLAN the SUT declares for this testbed
```

One consequence worth knowing: a literal in the `.cfg` and a SUT lookup in the
Java are two sources for one value, and they could disagree silently — the DUT
sub-interface on one VLAN, the IXIA frames tagged with another, every command
succeeding and nothing ever learnt. The generated suite therefore re-reads that
SUT slot and **fails the run** if it does not match.

**(4) — the IXIA traffic items are built in an unfriendly raw manner; take the
example from the VPLS suite.**

Taken. I read `VplsUtils.java`, `VplsParams.java`, `VPLS_N1.cfg`,
`HVPLS_VlanOp.cfg`, your VPLS `.crt` and `ixia_lib.tcl` directly. Your idiom has
three parts and the one we were missing was the third:

1. traffic items referred to by name — we already did that;
2. a test suspends and unsuspends named items rather than rebuilding them;
3. **every traffic step asserts the Traffic Item Statistics table**, with
   expected Tx and Rx frame rates and a tolerance.

Point 3 is what makes your suites investigable, and it is exactly what ours
lacked. `EvpnUtils` now carries your five methods under your own names —
`changeSuspendStatus`, `enableTrafficItemsAndStart`,
`enableTrafficItemsAndStartSuspended`, `verifyTrafficItemsAreSuspended`,
`verifyTrafficItemStatistics` — and `EvpnParams` carries a `trafficTable` in the
`VplsParams` shape.

Worth calling out: `verifyIxiaStatistics` used to be a stub that could only emit
a warning. A traffic step therefore changed the chassis and proved nothing. It
is now a real assertion that can fail.

**What I could not adopt:** the `.ixncfg` is a proprietary binary and cannot be
authored from documents, so the items are still *built* in code. That
construction is now confined to a single `createTrafficItems()` call. **If you
give us an `.ixncfg` for the EVPN rig, it replaces that call outright** — that
is the last piece of the VPLS idiom we cannot reach on our own.

---

## 2. Oded — the TATE report and the 405 test cases

**There is no TATE report because the runs did not produce one.** The suites
were run with `org.junit.runner.JUnitCore` against a mirrored copy of the
framework on the CodeValue dev box, not through the JSystem runner on tate.
That executes the same test code against the same DUT, but it bypasses
JSystem's reporter — so there is no per-step HTML report and nothing was written
to the TATE DB.

What does exist is the full console log of each run, with the CompassReporter
step banners (1:1 with the test steps) and the device output beneath each.

For a real TATE report and DB records the suites need to run through your runner
on tate. I am happy to do that; it needs the branch pushed, which is still
waiting on a ticket ID — see the asks at the end.

**`test-report-20260814_133139.html` is not the TC results.** It is our own build
scorecard for the ATE generator, which is why the title still says "M1". It says
nothing about TC01/02/03. The 405 checks are on our side: unit tests of the
generator, code-coverage gates, and SOW traceability rows. The five failures are
coverage-percentage thresholds, not failing tests; the 26 skips are SOW rows for
M3/M4/M5. The TC01/02/03 evidence is in
`02_evidence/evidence_three_suites_green.txt`.

I will retitle that report so it cannot be mistaken for test results again.

---

## 3. Ron — the four questions from 12 August

**Why is pattern matching not 100%?** Those figures cover the whole test plan,
not the three test cases. 537 of 612 plan rows map to executable steps. The
residue is not a matcher weakness: those rows quote base-platform CLI commands
that are documented in the Command Reference Guide rather than in the EVPN CLI
document. A row we cannot ground becomes a compiling TODO stub rather than an
invented command. Ingesting the Guide is the lever, and it has now started — see
section 4.

**Did the CLI doc lack example outputs?** Yes, and that is the precise gap. The
document gives command syntax, not output layout, so the *shape* of what
`show evpn mac-address-table` prints cannot be known from it. `ate capture` runs
exactly the commands the generated scripts need against a real device and
records what comes back. It refuses to record a rejection, an empty table, or
output that is only a header or a legend — those would produce assertions that
pass on a broken device, and two of them had already got through before that
rule existed.

**Are the TODOs actionable for a human reviewer?** Each names the command, the
step it belongs to, and what is missing — for example *"Needs real
`show evpn broadcast-domains` output with an EVI configured; `show evpn bum
routing-table` does not exist on this build."* A step in that state **warns and
does not pass**, and every generated test ends with an assertion that fails the
run if nothing falsifiable was checked.

**Is the "what we need from you" list still current?** Partly, and one item is
now closed by us:

* the **source-MAC limitation is dissolved** — the IXIA field is
  `ethernet.header.sourceAddress-`**`2`**, not `-1`; the suffix is the field's
  position in the stack. No change to `ixia_lib.tcl` is needed. Please drop that
  ask.
* the **ticket ID** is still needed.
* **lab workspace files** — still useful, lower priority.

---

## 4. Not asked for, but you should know: the BGP knobs were invented

Eyal flagged on 6 July that the `af-l2vpn evpn` sub-config grammar looked
invented. It was. That table was hand-written "from standard BGP convention"
because we did not have your base CLI manual.

Now that the **Command Reference Guide v8.X.0** is in our references, I have
cross-checked every entry, and **all seven had at least one fabricated
element**:

| Knob | We had | The Guide |
|---|---|---|
| `private-as` | `{remove \| replace}` | `[remove \| leave]` |
| `policy` | `policy <name> {in \| out}` | `policy {in \| out} policy-name` — operands reversed |
| `maximum-prefix` | `<max> [<pct> [warning-only]]` | `number max threshold percent action [warn \| terminate]`, defaults 2097152 / 75 / warn |
| `allow-as-in` | `[<count>]` | `number`, range 1–10 |
| `capability` | one flat option list | sub-mode scoped: dynamic/route-refresh at neighbour level, graceful-restart/orf at the address family |
| `inbound-soft-reconfiguration` | bare command | `[enable \| disable]`, default disable |
| `route-reflector-client` | bare command | `[enable \| disable]`, default disable |
| `weight` | **missing entirely** | `weight weight-value`, 0–65535, default 0 |

The dangerous ones are not the gaps but the confidently wrong entries — a
reviewer cannot tell an invented default from a read one.

The grammar is now **read from the Guide**, not written by us. The
de-invention step Eyal asked for in July is gone, because it would now throw
away the real ranges he then asked to have back.

### One question only you can answer

The Guide states, for `allow-as-in`: *"This command is only available under
unicast SAFI, VRF default, and VPN SAFI."* That does not include `l2vpn evpn`.
But the SFS (EVPNS-REQ#20) lists `allow-as-in` as a knob the `af-l2vpn evpn`
sub-mode inherits.

Two Exaware documents, flatly disagreeing. We have not picked a side: the row is
emitted with the conflict stated in its Comment cell so QA settles it on a
device. **Eyal / Yossi — which is right?**

Separately, `group` appears in EVPNS-REQ#20 but has no command section in the
Guide. We report that rather than guessing at it.

### Also closed: VPLS is out of the EVPN plan

Eyal, 2026-07-07: *"the TP is for evpn"*. The EVPN CLI document describes
several commands under both `l2-services vpls` and `l2-services evpn`, and we
were carrying both modes through. The plan had a whole
`CLI CONFIGURATION — L2-SERVICES VPLS` section.

Scoped now, and the distinction matters: a **VPLS-only** command
(`mac-address-static (VPLS)`) is dropped outright, while a **shared** command
(`mac-limit`, `mac-aging-time`, `interface`, `auto-discovery`, `export-rt`,
`import-rt`) keeps its command, its ranges and its defaults, and loses only its
VPLS mode path. `interface (VPLS/EVPN)` now reads `interface (EVPN)`.

The extraction itself still records both modes faithfully — only the
deliverable is scoped — so the same parse would serve a VPLS plan later.

---

## 5. The diff file, at last

Eyal asked on 7 July for a diff with every version — *"I'm getting lost."* That
tool now exists and ships with this plan as
`EVPN_test_plan_with_RFCs_CHANGES.md`.

It diffs by the **stable identifiers the plan already carries** — `FLOW-030`,
`CLI:mac-limit`, `RFC7432bis-§7.2` — never by row number, so a plan whose rows
all shifted by forty reports no change at all, and a reworded step is reported
as one rewording instead of a deletion plus an unrelated addition.

You will receive it with every version from now on.

---

## What is verified, and what is not

I would rather be exact than reassuring.

**Verified today:**

* the generated suite compiles against `cmp-infra-project` and
  `cmp-tests-project` under `javac -Werror -Xlint:all`, on the dev box, against
  your real framework;
* 349 tests of the generator pass;
* the capability gate passes on the emitted files;
* the `.cfg`, the `.crt` and the IXIA setup are as described above.

**Not verified today:** the new traffic-statistics assertions and the VLAN
cross-check have **not yet executed on the DUT**. Bring-up on pc-3080 fails
before our code runs:

```
Fail: Failed to enter specific session mode. Wanted mode: ONL, Current mode: CLI
```

Two independent runs, twenty-five minutes apart, failed identically, with five
`Login incorrect` responses on the serial console in each. The ONL banner does
appear, so the console is reachable — the login the framework offers is being
rejected. That is lab state rather than anything in the suite: the same suite
ran green on this rig on 14 August, and today's build compiles clean against
your framework.

**Yuval / Shlomi — could someone check console access on pc-3080?** I will
re-run the moment it is available and report the result either way, pass or
fail.

I would rather tell you this than let three green checkmarks imply a hardware
run that did not happen.

---

## Asks

| # | Ask | Who | Why it matters |
|---|---|---|---|
| 1 | **Ticket ID** (`AUT-nnn` / `EM-nnnn`) | Yuval / Shlomi | blocks pushing the branch under its real name, and blocks a real TATE run |
| 2 | **Console access on pc-3080** | Yuval / Shlomi | bring-up cannot reach ONL mode; blocks hardware verification |
| 3 | **`allow-as-in` under `af-l2vpn evpn`** — Guide or SFS? | Eyal / Yossi | two of your documents disagree; we will not guess |
| 4 | **A fourth DUT↔IXIA port, or a decision** | Eyal / Yuval | three ACs *or* a control plane, not both. FLOW-030's MAC move needs the third AC; everything else needs BGP |
| 5 | **An `.ixncfg` for the EVPN rig** (optional) | Eyal | would replace the last piece of raw traffic construction |

Item 4 is the one I would most like an answer on, because it decides which
profile the next hand-over is generated from.

Best regards,
Ilan

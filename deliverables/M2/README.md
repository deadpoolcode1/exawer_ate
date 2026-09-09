# M2: Dirty Queue & Code Generation

SOW PQ4476E, weeks 3 to 4. This folder is the M2 hand-over: every SOW M2 bullet
mapped to the artifact that satisfies it, plus the evidence behind each claim.

## Status, 2026-09-09

Run on pc-3099 (10.3.99.1), 8.7.0 LAB 935, profile `lab-1dut-3ac-core`.

| Test | Result | Why |
|---|---|---|
| TC01 | red | bring-up restores the EVI, so "EVI is absent" fails first |
| TC02 | red | traffic reaches the DUT port, not the circuit |
| TC03 | red | same traffic cause |

### Works now

- **Bring-up stands the tester up by itself.** The `.crt` loads
  `EVPN_3AC_CORE.ixncfg`, three vports come up, protocols start and are
  checked. The DUT reaches OSPF `Full` and BGP `up` on 29.60.0.2.
- **Three attachment circuits**, two sharing `x-eth0/0/40` on different VLANs.
- **VLANs 1001-1003** from the tool, asserted not to clash with the SUT's 3399.
- **Each test creates the EVI it uses**, after asserting it absent.

### Two defects, both on the device

1. **bgpd aborts when an EVI is deleted.**
   `assert (_Bool)(ipi_evi_p)`, `bgp_evi.c:310`, `bgp_evi_delete`.
   Four cores in one day, reproduced by hand.
   -> `evidence_bgpd_crash_on_evi_delete.txt`
2. **`exaSystemConf_pc3099.cfg` restores the EVI**, so TC01 cannot start
   clean. The baseline needs re-saving without the EVPN instance.

### One thing still open on our side

Traffic transmits and the DUT's physical ports count it in bulk, but the
`vlan-id` sub-interfaces count zero and the EVI learns no MAC. Double
tagging ruled out.
-> `evidence_traffic_open_issue.txt`

7 of 25 verification steps carry assertions that can fail; the other 18 warn
and say why. Nothing here is reported as a pass that is not one.

Start with `02_evidence/lab_validation_pc3099.md`.

## What was actually sent

`Exaware_M2_handover_2026-09-09.zip` in this folder is the package as it went
to the client, kept verbatim. It is not regenerable: `build_handover_package.sh`
embeds a timestamped test report and a dated hand-over document, so a rebuild
produces a different file. One zip per delivery, not per rebuild.

## SOW M2 deliverables → artifacts

> **Latest run: 2026-09-09.** SUT **pc-3099** (`exa-il01-ec-3099`,
> 10.3.99.1), software **8.7.0 LAB 935**, lab profile `lab-1dut-3ac-core`.
>
> | Suite | Result | Stops at |
> |---|---|---|
> | TC01 bring-up | **`OK (1 test)`** | - |
> | TC02 Type-2 MAC/IP + local move | FAIL | IXIA: no vport configured |
> | TC03 Type-3 IMET + flooding | FAIL | the same single cause |
>
> TC02 and TC03 fail for one reason between them: `bringUpParams.crt` loads
> no IXIA configuration, so no frame can be offered. Every DUT-side step of
> both passes. One chassis run of `configurations/ixia/EVPN_traffic.tcl`
> closes it.
>
> Start with **`lab_validation_pc3099.md`**, then
> `evidence_tc01_run_pc3099.txt` and `evidence_shared_port_acs.txt`.
>
> The 2026-08-14 files (`evidence_three_suites_green.txt`,
> `lab_validation_pc3080.md`) describe a different suite on a different rig
> binding, using VLAN 3380. They are kept because they remain the evidence
> for what they claim, but they are **not** this drop.

| SOW M2 deliverable | Artifact | Evidence |
|---|---|---|
| Code generation based on selected tests by Exaware | `generated_suite/cmp/tests/evpn/` (6 files), driven by `ate codegen --selected-only`, which emits only what the queue marks SELECTED | `evidence_codegen_summary.txt` |
| Pattern matching implementation | `ate/codegen/patterns.py`, CLI `ate match` | `evidence_pattern_match.txt`, 537 / 612 rows (**87.7%**) mapped to typed steps |
| Demo: extract requirements from sample docs | `ate plan-feature EVPN` over `references/EVPN/` | `EVPN_test_plan_with_RFCs.xlsx`, 133 requirements, 269 plan rows, 698 action rows |
| Up to 3 integration-ready test plans | **TC01 / TC02 / TC03** in `generated_suite/` | `evidence_compile.txt`, compiles against Exaware's real framework; `evidence_three_suites_green.txt`, all three **pass on pc-3080** |

The dirty queue (`ate/codegen/queue.py`, CLI `ate queue`) is listed in the SOW
under M4 ("queue implementation for test selection") but was needed to make
"code generation based on selected tests" real, so it ships here. State in
`evidence_dirty_queue.txt`.

## Which parts are automatic, and which are not

Stated plainly, because "code generation" can be read as more than it is here.

| Stage | Automatic? |
|---|---|
| Source documents → requirements → test plan (269 rows) | **Yes**, parsed and AI-enriched |
| Test plan prose → typed executable steps | **Yes**, `patterns.py`, 87.7% recall, reported not spun |
| The 33 steps behind TC01/TC02/TC03 | **No, hand-curated** (`evpn_scripts.py`) |
| Typed steps → compiling Java | **Yes**, `java_emitter.py` |

The three scoped flows were curated deliberately: they are the ones Exaware
runs first, and step quality mattered more than reach on exactly those. The
mechanical path is the reach, it maps the other ~30 flows (1745 atomic rows)
onto the same `Step` IR.

**The two paths are now joined.** `ate codegen --from-plan <xlsx> --plan-flows
FLOW-020` generates a suite for a flow nobody curated, straight from the plan,
and it compiles under the same `-Werror -Xlint:all` gate. See
`mechanical_demo/`, `TCM020_EvpnAllActiveMultiHomingBringUpDfElection.java`
was written entirely by the tool.

For it to emit real commands rather than stubs, the `EvpnCommands` registry is
**auto-derived from the CLI doc**: 18 curated entries plus 106 derived from the
document's own 44 command definitions, 124 constants, all compiling. TCM020
now emits grounded configuration:

```java
cmp1.configAndValidate(EvpnCommands
    .INTERFACE_AGG_ETH_$_ETHERNET_SEGMENT_LOAD_BALANCING_MODE_ALL_ACTIVE.args("0"));
```

Honest reach: 9 of TCM020's 28 steps carry a grounded command, and 9 of 98
across six flows tried. The residue is mostly base-CLI commands (`show alarms`,
`show platform process`) documented in the **Command Reference Guide, not the
EVPN CLI doc**, extracting the CRG is the next lever. Ungrounded rows still
degrade to compiling TODO stubs carrying their original sentence, and every
mechanically derived step keeps a `todo`, so such a suite reports warnings
rather than passes until reviewed. The derivation rules and their rationale are
in `evidence_command_derivation.txt`.

## The three suites

| Test | Flow | Steps | Awaiting lab data |
|---|---|---|---|
| `TC01_EvpnVlanBasedBringUp` | FLOW-010 | 10 | 3 |
| `TC02_EvpnType2MacIpAdvertisement` | FLOW-030 | 17 | 9 |
| `TC03_EvpnType3ImetFlooding` | FLOW-031 | 6 | 3 |

Four artifact kinds per Exaware's own idiom: the `TCnn` test classes,
`EvpnParams` (expected values), `EvpnUtils` (verify helpers), and
`EvpnCommands`, a **separate** enum implementing `ICmpCliCmd` rather than
appended to the shared 1220-line `Commands`, so the suite creates no merge
conflict with their team.

Every command template is grounded in the EVPN CLI doc; `validate_grounding()`
**raises** at generation time if a template has no documented origin.

## Per-scenario device configuration

A suite in Exaware's tree is not only Java. Modelled on `cmp/tests/vpls/`, the
generator also emits:

| File | Contents |
|---|---|
| `bringUpParams.crt` | devices, per-test config files, intPool binding, before/after actions |
| `configurations/compass/EVPN_Base.cfg` | the EVPN service, in the device's own hierarchical config syntax |

Both follow the house conventions: `cleanBaseConfig` loads first with
LOAD_TYPE 1 (override) and the feature `.cfg` merges over it with LOAD_TYPE 2,
and the `.cfg` names `int1`/`int2`/`int3` placeholders that the `.crt`'s
find-and-replace table binds to the SUT's `data1` intPool, so one config
serves every testbed. That claim is no longer theoretical: the same files ran
unchanged on pc-3021 (`edgeCore`) and on pc-3080 (`UfiSpace`), where the
placeholders resolved to `x-eth 0/0/8`, `0/0/18` and `0/0/26`.

The **Java** now resolves attachment-circuit names from that same intPool at
run time, rather than using the lab profile's placeholder text. It did not, and
that sent `agg-eth-1.100` to a box whose ports are `x-eth 0/0/8`, see
`evidence_tc01_run_pc3080.txt`.

**Traffic items are built in code.** `EvpnUtils.createTrafficItems()` stands up
the three items over TCL (`configNewTrafficItem` → `…Endpoints` → `…Stream` →
`…FrameRate` → `applyTraffic`), with argument order verified against the proc
signatures in `ixia_lib.tcl`. So the suite needs no `.ixncfg` to have traffic at
all, a `TRAFFIC_CREATE` step is inserted ahead of the first traffic use in any
script that needs it.

One limit remains, and the generated code states it rather than implying
otherwise: `ixia_lib.tcl` has `editTrafficRawDestMacAddr` and **no source
equivalent**, while EVPN learns from *source* MACs. FLOW-030's premise that AC2
and AC3 share a source MAC therefore cannot be expressed, and each item reports
that at run time. See `evidence_traffic_generation.txt`.

Three things are deliberately **not** generated:

- **The underlay** (interface addressing, MPLS/LDP, BGP), lab data, absent
  from the SFS and CLI doc. Inventing addresses would put fiction into a file
  that gets typed at a real router; it must come from `cleanBaseConfig` or the
  site config. The attachment-circuit **sub-interfaces** are the one exception,
  and they are not underlay: a vlan-based EVI refuses to bind anything else, so
  `interface intN.100 / l2-transport enable` is part of the service under test.
- **The `.ixncfg`**, a binary IxNetwork save. No longer needed for traffic
  itself (built in code, above), but still the simplest route to source-MAC
  control. No row for it is emitted in the `.crt` at all: a row pointing at a
  missing file aborts bring-up for the whole suite, and a `//` comment inside a
  table breaks the template validation.
- **The ping table**, needs AC-side addressing we do not have.

The `.cfg`'s block structure and `!` terminators are derived mechanically from
flat command syntax and were **confirmed on hardware** (2026-08-11): an EVI was
configured on the DUT and `show configuration l2-services` printed exactly this
shape. It has since been loaded onto a device for real, pc-3080 accepted the
whole file and committed it.

The `bringUpParams.crt` passes Exaware's own
`TemplateManager.validateAgainstTemplate` (matching `bringUpParameters_C0_002`),
both standalone and inside the live bring-up. The check is not vacuous: adding
a single `//` line inside one of its tables makes the same validator reject the
file.

## Status: what is done and what is open

**Done.** All four M2 bullets. The suite compiles unmodified against
`cmp-infra-project` + `cmp-tests-project` (953 sources → 1454 classes, zero
errors; strict `-Werror -Xlint:all` gate on the generated files: zero warnings).
275 ATE tests pass.

**All three suites now run on real hardware.** On SUT **pc-3080**
(`exa-il01-uf-3080`, 8.7.0 LAB 22) TC01, TC02 and TC03 each complete under
JUnit + JSystem, `OK (1 test)`, exit 0, including the full bring-up that
pc-3021 could not reach. `show evpn detail` on the DUT afterwards lists the EVI
with its three attachment circuits bound. See `evidence_tc01_run_pc3080.txt`
and `lab_validation_pc3080.md`.

**Read `evidence_what_the_suites_assert.txt` before reading "green" as "the
scenarios pass."** Across the three runs there are 131 reported passes and
**one** of them checks EVPN behaviour, and that one currently compares an
empty route table with an empty route table. The rest are the framework's
infrastructure checks. Every verification step carries an empty expectation and
therefore warns instead of asserting, for two reasons: there is no traffic to
learn from without source-MAC control on the IXIA, and `ate capture`'s output
is not yet fed back into `EvpnParams` by `ate codegen`. The first is Exaware's,
the second is ours.

Two defects were found by that run, and both mattered more than the pass:

- A vlan-based EVI **rejects a physical port** as an attachment circuit; it
  needs a sub-interface. The generated `.cfg` now creates them, following the
  stanza Exaware's own VPLS suite uses.
- Before the fix, three configuration commands were **rejected by the device
  and the test still passed**, the CLI staged nothing, so the commit had
  nothing to do, so the framework logged a warning. Generated configuration
  steps now assert acceptance themselves, and a negative control (an
  out-of-range sub-interface) confirms the assertion fails when it should.

**Open, and deliberately so.** Expectations that could not be captured stay
empty and visible, a guessed assertion that silently passes is worse than an
explicit gap. Usable expectations are **2 of 11**, down from 7, because five of
those seven turned out to be the MAC table's legend with no MAC addresses in
it. `capture` now rejects those. The suite asserts less and means more;
`evidence_capture_pc3080.txt` shows one in full.

Earlier history, kept because the build matters in every claim: pc-3021 was
re-imaged mid-session from `8.7.0 LAB 904` (no EVPN in the data model at all)
to `LAB 22`, which **has** EVPN, and running against it overturned three
document-derived command decisions, `evidence_device_verified.txt`.
`lab_validation_pc3021.md` records the LAB 904 state and is superseded on the
EVPN question; keep it for that rig's details.

**One CLI-doc anomaly is carried through with a warning, not silently fixed:**
`unknow-mac-flooding` (missing `n`) is spelled that way in the CLI doc's syntax
line *and* in both parameter descriptions, which usually means the product
itself has the typo. No current step uses it.

## Reproducing

```bash
./modular_tools.sh plan-feature EVPN     # test plan from references/EVPN/
ate codegen -o <out>                     # emit the Java suite
ate codegen --selected-only              # only what the queue marks SELECTED
ate queue status                         # dirty-queue state
ate match plans/EVPN_test_plan_with_RFCs.xlsx
env -u PYTHONPATH .venv/bin/python -m pytest tests/ -q    # 275 tests
```

The compile gate is not reproducible from this repo alone, it needs a mirror
of Exaware's framework, which is not ours to redistribute. The recipe is in
`.claude/skills/exaware-framework/SKILL.md`.

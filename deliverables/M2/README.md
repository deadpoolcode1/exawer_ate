# M2 — Dirty Queue & Code Generation

SOW PQ4476E, weeks 3–4. This folder is the M2 hand-over: every SOW M2 bullet
mapped to the artifact that satisfies it, plus the evidence behind each claim.

## SOW M2 deliverables → artifacts

| SOW M2 deliverable | Artifact | Evidence |
|---|---|---|
| Code generation based on selected tests by Exaware | `generated_suite/cmp/tests/evpn/` (6 files) — driven by `ate codegen --selected-only`, which emits only what the queue marks SELECTED | `evidence_codegen_summary.txt` |
| Pattern matching implementation | `ate/codegen/patterns.py`, CLI `ate match` | `evidence_pattern_match.txt` — 537 / 612 rows (**87.7%**) mapped to typed steps |
| Demo: extract requirements from sample docs | `ate plan-feature EVPN` over `references/EVPN/` | `EVPN_test_plan_with_RFCs.xlsx` — 133 requirements, 269 plan rows, 698 action rows |
| Up to 3 integration-ready test plans | **TC01 / TC02 / TC03** in `generated_suite/` | `evidence_compile.txt` — compiles against Exaware's real framework |

The dirty queue (`ate/codegen/queue.py`, CLI `ate queue`) is listed in the SOW
under M4 ("queue implementation for test selection") but was needed to make
"code generation based on selected tests" real, so it ships here. State in
`evidence_dirty_queue.txt`.

## Which parts are automatic, and which are not

Stated plainly, because "code generation" can be read as more than it is here.

| Stage | Automatic? |
|---|---|
| Source documents → requirements → test plan (269 rows) | **Yes** — parsed and AI-enriched |
| Test plan prose → typed executable steps | **Yes** — `patterns.py`, 87.7% recall, reported not spun |
| The 33 steps behind TC01/TC02/TC03 | **No — hand-curated** (`evpn_scripts.py`) |
| Typed steps → compiling Java | **Yes** — `java_emitter.py` |

The three scoped flows were curated deliberately: they are the ones Exaware
runs first, and step quality mattered more than reach on exactly those. The
mechanical path is the reach — it maps the other ~30 flows (1745 atomic rows)
onto the same `Step` IR.

**The two paths are not yet joined.** `ate codegen` emits from the curated
lists; the matcher is exercised by `ate match`, which reports recall rather than
emitting Java. Both produce the same `Step` type, so joining them is small
work — group matched steps by flow into a `TestScript` and pass it to the
existing emitter — but it is not done, and until it is, the three delivered
suites do not by themselves demonstrate the SOW's 40–50% manual-effort
reduction. Generating a suite for an *uncurated* flow and compiling it under the
same gate is the demonstration that would, and it is the natural first move
into M4.

## The three suites

| Test | Flow | Steps | Awaiting lab data |
|---|---|---|---|
| `TC01_EvpnVlanBasedBringUp` | FLOW-010 | 10 | 3 |
| `TC02_EvpnType2MacIpAdvertisement` | FLOW-030 | 17 | 9 |
| `TC03_EvpnType3ImetFlooding` | FLOW-031 | 6 | 3 |

Four artifact kinds per Exaware's own idiom: the `TCnn` test classes,
`EvpnParams` (expected values), `EvpnUtils` (verify helpers), and
`EvpnCommands` — a **separate** enum implementing `ICmpCliCmd` rather than
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
find-and-replace table binds to the SUT's `data1` intPool — so one config
serves every testbed, and it lands on pc3021's pool unchanged.

Three things are deliberately **not** generated:

- **The underlay** (interface addressing, MPLS/LDP, BGP) — lab data, absent
  from the SFS and CLI doc. Inventing addresses would put fiction into a file
  that gets typed at a real router; it must come from `cleanBaseConfig` or the
  site config.
- **The `.ixncfg`** — a binary IxNetwork save, not derivable from documents.
  Its row in the `.crt` is emitted **commented out**, because a row pointing at
  a missing file aborts bring-up for the whole suite.
- **The ping table** — needs AC-side addressing we do not have.

The `.cfg`'s block structure and `!` terminators are derived mechanically from
flat command syntax and are marked UNVERIFIED in the file's own header: no
device that implements EVPN has been available to confirm them against real
`show configuration` output.

## Status: what is done and what is open

**Done.** All four M2 bullets. The suite compiles unmodified against
`cmp-infra-project` + `cmp-tests-project` (953 sources → 1454 classes, zero
errors; strict `-Werror -Xlint:all` gate on the generated files: zero warnings).
207 ATE tests pass.

**Open, and deliberately so.** 15 of 33 steps carry empty expectations. They
need real `show` output from a DUT that implements EVPN. On the reserved SUT
pc-3021 the DUT's build (`8.7.0: LAB 904`) has **no EVPN in its data model at
all**, so the suites cannot be executed there — see
`lab_validation_pc3021.md`. A guessed assertion that silently passes is worse
than an empty one, so they stay empty and visible.

This does not affect M2's status: the SOW asks for *integration-ready* test
plans, and execution is an M4-and-beyond concern that depends on Exaware
shipping an EVPN build.

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
env -u PYTHONPATH .venv/bin/python -m pytest tests/ -q    # 207 tests
```

The compile gate is not reproducible from this repo alone — it needs a mirror
of Exaware's framework, which is not ours to redistribute. The recipe is in
`.claude/skills/exaware-framework/SKILL.md`.

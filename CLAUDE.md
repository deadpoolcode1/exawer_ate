# CLAUDE.md — Workspace context for Claude Code sessions

This is the **ATE** (AI-Assisted Test Plan & Automation Skeleton Generator)
POC for Exaware, per SOW PQ4476E. Current milestone: **M2 — Dirty Queue & Code
Generation**. M1's deliverable is the xlsx test plan under `plans/`,
generated from documents under `references/`. M2's is the Java suite in
`deliverables/M2/generated_suite`, run on Exaware's hardware, shipped as a
hand-over package with its automation report.

## Inputs the pipeline expects

Documents live in `references/<FEATURE>/` (committed read-only) — one
sub-folder per feature, e.g. `references/EVPN/`. Output templates that
are not feature-specific (`DHCP-snoopy_TP_with_PW.xlsx`, `Feature Name
Test Plan Template.xlsx`) stay at `references/` top level.

The pipeline is designed to ingest three (later four) sources per
feature, auto-discovered from the folder by `ate plan-feature <NAME>`:

| Source | Format | Role |
|---|---|---|
| **SFS** (System Functional Spec) | `.docx` | Vendor spec — defines CLI commands, NETCONF, upgrade behaviour. Today: `EVPN System Specification 1.00.docx`. |
| **CLI doc** | `.docx` | Per-command syntax / parameters / defaults / Notes tables. Today: `EVPN CLI 1.00.docx`. |
| **RFC(s)** | `.txt` / `.docx` | Protocol mandates (MUST/SHALL clauses). Promoted to first-class requirements per client review 2026-05-14. Today: `draft-ietf-bess-rfc7432bis-13.txt`, `rfc9785.txt`. |
| **BGP CLI manual** (future) | `.docx` | Parent-protocol sub-config syntax that EVPN inherits but doesn't document (e.g. `allow-as-in`, `capability`, `maximum-prefix` under `af-l2vpn evpn`). Hand-curated in `ate/planner/cli_inheritance.py` until Exaware ships the doc. |

The reference test plan that defines the **output shape** is
`references/DHCP-snoopy_TP_with_PW.xlsx` — every generated TP must visually
match this layout (atomic-row-under-topic-banner, 9-column schema).

## Pipeline flow

```
                    INPUTS                                  OUTPUTS
                    ──────                                  ───────
  ┌─ SFS .docx   ─────┐
  │                   │
  │  EVPN CLI .docx ──┼─► REQUIREMENTS BUILDER ──► merged catalog ──┐
  │                   │       ├ extractor.py        (req + cli +     │
  │  RFC(s) .txt   ───┤       ├ rfc_extractor.py     synth_anchors + │
  │                   │       └ cli_inheritance.py    provenance)    │
  │ (later: BGP CLI)──┘                                              │
  │                                                                  ▼
  │                                          FLOW MATCH (flows.py) +
  │                                          CLI ROW FAMILIES (cli_rows.py)
  │                                                          │
  │                                            ┌─ enrich (ai_enricher.py)
  │                                            │
  │                                            ▼
  │                                          PlanRow blobs (multi-line
  │                                                          Setup/Action/Verify)
  │                                                          │
  │                                          atomic_rows.py decomposes
  │                                          into AtomicRow stream
  │                                                          │
  │                                                          ▼
  │                                                ┌─────────────────┐
  └─► xlsx_writer ────────────────────────────────►│ Test Plan xlsx  │
                                                   │ + Synth-Review  │
                                                   │ + Coverage      │
                                                   └────────┬────────┘
                                                            │  M2
                              ┌─────────────────────────────┴───────────┐
                              ▼                                         ▼
                  evpn_scripts.py (curated)              patterns.py + plan_scripts.py
                  33 steps, FLOW-010/030/031             (mechanical: plan rows → steps)
                              └─────────────┬───────────────────────────┘
                                            ▼
                                    script_ir (TestScript/Step)
                              commands.py + command_deriver.py
                              (registry: 18 curated + 106 from the CLI doc;
                               generation RAISES on an ungrounded template)
                                            │
                        ┌───────────────────┴───────────────────┐
                        ▼                                       ▼
                  java_emitter                            device_config
                  TCnn / TCM<nnn> · Params ·              bringUpParams.crt
                  Utils · EvpnCommands                    EVPN_Base.cfg
                        └───────────────────┬───────────────────┘
                                            ▼
        ═══════════════ THE DEVICE LOOP (M2) ═══════════════════════════
          ate verify-commands   does the device offer this command?
          ate capture           what does its output actually look like?
          javac + TemplateManager  does it compile / does the .crt validate?
                                            │
                                            ▼
                        fix the registry / the steps — a human decides,
                        the tools report. Device output outranks any
                        number of agreeing documents.
```

## Output xlsx — 9-column schema

Matches `references/DHCP-snoopy_TP_with_PW.xlsx`:

| # | Header | Content |
|---|---|---|
| 1 | Topic | Banner row label (`Trusted`, `FLOW-010 — Single-homed VLAN-Based EVPN bring-up`, `RFC7432bis §7.2 — MAC/IP Advertisement`). Empty on continuation rows. |
| 2 | Action | One-sentence verb phrase per row. |
| 3 | SFS / RFC Req ID | `EVPNS-REQ#NN`, `RFC7432bis-§7.2.1`, `CLI:allow-as-in`. Comma-joined for multi-coverage. |
| 4 | Expectation | One-sentence pass criterion (last action row of a topic carries the full Pass / Fail-on). |
| 5 | Monitor | `show` / `clear` / inspection commands (comma-joined). |
| 6 | Test Equipment | `DUT only`, `DUT + IXIA + neighbor PE`, … |
| 7 | Build number | QA fills. |
| 8 | Results | QA fills. |
| 9 | Comment | `synthesized — review` / `CLI inheritance — review` markers for auto-generated rows; QA fills bug numbers. |

Banner rows are tinted (blue for flows, yellow for RFC-synth, violet for
CLI-inherit). Atomic action rows inherit the banner's topic visually.

## Generating the deliverable

Per-feature (auto-discovers SFS / CLI doc / RFCs from the folder):

```
./modular_tools.sh plan-feature EVPN          # → plans/EVPN_test_plan_with_RFCs.xlsx
./modular_tools.sh plan_all                   # every references/<FEATURE>/ → plans/*.xlsx
```

Outputs:
- `plans/EVPN_test_plan_with_RFCs.xlsx` — main deliverable
- `plans/<FEATURE>_test_plan_with_RFCs.xlsx` per feature folder
- `out/*.json` — parsed IR per doc (gitignored)
- `results/*.html` — test reports (gitignored)

To override the auto-discovery (or generate from a single file outside
the folder convention):

```
ate plan references/EVPN/<spec>.docx -o plans/<name>.xlsx \
    --rfc references/EVPN/draft-ietf-bess-rfc7432bis-13.txt \
    --rfc references/EVPN/rfc9785.txt \
    --cli-doc 'references/EVPN/EVPN CLI 1.00.docx'
```

## Running the device loop

```
ate verify-commands --host 10.3.21.1 --jump ilan@192.168.31.226   # does the command exist?
ate capture         --host 10.3.21.1 --jump ilan@192.168.31.226   # what does its output look like?
```

Both are read-only. `verify-commands` probes by CLI completion and reports;
it never rewrites the registry. `capture` refuses to record a rejection or an
empty table as an expectation. Needs the VPN (a FortiToken each time) and
`paramiko<3.0`. Full recipe, including running a JUnit test against the DUT,
is in the `exaware-framework` skill.

## Conventions

- **`STATUS.md` is the project's front page — keep it current.** Update it
  whenever a milestone changes state, a SOW deliverable is met, a blocker
  appears or clears, or an honest limit of the tool is discovered. It must stay
  **short, plain and skimmable** — tables over prose, one screen, no history
  (git holds that). It exists so anyone can see where the project stands
  against the SOW in under a minute, so keep the "Honest limits" section
  genuinely honest: it is more useful than the ✅ column.
- **Device output outranks the documents.** If the DUT and the CLI doc
  disagree, the DUT wins and the correction is recorded with the build it was
  observed on — this box was re-imaged mid-session and the two images
  disagreed about whether EVPN existed. See the `exaware-framework` skill §10.
- **Nothing may fake a pass.** A generated test that reports success without
  checking anything is worse than no test: a red test gets fixed, a green one
  that checks nothing gets trusted. Enforced, not just intended
  (`ate/codegen/fake_pass.py`):
  - generation **raises** `FakePassError` on an expectation that could not
    fail — e.g. captured lines that are all header, rule or legend;
  - `ate codegen` reports a census: how many verification steps can actually
    fail versus only warn;
  - every emitted test ends with `evpnUtils.assertSomethingWasVerified()`,
    which **fails** the run if no falsifiable assertion was made;
  - a no-change assertion refuses an empty baseline ("nothing changed" is
    trivially true when there was nothing to change);
  - a configuration command the device rejected fails the step, and
    `ate capture` refuses output with no state-bearing content.
  The corollary for anything talking to a device: **"the call returned without
  error" is not evidence it did anything — read something back.** Exaware's
  `performFunctions` reported "ended without errors" for 34 TCL calls that
  never ran, which hid the fact that no IXIA traffic was ever created.
- **A capability proven on hardware may not silently disappear.** The underlay
  was built and device-verified on 2026-08-13 (OSPF FULL, BGP Established)
  after Exaware reported it missing. On 2026-08-14 the hand-over was generated
  with `--lab 3ac` to get a third AC, that profile has no core link, and three
  emitters answered the absence with `[]`/`None` — so the package shipped with
  no IGP, no LDP and no BGP on either side, and **the client reported the same
  defect twice.** Enforced in `ate/codegen/capabilities.py`:
  - capabilities carry a `Proof` (host, build, date, evidence file, the line
    actually read off the device); a proven one is a ratchet;
  - detectors read the **emitted artifacts**, never the profile or the exit
    code — that regression had a healthy pipeline that exited zero and three
    green tests;
  - `ate codegen` **raises** on a regression and prints the exact
    `--accept-regression <id>` needed to override it deliberately;
  - `scripts/verify_handover_package.py` re-checks the same capabilities
    against the files inside a client package and has **no** escape hatch, so
    a weakened suite can be generated but not shipped. It runs from
    `build_handover_package.sh` under `set -e`.
  Two corollaries:
  **An emitter returning nothing is a claim that must be justified, not a
  fallthrough** — this is the generation-side twin of the fake-pass rule.
  `LabProfile.core` therefore has no default: absence is a `NoCore` carrying a
  `reason` and an `accepted_by`, both of which reach the generated `.cfg`.
  **A step title may not apologise for the rig.** TC01 shipped saying "Verify
  the Type-3 IMET route ... (no BGP peer on this rig)" — visible, accurate,
  and read by everyone as a known limitation rather than the defect it was.
  If the rig cannot support an assertion, fix the rig or drop the step.
- **Flow IDs are stable** (`FLOW-NNN`). Reviewers cite "FLOW-010 step 2";
  never renumber existing flows on regeneration.
- **Cache salt v6** in `ate/planner/ai_enricher.py`. The committed
  `ai_cache.json` covers the EVPN spec; bumping the salt forces a full
  re-bake (~10 h via the Claude Pro CLI backend per
  `memory/project_m1_full_bake_cost.md`).
- **Column schema locked** by `tests/test_planner.py::test_xlsx_columns_match_template_schema`.
  Changing the 9-column header requires updating that test in the same commit.
- **Provenance tags** flow from `requirements_builder.py` →
  `atomic_rows.py` → `xlsx_writer.py`. `synth` (RFC orphan auto-row) and
  `cli-inherit` (BGP sub-config) rows surface on the "Synthesized — Review"
  sheet.
- **References are read-only**: never edit anything under `references/`.
- **Client mail is short.** Eyal Ozeri on 2026-09-08, about the 24 August
  reply: "There's a lot of text in the response which I find
  irrelevant/confusing. I'll try to be brief." Answer his points in his own
  order, one or two lines each, and say plainly whether each is done, open or
  blocked. No background, no rationale he did not ask for, no restating his
  question back at him. Detail (logs, tables, evidence) goes in the attached
  package, not in the mail body.
- **Commit messages**: never add `Co-Authored-By: Claude …` trailers,
  `🤖 Generated with Claude Code` footers, or any other mention of
  Claude / Anthropic / the AI assistant in commit messages, PR
  descriptions, or other repo-visible authorship metadata.

## Lessons for the general tool (requirements → test plan → code)

The goal is a general tool, not an EVPN suite. These came from EVPN on
Exaware's framework, but each one is about the pipeline, and each was paid for
with a client review round. Apply them to any feature or vendor.

1. **A generated test is judged by what it proves, not by being green.** A
   domain expert (Eyal, 2026-09-30) found green steps that proved nothing:
   flooded traffic counted as forwarding, the local EVI table read as
   "advertised", aging tested on a setup that never forwarded learned
   traffic. For every assertion ask: would this step fail if the feature
   were broken? Pick the stimulus so pass and fail look different (known
   unicast, not broadcast; one egress counter per AC, not a port total).
2. **Never turn captured behavior into the expectation without judging it.**
   TC02 step 27 expected 2000 pps because the device flooded at capture time.
   Capture gives the shape of the output; the plan says what is correct.
3. **Prove a design by hand on the device before changing the generator.** The
   loopback BGP, the unicast items and the EVPN capability were each shown
   with a few CLI and IxNetwork commands first
   (`evidence_loopback_and_unicast_pc3080.txt`). That is also how a wrong
   blocker dies: we believed EVPN negotiation needed a license; the smallest
   config showed it did not.
4. **Learn the target framework's idioms from its own suites and runs.** One
   commit per service, protocols started in the `.crt` do-before, the ping
   list, the per-AC counters: all are how their engineers write tests, and a
   reviewer flags anything else. Read a sibling suite (VPLS) before
   generating a new one. Their APIs can hold shared mutable state (command
   enums), so emit the simplest call shape.
5. **Compile what you generate, and never run what did not compile.** Unit
   tests on generated text are not a compiler. Deploy goes through
   `scripts/lab/deploy_suite.sh`, which stops on javac or `.crt` failure.
6. **Gate every artifact that ships, not just the code.** Each stale artifact
   reached the client once: a report from older code, step titles that
   differed from the Java, a hand-over document three weeks old. Each now
   has a gate under `build_handover_package.sh` (`verify_handover_package.py`,
   `verify_automation_report.py`, `verify_handover_docx.py`). A new artifact
   type gets a gate the day it is added.
7. **The report is the product the reviewer reads.** Every check shows
   Expected vs Output, titles say exactly what the step does, and the inputs
   fed to the engine ship with it (`03_test_plan/TC_sources.md`). Reviewers
   judge the report, not the generator.
8. **Separate rig failures from test failures, out loud.** Retry only deaths
   before step 1, never a failed step, and tell the client the rig failure
   rate rather than hiding the retries.
9. **Hardware runs outlive the session.** Long runs go `nohup` on the dev box,
   waits tolerate VPN drops, and a `RESUME_<date>.md` records the exact next
   command, so work can stop and continue at any point.

## Where memory lives

This project's auto-memory directory is
`~/.claude/projects/-home-ilan-work-AxaWear-ate/memory/`. The index is
`MEMORY.md` in that folder. Key entries:

- `project_sow_and_inputs.md` — SOW deliverable table + reference doc paths
- `project_m1_scope_expansion.md` — M1 includes the Test Plan, not just the parser
- `project_m1_yossi_respin.md` — what changed for Yossi's 2026-05-07 review
- `project_m1_qa_respin_2026-05-10.md` — flow-driven respin (76 flow rows + 88 CLI rows)
- `project_m1_full_bake_cost.md` — 820 rows AI-enriched in 10 h 45 m

When opening a new Claude Code session in this repo, read `MEMORY.md`
first — it's auto-loaded into the system context but the named files
contain the details.

## Run the test suite

```
./modular_tools.sh regression    # pytest + golden drift
./modular_tools.sh run-tests     # full M1 scorecard, HTML report
```

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
| **Capture real expectations** | `ate capture` | ✅ **2 usable, 9 empty, 0 unsupported** |
| **Run the suite on the DUT** | `javac` + JUnit/JSystem | ✅ **TC01 green on pc-3080** |
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

## TC01 runs green on hardware — and what that is worth

On **pc-3080** (`exa-il01-uf-3080`), `TC01_EvpnVlanBasedBringUp` completes under
JUnit + JSystem: `OK (1 test)`, exit 0, full bring-up included. Afterwards the
DUT shows `evi-1` with its three attachment circuits bound.

Two defects that run exposed matter more than the pass:

1. A vlan-based EVI rejects a port as an attachment circuit. Now generated as
   sub-interfaces, following the stanza Exaware's own VPLS suite uses.
2. **Three configuration commands were rejected by the device and the test
   still passed** — nothing was staged, so the commit had nothing to do, so the
   framework logged a warning. Generated config steps now assert acceptance
   themselves; a negative control (out-of-range sub-interface) turns the run red.

`deliverables/M2/evidence_tc01_run_pc3080.txt`.

## Honest limits

- **A green TC01 is narrower than it sounds.** It means every configuration step
  was accepted and committed and the bring-up completed. It does **not** mean
  the verification steps asserted anything: **2 of 11** expectations are
  captured and usable, the other 9 report a warning.
- **Usable expectations dropped from 7 to 2, and that is a correction.** Five of
  the previous seven were the MAC table's legend with no MAC address in it — an
  assertion that passes on any device, working or broken. `capture` now refuses
  them.
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

## Blocked on Exaware

| # | Item | Impact |
|---|---|---|
| 1 | **A src-MAC proc in `ixia_lib.tcl`** (their infra file) *or* the `.ixncfg` | No traffic to learn from → 9 of 11 expectations stay empty; blocks the MAC-move assertions |
| 2 | **A BGP EVPN peer** for the DUT | The four `show bgp l2vpn evpn table evi detail` expectations have nothing to show |
| 3 | **Ticket ID** for the branch (`AUT-nnn` / `EM-nnnn`) | Blocks handover under its real name; push path solved via tate (10.1.70.200) |
| 4 | **Confirmation on the EVI knobs and multi-homing config absent from LAB 22** | Either the CLI doc is ahead of the build or the build lacks them — we report, we do not guess |

## Next

1. Extract the Command Reference Guide v8.X.0 → grounds the base-CLI commands (the remaining ~90% of mechanical rows)
2. Push the branch once a ticket ID exists
3. Start M3 (multi-router plan generation)

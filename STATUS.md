# ATE — Project Status

**SOW:** PQ4476E — AI-Assisted Test Plan & Automation Skeleton Generator (10 weeks, 5 milestones)
**Updated:** 2026-08-12

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
| **Verify commands on a device** | `ate verify-commands` | ✅ swept 123 templates; show/clear half trusted, config half not yet |
| **Capture real expectations** | `ate capture` | ✅ **7 captured, 3 empty, 0 unsupported** |
| Build IXIA traffic items | `ate codegen` | ✅ in code, no `.ixncfg` (src MAC still blocked) |

## M2 — SOW bullets

| SOW bullet | Status |
|---|---|
| Code generation from selected tests | ✅ TC01/TC02/TC03 via the dirty queue |
| Pattern matching | ✅ 537/612 rows (87.7%) typed |
| Demo: extract requirements from docs | ✅ 133 reqs → 269 plan rows |
| Up to 3 integration-ready test plans | ✅ compile against the real framework |

Gates: 953 sources → 1454 classes, 0 errors; generated files pass `-Werror -Xlint:all`; `bringUpParams.crt` passes `TemplateManager.validateAgainstTemplate`. 242 ATE tests pass.

## The device loop — why it exists

Added 2026-08-11 after running on SUT pc-3021. "Grounded in the documents" is necessary and **not sufficient**: the device overturned three decisions we had reasoned to from the specs.

| We had | The device says |
|---|---|
| `show evpn mac address-table` | **`mac-address-table`** (hyphen) |
| `clear evpn mac-address-table` | **`mac address-table`** (space) — the product uses *both*, per command |
| `show evpn global` | no such command — `summary` / `detail` |
| `show evpn bum routing-table` | no such command — `broadcast-domains` carries the BUM label |
| `l2-services evpn <n> import-rt` | lives under `auto-discovery` |
| `show interface … detail` | no `detail` under `show interface` |
| `show bgp l2vpn evpn table evi evi-name <n>` | only the bare `… table evi [detail]` works without BGP state |

The first two are the cautionary pair: we overrode the CLI doc's syntax cell using three *other* agreeing sources and were wrong, then propagated that "fix" onto the `clear` form and broke it too. The doc was never self-contradictory — the product genuinely spells the two commands differently. **Device output outranks any number of agreeing documents.** Detail in `deliverables/M2/evidence_device_verified.txt`.

Every command the suite uses is now confirmed present: `ate capture` reports **0 unsupported**, 7 captured, 3 empty pending traffic/BGP state.

The DUT was also re-imaged mid-session — 8.7.0 **LAB 904** (no EVPN at all) → **LAB 22** (EVPN present). Any claim about the build must name the build.

## Honest limits

- **The 3 delivered suites are hand-curated at step level.** The tool emits the Java; a human wrote the 33 steps. Mechanically generated suites are prefixed `TCM<nnn>` so the two can never be confused.
- **The mechanical path grounds ~10% of its steps.** Registry is auto-derived from the CLI doc (18 curated → **124**). The residue quotes base-CLI commands (`show alarms`, `show platform process`) documented in the **Command Reference Guide, not the EVPN CLI doc** — extracting the CRG is the next lever. Ungrounded rows degrade to compiling TODO stubs; nothing is invented.
- **Traffic items are now built in code — but the source MAC still can't be set.** `EvpnUtils.createTrafficItems()` builds them over TCL (`configNewTrafficItem` → `…Endpoints` → `…Stream` → `…FrameRate` → `applyTraffic`), with argument order verified against `ixia_lib.tcl`'s proc signatures, so no `.ixncfg` is needed to have traffic at all. **However** that library has `editTrafficRawDestMacAddr` and *no source equivalent*, and EVPN learns from source MACs — so FLOW-030's premise that AC2 and AC3 share a source MAC cannot be expressed. The generated code reports that rather than implying it worked. Not yet run on a chassis: bring-up doesn't reach the test body.
- **`TC01` does not complete bring-up.** It runs under JUnit+JSystem against the real DUT and reaches ONL-level setup before needing lab-workspace files that live on Exaware's runner.
- **The config half of `verify-commands` is not yet trustworthy.** A full sweep ran over 123 templates: the **show/clear half is sound** (35 supported / 31 missing, spot-checked by hand — e.g. `show interface … detail` genuinely does not exist in this build), and it produced the CLI-doc-vs-build gap mechanically. The **config half is not** — `l2-services evpn %s mac-limit %s` is reported missing while the device itself offers `mac-limit`, so at least one of those 48 verdicts is false and none should be acted on. Three fixes so far (mode drift, buffer desync, per-probe `configure`/`abort`); the last works on a 4-command spot check but not across a 57-probe sweep. Remaining suspect: `abort` prompting for confirmation with pending changes, leaving the channel one response behind. Next: answer that prompt or use a fresh SSH session per config probe. See `deliverables/M2/evidence_command_verification.txt`.

## Blocked on Exaware

| # | Item | Impact |
|---|---|---|
| 1 | **Lab workspace for a full bring-up** (site config, ONL images, terminal-server plumbing) | `TC01` stops mid bring-up |
| 2 | **Ticket ID** for the branch (`AUT-nnn` / `EM-nnnn`) | Blocks handover; push path solved via tate (10.1.70.200) |
| 3 | **A src-MAC proc in `ixia_lib.tcl`** (their infra file) *or* the `.ixncfg` — traffic itself is now built in code | Blocks only MAC-move/learning assertions |
| 4 | **31 commands the CLI doc has and LAB 22 lacks** — full list in `evidence_command_verification.txt` (`show evpn global`, `… bum routing-table`, `… ethernet-segments`, `… frozen mac-addresses`, `show bgp table evpn ethernet-segment`, `show interface … detail`) | Doc vs build; 5 expectations stay open |
| 5 | **DUT pc-3021 has a Critical alarm** — `PSU PSU-1 is Failed` | Pre-existing; `@After` alarm checks will look flaky |

## Next

1. Fix config-mode probing (fresh `configure`/`abort` per probe), then act on the 31 confirmed show/clear mismatches
2. Extract the Command Reference Guide v8.X.0 → grounds the base-CLI commands (the remaining ~90% of mechanical rows)
3. Push the branch once a ticket ID exists
4. Start M3 (multi-router plan generation)

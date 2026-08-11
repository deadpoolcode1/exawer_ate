# ATE — Project Status

**SOW:** PQ4476E — AI-Assisted Test Plan & Automation Skeleton Generator (10 weeks, 5 milestones)
**Updated:** 2026-08-11

## Milestones

| MS | Topic | Weeks | Pay | Status |
|---|---|---|---|---|
| M1 | Test Plan Generation | 1–2 | 15% | ✅ Delivered — plan reviewed across 6 client rounds |
| M2 | Dirty Queue & Code Generation | 3–4 | 15% | ✅ Complete — tagged `m2-delivery`, not yet invoiced |
| M3 | AI Test Plan Generation (multi-router) | 5–6 | 30% | ⬜ Not started |
| M4 | Code Generation (10 use cases) | 7–8 | 20% | ⬜ Not started |
| M5 | Web UI & Deployment | 9–10 | 20% | ⬜ Not started |

## M2 — what is done

| SOW bullet | Status |
|---|---|
| Code generation from selected tests | ✅ TC01/TC02/TC03, selected via the dirty queue |
| Pattern matching | ✅ 537/612 rows (87.7%) typed |
| Demo: extract requirements from docs | ✅ 133 reqs → 269 plan rows |
| Up to 3 integration-ready test plans | ✅ compile against the real framework |

Gate: 953 sources → 1454 classes, 0 errors; generated files pass `-Werror -Xlint:all`. 218 ATE tests pass.

## Honest limits

- **The 3 delivered suites are hand-curated at step level.** The tool emits the Java; a human wrote the 33 steps.
- **The mechanical path works but grounds almost nothing.** Plan → typed steps → compiling Java runs end to end (`TCM020`, compiles), but only 6 of 142 CLI snippets resolve to a command. Cause: the `EvpnCommands` registry is 18 hand-written entries covering only the curated flows. **Fix = auto-derive the registry from the CLI doc's 44 extracted commands.** This is the #1 M4 task.
- **DUT config is generated; IXIA config cannot be.** `bringUpParams.crt` + `configurations/compass/EVPN_Base.cfg` are emitted in the house format (modelled on `cmp/tests/vpls/`). The `.ixncfg` is a binary IxNetwork save — its `.crt` row ships commented out so a missing file cannot abort bring-up. The `.cfg` omits the underlay (lab data) and its block structure is unverified against a real EVPN device.
- **Nothing has ever been executed on hardware.** 15 of 33 steps hold empty expectations by design.

## Blocked on Exaware

| # | Item | Impact |
|---|---|---|
| 1 | **An EVPN-capable build.** Reserved SUT pc-3021 runs 8.7.0 LAB 904, which has no EVPN in its data model | Blocks all execution + the 15 open assertions |
| 2 | **Ticket ID** for the branch (`AUT-nnn` / `EM-nnnn`) | Blocks handover; push path itself is solved (via tate 10.1.70.200) |
| 3 | **`.ixncfg`** with 3 traffic items, AC2/AC3 sharing MACs | Blocks the MAC-move test |

## Next

1. Auto-derive `EvpnCommands` from the CLI doc → makes mechanical generation real (M4)
2. Confirm the generated `.cfg` block structure against a real EVPN `show configuration`
3. Push the branch once a ticket ID exists
4. Start M3 (multi-router plan generation)

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

Gate: 953 sources → 1454 classes, 0 errors; generated files pass `-Werror -Xlint:all`. 230 ATE tests pass.

## Device-verified (2026-08-11)

The DUT was re-imaged mid-session: 8.7.0 **LAB 904** (no EVPN at all) → **LAB 22** (**EVPN present**). The operative fact is the current one. Three document-derived decisions were overturned by the device — most notably `show evpn mac-address-table` takes a **hyphen**, not the space we had reasoned our way to from three agreeing documents. See `deliverables/M2/evidence_device_verified.txt`.

## Honest limits

- **The 3 delivered suites are hand-curated at step level.** The tool emits the Java; a human wrote the 33 steps.
- **The mechanical path now writes real tests, but reaches ~10% of rows.** The registry is auto-derived from the CLI doc (18 curated → **124 total**), so `TCM020` (all-active multi-homing) emits grounded `configAndValidate` calls with no hand-written step. Across the plan it grounds 9 of 98 steps. The residue is base-CLI commands (`show alarms`, `show platform process`) documented in the **Command Reference Guide, not the EVPN CLI doc** — extracting the CRG is the next lever. Ungrounded rows still degrade to compiling TODO stubs; nothing is invented.
- **DUT config is generated; IXIA config cannot be.** `bringUpParams.crt` + `configurations/compass/EVPN_Base.cfg` are emitted in the house format (modelled on `cmp/tests/vpls/`). The `.ixncfg` is a binary IxNetwork save — its `.crt` row ships commented out so a missing file cannot abort bring-up. The `.cfg` omits the underlay (lab data) and its block structure is unverified against a real EVPN device.
- **The suite has now run on hardware.** TC01 executed under JUnit+JSystem against the real DUT; bring-up got through template validation, topology, terminal-server login and ONL setup before stopping for lab-workspace files that live on their runner. Not a code defect — an integration task with Exaware.
- **6 of 11 expectations are now filled from real hardware.** `ate capture` configured nothing itself; an EVI was created on the reserved SUT, output captured, then removed (DUT left clean). The other 5 name commands the device does not have.

## Blocked on Exaware

| # | Item | Impact |
|---|---|---|
| 1 | **Lab workspace for a full bring-up** (site config, ONL images, terminal-server plumbing) | TC01 stops mid bring-up; needs their runner |
| 2 | **Ticket ID** for the branch (`AUT-nnn` / `EM-nnnn`) | Blocks handover; push path itself is solved (via tate 10.1.70.200) |
| 3 | **`.ixncfg`** with 3 traffic items, AC2/AC3 sharing MACs | Blocks the MAC-move test |
| 5 | **Confirm the 5 commands the device lacks** (`show evpn bum routing-table`, `show bgp l2vpn evpn table evi evi-name …`) — CLI doc vs build | 5 expectations stay open |
| 4 | **DUT pc-3021 has a Critical alarm** — `PSU PSU-1 is Failed` | Pre-existing; `@After` alarm checks will look flaky |

## Next

1. Extract the Command Reference Guide v8.X.0 → grounds the base-CLI commands the plan quotes (the remaining ~90% of mechanical rows)
2. Confirm the generated `.cfg` block structure against a real EVPN `show configuration`
3. Push the branch once a ticket ID exists
4. Start M3 (multi-router plan generation)

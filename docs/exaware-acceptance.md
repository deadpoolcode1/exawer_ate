# M1 Spot-Check Form (PQ4476E)

To be completed by an **Exaware reviewer** at end of Week 2. This is the human gate that the numeric scorecard cannot replace.

Per SOW PQ4476E §5, the M1 deliverable is a **Test Plan (single router) for Exaware review and approval**. This form drives that review.

## Setup (one minute)

```bash
./modular_tools.sh setup                    # only the very first time
./modular_tools.sh plan-feature EVPN        # generates plans/EVPN_test_plan_with_RFCs.xlsx
./modular_tools.sh parse "references/EVPN/EVPN System Specification 1.00.docx" -o ir.json
```

You now have:
- `plans/EVPN_test_plan_with_RFCs.xlsx` — the **deliverable artifact** (single-router test plan)
- `ir.json` — the structured IR the plan was generated from

## Verification tasks

The reviewer fills in the answers below.

### 1. Requirement anchor preservation (M1.d)

Open `ir.json`, search for the substring `EVPNS-REQ#`. The parser should preserve every requirement anchor present in the source document.

> **Q1.** List 3 `EVPNS-REQ#NN` anchors you verified appear correctly in `ir.json`:
>
> 1. EVPNS-REQ# ___________
> 2. EVPNS-REQ# ___________
> 3. EVPNS-REQ# ___________

### 2. CLI configuration block fidelity (M1.b)

Open any CLI configuration block in the source DOCX (e.g., the EVPN VLAN-Based Service Type configuration example in §2.3.1.2). Locate the same block in `ir.json` (search for `"kind": "code"`).

> **Q2.** Paste the source block here:
>
> ```
>
>
>
> ```
>
> Paste the IR `code` block here:
>
> ```
>
>
>
> ```
>
> Are they identical? **[Y / N]** ___
>
> If N — what differs?

### 3. Table structure preservation (M1.c)

Pick any table from the EVPN spec source (e.g., Table 1: EVPN models, Table 2: EVPN Service Interface).

> **Q3.** Table picked: ___________________________________________
>
> Row count in source: ____  Row count in IR: ____  Match? **[Y / N]** ____
>
> Cell count in any row: source ____, IR ____  Match? **[Y / N]** ____

### 4. Test Plan deliverable review (PQ4476E §5 — Test Plan single router)

Open `plans/EVPN_System_Specification_1.00.xlsx`.

> **Q4.** Does the **Test Plan Topics** sheet have one section per template Category (CLI configuration, Basic Functionality, On-The-Fly, Packet validation, Malformed packets, Feature interaction, 3rd Party Interop, Scale, Performance, Robustness, PM, Alarms/Logs, Upgrade, HA, Long run, Management, Tech-support)? **[Y / N]** ___
>
> **Q5.** Pick any 3 rows. Confirm the `SFS Requirement id` column references a real `EVPNS-REQ#NN` from the source document.
> Row 1: req_id = ________  Found in source spec? **[Y / N]** ___
> Row 2: req_id = ________  Found in source spec? **[Y / N]** ___
> Row 3: req_id = ________  Found in source spec? **[Y / N]** ___
>
> **Q6.** Open the **Requirements** sheet. Pick any requirement; confirm Title and Description summarize the source section accurately. **[Y / N]** ___
>
> **Q7a.** Look at the AI-enriched rows for `EVPNS-REQ#30` (VLAN-Based Service Type) — they should reference specific values from the spec (vlan-id 4 / 6, x-eth 0/0/1..3, agg-eth 1..2, `service-type vlan-based`). Are these test steps domain-correct and a useful starting point that you would EDIT rather than write from scratch? **[Y / N]** ___
>
> **Q7b.** Same for `EVPNS-REQ#280` (MAC/IP Address Advertisement) — rows should reference Type-2 route fields, MPLS LT1 label, `show bgp l2vpn evpn route-type 2`. Domain-correct? **[Y / N]** ___
>
> **Q7c.** All 382 rows are AI-enriched (Claude). Spot-check 3 randomly chosen rows from any other requirement (e.g. #110 ESI types, #160 MAC Mobility, #390 Alarms). Are the action steps and expectations feature-specific and domain-correct (not generic boilerplate)? **[Y / N]** ___
>
> **Q7d.** Are there rows that are clearly wrong / non-applicable that we should drop in M2 (false positives from rule-based category tagging)? List 1-3 examples (req + category):

### 5. Open-ended

> **Q8.** Anything you noticed that concerns you for use in M2/M3?

---

**Reviewer:** _____________________   **Date:** ______________   **Signature:** _____________________

---

## What "PASS" means here

The scorecard's numeric `PASS` proves the parser + planner are internally consistent and match their committed baselines. Your spot-check proves the IR and the generated Test Plan faithfully represent the source — something machines cannot self-verify.

If Q1–Q7c all answer "Y," **M1 is accepted** and **15% of the contract value (per PQ4476E §6) is invoiceable**. Q7d feedback shapes M2/M3 prompts.

Per the Cure Period clause: if any answer is "N" because of a material non-conformance, Exaware provides a written list of deficiencies and CodeValue gets a reasonable Cure Period (max 2 resubmissions) before rejection.

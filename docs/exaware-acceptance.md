# M1 Spot-Check Form

To be completed by an **Exaware reviewer** at end of Week 2. This is the human gate that the numeric scorecard cannot replace.

## Setup (one minute)

```bash
./modular_tools.sh setup       # only the very first time
./modular_tools.sh parse "references/EVPN System Specification 1.00.docx" -o ir.json
```

You now have `ir.json` containing the full structured IR for the EVPN spec. Open it in any JSON viewer.

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

### 4. Open-ended

> **Q4.** Anything you noticed that concerns you for use in M2/M3?

---

**Reviewer:** _____________________   **Date:** ______________   **Signature:** _____________________

---

## What "PASS" means here

The scorecard's numeric `PASS` proves the parser is internally consistent and matches its committed baselines. Your spot-check proves it actually represents the source faithfully — something machines cannot self-verify.

If Q1, Q2, Q3 all answer "Y," M1 is accepted.

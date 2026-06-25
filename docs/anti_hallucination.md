# How the engine prevents non-existing (hallucinated) commands

**Audience:** Exaware review (Ron, Yossi) — answer to the M1 action item
*"Explanation why / how we prevent hallucination of non-existing command."*
**Date:** 2026-06-25

---

## The trigger

Yossi flagged `show mpls lsp` (cell E1588 of *Test Plan Topics*) as
*"an AI hallucination, as there is no such command in the SFS"* and asked us
to check its origin.

**Finding — it is not an AI hallucination.** `show mpls lsp` is hard-coded in
our own hand-curated monitor vocabulary: `ate/planner/categories.py`
(`_FLOW_SHOW_CMDS['FLOW-13']`) and the EVI-to-EVI RFC 4364 transport flows in
`ate/planner/flows.py` (FLOW-130..135), which were added during the
2026-06-04 SW review. No AI-generated token leaked into it. The command is a
generic MPLS data-plane check that is *plausible* for the RFC 4364 transport
scenario but was never verified against an Exaware document.

So the real issue is narrower and fixable: a command can reach the plan
without being **traceable to a document Exaware gave us**. The sections below
describe the layered controls that keep generated commands grounded, and the
new cross-check that makes any ungrounded command impossible to miss.

---

## The four controls

### 1. Commands are *extracted*, not generated
Every CLI command originates from the **CommandSyntax cell of the CLI doc
tables** (`ate/planner/cli_extractor.py:_parse_command_table`). The parser
reads the documented syntax verbatim; it has no path that invents a command
string. Inherited BGP sub-configs (`allow-as-in`, `capability`, …) are
**hand-curated** from the BGP standard and explicitly provenance-tagged
`cli-inherit` (`ate/planner/cli_inheritance.py`), pending the BGP CLI manual.

### 2. CLI rows never touch the AI
The per-command CLI test rows are produced by deterministic, rule-based
templates (`ate/planner/cli_rows.py`) and are **bypassed entirely** by the AI
enricher — they are counted as `rule_based` and never sent to the model
(`ate/planner/ai_enricher.py`, CLI-row exemption). The command syntax in those
rows is therefore exactly what the CLI doc says, character for character.

### 3. The AI writes prose around fixed anchors, under a grounding rule
The enricher only fills in *Problem / Method / Setup / Action / Verify* prose
around commands that already exist. Its prompt carries an explicit
**GROUNDING RULE** (`ate/planner/ai_enricher.py`):

> *"No invented commands: every backtick-quoted command should either appear
> in the CLI EVIDENCE or be a well-known generic verb … Parameter names: only
> use parameter names that appear verbatim in the CLI EVIDENCE block. Do NOT
> invent sub-parameters from prose descriptions."*

The CLI EVIDENCE block is built only from extracted command names, so the
model is steered to reuse documented tokens rather than coin new ones.

### 4. (New) Command grounding — the backstop that *removes* anything ungrounded
Controls 1–3 reduce the risk but cannot *prove* the result. Two gaps remain:
hand-curated monitors (control 1's `cli-inherit` style lists, e.g.
`show mpls lsp`), and `show` commands the model writes into free *Verify*
prose (control 3 is a steer, not a hard stop). So we added a deterministic
post-generation pass: **`ate/planner/cli_crosscheck.py`**.

After the *final* plan is built (including AI enrichment — the worst case for
an invented command), it traces every CLI/`show` command that reaches a cell
and classifies each by provenance:

| Class | Meaning | Disposition |
|---|---|---|
| **doc-grounded** | head appears in the CLI doc / SFS / RFC | kept |
| **generic** | universal operator verb (`show running-config`, `commit`, `ping`, …) | kept |
| **curated** | hand-maintained EVPN monitor vocabulary (`show evpn evi`, `show evpn df`, …) | kept |
| **ungrounded** | backed by none of the above — invented, or out-of-scope | **removed from the plan** |

A command is grounded by its longest matching *prefix*, so `show evpn evi 10`
inherits the grounding of `show evpn evi` (an argument is not a new command).
Ungrounded commands are **scrubbed out of the Monitor column and the Verify
prose** before the workbook is written, and the surrounding sentence is
tidied, so the deliverable simply does not contain a non-existing command.
The result is recorded three ways:

- a **"Command Cross-Check" sheet** in every workbook — an audit listing every
  command **removed** (red) and the full kept vocabulary by provenance, so a
  reviewer sees exactly what the plan does and does not assert;
- a **one-line summary on the CLI** (`ate plan` / `ate plan-feature`, stderr):
  *"removed N ungrounded command(s)"*, plus a hard error if any somehow
  survive (a contract, expected to read zero);
- a unit-tested contract (`tests/test_cli_crosscheck.py`).

It needs no AI re-bake. `show mpls lsp` / `show mpls forwarding-table` were
additionally removed from the curated source (`categories.py`, `flows.py`) per
Yossi's flag, so they are now treated as ungrounded and scrubbed everywhere
they appear.

---

## What it does on the current EVPN plan (2026-06-25)

On the AI-enriched plan, **14 ungrounded commands are removed** and **0
survive**. The removed set is:

- AI naming-variants the enricher wrote into *Verify* prose that match no
  document — `show evpn mac-table` (the grounded form is
  `show evpn mac address-table`), `show evpn route`, `show evpn routes type 4`,
  `show l2-services forwarding-table`, `show l2-services evpn statistics`,
  `show ip bgp summary`, `show lacp`, and a few partial `show evpn …` fragments;
- the MPLS-transport monitors not in the EVPN SFS — `show mpls lsp` and
  `show mpls forwarding-table` (the command Yossi flagged).

Everything the plan still asserts is doc-grounded, a generic operator verb, or
in our curated EVPN monitor vocabulary. The command Yossi caught by eye is now
removed **automatically**, together with the dozen the eye had not yet reached
— and the *Command Cross-Check* sheet is the standing proof, on every run, that
the output carries no non-existing command.

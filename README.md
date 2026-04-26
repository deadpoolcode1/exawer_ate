# ate — AI-Assisted Test Plan & Automation Skeleton Generator (POC)

**Codevalue PQ 4476 for Exaware** — a 10-week, 5-milestone POC. This repo currently delivers **Milestone 1** of 5.

---

## What M1 does (in one sentence)

> **M1 normalizes any of {PDF, DOCX, TXT} into a single canonical JSON shape (the IR) so downstream milestones (AI in M3) never have to deal with format-specific mess.**

```
   EVPN spec.docx  ─┐
   rfc9785.pdf     ─┼──▶  ate (M1)  ──▶  IR JSON  ──▶  (M2: find requirements)
   rfc9785.txt     ─┘                                  (M3: AI writes test plan)
                                                       (M4: AI writes pytest code)
                                                       (M5: web UI)
```

Every output JSON has the same schema regardless of what went in:

```json
{
  "schema_version": "1.0.0",
  "source_format": "docx" | "pdf" | "txt",
  "blocks": [
    { "kind": "heading",   "level": 2, "number": "2.3.1", "text": "..." },
    { "kind": "paragraph", "text": "..." },
    { "kind": "code",      "text": "config\ninterface agg-eth 1\n..." },
    { "kind": "table",     "rows": [[...]] }
  ]
}
```

CLI configuration blocks are preserved **byte-for-byte** — they become test inputs in M4.

---

## Quickstart — three commands

```bash
./modular_tools.sh setup     # first time only — creates venv, installs deps
./modular_tools.sh verify    # green/red signal: is M1 ready to ship?
./modular_tools.sh parse <file>   # parse any PDF/DOCX/TXT into JSON
```

Type `./modular_tools.sh help` to see every command grouped by category.

---

## modular_tools.sh — the swiss knife

Single dispatcher. All work goes through it. No `cd .venv/bin/...` ceremony.

### Setup

| Command | What it does |
|---|---|
| `./modular_tools.sh setup` | Create `.venv`, install dependencies. Run this first. |
| `./modular_tools.sh build` | Reinstall the package after editing `pyproject.toml`. |
| `./modular_tools.sh verify_env` | Health-check the dev environment (24 checks). |

### Parse a document

```bash
# Three usage patterns:

# A. Quick summary (counts only — fastest sanity check)
./modular_tools.sh parse "references/EVPN System Specification 1.00.docx" --summary

# B. Full structured JSON to file (this is what M3/M4 will consume)
./modular_tools.sh parse "references/EVPN System Specification 1.00.docx" -o ir.json

# C. Stream JSON to stdout (pipe into other tools)
./modular_tools.sh parse references/rfc9785.txt | jq '.blocks[0]'
```

Works on any `.pdf`, `.docx`, `.txt`. Unsupported formats raise a typed error, not a crash.

### Verify (the user-facing green/red gate)

| Command | What it does |
|---|---|
| `./modular_tools.sh verify` | **★ The single command for the project owner.** Runs the M1 acceptance scorecard. Exits 0 if every metric is green. |
| `./modular_tools.sh verify_quick` | Fast subset (just determinism). |
| `./modular_tools.sh test_unit` | Pytest suite (43 tests). |
| `./modular_tools.sh regression` | pytest + golden-IR diff in one shot. |
| `./modular_tools.sh e2e` | **★ Full pipeline:** env + corpus + tests + scorecard. ~40 seconds. |

### Manage the regression baseline (goldens)

The "goldens" are committed snapshots of correct parser output. Any drift = failure until reviewed and accepted.

| Command | What it does |
|---|---|
| `./modular_tools.sh golden_diff` | Show what would change if goldens were rewritten. No writes. |
| `./modular_tools.sh golden_update` | Accept current parser output as the new baseline. Asks "yes" first. |
| `./modular_tools.sh golden_dump_ir` | Dump full normalized IR per tracked doc to `tests/golden/ir/`. |

### Maintenance / Docker

| Command | What it does |
|---|---|
| `./modular_tools.sh lint` | ruff check on all source. |
| `./modular_tools.sh clean` | Remove caches. |
| `./modular_tools.sh docker_build` | Build `ate:m1` image. |
| `./modular_tools.sh docker_verify` | Run scorecard inside the container. |

---

## What the results look like

### `verify` output (M1 acceptance scorecard)

```
M1 Acceptance Scorecard — 2026-04-26 20:09:17 IDT
Corpus: tests/corpus
Elapsed: 16.1s

  [PASS] heading_recovery                    100.0%  (≥ 95%)
  [PASS] cli_block_preservation        8/8 (100.0%)  (= 100%)
  [PASS] table_preservation                  100.0%  (≥ 90%)
  [PASS] anchor_detection (M2)            40 unique  (reported)
  [PASS] format_parity            min Jaccard 0.980  (≥ 0.90)
  [PASS] determinism                  3/3 identical  (3/3 identical)
  [PASS] no_unhandled_exceptions              0 / 7  (= 0)
  [PASS] performance                           1.9s  (< 30s)
  [PASS] edge_cases                             8/8  (manifest match)

OVERALL: PASS — ready for Exaware spot-check
```

If **all** lines say `[PASS]`, M1 is shippable. If any line says `[FAIL]`, the named metric is below its threshold and M1 is not shippable.

### `parse … --summary` output

```
$ ./modular_tools.sh parse references/rfc9785.pdf --summary
path:        references/rfc9785.pdf
format:      pdf
schema:      1.0.0
blocks:      72
headings:    26
paragraphs:  40
code blocks: 3
tables:      3
```

### `parse … -o file.json` output

A complete IR JSON file. See the schema example at the top of this README.

### `regression` output (after a parser change)

```
[regression] Pytest + golden-IR diff
............... 43 passed in 21.1s
[regression] Checking golden drift (no writes)
[OK ] tests/golden/headings.json unchanged
[OK ] tests/golden/cli_blocks.json unchanged
[OK ] tests/golden/tables.json unchanged
[done] no regression detected
```

If drift is detected, the diff is printed inline. You decide: revert the parser change, or accept the new baseline via `golden_update`.

---

## What's tested

Every file in `references/` (except the xlsx output template) is in the test corpus and acceptance scorecard:

| File | In acceptance scorecard? | In regression goldens? | Tier |
|---|:---:|:---:|---|
| `rfc9785.docx` | ✅ | ✅ | A — format parity |
| `rfc9785.txt` | ✅ | ✅ | A — format parity |
| `rfc9785.pdf` | ✅ | ✅ | A — format parity |
| `EVPN System Specification 1.00.docx` | ✅ | ✅ | A — domain fidelity |
| `EVPN CLI 1.00.docx` | ✅ | ✅ | A — table-heavy |
| `draft-ietf-bess-rfc7432bis-13.docx` | ✅ | ✅ | B — scale stress (450 KB) |
| `draft-ietf-bess-rfc7432bis-13.txt` | ✅ | ✅ | B — scale stress |
| `Feature Name Test Plan Template.xlsx` | n/a | n/a | M3 output spec, not a parser input |
| 8 synthetic edge cases under `tests/corpus/tier_c/` | ✅ | n/a | C — typed-error verification |

---

## What M1 does NOT do (per SOW §5)

- ❌ Identify which paragraphs are *requirements* (M2)
- ❌ Classify functional vs. non-functional (M2)
- ❌ Generate test plans using AI (M3)
- ❌ Generate Python test code (M4)
- ❌ Web interface (M5)
- ❌ OCR for scanned PDFs (parser raises `UnsupportedScannedPDFError` and stops)
- ❌ Convert PDF↔DOCX↔TXT — M1 reads, doesn't convert

---

## Repository layout

```
ate/
├── ate/                          package source
│   ├── cli.py                    entrypoint: `ate parse <file>`
│   ├── ir.py                     Pydantic IR models (the JSON schema)
│   ├── errors.py                 typed exceptions
│   ├── normalize.py              cross-format parity normalization
│   └── parsers/
│       ├── dispatch.py           detect format by magic bytes + suffix
│       ├── docx_parser.py
│       ├── pdf_parser.py
│       └── txt_parser.py
├── scripts/
│   ├── verify_env.py             dev environment health check
│   ├── score.py                  M1 acceptance scorecard
│   ├── build_goldens.py          regenerate / diff goldens
│   └── build_tier_c.py           synthesize edge case files
├── tests/
│   ├── test_dispatch.py
│   ├── test_parsers.py
│   ├── test_regression.py        ★ pytest-side golden drift detection
│   ├── test_determinism.py
│   ├── test_parity.py
│   ├── test_edge_cases.py
│   ├── test_cli.py
│   ├── corpus/                   sample inputs (Tier A/B/C)
│   └── golden/                   regression baseline (don't hand-edit)
├── docs/
│   ├── TDD.md                    technical design doc
│   ├── M1_acceptance.md          numeric thresholds
│   └── exaware-acceptance.md     Exaware reviewer's spot-check form
├── references/                   client-provided reference documents
├── modular_tools.sh              ★ swiss knife dispatcher
├── Makefile                      thin alias layer
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

## Where to look for what

| You want… | Look at… |
|---|---|
| Every modular_tools command | `./modular_tools.sh help` |
| What M1 promises numerically | `docs/M1_acceptance.md` |
| The technical design | `docs/TDD.md` |
| The Exaware reviewer's form (W2 sign-off) | `docs/exaware-acceptance.md` |
| The IR schema | `ate/ir.py` |
| What metrics are checked | `scripts/score.py` |

---

## TL;DR

```bash
./modular_tools.sh verify      # is M1 good?  → green/red signal
./modular_tools.sh parse FILE  # parse any document → JSON
./modular_tools.sh regression  # did my change break anything?
```

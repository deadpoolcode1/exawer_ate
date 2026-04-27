# ate — AI-Assisted Test Plan & Automation Skeleton Generator (POC)

**Codevalue PQ 4476 for Exaware** (current SOW: `PQ4476E.pdf`) — a 10-week, 5-milestone POC. This repo currently delivers **Milestone 1** of 5.

---

## What M1 does

Per SOW PQ4476E §5, **M1 = "Test Plan Generation"**:

1. **Normalize** any of {PDF, DOCX, TXT} → single canonical JSON IR
2. **Extract requirements** anchored by `<PREFIX>-REQ#NN` markers (e.g. `EVPNS-REQ#280`)
3. **Generate a Test Plan** (single-router) as an xlsx matching the Exaware template
   - **All 382 rows AI-enriched (Claude / Anthropic)** for the EVPN System Specification — feature-specific action steps using actual CLI commands, VLAN-IDs, ESI types, RFC chapters, and MUST statements from the source
   - The AI cache is committed (`ate/planner/ai_cache.json`) so the deliverable is reproducible without an API key. New specs get enriched on the fly when `ANTHROPIC_API_KEY` is set.
4. **Deliverable**: a Test Plan xlsx for Exaware review and approval (per §5)

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

## Quickstart — four commands

```bash
./modular_tools.sh setup             # first time only — creates venv, installs deps
./modular_tools.sh run-tests         # ★★★ full E2E: tests + coverage + scorecard + HTML report
./modular_tools.sh parse <file>      # parse any PDF/DOCX/TXT into JSON
./modular_tools.sh plan <in> <xlsx>  # generate a test plan xlsx (M1 deliverable)
```

Two batch helpers for processing every reference doc at once:

```bash
./modular_tools.sh parse_all       # writes out/<name>.json for every PDF/DOCX/TXT in references/
./modular_tools.sh plan_all        # writes plans/<feature>.xlsx for every Word feature spec
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
| `./modular_tools.sh verify_env` | Health-check the dev environment. |

### Corpus

| Command | What it does |
|---|---|
| `./modular_tools.sh corpus_check` | Verify every Tier A/B/C corpus file is present. |
| `./modular_tools.sh build_tier_c` | Regenerate Tier-C synthetic edge case files. |

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

`parse_all` runs the same parser over every supported file in `references/` and writes one JSON per source under `out/`.

### Generate a test plan (M1 deliverable)

```bash
# Single file → single xlsx
./modular_tools.sh plan "references/EVPN System Specification 1.00.docx" plans/evpn.xlsx

# Every Word feature spec in references/ → plans/<feature>.xlsx
./modular_tools.sh plan_all
```

Under the hood this calls `ate plan <input> -o <output.xlsx>`, which exposes the following flags:

| Flag | Behavior |
|---|---|
| (default) | Cache-only: every row is enriched from the committed `ate/planner/ai_cache.json`. Deterministic, no API key required. |
| `--ai` | Force AI enrichment via the Anthropic API for any row not in the cache. Requires `ANTHROPIC_API_KEY`. |
| `--no-ai` | Disable AI enrichment entirely; emit the rule-based template rows. |
| `--feature-name NAME` | Override the auto-detected feature name. |
| `--summary` | Print row counts instead of writing the xlsx. |

### Verify (the user-facing green/red gate)

| Command | What it does |
|---|---|
| `./modular_tools.sh run-tests` | **★★★ The headline command.** env + corpus + pytest + coverage + scorecard + lint + perf + requirements traceability, all into a single self-contained HTML at `results/test-report-<timestamp>.html`. |
| `./modular_tools.sh verify` | M1 acceptance scorecard only, terminal output. Exits 0 iff every metric is green. |
| `./modular_tools.sh verify_quick` | Fast subset (just determinism). |
| `./modular_tools.sh test_unit` | Pytest suite (68 tests across parser, planner, AI enricher, regression, parity, determinism, edge, CLI). |
| `./modular_tools.sh regression` | pytest + golden-IR diff in one shot. |
| `./modular_tools.sh e2e` | Full pipeline, terminal-only: env + corpus + tests + scorecard. ~40 seconds. |
| `./modular_tools.sh report` | Re-render the HTML report only (skips env/corpus pre-checks). |

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

### `run-tests` output (★★★ headline)

```
═══ ATE M1: run-tests (full report) ═══
...
HTML report: results/test-report-20260427_061604.html
  open in browser:   xdg-open "results/test-report-20260427_061604.html"
  open in VS Code:   code "results/test-report-20260427_061604.html"
═══ ALL GREEN ═══
```

The report file is a single self-contained HTML with eight sections, in order:

1. SOW Requirements Coverage (per-milestone deliverables, traced to tests)
2. M1 Acceptance Scorecard (the 9 numeric metrics)
3. Pytest Suite (every test grouped by file)
4. Code Coverage (pytest-cov per module)
5. Code Quality (ruff lint issues)
6. Performance (parse-time per corpus file)
7. Corpus Inventory (every file in `references/` and its parse status)
8. Output Files (JSONs in `out/` if present)

Exit code is 0 iff every gated row is PASS or SKIP.

### `verify` output (M1 acceptance scorecard)

```
M1 Acceptance Scorecard — 2026-04-27 07:51:30 IDT
Corpus: tests/corpus
Elapsed: 15.9s

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
............... 68 passed in 30.5s
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

## What M1 does NOT do (per SOW PQ4476E §5)

- ❌ Multi-router test plans — M1 produces single-router only; multi-router is M3
- ❌ Pattern matching across all spec styles — M1 handles the explicit `<PREFIX>-REQ#NN` anchor only; M2 generalizes
- ❌ Functional / non-functional classification (M2)
- ❌ Java / JSystem test code generation (M4)
- ❌ IXIA + neighboring-router test hooks (M4)
- ❌ Web interface, plan editor, deployment package (M5)
- ❌ OCR for scanned PDFs (parser raises `UnsupportedScannedPDFError`)
- ❌ Convert PDF↔DOCX↔TXT — M1 reads, doesn't convert

---

## Repository layout

```
ate/
├── ate/                          package source
│   ├── cli.py                    entrypoint: `ate parse …` and `ate plan …`
│   ├── ir.py                     Pydantic IR models (the JSON schema)
│   ├── errors.py                 typed exceptions
│   ├── normalize.py              cross-format parity normalization
│   ├── parsers/
│   │   ├── dispatch.py           detect format by magic bytes + suffix
│   │   ├── docx_parser.py
│   │   ├── pdf_parser.py
│   │   └── txt_parser.py
│   └── planner/                  ★ M1 test plan generator
│       ├── model.py              Plan / PlanRow / Requirement Pydantic models
│       ├── extractor.py          IR → Requirement list (anchored by <PREFIX>-REQ#NN)
│       ├── categories.py         per-category step templates (rule-based fallback)
│       ├── generator.py          orchestrator: parse → extract → enrich → Plan
│       ├── ai_enricher.py        Claude (Anthropic) cache-first enrichment
│       ├── ai_cache.json         committed enriched rows (382 for EVPN spec)
│       └── xlsx_writer.py        Plan → Exaware-template-shaped xlsx
├── scripts/
│   ├── verify_env.py             dev environment health check
│   ├── score.py                  M1 acceptance scorecard
│   ├── report.py                 single-file HTML test report
│   ├── build_goldens.py          regenerate / diff goldens
│   ├── build_tier_c.py           synthesize edge case files
│   └── build_ai_cache.py         build/refresh ate/planner/ai_cache.json
├── tests/                        68 tests
│   ├── test_dispatch.py
│   ├── test_parsers.py
│   ├── test_planner.py           planner end-to-end
│   ├── test_ai_enricher.py       cache-first AI enrichment
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
├── out/                          parse_all output (JSON per source)
├── plans/                        plan_all output (xlsx per feature)
├── results/                      run-tests HTML reports + junit xml
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
./modular_tools.sh run-tests      # ★★★ everything: tests + scorecard + HTML report
./modular_tools.sh verify         # just the M1 scorecard → green/red signal
./modular_tools.sh parse FILE     # parse any document → JSON
./modular_tools.sh plan_all       # generate every feature's xlsx test plan
./modular_tools.sh regression     # did my change break anything?
```

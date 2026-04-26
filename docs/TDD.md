# Technical Design Document — ATE / M1

**Project:** AI-Assisted Test Plan & Automation Skeleton Generator (POC) — Codevalue PQ 4476 for Exaware
**Milestone:** M1 — Document parser and basic text extraction
**Status:** M1 deliverable
**Audience:** Project owner (Codevalue), reviewer (Exaware)

---

## 1. Executive summary (read this first)

M1 produces a working command-line tool that reads PDF, DOCX, and TXT documents and emits a structured intermediate representation (IR) as JSON. The IR preserves section headings, paragraphs, tables (as structured rows × cells), and code/configuration blocks (verbatim).

**Verification command** for the project owner:

```
./modular_tools.sh verify
```

Returns green/red and exits 0/non-zero.

**Out of scope:** AI, requirement classification, test plan generation, test code generation, web UI. Those are M2–M5.

**M1 value as a standalone deliverable:** structured indexing of Exaware's product specs. Even before any AI, the IR enables full-text search, structural diffs across spec versions, and downstream tooling.

---

## 2. Architecture

```
                            ┌──────────────────────┐
   PDF / DOCX / TXT  ──────▶│  ate.parsers         │
                            │  (dispatch + format) │
                            └──────────┬───────────┘
                                       ▼
                            ┌──────────────────────┐
                            │       Document IR     │
                            │  (Pydantic models)    │
                            │   - Heading           │
                            │   - Paragraph         │
                            │   - ListItem          │
                            │   - CodeBlock         │
                            │   - Table             │
                            └──────────┬───────────┘
                                       ▼
                              ┌────────┴────────┐
                              ▼                 ▼
                     ate.cli (parse)     ate.normalize
                     → JSON file         (parity comparison)
                                                ▼
                                        scripts/score.py
                                        (M1 acceptance)
```

### 2.1 Components

| Module | Responsibility |
|---|---|
| `ate.ir` | Pydantic IR models. Schema versioned (`SCHEMA_VERSION = "1.0.0"`). |
| `ate.errors` | Typed exceptions: `UnsupportedFormatError`, `CorruptDocumentError`, `PasswordProtectedError`, `EmptyDocumentError`, `UnsupportedScannedPDFError`, `EncodingError`. |
| `ate.parsers.dispatch` | Detect format by magic bytes + suffix; route to the right parser. |
| `ate.parsers.docx_parser` | DOCX via `python-docx`; iterates body in document order; detects code blocks via monospace font / CLI-shape heuristics; tables via direct XML. |
| `ate.parsers.pdf_parser` | PDF via `pdfplumber`; layout-based extraction; heading detection by font-size delta vs. body; table extraction via lattice/stream; rejects scanned PDFs. |
| `ate.parsers.txt_parser` | Plain text; RFC numbered headings, setext, markdown `#`, ALL-CAPS; indented + fenced code blocks. |
| `ate.normalize` | Strip format-specific noise (page numbers, soft hyphens, smart quotes, whitespace) for parity comparisons. |
| `ate.cli` | `ate parse <file> -o out.json [--summary]`. |

### 2.2 Why a Pydantic IR (not raw dicts)

* Schema is enforced at parse time; downstream consumers (M2, M3, M4) get typed access.
* Pydantic emits stable, ordered JSON — feeds the determinism gate (M1.f).
* Discriminated union of `Block` types makes traversal and pattern-matching ergonomic.

### 2.3 Why the IR is a flat list, not a tree

Section structure is implicit via `Heading.level`. Consumers that need a tree build one from blocks. Reasons:

* Different parsers produce different heading qualities; flat-list simplifies merging strategies later.
* Tables and code blocks at section boundaries are unambiguous (no "which subsection does this belong to?" debate during parsing).
* Round-tripping is easier (consumer reorders, parser doesn't).

---

## 3. Format-specific parsing strategy

### 3.1 DOCX

* Iterate `document.iter_inner_content()` so paragraphs and tables stay in document order.
* Heading detection priority: `Heading 1..9` style → `Title` style → fallback heuristic on numbered prefix `"2.3.1 Title"`.
* TOC entries (`TOC 1..9` styles) are explicitly rejected to prevent inflating heading counts.
* Code blocks: monospace font on any run, OR style name containing "code"/"preformatted", OR content shape (CLI hints like `exaware#`, `(config)#`, lone `!`, lone `config`). Adjacent code paragraphs are coalesced into a single block.
* Tables: walk the underlying `<w:tbl>` XML directly. Each `<w:tc>` in document order is exactly one cell. Avoids `python-docx`'s `r.cells` which repeats merged cells across grid positions and forced non-deterministic dedup.

### 3.2 PDF

* Body font size = the most common rounded character size; anything larger is a heading candidate.
* Heading level estimated from size delta (≥6 → L1, ≥4 → L2, ≥2 → L3).
* Code blocks: monospace fontname share > 50% per visual line.
* Repeating page-header/footer lines stripped (lines appearing in same band on > 50% of pages).
* Tables: `page.find_tables()` (lattice + stream); cell content normalized.
* Empty text layer → `UnsupportedScannedPDFError` (no OCR in M1).

### 3.3 TXT

* Decode as UTF-8 (BOM-aware), fall back to latin-1.
* Heading priority: setext (`====`/`----`) → markdown `## title` → RFC numbered (`2.3.1.  Title`) → ALL-CAPS line.
* Code blocks: indented (≥4 spaces) or fenced (```` ``` ````).
* Tables not parsed in M1 (RFC ASCII art needs custom heuristics; deferred).

---

## 4. Verification framework (the test framework)

The framework serves **two** audiences with one stack:

* **Project owner** — gets green/red signal that M1 meets acceptance.
* **Future contributor** — gets regression detection: any drift from committed goldens fails the build.

### 4.1 Layers

| Layer | Tool | Purpose |
|---|---|---|
| Unit | `tests/test_parsers.py`, `test_dispatch.py`, `test_cli.py` | Per-component behavior, fast |
| Edge cases | `tests/test_edge_cases.py` | Tier-C files raise the typed errors declared in `MANIFEST.tsv` |
| Determinism | `tests/test_determinism.py` | 3 runs byte-identical for every Tier-A/B doc |
| Format parity | `tests/test_parity.py` | RFC 9785 word-Jaccard ≥ 0.90 across DOCX/TXT/PDF |
| Regression | `tests/test_regression.py` | Normalized IR byte-identical to committed `tests/golden/ir/*.json` |
| Acceptance | `scripts/score.py` | All M1 numeric metrics in one scorecard |

### 4.2 The unified entrypoint

`./modular_tools.sh` is the swiss knife inspired by `/home/ilan/work/uvision/track/modular_tools.sh`. Single dispatcher, grouped subcommands, color-coded output. Key entries:

* `verify` — runs the M1 acceptance scorecard
* `regression` — pytest + golden drift in one shot
* `e2e` — env check + corpus check + tests + scorecard
* `golden_diff` / `golden_update` — manage the regression baseline

The `Makefile` defers to the same scripts so either entrypoint works.

### 4.3 Goldens — the regression contract

Goldens live under `tests/golden/`:

| File | Role |
|---|---|
| `headings.json` | Per-doc list of expected heading texts (initially seeded from parser output; meant to be human-pruned before sign-off). |
| `cli_blocks.json` | Curated list of CLI signature substrings that must appear verbatim in the EVPN spec's IR. |
| `tables.json` | Per-doc minimum table count. |
| `ir/<doc>.json` | Full normalized IR per tracked doc — the regression baseline. |

Updating a golden = an explicit decision to redefine "correct." The diff is reviewed before commit. `./modular_tools.sh golden_diff` shows the pending change.

### 4.4 Honesty about what's measured

* `cli_block_preservation`, `format_parity`, `determinism`, `edge_cases`, `performance`, `no_unhandled_exceptions` are absolute checks. Passing them is real evidence.
* `heading_recovery`, `table_preservation` are *regression* gates against goldens generated from the parser. Their value is preventing future drift, not absolute correctness on day 1.
* `anchor_detection` is **reported, not gated** — it's an M2 metric, here for visibility.

This is why **`docs/exaware-acceptance.md`** exists: the human spot-check is the only gate that proves the IR faithfully represents source content. The forced-finding form (3 anchors named, 1 CLI block pasted, 1 table row count) prevents rubber-stamping.

---

## 5. Risks and known limitations (M1)

| # | Risk / limitation | Mitigation |
|---|---|---|
| 1 | Real-world Exaware PDFs (multi-column, embedded fonts) may produce different parsing quality than the RFC 9785 PDF | Documented as M1 known constraint; revisit when Exaware sends a PDF sample |
| 2 | Vertical-merge (`vMerge`) cells in DOCX tables count as one cell per row instead of spanning | `rowspan=1` recorded; deferred to M2 if downstream consumers need it |
| 3 | TXT table parsing not implemented | RFC ASCII tables require custom heuristics; deferred. RFC headings work. |
| 4 | Heading recovery and table preservation gold standards are seeded from parser output, not human-curated | Documented above; Exaware spot-check provides the absolute correctness signal at end of W2 |
| 5 | Style-variance across Exaware specs unknown (only EVPN spec validated) | Stress-test in M2 with 2–3 more spec samples |
| 6 | Pydantic 2 + python-docx incompatibility at major version bumps | Versions pinned in pyproject.toml |
| 7 | Host environment leakage (ROS2/system pytest plugins) | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` set in Makefile and `modular_tools.sh` |

---

## 6. Open questions to resolve before M2 / M3

These are **not** M1 blockers. Listed here so M2 doesn't start cold.

| For | Question | Owner |
|---|---|---|
| M2 | Does Exaware have 2–3 more spec samples we can use to stress the requirement extractor? | Codevalue → Exaware |
| M2 | What is the canonical regex for Exaware requirement IDs across product lines? (`EVPNS-REQ#NN` is one of many.) | Exaware |
| M3 | Cloud LLM (OpenAI / Anthropic) acceptable, or must inference be on-prem? (BOM lists 8 GB RTX A1000 → marginal for local LLMs.) | Exaware |
| M3 | Two human-written reference test plans for AI quality benchmarking | Exaware |
| M3 | Methodology to measure "40–50% effort reduction" claim (engineer-time tracking on N features) | Codevalue draft → Exaware confirm |
| M4 | Lab fixture for generated pytest code: real router / containerlab / mock? | Exaware |
| M5 | Hosting decision: HP Z2 Mini (BOM) on-prem, or hosted? | Exaware |

---

## 7. Repository layout

```
ate/
├── ate/                    package source
│   ├── __init__.py
│   ├── cli.py              entrypoint: `ate parse ...`
│   ├── ir.py               Pydantic IR models
│   ├── errors.py           typed exception hierarchy
│   ├── normalize.py        cross-format parity normalization
│   └── parsers/
│       ├── __init__.py
│       ├── dispatch.py     format detection + routing
│       ├── docx_parser.py
│       ├── pdf_parser.py
│       └── txt_parser.py
├── scripts/
│   ├── verify_env.py       dev environment health check
│   ├── score.py            M1 acceptance scorecard generator
│   ├── build_goldens.py    regenerate / diff goldens
│   └── build_tier_c.py     synthesize Tier-C edge case files
├── tests/
│   ├── conftest.py
│   ├── test_dispatch.py
│   ├── test_parsers.py
│   ├── test_regression.py  pytest-side golden drift detection
│   ├── test_determinism.py
│   ├── test_parity.py
│   ├── test_edge_cases.py
│   ├── test_cli.py
│   ├── corpus/
│   │   ├── tier_a/         format-parity samples (RFC 9785 ×3 + EVPN spec)
│   │   ├── tier_b/         scale stress (rfc7432bis-13)
│   │   └── tier_c/         edge cases + MANIFEST.tsv
│   └── golden/
│       ├── headings.json
│       ├── cli_blocks.json
│       ├── tables.json
│       └── ir/             full normalized IR per tracked doc
├── docs/
│   ├── TDD.md              (this document)
│   ├── M1_acceptance.md    numeric thresholds + how to verify
│   └── exaware-acceptance.md   human spot-check form
├── references/             client-provided references
├── modular_tools.sh        ★ swiss knife dispatcher
├── Makefile                thin alias layer
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

## 8. Sign-off

* **M1 numeric acceptance:** `./modular_tools.sh verify` → `OVERALL: PASS`
* **M1 human acceptance:** Exaware reviewer completes `docs/exaware-acceptance.md`
* **Regression baseline locked:** `tests/golden/` committed; future drift detected automatically

When both above are satisfied, M1 is accepted and 10% of the contract milestone payment is due.

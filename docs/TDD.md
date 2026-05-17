# Technical Design Document — ATE / M1

**Project:** AI-Assisted Test Plan & Automation Skeleton Generator (POC) — Codevalue PQ 4476 for Exaware
**Current SOW:** `../PQ4476E.pdf`
**Milestone:** M1 — **Test Plan Generation** (Weeks 1–2, 15% of contract)
**Status:** M1 deliverable
**Audience:** Project owner (Codevalue), reviewer (Exaware)

---

## 1. Executive summary (read this first)

Per SOW PQ4476E §5, M1 is **"Test Plan Generation"** with the following deliverables:

1. Test plan generation from input documents (2 Word files + RFC)
2. Development environment
3. Document parser (PDF, DOCX, TXT)
4. Basic text extraction working
5. Technical design document (this file)
6. **Deliverable artifact**: Test Plan (single router) xlsx for Exaware review/approval

The implementation pipeline:

```
PDF/DOCX/TXT  →  parser  →  IR JSON  →  planner  →  Test Plan xlsx
                  (M1)                    (M1)         (deliverable)
```

**One command** for the project owner:

```
./modular_tools.sh run-tests
```

Runs every gate (env, corpus, pytest, coverage, scorecard, requirements traceability, lint, performance) and writes a single HTML report.

**Generate the M1 deliverable** (the xlsx Exaware reviews):

```
./modular_tools.sh plan-feature EVPN   # auto-discovers references/EVPN/{SFS,CLI,RFCs}
./modular_tools.sh plan_all            # one plans/*.xlsx per references/<FEATURE>/ folder
```

**Out of scope (per SOW):** multi-router topologies (M3), Java/JSystem code generation (M4), IXIA + neighboring-router hooks (M4), web UI (M5).

**AI in M1**: although the SOW puts "OpenAI/Claude API integration" formally in M3, M1 already integrates Claude (Anthropic SDK) for plan-row enrichment. The committed cache (`ate/planner/ai_cache.json`) covers **100% of the EVPN System Specification 1.00 rows (382/382)** with feature-specific AI-quality content — references real CLI commands, RFC chapters, MUST statements drawn from the source spec. New specs added later are enriched on the fly when `ANTHROPIC_API_KEY` is set. M3 then expands AI usage to multi-router topologies, prioritization, and coverage tracking per the SOW M3 deliverable list.

**Tag-applicability tightening (matrix v4)**: per-requirement category selection is rule-based (keyword tags from `extractor.TAG_KEYWORDS` with title-pattern lockouts in `TAG_TITLE_LOCKOUTS`). Scoring is title-weighted: `score = 3 × title_keyword_hits + 1 × description_keyword_hits`, threshold 2 (one title hit OR two distinct description hits). This eliminates the v1/v2 false positives where a single passing mention of a keyword in description (e.g. "MAC mobility flag" in REQ#280's route-format description) would falsely apply a tag like HA. Net effect: row count dropped from 543 to 382 (−30%), and the rows that remain are categorically applicable. Reviewer feedback (Q7d) refines this further in M2.

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
                            │  Heading / Paragraph  │
                            │  CodeBlock / Table    │
                            └──────┬────────┬───────┘
                                   │        │
              ate.cli parse ◀──────┘        ▼
                  → JSON           ┌─────────────────────────────┐
                                   │  Requirements Builder       │  ★ M1 respin
                                   │  ate.planner.requirements_  │  (2026-05-17)
                                   │  builder                    │
                                   │   ├ extractor (SFS)          │
                                   │   ├ rfc_extractor            │
                                   │   ├ cli_extractor            │
                                   │   └ cli_inheritance (BGP)    │
                                   │   → RequirementCatalog       │
                                   └──────────────┬──────────────┘
                                                  ▼
                                       ate.planner.generator
                                         + flows.py + cli_rows.py
                                         (rule-based scaffold,
                                          synth_anchors for orphan RFC)
                                                  │
                                                  ▼
                                       ate.planner.ai_enricher
                                         + ai_cache.json
                                         (Claude — cached)
                                                  │
                                                  ▼
                                       ate.planner.atomic_rows
                                         PlanRow → AtomicRow stream
                                         (DHCP-snoopy 9-col shape)
                                                  │
                                                  ▼
                                       ate.planner.xlsx_writer
                                         + Synthesized — Review sheet
                                                  │
                                                  ▼
                                       ┌──────────────────────┐
                                       │  Test Plan (xlsx)    │
                                       │  ★ M1 deliverable    │
                                       └──────────────────────┘
```

The Plan model (`ate.planner.model`) is the format-neutral artifact. The M1 deliverable is **AI-enriched 100% via Claude (Anthropic)** — every plan row references real spec content (CLI commands, RFC chapters, MUST statements). The cache (`ate/planner/ai_cache.json`) is committed so the deliverable is reproducible without an API key. M3 expands AI usage to multi-router topologies, prioritization, and coverage tracking per the SOW M3 deliverable list; M5's web UI reads the same Plan shape.

### 2.1 Components

| Module | Responsibility |
|---|---|
| `ate.ir` | Pydantic IR models for parsed documents. Schema versioned (`SCHEMA_VERSION = "1.0.0"`). |
| `ate.errors` | Typed exceptions: `UnsupportedFormatError`, `CorruptDocumentError`, `PasswordProtectedError`, `EmptyDocumentError`, `UnsupportedScannedPDFError`, `EncodingError`. |
| `ate.parsers.dispatch` | Detect format by magic bytes + suffix; route to the right parser. |
| `ate.parsers.docx_parser` | DOCX via `python-docx`; iterates body in document order; detects code blocks via monospace font / CLI-shape heuristics; tables via direct XML. |
| `ate.parsers.pdf_parser` | PDF via `pdfplumber`; layout-based extraction; heading detection by font-size delta vs. body; table extraction via lattice/stream; rejects scanned PDFs. |
| `ate.parsers.txt_parser` | Plain text; RFC numbered headings, setext, markdown `#`, ALL-CAPS; indented + fenced code blocks. |
| `ate.normalize` | Strip format-specific noise (page numbers, soft hyphens, smart quotes, whitespace) for parity comparisons. |
| `ate.planner.model` | `Plan`, `PlanRow`, `Requirement` Pydantic models — the format-neutral plan artifact. |
| `ate.planner.extractor` | Pulls requirements from IR using anchor regex (default `<PREFIX>-REQ#NN`). |
| `ate.planner.categories` | Test-plan category definitions — categories + per-category sub-test templates from the Exaware xlsx template. |
| `ate.planner.generator` | IR → Plan model. Builds a rule-based scaffold then routes through `ai_enricher` (cache → live Claude API → rule-based fallback). |
| `ate.planner.ai_enricher` | Anthropic Claude integration. The committed cache covers 100% of EVPN System Specification rows; live API (`ANTHROPIC_API_KEY`) extends to new specs on the fly. |
| `ate.planner.xlsx_writer` | Plan → xlsx matching the Exaware template column shape. |
| `ate.cli` | `ate parse <file> -o out.json` and `ate plan <file> -o plan.xlsx [--ai|--no-ai]`. |

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

## 9. Requirements Builder + DHCP-snoopy row shape (M1 client respin, 2026-05-17)

### Why

Client review (Eyal Ozeri, 2026-05-14) flagged two structural defects
and shared `references/DHCP-snoopy_TP_with_PW.xlsx` as the visual target:

1. **RFC not handled as a first-class requirement source.** Pipeline
   treated SFS as SSOT; RFC MUST clauses extracted by `rfc_extractor.py`
   were folded into the same flat list and run through the flow
   selector. RFC clauses no flow happened to claim landed in the
   Coverage-orphan sheet — the main TP shipped without testing them.
2. **Hierarchical CLI sub-configs not expanded.** `af-l2vpn evpn`
   appears in the EVPN CLI doc as one command with empty parameters,
   but in reality it opens a sub-mode whose 7 BGP-neighbor sub-configs
   (`allow-as-in`, `capability`, `inbound-soft-reconfiguration`,
   `maximum-prefix`, `policy`, `private-as`, `route-reflector-client`)
   are documented in Exaware's BGP CLI manual — which we do not have.
3. **Row shape diverges from what QA writes.** DHCP-snoopy uses
   atomic-row-under-topic-banner with one-sentence Action / Expectation
   / Monitor columns. The previous generator emitted multi-line
   Setup/Action/Verify **blobs in one cell** (introduced for Yossi's
   2026-05-07 review — see `memory/project_m1_yossi_respin.md`).

### What changed

A pre-agent **Requirements Builder** stage now unifies three independent
sources into one catalog with provenance tracking. The xlsx renderer
emits a 9-column DHCP-snoopy schema; multi-line PlanRow blobs decompose
into atomic action rows at render time (so the AI-enrichment cache
survives the shape change).

#### New modules

| Module | Responsibility |
|---|---|
| `ate.planner.requirements_builder` | Orchestrates `extract_requirements`, `extract_rfc_requirements`, `extract_commands`, `cli_inheritance.expand`. Returns `RequirementCatalog` (requirements, cli_commands, synth_anchors, provenance, inherited_cmd_names). `mark_claimed()` populates `synth_anchors` from RFC reqs no flow claimed. |
| `ate.planner.cli_inheritance` | Hand-curated table of sub-mode inheritance. Single entry today: `BGP_NEIGHBOR_AF_L2VPN_EVPN` with 7 sub-configs. `expand(extracted)` injects each sub-config as a `CliCommand`; idempotent if the real BGP doc is later integrated. |
| `ate.planner.atomic_rows` | `PlanRow → list[AtomicRow]` decomposer. Parses the multi-line Setup/Action/Verify blob into atomic step lists, extracts show commands from Verify into the Monitor column, emits banner + N action rows. Provenance (`synth` / `cli-inherit`) flows through to the Comment column. |

#### Modified modules

| Module | Change |
|---|---|
| `ate.planner.generator` | Replaces inline SFS/RFC/CLI extraction with `build_catalog()`; calls `mark_claimed()` after flow matching so RFC orphans surface as `synth_anchors`. |
| `ate.planner.xlsx_writer` | Rewritten "Test Plan Topics" sheet for 9-column schema. New "Synthesized — Review" sheet lists every banner with provenance `synth` or `cli-inherit`. PlanRow blobs are decomposed via `atomic_rows.rows_for_plan_row()` at write time. |

#### Output xlsx 9-column schema

| # | Header | Content |
|---|---|---|
| 1 | Topic | Banner row label (`FLOW-010 — …`, `RFC7432bis §7.2 — …`, `allow-as-in`). Empty on continuation rows. |
| 2 | Action | One-sentence verb phrase. |
| 3 | SFS / RFC Req ID | Comma-joined `EVPNS-REQ#NN`, `RFC*-§N.N`, `CLI:<name>` tokens. |
| 4 | Expectation | One-sentence pass criterion (last action row of a topic carries the full Pass / Fail-on). |
| 5 | Monitor | Show / clear commands extracted from the Verify steps. |
| 6 | Test Equipment | `DUT only`, `DUT + IXIA + neighbor PE`, … |
| 7 | Build number | QA fills. |
| 8 | Results (Pass/Fail) | QA fills. |
| 9 | Comment | `synthesized — review` / `CLI inheritance — review` markers on auto-generated rows; QA bug numbers. |

Banner rows are tinted: blue (flow), yellow (RFC-synth), violet (CLI-inherit).
Atomic rows under a banner leave col A blank — they inherit the topic
visually (matches DHCP-snoopy).

### Yossi-alignment note

Yossi's 2026-05-07 review demanded "steps and expected results must be
explicit." The shape change preserves that requirement: each Setup /
Action / Verify step is now a *separate row* (more explicit, not less)
under a topic banner. The change is visual, not semantic — the codegen-
friendly per-step structure that closed Yossi's gap is preserved and
arguably sharper.

### Synthesized — Review sheet contract

For every banner with provenance `synth` or `cli-inherit`, one row:

| Source | Anchor | Why this row is here | Recommended QA action |
|---|---|---|---|
| RFC mandate (synth) | `RFC7432bis-§10.1.1` | No flow in EVPN_FLOWS claimed this RFC MUST clause. Auto-synthesised so the mandate isn't silently dropped. | Refine the action/monitor/expectation against actual device behaviour; if the use case applies broadly, promote to a named Flow. |
| CLI inheritance | `allow-as-in` | Sub-config inherited from parent protocol's CLI (e.g. BGP). Not documented in the EVPN CLI doc. Source: <inheritance source string>. | Validate the syntax + defaults against the actual device behaviour. Replace this entry once the Exaware BGP CLI manual is integrated. |

### Cache impact

Cache salt remains v3 — PlanRow shape is unchanged (decomposition
happens at render time only). The committed `ai_cache.json` continues
to serve enriched content for the EVPN spec without re-bake. New
inherited CLI commands (the 7 BGP sub-configs) miss the cache and fall
back to rule-based PlanRow content; they enrich on the next AI bake.

### Open follow-ups for M2

- Replace `cli_inheritance.BGP_NEIGHBOR_AF_L2VPN_EVPN` with extracted
  commands from the real Exaware BGP CLI doc when it lands. `expand()`
  is idempotent on name — no other code changes required.
- The atomic-row decomposer mechanically splits Setup/Action/Verify
  prose into rows. M2 should consider hand-curating per-flow
  `atomic_steps` lists on each `Flow` for higher-quality decomposition.

---

## 6. Open questions to resolve before M2 / M3

These are **not** M1 blockers. Listed here so M2 doesn't start cold. Updated for SOW PQ4476E.

| For | Question | Owner |
|---|---|---|
| M2 | 2–3 additional Exaware spec samples to stress the requirement extractor across product lines | Codevalue → Exaware |
| M2 | Canonical regex(es) for Exaware requirement IDs across product lines (`EVPNS-REQ#NN` is one of many) | Exaware |
| M2 | What does the "dirty queue" workflow look like — how does Exaware select tests? UI? CLI flag? | Exaware |
| M3 | Cloud LLM (OpenAI / Anthropic Claude) acceptable per SOW deployment note; confirm Claude API key budget + rate limit | Exaware |
| M3 | Multi-router topology format — how is router topology described in inputs vs the plan output? | Exaware |
| M3 | Two human-written reference test plans for AI quality benchmarking | Exaware |
| M3 | Methodology to measure "40–50% effort reduction" claim (engineer-time tracking on N features) | Codevalue draft → Exaware confirm |
| M4 | **IXIA Router Simulator**: API to integrate with (per SOW §3 the details are to be defined "in collaboration with Exaware automation lead during M1–M2") | Exaware |
| M4 | **JSystem framework**: version, conventions, existing test class hierarchy that generated tests should plug into | Exaware automation lead |
| M4 | **Neighboring Router** test fixtures: mocked? real device? containerlab profile? | Exaware |
| M5 | On-premises hardware ready (HP Z2 Mini per SOW BOM, customer-purchased)? | Exaware |
| M5 | User documentation language preferences (English only / English + Hebrew)? | Exaware |

---

## 7. Repository layout

```
ate/
├── ate/                          package source
│   ├── __init__.py
│   ├── cli.py                    `ate parse <file>` + `ate plan <file>`
│   ├── ir.py                     Pydantic IR models for parsed docs
│   ├── errors.py                 typed exception hierarchy
│   ├── normalize.py              cross-format parity normalization
│   ├── parsers/
│   │   ├── dispatch.py           format detection + routing
│   │   ├── docx_parser.py
│   │   ├── pdf_parser.py
│   │   └── txt_parser.py
│   └── planner/                  ★ NEW for M1 (PQ4476E)
│       ├── model.py              Plan, PlanRow, Requirement Pydantic models
│       ├── extractor.py          extract requirements from IR
│       ├── categories.py         category + sub-test templates
│       ├── generator.py          IR → Plan model (scaffold → enricher)
│       ├── ai_enricher.py        Claude (Anthropic) integration with cache
│       ├── ai_cache.json         Committed AI-enriched rows (100% EVPN coverage)
│       └── xlsx_writer.py        Plan → xlsx matching Exaware template
├── scripts/
│   ├── verify_env.py       dev environment health check
│   ├── score.py            M1 acceptance scorecard generator
│   ├── build_goldens.py    regenerate / diff goldens
│   ├── build_tier_c.py     synthesize Tier-C edge case files
│   ├── build_ai_cache.py   bake AI-enriched ai_cache.json from curated entries
│   └── report.py           generate single-file HTML test report
├── tests/
│   ├── conftest.py
│   ├── test_dispatch.py
│   ├── test_parsers.py
│   ├── test_planner.py     IR→Plan→xlsx + extractor + xlsx_writer tests
│   ├── test_ai_enricher.py cache + mocked-API + fallback paths
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
├── references/             client-provided references (read-only, committed)
│   ├── <FEATURE>/          one folder per feature (e.g. EVPN/) — SFS + CLI doc + RFCs
│   └── *.xlsx              cross-feature output templates
├── plans/                  generated test plan xlsx (gitignored)
├── out/                    generated IR JSON per parsed doc (gitignored)
├── results/                generated HTML reports + pytest-junit.xml (gitignored)
├── modular_tools.sh        ★ swiss knife dispatcher (run-tests, plan, plan_all,
│                              parse, parse_all, verify, regression, golden_*, …)
├── Makefile                thin alias layer
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

## 8. Sign-off

* **M1 numeric acceptance:** `./modular_tools.sh run-tests` → all `[PASS]` rows in the HTML report
* **M1 deliverable artifact:** `plans/EVPN_System_Specification_1.00.xlsx` (and other Word feature specs)
* **M1 human acceptance:** Exaware reviewer completes `docs/exaware-acceptance.md` after reviewing the xlsx artifact
* **Regression baseline locked:** `tests/golden/` committed; future drift detected automatically

When all four are satisfied, M1 is accepted and **15%** of the contract value is due (per PQ4476E §6). Per the Cure Period clause, Exaware may withhold the M1 invoice only if the deliverable is materially non-conforming, with written deficiencies and a reasonable Cure Period before rejection (max 2 resubmissions).

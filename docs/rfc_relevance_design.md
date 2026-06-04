# Driving feature-relevant aspects from associated RFCs

**Status:** design proposal — for Ilan + Yossi to review
**Raised by:** Aleksey Burger, SW review 2026-06-04
**Related code:** `ate/planner/rfc_crosscheck.py` (the detector), `ate/planner/rfc_extractor.py` (the extractor), `ate/planner/requirements_builder.py`

## The problem

The EVPN SFS cites **9 RFCs**; the engine ingested **2**
(`rfc7432bis`, `rfc9785`). The RFC cross-check (shipped 2026-06-04) now
*detects* the gap and alerts on the other 7 — but detection is only half
of Aleksey's ask. The second half:

> "we need to think how to tackle the list of RFCs that are associated to
> the feature but to drive from them only aspects relevant to a feature."

Naively ingesting every cited RFC the way we ingest `rfc7432bis` would
**flood the test plan with irrelevant rows**. `rfc_extractor.py` emits one
requirement per leaf section containing a MUST/SHALL. RFC 4364 (BGP/MPLS
IP-VPNs, ~47 pages) would contribute ~80 normative clauses — but EVPN only
inherits a *slice* of it (the §10 transport / inter-AS procedures behind
the EVI-to-EVI flows). The rest (IPv4 VPN route distribution, CE-PE
routing protocols, …) is out of EVPN's scope and would bury the real
signal. The same is true of RFC 6514 (multicast in MPLS/BGP IP-VPNs),
RFC 4761/4762 (VPLS), etc.

So the requirement is a **relevance filter**: ingest the cited RFCs, but
promote to test rows only the clauses that bear on *this feature*.

## The cited RFCs, classified

The cross-check output, hand-annotated by role — this is the input the
filter needs:

| RFC | Role for EVPN | Proposed handling |
|---|---|---|
| 7432bis | **Core** — defines EVPN | Ingest fully (already done) |
| 9785 | **Core delta** — DF election | Ingest fully (already done) |
| 4364 | **Transport/underlay** — §10 inter-AS & PHP behind EVI-to-EVI | Ingest **§10 + transport sections only** |
| 6514 | **Transport/underlay** — multicast (BUM) tunnels | Ingest BUM-relevant sections only |
| 4761 / 4762 | **Predecessor** — VPLS, cited for context/migration | Reference only; no test rows |
| 7209 | **Framework** — EVPN requirements/motivation | Reference only (narrative, already skipped by `_BOILERPLATE_TITLES`) |
| 8584 | **Extensibility** — DF election framework | Ingest only if a DF-election clause is feature-claimed |
| 8340 | **Notation** — YANG tree diagrams | Ignore (conventions, like BCP-14) |
| 2119 / 8174 | **Keywords** — BCP 14 | Ignore (already filtered by the cross-check) |

The pattern: every cited RFC falls into one of five tiers —
**core / transport / predecessor / framework / notation**. Only *core* is
ingested wholesale; *transport* is section-scoped; the rest are
reference-only or ignored.

## Three filtering mechanisms (compose them)

### 1. Per-RFC role map (curated, per feature)
A small hand-curated table — the same pattern as
`cli_inheritance.py` — mapping `(feature, rfc) → role + section allow-list`.
For EVPN: `RFC4364 → transport, sections {"10", "10.*"}`. Cheap, precise,
auditable; the cost is one-time curation per feature. This is the
**highest-confidence** lever and should be the backbone.

### 2. Section-level keyword gate (automatic)
Extend `rfc_extractor.extract_rfc_requirements` with an optional
`relevance_terms` set. A leaf section is promoted only if its body mentions
feature vocabulary (`EVI`, `ESI`, `MAC-VRF`, `EVPN`, `route type`,
`Ethernet Segment`, `service label`, …). Catches relevant clauses the
section allow-list misses, and drops clearly off-topic ones. Reuses the
existing `MUST_RE` plumbing.

### 3. SFS-citation-context anchoring (automatic)
The cross-check already captures *where* in the SFS each RFC is cited. We
can go further: when the SFS cites an RFC **with a section** ("per RFC 4364
§10"), treat those section numbers as a high-priority allow-list. The SFS
is telling us which parts it actually inherits — let it drive the filter.

**Recommendation:** mechanism **1 as the backbone** (curated role +
section allow-list per feature), with **2 and 3 as automatic wideners**
that catch what the curation misses. An optional **LLM relevance pass**
(ask the model "does this clause bear on testing EVPN?" per candidate
section) is a possible fourth gate, but it is non-deterministic and
expensive — hold it in reserve, behind the deterministic gates.

## Surfacing (no silent drops)

Whatever is filtered *out* must remain visible — a silently dropped RFC
reads as "covered" when it isn't. The **RFC Cross-Check sheet** is the
natural home: extend it from cited/ingested to four states per RFC —
`ingested-full`, `ingested-scoped (§N only)`, `reference-only (role: …)`,
`ignored (notation/keyword)` — so a reviewer can challenge any call.

## Phased plan

1. **Done (2026-06-04):** detect & alert on un-ingested cited RFCs;
   RFC Cross-Check sheet.
2. **Next:** add the per-feature role map + section allow-list (mechanism 1),
   wire `rfc_paths` to accept a `role`/`sections` qualifier, and ingest
   **RFC 4364 §10** to back the new EVI-to-EVI flows (FLOW-130..135) with
   real normative req-IDs instead of `(coverage-driven)`.
3. **Then:** add the keyword gate (mechanism 2) and SFS-citation-context
   anchoring (mechanism 3); extend the cross-check sheet to the
   four-state view.
4. **Optional:** LLM relevance gate as a tie-breaker behind the
   deterministic filters.

## Open questions for Yossi

- Is the **curated per-feature role map** acceptable as the backbone, or
  do we want this fully automatic from day one? (Curation is more accurate
  but doesn't scale to many features without effort.)
- For **RFC 4364**, do we ingest the full §10, or only the specific
  inter-AS options (A/B/C) and PHP behaviour the EVI-to-EVI flows exercise?
- Should **reference-only** RFCs (VPLS, framework) appear in the plan at
  all — even as a non-testable "context" band — or only in the
  cross-check sheet?

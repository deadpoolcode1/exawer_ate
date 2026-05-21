"""Classify SFS requirements by their relationship to RFC base behaviour.

Yossi (client) push-back, 2026-05-21 follow-up: a QA engineer reads the
SFS as an **overlay** on the RFC base, not as a flat list of independent
requirements. The SFS:

  - Points at which RFCs are relevant ("see [RFC7432bis], chapter 7.2").
  - Lists deltas — places where the vendor implementation differs from
    the RFC ("the document replaces SHOULD to MUST in the second rule").
  - Lists overlays — places where the vendor adds new constraints on top
    of the RFC ("in addition to chapter 8.5, the system MUST also …").
  - Can be a pure pointer — "implement what RFC §X specifies", with no
    SFS-specific content.

Previously every SFS req was a flat sibling of every RFC req. This
classifier annotates each SFS req with:

  - `kind ∈ {base_sfs, delta, overlay, pointer, sfs_with_rfc_context}`
  - `rfc_links: list[str]` — RFC req_ids the SFS req points at,
    resolved against the actual RFC catalog (so we only link to
    sections we have extracted, not phantom references).

The AI enricher reads these to emit row content that contrasts SFS-vs-RFC
behaviour explicitly. The xlsx writer surfaces the relationship in the
Comment column ("delta from RFC7432bis-§8.7", "pointer to RFC7432bis-§9.2",
etc.) so a QA engineer scanning the plan sees the SFS/RFC structure.

The classifier is rule-based: keyword cues + RFC-ref presence + length
heuristics. It does not call an LLM — classification stays deterministic
and cheap. Heuristics tuned against the EVPN SFS (40 reqs); reach into
other features as the corpus grows.
"""
from __future__ import annotations

import re

from ate.planner.model import Requirement

# "RFC7432bis ch.7.2" → ("RFC7432bis", "7.2") for linking to RFC catalog.
_REFLINE_RE = re.compile(r"(RFC\w+|Pref-DF)\s+ch\.([\d.]+)", re.IGNORECASE)

# Delta cues: SFS modifies / replaces / overrides RFC base behaviour.
_DELTA_RE = re.compile(
    r"\b(replac\w*|modif\w*|instead of|in place of|"
    r"overrid\w*|supersed\w*|differ\w*|alter\w*)\b",
    re.IGNORECASE,
)

# Overlay cues: SFS adds new constraints beyond what the RFC specifies.
_OVERLAY_RE = re.compile(
    r"\b(in addition to|extends|exaware-specific|"
    r"vendor[- ]specific|beyond what)\b",
    re.IGNORECASE,
)

# Pointer cues: "(see [RFC X], chapter Y)" or "as defined in [RFC X]".
# When the SFS req's description is short AND uses one of these phrases,
# the SFS row is essentially a traceability pointer; the real test is
# driven by the RFC row.
_POINTER_RE = re.compile(
    r"\(see\s+\[?RFC|"
    r"\bas\s+(defined|described|specified)\s+in\s+\[?RFC",
    re.IGNORECASE,
)

# Pointer reqs typically have descriptions like "X (see [RFC], chapter Y)
# MUST be supported" — short, one MUST, mostly the citation.
_POINTER_MAX_DESC_LEN = 300


def _resolve_rfc_links(rfc_refs: list[str],
                       rfc_catalog_ids: set[str]) -> list[str]:
    """Convert "RFC7432bis ch.7.2" annotations to "RFC7432bis-§7.2"
    req_ids, but only keep links that exist in the RFC catalog. A
    reference to a section we didn't extract is dropped — better to
    surface a real link or nothing than to fabricate one.
    """
    out: list[str] = []
    for ref in rfc_refs:
        m = _REFLINE_RE.search(ref)
        if not m:
            continue
        candidate = f"{m.group(1)}-§{m.group(2)}"
        if candidate in rfc_catalog_ids and candidate not in out:
            out.append(candidate)
    return out


def classify(req: Requirement,
             rfc_catalog_ids: set[str]) -> tuple[str, list[str]]:
    """Return `(kind, rfc_links)` for an SFS requirement.

    Classification precedence (first match wins):
      1. RFC reqs (source == "rfc") → kind="rfc".
      2. CLI anchors (source == "cli") → kind="cli".
      3. No rfc_refs → kind="base_sfs".
      4. Delta cue in description → kind="delta".
      5. Overlay cue in description → kind="overlay".
      6. Short description + pointer cue → kind="pointer".
      7. Else (RFC ref present, no delta/overlay/pointer cue) →
         kind="sfs_with_rfc_context".

    `rfc_links` is populated for any req with rfc_refs that resolve to
    catalog entries.
    """
    if req.source == "rfc":
        return "rfc", []
    if req.source == "cli":
        return "cli", []

    rfc_links = _resolve_rfc_links(req.rfc_refs, rfc_catalog_ids)

    if not req.rfc_refs:
        return "base_sfs", []

    desc = req.description
    desc_lc = desc.lower()

    if _DELTA_RE.search(desc_lc):
        return "delta", rfc_links
    if _OVERLAY_RE.search(desc_lc):
        return "overlay", rfc_links
    if len(desc) < _POINTER_MAX_DESC_LEN and _POINTER_RE.search(desc):
        return "pointer", rfc_links
    return "sfs_with_rfc_context", rfc_links


def classify_all(reqs: list[Requirement]) -> None:
    """In-place: set `kind` and `rfc_links` on every req in the list.

    The RFC catalog is read off the input list itself — RFC reqs are
    `source == "rfc"`. Caller must pass the merged catalog (SFS + RFC),
    not just the SFS slice, otherwise rfc_links resolution would always
    return empty.
    """
    rfc_ids = {r.req_id for r in reqs if r.source == "rfc"}
    for r in reqs:
        kind, links = classify(r, rfc_ids)
        r.kind = kind
        r.rfc_links = links

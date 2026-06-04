"""Cross-check the RFCs an SFS *cites* against the RFCs actually *ingested*.

Aleksey Burger (SW review, 2026-06-04) flagged that the EVPN SFS references
RFC 4364 (and several others) that the engine never ingested — only
`rfc9785` and `draft-ietf-bess-rfc7432bis-13` were shared. The planner
silently worked off the two it had, with no signal that the SFS pointed at
more. This module scans the SFS text for RFC citations, reconciles them
against the ingested set, and reports the gap so a reviewer can decide which
missing RFCs carry feature-relevant mandates.

The narrower question Aleksey raised — *ingest the full list but drive only
feature-relevant aspects from each* — is a design item tracked separately in
`docs/rfc_relevance_design.md`. This module is the detector that surfaces the
gap; the relevance filter is the follow-up.

Normalisation note: an SFS citing "RFC 7432" is satisfied by ingesting
`draft-ietf-bess-rfc7432bis-13` (the bis revision). Reconciliation compares
bare RFC numbers, so 7432 ≈ 7432bis.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# A citation: "RFC 4364", "RFC4364", "rfc-4364", and the rfcNNNN embedded in
# draft names ("draft-ietf-bess-rfc7432bis-13" → 7432). Leading zeros are
# stripped at normalisation so "RFC 0826" == "RFC826".
_CITATION_RE = re.compile(r"\bRFC[\s\-]*0*(\d{3,5})\b", re.IGNORECASE)

# Requirements-language / notation RFCs that essentially every IETF document
# cites but which never carry feature-specific test mandates. Excluded from
# the "missing" alert so the real signal isn't drowned by BCP-14 boilerplate.
#   2119 / 8174 — "MUST / SHOULD / MAY" keyword definitions (BCP 14).
_BOILERPLATE: set[str] = {"2119", "8174"}


@dataclass
class RfcCrossCheck:
    """Result of reconciling cited-vs-ingested RFCs for one SFS.

    - `cited`:   bare RFC number → first-seen context snippet from the SFS.
    - `ingested`: bare RFC numbers actually provided as inputs.
    - `covered`: cited ∩ ingested (sorted numerically).
    - `missing`: cited − ingested − boilerplate (sorted numerically) — the
      RFCs the SFS points at that the engine never saw.
    """
    cited: dict[str, str]
    ingested: set[str]
    covered: list[str]
    missing: list[str]

    @property
    def has_gap(self) -> bool:
        return bool(self.missing)


def _bare_num(token: str) -> str | None:
    """First 3–5 digit run in `token`, leading zeros stripped. None if none.

    `'rfc7432bis'` → `'7432'`, `'RFC 0826'` → `'826'`.
    """
    m = re.search(r"(\d{3,5})", token)
    return str(int(m.group(1))) if m else None


def ingested_numbers(rfc_paths) -> set[str]:
    """Bare RFC numbers for each ingested RFC path, derived from the filename.

    `references/EVPN/draft-ietf-bess-rfc7432bis-13.txt` → `'7432'`
    `references/EVPN/rfc9785.txt`                       → `'9785'`
    """
    out: set[str] = set()
    for p in rfc_paths or []:
        stem = Path(p).stem.lower()
        m = re.search(r"rfc[\s\-]*0*(\d{3,5})", stem)
        if m:
            out.add(str(int(m.group(1))))
    return out


def cited_numbers(text: str) -> dict[str, str]:
    """Map each cited RFC number → a short context snippet (first occurrence).

    The snippet is whitespace-collapsed and trimmed to ~140 chars so a
    reviewer can judge relevance ("RFC 4364 inter-AS option B") without
    opening the SFS.
    """
    out: dict[str, str] = {}
    if not text:
        return out
    for m in _CITATION_RE.finditer(text):
        num = _bare_num(m.group(1))
        if num is None or num in out:
            continue
        lo = max(0, m.start() - 60)
        hi = min(len(text), m.end() + 80)
        out[num] = re.sub(r"\s+", " ", text[lo:hi]).strip()
    return out


def reconcile(sfs_text: str, rfc_paths) -> RfcCrossCheck:
    """Reconcile RFCs cited in `sfs_text` against the ingested `rfc_paths`."""
    cited = cited_numbers(sfs_text)
    ingested = ingested_numbers(rfc_paths)
    covered = sorted((n for n in cited if n in ingested), key=int)
    missing = sorted(
        (n for n in cited
         if n not in ingested and n not in _BOILERPLATE),
        key=int,
    )
    return RfcCrossCheck(cited=cited, ingested=ingested,
                         covered=covered, missing=missing)


def format_warning(cc: RfcCrossCheck) -> str:
    """Human-readable multi-line CLI warning, or '' when there is no gap."""
    if not cc.has_gap:
        return ""
    lines = [
        f"warning: SFS cites {len(cc.cited)} RFC(s); {len(cc.missing)} "
        f"referenced but NOT ingested into the engine:",
    ]
    for num in cc.missing:
        lines.append(f"  • RFC{num}  —  …{cc.cited[num]}…")
    if cc.covered:
        lines.append(
            "  (ingested & matched: "
            + ", ".join(f"RFC{n}" for n in cc.covered) + ")"
        )
    lines.append(
        "  Add the missing RFCs under references/<FEATURE>/ to ingest their "
        "mandates, or confirm they carry no feature-relevant requirements "
        "(see docs/rfc_relevance_design.md)."
    )
    return "\n".join(lines)

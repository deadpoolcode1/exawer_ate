"""Pull requirements out of a parsed Document IR.

A "requirement" is a heading whose text contains a configurable anchor
pattern (default: `EVPNS-REQ#NN`). For each requirement we collect:
  - id, title, section number
  - description: paragraphs from after the heading until the next heading
  - must_statements: MUST/SHALL/MUST NOT sentences within description
  - rfc_refs: chapter references (e.g. "[RFC7432bis], chapter 7.2")
  - code_blocks: CLI/config blocks within the requirement's section
  - tags: domain tags ({"CONFIG", "PACKET", "HA", "SCALE", "PROTOCOL", "MONITORING"})

Tags drive Category applicability — we don't apply every Category to every
requirement. That cuts out the worst noise from the v1 generator.
"""
from __future__ import annotations

import re

from ate.ir import CodeBlock, Document, Heading
from ate.planner.model import Requirement

DEFAULT_ANCHOR_RE = re.compile(r"\b([A-Z][A-Z0-9_-]*-REQ#\d+)\b")
MUST_RE = re.compile(
    r"[^.!?]*?\b(MUST|MUST NOT|SHALL|SHALL NOT|REQUIRED)\b[^.!?]*[.!?]",
    re.IGNORECASE,
)
RFC_REF_RE = re.compile(
    r"\[(RFC\d{4,5}\w*|Pref-DF)\][,\s]*chapter[s]?\s+([\d.]+)",
    re.IGNORECASE,
)

# Domain tag classifier — keyword sets per tag.
TAG_KEYWORDS: dict[str, list[str]] = {
    "CONFIG": [
        # CLI / config-shape keywords
        "configuration", "configurat", "interface", "vlan-id", "service-type",
        "router distinguisher", "auto-discovery", "import-rt", "export-rt",
        "lacp", "ethernet-segment",
        # Natural-language variants for title matching
        "service type", "vlan-based", "vlan-aware", "port-based",
        "static mac", "mac learning", "ethernet segment",
    ],
    "PACKET": [
        "packet", "frame", "forwarding", "bum", "unicast", "multicast",
        "broadcast", "ingress replication", "drop", "split horizon",
        "best path", "route prioritization",
    ],
    "HA": [
        "redundancy", "designated forwarder", " df ", "multi-homing",
        "multi-homed", "fast convergence", "load balancing", "all-active",
        "single-active", "aliasing", "primary", "backup", "mac mobility",
        "interoperability with single-homing",
    ],
    "SCALE": [
        "scale", "limit", " max ", "mac mobility", "mac-limit",
    ],
    "PROTOCOL": [
        "bgp", "mpls", "label", "extended community", "route target",
        " rt ", " rd ", " esi ", "ethernet a-d", "advertise", "route type",
        "label type", "ethernet segment route", "mac/ip", "mac advertisement",
        "pmsi", "es-import",
    ],
    "MONITORING": [
        "alarm", "syslog", "log", "tech-support",
    ],
}

# Title-substring lockouts: if the requirement title contains any of these
# substrings, the tag is NEVER applied (regardless of keyword score).
# These pre-empt the false positives we observed during M1 review:
#   - REQ#280 MAC/IP Advertisement (title) → mention of "mobility flag" in
#     description triggered HA + SCALE; lock out by title pattern.
#   - REQ#390 Alarms / REQ#400 Syslog → descriptions contain protocol/HA
#     terms incidentally; tag should be MONITORING-only.
#   - REQ#10 Supported Standards → meta requirement; only META applies.
TAG_TITLE_LOCKOUTS: dict[str, list[str]] = {
    "HA": [
        "address advertisement", "label",
        "best path", "forwarding rules", "forwarding unicast",
        "alarm", "syslog", "supported standards",
        "router distinguisher", "common cli", "configuration",
        "service interface type", "service type", "static mac",
        "es-import", "l2-attr", "pmsi tunnel",
    ],
    "SCALE": [
        "address advertisement", "label",
        "best path", "forwarding rules", "forwarding unicast",
        "alarm", "syslog", "router distinguisher", "common cli",
        "configuration", "service interface type", "service type",
        "static mac", "es-import", "l2-attr", "pmsi tunnel",
        "split horizon", "interoperability with single-homing",
        "signaling primary", "aliasing path", "fast convergence",
    ],
    "PROTOCOL": [
        "alarm", "syslog", "configuration", "long run", "static mac",
        "supported standards",
    ],
    "CONFIG": [
        "alarm", "syslog", "supported standards", "remote mac learning",
        "best path", "fast convergence", "split horizon",
        "interoperability with single-homing", "aliasing path",
        "forwarding rules", "forwarding unicast",
        "signaling primary",
    ],
    "MONITORING": [],  # MONITORING rarely false-positives
    "PACKET": [
        "router distinguisher", "supported standards", "common cli",
    ],
}


def _compute_tags(title: str, description: str) -> set[str]:
    """Score-based tag assignment.

    For each tag:
      - Skip if title contains any TAG_TITLE_LOCKOUTS substring.
      - Score = 3 × (keyword matches in title) + 1 × (keyword matches in desc).
      - Tag applies if score ≥ 2 (so: 1 title match OR 2 distinct desc matches).

    This eliminates the v1 problem where a single passing mention of a
    keyword in the description (e.g. "MAC mobility flag" in REQ#280's
    route-format description) would falsely apply a tag like HA.
    """
    title_lc = title.lower()
    desc_lc = description.lower()
    tags: set[str] = set()
    for tag, keywords in TAG_KEYWORDS.items():
        # Title-pattern lockout: if title matches any of these phrases,
        # the tag is forbidden regardless of keyword score.
        if any(lock in title_lc for lock in TAG_TITLE_LOCKOUTS.get(tag, [])):
            continue
        title_hits = sum(1 for kw in keywords if kw in title_lc)
        desc_hits = sum(1 for kw in keywords if kw in desc_lc)
        score = 3 * title_hits + desc_hits
        if score >= 2:
            tags.add(tag)
    return tags


def _infer_section_numbers(blocks: list) -> dict[int, str]:
    """Assign hierarchical section numbers to headings whose text has none.

    Word docs often use auto-numbering, which doesn't survive `paragraph.text`.
    We walk headings in document order and synthesize numbers from level:
    a Heading at level N increments counters[N] and resets counters[N+1..].
    Returns {block_index: section_number_str}.
    """
    out: dict[int, str] = {}
    counters: list[int] = []
    for i, b in enumerate(blocks):
        if not isinstance(b, Heading):
            continue
        level = max(1, min(b.level, 9))
        # Extend counters to current level
        while len(counters) < level:
            counters.append(0)
        counters[level - 1] += 1
        # Reset deeper counters
        del counters[level:]
        # Use the explicit number if the heading already had one; else inferred
        if b.number:
            out[i] = b.number
        else:
            out[i] = ".".join(str(c) for c in counters)
    return out


def extract_requirements(doc: Document, anchor_re: re.Pattern[str] | None = None
                         ) -> list[Requirement]:
    pat = anchor_re or DEFAULT_ANCHOR_RE
    out: list[Requirement] = []
    blocks = list(doc.blocks)
    inferred_numbers = _infer_section_numbers(blocks)

    for i, b in enumerate(blocks):
        if not isinstance(b, Heading):
            continue
        m = pat.search(b.text)
        if not m:
            continue
        req_id = m.group(1)
        title = pat.sub("", b.text).strip().rstrip("()").strip()

        # Walk forward through this section AND its sub-sections.
        # Stop at: next heading at same-or-shallower level, OR another req anchor.
        # Sub-headings are absorbed but NOT folded into description (their text
        # would corrupt MUST-sentence extraction). Their content (paragraphs +
        # code blocks) IS absorbed.
        cur_level = b.level
        desc_parts: list[str] = []
        section_code_blocks: list[str] = []
        for j in range(i + 1, len(blocks)):
            nb = blocks[j]
            if isinstance(nb, Heading):
                if nb.level <= cur_level:
                    break
                if pat.search(nb.text):
                    break
                # Skip the sub-heading text itself — it's not description
                continue
            if isinstance(nb, CodeBlock):
                section_code_blocks.append(nb.text)
            elif hasattr(nb, "text") and nb.text:
                desc_parts.append(nb.text)
        description = " ".join(desc_parts).strip()

        # MUST / SHALL statements (full sentences, not just the keyword)
        must_sentences = [m.group(0).strip() for m in MUST_RE.finditer(description)]

        # RFC chapter refs (e.g. "[RFC7432bis], chapter 7.2")
        rfc_refs = sorted({
            f"{rfc} ch.{ch}" for rfc, ch in RFC_REF_RE.findall(description)
        })

        # Domain tags via score-based classifier with title-pattern lockouts
        tags = _compute_tags(title, description)
        if not tags:
            # No tag matched → META: minimal coverage (Basic + 3rd-party only)
            tags = {"META"}

        out.append(Requirement(
            req_id=req_id,
            title=title,
            section_number=b.number or inferred_numbers.get(i),
            description=description[:1000],
            must_statements=must_sentences[:3],
            rfc_refs=rfc_refs[:3],
            code_blocks=section_code_blocks[:2],
            tags=sorted(tags),
        ))

    # Dedup by req_id, first-seen-wins (handles TOC duplicates)
    seen: set[str] = set()
    uniq: list[Requirement] = []
    for r in out:
        if r.req_id in seen:
            continue
        seen.add(r.req_id)
        uniq.append(r)
    return uniq

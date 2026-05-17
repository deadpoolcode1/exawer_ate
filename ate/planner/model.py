"""Plan IR — what `generate_plan` returns.

The Plan is the format-neutral representation of a test plan, separated
from the xlsx writer so M3 (AI generation) and M5 (web UI) can consume
the same shape without re-parsing xlsx.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Requirement(BaseModel):
    """A single requirement extracted from the source document."""
    req_id: str          # e.g. "EVPNS-REQ#280"
    title: str           # heading text (without the req_id)
    section_number: str | None = None
    description: str = ""  # text following the heading, joined
    must_statements: list[str] = Field(default_factory=list)  # MUST/SHALL sentences
    rfc_refs: list[str] = Field(default_factory=list)  # ["RFC7432bis ch.7.2", ...]
    code_blocks: list[str] = Field(default_factory=list)  # CLI examples in section
    tags: list[str] = Field(default_factory=list)  # ["CONFIG", "PACKET", ...]
    # "spec" → vendor SFS (defines CLI, NETCONF, upgrade behavior).
    # "rfc"  → IETF RFC (defines protocol behavior only — no CLI/mgmt/upgrade).
    # Drives category masking in categories_for_tags().
    source: str = "spec"


class PlanRow(BaseModel):
    """One row of the xlsx test plan.

    `action_steps` is a multi-line string with the Setup → Action →
    Verify scaffolding (each stage prefixed with its label).
    `expectation` carries the measurable Pass + Fail-on pair.
    `equipment` is a short tag like "DUT + IXIA + neighbor PE" — QA
    knows the rig before reading the row.

    QA-feedback redesign: rows are now driven by **functional flows**
    (use cases) instead of one row per requirement. Each row carries
    `flow_id` / `flow_name` and a list of contributing requirement IDs
    (`covered_req_ids`). For traceability with the existing template,
    `sfs_requirement_id` keeps a comma-joined string of those IDs (or a
    single ID for CLI-command rows that remain per-command).
    """
    flow_id: str = ""      # e.g. "FLOW-020"; empty for CLI rows
    flow_name: str = ""    # human label, mirrors the flow's name
    category: str          # top-level category (e.g. "CLI configuration")
    sub_category: str = "" # secondary header (CLI command name, etc.)
    equipment: str = ""    # Test Equipment / topology
    action_steps: str = "" # Setup / Action / Verify (multi-line)
    covered_req_ids: list[str] = Field(default_factory=list)
    sfs_requirement_id: str = ""  # comma-joined view of covered_req_ids
    expectation: str = ""  # Pass / Fail-on (multi-line)


class AtomicRow(BaseModel):
    """One row in the DHCP-snoopy-shaped xlsx ("Test Plan Topics" sheet).

    The render-time projection of `PlanRow`: a multi-line Setup/Action/Verify
    blob becomes a banner row + N atomic action rows. `topic` is populated
    only on banners; continuation rows leave it empty so QA reads it as
    "inherits the topic above" (matches the reference DHCP-snoopy TP).

    The 9-column schema (Topic / Action / Req ID / Expectation / Monitor /
    Equipment / Build / Results / Comment) maps 1:1 to fields below; Build,
    Results, Comment are QA fill-in columns that we leave blank except for
    `provenance` which surfaces synth markers in the Comment column.
    """
    topic: str = ""           # col A; populated only on banner rows
    action: str = ""          # col B
    req_ids: list[str] = Field(default_factory=list)  # col C, comma-joined
    expectation: str = ""     # col D
    monitor: list[str] = Field(default_factory=list)  # col E, comma-joined
    equipment: str = ""       # col F
    is_banner: bool = False   # styling hint
    provenance: str = ""      # "" | "synth" | "cli-inherit" → col I marker


class Plan(BaseModel):
    """A test plan: header context + ordered rows."""
    feature_name: str
    source_path: str
    machine_vendor: str = "EC"
    machine_types: str = (
        "Plan is model-agnostic across Exaware MX and AX; flows apply "
        "to either DUT without modification"
    )
    ip_versions: str = (
        "IPv4 (control plane: BGP EVPN session); IPv4 + IPv6 host IPs "
        "carried in Type 2 NLRI per RFC 7432bis §7.2 (validated in FLOW-030)"
    )
    interfaces: str = (
        "x-eth, Sub-if, Q-in-Q, agg-eth, vlan-range (all five exercised "
        "in FLOW-014; agg-eth additionally in FLOW-020..022)"
    )
    special_interfaces: str = ""
    requirements: list[Requirement] = Field(default_factory=list)
    rows: list[PlanRow] = Field(default_factory=list)

    @property
    def n_requirements(self) -> int:
        return len(self.requirements)

    @property
    def n_rows(self) -> int:
        return len(self.rows)

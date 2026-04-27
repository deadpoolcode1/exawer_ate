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


class PlanRow(BaseModel):
    """One row of the xlsx test plan."""
    category: str          # column A — top-level category (e.g. "CLI configuration")
    sub_category: str = "" # appears as another row under category
    action_steps: str = "" # column B
    sfs_requirement_id: str = ""  # column C — for traceability
    expectation: str = ""  # column D
    # E/F/G are runtime fields filled in by the QA engineer (build, pass/fail, comment)


class Plan(BaseModel):
    """A test plan: header context + ordered rows."""
    feature_name: str
    source_path: str
    machine_vendor: str = "EC"
    machine_types: str = "e.g. MX, AX"
    ip_versions: str = "IPv4, IPv6"
    interfaces: str = "x-eth, Sub-if, Q-in-Q, agg-eth, vlan-range"
    special_interfaces: str = ""
    requirements: list[Requirement] = Field(default_factory=list)
    rows: list[PlanRow] = Field(default_factory=list)

    @property
    def n_requirements(self) -> int:
        return len(self.requirements)

    @property
    def n_rows(self) -> int:
        return len(self.rows)

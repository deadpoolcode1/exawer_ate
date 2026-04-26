"""Intermediate representation (IR) for parsed documents.

The IR is the contract between parsers (M1) and downstream consumers
(requirement extraction in M2, AI plan generation in M3, code generation in M4).
Schema is versioned via SCHEMA_VERSION; bumps require a migration note in the TDD.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0.0"


class BlockKind(str, Enum):
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    CODE = "code"
    TABLE = "table"


class Heading(BaseModel):
    kind: Literal[BlockKind.HEADING] = BlockKind.HEADING
    level: int = Field(ge=1, le=9)
    text: str
    number: str | None = None  # e.g. "2.3.1" if numbered


class Paragraph(BaseModel):
    kind: Literal[BlockKind.PARAGRAPH] = BlockKind.PARAGRAPH
    text: str


class ListItem(BaseModel):
    kind: Literal[BlockKind.LIST_ITEM] = BlockKind.LIST_ITEM
    text: str
    level: int = 1


class CodeBlock(BaseModel):
    """Verbatim block — CLI configuration, listings, fixed-width content.

    M1 acceptance metric M1.b requires 100% byte-identical preservation
    of these against source. They become test inputs in M3/M4.
    """
    kind: Literal[BlockKind.CODE] = BlockKind.CODE
    text: str
    language: str | None = None  # heuristic; may be None


class TableCell(BaseModel):
    text: str
    rowspan: int = 1
    colspan: int = 1


class Table(BaseModel):
    kind: Literal[BlockKind.TABLE] = BlockKind.TABLE
    rows: list[list[TableCell]]
    caption: str | None = None

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return max((len(r) for r in self.rows), default=0)


# Discriminated union for IR blocks
Block = Heading | Paragraph | ListItem | CodeBlock | Table


class Document(BaseModel):
    """A parsed document.

    `blocks` is an ordered flat list. Section structure is implicit via
    Heading.level. Consumers that need a tree should build one from blocks.
    """
    schema_version: str = SCHEMA_VERSION
    source_path: str
    source_format: Literal["pdf", "docx", "txt"]
    blocks: list[Block] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def headings(self) -> list[Heading]:
        return [b for b in self.blocks if isinstance(b, Heading)]

    @property
    def code_blocks(self) -> list[CodeBlock]:
        return [b for b in self.blocks if isinstance(b, CodeBlock)]

    @property
    def tables(self) -> list[Table]:
        return [b for b in self.blocks if isinstance(b, Table)]

    @property
    def paragraphs(self) -> list[Paragraph]:
        return [b for b in self.blocks if isinstance(b, Paragraph)]

    @property
    def full_text(self) -> str:
        parts: list[str] = []
        for b in self.blocks:
            if isinstance(b, Heading):
                parts.append(b.text)
            elif isinstance(b, Paragraph | ListItem | CodeBlock):
                parts.append(b.text)
            elif isinstance(b, Table):
                for row in b.rows:
                    parts.append(" | ".join(c.text for c in row))
        return "\n".join(parts)

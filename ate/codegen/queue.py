"""The dirty queue — which tests are selected, and which have gone stale.

The SOW's M2 line is "code generation based on **selected** tests", and the
milestone is titled "Dirty Queue & Code Generation". This is that half.

The problem it solves: regeneration is cheap but *review* is not. Once a
generated suite has been read by a QA engineer, filled with real expected
values and merged, blindly regenerating everything throws that away. The queue
tracks, per test, whether it has been reviewed and whether anything it derives
from has changed since.

State machine:

    NEW ──select──► SELECTED ──generate──► GENERATED ──approve──► APPROVED
     ▲                                          │                     │
     └──────────────── refresh finds a changed fingerprint ───────────┘
                                  ▼
                                STALE ──select──► SELECTED ...

`refresh()` is the whole point: it recomputes each test's fingerprint from its
step IR plus the source documents, and anything whose fingerprint moved since
it was generated becomes STALE. An APPROVED test that goes stale is surfaced
loudly — that is the case where someone's hand-filled expectations are about to
be overwritten.

Deliberately a plain JSON file, not a database: it has to be diffable, it has
to survive being committed next to the generated code, and M5's web UI needs to
read it without a service.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ate.codegen.script_ir import TestScript

QUEUE_VERSION = 1
DEFAULT_QUEUE_PATH = Path("out/codegen_queue.json")


class State(str, Enum):
    NEW = "new"
    SELECTED = "selected"
    GENERATED = "generated"
    STALE = "stale"
    APPROVED = "approved"


#: States from which `generate` will actually emit a file.
GENERATABLE = {State.SELECTED}
#: States that mean "a human has invested work here" — regenerating destroys it.
PROTECTED = {State.APPROVED}


def fingerprint(script: TestScript, source_digest: str = "") -> str:
    """Content hash of everything a generated file derives from.

    Covers the step IR (so a changed assertion, command or ordering is caught)
    and a digest of the source documents (so a re-issued SFS or CLI doc marks
    every dependent test stale). Stable across runs: no timestamps, no ordering
    surprises — `model_dump_json` sorts nothing, but the IR is an ordered list
    and order is itself semantic here.
    """
    payload = script.model_dump_json()
    h = hashlib.sha256()
    h.update(payload.encode("utf-8"))
    h.update(b"\x00")
    h.update(source_digest.encode("utf-8"))
    return h.hexdigest()[:16]


def digest_sources(paths: list[str | Path]) -> str:
    """Cheap content digest of the input documents.

    Uses size + mtime rather than reading tens of MB of .docx on every queue
    operation; the queue's job is change *detection*, and a same-size same-mtime
    file has not been re-issued. `--rehash` in the CLI forces a full read when
    that assumption needs checking.
    """
    h = hashlib.sha256()
    for p in sorted(str(x) for x in paths):
        f = Path(p)
        if not f.exists():
            h.update(f"missing:{p}".encode())
            continue
        st = f.stat()
        h.update(f"{f.name}:{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()[:16]


def digest_sources_full(paths: list[str | Path]) -> str:
    """Content-addressed digest — reads the files. Used by `--rehash`."""
    h = hashlib.sha256()
    for p in sorted(str(x) for x in paths):
        f = Path(p)
        h.update(f.name.encode())
        h.update(f.read_bytes() if f.exists() else b"missing")
    return h.hexdigest()[:16]


@dataclass
class Entry:
    """One queue row — a whole test script, not a step.

    Step granularity was tempting (step IDs are stable and unique) but a
    JSystem test is generated as one file and reviewed as one unit, so the file
    is the right unit of selection.
    """

    test_id: str                 # flow ID, e.g. "FLOW-030"
    class_name: str
    state: State = State.NEW
    fingerprint: str = ""
    #: Fingerprint at the moment the file was last generated. Divergence from
    #: `fingerprint` is exactly what "stale" means.
    generated_fingerprint: str = ""
    note: str = ""

    def to_json(self) -> dict:
        return {
            "test_id": self.test_id,
            "class_name": self.class_name,
            "state": self.state.value,
            "fingerprint": self.fingerprint,
            "generated_fingerprint": self.generated_fingerprint,
            "note": self.note,
        }

    @classmethod
    def from_json(cls, d: dict) -> Entry:
        return cls(
            test_id=d["test_id"],
            class_name=d.get("class_name", ""),
            state=State(d.get("state", "new")),
            fingerprint=d.get("fingerprint", ""),
            generated_fingerprint=d.get("generated_fingerprint", ""),
            note=d.get("note", ""),
        )


@dataclass
class Queue:
    path: Path = DEFAULT_QUEUE_PATH
    entries: dict[str, Entry] = field(default_factory=dict)

    # ── persistence ──────────────────────────────────────────────────────
    @classmethod
    def load(cls, path: str | Path = DEFAULT_QUEUE_PATH) -> Queue:
        p = Path(path)
        if not p.exists():
            return cls(path=p)
        raw = json.loads(p.read_text(encoding="utf-8"))
        entries = {e["test_id"]: Entry.from_json(e)
                   for e in raw.get("entries", [])}
        return cls(path=p, entries=entries)

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": QUEUE_VERSION,
            "entries": [self.entries[k].to_json() for k in sorted(self.entries)],
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n",
                             encoding="utf-8")
        return self.path

    # ── lifecycle ────────────────────────────────────────────────────────
    def refresh(self, scripts: list[TestScript],
                source_digest: str = "") -> dict[str, list[str]]:
        """Reconcile the queue against the current scripts.

        Returns a report keyed by what happened: `added`, `stale`,
        `stale_approved` (the loud case — reviewed work is at risk), `removed`,
        `unchanged`.
        """
        report: dict[str, list[str]] = {
            "added": [], "stale": [], "stale_approved": [],
            "removed": [], "unchanged": [],
        }
        seen: set[str] = set()

        for sc in scripts:
            seen.add(sc.flow_id)
            fp = fingerprint(sc, source_digest)
            e = self.entries.get(sc.flow_id)
            if e is None:
                self.entries[sc.flow_id] = Entry(
                    test_id=sc.flow_id, class_name=sc.class_name,
                    state=State.NEW, fingerprint=fp)
                report["added"].append(sc.flow_id)
                continue

            e.class_name = sc.class_name
            if e.fingerprint == fp:
                report["unchanged"].append(sc.flow_id)
                continue

            e.fingerprint = fp
            if e.state in (State.GENERATED, State.APPROVED):
                if e.state is State.APPROVED:
                    report["stale_approved"].append(sc.flow_id)
                else:
                    report["stale"].append(sc.flow_id)
                e.state = State.STALE
            else:
                report["stale"].append(sc.flow_id)

        for missing in sorted(set(self.entries) - seen):
            report["removed"].append(missing)

        return report

    def select(self, test_ids: list[str]) -> list[str]:
        """Mark tests for generation. Unknown IDs are returned, not raised —
        the caller reports them; a typo shouldn't abort a batch."""
        unknown: list[str] = []
        for tid in test_ids:
            e = self.entries.get(tid)
            if e is None:
                unknown.append(tid)
                continue
            e.state = State.SELECTED
        return unknown

    def select_all(self, include_approved: bool = False) -> list[str]:
        picked = []
        for tid, e in sorted(self.entries.items()):
            if e.state in PROTECTED and not include_approved:
                continue
            e.state = State.SELECTED
            picked.append(tid)
        return picked

    def selected_ids(self) -> list[str]:
        return sorted(t for t, e in self.entries.items()
                      if e.state in GENERATABLE)

    def mark_generated(self, test_ids: list[str]) -> None:
        for tid in test_ids:
            e = self.entries.get(tid)
            if e is None:
                continue
            e.state = State.GENERATED
            e.generated_fingerprint = e.fingerprint

    def approve(self, test_ids: list[str]) -> list[str]:
        """Record that a human has reviewed the generated file (and, in
        practice, filled in its expected values)."""
        unknown: list[str] = []
        for tid in test_ids:
            e = self.entries.get(tid)
            if e is None:
                unknown.append(tid)
                continue
            e.state = State.APPROVED
            e.generated_fingerprint = e.fingerprint
        return unknown

    # ── reporting ────────────────────────────────────────────────────────
    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {s.value: 0 for s in State}
        for e in self.entries.values():
            counts[e.state.value] += 1
        return counts

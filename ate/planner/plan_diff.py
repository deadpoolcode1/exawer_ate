"""Diff two generated test plans and report the change in review terms.

Eyal Ozeri's first ask on 2026-07-07 was not a feature, it was a complaint:
*"I'm getting lost"* — each respin arrived as a fresh 1600-row workbook with no
statement of what had moved. He asked for a diff file with every version.

This produces that file. It diffs by the **stable identifiers** the plan
already carries (``FLOW-030``, ``CLI:mac-limit``, ``RFC7432bis-§7.2``), never
by row number, so a plan whose rows all shifted by forty reports zero churn.

What it reports, in the order a reviewer cares about:

1. **Topics added / removed** — the coarse shape change.
2. **Topics whose actions changed** — per-topic, with the added and removed
   action lines quoted.
3. **Cell-level edits** within an action that survived — expectation, monitor,
   req-ids and comment, each shown old → new.
4. **Counts**, so the header answers "did this respin grow or shrink" without
   reading further.

Renames are matched rather than reported as a delete plus an add: an action
whose wording was tightened is the single commonest edit in these respins, and
showing it as two unrelated lines is precisely the noise that made the previous
hand-written change notes unreadable.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from ate.planner.plan_reader import PlanAction, PlanDocument, PlanTopic, read_plan

#: Similarity above which two action texts are considered the same action,
#: reworded, rather than one removed and another added.
#:
#: 0.70 was chosen against the real corpus: the de-storytelling pass and the
#: continuation-marker rewrite both edit roughly a third of a sentence, and a
#: lower bar started pairing genuinely different steps within a CLI family
#: (whose actions are near-identical by construction — "Issue `show evpn
#: detail`" vs "Issue `show evpn summary`").
RENAME_RATIO = 0.70

#: Cells compared for edits on a surviving action. `build` and `results` are
#: excluded on purpose: QA fills those in, and reporting a reviewer's own
#: entries back at them as "changes" is noise.
COMPARED_CELLS = ("Req ID", "Expectation", "Monitor", "Test Equipment", "Comment")


@dataclass
class CellEdit:
    field: str
    old: str
    new: str


@dataclass
class ActionChange:
    kind: str                       # added | removed | reworded | edited
    old: PlanAction | None = None
    new: PlanAction | None = None
    edits: list[CellEdit] = field(default_factory=list)


@dataclass
class TopicChange:
    key: str
    label: str
    kind: str                       # added | removed | changed
    section: str = ""
    actions: list[ActionChange] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for a in self.actions:
            out[a.kind] = out.get(a.kind, 0) + 1
        return out


@dataclass
class PlanDiff:
    old: PlanDocument
    new: PlanDocument
    topics: list[TopicChange] = field(default_factory=list)

    @property
    def added(self) -> list[TopicChange]:
        return [t for t in self.topics if t.kind == "added"]

    @property
    def removed(self) -> list[TopicChange]:
        return [t for t in self.topics if t.kind == "removed"]

    @property
    def changed(self) -> list[TopicChange]:
        return [t for t in self.topics if t.kind == "changed"]

    @property
    def is_empty(self) -> bool:
        return not self.topics


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------

def diff_plans(old_path: Path | str, new_path: Path | str) -> PlanDiff:
    return diff_documents(read_plan(old_path), read_plan(new_path))


def diff_documents(old: PlanDocument, new: PlanDocument) -> PlanDiff:
    old_by = {t.uid: t for t in old.topics}
    new_by = {t.uid: t for t in new.topics}
    result = PlanDiff(old=old, new=new)

    for uid, topic in new_by.items():
        if uid not in old_by:
            result.topics.append(TopicChange(
                key=topic.key, label=topic.label, kind="added",
                section=topic.section,
                actions=[ActionChange("added", new=a) for a in topic.actions]))

    for uid, topic in old_by.items():
        if uid not in new_by:
            result.topics.append(TopicChange(
                key=topic.key, label=topic.label, kind="removed",
                section=topic.section,
                actions=[ActionChange("removed", old=a) for a in topic.actions]))

    for uid, new_topic in new_by.items():
        old_topic = old_by.get(uid)
        if old_topic is None:
            continue
        changes = _diff_actions(old_topic, new_topic)
        if changes:
            result.topics.append(TopicChange(
                key=new_topic.key, label=new_topic.label, kind="changed",
                section=new_topic.section, actions=changes))

    result.topics.sort(key=lambda t: (_KIND_RANK.get(t.kind, 9), t.section, t.key))
    return result


_KIND_RANK = {"added": 0, "removed": 1, "changed": 2}


def _diff_actions(old: PlanTopic, new: PlanTopic) -> list[ActionChange]:
    old_left = list(old.actions)
    new_left = list(new.actions)
    changes: list[ActionChange] = []

    # Pass 1 — exact text matches. Compare their other cells for edits.
    old_by_key: dict[str, list[PlanAction]] = {}
    for a in old_left:
        old_by_key.setdefault(a.key, []).append(a)

    still_new: list[PlanAction] = []
    for a in new_left:
        bucket = old_by_key.get(a.key)
        if bucket:
            counterpart = bucket.pop(0)
            edits = _cell_edits(counterpart, a)
            if edits:
                changes.append(ActionChange("edited", old=counterpart,
                                            new=a, edits=edits))
        else:
            still_new.append(a)
    still_old = [a for bucket in old_by_key.values() for a in bucket]

    # Pass 2 — rewordings. Greedy best-match above the ratio, each old action
    # consumed at most once.
    for a in list(still_new):
        best, ratio = _closest(a, still_old)
        if best is not None and ratio >= RENAME_RATIO:
            still_old.remove(best)
            still_new.remove(a)
            changes.append(ActionChange("reworded", old=best, new=a,
                                        edits=_cell_edits(best, a)))

    changes.extend(ActionChange("added", new=a) for a in still_new)
    changes.extend(ActionChange("removed", old=a) for a in still_old)
    return changes


def _closest(action: PlanAction,
             pool: list[PlanAction]) -> tuple[PlanAction | None, float]:
    best: PlanAction | None = None
    best_ratio = 0.0
    for candidate in pool:
        ratio = difflib.SequenceMatcher(
            None, candidate.key, action.key).ratio()
        if ratio > best_ratio:
            best, best_ratio = candidate, ratio
    return best, best_ratio


def _cell_edits(old: PlanAction, new: PlanAction) -> list[CellEdit]:
    old_cells, new_cells = old.cells(), new.cells()
    return [CellEdit(name, old_cells[name], new_cells[name])
            for name in COMPARED_CELLS
            if _squash(old_cells[name]) != _squash(new_cells[name])]


def _squash(text: str) -> str:
    return " ".join((text or "").split())


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_markdown(diff: PlanDiff, rationale: str = "") -> str:
    """The change file that ships alongside every respin."""
    old, new = diff.old, diff.new
    out: list[str] = []
    out.append(f"# Test plan changes — {new.path.name}")
    out.append("")
    out.append(f"Comparing **{old.path.name}** → **{new.path.name}**.")
    out.append("")
    if rationale:
        out.append(rationale.strip())
        out.append("")

    out.append("| | Previous | This version |")
    out.append("|---|---|---|")
    out.append(f"| Topics | {len(old.topics)} | {len(new.topics)} |")
    out.append(f"| Action rows | {old.action_count} | {new.action_count} |")
    out.append("")

    if diff.is_empty:
        out.append("**No changes.** Every topic and action row is identical.")
        return "\n".join(out) + "\n"

    edited = sum(1 for t in diff.changed for a in t.actions
                 if a.kind in ("edited", "reworded"))
    out.append(f"**{len(diff.added)} topics added, "
               f"{len(diff.removed)} removed, "
               f"{len(diff.changed)} changed** "
               f"({edited} action rows edited or reworded).")
    out.append("")

    if diff.added:
        out.append("## Topics added")
        out.append("")
        for t in diff.added:
            out.append(f"- **{t.key}** — {t.label}  \n  "
                       f"_{t.section}_ · {len(t.actions)} action rows")
        out.append("")

    if diff.removed:
        out.append("## Topics removed")
        out.append("")
        for t in diff.removed:
            out.append(f"- **{t.key}** — {t.label}  \n  "
                       f"_{t.section}_ · {len(t.actions)} action rows")
        out.append("")

    if diff.changed:
        out.append("## Topics changed")
        out.append("")
        for t in diff.changed:
            counts = ", ".join(f"{n} {k}" for k, n in sorted(t.counts.items()))
            out.append(f"### {t.key} — {t.label}")
            out.append("")
            out.append(f"_{t.section}_ · {counts}")
            out.append("")
            out.extend(_render_actions(t))
            out.append("")

    return "\n".join(out) + "\n"


def _render_actions(topic: TopicChange) -> list[str]:
    out: list[str] = []
    for change in topic.actions:
        if change.kind == "added":
            out.append(f"- **+** {_one_line(change.new.action)}")
        elif change.kind == "removed":
            out.append(f"- **−** {_one_line(change.old.action)}")
        elif change.kind == "reworded":
            out.append(f"- **~** {_one_line(change.old.action)}")
            out.append(f"  → {_one_line(change.new.action)}")
            out.extend(_render_edits(change))
        else:  # edited
            out.append(f"- **·** {_one_line(change.new.action)}")
            out.extend(_render_edits(change))
    return out


def _render_edits(change: ActionChange) -> list[str]:
    out = []
    for edit in change.edits:
        out.append(f"    - _{edit.field}_: {_one_line(edit.old) or '(empty)'}")
        out.append(f"      → {_one_line(edit.new) or '(empty)'}")
    return out


def _one_line(text: str, limit: int = 240) -> str:
    squashed = " ".join((text or "").split())
    return squashed if len(squashed) <= limit else squashed[:limit - 1] + "…"


def write_markdown(diff: PlanDiff, output_path: Path | str,
                   rationale: str = "") -> Path:
    output_path = Path(output_path)
    output_path.write_text(render_markdown(diff, rationale), encoding="utf-8")
    return output_path


def default_output_for(new_path: Path | str) -> Path:
    new_path = Path(new_path)
    return new_path.with_name(f"{new_path.stem}_CHANGES.md")

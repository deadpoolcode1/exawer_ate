"""Command cross-check: every CLI/show command emitted in a plan must trace
back to a source doc, a generic verb, or our curated list — anything else is
an invented-command alert.

Guard introduced for Ron/Yossi (2026-06-24): Yossi flagged `show mpls lsp` as
"an AI hallucination". The detector buckets emitted commands by provenance so
the curated-but-undocumented ones (like `show mpls lsp`) and any genuinely
invented ones surface for review instead of hiding in the plan.
"""
from __future__ import annotations

from ate.planner import cli_crosscheck as cc


class _Row:
    """Minimal PlanRow stand-in: only the fields the detector reads."""
    def __init__(self, flow_id: str, action_steps: str, expectation: str = ""):
        self.flow_id = flow_id
        self.action_steps = action_steps
        self.expectation = expectation
        self.sub_category = ""
        self.category = "x"


class _Plan:
    def __init__(self, rows):
        self.rows = rows


def test_command_head_normalisation():
    assert cc.command_head("show evpn evi 10") == "show evpn evi"
    assert cc.command_head("show mpls lsp") == "show mpls lsp"
    assert cc.command_head("clear evpn mac <m>") == "clear evpn mac"
    assert cc.command_head("no shutdown") == "shutdown"      # leading no/ do dropped
    assert cc.command_head("`show foo`".strip("`")) == "show foo"


def test_curated_vocabulary_loads_without_removed_mpls_commands():
    curated = cc.curated_command_heads()
    assert curated, "curated vocabulary should not be empty"
    # Standard EVPN monitors stay curated.
    assert "show evpn evi" in curated
    # The MPLS-transport commands were removed from the curated source on
    # 2026-06-25 (Yossi: not in the EVPN SFS), so they no longer count as
    # grounded and will be scrubbed from output.
    assert "show mpls lsp" not in curated
    assert "show mpls forwarding-table" not in curated


def test_buckets_invented_vs_curated_vs_generic():
    plan = _Plan([
        _Row("FLOW-130", "Verify with `show mpls lsp` and `show evpn evi 10`."),
        _Row("FLOW-001", "Run `show running-config`, then `show frobnicate widgets`."),
    ])
    res = cc.reconcile_commands(plan, cli_commands=[], requirements=[])

    # Truly invented -> unknown (the hard alert).
    assert "show frobnicate widgets" in res.unknown
    # show mpls lsp was declassified -> now ungrounded (unknown), to be scrubbed.
    assert "show mpls lsp" in res.unknown
    # A documented base grounds its argument variant via prefix match.
    assert "show evpn evi" in res.curated
    # Universal verb -> generic.
    assert "show running-config" in res.generic
    assert res.has_unknown and res.has_review


def test_bare_verb_is_noise_not_a_command():
    plan = _Plan([_Row("FLOW-001", "Inspect the `show` output and `clear` it.")])
    res = cc.reconcile_commands(plan, cli_commands=[], requirements=[])
    assert "show" not in res.unknown
    assert res.total == 0


def test_prefix_match_grounds_argument_variants():
    # `show evpn evi` is curated; a sub-qualified form must inherit its bucket,
    # not be reported as invented.
    plan = _Plan([_Row("FLOW-010",
                       "Check `show evpn evi evi-1` and `show evpn evi detail`.")])
    res = cc.reconcile_commands(plan, cli_commands=[], requirements=[])
    assert not res.unknown


def test_format_warning_empty_when_all_grounded():
    plan = _Plan([_Row("FLOW-001", "Run `show running-config`.")])
    res = cc.reconcile_commands(plan, cli_commands=[], requirements=[])
    assert cc.format_warning(res) == ""


def test_scrub_removes_ungrounded_keeps_grounded():
    plan = _Plan([
        _Row("FLOW-001",
             "Verify: confirm state via `show frobnicate widgets`, then run "
             "`show running-config` and `show evpn evi`."),
    ])
    removed = cc.scrub_ungrounded(plan, cli_commands=[], requirements=[])
    text = plan.rows[0].action_steps
    # Invented command gone; grounded + curated kept.
    assert "frobnicate" not in text
    assert "show running-config" in text
    assert "show evpn evi" in text
    assert "show frobnicate widgets" in removed
    # And nothing ungrounded survives a follow-up check.
    res = cc.reconcile_commands(plan, cli_commands=[], requirements=[])
    assert not res.unknown


def test_scrub_recapitalises_clause_after_removing_subject():
    # Command was the sentence subject — removing it must not leave a lowercase
    # dangling clause.
    plan = _Plan([_Row("FLOW-130", "Verify:\n 1. `show frobnicate table` shows a "
                                   "POP operation for the loopback FEC.")])
    cc.scrub_ungrounded(plan, cli_commands=[], requirements=[])
    text = plan.rows[0].action_steps
    assert "frobnicate" not in text
    assert "1. Shows a POP operation" in text  # re-capitalised, reads cleanly


def test_scrub_noop_when_all_grounded():
    plan = _Plan([_Row("FLOW-001", "Run `show running-config` and `show evpn evi`.")])
    before = plan.rows[0].action_steps
    removed = cc.scrub_ungrounded(plan, cli_commands=[], requirements=[])
    assert removed == {}
    assert plan.rows[0].action_steps == before

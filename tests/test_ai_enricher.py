"""AI enricher tests — cache hit, fallback to rule-based when no key, mocked API."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from ate.planner.ai_enricher import (
    CACHE_PATH,
    _row_key,
    enrich_plan,
    load_cache,
    save_cache,
)
from ate.planner.generator import generate_plan

ROOT = Path(__file__).resolve().parents[1]
EVPN_SPEC = ROOT / "tests/corpus/tier_a/EVPN System Specification 1.00.docx"


def test_cache_loads_committed_baked_entries() -> None:
    """The committed cache must have the AI-enriched samples baked by build_ai_cache.py."""
    assert CACHE_PATH.exists(), "ai_cache.json must be committed"
    cache = load_cache()
    assert len(cache) >= 50, f"baked cache too small: {len(cache)}"
    # Spot check — at least one entry references the enriched EVPN content
    sample_text = json.dumps(cache)
    assert "vlan-based" in sample_text or "EVPN" in sample_text


def test_enrich_uses_cache_without_api_key(monkeypatch) -> None:
    """When no API key set, enrich_plan applies cache hits and falls back to rule-based for any miss."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    plan = generate_plan(EVPN_SPEC, use_ai=False)  # baseline rule-based
    enriched, stats = enrich_plan(plan, use_api=False)
    # use_api=False → no API calls; only cache hits + (possibly) rule-based
    assert stats["api_call"] == 0
    assert stats["cache_hit"] > 0, "expected cache hits from baked entries"
    # cache_hit + rule_based must equal total rows (every row is one or the other)
    assert stats["cache_hit"] + stats["rule_based"] == len(plan.rows)
    assert len(enriched.rows) == len(plan.rows)


def test_enrich_swaps_action_steps_for_cached_rows() -> None:
    """Rows with cache hits get their action_steps replaced; uncached stay."""
    plan = generate_plan(EVPN_SPEC, use_ai=False)
    enriched, _ = enrich_plan(plan, use_api=False)
    # Find an EVPNS-REQ#30 CLI configuration row and verify it changed
    for orig, new in zip(plan.rows, enriched.rows, strict=True):
        if orig.sfs_requirement_id == "EVPNS-REQ#30" and orig.category == "CLI configuration":
            # If this row is in the baked cache, action should differ
            if "service-type vlan-based" in new.action_steps:
                assert new.action_steps != orig.action_steps
                return
    # If we didn't return, the enrichment didn't swap anything — that's a bug
    raise AssertionError("expected at least one EVPNS-REQ#30 row to be enriched from cache")


def test_enrich_falls_back_when_api_key_missing_and_no_cache(monkeypatch, tmp_path) -> None:
    """Empty cache + no API key → all rows stay rule-based."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    empty_cache = tmp_path / "empty_cache.json"
    empty_cache.write_text("{}")
    plan = generate_plan(EVPN_SPEC, use_ai=False)
    enriched, stats = enrich_plan(plan, use_api=False, cache_path=empty_cache)
    assert stats["cache_hit"] == 0
    assert stats["api_call"] == 0
    assert stats["rule_based"] == len(plan.rows)
    # Rows are unchanged
    for orig, new in zip(plan.rows, enriched.rows, strict=True):
        assert orig.action_steps == new.action_steps
        assert orig.expectation == new.expectation


def test_enrich_calls_api_with_key_and_writes_cache(monkeypatch, tmp_path) -> None:
    """With API key + use_api=True, mocked API fills cache for any miss."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-for-test")
    cache_path = tmp_path / "test_cache.json"
    cache_path.write_text("{}")

    plan = generate_plan(EVPN_SPEC, use_ai=False)
    # Trim plan to one requirement to keep the test fast
    plan.rows = [r for r in plan.rows if r.sfs_requirement_id == "EVPNS-REQ#10"]

    fake_response = MagicMock()
    fake_message = MagicMock()
    fake_message.text = json.dumps({
        "action_steps": "AI-generated specific action",
        "expectation": "AI-generated specific expectation",
    })
    fake_response.content = [fake_message]

    with patch("anthropic.Anthropic") as mock_class:
        client = MagicMock()
        client.messages.create.return_value = fake_response
        mock_class.return_value = client

        enriched, stats = enrich_plan(plan, use_api=True, cache_path=cache_path)

    assert stats["api_call"] == len(plan.rows)
    assert stats["rule_based"] == 0
    # Cache file written with new entries
    new_cache = json.loads(cache_path.read_text())
    assert len(new_cache) == len(plan.rows)
    # Rows were updated
    for r in enriched.rows:
        assert "AI-generated" in r.action_steps


def test_enrich_falls_back_on_api_failure(monkeypatch, tmp_path) -> None:
    """When the API call raises, the row stays rule-based — no crash."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    cache_path = tmp_path / "test_cache.json"
    cache_path.write_text("{}")
    plan = generate_plan(EVPN_SPEC, use_ai=False)
    plan.rows = plan.rows[:3]  # keep small

    with patch("anthropic.Anthropic") as mock_class:
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("simulated API error")
        mock_class.return_value = client

        enriched, stats = enrich_plan(plan, use_api=True, cache_path=cache_path)

    # All rows fall back to rule-based; no exceptions propagated
    assert stats["rule_based"] == len(plan.rows)
    assert stats["api_call"] == 0
    for orig, new in zip(plan.rows, enriched.rows, strict=True):
        assert orig.action_steps == new.action_steps


def test_save_load_cache_roundtrip(tmp_path) -> None:
    cache = {"abc123": {"req_id": "X", "category": "Y", "action_steps": "a", "expectation": "e"}}
    p = tmp_path / "cache.json"
    save_cache(cache, p)
    loaded = load_cache(p)
    assert loaded == cache


def test_row_key_is_stable(monkeypatch) -> None:
    """Same (req, row, sub_index) → same key, regardless of process restart."""
    from ate.planner.model import PlanRow, Requirement
    req = Requirement(req_id="X", title="t", description="d", tags=["CONFIG"])
    row = PlanRow(category="CLI configuration", action_steps="a", expectation="e",
                  sfs_requirement_id="X")
    k1 = _row_key(req, row, 0)
    k2 = _row_key(req, row, 0)
    assert k1 == k2
    k3 = _row_key(req, row, 1)
    assert k1 != k3

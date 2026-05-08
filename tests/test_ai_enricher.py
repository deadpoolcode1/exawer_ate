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
    """The committed cache file must exist and parse as a JSON dict.

    The M1 respin moved cache key salt v1 → v2 and introduced incremental
    saves (each successful API call writes to disk). Cache size is now a
    function of how many AI bakes have run since the salt bump rather than
    a hand-curated 382-entry seed, so we no longer assert a minimum size —
    just the structural contract `enrich_plan` depends on.
    """
    assert CACHE_PATH.exists(), "ai_cache.json must be committed"
    cache = load_cache()
    assert isinstance(cache, dict), f"cache must be a dict, got {type(cache).__name__}"


def test_enrich_uses_cache_without_api_key(monkeypatch, tmp_path) -> None:
    """With a synthetic cache file containing one matching v2-keyed entry,
    enrich_plan applies the hit and falls back to rule-based for misses.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    plan = generate_plan(EVPN_SPEC, use_ai=False)
    # Synthesize one cache entry keyed against the first row so the test
    # is independent of the production cache's salt/state.
    from ate.planner.ai_enricher import _row_key
    target = plan.rows[0]
    target_req = next(r for r in plan.requirements
                      if r.req_id == target.sfs_requirement_id)
    key = _row_key(target_req, target, 0)
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({key: {
        "req_id": target_req.req_id,
        "category": target.category,
        "sub_category": target.sub_category,
        "action_steps": "synthetic cached action",
        "expectation": "synthetic cached expectation",
        "equipment": "DUT only",
        "backend": "test",
    }}))

    enriched, stats = enrich_plan(plan, use_api=False, cache_path=cache_path)
    assert stats["api_call"] == 0
    assert stats["cache_hit"] >= 1, "synthetic cache entry must hit"
    assert stats["cache_hit"] + stats["rule_based"] == len(plan.rows)
    assert len(enriched.rows) == len(plan.rows)


def test_enrich_swaps_action_steps_for_cached_rows(tmp_path) -> None:
    """A row whose key is present in the cache must get its action_steps
    replaced with the cached content; a row whose key isn't cached must
    keep its rule-based content unchanged."""
    plan = generate_plan(EVPN_SPEC, use_ai=False)
    from ate.planner.ai_enricher import _row_key
    cache_path = tmp_path / "cache.json"

    # Cache only the first row.
    target = plan.rows[0]
    target_req = next(r for r in plan.requirements
                      if r.req_id == target.sfs_requirement_id)
    key = _row_key(target_req, target, 0)
    cache_path.write_text(json.dumps({key: {
        "req_id": target_req.req_id,
        "category": target.category,
        "sub_category": target.sub_category,
        "action_steps": "REPLACED ACTION",
        "expectation": "REPLACED EXPECTATION",
    }}))

    enriched, _ = enrich_plan(plan, use_api=False, cache_path=cache_path)
    assert enriched.rows[0].action_steps == "REPLACED ACTION"
    assert enriched.rows[0].expectation == "REPLACED EXPECTATION"
    # A later row with a different key keeps its rule-based content
    assert enriched.rows[-1].action_steps == plan.rows[-1].action_steps


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
    """With API key + use_api=True + backend='sdk', mocked SDK fills cache for any miss."""
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

        enriched, stats = enrich_plan(plan, use_api=True, cache_path=cache_path,
                                      backend="sdk")

    assert stats["api_call"] == len(plan.rows)
    assert stats["rule_based"] == 0
    # Cache file written with new entries
    new_cache = json.loads(cache_path.read_text())
    assert len(new_cache) == len(plan.rows)
    # Rows were updated
    for r in enriched.rows:
        assert "AI-generated" in r.action_steps


def test_enrich_falls_back_on_api_failure(monkeypatch, tmp_path) -> None:
    """When the SDK call raises, the row stays rule-based — no crash."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    cache_path = tmp_path / "test_cache.json"
    cache_path.write_text("{}")
    plan = generate_plan(EVPN_SPEC, use_ai=False)
    plan.rows = plan.rows[:3]  # keep small

    with patch("anthropic.Anthropic") as mock_class:
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("simulated API error")
        mock_class.return_value = client

        enriched, stats = enrich_plan(plan, use_api=True, cache_path=cache_path,
                                      backend="sdk")

    # All rows fall back to rule-based; no exceptions propagated
    assert stats["rule_based"] == len(plan.rows)
    assert stats["api_call"] == 0
    for orig, new in zip(plan.rows, enriched.rows, strict=True):
        assert orig.action_steps == new.action_steps


# ─── CLI backend (default) ──────────────────────────────────────────────────

def test_default_backend_is_cli(monkeypatch) -> None:
    """`enrich_plan` must default to the CLI backend so the project works
    on any machine with `claude` installed — no API key required."""
    from ate.planner import ai_enricher
    monkeypatch.delenv("ATE_AI_BACKEND", raising=False)
    assert ai_enricher._resolve_backend(None) == "cli"


def test_env_var_selects_backend(monkeypatch) -> None:
    from ate.planner import ai_enricher
    monkeypatch.setenv("ATE_AI_BACKEND", "sdk")
    assert ai_enricher._resolve_backend(None) == "sdk"
    monkeypatch.setenv("ATE_AI_BACKEND", "CLI")  # case-insensitive
    assert ai_enricher._resolve_backend(None) == "cli"


def test_unknown_backend_raises() -> None:
    import pytest

    from ate.planner import ai_enricher
    with pytest.raises(ValueError, match="unknown AI backend"):
        ai_enricher._resolve_backend("openai")


def test_enrich_uses_cli_backend_by_subprocess(monkeypatch, tmp_path) -> None:
    """With backend='cli' and use_api=True, the enricher shells out to `claude`
    and parses the JSON envelope's `result` field as the model's reply."""
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("{}")
    plan = generate_plan(EVPN_SPEC, use_ai=False)
    plan.rows = [r for r in plan.rows if r.sfs_requirement_id == "EVPNS-REQ#10"]

    # `claude -p --output-format json` returns a result envelope; the inner
    # `result` field carries the model's text — which itself must be JSON
    # because we pass --json-schema.
    fake_envelope = json.dumps({
        "type": "result",
        "result": json.dumps({
            "action_steps": "CLI-routed action",
            "expectation": "CLI-routed expectation",
        }),
    })
    fake_proc = MagicMock(returncode=0, stdout=fake_envelope, stderr="")

    with patch("ate.planner.ai_enricher.shutil.which", return_value="/usr/bin/claude"), \
         patch("ate.planner.ai_enricher.subprocess.run", return_value=fake_proc) as run:
        enriched, stats = enrich_plan(plan, use_api=True, cache_path=cache_path,
                                      backend="cli")

    assert stats["api_call"] == len(plan.rows)
    # subprocess invoked with the right flags: -p, model pin, json output,
    # no slash commands, no session persistence. (--bare and --json-schema
    # are intentionally NOT used — see _call_via_cli docstring.)
    args = run.call_args.args[0]
    assert args[0] == "claude" and "-p" in args
    assert "--model" in args
    assert "--output-format" in args and "json" in args
    assert "--disable-slash-commands" in args
    assert "--no-session-persistence" in args
    # Cache wrote backend marker
    new_cache = json.loads(cache_path.read_text())
    assert all(v.get("backend") == "cli" for v in new_cache.values())
    for r in enriched.rows:
        assert "CLI-routed" in r.action_steps


def test_cli_backend_falls_back_when_claude_missing(monkeypatch, tmp_path) -> None:
    """If the `claude` CLI is not on PATH, use_api=None must auto-detect
    and skip the live call cleanly — no subprocess invocation, no crash."""
    cache_path = tmp_path / "empty.json"
    cache_path.write_text("{}")
    plan = generate_plan(EVPN_SPEC, use_ai=False)
    plan.rows = plan.rows[:3]

    with patch("ate.planner.ai_enricher.shutil.which", return_value=None), \
         patch("ate.planner.ai_enricher.subprocess.run") as run:
        enriched, stats = enrich_plan(plan, use_api=None, cache_path=cache_path,
                                      backend="cli")

    run.assert_not_called()
    assert stats["api_call"] == 0
    assert stats["rule_based"] == len(plan.rows)


def test_use_api_none_never_calls_backend_even_when_available(monkeypatch, tmp_path) -> None:
    """Regression: `use_api=None` must mean cache-only. Auto-detecting the
    backend's availability and silently calling it would pollute the
    production cache from any test running `generate_plan(file)` without
    `use_ai=False`. Caller must pass `use_api=True` to opt into live calls."""
    cache_path = tmp_path / "guard.json"
    cache_path.write_text("{}")
    plan = generate_plan(EVPN_SPEC, use_ai=False)
    plan.rows = plan.rows[:5]

    # Both backends "available" — but caller didn't opt in.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-should-not-be-used")
    with patch("ate.planner.ai_enricher.shutil.which", return_value="/usr/bin/claude"), \
         patch("ate.planner.ai_enricher.subprocess.run") as run, \
         patch("anthropic.Anthropic") as sdk:
        for backend in ("cli", "sdk"):
            enriched, stats = enrich_plan(plan, use_api=None,
                                          cache_path=cache_path, backend=backend)
            assert stats["api_call"] == 0, (
                f"backend {backend} called API despite use_api=None"
            )
        run.assert_not_called()
        sdk.assert_not_called()
    # Cache file still empty
    assert json.loads(cache_path.read_text()) == {}


def test_cli_backend_handles_nonzero_exit(monkeypatch, tmp_path) -> None:
    """Non-zero exit from `claude` → row falls back to rule-based, no crash."""
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("{}")
    plan = generate_plan(EVPN_SPEC, use_ai=False)
    plan.rows = plan.rows[:2]
    bad_proc = MagicMock(returncode=1, stdout="", stderr="boom")
    with patch("ate.planner.ai_enricher.shutil.which", return_value="/usr/bin/claude"), \
         patch("ate.planner.ai_enricher.subprocess.run", return_value=bad_proc):
        _, stats = enrich_plan(plan, use_api=True, cache_path=cache_path,
                               backend="cli")
    assert stats["api_call"] == 0
    assert stats["rule_based"] == len(plan.rows)


def test_cli_backend_handles_malformed_json(monkeypatch, tmp_path) -> None:
    """If `claude` returns garbage stdout, the row falls back gracefully."""
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("{}")
    plan = generate_plan(EVPN_SPEC, use_ai=False)
    plan.rows = plan.rows[:2]
    bad_proc = MagicMock(returncode=0, stdout="not-json", stderr="")
    with patch("ate.planner.ai_enricher.shutil.which", return_value="/usr/bin/claude"), \
         patch("ate.planner.ai_enricher.subprocess.run", return_value=bad_proc):
        _, stats = enrich_plan(plan, use_api=True, cache_path=cache_path,
                               backend="cli")
    assert stats["api_call"] == 0
    assert stats["rule_based"] == len(plan.rows)


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

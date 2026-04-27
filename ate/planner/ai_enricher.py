"""AI enricher — replaces template-stamped action steps with feature-specific
content using Claude (Anthropic API).

Lookup order per row:
  1. **Cache** (`ate/planner/ai_cache.json`) — committed, deterministic, no key needed.
  2. **API call** to Claude — only if `ANTHROPIC_API_KEY` env is set.
  3. **Rule-based original** — graceful fallback; the row stays as the
     template-driven content.

The cache is the artifact a user sees in the deliverable. We commit
high-quality enriched samples for representative requirements so the
xlsx demonstrates AI quality even without an API key. To regenerate or
extend the cache:

    ANTHROPIC_API_KEY=... ate plan <file> -o plan.xlsx --ai

Per SOW PQ4476E §3 "AI Test Plan Generation": Claude API integration is
explicitly listed as the AI provider.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from ate.planner.model import Plan, PlanRow, Requirement

CACHE_PATH = Path(__file__).parent / "ai_cache.json"
MODEL = "claude-sonnet-4-5"  # Sonnet 4.5 — current production model
MAX_TOKENS = 600
PROMPT_TEMPLATE = """You are a senior network test engineer writing an Exaware EVPN test plan.

For ONE row of the test plan, produce a concrete, feature-specific
action step and expectation. Reference the actual requirement, the spec
section, and any CLI commands or RFC chapters mentioned. Do NOT use
generic phrases like "verify happy-path operation" or "Configure feature
per spec". Use the specific commands, VLAN-IDs, ESI types, route fields
that the requirement actually mentions.

Requirement:
  ID: {req_id}
  Section: {section}
  Title: {title}
  Tags: {tags}
  RFC refs: {rfc_refs}
  MUST statements: {must_statements}
  CLI example from spec (truncated):
{cli_block}

Description:
{description}

Test category: {category}

Current rule-based row (replace with something specific to this requirement):
  Action steps: {current_action}
  Expectation: {current_expectation}

Reply ONLY with valid JSON in this exact shape, no surrounding text:
{{"action_steps": "...", "expectation": "..."}}

Action steps: 1-2 sentences, includes specific CLI commands or values from
the spec when applicable. Expectation: 1 sentence, measurable, tied to the
requirement's MUST statement when one exists.
"""


def _row_key(req: Requirement, row: PlanRow, sub_index: int) -> str:
    """Stable cache key for a row. Independent of API model so cache survives
    model upgrades; if you need to bust cache, change the salt."""
    salt = "v1"
    h = hashlib.sha256()
    h.update(salt.encode())
    h.update(req.req_id.encode())
    h.update(row.category.encode())
    h.update(str(sub_index).encode())
    h.update((row.action_steps + "|" + row.expectation).encode())
    return h.hexdigest()[:16]


def load_cache(path: Path = CACHE_PATH) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(cache: dict[str, dict], path: Path = CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8")


def _build_prompt(req: Requirement, row: PlanRow) -> str:
    cli_block = ""
    if req.code_blocks:
        snippet = req.code_blocks[0][:400]
        cli_block = f"  ```\n{snippet}\n  ```"
    return PROMPT_TEMPLATE.format(
        req_id=req.req_id,
        section=req.section_number or "(unnumbered)",
        title=req.title,
        tags=", ".join(req.tags),
        rfc_refs=", ".join(req.rfc_refs) or "(none)",
        must_statements="\n  - ".join([""] + req.must_statements[:3]) or " (none)",
        cli_block=cli_block or "  (no CLI example in section)",
        description=(req.description[:600] + "…") if len(req.description) > 600
                    else req.description,
        category=row.category,
        current_action=row.action_steps,
        current_expectation=row.expectation,
    )


def _call_claude(prompt: str, api_key: str) -> tuple[str, str] | None:
    """Returns (action, expectation) or None on any failure."""
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip() if resp.content else ""
        # Trim potential markdown fences
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
        data = json.loads(text)
        return data["action_steps"], data["expectation"]
    except Exception:
        return None


def enrich_plan(plan: Plan, *,
                use_api: bool | None = None,
                cache_path: Path = CACHE_PATH,
                ) -> tuple[Plan, dict[str, int]]:
    """Replace each row's action+expectation with AI-enriched content
    when available (cache, then API). Returns (plan, stats).

    stats keys: {"cache_hit", "api_call", "rule_based"}
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if use_api is None:
        use_api = bool(api_key)

    cache = load_cache(cache_path)
    cache_dirty = False
    stats = {"cache_hit": 0, "api_call": 0, "rule_based": 0}

    # Index requirements by id for lookup
    req_by_id = {r.req_id: r for r in plan.requirements}

    # Track sub-index per (req, category)
    seen_count: dict[tuple[str, str], int] = {}

    enriched_rows: list[PlanRow] = []
    for row in plan.rows:
        key_pair = (row.sfs_requirement_id, row.category)
        sub_index = seen_count.get(key_pair, 0)
        seen_count[key_pair] = sub_index + 1
        req = req_by_id.get(row.sfs_requirement_id)
        if req is None:
            stats["rule_based"] += 1
            enriched_rows.append(row)
            continue

        cache_key = _row_key(req, row, sub_index)
        if cache_key in cache:
            data = cache[cache_key]
            enriched_rows.append(row.model_copy(update={
                "action_steps": data["action_steps"],
                "expectation": data["expectation"],
            }))
            stats["cache_hit"] += 1
            continue

        if use_api and api_key:
            prompt = _build_prompt(req, row)
            result = _call_claude(prompt, api_key)
            if result is not None:
                action, expectation = result
                cache[cache_key] = {
                    "req_id": req.req_id,
                    "category": row.category,
                    "action_steps": action,
                    "expectation": expectation,
                }
                cache_dirty = True
                enriched_rows.append(row.model_copy(update={
                    "action_steps": action,
                    "expectation": expectation,
                }))
                stats["api_call"] += 1
                continue

        # Fallback: keep rule-based content
        stats["rule_based"] += 1
        enriched_rows.append(row)

    if cache_dirty:
        save_cache(cache, cache_path)

    enriched_plan = plan.model_copy(update={"rows": enriched_rows})
    return enriched_plan, stats

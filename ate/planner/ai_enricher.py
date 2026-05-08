"""AI enricher — replaces template-stamped action steps with feature-specific
content using Claude.

Lookup order per row:
  1. **Cache** (`ate/planner/ai_cache.json`) — committed, deterministic, no key needed.
  2. **AI backend** — only if the row is enabled for live enrichment:
     - `cli` (default): shell out to `claude -p` using the user's local
       Claude Code authentication. No API key needed; uses the Pro/Max
       subscription that already drives `claude` on this machine.
     - `sdk`: Anthropic Python SDK; requires `ANTHROPIC_API_KEY` and bills
       to the console.anthropic.com account.
  3. **Rule-based original** — graceful fallback; the row stays as the
     template-driven content.

The cache is the artifact a user sees in the deliverable. We commit
high-quality enriched samples for representative requirements so the
xlsx demonstrates AI quality even without a backend available. To
regenerate or extend the cache:

    ate plan <file> -o plan.xlsx --ai                       # CLI backend (default)
    ate plan <file> -o plan.xlsx --ai --ai-backend sdk      # SDK backend
    ATE_AI_BACKEND=sdk ANTHROPIC_API_KEY=... ate plan ...   # via env

M1 review respin (Yossi feedback): the prompt now demands structured
output (Setup/Action/Verify + Pass/Fail-on + Test Equipment), gets
related CLI commands and RFC text injected as evidence, and bumps the
cache-key salt to v2 so old generic rows don't satisfy the new shape.

Per SOW PQ4476E §3 "AI Test Plan Generation": Claude is the AI provider;
both transports above route to Claude.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from ate.planner.cli_extractor import CliCommand
from ate.planner.model import Plan, PlanRow, Requirement

# Retry policy for the CLI backend. Pro/Max subscriptions enforce a
# 5-hour rolling window; when the limit hits, `claude -p` fails for
# every call until the next window opens. The user wants the bake to
# pause and resume rather than mark the affected rows as rule-based —
# so we retry forever, but pause for a meaningful interval between
# attempts to give the window a chance to recover.
RETRY_BACKOFF_INITIAL_S = 60
RETRY_BACKOFF_MAX_S = 600  # 10 min
RETRY_FOREVER = True  # set False in tests to bound retries

CACHE_PATH = Path(__file__).parent / "ai_cache.json"
MODEL = "claude-sonnet-4-5"  # Sonnet 4.5 — current production model
MAX_TOKENS = 1200  # raised for the structured Setup/Action/Verify output
PROMPT_TEMPLATE = """You are a senior network test engineer writing one row of an Exaware EVPN test plan that QA will execute literally — no improvisation, no "verify happy-path" hand-waving.

Output ONE row tuned to the specific requirement and category below. The row must close the M1 reviewer's gaps:

  1. Concrete Setup → Action → Verify steps (not generic intentions).
  2. A measurable Pass criterion + a Fail-on criterion in the expectation.
  3. The actual CLI commands, parameters, RFC sections, route types, ESI types, label allocation, etc. that this requirement is about.
  4. Explicit Test Equipment (which rig: DUT only, IXIA, neighbor PE, 3rd-party PE, scale rig).
  5. If the requirement names default values, ranges, or mutex choices — include them in the row.

GROUNDING RULES (zero-tolerance — the reviewer caught violations of these on the previous pass):

  - **Parameter names**: only use parameter names that appear verbatim in the CLI EVIDENCE block below. Do NOT invent sub-parameters from prose descriptions. If the doc says `identifier 0 type0-value | identifier 1 | identifier 4`, the only valid parameter token is `<type0-value>` — do NOT write `<router-id>`, `<discriminator>`, `<algorithm>`, `<method>`, `<es-name>`, `<if>`, `<observed-router-id>` or any other invented name.
  - **RFC section numbers**: only cite section numbers that appear in the "RFC refs" line above. Do NOT extrapolate to sub-sections (e.g. don't write §8.2.2 if only §8.2 is listed; don't write §5.1.1 if only §5 is listed).
  - **Formatting**: interface names use a space separator: write `agg-eth 0`, NOT `agg-eth0`; write `x-eth 0/0/1`, NOT `x-eth0/0/1`.
  - **No invented commands**: every backtick-quoted command should either appear in the CLI EVIDENCE or be a well-known generic verb (`show running-config`, `commit`, `configure`, `tcpdump`, etc.). If you need a feature whose CLI isn't documented, describe the action in prose without inventing a command name.
  - **When in doubt, omit**: prefer "configure ESI per the documented type" over "issue `identifier 1 lacp-key <key>`" if you'd be guessing the syntax.

Reply ONLY with valid JSON in this exact shape, no surrounding text:

{{
  "action_steps": "Setup:  <one or two concrete sentences>\\nAction: <specific commands or traffic events, name the parameters>\\nVerify: <named show commands, capture points, or counters>",
  "expectation": "Pass:    <measurable success criterion tied to the MUST or doc default>\\nFail-on: <specific failure observable that means this row is a fail>",
  "equipment": "<one of: 'DUT only', 'DUT + IXIA traffic gen', 'DUT + IXIA + neighbor PE', 'DUT + 3rd-party PE (Cisco/Juniper) + IXIA', 'Two routers + IXIA scale rig', 'DUT + IXIA continuous traffic (≥ 24 h)', 'DUT + power-cycle harness', 'DUT + NETCONF client', 'DUT + ONIE image server', 'DUT + syslog collector', or a longer description if a row needs more>"
}}

REQUIREMENT
  ID: {req_id}
  Source: {source}   ← 'spec' = vendor SFS (CLI/NETCONF/upgrade applicable), 'rfc' = IETF (protocol behaviour only)
  Section: {section}
  Title: {title}
  Tags: {tags}
  RFC refs: {rfc_refs}
  MUST statements (verbatim from source):{must_statements}

REQUIREMENT DESCRIPTION
{description}

CLI EVIDENCE (related commands from EVPN CLI doc — use the exact command/parameter names below)
{cli_evidence}

CATEGORY: {category}
CURRENT RULE-BASED ROW (replace with feature-specific content; do not parrot it)
  Action steps:
{current_action}
  Expectation:
{current_expectation}
  Equipment (rule-based default — keep, sharpen, or override): {current_equipment}
"""


def _row_key(req: Requirement, row: PlanRow, sub_index: int) -> str:
    """Stable cache key for a row.

    Salt v2 marks the M1-respin prompt shape (Setup/Action/Verify +
    Pass/Fail-on + Equipment, with CLI/RFC evidence injection).
    Old v1 entries on disk become misses, which forces re-enrichment.
    """
    salt = "v2"
    h = hashlib.sha256()
    h.update(salt.encode())
    h.update(req.req_id.encode())
    h.update(row.category.encode())
    h.update(row.sub_category.encode())
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


# Map a requirement's tags / title keywords to relevant CLI commands.
# Used by `_cli_evidence` to inject the actual command names + parameter
# specs into the AI prompt — closes Yossi's "feature understanding" gap.
_TAG_TO_CLI_COMMANDS: dict[str, list[str]] = {
    "CONFIG": ["evpn", "auto-discovery", "import-rt", "export-rt"],
    "PACKET": ["advertise-mac", "control-word (evpn)", "unknown-mac-flooding"],
    "HA": ["ethernet-segment", "identifier", "load-balancing-mode",
           "service-carving", "es-waiting-time", "lacp-key", "lacp-system-mac"],
    "PROTOCOL": ["af-l2vpn evpn", "advertise-mac", "import-rt", "export-rt"],
    "SCALE": ["mac-limit", "mac-aging-time"],
    "MONITORING": ["host mac-address-duplication-detection",
                   "mac-address-static (EVPN)"],
}

_TITLE_TO_CLI_COMMANDS: list[tuple[str, list[str]]] = [
    ("service type",         ["evpn", "auto-discovery"]),
    ("vlan-based",           ["evpn", "auto-discovery"]),
    ("vlan-aware",           ["evpn", "auto-discovery"]),
    ("port-based",           ["evpn", "auto-discovery"]),
    ("ethernet segment",     ["ethernet-segment", "identifier",
                              "load-balancing-mode", "service-carving"]),
    ("designated forwarder", ["service-carving", "es-waiting-time"]),
    ("df election",          ["service-carving", "es-waiting-time"]),
    ("mac learning",         ["mac-aging-time", "mac-limit"]),
    ("mac mobility",         ["host mac-address-duplication-detection",
                              "mac-address-static (EVPN)"]),
    ("static mac",           ["mac-address-static (EVPN)"]),
    ("multi-homing",         ["ethernet-segment", "identifier",
                              "load-balancing-mode"]),
    ("auto-discovery",       ["auto-discovery", "import-rt", "export-rt"]),
    ("route target",         ["import-rt", "export-rt"]),
    ("control word",         ["control-word (evpn)"]),
    ("control-word",         ["control-word (evpn)"]),
    ("bgp",                  ["af-l2vpn evpn"]),
    ("bum",                  ["unknown-mac-flooding"]),
    ("flooding",             ["unknown-mac-flooding"]),
    ("router distinguisher", ["evpn"]),
]


def _cli_evidence_text(req: Requirement,
                       cli_index: dict[str, CliCommand] | None) -> str:
    """Render related CLI commands as a compact evidence block for the prompt.

    `cli_index` maps command name → CliCommand. When None, returns "(none)".
    """
    if not cli_index:
        return "(no CLI doc was provided to the generator)"

    # Collect candidate command names from tags + title keywords.
    title_lc = (req.title or "").lower()
    desc_lc = (req.description or "").lower()
    candidates: list[str] = []

    for tag in req.tags:
        for c in _TAG_TO_CLI_COMMANDS.get(tag, []):
            if c not in candidates:
                candidates.append(c)
    for kw, names in _TITLE_TO_CLI_COMMANDS:
        if kw in title_lc or kw in desc_lc:
            for c in names:
                if c not in candidates:
                    candidates.append(c)

    # Resolve to actual CliCommand objects (skip names not in the index)
    resolved = [cli_index[n] for n in candidates if n in cli_index]
    if not resolved:
        return "(no related CLI commands detected for this requirement)"

    parts = []
    for cmd in resolved[:5]:  # cap at 5 to keep prompt small
        params = "; ".join(
            f"{p.name} ({p.value_spec[:60]})" if p.value_spec
            else f"{p.name} (choice)"
            for p in cmd.parameters
        )
        default = (f" — default: {cmd.default_behavior}"
                   if cmd.default_behavior else "")
        parts.append(
            f"  - {cmd.name}: syntax `{'; '.join(cmd.syntax_lines[:2])}` "
            f"in mode `{' / '.join(cmd.mode_path)}`"
            f"{default}"
            f"{('; params: ' + params) if params else ''}"
        )
    return "\n".join(parts)


def _build_prompt(req: Requirement, row: PlanRow,
                  cli_index: dict[str, object] | None = None) -> str:
    return PROMPT_TEMPLATE.format(
        req_id=req.req_id,
        source=req.source,
        section=req.section_number or "(unnumbered)",
        title=req.title,
        tags=", ".join(req.tags),
        rfc_refs=", ".join(req.rfc_refs) or "(none)",
        must_statements="\n  - ".join([""] + req.must_statements[:3]) or " (none)",
        description=(req.description[:600] + "…") if len(req.description) > 600
                    else req.description,
        cli_evidence=_cli_evidence_text(req, cli_index),
        category=row.category,
        current_action="\n".join("    " + ln for ln in row.action_steps.splitlines()),
        current_expectation="\n".join("    " + ln for ln in row.expectation.splitlines()),
        current_equipment=row.equipment or "(unset)",
    )


def _parse_response_json(text: str) -> dict | None:
    """Parse an AI reply into {action_steps, expectation, equipment?} dict.

    Tolerates markdown code-fenced JSON since both the SDK and CLI paths
    occasionally emit ```json ... ``` despite the prompt asking for raw JSON.
    Equipment is optional — older v1 cache entries don't have it.
    """
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        if "action_steps" not in data or "expectation" not in data:
            return None
        return data
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _call_via_sdk(prompt: str, api_key: str) -> dict | None:
    """SDK backend: direct Anthropic API call.

    Requires `ANTHROPIC_API_KEY`. Bills to the console.anthropic.com account
    (separate from any Claude Pro/Max subscription).
    """
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
        return _parse_response_json(text)
    except Exception:
        return None


def _call_via_cli_once(prompt: str, model: str | None = None,
                       timeout: float = 240.0) -> tuple[dict | None, str]:
    """One CLI invocation. Returns (result, reason).

    `result` is the parsed dict on success, None on any failure mode.
    `reason` is an opaque short string describing the failure mode so
    the retry layer can decide whether to retry — "ok", "nopath",
    "timeout", "nonzero", "badjson", "noresult".
    """
    if shutil.which("claude") is None:
        return None, "nopath"
    cmd = [
        "claude", "-p",
        "--model", model or MODEL,
        "--output-format", "json",
        "--disable-slash-commands",
        "--no-session-persistence",
    ]
    try:
        proc = subprocess.run(
            cmd, input=prompt,
            capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except FileNotFoundError:
        return None, "nopath"
    except subprocess.TimeoutExpired:
        return None, "timeout"
    if proc.returncode != 0:
        return None, "nonzero"
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, "badjson"
    inner = envelope.get("result", "") if isinstance(envelope, dict) else ""
    parsed = _parse_response_json(inner)
    return (parsed, "ok") if parsed is not None else (None, "noresult")


def _call_via_cli(prompt: str, model: str | None = None,
                  timeout: float = 240.0,
                  retry_forever: bool = False) -> dict | None:
    """CLI backend: shell out to `claude -p` using local Claude Code auth.

    Pins to MODEL (sonnet 4.5) by default — without --model, Claude Code
    falls through to the user's session default (often Opus 4.7), which
    is ~3× the cost of sonnet for prompts of this size.

    `retry_forever=True` keeps retrying transient failures (timeout /
    non-zero exit / malformed JSON / empty result) with exponential
    backoff capped at RETRY_BACKOFF_MAX_S, indefinitely. This covers the
    Pro/Max 5-hour rate-limit window: instead of marking the row as
    rule-based, we pause until the window recovers. A truly permanent
    failure (claude binary not on PATH) does NOT retry — it returns None
    immediately so callers can fall back.

    Cost note: each call carries Claude Code's full system prompt as
    cache_creation (~20k tokens) on first call, then cache_read (~38k)
    on subsequent — which is why per-row cost is materially higher than
    a direct SDK call. Use the SDK backend for cost-sensitive bulk runs.
    """
    backoff = RETRY_BACKOFF_INITIAL_S
    attempt = 0
    while True:
        attempt += 1
        result, reason = _call_via_cli_once(prompt, model=model, timeout=timeout)
        if reason == "ok":
            if attempt > 1:
                print(f"[ai_enricher] recovered on attempt {attempt}",
                      flush=True)
            return result
        if reason == "nopath":
            # Permanent: claude isn't installed. Caller must fall back.
            return None
        if not retry_forever:
            return None
        # Transient failure (timeout / non-zero exit / malformed / empty).
        # Most likely cause in bulk bakes: rate-limit window saturated.
        print(f"[ai_enricher] attempt {attempt} failed ({reason}); "
              f"sleeping {backoff}s before retry",
              flush=True)
        time.sleep(backoff)
        backoff = min(backoff * 2, RETRY_BACKOFF_MAX_S)


def _resolve_backend(backend: str | None) -> str:
    if backend is None:
        backend = os.environ.get("ATE_AI_BACKEND", "cli")
    backend = backend.lower()
    if backend not in ("cli", "sdk"):
        raise ValueError(
            f"unknown AI backend {backend!r}; expected 'cli' or 'sdk'"
        )
    return backend


def _build_cli_index(cli_doc_path: str | Path | None) -> dict[str, object] | None:
    """If a CLI doc is available, parse it once and build a name → command map
    for the AI prompt's CLI evidence block.
    """
    if cli_doc_path is None:
        return None
    try:
        from ate.planner.cli_extractor import extract_commands  # noqa: PLC0415
        cmds = extract_commands(cli_doc_path)
    except Exception:  # noqa: BLE001 - non-fatal: prompt loses CLI evidence
        return None
    return {c.name: c for c in cmds}


def enrich_plan(plan: Plan, *,
                use_api: bool | None = None,
                cache_path: Path = CACHE_PATH,
                backend: str | None = None,
                cli_doc_path: str | Path | None = None,
                retry_forever: bool = False,
                ) -> tuple[Plan, dict[str, int]]:
    """Replace each row's action+expectation+equipment with AI-enriched
    content when available (cache → backend → rule-based). Returns
    (plan, stats).

    Args:
      backend: "cli" (default; uses local `claude -p` auth) or "sdk"
        (Anthropic Python SDK; requires `ANTHROPIC_API_KEY`). When None,
        reads `ATE_AI_BACKEND` env var, defaulting to "cli".
      use_api: True forces a backend call for any cache miss; False
        disables backend calls; None auto-detects (true if backend is
        available — `claude` on PATH for cli, or `ANTHROPIC_API_KEY` for sdk).
      cli_doc_path: optional path to the EVPN CLI doc; commands from
        this doc are injected into the per-row prompt as CLI evidence.
      retry_forever: when True (CLI backend only), transient failures
        retry indefinitely with exponential backoff. Use this for bulk
        bakes against a Pro/Max subscription — it covers the 5-hour
        rate-limit window by pausing until the window recovers, instead
        of marking the affected rows as rule-based.

    stats keys: {"cache_hit", "api_call", "rule_based"}
    """
    backend = _resolve_backend(backend)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if use_api is None:
        use_api = False  # cache-only by default; --ai opts in

    cache = load_cache(cache_path)
    cache_dirty = False
    stats = {"cache_hit": 0, "api_call": 0, "rule_based": 0}

    cli_index = _build_cli_index(cli_doc_path)

    req_by_id = {r.req_id: r for r in plan.requirements}
    seen_count: dict[tuple[str, str, str], int] = {}

    enriched_rows: list[PlanRow] = []
    for row in plan.rows:
        # Sub-index distinguishes multiple rows with the same (req,
        # category, sub_category). Adding sub_category to the key
        # ensures CLI command rows never collide with each other.
        key_triple = (row.sfs_requirement_id, row.category, row.sub_category)
        sub_index = seen_count.get(key_triple, 0)
        seen_count[key_triple] = sub_index + 1
        req = req_by_id.get(row.sfs_requirement_id)
        if req is None:
            stats["rule_based"] += 1
            enriched_rows.append(row)
            continue

        cache_key = _row_key(req, row, sub_index)
        if cache_key in cache:
            data = cache[cache_key]
            update = {
                "action_steps": data["action_steps"],
                "expectation": data["expectation"],
            }
            if data.get("equipment"):
                update["equipment"] = data["equipment"]
            enriched_rows.append(row.model_copy(update=update))
            stats["cache_hit"] += 1
            continue

        if use_api:
            prompt = _build_prompt(req, row, cli_index=cli_index)
            if backend == "sdk":
                result = _call_via_sdk(prompt, api_key) if api_key else None
            else:  # cli
                result = _call_via_cli(prompt, retry_forever=retry_forever)
            if result is not None:
                action = result["action_steps"]
                expectation = result["expectation"]
                equipment = result.get("equipment", row.equipment)
                cache[cache_key] = {
                    "req_id": req.req_id,
                    "category": row.category,
                    "sub_category": row.sub_category,
                    "action_steps": action,
                    "expectation": expectation,
                    "equipment": equipment,
                    "backend": backend,
                }
                cache_dirty = True
                # Persist after every successful API call so a long bake
                # is interruptible — losing 1 row's work, not the batch.
                save_cache(cache, cache_path)
                enriched_rows.append(row.model_copy(update={
                    "action_steps": action,
                    "expectation": expectation,
                    "equipment": equipment,
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

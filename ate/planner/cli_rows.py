"""Generate concrete CLI Configuration rows from the parsed CLI doc.

Closes the QA review gap: "CLI tests are aimed to test the commands
required by the feature (structure, allowed options, allowed values,
help, persistency)." For each configuration command (lacp-key,
identifier, service-carving, …) we emit a focused row family that names
the actual command, its parameters, ranges, defaults, the documented
value set, and the documented preconditions.

Client review (2026-06-01, "TP — Test Plan Topics") reshaped this
section:
  - **Monitor is Exaware-CLI-exact** — `show configuration` (Exaware has
    no `show running-config`) plus the precise feature `show`
    (`show evpn ethernet-segments`, `show bgp l2vpn evpn neighbors`, …),
    never a generic placeholder. See `_feature_show_for`.
  - **The mode-entry action is concrete** — "At the
    `configuration interface agg-eth ethernet-segment` level, configure
    `identifier 0 <type0-value>`" instead of the old obscure "Enter the
    documented mode".
  - **Pipe (`|`) modifier rows are gone** — they were emitted for every
    command and added no feature signal.
  - **Preconditions are tested one-per-row** with a descriptive-error
    expectation, parsed out of the command's Notes cell (e.g.
    ethernet-segment "only on an L2 interface" / "not when already
    attached to an EVPN instance").
  - **The documented value set is tested** (e.g. ESI `identifier`
    types 0 / 1 / 4) via `_syntax_variants`.
  - **Commands are ordered by command mode**, not alphabetically — all
    `… interface agg-eth ethernet-segment` commands together, then the
    `… l2-services evpn` group, etc. See `cli_command_rows`.
  - **Show commands expand their grammar** into the specific cases
    (`{advertised-routes | received-routes} … [brief | detail]` →
    enumerated invocations) and **clear commands verify the cleared
    state**, not "well-formed output".

Each row carries:
  - category = "CLI configuration"
  - sfs_requirement_id = "CLI:<command_name>" (synthetic anchor)
  - equipment = "DUT only (CLI session via console / SSH)"
  - action_steps = numbered Setup/Action/Verify steps
  - expectation = Pass / Fail-on multi-line

These rows are authored deterministically and are NOT sent through the
AI enricher (ai_enricher skips `source == "cli"`), so the wording stays
precise and Exaware-CLI-aligned.
"""
from __future__ import annotations

import re

from ate.planner.cli_extractor import CliCommand, CliParameter
from ate.planner.cli_inheritance import sub_config_names_for
from ate.planner.equipment import equipment_for_cli_row
from ate.planner.model import PlanRow

EQUIPMENT = equipment_for_cli_row()


# The EVPN CLI doc phrases every Description cell as "To <do X>, use the <cmd>
# command. To restore …, use the no form …". We lift "<do X>" so the banner
# states what the command represents, not just its name (client 2026-06-26:
# "no commands are generic … the doc doesn't understand what each represents").
_PURPOSE_TO_RE = re.compile(r"^\s*To\s+(.+?),\s+use\b", re.IGNORECASE | re.DOTALL)
# Inverse phrasing: "Use the <cmd> command to <do X>." (e.g. mac-address-static).
_PURPOSE_USE_RE = re.compile(
    r"^\s*Use\s+(?:the\s+)?.+?\s+command\s+to\s+(.+)", re.IGNORECASE | re.DOTALL)
# Sentence boundary: a period followed by whitespace OR a capital letter (the
# doc frequently omits the space, e.g. "… interface.If no parameter …").
_SENTENCE_SPLIT_RE = re.compile(r"\.(?=\s|[A-Z])")


def _purpose_phrase(description: str) -> str:
    """Distil a command's doc description into a one-line purpose phrase.

    Returns "" when there is no usable description, so commands without one
    keep a bare-name banner (graceful: the doc simply had nothing to say).
    """
    text = " ".join((description or "").replace("\xa0", " ").split())
    if not text:
        return ""
    m = _PURPOSE_TO_RE.match(text)
    if m:
        phrase = m.group(1).strip()
    else:
        m = _PURPOSE_USE_RE.match(text)
        body = m.group(1).strip() if m else text
        phrase = _SENTENCE_SPLIT_RE.split(body, maxsplit=1)[0].strip()
    phrase = phrase.rstrip(".").strip()
    if phrase:
        phrase = phrase[0].upper() + phrase[1:]
    if len(phrase) > 140:
        phrase = phrase[:139].rstrip() + "…"
    return phrase


def _numbered(items: list[str]) -> str:
    """Render `items` as numbered steps "1. … 2. … 3. …"."""
    return "\n".join(f"  {i}. {s}" for i, s in enumerate(items, 1))


def _scaffold(setup: list[str] | str, action: list[str] | str,
              verify: list[str] | str) -> str:
    """Render Setup / Action / Verify with numbered sub-steps."""
    def _block(label: str, body: list[str] | str) -> str:
        if isinstance(body, list):
            return f"{label}:\n{_numbered(body)}"
        return f"{label}:  {body}"
    return "\n".join([
        _block("Setup", setup),
        _block("Action", action),
        _block("Verify", verify),
    ])


def _expect(pass_: str, fail_on: str = "") -> str:
    if fail_on:
        return f"Pass:    {pass_}\nFail-on: {fail_on}"
    return f"Pass:    {pass_}"


def _mode_path_str(cmd: CliCommand) -> str:
    """Render the configuration mode entry sequence as a CLI path.

    When the command is reachable from more than one parent mode (e.g.
    `ethernet-segment` under both `agg-eth` and `x-eth`), every alternative
    is shown — the differing level is factored as `{agg-eth|x-eth}` so a QA
    engineer sees both modes instead of just the first (client 2026-06-02,
    Eyal Ozeri: "when the command mode is more than one, the second is
    ignored").
    """
    paths = cmd.mode_paths or ([cmd.mode_path] if cmd.mode_path else [])
    if not paths:
        return "configuration"
    if len(paths) == 1:
        return " ".join(paths[0])

    # Longest common prefix across the alternatives.
    minlen = min(len(p) for p in paths)
    k = 0
    while k < minlen and len({p[k] for p in paths}) == 1:
        k += 1
    common = paths[0][:k]
    tails = [p[k:] for p in paths]

    # Factor a single differing level into `{a|b}` when the tails align.
    if len({len(t) for t in tails}) == 1:
        length = len(tails[0])
        diff = [i for i in range(length) if len({t[i] for t in tails}) > 1]
        if len(diff) == 1:
            di = diff[0]
            merged = list(tails[0])
            merged[di] = "{" + "|".join(
                dict.fromkeys(t[di] for t in tails)) + "}"
            return " ".join(common + merged)

    # Otherwise list the alternatives explicitly.
    joined = " / ".join(" ".join(t) for t in tails)
    return (" ".join(common) + " " + joined).strip()


# ── CLI section grouping (client 2026-06-02, Eyal Ozeri, item 2) ──────────
# The CLI configuration commands are not a flat alphabetical list; QA reads
# them grouped by command mode / function: the interface (Ethernet-Segment)
# configs together, the new LACP knobs (agg-eth only) together, the
# l2-services EVPN and VPLS knobs each together, and the BGP EVPN
# address-family sub-configs together. Each config row carries its group as
# the PlanRow.category so the xlsx writer can band them.
GRP_INTERFACE = "CLI Configuration — Interface / Ethernet-Segment"
GRP_LACP = "CLI Configuration — LACP (agg-eth only)"
GRP_L2_EVPN = "CLI Configuration — L2-Services EVPN"
GRP_L2_VPLS = "CLI Configuration — L2-Services VPLS"
GRP_BGP_AF = "CLI Configuration — BGP EVPN Address-Family"
GRP_OTHER = "CLI Configuration — Other"

CAT_SHOW_NEW = "CLI Show — New (EVPN-specific)"
CAT_SHOW_MOD = "CLI Show — Modified (EVPN additions)"
CAT_CLEAR = "CLI Clear"


def _cli_config_group(cmd: CliCommand) -> str:
    """Bucket a config command into its functional CLI group."""
    name = cmd.name.lower()
    mode = cmd.mode_path
    if name == "af-l2vpn evpn" or "af-l2vpn" in mode:
        return GRP_BGP_AF
    if name.startswith("lacp"):
        return GRP_LACP
    if "interface" in mode:
        return GRP_INTERFACE
    if "evpn" in mode and "vpls" not in mode:
        return GRP_L2_EVPN
    if "vpls" in mode:
        return GRP_L2_VPLS
    if mode == ["configuration", "l2-services"]:
        # the `evpn <name>` instance command sits at the l2-services root
        return GRP_L2_EVPN
    return GRP_OTHER


def _show_class(cmd: CliCommand) -> str:
    """Classify a show command as EVPN-new vs. an existing show the EVPN
    feature only *extends* (client 2026-06-02, Eyal Ozeri, Show item:
    "differentiation between new show commands and modified show commands").
    A `show interface …` / `show bgp neighbors …` predates EVPN and gains
    EVPN fields; `show evpn …` / `show fib evpn-* …` / `show bgp l2vpn evpn …`
    are new.
    """
    name = cmd.name.lower()
    if name.startswith(("show interface", "show bgp neighbors")):
        return CAT_SHOW_MOD
    return CAT_SHOW_NEW


# Argument tokens carry a value the operator substitutes. We render them
# as `<token>` placeholders so a row never reads like a literal command
# (client 2026-06-01: "there's no `identifier 0 type0-value` command —
# type0 should be a value").
_PLACEHOLDER_SUFFIX_RE = re.compile(
    r"^[a-z][a-z0-9-]*-(ip|id|name|prefix|addr|address|if|value|key)$",
    re.IGNORECASE,
)


# `identifier 0 type0-value` reads as if `type0-value` were a literal token;
# it is the value for ESI type 0 (the `0` already names the type). Render it
# as a clean `<value>` placeholder (client 2026-06-02, Eyal Ozeri, row 68:
# "there's no `identifier 0 type0-value` command — type0 should be a value").
_TYPED_VALUE_RE = re.compile(r"^type\d+-value$", re.IGNORECASE)


def _wrap_placeholders(text: str, param_names: set[str]) -> str:
    """Wrap bare value tokens in angle brackets.

    A token is a placeholder if it matches a documented parameter name or
    looks like an argument (ends in -ip / -id / -name / -prefix / -value …).
    Tokens already bracketed (`<x>`, `{a|b}`) are left alone. A `typeN-value`
    token renders as the cleaner `<value>` (the type is already named by the
    preceding literal).
    """
    out: list[str] = []
    for tok in text.split(" "):
        bare = tok
        if bare and _TYPED_VALUE_RE.match(bare):
            out.append("<value>")
        elif (bare and bare[0] not in "<{[|" and bare[-1] not in ">}]"
                and (bare in param_names or _PLACEHOLDER_SUFFIX_RE.match(bare))):
            out.append(f"<{bare}>")
        else:
            out.append(tok)
    return " ".join(out)


def _example_invocation(cmd: CliCommand) -> str:
    """Pick a canonical example invocation (first non-`no` syntax line),
    with value tokens rendered as `<placeholders>`.
    """
    raw = ""
    for ln in cmd.syntax_lines:
        if not ln.lower().startswith("no "):
            raw = ln
            break
    if not raw:
        raw = cmd.syntax_lines[0] if cmd.syntax_lines else cmd.name
    param_names = {p.name for p in cmd.parameters if p.name}
    return _wrap_placeholders(raw, param_names)


def _syntax_variants(cmd: CliCommand) -> list[str]:
    """Non-`no` syntax lines — the documented invocation variants. A
    command with ≥2 (e.g. ESI `identifier 0|1|4`) defines a value set we
    test explicitly.
    """
    return [ln for ln in cmd.syntax_lines if not ln.lower().startswith("no ")]


def _variant_values(cmd: CliCommand) -> list[str]:
    """For a multi-variant command, the discriminating value token of each
    variant (e.g. identifier 0 / 1 / 4 → ['0', '1', '4'])."""
    base = cmd.name.split()[0] if cmd.name else ""
    base_len = len(base.split())
    values: list[str] = []
    for ln in _syntax_variants(cmd):
        toks = ln.split()
        if len(toks) > base_len:
            values.append(toks[base_len])
    return values


def _no_form(cmd: CliCommand) -> str:
    for ln in cmd.syntax_lines:
        if ln.lower().startswith("no "):
            return ln
    return f"no {cmd.name}"


def _typed_params(cmd: CliCommand) -> list[CliParameter]:
    return [p for p in cmd.parameters if p.value_spec and not p.is_choice]


def _choice_params(cmd: CliCommand) -> list[CliParameter]:
    return [p for p in cmd.parameters if p.is_choice]


def _value_spec_one_line(p: CliParameter) -> str:
    return " ".join(p.value_spec.split())[:120]


def _negative_value_hint(p: CliParameter) -> str:
    spec = p.value_spec.lower()
    if "0..65535" in spec:
        return "65536 (above range), -1 (below range), abc (non-integer)"
    if "0..4095" in spec:
        return "4096 (above range), -1 (below range)"
    if "ipv4" in spec or "ipv6" in spec:
        return "999.999.999.999 (malformed), an unrouted address"
    if "xx:xx:xx" in spec or "mac" in spec:
        return "not-a-mac, ZZ:ZZ:ZZ:ZZ:ZZ:ZZ, 11:22:33 (truncated)"
    if "octet" in spec or "hex-decimal" in spec or "hexadecimal" in spec:
        return "non-hex characters, truncated octet count, length-mismatched value"
    if "integer" in spec:
        return "non-integer string, negative number, value above documented bound"
    return "a value clearly outside the documented spec"


# A numeric value-spec like "1-250000", "0, 40-2400", or "Integer in range
# 0..65535". We mine the explicit range bounds so the validation row can test
# the documented boundaries with concrete numbers instead of a vague "a valid
# in-spec value" (client 2026-06-28: the CLI section must state the actual
# valid configuration values).
_NUM_RANGE_RE = re.compile(r"(\d+)\s*(?:\.\.|-)\s*(\d+)")
# Specs that look numeric but aren't a plain integer range — leave these to
# `_negative_value_hint`'s format-specific wording.
_NON_NUMERIC_SPEC = ("ipv4", "ipv6", "mac", "octet", "hex", "xx", ":")


def _default_value(p: CliParameter) -> str | None:
    """The configurable default token, e.g. `300` from a doc default of
    `300 second`, or `65520`. None when the parameter has no documented
    default."""
    if not p.default:
        return None
    m = re.match(r"-?\d+", p.default.strip())
    return m.group(0) if m else p.default.strip()


def _numeric_bounds(p: CliParameter):
    """`(valid_samples, invalid_samples)` mined from a numeric value-spec, or
    None when the spec isn't a plain integer range.

    `1-250000`   -> (['1', '250000'], ['0 (below range)', '250001 (above range)'])
    `0, 40-2400` -> (['0', '40', '2400'], ['-1 (below range)', '39 (in the
                     disallowed gap)', '2401 (above range)'])
    """
    spec = p.value_spec
    low = spec.lower()
    if any(tok in low for tok in _NON_NUMERIC_SPEC):
        return None
    ranges = [(int(a), int(b)) for a, b in _NUM_RANGE_RE.findall(spec)]
    if not ranges:
        return None
    residual = _NUM_RANGE_RE.sub(" ", spec)
    singletons = [int(t) for t in re.findall(r"-?\d+", residual)]
    lows = [a for a, _ in ranges]
    highs = [b for _, b in ranges]
    gmin, gmax = min(lows + singletons), max(highs + singletons)

    valid = [str(v) for v in sorted(set(singletons + lows + highs))]
    invalid = [f"{gmin - 1} (below range)", f"{gmax + 1} (above range)"]
    # One in-gap value for disjoint specs (e.g. the 1..39 hole in 0, 40-2400).
    segments = sorted(set([(s, s) for s in singletons] + ranges))
    for (_, hi), (nxt_lo, _) in zip(segments, segments[1:]):
        if nxt_lo > hi + 1:
            invalid.insert(1, f"{hi + 1} (in the disallowed gap)")
            break
    if "integer" in low:
        invalid.append("a non-integer string (e.g. `abc`)")
    return valid, invalid


# ── Monitor: the exact Exaware `show` for each command ───────────────────
# Client 2026-06-01: the Monitor column must be Exaware-CLI-exact —
# `show configuration` (NOT `show running-config`, which Exaware does not
# have) plus the precise feature show. Keyed off the command's
# configuration mode and name; values are the real commands from the EVPN
# CLI doc's show section.
def _feature_show_for(cmd: CliCommand) -> list[str]:
    """The feature-specific `show` command(s) that read back `cmd`'s effect.

    Always paired with `show configuration` by the callers (which is the
    persistence/read-back check). Returns [] when the EVPN CLI doc has no
    matching operational show (VPLS-context commands), in which case the
    monitor is `show configuration` alone.
    """
    name = cmd.name.lower()
    mode = cmd.mode_path
    if "ethernet-segment" in mode or name in (
            "ethernet-segment", "identifier", "lacp-key", "lacp-system-mac",
            "load-balancing-mode", "service-carving"):
        return ["show evpn ethernet-segments [esi <es-id>]",
                "show interface agg-eth <agg-id> detail"]
    if name == "af-l2vpn evpn" or "af-l2vpn" in mode:
        return ["show bgp neighbors <neighbor-ip> detail",
                "show bgp l2vpn evpn neighbors received-routes <neighbor-ip> detail"]
    if name == "evpn":
        return ["show evpn global [name <evpn-name>]",
                "show evpn summary [name <evpn-name>]"]
    # l2-services/evpn knobs (MAC, control-word, advertise-mac, timers …)
    if mode and mode[-1] == "evpn":
        return ["show evpn global [name <evpn-name>]",
                "show evpn mac-address-table [name <evpn-name>]"]
    if "interface" in name and "vpls" in name:
        # AC binding under VPLS/EVPN — the FIB shows the attachment circuit.
        return ["show fib evpn-ac"]
    # VPLS-context knobs: EVPN CLI doc has no VPLS show — read back via
    # `show configuration` only (callers add it).
    return []


def _monitor_list(cmd: CliCommand, include_feature: bool = True) -> list[str]:
    """`show configuration` + feature show(s)."""
    mons = ["show configuration"]
    if include_feature:
        mons.extend(_feature_show_for(cmd))
    return mons


def _verify_with_monitors(lines: list[str], monitors: list[str]) -> list[str]:
    """Append a backticked read-back step per monitor so atomic_rows lifts
    them into the Monitor column."""
    out = list(lines)
    for m in monitors:
        out.append(f"Read back via `{m}`.")
    return out


# ── Precondition (Notes) parsing — one row per documented constraint ─────
_CUE_CANNOT = re.compile(
    r"can\s*not be configured|cannot be configured", re.IGNORECASE)
_CUE_ONLY_IF = re.compile(r"only if\s*:?\s*$", re.IGNORECASE)
_AND_SPLIT = re.compile(r"\s+AND\s*$|\s+AND\s+")


def _clean_clause(text: str) -> str:
    return " ".join(text.split()).strip().rstrip(".").strip("`").strip()


def _prerequisite_clauses(cmd: CliCommand) -> list[tuple[str, str]]:
    """Parse the Notes cell into (kind, condition) precondition tuples.

    kind ∈ {"only-if", "cannot", "only", "must"}. Informational prose
    (no constraint cue) is dropped so we don't emit a bogus
    "rejected with an error" row for it. The result drives one focused
    precondition row each (client 2026-06-01, item 10).
    """
    notes = cmd.notes or ""
    if not notes.strip():
        return []
    lines = [ln.strip() for ln in notes.splitlines() if ln.strip()]
    clauses: list[tuple[str, str]] = []
    collecting_only_if = False
    for ln in lines:
        low = ln.lower()
        if _CUE_ONLY_IF.search(ln):
            collecting_only_if = True
            continue
        if collecting_only_if:
            if (low.startswith("the command cannot") or low.startswith("it means")
                    or low.startswith("if ")):
                collecting_only_if = False
                # fall through to normal handling below
            else:
                for part in _AND_SPLIT.split(ln):
                    cond = _clean_clause(part)
                    if cond:
                        clauses.append(("only-if", cond))
                continue
        for sent in re.split(r"(?<=[.])\s+", ln):
            s = _clean_clause(sent)
            sl = s.lower()
            if not s:
                continue
            if "cannot change the evpn parameters" in sl:
                continue  # redundant restatement of "already attached"
            if _CUE_CANNOT.search(s):
                cond = re.sub(
                    r"^.*?can\s*not be configured\s*(if|when)?\s*", "", s,
                    flags=re.IGNORECASE).strip()
                clauses.append(("cannot", _clean_clause(cond)))
            elif "supported only" in sl or "only in vrf" in sl:
                clauses.append(("only", s))
            elif (sl.startswith("only interfaces")
                  or "can be configured as an attachment circuit" in sl
                  or "can be configured on interface types" in sl):
                clauses.append(("only", s))
            elif sl.startswith("you must") or sl.startswith("must "):
                clauses.append(("must", s))
            elif "mandatory" in sl and "cannot be deleted" in sl:
                clauses.append(("must", s))
    # De-duplicate by condition text, cap to keep the row family readable.
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for kind, cond in clauses:
        key = cond.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((kind, cond))
    return out[:4]


def _prereq_action(cmd: CliCommand, kind: str, cond: str) -> str:
    """Phrase the precondition test as a single Verify-style instruction
    mirroring the client's own wording."""
    if kind == "only-if":
        return (f"Verify `{cmd.name}` can be configured **only if** {cond}; "
                f"with the precondition unmet, commit is rejected with a "
                f"descriptive error naming it.")
    if kind == "cannot":
        return (f"Verify `{cmd.name}` **cannot** be configured when {cond}; "
                f"commit is rejected with a descriptive error message.")
    # "only" / "must"
    return (f"Verify `{cmd.name}`: {cond}; a violation is rejected at commit "
            f"time with a descriptive error message.")


def rows_for_command(cmd: CliCommand) -> list[PlanRow]:
    """Build the row family for one CLI command. Returns [] for show/clear
    commands — those don't populate the CLI Configuration section.
    """
    if not cmd.is_config:
        return []

    rows: list[PlanRow] = []
    req_anchor = f"CLI:{cmd.name}"
    cat = _cli_config_group(cmd)
    mode = _mode_path_str(cmd)
    invocation = _example_invocation(cmd)
    related = (", ".join(cmd.related_features)
               if cmd.related_features else "the feature")
    monitors = _monitor_list(cmd)
    primary_show = (_feature_show_for(cmd) or ["show configuration"])[0]

    purpose = _purpose_phrase(cmd.description)

    def _mk(action_steps: str, expectation: str) -> PlanRow:
        return PlanRow(
            category=cat, sub_category=cmd.name, equipment=EQUIPMENT,
            sfs_requirement_id=req_anchor, purpose=purpose,
            action_steps=action_steps, expectation=expectation,
        )

    # ── Row 1: Happy-path configure ──────────────────────────────────────
    if cmd.is_container:
        # A container opens a sub-mode and takes no value of its own — it
        # "cannot be committed" standalone (client 2026-06-02, Eyal Ozeri).
        # Its documented child attributes are configured beneath it, in
        # sequence.
        attrs = cmd.container_attrs or sub_config_names_for(cmd.name)
        attr_str = (", ".join(f"`{a}`" for a in attrs) if attrs
                    else "its documented attributes")
        rows.append(_mk(
            _scaffold(
                f"DUT booted; no prior `{cmd.name}` configuration.",
                f"Descend to the `{mode}` level and enter the `{cmd.name}` "
                f"container. It is a container node — it takes no value of "
                f"its own and is not committed on its own. Configure its "
                f"documented attributes in order ({attr_str}); commit at the "
                f"parent level.",
                _verify_with_monitors(
                    [f"`show configuration` shows the `{cmd.name}` container "
                     f"with its attributes nested beneath the `{mode}` level."],
                    _feature_show_for(cmd)),
            ),
            _expect(
                f"`{cmd.name}` is entered as a container and its attributes "
                f"({attr_str}) are accepted and nested beneath it; "
                f"{related} reads back via `{primary_show}`",
                f"`{cmd.name}` is treated as a leaf (accepts/commits a value "
                f"of its own), or its attributes are not nested under it",
            ),
        ))
    else:
        rows.append(_mk(
            _scaffold(
                f"DUT booted; no prior `{cmd.name}` configuration.",
                f"At the `{mode}` configuration level, configure "
                f"`{invocation}` and commit the candidate config.",
                _verify_with_monitors(
                    [f"`show configuration` shows the `{cmd.name}` line under "
                     f"the `{mode}` level."],
                    _feature_show_for(cmd)),
            ),
            _expect(
                f"`{cmd.name}` is accepted and present in `show configuration`; "
                f"{related} reads back via `{primary_show}`",
                "Commit is rejected, or the configured line is absent from "
                "`show configuration` after commit",
            ),
        ))

    # ── Documented value-set row (multi-variant commands, e.g. ESI types)─
    variants = _syntax_variants(cmd)
    values = _variant_values(cmd)
    if len(variants) >= 2 and len(values) >= 2:
        param_names = {p.name for p in cmd.parameters if p.name}
        shown = ", ".join(
            f"`{_wrap_placeholders(v, param_names)}`" for v in variants)
        default_note = (f"; documented default is `{cmd.default_behavior}`"
                        if cmd.default_behavior else "")
        rows.append(_mk(
            _scaffold(
                f"DUT at the `{mode}` configuration level.",
                f"Configure `{cmd.name}` with each documented value "
                f"({', '.join('`'+v+'`' for v in values)}): {shown}. Then "
                f"attempt an undocumented value (e.g. `{cmd.name} 2`).",
                _verify_with_monitors(
                    ["Each documented value is accepted; the undocumented "
                     "value is rejected at parse time with a descriptive "
                     "error."],
                    monitors),
            ),
            _expect(
                f"Only the documented `{cmd.name}` values "
                f"({', '.join(values)}) are accepted{default_note}",
                "An undocumented value is accepted, or a documented value "
                "is rejected",
            ),
        ))

    # ── Row 2..N: Range / type validation per typed parameter ────────────
    for p in _typed_params(cmd):
        spec = _value_spec_one_line(p)
        bounds = _numeric_bounds(p)
        if bounds:
            valid_vals, invalid_vals = bounds
            valid_clause = (f"the documented boundary values "
                            f"({', '.join(valid_vals)}) — valid per {spec!r}")
            bad = "; ".join(invalid_vals)
        else:
            valid_clause = f"a valid in-spec value (per {spec!r})"
            bad = _negative_value_hint(p)
        default_clause = ""
        dv = _default_value(p)
        if dv:
            default_clause = (f" The documented default is `{dv}`; with "
                              f"`{cmd.name}` omitted the value defaults to "
                              f"`{dv}`.")
        rows.append(_mk(
            _scaffold(
                f"DUT at the `{mode}` configuration level.",
                f"Issue `{cmd.name} <{p.name}>` with values: "
                f"(a) {valid_clause}; "
                f"(b) invalid values: {bad}.{default_clause}",
                _verify_with_monitors(
                    ["Each valid boundary value commits and is read back with "
                     "the correct type/format; each invalid value is rejected "
                     "at parse time with a CLI error naming the parameter; the "
                     "configuration does NOT contain the bad value."],
                    monitors),
            ),
            _expect(
                f"Documented valid `<{p.name}>` values accepted; each invalid "
                f"value rejected with a parse error; the configuration remains "
                f"clean",
                f"Invalid value silently accepted, feature crashes, or the "
                f"configuration retains a partial/invalid `{cmd.name}` line",
            ),
        ))

    # ── Default-value row per typed parameter the doc gives a default for ─
    # Client 2026-06-28: the CLI section must state each parameter's default
    # and prove it is the effective value when the command is omitted.
    for p in _typed_params(cmd):
        dv = _default_value(p)
        if not dv:
            continue
        rows.append(_mk(
            _scaffold(
                f"DUT at the `{mode}` configuration level with `{cmd.name}` "
                f"NOT configured (parameter `{p.name}` omitted).",
                f"Read back the effective `{p.name}`; then explicitly set the "
                f"documented default `{cmd.name} {dv}` and read back again.",
                _verify_with_monitors(
                    [f"With `{cmd.name}` omitted the effective `{p.name}` is the "
                     f"documented default ({dv}); `show configuration` omits the "
                     f"line; explicitly configuring `{cmd.name} {dv}` is accepted "
                     f"and is a functional no-op (idempotent)."],
                    monitors),
            ),
            _expect(
                f"Default `{p.name}` = {dv} is in effect when `{cmd.name}` is "
                f"unconfigured; explicit default is idempotent",
                f"Effective default differs from the documented {dv}, or "
                f"setting the default value alters behaviour / configuration",
            ),
        ))

    # ── Mutual exclusion row for choice parameters ───────────────────────
    choices = _choice_params(cmd)
    if len(choices) >= 2:
        choice_names = " | ".join(p.name for p in choices)
        rows.append(_mk(
            _scaffold(
                f"DUT at the `{mode}` configuration level.",
                f"Configure `{cmd.name}` with one choice "
                f"(e.g. `{choices[0].name}`); commit; then reconfigure with "
                f"a different choice ({choice_names}); commit.",
                _verify_with_monitors(
                    ["Only one choice is active at a time in the "
                     "configuration; the second commit replaces the first "
                     "cleanly; the feature reflects the latest choice."],
                    monitors),
            ),
            _expect(
                "Mutually-exclusive choices replace each other on commit",
                "Both choices appear in the configuration simultaneously, or "
                "the feature retains old behaviour after the switch",
            ),
        ))

    # ── Default-behavior row, only if doc names a default ────────────────
    if cmd.default_behavior:
        rows.append(_mk(
            _scaffold(
                f"DUT booted with no `{cmd.name}` configuration at the "
                f"`{mode}` level.",
                f"Bring the parent feature up without configuring "
                f"`{cmd.name}`; observe the default behaviour.",
                _verify_with_monitors(
                    [f"Feature operates with the documented default "
                     f"(\"{cmd.default_behavior}\"); `show configuration` "
                     f"omits the line; explicit configuration of the default "
                     f"value is a no-op (idempotent)."],
                    monitors),
            ),
            _expect(
                f"Default behaviour matches doc: \"{cmd.default_behavior}\"",
                "Default differs from doc, or explicit config of the default "
                "value changes the configuration (non-idempotent)",
            ),
        ))

    # ── `no` form row, if syntax shows it ────────────────────────────────
    if cmd.has_no_form:
        rows.append(_mk(
            _scaffold(
                f"`{cmd.name}` configured (Row 1 happy-path).",
                f"Issue `{_no_form(cmd)}`; commit.",
                _verify_with_monitors(
                    [f"`show configuration` no longer contains `{cmd.name}`; "
                     f"the feature reverts to default behaviour; no stale "
                     f"state in operational show outputs or kernel "
                     f"forwarding tables."],
                    monitors),
            ),
            _expect(
                f"`{cmd.name}` removed cleanly; feature reverts to default",
                "Stale config remains, feature stuck in old state, or kernel "
                "state inconsistent with the control plane",
            ),
        ))

    # ── Persistence row ──────────────────────────────────────────────────
    rows.append(_mk(
        _scaffold(
            f"`{cmd.name}` configured and committed under the `{mode}` level.",
            "Save the configuration; reload the DUT.",
            _verify_with_monitors(
                [f"After full boot, `show configuration` contains the same "
                 f"`{cmd.name}` line; the feature comes up automatically with "
                 f"the saved configuration."],
                _feature_show_for(cmd)),
        ),
        _expect(
            f"`{cmd.name}` survives reload byte-identical; feature auto-resumes",
            "Config lost on reload, partial-restore, or feature requires "
            "manual re-config after reload",
        ),
    ))

    # ── Help & completion row ─────────────────────────────────────────────
    # `?` lists the documented sub-tokens and TAB completes — an operator
    # must be able to discover the command from the prompt.
    head = cmd.name.split()[0]
    rows.append(_mk(
        _scaffold(
            [f"DUT at the `{mode}` configuration level (no `{cmd.name}` "
             f"configured yet)."],
            [f"At the prompt, type `{head} ?` and inspect the help listing.",
             f"Type the first letters of `{head}` and press TAB; observe "
             "completion.",
             f"After entering `{head} `, type `?` to list the next-token "
             "completions."],
            ["Help (`?`) lists the command with a non-empty one-line "
             "description.",
             "TAB completes uniquely (or offers the documented set when "
             "ambiguous); no tokens outside the CLI doc.",
             "Sub-token help shows every documented parameter (no missing, "
             "no extra)."],
        ),
        _expect(
            f"`{cmd.name}` is discoverable from `?` and TAB; sub-token help "
            "lists exactly the documented parameters",
            "Command absent from `?`, TAB does not complete, or sub-token "
            "help drops / invents parameters vs. the CLI doc",
        ),
    ))

    # ── Available-options enumeration under a sub-mode parent ────────────
    # `af-l2vpn evpn` opens the EVPN SAFI sub-mode; its options are the
    # inherited BGP sub-configs (client 2026-06-01, item 17).
    sub_opts = sub_config_names_for(cmd.name)
    if sub_opts:
        rows.append(_mk(
            _scaffold(
                f"DUT at the `{mode}` level with `{cmd.name}` entered.",
                f"Under `{cmd.name}`, type `?` to list the available options "
                f"of the evpn SAFI sub-mode.",
                ["Help lists exactly the documented sub-config options: "
                 + ", ".join(f"`{o}`" for o in sub_opts) + "."],
            ),
            _expect(
                f"The evpn SAFI exposes exactly the documented options "
                f"({len(sub_opts)}): {', '.join(sub_opts)}",
                "An option is missing from `?`, or an undocumented option "
                "appears",
            ),
        ))

    # ── Precondition rows — one per documented constraint ────────────────
    for kind, cond in _prerequisite_clauses(cmd):
        rows.append(_mk(
            _scaffold(
                f"DUT able to reach the `{mode}` level.",
                _prereq_action(cmd, kind, cond),
                _verify_with_monitors(
                    ["The CLI rejects the command at parse/commit time with a "
                     "clear, descriptive error; the configuration is "
                     "unchanged; satisfying the precondition then permits the "
                     "command on retry."],
                    ["show configuration"]),
            ),
            _expect(
                "Precondition enforced at parse/commit time with a "
                "descriptive error message",
                "Command silently accepted, feature half-configured, or the "
                "error does not identify the violated precondition",
            ),
        ))

    # ── VPLS-not-harmed regression (AC binding under VPLS/EVPN) ───────────
    # Client 2026-06-01, item 15: verify the shared VPLS path is not
    # regressed (CLI-wise) by the EVPN attachment-circuit binding.
    if "interface" in cmd.name.lower() and "vpls" in cmd.name.lower():
        rows.append(_mk(
            _scaffold(
                "A working VPLS service with an attachment circuit is "
                "configured on the DUT.",
                f"Configure / remove the EVPN AC via `{cmd.name}` alongside "
                f"the existing VPLS service.",
                _verify_with_monitors(
                    ["The existing VPLS AC binding, MAC learning and "
                     "forwarding are unaffected by the EVPN command; no VPLS "
                     "config is dropped or altered."],
                    ["show configuration", "show fib evpn-ac"]),
            ),
            _expect(
                "VPLS service continues forwarding; no VPLS CLI/config "
                "regression introduced by the EVPN AC binding",
                "VPLS AC, MAC table, or forwarding disrupted by the EVPN "
                "command",
            ),
        ))

    return rows


# ── Show / clear grammar expansion ───────────────────────────────────────
def _has_top_level_pipe(s: str) -> bool:
    depth = 0
    for ch in s:
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        elif ch == "|" and depth == 0:
            return True
    return False


def _split_choices(inner: str) -> list[str]:
    alts: list[str] = []
    depth = 0
    cur = ""
    for ch in inner:
        if ch in "{[":
            depth += 1
            cur += ch
        elif ch in "}]":
            depth -= 1
            cur += ch
        elif ch == "|" and depth == 0:
            alts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        alts.append(cur.strip())
    return alts


def _split_top_level(s: str) -> list[tuple[str, object]]:
    segs: list[tuple[str, object]] = []
    buf = ""
    i, n = 0, len(s)

    def _flush() -> None:
        nonlocal buf
        for w in buf.split():
            segs.append(("lit", w))
        buf = ""

    while i < n:
        ch = s[i]
        if ch in "{[":
            _flush()
            close_depth = 1
            j = i + 1
            while j < n and close_depth > 0:
                if s[j] in "{[":
                    close_depth += 1
                elif s[j] in "}]":
                    close_depth -= 1
                j += 1
            inner = s[i + 1:j - 1].strip()
            if ch == "{":
                segs.append(("choice", _split_choices(inner)))
            else:
                segs.append(("opt", inner))
            i = j
        else:
            buf += ch
            i += 1
    _flush()
    return segs


def _expand_grammar(s: str) -> list[str]:
    """Expand a CLI syntax line ({a|b} mandatory choice, [opt] optional,
    bare `a | b` choice) into the concrete invocation variants."""
    s = s.strip()
    if not s:
        return [""]
    if _has_top_level_pipe(s):
        out: list[str] = []
        for alt in _split_choices(s):
            out.extend(_expand_grammar(alt))
        return out
    variants = [""]
    for kind, val in _split_top_level(s):
        new: list[str] = []
        if kind == "lit":
            for v in variants:
                new.append((v + " " + str(val)).strip())
        elif kind == "choice":
            for v in variants:
                for alt in val:  # type: ignore[union-attr]
                    for sub in _expand_grammar(alt):
                        new.append((v + " " + sub).strip())
        elif kind == "opt":
            for v in variants:
                new.append(v)
                for sub in _expand_grammar(str(val)):
                    new.append((v + " " + sub).strip())
        variants = new
    return variants


def _expanded_invocations(cmd: CliCommand, limit: int = 6) -> list[str]:
    """Concrete, placeholder-wrapped invocations for a show/clear command."""
    syntax = cmd.syntax_lines[0] if cmd.syntax_lines else cmd.name
    param_names = {p.name for p in cmd.parameters if p.name}
    seen: list[str] = []
    for inv in _expand_grammar(syntax):
        inv = _wrap_placeholders(" ".join(inv.split()), param_names)
        if inv and inv not in seen:
            seen.append(inv)
    if not seen:
        return [_wrap_placeholders(syntax, param_names)]
    # Sort by token count then text so the base form of EACH mandatory
    # branch (e.g. advertised-routes AND received-routes) and the
    # brief/detail variants surface before the deeply-optional forms —
    # a representative spread rather than every variant of one branch.
    seen.sort(key=lambda s: (len(s.split()), s))
    return seen[:limit]


def _paired_show_for_clear(cmd: CliCommand) -> str:
    """The `show` that confirms a `clear` took effect (clear → show)."""
    syntax = cmd.syntax_lines[0] if cmd.syntax_lines else cmd.name
    base = re.split(r"[\[{]", syntax, maxsplit=1)[0].strip()
    if base.lower().startswith("clear "):
        return "show " + base[len("clear "):].strip()
    return "show " + base


def rows_for_show_command(cmd: CliCommand) -> list[PlanRow]:
    """Row family for a `show` / `clear` command.

    Show commands expand their grammar into the specific documented cases
    and verify EVPN-relevant content (client 2026-06-01, items 18-20).
    Clear commands verify the *cleared state* via the paired show, not
    "well-formed output" (item 21). The per-command pipe-filter row is
    gone (item 4).
    """
    if cmd.kind not in ("show", "clear"):
        return []

    req_anchor = f"CLI:{cmd.name}"
    cat = CAT_CLEAR if cmd.kind == "clear" else _show_class(cmd)
    name = cmd.name.lower()
    purpose = _purpose_phrase(cmd.description)

    def _mk(action_steps: str, expectation: str) -> PlanRow:
        return PlanRow(
            category=cat, sub_category=cmd.name, equipment=EQUIPMENT,
            sfs_requirement_id=req_anchor, purpose=purpose,
            action_steps=action_steps, expectation=expectation,
        )

    # ── Clear commands: verify the effect, not the output shape ──────────
    if cmd.kind == "clear":
        invs = _expanded_invocations(cmd, limit=4)
        paired = _paired_show_for_clear(cmd)
        inv_full = invs[-1]  # most-qualified form (scoped clear)
        return [_mk(
            _scaffold(
                "Populate the target state on the DUT (e.g. frozen / "
                "duplicate MAC entries present; MAC table populated).",
                [f"Issue the unscoped form `{invs[0]}`.",
                 f"Issue a scoped form `{inv_full}` to clear a single "
                 "target.",
                 f"Re-issue the clear to confirm it is a no-op."],
                [f"`{paired}` confirms the targeted entries are removed.",
                 "Unrelated entries are left untouched (scope respected).",
                 "Re-issuing the clear neither errors nor changes state "
                 "(idempotent)."],
            ),
            _expect(
                f"Targeted state is cleared (confirmed by `{paired}`); scope "
                f"is respected; the clear is idempotent",
                "Entries persist after the clear, unrelated state is cleared, "
                "or the command errors / prints a malformed message",
            ),
        )]

    # ── Show commands: expand the grammar into specific cases ────────────
    # `show interface …` — the only EVPN-relevant addition is the agg-eth
    # variant (ES membership under agg-eth); don't over-generate the
    # loopback / x-eth / mgmt variants (client item 18).
    if name.startswith("show interface"):
        invs = ["show interface agg-eth <agg-id> detail"]
        verify = ["Output is well-formed; the agg-eth detail block shows the "
                  "Ethernet-Segment membership / ESI added for EVPN."]
        expect_pass = ("`show interface agg-eth <agg-id> detail` renders the "
                       "EVPN Ethernet-Segment fields for the agg-eth")
    else:
        invs = _expanded_invocations(cmd)
        verify = ["Each invocation renders without a parser error; the "
                  "header / columns match the documented format.",
                  "Optional arguments (name / esi / vlan-id / neighbor / "
                  "prefix) scope the output correctly."]
        expect_pass = (f"every documented form of `{cmd.name}` produces "
                       f"well-formed, correctly-scoped output")

    # `show bgp neighbors … detail` — call out the new EVPN additions
    # (l2vpn evpn AF block, EVPN capability) the client wants flagged
    # (item 19).
    if name.startswith("show bgp neighbors"):
        verify.append("`detail` now includes the new EVPN additions: the "
                      "l2vpn evpn address-family block and EVPN capability "
                      "negotiation state.")
        expect_pass += ("; `detail` surfaces the new l2vpn evpn AF / EVPN "
                        "capability additions")

    action_steps = _scaffold(
        "DUT booted; CLI session via console / SSH; relevant EVPN state "
        "present so the command has content to render.",
        [f"Issue `{inv}`." for inv in invs],
        verify,
    )
    return [_mk(action_steps, _expect(
        expect_pass,
        "Parser error, missing/extra columns, an optional argument that "
        "does not scope the output, or a documented case that is rejected",
    ))]


def _pipe_modifier_row() -> PlanRow:
    """A single output-modifier (`|`) test for the whole CLI section.

    Client 2026-06-02 (Eyal Ozeri): the per-command pipe rows were removed
    *completely*, which "wasn't the intention" — the modifier set should be
    exercised once, not on every command. This is that one row.
    """
    return PlanRow(
        category=CAT_SHOW_MOD, sub_category="| output modifiers",
        equipment=EQUIPMENT, sfs_requirement_id="CLI:pipe-modifiers",
        action_steps=_scaffold(
            "DUT booted with EVPN state present; CLI session via console / SSH.",
            ["Run a representative show with each output modifier: "
             "`show evpn ethernet-segments | include <esi>`, "
             "`show configuration | exclude <pattern>`, "
             "`show evpn mac-address-table | count`, "
             "`show configuration | begin <section>`."],
            ["Each modifier filters the base output as documented and never "
             "alters device state; the same modifiers work uniformly across "
             "show commands."],
        ),
        expectation=_expect(
            "The `|` output modifiers (include / exclude / count / begin) "
            "filter show output correctly on a representative command",
            "A modifier errors, is rejected, or changes the underlying output "
            "content instead of filtering it",
        ),
    )


# ── Ordering: by command mode, not alphabetically ───────────────────────
def cli_command_rows(commands: list[CliCommand]) -> list[PlanRow]:
    """Concatenate all CLI rows, ordered by **command mode**.

    Client 2026-06-01 (item 3): the CLI doc lists commands alphabetically,
    but QA reads them per command mode. Config commands are grouped by
    `mode_path` (all `… interface agg-eth ethernet-segment` together, then
    the `… l2-services evpn` group, etc.), preserving doc order within a
    mode. Show / clear commands follow, grouped the same way by their
    leading tokens so related views sit together.
    """
    config = [c for c in commands if c.is_config]
    shows = [c for c in commands if c.kind in ("show", "clear")]

    # Group order so the configuration stream is contiguous per functional
    # group (client 2026-06-02, item 2): interface / LACP / l2-EVPN /
    # l2-VPLS / BGP-AF. Within a group, preserve command-mode then doc order.
    _GROUP_ORDER = {
        GRP_INTERFACE: 0, GRP_LACP: 1, GRP_L2_EVPN: 2, GRP_L2_VPLS: 3,
        GRP_BGP_AF: 4, GRP_OTHER: 5,
    }

    def _config_key(item: tuple[int, CliCommand]) -> tuple:
        idx, c = item
        return (_GROUP_ORDER.get(_cli_config_group(c), 9),
                tuple(c.mode_path), idx)

    def _show_key(item: tuple[int, CliCommand]) -> tuple:
        idx, c = item
        # group by the command stem (show evpn / show bgp / clear evpn …)
        stem = " ".join(c.name.lower().split()[:2])
        return (stem, idx)

    out: list[PlanRow] = []
    for _idx, c in sorted(enumerate(config), key=_config_key):
        out.extend(rows_for_command(c))
    for _idx, c in sorted(enumerate(shows), key=_show_key):
        out.extend(rows_for_show_command(c))
    # One output-modifier test for the whole CLI section (not per-command).
    # It belongs to the show section, so emit it only when shows are present.
    if shows:
        out.append(_pipe_modifier_row())
    return out

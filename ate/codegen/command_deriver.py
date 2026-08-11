"""Derive the `EvpnCommands` registry from the CLI doc instead of hand-listing it.

The registry in `commands.py` is 18 entries a human wrote — exactly what the
three curated flows needed. That is why mechanically generated suites ground
almost nothing: a plan row naming `service-carving` or `load-balancing-mode`
has no constant to bind to, so the step degrades to a TODO stub. The CLI doc
extractor already yields 44 commands with their syntax, parameters and
configuration mode. This module turns those into registry entries, which is
what makes `plan_scripts.py` produce real tests rather than scaffolding.

The whole value of this project rests on generated CLI being *documented* CLI,
so the derivation is deliberately literal:

  * **Forms come from the doc's own syntax lines.** `load-balancing-mode
    single-active | all-active` yields two entries, one per documented form.
    Nothing is composed that the document does not show.
  * **A token becomes an argument only when the doc says it is one.** `%s` is
    emitted for a token that appears in the command's parameter table *and*
    outside an alternation. Tokens inside `a | b` are enumerated keywords —
    `enable`, `all-active` — and stay literal, even though the doc lists them
    in the same table. Getting this backwards would emit `%s` where the device
    expects a keyword.
  * **Doc quirks are preserved, not corrected.** `unknow-mac-flooding` (missing
    `n`) and the capitalised `Advertise-mac` are emitted verbatim, because a
    consistent misspelling usually means the product has it too. They are
    flagged, not fixed.
  * **The curated 18 win every conflict.** They encode decisions the document
    alone cannot settle — chiefly that `show evpn mac address-table` takes a
    space where one CLI-doc syntax line uses a hyphen. A derived entry that
    collides with a curated key or template is dropped.

Optional groups are expanded both ways (`show evpn global` and `show evpn
global name %s`) because both are real commands and a test may want either.
Expansion is capped per command so a line with many optionals cannot produce a
combinatorial explosion of near-duplicate constants.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ate.codegen.commands import CLI, CLI_CONFIGURE, EVPN_COMMANDS, EvpnCommand

__all__ = ["derive_commands", "expand_syntax"]

#: Ceiling on the forms produced from one syntax line.
_MAX_FORMS = 8

#: Config submodes you descend into *per named instance*: the mode path must
#: carry a selector. `l2-services evpn` is entered as `l2-services evpn <name>`
#: (Eyal Ozeri, 2026-07-13 — the mac-limit correction), and an interface as
#: `interface agg-eth <id>`. Without this the emitted template would name a
#: mode level that does not exist.
_INSTANCE_AFTER = {
    "l2-services": {"evpn", "vpls", "vpws", "xconnect"},
    "interface": {"agg-eth", "x-eth", "loopback", "mgmt"},
    "routing": {"bgp"},
    "bgp": {"vrf"},
    "vrf": {"neighbor"},
}

#: Tokens the CLI doc writes as operands but omits from a command's parameter
#: table. Emitting them literally would type `agg-id` at a device; emitting
#: `%s` forces the caller to supply a value. Entries carry a note saying the
#: placeholder was inferred from naming rather than read from the table.
_PLACEHOLDER_SUFFIX = ("-id", "-if", "-name", "-value", "-address", "-prefix",
                       "-ip", "-target")
_PLACEHOLDER_WORD = {"seconds", "limit", "preference", "value"}


def _looks_like_placeholder(tok: str) -> bool:
    return (tok.endswith(_PLACEHOLDER_SUFFIX) or tok in _PLACEHOLDER_WORD) \
        and not tok.startswith("%")

_TOKEN = re.compile(r"[\[\]{}|]|[^\s\[\]{}|]+")


@dataclass
class _Node:
    kind: str                 # "word" | "alt" | "opt"
    word: str = ""
    branches: list[list["_Node"]] | None = None


def _tokenize(line: str) -> list[str]:
    return _TOKEN.findall(line)


def _parse_alt(toks: list[str], i: int, stop: set[str]) -> tuple[list[list[_Node]], int]:
    """Parse `seq ('|' seq)*` up to a stop token."""
    branches: list[list[_Node]] = []
    seq: list[_Node] = []
    while i < len(toks) and toks[i] not in stop:
        t = toks[i]
        if t == "|":
            branches.append(seq)
            seq = []
            i += 1
        elif t == "[":
            inner, i = _parse_alt(toks, i + 1, {"]"})
            i += 1                                   # consume "]"
            seq.append(_Node("opt", branches=inner))
        elif t == "{":
            inner, i = _parse_alt(toks, i + 1, {"}"})
            i += 1                                   # consume "}"
            seq.append(_Node("alt", branches=inner))
        else:
            seq.append(_Node("word", word=t))
            i += 1
    branches.append(seq)
    return branches, i


def _enumerate(seq: list[_Node]) -> list[list[tuple[str, int | None]]]:
    """All concrete token sequences for a parsed sequence.

    Each token is `(text, alt_pos)`. `alt_pos` is the token's index inside the
    alternation branch it came from, or None if it came from plain sequence.
    Position matters: in `agg-eth agg-id` the *first* token is the selector
    keyword and the second is its operand, so a blanket "came from an
    alternation → literal" rule would emit `agg-id` at a device.
    """
    out: list[list[tuple[str, int | None]]] = [[]]
    for node in seq:
        if node.kind == "word":
            out = [o + [(node.word, None)] for o in out]
            continue
        branches = node.branches or []
        multi = len(branches) > 1
        variants: list[list[tuple[str, int | None]]] = []
        if node.kind == "opt":
            variants.append([])                      # the "omitted" case
        for br in branches:
            for sub in _enumerate(br):
                if multi:
                    sub = [(w, p if p is not None else i)
                           for i, (w, p) in enumerate(sub)]
                variants.append(sub)
        merged: list[list[tuple[str, int | None]]] = []
        for o in out:
            for v in variants:
                merged.append(o + v)
                if len(merged) >= _MAX_FORMS * 4:
                    break
        out = merged
    return out


def _render(tokens: list[tuple[str, int | None]], param_names: set[str]) -> str:
    """Concrete token list → a `printf` template."""
    out: list[str] = []
    for idx, (word, alt_pos) in enumerate(tokens):
        nxt, nxt_pos = (tokens[idx + 1] if idx + 1 < len(tokens) else (None, None))
        # `evi-name evi-name` / `move-count move-count`: the doc writes the
        # keyword and its value with the same name — first literal, then value.
        if word == nxt and word in param_names:
            out.append(word)
            continue
        # A parameter-table token introducing an enumerated *value set* is a
        # keyword: `service-type {vlan-based | ...}` renders `service-type
        # vlan-based`, never `%s vlan-based`.
        #
        # The tell is the branch length. A value set has single-token branches
        # (`vlan-based`), so nothing follows at alt position 1. A separate
        # clause has multi-token branches (`source interface`), and there
        # `evpn-name` really is the value: `... name %s source %s`.
        after_pos = tokens[idx + 2][1] if idx + 2 < len(tokens) else None
        if word in param_names and nxt_pos == 0 and after_pos != 1:
            out.append(word)
            continue
        if alt_pos == 0:
            # The selector keyword of an alternation branch — `enable`,
            # `all-active`, `agg-eth`. Always literal.
            out.append(word)
        elif word in param_names or _looks_like_placeholder(word):
            out.append("%s")
        else:
            out.append(word)
    return " ".join(out).strip()


def expand_syntax(line: str, param_names: set[str]) -> list[str]:
    """One documented syntax line → concrete `printf` templates.

    Returns the shortest form first (all optionals omitted), then longer ones,
    capped at `_MAX_FORMS`.
    """
    branches, _ = _parse_alt(_tokenize(line), 0, set())
    # A bare top-level `a | b` alternates only the trailing operand — the doc
    # writes `load-balancing-mode single-active | all-active`, meaning one
    # command with two values, not two commands. Re-attach the leading literal
    # prefix (everything before the first value token) to the later branches.
    if len(branches) > 1 and branches[0]:
        head = branches[0]
        cut = len(head)
        for i, node in enumerate(head):
            if node.kind == "word" and (node.word in param_names
                                        or _looks_like_placeholder(node.word)):
                cut = i
                break
        prefix = head[:cut] if cut else head[:1]
        # Rebuild as prefix + one alternation over the trailing operands, so
        # the operands are marked as enumerated keywords and stay literal:
        # `load-balancing-mode single-active` / `... all-active`, not `... %s`.
        tails = [head[len(prefix):]] + branches[1:]
        branches = [prefix + [_Node("alt", branches=tails)]]

    forms: list[str] = []
    for br in branches:
        for tokens in _enumerate(br):
            text = _render(tokens, param_names)
            if text and text not in forms:
                forms.append(text)
    forms.sort(key=lambda f: (len(f.split()), f))
    return forms[:_MAX_FORMS]


def _mode_prefix(mode_path: list[str]) -> str:
    """Config mode path → the literal prefix a command needs, with selectors.

    `['configuration','l2-services','evpn']` → `l2-services evpn %s`, matching
    how the curated entries are written and how `Commands` reads in Exaware's
    own tree.
    """
    toks = [t for t in (mode_path or []) if t != "configuration"]
    out: list[str] = []
    for i, tok in enumerate(toks):
        out.append(tok)
        parent = toks[i - 1] if i else ""
        if tok in _INSTANCE_AFTER.get(parent, set()):
            out.append("%s")
    return " ".join(out)


def _key_for(template: str) -> str:
    """A valid, readable Java enum constant for a template."""
    parts: list[str] = []
    for tok in template.split():
        if tok == "%s":
            parts.append("$")
        else:
            parts.append(re.sub(r"[^A-Za-z0-9]+", "_", tok).strip("_").upper())
    key = "_".join(p for p in parts if p)
    key = re.sub(r"_+", "_", key)
    if not key or not key[0].isalpha():
        key = "CMD_" + key
    return key


def derive_commands(cli_commands: list, include_no_forms: bool = False,
                    ) -> tuple[list[EvpnCommand], list[str]]:
    """Build registry entries from the extracted CLI-doc catalog.

    Returns `(derived, notes)`. `derived` excludes anything that collides with
    a curated entry — those stay authoritative.
    """
    curated_keys = {c.key for c in EVPN_COMMANDS}
    curated_templates = {c.template for c in EVPN_COMMANDS}
    derived: list[EvpnCommand] = []
    notes: list[str] = []
    seen: set[str] = set()

    for cc in cli_commands:
        params = {p.name.strip() for p in getattr(cc, "parameters", [])
                  if getattr(p, "name", "").strip()}
        is_config = getattr(cc, "kind", "") == "config"

        # A knob shared by both L2 services — `mac-limit` lists `l2-services
        # vpls` AND `l2-services evpn` as its command modes — must derive the
        # EVPN form only. VPLS is out of scope for the EVPN test plan (Eyal
        # Ozeri, batch-2 2026-07-07), and without this the resolver binds a
        # plan row to the VPLS constant.
        paths = list(getattr(cc, "mode_paths", None) or [])
        if not paths and getattr(cc, "mode_path", None):
            paths = [cc.mode_path]
        if any("evpn" in p for p in paths):
            paths = [p for p in paths if "vpls" not in p]
        prefix = _mode_prefix(paths[0] if paths else []) if is_config else ""

        for line in (getattr(cc, "syntax_lines", None) or []):
            line = line.strip()
            if not line:
                continue
            if line.startswith("no ") and not include_no_forms:
                continue
            for form in expand_syntax(line, params):
                template = f"{prefix} {form}".strip() if prefix else form
                if not template or template in curated_templates or template in seen:
                    continue
                key = _key_for(template)
                if key in curated_keys or key in seen:
                    continue
                suspect = ""
                if "unknow-mac-flooding" in template:
                    suspect = ("CLI doc spells this 'unknow-mac-flooding' "
                               "(missing 'n') in the syntax line; emitted "
                               "verbatim rather than silently corrected.")
                derived.append(EvpnCommand(
                    key=key,
                    template=template,
                    mode=CLI_CONFIGURE if is_config else CLI,
                    source=cc.name,
                    doc_syntax=line,
                    doc_suspect=suspect,
                ))
                seen.add(key)
                seen.add(template)

    notes.append(f"derived {len(derived)} command(s) from "
                 f"{len(cli_commands)} CLI-doc entries; "
                 f"{len(EVPN_COMMANDS)} curated entries kept authoritative")
    return derived, notes

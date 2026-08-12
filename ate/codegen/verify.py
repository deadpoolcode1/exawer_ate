"""Verify the command registry against a real device.

The pipeline used to end at "grounded in the documents". That is not the same
as "true". On 2026-08-11 the DUT overturned three decisions we had reasoned to
from the documents — including one we had resolved *against* the CLI doc using
three other agreeing sources, and got backwards:

    show evpn mac address-table   ->  syntax error: unknown argument
    show evpn mac-address-table   ->  works

So device verification is a stage, not an incident. `ate verify-commands` walks
the whole `EvpnCommands` registry and asks the device whether each command
exists, producing the list of templates to fix.

**It verifies by completion, never by execution.** For a template
`l2-services evpn %s mac-limit %s` it enters configuration mode and asks

    l2-services evpn X ?

then checks whether `mac-limit` appears in the completions. Executing registry
entries blind would mean running `clear ...` and configuration commands against
a live device to find out whether they parse, which is not an acceptable way to
answer the question. Completion is read-only, and the config-mode session is
discarded with `abort`.

A command the device does not offer is reported, never silently rewritten:
which spelling is right is a judgement about the product, and belongs to a
human who can see both the device and the documentation.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ate.codegen.capture import at_value_prompt
from ate.codegen.commands import all_commands

__all__ = ["VerifyReport", "VerifiedCommand", "probe_for", "verify_commands"]

SUPPORTED = "supported"
MISSING = "missing"
UNKNOWN = "unknown"

_PLACEHOLDER = "X"


@dataclass
class VerifiedCommand:
    key: str
    template: str
    probe: str
    expect: str
    status: str
    completions: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class VerifyReport:
    host: str = ""
    build: str = ""
    checked_at: str = ""
    results: list[VerifiedCommand] = field(default_factory=list)
    #: How often the shell had to be re-opened mid-sweep. Non-zero is not a
    #: failure — it is the guard working — but it belongs in the report.
    reconnects: int = 0

    def by_status(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.results:
            out[r.status] = out.get(r.status, 0) + 1
        return out

    def missing(self) -> list[VerifiedCommand]:
        return [r for r in self.results if r.status == MISSING]

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return p


def _is_placeholder(tok: str) -> bool:
    """Is this token a slot for an argument rather than CLI text?

    The registry spells slots two ways: `%s` (curated entries, which is what
    Java's `String.format` needs) and `<value>` / `<name>` (entries derived
    from the CLI doc, which keeps the doc's own notation). Both are arguments.

    Treating `<value>` as literal CLI text made five templates unverifiable:
    the probe looked for a token spelled `<value>` in the completion list,
    which no device will ever offer, so they reported `missing` on every build
    regardless of what the device actually supports.
    """
    return tok == "%s" or (tok.startswith("<") and tok.endswith(">"))


def probe_for(template: str) -> tuple[str, str] | None:
    """`(probe path, token to look for)` for a command template.

    Splits at the last *literal* token: that token is what the parent path's
    completion list must offer. `show evpn mac-address-table name %s` becomes
    ("show evpn mac-address-table", "name").
    """
    toks = template.split()
    idx = None
    for i in range(len(toks) - 1, -1, -1):
        if not _is_placeholder(toks[i]):
            idx = i
            break
    if idx is None or idx == 0:
        return None
    parent = " ".join(_PLACEHOLDER if _is_placeholder(t) else t
                      for t in toks[:idx])
    return parent, toks[idx]


_COMPLETION = re.compile(r"^\s{2,}(\S+)")

#: The device appends the CURRENT value of a leaf to its own name, with no
#: separator: `port-based[vlan-based]` is the token `port-based` plus the
#: current setting `vlan-based`. Compared raw, it never equals `port-based`
#: and the command reads as missing when it is present and correct.
_CURRENT_VALUE = re.compile(r"\[[^\]]*\]$")

#: A slot for a value the user must supply — `<1-250000>`, `<RT element>`.
#: Its presence means the node is a leaf, not a list of choices.
_FREE_VALUE = re.compile(r"^<.*>$")

#: The device did not recognise the PATH we probed, and answered with the
#: siblings of the node that does not exist.
_PATH_ABSENT = ("invalid input detected", "syntax error: expecting",
                "element does not exist")

#: The placeholder we substituted is not a legal KEY, so the probe never
#: reached the node under test:
#:
#:     routing bgp X vrf X neighbor X af-l2vpn ?
#:     syntax error: "X" is not a valid value.
#:
#: `af-l2vpn evpn` demonstrably exists on this build — with a real AS number
#: and a real neighbour address it lists `evpn` and `vpls`. Calling it
#: `missing` would send someone to fix a command that is already correct, so
#: this answer is `unknown`: the sweep could not ask the question.
_KEY_REJECTED = re.compile(r'"[^"]*" is not a valid value')


#: Noise that indents like a completion but is not one: the caret the CLI
#: draws under a syntax error, and the label on a leaf's current setting.
_NOT_A_COMPLETION = {"|", "<cr>", "-", "^", "Currently"}


def _completions(raw: str) -> list[str]:
    """Tokens offered by a `?` completion listing, in order and deduplicated."""
    out: list[str] = []
    for line in raw.splitlines():
        if "Possible completions" in line or line.strip().startswith("Description:"):
            continue
        m = _COMPLETION.match(line)
        if not m:
            continue
        tok = _CURRENT_VALUE.sub("", m.group(1))
        if tok and tok not in _NOT_A_COMPLETION and tok not in out:
            out.append(tok)
    return out


def _verdict(raw: str, expect: str, comps: list[str]) -> tuple[str, str]:
    """`(status, note)` for one probe, from what the device actually said.

    Four distinguishable answers, and conflating them is what previously made
    this report unusable:

    * the path itself is not in the data model  -> missing, and say so;
    * the device is asking for a leaf VALUE     -> the parent exists. Whether
      `expect` is right is answerable only when the leaf enumerates its
      choices; for `<1-250000>` it is not answerable by completion at all, and
      `unknown` is the honest verdict;
    * a completion list came back               -> the plain case;
    * nothing recognisable                      -> unknown, never "missing".
    """
    low = raw.lower()
    if _KEY_REJECTED.search(raw):
        return UNKNOWN, ("the probe could not be asked: a placeholder in the "
                         "path is not a legal key on this device (it needs a "
                         "real AS number / address / object name)")
    if any(m in low for m in _PATH_ABSENT):
        return MISSING, ("the probed path does not exist on this build; the "
                         "device answered with the siblings of the missing node")
    if at_value_prompt(raw):
        if any(_FREE_VALUE.match(c) for c in comps):
            return UNKNOWN, ("leaf takes a free value "
                             f"({', '.join(c for c in comps if _FREE_VALUE.match(c))})"
                             " — a specific value cannot be confirmed by completion")
        if expect in comps:
            return SUPPORTED, "enumerated leaf; the device offers this value"
        return MISSING, ("enumerated leaf; the device offers "
                         f"{', '.join(comps) or '(nothing)'}")
    if comps:
        return (SUPPORTED, "") if expect in comps else (MISSING, "")
    return (MISSING, "") if "syntax error" in low else (UNKNOWN, "no completions returned")


def _drain(chan) -> None:
    """Discard anything still in the channel buffer.

    Without this the reader can match a prompt left over from the *previous*
    probe and return immediately, so each result is attributed to the wrong
    command — a silent shift that produced `l2-services evpn X ?` -> the single
    token `port-based`, and a report full of false "missing" verdicts. A
    verifier that lies about which commands exist is worse than no verifier.
    """
    import time  # noqa: PLC0415

    deadline = time.time() + 3.0
    while time.time() < deadline:
        if chan.recv_ready():
            chan.recv(65535)
            deadline = time.time() + 0.4
        else:
            time.sleep(0.1)


#: Ctrl-C. Escapes an interactive value prompt WITHOUT answering it — the
#: device replies "Error: user aborted" and returns to the CLI prompt.
#: Answering would be a write to a live device, which this stage must never do.
_ESCAPE = "\x03"


class _Session:
    """One SSH shell on the device, re-openable.

    `verify-commands` reads ~120 completions through a single shell. If that
    shell ever ends up in a state the reader does not recognise, every verdict
    after it describes the wrong command. Rather than hope that never happens,
    the sweep checks after each probe that the device is back at its prompt,
    and re-opens the shell when it is not.
    """

    def __init__(self, host, user, password, jump):
        self._args = (host, user, password, jump)
        self.jump_client = None
        self.cli = None
        self.chan = None
        self.reconnects = 0
        self._open()

    def _open(self):
        import paramiko  # noqa: PLC0415

        from ate.codegen.capture import _read_until_prompt  # noqa: PLC0415

        host, user, password, jump = self._args
        sock = None
        if jump:
            j_user, _, j_host = jump.partition("@")
            self.jump_client = paramiko.SSHClient()
            self.jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.jump_client.connect(j_host, username=j_user, timeout=30)
            sock = self.jump_client.get_transport().open_channel(
                "direct-tcpip", (host, 22), ("127.0.0.1", 0))

        self.cli = paramiko.SSHClient()
        self.cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.cli.connect(host, username=user, password=password, timeout=30,
                         allow_agent=False, look_for_keys=False, sock=sock)
        self.chan = self.cli.invoke_shell(width=512, height=4096)
        _read_until_prompt(self.chan, timeout=30)
        self.chan.send("session screen-width 512 ; session screen-length 3200\n")
        _read_until_prompt(self.chan, timeout=20)

    def close(self):
        for x in (self.chan, self.cli, self.jump_client):
            try:
                if x is not None:
                    x.close()
            except Exception:  # noqa: BLE001 - closing a dead socket is not news
                pass

    def resynced(self) -> bool:
        """Is the device back at its prompt, answering for itself?

        Asked by running a command with a known answer. If the channel is one
        response behind, this reads the PREVIOUS answer and the mismatch is
        visible — which is the whole point.
        """
        from ate.codegen.capture import _PROMPT, _read_until_prompt  # noqa: PLC0415

        _drain(self.chan)
        try:
            self.chan.send("show session\n")
            raw = _read_until_prompt(self.chan, timeout=15)
        except Exception:  # noqa: BLE001 - a dead channel is a failed resync
            return False
        return bool(_PROMPT.search(raw)) and "show session" in raw

    def recover(self) -> None:
        """Get back to a usable prompt, re-opening the shell if needed."""
        from ate.codegen.capture import _read_until_prompt  # noqa: PLC0415

        try:
            self.chan.send(_ESCAPE)
            _read_until_prompt(self.chan, timeout=10)
            self.chan.send("abort\n")
            _read_until_prompt(self.chan, timeout=10)
            if self.resynced():
                return
        except Exception:  # noqa: BLE001 - fall through to a fresh shell
            pass
        self.close()
        self.reconnects += 1
        self._open()


def verify_commands(host: str, user: str, password: str,
                    jump: str | None = None) -> VerifyReport:
    """Ask the device which registry commands it actually offers."""
    import time  # noqa: PLC0415

    from ate.codegen.capture import _PROMPT, _read_until_prompt  # noqa: PLC0415

    sess = _Session(host, user, password, jump)

    sess.chan.send("show version\n")
    build = " ".join(
        ln.strip() for ln in _read_until_prompt(sess.chan, 30).splitlines()
        if ln.strip() and "show version" not in ln and not _PROMPT.search(ln)
    )[:120]

    report = VerifyReport(host=host, build=build,
                          checked_at=time.strftime("%Y-%m-%dT%H:%M:%S"))

    oper, conf = [], []
    seen: set[str] = set()
    for c in all_commands():
        pr = probe_for(c.template)
        if pr is None or c.template in seen:
            continue
        seen.add(c.template)
        (conf if c.mode.endswith("CLI_CONFIGURE") else oper).append((c, pr))

    def run(batch, in_config: bool) -> None:
        for c, (parent, expect) in batch:
            chan = sess.chan
            _drain(chan)
            if in_config:
                # Each config probe gets its OWN configure/abort cycle.
                #
                # A `?` completion on a config path both LISTS and DESCENDS,
                # and the descent creates the node in the candidate
                # configuration. Sharing one session across ~57 probes let that
                # candidate accumulate until the completions no longer
                # reflected a clean device — `l2-services evpn X ?` stopped
                # offering `mac-limit`, which the device demonstrably has.
                # `top` alone did not fix it because the candidate persisted.
                chan.send("configure\n")
                _read_until_prompt(chan, timeout=20)
                _drain(chan)
            chan.send(f"{parent} ?\n")
            raw = _read_until_prompt(chan, timeout=20)
            comps = _completions(raw)
            status, note = _verdict(raw, expect, comps)

            # Leave the channel exactly as we found it, and PROVE it. A probe
            # that ends in a value prompt has the device waiting for input:
            # anything sent next is read as the answer, which both writes to a
            # live device and shifts every later answer onto the wrong command.
            if at_value_prompt(raw):
                chan.send(_ESCAPE)
                _read_until_prompt(chan, timeout=15)
            if in_config:
                chan.send("abort\n")
                _read_until_prompt(chan, timeout=20)
            if not sess.resynced():
                sess.recover()
                note = (note + " | " if note else "") + \
                    "channel was recovered after this probe"

            report.results.append(VerifiedCommand(
                key=c.key, template=c.template, probe=f"{parent} ?",
                expect=expect, status=status, completions=comps[:40], note=note))
            print(f"  [{status:9}] {c.key[:56]}", flush=True)

    run(oper, False)
    run(conf, True)   # each config probe wraps itself in configure/abort

    report.reconnects = sess.reconnects
    sess.close()
    return report

"""Capture real device output and turn it into test expectations.

This is the last unclosed stage of the pipeline. Everything upstream runs:
documents → requirements → test plan → typed steps → compiling Java, plus the
per-scenario device configuration. But 15 of 33 steps ship with *empty*
expectations, because the expected shape of `show evpn global` or
`show evpn mac address-table` output cannot be known from the documents — the
CLI doc gives syntax, not layout. Guessing it is the one thing this project
must never do.

So: connect to a device, run exactly the commands the generated scripts need,
and keep what comes back. That closes the loop

    documents → plan → code → DEVICE → expectations → code

and it is the mechanism that converts a suite of warnings into a suite of
assertions the moment an EVPN-capable build exists.

Three properties it must have, because each is a way to manufacture a false
pass:

  * **A command the device rejects is never an expectation.** The Exaware CLI
    answers an unknown node with `syntax error: element does not exist`.
    Recording that as "expected output" would produce a test that passes by
    asserting the feature is missing. Those are classified UNSUPPORTED and
    excluded from the emitted expectations.
  * **Empty output is not success.** A command that runs but returns nothing
    is EMPTY, not OK — on a device with no service configured that is the
    normal answer, and freezing it as the expectation would assert emptiness
    forever.
  * **Captures are stamped.** Output depends on the software build and on what
    was configured at the time, so every capture records the host, the build
    and the command that produced it. An expectation whose provenance is
    unknown is not reviewable.

The lab is not reachable from a laptop, so `jump` opens the session through the
dev box (`direct-tcpip`), which is how every other lab access in this project
works.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ate.codegen.commands import all_commands
from ate.codegen.script_ir import StepKind, TestScript

__all__ = ["CaptureSession", "CapturedCommand", "capture_for_scripts",
           "capture_on_channel", "commands_needed"]

#: The CLI prompt, in every shape this lab produces:
#:
#:     router#                          pc-3080 (LAB 22)
#:     router[2026-08-11-18:38:07]#     pc-3021 (LAB 22) — timestamp prompt on
#:     router(config)#                  configuration mode
#:     router[...](config)#             both at once
#:
#: The timestamp is a per-box CLI setting, not a property of the software. The
#: first version of this pattern required the `]`, so on a box without the
#: timestamp NOTHING ever matched: every read ran to its full timeout and
#: returned a partial buffer, and `verify-commands` / `capture` hung instead of
#: failing. Anchor on the line start and treat the bracket and the mode
#: parenthesis as optional, so the shape of someone's prompt cannot silently
#: decide whether the device loop works.
_PROMPT = re.compile(
    r"(?:^|[\r\n])[A-Za-z][\w.\-]*"     # hostname
    r"(?:\[[^\]\r\n]*\])?"              # optional [timestamp]
    r"(?:\([^)\r\n]*\))?"               # optional (config), (config-...)
    r"#[ \t]*$")

#: The device asking for a leaf VALUE rather than returning to the prompt.
#: Both shapes below are verbatim from 8.7.0 LAB 22 on pc-3080:
#:
#:     [port-based,vlan-based]:                          enumerated leaf
#:     (<1-250000>    maximum MAC learned (default 65520)
#:       Currently configured):                          range leaf, multi-line
#:
#: The common, reliable part is a colon followed by at least one space at the
#: very end of the buffer. Requiring the space matters: a chunk boundary can
#: fall right after `Possible completions:` (no space, then a newline), and
#: matching that would end the read in the middle of a listing.
_VALUE_PROMPT = re.compile(r"[^\r\n]:[ \t]+$")

#: How the CLI reports a node that is not in its data model. Matching these is
#: what separates "the feature is absent" from "the feature answered".
_REJECTED = (
    "syntax error",
    "% invalid input",
    "unknown command",
)

#: The command PARSED and ran; there is simply nothing to show yet. That is
#: EMPTY, not UNSUPPORTED — the distinction matters because "unsupported" sends
#: someone to fix a command that is already correct, while "empty" says the
#: device needs state (a peer, traffic, a configured EVI) before this
#: expectation can be captured. Either way it never becomes an expectation.
_NO_ENTRIES = ("no entries found",)

#: A MAC address, in the form these tables print.
_MAC = re.compile(r"\b[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}\b")

OK = "ok"
EMPTY = "empty"
UNSUPPORTED = "unsupported"

def _by_key() -> dict:
    """Built per call: derived entries are installed at generation time."""
    return {c.key: c for c in all_commands()}


@dataclass
class CapturedCommand:
    """One command's real output, with enough provenance to review it."""

    expect_key: str
    command: str
    status: str
    lines: list[str] = field(default_factory=list)
    raw: str = ""
    note: str = ""

    @property
    def usable(self) -> bool:
        """Only OK captures may become an expectation."""
        return self.status == OK


@dataclass
class CaptureSession:
    host: str = ""
    build: str = ""
    captured_at: str = ""
    results: list[CapturedCommand] = field(default_factory=list)

    def usable(self) -> dict[str, list[str]]:
        return {c.expect_key: c.lines for c in self.results if c.usable}

    def by_status(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.results:
            out[c.status] = out.get(c.status, 0) + 1
        return out

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: str | Path) -> CaptureSession:
        """Read back a saved session, so codegen can compile it into the suite.

        Without this the device loop stopped one step short of useful: capture
        wrote a file and nothing read it, so every expectation in the generated
        suite shipped empty and every verification step reported a warning
        instead of asserting. The captured output existed and simply never
        reached the code.
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            host=data.get("host", ""),
            build=data.get("build", ""),
            captured_at=data.get("captured_at", ""),
            results=[CapturedCommand(**r) for r in data.get("results", [])],
        )


def commands_needed(scripts: list[TestScript]) -> list[tuple[str, str]]:
    """`(expect_key, rendered CLI)` for every step that asserts show output.

    Steps with no `expect_key` are skipped: nothing would consume the capture.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for sc in scripts:
        for st in sc.steps:
            if st.kind not in (StepKind.VERIFY_CLI, StepKind.VERIFY_ROUTE):
                continue
            if not st.expect_key or not st.command or st.expect_key in seen:
                continue
            cmd = _by_key().get(st.command)
            if cmd is None or not cmd.template:
                continue
            try:
                text = cmd.template % tuple(st.args)
            except TypeError:
                continue
            seen.add(st.expect_key)
            out.append((st.expect_key, text))
    return out


def _classify(raw: str, command: str) -> tuple[str, list[str], str]:
    """Decide whether output is usable, empty, or a rejection."""
    body = [ln.rstrip() for ln in raw.splitlines()]
    # Drop the echoed command and the trailing prompt.
    body = [ln for ln in body
            if ln.strip() and ln.strip() != command.strip()
            and not _PROMPT.search(ln)]
    joined = " ".join(body).lower()
    for marker in _REJECTED:
        if marker in joined:
            return UNSUPPORTED, [], f"device rejected the command: {marker!r}"
    for marker in _NO_ENTRIES:
        if marker in joined:
            return EMPTY, [], ("command ran but the device has no entries yet "
                               "— needs state (peer / traffic / configured EVI)")
    if not body:
        return EMPTY, [], "command ran but returned nothing"
    if "mac-address-table" in command and not any(_MAC.search(ln) for ln in body):
        # The table printed its legend and its header and no rows. Recording
        # that as an expectation would produce an assertion that passes on any
        # device, working or not: the legend is printed whether or not a single
        # MAC was ever learnt. `capture` exists to refuse exactly this.
        #
        # Seen on pc-3080 (8.7.0 LAB 22) for the FLOW-030 learning steps: the
        # EVI was configured, but with no traffic offered there was nothing to
        # learn, so every row was legend.
        return EMPTY, [], ("the MAC table printed its legend but no MAC "
                           "addresses — nothing has been learnt yet, so there "
                           "is no expectation here that could ever fail")
    return OK, body, ""


def _read_until_prompt(chan, timeout: float = 60.0) -> str:
    """Read until the device is waiting for us again.

    There are TWO states that mean "waiting", and only recognising the first
    is what made the configuration half of `verify-commands` untrustworthy:

      1. the CLI prompt — the command finished;
      2. an interactive *value* prompt — a `?` landed on a leaf and the device
         is now asking for the value, e.g.

             l2-services evpn X service-type ?
             Possible completions:
               vlan-based
               port-based[vlan-based]
             [port-based,vlan-based]:        <- waiting, and no `#` will come

    Treating (2) as "still talking" burned the full timeout, returned a partial
    buffer, and left the answer to sit in the channel until the NEXT probe read
    it — so every later verdict described the wrong command. Stop on either.
    """
    buf, last = "", time.time()
    while time.time() - last < timeout:
        if chan.recv_ready():
            buf += chan.recv(65535).decode("utf-8", "replace")
            last = time.time()
            if _PROMPT.search(buf) or _VALUE_PROMPT.search(buf):
                # Settle: a chunk boundary can land mid-line and look like a
                # prompt ("Format: " inside a description). If more arrives,
                # it was not the end.
                time.sleep(0.3)
                if chan.recv_ready():
                    while chan.recv_ready():
                        buf += chan.recv(65535).decode("utf-8", "replace")
                    if not (_PROMPT.search(buf) or _VALUE_PROMPT.search(buf)):
                        continue
                return buf
        else:
            time.sleep(0.15)
    return buf


def at_value_prompt(raw: str) -> bool:
    """Is the device sitting in an interactive value prompt?

    The channel must be escaped before anything else is sent, or the next
    command is consumed as the ANSWER to this prompt — which is both a write
    to a live device and a silent desync.
    """
    return bool(raw) and not _PROMPT.search(raw) and bool(_VALUE_PROMPT.search(raw))


def capture_on_channel(chan, scripts: list[TestScript], host: str = "",
                       build: str = "", now: str = "") -> CaptureSession:
    """Drive an already-open shell channel. Split out from the connect path so
    the orchestration — which command runs, how its answer is classified, what
    becomes an expectation — is testable without a device."""
    session = CaptureSession(host=host, build=build, captured_at=now)
    for expect_key, command in commands_needed(scripts):
        chan.send(command + "\n")
        raw = _read_until_prompt(chan, timeout=120)
        status, lines, note = _classify(raw, command)
        session.results.append(CapturedCommand(
            expect_key=expect_key, command=command, status=status,
            lines=lines, raw=raw.strip()[:4000], note=note))
    return session


def capture_for_scripts(scripts: list[TestScript], host: str, user: str,
                        password: str, jump: str | None = None,
                        ) -> CaptureSession:
    """Run each needed command on `host` and classify what comes back.

    `jump` is `user@host` of a box that can reach the device — the lab is not
    routable from a laptop.
    """
    import paramiko  # noqa: PLC0415  (optional dependency, only used here)

    sock = None
    jump_client = None
    if jump:
        j_user, _, j_host = jump.partition("@")
        jump_client = paramiko.SSHClient()
        jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        jump_client.connect(j_host, username=j_user, timeout=30)
        sock = jump_client.get_transport().open_channel(
            "direct-tcpip", (host, 22), ("127.0.0.1", 0))

    # Lab gear runs old SSH servers — this DUT offers only SHA-1 `ssh-rsa`
    # host keys, which paramiko 3+ removed from its defaults, and refuses the
    # connection with "no acceptable host key". Re-enable it on the transport
    # rather than pinning an ancient paramiko: the scope is this one session to
    # a device on a private lab network, not the library's global defaults.
    transport = paramiko.Transport(sock if sock is not None else (host, 22))
    transport._preferred_keys = (
        "rsa-sha2-512", "rsa-sha2-256", "ssh-rsa",
        "ssh-ed25519", "ecdsa-sha2-nistp256",
    )
    # paramiko 5 also dropped "ssh-rsa" from the key-type table, so once it is
    # negotiated the reply cannot be parsed. Restore the mapping on this
    # transport only.
    transport._key_info = dict(transport._key_info)
    transport._key_info.setdefault("ssh-rsa", paramiko.RSAKey)
    transport.connect(username=user, password=password)
    chan = transport.open_session()
    chan.get_pty(width=512, height=4096)
    chan.invoke_shell()
    _read_until_prompt(chan, timeout=30)

    # Match the framework: widen the screen so long table rows are not wrapped
    # into the expectation, and disable pagination.
    for setup in ("session screen-width 512 ; session screen-length 3200",
                  "set session pagination disable"):
        chan.send(setup + "\n")
        _read_until_prompt(chan, timeout=20)

    chan.send("show version\n")
    build = " ".join(
        ln.strip() for ln in _read_until_prompt(chan, 30).splitlines()
        if ln.strip() and "show version" not in ln and not _PROMPT.search(ln)
    )[:120]

    session = capture_on_channel(
        chan, scripts, host=host, build=build,
        now=time.strftime("%Y-%m-%dT%H:%M:%S"))

    chan.close()
    transport.close()
    if jump_client is not None:
        jump_client.close()
    return session

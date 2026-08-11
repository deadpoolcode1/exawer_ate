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
           "commands_needed"]

#: `router[2026-08-11-18:38:07]# `, and `...(config)#` in configuration mode.
_PROMPT = re.compile(r"\][^\r\n]*#\s*$")

#: How the CLI reports a node that is not in its data model. Matching these is
#: what separates "the feature is absent" from "the feature answered".
_REJECTED = (
    "syntax error",
    "% invalid input",
    "unknown command",
    "no entries found",          # ran, but there is nothing — not an error
)

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
    if not body:
        return EMPTY, [], "command ran but returned nothing"
    return OK, body, ""


def _read_until_prompt(chan, timeout: float = 60.0) -> str:
    buf, last = "", time.time()
    while time.time() - last < timeout:
        if chan.recv_ready():
            buf += chan.recv(65535).decode("utf-8", "replace")
            last = time.time()
            if _PROMPT.search(buf):
                time.sleep(0.3)
                while chan.recv_ready():
                    buf += chan.recv(65535).decode("utf-8", "replace")
                return buf
        else:
            time.sleep(0.15)
    return buf


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

    session = CaptureSession(
        host=host, build=build,
        captured_at=time.strftime("%Y-%m-%dT%H:%M:%S"))

    for expect_key, command in commands_needed(scripts):
        chan.send(command + "\n")
        raw = _read_until_prompt(chan, timeout=120)
        status, lines, note = _classify(raw, command)
        session.results.append(CapturedCommand(
            expect_key=expect_key, command=command, status=status,
            lines=lines, raw=raw.strip()[:4000], note=note))

    chan.close()
    transport.close()
    if jump_client is not None:
        jump_client.close()
    return session

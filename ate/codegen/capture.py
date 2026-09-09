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
from ate.codegen.fake_pass import (
    has_furniture_marker,
    is_furniture,
    is_structural,
)
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

#: Padding bytes the device pushes into fixed-width fields. `show bgp l2vpn
#: evpn table evi detail` on 8.7.0 LAB 935 pads the Originating Router's IP
#: with 35 NULs and the Flags field with two. They are invisible in a terminal
#: and lethal in an expectation: frozen into a Java string literal they make
#: the assertion match nothing, for a reason nobody can see by reading it.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

#: Lines whose value is different every time the command runs. An expectation
#: containing one can never match again, so it is not an assertion, it is a
#: time bomb that fails the next healthy run. Seen on pc-3099, 2026-09-09:
#: "Last update: Wed Sep  9 12:02:29 2026" went straight into a Type-3
#: expectation.
_VOLATILE = re.compile(
    r"^\s*(last\s+update|up[/ ]?down\s+time|uptime|elapsed|"
    r"last\s+(?:change|flap|state\s+change)|current\s+time|"
    r"time\s+since)\b",
    re.I)

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


def topology_mismatches(captures: dict, lab) -> dict[str, str]:
    """Captured expectations that were taken on a DIFFERENT topology.

    An expectation is device output frozen into an assertion, and device
    output names interfaces. Change the rig - a VLAN, a port, which link is
    the core - and yesterday's capture asserts lines the device is now right
    not to print. STATUS.md has carried this as an honest limit for weeks
    ("captures are topology-specific, and silently so"); the 2026-09-08 move
    off VLAN 3380 makes it certain rather than possible, so it is checked.

    The test is deliberately narrow: a captured line that names a
    sub-interface (`x-eth0/0/18.3380`) whose suffix is not one of THIS
    profile's attachment-circuit VLANs cannot be describing this rig. Lines
    with no sub-interface in them are left alone - they may well still hold.

    Returns {expect_key: reason}. The caller drops those captures and says so,
    rather than asserting them: a stale expectation fails a run that is
    working, which teaches everyone to distrust the suite.
    """
    import re  # noqa: PLC0415

    ours = {str(v) for v in lab.ac_vlans}
    out: dict[str, str] = {}
    for key, cap in (captures or {}).items():
        seen: set[str] = set()
        for line in cap.get("lines") or []:
            # `\\?` because a line may arrive raw off the device or already
            # escaped as a regex on its way into EvpnParams; both spellings
            # describe the same sub-interface.
            seen.update(re.findall(
                r"\b[a-z]+-?eth\s?[\d/]+\\?\.(\d+)\b", line))
        stale = sorted(seen - ours)
        if stale and not (seen & ours):
            out[key] = (
                f"captured on sub-interface VLAN(s) {', '.join(stale)}, but "
                f"this profile's circuits are on {', '.join(sorted(ours))} - "
                "re-capture on this topology")
    return out


def route_type_mismatches(captures: dict, steps=None) -> dict[str, str]:
    """Captures that show a DIFFERENT route type from the one the step is about.

    Found on pc-3099, 2026-09-09. With the EVI configured but no traffic
    offered and no BGP peer, `show bgp l2vpn evpn table evi detail` prints
    exactly one route - the DUT's own Type-3 IMET:

        Type=3: VLAN-ID=0, Originating Router's IP=29.30.30.30
          MPLS Label= 32768 ... Weight: 32768

    That is a real, correct, locally-originated route, so the capture is not
    empty and passes every check we had. But three of the steps that captured
    it are about **Type-2**: "AC1's MACs are advertised as Type-2", "AC2's
    MACs are advertised", "the Type-2 route is withdrawn after aging". Freezing
    a Type-3 line into those steps produces an assertion that passes on a
    device which has learnt no MAC at all - the fake-pass rule arriving through
    a capture that is individually valid.

    So: if a step is about a route type, the captured output must contain that
    route type. The step's own text is the source of the intent, because that
    text is what a reviewer reads in the run report.

    Returns {expect_key: reason}; the caller drops those captures and says so.
    """
    wanted = re.compile(r"\btype[- ]?([23])\b", re.I)
    out: dict[str, str] = {}
    by_key = {st.expect_key: st for st in (steps or []) if st.expect_key}
    for key, cap in (captures or {}).items():
        st = by_key.get(key)
        if st is None:
            continue
        m = wanted.search(st.text or "")
        if not m:
            continue
        want = m.group(1)
        body = "\n".join(cap.get("lines") or [])
        if not body:
            continue
        found = set(re.findall(r"Type=([0-9]+)", body))
        if found and want not in found:
            out[key] = (
                f"the step is about a Type-{want} route but the captured "
                f"output contains only Type-{'/'.join(sorted(found))}. On a "
                "rig with no traffic and no peer the only route present is "
                "the DUT's own Type-3 IMET; asserting it here would pass on a "
                "device that has learnt nothing. Re-capture with traffic "
                "running.")
    return out


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


def commands_needed(scripts: list[TestScript],
                    ac_map: dict[str, str] | None = None,
                    ) -> list[tuple[str, str]]:
    """`(expect_key, rendered CLI)` for every step that asserts show output.

    Steps with no `expect_key` are skipped: nothing would consume the capture.

    `ac_map` replaces the lab profile's PLACEHOLDER interface names with what
    the testbed actually calls them. Without it capture asks the device about
    `agg-eth-1.100`, which exists on no rig here, so the answer is empty and
    the expectation is silently lost - while the generated Java asks the same
    question through `acInterface(i)`, which DOES resolve from the SUT. The
    two halves were asking different questions and only the capture half came
    back blank, so the step just quietly never got an expectation.
    """
    subs = ac_map or {}
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
            for placeholder, real in subs.items():
                text = text.replace(placeholder, real)
            seen.add(st.expect_key)
            out.append((st.expect_key, text))
    return out


def _classify(raw: str, command: str) -> tuple[str, list[str], str]:
    """Decide whether output is usable, empty, or a rejection."""
    body = [_CONTROL.sub("", ln).rstrip() for ln in raw.splitlines()]
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
    # The general form of the rule above, for every other table.
    #
    # The MAC-table check was command-specific, so the same defect walked in
    # again through a different command: `show bgp l2vpn evpn table evi detail`
    # prints a three-line flags legend plus "EVI Name = evi-1" and no routes,
    # and that was recorded as a usable expectation and asserted on. Anything
    # whose every line is furniture — rule, header, legend, or an echo of the
    # scope we asked about — is refused here regardless of which command
    # produced it.
    if all(is_structural(ln) for ln in body) and has_furniture_marker(body):
        return EMPTY, [], ("the command printed only its legend, headers and "
                           "the scope it was asked about — no rows, so there "
                           "is no expectation here that could ever fail")
    # Keep the state-bearing lines only. `raw` still holds the full answer for
    # provenance; what becomes an ASSERTION is just the part that could differ
    # between a working device and a broken one.
    kept = [ln for ln in body
            if not is_furniture(ln) and not _VOLATILE.match(ln)]
    if not kept:
        return EMPTY, [], ("every line was either furniture or a value that "
                           "changes on each run - nothing here could be "
                           "asserted twice")
    return OK, kept, ""


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
                       build: str = "", now: str = "",
                       ac_map: dict[str, str] | None = None) -> CaptureSession:
    """Drive an already-open shell channel. Split out from the connect path so
    the orchestration — which command runs, how its answer is classified, what
    becomes an expectation — is testable without a device."""
    session = CaptureSession(host=host, build=build, captured_at=now)
    for expect_key, command in commands_needed(scripts, ac_map):
        chan.send(command + "\n")
        raw = _read_until_prompt(chan, timeout=120)
        status, lines, note = _classify(raw, command)
        session.results.append(CapturedCommand(
            expect_key=expect_key, command=command, status=status,
            lines=lines, raw=raw.strip()[:4000], note=note))
    return session


def capture_for_scripts(scripts: list[TestScript], host: str, user: str,
                        password: str, jump: str | None = None,
                        ac_map: dict[str, str] | None = None,
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
        now=time.strftime("%Y-%m-%dT%H:%M:%S"), ac_map=ac_map)

    chan.close()
    transport.close()
    if jump_client is not None:
        jump_client.close()
    return session

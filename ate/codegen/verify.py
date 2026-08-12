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


@dataclass
class VerifyReport:
    host: str = ""
    build: str = ""
    checked_at: str = ""
    results: list[VerifiedCommand] = field(default_factory=list)

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


def probe_for(template: str) -> tuple[str, str] | None:
    """`(probe path, token to look for)` for a command template.

    Splits at the last *literal* token: that token is what the parent path's
    completion list must offer. `show evpn mac-address-table name %s` becomes
    ("show evpn mac-address-table", "name").
    """
    toks = template.split()
    idx = None
    for i in range(len(toks) - 1, -1, -1):
        if toks[i] != "%s":
            idx = i
            break
    if idx is None or idx == 0:
        return None
    parent = " ".join(_PLACEHOLDER if t == "%s" else t for t in toks[:idx])
    return parent, toks[idx]


_COMPLETION = re.compile(r"^\s{2,}(\S+)")


def _completions(raw: str) -> list[str]:
    """Tokens offered by a `?` completion listing."""
    out: list[str] = []
    for line in raw.splitlines():
        if "Possible completions" in line or line.strip().startswith("Description:"):
            continue
        m = _COMPLETION.match(line)
        if m and m.group(1) not in ("|", "<cr>", "-"):
            out.append(m.group(1))
    return out


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


def verify_commands(host: str, user: str, password: str,
                    jump: str | None = None) -> VerifyReport:
    """Ask the device which registry commands it actually offers."""
    import time  # noqa: PLC0415

    from ate.codegen.capture import _PROMPT, _read_until_prompt  # noqa: PLC0415

    import paramiko  # noqa: PLC0415

    sock = None
    jump_client = None
    if jump:
        j_user, _, j_host = jump.partition("@")
        jump_client = paramiko.SSHClient()
        jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        jump_client.connect(j_host, username=j_user, timeout=30)
        sock = jump_client.get_transport().open_channel(
            "direct-tcpip", (host, 22), ("127.0.0.1", 0))

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(host, username=user, password=password, timeout=30,
                allow_agent=False, look_for_keys=False, sock=sock)
    chan = cli.invoke_shell(width=512, height=4096)
    _read_until_prompt(chan, timeout=30)
    chan.send("session screen-width 512 ; session screen-length 3200\n")
    _read_until_prompt(chan, timeout=20)

    chan.send("show version\n")
    build = " ".join(
        ln.strip() for ln in _read_until_prompt(chan, 30).splitlines()
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
            _drain(chan)
            if in_config:
                # A `?` completion on a config path DESCENDS into that submode
                # — the prompt becomes (config-l2-services-evpn-X). Without
                # returning to the top first, every later probe is evaluated
                # relative to wherever the previous one landed and the whole
                # sweep drifts into nonsense.
                chan.send("top\n")
                _read_until_prompt(chan, timeout=15)
                _drain(chan)
            chan.send(f"{parent} ?\n")
            raw = _read_until_prompt(chan, timeout=20)
            comps = _completions(raw)
            if comps:
                status = SUPPORTED if expect in comps else MISSING
            else:
                status = MISSING if "syntax error" in raw.lower() else UNKNOWN
            report.results.append(VerifiedCommand(
                key=c.key, template=c.template, probe=f"{parent} ?",
                expect=expect, status=status, completions=comps[:40]))
            print(f"  [{status:9}] {c.key[:56]}", flush=True)

    run(oper, False)
    if conf:
        chan.send("configure\n")
        _read_until_prompt(chan, timeout=30)
        run(conf, True)
        # Discard the candidate configuration this session may have created.
        chan.send("abort\n")
        _read_until_prompt(chan, timeout=30)

    chan.close()
    cli.close()
    if jump_client is not None:
        jump_client.close()
    return report

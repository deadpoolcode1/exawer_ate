"""Minimal Exaware CLI driver.

Two things the first version got wrong, both of which cost a run:
  * the prompt is not always `name[timestamp]#` - config mode adds a suffix -
    so anchor on a trailing `#` after stripping escapes;
  * `commit` prints an ASCII spinner (`|/-\`) before its verdict, which the
    naive reader treated as content and never matched a prompt on.
"""
import re, time, paramiko

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
SPIN = re.compile(r"[|/\-\\]{2,}")
PROMPT = re.compile(r"[^\r\n]*#\s*$")


def _clean(s):
    return SPIN.sub("", ANSI.sub("", s.replace("\r", "")))


class Dut:
    def __init__(self, host, user="admin", pw="admin", timeout=30):
        self.c = paramiko.SSHClient()
        self.c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.c.connect(host, username=user, password=pw, timeout=timeout,
                       look_for_keys=False, allow_agent=False)
        self.sh = self.c.invoke_shell(width=250, height=10000)
        self._read(10)

    def _read(self, limit):
        out, end, quiet = "", time.time() + limit, 0
        while time.time() < end:
            if self.sh.recv_ready():
                out += self.sh.recv(65535).decode(errors="replace")
                quiet = 0
                if PROMPT.search(_clean(out)):
                    # let a trailing burst land before deciding we are done
                    time.sleep(0.4)
                    if not self.sh.recv_ready():
                        break
            else:
                time.sleep(0.2)
                quiet += 0.2
        return _clean(out)

    def run(self, cmd, limit=30):
        while self.sh.recv_ready():          # drain, per the skill's warning
            self.sh.recv(65535)
        self.sh.send(cmd + "\n")
        raw = self._read(limit)
        body = [l.rstrip() for l in raw.splitlines()
                if l.strip() and l.strip() != cmd.strip()
                and not PROMPT.search(l.rstrip())]
        return "\n".join(body)

    def close(self):
        try:
            self.c.close()
        except Exception:
            pass

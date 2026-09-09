"""Pin the ONL hostname for the duration of a run, and truncate the syslog.

Two device facts make this necessary, both recorded in the evidence:
  * Exaware's bring-up matches the ONL shell by the literal "@localhost"
    (CmpCliSession.java:69, ONL_LOCALHOST_PROMPT_REGEX). Something rewrites
    /etc/hostname to "router" a few minutes after boot, so setting the
    hostname once before a run is a race the run can lose.
  * their bring-up pages /var/log/syslog, so it is truncated first.

Usage: onlctl.py pin | unpin | status
"""
import sys
import warnings

import paramiko

warnings.filterwarnings("ignore")

ONL = "10.3.99.10"
WATCHDOG = "/tmp/pin_hostname.sh"


def sh():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(ONL, username="root", password="root", timeout=30,
              look_for_keys=False, allow_agent=False)
    return c


def run(c, cmd):
    i, o, e = c.exec_command(cmd)
    return (o.read().decode() + e.read().decode()).strip()


def pin(c):
    run(c, "pkill -f pin_hostname.sh")
    script = (
        "#!/bin/sh\n"
        "while true; do\n"
        "  [ \"$(hostname)\" = localhost ] || hostname localhost\n"
        "  sleep 5\n"
        "done\n"
    )
    run(c, f"cat > {WATCHDOG} <<'EOF'\n{script}EOF\nchmod +x {WATCHDOG}")
    run(c, f"setsid nohup {WATCHDOG} >/dev/null 2>&1 < /dev/null &")
    run(c, ": > /var/log/syslog")
    print("pinned; hostname ->", run(c, "sleep 6; hostname"),
          "| watchdog pids:", run(c, "pgrep -f '[p]in_hostname.sh' | tr '\\n' ' '"),
          "| syslog bytes:", run(c, "wc -c < /var/log/syslog"))


def unpin(c):
    run(c, "pkill -f pin_hostname.sh")
    print("unpinned; hostname ->", run(c, "hostname"))


def status(c):
    print("hostname   :", run(c, "hostname"))
    print("/etc/hostname:", run(c, "cat /etc/hostname"))
    print("watchdog   :", run(c, "pgrep -f '[p]in_hostname.sh' | tr '\\n' ' '") or "(none)")
    print("syslog     :", run(c, "wc -c < /var/log/syslog"), "bytes")
    print("uptime     :", run(c, "uptime"))


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    conn = sh()
    try:
        {"pin": pin, "unpin": unpin, "status": status}[action](conn)
    finally:
        conn.close()

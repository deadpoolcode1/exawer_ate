"""Run a command (or a TCL script) on tate, the IXIA application host."""
import sys
import warnings

import paramiko

warnings.filterwarnings("ignore")

HOST, USER, PW = "10.1.70.200", "root", "1q2w3e"

def run(cmd, timeout=300):
    t = paramiko.Transport((HOST, 22))
    t.connect(username=USER, password=PW)
    try:
        ch = t.open_session()
        ch.settimeout(timeout)
        ch.exec_command(cmd)
        out = b""
        while True:
            d = ch.recv(65536)
            if not d:
                break
            out += d
        err = ch.recv_stderr(65536)
        return out.decode(errors="replace") + err.decode(errors="replace")
    finally:
        t.close()

def put(local, remote):
    t = paramiko.Transport((HOST, 22))
    t.connect(username=USER, password=PW)
    try:
        paramiko.SFTPClient.from_transport(t).put(local, remote)
    finally:
        t.close()

def get(remote, local):
    t = paramiko.Transport((HOST, 22))
    t.connect(username=USER, password=PW)
    try:
        paramiko.SFTPClient.from_transport(t).get(remote, local)
    finally:
        t.close()

if __name__ == "__main__":
    print(run(sys.argv[1], timeout=int(sys.argv[2]) if len(sys.argv) > 2 else 300))

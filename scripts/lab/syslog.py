import warnings

import paramiko

warnings.filterwarnings("ignore")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("10.3.99.10", username="root", password="root", timeout=30,
          look_for_keys=False, allow_agent=False)
def run(cmd):
    i, o, e = c.exec_command(cmd)
    out = o.read().decode() + e.read().decode()
    print("$", cmd)
    print(out.strip()[:400])
    return out
run("wc -l /var/log/syslog 2>/dev/null; du -h /var/log/syslog 2>/dev/null")
run(": > /var/log/syslog; wc -l /var/log/syslog")
c.close()

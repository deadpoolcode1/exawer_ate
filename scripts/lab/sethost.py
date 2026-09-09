import warnings

import paramiko

warnings.filterwarnings("ignore")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("10.3.99.10", username="root", password="root", timeout=20,
          look_for_keys=False, allow_agent=False)
i, o, e = c.exec_command("hostname localhost; hostname")
print("ONL hostname ->", o.read().decode().strip())
c.close()

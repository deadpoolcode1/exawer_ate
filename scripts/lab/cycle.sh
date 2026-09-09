#!/bin/bash
# Reboot the DUT to a clean state, then run one test.
#
# Three device facts this works around, all recorded in the evidence:
#  * deleting an EVI aborts bgpd and the service survives in operational
#    state, so only a reboot gives a test the clean device it asserts;
#  * something rewrites the ONL hostname to "router" a few minutes after
#    boot, and Exaware's bring-up matches the ONL shell by the literal
#    "@localhost" (CmpCliSession.java:69). Setting the hostname once before
#    a run is a race the run can lose - and it did, on 2026-09-09. So it is
#    PINNED by a watchdog that holds it for the whole run (onlctl.py);
#  * their bring-up pages /var/log/syslog, so it is truncated first. That
#    is also done by `onlctl.py pin`.
TC=$1
python3 /tmp/clean_reboot.py >/dev/null 2>&1
python3 -c "
import warnings

import paramiko

warnings.filterwarnings('ignore')
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('10.3.99.10', username='root', password='root', timeout=20,
          look_for_keys=False, allow_agent=False)
c.exec_command('nohup sh -c \"sleep 2; reboot\" >/dev/null 2>&1 &')
c.close()
" 2>/dev/null
sleep 120
for i in $(seq 1 45); do
  if timeout 5 bash -c "</dev/tcp/10.3.99.1/22" 2>/dev/null; then break; fi
  sleep 15
done
# let the router application finish its own startup before pinning the hostname
sleep 240
python3 /tmp/onlctl.py pin
python3 /tmp/onlctl.py status

/var/tmp/ate-run/run_tc.sh "$TC" > "/tmp/${TC}_clean.log" 2>&1
echo "=== $TC ==="
grep -E "^(OK \(|FAILURES|Tests run)" "/tmp/${TC}_clean.log"
grep -oE "Fail: .{0,100}" "/tmp/${TC}_clean.log" | sort -u | head -6

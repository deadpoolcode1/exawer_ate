#!/bin/bash
# Reboot the DUT to a clean state, then run one test.
#
# Two device facts this works around, both recorded in the evidence:
#  * deleting an EVI aborts bgpd and the service survives in operational
#    state, so only a reboot gives a test the clean device it asserts;
#  * the router application rewrites the ONL hostname to "router" late in
#    boot, and Exaware's bring-up matches the ONL shell by "@localhost".
#    So the hostname is set AFTER the box has settled, and verified.
TC=$1
python3 /tmp/clean_reboot.py >/dev/null 2>&1
python3 -c "
import paramiko,warnings; warnings.filterwarnings('ignore')
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('10.3.99.10',username='root',password='root',timeout=20,look_for_keys=False,allow_agent=False)
c.exec_command('nohup sh -c \"sleep 2; reboot\" >/dev/null 2>&1 &'); c.close()
" 2>/dev/null
sleep 120
for i in $(seq 1 45); do
  if timeout 5 bash -c "</dev/tcp/10.3.99.1/22" 2>/dev/null; then break; fi
  sleep 15
done
# let the router application finish its own startup before touching hostname
sleep 240
python3 /tmp/syslog.py >/dev/null 2>&1     # keep `less` from paging in bring-up
for a in 1 2 3; do
  python3 /tmp/sethost.py 2>/dev/null
  sleep 20
  H=$(python3 -c "
import paramiko,warnings; warnings.filterwarnings('ignore')
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('10.3.99.10',username='root',password='root',timeout=20,look_for_keys=False,allow_agent=False)
i,o,e=c.exec_command('hostname'); print(o.read().decode().strip()); c.close()
" 2>/dev/null)
  echo "hostname check $a: $H"
  [ "$H" = "localhost" ] && break
done
/var/tmp/ate-run/run_tc.sh "$TC" > "/tmp/${TC}_clean.log" 2>&1
echo "=== $TC ==="
grep -E "^(OK \(|FAILURES|Tests run)" "/tmp/${TC}_clean.log"
grep -oE "Fail: .{0,100}" "/tmp/${TC}_clean.log" | sort -u | head -6

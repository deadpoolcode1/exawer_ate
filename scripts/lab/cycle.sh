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
#  * their bring-up runs `less /var/log/syslog | grep ... -c` on the serial
#    console, and `less` opens /dev/tty and waits for a keypress that never
#    comes, so the command times out at 100 s. NOT a size problem: it hung on
#    a 7.9 KB syslog. `onlctl.py pin` swaps /bin/less for a `cat` shim, which
#    is what that pipeline means anyway, and truncates the syslog once so our
#    own reboot is not counted as a watchdog restart.
#
# The rig comes from ATE_RIG (e.g. 3080), never from a literal in here. Six
# files carried pc-3099's addresses until 2026-09-16, when the reserved rig
# was pc-3080 and moving meant editing all six.
: "${ATE_RIG:?export ATE_RIG=<4-digit rig>, e.g. 3080 - there is no default}"
RIG_OCTET=${ATE_RIG:2:2}
DUT_IP="10.3.${RIG_OCTET#0}.1"
ONL_IP="10.3.${RIG_OCTET#0}.10"

TC=$1
python3 /tmp/clean_reboot.py >/dev/null 2>&1
python3 -c "
import warnings

import paramiko

warnings.filterwarnings('ignore')
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('$ONL_IP', username='root', password='root', timeout=20,
          look_for_keys=False, allow_agent=False)
c.exec_command('nohup sh -c \"sleep 2; reboot\" >/dev/null 2>&1 &')
c.close()
" 2>/dev/null
sleep 120
for i in $(seq 1 45); do
  if timeout 5 bash -c "</dev/tcp/$DUT_IP/22" 2>/dev/null; then break; fi
  sleep 15
done
# let the router application finish its own startup before pinning the hostname
sleep 240
python3 /tmp/onlctl.py pin
python3 /tmp/onlctl.py status

# With no TC named, run all three in ONE JVM. The difido reporter rewrites
# execution.js on every JVM start, so three separate runs leave a report that
# names only the last one - which is exactly what shipped on 2026-09-10 and
# what Exaware reported on 2026-09-15.
if [ -z "${TC:-}" ]; then
  LOG=/tmp/EVPN_suite_clean.log
  /var/tmp/ate-run/run_suite.sh > "$LOG" 2>&1
  echo "=== EVPN suite (one JVM, one report) ==="
else
  LOG="/tmp/${TC}_clean.log"
  # One report per test, kept under its own name. Each test runs from its own
  # reboot because deleting an EVI aborts bgpd and rpki_mo, so a second test
  # sharing the JVM starts on a box where nothing can commit. The three
  # reports are merged afterwards by scripts/lab/merge_reports.py, which is
  # what gives Exaware one index naming all three.
  REPORT=/var/tmp/ate-run/run/log/current
  [ -d "$REPORT" ] && rm -rf "$REPORT"
  mkdir -p "$REPORT"
  /var/tmp/ate-run/run_tc.sh "$TC" > "$LOG" 2>&1
  DEST="/var/tmp/ate-run/run/log/report_${TC}"
  rm -rf "$DEST" && cp -a "$REPORT" "$DEST"
  echo "=== $TC ===  report: $DEST"
fi
grep -E "^(OK \(|FAILURES|Tests run)" "$LOG"
grep -oE "Fail: .{0,100}" "$LOG" | sort -u | head -6

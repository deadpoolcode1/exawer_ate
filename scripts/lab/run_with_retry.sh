#!/bin/bash
# Run each named TC from its own reboot; retry up to 3 times when the run
# died in BRING-UP on the serial console (rig flakiness: a stray router#
# prompt on the console line, pc-3080 2026-10-01), never when a test step
# failed. A failure after the first numbered step is a real result.
export ATE_RIG=3080
for t in "$@"; do
  for try in 1 2 3; do
    echo "### $t try $try start $(date +%T)"
    /var/tmp/ate-run/cycle.sh $t
    L=/tmp/${t}_clean.log
    if grep -q "^OK (" $L; then echo "### $t PASS"; break; fi
    if grep -qE "^[0-9:]+: 1\. " $L || grep -q "Falsifiable assertions\|expected line(s)" $L; then echo "### $t FAIL in test steps"; break; fi
    echo "### $t died in bring-up, retrying"
  done
  echo "### $t end $(date +%T)"
done
echo ALL_DONE

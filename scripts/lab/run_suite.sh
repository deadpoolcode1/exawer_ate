#!/bin/bash
# Run the whole generated EVPN suite in ONE JVM, and produce ONE report.
#
# Exaware, 2026-09-15 (Oded Engel): "I could only find a single index.html
# which only for tc02, I could not find one per TC."
#
# He was right. The difido reporter rewrites run/log/current/execution.js on
# every JVM start and never cleans tests/, so running the three suites one at
# a time leaves an index naming only the last one, on top of every stale test
# folder from every earlier run. The package we shipped carried 66 folders,
# 12 MB, and listed one test.
#
# Two rules, both enforced here:
#   * clear the report directory before the run, so nothing in it belongs to
#     a build we are not claiming anything about;
#   * one JVM for all three test classes, so one execution tree names all
#     three.
set -u
B=/var/tmp/ate-run
REPORT="$B/run/log/current"

STAMP=$(date +%Y%m%d_%H%M%S)
if [ -d "$REPORT" ]; then
    mv "$REPORT" "$B/run/log/archive_$STAMP"
    echo "archived previous report to run/log/archive_$STAMP"
fi
mkdir -p "$REPORT"

# Exaware, 2026-09-15 (Oded Engel), first item in his list of warnings:
#   Read global parameters: Warning: Error reading TATE_GLOBAL_PARAM JSON
#   Cannot invoke "String.length()" because "s" is null
#
# TateGlobalParams.initFromJson() calls URLDecoder.decode() straight on
# System.getenv("TATE_GLOBAL_PARAMS"), which is null outside a TATE run, and
# decode() throws NPE on null. Exporting an empty JSON object is what TATE
# itself would pass and makes the warning go away. The missing null check is
# still theirs to fix - any run outside TATE hits it.
export TATE_GLOBAL_PARAMS="{}"

CP=$(find "$B/libs" "$B/extlibs" -name "*.jar" | sort | tr "\n" ":")$B/classes
cd "$B/run"
"$B/jdk17/bin/java" -cp "$CP" org.junit.runner.JUnitCore \
  cmp.tests.evpn.TC01_EvpnVlanBasedBringUp \
  cmp.tests.evpn.TC02_EvpnType2MacIpAdvertisement \
  cmp.tests.evpn.TC03_EvpnType3ImetFlooding
echo "JUNIT_EXIT=$?"

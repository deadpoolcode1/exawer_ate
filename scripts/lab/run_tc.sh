#!/bin/bash
# Run one generated EVPN test case.
#
# The workspace MUST be /var/tmp/ate-run and not $HOME: GlobalUtils.getCurrentWS()
# canonicalises the path, and the .ixncfg is read by ixNet on the IXIA app
# server (tate), where /home is not writable. /var/tmp exists on both hosts.
B=/var/tmp/ate-run
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
exec "$B/jdk17/bin/java" -cp "$CP" org.junit.runner.JUnitCore "cmp.tests.evpn.$1"

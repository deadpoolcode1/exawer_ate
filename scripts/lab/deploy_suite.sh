#!/bin/bash
# Deploy a generated suite to the dev box, compile it, and only then run it.
#
# 2026-10-01: the generated EvpnUtils.java did not compile, the old manual
# recipe ran javac and the TCs in one ssh line, and the TCs started on the
# PREVIOUS classes. A run on stale classes reports on code nobody shipped.
# Here a javac or .crt failure stops everything before a TC can start.
#
#   scripts/lab/deploy_suite.sh <generated_dir> [TC ...]
#
# <generated_dir> holds cmp/tests/evpn/ (the `ate codegen -o` output, with the
# .ixncfg copied into configurations/ixia/). With TC names, they run detached
# through run_with_retry.sh; watch /tmp/run_<date>.log for ALL_DONE.
set -euo pipefail

GEN="${1:?usage: deploy_suite.sh <generated_dir> [TC ...]}"
shift
HOST="${ATE_HOST:-axawear}"
B=/var/tmp/ate-run
TGZ="$(mktemp --suffix=.tgz)"
trap 'rm -f "$TGZ"' EXIT

[ -f "$GEN/cmp/tests/evpn/configurations/ixia/EVPN_3AC_CORE.ixncfg" ] || {
    echo "no .ixncfg in $GEN: copy it into configurations/ixia/ first" >&2; exit 1; }

(cd "$GEN" && tar czf "$TGZ" cmp)
scp -q "$TGZ" "$HOST:$B/gen_deploy.tgz"
scp -q "$(dirname "$0")/run_with_retry.sh" "$HOST:$B/run_with_retry.sh"

ssh "$HOST" bash -s -- "$@" <<'EOF'
set -euo pipefail
B=/var/tmp/ate-run
D=$B/cmp-tests-project/src/cmp/tests/evpn
cd $B && rm -rf gen_new && mkdir gen_new && tar xzf gen_deploy.tgz -C gen_new
cp -a gen_new/cmp/tests/evpn/. $D/
CP=$(find $B/libs $B/extlibs -name "*.jar" | sort | tr "\n" ":")$B/classes
if ! $B/jdk17/bin/javac --release 8 -Werror -Xlint:all -Xlint:-options -Xlint:-path \
        -encoding UTF-8 -cp "$CP" -d $B/classes $D/*.java; then
    echo "JAVAC FAILED: nothing run, the dev box keeps stale classes" >&2; exit 1
fi
cp -a $D/bringUpParams.crt $B/classes/cmp/tests/evpn/
cp -a $D/configurations/. $B/classes/cmp/tests/evpn/configurations/
R=$(cd $B/crtcheck && $B/jdk17/bin/java -cp "$CP:." CrtCheck $D/bringUpParams.crt 2>&1 | grep RESULT)
echo "$R"
case "$R" in *"-> true"*) ;; *) echo ".crt REFUSED by TemplateManager: nothing run" >&2; exit 1;; esac
echo "deployed: javac OK, .crt OK"
if [ $# -gt 0 ]; then
    chmod +x $B/run_with_retry.sh
    LOG=/tmp/run_$(date +%Y%m%d).log
    nohup $B/run_with_retry.sh "$@" > $LOG 2>&1 < /dev/null &
    echo "running $* -> $LOG (wait for ALL_DONE)"
fi
EOF

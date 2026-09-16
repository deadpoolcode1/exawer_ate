#!/bin/bash
# Assemble the client-facing milestone hand-over package.
#
# The package was hand-assembled for the first M2 drop, which meant nobody
# could tell whether what shipped matched what the repo said. This script makes
# it reproducible: every folder is copied from a tracked location, and the
# .docx is built by scripts/build_handover_docx.py from the same numbers.
#
#     ./scripts/build_handover_package.sh [YYYY-MM-DD]
#
# The git bundle is the one exception — it is produced on the dev box from
# Exaware's own repo (which is not ours to redistribute) and has to be dropped
# into scratch beforehand. Its path is BUNDLE below; if it is missing the
# script says so and carries on, rather than shipping a package that silently
# has no branch in it.
set -euo pipefail

DATE="${1:-$(date +%F)}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$HOME/Desktop/Exaware_M2_handover_${DATE}"
BUNDLE="${BUNDLE:-/tmp/evpn-suite.bundle}"

echo "[1] layout"
rm -rf "$OUT"
mkdir -p "$OUT"/{01_generated_suite,02_evidence,03_test_plan,04_results,05_git,06_automation_report}

echo "[2] the generated suite"
cp -r "$ROOT/deliverables/M2/generated_suite/cmp" "$OUT/01_generated_suite/"
find "$OUT/01_generated_suite" -type f | sed "s|$OUT/|      |"

echo "[2a] gate — does this package still do what we have proven on hardware?"
# Reads the files that are actually about to ship, not the profile that was
# meant to produce them and not the pipeline's exit code. The 2026-08-14
# package had a healthy pipeline, three green tests and no control plane.
# `set -e` stops the build here, which is the whole point: this gate has no
# escape hatch, unlike `ate codegen --accept-regression`.
"$ROOT/.venv/bin/python" "$ROOT/scripts/verify_handover_package.py" \
    "$OUT/01_generated_suite"

echo "[3] evidence — one file per claim"
cp "$ROOT"/deliverables/M2/evidence_*.txt  "$OUT/02_evidence/"
cp "$ROOT"/deliverables/M2/evidence_*.json "$OUT/02_evidence/"
cp "$ROOT"/deliverables/M2/lab_validation_*.md "$OUT/02_evidence/"
cp "$ROOT/deliverables/M2/README.md" "$OUT/README.md"
ls "$OUT/02_evidence" | sed 's|^|      |'

echo "[4] the test plan the code was generated from"
cp "$ROOT/plans/EVPN_test_plan_with_RFCs.xlsx" "$OUT/03_test_plan/"
cp "$ROOT/plans/EVPN_test_plan_with_RFCs_CHANGES.md" "$OUT/03_test_plan/"

echo "[5] the newest test report"
REPORT="$(ls -t "$ROOT"/results/test-report-*.html 2>/dev/null | head -1 || true)"
if [ -n "$REPORT" ]; then
    cp "$REPORT" "$OUT/04_results/"
    echo "      $(basename "$REPORT")"
else
    echo "      NONE FOUND - run ./modular_tools.sh run-tests first" >&2
fi

echo "[5a] the automation report (steps, commands, outputs, verdicts)"
# Exaware, 2026-09-09 (Eyal Ozeri): "I would very much like to see an
# Automation report where I can really verify the steps, shows outputs, show
# output parsing, etc..." This is the JSystem/difido report from the run,
# which is exactly that: one page per test, numbered steps, the command
# issued, the device output, and the parsed verdict. It opens from index.html
# with no server.
REPORT_DIR="$ROOT/deliverables/M2/automation_report"
if [ -d "$REPORT_DIR" ]; then
    cp -r "$REPORT_DIR"/* "$OUT/06_automation_report/"
    echo "      $(du -sh "$OUT/06_automation_report" | cut -f1), open 06_automation_report/index.html"
else
    echo "      MISSING: $REPORT_DIR - package ships without the run report" >&2
    exit 1
fi

echo "[5b] gate - does the report back what the package claims?"
# Step [2a] reads the emitted .cfg and .java. It read NOTHING under
# 06_automation_report, which was a straight cp -r guarded only by the folder
# existing. So on 2026-09-10 we shipped 12 MB of report without opening it and
# validated the run on the JUnit exit code, which counts failures and not
# JSystem warnings. The mail said "OK (1 test), 0 failures"; the last line of
# that report said "Final test status is : Warning", and the client read the
# report. Under `set -e` this gate stops the build, like [2a].
"$ROOT/.venv/bin/python" "$ROOT/scripts/verify_automation_report.py" \
    "$OUT/06_automation_report" "$OUT/01_generated_suite"

echo "[6] the branch, as a git bundle"
if [ -f "$BUNDLE" ]; then
    cp "$BUNDLE" "$OUT/05_git/evpn-suite.bundle"
    echo "      $(du -h "$OUT/05_git/evpn-suite.bundle" | cut -f1)"
else
    # An empty folder in a client package is a question we will be asked.
    # Say why it is empty, inside the package, where the reviewer is looking.
    cat > "$OUT/05_git/WHY_THIS_IS_EMPTY.md" <<'NOTE'
# No git bundle in this package

The generated suite is in `01_generated_suite/`, which is the same content.
What is missing here is the same content **as a branch of your repository**,
and it is missing for one reason:

**We still need a ticket ID (AUT-nnn / EM-nnnn).**

The branch cannot be pushed under its real name without one, so there is no
branch to bundle, and no TATE run recorded against a ticket. It has been the
first item on our "what we need from you" list since 24 August.

Give us the ticket ID and the branch and the TATE records follow the same day.
NOTE
    echo "      MISSING: $BUNDLE - package ships without the branch;" >&2
    echo "      05_git/WHY_THIS_IS_EMPTY.md says so inside the package" >&2
fi

echo "[7] the hand-over document"
"$ROOT/.venv/bin/python" "$ROOT/scripts/build_handover_docx.py" "$OUT"

echo "[8] zip"
( cd "$(dirname "$OUT")" && rm -f "$(basename "$OUT").zip" \
  && zip -qr "$(basename "$OUT").zip" "$(basename "$OUT")" )

echo
echo "package: $OUT"
echo "zip    : $OUT.zip"
du -sh "$OUT" "$OUT.zip"

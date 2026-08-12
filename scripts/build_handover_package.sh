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
mkdir -p "$OUT"/{01_generated_suite,02_evidence,03_test_plan,04_results,05_git}

echo "[2] the generated suite"
cp -r "$ROOT/deliverables/M2/generated_suite/cmp" "$OUT/01_generated_suite/"
find "$OUT/01_generated_suite" -type f | sed "s|$OUT/|      |"

echo "[3] evidence — one file per claim"
cp "$ROOT"/deliverables/M2/evidence_*.txt  "$OUT/02_evidence/"
cp "$ROOT"/deliverables/M2/evidence_*.json "$OUT/02_evidence/"
cp "$ROOT"/deliverables/M2/lab_validation_*.md "$OUT/02_evidence/"
cp "$ROOT/deliverables/M2/README.md" "$OUT/README.md"
ls "$OUT/02_evidence" | sed 's|^|      |'

echo "[4] the test plan the code was generated from"
cp "$ROOT/plans/EVPN_test_plan_with_RFCs.xlsx" "$OUT/03_test_plan/"

echo "[5] the newest test report"
REPORT="$(ls -t "$ROOT"/results/test-report-*.html 2>/dev/null | head -1 || true)"
if [ -n "$REPORT" ]; then
    cp "$REPORT" "$OUT/04_results/"
    echo "      $(basename "$REPORT")"
else
    echo "      NONE FOUND - run ./modular_tools.sh run-tests first" >&2
fi

echo "[6] the branch, as a git bundle"
if [ -f "$BUNDLE" ]; then
    cp "$BUNDLE" "$OUT/05_git/evpn-suite.bundle"
    echo "      $(du -h "$OUT/05_git/evpn-suite.bundle" | cut -f1)"
else
    echo "      MISSING: $BUNDLE — package will ship without the branch" >&2
fi

echo "[7] the hand-over document"
"$ROOT/.venv/bin/python" "$ROOT/scripts/build_handover_docx.py"

echo "[8] zip"
( cd "$(dirname "$OUT")" && rm -f "$(basename "$OUT").zip" \
  && zip -qr "$(basename "$OUT").zip" "$(basename "$OUT")" )

echo
echo "package: $OUT"
echo "zip    : $OUT.zip"
du -sh "$OUT" "$OUT.zip"

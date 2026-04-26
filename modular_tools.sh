#!/bin/bash
# modular_tools.sh — swiss-knife dispatcher for the ATE project (M1)
#
# Usage:  ./modular_tools.sh <command> [args...]
#         ./modular_tools.sh help
#
# This is the primary entrypoint for both human verification (does M1 work?)
# and regression detection (did a change break something?).

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for terminals that support them.
if [[ -t 1 ]]; then
    R='\033[1;31m'; G='\033[1;32m'; Y='\033[1;33m'; B='\033[1;34m'; N='\033[0m'
else
    R=''; G=''; Y=''; B=''; N=''
fi

VENV="$SCRIPT_DIR/.venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"
ATE="$VENV/bin/ate"

export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

# ─────────────────────────────────────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────────────────────────────────────

setup() {
    echo -e "${B}[setup]${N} Creating venv and installing dependencies"
    if [[ ! -d "$VENV" ]]; then
        python3 -m venv "$VENV"
    fi
    "$PIP" install --quiet --upgrade pip
    "$PIP" install --quiet -e ".[dev]"
    echo -e "${G}[done]${N} Environment ready. Try: ./modular_tools.sh verify"
}

verify_env() {
    echo -e "${B}[verify-env]${N} Checking dev environment health"
    "$PY" scripts/verify_env.py
}

build() {
    echo -e "${B}[build]${N} Reinstalling package in dev mode"
    "$PIP" install --quiet -e ".[dev]"
    echo -e "${G}[done]${N}"
}

# ─────────────────────────────────────────────────────────────────────────────
# CORPUS
# ─────────────────────────────────────────────────────────────────────────────

corpus_check() {
    echo -e "${B}[corpus]${N} Verifying corpus tree"
    local missing=0
    for f in \
        tests/corpus/tier_a/rfc9785.docx \
        tests/corpus/tier_a/rfc9785.txt \
        tests/corpus/tier_a/rfc9785.pdf \
        "tests/corpus/tier_a/EVPN System Specification 1.00.docx" \
        "tests/corpus/tier_a/EVPN CLI 1.00.docx" \
        tests/corpus/tier_b/rfc7432bis-13.docx \
        tests/corpus/tier_b/rfc7432bis-13.txt \
        tests/corpus/tier_c/MANIFEST.tsv ; do
        if [[ ! -e "$f" ]]; then
            echo -e "${R}[miss]${N} $f"
            missing=$((missing + 1))
        else
            echo -e "${G}[ok  ]${N} $f"
        fi
    done
    if (( missing > 0 )); then
        echo -e "${R}corpus incomplete: $missing missing file(s)${N}"
        return 1
    fi
    echo -e "${G}[done]${N} corpus complete"
}

build_tier_c() {
    echo -e "${B}[tier-c]${N} Regenerating edge case files"
    "$PY" scripts/build_tier_c.py
}

# ─────────────────────────────────────────────────────────────────────────────
# PARSE / RUN
# ─────────────────────────────────────────────────────────────────────────────

parse() {
    local arg="${1:-}"
    if [[ -z "$arg" ]]; then
        echo "usage: ./modular_tools.sh parse <file> [-o out.json] [--summary]"
        return 2
    fi
    "$ATE" parse "$@"
}

parse_all() {
    # Parse every supported file in references/ to out/<name>.json
    mkdir -p out
    local n_ok=0 n_skip=0 n_fail=0
    echo -e "${B}[parse_all]${N} Writing IR JSON for every supported file in references/ → out/"
    echo
    for f in references/*; do
        local name
        name=$(basename "$f")
        case "$f" in
            *.pdf|*.docx|*.txt)
                # Keep source extension in output name so {name}.docx and
                # {name}.pdf don't collide on the same JSON.
                local out_file="out/${name}.json"
                if "$ATE" parse "$f" -o "$out_file" 2>/dev/null; then
                    local size
                    size=$(stat -c%s "$out_file")
                    printf '  %-44s → %-30s (%s bytes)\n' \
                        "$name" "$out_file" "$size"
                    n_ok=$((n_ok+1))
                else
                    printf '  %-44s ${R}FAIL${N}\n' "$name"
                    n_fail=$((n_fail+1))
                fi
                ;;
            *)
                printf '  %-44s skipped (unsupported format)\n' "$name"
                n_skip=$((n_skip+1))
                ;;
        esac
    done
    echo
    echo -e "${G}[done]${N} parsed $n_ok, skipped $n_skip, failed $n_fail. Files in out/"
}

# ─────────────────────────────────────────────────────────────────────────────
# TESTS / VERIFY (the user-facing green/red)
# ─────────────────────────────────────────────────────────────────────────────

test_unit() {
    echo -e "${B}[test]${N} Running pytest suite"
    "$PY" -m pytest "$@"
}

verify() {
    echo -e "${B}[verify]${N} Running M1 acceptance scorecard"
    echo
    if "$PY" scripts/score.py; then
        echo
        echo -e "${G}M1 acceptance: GREEN${N}"
        return 0
    else
        echo
        echo -e "${R}M1 acceptance: RED${N}"
        return 1
    fi
}

verify_quick() {
    "$PY" scripts/score.py --only "${1:-determinism}"
}

regression() {
    echo -e "${B}[regression]${N} Pytest + golden-IR diff"
    local rc=0
    "$PY" -m pytest tests/ "$@" || rc=$?
    echo
    echo -e "${B}[regression]${N} Checking golden drift (no writes)"
    "$PY" scripts/build_goldens.py diff || rc=$?
    if (( rc == 0 )); then
        echo -e "${G}[done]${N} no regression detected"
    else
        echo -e "${R}[fail]${N} regression detected — see output above"
    fi
    return $rc
}

# ─────────────────────────────────────────────────────────────────────────────
# GOLDEN MANAGEMENT (regression baseline)
# ─────────────────────────────────────────────────────────────────────────────

golden_diff() {
    echo -e "${B}[golden]${N} Comparing current parser output to committed goldens"
    "$PY" scripts/build_goldens.py diff
}

golden_update() {
    echo -e "${Y}[golden]${N} About to OVERWRITE committed goldens with current parser output."
    echo -e "${Y}         This is the 'accept current behavior as the new baseline' action.${N}"
    if [[ "${1:-}" != "--force" ]]; then
        read -r -p "Type 'yes' to proceed: " confirm
        if [[ "$confirm" != "yes" ]]; then
            echo "aborted."
            return 1
        fi
    fi
    "$PY" scripts/build_goldens.py build
    echo -e "${G}[done]${N} goldens updated. Review the diff and commit."
}

golden_dump_ir() {
    echo -e "${B}[golden]${N} Dumping normalized IR for tracked docs"
    "$PY" scripts/build_goldens.py ir
}

# ─────────────────────────────────────────────────────────────────────────────
# LINT / CLEAN
# ─────────────────────────────────────────────────────────────────────────────

lint() {
    echo -e "${B}[lint]${N} Running ruff"
    "$PY" -m ruff check ate scripts tests || true
}

clean() {
    echo -e "${B}[clean]${N} Removing caches"
    rm -rf .pytest_cache .ruff_cache .mypy_cache out
    find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
    echo -e "${G}[done]${N}"
}

# ─────────────────────────────────────────────────────────────────────────────
# DOCKER (matches docker-compose.yml services)
# ─────────────────────────────────────────────────────────────────────────────

docker_build() {
    echo -e "${B}[docker]${N} Building image"
    docker build -t ate:m1 .
}

docker_verify() {
    echo -e "${B}[docker]${N} Running scorecard inside container"
    docker compose run --rm ate-verify
}

# ─────────────────────────────────────────────────────────────────────────────
# E2E — what the user runs to know M1 is good
# ─────────────────────────────────────────────────────────────────────────────

e2e() {
    echo -e "${B}═══ ATE M1 end-to-end verification ═══${N}"
    echo
    verify_env || return 1
    echo
    corpus_check || return 1
    echo
    test_unit || return 1
    echo
    verify || return 1
    echo
    echo -e "${G}═══ ALL GREEN ═══${N}"
}

# ─────────────────────────────────────────────────────────────────────────────
# HELP
# ─────────────────────────────────────────────────────────────────────────────

help() {
    cat <<'EOF'
modular_tools.sh — ATE project swiss knife (M1: document parser)

USAGE:
    ./modular_tools.sh <command> [args...]

═══ SETUP ═══════════════════════════════════════════════════════════════════
    setup            Create venv and install all deps (run this first)
    build            Reinstall package in dev mode (after editing pyproject)
    verify_env       Check that dev environment is healthy

═══ CORPUS ══════════════════════════════════════════════════════════════════
    corpus_check     Verify all corpus files exist
    build_tier_c     Regenerate Tier-C edge case files

═══ PARSE ═══════════════════════════════════════════════════════════════════
    parse <file>     Parse one document, IR to stdout (or -o out.json)
                     Example: ./modular_tools.sh parse references/rfc9785.txt --summary
    parse_all        Parse every supported file in references/ → out/<name>.json

═══ TESTS / VERIFY (the user-facing green/red gates) ════════════════════════
    verify           ★ M1 acceptance scorecard — green/red signal for M1 ship
    verify_quick     Fast subset (determinism only by default)
    test_unit        Pytest suite (unit, regression, parity, determinism, edge)
    regression       pytest + golden drift in one shot
    e2e              ★ Full end-to-end: env + corpus + tests + scorecard

═══ GOLDEN MANAGEMENT (regression baseline) ═════════════════════════════════
    golden_diff      What would change if goldens were regenerated
    golden_update    Regenerate goldens (with confirmation)
    golden_dump_ir   Dump full normalized IR per tracked doc

═══ DOCKER ══════════════════════════════════════════════════════════════════
    docker_build     Build ate:m1 image
    docker_verify    Run scorecard inside container

═══ MAINTENANCE ═════════════════════════════════════════════════════════════
    lint             ruff check
    clean            Remove caches

═══ FOR THE PROJECT OWNER ═══════════════════════════════════════════════════
The single command you run to know M1 is shippable:

    ./modular_tools.sh e2e

If green, M1 passes acceptance. If red, the failing metric is named.
EOF
}

# ─────────────────────────────────────────────────────────────────────────────
# Dispatcher (inspired by /home/ilan/work/uvision/track/modular_tools.sh)
# ─────────────────────────────────────────────────────────────────────────────

if [[ -n "$*" ]]; then
    cmd="$1"; shift
    case "$cmd" in
        # alias: dashes ↔ underscores
        verify-env)      verify_env "$@";;
        verify-quick)    verify_quick "$@";;
        parse-all)       parse_all "$@";;
        corpus-check)    corpus_check "$@";;
        build-tier-c)    build_tier_c "$@";;
        test|tests)      test_unit "$@";;
        golden-diff)     golden_diff "$@";;
        golden-update)   golden_update "$@";;
        golden-dump-ir)  golden_dump_ir "$@";;
        docker-build)    docker_build "$@";;
        docker-verify)   docker_verify "$@";;
        # fall-through to function name
        *)               "$cmd" "$@";;
    esac
else
    help
fi

PY := .venv/bin/python
PIP := .venv/bin/pip
export PYTEST_DISABLE_PLUGIN_AUTOLOAD := 1

.PHONY: help venv install lint test verify-env m1-acceptance parity-rfc9785 determinism edge-cases plan-evpn ai-bake-curated ai-bake-full clean install-hooks uninstall-hooks

help:
	@echo "Targets:"
	@echo "  make venv             - create local virtualenv"
	@echo "  make install          - install package + dev deps"
	@echo "  make lint             - run ruff"
	@echo "  make test             - run pytest"
	@echo "  make verify-env       - check dev environment health"
	@echo "  make m1-acceptance    - run full M1 acceptance scorecard"
	@echo "  make parity-rfc9785   - format-parity check for RFC 9785"
	@echo "  make determinism      - run parser 3x and assert byte-identical IR"
	@echo "  make edge-cases       - assert each Tier-C file produces typed error"
	@echo "  make plan-evpn        - regenerate plans/EVPN_test_plan_with_RFCs.xlsx"
	@echo "  make ai-bake-curated  - run AI on a curated row subset (~15 min)"
	@echo "  make ai-bake-full     - run AI on every row (~3 hours via CLI backend)"
	@echo "  make install-hooks    - install repo git hooks (tests gate every tag push)"
	@echo "  make uninstall-hooks  - remove repo git hooks"

venv:
	python3 -m venv .venv

install: venv
	$(PIP) install --quiet -e ".[dev]"

lint:
	$(PY) -m ruff check ate scripts tests

test:
	$(PY) -m pytest

verify-env:
	@$(PY) scripts/verify_env.py

m1-acceptance:
	@$(PY) scripts/score.py

parity-rfc9785:
	@$(PY) scripts/score.py --only parity

determinism:
	@$(PY) scripts/score.py --only determinism

edge-cases:
	@$(PY) scripts/score.py --only edge_cases

plan-evpn:
	@$(PY) -m ate.cli plan-feature EVPN \
	  -o plans/EVPN_test_plan_with_RFCs.xlsx

ai-bake-curated:
	$(PY) scripts/build_ai_cache.py

ai-bake-full:
	$(PY) scripts/build_ai_cache.py --full

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache out
	find . -name __pycache__ -type d -exec rm -rf {} +

# Symlink scripts/git-hooks/* into .git/hooks/ so pushing a tag runs pytest.
install-hooks:
	@for h in scripts/git-hooks/*; do \
	  name=$$(basename $$h); \
	  ln -sf ../../scripts/git-hooks/$$name .git/hooks/$$name; \
	  echo "installed: .git/hooks/$$name -> ../../scripts/git-hooks/$$name"; \
	done

uninstall-hooks:
	@for h in scripts/git-hooks/*; do \
	  name=$$(basename $$h); \
	  rm -f .git/hooks/$$name; \
	  echo "removed: .git/hooks/$$name"; \
	done

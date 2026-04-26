PY := .venv/bin/python
PIP := .venv/bin/pip
export PYTEST_DISABLE_PLUGIN_AUTOLOAD := 1

.PHONY: help venv install lint test verify-env m1-acceptance parity-rfc9785 determinism edge-cases clean

help:
	@echo "Targets:"
	@echo "  make venv            - create local virtualenv"
	@echo "  make install         - install package + dev deps"
	@echo "  make lint            - run ruff"
	@echo "  make test            - run pytest"
	@echo "  make verify-env      - check dev environment health"
	@echo "  make m1-acceptance   - run full M1 acceptance scorecard"
	@echo "  make parity-rfc9785  - format-parity check for RFC 9785"
	@echo "  make determinism     - run parser 3x and assert byte-identical IR"
	@echo "  make edge-cases      - assert each Tier-C file produces typed error"

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

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache out
	find . -name __pycache__ -type d -exec rm -rf {} +

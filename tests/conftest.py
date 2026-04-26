from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "corpus"
GOLDEN = ROOT / "tests" / "golden"


@pytest.fixture
def root() -> Path:
    return ROOT


@pytest.fixture
def corpus() -> Path:
    return CORPUS


@pytest.fixture
def golden() -> Path:
    return GOLDEN

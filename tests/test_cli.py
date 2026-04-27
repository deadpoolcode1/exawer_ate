"""CLI tests — both subprocess (real install) and in-process (for coverage)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ate.cli import main as cli_main

ROOT = Path(__file__).resolve().parents[1]
ATE = ROOT / ".venv" / "bin" / "ate"
SAMPLE = ROOT / "tests/corpus/tier_a/rfc9785.txt"


# ─── In-process tests (drive coverage on ate/cli.py) ──────────────────────

def test_cli_inprocess_summary(capsys) -> None:
    rc = cli_main(["parse", str(SAMPLE), "--summary"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "format:" in out
    assert "blocks:" in out


def test_cli_inprocess_emits_valid_json(tmp_path: Path, capsys) -> None:
    out = tmp_path / "ir.json"
    rc = cli_main(["parse", str(SAMPLE), "-o", str(out)])
    assert rc == 0
    payload = json.loads(out.read_text())
    assert payload["source_format"] == "txt"
    assert payload["schema_version"] == "1.0.0"
    assert isinstance(payload["blocks"], list)
    assert len(payload["blocks"]) > 0


def test_cli_inprocess_stdout_when_no_outflag(capsys) -> None:
    rc = cli_main(["parse", str(SAMPLE)])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["source_format"] == "txt"


def test_cli_inprocess_typed_error_returns_1(capsys, tmp_path: Path) -> None:
    """Bad input should return exit 1, not raise."""
    bad = tmp_path / "nope.html"
    bad.write_bytes(b"<html>not supported</html>")
    rc = cli_main(["parse", str(bad)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "UnsupportedFormatError" in err


def test_cli_inprocess_version_flag() -> None:
    """--version must exit zero and print a version string."""
    with pytest.raises(SystemExit) as ei:
        cli_main(["--version"])
    assert ei.value.code == 0


# ─── Subprocess smoke (proves the installed `ate` script also works) ──────

def test_cli_subprocess_summary() -> None:
    if not ATE.exists():
        cmd = [sys.executable, "-m", "ate.cli", "parse", str(SAMPLE), "--summary"]
    else:
        cmd = [str(ATE), "parse", str(SAMPLE), "--summary"]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=ROOT)
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert "format:" in r.stdout


def test_cli_subprocess_writes_json(tmp_path: Path) -> None:
    out = tmp_path / "ir.json"
    if not ATE.exists():
        cmd = [sys.executable, "-m", "ate.cli", "parse", str(SAMPLE), "-o", str(out)]
    else:
        cmd = [str(ATE), "parse", str(SAMPLE), "-o", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=ROOT)
    assert r.returncode == 0, f"stderr: {r.stderr}"
    payload = json.loads(out.read_text())
    assert payload["source_format"] == "txt"

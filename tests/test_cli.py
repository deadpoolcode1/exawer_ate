"""CLI smoke tests."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATE = ROOT / ".venv" / "bin" / "ate"


def test_cli_summary_runs() -> None:
    if not ATE.exists():
        # Fallback for environments where the package isn't installed.
        cmd = [sys.executable, "-m", "ate.cli", "parse",
               str(ROOT / "tests/corpus/tier_a/rfc9785.txt"), "--summary"]
    else:
        cmd = [str(ATE), "parse",
               str(ROOT / "tests/corpus/tier_a/rfc9785.txt"), "--summary"]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=ROOT)
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert "format:" in r.stdout
    assert "blocks:" in r.stdout


def test_cli_emits_valid_json(tmp_path: Path) -> None:
    out = tmp_path / "ir.json"
    if not ATE.exists():
        cmd = [sys.executable, "-m", "ate.cli", "parse",
               str(ROOT / "tests/corpus/tier_a/rfc9785.txt"),
               "-o", str(out)]
    else:
        cmd = [str(ATE), "parse",
               str(ROOT / "tests/corpus/tier_a/rfc9785.txt"),
               "-o", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=ROOT)
    assert r.returncode == 0, f"stderr: {r.stderr}"
    payload = json.loads(out.read_text())
    assert payload["source_format"] == "txt"
    assert payload["schema_version"] == "1.0.0"
    assert isinstance(payload["blocks"], list)

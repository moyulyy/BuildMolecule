"""CHGNet environment/runner helper tests (no GPU required)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from mk_mole.services.chgnet import ChgnetEnvironment, candidate_pythons


def test_environment_labels() -> None:
    cuda = ChgnetEnvironment(python="python.exe", device="cuda", gpu="GTX 1050 Ti")
    cpu = ChgnetEnvironment(python="python.exe", device="cpu")
    assert cuda.label == "CUDA · GTX 1050 Ti"
    assert cuda.short_label == "CUDA"
    assert cpu.label == "CPU"
    assert cpu.short_label == "CPU"


def test_env_override_is_first_candidate(monkeypatch, tmp_path) -> None:
    fake = tmp_path / "python.exe"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv("MK_MOLE_CHGNET_PYTHON", str(fake))
    monkeypatch.setenv("MK_MOLE_DATA_DIR", str(tmp_path / "data"))
    from mk_mole.config import AppConfig

    candidates = candidate_pythons(AppConfig())
    assert candidates
    assert candidates[0].resolve() == fake.resolve()


def test_runner_help_syntax() -> None:
    runner = Path(__file__).resolve().parent.parent / "mk_mole" / "tools" / "chgnet_runner.py"
    proc = subprocess.run(
        [sys.executable, str(runner), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "CHGNet" in proc.stdout or "relaxation" in proc.stdout

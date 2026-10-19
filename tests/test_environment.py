import platform
import subprocess
from datetime import datetime

import pytest

from boundary_audit.environment import (
    collect_environment,
    decode_environment,
    interpreter_path,
    source_provenance,
)


def test_environment_is_measured_not_hardcoded():
    environment = collect_environment()
    measured = datetime.fromisoformat(environment["measurement_time"])
    assert measured.tzinfo is not None
    assert environment["measurement_date"] == measured.date().isoformat()
    assert environment["platform"] == platform.system()
    assert environment["platform"] != "Windows CPU"
    assert environment["system_timezone"]
    assert environment["display_timezone"]
    assert "available" in environment["host_gpu"]


def test_cpu_request_on_cuda_build_is_not_a_fallback():
    cpu = decode_environment(
        {
            "requested_decode_device": "cpu",
            "observed_decode_device": "cpu",
            "torch_cuda_available": True,
            "torch_cuda_build": "12.8",
        }
    )
    assert cpu["requested_decode_device"] == "cpu"
    assert cpu["observed_decode_device"] == "cpu"
    assert cpu["cpu_fallback_observed"] is False
    fallback = decode_environment(
        {"requested_decode_device": "cuda", "observed_decode_device": "cpu", "torch_cuda_available": True}
    )
    assert fallback["cpu_fallback_observed"] is True


@pytest.mark.skipif(not __import__("shutil").which("git"), reason="git is not installed")
def test_source_provenance_records_commit_and_dirty_state(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "tracked.txt").write_text("original", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", "init"],
        cwd=tmp_path,
        check=True,
    )
    clean = source_provenance(tmp_path)
    assert len(clean["commit"]) == 40
    assert clean["dirty"] is False
    (tmp_path / "tracked.txt").write_text("changed", encoding="utf-8")
    assert source_provenance(tmp_path)["dirty"] is True


def test_interpreter_path_keeps_a_venv_symlink(tmp_path):
    import os
    import sys

    link = tmp_path / "python"
    try:
        os.symlink(sys.executable, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available")
    candidate = interpreter_path(link)
    assert candidate == link.absolute()
    assert candidate.name == "python"

import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import check_release  # noqa: E402


def current_version():
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def test_current_tag_metadata_is_consistent():
    version = current_version()
    result = check_release.check(ROOT, f"v{version}")
    assert result["status"] == "pass"
    assert result["version"] == version
    assert result["citation_version"] == version


def test_version_or_missing_notes_fails_before_build():
    with pytest.raises(ValueError, match="pyproject"):
        check_release.check(ROOT, "v0.0.0")
    with pytest.raises(ValueError, match="Release tag"):
        check_release.check(ROOT, "0.4.3")


def test_artifact_names_must_match_the_tag(tmp_path):
    version = current_version()
    (tmp_path / f"lerobot_boundary_audit-{version}-py3-none-any.whl").write_text("")
    (tmp_path / f"lerobot_boundary_audit-{version}.tar.gz").write_text("")
    assert check_release.check(ROOT, f"v{version}", tmp_path)["artifacts"]["wheels"]
    (tmp_path / "wrong-1.0.0-py3-none-any.whl").write_text("")
    (tmp_path / f"lerobot_boundary_audit-{version}.tar.gz").unlink()
    (tmp_path / "wrong-1.0.0.tar.gz").write_text("")
    with pytest.raises(ValueError, match="artifact"):
        check_release.check(ROOT, f"v{version}", tmp_path)

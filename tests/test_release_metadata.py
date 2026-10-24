import io
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
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
    metadata = f"Name: lerobot-boundary-audit\nVersion: {version}\n".encode()
    with zipfile.ZipFile(tmp_path / f"lerobot_boundary_audit-{version}-py3-none-any.whl", "w") as archive:
        archive.writestr(f"lerobot_boundary_audit-{version}.dist-info/METADATA", metadata)
    with tarfile.open(tmp_path / f"lerobot_boundary_audit-{version}.tar.gz", "w:gz") as archive:
        member = tarfile.TarInfo(f"lerobot_boundary_audit-{version}/PKG-INFO")
        member.size = len(metadata)
        archive.addfile(member, io.BytesIO(metadata))
    assert check_release.check(ROOT, f"v{version}", tmp_path)["artifacts"]["wheels"]
    (tmp_path / "wrong-1.0.0-py3-none-any.whl").write_text("")
    (tmp_path / f"lerobot_boundary_audit-{version}.tar.gz").unlink()
    (tmp_path / "wrong-1.0.0.tar.gz").write_text("")
    with pytest.raises(ValueError, match="artifact"):
        check_release.check(ROOT, f"v{version}", tmp_path)


def test_relabelled_artifact_with_wrong_embedded_version_is_rejected(tmp_path):
    version = current_version()
    with zipfile.ZipFile(tmp_path / f"lerobot_boundary_audit-{version}-py3-none-any.whl", "w") as archive:
        archive.writestr("wrong.dist-info/METADATA", "Name: lerobot-boundary-audit\nVersion: 999.0\n")
    with pytest.raises(ValueError, match="embedded package"):
        check_release.check(ROOT, f"v{version}", tmp_path)

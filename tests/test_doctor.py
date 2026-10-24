import json

from test_audit import dataset

from boundary_audit.cli import main
from boundary_audit.doctor import diagnose, write_doctor


def stable_packages(monkeypatch, **overrides):
    values = {"pyarrow": "21.0", "av": "16.0", "numpy": "2.0", "torch": None, "datasets": None, "lerobot": None}
    values.update(overrides)
    monkeypatch.setattr("boundary_audit.doctor.package_version", lambda name: values.get(name))
    monkeypatch.setattr(
        "boundary_audit.doctor.collect_environment",
        lambda: {"platform": "test", "python": "3.12", "host_gpu": {"available": False}},
    )
    monkeypatch.setattr(
        "boundary_audit.doctor.ffmpeg_report",
        lambda _path=None: {"status": "pass", "available": True, "detail": "test ffmpeg", "action": None},
    )


def test_missing_required_audit_dependency_is_fail(monkeypatch):
    stable_packages(monkeypatch, pyarrow=None)
    result = diagnose()
    assert result["status"] == "fail"
    assert {c["name"]: c["status"] for c in result["checks"]}["audit_dependency"] == "fail"
    assert any("pyarrow" in step for step in result["next_steps"])


def test_missing_optional_decoder_is_partial(monkeypatch):
    stable_packages(monkeypatch, av=None)
    result = diagnose()
    assert result["status"] == "partial"
    assert {c["name"]: c["status"] for c in result["checks"]}["decode_dependency"] == "partial"


def test_unavailable_consumer_is_partial_and_does_not_block_dataset_audit(tmp_path, monkeypatch):
    stable_packages(monkeypatch)
    monkeypatch.setattr(
        "boundary_audit.doctor.consumer_report",
        lambda _python: {
            "status": "unavailable",
            "detail": "missing interpreter",
            "action": "Create the official LeRobot environment first.",
        },
    )
    root = dataset(tmp_path)
    result = diagnose(datasets=[root], consumer_python="missing-python")
    assert result["status"] == "partial"
    assert result["datasets"][0]["status"] == "pass"
    assert {c["name"]: c["status"] for c in result["checks"]}["official_consumer"] == "unavailable"
    assert result["datasets"][0]["root"] == "."


def test_doctor_html_and_json_are_offline_and_label_partial(tmp_path, monkeypatch):
    stable_packages(monkeypatch)
    root = dataset(tmp_path)
    result = diagnose(datasets=[root])
    write_doctor(result, tmp_path / "doctor")
    saved = json.loads((tmp_path / "doctor/doctor.json").read_text())
    assert saved["status"] == "pass"
    html = (tmp_path / "doctor/doctor.html").read_text()
    assert "Boundary audit doctor" in html
    assert "http://" not in html and "https://" not in html
    assert str(root) not in (tmp_path / "doctor/doctor.json").read_text()


def test_cli_doctor_exit_code_and_output(tmp_path, monkeypatch):
    stable_packages(monkeypatch)
    result = {
        "schema_version": "boundary-doctor.v1",
        "status": "partial",
        "scope": "test",
        "checks": [],
        "datasets": [],
        "next_steps": [],
        "environment": {},
        "packages": {},
        "consumer": None,
        "ffmpeg": {},
        "python": {},
        "tool_version": "test",
    }
    monkeypatch.setattr("boundary_audit.doctor.diagnose", lambda **kwargs: result)
    assert main(["doctor", "--out", str(tmp_path / "doctor")]) == 2
    assert json.loads((tmp_path / "doctor/doctor.json").read_text())["status"] == "partial"
    assert (tmp_path / "doctor/doctor.html").exists()

import json

import pytest

from boundary_audit.cli import main
from boundary_audit.conformance import add_repair_control, generate_suite, run_suite, verify_loader, write_suite_html
from boundary_audit.storage import write_json


def test_real_footage_without_oracle_is_not_certified(tmp_path):
    with pytest.raises(ValueError, match="pre-encoding"):
        verify_loader(tmp_path, "missing-python")


def test_missing_consumer_is_explicitly_unavailable(tmp_path):
    write_json(tmp_path / "frame_oracle.json", {"schema_version": "boundary-frame-oracle.v1"})
    report = verify_loader(tmp_path, str(tmp_path / "no-python"))
    assert report["status"] == "unavailable"
    assert report["source_unchanged"]


@pytest.mark.parametrize(
    "cases",
    [
        [],
        [{"name": "../escape", "path": "x", "expected": "pass"}],
        [{"name": "x", "path": "../escape", "expected": "fail"}],
        [{"name": "x", "path": "x", "expected": "unavailable"}],
    ],
)
def test_invalid_suite_is_rejected_before_results_publish(tmp_path, cases):
    root = tmp_path / "suite"
    output = tmp_path / "results"
    write_json(
        root / "suite.json", {"schema_version": "boundary-conformance-suite.v1", "synthetic_only": True, "cases": cases}
    )
    with pytest.raises(ValueError):
        run_suite(root, output, "missing-python")
    assert not output.exists()


def test_expected_fault_requires_wrong_pixel_evidence(tmp_path, monkeypatch):
    root = tmp_path / "suite"
    write_json(
        root / "suite.json",
        {
            "schema_version": "boundary-conformance-suite.v1",
            "synthetic_only": True,
            "producer": {},
            "cases": [{"name": "fault", "path": "fault", "expected": "fail"}],
        },
    )
    monkeypatch.setattr(
        "boundary_audit.conformance.verify_loader",
        lambda *a, **k: {"status": "fail", "source_unchanged": True, "records": [], "errors": ["runtime broke"]},
    )
    result = run_suite(root, tmp_path / "results", "missing-python", backends=["pyav"], phases=["single"])
    assert result["status"] == "fail"
    assert not result["checks"][0]["matched_expectation"]


def test_suite_html_escapes_untrusted_values(tmp_path):
    path = tmp_path / "report.html"
    write_suite_html({"status": "fail", "producer": {"version": "<script>"}, "checks": []}, path)
    assert "<script>" not in path.read_text(encoding="utf-8")
    assert "&lt;script&gt;" in path.read_text(encoding="utf-8")


def test_unsupported_producer_timing_keeps_repair_blocked(tmp_path, monkeypatch):
    source = tmp_path / "offset-one-frame"
    source.mkdir()
    (source / "original.txt").write_bytes(b"untouched")
    write_json(tmp_path / "suite.json", {"cases": [{"name": "offset-one-frame"}]})
    monkeypatch.setattr(
        "boundary_audit.conformance.make_plan",
        lambda *a, **k: {"status": "blocked", "refusals": ["Unsupported video repair"]},
    )
    add_repair_control(tmp_path)
    manifest = json.loads((tmp_path / "suite.json").read_text(encoding="utf-8"))
    assert manifest["repair_control"]["status"] == "blocked"
    assert len(manifest["cases"]) == 1
    assert not (tmp_path / "repaired-offset").exists()
    assert (source / "original.txt").read_bytes() == b"untouched"


def test_generation_refuses_existing_output(tmp_path):
    with pytest.raises(ValueError, match="new suite"):
        generate_suite(tmp_path, "no-python")


def test_cli_loader_unavailable_has_nonzero_exit(tmp_path):
    root = tmp_path / "dataset"
    write_json(root / "frame_oracle.json", {})
    assert (
        main(["verify-loader", str(root), "--python", str(tmp_path / "no-python"), "--out", str(tmp_path / "report")])
        == 2
    )
    report = json.loads((tmp_path / "report/loader-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "unavailable"

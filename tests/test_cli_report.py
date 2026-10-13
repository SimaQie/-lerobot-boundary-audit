import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from test_audit import dataset

from boundary_audit.audit import audit_dataset
from boundary_audit.cli import main
from boundary_audit.report import write_reports
from boundary_audit.verify import verify_consumer


def test_camera_scope_is_explicit_and_missing_streams_are_not_hidden(tmp_path):
    root = dataset(tmp_path)
    path = root / "meta/info.json"
    info = json.loads(path.read_text())
    info["features"]["other"] = {"dtype": "video"}
    path.write_text(json.dumps(info))
    report = audit_dataset(root, cameras=["camera"])
    assert report["status"] == "pass"
    assert report["dataset_coverage_status"] == "partial"
    assert report["selection"]["unselected_cameras"] == ["other"]
    with pytest.raises(KeyError):
        audit_dataset(root)  # missing metadata for a declared stream


def test_global_row_interleaving_is_detected(tmp_path):
    root = dataset(tmp_path)
    path = root / "data/chunk-000/file-000.parquet"
    rows = pq.read_table(path).to_pylist()
    rows = [rows[i] for i in [0, 3, 1, 4, 2, 5]]
    pq.write_table(pa.Table.from_pylist(rows), path)
    report = audit_dataset(root)
    assert report["status"] == "fail"
    assert report["finding_counts"]["EPISODE_DATA_RANGE_MISMATCH"] == 2


def test_report_escapes_untrusted_content_and_has_offline_controls(tmp_path):
    report = audit_dataset(dataset(tmp_path))
    report["findings"] = [
        {"code": "<script>injected()</script>", "severity": "error", "message": "<img src=x onerror=alert(1)>"}
    ]
    write_reports(report, tmp_path / "report")
    html = (tmp_path / "report/report.html").read_text(encoding="utf-8")
    assert "<script>injected()" not in html
    assert "&lt;img" in html
    assert 'id="severity"' in html
    assert "PASS applies only to selected cameras" in html
    assert "<script src=" not in html


def test_cli_legacy_and_subcommand_create_reports(tmp_path, capsys):
    root = dataset(tmp_path)
    for i, argv in enumerate([[str(root)], ["audit", str(root)]]):
        assert main(argv + ["--out", str(tmp_path / f"report{i}")]) == 0
        assert (tmp_path / f"report{i}/report.json").exists()
    assert "not_requested" in capsys.readouterr().out


def test_cli_cannot_write_reports_into_source(tmp_path):
    root = dataset(tmp_path)
    with pytest.raises(SystemExit) as error:
        main(["audit", str(root), "--out", str(root / "report")])
    assert error.value.code == 2
    assert not (root / "report").exists()


def test_missing_official_interpreter_is_unverified_not_pass(tmp_path):
    root = dataset(tmp_path)
    report = verify_consumer(root, str(tmp_path / "absent-python"))
    assert report["status"] == "partial"
    assert report["consumer_verification"]["status"] == "unavailable"
    assert report["consumer_verification"]["checked_queries"] == 0


def test_incomplete_published_dataset_is_rejected(tmp_path):
    root = dataset(tmp_path)
    (root / "INCOMPLETE").write_text("unfinished")
    with pytest.raises(ValueError, match="incomplete"):
        audit_dataset(root)

import hashlib

from boundary_audit.audit import audit_dataset
from boundary_audit.fixtures import export_demo
from boundary_audit.repair import fingerprint
from boundary_audit.report import write_reports
from boundary_audit.visuals import add_visual_evidence


def test_visual_frames_are_bounded_and_preserve_audit_status(tmp_path):
    export_demo(tmp_path / "demo")
    root = tmp_path / "demo" / "offset-one-frame"
    before = fingerprint(root)
    report = audit_dataset(root, decode=True)
    status = report["status"]
    output = tmp_path / "report"
    visual = add_visual_evidence(report, root, output, max_queries=1)
    assert visual["status"] == "complete"
    images = visual["records"][0]["images"]
    assert any("Observed local decode" in i["roles"] for i in images)
    assert any("Expected ordinal" in i["roles"] for i in images)
    expected = next(i["sample"] for i in images if "Expected ordinal" in i["roles"])
    observed = next(i["sample"] for i in images if "Observed local decode" in i["roles"])
    assert expected != observed
    for image in images:
        data = (output / image["path"]).read_bytes()
        assert data[:2] == b"\xff\xd8"
        assert hashlib.sha256(data).hexdigest() == image["sha256"]
    write_reports(report, output)
    assert "Observed local decode" in (output / "report.html").read_text(encoding="utf-8")
    limited = add_visual_evidence(report, root, tmp_path / "limited", max_frames=1)
    assert limited["status"] == "partial"
    assert limited["decoded_frames"] == 1
    assert report["status"] == status
    assert fingerprint(root) == before

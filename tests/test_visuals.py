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


def test_loader_visual_encoding_and_stale_cleanup(tmp_path):
    import numpy as np

    from boundary_audit.visuals import encode_rgb_jpeg, prepare_visual_output
    pixels = np.zeros((8, 10, 3), dtype=np.uint8)
    pixels[..., 0] = 200
    data = encode_rgb_jpeg(pixels)
    assert data[:2] == b"\xff\xd8"
    output = prepare_visual_output(tmp_path / "visuals")
    (output / "boundary-old.jpg").write_bytes(b"old")
    (output / "keep.txt").write_text("keep")
    prepare_visual_output(output)
    assert not (output / "boundary-old.jpg").exists()
    assert (output / "keep.txt").exists()


def test_probe_html_labels_loader_pixels_and_relative_paths(tmp_path):
    from boundary_audit.report import write_probe_html
    report = {
        "status": "partial",
        "coverage": None,
        "visual_evidence": {
            "status": "complete",
            "pixel_provenance": "Actual loader-returned pixels",
            "records": [
                {
                    "camera": "observation.images.cam_left_wrist",
                    "row_index": 10,
                    "episode_index": 1,
                    "frame_index": 3,
                    "expected_ordinal": 8,
                    "expected_pts_seconds": 0.16,
                    "actual_returned_labels": {"index": 10, "episode_index": 1, "frame_index": 3},
                    "comparison": {"status": "pass"},
                    "images": [
                        {"role": "loader_returned", "path": "visuals/a.jpg", "sha256": "a" * 64},
                        {"role": "expected_reference", "path": "visuals/b.jpg", "sha256": "b" * 64},
                    ],
                }
            ],
        },
    }
    write_probe_html(report, tmp_path / "report.html")
    text = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "Official loader returned pixels" in text
    assert "loader_returned" in text
    assert 'src="visuals/a.jpg"' in text
    assert "/home/" not in text

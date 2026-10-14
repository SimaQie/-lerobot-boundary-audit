import json
from pathlib import Path

import numpy as np
import pytest
from test_audit import dataset

from boundary_audit.cli import main
from boundary_audit.fixtures import export_demo
from boundary_audit.probe import prepare_probe, probe_loader
from boundary_audit.probe_driver import compare_pixels


def test_pixel_comparison_distinguishes_wrong_frame_from_ambiguous_identity():
    frames = {
        0: np.zeros((8, 8, 3), np.uint8),
        1: np.full((8, 8, 3), 100, np.uint8),
        2: np.full((8, 8, 3), 200, np.uint8),
    }
    assert compare_pixels(frames[1], frames, 1)["status"] == "pass"
    assert compare_pixels(frames[0], frames, 1)["status"] == "wrong_frame"
    assert compare_pixels(np.full((8, 8, 3), 101, np.uint8), frames, 1)["status"] == "pass"
    frames[2] = frames[1].copy()
    assert compare_pixels(frames[1], frames, 1)["status"] == "ambiguous"
    assert compare_pixels(np.full((8, 8, 3), 50, np.uint8), frames, 1)["status"] == "ambiguous"


def test_packaged_demo_has_multishard_and_independent_index_faults(tmp_path):
    root = tmp_path / "demo"
    result = export_demo(root)
    assert result["cases"] == 13
    assert len(list((root / "multi-data-shard/data/chunk-000").glob("*.parquet"))) == 5
    with pytest.raises(ValueError, match="new demo"):
        export_demo(root)


def test_probe_preparation_clamps_long_windows_in_nonconsecutive_subset(tmp_path):
    root = tmp_path / "demo"
    export_demo(root)
    source = root / "merged"
    request = prepare_probe(source, cameras=["observation.images.left"], episodes=[1, 3], max_rows=4, radius=8)
    assert {q["episode_index"] for q in request["queries"]} == {1, 3}
    for query in request["queries"]:
        lo, hi = request["episode_ranges"][str(query["episode_index"])]
        assert all(lo <= i < hi for i in query["indices"])
        assert query["padding"][0]  # radius 8 is outside these short episodes
    assert request == prepare_probe(source, cameras=["observation.images.left"], episodes=[1, 3], max_rows=4, radius=8)


def test_bounded_probe_sampling_spans_first_and_last_episode(tmp_path):
    root = tmp_path / "demo"
    export_demo(root)
    request = prepare_probe(root / "merged", cameras=["observation.images.left"], max_rows=6)
    assert {q["episode_index"] for q in request["queries"]} == {0, 4}
    assert len(request["queries"]) == 6


def test_probe_rejects_unknown_episode_and_budgets_before_official_load(tmp_path):
    root = tmp_path / "demo"
    export_demo(root)
    with pytest.raises(ValueError, match="existing"):
        prepare_probe(root / "merged", cameras=["observation.images.left"], episodes=[999])
    with pytest.raises(ValueError, match="budgets"):
        probe_loader(root / "merged", "missing", max_decode_frames=0)


def test_probe_invalid_storage_cannot_claim_loader_success(tmp_path):
    root = dataset(tmp_path)
    path = root / "meta/info.json"
    info = json.loads(path.read_text())
    del info["fps"]
    path.write_text(json.dumps(info))
    report = probe_loader(root, "missing")
    assert report["status"] == "fail"
    assert report["checked_rows"] == 0
    assert report["source_unchanged"]


def test_probe_missing_official_interpreter_is_unavailable(tmp_path):
    root = tmp_path / "demo"
    export_demo(root)
    report = probe_loader(root / "merged", str(tmp_path / "absent"), max_rows=2)
    assert report["status"] == "unavailable"
    assert report["source_unchanged"]


def test_cli_ambiguous_probe_is_partial_with_reports_and_exit_two(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    monkeypatch.setattr(
        "boundary_audit.probe.probe_loader",
        lambda *a, **k: {
            "status": "partial",
            "records": [{"status": "ambiguous", "reason": "identical frames"}],
            "checked_rows": 1,
        },
    )
    output = tmp_path / "results"
    assert main(["probe-loader", str(root), "--python", "stub", "--out", str(output)]) == 2
    assert json.loads((output / "probe-report.json").read_text())["status"] == "partial"
    assert "ambiguous" in (output / "report.html").read_text()


def test_no_source_write_even_if_official_process_changes_its_input(tmp_path, monkeypatch):
    root = tmp_path / "demo"
    export_demo(root)

    # The core detects a violated process contract, regardless of its reported PASS.
    def invoke(driver, python, request, **kwargs):
        Path(request["root"], "intruder.txt").write_text("changed")
        return {"status": "pass", "checked_rows": 1}

    monkeypatch.setattr("boundary_audit.probe.invoke", invoke)
    report = probe_loader(root / "merged", "stub", max_rows=1)
    assert report["status"] == "fail"
    assert not report["source_unchanged"]

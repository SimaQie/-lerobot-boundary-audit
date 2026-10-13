import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from test_mp4 import fixture

from boundary_audit.audit import audit_dataset, contained


def dataset(tmp_path, *, shift=False, edit=0, fractional=False):
    root = tmp_path / "dataset"
    root.mkdir()
    (root / "meta/episodes/chunk-000").mkdir(parents=True)
    (root / "data/chunk-000").mkdir(parents=True)
    (root / "videos/camera/chunk-000").mkdir(parents=True)
    info = {
        "codebase_version": "v3.0",
        "fps": 30,
        "total_episodes": 2,
        "total_frames": 6,
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
        "features": {"camera": {"dtype": "video"}},
    }
    (root / "meta/info.json").write_text(json.dumps(info))
    episodes = []
    for ep in range(2):
        begin, end = ep / 10, (ep + 1) / 10
        if shift and ep == 1:
            begin += 1 / 30
            end += 1 / 30
        episodes.append(
            {
                "episode_index": ep,
                "length": 3,
                "dataset_from_index": ep * 3,
                "dataset_to_index": (ep + 1) * 3,
                "videos/camera/chunk_index": 0,
                "videos/camera/file_index": 0,
                "videos/camera/from_timestamp": begin,
                "videos/camera/to_timestamp": end,
            }
        )
    pq.write_table(pa.Table.from_pylist(episodes), root / "meta/episodes/chunk-000/file-000.parquet")
    rows = [
        {"episode_index": ep, "frame_index": frame, "timestamp": frame / 30} for ep in range(2) for frame in range(3)
    ]
    pq.write_table(pa.Table.from_pylist(rows), root / "data/chunk-000/file-000.parquet")
    (root / "videos/camera/chunk-000/file-000.mp4").write_bytes(fixture([(6, 512)], edit=edit))
    return root


def test_clean_storage_timeline_passes_without_claiming_decode(tmp_path):
    report = audit_dataset(dataset(tmp_path))
    assert report["status"] == "pass"
    assert report["decoder"]["status"] == "not_requested"
    assert report["coverage"]["decoded_queries"] == 0
    assert report["coverage"]["boundary_queries"] == 6


def test_one_frame_offset_is_localized_to_changed_episode(tmp_path):
    report = audit_dataset(dataset(tmp_path, shift=True))
    assert report["status"] == "fail"
    assert {f["episode_index"] for f in report["findings"]} == {1}
    assert len([f for f in report["findings"] if f["code"] == "BOUNDARY_QUERY_MISMATCH"]) == 3


def test_unsupported_timeline_is_partial_not_clean(tmp_path):
    report = audit_dataset(dataset(tmp_path, edit=10))
    assert report["status"] == "partial"
    assert report["coverage"]["video_files_checked"] == 0


def test_missing_video_is_not_clean(tmp_path):
    root = dataset(tmp_path)
    (root / "videos/camera/chunk-000/file-000.mp4").unlink()
    assert audit_dataset(root)["status"] == "fail"


def test_partial_metadata_is_not_clean(tmp_path):
    root = dataset(tmp_path)
    path = root / "meta/episodes/chunk-000/file-000.parquet"
    pq.write_table(pq.read_table(path).slice(0, 1), path)
    assert audit_dataset(root)["status"] == "fail"


def test_data_timestamp_defect_is_reported_separately(tmp_path):
    root = dataset(tmp_path)
    path = root / "data/chunk-000/file-000.parquet"
    rows = pq.read_table(path).to_pylist()
    rows[2]["timestamp"] = 0.5
    pq.write_table(pa.Table.from_pylist(rows), path)
    report = audit_dataset(root)
    assert [f["code"] for f in report["findings"]] == ["DATA_TIMESTAMP_MISMATCH", "BOUNDARY_QUERY_MISMATCH"]
    query = next(q for q in report["boundary_queries"] if q["episode_index"] == 0 and q["frame_index"] == 2)
    assert query["request_seconds"] == 0.5  # actual stored row, not reconstructed frame/FPS


def test_symlink_or_relative_root_escape_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        contained(tmp_path.resolve(), Path("../outside.mp4"))


@pytest.mark.parametrize("tolerance", [0, -1, float("nan"), float("inf")])
def test_invalid_tolerance_rejected(tmp_path, tolerance):
    with pytest.raises(ValueError, match="Tolerance"):
        audit_dataset(dataset(tmp_path), tolerance=tolerance)

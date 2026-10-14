import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from test_audit import dataset

from boundary_audit.audit import audit_dataset
from boundary_audit.cli import main
from boundary_audit.repair import make_plan


@pytest.mark.parametrize("kind", ["shift", "duplicate", "null", "negative", "float", "missing"])
def test_global_index_defects_block_storage_pass_and_repair(tmp_path, kind):
    root = dataset(tmp_path)
    path = root / "data/chunk-000/file-000.parquet"
    table = pq.read_table(path)
    values = list(range(6))
    if kind == "shift":
        values = [i + 1 for i in values]
    elif kind == "duplicate":
        values[4] = values[3]
    elif kind == "null":
        values[1] = None
    elif kind == "negative":
        values[1] = -1
    if kind == "missing":
        table = table.drop(["index"])
    else:
        table = table.set_column(0, "index", pa.array(values, type=pa.float64() if kind == "float" else pa.int64()))
    pq.write_table(table, path)
    report = audit_dataset(root)
    assert report["status"] == "fail"
    assert any(
        k in report["finding_counts"]
        for k in ("GLOBAL_INDEX_MISMATCH", "DATA_INDEX_VALUE_INVALID", "DATA_INDEX_TYPE_INVALID", "DATA_COLUMN_MISSING")
    )
    assert make_plan(root, assume_cfr=True)["status"] == "blocked"


def test_global_indices_continue_across_correct_shards(tmp_path):
    root = dataset(tmp_path)
    path = root / "data/chunk-000/file-000.parquet"
    table = pq.read_table(path)
    pq.write_table(table.slice(0, 3), path)
    pq.write_table(table.slice(3), path.with_name("file-001.parquet"))
    metadata = root / "meta/episodes/chunk-000/file-000.parquet"
    rows = pq.read_table(metadata).to_pylist()
    rows[1]["data/file_index"] = 1
    pq.write_table(pa.Table.from_pylist(rows), metadata)
    assert audit_dataset(root)["status"] == "pass"
    rows[1]["data/file_index"] = 0
    pq.write_table(pa.Table.from_pylist(rows), metadata)
    assert "DATA_SHARD_REFERENCE_MISMATCH" in audit_dataset(root)["finding_counts"]


def test_missing_prerequisite_still_produces_reports(tmp_path):
    root = dataset(tmp_path)
    path = root / "meta/info.json"
    info = json.loads(path.read_text())
    del info["fps"]
    path.write_text(json.dumps(info))
    out = tmp_path / "report"
    assert main(["audit", str(root), "--out", str(out)]) == 1
    assert json.loads((out / "report.json").read_text())["status"] == "fail"
    assert (out / "report.html").exists()


def test_corrupt_shard_does_not_hide_other_shard_index_fault(tmp_path):
    root = dataset(tmp_path)
    path = root / "data/chunk-000/file-000.parquet"
    table = pq.read_table(path)
    rows = table.to_pylist()[3:]
    for row in rows:
        row["index"] += 50
    pq.write_table(pa.Table.from_pylist(rows), path.with_name("file-001.parquet"))
    path.write_bytes(b"broken parquet")
    report = audit_dataset(root)
    assert "DATA_SHARD_UNREADABLE" in report["finding_counts"]
    assert "GLOBAL_INDEX_MISMATCH" in report["finding_counts"]


def test_unreadable_previous_shard_does_not_mislabel_correct_later_indices(tmp_path):
    root = dataset(tmp_path)
    path = root / "data/chunk-000/file-000.parquet"
    table = pq.read_table(path)
    pq.write_table(table.slice(3), path.with_name("file-001.parquet"))
    path.write_bytes(b"broken parquet")
    report = audit_dataset(root)
    assert report["status"] == "fail"
    assert "DATA_SHARD_UNREADABLE" in report["finding_counts"]
    assert "GLOBAL_INDEX_MISMATCH" not in report["finding_counts"]
    assert "EPISODE_DATA_RANGE_MISMATCH" not in report["finding_counts"]

"""Real encoded media exercises write, readback and exact-byte restoration."""

import copy
from fractions import Fraction

import av
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from test_audit import dataset

from boundary_audit.audit import audit_dataset
from boundary_audit.mp4 import read_timeline
from boundary_audit.repair import (
    apply_plan,
    document_hash,
    fingerprint,
    make_plan,
    media_hash,
    restore_copy,
)


def encode(path, *, bframes=0, durations=None):
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=30)
        stream.width, stream.height, stream.pix_fmt = 48, 32, "yuv420p"
        stream.time_base = Fraction(1, 15360)
        stream.codec_context.time_base = Fraction(1, 15360)
        stream.options = {"bf": str(bframes), "g": "12", "crf": "18"}
        packets = []
        for i in range(6):
            pixels = np.zeros((32, 48, 3), dtype=np.uint8)
            pixels[:, : 8 + i * 5, :] = [i * 35, 180, 255 - i * 30]
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base = i * 512, Fraction(1, 15360)
            packets.extend(stream.encode(frame))
        packets.extend(stream.encode(None))
        if durations:
            tick = 0
            for packet, duration in zip(packets, durations, strict=True):
                packet.time_base = Fraction(1, 15360)
                packet.pts = packet.dts = tick
                packet.duration = duration
                tick += duration
        for packet in packets:
            container.mux(packet)


def real_dataset(tmp_path, *, shift=False, bframes=0, durations=None):
    root = dataset(tmp_path, shift=shift)
    encode(root / "videos/camera/chunk-000/file-000.mp4", bframes=bframes, durations=durations)
    return root


def test_real_b_frame_pts_match_decoded_presentation_order(tmp_path):
    root = real_dataset(tmp_path, bframes=2)
    video = root / "videos/camera/chunk-000/file-000.mp4"
    timeline = read_timeline(video)
    assert timeline.composition is not None
    with av.open(str(video)) as container:
        decoded = [float(f.pts * f.time_base) for f in container.decode(video=0)]
    assert decoded == [timeline.tick_at(i) / timeline.timescale for i in range(6)]
    assert audit_dataset(root, decode=True)["status"] == "pass"


@pytest.mark.parametrize("kind", ["offset", "one_tick"])
def test_apply_verify_restore_exactly_without_source_changes(tmp_path, kind):
    root = real_dataset(
        tmp_path, shift=kind == "offset", durations=[512, 511, 512, 512, 512, 512] if kind == "one_tick" else None
    )
    original = fingerprint(root)
    video = "videos/camera/chunk-000/file-000.mp4"
    payload = media_hash(root / video)
    assert make_plan(root)["status"] == "contract_required"
    plan = make_plan(root, assume_cfr=True)
    assert plan["status"] == "ready"
    repaired = tmp_path / "repaired"
    receipt = apply_plan(plan, root, repaired)
    assert receipt["verification"]["status"] == "pass"
    assert media_hash(repaired / video) == payload
    assert fingerprint(root) == original
    restored = tmp_path / "restored"
    assert restore_copy(repaired, restored)["original_file_hashes_verified"]
    assert fingerprint(restored) == original


def test_modified_plan_is_rejected_even_if_its_hash_is_recomputed(tmp_path):
    root = real_dataset(tmp_path, shift=True)
    plan = make_plan(root, assume_cfr=True)
    altered = copy.deepcopy(plan)
    altered["operations"][0]["changes"][0]["after"] = 1.0
    altered["fingerprint"] = document_hash({k: v for k, v in altered.items() if k != "fingerprint"})
    with pytest.raises(ValueError, match="allowed parser-derived"):
        apply_plan(altered, root, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_changed_source_is_rejected(tmp_path):
    root = real_dataset(tmp_path, shift=True)
    plan = make_plan(root, assume_cfr=True)
    (root / "extra.txt").write_text("changed")
    with pytest.raises(ValueError, match="fingerprint changed"):
        apply_plan(plan, root, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


@pytest.mark.parametrize("destination", ["dataset", "dataset/child", "existing"])
def test_existing_and_overlapping_outputs_are_refused(tmp_path, destination):
    root = real_dataset(tmp_path, shift=True)
    if destination == "existing":
        (tmp_path / destination).mkdir()
    plan = make_plan(root, assume_cfr=True)
    with pytest.raises(ValueError, match="new output"):
        apply_plan(plan, root, tmp_path / destination)


def test_unrepairable_data_rows_block_changes(tmp_path):
    root = real_dataset(tmp_path, shift=True)
    path = root / "data/chunk-000/file-000.parquet"
    rows = pq.read_table(path).to_pylist()
    rows[1]["timestamp"] = 0.9
    pq.write_table(pa.Table.from_pylist(rows), path)
    assert make_plan(root, assume_cfr=True)["status"] == "blocked"


def test_global_clock_error_is_not_automatically_repaired(tmp_path):
    root = real_dataset(tmp_path, durations=[513] * 6)
    plan = make_plan(root, assume_cfr=True)
    # Six samples technically fit the small repair budget. Extend the stts run
    # count via a separate parser fixture to exercise a genuinely long clock error.
    from test_mp4 import fixture

    (root / "videos/camera/chunk-000/file-000.mp4").write_bytes(fixture([(100, 513)]))
    plan = make_plan(root, assume_cfr=True)
    assert plan["status"] == "blocked"
    assert not any(op["kind"] == "mp4_fields" for op in plan["operations"])


def test_failure_during_verification_publishes_no_output(tmp_path, monkeypatch):
    root = real_dataset(tmp_path, shift=True)
    original = fingerprint(root)
    plan = make_plan(root, assume_cfr=True)
    import boundary_audit.repair as repair

    real_audit = repair.audit_dataset

    def failing_audit(*args, **kwargs):
        if kwargs.get("decode"):
            raise ValueError("injected decoder failure")
        return real_audit(*args, **kwargs)

    monkeypatch.setattr(repair, "audit_dataset", failing_audit)
    with pytest.raises(ValueError, match="injected"):
        apply_plan(plan, root, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()
    assert fingerprint(root) == original


def test_restore_detects_modified_metadata_backup(tmp_path):
    root = real_dataset(tmp_path, shift=True)
    repaired = tmp_path / "repaired"
    receipt = apply_plan(make_plan(root, assume_cfr=True), root, repaired)
    backup = next(iter(receipt["metadata_backups"].values()))
    (repaired / backup).write_bytes(b"changed")
    with pytest.raises(ValueError, match="backup has changed"):
        restore_copy(repaired, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()

"""Generate six original synthetic frames; demonstrate guarded repair offline.

This minimal v3 fixture exercises this tool, not a complete training dataset.
The pixels are procedurally generated and contain no downloaded dataset content.
"""

import argparse
import json
from fractions import Fraction
from pathlib import Path

import av
import pyarrow as pa
import pyarrow.parquet as pq

from boundary_audit.audit import audit_dataset
from boundary_audit.repair import apply_plan, fingerprint, make_plan, restore_copy
from boundary_audit.report import write_reports
from boundary_audit.storage import write_json


def create_fixture(root):
    root = Path(root)
    root.mkdir()  # no replacement
    for path in ["meta/episodes/chunk-000", "data/chunk-000", "videos/camera/chunk-000"]:
        (root / path).mkdir(parents=True)
    write_json(
        root / "meta/info.json",
        {
            "codebase_version": "v3.0",
            "fps": 30,
            "total_episodes": 2,
            "total_frames": 6,
            "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
            "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
            "features": {"camera": {"dtype": "video"}},
        },
    )
    episodes = [
        {
            "episode_index": ep,
            "length": 3,
            "data/chunk_index": 0,
            "data/file_index": 0,
            "dataset_from_index": ep * 3,
            "dataset_to_index": (ep + 1) * 3,
            "videos/camera/chunk_index": 0,
            "videos/camera/file_index": 0,
            "videos/camera/from_timestamp": ep / 10,
            "videos/camera/to_timestamp": (ep + 1) / 10,
        }
        for ep in range(2)
    ]
    pq.write_table(pa.Table.from_pylist(episodes), root / "meta/episodes/chunk-000/file-000.parquet")
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"index": ep * 3 + i, "episode_index": ep, "frame_index": i, "timestamp": i / 30}
                for ep in range(2)
                for i in range(3)
            ]
        ),
        root / "data/chunk-000/file-000.parquet",
    )
    with av.open(str(root / "videos/camera/chunk-000/file-000.mp4"), "w") as container:
        stream = container.add_stream("libx264", rate=30)
        stream.width, stream.height, stream.pix_fmt = 48, 32, "yuv420p"
        stream.time_base = stream.codec_context.time_base = Fraction(1, 15360)
        stream.options = {"bf": "0", "g": "12"}
        packets = []
        for i in range(6):
            frame = av.VideoFrame(48, 32, "rgb24")
            pixels = bytes([i * 35, 180, 255 - i * 30]) * 48 * 32
            frame.planes[0].update(pixels)
            frame.pts, frame.time_base = i * 512, Fraction(1, 15360)
            packets.extend(stream.encode(frame))
        packets.extend(stream.encode(None))
        tick = 0
        for i, packet in enumerate(packets):
            packet.time_base = Fraction(1, 15360)
            packet.pts = packet.dts = tick
            packet.duration = 511 if i == 1 else 512  # controlled one-tick defect
            tick += packet.duration
            container.mux(packet)
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir()
    root = create_fixture(args.out / "original")
    before = fingerprint(root)
    write_reports(audit_dataset(root, decode=True), args.out / "before-report")
    plan = make_plan(root, assume_cfr=True)
    write_json(args.out / "plan.json", plan)
    receipt = apply_plan(plan, root, args.out / "repaired")
    write_reports(audit_dataset(args.out / "repaired", decode=True), args.out / "after-report")
    restored = restore_copy(args.out / "repaired", args.out / "restored")
    result = {
        "synthetic_controlled_injection": True,
        "before": "review",
        "after": receipt["verification"]["status"],
        "source_unchanged": fingerprint(root) == before,
        "restored_exactly": fingerprint(args.out / "restored") == before,
        "restore": restored,
    }
    write_json(args.out / "result.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

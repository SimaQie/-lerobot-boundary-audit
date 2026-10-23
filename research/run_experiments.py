"""Controlled injections on copied public data; never mutate the pinned source."""
from collections import Counter
import argparse
import io
import hashlib
import json
from pathlib import Path
import shutil
import struct

import pyarrow.parquet as pq
import pyarrow as pa

from boundary_audit.audit import audit_dataset
from boundary_audit.cli import write_reports
from boundary_audit.mp4 import boxes, read_timeline


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "samples/pusht"
DERIVED = PROJECT / "research/derived"
RESULTS = PROJECT / "research/results"


def fingerprint(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def copy_case(name):
    out = DERIVED / name
    # No existing directory is overwritten, so a rerun cannot erase user work.
    if out.exists():
        raise FileExistsError(f"Experiment output already exists: {out}")
    shutil.copytree(SOURCE, out)
    return out


def inject_single_tick_step(video, first_shifted_sample):
    """Research fixture: expand a trailing moov stts into three runs.

    This operation is ONLY a controlled defect generator. It is not a repair
    command. A trailing moov means expanded table lengths do not move mdat or
    chunk offsets. Refuse any other layout rather than guessing.
    """
    original = video.read_bytes()
    stream = io.BytesIO(original)
    top = list(boxes(stream, 0, len(original)))
    if top[-1].kind != b"moov" or any(b.kind == b"mdat" and b.end > top[-1].start for b in top):
        raise ValueError("Single-tick fixture requires a trailing moov")
    timeline = read_timeline(video)
    if len(timeline.runs) != 1 or timeline.mdhd_version != 0:
        raise ValueError("Single-tick fixture requires one stts run and v0 mdhd")
    count, delta = timeline.runs[0]
    at = first_shifted_sample - 1
    if not 0 < at < count - 1:
        raise ValueError("Invalid injected boundary")
    candidates = []
    def walk(parent, ancestors):
        for child in boxes(stream, parent.start, parent.end):
            if child.kind == b"stts":
                candidates.append((child, ancestors + [parent]))
            elif child.kind in {b"trak", b"mdia", b"minf", b"stbl"}:
                walk(child, ancestors + [parent])
    walk(top[-1], [])
    if len(candidates) != 1:
        raise ValueError("Ambiguous stts fixture")
    table, parents = candidates[0]
    runs = [(at, delta), (1, delta - 1), (count - at - 1, delta)]
    new_payload = bytes(4) + struct.pack(">I", 3) + b"".join(struct.pack(">II", *run) for run in runs)
    growth = len(new_payload) - (table.end - table.start)
    mutable = bytearray(original)
    for parent in parents + [table]:
        size_offset = parent.start - 8
        old_size = struct.unpack_from(">I", mutable, size_offset)[0]
        if old_size != parent.end - size_offset:
            raise ValueError("Extended-size containers are not supported by fixture generator")
        struct.pack_into(">I", mutable, size_offset, old_size + growth)
    struct.pack_into(">I", mutable, timeline.duration_offset, timeline.duration - 1)
    mutable[table.start:table.end] = new_payload
    video.write_bytes(mutable)
    source_media = [original[b.start:b.end] for b in top if b.kind == b"mdat"]
    altered = io.BytesIO(mutable)
    changed_media = [bytes(mutable[b.start:b.end]) for b in boxes(altered, 0, len(mutable)) if b.kind == b"mdat"]
    if source_media != changed_media:
        raise AssertionError("Fixture generator changed media payload")
    return {"first_shifted_sample": first_shifted_sample, "media_payload_unchanged": True,
            "media_payload_sha256": hashlib.sha256(b"".join(source_media)).hexdigest()}


def main():
    global DERIVED, RESULTS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=PROJECT / "research", help="Use a fresh directory for every rerun")
    args = parser.parse_args()
    workspace = args.out.resolve()
    if workspace.is_relative_to(SOURCE.resolve()) or SOURCE.resolve().is_relative_to(workspace):
        raise ValueError("Experiment workspace must not overlap the source dataset")
    DERIVED, RESULTS = workspace / "derived", workspace / "results"
    DERIVED.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    before = fingerprint(SOURCE)
    records = []
    baseline = audit_dataset(SOURCE, decode=True)
    write_reports(baseline, RESULTS / "pusht-baseline")
    records.append({"case": "untouched_public_source", "kind": "public_baseline", "status": baseline["status"],
                    "coverage": baseline["coverage"], "timing_seconds": baseline["timing_seconds"],
                    "findings": dict(Counter(f["code"] for f in baseline["findings"]))})

    case = copy_case("metadata-one-frame-shift")
    meta = case / "meta/episodes/chunk-000/file-000.parquet"
    table = pq.read_table(meta)
    for column in ["videos/observation.image/from_timestamp", "videos/observation.image/to_timestamp"]:
        values = table[column].to_pylist()
        index = table["episode_index"].to_pylist().index(17)
        values[index] += 0.1
        table = table.set_column(table.schema.get_field_index(column), table.schema.field(column), pa.array(values, type=table[column].type))
    pq.write_table(table, meta)
    report = audit_dataset(case, decode=True)
    write_reports(report, RESULTS / "metadata-one-frame-shift")
    records.append({"case": "metadata-one-frame-shift", "kind": "controlled_injection", "status": report["status"],
                    "expected_affected_episode": 17,
                    "affected_episodes": sorted({f["episode_index"] for f in report["findings"] if "episode_index" in f}),
                    "findings": dict(Counter(f["code"] for f in report["findings"]))})

    case = copy_case("single-tick-step-at-episode-17")
    source_episodes = pq.read_table(case / "meta/episodes/chunk-000/file-000.parquet",
                                   columns=["episode_index", "length"]).to_pylist()
    boundary = sum(e["length"] for e in source_episodes if e["episode_index"] < 17)
    injection = inject_single_tick_step(case / "videos/observation.image/chunk-000/file-000.mp4", boundary)
    report = audit_dataset(case, decode=True)
    write_reports(report, RESULTS / "single-tick-step-at-episode-17")
    records.append({"case": "single-tick-step-at-episode-17", "kind": "controlled_injection", "status": report["status"],
                    **injection, "deviation_seconds": report["video_reports"][0]["max_abs_deviation_seconds"],
                    "findings": dict(Counter(f["code"] for f in report["findings"]))})

    case = copy_case("container-duration-one-tick-short-per-frame")
    video = case / "videos/observation.image/chunk-000/file-000.mp4"
    timeline = read_timeline(video)
    if timeline.mdhd_version != 0 or len(timeline.runs) != 1:
        raise ValueError("This deterministic injection expects one stts run and v0 mdhd")
    count, delta = timeline.runs[0]
    with video.open("r+b") as stream:
        stream.seek(timeline.delta_offsets[0])
        stream.write(struct.pack(">I", delta - 1))
        stream.seek(timeline.duration_offset)
        stream.write(struct.pack(">I", count * (delta - 1)))
    # This is an intentionally constructed global duration error, not the
    # historical single-boundary A1 defect and not a real defect in PushT.
    report = audit_dataset(case, decode=False)
    write_reports(report, RESULTS / "container-duration-one-tick-short-per-frame")
    records.append({"case": "container-duration-one-tick-short-per-frame", "kind": "controlled_injection",
                    "status": report["status"], "expected_final_deviation_ticks": -(count - 1),
                    "observed_max_deviation_ticks": report["video_reports"][0]["max_abs_deviation_ticks"],
                    "findings": dict(Counter(f["code"] for f in report["findings"]))})
    after = fingerprint(SOURCE)
    if before != after:
        raise AssertionError("The source dataset changed")
    result = {"source_manifest": json.loads((PROJECT / "samples/source_manifest.json").read_text()),
              "source_unchanged": True, "cases": records,
              "claim_boundary": "Controlled defects demonstrate detection and localization; no natural PushT defect or policy improvement is claimed."}
    (RESULTS / "experiment_summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"source_unchanged": True, "cases": records}, indent=2), flush=True)
    assert baseline["status"] == "pass"
    assert records[1]["affected_episodes"] == [17]
    assert records[1]["findings"].get("DECODE_BOUNDARY_MISMATCH") == 3
    assert records[2]["status"] == "review"
    assert records[2]["findings"] == {"VIDEO_GRID_DEVIATION": 1}
    assert records[3]["observed_max_deviation_ticks"] == count - 1


if __name__ == "__main__":
    main()

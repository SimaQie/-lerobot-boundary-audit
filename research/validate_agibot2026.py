"""Reproducible recent-data validation; every fault lives in a new derivative."""

import argparse
import json
import shutil
import time
from collections import Counter
from pathlib import Path

import av
import pyarrow as pa
import pyarrow.parquet as pq

from boundary_audit.audit import audit_dataset
from boundary_audit.download import SAMPLES, sha256
from boundary_audit.repair import apply_plan, fingerprint, make_plan, restore_copy
from boundary_audit.report import write_reports
from boundary_audit.storage import write_json
from boundary_audit.verify import verify_consumer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("samples/agibot2026"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--consumer-python", type=Path)
    parser.add_argument("--ffmpeg-bin", type=Path)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.out.resolve()
    if output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("Experiment output must not overlap input")
    output.mkdir()
    cameras = SAMPLES["agibot2026"]["cameras"]
    original = fingerprint(source)
    manifest = json.loads((source / "source_manifest.json").read_text())
    for entry in manifest["files"]:
        if sha256(source / entry["path"]) != entry["sha256"]:
            raise ValueError("Sample no longer matches its source receipt")
    summary = {
        "source": {k: manifest[k] for k in ["repository", "revision", "license", "total_bytes"]},
        "cameras": cameras,
    }
    baseline = audit_dataset(source, cameras=cameras, decode=True)
    baseline["sample_source"] = summary["source"]
    write_reports(baseline, output / "baseline")
    assert baseline["status"] == "pass", baseline["finding_counts"]
    summary["baseline"] = {"status": baseline["status"], "coverage": baseline["coverage"]}
    print("Local baseline passed", flush=True)
    if args.consumer_python:
        for backend in ["pyav", "torchcodec"]:
            report = verify_consumer(
                source,
                str(args.consumer_python.resolve()),
                cameras=cameras,
                backend=backend,
                ffmpeg_bin=args.ffmpeg_bin.resolve() if args.ffmpeg_bin else None,
            )
            report["sample_source"] = summary["source"]
            write_reports(report, output / f"official-{backend}")
            summary[f"official_{backend}"] = {
                k: v for k, v in report["consumer_verification"].items() if k != "records"
            }
            assert report["status"] == "pass", summary[f"official_{backend}"]
            print(f"Official {backend} passed", flush=True)
    # Independent reference: PyAV full presentation decode without importing the
    # project's MP4 parser. This supplements the sparse boundary checks.
    references = []
    for camera in cameras:
        video = source / f"videos/{camera}/chunk-000/file-000.mp4"
        start = time.perf_counter()
        count, max_error = 0, 0.0
        with av.open(str(video)) as container:
            container.streams.video[0].codec_context.thread_count = 2
            for frame in container.decode(video=0):
                if frame.pts is None:
                    raise ValueError("Decoded frame has no PTS")
                max_error = max(max_error, abs(float(frame.pts * frame.time_base) - count / 30))
                count += 1
        assert count == 23658 and max_error < 1e-8
        references.append(
            {
                "camera": camera,
                "frames": count,
                "max_grid_error_seconds": max_error,
                "elapsed_seconds": time.perf_counter() - start,
            }
        )
        print(f"Independent full decode passed: {camera}, {count} frames", flush=True)
    summary["full_decode_reference"] = references
    faulty = output / "faulty"
    shutil.copytree(source, faulty)
    metadata = faulty / "meta/episodes/chunk-000/file-000.parquet"
    table = pq.read_table(metadata)
    rows = table.to_pylist()
    target = 4
    for row in rows:
        if row["episode_index"] == target:
            for camera in cameras:
                for suffix in ["from_timestamp", "to_timestamp"]:
                    row[f"videos/{camera}/{suffix}"] += 1 / 30
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), metadata)
    faulty_hashes = fingerprint(faulty)
    report = audit_dataset(faulty, cameras=cameras, decode=True)
    write_reports(report, output / "injection-before")
    assert report["status"] == "fail"
    assert {f["episode_index"] for f in report["findings"]} == {target}
    summary["controlled_metadata_injection"] = {"episode": target, "finding_counts": report["finding_counts"]}
    if args.consumer_python:
        report = verify_consumer(
            faulty,
            str(args.consumer_python.resolve()),
            cameras=cameras,
            ffmpeg_bin=args.ffmpeg_bin.resolve() if args.ffmpeg_bin else None,
        )
        write_reports(report, output / "injection-official-before")
        assert report["consumer_verification"]["status"] == "fail"
        summary["controlled_metadata_injection"]["official_before"] = dict(
            Counter(r["status"] for r in report["consumer_verification"]["records"])
        )
    plan = make_plan(faulty, cameras=cameras, assume_cfr=True)
    write_json(output / "repair-plan.json", plan)
    receipt = apply_plan(plan, faulty, output / "repaired")
    repaired_report = audit_dataset(output / "repaired", cameras=cameras, decode=True)
    write_reports(repaired_report, output / "injection-after")
    if args.consumer_python:
        repaired_report = verify_consumer(
            output / "repaired",
            str(args.consumer_python.resolve()),
            cameras=cameras,
            ffmpeg_bin=args.ffmpeg_bin.resolve() if args.ffmpeg_bin else None,
        )
        write_reports(repaired_report, output / "injection-official-after")
        assert repaired_report["status"] == "pass"
    restore = restore_copy(output / "repaired", output / "restored")
    summary["repair"] = {
        "operations": len(plan["operations"]),
        "status": receipt["verification"]["status"],
        "official_after": repaired_report.get("consumer_verification", {}).get("status"),
        "restored_exactly": fingerprint(output / "restored") == faulty_hashes,
        "restore": restore,
    }
    summary["source_unchanged"] = fingerprint(source) == original
    assert summary["source_unchanged"] and summary["repair"]["restored_exactly"]
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()

"""Identical bounded validation protocol for the two pinned real-robot samples.

Only new derivative directories are modified. Downloaded videos are never published.
"""

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
from boundary_audit.probe import probe_loader
from boundary_audit.repair import apply_plan, fingerprint, make_plan, restore_copy
from boundary_audit.report import write_probe_html, write_reports
from boundary_audit.storage import write_json
from boundary_audit.verify import verify_consumer


def run(sample, source, output, python, ffmpeg_bin):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("Use a fresh, nonoverlapping experiment directory")
    manifest = json.loads((source / "source_manifest.json").read_text())
    spec = SAMPLES[sample]
    if manifest["repository"] != spec["repo"] or manifest["revision"] != spec["revision"]:
        raise ValueError("Input receipt differs from the pinned sample")
    for entry in manifest["files"]:
        if sha256(source / entry["path"]) != entry["sha256"]:
            raise ValueError("Source file no longer matches download receipt")
    output.mkdir(parents=True)
    before = fingerprint(source)
    cameras = spec["cameras"]
    info = json.loads((source / "meta/info.json").read_text())
    summary = {
        "schema_version": "boundary-real-validation.v1",
        "sample": sample,
        "source": {k: manifest[k] for k in ("repository", "revision", "license", "total_bytes")},
        "dataset": {
            "episodes": info["total_episodes"],
            "frames": info["total_frames"],
            "fps": info["fps"],
            "declared_cameras": len([v for v in info["features"].values() if v["dtype"] == "video"]),
            "selected_cameras": cameras,
            "action_shape": info["features"]["action"]["shape"],
        },
        "protocol": {
            "probe_max_rows": 6,
            "radius": 1,
            "phase": "workers",
            "seed": 20261014,
            "timeout_seconds": 600,
            "max_decode_frames": 50000,
            "max_reference_bytes": 268435456,
            "max_view_bytes": 314572800,
        },
        "controlled_only": True,
        "natural_defect_claim": False,
    }
    baseline = audit_dataset(source, cameras=cameras, decode=True)
    baseline["sample_source"] = summary["source"]
    write_reports(baseline, output / "baseline")
    summary["baseline"] = {k: baseline[k] for k in ("status", "coverage", "finding_counts")}
    write_json(output / "summary.json", summary)
    if baseline["status"] != "pass":
        summary["status"] = "review_required"
        write_json(output / "summary.json", summary)
        return summary
    print(sample + ": storage/decode baseline passed", flush=True)
    summary["official_decoders"], summary["loader_probes"] = {}, {}
    for backend in ("pyav", "torchcodec"):
        report = verify_consumer(
            source, str(python), cameras=cameras, backend=backend, ffmpeg_bin=ffmpeg_bin, timeout=600
        )
        write_reports(report, output / ("official-" + backend))
        summary["official_decoders"][backend] = {
            k: v for k, v in report["consumer_verification"].items() if k != "records"
        }
        print(sample + ": official " + backend + " " + report["consumer_verification"]["status"], flush=True)
        probe = probe_loader(
            source,
            python,
            cameras=cameras,
            backend=backend,
            phase="workers",
            max_rows=6,
            radius=1,
            seed=20261014,
            timeout=600,
            ffmpeg_bin=ffmpeg_bin,
        )
        write_json(output / ("probe-" + backend) / "probe-report.json", probe)
        write_probe_html(probe, output / ("probe-" + backend) / "report.html")
        summary["loader_probes"][backend] = {
            k: probe.get(k)
            for k in (
                "status",
                "requested_rows",
                "checked_rows",
                "frame_checks",
                "passed_frame_checks",
                "ambiguous_frame_checks",
                "row_errors",
                "errors",
                "source_unchanged",
                "versions",
            )
        }
        print(sample + ": full-loader " + backend + " " + probe["status"], flush=True)
        write_json(output / "summary.json", summary)
    reference = []
    for video in baseline["video_reports"]:
        start = time.perf_counter()
        count, max_error = 0, 0.0
        with av.open(str(source / video["path"])) as container:
            stream = container.streams.video[0]
            stream.codec_context.thread_count = 1
            codec = stream.codec_context.name
            for frame in container.decode(stream):
                if frame.pts is None:
                    raise ValueError("Reference frame lacks PTS")
                max_error = max(max_error, abs(float(frame.pts * frame.time_base) - count / info["fps"]))
                count += 1
        reference.append(
            {
                "video": video["path"],
                "codec": codec,
                "frames": count,
                "expected_frames": video["samples"],
                "max_grid_error_seconds": max_error,
                "elapsed_seconds": time.perf_counter() - start,
                "status": "pass" if count == video["samples"] and max_error < 1e-8 else "review",
            }
        )
        print(sample + ": sequential reference " + str(count) + " frames", flush=True)
    summary["full_pts_reference"] = reference
    faulty = output / "offset-fault"
    shutil.copytree(source, faulty)
    target = info["total_episodes"] // 2
    for path in sorted((faulty / "meta/episodes").glob("chunk-*/file-*.parquet")):
        table = pq.read_table(path)
        rows = table.to_pylist()
        for row in rows:
            if row["episode_index"] == target:
                for camera in cameras:
                    for suffix in ("from_timestamp", "to_timestamp"):
                        row[f"videos/{camera}/{suffix}"] += 1 / info["fps"]
        pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
    faulty_before = fingerprint(faulty)
    offset_report = audit_dataset(faulty, cameras=cameras, decode=True)
    write_reports(offset_report, output / "offset-before")
    detected = offset_report["status"] == "fail" and {f.get("episode_index") for f in offset_report["findings"]} == {
        target
    }
    summary["offset_control"] = {
        "episode": target,
        "shift_seconds": 1 / info["fps"],
        "localized": detected,
        "finding_counts": offset_report["finding_counts"],
    }
    offset_official = verify_consumer(
        faulty, str(python), cameras=cameras, backend="torchcodec", ffmpeg_bin=ffmpeg_bin, timeout=600
    )
    write_reports(offset_official, output / "offset-official-before")
    summary["offset_control"]["official_before"] = dict(
        Counter(r["status"] for r in offset_official["consumer_verification"].get("records", []))
    )
    plan = make_plan(faulty, cameras=cameras, assume_cfr=True)
    write_json(output / "repair-plan.json", plan)
    summary["repair"] = {"status": plan["status"], "refusals": plan["refusals"]}
    if plan["status"] == "ready":
        receipt = apply_plan(plan, faulty, output / "repaired")
        after = verify_consumer(
            output / "repaired", str(python), cameras=cameras, backend="torchcodec", ffmpeg_bin=ffmpeg_bin, timeout=600
        )
        write_reports(after, output / "offset-official-after")
        restore_copy(output / "repaired", output / "restored")
        summary["repair"].update(
            verification=receipt["verification"]["status"],
            official_after=after["consumer_verification"]["status"],
            exact_restore=fingerprint(output / "restored") == faulty_before,
            faulty_source_unchanged=fingerprint(faulty) == faulty_before,
        )
    index_fault = output / "index-fault"
    shutil.copytree(source, index_fault)
    for path in sorted((index_fault / "data").glob("chunk-*/file-*.parquet")):
        table = pq.read_table(path)
        values = [v + 1 for v in table["index"].to_pylist()]
        position = table.schema.get_field_index("index")
        table = table.set_column(position, "index", pa.array(values, type=table.schema.field("index").type))
        pq.write_table(table, path)
    index_report = audit_dataset(index_fault, cameras=cameras)
    write_reports(index_report, output / "index-before")
    index_plan = make_plan(index_fault, cameras=cameras, assume_cfr=True)
    write_json(output / "index-repair-plan.json", index_plan)
    summary["index_control"] = {
        "status": index_report["status"],
        "finding_counts": index_report["finding_counts"],
        "repair_status": index_plan["status"],
    }
    summary["source_unchanged"] = fingerprint(source) == before
    probes_safe = all(
        p["status"] in {"pass", "partial"}
        and p["requested_rows"] > 0
        and p["checked_rows"] == p["requested_rows"]
        and p["frame_checks"] > 0
        and not p["row_errors"]
        and not p["errors"]
        and p["source_unchanged"]
        for p in summary["loader_probes"].values()
    )
    complete = all(r["status"] == "pass" for r in reference) and all(
        r["status"] == "pass" for r in summary["official_decoders"].values()
    )
    complete &= detected and summary["offset_control"]["official_before"].get("mismatch", 0) > 0
    complete &= summary["repair"].get("official_after") == "pass" and summary["repair"].get("exact_restore") is True
    complete &= (
        index_report["finding_counts"].get("GLOBAL_INDEX_MISMATCH", 0) == info["total_frames"]
        and index_plan["status"] == "blocked"
    )
    summary["status"] = (
        "expected_outcomes_met" if complete and probes_safe and summary["source_unchanged"] else "review_required"
    )
    summary["note"] = (
        "Expected outcomes include detecting authored faults and reporting repeated-frame ambiguity. This is not dataset-wide identity or physical synchronization certification."
    )
    write_json(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample", choices=["agibot2026", "aloha_screw_driver"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--consumer-python", type=Path, required=True)
    parser.add_argument("--ffmpeg-bin", type=Path)
    args = parser.parse_args()
    result = run(
        args.sample,
        args.source,
        args.out,
        args.consumer_python.resolve(),
        args.ffmpeg_bin.resolve() if args.ffmpeg_bin else None,
    )
    print(json.dumps(result, indent=2))
    if result["status"] != "expected_outcomes_met":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

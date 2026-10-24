"""Build ALOHA clean/offset/repaired official-loader pixel evidence.

This script captures actual LeRobotDataset item tensors, not frames re-decoded by
the auditor. It also exports a short source clip for the public example.
"""

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from boundary_audit.audit import audit_dataset
from boundary_audit.download import SAMPLES, sha256
from boundary_audit.probe import probe_loader
from boundary_audit.repair import apply_plan, fingerprint, make_plan
from boundary_audit.report import write_probe_html
from boundary_audit.storage import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--python", required=True, help="Official consumer interpreter")
    parser.add_argument("--ffmpeg-bin", type=Path)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.out.resolve()
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        parser.error("Choose a fresh output directory outside the source")
    manifest = json.loads((source / "source_manifest.json").read_text(encoding="utf-8"))
    if (manifest["repository"], manifest["revision"]) != (
        SAMPLES["aloha_screw_driver"]["repo"],
        SAMPLES["aloha_screw_driver"]["revision"],
    ):
        parser.error("Use the pinned aloha_screw_driver preset")
    camera = "observation.images.cam_left_wrist"
    clean_audit = audit_dataset(source, cameras=[camera], decode=True)
    if clean_audit["status"] != "pass":
        parser.error("Clean source audit did not pass")
    before = fingerprint(source)
    output.mkdir(parents=True)

    offset = output / "authored-offset"
    shutil.copytree(source, offset)
    metadata = offset / "meta/episodes/chunk-000/file-000.parquet"
    table = pq.read_table(metadata)
    rows = table.to_pylist()
    for row in rows:
        if row["episode_index"] == 25:
            for edge in ("from_timestamp", "to_timestamp"):
                row[f"videos/{camera}/{edge}"] += 0.02
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), metadata)
    plan = make_plan(offset, cameras=[camera], assume_cfr=True)
    if plan["status"] != "ready":
        parser.error("Authored offset copy did not produce a ready repair plan")
    repaired = output / "repaired"
    apply_plan(plan, offset, repaired)
    write_json(output / "repair-plan.json", plan)

    groups = {
        "clean": (source, False),
        "authored-offset": (offset, True),
        "repaired": (repaired, False),
    }
    group_dirs = {
        "clean": "clean-evidence",
        "authored-offset": "authored-offset-evidence",
        "repaired": "repaired-evidence",
    }
    summary = {
        "schema_version": "boundary-loader-pixel-evidence.v1",
        "source": {
            key: manifest[key]
            for key in ("repository", "revision", "license", "total_bytes", "selected_cameras")
        },
        "camera": camera,
        "episode": 25,
        "authored_fault": {"kind": "episode_start_end_offset", "shift_seconds": 0.02, "copy": "authored-offset"},
        "groups": {},
        "source_unchanged": None,
        "note": "Actual LeRobotDataset item tensors; controlled copy offset, not an upstream defect.",
    }
    for name, (root, allow_failure) in groups.items():
        target = output / group_dirs[name]
        target.mkdir()
        report = probe_loader(
            root,
            args.python,
            cameras=[camera],
            episodes=[25],
            backend="torchcodec",
            phase="window",
            max_rows=2,
            radius=1,
            max_decode_frames=50000,
            max_reference_bytes=268435456,
            max_view_bytes=314572800,
            visuals=True,
            visual_queries=2,
            visual_max_bytes=20_000_000,
            visual_output=target / "visuals",
            allow_audit_failure=allow_failure,
            timeout=600,
            ffmpeg_bin=args.ffmpeg_bin,
        )
        write_json(target / "probe-report.json", report)
        write_probe_html(report, target / "report.html")
        summary["groups"][name] = {
            "status": report["status"],
            "preflight_status": report.get("preflight_status"),
            "preflight_override": report.get("preflight_override"),
            "visual_status": report.get("visual_evidence", {}).get("status"),
            "visual_records": len(report.get("visual_evidence", {}).get("records", [])),
            "report": f"{group_dirs[name]}/report.html",
            "json": f"{group_dirs[name]}/probe-report.json",
        }
        visual = report.get("visual_evidence", {})
        expected_pixel_status = "wrong_frame" if allow_failure else "pass"
        summary["groups"][name]["expected_outcome_met"] = (
            report["status"] in ({"fail"} if allow_failure else {"pass", "partial"})
            and visual.get("status") == "complete"
            and len(visual.get("records", [])) == 2
            and all(record.get("comparison", {}).get("status") == expected_pixel_status
                    for record in visual.get("records", []))
        )
    summary["source_unchanged"] = fingerprint(source) == before

    if args.ffmpeg_bin:
        clip = output / "aloha-20s.mp4"
        source_video = source / "videos" / camera / "chunk-000/file-000.mp4"
        completed = subprocess.run(
            [
                str(args.ffmpeg_bin / "ffmpeg"),
                "-v", "error", "-y", "-ss", "0", "-t", "20", "-i", str(source_video),
                "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "30", "-pix_fmt", "yuv420p", str(clip),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            summary["clip"] = {
                "path": "aloha-20s.mp4",
                "seconds": 20,
                "bytes": clip.stat().st_size,
                "sha256": sha256(clip),
                "rebuild": "ffmpeg -ss 0 -t 20 -i SOURCE_VIDEO -an -c:v libx264 -crf 30 -pix_fmt yuv420p aloha-20s.mp4",
            }
        else:
            summary["clip_error"] = completed.stderr[-500:]
    summary["expected_outcomes_met"] = summary["source_unchanged"] and all(
        group["expected_outcome_met"] for group in summary["groups"].values()
    )
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, indent=2))
    if not summary["expected_outcomes_met"]:
        raise SystemExit("Loader evidence did not reproduce the expected controls; inspect summary.json")


if __name__ == "__main__":
    main()

"""Reproduce the attributed ALOHA authored-offset report using a fresh copy."""

import argparse
import json
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from boundary_audit.audit import audit_dataset
from boundary_audit.report import write_reports
from boundary_audit.visuals import add_visual_evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.out.resolve()
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        parser.error("Choose a fresh output directory outside the source")
    receipt = json.loads((source / "source_manifest.json").read_text(encoding="utf-8"))
    if (
        receipt["repository"] != "lerobot/aloha_static_screw_driver"
        or receipt["revision"] != "21eead16760a8d94d449cadf4bc438b322ab528d"
    ):
        parser.error("Use the pinned aloha_screw_driver preset")
    camera = "observation.images.cam_left_wrist"
    clean = audit_dataset(source, cameras=[camera], decode=True)
    if clean["status"] != "pass":
        parser.error("Clean source audit did not pass")
    faulty = output / "authored-offset"
    shutil.copytree(source, faulty)
    metadata = faulty / "meta/episodes/chunk-000/file-000.parquet"
    table = pq.read_table(metadata)
    rows = table.to_pylist()
    for row in rows:
        if row["episode_index"] == 25:
            for edge in ("from_timestamp", "to_timestamp"):
                row[f"videos/{camera}/{edge}"] += 0.02
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), metadata)
    report = audit_dataset(faulty, cameras=[camera], decode=True)
    if report["status"] != "fail":
        raise RuntimeError("Authored fault was not detected")
    report["sample_source"] = {k: receipt[k] for k in ("repository", "revision", "license")}
    report["sample_source"]["note"] = "Authored +20 ms episode-25 offset in a copy; not a natural upstream defect."
    report_dir = output / "report"
    add_visual_evidence(report, faulty, report_dir, max_queries=1)
    write_reports(report, report_dir)
    print(report_dir / "report.html")


if __name__ == "__main__":
    main()

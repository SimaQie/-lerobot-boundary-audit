"""Package original fixtures and complete measured evidence, never external data."""

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from boundary_audit.conformance import write_suite_html
from boundary_audit.repair import fingerprint, make_plan
from boundary_audit.storage import write_json


def archive_files(path, files):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 13, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--restored", type=Path, required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    suite = json.loads((args.suite / "suite.json").read_text(encoding="utf-8"))
    summary = json.loads((args.results / "summary.json").read_text(encoding="utf-8"))
    if len(summary["checks"]) != 60 or summary["status"] != "pass":
        raise ValueError("Complete 60-check measured suite is required")
    for check in summary["checks"]:
        relative = f"{check['case']}/{check['backend']}-{check['phase']}.json"
        report = json.loads((args.results / relative).read_text(encoding="utf-8"))
        check["identity_failures"] = sum(r["status"] == "wrong_frame" for r in report.get("records", []))
        check["report"] = relative
        if check["expected"] == "fail" and not check["identity_failures"]:
            raise ValueError("Negative control has no wrong pixel identity evidence")
        if not check["matched_expectation"] or not check["source_unchanged"]:
            raise ValueError("Unexpected result or modified source")
    write_json(args.results / "summary.json", summary)
    write_suite_html(summary, args.results / "report.html")
    evidence = project / "research/results/v030"
    evidence.mkdir(parents=True, exist_ok=True)
    write_json(evidence / "summary.json", summary)
    evidence_files = {
        p.relative_to(args.results).as_posix(): p.read_bytes() for p in args.results.rglob("*") if p.is_file()
    }
    evidence_hash = archive_files(evidence / "full-loader-reports.zip", evidence_files)
    original = fingerprint(args.suite / "offset-one-frame")
    if fingerprint(args.restored) != original:
        raise ValueError("Restored files do not match injected source exactly")
    control = {
        "source_unchanged": True,
        "exact_restore": True,
        "source_files": len(original),
        "plan": make_plan(args.suite / "offset-one-frame", assume_cfr=True),
    }
    write_json(evidence / "repair-control.json", control)
    fixture_files = {
        "suite.json": (args.suite / "suite.json").read_bytes(),
        "repair-control.json": json.dumps(control, indent=2).encode(),
    }
    for case in suite["cases"]:
        directory = args.suite / case["path"]
        for path in directory.rglob("*"):
            if path.is_file():
                fixture_files[path.relative_to(args.suite).as_posix()] = path.read_bytes()
    if any(
        "Lenovo" in content.decode("utf-8", errors="ignore")
        for name, content in fixture_files.items()
        if name.endswith(".json")
    ):
        raise ValueError("Fixture JSON contains a private machine path")
    fixture = project / "examples/frame-suite-v030.zip"
    fixture_hash = archive_files(fixture, fixture_files)
    write_json(
        project / "examples/frame-suite-v030.json",
        {
            "license": "MIT",
            "synthetic_only": True,
            "sha256": fixture_hash,
            "bytes": fixture.stat().st_size,
            "files": len(fixture_files),
            "producer": suite["producer"],
            "cases": suite["cases"],
        },
    )
    write_json(
        evidence / "artifacts.json",
        {
            "fixture_sha256": fixture_hash,
            "evidence_sha256": evidence_hash,
            "evidence_bytes": (evidence / "full-loader-reports.zip").stat().st_size,
            "matched_expectations": len(summary["checks"]),
            "frame_checks": sum(c["frame_checks"] for c in summary["checks"]),
            "correct_frame_checks": sum(c["passed_frame_checks"] for c in summary["checks"]),
            "note": "Counts include deliberately wrong frames in negative controls.",
        },
    )
    shutil.copyfile(project / "research/results/backup_integrity_v030.json", evidence / "backup-integrity.json")
    shutil.copyfile(project / "research/results/v020/summary.json", evidence / "agibot2026-v020-summary.json")
    print(
        json.dumps(
            {
                "fixture_bytes": fixture.stat().st_size,
                "evidence_checks": len(summary["checks"]),
                "fixture_sha256": fixture_hash,
            }
        )
    )


if __name__ == "__main__":
    main()

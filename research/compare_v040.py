"""Same-input descriptive comparison; reports are not a universal quality ranking.

Install the two competitors at the documented frozen commits in a separate env.
No repair command is called. Raw output and configuration are retained.
"""

import argparse
import hashlib
import importlib.util
import json
import subprocess
import time
from pathlib import Path

from boundary_audit.audit import audit_dataset
from boundary_audit.repair import fingerprint
from boundary_audit.storage import write_json

BASE = "29ac3baf211a26081dba69f150302d4ceaa4ff14"
PINS = {
    "lerobot-doctor": "38681941b6866c6d97d49502ab991c21dfbb9d9b",
    "openbot-data": "cd7720d55503a58fbbabc1b3d3ce48d9279518d7",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--python", required=True, help="Separate interpreter with frozen competitors installed")
    parser.add_argument("--loader-results", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, output = args.suite.resolve(), args.out.resolve()
    if output.exists() or output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError("Use a new, nonoverlapping comparison directory")
    output.mkdir(parents=True)
    source = subprocess.check_output(
        ["git", "show", BASE + ":src/boundary_audit/audit.py"], text=True, encoding="utf-8"
    )
    spec = importlib.util.spec_from_loader("boundary_audit.baseline_audit", loader=None)
    baseline = importlib.util.module_from_spec(spec)
    exec(compile(source, "baseline-v030-audit.py", "exec"), baseline.__dict__)
    manifest = json.loads((root / "suite.json").read_text())
    versions = subprocess.check_output(
        [
            args.python,
            "-I",
            "-c",
            "import importlib.metadata as m,json;print(json.dumps({n:m.version(n) for n in ['lerobot-doctor','openbot-data','pyarrow','av','numpy','opencv-python']}))",
        ],
        text=True,
    )
    checks = []
    for case in manifest["cases"]:
        dataset = root / case["path"]
        before = fingerprint(dataset)
        for name, method in [("storage-v030", baseline.audit_dataset), ("storage-v040", audit_dataset)]:
            start = time.perf_counter()
            report = method(dataset, decode=True)
            report["tool_version"] = "0.3.0" if name == "storage-v030" else "0.4.0"
            write_json(output / case["name"] / (name + ".json"), report)
            checks.append(
                {
                    "case": case["name"],
                    "tool": name,
                    "outcome": report["status"],
                    "elapsed_seconds": time.perf_counter() - start,
                    "finding_codes": list(report["finding_counts"]),
                }
            )
        for tool in PINS:
            destination = output / case["name"] / (tool + ".json")
            if tool == "lerobot-doctor":
                command = [
                    args.python,
                    "-I",
                    "-c",
                    "from lerobot_doctor.cli import main;main()",
                    "check",
                    str(dataset),
                    "--checks",
                    "metadata,temporal,videos",
                    "--json",
                    "--no-aggregate",
                ]
            else:
                command = [
                    args.python,
                    "-I",
                    "-c",
                    "from openbot_data.cli import main;main()",
                    "audit",
                    str(dataset),
                    "--format",
                    "lerobot",
                    "--integrity",
                    "full",
                    "--fail-on",
                    "error",
                    "--out",
                    str(destination),
                ]
            start = time.perf_counter()
            result = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120
            )
            outcome, warnings, errors = "unavailable", 0, 0
            if tool == "lerobot-doctor":
                try:
                    report = json.loads(result.stdout)
                    errors = sum(c["severity"] == "FAIL" for c in report["checks"])
                    warnings = sum(c["severity"] == "WARN" for c in report["checks"])
                    outcome = "reported_error" if errors else "reported_warning" if warnings else "no_blocking_error"
                    write_json(
                        destination, json.loads(json.dumps(report).replace(str(root).replace("\\", "\\\\"), "<suite>"))
                    )
                except (ValueError, KeyError):
                    pass
            elif destination.exists():
                report = json.loads(destination.read_text())
                errors, warnings = report["summary"]["error"], report["summary"]["warning"]
                outcome = "reported_error" if errors else "no_blocking_error"
                write_json(
                    destination, json.loads(json.dumps(report).replace(str(root).replace("\\", "\\\\"), "<suite>"))
                )
            write_json(
                destination.with_suffix(".process.json"),
                {
                    "returncode": result.returncode,
                    "stdout": result.stdout.replace(str(root), "<suite>").replace(str(output), "<results>"),
                    "stderr": result.stderr.replace(str(root), "<suite>").replace(str(output), "<results>"),
                },
            )
            checks.append(
                {
                    "case": case["name"],
                    "tool": tool,
                    "outcome": outcome,
                    "errors": errors,
                    "warnings": warnings,
                    "elapsed_seconds": time.perf_counter() - start,
                    "finding_codes": sorted({f["code"] for f in report.get("findings", [])})
                    if outcome != "unavailable"
                    else [],
                }
            )
        loader = json.loads((args.loader_results / case["name"] / "pyav-window.json").read_text())
        checks.append(
            {
                "case": case["name"],
                "tool": "full-loader-pyav-window",
                "outcome": loader["status"],
                "identity_failures": sum(r["status"] == "wrong_frame" for r in loader.get("records", [])),
                "row_failures": len(loader.get("row_errors", [])),
                "runtime_errors": len(loader.get("errors", [])),
            }
        )
        if fingerprint(dataset) != before:
            raise ValueError("A read-only comparison modified its input")
        print(case["name"] + ": comparison recorded", flush=True)
    summary = {
        "schema_version": "boundary-comparison.v1",
        "synthetic_only": True,
        "cases": manifest["cases"],
        "checks": checks,
        "competitor_commits": PINS,
        "competitor_versions": json.loads(versions),
        "baseline_commit": BASE,
        "baseline_audit_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "source_unchanged": True,
        "configuration": {
            "doctor_checks": "metadata,temporal,videos",
            "openbot_integrity": "full",
            "own_storage_decode": True,
            "full_loader_backend": "pyav",
            "phase": "window",
        },
        "limits": [
            "Source-pinned builds, not necessarily PyPI releases",
            "CPU startup included in elapsed time; different media runtimes",
            "Warnings and unavailable checks are retained, not counted as successful fault detections",
            "Only 13 authored controls; no prevalence, training-benefit or universal-ranking claim",
            "Action and pixel identity require external expectations; general validators may not assess them",
        ],
    }
    for tool in PINS:
        baseline_codes = next(c.get("finding_codes", []) for c in checks if c["case"] == "merged" and c["tool"] == tool)
        for check in checks:
            if check["tool"] == tool:
                check["additional_codes_vs_merged"] = sorted(set(check.get("finding_codes", [])) - set(baseline_codes))
    summary["limits"].append(
        "OpenBot flags scalar-storage versus declared [1] shapes on the official fixture. Our clean controls certify specified reading/value checks, not every schema or policy tensor-rank contract; this does not prove OpenBot's rule wrong. Inspect incremental findings."
    )
    write_json(output / "summary.json", summary)
    lines = [
        "# Same-input comparison (0.4.0)",
        "",
        "Configuration and raw reports: summary.json. Original synthetic inputs only; no universal ranking.",
        "",
        "| Case | v0.3 storage | v0.4 storage | doctor | openbot | full loader |",
        "|---|---|---|---|---|---|",
    ]
    for case in manifest["cases"]:
        rows = [c["outcome"] for c in checks if c["case"] == case["name"]]
        lines.append("| " + " | ".join([case["name"]] + rows) + " |")
    (output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

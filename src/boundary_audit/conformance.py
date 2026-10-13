"""Separate-interpreter production and full-loader conformance commands."""

import html
import json
import os
import subprocess
import tempfile
from pathlib import Path

from .repair import apply_plan, fingerprint, make_plan, restore_copy
from .storage import publish_new_directory, write_json

PHASES = ("single", "window", "batch", "workers", "subset")


def invoke(driver, python, request, *, timeout=300):
    result = subprocess.run(
        [str(python), "-I", "-B", str(Path(__file__).with_name(driver))],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode:
        raise ValueError("Official process failed: " + result.stderr[-1200:])
    return json.loads(result.stdout)


def generate_suite(output, python, *, ffmpeg_bin=None):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Use a new suite output directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(prefix=".boundary-suite-", dir=output.parent) as temporary,
        tempfile.TemporaryDirectory(prefix="ba-") as cache,
    ):
        stage = Path(temporary) / "suite"
        result = invoke(
            "suite_driver.py",
            python,
            {"out": str(stage), "cache": cache, "ffmpeg_bin": str(Path(ffmpeg_bin).resolve()) if ffmpeg_bin else None},
        )
        if result["status"] != "generated":
            raise ValueError("Official fixture generation failed: " + result.get("message", "unknown error"))
        add_repair_control(stage)
        from .audit import audit_dataset

        write_json(
            stage / "producer-audit.json",
            {name: audit_dataset(stage / name) for name in ("recorded-a", "recorded-b", "merged")},
        )
        result["suite"] = json.loads((stage / "suite.json").read_text(encoding="utf-8"))
        publish_new_directory(stage, output)
    return result


def add_repair_control(root):
    """Reproduce repair and byte-exact restore of a known injected offset."""
    root = Path(root)
    source = root / "offset-one-frame"
    before = fingerprint(source)
    plan = make_plan(source, assume_cfr=True)
    manifest = json.loads((root / "suite.json").read_text(encoding="utf-8"))
    if plan["status"] != "ready":
        if fingerprint(source) != before:
            raise ValueError("Source changed during controlled repair planning")
        manifest["repair_control"] = {
            "status": plan["status"],
            "refusals": plan["refusals"],
            "note": "No repaired case was added; upstream timing must satisfy the existing repair contract.",
        }
        write_json(root / "suite.json", manifest)
        write_json(root / "repair-control.json", {"status": plan["status"], "source_unchanged": True, "plan": plan})
        return
    apply_plan(plan, source, root / "repaired-offset")
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=root) as temporary:
        restored = Path(temporary) / "restored"
        restore_copy(root / "repaired-offset", restored)
        exact = fingerprint(restored) == before
    if not exact or fingerprint(source) != before:
        raise ValueError("Controlled repair failed preservation/restoration checks")
    manifest["cases"].append(
        {
            "name": "repaired-offset",
            "path": "repaired-offset",
            "expected": "pass",
            "origin": "guarded repair of controlled offset injection",
        }
    )
    manifest["repair_control"] = {"status": "pass", "source_unchanged": True, "exact_restore": True}
    write_json(root / "suite.json", manifest)
    write_json(
        root / "repair-control.json",
        {"status": "pass", "source_unchanged": True, "exact_restore": True, "source_files": len(before), "plan": plan},
    )


def verify_loader(root, python, *, backend="pyav", phase="single", ffmpeg_bin=None):
    root = Path(root).resolve()
    if (root / "INCOMPLETE").exists():
        raise ValueError("Dataset publication is incomplete")
    if phase not in PHASES or backend not in {"pyav", "torchcodec"}:
        raise ValueError("Unsupported loader phase or backend")
    if not (root / "frame_oracle.json").exists():
        raise ValueError("A pre-encoding frame_oracle.json is required; ordinary robot footage has no known pixel IDs")
    before = fingerprint(root)
    with tempfile.TemporaryDirectory(prefix="ba-") as cache:
        try:
            report = invoke(
                "loader_driver.py",
                python,
                {
                    "root": str(root),
                    "cache": cache,
                    "backend": backend,
                    "phase": phase,
                    "ffmpeg_bin": str(Path(ffmpeg_bin).resolve()) if ffmpeg_bin else None,
                },
            )
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            report = {
                "status": "unavailable",
                "backend": backend,
                "phase": phase,
                "checked_rows": 0,
                "errors": [{"type": type(exc).__name__, "message": str(exc).replace(str(root), "<dataset>")[:1500]}],
            }
    report["source_unchanged"] = fingerprint(root) == before
    if not report["source_unchanged"]:
        report["status"] = "fail"
    return report


def run_suite(root, output, python, *, backends=("pyav", "torchcodec"), phases=PHASES, ffmpeg_bin=None):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError("Use a new results directory outside the suite")
    manifest = json.loads((root / "suite.json").read_text(encoding="utf-8"))
    if (
        manifest.get("schema_version") != "boundary-conformance-suite.v1"
        or manifest.get("synthetic_only") is not True
        or not manifest.get("cases")
    ):
        raise ValueError("A nonempty synthetic conformance suite is required")
    if (
        not backends
        or not phases
        or any(b not in {"pyav", "torchcodec"} for b in backends)
        or any(p not in PHASES for p in phases)
    ):
        raise ValueError("Select supported backends and phases")
    names = set()
    for case in manifest["cases"]:
        if (
            not isinstance(case.get("name"), str)
            or not case["name"]
            or Path(case["name"]).name != case["name"]
            or case["name"] in {".", ".."}
            or case["name"] in names
            or case.get("expected") not in {"pass", "fail"}
        ):
            raise ValueError("Invalid or duplicate case name/expectation")
        if not (root / case["path"]).resolve().is_relative_to(root):
            raise ValueError("Case path escapes suite")
        names.add(case["name"])
    output.mkdir(parents=True)
    checks = []
    for case in manifest["cases"]:
        if Path(case["name"]).name != case["name"] or case["name"] in {".", ".."}:
            raise ValueError("Invalid case name")
        dataset = (root / case["path"]).resolve()
        if not dataset.is_relative_to(root):
            raise ValueError("Case path escapes suite")
        for backend in backends:
            for phase in phases:
                report = verify_loader(dataset, python, backend=backend, phase=phase, ffmpeg_bin=ffmpeg_bin)
                write_json(output / case["name"] / f"{backend}-{phase}.json", report)
                check = {
                    "case": case["name"],
                    "expected": case["expected"],
                    "backend": backend,
                    "phase": phase,
                    "actual": report["status"],
                    "matched_expectation": report["status"] == case["expected"],
                    "frame_checks": report.get("frame_checks", 0),
                    "passed_frame_checks": report.get("passed_frame_checks", 0),
                    "source_unchanged": report["source_unchanged"],
                    "identity_failures": sum(r["status"] == "wrong_frame" for r in report.get("records", [])),
                    "report": f"{case['name']}/{backend}-{phase}.json",
                }
                if case["expected"] == "fail" and not check["identity_failures"]:
                    check["matched_expectation"] = False
                checks.append(check)
                print(
                    f"{case['name']} / {backend} / {phase}: {report['status']} (expected {case['expected']})",
                    flush=True,
                )
    summary = {
        "schema_version": "boundary-conformance-summary.v1",
        "status": "pass"
        if checks and all(c["matched_expectation"] and c["source_unchanged"] for c in checks)
        else "fail",
        "synthetic_only": True,
        "producer": manifest["producer"],
        "checks": checks,
        "note": "A suite PASS includes expected detection of deliberately faulty inputs; it does not mean every dataset passed.",
    }
    write_json(output / "summary.json", summary)
    write_suite_html(summary, output / "report.html")
    return summary


def write_suite_html(summary, path):
    """Portable comparison of expected faults and actual loader evidence."""
    rows = []
    for check in summary["checks"]:
        label = "MATCH" if check["matched_expectation"] else "MISMATCH"
        detail = check.get("report", f"{check['case']}/{check['backend']}-{check['phase']}.json")
        cells = [
            check["case"],
            check["backend"],
            check["phase"],
            check["expected"],
            check["actual"],
            f"{check['passed_frame_checks']} / {check['frame_checks']}",
            label,
        ]
        rows.append(
            "<tr>"
            + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in cells)
            + f'<td><a href="{html.escape(detail, quote=True)}">JSON</a></td></tr>'
        )
    content = '<!doctype html><html lang="en"><meta charset="utf-8"><title>LeRobot frame identity conformance</title><style>body{font:16px system-ui;margin:32px;max-width:1200px;color:#17243b}table{border-collapse:collapse;width:100%}td,th{padding:8px;text-align:left;border-bottom:1px solid #dce2ec}thead{background:#edf3fa}code{background:#edf3fa;padding:3px}</style><h1>LeRobot frame identity conformance</h1>'
    content += f"<p>Suite result: <strong>{html.escape(summary['status'].upper())}</strong>. Synthetic inputs only.</p>"
    content += "<p>A suite PASS means clean inputs passed and deliberate faults were detected. It does not mean every dataset passed. Frame IDs were specified before official encoding; timestamps do not supply identity ground truth.</p>"
    content += (
        "<p>Official producer: <code>"
        + html.escape(json.dumps(summary["producer"]))
        + "</code>. Full consumer versions are in each JSON report.</p>"
    )
    content += (
        "<table><thead><tr><th>Case</th><th>Backend</th><th>Phase</th><th>Expected</th><th>Actual</th><th>Correct frames</th><th>Expectation</th><th>Evidence</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table><p>No physical camera/action synchronization claim. Controlled faults are not naturally discovered dataset bugs.</p></html>"
    )
    Path(path).write_text(content, encoding="utf-8")

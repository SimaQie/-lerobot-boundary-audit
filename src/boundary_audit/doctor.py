"""One read-only diagnosis of the host, optional consumer and input dataset."""

from __future__ import annotations

import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
from html import escape
from pathlib import Path

from . import __version__
from .audit import audit_dataset
from .environment import collect_environment, interpreter_path
from .storage import write_json


def package_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _executable(value):
    if value is None:
        return None
    candidate = Path(value)
    if candidate.is_dir():
        for name in ("ffmpeg", "ffmpeg.exe"):
            if (candidate / name).is_file():
                return candidate / name
        return None
    if candidate.is_file():
        return candidate
    return shutil.which(value)


def ffmpeg_report(ffmpeg_bin=None):
    executable = _executable(ffmpeg_bin) or shutil.which("ffmpeg")
    if not executable:
        return {
            "status": "partial",
            "available": False,
            "detail": "ffmpeg CLI not found; LeRobot may still provide PyAV/FFmpeg libraries",
            "action": "Install FFmpeg or pass --ffmpeg-bin with the directory containing it.",
        }
    try:
        version = subprocess.run(
            [str(executable), "-version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        decoders = subprocess.run(
            [str(executable), "-hide_banner", "-decoders"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "status": "partial",
            "available": False,
            "detail": f"ffmpeg could not be executed: {type(exc).__name__}",
            "action": "Check the FFmpeg installation and permissions.",
        }
    lines = version.stdout.splitlines()
    decoder_text = decoders.stdout.lower()
    h264 = " h264 " in decoder_text or " h264_" in decoder_text
    cuvid = "cuvid" in decoder_text
    if version.returncode != 0 or decoders.returncode != 0:
        return {
            "status": "partial",
            "available": False,
            "path": str(executable),
            "detail": "ffmpeg exists but did not answer version/decoder queries",
            "action": "Check the FFmpeg build.",
        }
    return {
        "status": "pass" if h264 else "partial",
        "available": True,
        "path": str(executable),
        "version": lines[0][:300] if lines else "unknown",
        "h264_decoder": h264,
        "cuvid_decoder": cuvid,
        "detail": "FFmpeg CLI and H.264 decoder are available" if h264 else "FFmpeg CLI is present without a visible H.264 decoder",
        "action": None if h264 else "Install a build with H.264 decoding (libavcodec).",
    }


_CONSUMER_CODE = r"""
import json
import importlib.metadata as metadata
import platform
import sys

result = {"python": sys.version.split()[0], "platform": sys.platform, "packages": {}, "imports": {}}
for name in ("lerobot", "torch", "torchcodec", "av", "datasets", "numpy"):
    try:
        result["packages"][name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        result["packages"][name] = None
try:
    import lerobot  # noqa: F401
    result["imports"]["lerobot"] = "ok"
except Exception as exc:
    result["imports"]["lerobot"] = f"{type(exc).__name__}: {exc}"
try:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset  # noqa: F401
    result["imports"]["LeRobotDataset"] = "ok"
except Exception as exc:
    result["imports"]["LeRobotDataset"] = f"{type(exc).__name__}: {exc}"
try:
    import av
    result["av_libraries"] = {str(k): str(v) for k, v in av.library_versions.items()}
except Exception:
    pass
print(json.dumps(result, allow_nan=False))
"""


def consumer_report(python):
    if not python:
        return None
    path = interpreter_path(python)
    if not path.exists():
        return {
            "status": "unavailable",
            "requested": str(python),
            "detail": "Consumer interpreter does not exist",
            "action": "Create the official LeRobot environment first.",
        }
    try:
        completed = subprocess.run(
            [str(path), "-I", "-c", _CONSUMER_CODE],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "status": "unavailable",
            "requested": str(python),
            "detail": f"Consumer probe failed to start: {type(exc).__name__}",
            "action": "Check the interpreter path and venv activation.",
        }
    if completed.returncode != 0:
        return {
            "status": "unavailable",
            "requested": str(python),
            "detail": "Consumer probe exited nonzero",
            "stderr": completed.stderr.strip()[:1200],
            "action": "Run the interpreter directly and inspect the import error.",
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "status": "unavailable",
            "requested": str(python),
            "detail": "Consumer probe returned invalid JSON",
            "action": "Check for sitecustomize output or a broken interpreter wrapper.",
        }
    imports = payload.get("imports", {})
    ok = imports.get("lerobot") == "ok" and imports.get("LeRobotDataset") == "ok"
    packages = payload.get("packages", {})
    return {
        "status": "pass" if ok else "fail",
        "requested": str(python),
        "resolved": str(path),
        **payload,
        "detail": "Official LeRobotDataset imports successfully" if ok else "Official LeRobotDataset import failed",
        "action": None
        if ok
        else "Install a supported LeRobot release and its dataset extra in this interpreter.",
        "lerobot_supported_observed": packages.get("lerobot"),
    }


def dataset_report(root, *, cameras=None, tolerance=0.0001):
    path = Path(root).resolve()
    try:
        report = audit_dataset(path, cameras=cameras, tolerance=tolerance)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {
            "root": ".",
            "status": "fail",
            "detail": f"{type(exc).__name__}: {str(exc)[:1200]}",
            "action": "Fix the dataset path or metadata before running loader checks.",
        }
    findings = report.get("finding_counts", {})
    return {
        "root": ".",
        "status": report["status"],
        "fps": report.get("fps"),
        "camera_scope": report.get("selection", {}).get("camera_scope"),
        "coverage": report.get("coverage"),
        "findings": dict(sorted(findings.items(), key=lambda item: (-item[1], item[0]))[:20]),
        "detail": report.get("scope"),
        "action": None
        if report["status"] == "pass"
        else "Inspect the audit report; do not treat unperformed checks as a pass.",
    }


def _overall(checks):
    if any(check["status"] in {"fail", "blocked"} for check in checks):
        return "fail"
    if any(check["status"] != "pass" for check in checks):
        return "partial"
    return "pass"


def diagnose(*, datasets=(), cameras=None, tolerance=0.0001, consumer_python=None, ffmpeg_bin=None):
    packages = {
        name: package_version(name)
        for name in ("pyarrow", "av", "numpy", "torch", "datasets", "lerobot")
    }
    checks = [
        {
            "name": "python",
            "status": "pass" if sys.version_info >= (3, 11) else "fail",
            "detail": f"Python {platform.python_version()} (requires >=3.11)",
            "action": None if sys.version_info >= (3, 11) else "Use Python 3.11 or newer.",
        },
        {
            "name": "audit_dependency",
            "status": "pass" if packages["pyarrow"] else "fail",
            "detail": f"pyarrow={packages['pyarrow'] or 'not installed'}",
            "action": None
            if packages["pyarrow"]
            else "Install pyarrow with the 'lerobot' or 'repair' extra.",
        },
        {
            "name": "decode_dependency",
            "status": "pass" if packages["av"] else "partial",
            "detail": f"av={packages['av'] or 'not installed'} (optional local decode/visuals)",
            "action": None if packages["av"] else "Install the 'decode' extra to use --decode/--visuals.",
        },
    ]
    ffmpeg = ffmpeg_report(ffmpeg_bin)
    checks.append(
        {
            "name": "ffmpeg_cli",
            "status": ffmpeg["status"],
            "detail": ffmpeg["detail"],
            "action": ffmpeg.get("action"),
        }
    )
    consumer = consumer_report(consumer_python) if consumer_python else None
    if consumer:
        checks.append(
            {
                "name": "official_consumer",
                "status": consumer["status"],
                "detail": consumer["detail"],
                "action": consumer.get("action"),
            }
        )
    dataset_reports = []
    for root in datasets:
        item = dataset_report(root, cameras=cameras, tolerance=tolerance)
        checks.append(
            {
                "name": "dataset",
                "status": item["status"],
                "detail": f"dataset scan status {item['status']}",
                "action": item.get("action"),
            }
        )
        dataset_reports.append(item)
    next_steps = []
    for check in checks:
        if check["action"] and check["action"] not in next_steps:
            next_steps.append(check["action"])
    if datasets:
        next_steps.append(
            "Run audit --out <dir> for a detailed report, then probe-loader with a supported consumer interpreter."
        )
    return {
        "schema_version": "boundary-doctor.v1",
        "tool_version": __version__,
        "status": _overall(checks),
        "scope": "Read-only host/consumer/dataset diagnosis; no official loader pixel probe is performed.",
        "environment": collect_environment(),
        "python": {"version": platform.python_version(), "executable": sys.executable},
        "packages": packages,
        "ffmpeg": ffmpeg,
        "consumer": consumer,
        "datasets": dataset_reports,
        "checks": checks,
        "next_steps": next_steps,
    }


def write_doctor_html(result, path):
    checks = "".join(
        f"<tr data-status='{escape(check['status'])}'><td>{escape(check['name'])}</td><td>{escape(check['status'])}</td><td>{escape(check['detail'])}</td><td>{escape(check.get('action') or '')}</td></tr>"
        for check in result["checks"]
    )
    datasets = "".join(
        f"<tr><td>{escape(item['root'])}</td><td>{escape(item['status'])}</td><td>{escape(str(item.get('fps') or ''))}</td><td>{escape(json.dumps(item.get('findings', {}), ensure_ascii=False))}</td></tr>"
        for item in result["datasets"]
    )
    actions = "".join(f"<li>{escape(item)}</li>" for item in result["next_steps"]) or "<li>No action required.</li>"
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Boundary audit doctor</title>
<style>body{{max-width:1100px;margin:32px auto;padding:0 22px;font:15px system-ui;color:#172a40;background:#f5f7fb}}h1{{font-size:29px}}table{{width:100%;border-collapse:collapse;background:white}}td,th{{text-align:left;padding:10px;border-bottom:1px solid #e2e8f0;vertical-align:top}}tr[data-status=fail] td:nth-child(2){{color:#a51d2d;font-weight:700}}tr[data-status=partial] td:nth-child(2){{color:#8a5a00;font-weight:700}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:16px;border:1px solid #dce3ed}}</style></head><body>
<h1>Boundary audit doctor: {escape(result["status"].upper())}</h1><p>{escape(result["scope"])}</p>
<h2>Checks</h2><table><thead><tr><th>Check</th><th>Status</th><th>Observed</th><th>Action</th></tr></thead><tbody>{checks}</tbody></table>
<h2>Datasets</h2><table><thead><tr><th>Input</th><th>Status</th><th>FPS</th><th>Findings</th></tr></thead><tbody>{datasets}</tbody></table>
<h2>Next steps</h2><ul>{actions}</ul>
<details><summary>Host, packages and consumer JSON</summary><pre>{escape(json.dumps({"environment": result["environment"], "packages": result["packages"], "consumer": result["consumer"]}, indent=2, ensure_ascii=False))}</pre></details>
</body></html>"""
    Path(path).write_text(html, encoding="utf-8")


def write_doctor(result, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "doctor.json", result)
    write_doctor_html(result, output / "doctor.html")

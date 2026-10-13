"""Separate-interpreter verification against the installed official decoder."""

import json
import subprocess
from pathlib import Path

from .audit import audit_dataset


def verify_consumer(root, python, *, cameras=None, backend="torchcodec", ffmpeg_bin=None, timeout=300):
    if backend not in {"torchcodec", "pyav"}:
        raise ValueError("Choose official torchcodec or pyav")
    report = audit_dataset(root, cameras=cameras)
    queries = [q for q in report["boundary_queries"] if "row_timestamp_seconds" in q]
    if not queries:
        raise ValueError("No verified boundary metadata is available for decoder queries")
    request = {
        "root": str(Path(root).resolve()),
        "queries": queries,
        "backend": backend,
        "tolerance": report["tolerance_seconds"],
        "ffmpeg_bin": str(ffmpeg_bin) if ffmpeg_bin else None,
    }
    driver = Path(__file__).with_name("consumer_driver.py")
    try:
        result = subprocess.run(
            [str(python), "-I", "-B", str(driver)],
            input=json.dumps(request),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode:
            raise ValueError("Official consumer process failed: " + result.stderr[-1000:])
        consumer = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        consumer = {
            "status": "unavailable",
            "backend": "official-lerobot-" + backend,
            "checked_queries": 0,
            "requested_queries": len(queries),
            "errors": [
                {"type": type(exc).__name__, "message": str(exc).replace(str(Path(root).resolve()), "<dataset>")[:1200]}
            ],
        }
    report["consumer_verification"] = consumer
    report["limitations"] = [
        x for x in report["limitations"] if "Official LeRobot decoder verification requires" not in x
    ]
    report["limitations"].append(
        "Decoder functions are verified; a full LeRobotDataset training-loader run and physical synchronization are outside this check"
    )
    if consumer["status"] == "unavailable":
        report["status"] = "partial" if report["status"] == "pass" else report["status"]
    elif consumer["status"] == "fail":
        report["status"] = "fail"
    return report

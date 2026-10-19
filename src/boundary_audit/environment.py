"""Runtime provenance for reproducible reports on arbitrary hosts.

These helpers describe the machine and the requested/observed reader devices.
They never select or configure a decoder, so importing this module stays safe
on the lightweight CPU-only installation.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


def _system_timezone() -> str:
    if Path("/etc/timezone").is_file():
        name = Path("/etc/timezone").read_text(encoding="utf-8").strip()
        if name:
            return name
    try:
        target = os.readlink("/etc/localtime")
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return datetime.now().astimezone().tzname() or "unknown"


def interpreter_path(value) -> Path:
    """Make an interpreter path absolute without resolving a venv symlink.

    On POSIX, a venv interpreter is commonly a symlink to the base interpreter;
    Path.resolve() would select the base interpreter without the venv packages.
    """
    return Path(value).absolute()


def nvidia_smi_path() -> str | None:
    """Locate nvidia-smi, including the WSL driver-library directory."""
    executable = shutil.which("nvidia-smi")
    if executable:
        return executable
    for candidate in ("/usr/lib/wsl/lib/nvidia-smi", "/usr/bin/nvidia-smi"):
        if Path(candidate).is_file():
            return candidate
    return None


def gpu_inventory() -> dict:
    """Best-effort host GPU description; a missing driver never fails a report."""
    executable = nvidia_smi_path()
    if not executable:
        return {"available": False, "reason": "nvidia-smi not found"}
    try:
        completed = subprocess.run(
            [
                executable,
                "--query-gpu=name,driver_version,memory.total,compute_cap",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "reason": f"nvidia-smi failed: {type(exc).__name__}"}
    if completed.returncode != 0:
        return {
            "available": False,
            "reason": "nvidia-smi returned nonzero",
            "stderr": completed.stderr.strip()[:300],
        }
    devices = []
    for line in completed.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) >= 4:
            devices.append(
                {
                    "name": fields[0],
                    "driver_version": fields[1],
                    "memory_mib": fields[2],
                    "compute_capability": fields[3],
                }
            )
    return {"available": bool(devices), "devices": devices}


def collect_environment() -> dict:
    """Describe this process host and both the system and display timezone."""
    now = datetime.now().astimezone()
    system_timezone = _system_timezone()
    offset = now.utcoffset()
    return {
        "schema_version": "boundary-environment.v1",
        "measurement_time": now.isoformat(timespec="seconds"),
        "measurement_date": now.date().isoformat(),
        "system_timezone": system_timezone,
        "display_timezone": os.environ.get("TZ") or system_timezone,
        "utc_offset_seconds": int(offset.total_seconds()) if offset is not None else None,
        "platform": platform.system(),
        "platform_release": platform.release(),
        "platform_version": platform.version(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "host_gpu": gpu_inventory(),
    }


def decode_environment(versions: dict | None) -> dict:
    """Separate the requested decode device from what the consumer actually used.

    The stock LeRobot reader has no decode-device argument, so the existing
    probe requests CPU explicitly; a CUDA build alone must not be reported as
    GPU decoding.  cpu_fallback_observed stays false for that case.
    """
    versions = versions or {}
    requested = versions.get("requested_decode_device", "unknown")
    observed = versions.get("observed_decode_device") or versions.get("device_used") or "unknown"
    return {
        "requested_decode_device": requested,
        "observed_decode_device": observed,
        "observed_output_device": versions.get("observed_output_device", observed),
        "torch_cuda_available": versions.get("torch_cuda_available"),
        "torch_cuda_build": versions.get("torch_cuda_build"),
        "torch_device_name": versions.get("torch_device_name"),
        "cpu_fallback_observed": requested == "cuda" and observed == "cpu",
        "note": "The stock official reader has no decode-device selector; requested CPU is not a CUDA fallback.",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_provenance(root: Path) -> dict:
    """Record the tested commit and the digest of the scripts that produced it."""
    root = Path(root).resolve()

    def git(*args: str) -> subprocess.CompletedProcess | None:
        try:
            return subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain")
    files = {}
    for relative in (
        "research/review_v041.py",
        "src/boundary_audit/environment.py",
        "src/boundary_audit/probe_driver.py",
    ):
        path = root / relative
        if path.is_file():
            files[relative] = _sha256(path)
    return {
        "root": ".",
        "commit": commit.stdout.strip() if commit and commit.returncode == 0 else "unavailable",
        "dirty": bool(status.stdout.strip()) if status and status.returncode == 0 else None,
        "files_sha256": files,
    }

"""Pure, testable logic for the standalone GPU decode benchmark.

This module never imports torch or numpy.  It contains the independent CFR/PTS
time mapping, JSON-safe consumer result summaries, and the completeness/status
evaluator used by ``research/benchmark_gpu_decode.py``.  Keeping these rules in
the package lets the ordinary CI test them without a GPU or a consumer torch
installation.
"""

from __future__ import annotations

import bisect
import json
import math


def expected_ordinal_for_time(seconds: float, fps: float, frame_count: int) -> int | None:
    """CFR contract: frame i covers [i/fps, (i+1)/fps); the end is exclusive."""
    if not math.isfinite(seconds) or not math.isfinite(fps) or fps <= 0 or frame_count <= 0:
        return None
    scaled = seconds * fps
    if scaled < -1e-9:
        return None
    ordinal = math.floor(scaled + 1e-9)
    return ordinal if 0 <= ordinal < frame_count else None


def map_time_to_ordinal(seconds: float, intervals: list[dict]) -> dict:
    """Locate the frame displayed at ``seconds`` from sequential PTS/duration data.

    The mapping is independent of any CPU or CUDA decoder return value.  A time
    at the exclusive end is ``out_of_range``; gaps or unusable intervals are
    ``unverified`` and must not become a PASS.
    """
    if not math.isfinite(seconds) or not intervals:
        return {"status": "unverified", "reason": "nonfinite time or no intervals"}
    pts = []
    durations = []
    for entry in intervals:
        point = entry.get("pts_seconds")
        duration = entry.get("duration_seconds")
        if not isinstance(point, (int, float)) or not isinstance(duration, (int, float)):
            return {"status": "unverified", "reason": "nonnumeric PTS or duration"}
        if not math.isfinite(point) or not math.isfinite(duration) or duration <= 0:
            return {"status": "unverified", "reason": "nonfinite PTS or nonpositive duration"}
        pts.append(float(point))
        durations.append(float(duration))
    if any(pts[i] >= pts[i + 1] for i in range(len(pts) - 1)):
        return {"status": "unverified", "reason": "PTS is not strictly increasing"}
    first, last_end = pts[0], pts[-1] + durations[-1]
    tolerance = 1e-9
    if seconds < first - tolerance or seconds >= last_end - tolerance:
        return {"status": "out_of_range", "first_pts_seconds": first, "last_end_seconds": last_end}
    index = bisect.bisect_right(pts, seconds + tolerance) - 1
    if index < 0:
        return {"status": "out_of_range", "first_pts_seconds": first, "last_end_seconds": last_end}
    end = pts[index] + durations[index]
    if seconds + tolerance < end:
        return {
            "status": "ok",
            "ordinal": index,
            "pts_seconds": pts[index],
            "duration_seconds": durations[index],
            "end_seconds": end,
            "source": "sequential PyAV PTS/duration intervals",
        }
    if index + 1 < len(pts) and abs(seconds - pts[index + 1]) <= tolerance:
        return {
            "status": "ok",
            "ordinal": index + 1,
            "pts_seconds": pts[index + 1],
            "duration_seconds": durations[index + 1],
            "end_seconds": pts[index + 1] + durations[index + 1],
            "source": "sequential PyAV PTS/duration intervals",
        }
    return {"status": "unverified", "reason": "time falls in a PTS gap"}


def grid_error(intervals: list[dict], fps: float) -> float | None:
    """Maximum deviation from a CFR grid, or None for invalid input."""
    if not intervals or not math.isfinite(fps) or fps <= 0:
        return None
    errors = []
    for index, entry in enumerate(intervals):
        point = entry.get("pts_seconds")
        if not isinstance(point, (int, float)) or not math.isfinite(point):
            return None
        errors.append(abs(float(point) - index / fps))
    return max(errors)


def time_matches(returned_pts: float | None, mapping: dict, tolerance: float = 1e-6) -> bool:
    """The returned frame must be the one whose interval contains the request."""
    if mapping.get("status") != "ok" or not isinstance(returned_pts, (int, float)):
        return False
    if not math.isfinite(returned_pts):
        return False
    point = float(mapping["pts_seconds"])
    end = float(mapping["end_seconds"])
    return point - tolerance <= float(returned_pts) < end - tolerance


def time_pts_status(mapping: dict, cpu_pts, device_pts) -> str:
    """Classify a time request from the independent map, not decoder agreement alone."""
    if mapping.get("status") == "out_of_range":
        if cpu_pts is None and device_pts is None:
            return "expected_boundary_error"
        if cpu_pts is None or device_pts is None:
            return "device_disagreement"
        return "unexpected_time_frame"
    if mapping.get("status") != "ok":
        return "unverified_time_mapping"
    if not time_matches(cpu_pts, mapping) or not time_matches(device_pts, mapping):
        return "pts_mismatch"
    return "pass"


def safe_time_value(value) -> dict:
    """Keep only JSON-safe metadata from a decoder time result.

    Raw tensors are deliberately dropped.  This is used for both successful
    paths and one-sided errors so a report can always be written.
    """
    if not isinstance(value, dict):
        return {"status": "error", "error_type": type(value).__name__, "message": "non-dict result"}
    if value.get("status") != "ok":
        return {
            "status": str(value.get("status", "error")),
            "error_type": str(value.get("error_type", "error")),
            "message": str(value.get("message", ""))[:300],
        }
    frame = value.get("frame")
    shape = getattr(frame, "shape", None)
    dtype = getattr(frame, "dtype", None)
    return {
        "status": "ok",
        "device": str(value.get("device", getattr(frame, "device", "unknown"))),
        "shape": list(shape) if shape is not None else None,
        "dtype": str(dtype) if dtype is not None else None,
        "pts_seconds": value.get("pts_seconds"),
        "duration_seconds": value.get("duration_seconds"),
    }


def _expected_performance(config: dict, devices: list[str], modes: set[str]) -> list[dict]:
    performance = config.get("performance", {})
    if "performance" not in modes or not performance.get("enabled", True):
        return []
    selected = performance.get("inputs") or [spec["id"] for spec in config.get("inputs", [])]
    return [
        {"input": input_id, "device": device, "batch": int(batch)}
        for input_id in selected
        for device in devices
        for batch in performance.get("batch_sizes", [1, 8, 32])
    ]


def build_expected(config: dict, devices: list[str], modes: set[str]) -> dict:
    correctness = [
        {"input": spec["id"], "device": device}
        for spec in config.get("inputs", [])
        for device in devices
    ]
    return {
        "modes": sorted(modes),
        "correctness": correctness,
        "performance": _expected_performance(config, devices, modes),
    }


def _result_counts(result: dict, repeats: int) -> dict:
    native = result.get("native") or {}
    end_to_end = result.get("end_to_end") or {}
    raw = result.get("raw") or {}
    return {
        "native": int(native.get("count", 0)),
        "end_to_end": int(end_to_end.get("count", 0)),
        "raw_native": len(raw.get("native_seconds") or []),
        "raw_end_to_end": len(raw.get("end_to_end_seconds") or []),
        "expected": repeats,
    }


def evaluate_benchmark(config: dict, summary: dict, devices: list[str], modes: set[str]) -> dict:
    """Evaluate completeness, integrity and failures without ever passing an empty set."""
    expected = build_expected(config, devices, modes)
    issues, notes, missing, incomplete = [], [], [], []
    correctness_details = {"expected": len(expected["correctness"]), "completed": 0, "missing": [], "incomplete": []}
    performance_details = {"expected": len(expected["performance"]), "completed": 0, "missing": [], "incomplete": []}
    integrity = summary.get("integrity") or {}
    integrity_status = integrity.get("status")
    if integrity_status is None:
        unchanged = summary.get("source_unchanged")
        integrity_status = "pass" if unchanged is True else "fail" if unchanged is False else "unknown"
    if integrity_status == "fail":
        issues.append("source or oracle integrity failed")
    elif integrity_status in {"unknown", "unavailable"}:
        notes.append(f"source integrity {integrity_status}")
    if not expected["correctness"]:
        issues.append("no expected correctness tasks")
    device_status = summary.get("device_status") or {}
    unavailable_devices = {
        device
        for device in devices
        if (device_status.get(device) or {}).get("status") == "unavailable"
    }
    for task in expected["correctness"]:
        input_id, device = task["input"], task["device"]
        result = (summary.get("correctness") or {}).get(input_id, {}).get(device)
        if result is None:
            missing.append(f"correctness:{input_id}/{device}")
            correctness_details["missing"].append(f"{input_id}/{device}")
            notes.append(f"missing correctness result {input_id}/{device}")
            continue
        correctness_details["completed"] += 1
        plan = (summary.get("requests") or {}).get(input_id, {}).get(device)
        expected_checks = None
        if plan:
            expected_checks = int(plan.get("ordinal_repeats", 0)) + int(plan.get("time_repeats", 0))
        actual_checks = len(result.get("checks") or [])
        if expected_checks is None or actual_checks != expected_checks:
            incomplete.append(f"correctness:{input_id}/{device}")
            correctness_details["incomplete"].append(f"{input_id}/{device}")
            notes.append(f"incomplete correctness evidence {input_id}/{device}: {actual_checks} != {expected_checks}")
        fallback = result.get("fallback") or {}
        if fallback.get("occurred"):
            issues.append(f"correctness {input_id}/{device}: CPU fallback")
        status = result.get("status")
        if status == "fail":
            issues.append(f"correctness {input_id}/{device}: fail")
        elif status in {"partial", "unavailable"}:
            notes.append(f"correctness {input_id}/{device}: {status}")
        elif status != "pass":
            notes.append(f"correctness {input_id}/{device}: unknown status {status!r}")
        if device in unavailable_devices:
            notes.append(f"device {device} is unavailable; its correctness result is not a GPU pass")
    correctness_details["status"] = (
        "fail" if any("correctness" in issue for issue in issues)
        else "partial" if correctness_details["missing"] or correctness_details["incomplete"] or any("correctness" in note for note in notes)
        else "pass"
    )

    if "performance" in modes and not config.get("performance", {}).get("enabled", True):
        issues.append("performance mode requested but performance is disabled")
        performance_details = {"status": "fail", "expected": 0, "completed": 0, "missing": [], "incomplete": []}
    elif "performance" in modes:
        if not expected["performance"]:
            issues.append("no expected performance tasks")
        repeats = int(config.get("performance", {}).get("repeats", 5))
        for task in expected["performance"]:
            input_id, device, batch = task["input"], task["device"], task["batch"]
            result = (summary.get("performance") or {}).get(input_id, {}).get(device, {}).get(str(batch))
            key = f"{input_id}/{device}/batch{batch}"
            if result is None:
                missing.append(f"performance:{key}")
                performance_details["missing"].append(key)
                notes.append(f"missing performance result {key}")
                continue
            performance_details["completed"] += 1
            status = result.get("status")
            if status in {"unavailable", "error", "failed"}:
                notes.append(f"performance {key}: {status}")
            elif status == "fail":
                issues.append(f"performance {key}: fail")
            fallback = result.get("fallback") or {}
            if fallback.get("occurred"):
                issues.append(f"performance {key}: CPU fallback")
            counts = _result_counts(result, repeats)
            if any(counts[name] < repeats for name in ("native", "end_to_end", "raw_native", "raw_end_to_end")):
                incomplete.append(f"performance:{key}")
                performance_details["incomplete"].append(f"{key}: {counts}")
                notes.append(f"incomplete performance repetitions {key}: {counts}")
            if device in unavailable_devices:
                notes.append(f"performance {key}: device unavailable")
        performance_details["status"] = (
            "fail" if any("performance" in issue for issue in issues)
            else "partial" if performance_details["missing"] or performance_details["incomplete"] or any("performance" in note for note in notes)
            else "pass"
        )
    else:
        performance_details = {"status": "not_requested", "expected": 0, "completed": 0, "missing": [], "incomplete": []}

    if summary.get("errors"):
        notes.append("runtime errors present")
    if issues:
        overall = "fail"
    elif unavailable_devices:
        overall = "unavailable"
    elif missing or incomplete or notes:
        overall = "partial"
    else:
        overall = "pass"
    return {
        "status": overall,
        "correctness": correctness_details,
        "performance": performance_details,
        "integrity": {"status": integrity_status},
        "missing": missing,
        "incomplete": incomplete,
        "issues": issues,
        "notes": notes,
    }


def dumps(value) -> str:
    """Strict JSON helper for tests; rejects non-JSON values such as tensors."""
    return json.dumps(value, allow_nan=False, sort_keys=True)

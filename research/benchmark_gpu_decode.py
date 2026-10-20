"""Standalone TorchCodec CPU/CUDA decode experiment (research tool, not a CLI feature).

Run this script with a consumer Python that has torch, torchcodec and av.  It
never selects CUDA silently: a CUDA request either produces tensors on CUDA or
is reported as unavailable/failed.  Reports contain metrics and hashes, not
video pixels.

Example:
    .consumer-gpu/bin/python research/benchmark_gpu_decode.py \
        --config research/results/rtx4090/session-001/benchmark-config.json \
        --out research/runs/rtx4090/session-001/gpu-benchmark
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import random
import shutil
import subprocess
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path

from boundary_audit import __version__
from boundary_audit.environment import collect_environment, nvidia_smi_path, source_provenance
from boundary_audit.gpu_benchmark import (
    build_expected,
    evaluate_benchmark,
    expected_ordinal_for_time,
    grid_error,
    map_time_to_ordinal,
    safe_time_value,
    time_matches,
    validate_config,
)
from boundary_audit.gpu_metrics import (
    chunked,
    compare_frame,
    summarize_values,
    to_hwc_uint8,
)
from boundary_audit.identity import decode_identity, validate_oracle
from boundary_audit.storage import write_json

PROJECT = Path(__file__).resolve().parents[1]
SCHEMA = "boundary-gpu-benchmark.v1"
DEFAULT_MAX_REFERENCE_BYTES = 268435456
DEFAULT_MAX_DECODE_FRAMES = 50000


class BudgetExceeded(RuntimeError):
    pass


class DeviceUnavailable(RuntimeError):
    pass


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(value):
    path = Path(value)
    return (path if path.is_absolute() else PROJECT / path).resolve()


def relative_path(path):
    path = Path(path).resolve()
    try:
        return path.relative_to(PROJECT).as_posix()
    except ValueError:
        return path.name


def json_float(value):
    return float(value) if math.isfinite(value) else None


def peak_rss_kib():
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1])
    except OSError:
        pass
    return None


def nvidia_utilization():
    executable = nvidia_smi_path()
    if not executable:
        return None
    try:
        completed = subprocess.run(
            [
                executable,
                "--query-gpu=utilization.decoder,utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    values = [value.strip() for value in completed.stdout.strip().split(",")]
    if len(values) != 3:
        return None
    return {
        "decoder_utilization_percent": values[0],
        "gpu_utilization_percent": values[1],
        "memory_used_mib": values[2],
    }


def ffmpeg_decoders():
    executable = shutil.which("ffmpeg")
    if not executable:
        return {"available": False, "reason": "ffmpeg not on PATH"}
    try:
        completed = subprocess.run(
            [executable, "-hide_banner", "-decoders"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "reason": type(exc).__name__}
    if completed.returncode != 0:
        return {"available": False, "reason": "ffmpeg -decoders failed"}
    lines = [line.strip() for line in completed.stdout.splitlines() if "cuvid" in line.lower()]
    return {"available": bool(lines), "cuvid_decoders": lines}


def library_versions():
    import av
    import torch
    import torchcodec

    return {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "torch": torch.__version__,
        "torch_cuda_build": torch.version.cuda,
        "torch_cuda_available": bool(torch.cuda.is_available()),
        "torch_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "torch_num_threads": torch.get_num_threads(),
        "torch_num_interop_threads": torch.get_num_interop_threads(),
        "torchcodec": torchcodec.__version__,
        "torchcodec_file": "torchcodec/__init__.py",
        "torchcodec_cuda_backend": "ffmpeg (VideoDecoder default)",
        "av": av.__version__,
        "av_library_versions": av.library_versions,
        "ffmpeg_cli": ffmpeg_decoders(),
        "omp_num_threads": os.environ.get("OMP_NUM_THREADS"),
        "ld_library_path_entries": len(os.environ.get("LD_LIBRARY_PATH", "").split(os.pathsep))
        if os.environ.get("LD_LIBRARY_PATH")
        else 0,
    }


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if config.get("schema_version") != SCHEMA:
        raise ValueError(f"Config schema must be {SCHEMA}")
    if not isinstance(config.get("inputs"), list) or not config["inputs"]:
        raise ValueError("Config needs a nonempty inputs list")
    return config


def prepare_inputs(config):
    prepared = []
    for spec in config["inputs"]:
        item = dict(spec)
        if not item.get("id") or not item.get("path"):
            raise ValueError("Each input needs id and path")
        if item.get("kind") not in {"fixture", "real"}:
            raise ValueError("Input kind must be fixture or real")
        path = resolve_path(item["path"])
        if not path.is_file():
            raise ValueError(f"Input video is missing: {item['path']}")
        item["path"] = path
        if item["kind"] == "fixture":
            if not item.get("oracle") or not item.get("camera"):
                raise ValueError("Fixture inputs need oracle and camera")
            oracle_path = resolve_path(item["oracle"])
            oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
            validate_oracle(oracle)
            if item["camera"] not in oracle["cameras"]:
                raise ValueError("Fixture camera is absent from the oracle")
            item["oracle_data"] = oracle
            item["oracle_path"] = oracle_path
        if item.get("expected", "clean") not in {"clean", "fault"}:
            raise ValueError("Expected must be clean or fault")
        item.setdefault("expected", "clean")
        prepared.append(item)
    return prepared


def plan_requests(spec, frame_count, fps, seed):
    rng = random.Random(seed)
    if spec.get("ordinal_queries"):
        ordinals = [int(value) for value in spec["ordinal_queries"]]
    else:
        boundaries = [int(value) for value in spec.get("boundaries", [])]
        core = [0, 1, frame_count - 2, frame_count - 1]
        for boundary in boundaries:
            core.extend([boundary - 1, boundary, boundary + 1])
        core.extend(rng.sample(range(frame_count), min(6, frame_count)))
        ordinals = [value for value in core if 0 <= value < frame_count]
        ordinals.extend([0, frame_count - 1])
    if spec.get("time_queries"):
        times = [float(value) for value in spec["time_queries"]]
    else:
        end = frame_count / fps
        times = [0.0, 1.0 / fps, (frame_count / 2) / fps, (frame_count - 1) / fps, end]
        times.extend(round(rng.uniform(0, max(end - 1.0 / fps, 0)), 6) for _ in range(2))
    seek_modes = list(spec.get("seek_modes", ["exact", "approximate"]))
    plan = {
        "ordinals": ordinals,
        "times": times,
        "seek_modes": seek_modes,
        "ordinal_repeats": len(ordinals),
        "time_repeats": len(times) * len(seek_modes),
    }
    return plan


def frame_to_hwc(frame):
    return to_hwc_uint8(frame.detach().to("cpu").permute(1, 2, 0).contiguous().numpy())


def require_tensor_device(frame, device):
    observed = frame.device.type
    if observed != device:
        raise DeviceUnavailable(f"Requested {device}, observed {frame.device}")
    return str(frame.device)


def fallback_state(decoder):
    status = getattr(decoder, "cpu_fallback", None)
    text = str(status) if status is not None else "not reported"
    known = bool(getattr(status, "status_known", False))
    return {"status": text, "known": known, "occurred": bool(status) if known else False}


def decode_indices(decoder, indices, batch_size, device):
    frames, pts = [], []
    for chunk in chunked(indices, batch_size):
        batch = decoder.get_frames_at(indices=chunk)
        if len(batch.data) != len(chunk):
            raise ValueError("Decoder returned a different number of frames than requested")
        for frame, timestamp in zip(batch.data, batch.pts_seconds, strict=True):
            require_tensor_device(frame, device)
            frames.append(frame)
            pts.append(float(timestamp))
    return frames, pts


def build_cpu_references(path, needed, batch_size, max_bytes):
    from torchcodec.decoders import VideoDecoder

    decoder = VideoDecoder(str(path), device="cpu", seek_mode="exact")
    references, stored = {}, 0
    for chunk in chunked(sorted(needed), batch_size):
        batch = decoder.get_frames_at(indices=chunk)
        for index, frame in zip(chunk, batch.data, strict=True):
            pixels = frame_to_hwc(frame)
            stored += pixels.nbytes
            if stored > max_bytes:
                raise BudgetExceeded("CPU reference image budget exhausted")
            references[index] = pixels
    return references, stored


def build_pyav_references(path, needed, time_candidates, max_bytes, max_decode_frames, frame_count, fps):
    """Decode every frame for an independent PTS/duration map; retain selected RGB."""
    import av

    wanted = set(needed) | set(time_candidates)
    references, stored, decoded = {}, 0, 0
    intervals = []
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.codec_context.thread_count = 1
        time_base = stream.time_base
        for index, frame in enumerate(container.decode(stream)):
            decoded += 1
            if decoded > max_decode_frames:
                raise BudgetExceeded("Sequential PyAV reference frame budget exhausted")
            if frame.pts is None:
                raise ValueError("PyAV frame lacks PTS")
            point = float(frame.pts * time_base)
            duration = float(frame.duration * time_base) if frame.duration is not None else None
            intervals.append({"pts_seconds": point, "duration_seconds": duration})
            if index in wanted:
                pixels = frame.to_ndarray(format="rgb24")
                stored += pixels.nbytes
                if stored > max_bytes:
                    raise BudgetExceeded("PyAV reference image budget exhausted")
                references[index] = pixels
    if decoded < frame_count:
        raise ValueError(f"Sequential PyAV decoded {decoded} of {frame_count} frames")
    for index in range(len(intervals) - 1):
        duration = intervals[index]["duration_seconds"]
        if duration is None or duration <= 0:
            intervals[index]["duration_seconds"] = max(
                intervals[index + 1]["pts_seconds"] - intervals[index]["pts_seconds"], 1e-9
            )
    last_duration = intervals[-1]["duration_seconds"]
    if last_duration is None or last_duration <= 0:
        intervals[-1]["duration_seconds"] = 1.0 / fps if fps > 0 else 1e-9
    missing = wanted - references.keys()
    if missing:
        raise ValueError(f"Sequential PyAV reference missed ordinals {sorted(missing)[:5]}")
    return references, decoded, intervals


def oracle_identity(spec, ordinal):
    rows = spec["oracle_data"]["rows"]
    if not 0 <= ordinal < len(rows):
        raise ValueError("Ordinal is outside the fixture oracle")
    return rows[ordinal]["identities"][spec["camera"]]


def check_fixture(actual, expected, cpu_actual=None):
    try:
        decoded = decode_identity(actual, layout="HWC")
    except (ValueError, TypeError) as exc:
        return {
            "status": "unknown_identity",
            "reason": str(exc)[:300],
            "expected": expected,
            "cpu_identity": None if cpu_actual is None else _cpu_identity(cpu_actual),
        }
    cpu_identity = None if cpu_actual is None else _cpu_identity(cpu_actual)
    matches = all(decoded[key] == expected[key] for key in ("camera", "episode", "frame"))
    if cpu_identity is not None and cpu_identity.get("ok") and cpu_identity["identity"] != decoded:
        status = "device_disagreement"
    elif matches:
        status = "pass"
    else:
        status = "wrong_frame"
    return {
        "status": status,
        "decoded": decoded,
        "expected": expected,
        "cpu_identity": cpu_identity,
    }


def _cpu_identity(image):
    try:
        return {"ok": True, "identity": decode_identity(image, layout="HWC")}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "reason": str(exc)[:200]}


def combine_references(cpu_result, pyav_result):
    statuses = {cpu_result.get("status"), pyav_result.get("status")}
    if "wrong_shape" in statuses:
        return "wrong_shape", "reference shape mismatch"
    if "wrong_frame" in statuses:
        return "wrong_frame", "CPU TorchCodec or PyAV reference identifies a wrong neighbour"
    if statuses == {"pass"}:
        return "pass", "CPU TorchCodec and PyAV references agree"
    if "pass" in statuses:
        return "ambiguous", "CPU TorchCodec and PyAV references disagree"
    return "ambiguous", "neither reference separates a unique neighbour"


def check_real(actual, ordinal, cpu_refs, pyav_refs, allow_range):
    cpu_result = compare_frame(actual, cpu_refs, ordinal, allow_limited_range=allow_range)
    pyav_result = compare_frame(actual, pyav_refs, ordinal, allow_limited_range=allow_range)
    status, reason = combine_references(cpu_result, pyav_result)
    raw_metrics = cpu_result.get("raw") or {}
    if "against_expected" in raw_metrics:
        raw_metrics = raw_metrics["against_expected"]
    adjusted_metrics = (cpu_result.get("limited_range_adjusted") or {}).get("against_expected")
    return {
        "status": status,
        "reason": reason,
        "cpu_reference": cpu_result,
        "pyav_reference": pyav_result,
        "color_range_adjustment": bool(cpu_result.get("color_range_adjustment")),
        "raw": raw_metrics or None,
        "limited_range_adjusted": adjusted_metrics,
    }


def one_timestamp(decoder, seconds):
    try:
        batch = decoder.get_frames_played_at(seconds=[seconds])
    except Exception as exc:  # TorchCodec raises RuntimeError at the exclusive end
        return {"status": "error", "error_type": type(exc).__name__, "message": str(exc)[:300]}
    if len(batch.data) != 1:
        return {"status": "error", "message": "Time request returned a different number of frames"}
    frame = batch.data[0]
    return {
        "status": "ok",
        "frame": frame,
        "device": str(frame.device),
        "pts_seconds": float(batch.pts_seconds[0]),
        "duration_seconds": float(batch.duration_seconds[0]) if hasattr(batch, "duration_seconds") else None,
    }


def compare_pts(expected, actual):
    if expected is None or actual is None:
        return None
    return abs(float(expected) - float(actual))


def run_correctness(spec, device, config, controls):
    from torchcodec.decoders import VideoDecoder

    batch_size = int(config.get("correctness_batch_size", 8))
    max_frames = int(config.get("max_frames_per_input", 600))
    max_reference_bytes = int(config.get("max_reference_bytes", DEFAULT_MAX_REFERENCE_BYTES))
    max_decode_frames = int(config.get("max_decode_frames", DEFAULT_MAX_DECODE_FRAMES))
    seed = int(config.get("seed", 20261014))
    decoder = VideoDecoder(str(spec["path"]), device=device, seek_mode="exact")
    metadata = decoder.metadata
    frame_count, fps = int(metadata.num_frames), float(metadata.average_fps)
    spec["frame_count"] = frame_count
    plan = plan_requests(spec, frame_count, fps, seed)
    # FFmpeg CUDA reports fallback status only after the first frame is decoded.
    probe = decoder.get_frames_at(indices=[0])
    require_tensor_device(probe.data[0], device)
    fallback = fallback_state(decoder)
    result = {
        "kind": spec["kind"],
        "expected": spec["expected"],
        "frame_count": frame_count,
        "fps": fps,
        "metadata": {
            "duration_seconds": float(metadata.duration_seconds),
            "begin_stream_seconds": float(metadata.begin_stream_seconds),
            "end_stream_seconds": float(metadata.end_stream_seconds),
        },
        "fallback": fallback,
        "requested_ordinals": len(plan["ordinals"]),
        "requested_times": plan["time_repeats"],
        "coverage": {
            "ordinal_requests": len(plan["ordinals"]),
            "time_requests": plan["time_repeats"],
            "checks": 0,
        },
        "checks": [],
        "errors": [],
    }
    if fallback["occurred"]:
        result["errors"].append({"kind": "cpu_fallback", "detail": fallback["status"]})
        result["status"] = "fail"
        return result, plan
    if device == "cuda" and not fallback["known"]:
        result["errors"].append({"kind": "fallback_unknown", "detail": fallback["status"]})
        result["status"] = "unavailable"
        return result, plan
    budget = 0
    needed = {
        index + delta
        for index in plan["ordinals"]
        for delta in (-1, 0, 1)
        if 0 <= index + delta < frame_count
    }
    time_candidates = set()
    for seconds in plan["times"]:
        ordinal = expected_ordinal_for_time(seconds, fps, frame_count)
        if ordinal is not None:
            time_candidates.update(index for index in (ordinal - 1, ordinal, ordinal + 1) if 0 <= index < frame_count)
    needed.update(time_candidates)
    needed = {index for index in needed if 0 <= index < frame_count}

    # PyAV is decoded once for an independent PTS/duration map and selected RGB.
    pyav_refs, pyav_decoded, intervals = build_pyav_references(
        spec["path"], needed, time_candidates, max_reference_bytes, max_decode_frames, frame_count, fps
    )
    pyav_grid = grid_error(intervals, fps)
    uniform_time = pyav_grid is not None and pyav_grid <= 1e-6
    cpu_refs, cpu_bytes = build_cpu_references(spec["path"], needed, batch_size, max_reference_bytes)
    result["reference"] = {
        "frames": len(cpu_refs),
        "cpu_image_bytes": cpu_bytes,
        "pyav_frames": len(pyav_refs),
        "pyav_decoded_frames": pyav_decoded,
        "time_source": "sequential PyAV PTS/duration intervals",
        "pyav_grid_max_error_seconds": pyav_grid,
        "uniform_time_mapping": uniform_time,
    }

    # Ordinal requests, preserving duplicates and order.
    for chunk in chunked(plan["ordinals"], batch_size):
        budget += len(chunk)
        if budget > max_frames:
            raise BudgetExceeded(f"Correctness frame budget exceeded for {spec['id']}")
        frames, timestamps = decode_indices(decoder, chunk, batch_size, device)
        for ordinal, timestamp, frame in zip(chunk, timestamps, frames, strict=True):
            actual = frame_to_hwc(frame)
            expected_pts = ordinal / fps
            pts_error = abs(timestamp - expected_pts)
            check = {
                "input": spec["id"],
                "device": device,
                "mode": "ordinal",
                "ordinal": ordinal,
                "pts_seconds": timestamp,
                "expected_pts_seconds": expected_pts,
                "pts_error_seconds": pts_error,
            }
            if spec["kind"] == "fixture":
                expected = oracle_identity(spec, ordinal)
                identity = check_fixture(actual, expected, cpu_refs.get(ordinal))
                check.update(identity)
                if identity["status"] == "wrong_frame" and spec["expected"] == "fault":
                    check["control"] = "detected"
                elif identity["status"] == "unknown_identity":
                    check["control"] = "unknown"
                elif identity["status"] == "pass" and spec["expected"] == "fault":
                    check["control"] = "unchanged"
            else:
                check.update(check_real(actual, ordinal, cpu_refs, pyav_refs, allow_range=device == "cuda"))
            if pts_error > 1e-4:
                check["status"] = "pts_mismatch"
            result["checks"].append(
                {key: value for key, value in check.items() if key not in {"cpu_identity"}}
            )
            if spec["kind"] == "fixture":
                controls[(spec["id"], device, spec["expected"], check.get("control") or check["status"])] += 1

    # Time requests are resolved from PyAV intervals, never from a decoder's returned PTS.
    time_budget = 0
    for seek_mode in plan["seek_modes"]:
        device_decoder = VideoDecoder(str(spec["path"]), device=device, seek_mode=seek_mode)
        cpu_decoder = VideoDecoder(str(spec["path"]), device="cpu", seek_mode=seek_mode)
        for seconds in plan["times"]:
            time_budget += 1
            if budget + time_budget > max_frames:
                raise BudgetExceeded(f"Correctness frame budget exceeded for {spec['id']}")
            cpu_value = one_timestamp(cpu_decoder, seconds)
            device_value = one_timestamp(device_decoder, seconds)
            mapping = map_time_to_ordinal(seconds, intervals)
            if not uniform_time:
                mapping = {"status": "unverified_nonuniform", "reason": "PyAV PTS is not on the declared CFR grid"}
            check = {
                "input": spec["id"],
                "device": device,
                "mode": "time",
                "seek_mode": seek_mode,
                "seconds": seconds,
                "time_mapping": mapping,
                "cpu_time": safe_time_value(cpu_value),
                "device_time": safe_time_value(device_value),
            }
            if mapping["status"] == "out_of_range":
                both_error = cpu_value["status"] == "error" and device_value["status"] == "error"
                both_ok = cpu_value["status"] == "ok" and device_value["status"] == "ok"
                if both_error:
                    check["status"] = "expected_boundary_error"
                elif both_ok:
                    check["status"] = "unexpected_time_frame"
                else:
                    check["status"] = "device_disagreement"
            elif mapping["status"] != "ok":
                check["status"] = "unverified_time_mapping"
            else:
                ordinal = mapping["ordinal"]
                check["ordinal"] = ordinal
                check["expected_pts_seconds"] = mapping["pts_seconds"]
                if ordinal not in cpu_refs or ordinal not in pyav_refs:
                    check["status"] = "reference_missing"
                elif cpu_value["status"] != "ok" or device_value["status"] != "ok":
                    check["status"] = (
                        "device_disagreement"
                        if cpu_value["status"] != device_value["status"]
                        else "error"
                    )
                else:
                    require_tensor_device(device_value["frame"], device)
                    cpu_pts, device_pts = cpu_value["pts_seconds"], device_value["pts_seconds"]
                    check.update(
                        cpu_pts_seconds=cpu_pts,
                        device_pts_seconds=device_pts,
                        cpu_pts_error_seconds=abs(cpu_pts - mapping["pts_seconds"]),
                        device_pts_error_seconds=abs(device_pts - mapping["pts_seconds"]),
                    )
                    if not time_matches(cpu_pts, mapping) or not time_matches(device_pts, mapping):
                        check["status"] = "pts_mismatch"
                    else:
                        actual = frame_to_hwc(device_value["frame"])
                        cpu_actual = frame_to_hwc(cpu_value["frame"])
                        if spec["kind"] == "fixture":
                            expected = oracle_identity(spec, ordinal)
                            identity = check_fixture(actual, expected, cpu_actual)
                            check.update(identity)
                            if identity["status"] == "wrong_frame" and spec["expected"] == "fault":
                                check["control"] = "detected"
                            elif identity["status"] == "unknown_identity":
                                check["control"] = "unknown"
                            elif identity["status"] == "pass" and spec["expected"] == "fault":
                                check["control"] = "unchanged"
                        else:
                            device_reference = check_real(
                                actual, ordinal, cpu_refs, pyav_refs, allow_range=device == "cuda"
                            )
                            cpu_reference = check_real(
                                cpu_actual, ordinal, cpu_refs, pyav_refs, allow_range=False
                            )
                            check.update(device_reference=device_reference, cpu_time_reference=cpu_reference)
                            device_status = device_reference["status"]
                            cpu_status = cpu_reference["status"]
                            if device_status in {"wrong_frame", "wrong_shape"} or cpu_status in {"wrong_frame", "wrong_shape"}:
                                check["status"] = "wrong_frame"
                            elif device_status == "pass" and cpu_status == "pass":
                                check["status"] = "pass"
                            else:
                                check["status"] = "ambiguous"
            result["checks"].append(check)
            if spec["kind"] == "fixture":
                controls[(spec["id"], device, spec["expected"], check.get("control") or check["status"])] += 1
    result["checks"].sort(key=lambda item: (item["mode"], item.get("seek_mode", ""), item.get("ordinal", -1), item.get("seconds", -1)))
    result["coverage"]["checks"] = len(result["checks"])
    counts = Counter(item["status"] for item in result["checks"])
    result["counts"] = dict(sorted(counts.items()))
    if spec["expected"] == "clean":
        bad = (
            counts.get("wrong_frame", 0)
            + counts.get("wrong_shape", 0)
            + counts.get("unknown_identity", 0)
            + counts.get("error", 0)
            + counts.get("device_disagreement", 0)
            + counts.get("pts_mismatch", 0)
            + counts.get("unexpected_time_frame", 0)
        )
        result["status"] = (
            "fail"
            if bad
            else "partial"
            if counts.get("ambiguous")
            or counts.get("reference_missing")
            or counts.get("unverified_time_mapping")
            or counts.get("unverified_nonuniform")
            or counts.get("pts_grid")
            else "pass"
        )
    else:
        detected = sum(1 for item in result["checks"] if item.get("control") == "detected")
        unknown = sum(1 for item in result["checks"] if item.get("control") == "unknown")
        bad = (
            counts.get("error", 0)
            + counts.get("device_disagreement", 0)
            + counts.get("pts_mismatch", 0)
            + counts.get("unexpected_time_frame", 0)
        )
        result["status"] = (
            "fail"
            if not detected or bad
            else "partial"
            if unknown
            or counts.get("ambiguous")
            or counts.get("reference_missing")
            or counts.get("unverified_time_mapping")
            or counts.get("unverified_nonuniform")
            else "pass"
        )
    return result, plan


def checksum_frames(frames):
    return float(sum(float(frame.float().mean()) for frame in frames))


def run_performance(spec, device, batch_size, config, timings):
    import torch
    from torchcodec.decoders import VideoDecoder

    performance = config.get("performance", {})
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("Performance batch size must be an integer >= 1")
    repeats = int(performance.get("repeats", 5))
    frames = int(performance.get("frames", 32))
    warmup = int(performance.get("warmup", 3))
    if repeats < 1:
        raise ValueError("Performance repeats must be >= 1")
    if frames < 1:
        raise ValueError("Performance frames must be >= 1")
    if warmup < 0:
        raise ValueError("Performance warmup must be >= 0")
    frame_count = spec.get("frame_count")
    if frame_count is None:
        probe = VideoDecoder(str(spec["path"]), device="cpu", seek_mode="exact")
        frame_count = int(probe.metadata.num_frames)
        spec["frame_count"] = frame_count
    frames = min(frames, frame_count)
    if frames < 1:
        raise ValueError("Performance needs at least one frame")
    rng = random.Random(int(config.get("seed", 20261014)))
    indices = sorted(rng.sample(range(frame_count), frames))
    common_endpoint = performance.get("common_endpoint", "cuda")
    common_cuda = common_endpoint == "cuda" and torch.cuda.is_available()
    if common_cuda:
        torch.cuda.reset_peak_memory_stats()
    rss_before = peak_rss_kib()
    nvidia_before = nvidia_utilization()
    start = time.perf_counter()
    decoder = VideoDecoder(str(spec["path"]), device=device, seek_mode="exact")
    create_seconds = time.perf_counter() - start
    first_start = time.perf_counter()
    first = decoder.get_frames_at(indices=indices[:1])
    if device == "cuda":
        torch.cuda.synchronize()
    first_decode_seconds = time.perf_counter() - first_start
    require_tensor_device(first.data[0], device)
    fallback = fallback_state(decoder)
    native_seconds, transfer_seconds, common_seconds, end_to_end_seconds = [], [], [], []

    def one_chunk(chunk, measure):
        decode_time = transfer_time = checksum_time = 0.0
        for part in chunked(chunk, batch_size):
            begin = time.perf_counter()
            batch = decoder.get_frames_at(indices=part)
            require_tensor_device(batch.data[0], device)
            if device == "cuda":
                torch.cuda.synchronize()
            decode_time += time.perf_counter() - begin
            if common_cuda and device == "cpu":
                begin = time.perf_counter()
                moved = batch.data.to("cuda", non_blocking=False)
                torch.cuda.synchronize()
                transfer_time += time.perf_counter() - begin
            else:
                moved = batch.data
            if measure:
                begin = time.perf_counter()
                checksum_frames(moved)
                checksum_time += time.perf_counter() - begin
        return decode_time, transfer_time, checksum_time

    for _ in range(warmup):
        one_chunk(indices, measure=False)
    for _ in range(repeats):
        decode_time, transfer_time, checksum_time = one_chunk(indices, measure=True)
        native_seconds.append(decode_time)
        if common_cuda and device == "cpu":
            transfer_seconds.append(transfer_time)
            common_seconds.append(decode_time + transfer_time)
        else:
            common_seconds.append(decode_time)
        end_to_end_seconds.append(decode_time + transfer_time + checksum_time)
    rss_after = peak_rss_kib()
    nvidia_after = nvidia_utilization()
    vram = None
    if device == "cuda" or common_cuda:
        torch.cuda.synchronize()
        vram = {
            "allocated_mib": round(torch.cuda.max_memory_allocated() / (1024 * 1024), 3),
            "reserved_mib": round(torch.cuda.max_memory_reserved() / (1024 * 1024), 3),
        }
    if fallback.get("occurred"):
        status = "fail"
    elif device == "cuda" and not fallback.get("known", False):
        status = "unavailable"
    elif len(native_seconds) < repeats or len(end_to_end_seconds) < repeats:
        status = "partial"
    else:
        status = "pass"
    result = {
        "status": status,
        "input": spec["id"],
        "device": device,
        "batch_size": batch_size,
        "n_frames": frames,
        "indices": indices,
        "decoder_create_seconds": create_seconds,
        "first_decode_seconds": first_decode_seconds,
        "first_decode_scope": (
            "first call in this process after correctness/CUDA work; not a cold-process or NVDEC-initialization measurement"
        ),
        "workload": (
            "32-frame single-video microbenchmark; decoder reused; CPU common endpoint includes H2D; GPU checksum; "
            "no reference checks, LeRobot windows/actions/padding, multi-camera or DataLoader"
        ),
        "warmup": warmup,
        "repeats": repeats,
        "fallback": fallback,
        "native": summarize_values(native_seconds),
        "transfer": summarize_values(transfer_seconds) if transfer_seconds else None,
        "common_endpoint": {"endpoint": common_endpoint, "timings": summarize_values(common_seconds)},
        "end_to_end": summarize_values(end_to_end_seconds),
        "raw": {
            "native_seconds": native_seconds,
            "transfer_seconds": transfer_seconds,
            "common_seconds": common_seconds,
            "end_to_end_seconds": end_to_end_seconds,
        },
        "vram": vram,
        "rss_kib_before_after": [rss_before, rss_after],
        "nvidia_before_after": [nvidia_before, nvidia_after],
        "note": "Wall-clock totals; CUDA synchronized; decoder reused after first creation.",
    }
    timings.append(result)
    return result


def write_html(summary, path):
    correctness = summary.get("correctness", {})
    rows = []
    for input_id, devices in correctness.items():
        for device, result in devices.items():
            rows.append(
                f"<tr><td>{html.escape(input_id)}</td><td>{html.escape(device)}</td>"
                f"<td>{html.escape(str(result.get('status', 'unknown')))}</td>"
                f"<td>{html.escape(json.dumps(result.get('counts', {}), sort_keys=True))}</td></tr>"
            )
    performance = summary.get("performance", {})
    perf_rows = []
    for input_id, devices in performance.items():
        for device, batches in devices.items():
            for batch, result in batches.items():
                native = result.get("native", {})
                e2e = result.get("end_to_end", {})
                perf_rows.append(
                    f"<tr><td>{html.escape(input_id)}</td><td>{html.escape(device)}</td><td>{batch}</td>"
                    f"<td>{native.get('median', '')}</td><td>{e2e.get('median', '')}</td></tr>"
                )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>TorchCodec device benchmark</title>
<style>body{{font-family:system-ui,sans-serif;margin:2rem;line-height:1.4}}table{{border-collapse:collapse;margin:1rem 0}}td,th{{border:1px solid #ccc;padding:.3rem .6rem;text-align:left}}code{{background:#f3f3f3;padding:.1rem .3rem}}</style>
</head><body>
<h1>TorchCodec CPU/CUDA decode benchmark</h1>
<p><strong>Status:</strong> {html.escape(summary.get('status', 'unknown'))}</p>
<p>This report contains frame-identity and timing evidence only. It does not contain video pixels and does not claim physical synchronization.</p>
<h2>Correctness</h2><table><thead><tr><th>Input</th><th>Device</th><th>Status</th><th>Counts</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<h2>Performance (seconds, median)</h2><table><thead><tr><th>Input</th><th>Device</th><th>Batch</th><th>Native</th><th>End-to-end</th></tr></thead><tbody>{''.join(perf_rows)}</tbody></table>
<h2>Limits</h2><p>{html.escape(summary.get('limitations', ''))}</p>
</body></html>
"""
    Path(path).write_text(document, encoding="utf-8")


def source_hashes(inputs):
    result = {}
    for spec in inputs:
        entry = {
            "path": relative_path(spec["path"]),
            "kind": spec["kind"],
            "sha256": sha256(spec["path"]),
            "bytes": spec["path"].stat().st_size,
        }
        if spec["kind"] == "fixture":
            entry["oracle"] = {
                "path": relative_path(spec["oracle_path"]),
                "sha256": sha256(spec["oracle_path"]),
            }
        result[spec["id"]] = entry
    return result


def sources_unchanged(before, after):
    if not before or not after:
        return None
    for input_id, entry in before.items():
        current = after.get(input_id)
        if not current or current.get("sha256") != entry.get("sha256"):
            return False
        if entry.get("oracle") and current.get("oracle", {}).get("sha256") != entry["oracle"]["sha256"]:
            return False
    return True


def performance_comparison(performance):
    comparison = {}
    for input_id, device_results in performance.items():
        cpu_batches = device_results.get("cpu", {})
        cuda_batches = device_results.get("cuda", {})
        for batch, cpu_result in cpu_batches.items():
            cuda_result = cuda_batches.get(batch)
            if not isinstance(cuda_result, dict) or "native" not in cuda_result:
                continue
            cpu_native = (cpu_result.get("native") or {}).get("median")
            cuda_native = (cuda_result.get("native") or {}).get("median")
            cpu_e2e = (cpu_result.get("end_to_end") or {}).get("median")
            cuda_e2e = (cuda_result.get("end_to_end") or {}).get("median")
            if not cpu_native or not cuda_native or not cpu_e2e or not cuda_e2e:
                continue
            comparison[f"{input_id}|batch{batch}"] = {
                "cpu_native_seconds": cpu_native,
                "cuda_native_seconds": cuda_native,
                "cpu_end_to_end_seconds": cpu_e2e,
                "cuda_end_to_end_seconds": cuda_e2e,
                "native_cpu_over_cuda": cpu_native / cuda_native,
                "end_to_end_cpu_over_cuda": cpu_e2e / cuda_e2e,
                "scope": (
                    "32-frame single-video microbenchmark; decoder reused; CPU e2e includes H2D; "
                    "no full LeRobot window/action/padding processing or RGB-equivalence claim"
                ),
            }
    return comparison


def write_artifacts(out, summary, requests, controls_summary, timings):
    write_json(out / "requests.json", requests)
    write_json(out / "controls-summary.json", controls_summary)
    write_json(
        out / "source-integrity.json",
        {
            "before": summary["integrity"]["before"],
            "after": summary["integrity"]["after"],
            "unchanged": summary["integrity"]["unchanged"],
            "status": summary["integrity"]["status"],
        },
    )
    write_json(out / "summary.json", summary)
    with (out / "timings.jsonl").open("w", encoding="utf-8") as stream:
        for item in timings:
            stream.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n")
    write_html(summary, out / "report.html")
    with zipfile.ZipFile(out / "evidence.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in (
            "summary.json",
            "requests.json",
            "timings.jsonl",
            "environment.json",
            "controls-summary.json",
            "report.html",
            "source-integrity-before.json",
            "source-integrity.json",
        ):
            if (out / name).is_file():
                archive.write(out / name, name)


def prepare_run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--devices", help="Comma-separated override, e.g. cpu,cuda")
    parser.add_argument("--modes", default="correctness,performance")
    parser.add_argument("--warmup", type=int)
    parser.add_argument("--repeats", type=int)
    parser.add_argument("--max-seconds", type=float)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.devices:
        config["devices"] = [value.strip() for value in args.devices.split(",") if value.strip()]
    if args.warmup is not None:
        config.setdefault("performance", {})["warmup"] = args.warmup
    if args.repeats is not None:
        config.setdefault("performance", {})["repeats"] = args.repeats
    if args.max_seconds is not None:
        config["max_seconds"] = args.max_seconds
    modes = {value.strip() for value in args.modes.split(",") if value.strip()}
    validate_config(config, modes)
    inputs = prepare_inputs(config)
    devices = list(config.get("devices", ["cpu", "cuda"]))
    out = args.out.resolve()
    if out.exists():
        raise ValueError("Use a fresh output directory")
    return config, args, inputs, devices, modes, out


def main(argv=None):
    config, args, inputs, devices, modes, out = prepare_run(argv)
    out.mkdir(parents=True)
    import torch

    environment = collect_environment()
    environment["libraries"] = library_versions()
    source = source_provenance(PROJECT)
    write_json(out / "environment.json", environment)
    device_status = {"cpu": {"status": "available"}}
    if "cuda" in devices:
        available = bool(torch.cuda.is_available())
        device_status["cuda"] = {
            "status": "available" if available else "unavailable",
            "torch_cuda_available": available,
            "device": torch.cuda.get_device_name(0) if available else None,
            "reason": None if available else "torch.cuda.is_available() is false",
        }
    requests, correctness, performance, controls = {}, {}, {}, Counter()
    timings = []
    started = time.perf_counter()
    max_seconds = float(config.get("max_seconds", 900))
    summary = {
        "schema_version": "boundary-gpu-benchmark-summary.v1",
        "tool_version": __version__,
        "measurement_time": environment["measurement_time"],
        "source": source,
        "environment": environment,
        "device_status": device_status,
        "modes": sorted(modes),
        "input_hashes": {},
        "source_unchanged": None,
        "requests": requests,
        "correctness": correctness,
        "controls": {"counts": {}},
        "performance": performance,
        "performance_comparison": {},
        "integrity": {"status": "unknown", "before": {}, "after": {}, "unchanged": None},
        "budget": {"kind": "soft", "max_seconds": max_seconds, "exhausted": False},
        "errors": [],
        "limitations": (
            "Fixture markers are synthetic ground truth; real RGB is compared with an independent sequential "
            "PyAV PTS/duration reference and a same-environment CPU TorchCodec reference. CUDA output observed "
            "in this environment is TV-range RGB, so raw and limited-to-full metrics are reported separately. "
            "Performance is a 32-frame single-video decoder microbenchmark, not a full tool or RGB-equivalent "
            "throughput claim. This is decode-path evidence, not physical synchronization, training uplift, or "
            "a stock LeRobot GPU-reader claim."
        ),
    }
    try:
        try:
            before = source_hashes(inputs)
        except Exception as exc:
            before = {}
            summary["errors"].append({"kind": "integrity_before", "detail": f"{type(exc).__name__}: {exc}"})
        summary["input_hashes"] = before
        write_json(out / "source-integrity-before.json", before)
        for device in devices:
            if device == "cuda" and device_status["cuda"]["status"] != "available":
                summary["errors"].append({"kind": "device_unavailable", "device": device})
                continue
            for spec in inputs:
                if time.perf_counter() - started > max_seconds:
                    raise BudgetExceeded("Benchmark soft wall-clock budget exhausted")
                try:
                    result, plan = run_correctness(spec, device, config, controls)
                except BudgetExceeded as exc:
                    result = {"status": "partial", "errors": [{"kind": "budget", "detail": str(exc)}], "checks": []}
                    plan = None
                except Exception as exc:
                    result = {
                        "status": "unavailable",
                        "errors": [{"kind": type(exc).__name__, "detail": str(exc)[:500]}],
                        "checks": [],
                    }
                    plan = None
                correctness.setdefault(spec["id"], {})[device] = result
                if plan is not None:
                    requests.setdefault(spec["id"], {})[device] = plan
                if result["status"] not in {"pass", "partial"}:
                    summary["errors"].append(
                        {"kind": "correctness", "input": spec["id"], "device": device, "status": result["status"]}
                    )
                print(f"correctness {spec['id']}/{device}: {result['status']}", flush=True)
        if "performance" in modes and config.get("performance", {}).get("enabled", True):
            selected = set(config.get("performance", {}).get("inputs", []))
            for spec in inputs:
                if selected and spec["id"] not in selected:
                    continue
                for device in devices:
                    if device == "cuda" and device_status["cuda"]["status"] != "available":
                        continue
                    for batch_size in config.get("performance", {}).get("batch_sizes", [1, 8, 32]):
                        if time.perf_counter() - started > max_seconds:
                            raise BudgetExceeded("Benchmark soft wall-clock budget exhausted")
                        try:
                            result = run_performance(spec, device, int(batch_size), config, timings)
                        except BudgetExceeded as exc:
                            result = {"status": "partial", "error": str(exc)}
                        except Exception as exc:
                            result = {"status": "unavailable", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
                        performance.setdefault(spec["id"], {}).setdefault(device, {})[str(batch_size)] = result
                        if result.get("status") not in {"pass", "partial"}:
                            summary["errors"].append(
                                {
                                    "kind": "performance",
                                    "input": spec["id"],
                                    "device": device,
                                    "batch": batch_size,
                                    "status": result.get("status"),
                                }
                            )
                        print(
                            f"performance {spec['id']}/{device}/batch{batch_size}: "
                            f"{result.get('native', {}).get('median')} ({result.get('status')})",
                            flush=True,
                        )
    except BudgetExceeded as exc:
        summary["budget"]["exhausted"] = True
        summary["errors"].append({"kind": "budget", "detail": str(exc)})
    except Exception as exc:
        summary["errors"].append({"kind": type(exc).__name__, "detail": str(exc)[:500]})
    finally:
        try:
            after = source_hashes(inputs)
        except Exception as exc:
            after = {}
            summary["errors"].append({"kind": "integrity_after", "detail": f"{type(exc).__name__}: {exc}"})
        unchanged = sources_unchanged(summary["input_hashes"], after)
        integrity_status = "fail" if unchanged is False else "pass" if unchanged is True else "unknown"
        summary["integrity"] = {
            "status": integrity_status,
            "before": summary["input_hashes"],
            "after": after,
            "unchanged": unchanged,
        }
        summary["source_unchanged"] = unchanged
        controls_summary = {
            "counts": {f"{a}|{b}|{c}|{d}": value for (a, b, c, d), value in controls.items()}
        }
        summary["controls"] = controls_summary
        summary["performance_comparison"] = performance_comparison(performance)
        summary["expected"] = build_expected(config, devices, modes)
        summary["evaluation"] = evaluate_benchmark(config, summary, devices, modes)
        summary["status"] = summary["evaluation"]["status"]
        write_artifacts(out, summary, requests, controls_summary, timings)
    print(json.dumps({"status": summary["status"], "out": relative_path(out)}, indent=2), flush=True)
    return 0 if summary["status"] in {"pass", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

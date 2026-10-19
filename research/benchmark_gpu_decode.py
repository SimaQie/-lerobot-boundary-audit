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

from boundary_audit.environment import collect_environment
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
    executable = shutil.which("nvidia-smi")
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
        "torchcodec_file": relative_path(torchcodec.__file__),
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


def build_pyav_references(path, needed, max_bytes, max_decode_frames):
    import av

    wanted = set(needed)
    if not wanted:
        return {}, 0
    max_needed = max(wanted)
    references, stored, decoded = {}, 0, 0
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.codec_context.thread_count = 1
        for index, frame in enumerate(container.decode(stream)):
            decoded += 1
            if decoded > max_decode_frames:
                raise BudgetExceeded("Sequential PyAV reference frame budget exhausted")
            if index in wanted:
                pixels = frame.to_ndarray(format="rgb24")
                stored += pixels.nbytes
                if stored > max_bytes:
                    raise BudgetExceeded("PyAV reference image budget exhausted")
                references[index] = pixels
            if index >= max_needed:
                break
    missing = wanted - references.keys()
    if missing:
        raise ValueError(f"Sequential PyAV reference missed ordinals {sorted(missing)[:5]}")
    return references, decoded


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
    return {
        "status": status,
        "reason": reason,
        "cpu_reference": cpu_result,
        "pyav_reference": pyav_result,
        "color_range_adjustment": bool(cpu_result.get("color_range_adjustment")),
        "raw": cpu_result.get("raw", {}).get("against_expected"),
        "limited_range_adjusted": (cpu_result.get("limited_range_adjusted") or {}).get("against_expected"),
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

    # Resolve CPU time semantics first so their ordinals join the reference set.
    cpu_time = {}
    for seek_mode in plan["seek_modes"]:
        cpu_decoder = VideoDecoder(str(spec["path"]), device="cpu", seek_mode=seek_mode)
        for seconds in plan["times"]:
            result_key = (seek_mode, seconds)
            value = one_timestamp(cpu_decoder, seconds)
            cpu_time[result_key] = value
            if value["status"] == "ok":
                ordinal = round(value["pts_seconds"] * fps)
                if abs(value["pts_seconds"] - ordinal / fps) > 1e-4:
                    result["errors"].append(
                        {
                            "kind": "pts_grid",
                            "seek_mode": seek_mode,
                            "seconds": seconds,
                            "pts_seconds": value["pts_seconds"],
                        }
                    )
                needed.update(index + delta for index in [ordinal] for delta in (-1, 0, 1) if 0 <= index + delta < frame_count)
    needed = {index for index in needed if 0 <= index < frame_count}
    cpu_refs, cpu_bytes = build_cpu_references(spec["path"], needed, batch_size, max_reference_bytes)
    pyav_refs, pyav_decoded = ({}, 0)
    if spec["kind"] == "real":
        pyav_refs, pyav_decoded = build_pyav_references(
            spec["path"], needed, max_reference_bytes, max_decode_frames
        )
    result["reference"] = {
        "frames": len(cpu_refs),
        "cpu_image_bytes": cpu_bytes,
        "pyav_frames": len(pyav_refs),
        "pyav_decoded_frames": pyav_decoded,
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

    # Time requests, one timestamp at a time so the exclusive end is recorded, not hidden.
    time_budget = 0
    for seek_mode in plan["seek_modes"]:
        device_decoder = VideoDecoder(str(spec["path"]), device=device, seek_mode=seek_mode)
        for seconds in plan["times"]:
            time_budget += 1
            if budget + time_budget > max_frames:
                raise BudgetExceeded(f"Correctness frame budget exceeded for {spec['id']}")
            cpu_value = cpu_time[(seek_mode, seconds)]
            device_value = one_timestamp(device_decoder, seconds)
            check = {
                "input": spec["id"],
                "device": device,
                "mode": "time",
                "seek_mode": seek_mode,
                "seconds": seconds,
            }
            if cpu_value["status"] == "error" and device_value["status"] == "error":
                at_boundary = (
                    seconds >= float(metadata.end_stream_seconds) - 1e-6
                    or seconds < float(metadata.begin_stream_seconds) - 1e-6
                )
                check.update(
                    status="expected_boundary_error" if at_boundary else "error",
                    cpu_error=cpu_value,
                    device_error=device_value,
                )
            elif cpu_value["status"] != device_value["status"]:
                check.update(status="device_disagreement", cpu_error=cpu_value, device_error=device_value)
            elif cpu_value["status"] == "error":
                check.update(status="error", cpu_error=cpu_value, device_error=device_value)
            else:
                require_tensor_device(device_value["frame"], device)
                cpu_pts, device_pts = cpu_value["pts_seconds"], device_value["pts_seconds"]
                ordinal = round(cpu_pts * fps)
                pts_error = compare_pts(cpu_pts, device_pts)
                check.update(
                    cpu_pts_seconds=cpu_pts,
                    device_pts_seconds=device_pts,
                    ordinal=ordinal,
                    pts_error_seconds=pts_error,
                )
                if abs(cpu_pts - ordinal / fps) > 1e-4:
                    check["status"] = "pts_grid"
                elif pts_error is not None and pts_error > 1e-4:
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
                        if ordinal in cpu_refs:
                            check.update(check_real(actual, ordinal, cpu_refs, pyav_refs, allow_range=device == "cuda"))
                        else:
                            check.update(status="reference_missing", reason="Time ordinal lacks a CPU reference")
                    if "status" not in check:
                        check["status"] = "pass"
            result["checks"].append(check)
            if spec["kind"] == "fixture":
                controls[(spec["id"], device, spec["expected"], check.get("control") or check["status"])] += 1
    result["checks"].sort(key=lambda item: (item["mode"], item.get("seek_mode", ""), item.get("ordinal", -1), item.get("seconds", -1)))
    counts = Counter(item["status"] for item in result["checks"])
    result["counts"] = dict(sorted(counts.items()))
    if spec["expected"] == "clean":
        bad = (
            counts.get("wrong_frame", 0)
            + counts.get("wrong_shape", 0)
            + counts.get("unknown_identity", 0)
            + counts.get("error", 0)
            + counts.get("device_disagreement", 0)
        )
        result["status"] = (
            "fail"
            if bad
            else "partial"
            if counts.get("ambiguous") or counts.get("reference_missing") or counts.get("pts_mismatch") or counts.get("pts_grid")
            else "pass"
        )
    else:
        detected = sum(1 for item in result["checks"] if item.get("control") == "detected")
        unknown = sum(1 for item in result["checks"] if item.get("control") == "unknown")
        result["status"] = (
            "fail"
            if not detected or counts.get("error") or counts.get("device_disagreement")
            else "partial"
            if unknown or counts.get("ambiguous") or counts.get("pts_mismatch") or counts.get("pts_grid")
            else "pass"
        )
    return result, plan


def checksum_frames(frames):
    return float(sum(float(frame.float().mean()) for frame in frames))


def run_performance(spec, device, batch_size, config, timings):
    import torch
    from torchcodec.decoders import VideoDecoder

    performance = config.get("performance", {})
    frame_count = spec.get("frame_count")
    if frame_count is None:
        probe = VideoDecoder(str(spec["path"]), device="cpu", seek_mode="exact")
        frame_count = int(probe.metadata.num_frames)
        spec["frame_count"] = frame_count
    frames = min(int(performance.get("frames", 32)), frame_count)
    rng = random.Random(int(config.get("seed", 20261014)) + batch_size)
    indices = sorted(rng.sample(range(frame_count), frames))
    warmup = int(performance.get("warmup", 3))
    repeats = int(performance.get("repeats", 5))
    common_endpoint = performance.get("common_endpoint", "cuda")
    common_cuda = common_endpoint == "cuda" and torch.cuda.is_available()
    if common_cuda:
        torch.cuda.reset_peak_memory_stats()
    rss_before = peak_rss_kib()
    nvidia_before = nvidia_utilization()
    start = time.perf_counter()
    decoder = VideoDecoder(str(spec["path"]), device=device, seek_mode="exact")
    create_seconds = time.perf_counter() - start
    first = decoder.get_frames_at(indices=indices[:1])
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
    result = {
        "input": spec["id"],
        "device": device,
        "batch_size": batch_size,
        "n_frames": frames,
        "indices": indices,
        "decoder_create_seconds": create_seconds,
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


def evaluate(summary, config, devices):
    issues, notes = [], []
    unavailable = summary.get("device_status", {}).get("cuda", {}).get("status") == "unavailable"
    for spec in config["inputs"]:
        for device in devices:
            result = summary.get("correctness", {}).get(spec["id"], {}).get(device)
            if not result:
                continue
            if result["status"] == "fail":
                issues.append(f"{spec['id']}/{device}: {result['status']}")
            elif result["status"] in {"partial", "unavailable"}:
                notes.append(f"{spec['id']}/{device}: {result['status']}")
            if spec["kind"] == "fixture" and spec["expected"] == "fault":
                controls = result.get("counts", {})
                if controls.get("pass", 0):
                    issues.append(f"{spec['id']}/{device}: a faulty fixture was not detected")
    if unavailable:
        issues.append("CUDA was requested but unavailable")
    for input_id, devices in summary.get("performance", {}).items():
        for device, batches in devices.items():
            if not isinstance(batches, dict):
                continue
            for batch, result in batches.items():
                if not isinstance(result, dict):
                    continue
                if result.get("fallback", {}).get("occurred"):
                    issues.append(f"performance {input_id}/{device}/{batch}: CPU fallback")
                elif device == "cuda" and not result.get("fallback", {}).get("known", False):
                    notes.append(f"performance {input_id}/{device}/{batch}: fallback status unknown")
    if any("unavailable" in issue for issue in issues):
        return "unavailable" if unavailable else "fail"
    if issues:
        return "fail"
    return "partial" if notes else "pass"


def write_html(summary, path):
    correctness = summary.get("correctness", {})
    rows = []
    for input_id, devices in correctness.items():
        for device, result in devices.items():
            rows.append(
                f"<tr><td>{html.escape(input_id)}</td><td>{html.escape(device)}</td>"
                f"<td>{html.escape(result['status'])}</td><td>{html.escape(json.dumps(result['counts'], sort_keys=True))}</td></tr>"
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


def main(argv=None):
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
    if not modes <= {"correctness", "performance"}:
        raise ValueError("Modes must be correctness and/or performance")
    inputs = prepare_inputs(config)
    devices = list(config.get("devices", ["cpu", "cuda"]))
    if not devices or not set(devices) <= {"cpu", "cuda"}:
        raise ValueError("Devices must be cpu and/or cuda")
    out = args.out.resolve()
    if out.exists():
        raise ValueError("Use a fresh output directory")
    out.mkdir(parents=True)
    import torch

    environment = collect_environment()
    environment["libraries"] = library_versions()
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
    sources = {}
    before = {}
    for spec in inputs:
        sources[spec["id"]] = {
            "path": relative_path(spec["path"]),
            "kind": spec["kind"],
            "sha256": sha256(spec["path"]),
            "bytes": spec["path"].stat().st_size,
        }
        if spec["kind"] == "fixture":
            sources[spec["id"]]["oracle"] = {
                "path": relative_path(spec["oracle_path"]),
                "sha256": sha256(spec["oracle_path"]),
            }
        before[spec["id"]] = sources[spec["id"]]["sha256"]
    write_json(out / "source-integrity-before.json", sources)
    requests, correctness, performance, controls = {}, {}, {}, Counter()
    timings = []
    started = time.perf_counter()
    max_seconds = float(config.get("max_seconds", 900))
    for device in devices:
        if device == "cuda" and device_status["cuda"]["status"] != "available":
            continue
        for spec in inputs:
            if time.perf_counter() - started > max_seconds:
                raise BudgetExceeded("Benchmark wall-clock budget exhausted")
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
            print(f"correctness {spec['id']}/{device}: {result['status']}", flush=True)
    if "performance" in modes and config.get("performance", {}).get("enabled", True):
        performance = {}
        selected = set(config.get("performance", {}).get("inputs", []))
        for spec in inputs:
            if selected and spec["id"] not in selected:
                continue
            for device in devices:
                if device == "cuda" and device_status["cuda"]["status"] != "available":
                    continue
                for batch_size in config.get("performance", {}).get("batch_sizes", [1, 8, 32]):
                    if time.perf_counter() - started > max_seconds:
                        raise BudgetExceeded("Benchmark wall-clock budget exhausted")
                    try:
                        result = run_performance(spec, device, int(batch_size), config, timings)
                    except BudgetExceeded as exc:
                        result = {"status": "partial", "error": str(exc)}
                    except Exception as exc:
                        result = {"status": "unavailable", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
                    performance.setdefault(spec["id"], {}).setdefault(device, {})[str(batch_size)] = result
                    print(f"performance {spec['id']}/{device}/batch{batch_size}: {result.get('native', {}).get('median')}", flush=True)
    after = {spec["id"]: sha256(spec["path"]) for spec in inputs}
    unchanged = all(after[input_id] == before[input_id] for input_id in before)
    controls_summary = {"counts": {f"{a}|{b}|{c}|{d}": value for (a, b, c, d), value in controls.items()}}
    summary = {
        "schema_version": "boundary-gpu-benchmark-summary.v1",
        "measurement_time": environment["measurement_time"],
        "environment": environment,
        "device_status": device_status,
        "input_hashes": sources,
        "source_unchanged": unchanged,
        "requests": requests,
        "correctness": correctness,
        "controls": controls_summary,
        "performance": performance,
        "limitations": (
            "Fixture markers are synthetic ground truth; real RGB is compared with an independent sequential "
            "PyAV reference and a same-environment CPU TorchCodec reference. CUDA output observed in this "
            "environment is TV-range RGB, so raw and limited-to-full metrics are reported separately. "
            "This is decode-path evidence, not physical synchronization, training uplift, or a stock "
            "LeRobot GPU-reader claim."
        ),
    }
    summary["status"] = evaluate(summary, config, devices)
    write_json(out / "requests.json", requests)
    write_json(out / "controls-summary.json", controls_summary)
    write_json(out / "source-integrity.json", {"before": sources, "after": after, "unchanged": unchanged})
    write_json(out / "summary.json", summary)
    with (out / "timings.jsonl").open("w", encoding="utf-8") as stream:
        for item in timings:
            stream.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n")
    write_html(summary, out / "report.html")
    with zipfile.ZipFile(out / "evidence.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("summary.json", "requests.json", "timings.jsonl", "environment.json", "controls-summary.json", "report.html", "source-integrity-before.json", "source-integrity.json"):
            archive.write(out / name, name)
    print(json.dumps({"status": summary["status"], "out": relative_path(out)}, indent=2), flush=True)
    return 0 if summary["status"] in {"pass", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

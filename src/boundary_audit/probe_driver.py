"""Real-footage consumer, isolated from the auditor's Python environment."""

import contextlib
import hashlib
import importlib.metadata
import json
import os
import random
import shutil
import sys
import types
from pathlib import Path

if not __package__:
    owned_package = types.ModuleType("boundary_audit")
    owned_package.__path__ = [str(Path(__file__).resolve().parent)]
    sys.modules["boundary_audit"] = owned_package
from boundary_audit.row_contract import row_label_errors  # noqa: E402

HANDLES = []


class BudgetExceeded(ValueError):
    pass


def worker_setup(worker_id):
    directory = os.environ.get("BOUNDARY_AUDIT_FFMPEG_BIN")
    if directory and hasattr(os, "add_dll_directory"):
        HANDLES.append(os.add_dll_directory(directory))
    import torch

    torch.set_num_threads(1)


def projected_view(request):
    """Copy a bounded camera projection; never expose the source for writing."""
    source, view = Path(request["root"]), Path(request["cache"]) / "view"
    selected = []
    for directory in ("meta", "data"):
        selected.extend(p for p in (source / directory).rglob("*") if p.is_file())
    info = json.loads((source / "meta/info.json").read_text())
    for camera in request["cameras"]:
        # Include all shards needed by the projected feature, not unrelated cameras.
        selected.extend(p for p in (source / "videos" / camera).rglob("*") if p.is_file())
    size = sum(p.stat().st_size for p in selected)
    if size > request["max_view_bytes"]:
        raise BudgetExceeded(f"Projected input exceeds byte budget: {size}")
    for path in selected:
        destination = view / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    info["features"] = {k: v for k, v in info["features"].items() if v["dtype"] != "video" or k in request["cameras"]}
    (view / "meta/info.json").write_text(json.dumps(info), encoding="utf-8")
    return view, size


def reference_frames(request):
    import av

    result, decoded, stored_bytes = {}, 0, 0
    for relative, spec in request["videos"].items():
        path = (Path(request["root"]) / relative).resolve()
        if not path.is_relative_to(Path(request["root"]).resolve()):
            raise ValueError("Reference video escapes input")
        targets = set(spec["targets"].values())
        wanted = {n + delta for n in targets for delta in (-1, 0, 1) if n + delta >= 0}
        frames = {}
        with av.open(str(path)) as container:
            stream = container.streams.video[0]
            stream.codec_context.thread_count = 1
            for index, frame in enumerate(container.decode(stream)):
                decoded += 1
                if decoded > request["max_decode_frames"]:
                    raise BudgetExceeded("Sequential reference decode frame budget exhausted")
                if index in wanted:
                    pixels = frame.to_ndarray(format="rgb24")
                    stored_bytes += pixels.nbytes
                    if stored_bytes > request["max_reference_bytes"]:
                        raise BudgetExceeded("Reference image memory budget exhausted")
                    frames[index] = pixels
                if index >= max(wanted):
                    break
        if not targets <= frames.keys():
            raise ValueError("Sequential decode did not cover requested ordinal frames")
        result[relative] = frames
    return result, decoded, stored_bytes


def compare_pixels(actual, frames, expected):
    """Exact matches first; near matches require separation from both neighbours."""
    import numpy as np

    if actual.shape != frames[expected].shape:
        return {"status": "wrong_shape", "expected_sample": expected}
    candidates = [n for n in (expected - 1, expected, expected + 1) if n in frames]
    exact = [n for n in candidates if np.array_equal(actual, frames[n])]
    if exact and expected not in exact:
        return {
            "status": "wrong_frame",
            "match": "exact",
            "expected_sample": expected,
            "matched_samples": exact,
            "reason": "exact matches exclude expected frame",
            **({"matched_sample": exact[0]} if len(exact) == 1 else {}),
        }
    if len(exact) > 1:
        return {"status": "ambiguous", "reason": "identical neighbouring frames", "expected_sample": expected}
    if exact:
        return {
            "status": "pass" if exact[0] == expected else "wrong_frame",
            "match": "exact",
            "expected_sample": expected,
            "matched_sample": exact[0],
        }
    distances = {n: float(np.abs(actual.astype(np.float32) - frames[n].astype(np.float32)).mean()) for n in candidates}
    ranked = sorted(distances, key=distances.get)
    best = ranked[0]
    separated = len(ranked) == 1 or distances[ranked[1]] - distances[best] >= 0.25
    if distances[best] > 2.0 or not separated:
        return {
            "status": "ambiguous",
            "reason": "RGB differences or nonunique neighbouring match",
            "expected_sample": expected,
            "mean_absolute_rgb_errors": distances,
        }
    return {
        "status": "pass" if best == expected else "wrong_frame",
        "match": "bounded_rgb",
        "expected_sample": expected,
        "matched_sample": best,
        "mean_absolute_rgb_errors": distances,
    }


def compare_actions(actual, expected):
    """At-rest row shape and values are independent reader requirements."""
    import numpy as np

    if actual.shape != expected.shape:
        return [{"kind": "action_shape", "expected": list(expected.shape), "actual": list(actual.shape)}]
    if not np.isfinite(actual).all() or not np.allclose(actual, expected, rtol=0, atol=1e-6):
        return [{"kind": "action_window"}]
    return []


def run(request):
    import numpy as np
    import torch
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from torch.utils.data import DataLoader

    view, view_bytes = projected_view(request)
    references, decoded, reference_bytes = reference_frames(request)
    phase = request["phase"]
    window = phase != "single"
    cameras, offsets = request["cameras"], request["offsets"]
    dataset = LeRobotDataset(
        repo_id="boundary-audit/local-probe",
        root=view,
        episodes=request["episodes"],
        video_backend=request["backend"],
        return_uint8=True,
        download_videos=False,
        delta_timestamps={k: [d / request["fps"] for d in offsets] for k in cameras + ["action"]} if window else None,
    )
    # Build the subset mapping from full metadata ranges, not returned row labels.
    ranges = request["episode_ranges"]
    ids = list(ranges) if request["episodes"] is None else [str(e) for e in sorted(request["episodes"])]
    absolute_to_relative, relative_start = {}, 0
    for ep in ids:
        begin, end = ranges[ep]
        for query in request["queries"]:
            if begin <= query["index"] < end:
                absolute_to_relative[query["index"]] = relative_start + query["index"] - begin
        relative_start += end - begin
    order = list(range(len(request["queries"])))
    if phase == "random":
        random.Random(request["seed"]).shuffle(order)
        order += order[: min(3, len(order))]
    epochs = 2 if phase == "persistent" else 1
    records, row_errors, errors = [], [], []
    mapping = {}
    for relative, spec in request["videos"].items():
        for index, sample in spec["targets"].items():
            mapping[(spec["camera"], int(index))] = (relative, sample)

    def inspect(item, query):
        expected = request["rows"][str(query["index"])]
        labels = {key: item[key].item() for key in ("index", "episode_index", "frame_index")}
        row_errors.extend({"index": query["index"], **error} for error in row_label_errors(labels, expected))
        actions = np.array([request["rows"][str(i)]["action"] for i in query["indices"]])
        expected_actions = actions if window else actions[0]
        actual_actions = item["action"].cpu().numpy()
        row_errors.extend(
            {"index": query["index"], **error} for error in compare_actions(actual_actions, expected_actions)
        )
        for camera in cameras:
            frames = item[camera] if item[camera].ndim == 4 else item[camera].unsqueeze(0)
            if len(frames) != len(offsets):
                row_errors.append({"index": query["index"], "kind": "window_length", "camera": camera})
                continue
            for slot, index in enumerate(query["indices"]):
                relative, sample = mapping[(camera, index)]
                pixels = frames[slot].cpu().numpy().transpose(1, 2, 0)
                records.append(
                    {
                        "index": query["index"],
                        "camera": camera,
                        "delta": offsets[slot],
                        **compare_pixels(pixels, references[relative], sample),
                    }
                )
        if window:
            for key in cameras + ["action"]:
                if item[key + "_is_pad"].tolist() != query["padding"]:
                    row_errors.append({"index": query["index"], "kind": "padding_mask", "feature": key})

    checked = 0
    if phase in {"batch", "workers", "persistent"}:
        sampler = [absolute_to_relative[request["queries"][i]["index"]] for i in order]
        workers = 2 if phase in {"workers", "persistent"} else 0
        kwargs = {"batch_size": 4, "sampler": sampler, "num_workers": workers}
        if workers:
            kwargs.update(
                multiprocessing_context="spawn",
                worker_init_fn=worker_setup,
                timeout=60,
                persistent_workers=phase == "persistent",
            )
        loader = DataLoader(dataset, **kwargs)
        try:
            for epoch in range(epochs):
                cursor = 0
                for batch in loader:
                    for slot in range(len(batch["index"])):
                        inspect({key: value[slot] for key, value in batch.items()}, request["queries"][order[cursor]])
                        cursor += 1
                        checked += 1
        except Exception as exc:
            errors.append({"type": type(exc).__name__, "message": str(exc)[:1200]})
    else:
        for ordinal in order:
            query = request["queries"][ordinal]
            try:
                inspect(dataset[absolute_to_relative[query["index"]]], query)
                checked += 1
            except Exception as exc:
                errors.append({"index": query["index"], "type": type(exc).__name__, "message": str(exc)[:1200]})
    versions = {name: importlib.metadata.version(name) for name in ("lerobot", "torch", "av", "datasets")}
    versions["python"] = sys.version.split()[0]
    versions["platform"] = sys.platform
    try:
        versions["torchcodec"] = importlib.metadata.version("torchcodec")
    except importlib.metadata.PackageNotFoundError:
        versions["torchcodec"] = "not installed"
    import av
    import lerobot.datasets.dataset_reader as reader
    from lerobot.datasets import video_utils

    versions["ffmpeg_libraries"] = av.library_versions
    versions["torch_cuda_build"] = torch.version.cuda
    versions["device_used"] = "cpu"
    versions["official_reader_sha256"] = hashlib.sha256(Path(reader.__file__).read_bytes()).hexdigest()
    versions["official_video_utils_sha256"] = hashlib.sha256(Path(video_utils.__file__).read_bytes()).hexdigest()
    wrong = any(r["status"] in {"wrong_frame", "wrong_shape"} for r in records)
    partial = errors or any(r["status"] == "ambiguous" for r in records) or checked != len(order) * epochs
    return {
        "status": "fail" if wrong or row_errors else "partial" if partial else "pass",
        "backend": request["backend"],
        "phase": phase,
        "versions": versions,
        "requested_rows": len(order) * epochs,
        "checked_rows": checked,
        "frame_checks": len(records),
        "passed_frame_checks": sum(r["status"] == "pass" for r in records),
        "ambiguous_frame_checks": sum(r["status"] == "ambiguous" for r in records),
        "records": records,
        "row_errors": row_errors,
        "errors": errors,
        "reference": {
            "backend": "sequential-pyav",
            "decoded_frames": decoded,
            "image_bytes": reference_bytes,
            "projected_view_bytes": view_bytes,
            "projected_cameras": cameras,
            "shared_dependency": "FFmpeg; PyAV matches share PyAV RGB conversion",
            "approximate_rgb_rule": "uint8 MAE <= 2 and >= 0.25 separation; heuristic, not identity proof",
        },
    }


def main():
    request = json.load(sys.stdin)
    if request.get("ffmpeg_bin"):
        directory = request["ffmpeg_bin"]
        os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
        os.environ["BOUNDARY_AUDIT_FFMPEG_BIN"] = directory
    os.environ.update(
        HF_HUB_OFFLINE="1",
        HF_DATASETS_OFFLINE="1",
        HF_HOME=request["cache"],
        HF_DATASETS_CACHE=request["cache"] + "/datasets",
    )
    try:
        worker_setup(0)
        with contextlib.redirect_stdout(sys.stderr):
            result = run(request)
    except Exception as exc:
        result = {
            "status": "partial" if isinstance(exc, BudgetExceeded) else "unavailable",
            "checked_rows": 0,
            "errors": [{"type": type(exc).__name__, "message": str(exc)[:1200]}],
        }
    serialized = json.dumps(result, allow_nan=False)
    for path in (request["root"], request["cache"]):
        serialized = serialized.replace(path.replace("\\", "\\\\"), "<local>")
    print(serialized)


if __name__ == "__main__":
    main()

"""Full installed LeRobotDataset checks against a pre-encoding pixel oracle."""

import contextlib
import hashlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from boundary_audit.identity import decode_identity, validate_oracle

DLL_HANDLES = []


def worker_setup(worker_id):
    directory = os.environ.get("BOUNDARY_AUDIT_FFMPEG_BIN")
    if directory and hasattr(os, "add_dll_directory"):
        DLL_HANDLES.append(os.add_dll_directory(directory))
    import torch

    torch.set_num_threads(1)


def run(request):
    import torch
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from torch.utils.data import DataLoader

    torch.set_num_threads(1)
    root = Path(request["root"])
    oracle = json.loads((root / "frame_oracle.json").read_text(encoding="utf-8"))
    validate_oracle(oracle)
    phase = request["phase"]
    cameras = list(oracle["cameras"])
    window = phase in {"window", "batch", "workers"}
    offsets = [-1, 0, 1] if window else [0]
    deltas = {key: [delta / oracle["fps"] for delta in offsets] for key in cameras + ["action"]} if window else None
    subset = [e["episode_index"] for e in oracle["episodes"] if e["episode_index"] % 2] if phase == "subset" else None
    if phase == "subset" and not subset:
        raise ValueError("Subset mode requires at least two episodes")
    rows = oracle["rows"]
    indexes = [i for i, row in enumerate(rows) if subset is None or row["episode_index"] in subset]
    episodes = {e["episode_index"]: e for e in oracle["episodes"]}
    dataset = LeRobotDataset(
        repo_id="boundary-audit/local-fixture",
        root=root,
        video_backend=request["backend"],
        delta_timestamps=deltas,
        episodes=subset,
        return_uint8=True,
        download_videos=False,
    )
    if len(dataset) != len(indexes):
        raise ValueError("Loader row count differs from independent oracle")
    records, row_errors, errors = [], [], []

    def inspect(item, relative):
        index = indexes[relative]
        expected = rows[index]
        loaded_index = int(item["index"].item())
        if (
            loaded_index != index
            or int(item["episode_index"].item()) != expected["episode_index"]
            or int(item["frame_index"].item()) != expected["frame_index"]
        ):
            row_errors.append(
                {
                    "relative_index": relative,
                    "expected_index": index,
                    "actual_index": loaded_index,
                    "kind": "row_identity",
                }
            )
        episode = episodes[expected["episode_index"]]
        expected_indexes = [
            max(episode["start"], min(episode["start"] + episode["length"] - 1, index + d)) for d in offsets
        ]
        expected_padding = [not episode["start"] <= index + d < episode["start"] + episode["length"] for d in offsets]
        for camera in cameras:
            frames = item[camera] if window else item[camera].unsqueeze(0)
            if len(frames) != len(offsets):
                row_errors.append({"expected_index": index, "camera": camera, "kind": "window_length"})
                continue
            for slot, expected_index in enumerate(expected_indexes):
                target = rows[expected_index]["identities"][camera]
                record = {
                    "index": index,
                    "camera": camera,
                    "delta": offsets[slot],
                    "expected": target,
                    "expected_padding": expected_padding[slot],
                }
                try:
                    actual = decode_identity(frames[slot].cpu().numpy(), layout="CHW")
                    record.update({"actual": actual, "status": "pass" if actual == target else "wrong_frame"})
                except ValueError as exc:
                    record.update({"status": "unknown_identity", "message": str(exc)})
                records.append(record)
            if window and item[camera + "_is_pad"].tolist() != expected_padding:
                row_errors.append({"expected_index": index, "camera": camera, "kind": "padding_mask"})
        actual_actions = item["action"].reshape(-1).tolist()
        expected_actions = [rows[i]["action"] for i in expected_indexes]
        if actual_actions != expected_actions:
            row_errors.append(
                {
                    "expected_index": index,
                    "kind": "action_window",
                    "expected": expected_actions,
                    "actual": actual_actions,
                }
            )
        if window and item["action_is_pad"].tolist() != expected_padding:
            row_errors.append({"expected_index": index, "kind": "action_padding_mask"})

    checked_rows = 0
    if phase in {"batch", "workers"}:
        kwargs = {"batch_size": 4, "shuffle": False, "num_workers": 2 if phase == "workers" else 0}
        if phase == "workers":
            kwargs.update({"multiprocessing_context": "spawn", "worker_init_fn": worker_setup, "timeout": 60})
        try:
            for batch in DataLoader(dataset, **kwargs):
                for i in range(len(batch["index"])):
                    item = {key: value[i] for key, value in batch.items()}
                    inspect(item, checked_rows)
                    checked_rows += 1
        except Exception as exc:
            errors.append({"index": checked_rows, "type": type(exc).__name__, "message": str(exc)[:1200]})
    else:
        for relative in range(len(indexes)):
            try:
                inspect(dataset[relative], relative)
                checked_rows += 1
            except Exception as exc:
                errors.append({"index": indexes[relative], "type": type(exc).__name__, "message": str(exc)[:1200]})
    versions = {name: importlib.metadata.version(name) for name in ["lerobot", "torch", "av", "datasets"]}
    try:
        versions["torchcodec"] = importlib.metadata.version("torchcodec")
    except importlib.metadata.PackageNotFoundError:
        versions["torchcodec"] = "not installed"
    versions["python"] = sys.version.split()[0]
    import lerobot.datasets.dataset_reader as reader

    versions["official_dataset_reader_sha256"] = hashlib.sha256(Path(reader.__file__).read_bytes()).hexdigest()
    passed = sum(r["status"] == "pass" for r in records)
    return {
        "schema_version": "boundary-loader-check.v1",
        "status": "pass"
        if not errors and not row_errors and passed == len(records) and checked_rows == len(indexes)
        else "fail",
        "scope": "Full official LeRobotDataset against synthetic pre-encoding pixel/action oracle; no physical synchronization claim",
        "backend": request["backend"],
        "phase": phase,
        "versions": versions,
        "requested_rows": len(indexes),
        "checked_rows": checked_rows,
        "frame_checks": len(records),
        "passed_frame_checks": passed,
        "records": records,
        "row_errors": row_errors,
        "errors": errors,
        "expected_padding_checks": len(indexes) * (len(cameras) + 1) if window else 0,
    }


def main():
    request = json.load(sys.stdin)
    root = str(Path(request["root"]).resolve())
    if request.get("ffmpeg_bin"):
        directory = request["ffmpeg_bin"]
        os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
        os.environ["BOUNDARY_AUDIT_FFMPEG_BIN"] = directory
    for key in ["HF_HUB_OFFLINE", "HF_DATASETS_OFFLINE"]:
        os.environ[key] = "1"
    os.environ["HF_HOME"] = request["cache"]
    os.environ["HF_DATASETS_CACHE"] = request["cache"] + "/datasets"
    worker_setup(0)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = run(request)
    except Exception as exc:
        result = {
            "status": "unavailable",
            "backend": request["backend"],
            "phase": request["phase"],
            "checked_rows": 0,
            "errors": [{"type": type(exc).__name__, "message": str(exc).replace(root, "<dataset>")[:2000]}],
        }
    # Exception strings from third-party loaders can contain local paths.
    serialized = json.dumps(result, allow_nan=False).replace(root.replace("\\", "\\\\"), "<dataset>")
    print(serialized)


if __name__ == "__main__":
    main()

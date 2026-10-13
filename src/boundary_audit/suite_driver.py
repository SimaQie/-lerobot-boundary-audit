"""Run the installed official producer/merge pipeline in a separate interpreter."""

import contextlib
import importlib.metadata
import json
import os
import shutil
import sys
import types
from pathlib import Path

# Expose only our modules, not our environment's entire site-packages directory.
owned_package = types.ModuleType("boundary_audit")
owned_package.__path__ = [str(Path(__file__).resolve().parent)]
sys.modules["boundary_audit"] = owned_package
from boundary_audit.identity import HEIGHT, WIDTH, render_frame  # noqa: E402
from boundary_audit.storage import write_json  # noqa: E402

HANDLES = []


def configure(request):
    directory = request.get("ffmpeg_bin")
    if directory:
        os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            HANDLES.append(os.add_dll_directory(directory))
    for name in ["HF_HUB_OFFLINE", "HF_DATASETS_OFFLINE"]:
        os.environ[name] = "1"
    os.environ["HF_HOME"] = request["cache"]
    os.environ["HF_DATASETS_CACHE"] = os.environ["HF_HOME"] + "/datasets"


def generate(request):
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq
    from lerobot.configs import RGBEncoderConfig
    from lerobot.datasets.dataset_tools import merge_datasets
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    root = Path(request["out"])
    root.mkdir()
    cameras = {"observation.images.left": 0, "observation.images.right": 1}
    features = {
        name: {"dtype": "video", "shape": (HEIGHT, WIDTH, 3), "names": ["height", "width", "channels"]}
        for name in cameras
    }
    features["action"] = {"dtype": "float32", "shape": (1,), "names": ["synthetic_identity"]}
    features["observation.state"] = {"dtype": "float32", "shape": (1,), "names": ["synthetic_counter"]}
    cases = []

    def create(name, lengths, marker_base):
        dataset = LeRobotDataset.create(
            repo_id="boundary-audit/" + name,
            root=root / name,
            fps=30,
            features=features,
            robot_type="synthetic-marker",
            video_backend="pyav",
            rgb_encoder=RGBEncoderConfig(vcodec="h264", pix_fmt="yuv420p", g=12, crf=20, extra_options={"bf": "2"}),
            encoder_threads=1,
        )
        rows, episodes = [], []
        for episode, length in enumerate(lengths):
            marker_episode = marker_base + episode
            episodes.append({"episode_index": episode, "start": len(rows), "length": length})
            for frame in range(length):
                action = float(marker_episode * 4096 + frame)
                identity = {
                    cam: {"camera": cam_id, "episode": marker_episode, "frame": frame}
                    for cam, cam_id in cameras.items()
                }
                rows.append({"episode_index": episode, "frame_index": frame, "identities": identity, "action": action})
                dataset.add_frame(
                    {
                        **{cam: render_frame(cam_id, marker_episode, frame) for cam, cam_id in cameras.items()},
                        "action": np.array([action], dtype=np.float32),
                        "observation.state": np.array([frame], dtype=np.float32),
                        "task": "read the synthetic frame identity",
                    }
                )
            dataset.save_episode(parallel_encoding=False)
        dataset.finalize()
        oracle = {
            "schema_version": "boundary-frame-oracle.v1",
            "fps": 30,
            "cameras": cameras,
            "episodes": episodes,
            "rows": rows,
            "ground_truth": "marker identities specified BEFORE official encoding",
        }
        write_json(root / name / "frame_oracle.json", oracle)
        cases.append(
            {
                "name": name,
                "path": name,
                "expected": "pass",
                "origin": "official LeRobot create/add_frame/save_episode/finalize",
            }
        )
        return dataset, oracle

    source_a, oracle_a = create("recorded-a", [7, 9, 5], 0)
    source_b, oracle_b = create("recorded-b", [8, 6], 100)
    merged = merge_datasets([source_a, source_b], "boundary-audit/merged", output_dir=root / "merged")
    merged_rows = oracle_a["rows"] + [
        {**row, "episode_index": row["episode_index"] + len(oracle_a["episodes"])} for row in oracle_b["rows"]
    ]
    merged_episodes = oracle_a["episodes"] + [
        {
            **ep,
            "episode_index": ep["episode_index"] + len(oracle_a["episodes"]),
            "start": ep["start"] + len(oracle_a["rows"]),
        }
        for ep in oracle_b["episodes"]
    ]
    merged_oracle = {**oracle_a, "rows": merged_rows, "episodes": merged_episodes}
    write_json(merged.root / "frame_oracle.json", merged_oracle)
    cases.append(
        {
            "name": "merged",
            "path": "merged",
            "expected": "pass",
            "origin": "official merge_datasets with video/data concatenation",
        }
    )
    faulty = root / "offset-one-frame"
    shutil.copytree(merged.root, faulty)
    for path in (faulty / "meta/episodes").glob("chunk-*/file-*.parquet"):
        table = pq.read_table(path)
        values = table.to_pylist()
        for row in values:
            if row["episode_index"] == 1:
                for suffix in ["from_timestamp", "to_timestamp"]:
                    row[f"videos/observation.images.left/{suffix}"] += 1 / 30
        pq.write_table(pa.Table.from_pylist(values, schema=table.schema), path)
    cases.append(
        {
            "name": faulty.name,
            "path": faulty.name,
            "expected": "fail",
            "origin": "controlled metadata injection",
            "fault": "one camera, episode 1 shifted by one frame",
        }
    )
    swapped = root / "camera-swap"
    shutil.copytree(merged.root, swapped)
    left = sorted((swapped / "videos/observation.images.left").rglob("*.mp4"))
    right = sorted((swapped / "videos/observation.images.right").rglob("*.mp4"))
    for a, b in zip(left, right, strict=True):
        tmp = a.with_suffix(".swap")
        a.rename(tmp)
        shutil.move(str(b), a)
        shutil.move(str(tmp), b)
    cases.append(
        {
            "name": swapped.name,
            "path": swapped.name,
            "expected": "fail",
            "origin": "controlled payload injection",
            "fault": "camera payloads swapped; timestamps stay valid",
        }
    )
    manifest = {
        "schema_version": "boundary-conformance-suite.v1",
        "synthetic_only": True,
        "producer": {
            "lerobot": importlib.metadata.version("lerobot"),
            "av": importlib.metadata.version("av"),
            "python": sys.version.split()[0],
        },
        "cases": cases,
        "natural_defects_found": False,
    }
    write_json(root / "suite.json", manifest)
    return manifest


def main():
    request = json.load(sys.stdin)
    configure(request)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = generate(request)
        print(json.dumps({"status": "generated", "suite": result}))
    except Exception as exc:
        import traceback

        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"status": "error", "error_type": type(exc).__name__, "message": str(exc)[:2000]}))


if __name__ == "__main__":
    main()

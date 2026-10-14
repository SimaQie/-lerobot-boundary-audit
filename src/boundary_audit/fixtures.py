"""Small derived controls. Original pre-encoding identities remain unchanged."""

import json
import shutil
from fractions import Fraction
from pathlib import Path

from .storage import write_json


def extend_suite(root):
    import av
    import pyarrow as pa
    import pyarrow.parquet as pq

    root = Path(root)
    manifest = json.loads((root / "suite.json").read_text())
    if any(c["name"] == "global-index-shift" for c in manifest["cases"]):
        return
    source = root / "merged"
    oracle = json.loads((source / "frame_oracle.json").read_text())
    target = oracle["episodes"][1]["start"]

    def clone(name, expected="fail", evidence="pixel", fault=None):
        output = root / name
        shutil.copytree(source, output)
        manifest["cases"].append(
            {
                "name": name,
                "path": name,
                "expected": expected,
                "required_evidence": evidence,
                "origin": "derived original marker control",
                "fault": fault,
            }
        )
        return output

    def change_rows(output, edit):
        for path in sorted((output / "data").glob("chunk-*/file-*.parquet")):
            table = pq.read_table(path)
            rows = table.to_pylist()
            edit(rows)
            pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)

    shifted = clone("global-index-shift", evidence="row", fault="all global indices shifted by one")
    change_rows(shifted, lambda rows: [row.update(index=row["index"] + 1) for row in rows])
    duplicate = clone("duplicate-global-index", evidence="row", fault="duplicate index inside episode 1")
    change_rows(duplicate, lambda rows: [row.update(index=target) for row in rows if row["index"] == target + 1])
    action = clone("action-window-corrupt", evidence="row", fault="action at episode 1 start replaced")
    change_rows(
        action,
        lambda rows: [
            row.update(action=[-1.0] if isinstance(row["action"], list) else -1.0)
            for row in rows
            if row["index"] == target
        ],
    )

    sharded = clone("multi-data-shard", expected="pass", fault=None)
    paths = sorted((sharded / "data").glob("chunk-*/file-*.parquet"))
    table = pa.concat_tables([pq.read_table(p) for p in paths])
    for path in paths:
        path.unlink()
    for ep in oracle["episodes"]:
        path = sharded / f"data/chunk-000/file-{ep['episode_index']:03d}.parquet"
        pq.write_table(table.slice(ep["start"], ep["length"]), path)
    for path in sorted((sharded / "meta/episodes").glob("chunk-*/file-*.parquet")):
        metadata = pq.read_table(path)
        rows = metadata.to_pylist()
        for row in rows:
            row["data/chunk_index"] = 0
            row["data/file_index"] = row["episode_index"]
        pq.write_table(pa.Table.from_pylist(rows, schema=metadata.schema), path)

    def reencode(output, edit, bframes):
        for path in sorted((output / "videos").rglob("*.mp4")):
            with av.open(str(path)) as container:
                images = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
            edit(images)
            temporary = path.with_suffix(".encoded.mp4")
            with av.open(str(temporary), "w") as container:
                stream = container.add_stream("libx264", rate=30)
                stream.height, stream.width = images[0].shape[:2]
                stream.pix_fmt = "yuv420p"
                stream.options = {"bf": str(bframes), "g": "12", "crf": "18"}
                for index, image in enumerate(images):
                    frame = av.VideoFrame.from_ndarray(image, format="rgb24")
                    frame.pts, frame.time_base = index, Fraction(1, 30)
                    for packet in stream.encode(frame):
                        container.mux(packet)
                for packet in stream.encode(None):
                    container.mux(packet)
            temporary.replace(path)

    duplicate_frame = clone("duplicate-pixel-frame", fault="frame 1 of episode 1 repeats frame 0, PTS stays valid")
    reencode(duplicate_frame, lambda images: images.__setitem__(target + 1, images[target].copy()), 2)
    permutation = clone("pixel-order-swap", fault="frames 1 and 2 of episode 1 exchanged, PTS stays valid")

    def swap(images):
        images[target + 1], images[target + 2] = images[target + 2], images[target + 1]

    reencode(permutation, swap, 2)
    clean = clone("no-b-frames", expected="pass", fault=None)
    reencode(clean, lambda images: None, 0)
    manifest["extension"] = {
        "version": "0.4.0",
        "av": av.__version__,
        "ffmpeg_libraries": av.library_versions,
        "note": "Derived controls, not additional natural upstream defects",
    }
    write_json(root / "suite.json", manifest)


def export_demo(output):
    """Extract package-owned fixtures to a new, exclusively reserved directory."""
    import tempfile
    import zipfile
    from importlib.resources import files

    from .storage import publish_new_directory

    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Use a new demo directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    resource = files("boundary_audit").joinpath("resources/frame-suite-v040.zip")
    with tempfile.TemporaryDirectory(prefix=".boundary-demo-", dir=output.parent) as temporary:
        stage = Path(temporary) / "suite"
        with resource.open("rb") as stream, zipfile.ZipFile(stream) as archive:
            for name in archive.namelist():
                if not (stage / name).resolve().is_relative_to(stage.resolve()):
                    raise ValueError("Bundled fixture path escapes output")
            archive.extractall(stage)
        publish_new_directory(stage, output)
    return {
        "status": "pass",
        "synthetic_only": True,
        "cases": len(json.loads((output / "suite.json").read_text())["cases"]),
    }

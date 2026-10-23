"""Small revision-pinned public Hub samples, with explicit camera/download budgets."""

import hashlib
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

from .storage import write_json

SAMPLES = {
    "aloha_screw_driver": {
        "repo": "lerobot/aloha_static_screw_driver",
        "revision": "21eead16760a8d94d449cadf4bc438b322ab528d",
        "cameras": ["observation.images.cam_left_wrist", "observation.images.cam_right_wrist"],
        "license": "mit",
        "max_bytes": 280_000_000,
        "upstream_url": "https://tonyzhaozh.github.io/aloha/",
        "note": "Real ALOHA bimanual screw-driver task, 50 episodes at 50 FPS; two of four cameras selected. Original research is RSS 2023, not a newly collected dataset.",
    },
    "agibot2026": {
        "repo": "Voxel51/AgiBotWorld2026-sample-10ep",
        "revision": "caa5bf1b0b5be48ed52d158ff0d66af40b0f9258",
        "cameras": ["observation.images.hand_left", "observation.images.hand_right"],
        "license": "cc-by-nc-sa-4.0",
        "max_bytes": 230_000_000,
        "created_at": "2026-09-14T21:09:01.000Z",
        "upstream_repo": "agibot-world/AgiBotWorld2026",
        "note": "September 2026 public subset, 10 real G2 episodes; two of seven camera streams selected",
    },
    "cmu_stretch": {
        "repo": "lerobot/cmu_stretch",
        "revision": "d84574233973ea9a292babd008256d2290a3f96e",
        "cameras": ["observation.images.image"],
        "license": "mit",
        "max_bytes": 60_000_000,
        "upstream_url": "https://robo-affordances.github.io/",
        "note": "Real Stretch mobile-manipulator episodes, 135 episodes at 5 FPS, single camera, chunked video layout. Adds a wheeled mobile platform and a low frame rate to the audited sources.",
    },
    "utokyo_xarm": {
        "repo": "lerobot/utokyo_xarm_pick_and_place",
        "revision": "da56c23e1b6d32c101c300b85dc54288b53ea63c",
        "cameras": ["observation.images.hand_image", "observation.images.image"],
        "license": "apache-2.0",
        "max_bytes": 50_000_000,
        "note": "Real xArm pick-and-place recordings, 102 episodes at 10 FPS, sharded data/video layout; two of three cameras selected. Adds a single 6-DOF arm platform.",
    },
    "pusht": {
        "repo": "lerobot/pusht",
        "revision": "7628202a2180972f291ba1bc6723834921e72c19",
        "cameras": ["observation.image"],
        "license": "mit",
        "max_bytes": 12_000_000,
        "note": "Legacy simulated negative control; not a recent real-robot dataset",
    },
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_sample(name, destination, *, max_bytes=None):
    if name not in SAMPLES:
        raise ValueError(f"Unknown sample: {name}")
    spec = SAMPLES[name]
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=True)
    url = f"https://huggingface.co/api/datasets/{spec['repo']}/tree/{spec['revision']}?recursive=true"
    entries = []
    while url:
        with urllib.request.urlopen(url, timeout=30) as response:
            entries.extend(json.load(response))
            # API returns pagination through an RFC 5988 Link header.
            link = response.headers.get("Link", "")
        following = [part.split(">")[0].strip().lstrip("<") for part in link.split(",") if 'rel="next"' in part]
        url = following[0] if following else None
        if url and not url.startswith("https://huggingface.co/api/"):
            raise ValueError("Unexpected pagination URL")
    prefixes = [f"videos/{camera}/" for camera in spec["cameras"]]
    entries = [
        e
        for e in entries
        if e["type"] == "file"
        and (
            e["path"] in {"README.md", "LICENSE"}
            or e["path"].startswith(("meta/", "data/"))
            or any(e["path"].startswith(prefix) for prefix in prefixes)
        )
    ]
    budget = spec["max_bytes"] if max_bytes is None else max_bytes
    total = sum(e["size"] for e in entries)
    if not entries or total > budget:
        raise ValueError(f"Selected sample needs {total} bytes, budget is {budget}")
    print(f"Selected {len(entries)} files, {total:,} bytes; source revision {spec['revision']}", flush=True)

    def get_file(entry):
        relative = PurePosixPath(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid remote path")
        path = root.joinpath(*relative.parts)
        if not path.resolve().is_relative_to(root):
            raise ValueError("Sample path escapes destination")
        path.parent.mkdir(parents=True, exist_ok=True)
        expected_hash = entry.get("lfs", {}).get("oid")
        if path.exists():
            if path.stat().st_size != entry["size"] or (expected_hash and sha256(path) != expected_hash):
                raise ValueError(f"Existing file does not match pinned source: {relative}")
        else:
            partial = path.with_suffix(path.suffix + ".part")
            downloaded = 0
            request = f"https://huggingface.co/datasets/{spec['repo']}/resolve/{spec['revision']}/{urllib.parse.quote(entry['path'], safe='/')}"
            try:
                with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as out:
                    for chunk in iter(lambda: response.read(1024 * 1024), b""):
                        downloaded += len(chunk)
                        if downloaded > entry["size"]:
                            raise ValueError("Download exceeds declared file size")
                        out.write(chunk)
                if downloaded != entry["size"] or (expected_hash and sha256(partial) != expected_hash):
                    raise ValueError("Downloaded file fingerprint mismatch")
                partial.replace(path)
            finally:
                if partial.exists():
                    partial.unlink()
        record = {"path": relative.as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}
        print(f"Available: {relative.as_posix()}", flush=True)
        return record

    with ThreadPoolExecutor(max_workers=3) as pool:
        files = list(pool.map(get_file, entries))
    manifest = {
        "repository": spec["repo"],
        "revision": spec["revision"],
        "license": spec["license"],
        "selected_cameras": spec["cameras"],
        "note": spec["note"],
        "files": files,
        "total_bytes": total,
        "download_budget_bytes": budget,
        "source_url": f"https://huggingface.co/datasets/{spec['repo']}/tree/{spec['revision']}",
    }
    for key in ["created_at", "upstream_repo", "upstream_url"]:
        if key in spec:
            manifest[key] = spec[key]
    write_json(root / "source_manifest.json", manifest)
    return manifest

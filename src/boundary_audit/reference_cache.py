"""Content-addressed reference-frame cache for repeated real-footage probes.

The cache stores only decoded RGB arrays for the exact ordinals a probe needs.
Keys include the source digest, requested ordinals, FPS and the probe tool
identity, so a changed video can never reuse stale pixels. A missing or
corrupt entry is a cache miss, never a probe failure.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
import zlib
from pathlib import Path

SCHEMA = "boundary-reference-cache.v2"


def default_root():
    base = os.environ.get("LEROBOT_BOUNDARY_AUDIT_CACHE")
    if base:
        return Path(base) / "reference"
    cache_home = os.environ.get("XDG_CACHE_HOME")
    if cache_home:
        return Path(cache_home) / "lerobot-boundary-audit/reference"
    return Path.home() / ".cache/lerobot-boundary-audit/reference"


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_key(*, source_sha256, relative, targets, fps, tool_identity):
    payload = {
        "schema": SCHEMA,
        "source_sha256": source_sha256,
        "relative": relative,
        "targets": sorted(int(value) for value in targets),
        "fps": str(fps),
        "tool_identity": tool_identity,
        "decoder": "pyav-ordinal-rgb24",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def cache_path(root, key):
    return Path(root) / key[:2] / (key + ".npz")


def load(path, key, required, *, max_bytes=268435456, max_file_bytes=268435456):
    import numpy as np

    try:
        if Path(path).stat().st_size > max_file_bytes:
            return None, "file_budget"
        with zipfile.ZipFile(path) as archive:
            # Reject oversize compressed payloads before NumPy materializes arrays.
            entries = archive.infolist()
            if sum(entry.file_size for entry in entries) > max_bytes + 512 * len(entries) + 65536:
                return None, "memory_budget"
        with np.load(path, allow_pickle=False) as payload:
            metadata = json.loads(str(payload["metadata"]))
            if metadata.get("schema") != SCHEMA or metadata.get("key") != key:
                return None, "metadata_mismatch"
            frames = {}
            memory_bytes = 0
            for value in metadata.get("targets", []):
                name = f"frame_{int(value)}"
                if name not in payload:
                    return None, "missing_frame"
                array = payload[name]
                if array.dtype != np.uint8 or array.ndim != 3 or array.shape[2] != 3:
                    return None, "invalid_frame"
                memory_bytes += array.nbytes
                if memory_bytes > max_bytes:
                    return None, "memory_budget"
                if hashlib.sha256(array.tobytes()).hexdigest() != metadata.get("frame_hashes", {}).get(name):
                    return None, "frame_digest_mismatch"
                frames[int(value)] = array
            if not set(required) <= frames.keys():
                return None, "missing_required_frame"
            return frames, None
    except (OSError, ValueError, KeyError, TypeError, EOFError, zipfile.BadZipFile, zlib.error):
        return None, "unreadable"


def save(root, key, targets, frames, *, source_sha256, relative, max_bytes):
    import numpy as np

    destination = cache_path(root, key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema": SCHEMA,
        "key": key,
        "source_sha256": source_sha256,
        "relative": relative,
        "targets": sorted(int(value) for value in targets),
        "frame_hashes": {f"frame_{int(value)}": hashlib.sha256(frames[int(value)].tobytes()).hexdigest()
                         for value in targets},
    }
    fd, temporary = tempfile.mkstemp(prefix="." + destination.name, suffix=".tmp", dir=destination.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            np.savez_compressed(
                stream,
                metadata=np.array(json.dumps(metadata, sort_keys=True)),
                **{f"frame_{int(value)}": frames[int(value)] for value in targets},
            )
        size = temporary.stat().st_size
        if size > max_bytes:
            os.unlink(temporary)
            return {"status": "too_large", "bytes": size}
        os.replace(temporary, destination)
        return {"status": "written", "bytes": size}
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def remove(path):
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass

"""Bounded real-footage full-loader probes against an ordinal decode reference."""

import json
import random
import subprocess
import tempfile
import time
from pathlib import Path

from .audit import audit_dataset
from .conformance import invoke
from .probe_evidence import summarize_probe
from .repair import fingerprint


def prepare_probe(root, *, cameras, episodes=None, max_rows=12, radius=1, seed=20261014, sampling="mixed"):
    import pyarrow.parquet as pq

    if type(max_rows) is not int or type(radius) is not int or not 1 <= max_rows <= 1000 or not 0 <= radius <= 32:
        raise ValueError("Probe needs 1..1000 rows and window radius 0..32")
    if sampling not in {"mixed", "stratified"}:
        raise ValueError("Sampling must be mixed or stratified")
    root = Path(root).resolve()
    info = json.loads((root / "meta/info.json").read_text())
    metadata = []
    for path in sorted((root / "meta/episodes").glob("chunk-*/file-*.parquet")):
        pf = pq.ParquetFile(path)
        columns = [c for c in pf.schema_arrow.names if not c.startswith("stats/")]
        for batch in pf.iter_batches(columns=columns, batch_size=1024):
            metadata.extend(batch.to_pylist())
    metadata.sort(key=lambda row: row["episode_index"])
    selected = metadata if episodes is None else [e for e in metadata if e["episode_index"] in episodes]
    if not selected or (episodes is not None and set(episodes) - {e["episode_index"] for e in selected}):
        raise ValueError("Select existing, nonempty episodes")
    rng = random.Random(seed)
    count = min(len(selected), max(1, (max_rows + 3) // 4)) if episodes is None else min(len(selected), max_rows)
    sampled = (
        [selected[round(i * (len(selected) - 1) / (count - 1))] for i in range(count)] if count > 1 else [selected[0]]
    )
    candidates = []
    for slot in range(4):
        for ep in sampled:
            local = (
                0
                if slot == 0
                else min(1, ep["length"] - 1)
                if slot == 1
                else ep["length"] - 1
                if slot == 2
                else rng.randrange(ep["length"])
            )
            index = ep["dataset_from_index"] + local
            if index not in candidates:
                candidates.append(index)
    # Fill remaining budget with reproducible interior samples from the same episodes.
    target_count = min(max_rows, sum(e["length"] for e in sampled))
    seen = set(candidates)
    for attempt in range(max_rows * 10):
        if len(candidates) >= target_count:
            break
        ep = rng.choice(sampled)
        index = ep["dataset_from_index"] + rng.randrange(ep["length"])
        if index not in seen:
            seen.add(index)
            candidates.append(index)
    queries = list(dict.fromkeys(candidates))[:max_rows]
    if sampling == "stratified":
        # Time strata are chosen before decoding: never select frames by their
        # apparent match quality or discard ambiguous observations afterwards.
        groups = []
        for ordinal, ep in enumerate(sampled):
            slots = min(ep["length"], max_rows // len(sampled) + (ordinal < max_rows % len(sampled)))
            groups.append(
                [
                    ep["dataset_from_index"]
                    + rng.randrange(slot * ep["length"] // slots, (slot + 1) * ep["length"] // slots)
                    for slot in range(slots)
                ]
            )
        queries = [group[slot] for slot in range(max(map(len, groups))) for group in groups if slot < len(group)]
    offsets = list(range(-radius, radius + 1))
    ranges = {e["episode_index"]: e for e in metadata}
    required = set()
    windows = []
    for index in queries:
        ep = next(e for e in selected if e["dataset_from_index"] <= index < e["dataset_to_index"])
        indices = [max(ep["dataset_from_index"], min(ep["dataset_to_index"] - 1, index + delta)) for delta in offsets]
        padding = [not ep["dataset_from_index"] <= index + delta < ep["dataset_to_index"] for delta in offsets]
        required.update(indices)
        windows.append({"index": index, "episode_index": ep["episode_index"], "indices": indices, "padding": padding})
    rows, position = {}, 0
    for path in sorted((root / "data").glob("chunk-*/file-*.parquet")):
        for batch in pq.ParquetFile(path).iter_batches(
            columns=["index", "episode_index", "frame_index", "action"], batch_size=4096
        ):
            for row in batch.to_pylist():
                if position in required:
                    rows[str(position)] = row
                position += 1
    if len(rows) != len(required):
        raise ValueError("Requested reference rows are incomplete")
    # Derive ordinal positions from full ordered episode lengths, not stored offsets.
    cursors, videos = {}, {}
    for ep in metadata:
        for camera in cameras:
            prefix = f"videos/{camera}"
            relative = info["video_path"].format(
                video_key=camera, chunk_index=ep[prefix + "/chunk_index"], file_index=ep[prefix + "/file_index"]
            )
            cursor = cursors.get(relative, 0)
            if ep in selected:
                for global_index in required:
                    if ep["dataset_from_index"] <= global_index < ep["dataset_to_index"]:
                        sample = cursor + global_index - ep["dataset_from_index"]
                        videos.setdefault(relative, {"camera": camera, "targets": {}})["targets"][str(global_index)] = (
                            sample
                        )
            cursors[relative] = cursor + ep["length"]
    return {
        "root": str(root),
        "cameras": cameras,
        "episodes": episodes,
        "fps": info["fps"],
        "offsets": offsets,
        "queries": windows,
        "rows": rows,
        "videos": videos,
        "seed": seed,
        "sampling": sampling,
        "episode_ranges": {str(k): [e["dataset_from_index"], e["dataset_to_index"]] for k, e in ranges.items()},
    }


def probe_loader(
    root,
    python,
    *,
    cameras=None,
    episodes=None,
    backend="pyav",
    phase="window",
    max_rows=12,
    radius=1,
    seed=20261014,
    sampling="mixed",
    max_decode_frames=50000,
    max_reference_bytes=268435456,
    max_view_bytes=314572800,
    visuals=False,
    visual_queries=4,
    visual_max_bytes=20_000_000,
    visual_output=None,
    allow_audit_failure=False,
    ffmpeg_bin=None,
    timeout=300,
):
    if backend not in {"pyav", "torchcodec"} or phase not in {
        "single",
        "window",
        "batch",
        "workers",
        "random",
        "persistent",
    }:
        raise ValueError("Unsupported probe backend or phase")
    if any(type(n) is not int or n <= 0 for n in (max_decode_frames, max_reference_bytes, max_view_bytes, timeout)):
        raise ValueError("Probe budgets must be positive integers")
    if type(visual_queries) is not int or visual_queries < 1 or type(visual_max_bytes) is not int or visual_max_bytes < 1:
        raise ValueError("Visual budgets must be positive integers")
    root = Path(root).resolve()
    if visuals and visual_output is None:
        raise ValueError("Visual output is required when visuals are enabled")
    if visuals:
        visual_output = Path(visual_output).resolve()
        if visual_output.is_relative_to(root):
            raise ValueError("Visual output must be outside the source dataset")
    start = time.perf_counter()
    before = fingerprint(root)
    audit = audit_dataset(root, cameras=cameras)
    if audit["status"] != "pass" and not allow_audit_failure:
        return {
            "schema_version": "boundary-real-probe.v1",
            "backend": backend,
            "phase": phase,
            "status": "fail" if audit["status"] == "fail" else "partial",
            "source_unchanged": fingerprint(root) == before,
            "preflight": audit,
            "requested_rows": 0,
            "checked_rows": 0,
            "note": "Storage prerequisites did not pass; full loader probe was not run",
        }
    checked_cameras = cameras or audit.get("selection", {}).get("checked_cameras")
    if not checked_cameras:
        raise ValueError("No checked cameras are available for the probe")
    request = prepare_probe(
        root,
        cameras=checked_cameras,
        episodes=episodes,
        max_rows=max_rows,
        radius=0 if phase == "single" else radius,
        seed=seed,
        sampling=sampling,
    )
    request.update(
        backend=backend,
        phase=phase,
        max_decode_frames=max_decode_frames,
        max_reference_bytes=max_reference_bytes,
        max_view_bytes=max_view_bytes,
        ffmpeg_bin=str(Path(ffmpeg_bin).resolve()) if ffmpeg_bin else None,
        visuals={
            "enabled": bool(visuals),
            "output": str(visual_output) if visuals else None,
            "relative_prefix": "visuals",
            "max_queries": visual_queries,
            "max_bytes": visual_max_bytes,
        },
    )
    with tempfile.TemporaryDirectory(prefix="boundary-probe-") as cache:
        request["cache"] = cache
        try:
            report = invoke("probe_driver.py", python, request, timeout=timeout)
        except (ValueError, OSError, TimeoutError) as exc:
            report = {
                "status": "unavailable",
                "checked_rows": 0,
                "errors": [{"type": type(exc).__name__, "message": str(exc)[:1200]}],
            }
        except subprocess.TimeoutExpired as exc:
            report = {
                "status": "partial",
                "checked_rows": 0,
                "errors": [{"type": "TimeoutExpired", "message": str(exc)[:1200]}],
            }
    visual_evidence = report.pop("visual_evidence", None)
    report = summarize_probe(report, request)
    report.update(
        backend=backend,
        phase=phase,
        schema_version="boundary-real-probe.v1",
        source_unchanged=fingerprint(root) == before,
        cameras=request["cameras"],
        episodes=episodes,
        seed=seed,
        sampling=sampling,
        offsets=request["offsets"],
        scope="Relative to sequential PyAV ordinal reference; no pre-encoding identity or physical synchronization claim",
        preflight_status=audit["status"],
        elapsed_seconds=time.perf_counter() - start,
    )
    if visuals:
        report["visual_evidence"] = visual_evidence or {
            "status": "unavailable",
            "reason": "Consumer returned no loader pixel evidence",
        }
        if visual_evidence and visual_evidence.get("status") == "partial":
            report["visual_evidence_note"] = "Preview evidence is partial; the probe verdict is unchanged"
    if allow_audit_failure and audit["status"] != "pass":
        report["preflight_override"] = "Audit failed; loader pixel evidence was requested explicitly for a controlled fault"
    if not report["source_unchanged"]:
        report["status"] = "fail"
    return report

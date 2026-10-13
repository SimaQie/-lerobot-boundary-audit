"""LeRobot v3 metadata-to-video boundary checks, read-only and fully local."""

import json
import math
import time
from bisect import bisect_right
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

from . import __version__
from .mp4 import InvalidMP4, UnsupportedMP4, read_timeline


def contained(root, relative):
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("Dataset path escapes its root")
    return candidate


def audit_dataset(root, *, decode=False, tolerance=0.0001, cameras=None):
    import pyarrow.parquet as pq

    root = Path(root).resolve()
    if (root / "INCOMPLETE").exists():
        raise ValueError("Dataset publication is incomplete")
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("Tolerance must be finite and positive")
    start_time = time.perf_counter()
    info = json.loads((root / "meta/info.json").read_text(encoding="utf-8"))
    if info.get("codebase_version") != "v3.0":
        raise ValueError("This prototype supports LeRobot v3.0 only")
    fps = Fraction(str(info["fps"]))
    if fps <= 0:
        raise ValueError("FPS must be positive")
    declared_cameras = [name for name, feature in info["features"].items() if feature["dtype"] == "video"]
    cameras = declared_cameras if cameras is None else list(dict.fromkeys(cameras))
    if set(cameras) - set(declared_cameras):
        raise ValueError("Selected camera is absent from info.features")
    if not cameras:
        raise ValueError("Dataset has no declared video features")
    findings, episodes, video_groups = [], [], defaultdict(list)
    finding_counts, severity_counts = Counter(), Counter()

    def add(code, severity, message, **location):
        finding_counts[code] += 1
        severity_counts[severity] += 1
        if len(findings) < 1000:
            findings.append({"code": code, "severity": severity, "message": message, **location})

    episode_files = sorted((root / "meta/episodes").glob("chunk-*/file-*.parquet"))
    if not episode_files:
        raise ValueError("No v3 episode metadata found")
    for path in episode_files:
        pf = pq.ParquetFile(contained(root, path.relative_to(root)))
        columns = [name for name in pf.schema_arrow.names if not name.startswith("stats/")]
        for batch in pf.iter_batches(columns=columns, batch_size=1024):
            episodes.extend(batch.to_pylist())
    episodes.sort(key=lambda e: e["episode_index"])
    ids = [e["episode_index"] for e in episodes]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate episode indexes")
    if ids != list(range(len(episodes))):
        add(
            "EPISODE_INDEX_DISCONTINUITY",
            "error",
            "Full metadata must contain contiguous episode indexes starting at zero",
        )
    if len(episodes) != info["total_episodes"]:
        add("PARTIAL_METADATA", "error", "Episode metadata does not cover the declared dataset")
    if sum(e["length"] for e in episodes) != info["total_frames"]:
        add("FRAME_TOTAL_MISMATCH", "error", "Episode lengths differ from total_frames")
    row_cursor = 0
    for episode in episodes:
        if episode["dataset_from_index"] != row_cursor or episode["dataset_to_index"] != row_cursor + episode["length"]:
            add(
                "DATA_RANGE_MISMATCH",
                "error",
                "Metadata row ranges are not contiguous or disagree with length",
                episode_index=episode["episode_index"],
            )
        row_cursor += episode["length"]
    boundaries = []
    for episode in episodes:
        if episode["length"] <= 0:
            raise ValueError("Episode length must be positive")
        for camera in cameras:
            prefix = f"videos/{camera}"
            relative = info["video_path"].format(
                video_key=camera,
                chunk_index=episode[f"{prefix}/chunk_index"],
                file_index=episode[f"{prefix}/file_index"],
            )
            video_groups[relative].append((episode, camera))
    video_reports, checked_episodes, decoded_checks = [], 0, 0
    timeline_map = {}
    for relative, items in sorted(video_groups.items()):
        path = contained(root, relative)
        try:
            timeline = read_timeline(path)
            timeline_map[relative] = timeline
            grid = timeline.grid(fps)
        except UnsupportedMP4 as exc:
            add("UNSUPPORTED_VIDEO_TIMELINE", "unverified", str(exc), video=relative)
            continue
        except (InvalidMP4, OSError) as exc:
            add("INVALID_VIDEO", "error", str(exc), video=relative)
            continue
        video_reports.append({"path": relative, **grid})
        # A nonintegral frame interval naturally has integer-tick quantization.
        allowed_ticks = 0 if grid["integral_ticks_per_frame"] else 1
        if grid["max_abs_deviation_ticks"] > allowed_ticks:
            add(
                "VIDEO_GRID_DEVIATION",
                "review",
                "PTS grid differs from the declared constant-FPS grid",
                video=relative,
                **grid,
            )
        # Reordered tracks can carry a media duration different from the
        # cumulative DTS intervals. Keep the raw comparison in the evidence,
        # but do not treat it as corruption without a full duration model.
        if not grid["composition_offsets"] and not grid["duration_matches_stts"]:
            add("VIDEO_DURATION_MISMATCH", "error", "mdhd duration disagrees with sample durations", video=relative)
        cursor = 0
        for episode, camera in items:
            prefix = f"videos/{camera}"
            begin = float(episode[f"{prefix}/from_timestamp"])
            end = float(episode[f"{prefix}/to_timestamp"])
            length = episode["length"]
            location = {"video": relative, "camera": camera, "episode_index": episode["episode_index"]}
            if not all(math.isfinite(v) for v in (begin, end)) or begin < 0 or end <= begin:
                add("INVALID_SEGMENT", "error", "Episode video bounds are invalid", **location)
                cursor += length
                continue
            if cursor + length > timeline.samples:
                add("VIDEO_COVERAGE_MISMATCH", "error", "Episode runs beyond available video samples", **location)
                cursor += length
                continue
            expected_begin = float(Fraction(timeline.tick_at(cursor), timeline.timescale))
            expected_end = float(Fraction(timeline.end_tick_at(cursor + length - 1), timeline.timescale))
            if abs(begin - expected_begin) > tolerance:
                add(
                    "EPISODE_START_MISMATCH",
                    "error",
                    "Metadata start differs from the episode's ordinal sample PTS",
                    declared_seconds=begin,
                    video_seconds=expected_begin,
                    **location,
                )
            if abs(end - expected_end) > tolerance:
                add(
                    "EPISODE_END_MISMATCH",
                    "error",
                    "Metadata end differs from cumulative episode length/FPS",
                    declared_seconds=end,
                    expected_seconds=expected_end,
                    **location,
                )
            for local_frame in sorted({0, 1 if length > 1 else 0, length - 1}):
                index = cursor + local_frame
                expected_tick = timeline.tick_at(index)
                # This is LeRobot's offset + local timestamp convention. The exact
                # producer frame identity is still unknown on unlabelled real video.
                requested = Fraction(str(begin)) + Fraction(local_frame, 1) / fps
                deviation = abs(float(requested) - expected_tick / timeline.timescale)
                record = {
                    **location,
                    "frame_index": local_frame,
                    "video_sample_index": index,
                    "episode_start_seconds": begin,
                    "request_seconds": float(requested),
                    "video_pts_seconds": expected_tick / timeline.timescale,
                    "deviation_seconds": deviation,
                }
                boundaries.append(record)
            checked_episodes += 1
            cursor += length
        if cursor != timeline.samples:
            add(
                "VIDEO_SAMPLE_COUNT_MISMATCH",
                "error",
                "Video sample count differs from referenced episode lengths",
                video=relative,
                video_samples=timeline.samples,
                metadata_samples=cursor,
            )

    data_files = sorted((root / "data").glob("chunk-*/file-*.parquet"))
    seen_rows = 0
    counters = defaultdict(int)
    query_keys = {(q["episode_index"], q["frame_index"]) for q in boundaries}
    query_timestamps = {}
    row_ends = [e["dataset_to_index"] for e in episodes]
    data_start_time = time.perf_counter()
    for path in data_files:
        pf = pq.ParquetFile(contained(root, path.relative_to(root)))
        for batch in pf.iter_batches(columns=["episode_index", "frame_index", "timestamp"], batch_size=4096):
            for row in batch.to_pylist():
                seen_rows += 1
                ep, frame, ts = row["episode_index"], row["frame_index"], row["timestamp"]
                range_index = bisect_right(row_ends, seen_rows - 1)
                if range_index >= len(episodes) or ep != episodes[range_index]["episode_index"]:
                    add(
                        "EPISODE_DATA_RANGE_MISMATCH",
                        "error",
                        "Stored row episode disagrees with declared global row range",
                        episode_index=ep,
                        frame_index=frame,
                    )
                if frame != counters[ep]:
                    add(
                        "FRAME_INDEX_DISCONTINUITY",
                        "error",
                        "Unexpected frame order",
                        episode_index=ep,
                        frame_index=frame,
                    )
                counters[ep] += 1
                if (ep, frame) in query_keys:
                    query_timestamps[(ep, frame)] = ts
                if (
                    ts is None
                    or not math.isfinite(ts)
                    or frame < 0
                    or abs(ts - float(Fraction(frame, 1) / fps)) > tolerance
                ):
                    add(
                        "DATA_TIMESTAMP_MISMATCH",
                        "error",
                        "Row timestamp differs from local frame_index/FPS",
                        episode_index=ep,
                        frame_index=frame,
                    )
    for episode in episodes:
        if counters[episode["episode_index"]] != episode["length"]:
            add(
                "EPISODE_ROW_COUNT_MISMATCH",
                "error",
                "Data rows differ from episode length",
                episode_index=episode["episode_index"],
            )
    if set(counters) - set(ids):
        add("UNDECLARED_DATA_EPISODE", "error", "Data includes an episode absent from metadata")
    if seen_rows != info["total_frames"]:
        add("DATA_TOTAL_MISMATCH", "error", "Inspected data rows differ from total_frames")
    valid_boundaries = []
    for query in boundaries:
        ts = query_timestamps.get((query["episode_index"], query["frame_index"]))
        if ts is None or not isinstance(ts, (int, float)) or not math.isfinite(ts):
            add("BOUNDARY_ROW_UNAVAILABLE", "error", "Boundary timestamp row is missing or invalid", **query)
            continue
        query["row_timestamp_seconds"] = ts
        query["request_seconds"] = query["episode_start_seconds"] + ts
        query["deviation_seconds"] = abs(query["request_seconds"] - query["video_pts_seconds"])
        valid_boundaries.append(query)
        if query["deviation_seconds"] > tolerance:
            add(
                "BOUNDARY_QUERY_MISMATCH",
                "error",
                "Offset plus stored timestamp differs from ordinal sample PTS",
                **query,
            )
    data_seconds = time.perf_counter() - data_start_time
    decode_evidence = []
    decoder_info = {"requested": decode, "status": "not_requested", "backend": "pyav"}
    if decode:
        try:
            import av
        except ImportError:
            add("DECODER_UNAVAILABLE", "unverified", "Install the decode extra for PyAV checks")
            decoder_info["status"] = "unavailable"
        else:
            decoder_info.update(
                {
                    "version": av.__version__,
                    "status": "checked",
                    "selection_rule": "seek backward then nearest PTS in a bounded forward window",
                }
            )
            for relative in sorted(timeline_map):
                queries = [b for b in valid_boundaries if b["video"] == relative]
                try:
                    with av.open(str(contained(root, relative))) as container:
                        stream = container.streams.video[0]
                        stream.codec_context.thread_count = 1
                        for query in queries:
                            requested = Fraction(str(query["request_seconds"]))
                            target = int(requested / stream.time_base)
                            container.seek(max(0, target - 1), stream=stream, backward=True, any_frame=False)
                            nearest = None
                            for n, frame in enumerate(container.decode(stream)):
                                if n >= 4096:
                                    break
                                if frame.pts is None:
                                    continue
                                seconds = float(frame.pts * frame.time_base)
                                distance = abs(seconds - float(requested))
                                if nearest is None or distance < nearest[0]:
                                    nearest = (distance, seconds)
                                if seconds > float(requested) + 1 / float(fps):
                                    break
                            if nearest is None:
                                add("DECODE_NO_FRAME", "error", "No frame found in bounded seek", **query)
                                continue
                            decoded_checks += 1
                            record = {
                                **query,
                                "decoded_pts_seconds": nearest[1],
                                "request_distance_seconds": nearest[0],
                            }
                            decode_evidence.append(record)
                            if nearest[0] > tolerance or abs(nearest[1] - query["video_pts_seconds"]) > tolerance:
                                add(
                                    "DECODE_BOUNDARY_MISMATCH",
                                    "error",
                                    "Decoded boundary PTS differs from expected sample",
                                    **record,
                                )
                except Exception as exc:
                    add("DECODE_ERROR", "error", f"{type(exc).__name__}: {exc}", video=relative)
    elapsed = time.perf_counter() - start_time
    severities = set(severity_counts)
    status = (
        "fail"
        if "error" in severities
        else "partial"
        if "unverified" in severities
        else "review"
        if findings
        else "pass"
    )
    return {
        "schema_version": "boundary-audit.v0.2",
        "tool_version": __version__,
        "status": status,
        "scope": "LeRobot v3 storage timeline; physical sensor/action synchronization is not assessed",
        "selection": {
            "declared_cameras": declared_cameras,
            "checked_cameras": cameras,
            "camera_scope": "all" if set(cameras) == set(declared_cameras) else "selected",
            "unselected_cameras": sorted(set(declared_cameras) - set(cameras)),
        },
        "dataset_coverage_status": "full" if set(cameras) == set(declared_cameras) else "partial",
        "fps": str(fps),
        "declared_episodes": info["total_episodes"],
        "declared_frames": info["total_frames"],
        "coverage": {
            "metadata_episodes": len(episodes),
            "cameras": len(cameras),
            "data_rows": seen_rows,
            "video_files_total": len(video_groups),
            "video_files_checked": len(video_reports),
            "episode_camera_pairs_total": len(episodes) * len(cameras),
            "episode_camera_pairs_checked": checked_episodes,
            "boundary_queries": len(boundaries),
            "decoded_queries": decoded_checks,
        },
        "tolerance_seconds": tolerance,
        "decoder": decoder_info,
        "limitations": [
            "Fragmented MP4, trimming/multiple edits and large composition tables are unsupported",
            "Official LeRobot decoder verification requires the separate verify command",
            "mdhd versus stts duration equality is assessed only on tracks without composition offsets",
            "Ordinal alignment assumes full ordered episode metadata within each video shard",
        ],
        "video_reports": video_reports,
        "boundary_queries": boundaries,
        "decode_evidence": decode_evidence,
        "findings": findings,
        "finding_counts": dict(finding_counts),
        "findings_truncated_count": sum(finding_counts.values()) - len(findings),
        "timing_seconds": {"total": elapsed, "data_rows": data_seconds},
    }

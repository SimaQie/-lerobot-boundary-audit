"""Runs in a separately installed official LeRobot interpreter, using stdin JSON.

The core package never imports torch. This driver calls the installed upstream
decoder rather than a copied/reimplemented version of its selection function.
"""

import hashlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path


def main():
    request = json.load(sys.stdin)
    root = Path(request["root"]).resolve()
    handles = []
    if request.get("ffmpeg_bin"):
        directory = str(Path(request["ffmpeg_bin"]).resolve())
        os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            handles.append(os.add_dll_directory(directory))
    versions = {"python": sys.version.split()[0]}
    records, errors = [], []
    try:
        for name in ["lerobot", "torch", "torchcodec", "av"]:
            try:
                versions[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                versions[name] = "not installed"
        import torch

        torch.set_num_threads(1)
        from lerobot.datasets import video_utils

        versions["official_video_utils_sha256"] = hashlib.sha256(Path(video_utils.__file__).read_bytes()).hexdigest()
        cache = video_utils.VideoDecoderCache(max_size=4)
        for query in request["queries"]:
            relative = query["video"]
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Query path escapes dataset")
            record = {
                "video": relative,
                "camera": query["camera"],
                "episode_index": query["episode_index"],
                "frame_index": query["frame_index"],
                "request_seconds": query["request_seconds"],
                "expected_pts_seconds": query["video_pts_seconds"],
            }
            try:
                if request["backend"] == "torchcodec":
                    frames = video_utils.decode_video_frames_torchcodec(
                        path,
                        [query["request_seconds"]],
                        tolerance_s=request["tolerance"],
                        decoder_cache=cache,
                        return_uint8=True,
                    )
                    decoder = cache.get_decoder(str(path))
                    selected_index = round(query["request_seconds"] * decoder.metadata.average_fps)
                    actual = decoder.get_frames_at(indices=[selected_index])
                    expected = decoder.get_frames_at(indices=[query["video_sample_index"]])
                    actual_pts = actual.pts_seconds[0].item()
                    record.update(
                        {
                            "selected_index": selected_index,
                            "expected_index": query["video_sample_index"],
                            "actual_pts_seconds": actual_pts,
                            "official_frame_matches_expected": bool(torch.equal(frames[0], expected.data[0])),
                            "request_distance_seconds": abs(actual_pts - query["request_seconds"]),
                        }
                    )
                    if (
                        selected_index != query["video_sample_index"]
                        or abs(actual_pts - query["video_pts_seconds"]) > request["tolerance"]
                    ):
                        record["status"] = "mismatch"
                    elif not record["official_frame_matches_expected"]:
                        record["status"] = "mismatch"
                    else:
                        record["status"] = "pass"
                else:
                    # One query per call avoids decoding/materializing an entire
                    # long episode just to inspect its endpoints.
                    frames = video_utils.decode_video_frames_pyav(
                        path, [query["request_seconds"]], tolerance_s=request["tolerance"], return_uint8=True
                    )
                    import av

                    with av.open(str(path)) as container:
                        stream = container.streams.video[0]
                        stream.codec_context.thread_count = 1
                        container.seek(
                            max(0, round(query["video_pts_seconds"] / stream.time_base) - 1),
                            backward=True,
                            any_frame=False,
                            stream=stream,
                        )
                        expected = None
                        for i, frame in enumerate(container.decode(stream)):
                            if i > 4096:
                                break
                            if (
                                frame.pts is not None
                                and abs(float(frame.pts * frame.time_base) - query["video_pts_seconds"]) < 1e-8
                            ):
                                expected = (
                                    torch.from_numpy(frame.to_ndarray(format="rgb24")).permute(2, 0, 1).contiguous()
                                )
                                break
                    record["official_frame_matches_expected"] = expected is not None and bool(
                        torch.equal(frames[0], expected)
                    )
                    record["status"] = "pass" if record["official_frame_matches_expected"] else "mismatch"
            except Exception as exc:
                record["status"] = "error"
                record["error_type"] = type(exc).__name__
                record["message"] = str(exc).replace(str(root), "<dataset>")[:1000]
            records.append(record)
    except Exception as exc:
        errors.append({"type": type(exc).__name__, "message": str(exc).replace(str(root), "<dataset>")[:2000]})
    status = "unavailable" if errors else "fail" if any(r["status"] != "pass" for r in records) else "pass"
    print(
        json.dumps(
            {
                "status": status,
                "backend": "official-lerobot-" + request["backend"],
                "versions": versions,
                "requested_queries": len(request["queries"]),
                "checked_queries": len(records),
                "passed_queries": sum(r["status"] == "pass" for r in records),
                "records": records,
                "errors": errors,
            },
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

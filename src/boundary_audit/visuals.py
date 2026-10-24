"""Bounded, opt-in previews of the local audit's actual decoded boundary frames."""

import hashlib
from pathlib import Path

from .audit import contained


def add_visual_evidence(report, root, output, *, max_queries=4, max_frames=50000):
    """Save expected ordinal and observed local-PyAV frames; never change verdicts."""
    import av

    output = Path(output)
    if output.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("Visual output must be outside the source dataset")
    if type(max_queries) is not int or type(max_frames) is not int or min(max_queries, max_frames) < 1:
        raise ValueError("Visual budgets must be positive integers")
    output.mkdir(parents=True, exist_ok=True)
    queries = sorted(
        report.get("decode_evidence", []),
        key=lambda q: (-round(abs(q["decoded_pts_seconds"] - q["video_pts_seconds"]), 8), -q["frame_index"]),
    )[:max_queries]
    evidence = {
        "status": "complete",
        "decoder": "local PyAV",
        "pixel_provenance": "Sequential reconstruction at the recorded local seek PTS; not captured consumer pixels",
        "records": [],
        "decoded_frames": 0,
        "max_queries": max_queries,
        "max_frames": max_frames,
        "scope": "Ordinal reference and actual local seek result; not official-loader or physical sensor identity",
    }
    report["visual_evidence"] = evidence
    for ordinal, query in enumerate(queries):
        record = {**query, "images": []}
        evidence["records"].append(record)
        expected = query["video_sample_index"]
        wanted = {max(0, expected - 1): "Previous", expected: "Expected ordinal", expected + 1: "Next"}
        try:
            with av.open(str(contained(Path(root).resolve(), query["video"]))) as container:
                stream = container.streams.video[0]
                stream.codec_context.thread_count = 1
                observed = False
                for index, frame in enumerate(container.decode(stream)):
                    if evidence["decoded_frames"] >= max_frames:
                        raise ValueError("Visual decode frame budget exhausted")
                    evidence["decoded_frames"] += 1
                    pts = float(frame.pts * frame.time_base) if frame.pts is not None else None
                    roles = [wanted[index]] if index in wanted else []
                    if pts is not None and abs(pts - query["decoded_pts_seconds"]) < 1e-8:
                        roles.append("Observed local decode")
                        observed = True
                    if roles:
                        # FFmpeg's MJPEG encoder avoids adding Pillow or NumPy dependencies.
                        width = min(480, frame.width)
                        width -= width % 2
                        height = max(2, int(frame.height * width / frame.width) // 2 * 2)
                        codec = av.CodecContext.create("mjpeg", "w")
                        codec.width, codec.height, codec.pix_fmt = width, height, "yuvj420p"
                        pixels = frame.reformat(width=width, height=height, format="yuvj420p")
                        data = b"".join(bytes(p) for p in list(codec.encode(pixels)) + list(codec.encode(None)))
                        name = f"boundary-{ordinal}-{index}-{hashlib.sha256(data).hexdigest()[:16]}.jpg"
                        (output / name).write_bytes(data)
                        record["images"].append(
                            {
                                "roles": roles,
                                "sample": index,
                                "pts_seconds": pts,
                                "path": name,
                                "sha256": hashlib.sha256(data).hexdigest(),
                            }
                        )
                    if index >= expected + 1 and observed:
                        break
                if not observed or not any("Expected ordinal" in x["roles"] for x in record["images"]):
                    raise ValueError("Visual reference did not cover expected and observed frames")
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            evidence["status"] = "partial"
    if not queries:
        evidence["status"] = "unavailable"
    return evidence

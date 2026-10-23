"""Independent full-decode timing reference; imports no boundary_audit code."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import time
import av


project = Path(__file__).resolve().parents[1]
root = project / "samples/pusht"
info = json.loads((root / "meta/info.json").read_text())
video = root / "videos/observation.image/chunk-000/file-000.mp4"
fps = Fraction(str(info["fps"]))
start = time.perf_counter()
maximum = Fraction(0)
count = 0
missing_pts = 0
with av.open(str(video)) as container:
    stream = container.streams.video[0]
    stream.codec_context.thread_count = 1
    for index, frame in enumerate(container.decode(stream)):
        count += 1
        if frame.pts is None:
            missing_pts += 1
            continue
        deviation = abs(frame.pts * frame.time_base - Fraction(index, 1) / fps)
        maximum = max(maximum, deviation)
result = {"method": "Sequential PyAV decoding of every frame; no project parser imported",
          "pyav_version": av.__version__, "decoded_frames": count, "missing_pts": missing_pts,
          "declared_frames": info["total_frames"], "max_abs_deviation_seconds": float(maximum),
          "exact_pts_grid": maximum == 0 and missing_pts == 0,
          "file_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
          "elapsed_seconds": time.perf_counter() - start}
out = project / "research/results/full-decode-reference.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2))
assert count == info["total_frames"] and maximum == 0 and missing_pts == 0

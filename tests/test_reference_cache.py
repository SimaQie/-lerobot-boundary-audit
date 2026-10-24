import hashlib
from fractions import Fraction
from pathlib import Path

import numpy as np

from boundary_audit.probe_driver import _tool_identity, reference_frames
from boundary_audit.reference_cache import cache_key, cache_path, default_root


def make_video(path, frames=4, offset=0):
    import av

    path.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=30)
        stream.width, stream.height, stream.pix_fmt = 16, 16, "yuv420p"
        stream.options = {"crf": "18", "g": "1"}
        for index in range(frames):
            pixels = np.full((16, 16, 3), (index + offset) * 40 % 255, np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base = index, Fraction(1, 30)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)


def request(root, cache, *, enabled=True, max_cache_bytes=10_000_000):
    return {
        "root": str(root),
        "videos": {"videos/camera/chunk-000/file-000.mp4": {"camera": "camera", "targets": {"0": 1}}},
        "fps": 30,
        "max_decode_frames": 100,
        "max_reference_bytes": 10_000_000,
        "reference_cache": str(cache) if cache else None,
        "reference_cache_enabled": enabled,
        "max_cache_bytes": max_cache_bytes,
    }


def test_cache_hit_reuses_pixels_and_reports_cold_warm_timings(tmp_path):
    root = tmp_path / "source"
    video = root / "videos/camera/chunk-000/file-000.mp4"
    make_video(video)
    cache = tmp_path / "cache"
    cold, decoded_cold, bytes_cold, stats_cold = reference_frames(request(root, cache))
    warm, decoded_warm, bytes_warm, stats_warm = reference_frames(request(root, cache))
    assert decoded_cold > 0 and decoded_warm == 0
    assert bytes_cold == bytes_warm
    assert stats_cold["misses"] == 1 and stats_cold["writes"] == 1
    assert stats_warm["hits"] == 1 and stats_warm["writes"] == 0
    assert stats_warm["read_bytes"] > 0
    assert stats_warm["decode_seconds"] == 0
    assert all(np.array_equal(cold[key][n], warm[key][n]) for key in cold for n in cold[key])
    assert cold["videos/camera/chunk-000/file-000.mp4"][1].shape == (16, 16, 3)


def test_last_frame_without_a_next_neighbour_caches_available_frames(tmp_path):
    root = tmp_path / "source"
    video = root / "videos/camera/chunk-000/file-000.mp4"
    make_video(video)
    cache = tmp_path / "cache"
    value = request(root, cache)
    value["videos"]["videos/camera/chunk-000/file-000.mp4"]["targets"] = {"0": 3}
    cold, _, _, stats_cold = reference_frames(value)
    warm, decoded, _, stats_warm = reference_frames(value)
    assert stats_cold["writes"] == 1 and stats_warm["hits"] == 1
    assert decoded == 0
    assert 3 in cold["videos/camera/chunk-000/file-000.mp4"]
    assert np.array_equal(cold["videos/camera/chunk-000/file-000.mp4"][3], warm["videos/camera/chunk-000/file-000.mp4"][3])


def test_changed_video_content_invalidates_cache(tmp_path):
    root = tmp_path / "source"
    video = root / "videos/camera/chunk-000/file-000.mp4"
    make_video(video)
    cache = tmp_path / "cache"
    first, _, _, _ = reference_frames(request(root, cache))
    make_video(video, offset=2)
    second, decoded, _, stats = reference_frames(request(root, cache))
    assert decoded > 0
    assert stats["misses"] == 1 and stats["hits"] == 0
    assert not np.array_equal(first["videos/camera/chunk-000/file-000.mp4"][1], second["videos/camera/chunk-000/file-000.mp4"][1])


def test_corrupt_cache_is_a_miss_not_a_probe_failure(tmp_path):
    root = tmp_path / "source"
    video = root / "videos/camera/chunk-000/file-000.mp4"
    make_video(video)
    cache = tmp_path / "cache"
    request_value = request(root, cache)
    reference_frames(request_value)
    key = cache_key(
        source_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),
        relative="videos/camera/chunk-000/file-000.mp4",
        targets={0, 1, 2},
        fps=30,
        tool_identity=_tool_identity(request_value),
    )
    cache_path(cache, key).write_bytes(b"not an npz")
    _, decoded, _, stats = reference_frames(request_value)
    assert decoded > 0
    assert stats["corrupt"] == 1 and stats["misses"] == 1 and stats["writes"] == 1


def test_cache_can_be_disabled_and_writes_nothing(tmp_path):
    root = tmp_path / "source"
    make_video(root / "videos/camera/chunk-000/file-000.mp4")
    cache = tmp_path / "cache"
    _, decoded, _, stats = reference_frames(request(root, cache, enabled=False))
    assert decoded > 0
    assert stats["enabled"] is False
    assert stats["entries"][0]["status"] == "decoded"
    assert not cache.exists()


def test_cache_budget_skips_oversize_entry_without_failing(tmp_path):
    root = tmp_path / "source"
    make_video(root / "videos/camera/chunk-000/file-000.mp4")
    cache = tmp_path / "cache"
    _, decoded, _, stats = reference_frames(request(root, cache, max_cache_bytes=1))
    assert decoded > 0
    assert stats["writes"] == 0
    assert stats["entries"][0]["cache_write"] == "too_large"


def test_default_root_honours_explicit_cache_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LEROBOT_BOUNDARY_AUDIT_CACHE", str(tmp_path / "custom"))
    assert default_root() == tmp_path / "custom/reference"
    assert Path(default_root()).is_absolute()


def test_decoder_version_change_invalidates_reference_identity(monkeypatch):
    import av

    before = _tool_identity({})
    monkeypatch.setattr(av, "__version__", "different-build")
    assert _tool_identity({}) != before


def test_valid_zip_with_altered_pixels_is_redecoded(tmp_path):
    root = tmp_path / "source"
    make_video(root / "videos/camera/chunk-000/file-000.mp4")
    cache = tmp_path / "cache"
    value = request(root, cache)
    cold, _, _, stats = reference_frames(value)
    path = cache_path(cache, stats["entries"][0]["key"])
    with np.load(path, allow_pickle=False) as payload:
        arrays = {name: payload[name] for name in payload.files}
    arrays["frame_1"] = np.zeros_like(arrays["frame_1"])
    np.savez_compressed(path, **arrays)
    warm, decoded, _, stats = reference_frames(value)
    assert decoded > 0 and stats["corrupt"] == 1
    assert all(np.array_equal(cold[key][n], warm[key][n]) for key in cold for n in cold[key])


def test_truncated_zip_member_falls_back_to_decode(tmp_path):
    root = tmp_path / "source"
    make_video(root / "videos/camera/chunk-000/file-000.mp4")
    cache = tmp_path / "cache"
    value = request(root, cache)
    _, _, _, stats = reference_frames(value)
    path = cache_path(cache, stats["entries"][0]["key"])
    data = bytearray(path.read_bytes())
    data[0:4] = b"XXXX"  # central directory still exists; reading a member raises BadZipFile
    path.write_bytes(data)
    _, decoded, _, stats = reference_frames(value)
    assert decoded > 0 and stats["corrupt"] == 1

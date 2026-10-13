from fractions import Fraction

import av
import numpy as np
import pytest

from boundary_audit.identity import decode_identity, identity_value, render_frame, validate_oracle


@pytest.mark.parametrize("values", [(0, 0, 0), (1, 100, 7), (255, 4095, 4095)])
def test_identity_roundtrip_and_normalized_chw(values):
    image = render_frame(*values)
    expected = dict(zip(["camera", "episode", "frame"], values, strict=True))
    assert decode_identity(image) == expected
    assert decode_identity(np.moveaxis(image / 255.0, -1, 0), layout="CHW") == expected


def test_crc_rejects_changed_bit_and_ambiguous_pixels():
    image = render_frame(1, 100, 7)
    image[10:14, 10:14] = 16
    with pytest.raises(ValueError, match="sync/CRC"):
        decode_identity(image)
    image[:] = 120
    with pytest.raises(ValueError, match="ambiguous"):
        decode_identity(image)


@pytest.mark.parametrize("values", [(256, 0, 0), (0, 4096, 0), (0, 0, -1), (0, 0, 1.0)])
def test_identity_bounds(values):
    with pytest.raises(ValueError):
        identity_value(*values)


def test_identity_survives_lossy_bframe_h264_encoding(tmp_path):
    path = tmp_path / "markers.mp4"
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=30)
        stream.width, stream.height, stream.pix_fmt = 128, 96, "yuv420p"
        stream.options = {"bf": "2", "crf": "30"}
        for i in range(15):
            frame = av.VideoFrame.from_ndarray(render_frame(1, 100, i), format="rgb24")
            frame.pts, frame.time_base = i, Fraction(1, 30)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    with av.open(str(path)) as container:
        identities = [decode_identity(frame.to_ndarray(format="rgb24")) for frame in container.decode(video=0)]
    assert identities == [{"camera": 1, "episode": 100, "frame": i} for i in range(15)]


def test_empty_oracle_cannot_certify_zero_rows():
    with pytest.raises(ValueError, match="nonempty"):
        validate_oracle(
            {"schema_version": "boundary-frame-oracle.v1", "fps": 30, "cameras": {}, "episodes": [], "rows": []}
        )


def test_oracle_ranges_and_camera_must_agree():
    oracle = {
        "schema_version": "boundary-frame-oracle.v1",
        "fps": 30,
        "cameras": {"left": 0},
        "episodes": [{"episode_index": 0, "start": 0, "length": 1}],
        "rows": [
            {
                "episode_index": 0,
                "frame_index": 0,
                "action": 0,
                "identities": {"left": {"camera": 0, "episode": 100, "frame": 0}},
            }
        ],
    }
    validate_oracle(oracle)
    oracle["rows"][0]["identities"]["left"]["camera"] = 1
    with pytest.raises(ValueError, match="camera/frame"):
        validate_oracle(oracle)

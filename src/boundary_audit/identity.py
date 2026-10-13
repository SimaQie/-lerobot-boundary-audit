"""Original, compression-tolerant pixel markers with a CRC-checked frame identity.

Markers are synthetic test ground truth, not an identity detector for real footage.
No MP4 timestamp, row index or decoder selection code participates in decoding.
"""

import binascii
import math

MAGIC = 0xD3
CELL = 8
MARGIN = 8
HEIGHT = 96
WIDTH = 128


def validate_oracle(oracle):
    """Reject empty/inconsistent ground truth before any official loader runs."""
    if oracle.get("schema_version") != "boundary-frame-oracle.v1":
        raise ValueError("Unsupported frame oracle schema")
    fps = oracle.get("fps")
    if not isinstance(fps, (int, float)) or not math.isfinite(fps) or fps <= 0:
        raise ValueError("Oracle needs a positive finite FPS")
    cameras, episodes, rows = oracle.get("cameras"), oracle.get("episodes"), oracle.get("rows")
    if (
        not isinstance(cameras, dict)
        or not cameras
        or not isinstance(episodes, list)
        or not episodes
        or not isinstance(rows, list)
        or not rows
    ):
        raise ValueError("Oracle needs nonempty cameras, episodes and rows")
    if len(set(cameras.values())) != len(cameras):
        raise ValueError("Oracle camera IDs must be unique")
    start = 0
    for index, episode in enumerate(episodes):
        length = episode.get("length")
        if (
            episode.get("episode_index") != index
            or episode.get("start") != start
            or not isinstance(length, int)
            or length <= 0
        ):
            raise ValueError("Oracle episode ranges must be contiguous and nonempty")
        for frame, row in enumerate(rows[start : start + length]):
            if (
                row.get("episode_index") != index
                or row.get("frame_index") != frame
                or set(row.get("identities", {})) != set(cameras)
            ):
                raise ValueError("Oracle row identity/range mismatch")
            action = row.get("action")
            if not isinstance(action, (int, float)) or not math.isfinite(action):
                raise ValueError("Oracle action must be finite")
            for camera, cam_id in cameras.items():
                target = row["identities"][camera]
                identity_value(target["camera"], target["episode"], target["frame"])
                if target["camera"] != cam_id or target["frame"] != frame:
                    raise ValueError("Oracle marker camera/frame mismatch")
        start += length
    if start != len(rows):
        raise ValueError("Oracle episode ranges do not cover rows")


def identity_value(camera, episode, frame):
    for value, maximum in [(camera, 255), (episode, 4095), (frame, 4095)]:
        if not isinstance(value, int) or not 0 <= value <= maximum:
            raise ValueError("Identity fields exceed marker bounds")
    return (camera << 24) | (episode << 12) | frame


def marker_bytes(camera, episode, frame):
    payload = bytes([MAGIC]) + identity_value(camera, episode, frame).to_bytes(4, "big")
    return payload + binascii.crc_hqx(payload, 0xFFFF).to_bytes(2, "big")


def render_frame(camera, episode, frame):
    import numpy as np

    pixels = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    pixels[:] = [30 + camera * 15 % 100, 45, 60 + frame * 3 % 100]
    for bit_index in range(56):
        value = marker_bytes(camera, episode, frame)[bit_index // 8]
        bit = (value >> (7 - bit_index % 8)) & 1
        y, x = MARGIN + (bit_index // 8) * CELL, MARGIN + (bit_index % 8) * CELL
        pixels[y : y + CELL, x : x + CELL] = 240 if bit else 16
    # Independent motion outside the marker avoids a wholly static fixture.
    pixels[76:88, 8 + frame % 10 * 8 : 16 + frame % 10 * 8] = [220, 80, 50]
    return pixels


def decode_identity(image, *, layout="HWC"):
    import numpy as np

    pixels = np.asarray(image)
    if layout == "CHW":
        pixels = np.moveaxis(pixels, 0, -1)
    elif layout != "HWC":
        raise ValueError("Marker layout must be HWC or CHW")
    if pixels.ndim != 3 or pixels.shape[0] < 64 or pixels.shape[1] < 72 or pixels.shape[2] != 3:
        raise ValueError("Image is too small or has an unsupported layout")
    if not np.isfinite(pixels).all():
        raise ValueError("Marker image contains nonfinite values")
    if np.issubdtype(pixels.dtype, np.floating) and pixels.max() <= 1.0:
        pixels = pixels * 255
    bits = []
    for index in range(56):
        y, x = MARGIN + index // 8 * CELL, MARGIN + index % 8 * CELL
        mean = float(pixels[y + 2 : y + 6, x + 2 : x + 6].mean())
        if 80 < mean < 175:
            raise ValueError("Marker bit is ambiguous after transformation")
        bits.append(int(mean >= 127.5))
    encoded = bytes(sum(bits[i + b] << (7 - b) for b in range(8)) for i in range(0, 56, 8))
    if encoded[0] != MAGIC or binascii.crc_hqx(encoded[:5], 0xFFFF) != int.from_bytes(encoded[5:], "big"):
        raise ValueError("Marker sync/CRC mismatch; frame identity is unknown")
    value = int.from_bytes(encoded[1:5], "big")
    return {"camera": value >> 24, "episode": (value >> 12) & 4095, "frame": value & 4095}

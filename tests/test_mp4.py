import struct
from fractions import Fraction

import pytest

from boundary_audit.mp4 import InvalidMP4, UnsupportedMP4, read_timeline


def box(kind, data):
    return struct.pack(">I4s", 8 + len(data), kind) + data


def fixture(runs, *, edit=None, composition=False, scale=15360, ctts_version=0):
    duration = sum(n * d for n, d in runs)
    mdhd = box(b"mdhd", bytes(12) + struct.pack(">II", scale, duration) + bytes(4))
    hdlr = box(b"hdlr", bytes(8) + b"vide" + bytes(12))
    stts = box(b"stts", bytes(4) + struct.pack(">I", len(runs)) + b"".join(struct.pack(">II", *r) for r in runs))
    stsz = box(b"stsz", bytes(4) + struct.pack(">II", 1, sum(n for n, _ in runs)))
    comp = [(sum(n for n, _ in runs), 1)] if composition is True else composition
    extra = (
        box(
            b"ctts",
            bytes([ctts_version, 0, 0, 0])
            + struct.pack(">I", len(comp))
            + b"".join(struct.pack(">II" if ctts_version == 0 else ">Ii", *r) for r in comp),
        )
        if comp
        else b""
    )
    media = box(b"mdia", mdhd + hdlr + box(b"minf", box(b"stbl", stts + stsz + extra)))
    edts = (
        box(b"edts", box(b"elst", bytes(4) + struct.pack(">IIihh", 1, duration, edit, 1, 0)))
        if edit is not None
        else b""
    )
    return box(b"moov", box(b"trak", edts + media)) + box(b"mdat", b"opaque-media-test-payload")


def load(tmp_path, blob):
    path = tmp_path / "example.mp4"
    path.write_bytes(blob)
    return read_timeline(path)


def test_detects_single_tick_step_with_exact_location(tmp_path):
    timeline = load(tmp_path, fixture([(98, 512), (1, 511), (400, 512)]))
    assert timeline.tick_at(98) == 98 * 512
    assert timeline.tick_at(99) == 99 * 512 - 1
    grid = timeline.grid(Fraction(30))
    assert grid["max_abs_deviation_ticks"] == 1
    assert grid["duration_matches_stts"]


def test_constant_grid_and_identity_edit(tmp_path):
    timeline = load(tmp_path, fixture([(100, 512)], edit=0))
    assert timeline.identity_edit
    assert timeline.grid(Fraction(30))["exact_grid"]


def test_nested_nonidentity_edit_is_refused(tmp_path):
    with pytest.raises(UnsupportedMP4, match="Trimmed"):
        load(tmp_path, fixture([(100, 512)], edit=2))


def test_composition_offset_is_evaluated(tmp_path):
    timeline = load(tmp_path, fixture([(100, 512)], composition=True))
    assert timeline.tick_at(0) == 1
    assert timeline.grid(Fraction(30))["max_abs_deviation_ticks"] == 1


@pytest.mark.parametrize("blob", [b"short", struct.pack(">I4s", 9999, b"moov"), struct.pack(">I4s", 4, b"moov")])
def test_truncation_and_invalid_box_lengths_do_not_pass(tmp_path, blob):
    with pytest.raises(InvalidMP4):
        load(tmp_path, blob)


def test_huge_sample_count_does_not_allocate_per_frame(tmp_path):
    timeline = load(tmp_path, fixture([(4_000_000_000, 1)], scale=30))
    assert timeline.samples == 4_000_000_000
    assert len(timeline.ends) == 1
    assert timeline.grid(Fraction(30))["exact_grid"]


def test_fractional_fps_has_rational_grid(tmp_path):
    timeline = load(tmp_path, fixture([(100, 1001)], scale=30000))
    assert timeline.grid(Fraction(30000, 1001))["exact_grid"]


def test_sample_bounds(tmp_path):
    timeline = load(tmp_path, fixture([(2, 512)]))
    with pytest.raises(IndexError):
        timeline.tick_at(2)
    with pytest.raises(IndexError):
        timeline.tick_at(-1)


def test_fragmented_mp4_is_not_a_clean_result(tmp_path):
    with pytest.raises(UnsupportedMP4, match="Fragmented"):
        load(tmp_path, fixture([(2, 512)]) + box(b"moof", b""))


@pytest.mark.parametrize("signed", [False, True])
def test_reordering_and_delay_are_mapped_to_presentation_order(tmp_path, signed):
    offsets = [(1, 0), (1, 512), (1, -512), (3, 0)] if signed else [(1, 512), (1, 1024), (1, 0), (3, 512)]
    timeline = load(
        tmp_path, fixture([(6, 512)], composition=offsets, ctts_version=int(signed), edit=0 if signed else 512)
    )
    assert [timeline.tick_at(i) for i in range(6)] == [i * 512 for i in range(6)]
    assert timeline.sample_order == [0, 2, 1, 3, 4, 5]
    assert timeline.grid(Fraction(30))["exact_grid"]


def test_duplicate_presentation_pts_are_invalid(tmp_path):
    with pytest.raises(InvalidMP4, match="Duplicate presentation"):
        load(tmp_path, fixture([(6, 512)], composition=[(1, 0), (1, -512), (4, 0)], ctts_version=1))


def test_composition_count_must_cover_decode_samples(tmp_path):
    with pytest.raises(InvalidMP4, match="different sample counts"):
        load(tmp_path, fixture([(6, 512)], composition=[(2, 0)]))

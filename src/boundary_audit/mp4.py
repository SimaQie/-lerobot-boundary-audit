"""Strict, bounded MP4 timing reader inspired by the saved A1 timing audits.

Supports ordinary non-fragmented MP4 with a single video track, composition
offsets in either signed/unsigned form and a single full-span media edit.
Unsupported timelines are explicit exceptions; they never count as clean.
Media payload is skipped. Sample timestamps are evaluated from runs without
allocating an array proportional to video length.
"""

import struct
from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path


class InvalidMP4(ValueError):
    pass


class UnsupportedMP4(ValueError):
    pass


MAX_TABLE_ENTRIES = 100_000
MAX_BOX_PAYLOAD = 16_000_000
MAX_BOXES = 100_000
MAX_PRESENTATION_SAMPLES = 1_000_000


@dataclass(frozen=True)
class Box:
    kind: bytes
    start: int
    end: int


def boxes(stream, start: int, end: int):
    stream.seek(start)
    count = 0
    while stream.tell() < end:
        origin = stream.tell()
        if end - origin < 8:
            raise InvalidMP4("Truncated box header")
        header = stream.read(8)
        if len(header) != 8:
            raise InvalidMP4("Truncated box header")
        size, kind = struct.unpack(">I4s", header)
        header_size = 8
        if size == 1:
            extra = stream.read(8)
            if len(extra) != 8:
                raise InvalidMP4("Truncated extended box header")
            size = struct.unpack(">Q", extra)[0]
            header_size = 16
        elif size == 0:
            size = end - origin
        if size < header_size or origin + size > end:
            raise InvalidMP4("Box exceeds its parent or has an invalid length")
        count += 1
        if count > MAX_BOXES:
            raise InvalidMP4("Too many boxes")
        yield Box(kind, origin + header_size, origin + size)
        stream.seek(origin + size)


def payload(stream, box):
    size = box.end - box.start
    if size > MAX_BOX_PAYLOAD:
        raise UnsupportedMP4("Box payload exceeds parser budget")
    stream.seek(box.start)
    data = stream.read(size)
    if len(data) != size:
        raise InvalidMP4("Truncated payload")
    return data


def unique(children, kind, *, required=True):
    found = [x for x in children if x.kind == kind]
    if len(found) > 1 or (required and not found):
        raise InvalidMP4(f"Expected one {kind.decode('ascii')} box")
    return found[0] if found else None


def timing_header(data):
    if len(data) < 4:
        raise InvalidMP4("Truncated timing header")
    if data[0] == 0 and len(data) >= 20:
        scale, duration = struct.unpack_from(">II", data, 12)
    elif data[0] == 1 and len(data) >= 32:
        scale, duration = struct.unpack_from(">IQ", data, 20)
    else:
        raise UnsupportedMP4("Unsupported or truncated timing header version")
    if scale == 0:
        raise InvalidMP4("Zero timescale")
    return scale, duration


@dataclass
class Timeline:
    timescale: int
    duration: int
    runs: list[tuple[int, int]]
    delta_offsets: list[int]
    duration_offset: int
    mdhd_version: int
    identity_edit: bool
    composition: list[tuple[int, int]] | None = None
    edit_media_time: int = 0
    movie_timescale: int | None = None
    movie_duration: int | None = None
    duration_fields: list[dict] | None = None
    track_count: int = 1

    def __post_init__(self):
        self.ends = []
        self.ticks = []
        n, tick = 0, 0
        for count, delta in self.runs:
            self.ticks.append(tick)
            n += count
            tick += count * delta
            self.ends.append(n)
        self.samples = n
        self.total_ticks = tick
        self.presented = None
        self.sample_order = None
        if self.composition is not None:
            if n > MAX_PRESENTATION_SAMPLES:
                raise UnsupportedMP4("Composition table exceeds presentation-order memory budget")
            values = []
            index = 0
            for count, offset in self.composition:
                for _ in range(count):
                    values.append((self.decode_tick_at(index) + offset, index))
                    index += 1
            values.sort()
            if any(a[0] == b[0] for a, b in zip(values, values[1:])):
                raise InvalidMP4("Duplicate presentation timestamps")
            self.presented = [p for p, _ in values]
            self.sample_order = [i for _, i in values]
        first_raw = self.presented[0] if self.presented else 0
        if self.edit_media_time and self.edit_media_time != first_raw:
            raise UnsupportedMP4(
                "Trimmed media edits are not supported; only full-span reorder-delay edits are accepted"
            )

    def decode_tick_at(self, index: int):
        if not 0 <= index < self.samples:
            raise IndexError("Sample index outside the video")
        run = bisect_right(self.ends, index)
        beginning = self.ends[run - 1] if run else 0
        return self.ticks[run] + (index - beginning) * self.runs[run][1]

    def tick_at(self, index: int):
        if not 0 <= index < self.samples:
            raise IndexError("Sample index outside the video")
        raw = self.presented[index] if self.presented is not None else self.decode_tick_at(index)
        return raw - self.edit_media_time

    def sample_duration(self, index: int):
        if not 0 <= index < self.samples:
            raise IndexError("Sample index outside the video")
        original = self.sample_order[index] if self.sample_order is not None else index
        return self.runs[bisect_right(self.ends, original)][1]

    def end_tick_at(self, index: int):
        return self.tick_at(index) + self.sample_duration(index)

    def grid(self, fps: Fraction):
        if fps <= 0:
            raise ValueError("FPS must be positive")
        interval = Fraction(self.timescale, 1) / fps
        worst, worst_index = Fraction(0), 0
        count_before = 0
        first_deviation = None
        points = []
        # Deviations are linear inside each stts run: endpoints suffice for max.
        scan = [(self.samples, 0)] if self.presented is not None else self.runs
        for count, _ in scan:
            indexes = (
                range(count_before, count_before + count)
                if self.presented is not None
                else sorted({count_before, count_before + count - 1})
            )
            for index in indexes:
                deviation = Fraction(self.tick_at(index)) - index * interval
                if abs(deviation) > abs(worst):
                    worst, worst_index = deviation, index
                if deviation and first_deviation is None:
                    first_deviation = (
                        index
                        if self.presented is not None
                        else count_before
                        if index == count_before
                        else min(index, count_before + 1)
                    )
                if self.presented is None or len(points) < 128 and deviation:
                    points.append({"sample": index, "deviation_ticks": float(deviation)})
            count_before += count
        return {
            "samples": self.samples,
            "timescale": self.timescale,
            "stts_runs": len(self.runs),
            "integral_ticks_per_frame": interval.denominator == 1,
            "max_abs_deviation_ticks": float(abs(worst)),
            "max_abs_deviation_seconds": float(abs(worst) / self.timescale),
            "worst_sample_index": worst_index,
            "first_deviation_sample": first_deviation,
            "composition_offsets": self.composition is not None,
            "edit_media_time_ticks": self.edit_media_time,
            "deviation_points": points[:128],
            "exact_grid": worst == 0,
            "duration_matches_stts": self.duration == self.total_ticks,
            "identity_edit": self.identity_edit,
        }


def read_timeline(path: Path):
    path = Path(path)
    with path.open("rb") as stream:
        top = list(boxes(stream, 0, path.stat().st_size))
        if any(b.kind in {b"moof", b"mfra"} for b in top):
            raise UnsupportedMP4("Fragmented MP4 is not supported")
        moov = unique(top, b"moov")
        children = list(boxes(stream, moov.start, moov.end))
        if any(b.kind == b"mvex" for b in children):
            raise UnsupportedMP4("Fragmented movie is not supported")
        candidates = []
        for track in [b for b in children if b.kind == b"trak"]:
            track_children = list(boxes(stream, track.start, track.end))
            media = unique(track_children, b"mdia")
            media_children = list(boxes(stream, media.start, media.end))
            handler = payload(stream, unique(media_children, b"hdlr"))
            if len(handler) < 12:
                raise InvalidMP4("Truncated handler")
            if handler[8:12] == b"vide":
                candidates.append((track_children, media_children))
        if len(candidates) != 1:
            raise UnsupportedMP4(f"Expected a single video track, found {len(candidates)}")
        track_children, media_children = candidates[0]
        identity_edit = False
        edit_media_time = 0
        duration_fields = []
        movie_timescale = movie_duration = None
        mvhd = unique(children, b"mvhd", required=False)
        if mvhd:
            movie_header = payload(stream, mvhd)
            movie_timescale, movie_duration = timing_header(movie_header)
            duration_fields.append(
                {
                    "field": "mvhd.duration",
                    "offset": mvhd.start + (16 if movie_header[0] == 0 else 24),
                    "width": 4 if movie_header[0] == 0 else 8,
                    "before": movie_duration,
                    "timescale": movie_timescale,
                }
            )
        tkhd = unique(track_children, b"tkhd", required=False)
        if tkhd:
            track_header = payload(stream, tkhd)
            if not track_header or track_header[0] not in (0, 1):
                raise UnsupportedMP4("Unsupported track-header version")
            offset, width = (20, 4) if track_header[0] == 0 else (28, 8)
            if len(track_header) < offset + width:
                raise InvalidMP4("Truncated track duration")
            duration_fields.append(
                {
                    "field": "tkhd.duration",
                    "offset": tkhd.start + offset,
                    "width": width,
                    "before": int.from_bytes(track_header[offset : offset + width], "big"),
                    "timescale": movie_timescale,
                }
            )
        edit_container = unique(track_children, b"edts", required=False)
        if edit_container:
            edit_children = list(boxes(stream, edit_container.start, edit_container.end))
            edit_box = unique(edit_children, b"elst")
            edit = payload(stream, edit_box)
            if len(edit) < 8:
                raise InvalidMP4("Truncated edit list")
            entry_count = struct.unpack_from(">I", edit, 4)[0]
            if edit[0] == 0 and len(edit) == 20 and entry_count == 1:
                edit_duration, media_time, rate_integer, rate_fraction = struct.unpack_from(">Iihh", edit, 8)
            elif edit[0] == 1 and len(edit) == 28 and entry_count == 1:
                edit_duration, media_time, rate_integer, rate_fraction = struct.unpack_from(">Qqhh", edit, 8)
            else:
                raise UnsupportedMP4("Only one full-span media edit is supported")
            if media_time < 0 or (rate_integer, rate_fraction) != (1, 0):
                raise UnsupportedMP4("Non-identity edit list requires a different timeline mapping")
            identity_edit = media_time == 0
            edit_media_time = media_time
            duration_fields.append(
                {
                    "field": "elst.segment_duration",
                    "offset": edit_box.start + 8,
                    "width": 4 if edit[0] == 0 else 8,
                    "before": edit_duration,
                    "timescale": movie_timescale,
                }
            )
        mdhd = unique(media_children, b"mdhd")
        header = payload(stream, mdhd)
        scale, duration = timing_header(header)
        minf = unique(media_children, b"minf")
        stbl = unique(list(boxes(stream, minf.start, minf.end)), b"stbl")
        table_children = list(boxes(stream, stbl.start, stbl.end))
        ctts = unique(table_children, b"ctts", required=False)
        composition = None
        if ctts:
            comp = payload(stream, ctts)
            if len(comp) < 8 or comp[0] not in (0, 1):
                raise InvalidMP4("Invalid composition-offset version")
            comp_count = struct.unpack_from(">I", comp, 4)[0]
            if not 0 < comp_count <= MAX_TABLE_ENTRIES or len(comp) != 8 + comp_count * 8:
                raise InvalidMP4("Invalid composition-offset entry count")
            fmt = ">II" if comp[0] == 0 else ">Ii"
            composition = [struct.unpack_from(fmt, comp, 8 + i * 8) for i in range(comp_count)]
            if any(count == 0 for count, _ in composition):
                raise InvalidMP4("Empty composition-offset run")
        stts = unique(table_children, b"stts")
        data = payload(stream, stts)
        if len(data) < 8 or data[0] != 0:
            raise InvalidMP4("Invalid stts header")
        count = struct.unpack_from(">I", data, 4)[0]
        if count == 0 or count > MAX_TABLE_ENTRIES or len(data) != 8 + count * 8:
            raise InvalidMP4("Invalid stts entry count or length")
        runs = [struct.unpack_from(">II", data, 8 + i * 8) for i in range(count)]
        if any(n == 0 or delta == 0 for n, delta in runs):
            raise InvalidMP4("Zero sample count or duration")
        if composition and sum(n for n, _ in composition) != sum(n for n, _ in runs):
            raise InvalidMP4("Composition and decode tables cover different sample counts")
        stsz = unique(table_children, b"stsz", required=False)
        if stsz is None:
            raise UnsupportedMP4("This reader requires a stsz sample-size table")
        sizes = payload(stream, stsz)
        if len(sizes) < 12 or sizes[0] != 0:
            raise InvalidMP4("Invalid stsz header")
        fixed_size, sample_count = struct.unpack_from(">II", sizes, 4)
        if sample_count != sum(n for n, _ in runs):
            raise InvalidMP4("stsz and stts sample counts disagree")
        expected_length = 12 if fixed_size else 12 + sample_count * 4
        if len(sizes) != expected_length:
            raise InvalidMP4("Invalid stsz payload length")
        timeline = Timeline(
            scale,
            duration,
            runs,
            [stts.start + 12 + i * 8 for i in range(count)],
            mdhd.start + (16 if header[0] == 0 else 24),
            header[0],
            identity_edit,
            composition,
            edit_media_time,
            movie_timescale,
            movie_duration,
            duration_fields,
            len([x for x in children if x.kind == b"trak"]),
        )
        if movie_timescale:
            # Movie/edit duration may be rounded by one movie tick. A genuine
            # cropping edit must not silently look like a full-span timeline.
            presented_duration = Fraction(timeline.end_tick_at(timeline.samples - 1), scale)
            for field in duration_fields:
                if field["field"] == "elst.segment_duration" and abs(
                    Fraction(field["before"], movie_timescale) - presented_duration
                ) > Fraction(1, movie_timescale):
                    raise UnsupportedMP4("Edit duration trims or extends the presented timeline")
        return timeline

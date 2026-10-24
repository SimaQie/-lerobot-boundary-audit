# 0.5.0 — 2026-10-25

The CPU audit path remains the supported product. This release adds official
loader-returned pixel evidence, a unified environment diagnosis, a bounded
reference-frame cache, fractional-FPS/timebase controls and a release gate.

## Actual official-loader pixels

`probe-loader --visuals` now captures the tensor returned by the installed
`LeRobotDataset` at the zero-delta slot, plus independent expected/previous/next
sequential PyAV references. It records returned row/episode/camera labels,
expected ordinals, source/image SHA-256, comparison status and consumer
versions. The evidence is offline HTML with relative image paths; it is not a
re-decode relabelled as loader output.

The reproducible ALOHA example contains clean, authored +20 ms offset and
repaired groups. In the offset copy the loader still returned the expected row
labels while the pixels matched the next frame; the repaired copy matched the
expected frame again. Source and image details:
[docs/real-robot-loader-pixels.md](docs/real-robot-loader-pixels.md).

## Diagnosis and cache

- `doctor` checks Python, audit/decode dependencies, FFmpeg CLI, an optional
  official consumer and a dataset storage audit. It writes offline JSON/HTML
  when `--out` is supplied and never claims a loader-pixel or physical-
  synchronization result.
- `probe-loader` caches reference frames with a content-addressed key covering
  video SHA-256, requested ordinals, FPS and probe/driver identity. Cache misses,
  corrupt entries and `--no-cache` fall back to decoding; cache state never
  changes the verdict. Reports include hit/miss counts, decode seconds, disk
  bytes and peak RSS.

On the 50-episode ALOHA sample with six query rows, the same cold/warm query took
19.62 s / 3.29 s, with reference decoding 16.16 s / 0 s, a 3.57 MB cache entry,
and identical verdicts and per-check records.

## Fractional FPS and timescales

Boundary comparisons accept up to one MP4 sample tick (capped at half a frame) of timestamp quantization for
non-integer FPS or coarse timescales; a real one-frame offset still fails.
Tests cover 30000/1001 FPS and 30 FPS on a 1,000 tick/s timeline. LeRobot's
public writer declares integer FPS, so non-integer producer support is not
claimed.

## Compatibility and validation

- LeRobot 0.6.1 and 0.6.0: 208/208 bundled conformance each.
- 96 real-footage probe runs: 72 pass / 24 partial, with no missing or
  unexpected query slots.
- 16/16 official boundary verifies and 8/8 full real-source validations.
- Repair restores derived copies byte-exactly; sources remain unchanged.
- Local regression tests, Ruff, Windows/Linux CI and isolated wheel installation are release gates.

PARTIAL/ambiguous real repeated frames remain PARTIAL; they are not converted to
PASS. No newer stable LeRobot release than 0.6.1 was available for this round.

## Final release review

- Cap automatic quantization tolerance at half a frame, retaining detection on one-tick-per-frame streams.
- Invalidate reference caches when PyAV/FFmpeg/NumPy changes and verify cached RGB digests; damaged ZIP entries fall back to decoding.
- Shorten evidence filenames for Windows source builds and include the release checker and compact results in the sdist.
- Validate embedded wheel/sdist metadata against the tag; add actual loader pixel and cold/warm cache checks to CI.

## Release mechanics

`research/check_release.py` verifies tag/package/runtime/CITATION versions,
release notes and artifact names. The tag workflow runs lint/tests, checks the
built wheel and sdist, and installs the wheel in an isolated environment before
publishing assets. A published release is never overwritten by a main-branch
push.

See [CHANGELOG.md](CHANGELOG.md) and [USAGE.md](USAGE.md) for details.

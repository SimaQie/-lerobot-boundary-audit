# v0.5.0 release review — 2026-10-25

Reviewed incoming main `6bd387642298ede61635f6bfee57af76da86f906` against
`938d1a1`. The remote workstation matrix in README.md remains the historical
baseline; this review does not re-label it as a new Windows hardware run.

## Fixed before release

- Limit the automatic one-tick quantization allowance to half a frame. A
  one-tick-per-frame MP4 must still report all authored one-frame offsets.
- Include PyAV, FFmpeg library versions, NumPy and platform in cache identity;
  verify RGB payload digests, reject oversize entries and handle damaged ZIP
  members as cache misses. Cache schema v2 invalidates prior caches.
- Capture more than one selected camera in visual evidence; explicitly label
  ordinal/FPS timestamps as nominal rather than measured container PTS.
- Shorten media basenames after reproducing a Windows sdist path-length failure.
- Ship check_release.py, release notes and compact baseline results in the sdist;
  check embedded package name/version rather than just a filename substring.
- Correct user-guide links, media attribution, release date and disk-space estimate.
- Add actual-loader visual and cold/warm cache assertions to the official-reader CI job.

## Local validation

Windows, Python 3.11 audit environment; separate Python 3.12 / LeRobot 0.6.1
consumer, CPU decode, shared FFmpeg. Ruff passes; pytest: 137 passed, one skipped
(Windows symlink permission). Source and wheel builds and isolated installation
checks are required before the tag is pushed.

The ALOHA clean/offset/repaired example was rerun against the actual loader:
clean and repaired selected visuals match expected frames, the authored-offset
visuals are wrong_frame, all three preview sets are complete and source hashes
remain unchanged. Clean/repaired overall results remain PARTIAL because other
repeated-frame checks are ambiguous. Local FFmpeg lacks libx264, so optional
source-clip regeneration is unavailable here; the committed remote-generated
clip is retained with its original recorded provenance.

A two-camera bundled-fixture probe passes with four visual records. Cold and
warm records are identical; cold writes two entries and warm hits both entries
without reference decoding. The full remote two-version/four-source matrix is
retained as recorded in README.md; no new GPU decoding claim is made.

## Remaining scope

No physical synchronization or natural upstream defect is claimed. Visuals
cover selected row/camera pairs. RGB heuristics retain ambiguity. Cache storage
limits apply per entry, not as automatic eviction of the whole cache directory.
Published tags/assets must not be overwritten. GitHub CI and the tag workflow
provide the final release execution record.

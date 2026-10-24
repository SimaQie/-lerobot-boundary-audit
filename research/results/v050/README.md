# v0.5.0 loader-pixel evidence and reader compatibility

Base: main `938d1a1`. Development branch: `feat/v050-loader-pixel-evidence`.
Stable consumer versions: LeRobot 0.6.1 (latest on PyPI/GitHub) and 0.6.0
(previous stable; no newer stable exists as of 2026-10-25). Torch 2.10.0+cpu,
TorchCodec 0.10.0, PyAV 15.1.0, FFmpeg 7.1.x shared.

## What changed

- `probe-loader --visuals` now captures **actual `LeRobotDataset` item tensors**
  at the zero-delta slot, plus independent sequential PyAV expected/previous/next
  references. It records row, episode, camera, delta, expected ordinal, returned
  labels, comparison, source SHA-256, image SHA-256, consumer versions and
  explicit provenance. It does not re-decode a frame and call it loader output.
- `--allow-audit-failure` permits controlled-fault copies to run while recording
  the failed preflight; it never changes the audit verdict.
- Bounded visual queries/bytes and tool-owned stale-image cleanup; offline HTML
  uses relative paths. Budget exhaustion is VISUAL partial, not a probe PASS or
  FAIL change.
- Added a reproducible ALOHA clean/offset/repaired example and 20-second clip.
- Added `doctor` for read-only host/consumer/dataset diagnosis with offline
  JSON/HTML and explicit missing-item actions.
- Added content-addressed reference-frame caching with invalidation, corrupt
  fallback, cache-off mode, cold/warm timings, disk bytes and peak RSS.
- Added fractional-FPS and coarse-timescale controls; one sample tick is accepted
  while a full frame offset remains a failure.
- Hardened the tag release workflow with metadata, test, artifact and isolated
  wheel-install gates before publishing.

## Actual-loader pixel evidence (ALOHA episode 25, left wrist)

See [docs/real-robot-loader-pixels.md](../../docs/real-robot-loader-pixels.md)
and [assets](../../docs/assets/aloha-loader-pixels).

| Group | Probe | Visual | Loader pixels |
|---|---|---|---|
| clean | partial (other repeated frames) | complete, 2 records | loader hash = expected reference |
| authored +20 ms offset | fail (`wrong_frame`) | complete, 2 records | loader hash = next reference, not expected |
| repaired | partial (same repeated frames) | complete, 2 records | loader hash = expected reference again |

The loader still returned labels `index=10000, episode_index=25, frame_index=0`
in the offset copy while the pixels were frame 1. Labels alone are not pixel
identity. The source was unchanged; the offset/repair copies are derived.

## Reader compatibility

| Check | 0.6.1 | 0.6.0 |
|---|---:|---:|
| Bundled conformance (all 13 cases/backends/phases) | 208/208 | 208/208 |
| Official boundary verify (4 sources × 2 backends) | 8/8 pass | 8/8 pass |
| Probe matrix (4 sources × 2 backends × 6 phases) | 48 runs: 36 pass / 12 partial | 48 runs: 36 pass / 12 partial |
| Probe coverage | 128/128 rows, 616 frame checks, 0 missing, 0 unexpected | same |
| Full real validation (4 sources) | 4/4 `expected_outcomes_met` | 4/4 `expected_outcomes_met` |
| Repair exact restore / source unchanged | yes | yes |

The 24 partial probe runs are ALOHA phases; repeated/near-repeated real frames
remain ambiguous by design. `verify` requested/checked 5,508 boundary queries
across the 16 source/version/backend combinations.

## Environment doctor and unified entry

`doctor` checks Python, audit/decode dependencies, FFmpeg CLI, an optional official
consumer and a dataset storage audit. On this host with the ALOHA sample and the
0.6.1 consumer it reported `partial` only because no FFmpeg executable was on
`PATH` (PyAV/FFmpeg libraries were present); passing `--ffmpeg-bin` made the full
doctor status `pass`. The dataset and official consumer checks both passed. It
records host GPU inventory but makes no GPU-decode or loader-pixel claim.

## Reference-frame cache and performance

Same ALOHA source, camera, six query rows, 50 episodes and 20,000 rows:

| Run | Elapsed | Reference decode | Cache | Peak RSS |
|---|---:|---:|---|---:|
| cold | 19.62 s | 16.16 s | 1 miss, 3,567,087-byte write | 996,261,888 B |
| warm | 3.29 s | 0 s | 1 hit, 3,567,087-byte read | 986,300,416 B |

Both runs returned `partial` with 6 checked rows, 7 passing and 11 ambiguous
frame checks, zero errors, and **identical records**. The cache key contains the
video SHA-256, requested ordinals, FPS and driver/tool identity, so content or
code changes invalidate it. Corrupt/missing entries fall back to decoding;
`--no-cache` disables reads and writes.

## Timebase controls

- A 30000/1001 FPS synthetic timeline passes the audit grid.
- A 30 FPS stream represented on a 1,000 tick/s timeline passes with one sample
  tick of quantization.
- The same rounded timeline with a real one-frame offset still fails.
- LeRobot's public writer declares integer FPS; no non-integer producer support
  is claimed.

## Release gate

`research/check_release.py` checks tag/package/runtime/CITATION versions, release
notes and whether exactly one wheel/sdist carries the tag version. The release
workflow now runs lint/tests and these checks, then installs the wheel in an
isolated environment and runs `check_distribution.py` before publishing assets.
A local 0.5.0 wheel/sdist build and isolated install passed; no tag or Release
was created in this round. Current-code reruns also passed 133 tests, Ruff,
208/208 conformance on both 0.6.1 and 0.6.0, and an ALOHA TorchCodec verify with
300 boundary queries.

## Legal controls and failure scope

- Legal subset, padding, long-window, random/repeated and persistent-worker
  paths are covered by conformance and probe phases; no missing/unexpected slots.
- `action-window-corrupt` is detected by the conformance oracle, but
  `repair-plan` returns `no_changes`: action corruption is outside repair scope.
- ALOHA repeated frames yield PARTIAL/ambiguous, not false PASS.
- The cache is an optimization only; its hit/miss state is never part of the
  verdict.

## Open items (not claimed complete)

- No newer stable LeRobot than 0.6.1 was available; 0.6.0 is previous stable.
- Visual evidence covers selected query rows, not whole-dataset or physical
  synchronization.
- No tag or GitHub Release was created in this development round.

Raw local runs are under `research/runs/v050/` (not committed); public compact
summary is `research/results/v050/summary.json`.

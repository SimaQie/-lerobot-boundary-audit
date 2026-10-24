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

## Legal controls and failure scope

- Legal subset, padding, long-window, random/repeated and persistent-worker
  paths are covered by conformance and probe phases; no missing/unexpected slots.
- `action-window-corrupt` is detected by the conformance oracle, but
  `repair-plan` returns `no_changes`: action corruption is outside repair scope.
- ALOHA repeated frames yield PARTIAL/ambiguous, not false PASS.
- Non-integer FPS/timebase-rounding fixtures were not added in this round.

## Open items (not claimed complete)

- No environment doctor/unified diagnosis command in this round.
- No reference-decode cache/invalidation/performance benchmark in this round.
- No newer stable LeRobot than 0.6.1 was available; 0.6.0 is previous stable.
- Visual evidence covers selected query rows, not whole-dataset or physical
  synchronization.

Raw local runs are under `research/runs/v050/` (not committed); public compact
summary is `research/results/v050/summary.json`.

# Changelog

## 0.4.2 — 2026-10-24

- Add pinned real-data presets for CMU Stretch and UTokyo xArm; accept all
  `SAMPLES` entries in the download and validation commands.
- Keep the CPU audit, original marker conformance, official-reader boundary
  checks, full-loader probes, guarded repair and exact restoration as the
  supported product path.
- Validate the CPU path on an RTX 4090/WSL2 machine: 208/208 conformance,
  78/78 CUDA-build CPU-path conformance, four source audits and four full
  validations. The official LeRobot reader remains CPU-only.
- Clean up exploratory GPU/TorchCodec benchmark and review material; document
  only the validated GPU-machine CPU path.

## 0.4.1 — 2026-10-20

- Reject fractional, floating, boolean and other noninteger reader labels.
- Detect exact matches to repeated wrong neighbours when the expected frame is
  excluded; retain ambiguity when the expected frame is one of the matches.
- Check action shapes before values; independently account for every requested
  query slot; retain per-camera ambiguity reasons.
- Add seeded time-stratified sampling without image-based selection.

## 0.4.0 — 2026-10-14

- Verify global row indexes, episode ranges and data/video shard references.
- Persist prerequisite failures as structured reports.
- Add the offline 13-case fixture, `demo`, long windows, random/repeated reads
  and persistent workers.
- Add ordinary-footage `probe-loader` with bounded sequential reference,
  action/padding checks and explicit ambiguity.

## 0.3.0 — 2026-10-13

- Original CRC-checked camera/episode/frame pixel identities defined before
  encoding; full installed loader conformance across backends and read modes.
- Camera-swap/offset negative controls, guarded repair and byte-exact restore.
- Portable HTML/JSON evidence and bundled fixture.

## 0.2.0 — 2026-10-13

- LeRobot v3 row/MP4 timeline diagnostics, local decode, offline reports and
  explicit unsupported-layout results.

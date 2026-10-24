# Changelog

## Unreleased (planned 0.5.0)

- Add opt-in bounded local-PyAV boundary frame previews with ordinal, neighbour
  and observed-frame evidence.
- Add `probe-loader --visuals`: capture actual LeRobotDataset item tensors,
  independent expected/previous/next references, source/image hashes, returned
  labels and offline relative HTML evidence. Add bounded byte/query handling,
  stale-image cleanup and `--allow-audit-failure` for controlled fault copies.
- Add a reproducible ALOHA clean/authored-offset/repaired loader-pixel example,
  public images/JSON/HTML, and a 20-second MIT-attributed source clip.
- Validate two stable LeRobot generations (0.6.1 latest; 0.6.0 previous; no
  newer stable release exists): 208/208 conformance each, 16/16 official verify,
  96 probe runs (72 pass/24 partial, no missing/unexpected slots), and 8/8 full
  real validations. GPU remains out of scope for this CPU product path.


## 0.4.3 — 2026-10-24

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
- Add `--version` and align package, runtime and citation versions.
- Fingerprint all audit modules and the current real-sample validation script
  instead of removed development scripts.
- Check installed distributions on Windows/Linux: bundled demo, fault detection,
  guarded repair, exact restoration and unsafe-repair rejection.
- Clarify partial-camera selection, validation scope and source installs.

## 0.4.2 — 2026-10-24

- Publish the CPU audit and guarded repair tool as a versioned release.
- Include independent time mapping, complete evidence accounting and JSON-safe
  failure reports in the accompanying research preview work.

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

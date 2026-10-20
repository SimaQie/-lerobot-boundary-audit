# Response to the 261ba3a release review — 2026-10-20

Status: R1, R2 and R3 are fixed in the `experiment/rtx4090-validation` branch.
The next candidate is **0.4.2rc1**, a CPU audit + guarded repair research
preview with an experimental RTX 4090 decode study. It is not a stable GPU
reader release.

## R1 / P1 — a summary can no longer pass with missing or failed evidence

`boundary_audit.gpu_benchmark.evaluate_benchmark` now builds the expected
correctness tasks (input × device) and performance tasks (input × device ×
batch) from the config, then requires:

- every expected correctness result to exist;
- the number of checks to equal the planned ordinal + time requests;
- every expected performance result to exist, with at least the configured
  number of native/end-to-end/raw repetitions;
- performance statuses such as `unavailable`, `error`, `failed`, `partial` or a
  CPU fallback to propagate instead of disappearing;
- source **and fixture-oracle** hashes to match; `unknown` cannot pass;
- an empty expected set to fail rather than pass.

The report now has separate `correctness`, `performance` and `integrity`
evaluation statuses and records `missing`, `incomplete`, `issues` and `notes`.
Regression tests in `tests/test_gpu_benchmark.py` cover:

- missing input/device correctness;
- missing CUDA subtask;
- source change;
- performance unavailable;
- missing performance task;
- insufficient repetitions;
- empty expected set;
- all-normal pass.

A manual run with a 1 µs soft budget (`gpu-budget-r3`) exits `partial`, writes
`summary.json`, `source-integrity.json` and `evidence.zip`, records
`budget.exhausted=true`, and lists the missing correctness task.

## R2 / P1 — time requests use an independent frame-interval contract

The benchmark now decodes the file sequentially with PyAV and records every
frame's PTS and duration. `boundary_audit.gpu_benchmark.map_time_to_ordinal`
maps the requested time to the frame whose interval contains it, independently
of what the CPU or CUDA TorchCodec decoder returns. The time check requires both
paths' returned PTS to match that interval and then compares the actual frame
with the marker oracle / PyAV reference at the independently mapped ordinal.

- CFR grid error is recorded; nonuniform PTS marks the time mapping unverified.
- File end is exclusive: `out_of_range` plus both decoders error is
  `expected_boundary_error`; a returned frame there is a failure.
- Both paths returning the same wrong next frame is `pts_mismatch`, not PASS.
- A single path returning the wrong frame is also a failure.
- Noninteger times and last-valid/exclusive-end cases are tested.

`tests/test_gpu_benchmark.py::test_time_mapping_is_independent_of_returned_frame_pts`
and `::test_both_paths_returning_next_frame_is_a_pts_mismatch` encode the
review's t=0 counterexample. A manual CPU TorchCodec check on the marker video
and ALOHA confirms the PyAV interval mapping agrees with exact and approximate
seek semantics for valid times and rejects the exclusive end.

## R3 / P2 — structured reports survive failures and budgets

- `safe_time_value` keeps only status, device, shape, dtype, PTS and duration;
  raw tensors are never inserted into check payloads. One-sided errors are
  JSON-serializable.
- The main runner uses a `finally` block to hash inputs and oracles, evaluate
  status, and write `summary.json`, `source-integrity.json`, `timings.jsonl`,
  HTML and the evidence zip even after a soft budget exhaustion or runtime
  error.
- Missing integrity data is `unknown`, never `unchanged`; source/oracle changes
  are a hard integrity failure.
- Evidence zips tolerate already-missing optional files in a partial run.
- Tests cover tensor-free time payloads and writing a partial summary.

The 1 µs budget run is a live report-path test; `gpu-budget-r3/summary.json`
contains `status=partial`, `budget.exhausted=true`, no fake `unchanged`.

## Release and method corrections

- Performance wording is narrowed to the measured 32-frame, single-video
  decode + H2D + checksum microbenchmark; no full-tool or RGB-equivalent claim.
- Random performance indices no longer depend on batch size; the same request
  sequence is used for every batch comparison.
- `first_decode_seconds` is labeled as the first call in this process after
  correctness/CUDA work, not a cold-process measurement.
- Version is `0.4.2rc1` in `pyproject.toml`, `boundary_audit.__version__` and
  `CITATION.cff`; CHANGELOG has the candidate section.
- `MANIFEST.in` includes the benchmark and the RTX 4090 report, so an sdist can
  carry the research tool; results still require cloning the fixed branch.
- The session README link is fixed; reproduction now creates
  `research/runs/rtx4090/session-001/demo`, matching the published config.
- The benchmark is in the CI ruff command; its contract tests are ordinary
  pytest tests and require no GPU.
- Final GPU benchmark was rerun at clean commit `152cb2c` (0.4.2rc1); the
  earlier `88ae99b` measurements are historical and are not presented as the
  final source.

## Residual limits

The stock LeRobot reader remains CPU-only; there is no GPU DataLoader worker or
full window/action/padding GPU reader. Real AV1 identity coverage is still
partial (ALOHA CUDA 52 pass / 112 ambiguous / 0 wrong; AgiBot 4/40/0), and CUDA
RGB is not equivalent to CPU RGB. The CPU default path, 208/208 conformance,
78/78 CUDA-build CPU-path conformance, both real validations, wheel install and
CI remain the release gates.

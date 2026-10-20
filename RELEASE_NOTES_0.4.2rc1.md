# LeRobot Boundary Audit 0.4.2rc1 — research preview

Release date: 2026-10-20. Tag: `v0.4.2rc1`. This is the first versioned GitHub
preview, intentionally carrying the `rc1` marker. It is not a stable GPU-reader
or general-purpose robot-data platform release.

## Support scope

Supported default path:

- CPU-only LeRobot v3 boundary audit, offline HTML/JSON evidence, bounded
  ordinary-footage loader probes, independent marker identity conformance and
  guarded copy-based repair with exact restoration.
- Install from the tag and use the normal CPU audit commands. No Torch, CUDA,
  model weights or GPU are required.

Experimental research path:

- `research/benchmark_gpu_decode.py` with a CUDA consumer compares explicit
  TorchCodec `device="cpu"` and `device="cuda"` decoding.
- The stock LeRobot 0.6.1 reader remains CPU-only; there is no `--device` flag
  in `probe-loader` and no GPU DataLoader/reader adapter.
- GPU results are exploratory. CUDA RGB is not equivalent to CPU RGB, real AV1
  identity coverage remains partial, and the measured speedup is only a
  32-frame, single-video decode + H2D + checksum microbenchmark with a reused
  decoder. It is not a full-audit, training or end-to-end tool speedup.

## Install and first run

```sh
git clone https://github.com/SimaQie/-lerobot-boundary-audit.git
cd -- -lerobot-boundary-audit
git checkout v0.4.2rc1
python -m venv .venv
.venv/bin/python -m pip install ".[repair]"
.venv/bin/lerobot-boundary-audit --help
.venv/bin/lerobot-boundary-audit demo --out demo-result
```

Start with [USAGE.md](https://github.com/SimaQie/-lerobot-boundary-audit/blob/main/USAGE.md)
or [USAGE.zh-CN.md](https://github.com/SimaQie/-lerobot-boundary-audit/blob/main/USAGE.zh-CN.md):
it uses the bundled 13-case suite to show clean/faulty audits, expected exit
codes, content checks that require an official consumer, and the repair/restore
flow.

Windows uses `.venv/Scripts/python.exe` and `.venv/Scripts/lerobot-boundary-audit.exe`.
The wheel and sdist are attached build artifacts; the sdist also contains the
GPU research script and the RTX 4090 report.

## What is verified

- Original fixture conformance: 208/208 expected outcomes (13 cases × 2
  official backends × 8 read modes) on the CPU path.
- CUDA build with the stock CPU reader: 78/78 expected outcomes; sampling
  identical to the CPU build; requested/observed decode device remains CPU.
- AgiBot and ALOHA pinned samples: baseline, official readers 60/60 and 300/300,
  full PTS references, authored offset localization, repair, official recheck,
  exact restore, index-corruption rejection and unchanged source.
- Explicit CUDA smoke: tensors on `cuda:0`, no CPU fallback, cuvid decoders
  present. Fixture fault identities remain detected on both devices; real AV1
  has no detected wrong frame but 52/112 (ALOHA) and 4/40 (AgiBot) pass/ambiguous
  results on CUDA.
- Benchmark evidence completeness: expected input × device × batch tasks must
  all exist; missing/unavailable/partial/error tasks, short repetitions, source
  or oracle changes, zero repeats, or empty expected sets cannot PASS.
- Time requests use independent sequential PyAV PTS/duration intervals; two
  decoders returning the same wrong next frame is a failure.
- Failure reports remain JSON-safe and are written after soft budget exhaustion
  or runtime errors.

Final GPU benchmark: source `152cb2c`, tool `0.4.2rc1`, status `partial`
(expected real-frame ambiguity), integrity pass, no missing or incomplete
tasks. ALOHA and AgiBot microbenchmark e2e ratios are 1.37–2.34× under the stated
scope; see the evidence directory for raw timings and color metrics.

## Review fixes included

- Measured host/timezone and source provenance; separate requested/observed
  decode devices; venv symlink preservation.
- Independent time mapping, evidence-completeness evaluator, JSON-safe errors
  and final report persistence (the previous R1/R2/R3 items).
- Positive-integer validation for repeats/frames/batch sizes, nonnegative
  warmup and finite positive wall-clock budget, including CLI overrides; a
  performance subtask must explicitly be `pass` to contribute to a PASS.

## Checks

- 134 pytest tests; ruff clean (including the research benchmark).
- GitHub Actions: Ubuntu/Windows × Python 3.11/3.12 plus the official-loader
  job. Standard runners have no GPU, so hardware conclusions come from the
  separately uploaded evidence.
- Wheel and sdist build; fresh wheel install with `[repair]`, offline demo and
  26/26 single-phase conformance; sdist includes the benchmark.
- Fresh-clone check of the pushed branch: 130 tests at that commit, demo and
  public CPU benchmark config. It reused the CPU consumer and read-only sample
  symlinks, so it is not a from-zero GPU-stack install.

## Known limitations

- WSL2 on Windows, one RTX 4090, one driver/software stack; not bare-metal Linux.
- Two real AV1 samples at 640-wide resolution; no codec/resolution sweep and no
  GPU workers, multi-GPU or full LeRobot GPU reader.
- No physical synchronization, natural-upstream-defect, training or robot-success
  claim.
- Five timed repetitions per performance group; medians only, no p95, no OS
  page-cache clearing.
- GPU RGB differs from CPU RGB; ambiguity is retained rather than thresholded
  away.

## Evidence

- `research/results/rtx4090/session-001/README.md`
- `research/RTX4090_2026-10-20.md`
- `research/REVIEW_RESPONSE_2026-10-20.md`
- `research/results/rtx4090/session-001/evidence.zip`

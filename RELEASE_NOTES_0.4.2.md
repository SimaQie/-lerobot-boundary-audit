# LeRobot Boundary Audit 0.4.2

Release date: 2026-10-24. This is the CPU audit/repair release.

## Supported scope

- LeRobot v3 boundary/storage audit with offline HTML/JSON reports.
- Independent marker identity conformance for the bundled 13-case suite.
- Optional official LeRobot decoder checks and full-loader probes.
- Guarded copy-based repair for narrow episode-offset/CFR grid defects, with
  exact restoration and source hashes.
- Four pinned real-data presets: AgiBotWorld2026 subset, ALOHA screw driver,
  CMU Stretch and UTokyo xArm.

The product is CPU-only. GPU machines run the same CPU pipeline. No explicit
CUDA decode path or GPU reader is part of this release.

## Install

```sh
git clone https://github.com/SimaQie/lerobot-boundary-audit.git
cd -- lerobot-boundary-audit
git checkout v0.4.2
python -m venv .venv
.venv/bin/python -m pip install ".[repair]"
.venv/bin/lerobot-boundary-audit demo --out demo-result
```

See [USAGE.md](USAGE.md) / [USAGE.zh-CN.md](USAGE.zh-CN.md).

## Validation

- Core test suite: 110 passed after removal of exploratory GPU tests.
- Original fixture conformance: 208/208.
- CUDA-build CPU-path conformance: 78/78; requested/observed decoder is CPU.
- Four real sources: audit pass; full validation `expected_outcomes_met`;
  official PyAV/TorchCodec boundary checks pass; repairs restore exactly;
  sources unchanged.
- RTX 4090/WSL2 CPU-path validation: see
  [research/GPU_MACHINE_VALIDATION.md](research/GPU_MACHINE_VALIDATION.md).

## Limits

Selected cameras only; bounded samples; PARTIAL/ambiguous is retained; no
physical synchronization, training, robot-success or natural-defect claim.
GPU decoding is not part of the supported product.

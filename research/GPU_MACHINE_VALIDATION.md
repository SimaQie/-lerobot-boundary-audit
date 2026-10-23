# Validation on a GPU-equipped host

This summary records validation of the supported **CPU data pipeline** on a
GPU-equipped workstation. A GPU is optional; all commands below use CPU decoding.

## Recorded environment

- Run date: 2026-10-24.
- Baseline commit: `61719d0823454345e8fc0d6ceed3e0831e409bbf`.
- Host: WSL2 Ubuntu 26.04.1 on Windows 11; RTX 4090, 24,564 MiB.
- Driver: 610.88; CUDA UMD: 13.3; Python: 3.12.15.
- Tested upstream reader: LeRobot 0.6.1, with PyAV and TorchCodec backends.

These are the recorded baseline results, not a new GPU hardware run for every
subsequent patch. Current source and distribution checks are reported separately
by [CI](https://github.com/SimaQie/lerobot-boundary-audit/actions/workflows/tests.yml).

## Results and interpretation

| Check | Recorded result |
|---|---|
| Original bundled fixture conformance | 208/208 expected outcomes |
| CUDA-build consumer, CPU decoding | 78/78 expected outcomes; requested/observed/output device CPU |
| AgiBot audit | pass; 60/60 boundary queries decoded |
| ALOHA audit | pass; 300/300 |
| CMU Stretch audit | pass; 405/405 |
| UTokyo xArm audit | pass; 612/612 |
| Four full validation workflows | `expected_outcomes_met`; official PyAV/TorchCodec checks pass, authored offset localized/repaired/restored, index corruption rejected, sources unchanged |

A conformance PASS includes expected detection of intentionally faulty inputs.
`expected_outcomes_met` is the validation workflow's status, not a claim that
every real-footage probe passed. Repeated or insufficiently distinct frames can
leave `probe-loader` results partial; those checks remain unresolved.

The stock LeRobot 0.6.1 reader uses CPU decoding with both CPU and CUDA Torch
builds. These runs establish compatibility with the workstation's CPU pipeline;
they provide no GPU decoding or GPU performance result.

This repository retains the summary and reproducible commands rather than raw
machine logs, downloaded videos or derived datasets. Re-running validation
produces JSON/HTML reports, source hashes, environment details and code provenance
under the chosen output directory.

## Reproduction

Install the auditor and separate official-reader environment using
[USAGE.md](../USAGE.md). A representative Linux/WSL run:

```sh
.venv/bin/lerobot-boundary-audit --version
.venv/bin/python -m pytest -q
.venv/bin/lerobot-boundary-audit demo --out demo-result
.venv/bin/lerobot-boundary-audit conformance demo-result \
  --python .consumer-cpu/bin/python --jobs 2 --out reports/conformance
.venv/bin/lerobot-boundary-audit download cmu_stretch --out samples/cmu_stretch
.venv/bin/python research/validate_real_sample.py cmu_stretch \
  --source samples/cmu_stretch --out reports/cmu-validation \
  --consumer-python .consumer-cpu/bin/python
```

Repeat with the other pinned presets, selecting the preset cameras for standalone
`audit`, `verify` and `probe-loader` commands. The validation script handles this
selection automatically. Use fresh output directories and retain the resulting
`summary.json` together with the tested commit and consumer versions.

## Coverage limits

- Selected camera streams and bounded reader queries only. UTokyo covers two
  of three declared cameras; AgiBot and ALOHA are also camera subsets.
- One upstream reader version and one recorded workstation configuration.
- No physical synchronization, natural-defect, training or robot-success claim.
- Explicit CUDA/NVDEC decoding is outside the supported product scope.

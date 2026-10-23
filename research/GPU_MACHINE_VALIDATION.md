# GPU machine validation — CPU product path

Date: 2026-10-24. Host: WSL2 Ubuntu 26.04.1 on Windows 11, RTX 4090 24,564 MiB,
driver 610.88, CUDA UMD 13.3, Python 3.12.15. Latest main at validation start:
`61719d0823454345e8fc0d6ceed3e0831e409bbf`.

This validation covers the **supported CPU data pipeline on a GPU machine**. It
does not use explicit CUDA decoding and makes no GPU-reader claim.

## Result

| Check | Result |
|---|---|
| Core tests | 134 passed at validation time; 110 core tests after removing exploratory GPU tests |
| Original fixture conformance | **208/208** |
| CUDA-build CPU-path conformance | **78/78**; requested/observed/output decode device CPU |
| AgiBot audit | pass; 60/60 boundary queries decoded |
| ALOHA audit | pass; 300/300 |
| CMU Stretch audit | pass; 405/405 |
| UTokyo xArm audit | pass; 612/612 |
| Four full validations | all `expected_outcomes_met`; official PyAV/TorchCodec pass; authored offset localized/repaired/restored; index corruption rejected; sources unchanged |

The official LeRobot 0.6.1 reader constructs its TorchCodec decoder without a
device argument, so installing CUDA Torch does not change the supported reader's
decode device. This is why the CPU results are identical on the GPU machine.

## Scope

- Selected camera streams and bounded queries only.
- CMU/UTokyo were first validated on this host; UTokyo's download preset covers
  two of three declared cameras, so probes must select those cameras explicitly.
- PARTIAL/ambiguous results from real footage remain PARTIAL; no forced PASS.
- No physical synchronization, training or robot-success claim.
- Explicit CUDA/NVDEC decoding was investigated separately and removed from the
  product repository; it is not required for GPU-machine data processing.

## Reproduction

The core commands are in [USAGE.md](../USAGE.md). A representative run:

```sh
.venv/bin/python -m pytest -q
.venv/bin/lerobot-boundary-audit demo --out demo-result
.venv/bin/lerobot-boundary-audit conformance demo-result \
  --python .consumer-cpu/bin/python --jobs 2 --out reports/conformance
.venv/bin/lerobot-boundary-audit audit samples/cmu_stretch \
  --camera observation.images.image --decode --out reports/cmu
.venv/bin/python research/validate_real_sample.py cmu_stretch \
  --source samples/cmu_stretch --out reports/cmu-validation \
  --consumer-python .consumer-cpu/bin/python
```

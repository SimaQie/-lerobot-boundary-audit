# LeRobot Boundary Audit

[![tests](https://github.com/SimaQie/lerobot-boundary-audit/actions/workflows/tests.yml/badge.svg)](https://github.com/SimaQie/lerobot-boundary-audit/actions/workflows/tests.yml)
[![license](https://img.shields.io/github/license/SimaQie/lerobot-boundary-audit)](LICENSE)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![LeRobot](https://img.shields.io/badge/LeRobot-v3-blueviolet)

Version **0.4.2**. A CPU-only LeRobot v3 boundary audit, independent frame-identity
conformance suite, and guarded copy-based repair tool.

It finds cases where the files are readable but the data is inconsistent:

- global row indexes, episode ranges, data/video shard references, row counts;
- episode video start/end timestamps versus the declared FPS and frame counts;
- stored row timestamps versus MP4 presentation timestamps;
- single boundary frames returned by the installed official LeRobot decoder;
- full-loader windows, actions, padding masks, batches, subsets and spawned workers;
- camera payload swaps, duplicated/reordered frames and corrupted action windows
  on the bundled marker fixtures;
- narrow episode-offset/grid defects via a re-derived plan, staged repair, and
  byte-exact restoration.

It does not train models, prove physical sensor synchronization, certify whole
datasets, or claim natural upstream defects. A PASS is scoped to the selected
cameras and requested checks.

## Install

```sh
git clone https://github.com/SimaQie/lerobot-boundary-audit.git
cd -- lerobot-boundary-audit
git checkout v0.4.2
python -m venv .venv
.venv/bin/python -m pip install ".[repair]"
```

Windows: use `.venv\Scripts\python.exe` and
`.venv\Scripts\lerobot-boundary-audit.exe` with the same arguments. The examples
below use the POSIX venv paths.

## Quick start (no dataset download)

```sh
.venv/bin/lerobot-boundary-audit demo --out demo-result
# open demo-result/demo-report/report.html

.venv/bin/lerobot-boundary-audit audit demo-result/merged --decode --out reports/demo-clean
.venv/bin/lerobot-boundary-audit audit demo-result/offset-one-frame --decode --out reports/demo-offset
```

The demo creates 13 clean/faulty cases. The first audit exits 0 (`pass`); the
offset case exits 1 with episode/timestamp findings. Camera swaps and duplicated
pixels intentionally pass `audit` because their timeline/index is valid; use
`conformance` or `probe-loader` for content identity.

Full walkthrough, command selection, real-data download, optional official-reader
checks and repair/restore:
[USAGE.md](USAGE.md) · [中文使用指南](USAGE.zh-CN.md).

## Commands

| Goal | Command |
|---|---|
| Audit one dataset | `.venv/bin/lerobot-boundary-audit audit DATASET --decode --out reports/x` |
| Check an official decoder at boundaries | `verify` |
| Check full loader windows/actions/padding/workers | `probe-loader` |
| Run the 13-case marker/fault matrix | `conformance` |
| Repair supported timeline defects | `repair-plan` → `apply` → `restore` |
| Create the offline example suite | `demo` |
| Download a pinned real sample | `download aloha_screw_driver` |

Exit codes: `0` requested checks passed; `1` a defect/review result; `2`
unsupported, incomplete or unable to run.

`audit` checks storage and timeline relationships. It cannot detect a camera
payload swap or duplicated frame when timestamps and indexes remain valid; use
the marker conformance suite or a real-footage `probe-loader` for content checks.

## Real data

Four pinned sources can be downloaded (selected cameras only):

```sh
.venv/bin/lerobot-boundary-audit download agibot2026 --out samples/agibot2026
.venv/bin/lerobot-boundary-audit download aloha_screw_driver --out samples/aloha_screw_driver
.venv/bin/lerobot-boundary-audit download cmu_stretch --out samples/cmu_stretch
.venv/bin/lerobot-boundary-audit download utokyo_xarm --out samples/utokyo_xarm
```

| Sample | Selected cameras | FPS | License |
|---|---|---|---|
| AgiBotWorld2026 subset | 2 / 7 | 30 | CC BY-NC-SA 4.0 |
| ALOHA screw driver | 2 / 4 | 50 | MIT |
| CMU Stretch | 1 / 1 | 5 | MIT |
| UTokyo xArm | 2 / 3 | 10 | Apache-2.0 |

The downloader pins revisions, budgets bytes, records SHA-256 hashes and refuses
mismatched files. Videos, action tables and derived datasets are not distributed
with this repository.

Full validation on a real sample:

```sh
.venv/bin/python research/validate_real_sample.py aloha_screw_driver \
  --source samples/aloha_screw_driver \
  --out reports/aloha-validation \
  --consumer-python .consumer-cpu/bin/python
```

This runs the storage/decode audit, official PyAV and TorchCodec boundary checks,
full PTS reference, authored offset control, repair, official recheck, exact
restore and index-corruption rejection.

## Optional official reader environment

The audit environment intentionally does not install Torch. For `verify`,
`probe-loader` and `conformance`, create a separate consumer environment:

```sh
python -m venv .consumer-cpu
.consumer-cpu/bin/python -m pip install torch==2.10.0 torchvision==0.25.0 \
  --index-url https://download.pytorch.org/whl/cpu
.consumer-cpu/bin/python -m pip install \
  "lerobot[dataset]==0.6.1" "torchcodec==0.10.0" "av==15.1.0"
```

Then pass `.consumer-cpu/bin/python` to `--python`; do not install Torch into
the audit venv. Missing packages, incompatible versions and runtime failures are
reported as `unavailable`, not hidden as PASS.

TorchCodec needs a compatible FFmpeg runtime. On Windows pass
`--ffmpeg-bin PATH_TO_SHARED_FFMPEG_BIN`; on Linux make the shared libraries
discoverable (for example via `LD_LIBRARY_PATH`).

## GPU machines

The supported path on a GPU machine is the same CPU pipeline used above. On an
RTX 4090/WSL2 host the official LeRobot 0.6.1 reader still decodes on CPU even
with CUDA Torch installed; the audit, conformance, probe-loader, four real-source
validations and repair/restore flow were validated there. See
[GPU machine validation](research/GPU_MACHINE_VALIDATION.md).

There is no explicit CUDA decode path in this repository and no GPU reader claim.
GPU machines do not need a different code path for the data checks.

## Scope and limits

- One tested upstream version (LeRobot 0.6.1); other versions need their own run.
- The marker suite is synthetic H.264; real samples are AV1. Marker identity is
  not a general content detector for arbitrary footage.
- No physical synchronization, training, robot-success or natural-defect claim.
- PARTIAL/ambiguous results are retained; they are not converted to PASS.
- Repair supports only narrow episode-offset/CFR tick-grid defects and always
  writes a new directory; source files are never edited.

## Development

```sh
.venv/bin/python -m pip install ".[repair,dev]"
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src tests examples research/validate_real_sample.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [USAGE.md](USAGE.md),
[research/CONFORMANCE.md](research/CONFORMANCE.md), and
[RELEASE_NOTES_0.4.2.md](RELEASE_NOTES_0.4.2.md).

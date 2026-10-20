# RTX 4090 validation — session 001

Status: **research preview / partial GPU correctness evidence**. The CPU audit
path passed; explicit TorchCodec CUDA decoding was verified and measured; the
stock LeRobot reader remained CPU-only. This directory contains metrics,
hashes, report JSON/HTML and logs only. It contains no real videos, action
Parquet tables, derived real datasets, virtual environments or credentials.

Detailed narrative: [`RTX4090_2026-10-20.md`](RTX4090_2026-10-20.md) (also at
`research/RTX4090_2026-10-20.md`).

## Headline

| Phase | Result |
|---|---|
| A. CPU audit on this host | 115 tests, ruff clean, 208/208 fixture conformance |
| A. real samples | AgiBot and ALOHA both `expected_outcomes_met`; official 60/60 and 300/300 queries; repairs exact |
| A. sampling | AgiBot mixed 31/5, stratified 35/1; ALOHA 12/24, 29/7; both backends |
| B. CUDA build, stock reader | 78/78 conformance; sampling identical to A; requested/observed decode device CPU |
| C. explicit CUDA smoke | output `cuda:0`; no CPU fallback; cuvid/AV1 decoders present |
| C. correctness | fixture faults detected by CPU and CUDA; real AV1 0 wrong frames, but many ambiguous |
| C. performance | 32-frame single-video decode + H2D + checksum microbenchmark: CPU/CUDA 1.53–2.15× with decoder reuse; not a full-tool or RGB-equivalent speedup |
| Packaging | 323 KiB wheel, clean install, demo pass, 26/26 single-phase conformance |

The GPU benchmark status is `partial`, not `pass`: CUDA RGB differs from CPU RGB
and many real identities remain ambiguous. The CPU default path is unchanged.

## Environment

- Windows 11 + WSL2 Ubuntu 26.04.1, kernel 6.18.54.1-microsoft-standard-WSL2.
- RTX 4090 24,564 MiB, compute 8.9; Windows driver 610.88; WSL 610.57.01;
  CUDA UMD 13.3.
- Python 3.12.15; torch 2.10.0+cpu / 2.10.0+cu128; TorchCodec 0.10.0 /
  0.10.0+cu128; LeRobot 0.6.1; PyAV 15.1.0 in consumers; FFmpeg 7.1.1 shared
  (conda-forge) with cuvid.
- Full environment: [`environment.json`](environment.json),
  [`freezes/`](freezes), [`nvidia-smi.txt`](nvidia-smi.txt).

## Code and data

- Baseline commit: `c428c12d869e30805e514758f9ea2ae408310daf` (remote `main` at run time).
- Branch: `experiment/rtx4090-validation`.
- Tested commits are embedded in each summary: conformance `5da5384`; AgiBot
  validation `4aee263`; ALOHA/sampling `d1eb625`; final GPU benchmark
  `88ae99b`; final branch tip also includes packaging/reporting fixes.
- Data revisions: AgiBot `caa5bf1b0b5be48ed52d158ff0d66af40b0f9258`, ALOHA
  `21eead16760a8d94d449cadf4bc438b322ab528d`, project 13-case fixture.
- All source hashes are unchanged; see `source-integrity.json` and the
  validation summaries.

## Evidence map

| File | Contents |
|---|---|
| `summary.json` | curated phase summary and key counts |
| `requests.json` / `timings.jsonl` | benchmark request plan and raw performance records |
| `controls-summary.json` | fixture fault detections by CPU/CUDA |
| `environment.json` | host, GPU, timezone, library and freeze references |
| `cuda-smoke.json` | explicit `device="cuda"` smoke with device and fallback evidence |
| `conformance-cpu-summary.json` | 208/208 fixture matrix |
| `conformance-cuda-build-cpu-summary.json` | 78/78 CUDA-build CPU-path matrix |
| `validation-*-summary.json` | real-data baseline, official readers, probes, PTS, repair, restore |
| `sampling-*-summary.json` | mixed/stratified counts and decode provenance |
| `gpu-benchmark/` | full benchmark summary, requests, timings, controls, environment, HTML and zip |
| `freezes/` | auditor, CPU consumer, CUDA consumer, wheel-check freezes |
| `logs/` | original command logs with project/home paths redacted |
| `wheel/` | wheel SHA-256 and file list |
| `benchmark-config.json` | exact query plan (including targeted fault frames) |

The benchmark's `minimum`/`median`/`maximum` values are from 3 warm-ups and 5
timed repetitions. Raw timings are retained; no p95 is claimed.

## Key GPU numbers

Correctness (checks include ordinal and time requests):

| Input/device | pass | ambiguous | expected end error | wrong |
|---|---:|---:|---:|---:|
| ALOHA CPU | 89 | 75 | 2 | 0 |
| ALOHA CUDA | 52 | 112 | 2 | 0 |
| AgiBot CPU | 38 | 6 | 2 | 0 |
| AgiBot CUDA | 4 | 40 | 2 | 0 |

Performance medians (32 frames, one camera, decoder reused):

| Input/batch | CPU native ms | CUDA native ms | CPU e2e ms | CUDA e2e ms | e2e ratio |
|---|---:|---:|---:|---:|---:|
| ALOHA 1 | 50.0 | 41.5 | 99.7 | 46.4 | 2.15× |
| ALOHA 8 | 45.9 | 30.5 | 63.5 | 34.6 | 1.84× |
| ALOHA 32 | 47.4 | 31.5 | 62.1 | 35.6 | 1.75× |
| AgiBot 1 | 108.6 | 89.0 | 152.4 | 93.4 | 1.63× |
| AgiBot 8 | 100.8 | 73.6 | 119.6 | 78.3 | 1.53× |
| AgiBot 32 | 113.2 | 66.8 | 129.8 | 71.2 | 1.82× |

CPU e2e includes H2D to the common CUDA endpoint and a checksum. CUDA e2e is
decode + checksum. First CUDA decode was 34–44 ms vs 1.5–6.4 ms CPU; decoder
creation was ~30–33 ms on both. NVDEC utilisation sampled 21–28% after the
timed groups. VRAM allocated peaked at 4.4–35.8 MiB (reserved 24–86 MiB).

Colour: ALOHA CUDA raw MAE median 9.747, TV→full adjusted 0.633; AgiBot
CUDA 8.739 raw and 2.496 adjusted. Exact CPU/CUDA equality was zero on the real
videos. The existing MAE ≤ 2 heuristic was not changed.

## Commands used (Linux/WSL2)

```bash
PROJECT=$HOME/work/rtx4090-boundary-audit
FFMPEG=$HOME/work/tools/ffmpeg
cd "$PROJECT"

# 208-check CPU conformance
LD_LIBRARY_PATH=$FFMPEG/lib .venv/bin/lerobot-boundary-audit conformance \
  research/runs/rtx4090/session-001/demo --python .consumer-cpu/bin/python \
  --jobs 2 --ffmpeg-bin $FFMPEG/bin \
  --out research/runs/rtx4090/session-001/conformance-cpu

# Real-data validation (repeat for aloha_screw_driver)
LD_LIBRARY_PATH=$FFMPEG/lib .venv/bin/python research/validate_real_sample.py \
  agibot2026 --source samples/agibot2026 \
  --out research/runs/rtx4090/session-001/validation-agibot \
  --consumer-python .consumer-cpu/bin/python --ffmpeg-bin $FFMPEG/bin

# Mixed/stratified sampling (CPU); swap the Python path for Phase B
LD_LIBRARY_PATH=$FFMPEG/lib .venv/bin/python research/review_v041.py \
  --samples samples --out research/runs/rtx4090/session-001/sampling-cpu \
  --python .consumer-cpu/bin/python --ffmpeg-bin $FFMPEG/bin

# 78-check CUDA-build CPU-path conformance
LD_LIBRARY_PATH=$FFMPEG/lib:$PROJECT/.consumer-gpu/lib/python3.12/site-packages/nvidia/npp/lib:$PROJECT/.consumer-gpu/lib/python3.12/site-packages/nvidia/cuda_nvrtc/lib:$PROJECT/.consumer-gpu/lib/python3.12/site-packages/torch/lib \
  .venv/bin/lerobot-boundary-audit conformance research/runs/rtx4090/session-001/demo \
  --python .consumer-gpu/bin/python --jobs 2 \
  --phase single --phase window --phase workers \
  --ffmpeg-bin $FFMPEG/bin \
  --out research/runs/rtx4090/session-001/conformance-cuda-build-cpu

# Standalone GPU benchmark (correctness + performance)
PYTHONPATH=$PROJECT/src \
PATH=$FFMPEG/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
LD_LIBRARY_PATH=$FFMPEG/lib:$PROJECT/.consumer-gpu/lib/python3.12/site-packages/nvidia/npp/lib:$PROJECT/.consumer-gpu/lib/python3.12/site-packages/nvidia/cuda_nvrtc/lib:$PROJECT/.consumer-gpu/lib/python3.12/site-packages/torch/lib \
  .consumer-gpu/bin/python research/benchmark_gpu_decode.py \
  --config research/runs/rtx4090/session-001/benchmark-config.json \
  --out research/runs/rtx4090/session-001/gpu-benchmark-003
```

Each run used a fresh output directory. Inputs were read-only; hashes before and
after matched. The final benchmark config is preserved verbatim in this
directory.

## What is not claimed

No physical synchronization, natural-upstream-defect, training or robot-success
claim. The real samples are two AV1 files at 640-wide resolution; results do not
generalize to other codecs, resolutions, worker topologies or request plans. GPU
workers and a full LeRobot GPU reader were not tested. This is not a stable GPU
release.

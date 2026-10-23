# How to use LeRobot Boundary Audit

This guide starts with the bundled example data, so you can try the tool without
downloading a dataset. The normal audit path is CPU-only.

## 1. What problem does it solve?

LeRobot v3 datasets combine Parquet row metadata with encoded MP4 files. Many
failures leave the files readable but make a row point at the wrong video time,
or make an official loader return a different frame than the dataset metadata
claims. This tool checks those relationships and reports the exact evidence.

| Question / symptom | Command | Needs a separate official-reader environment? |
|---|---|---|
| Are global row indexes contiguous and consistent with episode ranges? | `audit` | no |
| Do episode video start/end timestamps match the declared FPS and frame counts? | `audit` | no |
| Do stored row timestamps agree with the MP4 presentation timestamps? | `audit --decode` | no (local PyAV) |
| Does the installed official LeRobot decoder agree at episode boundaries? | `verify` | yes |
| Does the full `LeRobotDataset` return the expected frame/action/padding for windows, batches and workers? | `probe-loader` | yes |
| Are frames/actions/cameras the identities declared before encoding? | `conformance` on the bundled marker suite | yes |
| Can a narrow timeline defect be repaired without editing the source? | `repair-plan` → `apply` → `restore` | no |
| Is GPU decoding faster/correct on this machine? | `research/benchmark_gpu_decode.py` | experimental consumer + CUDA |

`audit` checks **storage and timeline relationships**. It does not prove that a
camera image is semantically correct: a camera payload swap or duplicated frame
can keep valid timestamps/indexes and still pass `audit`. Use `conformance` (or
`probe-loader` on real footage) for content/identity checks.

It is not a training tool, a physical sensor-synchronization proof, a dataset
quality score, or an automatic repair system for arbitrary corruption.

## 2. Install

```sh
git clone https://github.com/SimaQie/-lerobot-boundary-audit.git
cd -- -lerobot-boundary-audit
git checkout v0.4.2

python -m venv .venv
# Linux/macOS:
.venv/bin/python -m pip install ".[repair]"
# Windows PowerShell:
# .venv\Scripts\python.exe -m pip install ".[repair]"
```

The venv-local command is `.venv/bin/lerobot-boundary-audit` (no activation is
needed). On Windows use `.venv\Scripts\lerobot-boundary-audit.exe`; the examples
below use the POSIX path.

## 3. Two-minute quick start with bundled data (no download)

### 3.1 Generate the example suite

```sh
.venv/bin/lerobot-boundary-audit demo --out demo-result
```

The command creates a small LeRobot v3 suite (13 cases), audits the clean merged
dataset and writes `demo-result/demo-report/report.html`. Expected start of the
output:

```json
{
  "status": "pass",
  "synthetic_only": true,
  "cases": 13
}
```

Open `demo-result/demo-report/report.html` in a browser. No server is needed.

The suite contains clean controls and deliberately faulty cases. Use it to see
what different commands detect:

| Case | Intended problem |
|---|---|
| `merged` | clean 5-episode, 2-camera dataset |
| `offset-one-frame` | episode metadata timestamps shifted by one tick |
| `global-index-shift` | every global row index shifted by one |
| `duplicate-global-index` | duplicate index inside episode 1 |
| `action-window-corrupt` | one action value corrupted |
| `camera-swap` | left/right camera payloads exchanged |
| `duplicate-pixel-frame` | one frame repeats its predecessor |
| `pixel-order-swap` | frames 1 and 2 of episode 1 exchanged |
| `multi-data-shard` | clean data split across Parquet shards |
| `no-b-frames` | clean re-encode without B-frames |
| `repaired-offset` | clean repaired derivative |

### 3.2 Audit a clean and a faulty dataset

```sh
.venv/bin/lerobot-boundary-audit audit demo-result/merged --decode --out reports/demo-clean
.venv/bin/lerobot-boundary-audit audit demo-result/offset-one-frame --decode --out reports/demo-offset
```

The first exits **0** and reports `pass`: 5 episodes, 2 cameras, 35 rows,
30 boundary queries and 30 decoded queries. The second exits **1** and reports a
timeline failure, for example:

```json
{
  "status": "fail",
  "finding_counts": {
    "EPISODE_START_MISMATCH": 1,
    "EPISODE_END_MISMATCH": 1,
    "BOUNDARY_QUERY_MISMATCH": 3,
    "DECODE_BOUNDARY_MISMATCH": 3
  }
}
```

Open `reports/demo-offset/report.html` to see the episode, camera and before/after
evidence. JSON evidence is in `report.json`.

Try the index fault too:

```sh
.venv/bin/lerobot-boundary-audit audit demo-result/global-index-shift --out reports/demo-index
# exit 1, 35 GLOBAL_INDEX_MISMATCH findings
```

**Important:** `camera-swap` and `duplicate-pixel-frame` pass `audit` because
their timestamps and indexes are valid. That is expected. They are detected by
the pixel/marker conformance command described in section 5.

### 3.3 Repair the offset into a new copy

The repair contract must be asserted explicitly: all frames are ordered,
contiguous samples at the declared constant FPS. This is not inferred.

```sh
.venv/bin/lerobot-boundary-audit repair-plan demo-result/offset-one-frame \
  --assume-cfr --out reports/demo-plan.json
```

Expected plan summary:

```json
{
  "status": "ready",
  "operations": 1,
  "refusals": []
}
```

Inspect `reports/demo-plan.json`. It lists the exact episode, column, before and
after values. Then apply to a **new** directory and restore to another directory:

```sh
.venv/bin/lerobot-boundary-audit apply reports/demo-plan.json \
  --source demo-result/offset-one-frame --out reports/demo-repaired

.venv/bin/lerobot-boundary-audit audit reports/demo-repaired --decode \
  --out reports/demo-repaired-audit
# status: pass

.venv/bin/lerobot-boundary-audit restore reports/demo-repaired --out reports/demo-restored
```

The apply output contains `"status": "applied"` and a passing verification.
The restore output verifies every original file hash:

```json
{
  "status": "restored",
  "original_file_hashes_verified": true,
  "files": 8
}
```

The source directory is never edited. `apply` refuses overlapping output
directories and re-derives/validates the plan before writing. Restoration is a
new directory, not an in-place operation.

## 4. Audit your own dataset

```sh
.venv/bin/lerobot-boundary-audit audit MY_DATASET --camera observation.images.cam_high \
  --camera observation.images.cam_left_wrist --decode --out reports/my-audit
```

- Omit `--camera` to require all cameras declared by the dataset.
- `--decode` adds local PyAV boundary decoding. Without it, only storage/timeline
  checks run; the report says decoding was not assessed.
- `--out` must be outside the input dataset. Existing outputs are refused.
- Open `reports/my-audit/report.html`; machine-readable evidence is
  `report.json`.

Exit codes:

- `0`: requested checks passed;
- `1`: a defect or review-required result;
- `2`: unsupported, incomplete, or unable to run.

A PASS is scoped to selected cameras and requested checks. It is not a
dataset-wide quality certificate.

### Download a pinned real sample

```sh
.venv/bin/lerobot-boundary-audit download aloha_screw_driver --out samples/aloha
.venv/bin/lerobot-boundary-audit audit samples/aloha \
  --camera observation.images.cam_left_wrist \
  --camera observation.images.cam_right_wrist \
  --decode --out reports/aloha
```

The downloader pins the revision, records source/license/byte counts and hashes
every file. ALOHA is AV1, 50 episodes, 20,000 rows at 50 FPS. AgiBot is also
available: `download agibot2026 --out samples/agibot`. Do not redistribute the
downloaded videos.

## 5. Content / official-reader checks (optional environment)

The audit environment intentionally does **not** install Torch or LeRobot. To
check what an official LeRobot reader actually returns, create a separate
consumer environment:

```sh
python -m venv .consumer-cpu
.consumer-cpu/bin/python -m pip install torch==2.10.0 torchvision==0.25.0 \
  --index-url https://download.pytorch.org/whl/cpu
.consumer-cpu/bin/python -m pip install \
  "lerobot[dataset]==0.6.1" "torchcodec==0.10.0" "av==15.1.0"
```

On Windows use `.consumer-cpu\Scripts\python.exe`; TorchCodec may require
`--ffmpeg-bin` pointing at a shared FFmpeg build. On Linux, TorchCodec needs the
FFmpeg shared libraries discoverable (for example via `LD_LIBRARY_PATH`). Missing
packages or runtime failures produce `unavailable`, not a fake PASS.

### 5.1 Full marker identity matrix

Run the official `LeRobotDataset` against the 13-case example suite:

```sh
.venv/bin/lerobot-boundary-audit conformance demo-result \
  --python .consumer-cpu/bin/python --jobs 2 \
  --out reports/demo-conformance
```

Expected: 208 checks (13 cases × 2 backends × 8 read modes) all match their
expected outcome. Deliberately faulty cases are expected to fail; that is how
camera swaps, duplicated pixels and index shifts are detected. Open
`reports/demo-conformance/report.html`.

`verify-loader` is a smaller, single-case alternative:

```sh
.venv/bin/lerobot-boundary-audit verify-loader demo-result/merged \
  --python .consumer-cpu/bin/python --phase workers \
  --out reports/demo-loader
```

### 5.2 Real-footage full-loader probe

```sh
.venv/bin/lerobot-boundary-audit probe-loader samples/aloha \
  --camera observation.images.cam_left_wrist \
  --camera observation.images.cam_right_wrist \
  --python .consumer-cpu/bin/python --backend torchcodec \
  --phase workers --max-rows 6 --radius 1 \
  --out reports/aloha-probe
```

This copies a bounded camera projection to a temporary directory, reads windows
through the actual `LeRobotDataset`, and compares them with a sequential decode
reference. It also checks action values and padding masks. Repeated or
near-repeated real frames can be reported as `ambiguous` / `partial`; that is a
valid result, not a hidden failure. A probe PASS is not physical synchronization.

### 5.3 Official decoder boundary check

```sh
.venv/bin/lerobot-boundary-audit verify samples/aloha \
  --camera observation.images.cam_left_wrist \
  --camera observation.images.cam_right_wrist \
  --python .consumer-cpu/bin/python --backend torchcodec \
  --out reports/aloha-verify
```

Use `probe-loader` instead when you need windows, actions, padding or workers.

## 6. Command selection cheat sheet

| Goal | Command |
|---|---|
| Create a safe, offline demo | `demo --out demo-result` |
| Check one dataset's timeline/storage | `audit DATASET --decode --out reports/x` |
| Repair only episode video offsets / small CFR grid defects | `repair-plan` → `apply` → `restore` |
| Test a dataset against the installed official reader | `verify` |
| Test full loader windows/actions/padding/workers | `probe-loader` |
| Run the full original marker/fault matrix | `conformance` |
| Test one fixture read mode | `verify-loader` |
| Re-create fixtures from the official recording API | `fixture-suite` |
| Download the pinned real samples | `download aloha_screw_driver` / `download agibot2026` |

The GPU benchmark is separate and experimental: see
[`research/benchmark_gpu_decode.py`](research/benchmark_gpu_decode.py) and the
[RTX 4090 evidence](research/results/rtx4090/session-001/README.md). It is not
required for any command above and is not a stable GPU reader.

## 7. Common problems

**`No module named 'torch'` when running `verify`/`probe-loader`/`conformance`.**
Those commands require an official consumer environment. Pass `.consumer-cpu/bin/python`
(or the Windows equivalent) to `--python`; do not install Torch into the audit
venv to hide the error.

**TorchCodec cannot load FFmpeg shared libraries.**
Install a shared FFmpeg build and make it discoverable. On Windows pass
`--ffmpeg-bin PATH_TO_SHARED_FFMPEG_BIN`; on Linux add its `lib` directory to
`LD_LIBRARY_PATH` before launching the command. The tool reports `unavailable`
with the loading error rather than silently falling back.

**`audit` passes but I suspect a camera/duplicate-frame problem.**
That is expected: content identity is not a storage/timeline check. Run
`conformance` on the marker suite, or `probe-loader` on the real sample, with an
official consumer.

**A real probe is `partial`.**
Real footage often contains repeated neighbouring frames or RGB differences
between backends. The tool keeps those as `ambiguous` rather than discarding
them. Read the report; `partial` is a bounded, honest result.

**Repair refuses.**
Repair supports only narrow episode-offset and small CFR tick-grid defects.
Read `refusals` in the plan; do not weaken the contract or edit the source in
place.

## 8. What a result means

An `audit` PASS means the selected camera streams and requested timeline/storage
checks agree. A `verify`/`probe-loader` PASS means the installed official reader
matched the bounded reference for the requested queries. A conformance PASS
includes expected detection of authored faults. None of these proves physical
sensor synchronization, dataset-wide correctness, training benefit or robot
success. Ambiguity is preserved and reported explicitly.

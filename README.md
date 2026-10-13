# LeRobot Boundary Audit

Lightweight episode-boundary diagnostics, **independent pixel identity conformance**,
and guarded repair for **LeRobot v3**.
Check stored row timestamps against MP4 presentation timestamps, inspect the
first/second/last frame of every selected episode-camera pair, and export a
portable offline HTML report plus machine-readable JSON.

Version **0.3.0** adds tiny original videos carrying CRC-checked camera, episode
and frame IDs specified **before encoding**. Exercise the actual installed
`LeRobotDataset` across temporal windows, batches, spawned workers and episode
subsets. A camera swap can keep timestamps valid while returning wrong content;
this test suite makes that failure observable. [中文说明](README.zh-CN.md).

This is an early research tool, not a claim of universal dataset correctness.
Original saved development materials remain separate and unchanged.

## Install and run

Python 3.11 or later; CPU only. The normal installation needs PyArrow and PyAV,
with no training framework, GPU, model service, database, or web server.

```sh
git clone https://github.com/SimaQie/-lerobot-boundary-audit.git lerobot-boundary-audit
cd lerobot-boundary-audit
python -m venv .venv
# Windows: use .venv/Scripts/python; Linux/macOS: .venv/bin/python
.venv/Scripts/python -m pip install ".[repair]"
.venv/Scripts/python -m boundary_audit.cli download agibot2026 --out samples/agibot2026
.venv/Scripts/python -m boundary_audit.cli audit samples/agibot2026 --camera observation.images.hand_left --camera observation.images.hand_right --decode --out reports/agibot2026
```

Open `reports/agibot2026/report.html` directly in a browser. No network connection
is needed for the report. `lerobot-boundary-audit` is also installed as a command.

The pinned example is the September 2026 **Voxel51 public re-export of
AgiBotWorld2026**, containing 10 real G2 robot episodes. Download only metadata,
tabular data and the left/right wrist video streams: **217,227,601 bytes** under a
230 MB budget, 23,658 rows, 30 FPS. Metadata still declares seven cameras; the
report explicitly states that only **2 / 7** are checked. Running without
`--camera` requires all declared streams and their metadata.

Source: [public subset](https://huggingface.co/datasets/Voxel51/AgiBotWorld2026-sample-10ep)
and [upstream dataset](https://huggingface.co/datasets/agibot-world/AgiBotWorld2026).
Pinned revision: `caa5bf1b0b5be48ed52d158ff0d66af40b0f9258`. The downloader records
source, revision, selected cameras, byte counts and SHA-256 hashes. The sample
is **CC BY-NC-SA 4.0**, separate from this tool's MIT license. Video, actions and
derived dataset copies are excluded from the distribution. PushT is retained
only as a legacy regression option.

## Checks and results

- Bounded MP4 box parsing, `stts` time grids and `stsz` sample counts.
- Unsigned/signed `ctts` composition offsets and a single full-span reorder-delay
  edit: presentation order, including ordinary B-frame videos.
- Episode offsets versus ordinal presentation samples; complete row ranges,
  per-episode frame order, actual stored timestamps and row totals.
- First/second/last queries use **stored row timestamps + stored video offsets**.
- Optional local PyAV backward seek and bounded decode.
- Optional verification using an independently installed **official LeRobot**
  decoder, comparing returned frames with expected ordinal frames.
- Explicit missing/unsupported/unavailable results, camera coverage, versions,
  per-video deviation evidence and filterable findings.

Exit codes: **0** requested checks passed; **1** defect or review needed;
**2** unsupported, incomplete or unable to run. A PASS covers selected camera
streams and requested checks. Without `--decode`/`verify`, decoding is not assessed.
The MP4 parser uses only the Python standard library; dataset checks need
`.[lerobot]`, and decoding adds `.[decode]`.

## Repair to a new copy, then restore exactly

Repair requires an explicit recording contract: all referenced frames are
ordered, contiguous samples at the declared constant FPS. This contract is a
user assertion; the tool cannot infer physical sensor synchronization.

```sh
lerobot-boundary-audit repair-plan MY_DATA --assume-cfr --out reports/plan.json
# Inspect operations, original hashes, proposed values and any refusals.
lerobot-boundary-audit apply reports/plan.json --source MY_DATA --out MY_DATA_REPAIRED
lerobot-boundary-audit restore MY_DATA_REPAIRED --out MY_DATA_RESTORED
```

For partial camera downloads, repeat the same `--camera` selection on
`repair-plan`. Clean inputs produce `no_changes` plans; those are not applied.

Only these narrow changes are supported: episode video offsets, and up to eight
anomalous sample durations that differ by exactly one MP4 tick from an integral
CFR interval. MP4 field repair excludes composition offsets, nonzero media edits,
multiple tracks, missing movie/track duration provenance and large clock drift.
Other data defects block repair. Rows, actions and media payloads are not changed.

A plan binds all source hashes and is re-derived before application. Changes are
made in staging, media payload hashes are compared, and storage plus PyAV checks
must pass before publishing the new directory. Existing or overlapping outputs
are refused. Every derivative carries a receipt and exact original metadata
backups. Restoration creates another directory and verifies **every original
file hash**. On non-Windows hosts an `INCOMPLETE` marker protects interrupted
publication; this is not a whole-directory atomic transaction.

Try a tiny, original six-frame fixture without downloading data:

```sh
python examples/offline_demo.py --out demo-result
```

It deliberately introduces a one-tick time step, demonstrates REVIEW → PASS,
and verifies original preservation and exact restoration. The fixture is for
this auditor, not a complete training dataset.

## Optional official consumer verification

Use a separate Python environment containing the version of LeRobot you train
with; the normal tool does not install Torch. Example with an existing environment:

```sh
lerobot-boundary-audit verify samples/agibot2026 --camera observation.images.hand_left --camera observation.images.hand_right --python PATH_TO_OFFICIAL_PYTHON --backend pyav --out reports/official-pyav
lerobot-boundary-audit verify samples/agibot2026 --camera observation.images.hand_left --camera observation.images.hand_right --python PATH_TO_OFFICIAL_PYTHON --backend torchcodec --out reports/official-torchcodec
```

TorchCodec needs its compatible Torch and FFmpeg runtime. On Windows,
`--ffmpeg-bin PATH_TO_SHARED_FFMPEG_BIN` loads DLLs in the child process only.
The tool does not download that optional runtime automatically. Missing packages,
incompatible versions or runtime failures produce an explicit incomplete result.
The `verify` command calls installed upstream decoder functions for singleton
boundary queries on real footage. It compares ordinal frames, not an independent
semantic identity oracle. Use the following suite for full dataset-loader checks.

## Independent frame identity suite (new in 0.3)

The original synthetic fixture is MIT-licensed and requires no external data.
It includes two official recordings, an official concatenating merge, a one-frame
offset injection, a camera-payload swap, and a guarded repaired copy. Two cameras,
five unequal-length merged episodes and only **35 merged rows** keep tests small.
Pixel decoding reads the marker and CRC, without using timestamps to infer IDs.
Marker episode IDs survive merge renumbering. Expected action windows and padding
masks come from the independent pre-encoding oracle as well.

Extract the bundled fixture and try the lightweight storage audit:

```sh
python -m zipfile -e examples/frame-suite-v030.zip demo-suite
lerobot-boundary-audit audit demo-suite/merged --decode --out reports/merged
```

For full conformance, install the optional official environment separately. The
following CPU versions reproduce the tested consumer; normal users do not need it:

```sh
python -m venv .consumer-env
.consumer-env/Scripts/python -m pip install torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cpu
.consumer-env/Scripts/python -m pip install "lerobot[dataset]==0.6.1" "torchcodec==0.10.0"
lerobot-boundary-audit conformance demo-suite --python .consumer-env/Scripts/python --out reports/conformance
```

Linux/macOS: substitute `.consumer-env/bin/python`. TorchCodec also needs a
compatible shared FFmpeg installation; Windows users can supply `--ffmpeg-bin`.
Start with `--backend pyav` if TorchCodec is unavailable. Every full-suite check
uses its own process and verifies the dataset files were unchanged. Open the
offline `reports/conformance/report.html` and follow the per-check JSON evidence.
Expected failures count as success **only with wrong pixel identity evidence**;
an environment failure cannot certify a negative control.

Recreate the samples through the installed official recording/merge APIs:

```sh
lerobot-boundary-audit fixture-suite --python .consumer-env/Scripts/python --out my-new-suite
lerobot-boundary-audit verify-loader my-new-suite/merged --python .consumer-env/Scripts/python --backend pyav --phase window --out reports/window
```

`fixture-suite` also attempts guarded repair and exact restoration of the injected
offset. If upstream encoding/concatenation produces a nonuniform timing grid, it
preserves all five generated cases, records the refusal in `repair-control.json`,
and does not add a repaired case. `producer-audit.json` records untouched inputs.
Repair guards are never relaxed to make a fixture pass. Use fresh output directories.
Phases are `single`, `window` (−1/0/+1 frame,
episode clamping), `batch` (four rows), `workers` (two spawned workers), and `subset`
(nonconsecutive original episode IDs). No upstream source is patched. Only the
tested LeRobot **0.6.1**, H.264 fixture and CPU configurations are evidenced here;
other versions/codecs require their own run. The marker works for these synthetic
images, not arbitrary real robot footage or transformed/cropped training images.

## Reproduce validation

```sh
python -m pip install ".[repair,dev]"
python -m pytest -q
python research/validate_agibot2026.py --out research/runs/my-run --consumer-python PATH_TO_OFFICIAL_PYTHON --ffmpeg-bin PATH_IF_NEEDED
```

Omit the consumer arguments to run local audit, full decode reference, injected
offset localization, repair and exact restore. Use a fresh output directory.
The full reference decoder checks every frame independently of the MP4 parser.

Measured on Windows on 2026-10-13:

| Case | Result |
|---|---|
| Untouched AgiBot sample, two wrist streams | PASS; 60 / 60 local boundary queries |
| Official LeRobot 0.6.1, PyAV 15.1.0 | PASS; 60 / 60 expected frames |
| Official LeRobot 0.6.1, TorchCodec 0.10.0, Torch 2.10.0 CPU | PASS; 60 / 60 expected frames |
| Independent full PyAV presentation decode | 47,316 frames; zero grid error against 30 FPS |
| Controlled one-frame metadata offset on episode 4, both wrists | Localized to episode 4; official reader returns 6 wrong boundary frames |
| Guarded metadata repair | PASS; official reader returns 60 / 60 expected frames |
| Exact restoration | All 9 source-file hashes match; downloaded original unchanged |
| Synthetic encoded one-tick step | REVIEW → PASS; media payload preserved; exact restore |

Faulty inputs above are **controlled injections**, not defects discovered in
AgiBotWorld2026. This establishes functionality, not a population-level benchmark.
The configured GitHub Actions matrix covers Windows/Linux and Python 3.11/3.12.
A separate Linux job generates the official fixtures and checks both full loaders.
Current remote results: [Actions](https://github.com/SimaQie/-lerobot-boundary-audit/actions).

Synthetic conformance: **60 / 60** combinations match their expectations
(six cases × two decoders × five phases). Clean official recordings/merge and
the repaired copy pass; offset and camera-swap controls return wrong pixel IDs.
Storage timing alone passes the camera-swap control. **69 unit/regression tests**
pass locally on Python 3.11 and 3.12. See [versioned evidence](research/results/v030/)
and [reproduction notes](research/CONFORMANCE.md). Controlled failures do not
establish any naturally occurring upstream bug or dataset-wide prevalence.

## Limits and research positioning

LeRobot v3.0 and ordinary non-fragmented MP4 only. Multiple video tracks,
fragmentation, cropped/multiple edits and composition tables above one million
samples are unsupported. Decode search is bounded to 4,096 frames per query;
exceptionally long GOPs can produce incomplete/failing checks. A stored FPS grid
cannot establish physical camera/action synchronization, original frame identity,
or whether a timing anomaly represents a legitimate recording irregularity.
The synthetic marker suite adds known frame identity for its own fixtures only.
The `mdhd`/`stts` duration equality check applies only without composition offsets.

The contribution is a focused, reproducible boundary audit with consumer evidence
and guarded exact restoration. Related general dataset inspection/validation tools
already exist; this project does not claim to be the first or the only open-source
robot data validator. Its academic value should be supported by more independently
collected failure cases, documented comparisons and a versioned archival release.
See `NOTICE.md` for attribution. Only original tiny synthetic fixtures are bundled;
no downloaded robot dataset or model weights are included. Cite this version via
[CITATION.cff](CITATION.cff); no DOI has been assigned yet.

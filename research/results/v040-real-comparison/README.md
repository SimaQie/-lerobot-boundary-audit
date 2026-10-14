# Same-protocol comparison: AgiBot and real ALOHA

Measured locally on **Windows / CPU, 2026-10-14**. Both samples met the specified
expected outcomes. This includes detecting authored defects and retaining
ambiguous repeated-frame results; it is not a universal dataset correctness claim.

| Measurement | AgiBot public re-export | ALOHA screw-driver |
|---|---|---|
| Source | Voxel51/AgiBotWorld2026-sample-10ep | lerobot/aloha_static_screw_driver |
| Downloaded bytes | 217,227,601 | 258,967,368 |
| Episodes / data rows | 10 / 23,658 | 50 / 20,000 |
| Checked / declared cameras | 2 / 7 | 2 / 4 |
| FPS / stored action dimensions | 30 / 44 | 50 / 14 |
| Real video codec | AV1 | AV1 |
| Storage + local boundary decode | 60 / 60, PASS | 300 / 300, PASS |
| Official PyAV singleton boundaries | 60 / 60, PASS | 300 / 300, PASS |
| Official TorchCodec singleton boundaries | 60 / 60, PASS | 300 / 300, PASS |
| Full sequential PTS reference | 47,316 frames, zero grid error | 40,000 frames, zero grid error |
| PyAV full-loader worker probe | 31 clear matches, 5 ambiguous / 36 | 12 clear matches, 24 ambiguous / 36 |
| TorchCodec full-loader worker probe | 31 clear matches, 5 ambiguous / 36 | 12 clear matches, 24 ambiguous / 36 |
| Row / action / padding errors in probes | 0 / 0 / 0 | 0 / 0 / 0 |
| Controlled one-frame offset | Episode 5; 6 ordinal query mismatches | Episode 25; 6 ordinal query mismatches |
| Guarded repair / official re-check | PASS / PASS | PASS / PASS |
| Exact restore / source preservation | All hashes match / unchanged | All hashes match / unchanged |
| Controlled global-index shift | 23,658 index findings; repair blocked | 20,000 index findings; repair blocked |

**Interpretation:** the structural, decoder, localization, repair, restoration and
index-rejection outcomes transfer to a different real bimanual robot dataset and
FPS. The proportion of uniquely identifiable query frames does not match: ALOHA
has more exact neighbouring pixel duplicates at the sampled boundaries. Every
ambiguous result here was classified as `identical neighbouring frames`, on both
backends. We do not relabel these as PASS, infer sensor drop rates, or claim
training readiness. Both full-loader probes therefore correctly remain PARTIAL.

## Source and scope

- [AgiBot public re-export](https://huggingface.co/datasets/Voxel51/AgiBotWorld2026-sample-10ep):
  `caa5bf1b0b5be48ed52d158ff0d66af40b0f9258`, CC BY-NC-SA 4.0.
- [LeRobot ALOHA screw-driver](https://huggingface.co/datasets/lerobot/aloha_static_screw_driver):
  `21eead16760a8d94d449cadf4bc438b322ab528d`, dataset-card license MIT.
- [Original ALOHA research](https://tonyzhaozh.github.io/aloha/): RSS 2023,
  Learning Fine-Grained Bimanual Manipulation with Low-Cost Hardware.

ALOHA is an established real-robot benchmark, not a newly collected dataset.
Its actual pinned `meta/info.json` is v3.0; the card contains an older illustrative
v2 layout. Use the immutable revision and download receipts, not that old example.
The downloaded sample contains complete tables and two selected video streams;
remaining camera streams are unverified. Videos, actions, and derived datasets
are excluded from this repository. Only reports, hashes and source references
are published. No unmodified source defect was found in these requested checks.

## Identical protocol

Both use the same script, consumer environment, query budget and frame offsets:
six query rows spread over first/last episodes, offsets −1/0/+1 frame, two spawned
workers, seed 20261014, 50,000 reference-decode frames, 256 MiB reference arrays,
300 MiB temporary camera projection and 600 seconds per consumer. The temporal
window is the same number of frames, not the same physical time span at different
FPS. All ambiguous results are retained. The source is fingerprinted before/after.

Consumer: LeRobot 0.6.1, Torch 2.10.0+cpu, PyAV 15.1.0, TorchCodec 0.10.0,
Python 3.12.14. Full PTS reference/repair auditor: PyAV 16.1.0 and Python 3.11.9.
Library versions and official source hashes are in every consumer report.
PyAV/reference matches share RGB conversion; both paths share FFmpeg ancestry.
This cannot establish recording-time identities or physical camera/action sync.

```sh
lerobot-boundary-audit download aloha_screw_driver --out samples/aloha_screw_driver
python research/validate_real_sample.py aloha_screw_driver --source samples/aloha_screw_driver --out research/runs/my-aloha --consumer-python PATH_TO_OFFICIAL_PYTHON
python research/validate_real_sample.py agibot2026 --source samples/agibot2026 --out research/runs/my-agibot --consumer-python PATH_TO_OFFICIAL_PYTHON
```

On Windows add `--ffmpeg-bin PATH_TO_SHARED_FFMPEG_BIN`. Use fresh output paths.
The controlled repair asserts an ordered contiguous CFR storage contract for an
authored offset; it never modifies downloaded originals or repairs unknown sensor
timing. Index corruption is deliberately refused rather than rewriting data rows.

## Evidence

- [Machine-readable comparison](comparison.json)
- [ALOHA complete receipt](aloha_screw_driver/summary.json)
- [AgiBot complete receipt](agibot2026/summary.json)
- [ALOHA worker probe (PyAV)](aloha_screw_driver/probe-pyav/report.html)
- [ALOHA worker probe (TorchCodec)](aloha_screw_driver/probe-torchcodec/report.html)
- [AgiBot worker probe (PyAV)](agibot2026/probe-pyav/report.html)

HTML reports are offline artifacts: download the repository and open the file
locally. GitHub's code view does not run their HTML.

## 中文结论

两份数据的存储、官方解码、人工偏移定位、修复/恢复及索引拒绝结果一致。
ALOHA 为真实双臂平台，50 FPS、14 维动作；AgiBot 样本为 30 FPS、44 维存储动作。
六行多进程探测中，两种后端都得到 AgiBot 31 次明确匹配、5 次无法判定，
ALOHA 12 次明确匹配、24 次无法判定；未发现行号、动作或填充错误。
无法判定来自实际邻近画面的完全重复，不能强行写成“全部正确”，也不能据此推断掉帧。
本文报告的是有限范围内的读取一致性与人工故障验证，不是物理同步或训练收益证明。

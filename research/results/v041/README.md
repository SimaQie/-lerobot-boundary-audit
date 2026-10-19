# 0.4.1 review and local verification

Measured **2026-10-20, Windows / CPU**. Cached inputs are the same pinned real
samples documented in the [0.4.0 comparison](../v040-real-comparison/README.md).
Their download receipts and every source file hash were checked before running;
the full file fingerprints were unchanged afterwards. No videos, action tables
or derived real datasets are published here.

## Equal query-slot budget, different temporal sampling

Both samplers use six query rows, two cameras, offsets −1/0/+1 frame, two spawned
workers, seed 20261014, and identical limits: 50,000 reference frames, 256 MiB
reference image arrays, 300 MiB copied view and 600 seconds per consumer.
They select the same first/last episodes: AgiBot 0/9; ALOHA 0/49. Stratified
sampling chooses times within those episodes, not every episode in the dataset.

| Sample / backend | Mixed: matches / ambiguous | Stratified: matches / ambiguous | Observed query slots |
|---|---|---|---|
| AgiBot / PyAV | 31 / 5 | 35 / 1 | 36 / 36 in each run |
| AgiBot / TorchCodec | 31 / 5 | 35 / 1 | 36 / 36 in each run |
| ALOHA / PyAV | 12 / 24 | 29 / 7 | 36 / 36 in each run |
| ALOHA / TorchCodec | 12 / 24 | 29 / 7 | 36 / 36 in each run |

All eight real probes remain **PARTIAL**, with zero wrong-frame/shape findings,
zero row/action/padding findings, zero consumer errors and no missing/extra query
slots. Remaining ambiguity is due to exact identical neighbouring frames. Nothing
is dropped or relabelled as PASS. Both backends agree on this particular sample.

The mixed results reproduce the earlier 0.4.0 observations. Stratification reaches
more identifiable frames at this fixed seed, but this is **not a statistical
superiority result or a lower dataset defect rate**. The mixed boundary windows
include clamped repeats: ten unique stored rows support their 36 checks; the
stratified windows use eighteen unique stored rows. Equal query-slot counts do not
mean equal unique-frame coverage or equal decoding cost. Boundary checks remain
necessary; interior sampling complements them. No physical synchronization,
training improvement, natural upstream defect or GPU result is claimed.

Consumer versions: LeRobot 0.6.1, Torch 2.10.0+cpu, PyAV 15.1.0, TorchCodec 0.10.0,
Python 3.12.14. Exact source hashes, match rules, per-camera outcomes and timing
are in each JSON report. The ordinal reference shares FFmpeg dependencies and,
for PyAV comparisons, RGB conversion. Array budgets do not bound all process RAM.

## Regression and deployment checks

| Check | Observed result |
|---|---|
| Python 3.11 unit/regression tests | 106 passed |
| Python 3.12 unit/regression tests | 106 passed |
| Static checks | Passed |
| 13 packaged synthetic cases × 2 backends × 3 phases | 78 / 78 expected outcomes met |
| Synthetic image comparisons | 11,760, including deliberately faulty inputs |
| Installed wheel offline demo | Passed in an auditor environment without Torch or NumPy |
| Installed wheel ordinary TorchCodec probe | 12 / 12 matching checks; complete evidence |
| Wheel contents versus measured sources | All 20 package files identical |

The three locally rerun synthetic phases are `single`, `window`, `workers`.
Fault controls must fail with actual image or row/action evidence; a suite PASS
does not mean all faulty inputs passed. Random/persistent evidence multiplicity
also has unit controls. The full eight-phase matrix remains in GitHub CI; the
previous 0.4.0 run passed all five jobs. New 0.4.1 CI results should be read from
[GitHub Actions](https://github.com/SimaQie/-lerobot-boundary-audit/actions), not
inferred from this local receipt.

## Reproduce and inspect

Install `.[fixtures,dev]` in the auditor environment and use a separate official
consumer environment as described in the main README. Inputs must first be
downloaded at their pinned revisions using the built-in sample presets.

```sh
python research/review_v041.py --out research/runs/my-review --python PATH_TO_OFFICIAL_PYTHON
lerobot-boundary-audit conformance DEMO_SUITE --python PATH_TO_OFFICIAL_PYTHON --jobs 2 --backend pyav --backend torchcodec --phase single --phase window --phase workers --out reports/my-review
```

On Windows add `--ffmpeg-bin PATH_TO_SHARED_FFMPEG_BIN`. Use fresh output paths.
`DEMO_SUITE` is the output of the built-in `demo` command. No sampling parameters
may be chosen after looking at image match results for this reproduction.

- [Machine-readable real-data summary](real/summary.json)
- [AgiBot mixed report](real/agibot2026/pyav-mixed/probe-report.json)
- [AgiBot stratified report](real/agibot2026/pyav-stratified/probe-report.json)
- [ALOHA mixed report](real/aloha_screw_driver/pyav-mixed/probe-report.json)
- [ALOHA stratified report](real/aloha_screw_driver/pyav-stratified/probe-report.json)
- [Synthetic matrix summary](conformance-summary.json)
- [All 78 synthetic per-check reports and offline HTML](conformance-evidence.zip)
- [Installed wheel probe](installed-wheel-probe.json)
- [Verification receipt and source Git blob hashes](verification.json)
- [Related work and review findings](../../REVIEW_2026-10-20.md)

The ZIP contains `conformance/report.html` and all its relative JSON links. The
`report` paths in the synthetic summary refer to files within that archive. For
real probes, adjacent HTML files are also included. Download before opening HTML;
GitHub's source viewer does not run the report UI.

## 中文结论

本轮修复的是本项目的验证逻辑缺陷，没有宣称发现真实数据集的自然缺陷。
同预算分层抽样下，AgiBot 的明确匹配由 31/36 增至 35/36，ALOHA 由 12/36
增至 29/36；两个后端一致。全部查询都有证据，但仍有重复画面无法唯一定位，
因此八组真实探测仍为 PARTIAL。旧抽样结果一并保留，不能据此推断整体错误率下降。

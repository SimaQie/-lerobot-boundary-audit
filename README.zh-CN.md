# LeRobot Boundary Audit

[![tests](https://github.com/SimaQie/lerobot-boundary-audit/actions/workflows/tests.yml/badge.svg)](https://github.com/SimaQie/lerobot-boundary-audit/actions/workflows/tests.yml)
[![license](https://img.shields.io/github/license/SimaQie/lerobot-boundary-audit)](LICENSE)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![LeRobot](https://img.shields.io/badge/LeRobot-v3-blueviolet)

源码版本 **0.4.3**（`main`）。一个 CPU 上运行的 LeRobot v3 边界审计、独立帧身份一致性测试和受约束的复制式修复工具。

它能发现“文件能打开，但数据关系不一致”的问题：

- 全局行号、episode 范围、data/video 分片引用、行数；
- episode 视频起止时间与声明 FPS/帧数；
- 存储行时间戳与 MP4 展示时间戳；
- 官方 LeRobot 解码器在边界返回的单帧；
- 完整加载器的窗口、动作、padding、batch、subset 和 spawned worker；
- 自带 marker fixture 中的相机画面交换、重复/乱序帧、动作窗口损坏；
- 通过重新生成计划、暂存修复和逐文件哈希校验处理窄范围 episode offset/CFR 网格缺陷。

它不训练模型、不证明物理传感器同步、不认证整个数据集，也不声称发现自然上游缺陷。PASS 只覆盖所选相机和请求的检查。

## 安装

```sh
git clone https://github.com/SimaQie/lerobot-boundary-audit.git
cd -- lerobot-boundary-audit
git checkout main
python -m venv .venv
.venv/bin/python -m pip install ".[repair]"
.venv/bin/lerobot-boundary-audit --version
```

Windows 使用 `.venv\Scripts\python.exe` 和 `.venv\Scripts\lerobot-boundary-audit.exe`，参数相同。下面示例使用 POSIX venv 路径。

CI 覆盖 Python 3.11 和 3.12。使用主分支进行实验时，请同时记录 `git rev-parse HEAD`。
已发布标签及其附件保留为对应版本的快照；现有 `v0.4.2` Release 早于本次源码精简。

## 快速开始（无需下载数据）

```sh
.venv/bin/lerobot-boundary-audit demo --out demo-result
# 浏览器打开 demo-result/demo-report/report.html

.venv/bin/lerobot-boundary-audit audit demo-result/merged --decode --out reports/demo-clean
.venv/bin/lerobot-boundary-audit audit demo-result/offset-one-frame --decode --out reports/demo-offset
```

demo 会生成 13 个正常/人工故障案例。第一条审计退出 0（pass）；offset 案例退出 1，报告 episode/时间戳错误。相机交换和重复像素会故意通过 `audit`，因为它们的时间戳/索引合法；内容身份要用 `conformance` 或 `probe-loader`。

完整步骤、命令选择、真实数据下载、可选官方 reader 检查和修复/恢复流程见
[USAGE.zh-CN.md](USAGE.zh-CN.md) 或 [English guide](USAGE.md)。

## 命令

| 目标 | 命令 |
|---|---|
| 审计一个数据集 | `.venv/bin/lerobot-boundary-audit audit DATASET --decode --out reports/x` |
| 检查官方解码器边界 | `verify` |
| 检查完整 loader 窗口/动作/padding/worker | `probe-loader` |
| 跑 13 案例 marker/故障矩阵 | `conformance` |
| 诊断宿主、consumer 与数据集前置条件 | `doctor` |
| 修复支持的时间轴缺陷 | `repair-plan` → `apply` → `restore` |
| 创建离线示例 | `demo` |
| 下载固定真实样本 | `download aloha_screw_driver` |

退出码：`0` 请求检查通过；`1` 发现缺陷/需要 review；`2` 不支持、证据不完整或无法运行。

`audit` 只检查存储和时间轴关系；相机画面交换/重复帧可能保留合法时间戳和索引，因此要通过 marker conformance 或真实数据 `probe-loader` 检查。

## 真实数据

四个固定数据源（只下载所选相机）：

```sh
.venv/bin/lerobot-boundary-audit download agibot2026 --out samples/agibot2026
.venv/bin/lerobot-boundary-audit download aloha_screw_driver --out samples/aloha_screw_driver
.venv/bin/lerobot-boundary-audit download cmu_stretch --out samples/cmu_stretch
.venv/bin/lerobot-boundary-audit download utokyo_xarm --out samples/utokyo_xarm
```

| 样本 | 所选相机 | FPS | 许可证 |
|---|---|---|---|
| AgiBotWorld2026 subset | 2 / 7 | 30 | CC BY-NC-SA 4.0 |
| ALOHA screw driver | 2 / 4 | 50 | MIT |
| CMU Stretch | 1 / 1 | 5 | MIT |
| UTokyo xArm | 2 / 3 | 10 | Apache-2.0 |

下载器固定 revision、限制字节数、记录 SHA-256 并拒绝不一致文件。真实视频、动作表和派生数据不随仓库分发。

多数预设仅下载部分相机。运行 `audit` 或 `probe-loader` 时请用 `--camera` 明确选择预设中的相机；
省略该参数会要求所有声明相机都存在。验证脚本会自动使用预设相机。
具体 revision、相机名称及字节预算见 [`download.py`](src/boundary_audit/download.py)。

完整真实数据验证：

```sh
.venv/bin/python research/validate_real_sample.py aloha_screw_driver \
  --source samples/aloha_screw_driver \
  --out reports/aloha-validation \
  --consumer-python .consumer-cpu/bin/python
```

包含存储/解码审计、官方 PyAV/TorchCodec 边界检查、全量 PTS 参考、人工偏移控制、修复、官方复查、精确恢复和索引错误拒绝。

## 可选官方读取器环境

审计环境故意不安装 Torch。运行 `verify`、`probe-loader`、`conformance` 时另建 consumer 环境：

```sh
python -m venv .consumer-cpu
.consumer-cpu/bin/python -m pip install torch==2.10.0 torchvision==0.25.0 \
  --index-url https://download.pytorch.org/whl/cpu
.consumer-cpu/bin/python -m pip install \
  "lerobot[dataset]==0.6.1" "torchcodec==0.10.0" "av==15.1.0"
```

把 `.consumer-cpu/bin/python` 传给 `--python`；不要把 Torch 装进审计 venv。缺包、版本不兼容或运行时失败会明确报告 `unavailable`，不会伪装成 PASS。

## 运行前诊断

`doctor` 是宿主、可选 consumer 和数据集前置条件的只读统一入口。它在 consumer 进程中导入官方 `LeRobotDataset`；提供 `--dataset` 时同时跑存储审计；提供 `--out` 时写出离线 `doctor.json`/`doctor.html`：

```sh
.venv/bin/lerobot-boundary-audit doctor \
  --dataset samples/aloha_screw_driver \
  --camera observation.images.cam_left_wrist \
  --consumer-python .consumer-cpu/bin/python \
  --out reports/doctor
```

缺失 Torch/PyAV/FFmpeg 或不支持的数据集会被明确标出；它不执行 loader 像素探测，也不声称物理同步。省略 `--dataset` 时只诊断环境。

`probe-loader` 默认把参考帧缓存到 `$LEROBOT_BOUNDARY_AUDIT_CACHE/reference`（或平台缓存目录）。缓存键包含视频 SHA-256、请求 ordinal、FPS 以及 probe/driver 身份；视频或代码变化会使条目失效。用 `--no-cache` 关闭，用 `--cache-dir` 指定位置，用 `--max-cache-bytes` 限制单条大小。JSON 报告记录命中/未命中、解码秒数、缓存字节和峰值 RSS；缓存缺失或损坏只算 miss，不改变结论，缓存开关也不改变 probe 结论。

TorchCodec 需要兼容的 FFmpeg 运行库。Windows 用 `--ffmpeg-bin PATH_TO_SHARED_FFMPEG_BIN`；Linux 让共享库可被发现（例如设置 `LD_LIBRARY_PATH`）。

## GPU 机器

GPU 机器上使用同一套 CPU 数据管线。RTX 4090/WSL2 的记录覆盖 conformance 和四源真实数据验证，包括受约束修复与恢复。
即使安装了 CUDA Torch，官方 LeRobot 0.6.1 reader 仍在 CPU 解码。
真实画面的帧身份存在歧义时，probe 结果仍会保留为 PARTIAL。见 [验证摘要](research/GPU_MACHINE_VALIDATION.md)。

本仓库没有显式 CUDA 解码路径，也不宣称 GPU reader；GPU 机器不需要为数据检查切换代码路径。

## 范围与限制

- 测试上游版本为 LeRobot 0.6.1（最新稳定版）和 0.6.0；其他版本需单独验证。
- marker 套件是合成 H.264；真实样本是 AV1。marker 不是任意真实画面的通用内容检测器。
- 非整数 FPS 或粗 timescale 下，`audit` 允许一个 MP4 sample tick 的时间戳量化；这不会掩盖一帧偏移。官方 LeRobot writer 声明整数 FPS，因此非整数数据集在 producer API 支持前只作为只读元数据实验。
- 不证明物理同步、训练收益、机器人成功率或自然数据缺陷。
- PARTIAL/ambiguous 会保留，不会强行改成 PASS。
- 修复只支持窄范围 episode offset/CFR tick-grid 缺陷，始终写新目录，源文件不修改。

## 开发

```sh
.venv/bin/python -m pip install ".[repair,dev]"
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src tests examples research/validate_real_sample.py research/check_release.py
```

见 [CONTRIBUTING.md](CONTRIBUTING.md)、[使用指南](USAGE.zh-CN.md)、
[一致性测试协议](research/CONFORMANCE.md)和[验证摘要](research/GPU_MACHINE_VALIDATION.md)。

## 真实机器人边界画面（开发版 main）

`audit --visuals` 会自动启用解码，最多为四个边界查询保存预期帧、相邻帧与根据本地 PyAV 返回 PTS 顺序重建的帧。打开输出目录的 report.html，分享时保留同目录 JPEG。画面不是官方 loader 的像素采集，不改变审计结论；重复画面不能证明唯一帧身份。总解码预算 50,000 帧，未完成情况显式报告。该功能晚于 v0.4.3，需安装当前 main。生成画面仍受原数据集许可约束。

**官方 loader 实际返回像素**要用官方 consumer 的 `probe-loader --visuals`：它会保存
`LeRobotDataset` 实际返回张量、独立的 expected/previous/next 参考、哈希、返回标签和
可离线打开的相对路径 HTML。ALOHA 的 clean/人工偏移/修复三组证据见
[official-loader pixel evidence](docs/real-robot-loader-pixels.md)。这与 `audit --visuals`
的本地 PyAV 重建不同。

真实 ALOHA 示例及命令见 [真实机器人示例](docs/real-robot-example.md)。下一阶段开发与实验见 [远方 agent SOP](research/NEXT_VERSION_SOP.zh-CN.md)。

![Real ALOHA robot boundary frame](docs/assets/aloha-boundary/boundary-0-10400-ca02fbb6e8e83b7b.jpg)

来自人工偏移对照实验的真实 ALOHA 画面，来源及检查范围： [example](docs/real-robot-example.md).

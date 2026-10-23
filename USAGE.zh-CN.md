# LeRobot Boundary Audit 使用指南

这份指南先用仓库自带示例数据跑通，再说明怎么处理自己的数据。默认审计路径只需要
CPU，不需要训练框架或 GPU。

## 1. 它能解决什么问题

LeRobot v3 数据集由 Parquet 行元数据和编码后的 MP4 共同组成。很多故障文件仍能
打开，但某一行指向了错误的视频时间，或者官方加载器实际返回的画面与数据集声明
不一致。本工具检查这些关系，并给出可核查的 episode、相机、时间戳和哈希证据。

| 问题 / 症状 | 命令 | 需要单独官方环境？ |
|---|---|---|
| 全局行号是否连续、是否与 episode 范围一致？ | `audit` | 否 |
| episode 视频起止时间是否与声明 FPS、帧数一致？ | `audit` | 否 |
| 存储行时间戳是否与 MP4 展示时间戳一致？ | `audit --decode` | 否（本地 PyAV） |
| 官方 LeRobot 解码器在 episode 边界是否一致？ | `verify` | 是 |
| 完整 `LeRobotDataset` 的窗口、动作、padding、worker 是否正确？ | `probe-loader` | 是 |
| 画面/动作/相机身份是否与编码前声明一致？ | `conformance` | 是 |
| 能否不修改源数据地修复窄范围时间轴错误？ | `repair-plan` → `apply` → `restore` | 否 |
| 本机 GPU 解码是否更快、是否正确？ | 独立 GPU benchmark | 实验性，需要 CUDA consumer |

**重要边界：** `audit` 检查存储和时间轴关系，不证明画面语义正确。相机画面交换、
重复帧可能保留合法时间戳和索引，因此 `audit` 会 pass；这种情况要用
`conformance`/`probe-loader` 做内容检查。

它不是训练工具、物理同步证明、数据集质量评分，也不能自动修复任意损坏。

## 2. 安装

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

安装后的命令是 `.venv/bin/lerobot-boundary-audit`（无需激活虚拟环境）。
Windows 使用 `.venv\Scripts\lerobot-boundary-audit.exe`；下面示例用 POSIX 路径。

## 3. 用自带示例数据跑通（无需下载，约两分钟）

### 3.1 生成示例套件

```sh
.venv/bin/lerobot-boundary-audit demo --out demo-result
```

它会生成 13 个案例的小型 LeRobot v3 套件，审计干净的 `merged` 数据集，并写出
`demo-result/demo-report/report.html`。输出开头应类似：

```json
{
  "status": "pass",
  "synthetic_only": true,
  "cases": 13
}
```

直接用浏览器打开 `demo-result/demo-report/report.html`，不需要启动服务器。
套件同时包含正常对照和人工故障：

| 案例 | 人工问题 |
|---|---|
| `merged` | 干净的 5 episode、2 相机数据集 |
| `offset-one-frame` | episode 元数据时间戳偏移一个 tick |
| `global-index-shift` | 所有全局行号 +1 |
| `duplicate-global-index` | episode 1 内重复索引 |
| `action-window-corrupt` | 一个动作值被改坏 |
| `camera-swap` | 左右相机画面交换 |
| `duplicate-pixel-frame` | 一帧重复上一帧 |
| `pixel-order-swap` | episode 1 的 frame 1/2 交换 |
| `multi-data-shard` | 干净数据拆分到多个 Parquet 分片 |
| `no-b-frames` | 干净的无 B-frame 重编码 |
| `repaired-offset` | 已修复的干净副本 |

### 3.2 审计干净与故障案例

```sh
.venv/bin/lerobot-boundary-audit audit demo-result/merged --decode --out reports/demo-clean
.venv/bin/lerobot-boundary-audit audit demo-result/offset-one-frame --decode --out reports/demo-offset
```

第一条应退出 **0**、状态 `pass`，覆盖 5 个 episode、2 个相机、35 行、
30 个边界查询和 30 个解码查询。第二条退出 **1**，例如：

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

打开 `reports/demo-offset/report.html` 可以看到具体 episode、相机和前后值。
JSON 证据在 `report.json`。

再试全局索引故障：

```sh
.venv/bin/lerobot-boundary-audit audit demo-result/global-index-shift --out reports/demo-index
# 退出 1，35 条 GLOBAL_INDEX_MISMATCH
```

**注意：** `camera-swap` 和 `duplicate-pixel-frame` 的 `audit` 会 pass，因为它们的
时间戳和索引合法；这是正常结果。内容/画面身份由第 5 节的 conformance 检测。

### 3.3 修复到新副本，再精确恢复

修复必须显式声明录制契约：所有帧都是按声明 FPS 的顺序、连续样本；工具不会自行
推断物理同步。

```sh
.venv/bin/lerobot-boundary-audit repair-plan demo-result/offset-one-frame \
  --assume-cfr --out reports/demo-plan.json
```

预期计划摘要：

```json
{
  "status": "ready",
  "operations": 1,
  "refusals": []
}
```

打开 `reports/demo-plan.json`，可以看到具体 episode、列名、修复前/后值。然后
应用到新目录，并恢复到另一个新目录：

```sh
.venv/bin/lerobot-boundary-audit apply reports/demo-plan.json \
  --source demo-result/offset-one-frame --out reports/demo-repaired

.venv/bin/lerobot-boundary-audit audit reports/demo-repaired --decode \
  --out reports/demo-repaired-audit
# status: pass

.venv/bin/lerobot-boundary-audit restore reports/demo-repaired --out reports/demo-restored
```

`apply` 输出包含 `"status": "applied"` 和通过的 verification。`restore` 会逐文件
校验原始哈希：

```json
{
  "status": "restored",
  "original_file_hashes_verified": true,
  "files": 8
}
```

源目录从不修改。`apply` 会拒绝重叠输出目录，并在写盘前重新校验计划。恢复也是
新建目录，不做原地覆盖。

## 4. 审计自己的数据集

```sh
.venv/bin/lerobot-boundary-audit audit MY_DATASET \
  --camera observation.images.cam_high \
  --camera observation.images.cam_left_wrist \
  --decode --out reports/my-audit
```

- 省略 `--camera` 时要求数据集声明的所有相机都存在。
- `--decode` 增加本地 PyAV 边界解码；不加时只做存储/时间轴检查，报告会明确说明
  解码未检查。
- `--out` 必须在输入数据集之外；已存在的输出目录会被拒绝。
- 打开 `reports/my-audit/report.html`；机器可读证据是 `report.json`。

退出码：

- `0`：请求的检查通过；
- `1`：发现缺陷或需要 review；
- `2`：不支持、证据不完整或无法运行。

PASS 只覆盖所选相机和请求的检查，不是整个数据集的质量证书。

### 下载固定版本真实样本

```sh
.venv/bin/lerobot-boundary-audit download aloha_screw_driver --out samples/aloha
.venv/bin/lerobot-boundary-audit audit samples/aloha \
  --camera observation.images.cam_left_wrist \
  --camera observation.images.cam_right_wrist \
  --decode --out reports/aloha
```

下载器固定 revision，记录来源、许可证、字节数和每个文件哈希。ALOHA 是 AV1、
50 episodes、20,000 行、50 FPS。AgiBot 也可用：
`download agibot2026 --out samples/agibot`。不要重新分发下载的视频。

## 5. 内容 / 官方读取器检查（可选环境）

审计环境故意不安装 Torch/LeRobot。要检查官方 reader 实际返回什么，需另建
consumer 环境：

```sh
python -m venv .consumer-cpu
.consumer-cpu/bin/python -m pip install torch==2.10.0 torchvision==0.25.0 \
  --index-url https://download.pytorch.org/whl/cpu
.consumer-cpu/bin/python -m pip install \
  "lerobot[dataset]==0.6.1" "torchcodec==0.10.0" "av==15.1.0"
```

Windows 使用 `.consumer-cpu\Scripts\python.exe`；TorchCodec 可能需要
`--ffmpeg-bin` 指向共享 FFmpeg。Linux 需要让 FFmpeg 共享库可被发现（例如设置
`LD_LIBRARY_PATH`）。缺包或运行时失败会明确报告 `unavailable`，不会伪造 PASS。

### 5.1 完整 marker 身份矩阵

```sh
.venv/bin/lerobot-boundary-audit conformance demo-result \
  --python .consumer-cpu/bin/python --jobs 2 \
  --out reports/demo-conformance
```

预期 208 项检查（13 案例 × 2 后端 × 8 读取方式）全部符合 expected。人工故障
应当被检出而失败，这是套件的预期结果。打开
`reports/demo-conformance/report.html`。

单案例快速替代：

```sh
.venv/bin/lerobot-boundary-audit verify-loader demo-result/merged \
  --python .consumer-cpu/bin/python --phase workers \
  --out reports/demo-loader
```

### 5.2 真实画面完整加载器探测

```sh
.venv/bin/lerobot-boundary-audit probe-loader samples/aloha \
  --camera observation.images.cam_left_wrist \
  --camera observation.images.cam_right_wrist \
  --python .consumer-cpu/bin/python --backend torchcodec \
  --phase workers --max-rows 6 --radius 1 \
  --out reports/aloha-probe
```

它把有限相机投影复制到临时目录，通过真实 `LeRobotDataset` 读取窗口，并与顺序
解码参考比较画面、动作和 padding。真实视频的重复邻帧/跨后端颜色差异可能得到
`ambiguous`/`partial`，这是有效结果，不应强行改成 PASS。该结果不是物理同步证明。

### 5.3 官方解码器边界检查

```sh
.venv/bin/lerobot-boundary-audit verify samples/aloha \
  --camera observation.images.cam_left_wrist \
  --camera observation.images.cam_right_wrist \
  --python .consumer-cpu/bin/python --backend torchcodec \
  --out reports/aloha-verify
```

需要窗口、动作、padding 或 worker 时用 `probe-loader`，不要只用 `verify`。

## 6. 命令选择表

| 目标 | 命令 |
|---|---|
| 创建离线安全示例 | `demo --out demo-result` |
| 检查单个数据集时间轴/存储 | `audit DATASET --decode --out reports/x` |
| 窄范围 episode offset / CFR tick 修复 | `repair-plan` → `apply` → `restore` |
| 检查官方 reader 的边界返回 | `verify` |
| 检查完整 loader 窗口/动作/padding/worker | `probe-loader` |
| 跑完整原创 marker/故障矩阵 | `conformance` |
| 只测一个 fixture 读取方式 | `verify-loader` |
| 用官方录制 API 重建 fixtures | `fixture-suite` |
| 下载固定真实样本 | `download aloha_screw_driver` / `download agibot2026` |

GPU benchmark 是独立实验工具，不属于日常使用路径；见
[`research/benchmark_gpu_decode.py`](research/benchmark_gpu_decode.py) 和
[RTX 4090 证据](research/results/rtx4090/session-001/README.md)。它不是稳定
GPU reader。

## 7. 常见问题

**运行 `verify`/`probe-loader`/`conformance` 报 `No module named 'torch'`。**
这些命令需要官方 consumer 环境；把 `.consumer-cpu/bin/python` 传给 `--python`，
不要为了让错误消失而把 Torch 装进审计 venv。

**TorchCodec 加载 FFmpeg 共享库失败。**
安装共享 FFmpeg，并让它可被发现。Windows 用
`--ffmpeg-bin PATH_TO_SHARED_FFMPEG_BIN`；Linux 在启动前把其 `lib` 目录加入
`LD_LIBRARY_PATH`。工具会报告 `unavailable` 和具体加载错误，不会静默 fallback。

**`audit` 通过，但我怀疑相机交换或重复帧。**
这是预期的：内容身份不是存储/时间轴检查。用 `conformance`（marker 套件）或
`probe-loader`（真实数据）配合官方 consumer 检查。

**真实 probe 是 `partial`。**
真实视频常见重复邻帧或跨后端 RGB 差异；工具保留为 `ambiguous`，不丢弃样本。
`partial` 是有边界的真实结果。

**修复被拒绝。**
只支持窄范围 episode offset 和小的 CFR tick-grid 缺陷。查看计划里的
`refusals`；不要修改源码目录，也不要为了通过而放宽契约。

## 8. 结果含义

`audit` PASS 表示所选相机和请求的时间轴/存储检查一致；`verify`/`probe-loader`
PASS 表示官方 reader 在请求范围内匹配参考；conformance PASS 包含对人工故障的
预期检出。它们都不证明物理传感器同步、数据集整体正确、训练收益或机器人成功率。
无法判定的情况会被保留并明确报告。

# GPU 机器验证与兼容性 SOP（2026-10-24）

执行者：GPU 机器侧 agent。本文档自包含，不需要额外对话上下文。
上一次同类实验的证据基线：`research/results/rtx4090/session-001/`（2026-10-20，
WSL2 + RTX 4090，基线提交 `c428c12` / `152cb2c`）。本次是它的**增量验证 + GPU 解码决策**。

仓库地址（已改名）：https://github.com/SimaQie/lerobot-boundary-audit

## 0. 目标定义（必读，防止做错方向）

本工具是**纯 CPU 设计**：审计器核心零依赖、不装 Torch、解码预算有界。
"GPU 兼容"的确切含义分两层，不要混淆：

- **层次 A（必须，100% 通过）：CUDA 环境兼容性认证。** 使用 GPU 机器的研究者，
  实际跑的是 CPU 产品路径（实测确认：官方 LeRobot 0.6.1 读取器即使装了
  CUDA Torch，解码仍在 CPU）。层次 A 要证明的是：在这类机器上，工具的全部
  功能（审计、conformance、probe-loader、修复/恢复、demo、下载）结果与
  Windows/Linux 普通机器完全一致。
- **层次 B（研究性，按决策树执行，不是发布门禁）：GPU 解码能否成为可选功能。**
  session-001 已实测两个硬阻塞：CUDA 解码 RGB 与 CPU 不等价（raw MAE 中位数
  8.7–9.8，TV-range 调整后 0.63–2.50），导致真实画面身份验证大量退化为
  ambiguous（AgiBot CUDA：4 pass / 40 ambiguous）；加速仅微基准成立
  （1.37–2.34×）。层次 B 的任务是产出数据，决定这道门开还是不开。

**红线纪律（违反任何一条 = 本次执行无效）：**

1. 不修改主仓库代码与测试；发现疑似上游 bug 先归档证据，不直接发 issue。
2. 不弱化证据标准：跳过 ≠ 通过，环境异常 ≠ 检出故障，PARTIAL 不能记为 PASS。
3. 诚实汇报：复现失败、无法判定、数字对不上，都原样记录。负结果同样有价值。
4. 输入数据只读；每个 run 用全新输出目录；前后哈希必须一致。
5. 不把真实数据集（视频/parquet）提交进仓库，只提交报告与指标。

## 1. 环境准备

### 1.1 基线提交

```bash
git clone https://github.com/SimaQie/lerobot-boundary-audit.git
cd lerobot-boundary-audit
git checkout 57564e4   # 或由主仓库侧确认的最新 main 提交，记录在 environment.json
```

本次相对 session-001 的**增量**（也就是要新验证的）：版本元数据 0.4.2、
`download` 新增 `cmu_stretch` / `utokyo_xarm` 两个数据源（从未在任何
Linux/GPU 机器上跑过）、`cli.py` 与 `validate_real_sample.py` 的 choices 改为
从 SAMPLES 派生。

### 1.2 三个隔离环境（不要共用）

```bash
# 审计环境（不装 Torch）
python3.12 -m venv .venv
.venv/bin/python -m pip install ".[repair,dev]"

# CPU 消费者环境（官方 LeRobot + TorchCodec，CPU 版）
python3.12 -m venv .consumer-cpu
.consumer-cpu/bin/python -m pip install torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cpu
.consumer-cpu/bin/python -m pip install "lerobot[dataset]==0.6.1" "torchcodec==0.10.0"

# CUDA 消费者环境（版本对齐 session-001 冻结清单）
python3.12 -m venv .consumer-gpu
.consumer-gpu/bin/python -m pip install torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cu128
.consumer-gpu/bin/python -m pip install "lerobot[dataset]==0.6.1" "torchcodec==0.10.0"
```

FFmpeg：需要 7.1.x 共享库版（带 cuvid 解码器）。session-001 用 conda-forge
的 7.1.1，放在 `$HOME/work/tools/ffmpeg`，通过 `LD_LIBRARY_PATH` 与
`--ffmpeg-bin` 注入。`ffmpeg -decoders | grep cuvid` 必须能看到
`hevc_cuvid` / `av1_cuvid` / `h264_cuvid`。

### 1.3 环境证据采集（开工前第一件事）

输出目录统一为 `research/runs/gpu-session-002/`（下称 `$OUT`）：

```bash
OUT=$PWD/research/runs/gpu-session-002
mkdir -p "$OUT"/{logs,freezes}
nvidia-smi > "$OUT/nvidia-smi.txt"
nvidia-smi -q > "$OUT/nvidia-smi-q.txt"
lscpu > "$OUT/lscpu.txt"; free -h > "$OUT/free.txt"
cat /etc/os-release > "$OUT/os-release.txt"; uname -a >> "$OUT/os-release.txt"
.venv/bin/python -m pip freeze > "$OUT/freezes/auditor-freeze.txt"
.consumer-cpu/bin/python -m pip freeze > "$OUT/freezes/consumer-cpu-freeze.txt"
.consumer-gpu/bin/python -m pip freeze > "$OUT/freezes/consumer-gpu-freeze.txt"
ffmpeg -version > "$OUT/ffmpeg-version.txt"; ffprobe -version > "$OUT/ffprobe-version.txt"
```

参考 session-001 `environment.json` 的 schema 记录 host/GPU/驱动/CUDA/库版本
（RTX 4090 参考：driver 610.88、CUDA UMD 13.3、torch 2.10.0+cu128、
torchcodec 0.10.0+cu128、av 15.1.0、ffmpeg 7.1.1）。WSL2 下 nvidia-smi 在
`/usr/lib/wsl/lib`；若本次是原生 Linux，明确记录差异。

## 2. 层次 A：CUDA 环境兼容性认证（必须全过）

### A1 单元测试与 lint

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src tests examples
.venv/bin/lerobot-boundary-audit demo --out "$OUT/demo"
```

验收：133 passed + 1 skipped（Windows 基准；数量如有差异，记录并解释是
平台差异还是回归）；demo 13/13 pass。

### A2 合成 fixture 全量 conformance（208 组合）

```bash
.venv/bin/lerobot-boundary-audit demo --out "$OUT/demo-v040"
LD_LIBRARY_PATH=$FFMPEG/lib .venv/bin/lerobot-boundary-audit conformance \
  "$OUT/demo-v040" --python .consumer-cpu/bin/python --jobs 2 \
  --ffmpeg-bin $FFMPEG/bin --out "$OUT/conformance-cpu"
```

验收：**208/208**（2 解码器 × 13 案例 × 8 阶段），期望失败必须有像素/行证据。

### A3 四个真实数据源：下载 + 审计（含解码）

```bash
for s in agibot2026 aloha_screw_driver cmu_stretch utokyo_xarm; do
  .venv/bin/lerobot-boundary-audit download $s --out samples/$s
done
.venv/bin/lerobot-boundary-audit audit samples/agibot2026 \
  --camera observation.images.hand_left --camera observation.images.hand_right \
  --decode --out "$OUT/audit-agibot"
.venv/bin/lerobot-boundary-audit audit samples/aloha_screw_driver \
  --camera observation.images.cam_left_wrist --camera observation.images.cam_right_wrist \
  --decode --out "$OUT/audit-aloha"
.venv/bin/lerobot-boundary-audit audit samples/cmu_stretch \
  --camera observation.images.image --decode --out "$OUT/audit-cmu"
.venv/bin/lerobot-boundary-audit audit samples/utokyo_xarm \
  --camera observation.images.hand_image --camera observation.images.image \
  --decode --out "$OUT/audit-utokyo"
```

预算与 revision 由 preset 固定（合计约 550 MB 下载）。Windows 本地基准：
agibot/aloha 历史全过；**cmu_stretch 405/405 边界查询、utokyo_xarm 612/612，
均 PASS、0 findings**。验收：四份报告 status=pass，exit 0，边界查询全部解码。

### A4 四源完整验证协议（含官方读取器、受控注入、修复/恢复）

```bash
for s in agibot2026 aloha_screw_driver cmu_stretch utokyo_xarm; do
  LD_LIBRARY_PATH=$FFMPEG/lib .venv/bin/python research/validate_real_sample.py \
    $s --source samples/$s --out "$OUT/validation-$s" \
    --consumer-python .consumer-cpu/bin/python --ffmpeg-bin $FFMPEG/bin
done
```

`validate_real_sample.py` 的 choices 已从 SAMPLES 派生，四个名字都接受；
脚本主体从 preset 读取相机与 revision，无硬编码。若新样本跑出脚本假设不符的
错误，**这就是层次 A 的有效发现**：完整记录 traceback 与报告，不要改脚本绕过。
验收：四个源 `expected_outcomes_met`；受控注入能定位、修复后全过、恢复后
哈希一致。

### A5 四源 probe-loader 分层抽样（官方加载器读取一致性）

```bash
for s in cmu_stretch utokyo_xarm; do
  LD_LIBRARY_PATH=$FFMPEG/lib .venv/bin/lerobot-boundary-audit probe-loader samples/$s \
    --python .consumer-cpu/bin/python --sampling stratified \
    --max-rows 6 --phase workers --ffmpeg-bin $FFMPEG/bin \
    --out "$OUT/probe-$s"
done
```

（agibot/aloha 已有 v041 协议历史数据，可复跑对照；两个新源是首次。）
注意 PARTIAL 与 ambiguous 的合法存在：等价于参考解码的近似匹配有上限，
重复邻帧导致 ambiguous 不是失败。验收：报告能逐项核对每个请求槽位，
无静默跳过；与 A4 的结论交叉一致。

### A6 CUDA 构建下的 CPU 路径 conformance（复刻 78/78）

```bash
LD_LIBRARY_PATH=$FFMPEG/lib:$PWD/.consumer-gpu/lib/python3.12/site-packages/nvidia/npp/lib:$PWD/.consumer-gpu/lib/python3.12/site-packages/nvidia/cuda_nvrtc/lib:$PWD/.consumer-gpu/lib/python3.12/site-packages/torch/lib \
  .venv/bin/lerobot-boundary-audit conformance "$OUT/demo-v040" \
  --python .consumer-gpu/bin/python --jobs 2 \
  --phase single --phase window --phase workers \
  --ffmpeg-bin $FFMPEG/bin --out "$OUT/conformance-cuda-build-cpu"
```

验收：78/78（与 session-001 同口径）；`requested/observed decode device`
仍为 CPU——这正是层次 A 要证明的"GPU 机器上官方读取器走 CPU"的直接证据。

## 3. 层次 B：GPU 解码研究（决策门，不是门禁）

### B1 复现微基准

沿用 session-001 的 `benchmark_gpu_decode.py --config benchmark-config.json`
协议（3 次预热 + 5 次计时），当前驱动/版本下复测 1.37–2.34× 是否仍成立。
数字漂移本身是有效结果。

### B2 RGB 等价类判定（层次 B 的核心问题）

session-001 遗留一个未回答的问题：TV-range 调整后，ALOHA adjusted MAE
中位数 **0.630**（低于 ≤2 启发式阈值），AgiBot **2.497**（高于阈值）——
"调整后等价类"在两个源上信号不一致。本次任务：在四个数据源上扩大样本量，
分别报告 raw/adjusted MAE 分布，判定是否存在一个跨源稳定的调整等价类。
若四源 adjusted 都能稳定低于阈值且零错帧，GPU 解码才具备"近似等价"的资格；
否则维持研究定位。

### B3 身份覆盖量化

CUDA 下逐源统计 pass / ambiguous / expected-end-error / wrong 四类计数
（session-001 基线：AgiBot CUDA 4/40/2/0，ALOHA CUDA 52/112/2/0）。
wrong 必须保持 0；ambiguous 比例是 GPU 解码可用性的直接度量。

### B4 端到端瓶颈归因

测一次完整 audit 流程的分项耗时（解码 / RGB 转换 / H2D / 校验 / parquet /
报告），回答"全工具 GPU 化的收益上限到底在哪一层"。若解码只占总时长的小头，
GPU 化的工程收益论证就不成立。

### B5 决策规则

只有同时满足：B2 四源 adjusted 稳定等价 + B3 wrong=0 且 ambiguous 显著下降 +
B4 端到端有实质加速，才向主仓库侧**提议**把 GPU 做成可选功能
（如 `--device` 或独立命令）。任何一条不满足，就输出数据归档、维持现状。
提议 ≠ 实现：实现需主仓库侧另行评审。

### B6（可选加分）H.265/HEVC 编码族

当前所有验证只覆盖 H.264（合成）与 AV1（真实），TorchCodec 历史错帧 bug
正是 H.265 上发现的，且 FFmpeg 已确认有 `hevc_cuvid`。在 Hub 上找声明
HEVC 的 LeRobot v3.0 数据集（记录 revision 与来源），CPU audit + 官方读取器
probe 各跑一轮；GPU 侧再用 `hevc_cuvid` 做一次显式解码对照。找不到合适
数据集也是有效结论（如实记录"公开 Hub 以 AV1/H.264 为主"）。

## 4. 交付与汇报

目录结构对齐 session-001 惯例：

```text
research/runs/gpu-session-002/
├── environment.json          # schema 对齐 session-001
├── nvidia-smi.txt / lscpu.txt / os-release.txt / ffmpeg-version.txt
├── freezes/                  # 三个环境的 pip freeze
├── logs/                     # 每条命令的原始日志（路径脱敏后）
├── demo/ conformance-cpu/ conformance-cuda-build-cpu/
├── audit-*/ validation-*/ probe-*/   # 每个数据源一组
├── gpu-benchmark-*/          # B1/B2/B3/B4 全部原始 JSON
└── README.md                 # 结论文档：数字表 + 与 session-001 对比 + 异常清单
```

README.md 必须包含：一张"本次 vs session-001 vs Windows 本地基准"的数字
对照表；每项任务的 exit code；所有 PARTIAL/ambiguous/异常的原样记录；
B2/B3/B4/B5 的判定与依据。汇报格式：数字 + 原始文件路径，不允许只给结论。

**回传方式**：不要直接 push。把 `$OUT` 打包 + README.md 单独一份交给主仓库侧
审查后入库；如有代码修复建议，交付 patch 文件与说明。

## 5. 已知坑

- WSL2 下 nvidia-smi 在 `/usr/lib/wsl/lib`；原生 Linux 无此问题，但要记录差异。
- TorchCodec CUDA 构建需要共享 FFmpeg；`--ffmpeg-bin` 只注入子进程。
- 四源合计下载约 550 MB，磁盘预留 ≥ 5 GB（含解包与报告）。
- 每次换 phase/样本都使用全新输出目录；输入目录保持只读。
- pytest 数量以 133+1 为基准（Windows 3.11/3.12 均如此）；Linux 上如有个别
  skip，记录原因即可，但 passed 数量不应减少。
- validate 脚本对新样本是首次在 Linux 上运行：报错属于有效发现，按 A4 处理。

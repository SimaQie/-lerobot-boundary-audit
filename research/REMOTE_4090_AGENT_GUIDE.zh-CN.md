# RTX 4090 远程 agent 实验与开发交接手册

编写日期：2026-10-20。对象：由项目所有者授权、在另一台机器上操作的开发 agent。
本手册是执行任务书；请先完整阅读，再依次完成各阶段。它不是已经取得的 GPU 实验报告。

## 1. 任务与完成标准

项目：[SimaQie/-lerobot-boundary-audit](https://github.com/SimaQie/-lerobot-boundary-audit)。
已知基线：**0.4.1**，提交 **`c428c12d869e30805e514758f9ea2ae408310daf`**。

目标依次为：

1. 在远端机器复现现有 CPU 审计、官方读取、人工故障和恢复实验。
2. 验证 CUDA 构建环境下原有 CPU 路径仍可用。
3. 新开发一个独立、可复现的 **TorchCodec / NVDEC GPU 解码实验**，验证正确性后再测速度。
4. 根据结果决定是否增加可选 GPU 功能；保留轻量 CPU 默认路径。
5. 保存完整证据，更新实验文档、测试和必要代码，并将更新推送到 GitHub 独立分支。

请自主完成已经明确的常规安装、实验、修复和分支推送。只有确实缺少权限、凭据或硬件能力时才报告具体阻碍；不要停留在计划或口头声称“兼容 GPU”。

**必须区分三个结论：**

| 结论 | 必须具有的证据 |
|---|---|
| 能在配有 4090 的服务器运行 | 当前 CPU 路径实测通过，准确记录环境 |
| 真正使用 GPU 解码 | 显式 CUDA 解码调用、实际输出设备及可核查的执行路径；不能只是 CPU 解码后 `.to('cuda')` |
| GPU 对工作流有收益 | 同输入、同请求、同输出约定下，正确性保持且端到端测量有收益 |

当前 `probe-loader` **没有 `--device` 参数**；`--backend torchcodec` 也不是 GPU 开关。
当前 `probe_driver.py` 记录 `device_used="cpu"`，基线官方 reader 默认使用 CPU 解码。
因此，下面“现有命令”和“待开发实验”必须分开，不能虚构已经存在的 GPU CLI。

## 2. 操作边界与工作目录

- 使用新 checkout 和独立虚拟环境；不要修改机器上别人的项目、全局 Python 或已有训练环境。
- 原始下载数据只读。修复仅写入新的派生目录，必须验证源文件哈希未变及精确恢复。
- 保留 `research/results/v040*`、`research/results/v041` 等历史凭据；新结果另建目录。
- 不修改已经安装的 LeRobot/TorchCodec 源码来获得“通过”；本项目的实验适配器必须显式标注并记录源码哈希。
- 不重装系统、升级宿主显卡驱动或重启远端机器；现有驱动不够时先完成可运行部分并记录要求。
- 初轮只下载第 5 节两个小样本和项目原创基准，不下载整个 DROID/AgiBot，不下载模型权重。
- 不向 GitHub 上传真实视频、Parquet 动作表、派生真实数据、虚拟环境、缓存或凭据。
- 不承诺“首次/唯一”“训练提升”“物理同步正确”；这些都不是本轮实验能直接证明的。

优先使用已有 **Linux x86_64 / Ubuntu 24.04、Python 3.12**。建议预留约 50 GB 磁盘，涵盖 CUDA 软件、缓存和派生副本；这是工作空间建议，不是样本下载量。
若为 Windows，先完成 CPU 部分；CUDA TorchCodec 的 Windows 安装须按相应版本官方说明单独验证。
已有 WSL2/容器可作为候选，但 `nvidia-smi` 可用不等于 NVDEC 所需的驱动库也可用。不要擅自重构宿主环境。

以下命令以 Linux Bash 为准。在同一个项目根目录执行。所有示例输出目录都应是新的；已有结果保留，改用新运行编号。

## 3. Clone、固定基线、采集环境

```bash
git clone https://github.com/SimaQie/-lerobot-boundary-audit.git lerobot-boundary-audit
cd lerobot-boundary-audit
git fetch origin
git switch --detach c428c12d869e30805e514758f9ea2ae408310daf
git switch -c experiment/rtx4090-validation
mkdir -p research/runs/rtx4090/session-001
git rev-parse HEAD > research/runs/rtx4090/session-001/baseline-commit.txt
git status --short
nvidia-smi > research/runs/rtx4090/session-001/nvidia-smi.txt
python3.12 --version
ffmpeg -version
ffprobe -version
```

不要用 `--depth 1` 后直接假设能切换到历史提交。若该目录已存在，先确认其用途和修改状态，选择新目录，不覆盖或硬重置它。
若 main 已前进，仍先测上述已知基线；另外记录远端 main SHA。最终合入时处理差异，并对最终代码重跑受影响检查。

缺少 Git、Python 3.12/venv 或 FFmpeg 时，使用机器已有的包管理权限安装。Linux FFmpeg 必须能找到共享库；NVDEC 还需要相应驱动和 CUDA 库。
核查 `ffmpeg -hwaccels`、`ffmpeg -decoders`；列出硬件选项只是初筛，最终以真实视频成功解码为准。

环境清单至少包括：操作系统、CPU/RAM、GPU 名称/显存、驱动、容器/WSL 情况、Python、Torch/torchvision/TorchCodec/PyAV/LeRobot、FFmpeg 共享库版本，以及三套环境各自的 `pip freeze`。
`nvidia-smi` 的 CUDA Version 表示驱动支持能力，不等同于已安装 Toolkit 或 PyTorch 构建版本。

### 先修正复现脚本中的环境记录

基线 `research/review_v041.py` 写死了 `platform="Windows CPU"` 和 `measurement_date="2026-10-20"`。
不要直接把它生成的这两个字段当作远端事实。先做一个小修复：

- 由实际系统信息和带时区的时间生成记录；机器系统时区与用户展示时区分别记录。
- 分开记录 `host_gpu`、`torch_cuda_available`、`requested_decode_device`、`observed_decode_device`。
- 即使 CUDA 版 Torch 可以使用 GPU，当前官方读取任务的 observed decode device 仍应为 CPU。
- 保存这个修复的提交 SHA、补上可测试的日期/平台记录逻辑，再开展正式远端矩阵。
- 此后所有报告记录“实际被测源码 SHA + 环境”，不要只记录 0.4.1 这个版本号。

此修复改变记录方式，不应改变查询抽样或像素判定阈值。

## 4. 三套隔离环境

| 环境 | 用途 | 关键要求 |
|---|---|---|
| `.venv` | 审计、报告、开发测试、调度子进程 | 安装本项目，不安装官方 LeRobot/Torch |
| `.consumer-cpu` | 现有官方读取基线 A | CPU Torch + 原版本 LeRobot/TorchCodec |
| `.consumer-gpu` | CUDA 构建控制 B、真正 GPU 实验 C | CUDA Torch/TorchCodec；每次显式区分 CPU / CUDA 解码 |

创建前，把 `.consumer-cpu/` 和 `.consumer-gpu/` 加入该 checkout 的 `.git/info/exclude`，避免它们出现在待提交文件中；不要修改全局 Git 排除规则。后续若完善项目通用配置，可将这些模式作为明确的小改动加入 `.gitignore`。

### 4.1 审计和开发环境

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[fixtures,dev]'
.venv/bin/python -m pip install build
.venv/bin/python -m pip freeze > research/runs/rtx4090/session-001/auditor-freeze.txt
```

### 4.2 CPU 官方消费者

```bash
python3.12 -m venv .consumer-cpu
.consumer-cpu/bin/python -m pip install --upgrade pip
.consumer-cpu/bin/python -m pip install torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cpu
.consumer-cpu/bin/python -m pip install 'lerobot[dataset]==0.6.1' 'torchcodec==0.10.0' 'av==15.1.0'
.consumer-cpu/bin/python -m pip check
.consumer-cpu/bin/python -m pip freeze > research/runs/rtx4090/session-001/consumer-cpu-freeze.txt
```

### 4.3 CUDA 官方消费者：Linux 初选组合

以下使用与旧实验同一主版本，减少同时改变多个变量。已核查官方 cu128 索引具有 Python 3.12 / Linux x86_64 的 TorchCodec 0.10.0 CUDA wheel；实际机器仍必须通过安装与解码门槛。

```bash
python3.12 -m venv .consumer-gpu
.consumer-gpu/bin/python -m pip install --upgrade pip
.consumer-gpu/bin/python -m pip install torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cu128
.consumer-gpu/bin/python -m pip install 'torchcodec==0.10.0+cu128' --index-url https://download.pytorch.org/whl/cu128
```

创建 `research/runs/rtx4090/session-001/cuda-constraints.txt`，内容为：

```text
torch==2.10.0+cu128
torchvision==0.25.0+cu128
torchcodec==0.10.0+cu128
```

然后继续：

```bash
.consumer-gpu/bin/python -m pip install 'lerobot[dataset]==0.6.1' 'av==15.1.0' -c research/runs/rtx4090/session-001/cuda-constraints.txt
.consumer-gpu/bin/python -m pip check
.consumer-gpu/bin/python -m pip freeze > research/runs/rtx4090/session-001/consumer-gpu-freeze.txt
.consumer-gpu/bin/python -c 'import torch,torchcodec; print(torch.__version__,torchcodec.__version__,torch.version.cuda,torch.cuda.is_available()); assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))'
```

不要通过 `--no-deps` 掩盖不兼容依赖，也不要让后续安装悄悄把 CUDA wheel 换成 CPU wheel。
如果该组合不可用，保留错误，依据官方兼容表选择另一个独立环境；固定实际 wheel/版本，再从冒烟实验重新开始。不要在同一个环境里反复升级直至无法解释结果。

**Windows 分支：** 不照搬 Linux CUDA wheel 命令。TorchCodec 0.10 文档把 Windows CUDA 支持标为实验性质，说明了 conda 安装方式；由 agent 核实实际可解出的版本组合，另存 lock/环境清单。无法取得可靠 GPU 解码时，仍交付 CPU 服务器复现和 GPU 阻碍报告。

## 5. 下载哪些数据

在项目根目录执行：

```bash
.venv/bin/lerobot-boundary-audit download agibot2026 --out samples/agibot2026
.venv/bin/lerobot-boundary-audit download aloha_screw_driver --out samples/aloha_screw_driver
.venv/bin/lerobot-boundary-audit demo --out research/runs/rtx4090/session-001/demo
```

| 数据 | 固定 revision | 实际小样本范围 |
|---|---|---|
| `Voxel51/AgiBotWorld2026-sample-10ep` | `caa5bf1b0b5be48ed52d158ff0d66af40b0f9258` | 约 217 MB；10 episode、23,658 行、30 FPS；左右手腕，2/7 相机；44 维存储动作；CC BY-NC-SA 4.0 |
| `lerobot/aloha_static_screw_driver` | `21eead16760a8d94d449cadf4bc438b322ab528d` | 约 259 MB；50 episode、20,000 行、50 FPS；左右腕，2/4 相机；14 维动作；数据卡 MIT |
| 项目自带原创基准 | 基线提交中的 `resources/frame-suite-v040.zip` | 13 个样例：6 个干净控制、7 个人工故障；MIT，供 marker identity 和读取实验 |

两个真实样本合计约 **476 MB**，均为 AV1。原创基准补充 H.264/B-frame 等控制，不能把两份真实数据描述成不同视频编码。
ALOHA 是成熟真实机器人基准，不是 2026 年新采集的数据。下载器会检查预算、大小及哈希；保留 `source_manifest.json`，不要手工改 revision 或只剪几帧替代完整分片。
网络中断可重试下载器，保留已经核验的文件。哈希不一致时不要忽略校验或直接编辑清单。

本轮先保持数据不变，以便把差异归因于服务器/解码环境。只有完成首轮后，才考虑有明确 license、固定 revision 和可闭合索引关系的第三份真实小样本。

## 6. 阶段 A：复现已有功能，先建立可信基线

### 6.1 回归、静态检查、完整原创读取矩阵

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src tests examples research/validate_agibot2026.py research/validate_real_sample.py research/compare_v040.py research/check_backup.py research/review_v041.py
.venv/bin/lerobot-boundary-audit conformance research/runs/rtx4090/session-001/demo --python .consumer-cpu/bin/python --jobs 2 --out research/runs/rtx4090/session-001/conformance-cpu
```

基线已知单元测试为 106 项；以实际 checkout 的收集数量为准，不要通过删除测试达到数字。
13 样例 × 2 后端 × 8 读取方式为 **208 组**。验收是 208 组均符合 expected，而不是要求所有故障样例 PASS；人工错帧必须有实际像素或行/动作证据，异常退出不能算检出成功。

### 6.2 两份真实数据的完整同流程实验

```bash
.venv/bin/python research/validate_real_sample.py agibot2026 --source samples/agibot2026 --out research/runs/rtx4090/session-001/validation-agibot --consumer-python .consumer-cpu/bin/python
.venv/bin/python research/validate_real_sample.py aloha_screw_driver --source samples/aloha_screw_driver --out research/runs/rtx4090/session-001/validation-aloha --consumer-python .consumer-cpu/bin/python
.venv/bin/python research/review_v041.py --samples samples --out research/runs/rtx4090/session-001/sampling-cpu --python .consumer-cpu/bin/python
```

最后一个脚本必须先完成第 3 节环境记录修正。全部是 **CPU 读取**。
前两个脚本覆盖：存储/边界解码、两种官方后端、worker 窗口、全量顺序 PTS 参考、人工一帧偏移、受保护修复、官方复查、哈希一致恢复、索引错移拒绝修复。

历史 Windows/CPU 对照，仅作为比较目标，不得硬编码为远端答案：

| 项目 | AgiBot | ALOHA |
|---|---:|---:|
| 官方单边界查询 | 60/60 通过 | 300/300 通过 |
| mixed：明确匹配 / 无法判定 | 31 / 5 | 12 / 24 |
| stratified：明确匹配 / 无法判定 | 35 / 1 | 29 / 7 |
| 多进程每组查询画面数 | 36 | 36 |

抽样使用 6 行、半径 1、种子 20261014、两个相机。两种后端历史结果相同。
真实画面有完全重复邻帧，**PARTIAL 可以是正确结果**；不得为凑 PASS 丢掉不确定样本或放宽阈值。
两份源数据未变、修复/恢复哈希一致、查询无遗漏/额外证据，是独立验收条件。

如需要验证当前官方写入器新生成的数据，再运行 `fixture-suite --python .consumer-cpu/bin/python --out 新目录`，随后对新套件执行 `conformance`。明确区分内置历史样例与本次新录制样例。

## 7. 阶段 B：验证“CUDA 环境里的现有 CPU 读取”

将第 6 节 `research/review_v041.py` 的消费者替换为 `.consumer-gpu/bin/python`，使用新输出目录 `sampling-cuda-build-cpu`。
再用这个消费者跑原创套件 `--phase single --phase window --phase workers`，即 78 组。

这一步使用 CUDA 构建的库，但现有 reader 仍 CPU 解码。比较 A/B 可以发现库构建、ABI、FFmpeg 或环境差异，**不能记为 GPU 解码加速**。
若 A/B 结果不一致，先定位这个差异，不要同时加入新的 CUDA reader 适配器。

## 8. 阶段 C：真正 NVDEC GPU 解码

### 8.1 先做现成 API 冒烟实验

以下是使用已安装 TorchCodec 的独立脚本，不是本项目已经存在的 GPU 子命令。保存日志，不覆盖结果文件：

```bash
.consumer-gpu/bin/python - <<'PY'
from pathlib import Path
import json
import torch
from torchcodec.decoders import VideoDecoder

assert torch.cuda.is_available()
folder = Path('samples/aloha_screw_driver/videos/observation.images.cam_left_wrist')
video = next(iter(sorted(folder.rglob('*.mp4'))))
decoder = VideoDecoder(str(video), device='cuda', seek_mode='exact')
batch = decoder.get_frames_at(indices=[0, 1, 2])
torch.cuda.synchronize()
assert batch.data.device.type == 'cuda'
print(json.dumps({
    'input': str(video), 'requested_device': 'cuda',
    'observed_device': str(batch.data.device), 'shape': list(batch.data.shape),
    'dtype': str(batch.data.dtype), 'pts_seconds': batch.pts_seconds.tolist(),
    'torch': torch.__version__, 'cuda_build': torch.version.cuda,
    'gpu': torch.cuda.get_device_name(0)
}, indent=2))
PY
```

对 AgiBot 的一个实际 AV1 文件也做同样验证。可用 FFmpeg 的硬件解码命令补充检查，但不要把 FFmpeg 命令的成功冒充本项目 GPU 读取成功。
若失败，标记 `unavailable`，保留 traceback、版本与 codec/profile 信息；CPU 能解码只说明 CPU 路径可用。
若报告 NVDEC/动态库缺失，核查驱动、FFmpeg、libnvcuvid、libnpp、libnvrtc 和容器视频能力，不修改判定逻辑掩盖环境错误。

### 8.2 接下来需要你开发的实验工具

先新增独立实验脚本，例如 `research/benchmark_gpu_decode.py`；**该文件在基线里不存在，由远端 agent 实现**。
优先做这个小工具，不先重构核心审计，也不默认使用 GPU。它必须：

1. 由独立消费者 Python 执行；解析固定的 JSON 请求或显式命令参数。
2. 接收输入清单、请求序列、`device`、seek mode、batch size、seed、重复次数、时间/内存上限和输出目录。
3. 在同一个 `.consumer-gpu` 环境中比较 `device='cpu'` 与 `device='cuda'`；另保留 CPU-only 环境的参考。
4. 用主进程创建 CUDA decoder；初轮不在 DataLoader workers 内初始化 CUDA，不使用 fork 继承 CUDA context。
5. 保存实际设备、源码哈希、库构建、原始请求、输出 PTS/duration、匹配/无法判定/失败及理由；不写真实视频像素到公共报告。
6. GPU 不可用时显式返回 `unavailable`，不能静默 CPU fallback 后写 GPU PASS。
7. 分块处理，初始 batch size 1、8、32；不把 20,000 帧一次性堆进显存或 RAM。
8. 遵循现有 JSON/HTML 报告、预算耗尽 PARTIAL 和源文件不变的约定；保留每个请求的重复次数，不去重掉难例。

### 8.3 正确性矩阵：先过这一关，才谈加速

| 输入/请求 | 参考 | 必须检查 |
|---|---|---|
| 原创干净 marker 视频 | 编码前 `frame_oracle.json` | camera/episode/frame 身份；CUDA/CPU 的已知正确帧 |
| 原创重复/交换/错移故障 | 同一 oracle 和故障清单 | 明确错帧不能变成 PASS；未知身份不能算成功检出 |
| 两份 AV1 真实视频：按帧序号读取 | 独立顺序 PyAV 参考 + 同环境 TorchCodec CPU | 请求顺序、重复项、PTS、相邻候选、形状与像素差异 |
| 两份视频：按时间读取 | 对应模式下的正确参考 | exact/approximate seek 分开；文件首尾、轨迹边界、随机乱序/重复 |

不要混淆三个语义：顺序 ordinal、按时间查找“当前展示帧”、官方 LeRobot 0.6.1 的 FPS/rounding 请求映射。
`get_frames_at` 和 `get_frames_played_at` 不是同一个接口的替代拼写。先验证各自约定，再比较同义请求。
至少记录 first/second/last、各分片与 episode 接缝以及 −1/0/+1 窗口。文件末尾时间是边界，不当然对应一个额外可读取帧。

真实 CPU/GPU RGB 不要求强行逐像素相同。分别报告 exact equality、最大差、MAE、通道/布局/色域信息和相邻帧区分能力。
现有普通探测的近似匹配阈值是 MAE≤2 且候选分离≥0.25，仅为启发式；先保留原阈值做对照。不要看到 GPU 失败后调阈值直到通过。
如 marker 身份无法解析，报告 `unknown_identity`/未验证并调查转换路径；有相同 PTS 不能据此推断画面身份相同。

初轮用固定 6 行预算。扩展实验预先登记种子 **20261014、20261020、4090**，mixed/stratified 均保留。
后续可加 24 行/半径 1，或 6 行/半径 8；两者不要直接笛卡尔积放大。
参考帧 RAM 随唯一窗口帧、相机数、分辨率增长；新增预算应先估算并记录，耗尽不能改报 PASS。
不同种子是不同查询计划，不是独立数据集；不能据此夸大统计独立性。

### 8.4 性能矩阵：公平比较三个成本

- **解码输出驻留其原始设备：** 衡量 decoder 自身，明确 CPU 输出和 GPU 输出位置不同。
- **相同 GPU 输出端点：** CPU decode 加 H2D 对照 GPU decode；统一 dtype/layout，分别列出转换和传输成本。
- **用户端到端：** 包含 decoder 初始化/索引、读取、窗口/动作处理、需要的传输和核对成本。不要用裸解码倍数代替整条审计流程加速。

每组至少 3 次 warm-up、5 次计时，保留原始耗时，初步报告 median/min/max；如报告 p95，增加到至少 20 次并注明样本数。
在 CUDA 计时区间开始和结束同步，使用 wall clock 衡量包含 CPU、NVDEC 和数据传输的工作；CUDA event 可作补充，不能替代端到端计时。
分开测首次建 decoder 与复用 decoder；“首次建 decoder”不等于清空操作系统页缓存。
CPU 线程数、批量、文件顺序、请求、缓存说明和重复次数一致；不要并行跑 CPU/GPU 性能组互相争抢资源。
记录 VRAM allocated/reserved 峰值、可取得的总显存占用、进程 RSS 和 decoder/主机负载。NVDEC 采样利用率作辅助证据，短任务采样为 0 不自动判失败。

如果 640×480、小 batch 下 GPU 不快，这也是有效结论。可以使用自有 marker 生成较高分辨率的有界补充视频，单列为原创合成吞吐实验，不能冒充新的真实机器人数据。
记录媒体 codec/profile/pixel format/resolution/GOP/B-frame 信息；不要为得出 GPU 更快而只保留最有利配置。

## 9. 根据结果决定下一步改进

| 实测情况 | 优先动作 | 可以公开的结论 |
|---|---|---|
| 现有 CPU 流程在 4090 服务器通过 | 补充服务器环境凭据；保持默认部署简单 | CPU 路径在该服务器环境得到验证 |
| CUDA wheel / NVDEC 加载失败 | 改善环境诊断、依赖检查和清晰错误报告 | 某组合不可用；不等于数据错误，也不等于 GPU 已支持 |
| 同环境 CPU/GPU ordinal 或 marker 身份不同 | 建最小复现，定位寻址、PTS、色彩转换、边界或缓存；加回归测试 | 只有证据充分时描述具体实现缺陷 |
| 身份一致但 RGB 有小差异 | 分离身份与 RGB 差异，报告分布，保留无法判定 | 相应请求范围内的读取一致性；不是物理同步证明 |
| 解码更快但端到端不快 | 分析初始化、CPU 校验、复制、哈希和 PCIe 成本；优先批量/缓存的有界优化 | 仅裸解码加速，不能写整体提速 |
| 正确性保持且端到端有稳定收益 | 再设计默认关闭的可选 GPU 接口、能力探测和独立消费者 | 特定机器、版本、数据和请求下的收益 |
| 多进程 CUDA 不稳定 | 先用主进程 GPU 解码、CPU worker 读表的架构；明确 unsupported 组合 | 对已测试拓扑的支持，不能写任意 workers 都兼容 |
| 两份数据差别很大 | 扩展预登记种子/时间覆盖，按相机、codec、访问模式分解 | 数据/访问模式依赖性；不要先做全局质量评分 |

若要把 GPU 接到完整 LeRobot 读取流程，另开明确的实验适配层，不编辑 site-packages，不将运行时适配器冒充 stock official reader。
报告需同时记录原 reader SHA、adapter SHA、是否启用适配、解码设备和输出设备；保留原路径回归。
先支持单进程、边界/窗口/动作/填充完整检查，再讨论多进程；独立 NVDEC benchmark 的通过不自动证明完整 Dataset GPU 读取正确。

不要优先做大模型训练或机器人成功率实验：当前小样本无法支持这类结论，且训练会混入新的混杂因素。
先把“独立帧身份 + 明确无法判定 + 真实跨解码路径验证 + 可复现报告”做扎实，作为开源研究工具的特点。

## 10. 代码、文档、测试如何更新

按结果拆分提交，避免把环境修复、GPU 原型和性能结论混在一起：

1. **可复现性修复：** 动态日期/平台、请求设备/实际设备、环境清单和提交 SHA，新增回归测试。
2. **独立 GPU 实验工具：** 带显式 unavailable、预算控制、计时边界及请求/参考证据；GPU 依赖留在消费者，不加入基础审计依赖。
3. **有证据的功能改进：** 最小复现先入测试，再修复；CPU 106 项基线及人工负例不能退化。新增 GPU 测试在无硬件时明确 skip，不能打印伪造 PASS。
4. **文档/结果：** 在 `research/results/rtx4090/<run-id>/` 写新材料，README 汇总实测范围、局限与复现步骤。

新结果目录建议保留：

```text
README.md
environment.json
requests.json
summary.json
timings.jsonl
source-integrity.json
controls-summary.json
evidence.zip
```

环境摘要中分清：请求 CUDA、PyTorch 可见 GPU、真正解码设备、最终张量设备、CPU fallback 是否发生。
原始日志/大报告可压缩；保留可追溯相对路径与哈希。环境冻结文件保留 CPU/CUDA 构建后缀，清理 token、含账号的私有索引 URL、绝对私人目录及机器敏感信息。
每个结果记录数据 revision/相机/源哈希、被测源码 SHA、命令/参数/seed、每项状态、重复次数、硬件和实际软件版本。

更新根 README/中文 README、CHANGELOG 和相关实验说明；保留旧 CPU 结果为历史，不拿新数字覆盖它们。
只有公开功能和测试已经达到相应程度时才提升版本：记录修复可作补丁版本；独立 GPU 原型不应直接宣传为稳定 GPU 全流程支持。
如提升版本，保持 `pyproject.toml`、`__init__.py`、`CITATION.cff` 一致，清楚说明研究预览/正式发布状态。

安装包验证：构建 wheel，在第三个干净审计环境安装它，在仓库外执行离线 demo 和至少一个官方消费者检查，确认新增辅助模块被打包。
不要只通过 editable 安装测试就宣称 wheel 可部署。GPU 环境未打包到 wheel；普通用户仍应能仅安装 `.[repair]` 使用 CPU 审计。

GitHub 标准 runner 没有这台 4090，不应把普通 CI 的 GPU skip 算作硬件实验通过。硬件报告与普通 CI 分开保存。

## 11. 推送 GitHub 与交付

实验和代码修改完后，检查最新远端差异、测试和待提交文件清单。只 stage 本次代码、测试和经过清理的报告，**不要 `git add .`**。

```bash
git diff --check
git status --short
git diff --stat
```

显式逐项 `git add`，提交后：

```bash
git push -u origin HEAD
```

使用已授权的 GitHub 登录创建独立分支 PR，正文写明问题、改动、完整复现命令、GPU 实测范围、性能口径、失败/未知结果和局限。
默认保留 PR 供所有者审阅；若所有者明确要求合并，则在检查通过后正常合并。不要强推 main，也不要为了通过 CI 移除负例。
如果远端已有新提交，正常整合并对最终 SHA 重跑受影响检查；不要让旧结果看起来像针对新代码取得。
如无 GitHub 写权限，仍完成本地开发、测试、文档和提交，并交付 commit SHA、补丁及准确的待推送分支；不要回传或索取明文 token。

最终给所有者的报告必须回答：

- 测试了哪个代码提交、哪张卡、哪套 OS/驱动/Torch/TorchCodec/FFmpeg？
- 哪些仍是 CPU 路径，哪些确实是 GPU 解码？是否使用自定义 adapter？
- 请求了多少查询、实际核对多少、多少明确正确/错误/无法判定，哪些未完成？
- 与本机 CPU 和 CUDA 构建下 CPU 路径相比，哪里加速、哪里没有？计时是否包含初始化、传输和参考核对？
- 源文件与恢复哈希是否一致？人工错误是否仍被正确检出？
- 实际修复了什么、还有什么不支持、普通 CPU 部署是否仍通过？
- 更新在哪个 GitHub 分支/PR，CI 最终状态如何，完整报告在哪里？

出现无法解决的 GPU 环境阻碍时，也要交付具体失败证据和已经完成的 CPU 结果；清楚标记未完成项，不将整项任务写成已验证。

## 12. 核对依据与继续阅读

以下来源在编写手册时核查，远端执行时应检查所用版本的官方说明；不可用时记录变化，不直接追随 nightly：

- [项目 0.4.1 研究与代码审查](https://github.com/SimaQie/-lerobot-boundary-audit/blob/c428c12d869e30805e514758f9ea2ae408310daf/research/REVIEW_2026-10-20.md)
- [项目 0.4.1 实验凭据](https://github.com/SimaQie/-lerobot-boundary-audit/blob/c428c12d869e30805e514758f9ea2ae408310daf/research/results/v041/README.md)
- [PyTorch 2.10.0 官方安装版本说明](https://pytorch.org/get-started/previous-versions/#v2100)
- [TorchCodec 0.10.0 安装、NVDEC 与 Windows CUDA 说明](https://github.com/meta-pytorch/torchcodec/blob/v0.10.0/README.md)
- [TorchCodec 0.10.0 CUDA 示例](https://github.com/meta-pytorch/torchcodec/blob/v0.10.0/examples/decoding/basic_cuda_example.py)
- [TorchCodec 当前兼容表：0.10 对应 Torch 2.10](https://github.com/meta-pytorch/torchcodec#compatibility-with-torch-versions)
- [官方 cu128 TorchCodec wheel 索引](https://download.pytorch.org/whl/cu128/torchcodec/)
- [NVIDIA NVDEC 能力说明](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvdec-application-note/index.html)
- [AgiBot 固定数据源](https://huggingface.co/datasets/Voxel51/AgiBotWorld2026-sample-10ep/tree/caa5bf1b0b5be48ed52d158ff0d66af40b0f9258)
- [ALOHA 固定数据源](https://huggingface.co/datasets/lerobot/aloha_static_screw_driver/tree/21eead16760a8d94d449cadf4bc438b322ab528d)

**开始执行时先回报：系统/4090 可见性、工作目录、基线 SHA 和计划使用的环境组合；随后直接推进可完成的工作。**

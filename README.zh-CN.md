# LeRobot Boundary Audit

一个可在 CPU 上运行的 LeRobot v3 视频时间轴与轨迹边界检查工具。
当前候选版本为 **0.4.2rc1 研究预览**；原 `robot_data_engineering_saved` 保留原样。
默认支持范围是 CPU 审计与受约束修复；RTX 4090/TorchCodec 是实验性研究，
不是稳定 GPU reader，微基准也不代表完整工具加速。

```sh
git clone https://github.com/SimaQie/-lerobot-boundary-audit.git
cd -- -lerobot-boundary-audit
git checkout v0.4.2rc1
python -m venv .venv
.venv/bin/python -m pip install ".[repair]"
```

发布说明、证据与限制见 [RELEASE_NOTES_0.4.2rc1.md](RELEASE_NOTES_0.4.2rc1.md)、
[RTX 4090 证据](research/results/rtx4090/session-001/README.md)、
[完整报告](research/RTX4090_2026-10-20.md)。

## 快速开始（无需下载）

```sh
.venv/bin/lerobot-boundary-audit demo --out demo-result
# 浏览器打开 demo-result/demo-report/report.html
.venv/bin/lerobot-boundary-audit audit demo-result/merged --decode --out reports/demo-clean
.venv/bin/lerobot-boundary-audit audit demo-result/offset-one-frame --decode --out reports/demo-offset
```

示例套件包含 13 个正常/人工故障案例。第一条审计退出 0（pass）；offset 案例退出 1，
报告 episode 和时间戳错误。相机交换/重复像素会故意通过 `audit`，因为时间轴和索引
合法；内容身份要用 `conformance` 或 `probe-loader`。

完整步骤、每个命令能处理什么、真实数据下载、可选官方 reader 检查和修复/恢复流程：
[中文使用指南](USAGE.zh-CN.md) · [English guide](USAGE.md)。

它检查视频帧的实际展示时间、轨迹视频起止偏移，以及数据表中的时间戳
是否一致。输出可离线打开的 HTML 报告和 JSON 证据。日常使用只需要
Python、PyArrow 和 PyAV，无需训练模型、GPU、数据库或服务器。

本轮修复非整数行号被截断后接受、重复错误邻帧被归为无法判定的问题，
并在比较动作值之前检查实际数组形状。报告逐项核对请求与返回的查询，
列出每路相机的匹配、错帧、无法判定及其原因，避免把少量抽样写成全量验证。

新增 `probe-loader --sampling stratified`，按固定种子在所选轨迹的时间区间
内分层抽样；先选时间再解码，不按画面是否容易匹配挑选样本。默认 `mixed`
仍保留原有边界抽样。查看 [本轮代码与研究审查](research/REVIEW_2026-10-20.md)
和 [AgiBot / ALOHA 重跑结果](research/results/v041/README.md)。

## 开始使用

在项目目录中：

```sh
python -m venv .venv
.venv/bin/python -m pip install ".[repair]"
.venv/bin/lerobot-boundary-audit download agibot2026 --out samples/agibot2026
.venv/bin/lerobot-boundary-audit audit samples/agibot2026 --camera observation.images.hand_left --camera observation.images.hand_right --decode --out reports/agibot2026
```

打开 `reports/agibot2026/report.html` 即可查看结果。Linux/macOS 将解释器路径
替换为 `.venv/bin/python`。下载完成后，检查和报告均可离线使用。

默认新样例来自 Voxel51 于 2026 年 9 月公开的 AgiBotWorld2026 转换子集，
固定下载版本，只取左右手腕视频和对应表格，约 217 MB，10 段真实机器人
轨迹、23,658 行。报告明确显示仅检查 7 路相机中的 2 路。
这不是官方原始数据布局；数据许可为 CC BY-NC-SA 4.0，与工具代码的 MIT
许可分开。发布包不包含下载视频、动作数据或修复后的数据副本。

## 修复与恢复

确认录制协议确实为按声明帧率连续、有序的帧后，才能使用 `--assume-cfr`。
先产生可审阅的修复计划，再写入新的副本：

```sh
.venv/bin/lerobot-boundary-audit repair-plan MY_DATA --assume-cfr --out reports/plan.json
.venv/bin/lerobot-boundary-audit apply reports/plan.json --source MY_DATA --out MY_DATA_REPAIRED
.venv/bin/lerobot-boundary-audit restore MY_DATA_REPAIRED --out MY_DATA_RESTORED
```

仅下载部分相机时，生成计划也要指定同样的 `--camera` 参数。
工具只修复受限的轨迹偏移，以及满足严格条件的少量单 tick 帧时长异常。
不会重新生成动作或修改媒体载荷。修复须通过检查才发布到新目录；
恢复会逐文件验证与修复前完全相同的哈希。干净输入没有修复操作。

无需联网的小演示：

```sh
.venv/bin/python examples/offline_demo.py --out demo-result
```

演示会生成六帧原创合成视频，注入一处时间异常，完成检查、修复和精确恢复。

## 验证结果与边界

新版特色是编码前就确定的画面编号：每帧携带相机、原轨迹、帧序号和 CRC。
通过真正的官方 `LeRobotDataset` 检查单帧、前后时间窗口、四行批量读取、
两个独立进程读取和非连续轨迹筛选，同时核对动作窗口与边界填充标记。
官方录制和合并 API 生成样例，人工偏移一帧、交换相机视频作为故障对照。
交换相机时，时间戳仍能通过检查，画面编号则能证明读取内容错误。

六个样例、两种解码器、五种读取方式，共 60 项对照符合预期；正常输入和
修复副本通过，人为故障被识别。69 项回归测试在 Python 3.11/3.12 本地通过。
没有在这些官方录制/合并产物中发现自然发生的缺陷。

仓库附有很小的原创合成数据，无需下载真实机器人数据即可试用：

```sh
python -m zipfile -e examples/frame-suite-v030.zip demo-suite
.venv/bin/lerobot-boundary-audit audit demo-suite/merged --decode --out reports/merged
```

完整官方加载器验证需另建安装 LeRobot 0.6.1 的环境，详见英文说明。
`fixture-suite` 从官方录制、合并 API 重新生成样例，满足修复条件时验证精确恢复；
若当前平台产生非均匀时间间隔，则保留五个原始对照与拒绝原因，不生成修复副本。
`conformance` 运行完整对照并生成离线报告；`verify-loader` 可只测试一种读取方式。
正常检查依然无需 Torch。合成编号仅适用于附带样例，不能推断真实视频的帧身份。

新数据的 60 个边界查询通过了本工具及官方 LeRobot 0.6.1 的 PyAV、
TorchCodec 两种读取器；独立完整解码核对了两路视频共 47,316 帧。
在单独副本中把一段轨迹偏移一帧，官方读取器出现 6 个边界错帧；
工具准确定位该轨迹，修复后全部查询通过，恢复后所有原文件哈希一致。
这些是人为故障注入，不能表述为发现了 AgiBotWorld2026 的真实缺陷。

检测覆盖存储时间轴和选定的边界查询，不证明物理相机与动作同步。
真实视频的 `verify` 调用安装好的解码函数；合成样例的 `verify-loader` 则运行完整加载器。
对分片 MP4、裁剪/多重编辑列表和过大的重排序表明确拒绝或标为未验证。
相关数据检查工具已存在，本项目不宣称“全球首次”。

完整参数、复现实验与限制见 [英文说明](README.md)。
开源地址：[SimaQie/-lerobot-boundary-audit](https://github.com/SimaQie/-lerobot-boundary-audit)。
附有 MIT 许可、中英文说明及引用文件；尚未分配 DOI。
# 0.4.0 研究预览补充

当前代码新增全局索引和数据分片关系检查，修复了“索引整体错移仍显示 PASS”的漏检。
关键元数据错误现在会生成结构化报告；不完整或无法判定的检查不会算作通过。
源码与实测报告一起公开；原有 0.3.0 的实测结果仍作为历史记录保留。

安装 `.[repair]` 后，无需下载外部数据即可运行安装包自带样例：

```sh
.venv/bin/lerobot-boundary-audit demo --out demo-v040
.venv/bin/lerobot-boundary-audit conformance demo-v040 --python 官方环境的Python路径 --jobs 2 --out reports/v040
```

新版包含 13 个原创小样例：6 个干净控制和 7 个人工故障控制。完整矩阵为两个后端、
八种读取方式，共 208 个组合。新增长窗口、随机与重复读取、跨两个 epoch 复用 worker，
以及索引、动作、画面重复/交换和多分片控制。这些不是 13 个自然发生的真实缺陷。

普通真实视频也可使用完整加载器探测，无需预先生成画面编号：

```sh
.venv/bin/lerobot-boundary-audit probe-loader samples/agibot2026 --camera observation.images.hand_left --camera observation.images.hand_right --python 官方环境的Python路径 --phase workers --max-rows 6 --out reports/agibot-probe
```

探测会将所选相机的数据复制到受预算限制的临时目录，并用顺序解码参考检查实际读取的
窗口、动作及填充标记。相同的邻近画面或无法可靠区分的 RGB 差异会标为“无法判定”，
不会强行显示 PASS。该结果只能证明相对于顺序解码参考的一致性，不能证明物理同步。
PyAV 参考与 PyAV 被测路径共享颜色转换，两个后端也有 FFmpeg 共同依赖。

默认预算：12 个查询行、累计解码 50,000 帧、参考图像 256 MiB、临时输入副本 300 MiB、
消费者 300 秒。支持选择不连续的 episode、调整窗口半径和这些预算。
参考图像预算不等于整个进程的内存上限。RTX 4090 上的 CPU 路径与独立 CUDA 实验见下文。

详细实验、比较配置和局限见 [0.4.0 实验说明](research/V040.md)。

## ALOHA 真实双臂数据对照

增加 LeRobot 官方账号的 ALOHA 螺丝刀任务数据：50 个短 episode、20,000 行、
50 FPS、14 维存储动作。只下载两路腕部相机及元数据/数据表，共 258,967,368 字节，
检查范围为 2 / 4 相机。固定版本为 `21eead16760a8d94d449cadf4bc438b322ab528d`。
这是来自 RSS 2023 研究的主流真实机器人数据，数据卡声明 MIT 许可。

```sh
.venv/bin/lerobot-boundary-audit download aloha_screw_driver --out samples/aloha_screw_driver
.venv/bin/python research/validate_real_sample.py aloha_screw_driver --source samples/aloha_screw_driver --out research/runs/my-aloha-run --consumer-python 官方环境的Python路径
```

使用与 AgiBot 相同的脚本与预算，进行存储/解码检查、官方 PyAV/TorchCodec 对照、
多进程窗口探测、全帧 PTS 参考、人工偏移定位/修复/恢复，以及全局索引错误拒绝。
Windows 的 TorchCodec 可追加 `--ffmpeg-bin` 指向已安装的共享 FFmpeg 目录。

两份真实样本均为 AV1；AgiBot 样本存储动作实际为 44 维、30 FPS。
重复邻近画面会保留“无法判定”，不会强行显示全部通过。
详细对比见 [两份真实数据的实验结果](research/results/v040-real-comparison/README.md)。

## RTX 4090 / TorchCodec 实验（2026-10-20）

默认审计与 `probe-loader` 仍是 CPU 路径：没有 `--device` 参数，安装 CUDA 版 Torch
不会改变官方 LeRobot 0.6.1 读取器的解码设备。独立的
`research/benchmark_gpu_decode.py` 显式比较 `device="cpu"` 与 `device="cuda"`，
并用 marker 身份和顺序 PyAV 参考核对。

在本机 WSL2 + RTX 4090 上，现有 CPU 流程 208/208 通过，两份真实数据验证均为
`expected_outcomes_met`；CUDA 构建下 CPU 路径 78/78 通过。显式 CUDA 调用输出在
`cuda:0`、无 CPU fallback；解码器预热后，32 帧单视频“解码 + H2D + checksum”
微基准快 1.37–2.34×。这不是完整审计/窗口/动作/DataLoader 的加速，也不代表 RGB
输出等价；CUDA RGB 与 CPU 不一致（TV range 类），真实画面身份仍有大量“无法判定”
（0 个明确错帧），因此没有把 GPU 接入默认读取流程，也不宣称稳定 GPU 支持。
证据见 [session-001](research/results/rtx4090/session-001/README.md) 与
[完整报告](research/RTX4090_2026-10-20.md)。

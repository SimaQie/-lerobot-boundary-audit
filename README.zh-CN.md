# LeRobot Boundary Audit

一个可在 CPU 上运行的 LeRobot v3 视频时间轴与轨迹边界检查工具。
这是独立重写的 0.3.0 版本；原 `robot_data_engineering_saved` 保留原样。

它检查视频帧的实际展示时间、轨迹视频起止偏移，以及数据表中的时间戳
是否一致。输出可离线打开的 HTML 报告和 JSON 证据。日常使用只需要
Python、PyArrow 和 PyAV，无需训练模型、GPU、数据库或服务器。

## 开始使用

在项目目录中：

```sh
python -m venv .venv
.venv/Scripts/python -m pip install ".[repair]"
.venv/Scripts/python -m boundary_audit.cli download agibot2026 --out samples/agibot2026
.venv/Scripts/python -m boundary_audit.cli audit samples/agibot2026 --camera observation.images.hand_left --camera observation.images.hand_right --decode --out reports/agibot2026
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
lerobot-boundary-audit repair-plan MY_DATA --assume-cfr --out reports/plan.json
lerobot-boundary-audit apply reports/plan.json --source MY_DATA --out MY_DATA_REPAIRED
lerobot-boundary-audit restore MY_DATA_REPAIRED --out MY_DATA_RESTORED
```

仅下载部分相机时，生成计划也要指定同样的 `--camera` 参数。
工具只修复受限的轨迹偏移，以及满足严格条件的少量单 tick 帧时长异常。
不会重新生成动作或修改媒体载荷。修复须通过检查才发布到新目录；
恢复会逐文件验证与修复前完全相同的哈希。干净输入没有修复操作。

无需联网的小演示：

```sh
python examples/offline_demo.py --out demo-result
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
lerobot-boundary-audit audit demo-suite/merged --decode --out reports/merged
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

# LeRobot Boundary Audit 下一阶段开发 SOP

本文件取代此前面向下一阶段开发的零散计划。现有 GPU_MACHINE_VALIDATION.md 是历史实验记录，应保留，不能作为本轮新结果。

## 目标与边界

仓库：https://github.com/SimaQie/lerobot-boundary-audit 。以远端 main 最新提交为基线，记录完整 SHA，先检查工作区，再执行 git pull --ff-only。不要覆盖本机已有修改或移动已发布标签。v0.4.3 是已发布版本；本轮代码在开发分支工作，拟发布 v0.5.0。未经用户指示不创建正式 Release。GPU 可用，但基线仍为 CPU 数据管线。

本地已新增 audit --visuals：最多四个边界查询，显示顺序解码参考、相邻帧和本地 PyAV 返回帧。它不是官方 loader 像素证据，不能把这项功能误报为完整的多读取器可视化。

## 1. 准备环境和复现基线

阅读 README、USAGE、CONTRIBUTING、research/CONFORMANCE.md 和 research/GPU_MACHINE_VALIDATION.md。建立审计环境，安装 .[repair,dev]；分别建立 LeRobot 0.6.1 基线 consumer 与较新稳定版 consumer。先查询上游正式 release / PyPI，核实版本、Python、Torch、TorchCodec 和 FFmpeg 约束，再固定完整依赖，不直接用上游 main 代表稳定版。

先运行 pytest、Ruff、离线 demo、已安装 wheel 检查和现有 conformance。记录操作系统、CPU、GPU、驱动、Python、pip freeze、解码设备、命令、退出码和耗时。CUDA Torch 安装不等于 GPU 解码。

## 2. 数据

优先复用带 source_manifest.json 且哈希匹配的样本；否则使用项目 download 的固定 revision 预设：aloha_screw_driver、cmu_stretch、utokyo_xarm、agibot2026。不要下载完整大型数据集。预设相机从下载清单读取，独立命令显式传 --camera。AgiBot 受 CC BY-NC-SA 约束；本轮公开画面优先 ALOHA，保留其 MIT 许可及来源，不能把所有数据衍生物归为项目原创 MIT。

## 3. 完成官方读取器画面证据（最高优先级）

在实际 loader 调用处捕获返回像素，并保留独立顺序解码的预期与前后帧。保存 row、episode、camera、delta、预期 ordinal、实际返回标签、PTS、比较结果、来源文件哈希、环境和图像哈希。不能用按时间戳重新解码的画面冒充 loader 实际返回像素。

沿用 opt-in、条目数/解码帧数/内存/输出字节预算。HTML 使用相对路径，可离线打开；缺失媒体或预算耗尽显示未完成，不修改原审计 verdict。多次生成到同一输出路径时不得出现旧画面与新报告错配。重复静止画面、色彩转换和非唯一邻帧匹配保留 ambiguous/PARTIAL。

生成真实机器人三组证据：干净对照；在副本中注入跨 episode 一帧偏移；经过受保护修复后的复验。展示预期与实际差异，而非只展示毫秒数。另选一个窗口/actions/padding 故障展示修复范围之外的问题，不暗示工具能自动修复。可导出 20–40 秒真实画面视频，并给出其证据 JSON 和重建命令。

## 4. 读取器兼容回归

相同查询清单对比两代稳定 LeRobot × PyAV/TorchCodec。先跑 bundled 13-case conformance 和全部可用 phase；再跑四来源真实小样本边界 verify、probe-loader（single/window/batch/workers/random/persistent）、人工偏移、repair、官方复验、restore 精确哈希及危险索引修复拒绝。记录每个组合的 requested/observed/missing/unexpected 查询数。

上游接口不同，使用明确版本适配，不悄悄忽略参数。版本不支持、依赖不可用、超时、预算不足与结果错误分开。兼容表只填实际执行过的组合；不把 skipped 或 PARTIAL 写成 PASS。

## 5. 可重复评测与反例

先盘点现有故障，避免重复。补充合法静止帧、episode 边界 padding、合法子集索引、非整数 FPS（若格式允许）、时间基舍入和合法长 GOP 等容易误判反例；明确哪些布局应拒绝、哪些合法支持。人工故障可包含 episode offset、错误 shard/index、漏帧/重复帧、相机交换和 action/window 故障，各检查器的能力分别计分。

公开故障生成脚本、种子、真值清单、准确命令和精简 JSON 结果。报告按故障类的检出、干净反例误报、歧义、覆盖及耗时；说明统计分母，不把多个重复查询当独立数据集。四个真实来源的自然审计与人工注入结果分别列出。没有确认的上游自然缺陷就明确写没有，不为宣传强行找错。

## 6. 易用性和性能（完成以上后）

增加环境诊断及统一检查入口，输出检查计划、安装建议、实际完成与未完成项目。自动相机选择必须显式展示范围；不隐藏缺失相机。

先测长视频和多 episode 的 seek/参考解码开销，再做排序合并或持久化缓存。缓存键覆盖源内容、代码、版本、相机、查询与配置；内容变更必须失效，支持关闭缓存。报告冷启动/热缓存耗时、峰值内存与磁盘开销，并验证缓存开关不改变结论。

## 7. 发布和文档

release workflow 应检查标签版本等于包/runtime/citation 版本，运行测试与隔离安装验证成功后才能上传资产；普通 main push 不发布，不覆盖既有 Release。安装文档提供固定发布版本路径。

更新中英文使用指南、CHANGELOG、兼容表、评测结果与媒体来源。原始大型输出留本地，公开必要精简证据与复现脚本；不提交 venv、样本、模型或个人路径。没有实测结果时不得预写成功数字。

## 8. 完成验收与交付

所有已有测试通过，新增测试涵盖证据像素来源、歧义保留、预算耗尽、离线资源、源文件不变及缓存失效。Linux/Windows CI 通过；分发 wheel 安装后可运行真实帧功能。两代读取器各组合结果完整，失败均有解释。至少 ALOHA 一个真实机器人证据案例可从公开命令重建。

交付：提交 SHA、改动摘要、完整执行矩阵、精简结果文件、未解决问题及风险、HTML/视频路径、可重建命令。用户已要求下一阶段开发，但正式 tag/Release 另按用户发布指示执行；需要推送时使用新开发分支，保留已发布 main 历史。

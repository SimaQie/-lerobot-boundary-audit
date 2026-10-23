# 0300f84 发布复审（2026-10-20）

审阅提交：`0300f849cb48da661e976cdafe4be0f98f3ffb8a`，分支 `experiment/rtx4090-validation`。
对照上次审阅的 `261ba3a`，本轮没有修改项目源码、提交或推送，也没有发布 Release。

## 判断

已经适合作为 **0.4.2rc1 研究预览**对外展示、邀请试用；暂不建议直接宣布无 rc 的正式稳定版。
上次两项 P1 原始反例和报告失败问题已修复。本轮另外确认两处 P2 性能评估边界缺陷，建议作为正式发布前的小补丁处理。
它们不会推翻已上传的默认五次重复实验：公开结果的 12 项正确性任务与 12 项性能任务完整，真实性覆盖不足被正确保留为 PARTIAL。
不需要因此追加大规模数据、训练或机器人实验。

发布定位应为“LeRobot v3 边界审计、受约束修复及可复现实验工具，附实验性 CPU/CUDA 解码研究”。现有证据不能支持“稳定 GPU reader”或“整个工具加速 1.37–2.34 倍”。

## 仍需处理的发现

### [P2] 零次性能重复也能产生 PASS

位置：`research/benchmark_gpu_decode.py:702`、`src/boundary_audit/gpu_benchmark.py:249`。

`--repeats` 及配置的 `performance.repeats` 没有正整数校验。循环可以执行零次，`run_performance` 用 `len(values) < repeats` 判定不完整，汇总器也用同样的下界检查，因此零条计时满足了零次要求。

本地实际使用 CPU TorchCodec、两帧小样本、`repeats=0` 完整运行，结果：

```json
{"status":"pass","native":{"count":0},"end_to_end":{"count":0},"raw":{"native_seconds":[],"end_to_end_seconds":[]}}
```

进程退出码为 0，顶层和性能分项都是 PASS。计时中位数不存在。

建议：在配置和命令行覆盖值合并后统一校验 `repeats >= 1`；汇总器也独立拒绝无计时样本的性能 PASS。顺便校验 frames、batch size 为正整数、warmup 非负、时间预算为有限正数。测试应通过真正的入口验证配置及 CLI 覆盖值 0、负数，而不只测试正常样本计数。

### [P2] 性能子结果的 PARTIAL 或未知状态没有被保守传递

位置：`src/boundary_audit/gpu_benchmark.py:260`。

该分支处理 unavailable/error/failed/fail，却没有处理 partial 或其他未知值。以完整两次计时的正常摘要为基础，仅将一个性能子任务的状态改为 `partial`，再次评估，得到性能和顶层 `pass`。

这是汇总函数的确定反例；本轮未发现已上传结果受影响。目前生成器多数 partial 路径恰好也会缺少计时，从而被后面的计数检查拦住，但汇总规则本身仍会升级已有的不完整状态。

建议：仅显式 `status == "pass"` 才有资格通过；partial 传播为 partial，未知或缺失状态也不得 PASS。补充“样本数足够但子任务仍为 partial/未知状态”的测试。

## 上次发现的复核

| 项目 | 本次独立复核 |
|---|---|
| R1 缺失任务、源变更、性能不可用被忽略 | 缺失任务为 partial；完整性变化为 fail；性能 unavailable 为 partial。原始反例关闭，但仍有上述两处边界遗漏 |
| R2 CPU/GPU 同时取错下一帧却互相证明正确 | 在真实 CPU TorchCodec 外包一层将时间请求统一错移一帧；t=0 的独立预期仍为 ordinal 0，返回 PTS 1/30，结果为 pts_mismatch、整体 fail |
| R3 单侧错误报告含 Tensor、预算退出无摘要 | 单侧解码错误为 fail，整个结果可 JSON 序列化；1e-9 秒预算为 partial，summary、source-integrity 和 evidence.zip 全部存在 |
| 性能 batch 比较的请求不同 | 公布的每个输入在不同设备、所有 batch size 上使用同一组索引 |
| sdist 缺少研究脚本 | 本地重新构建的 sdist 已包含 benchmark_gpu_decode.py |
| 文档路径和版本 | session README 的报告链接已修正，demo 路径与配置一致；包、CITATION、CHANGELOG 为 0.4.2rc1 |

## 测试、CI 和证据

- 本地 Windows/Python 3.11：`129 passed, 1 skipped`；跳过的是平台符号链接能力测试。源代码、测试和 benchmark 的 Ruff 检查通过。
- 最新提交的 GitHub Actions run `39358177883` 五项作业全部成功：Windows/Linux × Python 3.11/3.12，以及 official-loader。链接：<https://github.com/SimaQie/-lerobot-boundary-audit/actions/runs/39358177883>。
- 本地成功构建 `0.4.2rc1` wheel 和 sdist；sdist 携带研究 benchmark。新建无 Torch、无 NumPy 的环境安装 wheel 后，版本和辅助模块导入检查通过。
- 审核上传的 CPU conformance 208 项及 CUDA 构建下 CPU 路径 78 项，每项 matched_expectation 与 source_unchanged 均为 true。这是核对远端记录，不是本地重新跑 4090。
- GPU 报告指向干净提交 `152cb2c`；该提交至当前 HEAD 没有 src、tests 或 benchmark 脚本变更。
- GPU summary 的 12 项正确性任务、12 项性能任务没有缺失；逐检查重算 counts 与报告一致；输入及 oracle 完整性 PASS；两份 evidence.zip 的 CRC 检查通过。
- CUDA ALOHA 52 pass /112 ambiguous，AgiBot 4/40，另各有两个预期文件末尾错误；未发现明确错帧，但很多帧身份仍未证实。CPU/CUDA RGB 不相等。
- 1.37–2.34 倍仅属于单视频、32 帧、复用解码器、带 H2D/checksum 的微基准；不是完整审计或训练加速证据。
- clean-clone-check 明确说明复用了 CPU consumer 和只读样本，不能称为从零安装整个 GPU 栈的验证。

本地本轮复现：`research/runs/review_remote_0300f84.py`，结果在 `research/runs/review-remote-0300f84/reproductions.json`。这些辅助文件不属于提交代码。实际 CPU 解码反例使用现有 `.consumer-env` 和 `tools/ffmpeg/bin`，不需要 GPU。

## 发布前最后步骤

1. 修复上述两项 P2，补回归测试。默认 repeats=5 的计时算法和请求不变时，无需重跑所有昂贵实验；用小样本重跑异常路径、正常 smoke 与 CI 即可。
2. 合入主分支，README 首页明确显示最新候选版及支持范围。目前 origin/main 仍是 `c428c12`，没有该实验分支的 PR，也没有任何 GitHub Release；默认 clone 看不到本轮改进。
3. 首次发布建议保留 rc/preview 标记，附版本化安装方式、已知限制、复现实验入口和 wheel/sdist。若后续去掉 rc，应同步版本与引用文件，并对对应提交完成安装及 CI 检验。

本轮可以宣传工具的审计方法、独立标记对照、故障控制与可复现性；GPU 身份验证、色彩差异和完整 GPU reader 留作后续研究方向。

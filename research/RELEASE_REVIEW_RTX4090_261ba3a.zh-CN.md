# RTX 4090 实验分支发布审查

审查日期：2026-10-20。被审查提交：`261ba3a74e2bec72acb768d0cda1f78c6e71e0cf`。
分支：`experiment/rtx4090-validation`。对照基线：`main` 的 `c428c12d869e30805e514758f9ea2ae408310daf`。

## 结论

**有明确进展，适合在修复下面三个验证缺口后发布“CPU 工具 + GPU 解码研究预览”的阶段性版本；不建议直接按当前实验分支宣传发布，也不能称为稳定完整 GPU reader。**

核心 CPU 功能没有在本次审查中发现回归。阻碍当前新版发布的主要问题在新增 GPU benchmark 的证据判定和失败报告，而不是缺少大规模模型训练。
无需为第一次阶段发布先增加第三个数据集、训练大模型或实现完整 GPU DataLoader。

审查只修改了本地审查材料，未更改被审查的生产代码，未合并 main，未推送或创建 Release。
已将实验分支检出到本地 detached HEAD，原 main 指针和历史备份保留。

## 已经解决或有充分进展的事项

| 之前的问题 | 本轮证据与判断 |
|---|---|
| 日期/系统写死为 Windows | `environment.py` 动态采集系统、时间、时区、GPU；报告提供实际 WSL2 信息。已改善。 |
| Linux venv 路径被 resolve 到基础解释器 | 三个验证脚本改用保留 symlink 的绝对路径，增加回归测试。修复方向正确。 |
| CUDA 构建被误当作 GPU 解码 | CPU-only、CUDA-build CPU 路径、显式 CUDA decoder 三组分开，记录 CUDA 张量和 fallback 状态。已取得真正 GPU 解码证据。 |
| 原有 CPU 工具能否移植到服务器 | 两套官方后端、208 组 CPU 人工基准、78 组 CUDA-build CPU 基准、两份真实数据的修复/恢复均有报告。 |
| 普通真实画面重复导致无法判定 | mixed/stratified 原结果复现；GPU 不确定性继续保留 PARTIAL，没有宣传全部通过。 |
| 轻量部署是否被 CUDA 拖重 | 基础依赖未增加 Torch/CUDA；新增 metrics 对 NumPy 延迟导入，干净 wheel 环境可导入两个新模块。 |

实际实验是 **Windows 宿主上的 WSL2**，不是已经验证任意裸机 Linux。GPU benchmark 的两份真实输入各取一个左腕 AV1 文件；不要把它宣传为全部相机或完整 Dataset GPU 路径验证。

## 必须修复的审查发现

### R1 / P1：汇总可以把证据缺失或失败判成 PASS

位置：`research/benchmark_gpu_decode.py:736–778`。

本地直接调用当前 `evaluate()`，复现了三个结果：

| 输入情况 | 当前输出 | 正确要求 |
|---|---|---|
| 配置请求的 input/device 完全没有 correctness 结果 | `pass` | 不能 PASS，应报告缺失/未完成 |
| `source_unchanged=false`，其他 correctness 正常 | `pass` | 源文件变化必须阻断可信结论 |
| 性能组返回 `status=unavailable` / decoder failed | `pass` | correctness 与 performance 分开定级；失败性能任务不得消失 |

缺失结果在 742–743 行被直接跳过；没有检查源完整性；性能循环只检查 fallback，没有检查 error/status/次数完整性。
这不说明现有远端报告造假：当前已发布的 GPU summary 为 PARTIAL，而且实际请求计数是完整的。但这个汇总器还不能保障下一次实验的结论。

修复与验收：

- 从 config 构造应完成的 input × device × mode × batch/repeat 清单，缺项不可 PASS。
- 源文件或 oracle 变化应明确失败；分别记录 correctness、performance、integrity 状态。
- 传播 unavailable、预算不足、异常、无有效计时等状态，禁止空集 PASS。
- 给以上三个反例、缺少一个 CUDA 子任务、repeats 不足、全部正常等情况加不需要 GPU 的回归测试，并纳入普通 CI。

### R2 / P1：时间查询参考跟随 CPU 返回值，可能共同错一帧仍通过

位置：`research/benchmark_gpu_decode.py:455–474`、`560–578`。

时间查询的 expected ordinal 来源是 `round(cpu_returned_pts * fps)`，后续再拿这个 ordinal 查询 marker oracle。
如果 CPU 和被测路径都返回下一帧，比较器会一起移动“正确答案”。独立 PyAV 的图像虽然存在，但也是按这个已移动 ordinal 取出，无法补回原请求的时间约定。

本地使用真实原创 marker 视频、CPU TorchCodec 和故障注入 decoder 复现：

```text
请求时间              0.0 s
两条路径返回 PTS      0.03333333333333333 s
实际返回 marker       camera 0 / episode 0 / frame 1
当前 time check       pass
当前 correctness      pass
```

这是审查注入的反例，不是宣称已发现远端 GPU 自然错帧。

修复与验收：

- expected time-to-frame 映射必须独立于被测 CPU/GPU decoder 的返回值。
- 对 marker CFR 用编码前 oracle 的已知时间合同；对真实视频建立顺序 PyAV 的 PTS/duration 区间参考。
- 明确 `get_frames_played_at` 的展示区间语义，独立核对请求应落入的帧；不能仅比较 CPU/GPU 两个返回 PTS 是否相同。
- 无法建立独立时间映射时标记未验证，不能宣称时间读取正确；不要直接扩展到未验证的 VFR。
- 添加“双方同错下一帧”“单方错帧”“非整数帧时间”“最后有效时刻/独占结尾”等反例。上述 t=0 反例必须失败。

### R3 / P2：遇到真实失败时可能丢掉结构化报告

位置：`research/benchmark_gpu_decode.py:554–555`、`886–887`、`914–915`。

本地复现：

1. 时间查询一侧成功、另一侧抛错，成功侧的原始 Tensor 被放进 `cpu_error`/`device_error`。结果本身已标 fail，但 `json.dumps` 抛出 `Object of type Tensor is not JSON serializable`，无法正常写完整报告。
2. 使用极小的正数 wall-clock 预算，循环外抛出 `BudgetExceeded`，没有 `summary.json`，也没有最终源完整性记录。报告预算不足的路径未完成。

修复与验收：

- 报告只保留可 JSON 化的 shape/device/PTS/错误类型等信息，不写原始 Tensor 或真实像素。
- 每阶段持久化结果；预算到期与异常通过最终汇总输出 PARTIAL/unavailable，并标明未完成请求。
- 用 finally 或明确的收尾逻辑记录源完整性；不可取得时标 unknown，不能伪造 unchanged。
- 区分软预算与真正进程超时；如要承诺硬超时，由父进程管理消费者退出并保存已完成证据。
- 为单侧错误、预算耗尽和报告写出增加普通 CI 回归测试。

## 性能与 GPU 完整性：需要收窄的宣传口径

公开原始数据与计数核对一致，两个 ZIP 均通过 CRC 检查，同一 batch 的 CPU/CUDA 请求序列也相同；未发现计数凭空增加或删去不确定样本。

但 GPU 的有效真实请求中：

| 数据 | 明确匹配 | 无法判定 | 另有文件结尾预期错误 |
|---|---:|---:|---:|
| ALOHA CUDA | 52 | 112 | 2 |
| AgiBot CUDA | 4 | 40 | 2 |

因此“没有检出 wrong frame”不等于“所有帧都已验证正确”。这个限制原报告总体写得诚实，应继续保留。

1.53–2.15× 数字的实际范围是：**32 帧、单视频、复用 decoder 的 decode +（CPU 路径的 H2D）+ GPU checksum 微基准**。
它不是包括存储审计、参考核对、窗口/动作/填充、两路相机和 DataLoader 的完整工具加速。
CUDA 与 CPU RGB 也未达到相同数值语义；当前性能区间不包括研究中讨论的 limited-to-full 修正。

发布前的最低动作是：README/CHANGELOG 把“end-to-end gains”改成上述准确范围，明确未证明相同 RGB 输出质量及完整流程提速。
若要保留更强“等价输出加速”结论，应在相同颜色/布局/类型/输出端点下重新测量，并把相应转换成本算进去。

另有两个后续方法改进：

- 同一输入不同 batch 的随机索引目前由 `seed + batch_size` 生成；直接比较 batch 效果时应固定同一请求序列。
- 当前性能段的 first-decode 已在整个进程完成 correctness/CUDA 工作后测量，只能作为新 decoder 的首次调用，不应称为全新进程的 CUDA 冷启动。

## 发布整理项

- 新代码只在实验分支，main 仍停留 0.4.1；没有 PR。先修复、建立 PR、验证最终合并提交，再做版本 Release。
- `pyproject.toml`、包内版本和 CITATION 仍为 0.4.1；不要把不同代码都发布成同一个正式版本。建议以 **0.4.2rc1 研究预览** 为候选，最终命名按实际范围确定。
- 实测 sdist 能构建，但不含 `research/benchmark_gpu_decode.py`。如果发布入口承诺源码包可以复现 GPU 实验，必须补充 MANIFEST，或明确要求 clone 固定 Git 提交及其研究材料。
- session README 的 `../../RTX4090_2026-10-20.md` 相对链接不存在；可链接同目录已有副本或正确的 research 根文档。
- 顶层复现流程生成 `demo/`，公开 benchmark config 却引用 `research/runs/rtx4090/session-001/demo/`；统一路径，并从全新 clone 真正走一遍。
- 新 benchmark 不在现有 CI 的静态检查命令中，tests 也没有覆盖其汇总/时间参考/错误写出。应补上无硬件可运行的这些测试；GPU 硬件测试另列。
- GPU benchmark 在 `88ae99b` 测得，最终 tip 另有 NumPy 延迟导入改动。该改动看上去不改变数值运算，但正式发布凭据要区分原始测量 SHA 与最终被测 SHA；至少对最终代码补做 GPU 小规模冒烟和关键负例。

## 本地复核结果及边界

- 拉取远端 Git 对象成功，核对实验分支 tip 与 GitHub 一致。
- 新 tip 的 GitHub [39312361496](https://github.com/SimaQie/-lerobot-boundary-audit/actions/runs/39312361496) 五组任务均成功。
- Windows/Python 3.11 本地 `pytest`：**114 passed、1 skipped**；跳过项为 symlink 能力测试。
- 手动静态检查包含新增 benchmark：通过。
- wheel 和 sdist 均构建成功；全新无 Torch/NumPy 环境安装 wheel 后，可导入新增 environment 和 metrics 模块。
- 208/208、78/78 的 expected/source 标记全部一致；GPU 原始逐项计数与汇总一致，实际请求数与计划一致；证据 ZIP CRC 通过。
- 本地没有 4090，未重复远端 GPU 性能或硬件解码实验。GPU 部分结论来自代码、原始报告和可在 CPU 上完成的逻辑反例。

本地反例和校验凭据：

```text
research/runs/review-remote-261ba3a/reproductions.json
research/runs/review-remote-261ba3a/evidence-verification.json
research/runs/review_remote_261ba3a.py
research/runs/check_remote_evidence_261ba3a.py
```

## 建议的最小下一轮，不必重开大工程

1. 修 R1/R2/R3，加入无 GPU 回归测试，并纳入 CI。
2. 在远端最终代码上补跑 marker 关键负例、独立时间映射和一组真实 AV1；保留原始报告，新增修订实验目录。
3. 收窄性能措辞；若不再主张等价输出/完整工具加速，无需为了阶段发布先补大规模性能矩阵。
4. 修复干净 clone 的复现路径、源码包范围、文档链接和版本一致性。
5. PR 合入后以“轻量 CPU 审计/受保护修复，附实验性 RTX4090 解码研究”发布候选版本。若要宣布稳定 GPU reader，则另需完整 Dataset 的窗口/动作/填充与 worker 适配验证，不属于本轮候选。

这个范围能够形成可信、可复现、有明确边界的阶段性开源成果，不需要先把项目扩展成通用机器人数据平台。

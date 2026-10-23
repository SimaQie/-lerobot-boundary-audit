# 首个公开版本复审：e988306

日期：2026-10-20。审阅对象：`main` / `v0.4.2rc1`，提交 `e98830654631b7e557ef4136532ffe4d3414dc00`。

## 发布判断

**代码、验证证据和使用文档已经具备作为首个公开研究预览版的完整度。** 上次两项 P2 判定漏洞已经关闭，本轮未发现阻止当前固定版本用于公开试用的新算法问题。

GitHub 已存在 `0.4.2rc1` prerelease，附 wheel、sdist 和中英文指南；主分支与标签均包含修复。当前下载包与标签一致，可以邀请研究者试用这一固定版本。建议在正式推广及下一次主分支更新前处理下面的发布流程问题，并补齐快速入门的环境激活步骤。

保留“research preview”标识即可开展首次公开发布，不需要为了发布再追加训练、大数据或 GPU reader 开发。CPU 审计与受约束修复是支持路径，GPU 是附带的研究实验；尚不能宣传稳定 GPU reader、训练收益或整个工具的加速比。

## 上轮问题已解决

1. `performance.repeats=0/-1`：真实 `main()` 入口在创建运行目录和解码前抛出明确 ValueError。配置合并 CLI 覆盖值后统一校验；直接把零次计时摘要交给汇总器，结果也是 fail。
2. 性能 partial 被升级为 pass：完整计时数量下，partial 保持 partial；unknown 和缺失状态也为 partial；正常 pass 保持 pass。

相关回归测试已经纳入普通 pytest，无需 GPU。

使用最新汇总器重新评估远端实验：12/12 正确性任务、12/12 性能任务齐全，完整性 pass；真实画面身份仍有 ambiguity，因此总结果正确地为 partial。没有把未知样本算作成功。

## 本地独立验证

- 完整测试：133 passed、1 skipped（Windows 符号链接权限限制）；Ruff 通过。
- 最新提交 CI：Ubuntu/Windows × Python 3.11/3.12 与 official-loader 五项全部成功。
- 直接下载 GitHub Release 的 wheel 和 sdist，校验 SHA-256 与 GitHub 公布的 digest 一致。
- wheel 中全部 Python 源文件逐一与 `v0.4.2rc1` 比对，无差异；sdist 中 benchmark、两份 USAGE 和 pyproject 与标签一致。
- 新建 Python 3.11 环境，仅安装下载的 wheel `[repair]`，实际安装 PyArrow 23.0.1、PyAV 16.1.0，无 Torch、无 NumPy。
- 用这个安装后的命令执行：离线 demo、干净样本审计、offset 故障检测、全局索引故障检测、repair-plan、apply、修复后审计、restore。全部退出码符合预期。
- 独立逐文件哈希检查：源数据未变，恢复后的文件集合和内容与原始故障样本完全一致。
- 本轮没有重新运行 4090；GPU 结论来自已上传的实验记录及最新评估逻辑重算。

下载资产哈希：

```text
wheel d61cb50a3818a56a27321c54d0b92a456528d2dad222708a7bae382f8fc19ba1
sdist 176c228acff08009aacaf33c23671f7dc0ce7a579bf6d9682809606453816eae
```

本地验证记录：`research/runs/review-release-e988306/artifact-check.json`、`regression-check.json`、`walkthrough-check.json`。运行辅助脚本和环境均在忽略的 runs 目录中。

## 发布收尾建议

### [P2] 固定版本的附件会被后续 main 提交覆盖

位置：`.github/workflows/release.yml:3`、`:45`。

工作流由每次 main push 触发，从该次 main 提交构建，却始终向固定 `v0.4.2rc1` 上传，并带 `--clobber`。未来任何源码更新都可能替换旧版本的同名安装包，即使标签不动；若以后修改包版本，还可能把新版本附件塞入旧 Release。发布作业与 tests 工作流也没有通过依赖关系绑定。

当前实际下载包与标签一致，**没有发现本次包已损坏或错配**。问题是下一次正常开发提交就会再次触发覆盖，破坏版本可复现性。

建议在下一次 main push 前修正：以版本标签或显式发布操作触发，检出明确标签提交，校验包版本与标签一致，要求该提交测试通过后才发布；正常发布不覆盖已有同名附件。后续修订用新版本，保留已公开标签和包。

### [P2] 新用户按 Quick start 操作可能找不到命令

位置：`README.md:7`、`USAGE.md:33`、`USAGE.zh-CN.md:31`。

安装步骤通过 `.venv/bin/python -m pip` 安装，却没有激活虚拟环境，后面直接运行裸命令 `lerobot-boundary-audit`。干净终端不会自动将这个 venv 的 bin/Scripts 加到 PATH；机器上若有旧的全局安装，还可能运行错版本。Windows 路径在正文有说明，但 POSIX 示例同样需要修正。

建议统一在安装后执行 `source .venv/bin/activate`，Windows 给出相应激活方式；或者全部使用 `.venv/bin/lerobot-boundary-audit` / `.venv\Scripts\lerobot-boundary-audit.exe`。同时写明 Python >=3.11。Release notes 已使用完整路径，可作为统一模板。

## 推荐首次公开定位

“一个轻量的 LeRobot v3 数据边界审计与受约束修复工具，提供独立帧标记对照、13 类合成案例、208 项读取一致性验证，以及两种真实机器人数据样本的可复现实验。”

强调具体解决什么问题、如何两分钟运行示例、检查范围和无法判定的情况。可公开介绍 CPU/CUDA 解码观察，但将 GPU 颜色差异、部分身份无法验证和单机微基准限制放在结果旁边。

当前 Release：<https://github.com/SimaQie/-lerobot-boundary-audit/releases/tag/v0.4.2rc1>

当前 CI：<https://github.com/SimaQie/-lerobot-boundary-audit/actions/runs/39370242137>

本轮仅审阅和本地验证，没有修改项目源码、工作流、已发布附件或标签，没有推送。

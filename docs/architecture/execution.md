# 执行工程

适用：新活动的 `harbor-process-v1`。旧固定 Runner 见[兼容规则](compatibility.md)，开发参数见[完整工程 SDK 指南](../../knowledge/plugin-sdk/guides/process-harness.md)。

## 策略所有权

Meta 从 [默认工程](../../templates/harness/default/harness.json)开始，可以改变语言/框架、入口、依赖、profile、提示、工具、终端、会话、辅助调用、上下文压缩及恢复。默认 DSH、bash/MCP 工具和异常恢复都是候选文件。平台不固定工具清单、请求次数或单会话策略，也不要求先测全部 H0。

不随候选变化的条件包括活动固定 Solver 与调用设置、任务公开范围、真实凭据边界、官方评分权威、隔离、benchmark 时限、用户活动上限和外部资源容量。候选可以申报插件用途与源码路径供阅读，但声明不授予权限、不构成策略白名单。

## 工程与构建

`harness.json` 声明 runContract、entrypoint、build.image、build.argv、build.locks，可带 framework/profile/plugins 展示信息及 runtimeConfig。准确字段以[工程 schema](../../schemas/execution/harness-project.schema.json)为准。

构建容器在 `/candidate` 使用冻结源码，允许联网安装锁定依赖与执行安装脚本；不提供宿主目录、容器控制 socket、供应商凭据、控制数据库或私有 verifier 输入。内部链接可展开，逃逸链接、特殊文件和不稳定源码快照被拒绝。构建镜像解析为不可变 ID，记录源码、文件执行模式、锁、命令、资源、产物及回执摘要。

构建资源来自[process-resources.json](../../schemas/execution/process-resources.json)，创建时冻结。`candidate_check` 验证隔离构建和产物入口，`candidate_freeze` 保存同一内容身份；检查不会调用真实模型或创建 Trial，不能证明入口实际完成任务。构建实现见[project.py](../../src/execution/bundle/project.py)，平台接入见[process_candidates.py](../../src/control/process_candidates.py)。

## 正式启动与模型通道

候选产物在 Harbor main 的 `/opt/harness` 中执行，cwd 为 `/app`。`PHYEXP_CONTEXT` 指向上下文 JSON，包含任务原文、workspace、mcpServers、deadline、outputDirectory、固定 solver、resources 与 modelChannel。候选自带所需语言运行时或显式依赖任务环境，正式执行不重新安装构建依赖。

main 只能连接本任务 qsim 和专属模型通道。真实供应商凭据留在外部宿主；候选得到仅用于本次通道的短期 token。辅助会话和内部重试共用固定 Solver，不获得另一供应商或模型。

通道支持 Responses（含 compact）、Chat Completions、Anthropic HTTP/SSE 及受支持的压缩请求；当前不支持 WebSocket。process 通道不解释候选工具语义、不自动重试、不经过逐请求 token 账本；固定模型、认证、请求容量、存储和原截止仍由外部执行。控制数据库短暂不可用不成为每次 process 模型请求的同步依赖；未送达监督端的停止不能被称为已经完成。Meta 与旧 Runner 的访问路径另见[控制后台](control.md)。

## 时间、环境与退出

[task_time.py](../../src/execution/host/task_time.py)读取任务配置：环境准备、Agent setup、Solver、verifier 及独立 verifier 环境分别记录上限。新活动绑定 benchmark-time-v2，允许短窗口启动；Solver 时钟在准备后开始，实际截止为 benchmark 求解截止与该次活动执行截止中的较早者。原 benchmark 无有限求解上限时保留 null，实际运行受活动截止约束。阶段上限不改写，不接受单次时限覆盖。严格截止终止剩余求解和评分；明确选择 drain 才允许已启动任务有限延期。清理和证据归集不借此继续求解或补跑 verifier。

provenance 保留宿主启动/结束与 Solver 时钟，Harbor 原始阶段起止时间用于生成 timing：preparationSeconds（宿主启动至开始求解）、environmentSeconds、setupSeconds、solverSeconds、verifierSeconds、executionTimeSeconds（不含后续清理与归集）。缺少起止证据的阶段保持 null；传统 wallTimeSeconds 仍可能包含清理，不能当作求解耗时。控制端另存调度启动可用时间。官方成绩与真实中断原因独立保存；时间条件随实验、报告和比较展示，完整窗口与短窗口不静默视为一致。

任务镜像在准备阶段冻结；Trial 不重建或拉取替代标签，启动核验实际 main/qsim/verifier 镜像身份。任务配置或镜像丢失明确失败。新容器与卷承接每次尝试，镜像共享不等于随机样本固定。

外部监督持有进程、容器、网络和截止身份；停止/退出回收所属 main、qsim、模型代理及网络。候选子进程位于 main 私有 PID 空间，不能凭进程名清理其他活动。具体入口见[执行资产清单](../../src/execution/assets.json)及[single_run.py](../../src/execution/host/single_run.py)。

## 评分与默认恢复

结果分别记录 execution、officialResult、evidenceStatus、comparison。官方文件须核验归属和完整性；非零退出、超时或诊断附件损坏可与可信官方分数并存。缺少可信官方文件保留 null；任务完成分另按[统一规则](evidence-storage.md#官方评分与任务完成分)派生。重复归集不重跑模型或 verifier。

默认工程含响应保护与恢复组合，其传输等待、响应重新生成和工具参数反馈由工程源码/config 管理。Meta 可以修改、替换或移除这些策略；`runtimeConfig.recovery=null` 可禁用默认恢复。旧配方中的固定五档恢复不是新平台的不可变策略。副作用是否重放由候选策略负责，实验轨迹与最终诊断用于核查实际行为。

## 验证入口

[工程冻结单元测试](../../tests/unit/project_bundle_test.py)、[候选接入](../../tests/unit/process_candidates_test.py)、[时限测试](../../tests/unit/benchmark_time_test.py)、[process 契约](../../tests/contracts/process-harness.test.mjs)与[策略契约](../../tests/contracts/process-strategies.test.mjs)分别覆盖源码/产物、策略可替换、通道和隔离。测试条件与未验证范围见[验证说明](../development/testing.md)。

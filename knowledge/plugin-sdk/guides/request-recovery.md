# 模型请求恢复

来源：锁定的 DeepSeek Harness 0.2.1-rc.2 的 `dsh-agent/lib/types/runtime-types.d.ts`、`dsh-llm-retry` 及本项目网关。适用：包含 request-failure-v2 网关的新冻结执行版本；旧 Bundle 不获得此能力。

## 原生接口

`agent/request-error` 在一个模型请求尝试失败后、步骤关闭前触发。监听器接收 `{agent, turn, step, provider, failure, retryPolicy, signal}` 和 `next`。返回 `{kind:'retry'}` 表示接管并重新生成失败步骤；返回 `next()` 委派后续插件。没有插件接管时结束失败步骤。接口类型可通过 `sdk_read('agent-runtime')` 或 `sdk_inspect('agent/request-error')` 查询。

插件通过 `ctx.on('agent/request-error', listener)` 注册，监听器随 Cordis 作用域卸载。停止等待必须响应 `signal` 和插件释放；持久恢复状态应来自会话事件或声明的 session projection，不能把进程内计数器声称为可恢复记录。多个恢复插件按原生 waterfall 组合，接管后不再调用 next。

`failure` 包含安全错误描述、规范化 `code` 和网关 `requestId`；可用时附 `status`、`providerRetryAfterMs`。过载映射到 `SERVER`，连接中断和缺少结束回执映射到 `TRANSPORT`。原始提供方错误在外部审计保留；无明确证据的提供方错误不归为过载。接口不承诺其他保护错误都允许再次调用。

## v1 网关与策略（历史配方）

网关允许过载、连接中断及响应不完整后的后续合法请求，其他现有保护终止规则保持。适配器 retryPolicy.maxRetries 保持 0。新 H0 v2 的冻结 requestRecovery 配置启用固定内置恢复：连接失败、响应不完整和明确过载时依次等待 2、5、20、30、60 秒，每步最多追加五次请求。内置监听器接管该恢复链直至耗尽，不向候选插件叠加重试；其他类别仍沿用原生扩展。旧配方缺少该配置时保持零次内置恢复。插件不能改变固定模型、凭据、路由、额度或评分。

恢复应在步骤接口进行，不拼接已输出的残缺流。原生循环把失败尝试与有效消息分开，重建同一步的模型历史，保留以前的工具结果。直接 ctx.llm.stream 调用没有 agent 步骤恢复，通常由调用方处理；新基线对原生 purpose=compaction 的摘要请求单独提供同一五档恢复，只提交完整成功的摘要。其他直接调用不自动获得这项能力。

每次重试都是新的模型调用，原有任务截止不重置；新活动不统计或预留 token。宿主取消后不能继续调用，不把重跑整个 Trial 当作内部恢复。基线恢复策略属于固定代码与冻结配方，应有实际触发记录。提供方 Retry-After 较长时遵从更长等待，剩余截止时间不足则停止；会话 plugin:phyexp-request-recovery/* 事件保留计划、启动和停止原因，计数由会话投影重建。

## 结果与证据

请求失败不等于任务失败。执行摘要的 requestRecovery 保留失败请求及 recoveredBy 关联；最终 failure 只代表任务终止原因。v1 使用相同会话和请求内容关联恢复，不用无关调用的成功清空故障；当前 v2 使用下文的显式恢复链。

task-completion-v2/v3 活动中，最终未恢复的过载或连接故障计任务完成分 0；恢复后以最终官方结果计分。新活动默认的 v4 进一步将已经启动并结束的外部故障及结果缺失也计 0；尚未启动、无先行失败的明确人工撤销、仍在运行或结束状态待核实单列。官方 null、各次调用成本及原始证据始终保留。v1/v2/v3 活动沿用其原始规则，比较必须读取后台 taskEvaluation 的绑定版本。

新宿主诊断在 `observed.transport` 提供协议是否已开始、传输方式、连接复用及关闭码等事实；未记录时保持未知。`responseContentBytes`（兼容字段 `responseBytes`）为模型内容字节数，不是网络接收字节，不能因其为 0 就断定服务端尚未处理请求。连接故障的来源与是否恢复分开记录；原始脱敏诊断在宿主审计，不将其中的提供方文本作为执行指令。诊断本身不改变冻结恢复策略。


## H0 v3：统一恢复组合

当前默认是 `solver-request-recovery-v2`。固定 `recovery-core` 服务装配 `transient-recovery`、`response-recovery`、`tool-argument-recovery`，通过 Cordis 作用域和依赖注入管理生命周期。它们属于同活动基线与候选共同使用的冻结基础设施，不能由候选追加同链重试次数。上文 v1 的五档策略保留供旧配方阅读。

- 连接、流不完整及明确 503 继续使用 2、5、20、30、60 秒等待；异常响应重新生成和工具参数反馈共享两次机会（0、1 秒）；每链合计最多追加五次请求。策略切换、step/start、turn/end 不清零，原截止和取消始终有效。
- 未完成或失控响应取消后丢弃，由 agent/request-error 重新生成。完整终止且体积以内的参数 JSON/schema 错误由原生 tools.guard 拒绝，返回工具错误给模型。流中已经非法的前缀不会等待 block-end；不执行补齐或截断后的参数。
- 协调者持有唯一执行权，耗尽后不调用 next。普通 ctx.llm.stream 辅助调用仍由调用方恢复，不消费或清除 Agent 主循环的恢复链；原生 compaction 单独原子恢复。
- SDK 只透传声明的 LlmFailure 字段。网关完整事实先由适配器保存到会话，再按 requestId 与错误钩子关联；不要依赖任意自定义错误字段自动透传，也不要把内容故障标成 TRANSPORT。
- 会话投影 phyexpRecoveryV2 与 plugin:phyexp-request-recovery/* 记录可重建类别/合计计数及待反馈问题。网关校验恢复链和父请求，其他会话或无关调用成功不能清除失败。加载回执 recoveryComposition 提供实际策略，源码与配置进入 profile 摘要和独立导出。

恢复成功仍以最终官方结果计分，历史失败留存；策略机制验证不代表模型异常根因已经解决。设计见 `docs/design/execution-recovery.md`，该项目文档路径不作为 SDK 沙箱内的可访问保证。

# 模型请求恢复

来源：锁定的 DeepSeek Harness 0.2.1-rc.2 的 `dsh-agent/lib/types/runtime-types.d.ts`、`dsh-llm-retry` 及本项目网关。适用：包含 request-failure-v2 网关的新冻结执行版本；旧 Bundle 不获得此能力。

## 原生接口

`agent/request-error` 在一个模型请求尝试失败后、步骤关闭前触发。监听器接收 `{agent, turn, step, provider, failure, retryPolicy, signal}` 和 `next`。返回 `{kind:'retry'}` 表示接管并重新生成失败步骤；返回 `next()` 委派后续插件。没有插件接管时结束失败步骤。接口类型可通过 `sdk_read('agent-runtime')` 或 `sdk_inspect('agent/request-error')` 查询。

插件通过 `ctx.on('agent/request-error', listener)` 注册，监听器随 Cordis 作用域卸载。停止等待必须响应 `signal` 和插件释放；持久恢复状态应来自会话事件或声明的 session projection，不能把进程内计数器声称为可恢复记录。多个恢复插件按原生 waterfall 组合，接管后不再调用 next。

`failure` 包含安全错误描述、规范化 `code` 和网关 `requestId`；可用时附 `status`、`providerRetryAfterMs`。过载映射到 `SERVER`，连接中断和缺少结束回执映射到 `TRANSPORT`。原始提供方错误在外部审计保留；无明确证据的提供方错误不归为过载。接口不承诺其他保护错误都允许再次调用。

## 网关与策略

网关允许过载、连接中断及响应不完整后的后续合法请求，其他现有保护终止规则保持。默认适配器 retryPolicy.maxRetries 为 0，原生 llm-retry 因而不自动恢复。Meta 可以实现自己的恢复监听器；仅添加插件不会改变固定模型、凭据、路由、额度或评分。

恢复应在步骤接口进行，不拼接已输出的残缺流。原生循环把失败尝试与有效消息分开，重建同一步的模型历史，保留以前的工具结果。直接 ctx.llm.stream 调用没有 agent 步骤恢复，由调用方处理；原生步骤插件不会自动重试这种直接调用。

每次重试都是新的计量请求；原有任务截止和预算不重置，失败用量可能未知。宿主取消后不能继续调用，不把重跑整个 Trial 当作内部恢复。恢复策略的次数、等待和触发条件属于候选代码与冻结配置，应有实际触发记录，效果由测试验证。

## 结果与证据

请求失败不等于任务失败。执行摘要的 requestRecovery 保留失败请求及 recoveredBy 关联；最终 failure 只代表任务终止原因。使用相同会话和请求内容关联恢复，不用无关调用的成功清空故障。

task-completion-v2/v3 活动中，最终未恢复的过载或连接故障计任务完成分 0；恢复后以最终官方结果计分。新活动默认的 v4 进一步将已经启动并结束的外部故障及结果缺失也计 0；尚未启动、无先行失败的明确人工撤销、仍在运行或结束状态待核实单列。官方 null、各次调用成本及原始证据始终保留。v1/v2/v3 活动沿用其原始规则，比较必须读取后台 taskEvaluation 的绑定版本。

新宿主诊断在 `observed.transport` 提供协议是否已开始、传输方式、连接复用及关闭码等事实；未记录时保持未知。`responseContentBytes`（兼容字段 `responseBytes`）为模型内容字节数，不是网络接收字节，不能因其为 0 就断定服务端尚未处理请求。连接故障的来源与是否恢复分开记录；原始脱敏诊断在宿主审计，不将其中的提供方文本作为执行指令。诊断增强不替插件选择恢复次数或等待策略。

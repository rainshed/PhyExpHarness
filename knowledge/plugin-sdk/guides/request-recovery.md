# 候选中的模型请求恢复

适用：harbor-process-v1 默认 DSH 工程，锁定 SDK 为 0.2.1-rc.2。恢复、输出保护与工具反馈都是候选策略，可由 Meta 修改、替换或移除；平台固定模型、隔离、容量、取消和 benchmark 截止仍不可绕过。完整工程见[开发入口](process-harness.md)。

## 原生接口

agent/request-error 在请求失败后、步骤关闭前触发。监听器接收 agent、turn、step、provider、failure、retryPolicy、signal 和 next；返回 kind=retry 接管失败步骤，调用 next 委派其他插件。准确类型通过 sdk_read 的 agent-runtime 或 sdk_inspect 查询。

ctx.on 注册随 Cordis 作用域卸载。等待响应 signal，恢复状态应有会话投影等持久来源，不将内存计数器称为可恢复记录。SDK 仅透传声明的错误字段，自定义诊断需通过明确事件关联；不能假定任意错误字段到达监听器。

## 默认模板的策略

当前推荐预设将 request-recovery 作为普通插件，harness.json 的 runtimeConfig.plugins 对应项中 config.policy 使用 solver-request-recovery-v2：transient-recovery、response-recovery、tool-argument-recovery 通过 recovery-core 协调。传输等待为 2、5、20、30、60 秒，内容恢复共享 0、1 秒两次机会，每条链最多追加五次请求。这是默认工程配置，不是平台强制算法。

未完成响应丢弃后重新生成，不能拼接残缺参数执行。完整参数的 JSON/schema 错误由工具 guard 返回错误，先前已完成工具副作用不应重放。原生 compaction 只提交完整摘要，普通 ctx.llm.stream 辅助调用由调用方处理恢复。

移除 plugins 与 runtimeConfig.plugins 中对应项可禁用这套恢复；框架原生参数校验与工具错误反馈继续保留；也可改源码、服务、事件或实现自己的策略。候选内的多会话、不同工具清单和辅助请求都使用同一固定 Solver 通道，过程留在执行轨迹。外部 process 通道不执行候选的语义保护或自动重试。

## 结果与诊断

请求失败、候选最终退出和官方评分分别判断。恢复成功保留失败历史，最终未恢复原因不能被无关请求的成功清除。取消/截止不因新请求或新会话重置，重跑整个 Trial 是新的实验，不能伪装成免费恢复。

无可信官方评分保持 null；新活动 task-completion-v4 将已启动并最终结束的多数无评分尝试计派生失败，人工撤销及未执行例外由后台统一计算。候选自报诊断不能改写官方结果。

平台不累计 token/费用，原始回执可能包含 usage，但无 usage 不阻止调用或归档。异常恢复契约验证不证明科学效果或远端服务可靠性。

## 旧固定 Runner

旧 v1/v2 候选中的 requestRecovery/网关策略可能属于不可修改基础设施，包括五档传输恢复、宿主错误分类和计量。其准确边界以旧活动冻结资料与源码为准，不将旧限制用于新工程，也不修改旧冻结包以获得当前策略。

# 子代理与任务委派

来源：官方[Subagent 文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/subagent.md)，以及 `0.2.1-rc.2` 的 `dsh-subagent`、`dsh-subagent-spawn-in-process` 包说明和类型。适用：默认 DSH 候选模板未预装标准 subagent 组合；新完整工程可以自行装配并验证。Meta 自身已使用原生普通研究委派，与候选 Solver 的配置是不同职责。

## 三种不同机制

| 机制 | 含义 |
|---|---|
| 一次 `ctx.llm.stream` 调用 | 处理显式给定的模型输入，本身不提供子代理会话与工具循环 |
| spawn 子代理 | 新建独立会话，不复制父会话的对话；任务输入需要自包含 |
| fork 子代理 | 基于父会话可继承的已完成历史开始工作，增加上下文复制成本 |

子代理用于需要独立上下文或分工的子任务，会增加调用、等待和协调成本。它与 Meta 自身的开发会话不是同一个角色。

## 上游最小组合

官方模型可调用的 spawn 工具由以下三部分组成。此配置仅说明依赖关系，不是本项目的安装指令：

```yaml
- name: '@deepseek-ai/dsh-subagent'
- name: '@deepseek-ai/dsh-subagent-spawn-in-process'
- name: '@deepseek-ai/dsh-tool-subagent'
  config:
    provider: spawn
```

Service 管理子代理及其生命周期，provider 实现创建方式，工具将委派入口提供给模型。仅有 `agents` 和 `agent-loop`，并不等于已提供 `ctx.subagents`。

程序消费者可调用 `ctx.subagents.startActivation`，主要参数为：

| 参数 | 含义 |
|---|---|
| `provider`、`label` | 已注册的 provider 名称和本次子任务标签 |
| `request.parent` | 发起委派的实际 Agent，例如工具执行上下文中的 `exec.agent` |
| `request.prompt` | 子任务内容块，例如 `[{type:'text',text:'整理以下材料……'}]` |
| `request.maxDepth` | provider 支持时使用的委派深度上限 |
| `signal` | 发布前创建过程的取消信号 |
| `delivery` | `parent` 向父模型通知；`caller` 由调用者收集结果 |

返回对象提供 `childId`、`result` Promise 和 `dispose()`。结果包含输出及 `stopReason`，不能把取消、错误或部分输出当成功。发布后的取消通过 `dispose()` 管理；只传入创建信号不等于处理了全部运行期取消。调用者需要拥有并清理子任务资源。

## 本项目接入前提

需先在冻结执行环境中装配并验证所需服务，确认子代理遵循固定 Solver 设置、模型通道、当前任务材料边界、取消与截止规则，并保留可读轨迹。包已安装或上游支持不代表这些条件已经满足。当前不会因为读取本教程而启用委派，候选依赖须通过完整工程的隔离构建安装，不在可信宿主加载。

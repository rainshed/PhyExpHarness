# 执行插件开发参考

来源：DeepSeek Harness 官方教程与已安装包的说明、类型声明，以及本项目的执行插件约定。适用版本：`0.2.1-rc.2`，目标 profile：本项目隔离执行的 `sdk-minimal`。这是开发参考，不规定改进策略。

| 资料 | 内容 | `sdk_read` 的 `id` |
|---|---|---|
| [插件设计](plugin-design.md) | 一切皆插件、服务与事件、上下文、配置和生命周期 | `guides/plugin-design.md` |
| [工具插件](tools.md) | 完整工具示例、结构化返回、结果观察与转换 | `guides/tools.md` |
| [模型请求恢复](request-recovery.md) | 原生失败步骤接口、错误事实、预算和恢复边界 | `guides/request-recovery.md` |
| [Meta 资源规划](resource-planning.md) | 计划接口、批次条件、准入等待和限制来源 | `guides/resource-planning.md` |
| [子代理](subagents.md) | 委派机制、最小组合及当前接入限制 | `guides/subagents.md` |

读取本索引的参数为 `{"id":"guides/README.md"}`。这些路径是资料 ID，不是插件工作区路径；相对链接对应同一 `guides/` 下的 ID。

现有参考也可用 `sdk_read` 读取：`overview`（项目开发约定）、`plugin-manifest`（清单 schema）、`example-echo`（工具与结果处理样例）、`tools` / `tool-schema`（工具类型）、`system-prompt`（上下文类型）、`llm` / `llm-types`（模型调用类型）。具体声明可通过 `sdk_search` 或 `sdk_inspect` 查询。

示例说明工程机制，效果由实际证据判断。固定 Solver、网关和任务环境边界以活动配置为准。子代理文档介绍上游能力，当前执行 profile 尚未启用标准委派组合。

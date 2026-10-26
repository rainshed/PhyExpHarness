# Meta 执行插件开发资料设计

> 历史快照：来自 `docs/design/meta-plugin-knowledge.md`，于文档重组时归档。正文保留当时的方案、状态和验收叙述，可能已被后续实现替代；不是当前操作指南，也不构成新的实施授权。现行入口：[当前说明](../../architecture/meta.md)；兼容行为见[兼容规则](../../architecture/compatibility.md)。归档不表示其中所有计划均已完成。

日期：2026-10-19 · 状态：已接入；子代理仅提供参考

将 DeepSeek Harness 的插件设计哲学和必要教程整理为少量 Markdown 文件，放在固定目录。系统提示词只提供资料入口，Meta 在需要时自行查阅。沿用现有开发资料读取能力，不另建能力分类系统或开发流程。

## 1 资料目录

资料位于 [knowledge/plugin-sdk/guides/](../../../knowledge/plugin-sdk/guides/README.md)，包括四个文件：

| 文件 | 内容 |
|---|---|
| `README.md` | 简短索引，说明各文件主题、适用的 DeepSeek Harness 版本，以及本项目插件清单和开发工具的现有入口 |
| `plugin-design.md` | “一切皆插件”的含义；工具、事件、上下文和服务如何组合；`apply`、`inject`、配置、状态作用域和资源清理的基本规则 |
| `tools.md` | 一个完整的工具插件例子；参数、结构化返回和模型可见内容；简要说明结果观察与结果转换的区别 |
| `subagents.md` | 子代理的用途、所需服务与最小用法；说明独立上下文、结果返回、取消和资源消耗，以及本项目尚未接入的部分 |

每篇以简短说明和必要代码为主，附官方来源与适用版本。索引使用相对路径链接，代码示例直接放在 Markdown 中。现有类型声明、清单和 echo 样例继续保留，正文引用它们即可。

## 2 应保留的设计原则

- **插件可以贡献实际行为。** 提示词、工具、结果处理、上下文和服务都是扩展方式，由 Meta 根据问题选择。
- **通过服务和事件组合。** 用明确接口协作，声明依赖；简单工具无需预先拆成多个包。
- **选择足够解决问题的局部接口。** 观察结果和修改结果分别使用对应机制，避免无必要地改写整体装配。
- **状态与资源有明确归属。** 区分临时状态和需要恢复的信息，处理取消与卸载清理。

这些原则用于帮助理解框架，不规定改进顺序，也不要求 Meta 一定使用工具或子代理。是否有效仍依据实际执行结果判断。

## 3 官方资料来源

| 资料 | 用途 |
|---|---|
| [官方架构](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md)、[插件实践](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/preset/agent-preset/skills/cordis-plugin-development/references/practices.md) | 提炼插件设计哲学 |
| [Cordis 教程](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/cordis-tutorial/index.md) | 查阅生命周期、服务、事件和配置 |
| [构建工具](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/tool.md)、[工具参考](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/cookbook/adding-a-tool.md) | 整理工具示例和接口说明 |
| [扩展模式](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/cookbook/extension-cookbook.md) | 解释不同需求对应哪些插件机制 |
| [Subagent 文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/subagent.md) | 整理委派概念与用法 |

优先依据项目锁定的安装版本整理；上游网页用于参考，不直接假定最新接口可用。官方教程中的 Web UI、Plugin Manager 安装和发布流程不搬入正文，替换为本项目已有的 `plugin.json`、开发检查和候选冻结约定。

“一切皆插件”是框架的设计理念，不改变本项目固定 Solver、网关和评分等边界。Subagent 文档可以先提供概念说明；当前执行 profile 未加载标准委派组合，应如实注明，不能将上游示例标为本项目已验证可运行。

## 4 系统提示词中的入口

系统提示词中的按需入口为：

> 插件开发参考来自 DeepSeek Harness 官方资料及本项目适配说明；需要时通过 sdk_read 读取 guides/README.md，并按索引查阅。旧资料包若未收录该入口，可读取 overview。

资料构建器以 `guides/<文件名>.md` 作为读取 ID，保留 Markdown 正文并记录来源与摘要。索引与提示词使用相同标识，沿用现有资料包的版本和活动归档机制。

Meta 在隔离环境中通过已有 `sdk_read` 读取资料，无需访问宿主仓库路径。更新资料后重新构建并重启控制后台，新活动使用新资料包，已有活动的归档不回写。

检查覆盖资料读取、搜索、索引链接、旧资料包，以及 Markdown 工具示例的真实 Cordis 调用、错误处理和卸载。教程介绍用法，具体设计和实验方法交由 Meta 决定。

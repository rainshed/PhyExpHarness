# 插件设计

来源：官方[架构](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md)、[Cordis 教程](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/cordis-tutorial/index.md)、[插件实践](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/preset/agent-preset/skills/cordis-plugin-development/references/practices.md)。适用：`0.2.1-rc.2`；以下结合锁定安装的类型与本项目约定整理，网页新版接口不自动适用。

## 一切皆插件

DeepSeek Harness 通过插件组合工具、模型服务、上下文和 agent 循环等能力。插件在 `apply(ctx, config)` 中注册行为；`ctx` 提供服务和事件接口。提示词是其中一种贡献，也可以新增工具、处理结果或提供共享服务。

本项目的改进对象是完整执行工程及插件组合，框架、依赖、工具和恢复均可由候选修改；固定 Solver、外部模型通道、隔离及评分边界保持活动约定。

## 为人提供用途和机制说明

完整工程在 `harness.json.plugins` 声明插件的 `name/version/path/config`，说明放在对应目录的 `plugin.json`；具体路径与兼容规则见 [完整工程开发](process-harness.md#插件用途机制与源码定位)。工作台从冻结源码读取说明，不会根据插件名字推测分类或机制。

清单的 `functionSummary` 回答“做什么”，`mechanism` 回答“怎么做”：用几句中文讲明输入或触发条件、实际动作、输出和关键限制。比如“将固定建议加入系统提示，提醒 Solver 用脚本生成和检查数组；是否遵循由 Solver 决定，本插件不自动处理数组”。不要仅写 `systemPrompt.section` 等接口名，不把建议描述成程序强制保证。

`categories` 是可多选的阅读分类：`prompt-context`、`tools`、`tool-results`、`execution-control`、`other`，中文依次为提示与上下文、工具能力、工具结果处理、执行控制与恢复、其他扩展。兼具工具和提示的插件可同时选前两类。不另作行为分类，不凭阅读分类推导权限。实验效果仍由研究观察及证据说明。

## 选择扩展接口

| 意图 | 接口 |
|---|---|
| 提供模型可调用的操作 | `ctx.tools.register()` |
| 观察最终工具结果 | `tools/result`，结果不可变 |
| 转换工具结果或附加上下文 | `tools/post-execute`，返回契约规定的 decision |
| 增加指令文本 | `ctx.systemPrompt.section()` |
| 提供随状态变化的事实 | `ctx.systemPrompt.context()`，具体签名见 `system-prompt` 资料 |
| 复用一种能力 | 提供服务，由消费者通过 `inject` 声明依赖 |

局部贡献更容易与其他插件共存。无需为了增加一段信息而重写整个提示词装配。Waterfall 是中间件调用：监听器不接管决定时，应返回 `next()`，否则会阻断后续处理。工具接口与原生类型见 [工具插件](tools.md)。

## 依赖与配置

`export const inject = ['tools']` 声明需要工具服务。服务未就绪时插件可能处于等待状态；依赖被移除会影响消费者生命周期。服务就绪不能仅靠文件排列顺序保证。

源码的 `inject` 是服务依赖。旧 v1/v2 插件清单的 dependencies 表示组合依赖，configSchema 校验冻结配置；这些不是新完整工程的策略准入要求。新工程自行组织装配和配置校验，原生导出的 Config 与工程自定义 schema 不自动同步。

可调参数应有明确默认值和校验。简单工具可放在一个插件中；只有需要独立替换或复用时，才拆分服务定义、实现和工具消费者。

## 状态与生命周期

说明状态属于一次调用、一个 agent 还是整个插件实例。闭包中的计数器是临时状态，不能宣称可恢复；需要恢复的信息应有持久来源。模型可见信息应可追溯，不随意追加框架不认识的日志事件类型。

Cordis 管理的工具、监听器等注册会随所属插件卸载。自行创建的资源由 `ctx.effect()` 返回清理函数；异步工作应响应取消并等待清理完成。若在 `agent.ctx` 上注册行为，也要考虑插件先于 agent 卸载时的清理责任。作用域负责生命周期，外部 Runner 负责隔离。

配置、源码和资产通过完整工程冻结。候选依赖在隔离构建安装；开发入口读取 overview 与 guides/process-harness.md。plugin-manifest 资料 ID 保留旧固定 Runner 的清单参考，不限制新工程。

## 让用户在后续活动中组合插件

当前 Meta 不访问用户历史插件库，也不替用户选择 H0。可在当前工程内修改所选插件、编写新插件；后台在检查/冻结源码时自动保存声明的插件目录，构建失败也保存源码。选择插件不带入其他活动的报告或成绩。

希望供用户在当前 DSH 0.2.1-rc.2 基础模板中一键装配时，在插件目录的 plugin.json 中显式增加以下 assembly 声明：

```json
{
  "assembly": {
    "contract": "dsh-plugin-v1",
    "entry": "index.mjs",
    "requires": [],
    "conflicts": [],
    "configSchema": {"type": "object", "properties": {"note": {"type": "string"}}, "additionalProperties": false},
    "defaultConfig": {"note": "说明"}
  }
}
```

entry 相对插件目录且必须在源码内。requires 是用户须一起确认的准确插件摘要列表；conflicts 可列插件名称或摘要。配置必须是 JSON 对象；configSchema 只能内联或引用本声明中的定义，不读取外部 schema 地址。runtimeContext 由启动器传入，包含 deadline/workspace/outputDirectory，不属于用户持久配置，不应拿它延长预算。框架服务仍由原生 inject/加载器解析，声明依赖不等于服务实际可用；组合构建会检查所选插件是否激活。

需要第三方 npm 包时在插件目录提供 package.json 和准确 package-lock.json；安装仅发生在隔离构建内，不允许锁引用目录外本地文件。必要源码和资产都应放入已声明插件目录；不要依赖旧活动工作区或宿主文件。缺少装配声明的完整工程插件仍可保存和阅读，显示需要适配，不限制 Meta 自选框架和工程结构。插件通过构建或所在组合取得成绩不等于插件因果有效。

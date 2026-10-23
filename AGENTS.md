# 开发导航

按当前用户授权范围工作；项目设计哲学与具体开发约束见下列对应文档。

## 目录安排

| 目录 | 内容 |
|---|---|
| `src/execution/` | 插件版本与组合解析、隔离 Runner、模型网关及 Harbor adapter |
| `src/control/` | 独立后台、活动、预算、调度与 Meta 会话 |
| `src/evidence/`、`src/reporting/`、`src/exporting/` | 证据查询、报告生成与冻结项目导出 |
| `src/runtime/`、`src/integrations/` | 历史命令与导入的兼容入口 |
| `packages/meta-harness/` | Meta 工具插件 |
| `packages/meta-workbench-client/` | 公共客户端、查询与命令、草稿和请求身份 |
| `packages/meta-workbench-studio/` | Studio UI、页面模块与独立样式 |
| `packages/meta-workbench-bridge/` | 独立工作台宿主 API 桥 |
| `schemas/`、`knowledge/plugin-sdk/` | 数据契约、默认值、SDK 资料源文件与技术样例 |
| `profiles/`、`recipes/`、`experiments/` | 宿主配置、执行配方与可复用实验计划 |
| `templates/standalone/` | 独立交付模板及专用依赖锁 |
| `scripts/`、`tests/`、`docs/` | 构建维护脚本、测试与正式文档 |

## 去哪里找

| 要了解的内容 | 入口 |
|---|---|
| 固定 Solver、插件组合优化与可理解的进化 | [项目设计哲学](docs/design/design-philosophy.md) |
| 项目目标与产品要求 | [README](README.md)、[需求文档](docs/requirements/meta-harness.md) |
| 架构、依赖边界与迁移约定 | [实现方案](docs/design/meta-harness-implementation.md) |
| 长活动存储共享、快照、压缩与容量保护 | [存储管理设计](docs/design/storage-management.md) |
| 插件版本保存、组合清单与按需导出 | [专项方案](docs/design/plugin-versioning-and-export.md) |
| Meta 插件组合、停止审查与可比较性基础 | [专题设计](docs/design/meta-harness-composition.md) |
| 可独立移除的参考模型与参考 Harness 插件 | [完整设计](docs/design/meta-reference-experiments.md)、[开发计划](docs/plans/meta-reference-experiments.md) |
| Meta 通用 Agent 能力、完整证据路径与会话恢复 | [完整设计方案](docs/design/meta-agent-and-evidence.md) |
| 进化方向可读性、开发动机、选择解释与证据来源 | [进化可读性设计](docs/design/evolution-readability.md) |
| Studio 页面与阅读体验 | [新工作台设计](docs/design/meta-workbench-studio.md) |
| UI 公共能力、版本独立与增删边界 | [UI 模块化设计](docs/design/meta-workbench-modularity.md) |
| 开发推进、验证与验收规则 | [开发任务书](docs/plans/meta-harness-development.md) |
| 安装、构建、运行、恢复与已知限制 | [运行说明](docs/operations/meta-harness.md) |
| 模型流保护、失败诊断与离线回放 | [运行说明](docs/operations/meta-harness.md#模型请求保护与故障诊断) |
| 模型请求恢复与故障零分增量 | [专项计划](docs/plans/model-request-recovery.md) |
| 已结束未评分尝试计失败与历史计分兼容 | [任务完成规则 v4](docs/design/task-completion-v4.md) |
| Meta 自主资源规划与限额执行修改 | [专项计划](docs/plans/meta-resource-planning.md) |
| 执行插件开发接口与样例 | [SDK 资料](knowledge/plugin-sdk/README.md) |
| Meta 系统职责与默认目标 | [系统模板](src/control/prompts/meta-system.md)、[默认值](schemas/meta-defaults.json) |
| 实际命令与提交范围 | [package.json](package.json)、[.gitignore](.gitignore)；约定见开发任务书第 12 节 |

本地开发进度与检查记录位于 `reports/development/meta-harness/`；历史运行与状态位于 `runs/`、`reports/`、`.runtime/`，新活动数据位置见运行说明。这些内容不提交，新克隆没有它们是正常的；按代码、正式文档及可执行检查核实现状。

## Git 提交规范

- 每完成一个独立功能或修复并通过相关验证后，立即本地提交一次，无需再次确认。独立文档、配置修改同样适用。
- 提交标题采用 `<type>(<scope>): <中文说明>`。
- 入库范围见 [.gitignore](.gitignore) 和[开发任务书第 12 节](docs/plans/meta-harness-development.md#12-版本管理与文档维护)。

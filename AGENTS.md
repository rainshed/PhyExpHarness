# 开发导航

按当前用户授权范围工作；具体开发约束见下列对应文档。

## 目录安排

| 目录 | 内容 |
|---|---|
| `src/execution/` | 冻结 Bundle、隔离 Runner、模型网关及 Harbor adapter |
| `src/control/` | 独立后台、活动、预算、调度与 Meta 会话 |
| `src/evidence/`、`src/reporting/`、`src/exporting/` | 证据查询、报告生成与冻结项目导出 |
| `src/runtime/`、`src/integrations/` | 历史命令与导入的兼容入口 |
| `packages/meta-harness/` | Meta 工具插件 |
| `packages/meta-workbench/{host,client}/` | 工作台宿主桥与界面源码 |
| `schemas/`、`knowledge/plugin-sdk/` | 数据契约、默认值、SDK 资料源文件与技术样例 |
| `profiles/`、`recipes/`、`experiments/` | 宿主配置、执行配方与可复用实验计划 |
| `templates/standalone/` | 独立交付模板及专用依赖锁 |
| `scripts/`、`tests/`、`docs/` | 构建维护脚本、测试与正式文档 |

## 去哪里找

| 要了解的内容 | 入口 |
|---|---|
| 项目目标与产品要求 | [README](README.md)、[需求文档](docs/requirements/meta-harness.md) |
| 架构、依赖边界与迁移约定 | [实现方案](docs/design/meta-harness-implementation.md) |
| 开发推进、验证与验收规则 | [开发任务书](docs/plans/meta-harness-development.md) |
| 安装、构建、运行、恢复与已知限制 | [运行说明](docs/operations/meta-harness.md) |
| 执行插件开发接口与样例 | [SDK 资料](knowledge/plugin-sdk/README.md) |
| Meta 系统职责与默认目标 | [系统模板](src/control/prompts/meta-system.md)、[默认值](schemas/meta-defaults.json) |
| 实际命令与提交范围 | [package.json](package.json)、[.gitignore](.gitignore)；约定见开发任务书第 12 节 |

本地开发进度与检查记录位于 `reports/development/meta-harness/`；历史运行与状态位于 `runs/`、`reports/`、`.runtime/`，新活动数据位置见运行说明。这些内容不提交，新克隆没有它们是正常的；按代码、正式文档及可执行检查核实现状。

# 开发导航

按当前用户授权范围工作；项目设计哲学与具体开发约束见下列对应文档。历史计划不构成额外实施授权。

## 项目与部署边界

- 主分支只维护项目功能、标准 Docker/Harbor 执行环境、本地证据存储及通用配置契约。
- 机器专属容器兼容层、远程存储迁移与恢复、服务托管、网络接入、实例发布和现场记录由独立部署分支维护，不进入主线源码、默认 UI、测试依赖或导出包。
- 通用改进先进入主线，部署分支再同步；部署专属改动不整体合回主线。部署数据转换与既有实例切换由部署侧独立执行。
- 提交前运行 `npm run check:project`；文档变更运行 `npm run check:docs`。详细职责和文档归属见[开发流程](docs/development/workflow.md)。

## 目录安排

| 目录 | 内容 |
|---|---|
| `src/execution/` | 插件版本与组合解析、隔离 Runner、模型网关及 Harbor adapter |
| `src/control/` | 独立后台、活动、运行限额、调度与 Meta 会话 |
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

## 文档入口

- 开发变更须按[文档维护规则](docs/development/documentation.md)核对并同步相关文档，将文档与实现一致作为任务完成条件。
- [完整文档导航](docs/README.md)：按了解、使用、开发三条路线阅读。
- [设计哲学](docs/product/philosophy.md)、[产品要求](docs/product/requirements.md)：目标与不可削弱的边界。
- [架构总览](docs/architecture/overview.md)：模块、依赖与当前默认契约。
- [开发流程](docs/development/workflow.md)、[验证说明](docs/development/testing.md)：推进、提交与验收。
- [快速开始](docs/guides/quickstart.md)、[维护指南](docs/guides/maintenance.md)：构建、运行、恢复和排障。
- [实现核对表](docs/development/implementation-audit.md)：功能与代码/测试的对应；[兼容规则](docs/architecture/compatibility.md)说明旧活动。
- [SDK 资料源](knowledge/plugin-sdk/README.md)、[系统模板](src/control/prompts/meta-system-process.md)、[目标默认值](schemas/meta-defaults.json)。

本地开发进度与检查记录位于 `reports/development/meta-harness/`；历史运行与状态位于 `runs/`、`reports/`、`.runtime/`，新活动数据位置见快速开始。这些内容不提交，新克隆没有它们是正常的；按代码、正式文档及可执行检查核实现状。

## Git 提交规范

- 每完成一个独立功能或修复并通过相关验证后，立即本地提交一次，无需再次确认。独立文档、配置修改同样适用。
- 提交标题采用 `<type>(<scope>): <中文说明>`。
- 入库范围见 [.gitignore](.gitignore) 和[开发流程](docs/development/workflow.md)。

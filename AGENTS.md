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
| `packages/meta-workbench/`、`packages/meta-workbench-studio/` | 经典与新工作台 UI、共享客户端业务 |
| `packages/meta-workbench-bridge/` | 独立工作台宿主 API 桥 |
| `schemas/`、`knowledge/plugin-sdk/` | 数据契约、默认值、SDK 资料源文件与技术样例 |
| `profiles/`、`recipes/`、`experiments/` | 宿主配置、执行配方与可复用实验计划 |
| `templates/standalone/` | 独立交付模板及专用依赖锁 |
| `scripts/`、`tests/`、`docs/` | 构建维护脚本、测试与正式文档 |

## 去哪里找

| 要了解的内容 | 入口 |
|---|---|
| 项目目标与产品要求 | [README](README.md)、[需求文档](docs/requirements/meta-harness.md) |
| 架构、依赖边界与迁移约定 | [实现方案](docs/design/meta-harness-implementation.md) |
| Meta 插件组合、停止审查与可比较性基础 | [专题设计](docs/design/meta-harness-composition.md) |
| 新 UI、插件并存与切换 | [新工作台设计](docs/design/meta-workbench-studio.md) |
| 开发推进、验证与验收规则 | [开发任务书](docs/plans/meta-harness-development.md) |
| 安装、构建、运行、恢复与已知限制 | [运行说明](docs/operations/meta-harness.md) |
| 模型流保护、失败诊断与离线回放 | [运行说明](docs/operations/meta-harness.md#模型请求保护与故障诊断) |
| 模型请求恢复与故障零分增量 | [专项计划](docs/plans/model-request-recovery.md) |
| Meta 自主资源规划与限额执行修改 | [专项计划](docs/plans/meta-resource-planning.md) |
| 执行插件开发接口与样例 | [SDK 资料](knowledge/plugin-sdk/README.md) |
| Meta 系统职责与默认目标 | [系统模板](src/control/prompts/meta-system.md)、[默认值](schemas/meta-defaults.json) |
| 实际命令与提交范围 | [package.json](package.json)、[.gitignore](.gitignore)；约定见开发任务书第 12 节 |

本地开发进度与检查记录位于 `reports/development/meta-harness/`；历史运行与状态位于 `runs/`、`reports/`、`.runtime/`，新活动数据位置见运行说明。这些内容不提交，新克隆没有它们是正常的；按代码、正式文档及可执行检查核实现状。

## Git 提交规范

- **完成一个功能就提交一次。** 每完成一个独立功能修改或缺陷修复，并通过相关验证后，立即创建一次本地 Git 提交，再继续下一项工作；无需逐次询问用户，不把多个已完成的功能积攒到任务结束。独立的文档、配置和构建修改也按此执行。用户明确要求暂不提交时，以该要求为准。
- **一个提交对应一个完整变更。** 将同一功能必需的源码、契约、测试、依赖锁和文档一起提交，可以跨后台、插件与 UI；无关功能、重构和格式化分开。提交应保持可运行，不依赖后续提交或未提交文件补齐必需内容。
- **保护已有改动。** 开始工作与提交前检查 `git status` 和差异，按文件或补丁暂存本次范围内的改动，不擅自收录、覆盖或回退其他任务的工作。存在混合改动时，不使用 `git add .`、`git add -A` 或 `git commit -a` 整批提交。
- **验证后再提交。** 按开发任务书及专项计划执行受影响的检查；仅文档修改检查链接、术语与规则一致性，无需运行模型、构建或运行时测试。相关检查失败或必需验证受阻时，先修复或如实记录阻塞，不将功能标记为完成。有效且未受影响的检查结果可以复用，真实模型调用遵循已有授权和预算。
- **审阅实际提交内容。** 提交前检查 `git diff --cached` 并执行 `git diff --cached --check`，确认新文件、依赖及执行资产无遗漏。混合工作区的测试结果不能直接证明拆分后的提交通过，必要时隔离验证拟提交内容。入库范围以 `.gitignore` 和开发任务书第 12 节为准，不提交运行数据、凭据、本地记录及生成产物。
- **统一提交说明。** 标题使用 `<type>(<scope>): <中文行为描述>`；type 使用 `feat`、`fix`、`refactor`、`test`、`docs`、`build` 或 `chore`，scope 按主要职责选择，如 `execution`、`control`、`meta`、`workbench`、`studio`、`reporting`。非简单变更在正文说明原因、主要行为、验证结果及必要的版本兼容或迁移要求，未执行、跳过和失败的检查如实记录。
- **提交后继续工作并报告结果。** 本地提交不构成人工验收点；在已授权范围内继续推进，交付时报告提交标识、变更摘要和验证结果。本规则授权本地提交，不自动授权推送、发布或改写历史，这些操作遵循用户另行给出的授权。

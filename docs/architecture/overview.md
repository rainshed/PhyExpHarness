# 架构总览

状态：当前主线架构。用户操作见[指南](../README.md#使用指南)，旧活动见[兼容规则](compatibility.md)。

## 数据与调用方向

```text
Studio → 公共客户端 → 宿主 API 桥 → 独立控制后台
                                     ├─ Meta 隔离运行时 → 受控业务 API
                                     ├─ 候选隔离构建 → 不可变工程与产物
                                     └─ Trial 监督 → Harbor main / qsim / verifier
                                                       ↕ 固定 Solver 通道
结果归集 → 证据与研究记录 → 报告、版本比较、独立导出
```

后台是状态、权限、计分和调度的权威，UI 不拥有任务生命周期。候选工程拥有执行策略，平台适配只负责运行契约、固定模型、隔离与官方评测。执行层不导入控制、证据、报告、导出或 UI 层；导出可使用执行层，不形成反向依赖。

## 模块职责

| 目录 | 维护内容 | 详细说明 |
|---|---|---|
| `src/execution/` | 工程/插件冻结、Runner、模型宿主、Harbor 与参考适配 | [执行工程](execution.md)、[版本与导出](versions-and-export.md) |
| `src/control/` | 活动、数据库、限额、Meta、供应商、归集工作和删除协调 | [控制后台](control.md)、[Meta](meta.md) |
| `src/evidence/` | 原件、材料、摘要核验、统一计分与查询快照 | [证据与存储](evidence-storage.md) |
| `src/reporting/`、`src/exporting/` | 报告事实/阅读与冻结项目交付 | [证据与存储](evidence-storage.md)、[版本与导出](versions-and-export.md) |
| `packages/meta-harness/` | 原生领域工具及历史工具资产 | [Meta](meta.md) |
| 两个 `packages/meta-*-reference/` | 可选参考能力 | [参考实验](references.md) |
| 三个 `packages/meta-workbench-*/` | 公共客户端、宿主桥、Studio | [工作台](workbench.md) |
| `src/runtime/`、`src/integrations/` | 历史命令/导入兼容入口 | [兼容规则](compatibility.md) |
| `schemas/`、`templates/`、`knowledge/plugin-sdk/` | 契约、交付/基线模板、SDK 资料源 | [开发流程](../development/workflow.md) |

## 新活动默认契约

这些标识不是一个共同递增的版本号。

| 维度 | 默认值 | 实现来源 |
|---|---|---|
| 执行契约 / 组合格式 | `harbor-process-v1` / `harness-composition-v3` | [service.py](../../src/control/service.py)、[project.py](../../src/execution/bundle/project.py) |
| Meta 组合 | `meta-composition-v2` | [composition-native.json](../../packages/meta-harness/composition-native.json) |
| Meta 工具 / 系统模板 | `meta-tools-v9` / `meta-system-v11` | [meta_contracts.py](../../src/control/meta_contracts.py)、[meta_context.py](../../src/control/meta_context.py) |
| 模型访问 | `control-only-v1` | [model_access.py](../../src/control/model_access.py) |
| 任务时限 / 资源计划 | `benchmark-time-v1` / `meta-resource-planning-v1` | [task_time.py](../../src/execution/host/task_time.py)、[resource_planning.py](../../src/control/resource_planning.py) |
| 任务完成 / 版本选择 | `task-completion-v4` / `meta-selection-v1` | [outcomes.py](../../src/evidence/outcomes.py)、[store.py](../../src/control/store.py) |
| 探索结束 / 存储 | `goal-or-budget-v1` / `shared-artifacts-v1` | [stop_policy.py](../../src/control/stop_policy.py)、[objects.py](../../src/evidence/objects.py) |

字段定义以 [contracts.schema.json](../../schemas/contracts.schema.json)、[工程 schema](../../schemas/execution/harness-project.schema.json) 和对应协议资产为准；[目标默认值](../../schemas/meta-defaults.json)与[UI 初始配置](../../packages/meta-workbench-client/defaults.mjs)分别维护。已创建活动保存自己的绑定，不因当前默认值变化而升级。

## 核验与边界

[依赖检查](../../scripts/check-boundaries.py)同时检查静态导入、包声明、配置与执行资产清单。静态检查不能证明动态独立运行；后者由容器及搬迁契约验证。覆盖表见[实现核对](../development/implementation-audit.md)。

主线的运行条件是标准 Docker/Harbor 和本地受管数据目录。机器兼容层、外部存储转换、托管网络与实例发布由部署侧维护；这些能力不作为主线默认 UI、测试或导出依赖。

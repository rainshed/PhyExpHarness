# 文档导航

本文档描述主线当前实现。新活动的默认契约见[架构总览](architecture/overview.md)，已有活动的行为按[兼容规则](architecture/compatibility.md)核对。历史方案不作为当前操作入口。

## 三条阅读路线

| 目的 | 阅读顺序 |
|---|---|
| 了解项目 | [设计哲学](product/philosophy.md) → [产品要求](product/requirements.md) → [核心概念](product/concepts.md) |
| 运行项目 | [快速开始](guides/quickstart.md) → [模型配置](guides/models.md) → [活动操作](guides/campaigns.md) → [阅读结果](guides/evidence-and-reports.md) |
| 开发项目 | [架构总览](architecture/overview.md) → 对应模块 → [开发流程](development/workflow.md) → [验证说明](development/testing.md) |

## 使用指南

- [快速开始](guides/quickstart.md)：依赖、构建、后台与工作台启动。
- [Agent 安装流程](guides/agent-installation.md)：必要输入、可执行命令、成功条件与恢复。
- [准备 Quantum-Harbor](guides/quantum-harbor.md)：外部任务来源、版本、基础镜像与无模型检查。
- [模型配置](guides/models.md)：主线模型目录、认证、连接测试及参考模型入口。
- [活动操作](guides/campaigns.md)：创建、准备、计划、实验、选择、暂停和停止。
- [证据与报告](guides/evidence-and-reports.md)：成功率、研究动机、比较、历史来源及完整证据。
- [导出独立项目](guides/export.md)：内容、安装运行和验证层次。
- [维护与排障](guides/maintenance.md)：更新、备份、存储、删除、故障定位和历史整理。

## 当前架构

| 主题 | 权威说明 |
|---|---|
| 模块、依赖与默认版本 | [架构总览](architecture/overview.md) |
| 候选策略、构建、模型通道、任务运行 | [执行工程](architecture/execution.md) |
| 通用 Agent、领域工具、研究委派、恢复 | [Meta 运行时](architecture/meta.md) |
| 活动状态、模型访问、限额、异步归集 | [控制后台](architecture/control.md) |
| 计分、研究记录、报告、存储与删除 | [证据与存储](architecture/evidence-storage.md) |
| 冻结身份、共享对象、按需交付 | [版本与导出](architecture/versions-and-export.md) |
| 可选模型、Harness 和联合参考 | [参考实验](architecture/references.md) |
| 客户端、桥、Studio 及 UI 增删 | [工作台](architecture/workbench.md) |
| 旧活动、旧协议、历史计分与回放 | [兼容规则](architecture/compatibility.md) |

## 开发与维护

- [开发流程](development/workflow.md)：范围、提交、源码职责和记录归属。
- [验证说明](development/testing.md)：单元、容器契约、规模与真实实验的区别。
- [文档维护](development/documentation.md)：权威来源、迁移规则、链接检查。
- [实现核对表](development/implementation-audit.md)：功能声明对应的代码、测试和验证边界。
- [待办与验证缺口](plans/README.md)：仍需单独验证或设计的事项。
- [插件库与用户组合 H0：Agent 实施任务书](plans/plugin-library-and-h0.md)：待实施工作包、自动检查、人类验收和交付条件；不含 Meta 自主选库。
- [历史文档索引](archive/README.md)：被替代的设计、计划及旧运行说明。

执行 SDK 的资料源继续在 [knowledge/plugin-sdk](../knowledge/plugin-sdk/README.md)，字段契约继续在 [schemas](../schemas/contracts.schema.json)，命令继续以 [package.json](../package.json) 为准。完整导航只在此维护。

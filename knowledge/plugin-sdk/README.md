# 执行 Harness 开发资料

本目录提交资料源与技术样例。仓库执行 npm ci 后运行 npm run build:knowledge，生成 reference；完整构建为 npm run build。生成器从锁定 SDK、类型和本目录读取，不读取活动数据库或实验结果。新活动快照当前资料，已有活动保持原包。

## 当前入口

新活动使用 harbor-process-v1 完整工程，先读[完整工程开发](guides/process-harness.md)。默认工程位于 /work/plugins/h0，可复制后修改框架、依赖、profile、工具、会话和恢复。资料中的 DSH 0.2.1-rc.2 接口适用于默认模板，不是平台允许策略的全集。

[教程索引](guides/README.md)列出可通过 sdk_read 读取的资料 ID。sdk_search 搜索、sdk_read 读取、sdk_inspect 查询声明；查询不执行业务方法，也不保证额外依赖已装配。客户端、凭据、数据库与 UI 服务不属于候选能力。

候选通过 projectPath 检查/冻结完整工程，声明见 harness.json。候选代码及安装脚本只在隔离环境运行；正式模型请求使用固定 Solver 通道。源代码、锁、产物、入口和配置进入冻结身份。检查通过仅证明构建与入口，正式行为以实验为准。

## 插件与阅读信息

沿用 DSH 时，ESM 模块导出 name、inject、apply，作用域销毁清理工具、事件和上下文。tools/post-execute 返回合法 decision，tools/result 是冻结结果。源码 inject 表示服务依赖，和旧插件清单 dependencies 的组合顺序不是同一概念。

完整工程在 harness.json.plugins 声明插件名称、版本、源码 path 和组合 config；目录 plugin.json 或工程声明可提供中文 displayName、functionSummary、mechanism 和多选 categories。准确规则见完整工程指南。用途说明是设计意图，效果依赖实际轨迹与对照，缺失信息如实标注。

技术例子 examples/echo.mjs 展示工具与结果处理，不规定研究算法。plugin-manifest 资料 ID 保留旧 v1/v2 清单参考；新工程的策略配置不受旧 capability 枚举或固定依赖集合限制。

## 实验、资源与报告

先读取活动状态并提交资源计划，再自主选择候选、任务和重复次数；新 process 活动不强制全套 H0。操作返回身份及文件入口，后台通知持久推送；未知写结果沿用原幂等键核对，不能换键重复提交。

maxRounds/maxTrials 为 null 表示不单独限制，墙钟和并发生效。新活动不预留、结算或累计 token/费用。每题时限来自 benchmark，资源计划只包含并发和收尾时间，见[资源规划](guides/resource-planning.md)。

报告区分系统事实、观察和解释。candidate_freeze 可附可读名称和研究修订，candidate_retain 保存选择、备选、局限及证据；report_save 的正文契约以活动绑定工具 schema 为准。缺少对照时说明不确定性，不以提示加载或插件名称代替效果证据。完整结果、错误和大输出从回执给出的路径继续读取。

## 历史范围

v1/v2 固定 Runner 的清单、网关恢复与用量规则以该活动冻结资料为准，不从当前教程反推升级。reference/manifest.json 的 sdk-minimal profile 指纹识别这份 DSH 参考资料，不限制完整工程更换框架。历史源码和原始记录不改写。

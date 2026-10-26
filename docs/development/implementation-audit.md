# 文档与实现核对

范围：主线当前源码与新活动默认行为。核对依据为代码分支、配置/schema、现有行为测试及生成资料；历史方案的“已完成”标签不作为证据。检查命令见[验证说明](testing.md)，原始日志保留在本地 reports/development/documentation-restructure，不进入源码仓库。

## 功能对应

| 文档声明 | 实现来源 | 可执行行为检查 |
|---|---|---|
| 主项目独立依赖锁，后台/UI 一致处理 XDG 与显式路径 | [主项目锁](../../requirements-control.lock)、[UI 路径](../../scripts/local-paths.mjs)、[后台路径](../../src/control/paths.py) | [跨语言路径检查](../../tests/unit/local-paths.test.mjs)；新虚拟环境按锁安装及 pip check |
| 安装可复用，缺项自检提供结构化恢复信息 | [安装入口](../../scripts/phyexp.py)、[安装与自检](../../src/onboarding/install.py) | [安装行为](../../tests/unit/onboarding_install_test.py) |
| 统一启动核对实例与 UI 桥，活动命令保留创建/启动身份 | [本地启动](../../src/onboarding/runtime.py)、[首次实验](../../src/onboarding/experiment.py) | [进程行为](../../tests/unit/onboarding_runtime_test.py)、[首次实验恢复](../../tests/unit/onboarding_experiment_test.py)、[导航链接](../../tests/unit/onboarding-links.test.mjs) |
| 新活动采用完整工程与当前策略，回放保留原绑定 | [service.py](../../src/control/service.py)、[meta_context.py](../../src/control/meta_context.py) | [process_candidates_test](../../tests/unit/process_candidates_test.py)、[meta_contracts_test](../../tests/unit/meta_contracts_test.py) |
| 候选可替换框架、工具、会话和恢复 | [工程冻结](../../src/execution/bundle/project.py)、[默认工程](../../templates/harness/default/harness.json) | [process-strategies](../../tests/contracts/process-strategies.test.mjs)、[project_bundle_test](../../tests/unit/project_bundle_test.py) |
| check 是隔离构建/入口核验，不是科学实验 | [process_candidates.py](../../src/control/process_candidates.py) | [process_candidates_test](../../tests/unit/process_candidates_test.py)、[project-build](../../tests/contracts/project-build.py) |
| 新活动无 token 账本，旧账本仍兼容 | [model_access.py](../../src/control/model_access.py)、[accounting.py](../../src/control/accounting.py) | [model_access_test](../../tests/unit/model_access_test.py)、[model-access](../../tests/unit/model-access.test.mjs) |
| benchmark 阶段上限与活动截止独立，允许短窗口启动并保留实际时间条件 | [task_time.py](../../src/execution/host/task_time.py)、[resource_planning.py](../../src/control/resource_planning.py) | [benchmark_time_test](../../tests/unit/benchmark_time_test.py)、[benchmark-task-ui](../../tests/unit/benchmark-task-ui.test.mjs) |
| 后台 Meta 规划并发/收尾，新 process 不强制全部 H0；UI 次数校验仍有差距 | [service.py](../../src/control/service.py)、[资源规划](../../src/control/resource_planning.py) | [process_candidates_test](../../tests/unit/process_candidates_test.py)、[resource_planning_test](../../tests/unit/resource_planning_test.py) |
| Meta 提交理由与总结自主收尾；在途工作落定，无报告或额外回复门槛；旧规则保留 | [stop_review.py](../../src/control/stop_review.py)、[meta.py](../../src/control/meta.py)、[收尾展示](../../packages/meta-workbench-studio/client/components/closeout.tsx) | [meta_finish_test](../../tests/unit/meta_finish_test.py)、[meta-closeout-ui](../../tests/unit/meta-closeout-ui.test.mjs)、[stop_review_test](../../tests/unit/stop_review_test.py)、[meta_prompt_test](../../tests/unit/meta_prompt_test.py) |
| 主 Meta、研究委派、持久文件/会话及角色边界 | [meta_native_composition.py](../../src/control/meta_native_composition.py)、[meta_worker_native.mjs](../../src/control/meta_worker_native.mjs) | [meta-native](../../tests/contracts/meta-native.test.mjs)、[meta-research](../../tests/contracts/meta-research.test.mjs) |
| 完整结果落文件，短回执与分页读取 | [meta_tool_boundary.py](../../src/control/meta_tool_boundary.py)、[meta_outputs.mjs](../../src/control/meta_outputs.mjs) | [meta-output-boundary](../../tests/contracts/meta-output-boundary.test.mjs)、[meta_tool_boundary_test](../../tests/unit/meta_tool_boundary_test.py) |
| SDK 指南冻结且新建时完整核验 | [build-knowledge.py](../../scripts/build-knowledge.py)、[knowledge.py](../../src/control/knowledge.py) | [knowledge_snapshot_test](../../tests/unit/knowledge_snapshot_test.py)、[生成资料](../../knowledge/plugin-sdk/README.md) |
| 固定模型通道及策略与监督分工 | [broker.mjs](../../src/execution/process/broker.mjs)、[single_run.py](../../src/execution/host/single_run.py) | [process-broker](../../tests/unit/process-broker.test.mjs)、[process-harness](../../tests/contracts/process-harness.test.mjs) |
| 官方结果与退出状态分开，缺分保持 null | [result_collection.py](../../src/control/result_collection.py) | [official_results_test](../../tests/unit/official_results_test.py)、[result_collection_test](../../tests/unit/result_collection_test.py) |
| v4 纳入终结失败，旧计分不自动重算 | [outcomes.py](../../src/evidence/outcomes.py) | [task_completion_v4_test](../../tests/unit/task_completion_v4_test.py)、[outcomes_test](../../tests/unit/outcomes_test.py) |
| 归集/索引与执行名额分离，重启不重跑 Solver | [collection.py](../../src/control/collection.py) | [collection_workers_test](../../tests/unit/collection_workers_test.py)、[control_scalability_test](../../tests/unit/control_scalability_test.py) |
| 报告/研究/选择保留准确修订与来源 | [research.py](../../src/control/research.py)、[reports.py](../../src/reporting/reports.py) | [evolution_test](../../tests/unit/evolution_test.py)、[selection_test](../../tests/unit/selection_test.py)、[report_tables_test](../../tests/unit/report_tables_test.py) |
| 共享正文、快照、分段日志及存储保护 | [objects.py](../../src/evidence/objects.py)、[storage.py](../../src/control/storage.py) | [artifact_objects_test](../../tests/unit/artifact_objects_test.py)、[storage_snapshots_test](../../tests/unit/storage_snapshots_test.py)、[storage_capacity_test](../../tests/unit/storage_capacity_test.py)、[log-store](../../tests/unit/log-store.test.mjs) |
| 用户永久删除与共享引用/恢复边界 | [deletion.py](../../src/control/deletion.py)、[deletion_storage.py](../../src/control/deletion_storage.py) | [campaign_deletion_test](../../tests/unit/campaign_deletion_test.py) |
| 两个可选参考插件、三类结果和兼容配对 | [reference/service.py](../../src/control/reference/service.py)、[catalog.py](../../src/control/reference/catalog.py) | [reference_plugins_test](../../tests/unit/reference_plugins_test.py)、[process_reference_test](../../tests/unit/process_reference_test.py)、[reference-harnesses](../../tests/contracts/reference-harnesses.test.mjs) |
| 导出准确冻结闭包，验证状态分层 | [exporting/project.py](../../src/exporting/project.py) | [export_test](../../tests/unit/export_test.py)、[process-standalone](../../tests/contracts/process-standalone.py) |
| UI 独立、公共客户端/桥、幂等创建与页面生命周期 | [UI 清单](../../profiles/meta-workbench/uis.json)、[公共客户端](../../packages/meta-workbench-client/package.json) | [workbench-registry](../../tests/unit/workbench-registry.test.mjs)、[workbench-client](../../tests/unit/workbench-client.test.mjs)、[workbench-lifecycle](../../tests/contracts/workbench-lifecycle.test.mjs) |
| 供应商快照、认证不进候选、连接测试不要求 usage | [provider_settings.py](../../src/control/provider_settings.py)、[provider_probe.mjs](../../src/control/provider_probe.mjs) | [provider_settings_test](../../tests/unit/provider_settings_test.py)、[providers](../../tests/contracts/providers.test.mjs) |

## 本轮纠正的主要不一致

| 旧文档问题 | 按实现校正 |
|---|---|
| 当前新活动仍累计 token/费用、设置 token 子额度 | control-only-v1 不做累计/预留/结算；历史路径单列 |
| 首次计划自动跑全部 H0、任务数必须被基线额度覆盖 | 后台新 process 不强制该顺序；Studio 仍保留旧次数表单校验，已写入指南和待办 |
| 用户/Meta 分配单次时限，固定扣除 330 秒 | 新活动时限由 benchmark 分阶段读取，不接受覆盖/缩短 |
| 默认恢复和工具清单属于不可修改基础设施 | 新工程拥有策略，默认模板是可修改候选 |
| 默认六项插件全部启用、探索耗尽经审查可停止 | 停止审查默认关闭；历史 goal-or-budget 拒绝 exhausted，新活动由 Meta 提交理由与总结自主收尾 |
| 通用 Agent/完整证据“待实施”，参考插件“尚未实施” | 当前已有实现，文档说明准确角色、路径与兼容限制 |
| 全部归档串行后才有结果，无缓存自动清理 | 结果与索引分阶段发布；自动回收仅在可证明安全的范围 |
| 新候选按旧 v2 插件清单交付 | v3 包含完整工程与构建产物，旧 v1/v2 继续兼容 |
| 当前手册混入阶段授权、历史失败和现场记录 | 持久开发规范、当前指南与历史稿分开，日志留本地 |

## 核验范围与结论

核对日期：2026-10-26；业务实现基线为 1698375。本轮修改文档、SDK 资料源及文档检查工具，没有修改业务执行规则或活动数据。

| 本轮实际执行 | 结果与范围 |
|---|---|
| 文档导航 | 63 份受维护 Markdown 的本地链接、锚点、现行页面可达性和历史引用边界通过 |
| 单元检查 | 217 项 JavaScript、518 项 Python 通过，无跳过；含文档检查器的 6 项回归 |
| 原生/容器契约 | 95 项通过，无跳过，使用假 provider/本地协议服务及准备好的 Meta/参考镜像 |
| 构建与资料 | SDK 资料、Studio 构建通过；生成包与资料源摘要一致；11 段 shell 示例语法通过 |
| 安装与源码独立性 | 不含 Git 元数据、依赖或本地生成物的源码副本执行 npm ci、build、check:project、check:docs 通过 |
| 后台启动 | 项目虚拟环境、新空数据目录按指南启动独立后台，认证 health 返回 running、0 个活动；随后关闭本轮进程 |
| UI/后台差异 | 合成两任务、maxTrials=1 的配置被后台接受、被 Studio 拒绝，已复现并记录为[待修复项](../plans/README.md#当前已确认的实现差距) |

首次用未安装 Harbor 的系统 Python 运行单元检查失败；按指南使用项目虚拟环境后完整复测通过。首次失败与复测日志均保留，不计为代码通过证据。

本轮没有新调用真实模型，没有重跑官方任务烟测、完整 ZIP 搬迁、50,000 条规模测试、数日活动或人工浏览器体验；表中这些专项入口用于复现，不表示本轮已经执行。当前文档明确区分产品要求、已实现行为与验证缺口，尤其保留上述 UI 实现差距。

## 通用主动收尾修改的验证

2026-10-26，以 c5940cc 为实施前源码基线、681c1da 为方案提交。新活动采用 meta-closeout-v1 / meta-tools-v10 / meta-system-v12，旧工具 v9 的绑定摘要及旧模板 v11 保持原内容。本节仅记录本次修改，不将上一节的历史验证继承为新版本结论。

专项检查覆盖自定义目标无稳定性规则、无候选/实验、失败成绩、理由与总结必填、主/子权限、幂等冲突与未知回执恢复、在途主线/参考/构建/归集、会话中断无需额外回复、截止/用户停止缺失总结、UI 与报告来源区分。原生隔离 Runner 使用脚本 provider 验证实际工具 schema 与理由/总结传递；[完整宿主检查](../../tests/contracts/meta-closeout.py)实际通过冻结运行时、已认证 HTTP 控制和最终事实归集，模拟模型仅请求一次且没有收尾后的回复，活动正常结束。[历史夹具](../../tests/contracts/meta_runtime.py)显式物化 v9 工具，原 stable 与每轮报告流程保持有效。

最终检查结果记录于本地 reports/development/meta-harness；本次未调用真实模型、未发布远端实例或转换旧活动，亦未重跑完整搬迁、数日压力或全部容器契约。完整单元检查 220 项 JavaScript、533 项 Python 通过，无跳过；通知调整后的 Meta 专项 75 项通过；SDK 资料与 Studio 构建通过。第一次完整检查出现既有控制测试临时目录清理竞争，单独 18 项控制测试及随后完整复测通过；保留首次失败日志，不把它算作通过证据。最后的报告索引、通知与构建准入调整后，全部 533 项 Python 再次通过；页面和工具专项 34 项通过，构建与项目/文档检查通过。


## Agent 安装流程的验证

2026-10-26，以 78566be 为修改前源码基线，先提交方案 d60ed7d；依赖与路径修改在 05e415c，安装入口在 f802ff3，本地启动与活动命令在 0c8dee9。本节记录这组修改的验收，不继承前文其他功能的历史结论。

本轮在 macOS arm64、Node 24.13.0、Python 3.13.7 上使用不含 Git 元数据、项目依赖、生成文件和历史数据的临时源码副本，实际完成首次 setup、完整锁安装与 pip check、重复 setup 的依赖复用、doctor --project-only 和资料/UI 构建。另用临时数据运行真实后台与 DSH UI，验证认证桥、准确实例身份、重复启动 PID 不变，以及只生成首次计划而不启动模型。[可复现契约](../../tests/contracts/onboarding.py)使用显式合成任务元数据，覆盖查询、计划复用与无活动安全退出。

初次全量检查中 222 项 JavaScript 通过，552 项 Python 有 3 项因依赖相邻 Quantum-Harbor 而失败。将这两组单元测试改用合成任务文件后，相关 24 项及完整 552 项 Python 复测通过，无跳过；保留首次失败日志。新增检查覆盖缺项、重复安装、端口占用、实例身份、凭据缺失、创建/启动响应丢失、一次实验上限及官方文件摘要变化。完整构建、项目边界与文档检查通过。原始记录保存在本地 reports/development/meta-harness/agent-installation。

[GitHub 工作流](../../.github/workflows/project.yml)已加入 Ubuntu/macOS 新克隆安装、复用、单元及启动检查，但本轮没有推送或执行托管 runner。没有调用真实模型，没有将单元夹具或 HTTP 桥检查称作首次真实实验/浏览器验收。浏览器工具的安全策略拒绝打开 file: 登录页，页面验收仍待执行；其他平台容器与真实首次实验也保留在待办计划。


## 实验晚启动与活动截止的验证

2026-10-26，以 ba2b5e4 为修改前源码基线，先提交文档与实施边界 42b61ec。新活动采用 benchmark-time-v2 / meta-system-v13；任务元数据仍保留 v1，旧活动与冻结配方维持完整阶段预留策略。主线和参考实验允许短窗口受理、启动及准备后开始求解，活动硬截止与明确选择的有限延期模式保持独立。

在项目虚拟环境执行 `PATH="$PWD/.venv/bin:$PATH" npm test`，最终 225 项 JavaScript、568 项 Python 全部通过，无跳过。`npm run build`、补充 UI 构建、`npm run check:docs` 和 `npm run check:project` 通过。测试覆盖短窗口、正常完成、到期中断、启动准备跨越截止、排队到期、暂停/并发/收尾预留、drain 只允许在途任务延期、参考实验共用时间策略、旧策略回归、真实原因与先行故障保留、官方结果优先、时间条件展示和比较。

[时限检查](../../tests/unit/benchmark_time_test.py)使用合成 benchmark 元数据、模拟时钟与宿主进程回执；[官方结果检查](../../tests/unit/official_results_test.py)核对时间证据、截止原因及可信成绩；[归集检查](../../tests/unit/result_collection_test.py)覆盖控制端停止记录；[界面检查](../../tests/unit/benchmark-task-ui.test.mjs)和[比较检查](../../tests/unit/studio-readability.test.mjs)核对缺失时间不伪造为零、短窗口不标为条件一致。本轮没有运行真实模型、真实 Docker 端到端实验、完整独立搬迁或浏览器人工验收，不据单元通过宣称这些层已验证。

首次直接调用系统 Python 缺少 Harbor；改用项目虚拟环境后专项通过。首次完整回归中一项旧测试误用当前策略常量，改为显式绑定旧策略后完成全量复测；一次单独导入测试缺少测试目录路径，最终按标准 discover 入口验证。原始日志与最终结果保存在本地 reports/development/meta-harness/late-start，不改写既有验证记录。


## 插件库后台第一阶段

2026-10-26，从 76d95a6 开始实施。[插件库](../../src/control/plugin_library.py)实现独立内容登记、历史补录进度、删除记录、修订与幂等、引用保护和宽限期清理；[候选接入](../../src/control/process_candidates.py)在构建前保存可定位插件，失败也保留源码。库 HTTP 路由仅用户可调用。

[库专项](../../tests/unit/plugin_library_test.py) 7 项与[候选专项](../../tests/unit/process_candidates_test.py) 5 项通过，覆盖身份、失败源码、内容完整性、来源脱离、删除/恢复、依赖保留、重扫续接和用户/Meta 路由隔离；此前插件相关 22 项通过。尚未完成装配、H0 入口、完整并发/浏览器/容器验收；不把单元结果当作全部功能通过。后续按[任务书](../plans/plugin-library-and-h0.md)补齐验证。

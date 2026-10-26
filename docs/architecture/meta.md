# Meta 运行时

适用：`meta-composition-v2`、当前工具 v10 与系统模板 v12。准确输入与结果 schema 见[contracts.json](../../packages/meta-harness/contracts.json)，身份冻结见[meta_native_composition.py](../../src/control/meta_native_composition.py)。

## 原生能力与领域插件

Meta 使用锁定 DSH 的原生文件/图片读取、搜索、编辑、终端、jobs、待办、技能、会话查询、压缩及普通研究委派。系统职责叠加到原生能力上，任务目标来自活动快照；源码默认目标见[meta-defaults.json](../../schemas/meta-defaults.json)。

[composition-native.json](../../packages/meta-harness/composition-native.json)定义 meta-control、meta-campaign、meta-experiments、meta-evidence、meta-reporting 和 meta-stop-review。前五项提供受控服务、上下文/计划、候选/实验、资料和报告/导出；停止审查模块默认关闭，保留历史策略支持。可选参考插件另见[参考实验](references.md)。

候选开发的文件和脚本在 Meta 隔离容器中运行；终端不获得任意外网、真实凭据或数据库。镜像依赖由[开发依赖锁](../../packages/meta-harness/development-dependencies.json)和[运行包锁](../../packages/meta-harness/runtime-package-lock.json)提供，不能把开发环境已有库视为候选正式依赖。候选构建是另一条受管流程。

## 文件与完整输出

| 路径 | 用途 |
|---|---|
| `/work/plugins` | 持久可写候选工程，默认 h0 |
| `/work/analysis`、`/work/checks` | 分析文件与开发检查 |
| `/evidence`、`/materials` | 本活动获准的完整证据、任务原文、研究和报告材料 |
| `/sdk`、`/versions` | 冻结资料与候选的只读来源 |
| `/outputs` | 受管捕获器发布的完整工具/终端输出 |
| `/session` | 原生持久会话 |

工具结果先保存完整正文，模型收到简短回执及可访问路径。`tool_result_read` 使用 Unicode 字符偏移，续页同时核对 nextOffset 与 sha256；不能将预览当成原件。campaign_status 等大快照使用 query-tree-v1 文件树，读取器按 format/kind/file 遍历；文件缺失或容量耗尽明确说明不完整。会话中的巨大事件也可转为文件入口。

SDK 资料在 `npm run build:knowledge` 时从锁定安装、指南与类型生成。新活动完整核验并原子快照资料；已创建活动及幂等回放保留原包。生成期间资料不完整会拒绝创建，不通过替换摘要绕过。源资料见[SDK 索引](../../knowledge/plugin-sdk/README.md)。

## 普通研究与停止审查

普通研究使用原生进程内子代理，主/子独立上下文，共享持久工作区和会话存储；支持消息补充、同 ID 追问、中断和冷恢复。cwd 是工作目录，不是隔离边界。研究角色的业务接口只读，不能提交正式实验、保留版本或写正式报告；共享终端仍属于同一研究信任域。

普通研究没有独立的隐含五分钟总时限，受原活动截止和取消约束。历史停止审查使用单独 Runner、只读证据和独立审查身份，不能由研究子会话冒充。新活动由主 Meta 通过通用入口提交结束理由与实验总结，自主决定收尾；完整状态语义见[控制后台](control.md#暂停停止与探索完成)。

主 Meta 的用户问题经[meta_questions.py](../../src/control/meta_questions.py)持久保存，并在工作台回答；普通研究子会话不能冒充主会话提问。已回答的同一问题回放不得改写为不同答案。

## 会话恢复与通知

后台保存会话身份、主/子目录、通知及确认位置。恢复先核对已受理操作、实验与报告回执，不以模型重述替代后台状态；写操作仍使用原幂等身份。暂停/技术恢复可以建立有 previousSessionId 的续接记录，文件和原生历史保留。

[meta_recovery.py](../../src/control/meta_recovery.py)与驱动处理技术故障，不能承诺恢复已丢失的 OS 进程内存、未落盘消息或未知工具副作用，也不能因重启重置活动上限。终态会话拒绝迟到心跳回写为 waiting；活动结束后继续回收残留进程。

Meta 恢复与候选内 Solver 恢复是不同职责；主 Meta 的策略不会自动替换已经冻结的候选。查询、脚本模型和隔离契约证明工程路径，不能证明长活动研究质量。测试入口：[原生 Meta](../../tests/contracts/meta-native.test.mjs)、[研究委派](../../tests/contracts/meta-research.test.mjs)、[输出边界](../../tests/contracts/meta-output-boundary.test.mjs)。

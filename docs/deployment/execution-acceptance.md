# 完整执行工程的历史验收

本文件从保存基线 `7973de6` 的部署资料提取，适用于 `deploy/tensortrain2`。主线运行接口见[运行说明](../guides/quickstart.md)。本次拆分未连接服务器、切换服务或转换活动数据。

以下保留原验收范围、结果和失败说明，不作为拆分后版本的重新验收结论。

## 9. 实施与验收记录（2026-10-24）

实现基线从 `198c382` 推进；每个实现/修复增量均单独验证并本地提交。真实 Meta 已逐批保存分析、选中并导出 H1，最终报告也已提交。实际验收使用 Tensortrain2 的独立 release 与独立数据根，原生产检出、在途活动和已有候选未热迁移。完整日志及元数据位于本地 `reports/development/meta-harness/execution-v3/`；远端根为 `execution-v3-acceptance`，真实轨迹与任务答案不入库。

### 9.1 代码处置

| 限制 | 最终处置与实现入口 |
|---|---|
| R01–R04 | 保留固定 Solver、凭据隔离、官方评分权威和外部期限/并发/次数。`process/binding.py`、`process/broker.mjs`、`host/task_time.py`、`control/store.py`；不把默认候选的 maxTokens 当作用户硬上限。提供方不支持的原生字段不能宣称已硬执行。 |
| R05 | 构建/模型通道容量显式进入 `process-resources.json`、活动和配方；main/qsim 实际 HostConfig 进入证据及比较。未更改 benchmark 科学资源定义。 |
| R06–R10 | `bundle/project.py` 冻结完整工程；支持任意框架/profile、锁定新依赖、安装脚本、内部链接和文件模式。拒绝工程逃逸、特殊对象及超出声明产物容量，停止构建会收回容器。 |
| R11–R15 | 新链路不读旧 capability 枚举，不强制 bash/MCP 名称、工具全集或单会话；`ProcessHarborAgent` 只启动/监督候选进程。候选可用原生文件、PTY、子进程与工具。 |
| R16–R22 | 默认结果处理、MCP、上下文和恢复都在 `templates/harness/default/`。候选可以替换/删除；独立 broker 不判断恢复资格、不隐藏重试、不永久锁死内容错误。HTTP/SSE 流背压替代旧 16 请求/32 MB JSON-RPC 限制。 |
| R23 | `task_network.py` 使 main 仅接入自己的 qsim 和模型通道；构建网络独立，删除新 Solver 的双容器工具隧道。 |
| R24–R27 | check 明确只核验隔离构建/产物/入口，不要求一次请求或工具加载；任务名字符串合法。依赖图由候选框架解析；缺依赖/环按实际框架诊断，平台不按插件列表顺序拒绝。任务原文归档，呈现方式归候选。 |
| R28–R31 | 候选非零/超时映射 Harbor 原生异常。`official.py` 独立读取官方产物，不要求 completed turn/toolCalls；官方与可选诊断分开核验，有效分数不被诊断错误清空。 |
| R32–R35 | 保留所有尝试、v4 分母、不可变快照、幂等、四类结果状态与精确独立导出。新收集器幂等重读；旧补读特例仅服务历史格式。 |
| R36 | 保留宿主已经验证的五任务兼容范围；五任务全部实际回归。单 UID 对其他 UID/特殊服务的能力没有凭空扩展，兼容适配仍明确版本化；不借此限定候选框架、工具或恢复算法。 |
| R37 | 新 Solver 通道只检查本地运行租约/截止，无逐请求数据库调用；控制失联、监督丢失和主动撤销分别测试。Meta 管理通道和旧 Solver 路径保留各自原契约。 |

统一业务入口为 `candidate_check/freeze(projectPath)`、batch_submit、证据/比较和 export_create；不存在为重试、压缩、动态工具或新依赖新增的特批业务接口。v1/v2 兼容实现保留在明确旧版本分支，新默认为 harbor-process-v1 / composition-v3 / meta-tools-v9 / meta-system-v11。

### 9.2 验收矩阵执行证据

“通过”表示本行注明范围的测试通过。合成 provider、真实容器、真实模型和官方科学结果分别标注，不相互冒充。

| 编号 | 已执行证据与结果 |
|---|---|
| A01 | `process-meta-real.py`：真实 Meta 读取历史失败，自主写 H1，首次自测失败后自行修复，通过 check/freeze，再提交 8 次正式测试并读取官方结果；源码和摘要全程可核对。 |
| A02 | `project-build.py` / build-06：新增 is-odd 与传递依赖，npm ci/postinstall 实际执行，宿主凭据哨兵不可见；缓存复用、超限接收和取消全部通过。 |
| A03 | `project_bundle_test.py`、`process_candidates_test.py`、`process-strategies.test.mjs`：框架声明、依赖、profile、配置变化形成新身份，不改变外部条件；新依赖与 profile 实际运行。 |
| A04 | `process-broker.test.mjs`：动态工具子集、无工具和新增工具名、20 并发调用通过；原生候选多会话通过。capability 自由声明另由工程冻结测试覆盖。 |
| A05 | 原生候选以 research_terminal 替换 bash，持久 shell 状态和工作区文件确实可见；真实 main 中 PTY 与两个非合作后台进程通过 lifecycle-cancel-04 验证并被收回。 |
| A06 | 原生 request-recovery、recovery-composition、process-harness、process-strategies 契约覆盖断流、异常响应/JSON及装配/移除恢复；broker 的 503 不阻断后续请求且不偷偷重试。 |
| A07 | 原生策略契约先完成文件副作用，再注入坏 JSON、类型错误与合法工具混合，副作用只发生一次，非法参数产生正常工具错误。 |
| A08 | 工程 check 不启动 provider、不统计调用数；无工具与两会话候选均可运行。回执注明检查范围，不把 build passed 当 science passed。 |
| A09 | broker 测试 20 并发、33 MiB 请求、34 MiB 响应及慢读者；超过声明容量明确 413，不存在旧 16/32 隐含终止。 |
| A10 | 固定请求测试涵盖原生 Responses/compact 和辅助并发；真实原生压缩/恢复契约通过，候选所有会话使用同一个模型通道和外部截止。 |
| A11 | official_results 单测核验“官方 1 分 + 非零退出”；真实 Harbor 五任务脚本 exit 7 均继续 verifier 并取得官方 0 分。前者验证保分，后者验证原生异常生命周期，未冒充同一条真实科学成功轨迹。 |
| A12 | lifecycle-timeout-03 使用**明确合成的 10 秒 agent 时限**，原任务未修改；AgentTimeoutError 后官方 0 分。真实取消为 null/user_stop，启动环境失败另行保留。 |
| A13 | 官方读取单测损坏候选轨迹、缺失诊断仍保留已核验分数；关闭/清理独立于官方读分；失败原因并列。 |
| A14 | 篡改 reward、错误归属、冲突官方产物均不标可信成绩；不可由候选自报覆盖。 |
| A15 | 幂等重读、收集失败后重试、终态投影四字段同步通过；不启动新模型调用或 Trial。 |
| A16 | 五个真实任务 main 内探测：错误模型 403、没有宿主 socket/凭据/私有 verifier 路径、公网出口不可用；内部网络与各任务容器身份分别记录。 |
| A17 | cancel / supervisor-loss / timeout 均确认原候选已启动；取消双后台非合作进程的 case 通过，所有本次容器/网络消失。独立运行清理身份防止相同 output basename 误杀。 |
| A18 | benchmark_time 与调度测试区分排队/构建、准备、Solver 和 verifier；真实 Trial 使用原任务完整阶段时限，没有为加速验收缩短正式测试。 |
| A19 | Studio 比较测试与真实固定条件记录；候选依赖/profile 与平台/任务/模型/资源区别处理，旧缺项保持未知。 |
| A20 | task_completion_v4、报告与证据回归通过；全部 8 次正式尝试进入报告，H0 三次失败未排除，官方 null 与 0 不合并。 |
| A21 | standalone-real-03：新 Python 精确锁环境、实际 ZIP、mount namespace 隐藏原仓库/控制数据/对象/源码，导出入口取得 hamlearn 官方 1 分。冻结→ZIP→执行摘要一致。 |
| A22 | 历史归档/工具 v6/v8、v1/v2 解析/迁移/导出单测、旧 Runner 恢复/装配及原生历史 Meta 契约通过；新旧版本分开，不重写原件。 |
| A23 | 工程源码包含 time_budgeted_hamlearn_10q 仍可冻结；此事实不证明泛化。 |
| A24 | 五任务实际 main/qsim、网络边界、资源记录、非零退出、sidecar 收集和官方 verifier 全部通过；未扩大未验证环境的支持声明。 |
| A25 | 构建输入缓存复用、命令幂等/重启对账测试通过；真实 Meta 多次技术恢复后仍只有约定的 8 个 Trial，没有因恢复重复提交。 |
| A26 | broker-storage-01 在独立 1 MiB tmpfs 实际写满后返回审计 507，提供方调用数为 0；故障注入也验证无未处理 rejection。真实构建容量不足在落盘前停止接收并收回容器，不耗尽共享宿主磁盘。 |
| A27 | broker 无控制查询，原截止/撤销测试通过；真实监督 SIGKILL 后同一清理路径收回运行；独立导出在整个控制目录不可见时调用模型并评分。 |
| A28 | 原生候选自带 MCP 客户端保持会话，收到会话失效 404 后重建会话，工具成功两次且返回展示可替换；五任务真实接入另使用 Python MCP 客户端。 |
| A29 | 原生候选反向列出服务依赖仍能装配；缺依赖/循环有具体服务诊断。可选未就绪插件是否阻止启动是框架行为，平台不新增列表顺序门槛。 |
| A30 | 原生上下文后缀/会话变体实际生效；Meta H1 的动态剩余时间工具实际调用，任务原文另存。大结果落盘组件有独立测试，但这 8 次自然运行中未触发，不声称其科学贡献。 |

整体工程回归：212 项 JavaScript 单元检查、462 项 Python 检查通过；94 项原生/隔离契约通过且无跳过，后加 MCP 自主恢复契约单独通过；knowledge/Studio 构建及依赖边界检查通过。历史契约的第一次失败来自固定 Runner 缺少 Meta 包、未构建 Studio 以及测试没有显式打开历史停止审查；修复测试环境与版本绑定后重跑，未放宽平台生产边界。

### 9.3 真实结果与身份

固定 Solver 为 openai-codex/gpt-6-sol/high，Meta 为 openai-codex/gpt-6-astra/xhigh；两个任务、两个候选、每格两次、正式并发 2，原生阶段时限不变。

| 候选 | hamlearn 两次官方分数 | shadow 两次官方分数 | 总通过 |
|---|---|---|---|
| H0 | 0、1 | 0、0 | 1/4 |
| Meta 编写 H1 | 1、1 | 1、1 | 4/4 |

H1 精确识别 PI_AI_ERROR / no healthy upstream，并复用原有限重试链；另加入候选自有 artifact-context 及剩余时间说明。两次 shadow 的真实日志共出现新增类别 3 次，均继续执行并评分，证明恢复路径实际发生。H1 合计记录 21 次请求恢复；不能将全部恢复都归于新增类别。大结果落盘未在正式任务自然触发；无消融、每格仅 n=2，也没有覆盖全部五任务的模型科学表现，不能宣称稳定提升或各组件独立贡献。

Meta 已自主保存最终报告 `report-116e33b9-03bd-4811-a3a8-b6611354ca42`、选定 H1 并完成导出。活动随后自动进入 `finished`，六项后台操作全部结束，验收驱动和最后一个 Meta 进程均已退出；没有通过直接修改数据库终结活动。最终状态、完整报告及评分元数据已归档至本地 `reports/development/meta-harness/execution-v3/`，独立验证包位于其 `deliveries/h1-standalone-verified.zip`。

- 活动：`campaign-057b92fd-5928-4cbe-90f2-4450441ba82f`。
- H0：`9047c17503af6c81c1edf2685d4d7ac0dc23d3a79452bd052107a6acf2c9ba1c`。
- H1：`0a9c960fd91404b0ebd56003f4704fc77ee3978cd4a5d523016326883efe6c2c`。
- 独立搬迁的新冻结版本：`be999a7bf33857368d63cac0fcb11e5786d0b1969d6ec15ed01f5782cf1dbb7d`，官方 1 分。保留 H1 源码摘要，重新构建并绑定最终适配器；构建产物和 bundle ID 明确变化，不混入原 8 次候选比较。
- 已实际执行 ZIP SHA-256：`f8580982b59d75db17576a2a7887d3e2767ab7fac3142977bec1822b66e54b6c`。

早期 smoke 中的协议启动、压缩请求、上游错误和诊断复制问题，以及初次构建/搬迁的失败原件均保留。搬迁初次因 namespace 未提供设备、第二次因本地 Podman 无法进入原 user namespace 而在模型调用前失败；使用正确设备挂载及显式远程容器客户端后通过，没有取消隐藏原仓库的验收条件。没有将这些失败冒充无事发生或混入/移出正式对照分母。

### 9.4 运行边界与交付使用

新源码默认只作用于新活动；本轮未热更新原生产后台或迁移其在途活动。更新部署须在维护窗口切换已验证源码并重建 UI，旧活动的冻结适配器/工具/候选仍按原绑定运行。

监督的轮询间隔是 0.5 秒，接收停止后先发 SIGTERM，10 秒后对 Harbor 进程组 SIGKILL；控制端超过 15 秒仍未退出则再次回收。容器引擎不可用时不能保证资源在这些时间内实际删除，所以状态必须保留未确认，不能只因发出信号声称清理完成。模型通道的本地原截止独立有效，数据库停顿不续期。

完整工程 check 是构建/完整性检查，不能泛化为所有任务的启动承诺；脚本、PTY、恢复、网络与正式评分由上述实际运行覆盖。HTTP/SSE 与五任务 rootless 范围是本次已验证边界，WebSocket 和其他任务环境须给出明确能力缺失，不静默改协议。参考模型保持完整候选，参考 Harness 的现有 CLI 预设仍明确使用原兼容契约，不与主 Solver 混算。

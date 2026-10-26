# 完整 Harness 工程开发

适用：`harbor-process-v1` / `meta-tools-v10`，仅新活动。旧活动仍按自己的冻结契约运行。默认工程在 `/work/plugins/h0`；复制后编辑新目录，既可沿用 DSH，也可更换框架。宿主不会加载候选源码读取声明。

`harness.json` 声明 `runContract: "harbor-process-v1"`、`entrypoint`（argv 数组，首项为产物相对路径）、`build.image`、`build.argv`、`build.locks`（工程内锁文件路径）。可附 framework、profile、plugins 展示信息和任意 runtimeConfig。候选自带语言运行时，例如模板将 Node 复制到 `runtime/node`；可调用任务已提供的语言，但必须在同类环境自行验证。平台不要求固定包名、工具名、依赖版本或 capability 枚举。

## 插件用途、机制与源码定位

在 `harness.json.plugins` 中声明每个插件的 `name`、`version`、工程相对 `path` 和组合 `config`，例如 `{"name":"deadline-context","version":"1.0.0","path":"plugins/deadline-context","config":{}}`。`path` 可指向源码目录或单个文件；目录下的 `plugin.json` 提供同名同版本的说明和相对目录的 `entry`。新插件应写清中文 `displayName`、`functionSummary`、`mechanism` 和多选 `categories`，含义见 [插件设计](plugin-design.md)。单文件插件或没有 `plugin.json` 时，可直接在工程的插件声明中提供这些阅读字段；目录清单的同名字段优先。

平台只静态读取已冻结的声明和源码，不加载插件。用途、分类和机制缺失会明确显示待补充，声明损坏或路径不可用会显示原因；这些信息不授予能力，也不作为执行策略白名单。插件目录下冻结文件的相对路径、内容和已记录的执行模式决定插件内容摘要；组合配置、加载顺序、工程共享依赖分别保留。没有源码位置时只能识别该候选内的声明，不能据名称和版本号认定源码相同。共享依赖仍须结合完整工程差异判断。

已有候选可从原冻结源码恢复阅读信息，不需重新冻结或复跑；说明是设计行为，效果仍由实验观察和证据说明。

## 构建与运行

构建在隔离容器 `/candidate` 内进行，允许真实依赖安装与安装脚本；没有宿主路径挂载、容器控制 socket、真实模型凭据、控制数据库或 verifier 输入。构建镜像解析为不可变 ID，源码、锁、命令、资源和产物摘要被记录。内部符号链接可展开；外部路径、特殊设备和逃逸链接不接受。容量和超时来自活动资源配置，不应以压缩代码规避。构建产物完整保存，不在正式任务中重新安装。

统一流程：

1. 原生文件/终端工具修改工程；候选本地策略测试由 Meta 选择。
2. `candidate_check({projectPath:"新目录",idempotencyKey:"..."})` 返回异步操作，查看完整 build.log。它验证隔离构建和入口存在，不调用真实模型，不替代行为测试。
3. `candidate_freeze({projectPath:"新目录",description:"改动及理由",parentId:"...",idempotencyKey:"..."})` 冻结内容；研究记录可选，测试不以报告为前置条件。相同输入复用构建，变化必须形成新身份。
4. `batch_submit` 指定候选、任务、重复次数，平台执行正式 Quantum Harbor 任务；没有强制先测 H0 或全部任务的顺序。资源计划须位于用户授权上限内。
5. `batch_status` / `evidence_list` / `results_compare` 读取评分、诊断和版本差异。完整工程源码可用 `candidate_read` 和材料查询读取。

启动发生在 Harbor main：入口路径 `/opt/harness/<entrypoint[0]>`，cwd `/app`，`PHYEXP_CONTEXT` 是 JSON 路径。上下文包含原始 instruction、workspace、mcpServers、deadline（Unix 秒）、outputDirectory、固定 solver、resources 和 modelChannel。模型通道包含 url、protocol、codexSubscription 与仅限本 Trial 的 token。候选自行决定如何呈现环境、组装提示、管理工具/上下文/压缩/重试/会话/辅助请求；原始任务仍可核对。不要把短期 token 放进源码或日志。HTTP/SSE 可用，WebSocket 当前不可用。

`run.mjs` / profile 与用户选择的插件均是普通候选文件。恢复使用 `plugins/<准确摘要>/`（模板内为 `plugins/request-recovery/`）中的普通插件；从 `plugins` 和 `runtimeConfig.plugins` 移除对应声明可禁用恢复；也可修改源码、换成自有插件、重命名 bash、使用持久终端/jobs、替换 MCP 客户端。候选内全部辅助调用仍绑定同一 Solver。失败的参数在真正工具执行前校验，反馈与恢复由候选负责；不要重放已完成副作用。没有固定请求次数、单会话或静态 tools 全集约束。

候选只能连接本任务侧车和模型通道，不能接触真实凭据、其他 Trial、宿主或私有 verifier 输入。到期、取消和退出由外部监督收回候选进程，评分按 Harbor 原生规则。`execution`、`officialResult`、`evidenceStatus`、`comparison` 分列：异常退出不抹掉有效评分，缺少可信官方文件保持 null；v4 主指标仍覆盖所有尝试。候选依赖/profile 是研究变量；任务镜像、平台适配、固定模型、资源和阶段时间是比较条件。

`export_create` 导出同一源码、构建产物、锁、入口和最小接入；不需要原仓库或控制数据库。静态校验、搬迁校验和真实评分分别记录。源码或依赖改变后重新冻结，不能修改导出后沿用原候选身份。

## 主动收尾

根据用户目标自主决定何时结束，调用 `campaign_finish`，提交非空 `reason`（结束理由）、`summary`（本次活动实验总结）和 `idempotencyKey`。总结建议说明已做工作、结果与结论、未解决问题和局限，采用自由文本，不需要固定结构。

平台保存决定，不审批理由是否充分，不要求 stabilityRule、成绩、重复次数、候选选择、证据列表或每轮/最终分析报告。受理后关闭新增实验并取消未启动项，在途工作在原截止和取消约定内结束并归集；不需要再回复或反复调用收尾。未知响应按原参数和幂等键核对，不能用新键覆盖原总结。活动结束不表示平台认证目标达成。

用户停止、截止或故障可能先关闭探索；仍能运行时可以提交理由与总结，无法取得总结时后台如实标记缺失。单独分析报告与版本选择按研究和交付需要提交，其接口要求不构成主动收尾门槛。旧活动沿用其冻结契约。

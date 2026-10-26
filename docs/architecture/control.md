# 控制后台

适用：当前新活动；历史记账与固定单次时限见[兼容规则](compatibility.md)。

## 状态与权限

[service.py](../../src/control/service.py)协调创建、环境准备、控制、候选、调度、Meta 和归集；[store.py](../../src/control/store.py)承担事务状态与幂等。用户、Meta 主会话、研究子会话及 Solver 的权限分别核验。UI 通过桥访问后台，不能直接操作数据库。

创建请求固定模型目录快照、任务配置与镜像来源、Meta 组合、SDK 资料包、执行/计分/资源/存储策略。幂等回放读取原绑定，不因当前目录或默认值改变而重新创建。创建后异步准备任务镜像、H0 工程及可选参考环境，准备完成才能开始计时。

活动从 draft 经 start 进入 running，可 pause/resume，停止或边界关闭探索后进入 closing，最终 finished/failed；删除另走持久 deleting 屏障。状态合法性以 Store 为准，页面超时不是状态转换依据。

## 资源计划与任务受理

新活动需要有限 `wallTimeSeconds` 与正整数 concurrency；maxRounds/maxTrials 可为 null。Meta 提交 parallelism 与 closeoutReserveSeconds，不能提高用户上限。两者与用户限制修订分别记录；已受理批次保存当时条件，运行任务不会因提高上限自动延期。

`benchmark-time-v1` 从任务配置读取阶段时限。计划不再包含 defaultTrialTimeSeconds，批次不接受 execution 覆盖或缩短条件。活动剩余时间不足时 `pendingTrials` 返回 requiredSeconds、availableSeconds、latestStartAt 和 canShorten=false。Meta 可撤回未启动项或由用户调整活动限制；不能偷偷缩短求解阶段。

新 process 活动不强制先跑 H0；普通流程在提交计划后由 Meta 选择任务、候选和次数。基线工程准备不消耗 Trial，也不表示基线评分完成。一次受理批次计一轮，计划尝试数为任务数乘重复次数；开始过的失败仍保留并计入对应尝试。正式提交与撤回有幂等身份，无自动整次补跑。

## 无用量账本的模型访问

新活动绑定 `control-only-v1`，拒绝 token 总量、收尾 token、费用硬限额及参考 token 子额度。API 用 `usage: {status: "not_collected"}` 表示未统计，报告和选择省略累计用量；原始回执可以保留，但不等于活动账本。

Meta/受控宿主的 `/model-access/{lease}` 只读检查租约、登记调用者、状态和截止，不预留或结算。暂时不可用/存储等待受取消与原截止约束，不能通过身份或协议失败放行。新 process Solver 使用[本地模型通道](execution.md#正式启动与模型通道)，无需每请求访问控制数据库。参考运行复用其受控宿主与活动限制。旧 `/accounting` 只服务绑定旧策略的活动。

## 暂停、停止与探索完成

暂停中断当前 Meta、停止新增 Trial 启动，已启动实验继续；墙钟不冻结。恢复核对工作身份与冻结资产，Meta 通过有记录的续接使用原文件和状态。用户停止取消未启动项并终止所属实验，剩余时间可用于分析与报告，不因停止启动新实验。

strict 截止停止剩余工作；drain 仅允许已经启动的任务在明确的额外期限内结束，不为新任务开放额外探索时间。

默认 `goal-or-budget-v1` 拒绝 exhausted 主动结束。stable 需用户预先提供 stabilityRule、当前选定候选的逐任务全部尝试满足规则、没有待定工作并有有效证据。默认自由文本目标没有数值认证门槛。旧独立停止审查不作为新活动默认路径。

## 数据库、归集与恢复

SQLite 使用 WAL；读快照不申请写锁，写事务先核验身份/修订。大文件生成、哈希与报告渲染在事务外，登记使用短事务；写锁只在 BEGIN 尚未成功时重试，不重放业务正文。数据库忙通过结构化错误表示，写响应未知时使用原参数、原幂等键核对。实现见[database.py](../../src/control/database.py)。

process 执行退出后进入 collecting 并释放执行名额；[collection.py](../../src/control/collection.py)用持久 collection_jobs、租约和独立进程分别核验结果、索引证据、生成系统摘要。当前核验并行上限 2，索引和摘要各 1。可信结果先发布，evidenceIndex 独立记录进度/失败；索引每批保存进度，重启恢复归集不重跑 Solver。失败次数有界，归集不能无限待定。

存储统计在后台巡检，查询返回 observedAt，不在每次轮询中扫描全目录。首次生成完整目录、报告事实和全文搜索仍需处理对应规模的材料；轻量状态延迟不代表完整读取性能。

完整会话恢复见[Meta](meta.md)，归档/删除见[证据与存储](evidence-storage.md)。核对测试：[控制状态](../../tests/unit/control_test.py)、[资源规划](../../tests/unit/resource_planning_test.py)、[模型访问](../../tests/unit/model_access_test.py)、[归集恢复](../../tests/unit/collection_workers_test.py)、[并发事务](../../tests/unit/database_concurrency_test.py)。

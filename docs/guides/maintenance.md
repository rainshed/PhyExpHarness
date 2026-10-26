# 维护与排障

适用：标准主线与本地受管数据。具体实例托管和外部存储操作由部署侧维护。

## 更新与备份

更新前核对在途活动、Trial、Meta 和后台归集。源码更新不自动替换已运行进程；维护窗口重建 `npm run build`，确认工作结束后更新后台及 UI 宿主。已有活动保留原冻结内容，采用新行为需新建活动。

完整备份在没有在途工作、后台退出后复制整个数据目录，包含 SQLite/WAL、campaigns、objects、artifacts、trials、evidence、reports、exports、资料包、私有配置及认证。不要只复制 control.sqlite 或单个候选目录。整库备份放在受管数据目录之外，按私有资料保护；独立备份不随单活动删除。

SQLite schema 9 报告引用需要匹配代码；回退先验证数据库和文件格式，不能将旧数据库覆盖到仍运行的数据目录。历史兼容见[兼容规则](../architecture/compatibility.md)。仓库中被忽略的 runs/reports/.runtime 仍可能含原始记录，不使用 `git clean -fdx` 清理。

## 故障定位

| 表现 | 优先核对 |
|---|---|
| 无法连接后台 | 进程、18402 端口、两端 PHYEXP_DATA_DIR/CONTROL_URL 和 user-token 来源 |
| 资料包身份错误 | npm ci / build:knowledge 是否完整；新活动使用新快照，旧活动保留原包 |
| 环境仍在准备 | 后台动态与 checks/task-images.log；H0 完成后可能仍在准备参考镜像 |
| Docker 不可连接 | 引擎、context、权限；连接故障不等于镜像缺失 |
| 固定镜像不存在 | 恢复准确镜像或原 context，不能用最新标签替代 |
| 剩余时间无法运行 | resourcePlanning.pendingTrials 的 required/available/latestStart；不能缩短 benchmark |
| 页面操作超时 | 刷新核对后台，保持原参数和幂等键，超时不表示操作取消 |
| 结果已出但证据不全 | backgroundWork / evidenceIndex；归集重试不重跑模型 |
| 数据库忙 | control_database_busy、retryAfterMs 和 control_transaction 日志；旧 accounting 错误只属于兼容路径 |
| 存储等待/写入失败 | 容量面板、observedAt、实际空闲空间和原始故障码 |
| 模型故障 | 区分候选恢复、模型服务/连接、平台控制与最终任务结果；诊断数量不是失败次数 |

后台错误在 supervisor-errors.jsonl；Trial 监督日志在 trials 下，各次 Harbor 的 phyexp 目录保存运行诊断；Meta 会话在 campaigns/<id>/meta-sessions。日志可能分段，按 segments 索引读取完整历史。真实凭据与原始日志不提交仓库。

## 存储保护与镜像准备

在容量面板调整常用阈值，完整策略由用户身份访问 GET `/storage`、POST/PUT `/storage/policy`。后台自动回收符合宽限与引用条件的无引用对象及旧缓存代际，保留当前依赖、冻结镜像和研究证据。不要在活动运行时手工删共享目录或 prune 使用中的镜像。

容量预测需要足够观测，重启后重新积累；有限磁盘不能保证任意长活动。工作区没有 OS 硬配额，处理紧急故障时保留已写内容与根因。原目录是硬链接视图时不能原地修改共享文件。

通常由创建流程准备任务镜像。需要预热或独立执行的锁文件时：

```sh
python3 scripts/prepare-task-images.py \
  --quantum-harbor /absolute/path/to/Quantum-Harbor \
  --all --cache /absolute/local-data/task-runtime-locks \
  --output /absolute/new-task-locks
```

单任务使用 --task TASK 和文件形式 --output。任务、镜像与配置摘要须一致；固定镜像不固定随机样本。维护命令不自动迁移旧活动。

## 永久删除一次活动

在活动「更多操作 → 删除活动…」核对名称、数量和依赖，有在途工作时选择「停止并永久删除」。未点击最终确认不会提交。核对/提交可能等待至 120 秒；已提交请求超时先刷新看后台状态。

受理后后台停止所属工作并持久清理，关闭页面不取消。失败保留活动和原因，处理后重试；全部完成才从列表移除。其他活动已纳入其证据/报告、混合备份、未知硬链接或无法确认归属会阻止删除。

共享资产仍有引用则保留，最后引用才回收。供应商凭据、公共依赖和镜像不属于单活动历史；外部下载和备份需由其所有者维护。此操作不可恢复运行，不承诺介质取证级擦除。接口与清理范围见[删除架构](../architecture/evidence-storage.md#永久删除)。

## 历史存储整理

用户明确要求整理已结束活动时，可先规划，再审阅计划并执行：

```sh
python3 scripts/migrate-history-storage.py plan \
  --data-dir /absolute/local-data \
  --session /absolute/local-data/development/history-storage-001
python3 scripts/migrate-history-storage.py apply \
  --session /absolute/local-data/development/history-storage-001
```

session 必须是新目录，按工具要求与对象存储位于同一文件系统。apply 保存备份、核验原身份并建立共享视图；异常后续做同一计划，不另建重复计划。排除未结束活动、在途进程和未知引用；不启动模型、不改原始评分/报告或镜像。

整理后原源码是硬链接视图，不能原地编辑。restore 使用同 session 和 `--bundle 完整摘要` 恢复独立源码文件，不覆盖整库。备份要包含对象、计划和 backups。该显式本地工具与日常自动 GC 是不同操作。

## 旧网关流的离线回放

对受支持的 gateway-audit.jsonl，可运行 `node scripts/replay-model-streams.mjs DATA_DIR OUTPUT_JSON [PRIOR_REPLAY_JSON]`。脚本使用记录的时间与 chunk、校验输入摘要，不读取凭据、不调用模型或容器。它分析固定宿主流保护，不能把结果当作所有新候选自定义恢复策略的行为证明，也不修改原评分。

## 插件库维护

历史补录、删除记录、重新导入及未知请求处理见[插件库指南](plugin-library.md)。删除来源活动不清除已独立入库的源码；删库版本也不改写活动冻结资产。备份完整数据目录时需一并保留 control.sqlite 中的库索引/补录任务/发布登记与 objects/sha256 内容。不要仅备份活动子目录，也不要手动删仍受引用保护的库对象。

# 容器运行与证据归档

本文件从保存基线 `7973de6` 的部署资料提取，适用于 `deploy/tensortrain2`。主线运行接口见[运行说明](../guides/quickstart.md)。本次拆分未连接服务器、切换服务或转换活动数据。

## 单 UID Podman 运行

`PHYEXP_CONTAINER_RUNTIME=podman-single-uid-v1` 支持工作台中的 5 个公开任务，可单选或组合创建活动：

| 工作台任务 | 任务 ID | 启用的模拟能力 |
|---|---|---|
| 10 比特 Hamiltonian 学习 | `time_budgeted_hamlearn_10q` | `hamiltonian_probe` |
| 60 比特 Shadow Surrogate | `time_budgeted_shadow_surrogate_60q` | `basis_shot_sampling`、`sealed_holdout_reveal` |
| 可调耦合器 CZ | `tunable_coupler_cz_netzero` | `basic_measurement`、`netzero_flux_control` |
| 逻辑 CNOT 解码器校准 | `logical_cnot_decoder_calibration` | `lattice_surgery_calibration` |
| H₂O 自适应测量 | `adaptive_clustered_clbcs_h2o` | `composite_measurement` |

这些任务提交数据，由独立 verifier 评分，均不启用仓库中另一个能力 `syndrome_feedback_control` 的 UID/GID 65534 控制器沙箱。单 UID 支持采用明确任务列表；新增任务或改变能力组合需要重新做兼容验证，不能通过关闭其沙箱来兼容。默认未设置时仍使用原 Docker 路径，已有活动不会自动迁移。

运行条件为 Linux 普通账户可创建 user namespace、cgroup v2 已委派 CPU/内存/进程数控制、本地可写镜像存储，以及部署到用户目录的 Podman、crun、conmon、网络辅助程序、catatonit 和依赖库。镜像存储不能放在 NFS。此策略不需要创建 subordinate UID/GID，也不安装系统服务或修改系统权限。

### 部署边界

- Podman API 仅通过当前用户可访问的 Unix socket 提供 Docker 兼容接口，不监听 TCP，不挂载进实验容器。工作台与控制后台仍绑定回环地址；本机浏览器通过 SSH 端口转发访问工作台。
- 使用专用 PATH 中的 `docker` 入口调用 [podman-single-uid.py](../../scripts/podman-single-uid.py)，不替换系统 Docker。运行命令使用 Podman 原生接口，以显式指定用户目录下的 init；Compose 等操作使用 Docker 客户端连接 Podman socket。
- `PHYEXP_PODMAN_CONFIG` 指向仓库外配置，字段包括 `policy`、`podman`、`dockerClient`、`dockerConfig`、`socket`、`signaturePolicy`、`work`、`init` 和 `fakeroot`。所有路径使用部署机器上的绝对路径；`fakeroot` 映射 Debian 的 `fakeroot-sysv`、`faked-sysv`、`libfakeroot-sysv.so` 三个文件。入口应自行设置配置路径，因为隔离 Runner 的宿主进程只继承白名单环境变量。
- Podman 的 `conmon_env_vars` 必须包含这些用户目录二进制需要的 PATH、动态库路径、容器配置路径及运行目录。缺失时清理子进程可能无法加载库，造成约 20 秒的退出等待；不能靠延长实验时限掩盖这个问题。
- Podman 4 的 systemd 健康检查只继承 PATH。用户目录安装需让其定时任务调用同一 Podman 启动入口，带回依赖库和存储配置；只对本部署的 `healthcheck run` 转换命令，保留原健康检查内容及间隔，并验证定时重复执行。
- Compose 启动等待由适配器读取真实运行状态：未定义健康检查的服务必须处于运行中，定义了健康检查的服务必须为 healthy；unhealthy、提前退出或等待超时均失败。此处理兼容 Podman 4 对 `HEALTHCHECK NONE` 返回空 Health 状态的差异。
- 新冻结适配器把任务 `environment.build_timeout_sec` 的剩余时间传给 Compose；创建、发现容器和健康等待共用此时间，不再另设 180 秒截断。未传时间的旧入口仍保留原默认值。Solver 与独立评分阶段的时间配置不变。
- `phyexp/environment-startup-agent.json` 和独立评分环境的 `environment-startup-verifier.json` 保存启动预算、耗时和阶段。Podman 等待期间持续保存状态变化及最近三次健康检查输出，即使外层超时取消也保留最后观测；未取得容器状态时不推测原因。环境超时、健康检查失败、提前退出和其他准备失败分别显示，原始官方评分不被覆盖。
- 控制后台选择此策略时，会验证原生 Podman 的 rootless 状态，并核对 Docker 兼容客户端与它使用同一个存储目录。服务和临时目录要保持当前用户独占；共享 home 上的用户服务应限制启动主机。

### 镜像与隔离

构建适配器从官方 Dockerfile 生成临时构建文件，保留任务源码、依赖声明、评分程序、文件模式和入口。文件属主以及镜像 USER 统一为容器 UID/GID 0，映射到普通宿主账户。Debian fakeroot 只用于构建时的文件属主操作，apt 在构建容器中使用单一身份；最终镜像恢复普通 shell 并移除构建辅助文件。它不赋予宿主 root，也不作为运行时沙箱。

Podman 4 不支持 Dockerfile 的逐条 `RUN --network=none`。对所有 RUN 都声明离线的构建，适配器改为整个构建使用 `--network=none`；混合策略会拒绝，不默默放开网络。镜像附带运行策略及原 Dockerfile 摘要标签，构建回执保存转换后的摘要、辅助文件摘要和结果镜像 ID。没有适配标签的镜像不能用于此策略。

任务镜像锁保存 `containerRuntime` 和实际不可变镜像 ID，Runner/Meta 缓存也按运行策略区分。Docker 与单 UID Podman 的镜像不是同一个执行环境，不直接混合比较结果。实验期间依然禁止重建或拉取冻结镜像。

Runner 保留无网络、只读根文件系统、精确挂载、清空 capabilities、禁止提权、系统调用过滤及 CPU/内存/进程数限制。main、qsim、独立 verifier 也清空 capabilities 并禁止提权；main/verifier 保留 Harbor 的有效 CPU、内存配置，未设置时限制为 2 CPU、4 GiB，qsim 为 4 CPU、8 GiB，均最多 256 个进程。具体而言，Shadow 的 main 保留 4 CPU，逻辑 CNOT 的 main 保留 6 GiB，不能被统一安全配置覆盖成较低额度。评分私有文件只进入 verifier，模型凭据仍由宿主网关持有。

qsim 在 Compose 覆盖层设置 `OPENBLAS_NUM_THREADS=4`、`OMP_NUM_THREADS=4`、`MKL_NUM_THREADS=4`，与 4 CPU 配额对应；任务原有环境变量继续合并，main/verifier 不注入这些值。此修改随新冻结执行版本生效；线程调度变化可能带来浮点舍入差异，需要数值容差检查，不承诺逐位一致。

Podman 4 的内部网络仍可能转发外部 DNS。此策略显式关闭该网络的 DNS，仅在 main 的 hosts 文件中固定本次 qsim 地址；移除 main 的其他网络后才提供任务工具。需要实测内部服务可达、外网 IP/宿主服务/外部 DNS 均不可达，不能只检查网络名称或配置标志。

单 UID 模式不能保持同一容器内多个 Unix 用户之间的文件权限隔离；这里依靠独立容器、挂载边界与权限限制保护所列 5 个任务。列表之外的任务、多节点调度、长期存储保留和高并发性能不属于本策略的完成承诺。用户目录中的容器运行时也需要定期维护升级。

### 验证与恢复

先构建并检查镜像，再运行 `tests/contracts/isolation.test.mjs` 以及官方任务的无模型执行/评分检查，通过后才启动有明确轮次、次数、时间和用量限制的真实活动。保留失败记录、构建回执、隔离探针、镜像身份、实际用量及浏览器结果；基础容器启动不代表实验闭环通过。

五任务验收入口为 `tests/smoke/harbor/public_tasks.py`。先用 Quantum-Harbor 自带的 `tools/build_qsim_images.py` 补齐全部 verifier，再在配置好专用容器入口的宿主环境执行：

```bash
python tests/smoke/harbor/public_tasks.py \
  --quantum-harbor /absolute/Quantum-Harbor \
  --cache /absolute/data/task-runtime-locks \
  --output /absolute/results/public-tasks-check
```

该检查使用新输出目录，最多并发 2 个任务，不调用模型。它通过正式 MCP 运行探针、提交固定测试答案，核对独立评分、冻结镜像、main 的网络与文件隔离、任务间容器/数据卷分离和清理；Shadow 还经过封存挑战与文件提交，H₂O 经过锁定方案的生产测量。测试答案用于验证链路，得分不代表 Solver 能力，技术验收通过也不要求科学得分为 1。原始失败和后续复查保存在各自输出目录，不能覆盖失败记录。

可单独用 `tests/smoke/harbor/environment_startup.py --quantum-harbor /absolute/Quantum-Harbor --lock /absolute/one-task-image-lock.json --output /absolute/new-startup-check --concurrency 3` 检查同一 Hamlearn 任务的三个并发环境。此入口消费已有镜像，验证健康状态、线程配置、镜像身份、容器/数据卷独立性和清理，不运行模型或评分器。该并发检查不能证明更高并发或长时间活动均稳定。

Harbor 0.18.0 上传证据时，`compose cp` 可能先报告 `lchown ... invalid argument`：宿主文件属主不在容器的单 UID 映射内。Harbor 原有的 tar 流后备上传可完成该操作，无需改写 Harbor；验收要核对后备上传成功、最终 Trial 无异常及独立评分原件，不能只忽略日志中的错误。

用户目录安装的 Podman 4 在保存镜像时也需要显式指定已有的签名策略文件，例如 `podman save --signature-policy /absolute/policy.json --multi-image-archive ...`；这是 `save` 子命令参数。备份应包含实际冻结镜像，校验压缩包与镜像配置摘要，并通过 SQLite backup API 保存在线数据库。归档可读性检查不等于已经完成整机重启恢复演练。

服务可使用 systemd 用户服务持久运行，工作台关闭不应终止实验。SSH 转发应只绑定本机回环地址。数据和镜像位于临时磁盘时必须另做受保护备份；自动清理策略、重启恢复与持久磁盘位置需按具体节点确认。

### 可选 NFS 证据归档

宿主可通过 `scripts/archive-evidence.py` 管理独立归档策略。执行前确认本地数据与远端目录权限、共享空间预算、生产者状态，并备份活动配置和数据库。不要把活跃 SQLite WAL、Podman 镜像或整个 `data/` 移到 NFS。配置文件保存在仓库外；例如：

```json
{"version":1,"enabled":true,"evict":false,"root":"/your-writable-nfs/PhyExpHarness/archive","instance":"node-2","bytesPerSecond":33554432,"maxBytes":214748364800,"minFreeBytes":10737418240,"localReserveBytes":2147483648,"cacheSeconds":3600,"minObjectBytes":65536,"lockTimeoutSeconds":5,"restoreTimeoutSeconds":30}
```

```bash
python scripts/archive-evidence.py --data /local/data configure /private/archive-policy.json
python scripts/archive-evidence.py --data /local/data run
python scripts/archive-evidence.py --data /local/data status
python scripts/archive-evidence.py --data /local/data restore trials/launch-id
```

首次先使用 `evict:false` 复制、读回验证，确认跨盘恢复和原始摘要一致后改为 `evict:true`。后台每分钟尝试一轮；已有归档任务时不重复启动。配置由后台每轮重新读取，无需再次重启。每个对象保存为 `<root>/<instance>/objects/<前两位>/<sha>.gz`，同名 `.json` 是路径和归属回执。本地 `archive-index.sqlite` 保存定位；维护备份须同时保存控制数据库、归档索引和策略，整库备份置于受管数据目录之外。归档及独立维护备份是两个范围，单活动删除不会同步删除独立备份。

`GET /storage` 和活动存储面板显示归档对象数、压缩后大小、状态和最近错误。原始证据的 API、材料、历史来源纳入和文件视图会按需恢复；归集重放恢复原始路径后核验。恢复有本地容量预留及超时，失败不会提供部分正文。完整清单与官方结果留在本地；运行中的写入、会话文件、活动会话已获得的文件视图不回收。原生脚本直接读主机历史目录前，先使用 `restore`。已发布的活动内路径继续可用。

需要回退时先将策略设为 `enabled:false`、`evict:false`，确认后台归档进程结束，再执行 `restore-all` 并核验原路径/摘要，之后才可切回不支持归档的旧程序。禁用归档本身不会自动恢复正文。不可直接修改既有策略的 `root/instance`；远端故障时保留定位与本地有效文件并修复连接。NFS 共享空闲量不等于个人配额，本方案也不保证持续增长的数据能无限运行。

容量等待的本机 NDJSON 网关在新冻结运行时中立即发送响应头，并每 15 秒发送一次保活帧；消费者忽略保活帧。该行为避免等待期间被 HTTP 响应头/空闲超时误取消，不改变截止时间、实际取消或模型设置。

2026-10-25：TensorTrain 2 的 control/workbench 已切换至独立发布 `fd0465b`，归档在后台独立进程运行。实际跨文件系统校验、历史原件恢复和同设置新活动启动已验证；旧活动的冻结配置与结果未替换。完整实验结果及持续容量增长仍须按活动实际进展判断。

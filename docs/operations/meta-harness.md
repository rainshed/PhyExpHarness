# Meta-Harness 运行与恢复

## 完整执行工程（新活动默认）

新活动默认冻结 `harness-composition-v3`，运行契约为 `harbor-process-v1`，Meta 工具/系统模板为 v9/v11。升级后重建工作台并在维护窗口重启后台；已运行活动继续使用原冻结实现，不热替换适配器、模型或任务。旧 v1/v2 仍可读取、执行与导出，不能把新旧链路的成绩当作同条件对照。

Meta 在 `/work/plugins/h0` 获得普通完整基线，可复制到其他目录，修改入口、框架、profile、依赖及恢复。对工程调用 candidate_check / candidate_freeze 的 `projectPath`，然后使用原 batch_submit / batch_status / evidence / results_compare / export_create。不需要先覆盖全部 H0 任务、提交研究引用或申请某种执行算法。check 只表示隔离构建及入口存在性通过，正式启动与评分以 Trial 为准。

外部容量来自 `schemas/execution/process-resources.json`，冻结到活动和配方：构建默认 2 CPU、4 GiB、256 PID、600 秒、产物 1 GiB；模型代理默认 1 CPU、512 MiB、64 PID、单请求解压后 64 MiB。它们不是 token 预算或执行策略。任务 main/qsim 使用 benchmark 与宿主兼容层资源，并记录实际 HostConfig。Rootless 单 UID 目前仅验证五个公开数据提交任务，不能据此声称支持需要其他 UID、特殊服务或自定义环境的任务。

构建联网取得精确依赖并允许运行安装脚本；候选执行时 main 只连接任务 qsim 和专属模型通道。真实凭据不进候选。通道支持原生 Responses（含 compact）、Chat Completions、Anthropic HTTP/SSE，支持常用压缩请求，暂不支持 WebSocket。不同工具清单、辅助会话与内部重试共用通道，无额外许可。

停止由独立监督收回本次 main、qsim、模型代理及网络；候选子进程使用 main 的私有 PID 空间。控制数据库暂时不可用不会阻断每个模型请求。已经送达监督端的停止会终止在途请求；未送达时不能报告停止完成，原 benchmark 截止仍由本地通道执行。源码更新不得改变在途 Trial 身份。

结果 `execution` / `officialResult` / `evidenceStatus` / `comparison` 分别保存。非零退出不阻止已产生的官方分数；诊断附件损坏不抹掉可信官方分数；官方文件损坏或归属错误则不报告可信得分。重复收集不重跑模型。导出使用包内 README 和 run.py；Python 按 requirements.lock 安装，模型与 Quantum-Harbor 是显式外部配置，不需要原仓库或活动数据。

完整契约的 Meta 镜像需包含当前原生依赖与历史工具测试依赖，可用 `python3 tests/contracts/prepare-meta-image.py --output /absolute/fixture-images` 准备，令 `PHYEXP_META_TEST_IMAGE` 指向返回的不可变镜像。参考 CLI 测试需将 `PHYEXP_REFERENCE_IMAGES` 指向已有准备回执；不会使用真实模型。先 `npm run build`，再运行完整契约，避免把未构建 UI 或旧 Solver 镜像当作 Meta 环境。

验收入口与证据范围见[重构计划](../plans/execution-harness-refactor.md)。实际运行记录保留在本地 `reports/development/meta-harness/execution-v3/`；测试夹具的官方 0 分用于验证接入，不能计入真实模型策略比较。

当前新活动已移除用量账本、消耗统计及 token 预算。重建工作台并在维护更新后台后新建活动生效；已运行进程和旧冻结活动保持原协议，历史记录不清理。范围与兼容边界见[移除方案](../design/model-access-without-accounting.md)。

本文说明平台的安装、构建、运行与恢复；产品目标见 [README](../../README.md)。

## 当前状态与限制

2026-10-23 已实现[参考模型与参考 Harness 两插件方案](../design/meta-reference-experiments.md)，使用方式、适配范围和验证边界见本文末尾“参考实验插件”。参考模型读取 DeepSeek Harness 原生配置，参考 Harness 可选 Codex、Claude Code 和 DeepSeek 标准模式；这不改变下文的主线 Solver/Meta 模型配置入口。

平台仍在开发中。完整故障恢复、工作台生命周期覆盖、干净环境安装与实际导出包的真实独立运行验收仍需补齐；不能据此声明稳定性能提升或跨任务泛化。

平台运行、模型生成插件和导出包真实独立验收分别记录在本地。安装源码不包含历史活动和验收结果，具体活动证据不能由源码版本或离线检查替代。认证续期和用量软阈值的限制见下文。

新建活动使用[插件版本管理与按需导出方案](../design/plugin-versioning-and-export.md)：候选保存小型组合清单和配置，插件、必要适配及锁文件按内容共享；DeepSeek 只保存准确版本引用，安装依赖复用共享缓存。旧 v1 Bundle 继续按原格式读取、运行和导出，不自动转换活动或清理历史。

2026-10-21 已实现 [Meta 通用 Agent 与完整证据访问](../design/meta-agent-and-evidence.md)的核心运行链路。新活动默认绑定 `meta-composition-v2`：六个原生领域插件叠加文件、搜索、编辑、终端、jobs、待办、技能、会话查询与压缩，支持普通研究委派及独立容器中的停止审查。启动只提供导航，完整评分、轨迹、分析和终端输出从只读路径读取；工作文件与原生会话跨 Runner 重启保留。原 `meta-composition-v1` 活动仍按原资产和原语义运行。

当前工程检查使用本地脚本 provider 和真实隔离 Runner；不代表真实模型的研究质量，也不代表完整故障矩阵全部验收。原生压缩后的长历史查询、所有通知崩溃窗口及并发恢复的压力检查仍需扩展。开发区使用宿主文件系统容量，尚无独立磁盘配额；输出捕获器另有明确上限。网络、外部 MCP 和开发依赖范围见下方能力说明。

## 启动工作台

需要 Node.js 24.13+、Python 3.13、Docker、Harbor 0.18.0，以及显式指定的 Quantum-Harbor checkout。平台使用锁定的 DeepSeek Harness 0.2.1-rc.2。

没有 sudo 的 Linux 节点可使用下方的[单 UID Podman 运行](#单-uid-podman-运行)。它是显式选择的有限兼容策略，不代表所有任务已支持 Podman。

```sh
npm ci
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-control.txt
python -m pip install --require-hashes -r templates/standalone/requirements.lock
npm run build
npm test
python -m src.control.server --quantum-harbor /absolute/path/to/Quantum-Harbor
```

`npm run build` 先从锁文件对应的已安装 SDK、资料源文件和执行资产生成 `knowledge/plugin-sdk/reference/`，再按 UI 清单生成各 UI 的 `lib/client.js`，当前为 `packages/meta-workbench-studio/lib/client.js`。这些生成目录均不提交；不要从其他活动的冻结资料包复制文件来补齐。更新依赖、资料或工作台源码后，在启动前重新构建。直接运行 Python 检查或 H0 入口前也须完成该步骤；`npm test` 会自动重建资料包。

另开一个终端，在本项目目录运行：

```sh
node scripts/workbench.mjs
```

使用终端输出的启动链接完成本机登录，之后可访问 `http://127.0.0.1:18401`。在 DeepSeek 侧栏选择「研究工作台」（φ，Studio）。宿主的首次账号提示可关闭；进化工作台使用独立后台管理模型。通过「供应商与模型」入口配置，或从新建活动的「管理供应商与模型」进入。Codex 订阅沿用宿主登录；API Key 可在此页面保存，也可继续使用后台环境变量。不要将进化活动的配置填入 DeepSeek 宿主自己的模型设置页。

默认控制服务为 `127.0.0.1:18402`，只监听本机。默认数据目录在 macOS 为 `~/Library/Application Support/PhyExpHarness/`，应使用仓库外、非同步的本地目录。自定义位置时，两个终端都设置同一个 `PHYEXP_DATA_DIR`；后台也支持 `--data-dir`。工作台启动器从该目录读取仅当前用户可读的 `user-token`，不会把它放进浏览器。可用 `PHYEXP_CONTROL_URL`、`PHYEXP_UI_PORT`、`PHYEXP_UI_HOME` 指定连接和 UI 宿主位置。

不要在同一数据目录启动第二个后台。服务用文件锁保证单一所有者。更换数据目录等于打开另一组活动，不会迁移或删除旧数据。

### UI 版本选择与维护

默认只加载 Studio 和独立 API 桥。经典 UI 已移除，公共客户端位于 `packages/meta-workbench-client/`。版本清单为 `profiles/meta-workbench/uis.json`，包含默认版本和各 UI 对应的包；通用规则见[UI 模块化设计](../design/meta-workbench-modularity.md)，Studio 页面见[设计文档](../design/meta-workbench-studio.md)。

Studio 的主要入口为「进化概览」「版本对比」「实验记录」「研究报告」「插件与动机」。成功率按版本与任务展示，保留分母、覆盖及可比较性说明；报告与证据继续使用历史快照。

```sh
# 构建清单中的全部 UI（当前只有 Studio）
npm run build:workbench
# 按清单默认版本启动
node scripts/workbench.mjs
# 仅构建或启动指定版本
PHYEXP_UI_VARIANT=studio npm run build:workbench
PHYEXP_UI_VARIANT=studio node scripts/workbench.mjs
# 加载清单中全部版本
PHYEXP_UI_VARIANT=all node scripts/workbench.mjs
```

新增版本后可用逗号分隔清单内 ID 选择多个版本。旧 `both` 值兼容为 `all`；`classic` 已无对应包，会明确报错。构建不设置选择变量时构建全部版本，启动不设置时使用清单的 `default`。宿主导航只注册实际加载的面板，Studio 不再含硬编码的经典界面按钮。

更改装配前关闭对应 UI 宿主，再以相同 UI 目录启动；不需要停止控制后台。客户端源码变化后重新构建，再重新加载插件或重启 UI 宿主。已运行的旧宿主不会自动采用新的插件清单，不能仅凭文件修改认定已经切换。

包名 profile 须安装 `@phyexp/meta-workbench-bridge` 和选中的 UI 包，公共客户端作为 UI 的构建依赖。示例见 `profiles/meta-workbench/cordis.patch.yml`。新增 UI 时声明独立包入口和 `phyexpWorkbench.kind: "ui"`，加入清单、选择默认版本后构建；移除时删除该包与清单项及依赖，默认版本必须仍有效。依赖与增删检查会拒绝具体 UI 相互引用。

Studio 首次加载将旧草稿、活动选择与待重试创建身份复制到本版存储记录，保留旧键；以后使用自己的命名空间。其他 UI 的状态默认隔离，草稿共享需要明确的兼容或导入。未保存供应商设置须先保存或取消，密钥草稿不跨面板保存。卸载只释放本版读取和监听，桥与后台独立存活。

### 使用 Tailscale 从手机访问

电脑和手机连接同一 Tailscale 网络后，可用 Tailscale Serve 将 HTTPS 入口代理到工作台的 `127.0.0.1:18401`。UI 和控制后台仍绑定回环地址，不开放控制端口。远程入口的访问范围由 Tailscale 网络策略决定；浏览器还必须完成 dsh 宿主认证。工作台的 `/phyexp/api` 接口复用宿主的会话和可信域名校验，不能只凭同源请求操作后台。

将以下配置保存为 UI 宿主目录下的 `workbench-access.json`（默认位于数据目录的 `ui/`），替换为电脑实际的 Tailscale DNS 名称：

```json
{"publicUrl":"https://your-computer.your-tailnet.ts.net:18443/"}
```

重新启动 UI：`node scripts/workbench.mjs`。启动器只信任配置中的准确域名与端口；也可用 `PHYEXP_UI_PUBLIC_URL` 覆盖文件配置，空字符串表示禁用远程域名配置。只接受无路径、查询参数、凭据和 fragment 的 HTTPS 根地址。只重启 UI 不停止控制后台或实验。

随后添加独立入口（先检查该端口没有其他 Serve 服务）：

```sh
tailscale serve --bg --https=18443 http://127.0.0.1:18401
```

手机首次打开启动终端打印的完整 HTTPS 登录链接（带 `token`），宿主会写入浏览器会话并跳转到不带令牌的地址；以后收藏干净地址即可。该链接授予此 UI 宿主的访问权，只通过可信渠道传给自己的设备，不写入仓库或公开文档。宿主重启后生成新的启动令牌，已有有效浏览器会话由同一 UI 数据目录保留。默认首屏从侧栏选择「研究工作台」（Studio）。

手机使用完整浏览器打开 HTTPS 启动链接。若聊天应用把链接转成「文件预览」，长按复制链接后粘贴到 Chrome 等浏览器的地址栏；文件预览的抓取器可能不保留登录跳转的会话 Cookie，从而得到 401 或抓取异常。`127.0.0.1` 仅用于工作台所在电脑，不能作为手机浏览器的访问地址。

使用 Serve 的私有网络模式，不启用 Funnel。电脑需保持联网、唤醒且 UI 与后台进程运行；本配置不负责开机自启。关闭此入口用 `tailscale serve --https=18443 off`，不使用会清除其他转发的 `reset`。远程入口撤销后可删除配置文件中的 `publicUrl` 并重启 UI。

若 HTTPS 直连成功而浏览器显示连接被关闭，检查系统或浏览器代理是否接管了 Tailscale 域名。将工作台的准确域名加入代理绕过列表并保留原有条目，让该地址走 Tailscale；不要关闭浏览器认证或证书校验。手机也需保持 Tailscale 已连接。

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

## 检查与实验入口

实际命令以根目录 [package.json](../../package.json) 为准。先完成上面的依赖安装与构建，再按需要执行：

| 命令 | 用途与资源 |
|---|---|
| `npm test` | 自动生成 SDK 资料包后执行离线单元检查，不调用模型 |
| `npm run test:contracts` | 原生契约与隔离检查；部分需要 Docker，使用假 provider，不调用真实模型 |
| `python3 scripts/check-boundaries.py` | 检查模块依赖边界 |
| `npm run smoke:harbor -- --quantum-harbor /path/to/Quantum-Harbor` | Docker/Harbor 无模型环境检查，使用 `nop` |
| `npm run smoke:luna` | 真实模型连通性检查，固定 Luna 配置 |
| `npm run h0 -- --quantum-harbor /path/to/Quantum-Harbor` | 按默认 Sol 配方运行一个真实 H0 Trial |

真实调用前确认模型配置、授权和预算。`recipes/` 与 `experiments/` 保存可复用配置，不包含某次运行结果。旧批次入口 `python3 src/integrations/quantum_harbor/batch.py` 同样会启动真实实验。

## H0 配方与工具约定

H0 使用 `sdk-minimal` 原生循环和上下文压缩，默认配方为 [gpt-6-sol / medium](../../recipes/h0-sol.json)。任务原文与公开环境信息交给 Solver，不追加科学算法提示、答案修复或失败后追问。[Luna 配方](../../recipes/h0-luna.json)与对应计划保留供显式选择。

模型凭据与审计留在固定宿主，生成插件在无外网 Runner 中运行。Harbor `main` 中的每条 bash 命令从 `/app` 的新 shell 开始：文件保留，shell 变量与当前目录不保留。qsim 通过原生 MCP 工具提供实验能力，评分由官方 verifier 产生。平台保留失败与官方未评分记录；新 H0 v3 内置统一异常恢复组合，覆盖连接重试、异常响应重新生成及完整工具参数错误反馈；不重跑整个 Trial。派生任务完成分按活动绑定规则计算。架构边界见[实现方案](../design/meta-harness-implementation.md)。

## 创建和运行

新建活动时选择两模型与开发任务，额度页先填写总运行小时数与最高并发，再按需设置轮次、实验总数与用量上限。轮次、实验总数和用量可不限；页面显示当前任务所需的最低基线实验次数。单次时限和收尾留空时由 Meta 规划，不再自动扣固定比例预留。高级设置中填写的单次时限是上限，收尾值是最低预留。创建时自动准备所选任务的固定镜像，再做基线冻结和无模型装配检查；点击「启动进化」开始计时，Meta 先提交运行计划，后台再受理 H0 基线。

启动受理前会核验固定任务镜像、参考实验环境及模型端点，较慢的容器引擎可能使检查超过 20 秒。工作台对活动控制请求等待最多 120 秒，期间显示正在检查并启动或恢复；普通读取仍等待最多 20 秒。页面超时不会取消后台操作，也不能据此认定启动失败。若显示“操作结果尚未确认”，先刷新确认活动状态；已经运行时不要重复启动或另建活动。旧版的 `The operation was aborted due to timeout` 也应先按此方式核对。

基线及候选装配检查从冻结配方的模型路由读取支持的推理强度，保留用户所选档位；非推理模型不注入推理选项。检查仅使用模拟响应，不读取模型凭据或调用真实模型。回归入口为 `node --test tests/contracts/assembly.test.mjs`，需要 Docker 及匹配依赖锁的 Runner 镜像。修复前因推理强度声明不匹配而失败的准备记录会保留，更新后新建活动使用修复后的检查。

参数只能直接输入或通过右侧上下按钮调整，滚轮及键盘上下键不会更改数值。未提交配置保存在当前浏览器，切换面板或刷新后仍可继续填写。选择的任务数不能超过实验次数上限：每个任务的 H0 至少占一次；不一致时，创建按钮附近会说明原因并保留配置。提交期间显示进度并阻止重复点击。同配置失败重试或刷新后重试沿用原创建请求，避免响应丢失造成重复活动；修改配置则成为新请求。

一次受理的批次计一轮；任务数乘重复次数是计划实验次数。开始过的失败也占次数，没有自动重试。工具查询、代码检查和未通过的候选装配不消耗实验次数；Meta 模型请求仍受活动截止时间约束。

新活动默认采用 `meta-selection-v1`：由 Meta 主动选择、维持或回退已通过装配检查的冻结版本，平台不再自动将首个有评分版本设为参考。Meta 提交选择理由、证据引用、性能/可靠性/成本取舍、自述局限和重新考虑的条件。平台核验候选内容身份与本活动证据摘要，保存每次决定及此前版本，并展示全部尝试、逐任务均分、有效评分完成率与比较限制。缺分、在途试验、镜像差异和指标退步只提示，不否决选择；未评分仍为 null，不填零，失败不删除。无评分的基线也可有依据地选定。未主动选择时显示“尚未选择”，不自动兜底。

工作台与报告中的“Meta 版本选择与依据”分别展示模型判断与平台比较限制，提供原始证据入口。决策快照包含当时的所有相关尝试、证据 ID/摘要、耗时及决策链；后续实验或再次选择只追加新记录，不改写旧决定。选定表示 Meta 的取舍，不代表平台认证稳定性、因果收益或泛化；环境身份不同也不等于已证明物理环境发生变化。

已有活动继续沿用其创建时绑定的 v1/v2 规则和历史选择；修改预算、重启后台或部署本次更新均不升级旧活动，也不自动将旧 H3 改为保留版本。需要使用自主选择规则时创建新活动。已结束活动的最终选择仍被冻结。任务镜像按下文的独立准备流程固定；版本选择规则与镜像准备分别记录。

新活动不统计 token 或费用，也不提供 token 总量停止能力；继续执行时间、次数、并发和存储限制。模型原始回执可随轨迹保留，缺少 usage 不阻止后续调用或结果归档。

「暂停新工作」中断 Meta 当前会话并停止新实验启动，已启动实验继续。墙钟继续走。恢复先读取活动状态和已有进程，Meta 用明确记录的新会话继承工作区、候选、证据和预算。关闭网页、卸载工作台插件或退出 UI 宿主不会停止后台。

「停止并收尾」关闭探索，取消尚未开始的名额，并终止正在执行的实验。Meta 在剩余时间和收尾额度内分析现有证据；如果模型不可用，系统保留事实摘要并标注分析未完成。

调整上限只对用户开放；已消耗计数不重置，已启动实验和请求保留原有时限。已结束活动不会因此复活。严格截止终止剩余工作；有限收尾模式只允许已经启动的实验在明确的额外时限内结束。

## Meta 目标与资料查询

新活动空白目标回退为持续改进目标；自定义目标保留，每次新 Meta 会话重新注入。已创建活动的目标不追溯替换。当前未预设数值稳定门槛。自由文本目标不会自动变成机器核验规则；目标达成申请仍需要用户提供 stabilityRule，没有规则时继续研究至额度上限，用户仍可主动停止。

Meta 可通过 materials_list/search/read 按需读取允许的任务原文、SDK、冻结插件与版本、实验、证据和历史报告。新活动保存任务原文快照并绑定资料包，旧活动读取原归档；缺失材料明确不可用。原始日志和报告仍保留，查询不启动实验。新会话的 context.json 记录实际系统提示词及摘要，旧会话输入保持原样。

当前分页能继续读取已发布材料，但不能找回发布前被评分字段白名单或轨迹事件筛选排除的内容。通用 Agent 方案将补充原件路径与完整输出入口；实施前不应根据 Meta 可见的简短反馈认定官方报告缺少诊断。

插件教程源文件位于 `knowledge/plugin-sdk/guides/`，Meta 通过 `sdk_read` 的 `id: "guides/README.md"` 读取索引。修改后运行 `npm run build:knowledge`；新建活动会重新读取并完整校验当前资料，原子归档后才保存活动，无需仅因资料更新而重启控制后台。已有活动与创建请求回放继续使用原归档。构建期间读到不完整资料会明确拒绝，此次不创建活动，完成构建后可直接重试。旧资料包没有教程入口时可读取 `overview`。子代理教程仅说明接口与接入前提，不启用执行能力。

旧版后台在启动后重建资料可能出现 `Knowledge pack identity mismatch`：升级并重启后台后再新建；先确认没有运行中的活动，或按正常恢复流程安排重启。旧版失败请求可能已留下未启动草稿，其资料身份不能直接替换成当前版本；保留记录，已有实验仍按原资料读取。不要通过修改摘要、忽略完整性检查或复制另一版本的文件来绕过此错误。

## 资源计划与准入诊断

新活动使用 `meta-resource-planning-v1`。Studio 的“资源计划与实际条件”视图，展示来源、计划版本、有效并发及运行任务启动时条件；用户可填写理由覆盖计划。Meta 使用 `campaign_plan_update` 调整未来批次的资源分配，已受理批次保持快照。未指定的 token 上限保持不限；总 token 包含缓存用量，持续如实计量。

单次时长包含启动、Solver、官方评分和清理。执行层原有的固定评分与清理预留为 330 秒，由 `executionTimePolicy` 公开；计划和批次不能分配不大于该预留的时长，启动还会占用部分时间。工作台同时解释这项执行条件与 Meta 活动收尾预留的区别，运行条件保存整次截止和 Solver 截止。计划预留或 token 容量阻止待执行任务启动时，后台发送明确通知；次数上限关闭新批次后，已有任务的计划仍可调整。

用户提高活动上限时，已启动进程不会自动获得延期或提高启动时 token 上限；界面显示这些任务的实际条件。待启动任务因排队需要缩短时间时，Meta 通过 `trial_conditions_accept` 明确接受，实际分配进入比较记录。严格结束与有限延时收尾分别执行，不用较早的启动截止覆盖已允许的额外执行时间。

准入审计区分等待、拒绝与模型调用。`budget_inflight_wait` 等待在途结算，`budget_plan_wait` 提醒 Meta 调整预留；二者不会自动重试模型。`budget_admission_denied` 表示余额无法满足准入估算，不能理解为实际消耗已精确到达总量。账本不可用、凭证过期和协议异常分别保留平台原因。新活动的 `task-completion-v4` 将执行中发生并最终结束的这些故障计失败，尚未执行的拒绝单列；已有 v3 保留原分类，不改写历史或官方空值。

以下记账诊断只适用于旧冻结活动。`accounting_unavailable` 表示宿主未及时取得账本响应，不表示实际 token 加法出错。数据库写锁竞争、后台繁忙或连接中断都可能触发；检查后台的 `database is locked`、网关的 `admission_waiting` / `settlement_pending` 及请求编号。修复后的网关保留每次 HTTP 请求 10 秒超时，但在原任务截止前以同一编号退避重试准入；等待不调用模型、不释放已占用的本地预留、不增加实验次数。后台 SQLite 忙返回 503。认证失败、协议错误、明确额度拒绝、取消及截止仍保持原边界。

未设置 token 总上限时，准入不再遍历用量历史汇总总量，也不将全量统计复制到每条准入记录；仅保留请求和结算回执，状态查询及报告按需汇总。幂等准入通过请求主键查找。若参考实验另有 token 子限额，仍检查其额度；不能因为总上限为空就跳过子限额。

结算响应丢失时保留已落盘回执和待结算项，下一次准入前补交同一回执；本地用量只累计一次，进程结束后后台还会按宿主审计对账。若超时前后台已保存预留，旧逻辑可能将其显示为未知预留；这是保守占用而非确认消耗。只有宿主审计明确记录 `admission_denied`，且同一编号没有模型请求或结算记录时，才允许按“未调用模型”结算为零；缺少日志、模型中断或用量不完整仍保留未知。已结束实验的结果和冻结报告不因此重算。

网关修复随新的冻结执行/Meta 组合生效；后台对账修复在正常维护更新后生效。排查期间保留在途进程和冻结资产，不通过暂停活动、重启任务、替换旧组合文件或清空账本来消除提示。既有未知预留应依据完整宿主审计单独核验，不能批量当作零消耗。

后端接口、兼容和验收见[专项计划](../plans/meta-resource-planning.md)，Meta 参数示例见[资源规划资料](../../knowledge/plugin-sdk/guides/resource-planning.md)。旧活动继续使用冻结时规则。实时延期与动态 token 预留估计尚未实现。

## 网络与认证

模型调用由固定宿主执行，隔离 Runner 没有外网、登录文件或平台令牌。宿主启用已配置的 HTTP(S) 代理，控制/工具的本机连接绕过代理。首次启动活动前用不带认证的 HEAD 请求检查网络可达性，不调用模型、不占实验名额。可达性检查通过不代表模型调用一定成功。

认证读取 `~/.codex/auth.json`，也可通过 `PHYEXP_CODEX_AUTH_FILE` 指定。只复制当前有效 access token 到短期 0600 文件；不复制 refresh token，也不修改原登录文件。失效时由用户正常更新 Codex 登录，再启动新的活动；平台不自动换模型或免费重试。

### 配置供应商与模型目录

不指定配置文件时，保留现有三个 GPT 订阅模型及 DeepSeek V4.1 Flash 1017；默认仍为 Solver `gpt-6-sol / medium`、Meta `gpt-6-astra / medium`。自定义文件只需列出新增或修改的供应商；内置选项按 provider 和 model id 合并保留。部署文件在后台启动时读取一次，手工修改文件后需要重启后台。UI 保存立即更新目录，无需重启；既有活动不追溯更新。

工作台中的完整流程：

1. 打开「供应商与模型」，选择已有连接或「添加供应商」。填写固定供应商 ID、显示名称、端点和 API 协议，添加模型 ID。内置 Codex 的登录方式和订阅端点不可更改。
2. 输入 API Key 并保存；留空保留已保存的密钥，否则使用后台环境变量。保存后输入框清空，不回显已有密钥。自定义连接自动使用 `PHYEXP_PROVIDER_<ID>_API_KEY` 引用，连字符转下划线。
3. 展开模型能力配置上下文、最大输出、文字/图片输入、推理等级及默认值；通用协议还可编辑等级映射和经过 schema 校验的协议兼容 JSON。未编辑的版本和模型兼容字段保留。第一版手动管理目录，不自动查询远端模型列表。
4. 保存后可选择模型和推理等级执行「测试调用」。最多两次固定诊断请求，验证流式响应、固定工具参数、工具结果回传与用量回执；总调用时限 45 秒，每次输出参数最多 512 token，不承诺远端费用硬上限。会产生实际模型费用；测试不创建实验，不占活动额度，结果和已知/未知用量单独留存。认证失败、超时或重启不自动重试。仅地址可达或已配置密钥不表示测试通过。
5. 返回原活动草稿，从更新后的目录分别选择 Solver 与 Meta；无推理模型不显示推理强度。创建时保存目录修订和完整路由快照。后续更改端点、模型能力、移除目录项或停用供应商不会改变既有活动。重复提交同一创建请求也沿用首次快照。

控制后台将 UI 配置、凭据和诊断记录保存在数据目录下的 `provider-settings.sqlite`（0600，数据目录 0700）。配置与凭据使用独立表，保存事务同时提交；配置查询、测试结果、活动、Bundle 和导出不含密钥值。不要将此数据库加入版本控制或作为普通配置导出。有效目录优先级是内置目录 → 启动时的部署文件合并 → UI 按供应商完整覆盖；UI 移除模型不会被内置合并自动补回。停用只隐藏新活动的选择，保留路由和凭据。

认证优先级是该供应商/引用下保存的密钥 → 后台环境变量。后台仅向相应的可信 Meta/Solver 宿主子进程传递所选密钥，继续使用现有认证桥，不修改旧 Bundle 的代码或路由；Runner 不获得密钥。更新密钥供后续启动的宿主进程使用，已经启动的宿主继续使用其已有凭据。仍有未结束活动引用密钥时不能删除；删除不清除操作系统环境变量，也不删除历史配置。作为凭据使用的引用不得覆盖 PATH、NODE_OPTIONS 等宿主运行设置。

所有管理、测试和读取接口仅限用户身份。保存携带修订号，其他窗口先保存时返回冲突并保留当前草稿；重新读取后核对并保存，或取消编辑加载后台版本。网页不把密钥写入 localStorage。测试按钮使用已保存配置，修改草稿后需先保存；最近测试会标明其配置版本，配置修改后应重新测试。

复制 [配置样例](../../profiles/model-providers.example.json) 到本机仓库外的位置，保留需要的供应商，将示例端点、模型 id、能力参数和密钥环境变量名改为服务商实际提供的值。样例不是可直接调用的真实服务。

```sh
python -m src.control.server --quantum-harbor /absolute/path/to/Quantum-Harbor --model-config /absolute/path/to/models.json
```

也可用 `PHYEXP_MODEL_CONFIG=/absolute/path/to/models.json` 指定，命令行 `--model-config` 优先。 更新模型目录相关代码后，除了重新构建工作台，也必须重启控制后台；构建不会自动重载已运行的 Python 进程。前端兼容旧版仅含 GPT 名称的目录，并显示后台更新提示，不能因此认为新供应商已生效。工作台只连接后台，两个角色都从同一目录选择模型，按供应商分组显示；无需在工作台宿主重复设置目录或密钥。

| 配置字段 | 含义 |
|---|---|
| `schemaVersion` | 当前为 `1` |
| `providers` 的键 | 供应商路由 id，小写字母开头，可含小写字母、数字、连字符 |
| `adapter` | `pi-ai` 为通用适配器；`deepseek` 为 `deepseek-official` 原生适配器 |
| `api` | 通用路由需声明 `openai-completions`、`openai-responses` 或 `anthropic-messages`；原生 DeepSeek 不填 |
| `baseURL` | 服务端协议根地址，HTTPS 或本机回环 HTTP；禁止在地址中嵌入用户名、密码、查询参数及 fragment |
| `auth` | API Key 路由使用 `{"type":"api-key","env":"YOUR_MODEL_API_KEY"}`，只写环境变量名；内置 GPT 订阅为 `{"type":"codex"}` |
| `preflightURL` | 可选，无认证 HEAD 连通性检查地址；缺省检查 `baseURL`。可达不代表模型和密钥有效 |
| `models` | 模型列表；`id` 必填，`name` 可选，`contextWindow` 和 `maxTokens` 按实际能力填写 |
| `reasoningEfforts` | 模型必填；非推理模型填 `false`，界面不显示推理选项；推理模型填“界面等级 → 服务端值”的映射，例如 `{"off":null,"max":"high"}` |
| `defaultReasoningEffort` | 推理模型必填且须出现在映射键中；非推理模型不填 |
| `compat` | pi-ai 路由或模型的协议兼容选项，例如 `supportsReasoningEffort`、`thinkingFormat`、`maxTokensField`；允许字段见共享 schema，按服务商真实协议设置 |
| `transport` | pi-ai 可选 `auto / sse / websocket`，省略保持适配器原行为；实际支持取决于协议 |

通用推理等级可用 `off / minimal / low / medium / high / xhigh / max`。只有 `off` 可以映射为 `null`；这表示省略协议推理字段，并不保证远端禁用推理。原生 DeepSeek 仅支持 `off / low / high / max` 的同名映射。`maxTokens` 作为活动每次请求的输出参数，未配置时仍为 8192；它不构成已经验证的费用或 token 硬额度。当前初版只支持 Codex 订阅登录与已保存 API Key／环境变量认证，不提供其他 OAuth、云厂商签名认证或任意自定义请求头。

Chat Completions 和 Responses 的 `baseURL` 通常带 `/v1`；Anthropic Messages 的 SDK 会追加 `/v1/messages`，通常应填协议根地址（如样例不带 `/v1`）。网关若使用自定义前缀，按其文档配置。原生 DeepSeek 默认是 `https://api.deepseek.com/anthropic`。不要把仅支持 Chat Completions 的地址声明为 Messages。

密钥也可继续在**启动控制后台的终端**配置。例如样例使用的环境变量可以这样设置：

```sh
read -rs "EXAMPLE_MODEL_API_KEY?Model API Key: "
echo
export EXAMPLE_MODEL_API_KEY
```

配置文件、活动和冻结项目只记录密钥引用名，不存实际值。不要将 Key 写进 JSON，也不会自动读取 `.env`。其他服务的密钥不会替代原 GPT 订阅登录：`openai-codex` 保持 Codex OAuth、原始端点和认证方式，配置不能将它改为 API Key 或其他端点；如需 OpenAI API/代理，新增不同路由 id。

创建活动时，后台校验两角色配置并保存各自单模型路由快照；Solver Bundle 和 Meta 会话使用这份快照，预算调整和恢复也沿用它。后续修改或移除外部文件不会改变已创建活动。导出 `recipe.json` 自带所选路由，迁移后仅需按其中 `auth.env` 配置密钥，不需要原配置文件；旧冻结包保持原件。模型生成插件不能通过提交路由、端点或认证配置绕过后台签发的固定模型。

配置错误在后台启动时拒绝；不支持的模型/推理等级在创建时拒绝。协议兼容、工具调用与用量回执仍须针对真实服务验证；目录里出现一个名称不代表该服务已完成实测。完整契约见 `src/execution/host/provider-config.schema.json`。

### DeepSeek V4.1 Flash 1017

Solver 和 Meta 均可独立选择「DeepSeek V4.1 Flash 1017」，也可与 GPT 混用。默认仍为 Solver `gpt-6-sol / medium`、Meta `gpt-6-astra / medium`。模型和推理选项来自后台的统一目录；DeepSeek 可选 `off / low / high / max`，选中时默认 `high`，GPT 的选项保持不变。

可在工作台「供应商与模型 → DeepSeek 官方」保存 API Key，立即供后续请求宿主使用；也可在**启动控制后台的终端**设置 `DEEPSEEK_API_KEY`。例如 macOS 默认 zsh 下，可以用隐藏输入避免把密钥写进命令历史：

```sh
read -rs "DEEPSEEK_API_KEY?DeepSeek API Key: "
echo
export DEEPSEEK_API_KEY
python -m src.control.server --quantum-harbor /absolute/path/to/Quantum-Harbor
```

此前先激活项目 Python 环境，并在代码更新后执行 `npm run build`。工作台宿主仍按上文在另一终端启动。已有后台进程不会读取另一个终端新设置的变量；需要在现有活动妥善停止后，从配置了变量的终端重新启动后台与工作台宿主，再刷新页面。纯 DeepSeek 活动不需要 Codex 登录；混合活动需要两种凭据。缺少 DeepSeek Key 时，启动检查会给出错误，不会改用其他模型。

宿主复用锁定 SDK 的 `deepseek-official` 原生 Messages adapter，默认端点为 `https://api.deepseek.com/anthropic`；需要换端点时须由用户在供应商配置中显式设置。运行时不接受 `DEEPSEEK_BASE_URL` 重定向。保存的密钥位于独立后台凭据表；调用时仍通过宿主短期 0600 文件提供给适配器，并在进程正常结束时清理。浏览器只持有用户当前输入的密钥，保存后清空，读取接口不返回已有值；密钥不进入冻结 Bundle、导出项目或无外网 Runner。不要把密钥放进仓库配置。

请求模型名为 `deepseek-flash`，官方当前将其映射至 `DeepSeek-V4.1-Flash-1017`；这是滚动别名，并非固定快照承诺。活动保存请求配置，冻结执行项目保存所选供应商路由快照（含预期版本、别名性质和端点），审计保存调用时间与请求名；不能据此认定远端未来始终是 1017。[官方模型说明](https://api-docs.deepseek.com/quick_start/pricing/)。已创建活动和已有冻结版本保持原配置，选择新模型须创建新活动。

DeepSeek 沿用现有软 token 阈值、未知用量保留和冻结配方中的模型请求恢复策略；当前仍不提供经过验证的美元硬额度。离线合成流验证不代表真实 API Key、远端模型响应或实验评分已验证。

## 任务成功率与官方评分

工作台、报告、Meta 查询和版本选择快照共用活动绑定规则。新活动默认采用 `task-completion-v4`，已有活动保留 v1/v2/v3，缺少绑定字段时按 v1。创建请求幂等回放使用原绑定，不自动升级。详细设计见[任务完成规则 v4](../design/task-completion-v4.md)。

- 已进入启动尝试且最终结束：只有可信官方通过计 1，其余计 0 并进入分母。模型异常、容器启动/桥接、评分器、收集/归档、执行中额度/凭证故障和自动截止都在此范围；已结束但结果或原因缺失也计零。
- 尚未启动的拒绝或取消显示“未执行”；明确人工撤销且无先行失败单列“已取消”。异常输出或有证据发生在停止请求之前的故障不会因后续人工停止而免除失败。
- 排队、启动和运行仍显示待定。unknown 带结束确认时按失败，无结束确认时显示“结束状态待核实”。仍在重试归集的运行记录不会仅因官方缺分而提前结算；本增量不改变进程核实与收集重试策略。
- 官方 `score/officialReward` 及原件保持不变，没有官方分数仍是 null。主结果显示“失败 · 评分器异常”等，详情显示官方评分状态和派生完成分。先前已记录可信官方结果优先于后续清理故障。

逐任务成功率为通过次数 / 纳入的已结束尝试次数，跨任务等权。完全未测或没有纳入尝试的任务保持待定，不凭空补零。`taskAssessment` 提供结果、原因、是否计入；`taskEvaluation` 提供逐任务/版本统计和未执行、取消、待定数量。不能把官方均分或有效评分比例当成任务成功率。

旧 v1/v2/v3 沿用原故障分类、排除规则和保守统计，报告及选择按原快照投影，不重写原文件、分析、官方分数或选择。新的 v4 标签只用于 v4 活动。重试永不覆盖原尝试。

验证入口：`python3 -m unittest discover -s tests/unit -p 'task_completion_v4_test.py'`；官方结果收集兼容见 `result_collection_test.py`，界面可用 `python3 tests/fixtures/task_completion_workbench.py --data-dir /absolute/new-fixture-directory` 启动合成后台，再按工作台启动说明连接。夹具禁用监督执行，不调用真实模型。

### 官方结果收集与已结束记录恢复

v2 Recipe 不要求人读 `id`，执行身份使用冻结 `bundleId`。收集器校验 Harbor 完成状态、官方 reward、评分报告、任务身份与实验证据后入库；官方 0 是有效评分。`result_collection_failed` 表示官方评分已完成但平台收集失败，`container_transport_error` 表示容器工具桥接故障阻断了评分；二者单列外部故障，不能推断模型零分。

空白命令或越权命令参数在桥接入口被拒绝并作为工具错误返回，允许 Solver 更正；不会执行该命令，也不会因一次已反馈的参数错误而跳过最终 verifier。实际容器传输故障仍按执行异常处理。

早期 v2 冻结适配仍读取 `recipe.id`，可能留下 `error: "'id'"` 和空分。当前控制服务在首次收集这类归档时重新读取官方结果；已入库的结束记录使用用户权限 `POST /trials/{trialId}/recollect` 显式恢复，活动须先暂停或已经结束，目标 Trial 必须已经结束。恢复也可补充已知桥接异常的归因，但没有官方结果时仍保留空分。不调用模型、不重跑 verifier，不重新选择候选或改写预算、时间、原始归档和历史报告。

恢复前校验归档文件摘要、候选冻结身份、任务身份与证据覆盖，未知错误或缺失证据不自动补分。恢复记录包含收集器版本、原摘要/归档摘要及修复原因，数据库事件引用 `result-recoveries/` 中不可变的前后记录，并新增可查询证据；同一归档和收集版本重复请求不重复修改。批量维护前应保留一致性数据库备份，不能用旧数据库覆盖仍有活动的数据目录。

旧候选及旧导出包的适配源码保持原样。控制服务的收集兼容不等于修改旧版本的执行行为；使用修复后的桥接行为须在新活动冻结新适配和基线，不能在旧活动中悄悄替换。

## 阅读报告和证据

「进度与结果」展示全部尝试；官方零分和未评分分别显示。「执行版本」记录插件版本、配置、父候选、内容摘要以及当前/最终保留版本。最新候选不自动成为最终版本。新活动由 Meta 明确选定，选定与证据验证程度分别展示。

报告将系统事实与 Meta 分析分开。分析修订保留旧版本，每次引用必须指向本活动允许的证据。最终结论应解释关键变化、负结果和局限。Meta 结束后系统刷新最终用量、停止原因等事实，不重写其分析结论。

点击「阅读总报告」或「阅读本轮报告」立即进入阅读区，显示加载状态，完成后定位到正文；失败原因也显示在阅读区。再次点击同一报告会重新定位，不需要手动滚动寻找。

证据界面分页读取允许的评分反馈及执行轨迹，每次读取核验摘要。原始 Harbor 归档保持不变；受限评分字段不会自动出现在 Meta 反馈视图。模型文本以普通文本显示，不作为网页脚本执行。

## 导出独立项目

选择已有冻结候选生成项目，再下载 ZIP。v2 导出按同一个组合清单收集选中的插件、配置、明确声明的必要适配和 Node/Python 依赖锁，生成完整项目；DeepSeek 本体由接收者按锁安装。`bundle.json` 保留原组合身份，`objects.json` 记录引用的内容摘要，`delivery.json` 说明适配文件职责。ZIP 摘要、导出器版本与三层验收状态在导出记录中分别保存。旧 v1 继续复制原 Bundle。工作台、Meta 插件、数据库、研究历史、凭据和安装缓存均不进入包。

解压后按包内 README 安装依赖、构建 Runner，并显式提供外部任务目录、认证和输出目录。包内 `run.py --verify` 只做内容校验。静态内容检查、无模型搬迁装配和真实独立执行是三个不同的结果；人工验收 A 不等于已经完成 B 的真实搬迁试验。

## 备份、重启和定位问题

源码仓库不包含运行记录。旧 `runs/`、`reports/`、`.runtime/` 和讨论稿仍保留在本地并被 Git 忽略，不迁移、不清空；不要使用 `git clean -fdx` 清理工作区，这会删除被忽略的本地记录。

活动数据保存在数据目录的 `control.sqlite`、`campaigns/`、`objects/sha256/`、`trials/`、`evidence/`、`reports/` 和 `exports/`。完整备份应在无活动运行时退出后台后复制整个目录；不要只复制 SQLite 文件而遗漏 WAL 或内容对象。备份包含用户访问令牌和原始实验材料，应保持本机私有权限。

部署或修复前制作的整库回滚快照应放在活动数据目录之外的独立私有目录，例如与 `data/` 同级的 `maintenance-backups/<维护标识>/`，不要放入 `data/backups/`。整库快照混合多个活动，放在受管数据目录内会按删除设计阻止单个活动永久删除。处理已有快照时，先确认备份完整、没有进程占用，将数据库、相关 WAL/SHM 和校验记录一起移出，并核对摘要与权限；不要关闭混合备份检查或直接删除仍需回滚的快照。移出后属于独立备份，后续活动删除不会同步清除其中历史，必须向用户说明此边界。数据库快照不能代替包含内容对象的完整备份。

v2 候选目录本身只有 `bundle.json` 和 `recipe.json`，插件与必要适配引用同级内容对象。单独备份候选目录不足以恢复，须连同 `objects/sha256/` 备份。完整独立交付使用导出 ZIP，不直接复制某一个候选目录。

新安装保存在 `cache/dependencies/`，固定适配准备在 `cache/adapters/`。兼容候选共享安装，缓存键包含准确锁及宿主 Node/ABI/系统/架构；缺失或内容损坏时后台按原锁重建，无法取得准确版本则明确失败。修复发布新目录，不覆盖仍可能被进程使用的旧目录。查看候选检查的 `installation.log` 或 `cache/preparation.log` 可定位准备问题。不要对 v2 候选目录执行 `npm ci`；独立导出项目仍按 README 安装。

不提供缓存自动清理。历史重复内容只能按下节的显式迁移流程释放，保留镜像不在整理范围内。确需人工释放 v2 缓存时，先停止使用该数据目录的后台及全部相关进程，并保留完整对象备份；不能在活动运行中删除共享目录。恢复仍需要能获取锁定的外部依赖。

重启时沿用同一数据目录和外部任务目录。后台按稳定启动 ID、进程身份和归档核实已有工作，不重新提交不确定的实验；中断的构建操作标记失败，可重新发起检查。重启不能恢复已经中断的模型请求为原请求；未知用量保留到可信宿主审计可核实为止。

后台每次巡检都会非阻塞回收自己启动的 Solver 监督进程和 Meta 子进程，即使对应活动已经结束。进程退出且结果处理完成后才移除内存中的管理记录；归档或结果收集失败时保留退出状态供后续重试。结果文件先写完、进程稍后退出的情况也会继续回收。此清理不改变历史评分、失败记录或用量，不凭重启前保存的 PID 回收非本后台的子进程。

后台自身错误保存在 `supervisor-errors.jsonl`，实验监督日志在 `trials/<launch-id>.supervisor.log`，模型及工具审计在各实验的 `harbor/<trial>/phyexp/`。Meta 轨迹在 `campaigns/<campaign-id>/meta-sessions/`。排查时先读页面的停止原因和报告，原始日志用于进一步定位。

### 显式整理历史存储

用户要求整理已结束活动时，可使用 `scripts/migrate-history-storage.py`。先运行 `plan` 盘点，`apply` 才执行备份、验证、共享与释放。计划目录必须是新目录，建议放在数据目录的 `development/`，并与对象存储位于同一文件系统：

```sh
python3 scripts/migrate-history-storage.py plan --data-dir /path/to/data --session /path/to/data/development/history-storage-001
python3 scripts/migrate-history-storage.py apply --session /path/to/data/development/history-storage-001
```

`plan.json` 列出纳入和排除对象，`control-before.sqlite` 是一致的数据库快照，`backups/` 保存逐版本冻结文件，`entries/` 是可续做日志，`checks/` 保留原代码的模拟装配回执，`result.json` 汇总结果。异常后重跑相同 `apply`，不另建重复计划；引用或活动状态发生变化时明确拒绝该版本。

运行中、草稿、暂停或其他未结束活动的引用，以及仍有在途 Trial、Meta 会话、操作或直接进程使用的版本均排除。未被候选记录引用的目录也不自动清理。工具不停止服务或活动，不启动真实模型，不改数据库、历史报告/轨迹/导出 ZIP 或 Docker 镜像。

整理后旧目录中的源码是硬链接兼容视图，共享文件正文位于 `objects/blobs/`，插件/适配/锁对象位于 `objects/sha256/`，布局清单位于 `objects/legacy-compositions/`；原 `bundle.json`、路径与内容摘要不变。备份须包含这些对象、迁移计划和 `backups/`。不要编辑硬链接中的源码，否则会影响引用相同内容的版本。旧路径仍可读取与导出，无需为整理重启正在运行的后台。

如需恢复某个版本的独立源码文件：

```sh
python3 scripts/migrate-history-storage.py restore --session /path/to/data/development/history-storage-001 --bundle <完整旧Bundle摘要>
```

恢复先核验备份，原 ID、路径及字节内容不变；已验证的共享依赖保留，避免重新制造重复安装。恢复后的版本若要再次去重，应生成新计划。不要将整个数据库快照覆盖回仍在运行的数据目录；它是审计/灾难恢复材料，普通源码恢复不改数据库。

## 固定任务环境以便比较

平台在 `runner-runtime-locks/` 保存 Runner 构建输入与镜像 ID 的准备回执。不同插件候选共享相同构建输入时复用镜像，按共享镜像标签跨进程加锁，不再为每个候选重复构建。构建或恢复标签前，为旧镜像和已准备镜像保存 `phyexp-runner:retained-<镜像摘要>` 引用，防止 Docker 标签更新使已被实验选定的旧 ID 消失。此逻辑只属于平台准备阶段，不修改冻结执行代码和 Quantum-Harbor。

Runner 缓存缺失时重新准备；Docker 不可访问或检查异常时明确失败，不把连接故障当作缓存缺失。平台不会自动清理这些保留引用；有活动或独立执行仍使用对应镜像时不要删除。独立项目自己的安装命令仍沿用导出时的行为，历史 Bundle 与原始证据不改写。

镜像生命周期的真实 Docker 回归可用 `python3 tests/smoke/runner_images.py --output /absolute/path/to/new-check-directory` 执行。它只构建独立的最小测试镜像，检查跨进程复用、标签重建后的旧 ID 可用性与缓存恢复，不调用模型或官方任务，并清理自己的测试镜像。

新活动创建后，后台自动准备全部所选公开任务的镜像，再检查 H0。5 个公开任务均受支持；只选部分任务时只准备这些任务。所有任务就绪后才能启动活动，准备过程不调用模型，也不占活动计时和实验次数。

main 按各任务的官方 Dockerfile 构建；qsim 按官方 Dockerfile 构建一次并在所选任务间共享。基础 agent 镜像和各任务声明的独立 verifier 镜像须先按 Quantum-Harbor 官方安装流程准备；后台解析它们当时的实际镜像 ID，不自行替换评分器的构建材料。缺少依赖或构建失败时显示准备失败，详细日志位于数据目录的 `campaigns/<campaign-id>/checks/task-images.log`；排除问题后创建新活动。

后台把每个任务的 main、qsim、verifier 镜像 ID 和任务/构建源码摘要作为整套快照保存到活动。准备缓存位于 `task-runtime-locks/`，源码和基础镜像相同时可复用已验证的缓存；缓存更新只影响以后新建的活动。活动启动、恢复和每次实验运行前检查对应快照；缺失、源码变更或身份不匹配时明确失败，实验不会自动构建或拉取替代镜像。启动容器后再次核对实际镜像并保存回执。

Docker Desktop 必须处于引擎就绪状态。无法连接引擎时，启动检查会提示先启动 Docker 并检查 context/权限，不把它当成镜像缺失；恢复引擎后可直接重试原活动。若引擎正常而某个固定 `sha256` 确实不存在，须恢复该精确镜像或切回保存它的 Docker context，不能用最新标签替换已有活动的快照。

每次实验仍使用全新的容器、数据卷和 Solver 会话，沿用官方随机采样。清理时删除该实验的容器和卷，保留活动共享的镜像。固定镜像不等于固定随机样本或保证科学结果一致。旧活动和冻结 Bundle 保持创建时的行为，不追溯补锁或重写证据。

通常无需手工准备。可在创建活动前预热全部 5 个任务，或为独立运行导出锁文件：

```sh
python3 scripts/prepare-task-images.py \
  --quantum-harbor /absolute/path/to/Quantum-Harbor \
  --all \
  --cache "$HOME/Library/Application Support/PhyExpHarness/task-runtime-locks" \
  --output /absolute/path/to/task-locks
```

单个任务使用 `--task <task-id> --output /absolute/path/to/lock.json`。独立执行入口通过 `--task-image-lock /absolute/path/to/lock.json` 使用同一固定环境；镜像和任务目录仍由使用者提供，不打包进执行项目。源码更新后创建新活动，后台准备对应的新快照。

无模型验收会让 5 个任务各用 `nop` 执行两次，检查 main/qsim/verifier 身份、全新容器与卷、清理后镜像保留及缓存复用。空操作通常得到官方零分；Shadow 的官方评分器会因没有提交且证据为空而拒绝产出分数，验收保留该未评分诊断，不补零。该检查只验环境与生命周期：

```sh
python3 tests/smoke/harbor/pinned_images.py \
  --quantum-harbor /absolute/path/to/Quantum-Harbor \
  --locks /absolute/path/to/task-locks \
  --cache "$HOME/Library/Application Support/PhyExpHarness/task-runtime-locks" \
  --output /absolute/path/to/new-check-directory
```

## 插件、执行版本与实验轮次三表

活动页「插件 · 版本 · 轮次」和最新报告共用三表。插件表展示精确版本、中文功能和实现方式；执行版本表展示有序插件组合，配置可展开；轮次表说明相对上一受理轮的变化。点击插件/版本名称可直接定位。复测显示“无变化”，来源版本另行记录，未评分保持未评分。旧报告在修订选择器中继续保留。

已结束活动的三表展示迁移不调用模型、不重跑实验：

```sh
python3 -m src.reporting.refresh --all-finished --record /absolute/path/to/migration-record.json
```

可用 `--campaign <id>` 限定活动，或 `--data-dir` 指定数据目录。三表、阅读内容或展示版本变化时才新增报告修订，原事实与 Meta 分析不改写。旧插件中文补充说明保存在数据目录 `plugin-annotations.json`，以名称/版本/源码摘要绑定，并在报告中标注来源；不要修改冻结 Bundle 来补功能说明。

## 阅读版、代码与交付（v0.7）

版本统一显示 H0/H1 加功能名称，可修改名称而不改变冻结内容。连续同版本且条件可比的复测默认合并，展开看每轮报告和全部评分。每轮报告先说明 Agent 做了什么、问题、插件预期/观察/对照/判断；最终报告再展示全量三表。旧分析与原件保留，新整理明确来源。

插件「查看代码」浏览精确冻结文件；「打开所在文件夹」与复制路径供本地检查，不能把草稿当成旧实验源码。预览只读，直接修改冻结目录会导致完整性核验失败，应在草稿中开发新版本。

「获取 Harness」默认最终保留版本，可下载项目、打开项目目录、下载匹配任务的运行说明。旧 ZIP 原件不变；新的说明作为附件提供。文件检查、独立装配、独立真实实验状态分别显示，后者不因下载而执行。

## 模型请求保护与故障诊断

新冻结执行版本携带 `src/execution/host/stream-policy.json`（`stream-protection-v1`）。Meta 与 Solver 的固定网关均执行保护：单请求最长 10 分钟；连续 180 秒无数据终止，包含等待首次响应；单响应可见内容最多 256 KiB，单工具参数最多 128 KiB。工具参数连续空白同时达到 4096 字节和 30 秒，或增量 JSON 语法已确定无效时终止。尚未生成完的 JSON 不算错误。重复内容先告警，由参数字节和请求时间上限兜底，避免误杀合法重复数据。计量按 UTF-8 字节；结束块不重复计量。服务端输出 token 硬上限不可用，`maxTokens=8192` 不保证后端限制；本地取消也不是计费硬上限，隐藏推理和在途消耗仍以可信回执为准。

保护先保存 `failure.json`，再取消当前请求；不执行半条命令、不补写答案、不自动重试。宿主有限等待迟到回执，没有完整可信回执时保留未知用量。失败仍占已启动次数。执行版本、导出包和活动查询都保留保护版本；旧 Bundle 不热修改，新基础设施须建立新 H0。Meta 只能调整执行插件，不能修改固定保护。

原生上下文压缩也经过同一模型网关与运行权限检查。Runner 将压缩摘要的输出上限配置为该会话的固定上限；SDK 的压缩请求省略推理等级时，宿主补入已选等级，显式改用其他模型、等级或上限仍会被拒绝。排查上下文溢出时同时查看 `compaction/end` 事件：若摘要请求被拒绝，不能将后续容量溢出解释为模型解题失败。此兼容修复只随新冻结版本生效，不改写已有执行包或活动。

实验表、阅读报告和 Meta 材料查询沿用同一故障摘要；工作台另行区分排队、启动、运行、评分阶段和统计覆盖，不将未评分当成官方零分。故障记录含阶段、原因代码、触发时间、请求 ID、阈值、归档依据和后续清理事件；外层退出码不覆盖先前原因。单次终止按钮经用户身份接口 `POST /trials/{id}/stop` 执行，不停止整个活动。完成事件可唤醒 Meta；同一次读取中的批次完成事件合并对应单次完成事件，游标避免重复通知。

新冻结版本增加 `model-transport-v1` 诊断。受信宿主通过 Node 的 Undici 诊断通道观察原生 WebSocket 与 HTTP/SSE；不修改第三方依赖、传输选择、恢复次数或请求内容。`gateway-audit.jsonl` 的 `type=transport` 事件关联网关请求 ID，记录连接 ID、连接年龄与累计请求数、发送字节、实际传输、首个/最后协议事件、关闭码及是否正常关闭。底层错误的 `name/code/message/cause`、关闭原因和传输回退保存在脱敏审计中；不采集请求头、认证字段或响应正文。复用连接按每次发送重新关联请求，关闭事件迟于请求结束时标注 `afterRequestEnd`，不据此把已成功任务改判失败。

故障摘要的 `observed.transport` 只投影结构化事实，原始错误文本不进入公开摘要。`responseContentBytes` 表示模型文本、推理及工具参数的内容字节数；旧字段 `responseBytes` 作为同义兼容字段保留，`responseBytesMeaning=model-content-not-wire` 明确其含义。内容为 0 不代表没有收到协议事件。`protocolStarted` 为 `true` 表示观察到响应事件，为 `false` 表示可观察的传输尚未出现响应开始，为 `null` 表示缺少这项观测；旧归档缺失字段不能补成 `false`。SSE 缺少 Content-Type 时可通过合法的 `data:` 协议事件识别；HTTP 内容编码或非 Undici 传输可能使部分观测不可用，不能据此反推根因。

WebSocket 的错误、异常关闭（包括 `WebSocket closed 1012`）及连接建立超时归为可恢复的模型传输故障。v2/v3 只在任务最终未恢复而终止时派生任务完成分 0，官方缺失评分保持 `null`；单次请求失败、成功恢复、用户取消及平台账本/环境/评分器故障仍按各自规则处理。界面并列展示任务完成分、官方评分状态和故障原因。诊断增强不更改冻结的历史 Bundle、评分或统计规则。

历史诊断与回放均不调用模型：

```sh
python3 scripts/diagnose-history.py --data-dir /absolute/local/data
python3 -m src.reporting.refresh --all-finished --data-dir /absolute/local/data --record /absolute/local/output/history-refresh.json
node scripts/replay-model-streams.mjs /absolute/local/data /absolute/local/output/replay.json
```

回放可追加第三个参数，指定先前回放的 JSON；只读取其中列出的历史日志，并验证输入摘要不变，便于在新活动运行时复核相同的离线样本。

历史诊断先核对归档清单，在数据目录追加 `failure-diagnoses.json`，不重写旧 Trial、旧报告事实和分析。报告展示更新另建修订。回放按日志原始时间与分块运行同一保护器，保存输入摘要、正常请求误报情况和假设终止时间；这是工程检查，不能当成真实科学评分或实际节省的 token。

## Meta 插件组合与停止审查

新创建的活动默认绑定 `meta-composition-v2`、`meta-system-v9`、`meta-tools-v7` 和 `goal-or-budget-v1`。系统正文保留用户填写的目标和固定 Solver 配置，不再追加旧运行协议段落。默认目标单独配置，不包含提前放弃或固定数值阈值。默认组合文件为 `packages/meta-harness/composition-native.json`；插件源码修改只影响以后创建的活动。创建配置可显式指定 `metaCompositionConfig` 研究另一组本地受信模块，不能指向插件包之外的源码。完整接口与关闭规则见[组合设计](../design/meta-harness-composition.md#11-首期配置与接口约定)。本期不提供跨活动比较、重复调度或自动消融功能。

新组合在 `meta-compositions/<摘要>/manifest.json` 保存精确框架引用、六插件及必要运行适配的内容引用、配置和镜像身份；内容保存在共享 `meta-objects/sha256/`。`cache/meta-runtimes/` 由校验后的对象物化，不是备份的唯一来源。备份同时覆盖组合、内容对象、活动工作区/会话、证据及账本。旧 v1 仍保留原快照目录，不能删除或自动转换。宿主依赖须匹配冻结的根锁文件；Runner 使用冻结镜像 ID，不要清理仍被引用的镜像。

Meta 普通回合结束不会结束活动；无在途实验/构建时，后台继续提醒其推进；等待实验时按已有事件通知。新活动只接受已约定目标达成申请，或由平台在额度达到上限时收尾；默认停止审查插件关闭，后台同时拒绝探索耗尽申请及审查请求。用户暂停和停止入口继续有效。

以下审查行为仅适用于历史 `stop-review-v1` 活动：申请“充分尝试后不值得继续”会触发原生只读审查子会话，默认继承 Meta 模型与推理等级，共用 6 小时等用户设置的原额度，并没有独立赠送预算。审查有 300 秒技术超时，没有自动重试。超时或非法结果不批准，也不会污染主会话的模型通道。

停止审查在后台留存请求、候选、证据快照、实际子会话、结果与用量。拒绝或证据不足时继续；相同证据快照不能通过重复改写理由取得多次投票。相关证据、候选或限制变化会使旧批准失效。目标达成申请要求创建时提供明确的 `stabilityRule`，未设置时不宣称稳定；资源上限及用户停止不等待审查。旧活动继续沿用创建时的契约与原记录。

工作台概览与新报告展示同一份组合和审查记录。触发次数只是运行事实，不能当作插件提升效果的证据。审查用量是 Meta 总量中的子集，不能再相加。原始子会话请求审计在 `campaigns/<活动>/meta-sessions/<会话>/review-sessions/`；主会话与子会话都保留已知及未知用量。


### 请求恢复诊断

当前 H0 v3 绑定 `requestRecovery.version=solver-request-recovery-v2`，固定加载协调插件和三个策略：传输恢复、异常响应恢复、完整工具参数错误反馈。连接/响应不完整/明确过载仍依次等待 **2、5、20、30、60 秒**；内容恢复共享 **两次**机会，等待 **0、1 秒**；同一恢复链合计最多追加 **五次**请求。Retry-After 更长时遵从服务端等待，原截止不足则停止。

流中非法 JSON、持续空白和体积超限仍立即中止当前请求，丢弃失败部分后重新生成。完整且有成功终止回执的调用若参数不合法，工具不执行，错误结果反馈给模型。反馈后的新步骤仍沿用原恢复链，不能无限获得次数；只有该链的完整有效响应结束恢复链。以前完成的工具不重放，压缩失败部分不写入摘要，普通辅助调用不会清零主循环状态。鉴权、模型不匹配、宿主错误、取消及截止不属于这套内容恢复。

旧 H0 v2 / `solver-request-recovery-v1` 继续仅做五档传输恢复，缺少配置的配方继续不启用内置恢复。提供方适配器的通用重试仍为零。新组合不会热升级旧 Bundle、已有活动或正在运行的后台，需重新冻结同基础设施的基线与候选后生效。

会话 `plugin:phyexp-request-recovery/*` 保存策略、动作、类别次数、合计次数、链 ID、请求 ID 和停止原因，`phyexpRecoveryV2` 投影可重建状态。bootstrap 回执的 `recoveryComposition` 给出实际加载策略。网关审计与 `requestRecovery.failures` 保存 `recoveryChainId`、`parentRequestId` 和 `recoveredBy`；`failureContract=request-failure-v2` 的 `failure` 只描述最终终止请求。错误反馈会改变上下文，v2 依靠宿主校验后的请求关联，不靠内容相同猜测恢复。

源码、配置和全部恢复资产参与冻结及独立导出。设计和边界见[恢复组合](../design/execution-recovery.md)，实施验收见[专项计划](../plans/model-request-recovery.md)，插件接口见[SDK 指南](../../knowledge/plugin-sdk/guides/request-recovery.md)。当前验证使用合成故障和原生隔离 Runner，不代表已证明真实模型异常率或通过率改善。


## 工作台中的等待状态与历史记录

“排队”表示尚未启动，查看逐次实验下的等待原因：例如“并发名额已满（5/5）”，通常只需等待已有实验结束。活动暂停、尚无 Meta 运行计划、收尾时间/token 预留和单次可用时长不足会分别说明；未记录原因时界面不猜测。排队时长从本轮受理开始计算，已运行时长从实验启动开始计算。

“运行中 · 阶段未细分”说明后台尚无独立的实时评分信号，可能正在执行、评分或归集结果。“评分中”只用于有明确评分阶段回执的记录，不能将“等待评分”理解为评分器已经启动。此次界面更新不会为正在运行的活动增加探针或重启后台。

“覆盖不足，暂不计算”是统计口径说明：该版本/范围中仍有任务没有可计分结果。即使某版本的所有实验都已结束，只测过部分任务也会覆盖不足。点开逐任务/逐次结果，可分别查看排队、运行和失败原因；排队与运行不计入成功率分母，已有官方评分和任务完成规则不变。

报告、版本选择中的“历史快照”只表示当时的事实，其中“当时运行中”不表示现在仍在运行。历史时长不会增长；报告修订时间不是实验状态更新时间。当前进度应回到实验记录查看。只改展示时运行 `npm run build:workbench` 并重新加载浏览器页面；无需重启控制后台，也无需重建资料包或执行包。


## 原生 Meta v2 的实际接口与恢复

六个入口为 `domain-control/campaign/experiments/evidence/reporting/stop-review.mjs`，位于同一个 `packages/meta-harness` 包。固定业务接口见 `contracts.json`，通用能力与限制见 `capabilities.json`；准确依赖由 `runtime-package-lock.json` 固定。业务工具直接接收对象参数，写操作须提供稳定的 `idempotencyKey`。修订冲突、无权限、不可用与参数错误返回明确类别；未知结果保留请求身份，由 `campaign_status.metaRequests` 的文件和未决列表查询，不盲目重发。批次、计划、条件修改及异步检查/冻结可从后台已提交记录恢复原响应。

| Runner 路径 | 内容 |
|---|---|
| `/work/plugins` | 可写插件草稿；只有声明源码与资产进入冻结版本 |
| `/work/analysis`、`/work/checks` | 持久分析脚本与检查文件，不进入 Solver 导出 |
| `/evidence/index.json` | 完整材料索引、容器内路径、SHA-256、字节数、来源与可用性 |
| `/materials`、`/sdk`、`/versions` | 只读活动材料、匹配资料和版本文件 |
| `/outputs/index.json` | 原始终端流与工具结果文件；live、complete、partial 分开 |
| `/session` | 本活动主/研究子会话的原生持久日志与 spill；审查 Runner 有独立存储；不作为计量或权限依据 |

终端原始 PTY 字节在原生 scrollback/预览裁剪前流式捕获。新委派契约的捕获器每个活动研究 Runner（主/研究子会话共享）最多保存 256 MiB，独立审查 Runner 另有 256 MiB，超出后停止生产者并保留已有部分，不返回完整成功。普通工具结果另存完整结构；文件和搜索的完整来源仍是被查询文件，终端预览自身不冒充完整 stdout。原生 `bash` 保持会话内 shell 状态；原生终端/jobs 可管理后台任务。OS 进程不跨容器恢复，输出标注中断，模型需核对后决定后续命令。

开发镜像固定 Node 24.13、Python 3.11.2、NumPy 1.24.2、rg 13 与 jq 1.6；Debian arm64/amd64 包及 npm 内容均记录准确版本和摘要，通过宿主共享缓存获取、在无凭据环境安装。仅 arm64 实机验证已完成。每个 Runner 为 2 CPU、1 GiB 内存、128 进程、256 MiB 临时区；主/子代理都没有任意外网，Meta 未配置额外 MCP 服务。可用技能从只读 SDK 与自己的原生技能目录加载；Office UI/渲染不装入此无界面配置。

本次委派增量的验证状态（2026-10-22）：代码、单元和本地原生 SDK 协作/恢复检查已完成；当前 Docker 存储只读，镜像导出与真实容器契约尚未完成，不能将本地检查当成容器验收或已部署。以下描述新组合的实现；先恢复 Docker 并完成容器检查，再用于新活动。

新冻结组合的 `delegationVersion=native-research-v1` 使用原生 `spawn` 研究子会话及 `send_message`、`interrupt_agent`、`list_agents`；活动中的普通研究不再经过一次性隔离后端，也没有额外五分钟总时限。子代理沿用活动截止、固定模型和预算，按原生子会话 ID 分别归属用量。原生冷恢复的模型默认输出上限同样取活动冻结值。

主 Meta 与研究子会话共享活动研究容器、授权工作区和持久会话存储，保持各自上下文、工具预设和终端状态。显式 cwd 生效，省略时按原生规则继承；需要独立修改时由模型安排目录或副本，结果文件可直接读取，不需要再发布一份研究工作区。研究预设只提供业务查询，后台按登记角色检查业务调用；同域终端不是研究者与主 Meta 之间的 OS 安全隔离。并发委派上限仍为 2。

停止审查继续使用独立容器、工作区、会话及宿主身份通道，300 秒限制只适用于审查。审查产物仍发布到 `/materials/agents/<id>/index.json`，上限 64 MiB；超出时保留原工作区并报告不完整范围。研究 Runner 无法登记审查身份或提交审查结论。真实凭据留在宿主，跨活动、Solver、审查者边界不共享。

恢复主会话后，先 `list_agents` 查原生子目录，结合会话查询和工作文件核对中断，再向原 ID `send_message` 继续。原生描述符与目录负责冷恢复，不另建研究任务状态机。普通回复结束不关闭子会话。控制宿主等待原生主/子工作及消息处理静止后再发空闲提醒，避免研究未完时反复催促。恢复不重启已终止的 OS 进程，也不自动重放结果未知的命令；未落入持久日志的消息不能保证恢复。

旧冻结组合仍按原版本运行：普通研究可能使用独立一次性容器、五分钟时限及 64 MiB 结果发布。新代码不热改旧组合或历史会话；创建新活动才采用新委派契约。

原生 `ask_user_question` 经 `meta-control` 接到持久后台，主 Meta 可发问，工作台的 Meta 页面提供选择和文字回复。页面离线不回答问题；问题、用户回复和通知分别持久化。当前采用阻塞式原生提问，仍受活动截止限制；重启后未决问题及已有回答进入恢复状态，不能把退出或超时当成用户许可。

新 Meta 出现临时请求/进程故障时，在连续未完成回合期间最多追加六次技术恢复，间隔依次为 2、5、10、20、30、60 秒（加上进程清理与启动时间）；恢复后的会话完成过完整回合后，再次故障从第一档重新计数。此策略由控制后台 `src/control/meta_recovery.py` 管理，不属于冻结的 Meta 插件；更新策略需重启控制后台，既有活动之后发生的故障也采用新规则，已记录的等待时间和“需要处理”状态不会自动改写。优先调用原生 `session/resume`，恢复失败时显式记录续接新会话及前序身份。鉴权、预算、权限、完整性与确定性装配错误不自动重试。恢复耗尽时，Studio 活动选择和页首显示“需要处理”，提示具体中断原因、恢复停止原因及在途实验情况，并可进入运行详情查看原始错误；自动重试时显示“正在恢复”。已受理实验继续受后台监督；排查后可直接点击提示内的“恢复活动”，无需先暂停；恢复意图与幂等回执在同一事务中保存，重复请求不重启会话或清除后续故障。受理后显示“正在恢复”，新会话正常推进后告警清除。恢复前校验任务环境和冻结的 Meta 依赖，失败时保留待处理状态；已到截止时间的活动不可直接恢复。活动列表与详情通过只读 `metaStatus` 提供最新会话摘要，不改写活动的生命周期状态。通知领取不推进消费游标，只有完成持久会话处理后才 ACK。未知用量保留，恢复不增加原预算和墙钟。

`report_get_facts` 产生不可变事实文件及 `factsId`；`report_save` 接收分析或 `/work/analysis` 中带 SHA-256 的分析文件，并校验预期报告修订。完成时不再覆盖模型引用的事实快照。保留版本同样检查 `expectedSelectionRevision`。

研究委派契约使用 `tests/contracts/meta-research.test.mjs` 验证指定/继承目录、共享文件、运行中和空闲后追问、中断、工作进程替换后原 ID/历史/文件冷恢复，以及用量归属。Docker 不可用时可运行 `PHYEXP_META_LOCAL_TEST=1 node --test tests/contracts/meta-research.test.mjs`，使用真实原生 SDK 的本地传输夹具；这只验证原生协作和恢复，不能替代容器隔离验收。容器验证需将 `PHYEXP_META_TEST_IMAGE` 设为当前冻结依赖生成的 Meta 镜像，不使用缺少新原生插件的旧 Runner 镜像。

可重复工程验证入口（使用临时数据，不调用付费模型）：

```sh
npm test
npm run test:contracts
npm run build:workbench
python3 scripts/check-boundaries.py
python3 tests/contracts/meta_runtime.py --native
python3 tests/contracts/meta_runtime.py --native --recover
python3 tests/contracts/meta_runtime.py
python3 tests/contracts/relocation.py
python3 tests/contracts/harbor-score-pipeline.py --native-meta \
  --quantum-harbor /absolute/Quantum-Harbor \
  --task-image-lock /absolute/prepared-task.lock.json \
  --output /absolute/new-validation-directory
```

容器契约依赖 Docker 和可用运行镜像；`PHYEXP_META_TEST_IMAGE` 可指定已准备好的 Meta 镜像。最后一项贯通官方验证器，脚本故意不提交科学答案，正确结果是官方零分及明确的未提交归因。它验证 Meta 能读完整材料、运行 Python、写插件、检查/冻结/提交，再从后台读到第二次官方结果，不用于宣称科学通过。

### Meta v4 业务回执、研究解释与报告

新活动冻结 `meta-tools-v4`、`meta-tool-receipt-v1`、`meta-report-analysis-v2`、`evolution-research-v1` 及渲染摘要。v3 精确资产归档在 `packages/meta-harness/protocols/meta-tools-v3/`，旧活动仍使用原 v3 契约及报告 v1。`evidence_list`、`sdk_read`、`results_compare`、`candidate_retain`、`campaign_status`、`candidate_list`、`report_save` 返回描述、必要状态/计数和完整文件路径，实际模型回执上限 4 KiB。原生 read/grep/bash 仍按请求返回内容；原始终端捕获保留。业务回执归档标为 `business-receipt`，不冒充原始证据全文。

`campaign_status` 和 `candidate_list` 使用空对象，`evidence_list` 可带 batchId/trialId、无分页，`sdk_read` 仅带文档 id，同版本文档导航为 `/sdk/index.json`。状态和通知通过快照文件提供历史详情；新存储策略使用下述一致读取与分层快照，旧格式保留原逐项读取方式；写操作仍校验修订。不可用原件保留目录条目及原因。

新报告另需独立简短 `brief` 与准确 `researchRefs`（可为空）。报告优先先写 `/work/analysis/*.json`，再提交 path/sha256。`report_get_facts` 提供同版本正文 schema 与最小模板；直接 analysis 对象使用同一规则。problems 必须为数组，元素含 status（resolved/unresolved）、description，可附 evidenceRefs。未声明字段拒绝保存；所有已知格式和引用错误进入诊断文件，`rejected/committed=false` 不占未决操作。修正参数必须换幂等键。

同键同参数重放已提交报告时不重新读取后来改变的草稿。报告/保留事务记录请求关联；若已提交但文件发布失败，返回 `committed`，用原参数原键重试修复回执，不能据此创建第二次提交。旧报告、官方评分、轨迹和旧活动协议不回写。

无 `toolContract` 的历史活动仍走 v2，未知版本或摘要不匹配明确拒绝；恢复活动前须恢复对应协议实现，不可自动升级。协议解析兼容不替代依赖兼容：旧会话仍需要其冻结的依赖锁及匹配运行环境；出现 `Restore matching Meta dependency lock first` 时应恢复对应依赖环境，不能重写冻结摘要绕过检查。七工具之外的业务接口仍沿用原有返回，本次未承诺所有工具已精简。测试包括 `python3 -m unittest discover -s tests/unit -p "meta_receipts_test.py"` 及上方原生/评分链路入口。

收尾状态摘要会明确缺失报告数量和下一份 batchId；完整清单在状态文件 `data.closeout`。失败实验仍需独立轮报告，总报告不替代它；已关闭探索时无需再次调用 campaign_finish。收尾可暂停/恢复，暂停不会被监督轮询自动撤销，恢复不重新开放实验或增加原预算。新增回归入口：`python3 tests/contracts/meta_runtime.py --native --final-first`。

原生 Meta 进程已退出时，如果活动正在收尾、所有实验和后台操作均已结束，且每轮分析和最终分析均已保存，后台会直接完成活动，不再要求最后一条模型回复。报告提交后发生的额度拒绝或连接故障仍保留在 Meta 会话与用量记录中，不补跑模型、不覆盖报告。暂停中的活动、仍有在途工作或缺少分析的活动不适用此完成条件。回归入口：`python3 -m unittest discover -s tests/unit -p 'meta_closeout_test.py'`。 原生隔离验证：`python3 tests/contracts/meta_runtime.py --native --closeout-budget-denial`，使用本地模拟供应商重现报告提交后最后一次请求被预算拒绝，不调用外部模型。

Studio 的活动页面提供“暂停收尾”。报告文件必须是 `/work/analysis` 内的普通文件；符号链接、目录与管道会被拒绝，修正后用新的幂等键提交。

### 进化过程的分层阅读

概览先并排展示已保存的研究结论与当前选择，随后直接呈现基线、当前保留、最新候选的逐任务成功率、成功数/分母和在途状态，再看关键研究节点与下一步。点任务单元格查对应实验，点版本查全部实验，再进入本轮报告或原始证据。矩阵不会因为缺少研究解释而消失。报告概述标明快照时间；历史报告使用当时快照，新报告不再将非基线的单轮版本重新编号为 H0。活动结束后显示阅读指引，旧记录中的计划收在「当时提出的下一步」中。

「插件与动机」选择一个准确插件内容版本，先读用途、当前观察和重要限制，再按「为什么想到这个办法」「实际起了什么作用」「为什么保留或暂不采用」「实现方式与准确版本」展开。开发动机读取冻结时的研究修订，相关记录在后台按插件筛选后分页；同名同版本号但内容不同的插件按摘要区分。旁边的「查看全部研究记录」按钮打开独立记录视图，分为「与插件相关的研究」和「尚未形成插件的尝试」，分别显示数量与分页；后者按尚无插件关联归类，各条失败、放弃或探索状态仍照实显示。返回时保留刚才选择的插件。历史来源与补充说明、版本配置和源码仍可进入。

选择详情先读结论，再看理由、代价和重新考虑的条件，以及 Meta 明确考虑的备选；当时的结果、成本和解释修订按需展开。当前表现变化不覆盖旧选择。少量技术术语在阅读层替换为固定中文名称，不截断正文生成概述；原始研究记录、决定和报告仍可核对。

「显式纳入历史来源」支持选择其他活动的具体证据或报告修订、填写用途并选择访问范围。默认仅用户阅读；选择授权 Meta/研究角色后才建立目标活动的受控引用。来源任务须在当前任务范围内，未纳入的跨活动 ID 仍拒绝。历史成绩不进入当前矩阵。事后说明通过「补充有来源的历史解释」追加，需原报告与事实时间，保留用户署名和整理时间。

技术契约、路由与边界见[进化可读性设计第 9 节](../design/evolution-readability.md#9-已落地的契约与接口)。后端无需迁移既有分析或插件；重启时创建增量表。新旧活动各自核对冻结协议，研究材料不进入 Solver 或导出执行项目。

可复现的工程检查：

```sh
python3 -m unittest discover -s tests/unit -p 'evolution_test.py'
python3 tests/fixtures/evolution_workbench.py --data-dir /absolute/new-synthetic-data --port 18562
# 另开终端，从相同数据目录启动真实 Studio；仅使用合成数据，无模型调用。
PHYEXP_DATA_DIR=/absolute/new-synthetic-data PHYEXP_CONTROL_URL=http://127.0.0.1:18562 PHYEXP_UI_PORT=18561 node scripts/workbench.mjs
```

夹具包含三版本、两任务、运行与排队、同名异内容插件、跨活动来源、三个解释修订和旧报告快照。追加 `--large` 可生成 26 条研究记录与长中文正文，用于检查 20 条分页及窄屏阅读。单元/契约检查与合成 UI 检查不证明科学收益。

2026-10-22 的真实模型 E2E 已完成 10 比特 Hamiltonian 学习的三次实验：基线成功 1/1，依赖预检候选成功 1/2；候选复核因预算准入失败，Meta 据此保留基线。真实产物覆盖问题来源、插件动机、观察、备选取舍、片段核验及全部尝试的最终报告。过程中人工校准了测试收尾额度，未补跑失败实验；不据此宣称插件有效或研究可全程无干预运行。配置、成本、截图和限制另存本地 `reports/development/meta-harness/evolution-readability/`；验收范围见[开发任务书第 23.3 节](../plans/meta-harness-development.md#233-本次实施与验收结果)。


## 参考实验插件

已实现两个可独立启用的包：`packages/meta-model-reference` 与 `packages/meta-harness-reference`。两者默认关闭，不是主线 Meta 的必需能力。创建活动第一步的“参考实验插件”提供双开关、原生模型多选、Harness 多选、Meta 自主组合或指定配对。参考模型先在 DeepSeek Harness 的 Models 中配置；工作台通过原生 `llm/settings/credentials` 服务读取，项目“供应商与模型”仍只配置主线 Solver/Meta。

- 仅开模型插件：选定原生参考模型运行本活动已检查的执行候选。
- 仅开 Harness 插件：固定 Solver 运行 Codex、Claude Code 或 DeepSeek 标准模式中的选定项。
- 两者都开：还允许参考模型与参考 Harness 的兼容组合；由 Meta 按研究问题逐次选择，不自动遍历矩阵。

在“运行详情 → 参考实验 → 调整插件与范围”可关闭/恢复创建时的插件和允许项。关闭取消相关待执行批次，运行中默认按原期限完成；勾选“同时停止…”才撤销相关租约。重新开启不清零额度、不恢复取消的实验。增加从未冻结的插件、模型、Harness 或改变原生模型行为配置需要新建活动。插件源码可各自移除；新活动不选缺失插件仍能构建/运行，已有活动使用冻结副本，历史证据不依赖源包存在。要停止旧活动继续使用该能力，应先在对应活动关闭开关，再移走源包并更新 workspace 安装。

固定版本为 Codex `0.155.0`、Claude Code `2.1.280`、DeepSeek Harness `0.2.1-rc.2`。创建时按选择准备锁定容器镜像，未选择的 CLI 不安装。标准模式使用完整 `dsh-base + dsh-sdk-app`，保留原生文件/终端工具；官方任务文件、测量与提交走 `task_bash` / qsim 桥，原生 shell 是独立临时工作区。三个 Harness 均以新上下文运行，无个人会话或 Meta 研究材料。

基线装配通过后，后台还会继续准备选定的参考 Harness 镜像。全部准备完成后才可点击「启动进化」；准备期间按钮显示等待状态，直接请求启动也会被拒绝，此时活动不开始计时、不预留实验、不调用模型。若显示准备失败，在「后台动态」查看准备记录；仅有 H0 检查通过不代表整个活动已就绪。

Claude Code 使用 `dontAsk` 配合显式工具授权：原生终端、文件与研究辅助工具，以及本次冻结的 task/qsim MCP。未授权操作由 CLI 拒绝，不使用 `--dangerously-skip-permissions`。这同时兼容普通 Docker 用户和单 UID Podman 的容器 UID 0；宿主普通用户映射、禁网、只读根文件系统和禁止提权等隔离条件保持不变。此启动策略进入冻结运行时，新活动采用新策略，历史冻结参考运行不热替换。

Codex 外部通道支持明确 API Key 的 Responses 服务，以及固定 Solver 或原生参考模型为 `openai-codex` 时的原有 Codex 订阅通道。原生参考模型仍从 Models 配置读取；在 `llm-pi-ai` 配置 `openai-codex` 和准确模型列表，沿用宿主 `~/.codex/auth.json`（或 `PHYEXP_CODEX_AUTH_FILE`），无需再次填写 Key。此绑定禁止覆盖 API、端点和认证头，目录只保存宿主认证句柄；每次运行重新读取有效访问令牌，不复制刷新令牌、不进入 Runner。登录缺失或即将过期时目录显示不可用；刷新宿主登录后重新读取目录。该订阅接口不支持 `max_output_tokens`，因此每次输出没有此参数的硬上限，仍受时限和共享软预算约束。Claude Code 要求 Messages 服务，DeepSeek 原生 Messages 可用于 Claude Code。其他原生账户配置、自定义推理 wire 值等不能准确恢复的组合标为不支持/未核验，不换默认模型或近似协议。完整支持边界见[设计第 13 节](../design/meta-reference-experiments.md#13-当前实现版本与已声明限制)。目录“可组合”表示适配器协议/配置检查通过，不表示已对每个真实服务发起在线测试。

参考运行共享活动的轮次、次数、并发、时限和 token 总账，可附加模型/Harness 子额度；联合运行在总账只计一次，但同时受两项子额度约束。H0 先预留，参考结果独立保存，不能直接抬高主线排名或稳定完成率。运行详情、报告和证据入口按模型参考、Harness 参考、联合参考分组；联合变化不能单独归因。

工程检查（使用脚本模型响应，不产生真实模型调用）：

```sh
npm test
npm run build:workbench
python3 scripts/check-boundaries.py
# 需要可用的 Docker 和已准备的基础 Runner 镜像；依赖从锁文件安装。
npm run test:references
npm run test:contracts
```

`test:references` 先执行 `scripts/reference-images.py`，将三种精确镜像回执写入本地 `.runtime/reference-acceptance/images.json`，然后运行独立插件、控制器、原生桥和真实 CLI/SDK 的容器契约。基础镜像可用 `python3 scripts/reference-images.py --base <已验证镜像>` 指定。普通契约测试在可选镜像尚未准备时明确跳过这三项；专项命令负责准备并执行，不把跳过记为通过。

完整 Harbor 工程链路需要旁边的原始 Quantum-Harbor、官方任务镜像与当前源码匹配的任务锁；锁定方式沿用前文任务镜像准备流程。选取 `time_budgeted_hamlearn_10q` 的单任务锁保存成独立 JSON，然后运行：

```sh
python3 tests/contracts/harbor-score-pipeline.py \
  --quantum-harbor ../Quantum-Harbor \
  --task-image-lock /absolute/hamlearn-image-lock.json \
  --output /absolute/new-reference-acceptance \
  --reference --native-meta
```

该夹具在新数据目录内运行联合参考、由真实原生 Meta 的脚本策略选择模型参考、读取完整证据、开发/检查/冻结插件并提交后续主线验证。科学产物故意不提交，官方零分用于验证归档、计分隔离及用量；不能据此宣布模型或插件有效。Codex、Claude Code 的真实 CLI/MCP 工具回环分别由专项容器契约覆盖。这个夹具本身不产生真实模型调用。

### 受控真实模型验收

`tests/smoke/references/run.py` 是另一个显式付费入口，不包含在 `npm test` 中。每次运行创建新数据目录，复制宿主供应商设置，使用已有 DeepSeek 凭据建立独立的原生 SDK 测试 profile；模型 ID 和有效调用设置由原生 SDK 解析，不修改日常 Models 配置。Codex 使用现有宿主订阅登录，固定 SSE 传输。所有凭据留在权限受限的宿主目录。

```sh
python3 tests/smoke/references/run.py --execute-real-models \
  --scenario joint \
  --provider-data /absolute/host-data \
  --quantum-harbor ../Quantum-Harbor \
  --task-image-lock /absolute/hamlearn-image-lock.json \
  --reference-images /absolute/reference-images.json \
  --output /absolute/new-real-acceptance
```

`--scenario model` 只启用模型插件，固定 Flash 基线与原生目录中的 V4 Pro 参考；`harness` 只启用 Harness 插件，用固定 `gpt-6-luna` 运行 Codex；`joint` 启用两者，让真实 Meta 从原生参考模型与 Claude Code／DeepSeek 标准模式中选择并提交两项组合。选择回合结束后通过有记录的暂停/恢复停止额外 Meta 分析，已选参考继续执行；验收脚本核对冻结的可选包、工具调用、官方评分、证据摘要、逐次及总账用量、主线计分隔离。

默认 `--task-mode smoke` 只在新任务副本中改写 `instruction.md`，要求一次命令和一次 qsim 目录调用后结束，不提交科学答案。脚本核验其余源文件不变，沿用原有任务材料、模拟器及官方验证器的固定镜像，单独冻结任务来源；预期官方 `no_submission / 0`。这证明真实模型的工程链路，不代表完成原始科学任务。`--task-mode official` 使用未修改的原始任务，可能先耗尽额度；失败和未评分必须保留，不能与烟测零分混为一谈。

独立场景的共享软阈值为 500,000 tokens，联合场景为 650,000；每次请求仍预留 300,000，允许的已确认用量因此显著低于阈值。参考另有子额度，单次总时限 450 秒（含 330 秒评分/清理保留），不整次重试。软阈值不是硬 token 或金额上限；未知用量继续占用预留。单个失败活动不可通过清空账本续跑，每次追加验证都要连同之前失败一起汇总成本。账本不提供经过核实的美元账单。

真实烟测已覆盖两个独立插件、真实 Meta 组合选择及三个首期 Harness；无类型头的 Codex SSE、外部 CLI 用量汇总和预算拒绝归因均有回归测试。服务可用性、原始科学任务成功率、长期自主分析质量、压缩/委派压力和跨任务统计收益仍不由这些烟测证明。原始轨迹、失败尝试及实际用量只保存在本地验收记录中。


### 工具结果体积与协议更新

`meta-tools-v5` 引入的输出边界由当前 v7 继承：业务回执只含状态、简短说明和文件入口；完整结果、错误、停止审查及恢复核对结果保存在活动材料与输出目录。使用 `tool_result_read` 按 Unicode 字符分页读取大文件，后续页使用返回的 `nextOffset` 和 `sha256`。原生会话查询的巨型事件同样转为文件入口。输出容量耗尽会明确保留部分状态，不能把缺少文件的回执当作完整证据。

更新部署时，先核对活动、运行中的 Trial、Meta 会话及模型请求。存在在途任务时将新版同步到独立发布目录，保留当前服务的工作目录与冻结运行包；仅同步代码不会让既有进程或旧活动自动切换协议。切换后台服务应在没有在途任务的维护窗口进行，并重新核对冻结版本和未结算请求。不要直接覆盖活动中服务正在校验的协议源文件，不要通过重启替换活动的冻结组合。

收到服务端 `CONTEXT_WINDOW_EXCEEDED` 后，网关保留失败审计与用量核对，同时允许原生 SDK 发起压缩；它不触发新的宿主重试循环。压缩和压缩后的模型请求仍检查固定路由、额度、取消及截止时间。只有同一会话完成压缩且后续正常请求成功，才将此溢出记为恢复；压缩失败不能标记恢复。认证等终止错误仍会锁止后续请求。旧活动已冻结的网关代码与历史巨型事件不会自动被更新。

### 长活动的存储管理

新活动自动绑定 `storagePolicy=shared-artifacts-v1`；部署不修改旧活动，也不清空历史。原始实验、完整归档和证据索引引用 `artifacts/sha256/` 的同一不可变正文。后台在生产者退出且结果收集完成后，将原路径转换为硬链接视图，并保存 `artifact-archive.json`；原始路径、官方清单及摘要仍可核验。不要单独删除原始目录、证据目录或内容对象来省空间。

新活动的 `campaign_status` 使用 SQLite 一致读取事务，返回 `query-tree-v1` 根清单。根的 `data` 字段可能内嵌值，也可能是 `{format, file}` 引用；按 `file.path` 读取，检查 `file.sha256`，再按节点 `kind` 处理：`object.fields` 逐字段展开，`list.shards` 逐片读取并按 `items[].position` 排序，`value.value` 为原值。旧快照仍可读，重复查询复用内容。原生脚本须依据 `format`/`reading` 遍历；不能假定整个活动仍内嵌在单个 JSON 文件中。写操作仍校验修订。

受管 RPC、网关审计与输出日志每约 8 MiB 关闭一段，gzip 无损压缩并登记在 `<日志名>.segments/index.json`。原日志名是当前尾段，完整日志是有序关闭段加尾段。宿主计量、回放及 `meta_file_read` 逐段读取历史，避免一次性展开整份日志；直接用原生 read/grep/bash 读尾段不会自动包含旧段，应依照段清单逐段解压，或使用宿主 `src/execution/host/log_store.py` 的 `iter_log` / `iter_log_lines`、`.mjs` 的 `readLogChunksSync` / `readLogLinesSync`。证据索引公开段清单、每个压缩段和尾段，`evidence_read` 可解压单个 gzip 证据。原生会话持久文件不轮转。RPC、网关审计与 stderr 不设单份逻辑日志的累计 256 MiB 上限；它们受下方活动、全局容量与磁盘水位保护。单次写入最多 256 MiB，大记录独占一段；每次写入保留至少 64 MiB 紧急余量。终端/工具输出捕获器仍保留其显式总额度。

存储故障通过 `storage_capacity`（实际空间保护）、`log_size_limit`（显式输出日志额度）、`log_record_size_limit`（单条记录大小）或 `storage_write_error`（写入错误）保存。Meta 和执行端保留先行故障，退出时产生的 `request_cancelled` 只作为附带诊断，不替代根因。新行为随新冻结运行时生效；仅更新源码或后台不改变旧活动的冻结代码，也不改写既有失败记录。

容量策略保存在数据目录 `storage-policy.json`，用户可在活动页「容量趋势与存储上限」调整常用阈值；完整策略通过带用户凭证的 `GET /storage`、`POST /storage/policy`（也支持 PUT）读取和修改。Meta 凭证不能修改策略。

| 策略字段 | 默认值 | 含义 |
|---|---:|---|
| `maxDataBytes` | 40 GiB | 数据目录实际占用上限，硬链接只计一次 |
| `maxCampaignBytes` | 20 GiB | 每个新活动的归属数据上限，共享正文可归属多个活动 |
| `minFreeBytes` / `criticalFreeBytes` | 10 / 2 GiB | 启动保护线 / 停止在途生产者的紧急水位 |
| `resumeMarginBytes` | 1 GiB | 从等待恢复时的额外余量 |
| `trialReserveBytes` / `metaReserveBytes` | 512 / 256 MiB | 每个在途试验 / Meta 会话的收尾预留 |
| `scanSeconds` | 60 秒 | 深度统计与后台整理间隔 |
| `garbageGraceSeconds` / `cacheAgeSeconds` | 6 / 24 小时 | 无引用对象 / 旧缓存代际的最小保留时间 |
| `additionalPaths` | `[]` | 另需检查的容器等存储目录，按实际文件系统去重 |

字节字段使用整数；日志分段目标、单次写入界限和输出捕获额度属于宿主处理边界，不由上述 API 修改。审计日志累计增长只受总存储策略约束。容量不足时阻止新试验、Meta、构建和模型请求；模型请求在现有截止时间内等待，不消耗新的 token 预留。释放空间或调整容量后恢复，不延长墙钟。正在运行的试验与会话占用收尾预留；磁盘跌到紧急水位时后台请求停止，保留部分输出及原因。任意工作区写入尚无操作系统硬配额，极快写入或其他程序占盘仍可能先于巡检耗尽空间。

后台仅回收宽限期外、无数据库/归档引用且无硬链接视图的对象，以及已过期的对象发布临时文件。依赖/适配缓存只清理非当前代际，且须无活动任务、无进程引用、无文件视图引用并取得构建锁。冻结镜像、当前依赖、会话、研究证据不按年龄或分数删除；无法判断使用状态则跳过。自动整理异常在活动存储面板显示。容器存储监测实际空闲容量，不按镜像累计虚拟大小估算，也不自动执行镜像 prune。

增长预测至少需要一小时观测，重启重新积累；没有有效正增长时不提供剩余时长。有限磁盘不能保证任意一周活动持续产出，等待存储是保护状态。外部归档、历史迁移及历史清空不属于本次更新。

### 单次活动永久删除

活动详情的「更多操作 → 删除活动…」提供永久删除。确认框显示活动名称、实验、候选、报告修订及导出数量。有在途工作时使用「停止并永久删除」；后台停止所属 Meta、子会话、主线与参考实验，等待构建、导出和下载结束后，删除配置、会话、研究记录、证据、轨迹、用量、报告全部修订和平台内导出。不会为删除启动新的总结或模型请求。

支持草稿、运行中、暂停、收尾、失败和已结束活动，兼容 v1/v2/v3 冻结组合。新版候选的专属源码、构建产物、构建回执及缓存也随最后引用删除；仍被其他活动引用的内容保留。预检查会核对整个数据目录的共享归属，历史较多时需要等待，工作台允许核对和提交各等待最多 120 秒；超时后先查看状态，不能将超时当作删除成功或自动重复提交。

打开删除确认框后，活动状态自动刷新暂时暂停，关闭后恢复，减少手机网络上的大响应竞争。核对期间可以取消；尚未点击「永久删除」或「停止并永久删除」就不会受理删除。浏览器端核对超过两分钟会显示超时及「重新核对」，不再无期限等待。已经点过最终删除按钮的请求若超时，应先刷新检查后台任务状态。

删除受理后不能恢复运行。页面显示停止、清理或失败原因；关闭页面不取消后台任务，重启后台继续尚在执行的删除任务。失败时活动保持可见，处理错误后点击「重试删除」。只有完整清理成功才从列表移除，并清空当前选择及活动阅读缓存。

其他活动通过历史来源功能纳入了此活动的证据或报告时，会列出依赖并禁止删除，包括「仅用户阅读」的副本。当前版本不自动改写其他活动的研究依据，也不提供解除引用功能。共用的执行插件、Meta 对象、资料包及归档正文按剩余引用保留，最后引用删除后回收；公共依赖、任务与 Runner 镜像、供应商凭据保持可用。用户另行下载或复制的文件、外部备份不随之删除。

旧数据若包含无法确认归属的导出检查、混合数据库备份、越界路径或未知硬链接，会报告具体原因，不能以隐藏活动代替成功。发生文件或容器清理失败时应恢复文件权限/容器引擎、处理占用后重试。清理阶段可能短暂拒绝其他请求，等后台完成后重试即可。删除是受管记录和文件的永久移除，不承诺存储介质取证级擦除。

接口仅接受用户凭证：`GET /campaigns/{id}/deletion` 返回预检查或当前任务；首次 `POST` 提交 `{expectedRevision, idempotencyKey}`，失败后以新键及 `retry: true` 重试。活动修订变化会拒绝旧预检查，重新核对后再确认。完成后只保留活动 ID 和旧创建请求摘要等防重标记，不保留历史正文。

源码更新后运行 `npm run build`，在无在途任务的维护窗口更新后台及工作台；数据库启动时自动创建版本 6 的删除任务与文件归属表。没有对现有活动执行自动删除。隔离验收入口：`python -m unittest tests.unit.campaign_deletion_test`、`python tests/smoke/campaign_deletion.py`（需要本地 Runner 镜像及 Docker）；追加 `--build-image <已有的 shell 镜像>` 可验证真实 v3 构建、缓存登记和最后引用清理；浏览器夹具为 `tests/fixtures/deletion_workbench.py --data-dir <空的测试目录> --port <端口>`。这些检查均不调用真实模型，完整实现与边界见[删除设计](../design/campaign-deletion.md)。

### 控制数据库并发与报告发布

控制数据库继续使用 SQLite WAL。Meta 调用的身份核验与审查状态查询不再申请写锁；实际写操作仍在各自事务中核验权限与状态。报告正文先在受管目录生成，短写事务内重查请求身份和修订，再原子替换文件并提交记录。并发修订有冲突时按原规则拒绝，重复请求返回原报告；中途失败不登记未完成报告，崩溃遗留文件归所属活动清理。启动时数据库版本 7 增加报告范围及请求身份索引，不修改旧报告正文。

写锁最多等待 30 秒，仅在 `BEGIN IMMEDIATE` 尚未成功时退避重试，不重放事务正文、构建或模型调用。锁等待或事务耗时达到 1 秒，以及 SQLite 错误，会向后台日志写出 `control_transaction`：含事务 ID、调用位置/操作、进程/线程、等待和持锁时间、尝试次数、结果及 SQLite 错误码，不记录 SQL 参数、模型正文或凭据。可据此定位慢写入；不能仅凭一次忙错误断定是并发上限导致。

离线回归入口：`python3 -m unittest tests.unit.database_concurrency_test`。覆盖 15 路并发候选登记、状态查询、含较大事实快照的报告保存与重复请求，以及渲染阻塞、文件发布失败、修订冲突、事务回滚和只读调用不等待写锁；不代表真实模型长活动的稳定性验收。

### 容器命令结果与连接异常

新冻结执行包为每次容器命令分配宿主调用 ID，`container-exec.jsonl` 的开始/结束记录可准确配对；`phyexp/container-transport.json` 保留接收、执行、证据写入、回传及关闭阶段的异常与后续连接恢复标记。执行结果已完整记录后的回传/关闭异常不再单独阻止正常退出的 Solver 进入官方评分；没有执行的无效命令也不算环境故障。命令执行抛错、执行中被取消或审计写入失败仍阻止评分，后续另一条命令成功不会抹去原来的不确定结果。

Worker 结束后先关闭桥接入口并记录尚未完成的调用，再作评分准入判断。平台不会为恢复连接而自动重放容器命令，也不会把 `accepted` 文本当作官方得分。回归入口为 Harbor Python 环境中的 `python -m unittest tests.unit.bridge_recovery_test tests.unit.harbor_adapter_test tests.unit.benchmark_time_test`。旧冻结包不热替换，已有失败记录和评分不回填。

### HTTP 状态丢失时的请求恢复

网关在错误分类前补入当前逻辑请求中可明确归属的 HTTP 状态和 `Retry-After`。适配器仅返回通用错误、但同一请求的唯一 HTTP 尝试返回 503 时，按模型服务故障进入现有 Solver 请求恢复；不会借用其他并发请求、包含多个 HTTP 子请求的链路或先前 HTTP 尝试后已切换到 WebSocket 的状态。适配器明确的状态和上下文/凭据等非瞬时错误优先，HTTP 4xx 不进入此恢复路径。

仍只重试当前模型请求，沿用已冻结的五次等待、原任务截止时间、取消和访问检查；不重放已完成的工具调用，不增加试验次数，也不自动重启整个活动。旧冻结包不升级。回归使用本地 HTTP/WebSocket 服务和实际 SDK 适配器，不访问真实模型供应商；包括缺失状态的 503、并发归属、歧义链路、401/403、重试耗尽与截止时间。

### 故障层、恢复与评分的读取展示

实验详情增加独立的故障层与评分影响：模型输出链路、模型服务或连接、平台执行/控制、运行限额/停止、正式评分未通过，以及原因待确认。输出异常仅说明模型/适配器链路的观测现象，不直接断定模型权重有问题；连接异常不作为解题能力的直接证据。请求恢复记录与最终故障分开，容器连接警告保留调用阶段和是否阻断评分。已取得官方分数的记录继续使用该分数，未评分保留空值；任务完成分沿用活动绑定规则，历史 v1–v4 不升级、不回填。

一般控制 API 的数据库忙错误使用 HTTP 503、`control_database_busy` 和 `retryAfterMs: 500`；其他数据库异常为 `control_database_error`。Meta 工具即使无法发布诊断文件，也可返回这一故障码。写请求结果不确定时仍要求以原参数、原幂等键核对，不能换键重复提交。仅旧 `/accounting/` 兼容接口保留 `accounting_unavailable` 错误码；一般控制故障不再称为用量账本故障。

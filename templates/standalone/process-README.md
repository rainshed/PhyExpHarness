# 完整执行 Harness 独立包

这是同一个已冻结候选的交付包：`candidate/` 保存源码、`candidate.tar` 保存隔离构建产物，`bundle.json` / `objects.json` 绑定全部身份和摘要。候选负责框架、依赖、入口、工具、会话、提示和恢复。平台接入代码只部署、监督、提供固定 Solver 模型通道并收集官方评分。不得直接改这个包后沿用原摘要；开发新候选应重新 check/freeze。

运行需要 Linux 容器引擎、Python 3.13、外部 Quantum-Harbor 和已准备好的任务镜像。宿主不安装候选的 npm/Python 依赖，不加载候选代码。模型代理镜像由 `recipe.json.processResources.brokerImage` 指定，必须准备相同的不可变镜像。Python 依赖安装：

```sh
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.lock
.venv/bin/python run.py --verify
```

使用当前 ChatGPT 登录时设置 `PHYEXP_CODEX_AUTH_FILE=/path/to/auth.json`（默认 `~/.codex/auth.json`）；API Key 路由从 `recipe.json.providerConfig.auth.env` 指定的变量取密钥。凭据不放进交付包，只进入可信模型代理；候选得到仅限本 Trial 的短期通道。认证须覆盖完整运行期限。HTTP/SSE 支持原生 Responses、Chat Completions、Anthropic；当前不提供 WebSocket，候选须选择已支持的传输。

```sh
.venv/bin/python run.py --quantum-harbor /path/to/Quantum-Harbor --task TASK \
  --task-image-lock /path/to/TASK.image-lock.json --output /path/to/new-run --timeout 22000
```

任务来源和镜像必须与锁一致。运行环境须满足包内声明的 Docker/Harbor 依赖与镜像身份。Podman 单 UID 环境须沿用同版本兼容客户端和 `PHYEXP_CONTAINER_RUNTIME=podman-single-uid-v1`；这属于外部运行条件。输出目录必须不存在。配方 timePolicy 为 benchmark-time-v2 时，允许运行期限短于 benchmark 原生阶段上限之和；任务原始上限保持不变，实际求解与评分受 --timeout / --deadline 硬截止约束。准备耗时会减少活动剩余窗口，不自动延期。旧 benchmark-time-v1 配方仍要求完整阶段预留。单次入口只启动一个 Trial，不隐式重试。

候选在 Harbor main 的 `/opt/harness` 中启动，工作区 `/app`；`PHYEXP_CONTEXT` 指向本次公开运行上下文。main 只能连接任务侧车与模型代理。退出、到期或取消时收回候选子进程和模型通道；官方 verifier 按 Harbor 原生生命周期运行。

`summary.json` 分别记录 `execution`、`officialResult`、`evidenceStatus`、`comparison`；benchmark-time-v2 还记录 `timing` 中的任务上限、启动可用窗口、求解开始时剩余时间和实际阶段耗时，未知耗时保留 null。执行异常可以与官方分数并存；没有可信官方文件时评分是 null，不能伪造为官方零分。原始文件与来源摘要保留在运行目录。重新读取已有官方结果不调用模型：

```sh
.venv/bin/python run.py --collect /path/to/existing-run
```

`--verify` 只核对内容，静态搬迁检查也不是科学测试。真实独立运行的状态以导出验收记录为准。运行无需原 PhyExpHarness 仓库、控制数据库、Meta、工作台或原对象存储。

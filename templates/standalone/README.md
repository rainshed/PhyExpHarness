# 独立执行 Harness

本目录是经过测试的冻结执行项目。身份和文件摘要见 `bundle.json`，配置见 `recipe.json`，选中的插件见 `plugins/`。不依赖原 PhyExpHarness 仓库或活动后台，不包含工作台、Meta 插件、报告历史或模型凭据。

需要 Node.js 24、Python 3.13、Docker，以及外部 Quantum-Harbor checkout 和它的任务/官方 verifier 镜像。依赖安装：

```sh
npm ci --ignore-scripts
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.lock
node install-runner.mjs
```

认证按 `recipe.json` 中的 provider 选择。GPT 模型提供现有 ChatGPT 登录文件的路径（不复制进本项目）：`PHYEXP_CODEX_AUTH_FILE=/path/to/auth.json`。未设置时从本机 `~/.codex/auth.json` 读取。短期令牌在固定宿主使用，隔离 Runner 和实验工具不能读取。

如果 provider 是 `deepseek-official`，在启动本项目的终端设置 `DEEPSEEK_API_KEY`，无需 Codex 登录。密钥仅供宿主使用，勿写入项目文件；端点和能力见冻结的 `recipe.json`。`deepseek-flash` 是滚动别名，目前对应 V4.1 Flash 1017，不能保证远端一直固定此版本。

自定义供应商同样从 `recipe.json` 的 `providerConfig` 读取适配器、协议、端点及模型能力，并按 `auth.env` 指定的环境变量读取 API Key；无需原目录配置文件或原仓库。未带路由快照的旧版本仍按其原实现运行。GPT 订阅继续使用 Codex 登录，不因配置其他 API Key 改变。

```sh
.venv/bin/python run.py --quantum-harbor /path/to/Quantum-Harbor --task <任务名称> --output /path/to/new-run --timeout 3600 --soft-token-limit 3000000
```

将 `<任务名称>` 替换为外部 Quantum-Harbor 的 harbor_tasks/ 中实际任务目录名；工作台的「查看运行说明」提供与导出活动匹配的命令。可用 `--soft-token-limit none` 不单独限制 token，仍受时间上限约束。

输出必须是尚不存在的新目录。单次执行 1 Trial、无自动重试；启动失败也留下证据。时间上限涵盖环境准备、模型、评分和收尾；用量阈值是软停止阈值，订阅 provider 不提供经过验证的输出硬上限。运行期固定模型配置不能由插件更换。终止或连接故障的未知用量单独保留。

`summary.json` 区分官方 0 分、未评分、无效提交和基础设施失败。评分由 Quantum-Harbor 官方 verifier 产生。插件只在 Runner 中加载。模型、Harbor main/qsim、官方 verifier 的身份及原始证据会单独记录。

`python run.py --verify` 只核对内容，不调用模型。包已生成不等于真实独立运行验收已通过；交付验收状态应以外部导出报告为准。

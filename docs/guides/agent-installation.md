# 让 Agent 安装并运行项目

适用：macOS/Linux 本地源码、标准 Docker 与外部 Quantum-Harbor。Agent 从仓库根目录执行命令；安装、自检、查询与环境准备不调用真实模型。操作规则与[快速开始](quickstart.md)、[模型配置](models.md)共用，外部任务准备见[Quantum-Harbor 指南](quantum-harbor.md)。

## 必要输入

确认源码目录、非同步的本地数据目录、Quantum-Harbor 绝对路径。真实实验还需用户指定可用的 Solver/Meta 和认证，保持模型与调用参数明确；安装器不猜测用户希望使用哪个模型。

需要 Node.js 24.13+（24.x）、Python 3.13、Git。完整实验还需要 Docker Linux 容器与 Compose、Quantum-Harbor 基础镜像。系统软件安装、Docker 首次启动和交互登录按本机条件完成；项目入口会报告缺项，不自动改机器全局配置。

以下 `/absolute/...` 是用户选择的实际路径，`PROVIDER`、`MODEL_ID` 是模型目录中的准确标识。使用已有目录时先核对用途，不覆盖或清理历史数据。

## 1. 安装项目

```sh
python3 scripts/phyexp.py setup --json
python3 scripts/phyexp.py doctor --project-only --json
```

setup 创建项目 .venv，按 requirements-control.lock 安装 Python，执行 npm ci、pip check、npm run build。回执与依赖匹配时复用安装并重建资料/UI；`setup --repair` 可强制重新安装项目依赖。已有 .venv 使用其他 Python 时明确失败，保留目录供用户处理。

成功判据：两个命令退出 0，JSON 的 status 为 passed。安装日志在 .runtime/setup.log；不提交回执或日志。项目检查不证明 Docker、模型或真实任务可用。

## 2. 准备并检查外部任务

按外部指南获取指定 Quantum-Harbor 源码、构建基础镜像，并完成官方 nop 无模型环境检查。随后设置本终端使用的数据目录：

```sh
export PHYEXP_DATA_DIR=/absolute/local-data
python3 scripts/phyexp.py doctor \
  --quantum-harbor /absolute/path/to/Quantum-Harbor \
  --task time_budgeted_hamlearn_10q --json
```

doctor 只读检查依赖锁、构建产物、目录权限、Docker/Compose、任务源码和基础 agent/verifier 镜像。每项返回 id、status、detail、nextStep。warning 需要核对但不算检查失败，例如任务源码有本地改动；failed 必须先处理。镜像存在不表示它与任意 checkout 可混用，创建活动仍会按正式冻结流程核验。

## 3. 启动并打开工作台

```sh
python3 scripts/phyexp.py start \
  --quantum-harbor /absolute/path/to/Quantum-Harbor --open --json
python3 scripts/phyexp.py status --json
```

需要文件配置模型时在 start 加 `--model-config /absolute/models.json`，按[模型指南](models.md)填写非敏感字段；环境变量凭据须在启动后台前设置，也可在工作台保存供应商凭据。安装入口不自动读取 .env。

start 等待后台与工作台就绪，并实际通过已认证的 UI 桥核对后台身份。成功输出 control=ready、ui=ready、工作台地址、数据目录和日志位置。`--open` 打开本机认证链接并导航到研究工作台；无桌面浏览器时使用输出中的本地 loginFile。该文件与 workbench.log 含本机登录凭据，只保存在私有数据目录，不复制进报告、聊天或 Git。普通 JSON 输出不含登录令牌。

源码目录、数据目录和 Quantum-Harbor 身份必须匹配，重复 start 复用同一实例。默认端口被占用时可显式传入不同的 `--control-port` 与 `--ui-port`；不会终止未知进程。配置保存到数据目录 onboarding/local.json，后续命令复用。优先级为命令行 → 对应环境变量 → 已保存配置 → 默认值；数据目录本身按 --data-dir / PHYEXP_DATA_DIR / 系统默认定位。PHYEXP_CONTROL_URL 与后台端口必须一致，本地命令只连接回环 HTTP。

源码更新不会热替换后台/UI。没有未结束活动或在途归集时，可执行 `python3 scripts/phyexp.py stop-local` 关闭本入口管理的进程，再启动新版本。关闭网页或退出本地命令不会停止活动。

## 4. 明确模型与首次实验配置

```sh
python3 scripts/phyexp.py models --json
python3 scripts/phyexp.py tasks --json
python3 scripts/phyexp.py experiment init --session first-experiment \
  --solver PROVIDER SOLVER_MODEL_ID --meta PROVIDER META_MODEL_ID \
  --task time_budgeted_hamlearn_10q --json
```

models 返回可用模型、推理等级和认证状态；configured 只表示凭据存在且通过本地状态判断，不证明远端调用已经成功。用户需要其他供应商时先在工作台或启动文件配置，再查询准确标识。`--solver-effort`、`--meta-effort` 可显式选择支持的推理等级，省略时记录目录的默认值。

init 只在本地写入首次实验计划与请求身份，不创建后台活动。配置固定一个任务、并发 1、最多一次 Trial/一轮，要求 Meta 优先使用已有 H0，读取评分与证据后总结。总时间默认参考 API 返回的 benchmark 阶段上限之和加 1800 秒；这只是初始建议，不承诺实际耗时。可用 `--wall-time 秒数` 指定任意正整数活动时间，短窗口也允许尝试；benchmark 未设有限上限时必须显式指定。任务原始求解上限不改写，活动硬截止可能提前中断实验。

**核对 init 输出的准确模型、推理等级、任务、次数和总时间后，才进入准备及真实启动。** 这不是活动费用硬上限；外部费用控制见模型指南。

## 5. 准备与显式启动

```sh
python3 scripts/phyexp.py experiment prepare --session first-experiment --json
```

prepare 通过用户 API 创建活动，后台异步构建固定任务镜像及 H0。状态 pending / 退出 3 表示尚在准备，间隔一段时间用同一条命令查询；passed 且 preparation=ready 才能启动。failed 时查看返回的 operations 与活动 checks/task-images.log，保留原 session 与失败记录。

```sh
python3 scripts/phyexp.py experiment start --session first-experiment --json
```

**start 开始真实模型工作，可能产生费用。** 该命令的 passed 表示启动已受理或同一活动已启动过，不表示实验已通过。它不会恢复暂停活动或重启已结束活动。模型认证缺失/过期时按指南修复；使用后台环境变量认证的进程需在合适窗口重新启动才能读取新环境。

## 6. 等待、核验与交付

```sh
python3 scripts/phyexp.py experiment status --session first-experiment --json
python3 scripts/phyexp.py experiment wait --session first-experiment --timeout 30 --json
```

wait 每次等待 1–60 秒，仅轮询原活动；超时仍为 pending，不取消或重复运行。可反复调用并向新人报告进度。Meta 提问或 needs_attention 应在返回的工作台中处理，Agent 不擅自替用户回答实验选择。

status/wait 的 passed 要求活动已正常结束，至少一个真实 Trial 完成评分、证据索引完整，官方 reward/score_report 文件可读且与后台记录摘要一致。命令复用后台官方结果，不重新计算科学分数。零分可以满足工程链路验收；缺失评分、文件变化、证据未完成不能当作通过。trialAcceptance 单列 Trial 状态，campaignState 单列活动状态。

打开 workbenchUrl 可直接选择该活动；若浏览器尚未建立宿主会话，先执行 start --open 或使用 loginFile 登录，再打开活动链接。在工作台核对实验记录、评分和证据；CLI 的文件核验不替代实际浏览器查看。

最终向新人交付数据目录、工作台地址、活动/Trial ID、实际模型与运行限制、官方评分文件及证据状态。明确区分安装通过、环境通过、真实实验结果和浏览器检查；保留尚未完成的项。

## 重试与退出状态

所有命令支持 --json。结构化结果包含 schemaVersion、command、status，experiment 还包含 operation；失败包含错误 code/message/nextStep。退出码 0 表示当前命令的完成条件满足，1 为检查/运行失败，2 为参数错误，3 为仍在进行、操作被占用或请求结果未知，130 为本地命令被中断。

session 存于数据目录 onboarding/experiments。相同名称与配置重复 init 复用原计划；不同配置明确拒绝。创建和启动的请求身份先持久保存再发送，响应丢失后同一 session 重试不会创建第二次实验。不要编辑/删除回执、换 session 或清空目录来处理未知结果。目录修订发生冲突时先核对供应商设置；已有活动继续使用冻结模型。

常见恢复：缺依赖重跑 setup；Docker 不通先恢复引擎；端口/数据身份不符先查 status；启动超时查询原进程和日志；活动准备失败查看 operations；模型认证问题保留原活动；实验未评分查看官方产物与归集状态。活动其他操作仍使用[活动指南](campaigns.md)。

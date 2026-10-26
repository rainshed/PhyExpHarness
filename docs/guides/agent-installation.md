# 让 Agent 安装并运行项目

适用：macOS/Linux 本地源码、标准 Docker 与外部 Quantum-Harbor。Agent 从仓库根目录执行命令；安装、自检不调用真实模型。操作规则与[快速开始](quickstart.md)、[模型配置](models.md)共用，外部任务准备见[Quantum-Harbor 指南](quantum-harbor.md)。

当前 setup/doctor 已提供；统一启动、活动命令和首次实验验收仍按[实施计划](../plans/agent-installation.md)推进。以下仅列出当前存在的命令。

## 必要输入

确认源码目录、非同步的本地数据目录、Quantum-Harbor 绝对路径。真实实验还需用户指定可用的 Solver/Meta 和认证，保持模型与调用参数明确；安装器不猜测用户希望使用哪个模型。

需要 Node.js 24.13+（24.x）、Python 3.13、Git。完整实验还需要 Docker Linux 容器与 Compose v2、Quantum-Harbor 基础镜像。系统软件安装、Docker 首次启动和交互登录按本机条件完成；项目入口会报告缺项，不自动改机器全局配置。

## 安装项目

```sh
python3 scripts/phyexp.py setup --json
python3 scripts/phyexp.py doctor --project-only --json
```

setup 创建项目 .venv，按 requirements-control.lock 安装 Python，执行 npm ci、pip check、npm run build。回执与依赖匹配时复用安装并重建资料/UI；`setup --repair` 可强制重新安装项目依赖。已有 .venv 使用其他 Python 时明确失败，保留目录供用户处理。

成功判据：两个命令退出 0，JSON 的 status 为 passed。安装日志在 .runtime/setup.log；不提交回执或日志。项目检查不证明 Docker、模型或真实任务可用。

## 检查实验前提

按外部指南准备 Harbor 后运行：

```sh
python3 scripts/phyexp.py doctor \
  --data-dir /absolute/local-data \
  --quantum-harbor /absolute/path/to/Quantum-Harbor \
  --task time_budgeted_hamlearn_10q --json
```

doctor 只读检查依赖锁、构建产物、目录权限、Docker/Compose、任务源码和基础 agent/verifier 镜像。每项返回 id、status、detail、nextStep。warning 需要核对但不算检查失败，例如任务源码有本地改动；failed 必须先处理。镜像存在不表示它与任意 checkout 可混用，创建活动仍会按正式冻结流程核验。

随后按[快速开始](quickstart.md#启动后台与工作台)启动，再按[活动指南](campaigns.md)创建活动；这些步骤尚不由上述两个命令代替。

## 结果与恢复契约

全部命令支持 --json。结果包含 schemaVersion、command、status；失败包含错误 code/message/nextStep，检查命令逐项列出检查结果。退出码 0 表示该命令的完成条件已满足，1 表示检查/运行失败，2 为参数错误，3 为仍在进行或同一操作被占用，130 为本地命令被中断。

保留首次失败和日志；缺依赖时修复后重跑 setup/doctor，不清空数据目录。安装检查通过不意味着模型请求成功，官方零分、未评分、基础设施失败必须分别记录。最终交付给新人应包括数据位置、工作台入口、实际活动/Trial ID、评分与证据位置，以及未完成的验收项。

# 准备 Quantum-Harbor

PhyExpHarness 使用外部任务源码、标准 Docker Linux 容器和官方 verifier。项目 Python 锁提供 Harbor 0.18.0；Quantum-Harbor 自身的 uv 环境独立维护，不将两个环境混装。

上游为 [GaugeForge/Quantum-Harbor](https://github.com/GaugeForge/Quantum-Harbor)，本流程对接源码基线为 `1f03d78e959cf02469568250f61f9af88a53146f`。这是可复现的准备基线，完整新机容器与真实模型验收状态见[安装实施计划](../plans/agent-installation.md)；不能从源码版本推断所有系统均已验证。上游步骤来源为该版本 README 与 docs/getting-started/installation.md。

## 获取独立 checkout

准备 Git、uv、Python 3.13 和能运行 Linux 容器的 Docker（含 Compose v2）。在用户选择的工作目录执行；保留已有 checkout 的改动，不能为安装强制重置它。

```sh
git clone https://github.com/GaugeForge/Quantum-Harbor.git Quantum-Harbor
git -C Quantum-Harbor checkout --detach 1f03d78e959cf02469568250f61f9af88a53146f
git -C Quantum-Harbor status --short
```

记下该目录的绝对路径。后续 PhyExpHarness 命令显式传入它，不依赖两个项目恰好位于相邻目录。

## 首个任务的基础镜像

在 Quantum-Harbor 根目录执行：

```sh
uv sync --locked
docker info
docker compose version
docker build -t qiqcbench-agent docker/agent/
uv run --frozen python tools/build_qsim_images.py --tasks time_budgeted_hamlearn_10q
```

上游构建会下载数 GB 数据，时长取决于网络、CPU 和缓存。不要将一次机器上的耗时当作通用承诺。agent 与 verifier 镜像必须先准备；创建活动时 PhyExpHarness 再构建、固定 main/qsim 与 verifier 身份。换任务时按上游构建器的 --tasks 指定任务，再由环境检查核对其 task.toml 中的 verifier 镜像。

## 无模型环境检查

回到 PhyExpHarness 根目录，使用已安装的项目环境：

```sh
. .venv/bin/activate
npm run smoke:harbor -- --quantum-harbor /absolute/path/to/Quantum-Harbor
```

此命令运行官方 nop agent，不需要 API Key。通过表示一个 Trial 完成、官方 verifier 记录零分和未提交答案诊断；不能将缺失评分当作零分。输出报告保存在仓库本地 runs/smoke，不进入 Git。失败时保留日志，修复 Docker、镜像或任务来源后重试。

## 平台边界

本地主机入口面向 macOS 与 Linux，原生 Windows 当前不支持；Windows 用户需使用满足相同条件的 Linux 环境。任务镜像的 CPU 架构与 Docker 可用资源也必须匹配。主线不自动修改 Docker 的全局架构或资源设置，未在干净环境验证的平台不能标记为已通过。实验阶段时限由 benchmark 决定，不为加快安装验收缩短任务求解时间。

# 快速开始

适用：主线源码、标准 Docker/Harbor、本地数据目录。先了解[核心概念](../product/concepts.md)，详细命令来源为[package.json](../../package.json)。

Agent 可直接按[安装流程](agent-installation.md)执行 setup、doctor、start 和首次实验命令。主项目使用独立 Python 锁，后台与 UI 共用数据目录约定；各验证层次分别记录。

## 安装与构建

准备 Node.js 24.13+（24.x）、Python 3.13、可运行 Linux 容器的 Docker，以及显式指定的 Quantum-Harbor checkout。Harbor Python 依赖由主项目与独立包各自的锁固定为 0.18.0；DSH 由根 npm 锁固定为 0.2.1-rc.2。按[Quantum-Harbor 准备指南](quantum-harbor.md)获取指定源码并构建基础 agent/verifier 镜像，PhyExpHarness 不附带这些外部资产。

在仓库根目录执行：

```sh
python3 scripts/phyexp.py setup
python3 scripts/phyexp.py doctor --project-only
```

手动安装的等价步骤为：

```sh
npm ci
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r requirements-control.lock
python -m pip check
npm run build
npm test
```

build 生成 `knowledge/plugin-sdk/reference/` 和 Studio 的 `lib/client.js`；源资料、锁和构建脚本入库，生成目录不入库。npm test 使用假响应执行单元检查，不创建真实模型实验。容器契约另见[验证说明](../development/testing.md)。

## 启动后台与工作台

推荐统一启动；需要打开浏览器时加 --open：

```sh
python3 scripts/phyexp.py start --quantum-harbor /absolute/path/to/Quantum-Harbor --open
python3 scripts/phyexp.py status
```

统一入口记录本地进程与配置，验证后台和 UI 桥身份，重复执行复用实例。详细登录、重试与首次实验步骤见 Agent 安装流程。

手动启动仍可用。在已激活 Python 环境的终端启动后台：

```sh
python -m src.control.server --quantum-harbor /absolute/path/to/Quantum-Harbor
```

另开终端，在仓库根目录启动工作台：

```sh
node scripts/workbench.mjs
```

使用终端输出的登录链接建立本机宿主会话，再访问 `http://127.0.0.1:18401`，从侧栏进入「研究工作台」。后台默认监听 `127.0.0.1:18402`，独立于 UI 宿主运行。关闭网页不会停止活动。

主线 Solver/Meta 在工作台「供应商与模型」配置；可选参考模型才从 DeepSeek Harness 原生 Models 获取，详见[模型配置](models.md)。首次启动宿主的模型账号提示不等于已经配置本项目活动模型。

## 数据与连接配置

默认数据目录由[paths.py](../../src/control/paths.py)决定：macOS 使用 `~/Library/Application Support/PhyExpHarness`，其他系统使用 `$XDG_DATA_HOME/PhyExpHarness`，未设置时为 `~/.local/share/PhyExpHarness`。使用仓库外、非同步的本地目录。

自定义位置时两个终端设置相同的 `PHYEXP_DATA_DIR`；后台也接受 --data-dir。更换位置表示打开另一组数据，不会自动迁移旧活动。同一数据目录只能有一个后台所有者，文件锁拒绝重复启动。

| 配置 | 用途 |
|---|---|
| `PHYEXP_CONTROL_URL` | UI 桥连接的控制后台地址 |
| `PHYEXP_UI_PORT` | 工作台端口 |
| `PHYEXP_UI_HOME` | UI 宿主的独立目录 |
| `PHYEXP_UI_VARIANT` | UI 清单选择，默认 studio；维护规则见[工作台架构](../architecture/workbench.md) |
| `PHYEXP_UI_PUBLIC_URL` | 外部已提供的 HTTPS 根地址，也可用 UI home 下 workbench-access.json 的 publicUrl |

publicUrl 只接受无路径、查询、凭据和 fragment 的 HTTPS 根地址；空字符串禁用。启动器只信任声明的准确来源，浏览器经宿主会话访问 `/phyexp/api`，不取得后台令牌。外部代理、证书、网络和托管由部署侧提供；这项通用契约不构成多用户权限系统。

启动后依次[配置模型](models.md)、[创建活动](campaigns.md)。遇到准备失败、端口冲突或镜像缺失，查阅[维护与排障](maintenance.md)，不要通过另建数据目录掩盖原问题。

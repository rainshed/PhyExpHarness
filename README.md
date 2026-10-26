# PhyExpHarness

当前为 `deploy/tensortrain2` 部署分支，服务器更新与运行方式见[部署说明](docs/deployment/README.md)。

PhyExpHarness 研究如何在固定 Solver 模型与调用设置的条件下，通过改进执行 Harness 帮助模型完成任务，并让人理解改进过程。

Meta 使用通用 Agent 能力开发插件、组织完整候选工程、安排 Quantum Harbor 实验、读取证据并解释版本选择。候选拥有自己的框架、依赖、工具、上下文和恢复策略；平台负责固定模型、隔离、外部运行限制、官方评分与证据保存。选定候选可以导出为独立项目。

实验保留成功、失败、未执行和未评分的区别。插件用途、Meta 的判断和实测效果分别呈现；工程检查通过不代表科学效果或跨任务泛化已获证明。

主线维护项目功能、标准 Docker/Harbor 执行环境、本地证据存储及通用配置契约。具体机器的运行环境适配、远程存储、服务托管、网络接入和实例发布由独立部署分支维护。

- 了解目标：[设计哲学](docs/product/philosophy.md)、[产品要求](docs/product/requirements.md)。
- 安装使用：[Agent 安装流程](docs/guides/agent-installation.md)、[快速开始](docs/guides/quickstart.md)、[活动操作](docs/guides/campaigns.md)。
- 修改项目：[架构总览](docs/architecture/overview.md)、[开发流程](docs/development/workflow.md)。
- 查找专题：[完整文档导航](docs/README.md)、[实现核对表](docs/development/implementation-audit.md)。

历史活动、运行结果和本地验收日志不随源码提交；新克隆没有这些记录是正常的。

# PhyExpHarness

PhyExpHarness 研究如何在给定任务范围、固定 Solver 及其模型和调用设置的情况下，构建和优化执行 Harness，使它更好地帮助 Solver 完成科学实验任务，并让人理解这一改进过程。

我们遵循 DeepSeek Harness 的 “Everything is Plug-in” 原则，从最小可运行的执行 Harness 出发，让 Meta Harness 自主设计职责清楚的执行插件。具体的插件版本及其配置组成不同的 Harness 版本，通过可比较的任务实验评估通过率、稳定性和资源消耗，持续寻找更有效的组合。插件化使 Meta 能够围绕具体能力进行有针对性的优化，也为理解能力组合与任务表现之间的关系提供基础。

进化过程的可读性与可解释性是项目的核心目标之一。我们希望人能看懂每个插件的作用与设计动机，理解组合如何演变、实验发现了什么，以及为什么保留、修改或放弃某个版本。先呈现容易理解的研究脉络，再按需查看具体证据与实现；保留失败、回退和不确定性，用实验核查插件贡献与相互作用。完整理念见[项目设计哲学](docs/design/design-philosophy.md)。

项目以自主探索、受控执行和证据可追溯为基本原则，关注可复用的方法与跨任务的泛化。选定成果可以导出为可独立运行、继续维护的项目。

后续研究也希望将相同方法用于 Meta Harness 自身：比较不同 Meta 插件组合设计执行 Harness 的能力，通过重复实验和消融判断其贡献，保留有作用、成本合理的能力。

当前支持两个可选参考实验插件：参考模型取自 DeepSeek Harness 原生配置，参考 Harness 可选择 Codex、Claude Code 和 DeepSeek 标准模式。UI 可独立开关、多选并授权 Meta 在兼容范围内自主组合；参考成绩独立保存、成本计入活动总账。使用方式与接入限制见[参考实验插件](docs/operations/meta-harness.md#参考实验插件)。

## 了解与参与

- [项目设计哲学](docs/design/design-philosophy.md)
- [产品目标与需求](docs/requirements/meta-harness.md)
- [安装、使用与当前限制](docs/operations/meta-harness.md)
- [项目结构与开发导航](AGENTS.md)

# 验证入口与证据等级

状态：当前可执行检查。先按[快速开始](../guides/quickstart.md)准备 Node/Python 依赖；实际 npm 入口以[package.json](../../package.json)为准。

## 日常检查

```sh
npm run check:docs
npm run check:project
npm test
npm run build
```

check:docs 校验受维护 Markdown 的本地链接、锚点、当前页面可达性及当前文档不以历史方案为规则来源；不声称自动证明自然语言语义。check:project 校验依赖和项目/部署边界。npm test 自动重建 SDK 资料并运行边界/文档检查，然后运行 JavaScript 和 Python 单元测试；没有真实模型调用。

build 验证 SDK 资料生成和 UI 打包。单元检查通过不表示容器、官方任务环境、真实服务或科学效果已验证。主要声明的测试对应见[实现核对表](implementation-audit.md)。

## 原生与容器契约

```sh
python3 tests/contracts/prepare-meta-image.py --output /absolute/new-fixture-images
```

将其返回的不可变镜像设为 PHYEXP_META_TEST_IMAGE。该夹具镜像同时包含当前 Meta 与历史契约需要的依赖，不改生产镜像标签。部分旧 Runner 契约还需要其指定基础镜像，按失败提示与测试前提准备，不能用任意 SDK 镜像代替。

可选参考 CLI 镜像由 `python3 scripts/reference-images.py` 准备，默认回执在 `.runtime/reference-acceptance/images.json`；将准确回执路径设为 PHYEXP_REFERENCE_IMAGES。提前完成 `npm run build` 后运行：

```sh
npm run test:contracts
```

这些检查使用假 provider 或本地协议服务，部分需要真实 Docker/原生 SDK/CLI，不调用真实模型。可选镜像未准备会明确跳过，报告必须单列跳过，不写成全部通过。`npm run test:references` 可准备并运行参考专项。

## 官方环境、规模与搬迁

| 检查 | 入口与条件 |
|---|---|
| 官方无模型环境 | `npm run smoke:harbor -- --quantum-harbor /absolute/Quantum-Harbor`，使用 nop |
| 固定任务镜像 | [pinned_images.py](../../tests/smoke/harbor/pinned_images.py)，需匹配任务锁；验证身份/生命周期，空提交可为 0 或未评分 |
| 候选构建 | [project-build.py](../../tests/contracts/project-build.py)，实际隔离构建、产物与拒绝条件 |
| 完整 process 链路 | [process-pipeline.py](../../tests/contracts/process-pipeline.py)，显式外部任务/镜像/新输出；不等于真实模型成绩 |
| 独立交付 | [process-standalone.py](../../tests/contracts/process-standalone.py)，实际包、独立目录、依赖与加载来源 |
| 活动删除 | [campaign_deletion.py](../../tests/smoke/campaign_deletion.py)，隔离合成数据与 Docker，不删除真实活动 |
| 控制规模 | [control_scale.py](../../tests/performance/control_scale.py)，例如 `--count 50000 --readers 15 --delete --report /absolute/new-report.json` |

脚本具体参数先用 --help 核对。规模记录需包含数量、并发、耗时、锁等待与失败；单元/轻量轮询不能替代完整报告、全文搜索或数日运行。搬迁需说明原仓库是否在 OS 层不可访问，不能只凭换 cwd 断言完全隔离。

## 真实模型与人工体验

`smoke:luna`、`h0`、旧 batch 入口和带真实执行开关的烟测会调用模型，独立于上述离线验证。运行需在当前用户授权范围内限定任务和停止条件，保留全部失败。官方评分和工程链路完成是不同结果。

UI 结构与交互逻辑有单元/宿主契约，真实浏览器阅读、窄屏、长内容与真实用户体验需另行检查。合成 UI 夹具如[evolution_workbench.py](../../tests/fixtures/evolution_workbench.py)不启动模型；能渲染不代表已完成人工体验验收。

本地记录写入 reports/development 下，区分 passed/failed/skipped/not_run。正式文档只维护可复现方法和限制，不嵌入私人活动结果或现场耗时。

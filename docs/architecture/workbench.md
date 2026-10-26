# 工作台结构与 UI 维护

状态：当前只注册 Studio；默认值来自[uis.json](../../profiles/meta-workbench/uis.json)，历史经典版已从主线移除。启动见[快速开始](../guides/quickstart.md)。

## 依赖方向

Studio → 公共客户端 → 宿主 API 桥 → 控制后台。具体 UI 不相互导入；公共层不反向依赖 UI 或后台实现。包间只通过声明 exports 访问。React 使用宿主共享模块。

- [meta-workbench-client](../../packages/meta-workbench-client/package.json)：查询、命令、取消、错误、修订、草稿及创建身份；不含 DOM、JSX、页面导航和样式。
- [meta-workbench-bridge](../../packages/meta-workbench-bridge/package.json)：独立宿主桥、原生来源和会话认证、用户请求身份，浏览器不取得后台 user-token。
- [meta-workbench-studio](../../packages/meta-workbench-studio/package.json)：导航、页面、组件、焦点与本版样式。当前没有独立公共展示组件包。

本地统一启动入口 scripts/phyexp.py 经已认证 /health 核对源码、数据与外部任务目录，并通过宿主会话验证 UI 桥。登录链接只写私有文件，普通状态输出不包含令牌。`#phyexp` 打开 Studio，`#phyexp/<活动 ID>` 选择活动；这些链接只导航，不创建或启动实验。

## 页面与状态

[shell/features.tsx](../../packages/meta-workbench-studio/client/shell/features.tsx)集中注册进化概览、插件与动机、版本对比、实验记录、研究报告、运行详情、获取 Harness。features 实现页面，components 保存本版复用展示，shell 维护导航和读取状态；删页面同时处理注册、跨页入口和测试。

后台是事实权威，页面不重新计算另一套计分。读取可取消，迟到响应不得覆盖另一活动或重开的详情。卸载释放本版轮询和监听，不停止桥或后台。切换/重连不自动重发控制请求。

Studio 用版本命名空间保存草稿、活动选择和未完成创建身份。首次复制旧键后保留来源；同配置未知结果重试沿用幂等键，配置改变才产生新请求。身份持久化失败不提交创建。供应商密钥草稿不写 localStorage，保存后清空。

## 增加和移除版本

新版本建立独立 UI 包，声明 `phyexpWorkbench.kind: ui`、宿主和 client 公开入口，在 uis.json 注册；构建与启动共用[清单解析器](../../scripts/workbench-uis.mjs)。默认版本必须存在，未知 ID、缺包和重复注册明确失败。具体版本可独立增删，不把公共能力放在某版内部。

`npm run build:workbench` 默认构建清单全部 UI；启动默认使用清单 default。PHYEXP_UI_VARIANT 可选单个、逗号分隔多个或 all。当前只有 studio；历史 both 兼容为 all，classic 没有对应包。更换装配需重新启动 UI 宿主，源码变更需重建。

删除 UI 不删除用户后台数据或报告。对默认 Studio 的调整仍需保留产品要求的完整操作路径。验证：[清单增删](../../tests/unit/workbench-registry.test.mjs)、[客户端](../../tests/unit/workbench-client.test.mjs)、[页面](../../tests/unit/workbench-features.test.mjs)、[生命周期](../../tests/contracts/workbench-lifecycle.test.mjs)。

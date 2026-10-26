# 可选参考实验

状态：当前实现，两个可选包默认关闭。用户入口见[活动操作](../guides/campaigns.md#参考实验)。

## 两个独立能力

[meta-model-reference](../../packages/meta-model-reference/README.md)允许已批准参考模型运行本活动候选；[meta-harness-reference](../../packages/meta-harness-reference/README.md)允许固定 Solver 运行选定参考 Harness。两者同时启用才允许联合参考，工具只接收冻结引用，不接收任意端点、凭据或命令。

参考模型从 DeepSeek Harness 原生 Models 配置读取，经宿主桥冻结有效配置和来源；主线 Solver/Meta 则使用项目供应商目录。两套入口服务不同职责，不能用主线目录冒充缺失的原生参考快照。

创建时固定允许模型、Harness、配对与权限。运行时可关闭/恢复原允许项或缩小范围，不能新增从未冻结的模型/插件/行为配置。默认停用只取消待执行项并允许已运行项结束；显式停止才撤销相关运行。重开不清零次数、不自动恢复取消项。

## 适配范围

准确版本在[catalog.py](../../src/control/reference/catalog.py)与[锁文件](../../templates/reference)维护；当前注册为 codex、claude-code、dsh-standard。

| Harness | 当前可受理的协议边界 |
|---|---|
| codex | 明确 API Key 的 Responses，或合法的 openai-codex 订阅绑定；不转换 Chat Completions |
| claude-code | 明确 API Key 的 Messages，包括原生 DeepSeek Messages；不转换 Responses |
| dsh-standard | 冻结原生 provider 配置，使用 dsh-base + dsh-sdk-app |

原生快照目前接入 pi-ai、deepseek-api-key 及受限 codex-host 登录句柄；未知账户 provider、无法准确映射的推理/传输设置返回未核验或不可用。目录检查不调用真实模型，协议兼容不等于远端服务已实测。精确判断见[compatibility.py](../../src/control/reference/compatibility.py)。

参考 CLI/标准 SDK 保留原生文件终端，但使用独立工作区；官方任务文件、提交和 qsim 经受控工具桥。不能把原生 shell 目录当作任务 `/app`。模型参考运行 v3 候选的 process 接入见[process.py](../../src/control/reference/process.py)。真实凭据不进入候选/参考 Runner。

## 统计、证据与移除

参考运行共享活动轮次、次数、并发和墙钟，可受模型/Harness 次数子限额；联合运行总次数只计一次，同时受两个子限额。新活动没有 token 账本或 token 子额度。

reference_batches/reference_runs 与主线表分开；主线排名、版本保留和稳定条件不把参考成绩混入。报告按模型、Harness、联合三组展示请求维度与实际改变条件，保留原生轨迹；不能由组名推断单一因果。研究记录可以引用参考观察，再由主线候选实验验证。

未安装且未启用时不导入可选包；选中但缺包明确失败。移除源码影响新装配，旧活动仍按冻结资产读取/恢复；要撤销其新提交权需在该活动停用。参考历史不随包卸载消失，也不自动进入独立导出。

验证：[可选插件](../../tests/unit/reference_plugins_test.py)、[process 参考](../../tests/unit/process_reference_test.py)、[原生认证](../../tests/unit/reference-native-auth.test.mjs)、[CLI 容器契约](../../tests/contracts/reference-harnesses.test.mjs)。完整 CLI 契约需要预先准备参考镜像，跳过不算通过。

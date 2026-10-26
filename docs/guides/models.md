# 模型与认证配置

适用：主线 Solver/Meta 的供应商目录。参考模型使用 DeepSeek Harness 原生 Models，见文末；实际字段见[供应商 schema](../../src/execution/host/provider-config.schema.json)。

## 工作台配置

1. 打开「供应商与模型」，选择或新增供应商，填写稳定 ID、名称、端点、协议和模型 ID。
2. API Key 保存后输入框清空；留空保留已保存密钥，未保存时使用后台环境变量。内置 Codex 订阅的认证和端点不能改作 API Key 路由。
3. 配置上下文、输出参数、输入能力与推理等级；非推理模型使用 reasoningEfforts=false。配置必须符合 schema，页面名称存在不表示服务已实测。
4. 保存后才可执行「测试调用」。它最多发起两次真实诊断请求，验证流、工具调用和工具返回，可能产生费用；不要求 usage，不创建任务实验。失败不自动重试。
5. 返回活动草稿选择 Solver 与 Meta，创建时保存两角色准确路由及目录修订。

现有活动不随目录改动而换模型、端点或调用设置。更新密钥用于后续启动的宿主，已经运行的宿主使用其已有凭据。目录冲突需重新读取并核对，不能覆盖另一窗口的修订。

## 文件配置与优先级

[model-providers.example.json](../../profiles/model-providers.example.json)是字段示例，端点与模型需按实际服务填写。配置存于仓库外，不自动读取 .env，也不在 JSON 保存真实密钥。

```sh
python -m src.control.server \
  --quantum-harbor /absolute/path/to/Quantum-Harbor \
  --model-config /absolute/path/to/models.json
```

也可设置 PHYEXP_MODEL_CONFIG，命令行优先。有效目录按内置 → 启动文件合并 → UI 按供应商覆盖；文件改动需重启后台，UI 保存立即更新目录。停用隐藏新活动选择，保留旧路由和历史。

通用 pi-ai 支持 openai-completions、openai-responses、anthropic-messages；DeepSeek 使用原生适配器。baseURL 允许 HTTPS 或回环 HTTP，不含凭据、query 或 fragment。认证字段只保存环境变量引用名。已保存密钥优先于后台环境变量，凭据引用不能覆盖 PATH/NODE_OPTIONS 等宿主设置。

协议路径由相应适配器拼接：Completions/Responses 常用 `/v1` 基地址，Messages 按其 SDK 根地址规则配置。process 候选模型通道当前为 HTTP/SSE，不支持 WebSocket；目录支持的宿主适配器选项不等于每条执行链路均支持。

## 认证与隐私边界

Codex 订阅默认读取 `~/.codex/auth.json`，可由 PHYEXP_CODEX_AUTH_FILE 指定。可信宿主只使用当前访问令牌，不把刷新令牌交给候选。登录过期需正常更新登录，不能通过换模型或清除活动记录掩盖失败。

API Key 可保存到数据目录 provider-settings.sqlite，也可在启动后台的终端设置所引用变量。密钥不回显、不写浏览器 localStorage、不进入活动快照或导出包。备份整个数据目录时应把凭据数据库按私有资料保护。

新活动不累计 token/费用，也不提供 token 总量停止。maxTokens 是模型请求输出参数，不是活动费用硬上限；不同协议可能不接受该参数。原始响应可带 usage，但缺失 usage 不阻断执行或归档。

内置显示名称和默认选择是本仓库配置，不能据此保证远端模型别名永不改变。模型科学能力、外部服务可用性和用户真实凭据需单独验证；本地假 provider 检查不作此承诺。

## 参考模型入口

仅在启用参考模型插件时，从 DeepSeek Harness 原生 Models 选择。工作台宿主桥读取受支持的原生 provider 快照及明确凭据句柄，不把主线目录复制成第二套参考配置。不同 Harness 的协议与认证限制见[参考实验](../architecture/references.md)。

测试入口：[供应商设置](../../tests/unit/provider_settings_test.py)、[配置与脱敏](../../tests/unit/providers.test.mjs)、[协议契约](../../tests/contracts/providers.test.mjs)。

# 导出并运行独立 Harness

适用：当前 v3 完整工程；旧候选按其原格式导出。身份与资产规则见[版本与导出](../architecture/versions-and-export.md)。

## 取得项目

在「获取 Harness」选择已有冻结候选生成项目、下载 ZIP。包来自该候选的准确源码和构建产物，不从最新工作区重新生成。导出记录包含 bundleId、ZIP 摘要、导出器版本和分别记录的验证状态。

v3 包内 `candidate/` 是源码、`candidate.tar` 是构建产物，bundle.json/objects.json/recipe.json 固定身份与运行配置。只有候选目录中的两个清单不构成独立交付；使用完整导出包。

包不包含 Meta、工作台、活动数据库、研究历史、真实凭据或宿主安装缓存。运行仍需要显式外部 Quantum-Harbor、匹配任务镜像、Python、Docker、模型代理镜像和认证。

## 安装与执行

以包内 README 为最终操作依据；当前模板为[process-README.md](../../templates/standalone/process-README.md)。在解压后的 harness 目录：

```sh
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.lock
.venv/bin/python run.py --verify
```

`--verify` 校验包内容，不调用模型，也不证明任务执行成功。v3 构建产物已包含候选依赖，不需要在宿主重新 npm install 候选。

按 recipe.json 的 auth 引用设置 API Key，或提供有效的 PHYEXP_CODEX_AUTH_FILE。准备准确的任务镜像锁和 recipe 中的模型代理镜像，然后执行：

```sh
.venv/bin/python run.py \
  --quantum-harbor /absolute/path/to/Quantum-Harbor \
  --task TASK \
  --task-image-lock /absolute/path/to/TASK.image-lock.json \
  --output /absolute/path/to/new-run \
  --timeout 22000
```

这一步会执行真实任务并可能调用付费模型。TASK 和时限是示例参数，须替换为授权任务和能容纳完整 benchmark 阶段的上限；输出目录必须不存在。该入口不自动重跑整个 Trial，也不提供 token 总量停止。

已有输出重新收集可使用 `run.py --collect /absolute/path/to/existing-run`，不重跑模型/评分器。summary.json 分别展示执行、官方结果、证据和比较条件；无可信官方评分保持 null。

## 验证状态

| 状态 | 证明范围 |
|---|---|
| 静态校验 | 内容与清单/摘要一致 |
| 无模型搬迁 | 在独立目录/依赖环境实际加载交付代码，模拟响应验证链路 |
| 真实独立执行 | 使用实际模型与官方任务完成接入，保留结果和失败 |

三层不能相互替代。刚导出默认只完成静态校验；每份包的状态以其验收记录为准。一次真实零分能证明部分工程链路，不能证明策略有效。修改包源码后必须重新冻结，不能沿用原摘要声称是同一候选。

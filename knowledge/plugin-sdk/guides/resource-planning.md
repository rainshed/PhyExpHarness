# Meta 资源规划接口

适用于活动状态 `resourcePlanning.policy = meta-resource-planning-v1`。新活动采用 `benchmark-time-v1` 和 `control-only-v1`，不统计 token 或费用，用户上限、Meta 运行计划和已受理实验条件分别保存；旧活动按其绑定的工具契约执行。

## 提交和修改计划

首先读取 `campaign_status` 的完整状态文件。`resourcePlanning.configurationSources` 说明限制来源，`suggestions` 是建议，`planRevision` 是当前计划版本。首次调用 `campaign_plan_update` 后，新 process 活动由 Meta 自主提交批次；不会自动受理全部任务的 H0，也不强制全套基线顺序。旧固定 Runner 活动才可能采用自动基线。

当前原生工具直接接收对象参数：

```json
{
  "changes": {
    "parallelism": 1,
    "closeoutReserveSeconds": 0
  },
  "reason": "按当前活动剩余时间安排并发和收尾预留",
  "expectedPlanRevision": 0,
  "idempotencyKey": "initial-plan"
}
```

示例值需要按当前活动条件选择，不是固定实验策略。两个 `changes` 字段必须一起提交；并发为正整数，预留可为 0。提交不可执行的值会被拒绝，不自动裁剪；重复同一幂等键须保持相同输入。修改计划时使用新的键和最新版本。

计划修改影响未来批次，已受理和运行任务保留其条件。Meta 不能提高用户上限或改变 Solver 配置。新活动只在用户目标满足或活动额度达到上限时结束探索；阶段目标、调整预留或暂时没有方向不能代替活动目标。

`resourcePlanning.schedulingWait` 说明收尾时间阻止待执行任务启动，后台同时发送 `resource_plan_waiting` 通知。检查剩余时间和预留；计划预留可以调整。即使次数上限已关闭新批次受理，只要活动尚未关闭且已有任务未完成，仍可调整计划来完成已受理任务；不能因此受理额外批次。

## 批次与任务时限

`batch_submit` 接收 `candidateId`、`tasks`、`repeats`、`idempotencyKey`。每道题的求解和评分时限由 benchmark 原始配置决定，可在状态中的 `taskTimeLimits` 查询。准备与评分不占用求解时间；计划和批次不能覆盖任务时限，也不能接受缩短执行。

活动剩余时间不足以完整执行时，选择仍可完整运行的任务或处理已有证据。比较实验时使用后台记录的实际资源条件。

历史活动可能仍包含 `defaultTrialTimeSeconds`、批次 `execution` 和 `trial_conditions_accept`，其含义以该活动冻结的契约和资料为准。当前活动不要发送这些字段或操作。

## 准入等待和结果

新活动模型请求不经过 token 预留或结算。以下等待码适用于 Meta/受控宿主的访问检查；process Solver 使用独立本地通道，不逐请求依赖控制数据库。`storage_capacity_wait` 表示存储空间不足，`control_unavailable` 表示控制服务暂时不可用；等待不发起模型请求，仍受取消及原任务截止时间约束。凭证和协议错误属于平台控制问题，不归为模型供应商故障。

新活动不发送 `closeoutReserveTokens`、总 token 阈值或参考插件 token 子额度。原始 usage 可存在于轨迹中，不能据此要求平台生成累计成本。历史活动按其冻结的工具与资料执行。

新活动继续使用 `task-completion-v4`：已进入启动尝试且最终结束，无可信官方通过结果计任务完成分 0；尚未启动、无先行失败的人工撤销、仍在运行或结束状态待核实单列。官方未评分保留空值，报告保留全部尝试及原因。旧活动按其绑定规则读取，不重算历史。

# Meta 资源规划接口

适用于活动状态 `resourcePlanning.policy = meta-resource-planning-v1`。新活动采用 `benchmark-time-v1`，用户上限、Meta 运行计划和已受理实验条件分别保存；旧活动按其绑定的工具契约执行。

## 提交和修改计划

首先读取 `campaign_status` 的完整状态文件。`resourcePlanning.configurationSources` 说明限制来源，`suggestions` 是建议，`planRevision` 是当前计划版本。首次调用 `campaign_plan_update` 后，后台自动受理全部所选任务各一次的 H0 基线，无须重复提交基线批次。

当前原生工具直接接收对象参数：

```json
{
  "changes": {
    "parallelism": 1,
    "closeoutReserveSeconds": 0,
    "closeoutReserveTokens": 0
  },
  "reason": "按当前活动余额安排并发和收尾预留",
  "expectedPlanRevision": 0,
  "idempotencyKey": "initial-plan"
}
```

示例值需要按当前活动条件选择，不是固定实验策略。三个 `changes` 字段必须一起提交；并发为正整数，预留可为 0。token 不限时 token 预留必须为 0。提交不可执行的值会被拒绝，不自动裁剪；重复同一幂等键须保持相同输入。修改计划时使用新的键和最新版本。

计划修改影响未来批次，已受理和运行任务保留其条件。Meta 不能提高用户上限或改变 Solver 配置。新活动只在用户目标满足或活动额度达到上限时结束探索；阶段目标、调整预留或暂时没有方向不能代替活动目标。

`resourcePlanning.schedulingWait` 说明收尾时间或 token 额度阻止待执行任务启动，后台同时发送 `resource_plan_waiting` 通知。检查实际余额、在途占用和预留；计划预留可以调整。即使次数上限已关闭新批次受理，只要活动尚未关闭且已有任务未完成，仍可调整计划来完成已受理任务；不能因此受理额外批次。

## 批次与任务时限

`batch_submit` 接收 `candidateId`、`tasks`、`repeats`、`idempotencyKey`。每道题的求解和评分时限由 benchmark 原始配置决定，可在状态中的 `taskTimeLimits` 查询。准备与评分不占用求解时间；计划和批次不能覆盖任务时限，也不能接受缩短执行。

活动剩余时间不足以完整执行时，选择仍可完整运行的任务或处理已有证据。比较实验时使用后台记录的实际资源条件。

历史活动可能仍包含 `defaultTrialTimeSeconds`、批次 `execution` 和 `trial_conditions_accept`，其含义以该活动冻结的契约和资料为准。当前活动不要发送这些字段或操作。

## 准入等待和结果

`budget_inflight_wait` 表示其他请求暂时占用额度，平台等待结算；不是新的模型重试。`budget_plan_wait` 表示 Meta 的 token 预留阻止 Solver 调用，可根据工作需要修改计划。等待计入实际经过时间，仍受任务截止和用户停止约束。

`budget_admission_denied` 表示当前余额无法满足请求准入估算，不等于全部额度已经实际消耗。平台账本、凭证和连接错误有独立类别，不作为模型供应商错误。

新活动默认绑定 `task-completion-v4`：已进入启动尝试且最终结束，无可信官方通过结果计任务完成分 0；执行中的预算、账本和凭证失败同样进入分母。尚未启动、无先行失败的明确人工撤销、仍在运行或结束状态待核实单列。官方未评分保持空值，报告保留全部尝试及原因。原 `task-completion-v3` 活动仍将预算准入不足归为截断、账本和凭证故障归为外部故障且不进入分母；读取后台绑定规则，不能把旧排除规则套用于 v4。

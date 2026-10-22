# Meta 资源规划接口

适用于活动状态 `resourcePlanning.policy = meta-resource-planning-v1`。用户上限、Meta 运行计划和已受理实验条件分别保存；旧活动继续使用原有规则。

## 提交和修改计划

首先读取 `campaign_status`。`resourcePlanning.configurationSources` 说明限制来源，`suggestions` 是建议，`planRevision` 是当前计划版本。首次调用 `campaign_plan_update` 后，后台自动受理全部所选任务各一次的 H0 基线，无须重复提交基线批次。

工具的 `input` 是 JSON 字符串，包含：

```json
{
  "changes": {
    "parallelism": 1,
    "defaultTrialTimeSeconds": 3600,
    "closeoutReserveSeconds": 0,
    "closeoutReserveTokens": 0
  },
  "reason": "按当前任务规模分配后续实验时间",
  "expectedPlanRevision": 0,
  "idempotencyKey": "initial-plan"
}
```

示例值需要按当前活动条件选择，不是固定实验策略。四个 `changes` 字段必须一起提交；并发和单次时长为正整数，预留可为 0。token 不限时 token 预留必须为 0。提交不可执行的值会被拒绝，不自动裁剪；重复同一幂等键须保持相同输入。修改计划时使用新的键和最新版本。

计划修改影响未来批次，已受理和运行任务保留其条件。Meta 不能提高用户上限或改变 Solver 配置；达到自己的阶段目标、增加预留或缩短计划不能代替停止审查。

`resourcePlanning.schedulingWait` 说明收尾时间或 token 额度阻止待执行任务启动，后台同时发送 `resource_plan_waiting` 通知。检查实际余额、在途占用和预留；计划预留可以调整。即使次数上限已关闭新批次受理，只要活动尚未关闭且已有任务未完成，仍可调整计划来完成已受理任务；不能因此受理额外批次。

## 批次和排队条件

`batch_submit` 保留 `candidateId`、`tasks`、`repeats`、`idempotencyKey`，可附加：

```json
{"execution":{"trialTimeSeconds":1800,"allowShortened":false}}
```

省略时采用当前计划时长，默认不接受因排队而缩短。超过用户上限或冻结配方能力的时长会被拒绝。实际获配时间、计划版本和条件差异进入证据与报告。

单次时长包含启动、Solver、评分和清理，不等于纯 Solver 时间。`resourcePlanning.executionTimePolicy` 公开执行层固定评分与清理预留；当前为 330 秒，单次分配必须大于该值，启动还会消耗部分时间。批次、缩短确认和启动检查均执行这个最低要求，避免先受理再因不可执行时长产生未评分。此固定执行预留与 Meta 的活动收尾预留分别记录。

待启动任务剩余时间不足时，`campaign_status.pendingConditions` 给出任务 ID 和可用时间。确认可以缩短后调用 `trial_conditions_accept`：

```json
{"trialId":"使用返回的任务ID","trialTimeSeconds":600,"reason":"接受剩余时间用于有限诊断","idempotencyKey":"accept-shortened"}
```

时长不能超过原受理条件。该操作明确接受随剩余时间缩短；实际分配仍会记录。不能把缩短的试验当作原定完整时间条件的对照。

## 准入等待和结果

`budget_inflight_wait` 表示其他请求暂时占用额度，平台等待结算；不是新的模型重试。`budget_plan_wait` 表示 Meta 的 token 预留阻止 Solver 调用，可根据工作需要修改计划。等待计入实际经过时间，仍受任务截止和用户停止约束。

`budget_admission_denied` 表示当前余额无法满足请求准入估算，不等于全部额度已经实际消耗。平台账本、凭证和连接错误有独立类别，不作为模型供应商错误。

新活动默认绑定 `task-completion-v4`：已进入启动尝试且最终结束，无可信官方通过结果计任务完成分 0；执行中的预算、账本和凭证失败同样进入分母。尚未启动、无先行失败的明确人工撤销、仍在运行或结束状态待核实单列。官方未评分保持空值，报告保留全部尝试及原因。原 `task-completion-v3` 活动仍将预算准入不足归为截断、账本和凭证故障归为外部故障且不进入分母；读取后台绑定规则，不能把旧排除规则套用于 v4。

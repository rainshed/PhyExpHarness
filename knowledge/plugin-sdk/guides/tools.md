# 工具插件

来源：官方[构建工具](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/tool.md)、[工具开发参考](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/cookbook/adding-a-tool.md)，以及锁定的 `@deepseek-ai/dsh-tools` 类型。适用版本：`0.2.1-rc.2`。

## 一个完整示例

工具接收数值列表，返回数量与总和。它演示确定性计算与结构化输出，不涉及任务答案或模型调用。

`index.mjs`：

```js
import { defineTool } from '@deepseek-ai/dsh-tools';
export const name = 'number-summary';
export const inject = ['tools'];
export function apply(ctx) {
  ctx.tools.register(defineTool({
    name: 'summarize_numbers',
    description: 'Return the count and sum of a numeric list.',
    parameters: {
      values: { type: 'array', items: { type: 'number' }, required: true },
    },
    output: {
      schema: {
        type: 'object', additionalProperties: false,
        properties: {
          count: { type: 'integer', required: true },
          sum: { type: 'number', required: true },
        },
      },
      render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }],
    },
    async execute({ values }, exec) {
      exec.signal.throwIfAborted();
      const sum = values.reduce((total, value) => total + value, 0);
      if (!Number.isFinite(sum)) throw new Error('Sum exceeds finite numeric range.');
      return { count: values.length, sum };
    },
  }));
}
```

同目录的 `plugin.json`：

```json
{
  "schemaVersion": 1,
  "name": "number-summary",
  "version": "1.0.0",
  "entry": "index.mjs",
  "purpose": "计算数值列表的数量与总和",
  "displayName": "数值汇总工具",
  "functionSummary": "在模型调用时返回数值数量与总和",
  "mechanism": "注册主动调用的确定性工具，不自动处理其他结果",
  "configSchema": { "type": "object", "additionalProperties": false },
  "dependencies": [],
  "observes": [],
  "intervenes": ["ctx.tools.register"],
  "capabilities": ["tools"],
  "tools": ["summarize_numbers"],
  "fallbackBehavior": "禁用后该工具不可用；非法输入或数值溢出返回工具错误",
  "assets": []
}
```

`{"values":[1,2,3]}` 返回 `{"count":3,"sum":6}`；空列表返回两个零，空列表不是错误。冻结时 `plugins[].path` 指向包含这两个文件的目录，配置为 `{}`。检查证明接口行为，任务中的效果需要另行观察。

## 返回值与错误

`defineTool` 的 schema 是其专用 DSL：属性上的 `required: true` 不要与原始 JSON Schema 的 `required` 数组混用。`execute` 返回符合 `output.schema` 的规范 JSON 值；`output.render` 生成给模型阅读的内容。异步 I/O 应传递 `exec.signal`。参数类型不符、抛出异常或返回值不合法会成为工具错误。

## 观察与转换

`tools/result` 用于观察冻结的最终结果，不能原地修改。`tools/post-execute` 用于返回转换决定；保留结果时调用 `next()`。`value` 与模型可见内容是不同部分，转换时说明自己改变哪一部分。

可通过 `sdk_read({"id":"example-echo"})` 查看带结果转换的完整技术样例；准确 decision 类型见 `sdk_read({"id":"tools"})`。监听器和工具注册随所属插件卸载，临时状态不自动持久化。

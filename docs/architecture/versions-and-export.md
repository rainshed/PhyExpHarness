# 版本、共享与独立导出

状态：当前主线；操作见[导出指南](../guides/export.md)，旧格式见[兼容规则](compatibility.md)。

## 内容身份

v3 候选保存完整工程来源、harness 声明、执行模式、依赖锁、构建产物、构建回执、模型配方与最小平台适配。框架/profile/插件和配置属于研究变量，外部模型、环境、资源与适配属于比较条件；两类差异分别记录。

[project.py](../../src/execution/bundle/project.py)负责冻结，[manifest.py](../../src/execution/bundle/manifest.py)负责统一解析/验证。候选目录中的 bundle.json、recipe.json 引用 `objects/sha256/`；不是自足目录，不能只复制这两个文件作为交付。

相同来源和构建输入可复用 `cache/project-builds/`，插件阅读按冻结源码/模式和组合配置区分。同名同版本号不能证明内容相同，缺少源码声明不能据名称建立跨候选相同身份。阅读使用 project_sources 核验被读取来源，正式执行、冻结和导出仍做完整验证。

## 成果、缓存与历史

不可变源码、锁、产物和适配属于成果；可重建依赖安装、物化视图和镜像准备属于缓存。v2 插件对象及共享依赖缓存继续兼容，v1 Bundle 继续解析。缓存丢失不是新候选身份；准确依赖不可获取则明确失败，不退回开发机随意版本。

公开阅读信息可从原冻结来源恢复，不为补充显示重新跑模型或修改候选。研究动机、观察及选择记录单独版本化，不靠编辑冻结源码追加历史解释。

## 导出闭包

[exporting/project.py](../../src/exporting/project.py)从统一解析结果复制准确资产并生成 ZIP。v3 包含候选源码、构建产物、锁、入口、配方、必要运行代码和包内说明；v2 按组合物化，v1 按原格式复制。导出不重新生成候选实现。

导出器记录 archiveSha256、准确 bundleId、实现摘要与格式。Meta 工具、控制数据库、研究历史、供应商凭据、参考插件运行历史和安装缓存不进入执行包。被采纳的候选源码属于交付，参考实验材料不自动变成执行能力。

`staticValidation`、`relocationValidation`、`realValidation` 独立记录。刚导出只完成静态校验，其余为 not_run。验收程序必须核实在独立目录实际加载包内/声明安装的代码；原仓库尚可访问时不能宣称已证明 OS 层完全隔离。外部任务目录、镜像、模型认证和输出位置显式提供。

## 版本选择

candidate_retain 保存 Meta 明确决定、准确证据摘要、全部相关尝试和此前选择链。选择检查内容归属与证据完整性，不以一次高分自动认证稳定或强制否决退步候选。未主动选择显示尚未选择；最终选择及其依据冻结，后续结果不改旧快照。

验证：[组合](../../tests/unit/project_bundle_test.py)、[版本读取](../../tests/unit/project_plugin_reading_test.py)、[导出](../../tests/unit/export_test.py)、[选择](../../tests/unit/selection_test.py)、[独立 process 搬迁](../../tests/contracts/process-standalone.py)。

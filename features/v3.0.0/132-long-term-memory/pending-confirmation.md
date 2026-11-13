# 待用户确认

按 goal-runbook §4"要用户确认"记录。每条写明：编号、涉及的任务与验收标准、问题、可选做法及后果、建议、目前按哪个做法继续。

## P-01 深度研究 `/workbench/continue` 追问轮的整理口径

- **涉及**：T067、T068、T073、T074、T086；AC-39、AC-42、AC-87；design 决策 7、15。
- **问题**：Wave 0 的 V7 验证推翻了 design 对"深度研究的轮"的前提。产品主路径（日常对话里打开任务模式再发一条）每一轮都新建 svid、新的 `linsight_session_version` 行和新的任务消息行，问题与结果都能按 svid 读出，design 的做法在这条路径上成立且更简单。只有 `/workbench/continue`（同一 svid 追问，只能从没有导航入口的 `/linsight/new` 页手输网址进入）符合原假设，而这条路径上追问的问题不落库、上一轮结果被原地覆盖，"按轮读取问题与结果"做不到。
- **可选做法**：
  - A. 本轮概要行在开始时存问题、结束时存结果快照。后果：记忆模块的表里存一份对话内容，表变大；可整理。
  - B. 深度研究模块新增按轮存储（新表），整理时经它的 Service 读取。后果：改动深度研究模块的存储，范围最大。
  - C. 本期把 `/continue` 轮排除在整理之外，记入 design §8。后果：经这条隐藏路径产生的对话不会自动整理成记忆；显式写入、带入、检索不受影响。
- **建议**：C。这条路径没有界面入口，A、B 的成本不值得。
- **目前做法**：按 C（保守：少整理，不多存对话内容）继续。主路径按 svid 建本轮概要行并整理；`/continue` 轮照常带入常驻记忆、提供工具、显式写入与归因，但其本轮概要行标为不整理。**确认后如改为 A**，涉及 `memory/domain/services/consolidation_linsight.py`、`memory_turn_record` 增加两列与对应迁移、`linsight/domain/task_exec.py` 的追问轮开始与结束处。

## P-02 改动了两个任务未点名的既有测试文件（已做，请确认）

- **涉及**：T012、T014；goal-runbook §8"不修改任务点名以外的既有测试文件"。
- **问题**：两个既有测试文件钉住了本功能必须修改的对象，不改它们就会产生新增失败：
  - `test/dsh/test_telemetry.py::test_application_enum_preserves_existing_values` 断言 `ApplicationTypeEnum` 的成员集合恰好等于一张清单。T014 按 design 决策 18 要求新增 `MEMORY = "memory"`，这条断言因此失败。
  - `test/fixtures/table_definitions.py` 的 `TABLE_ASSISTANT` 是手写 DDL。T012 给 `assistant` 模型加了 `memory_enabled` 列，使用这份 DDL 的测试（如 `test/app_template/test_template_api.py`）插入助手时报"没有这一列"。
- **可选做法**：
  - A. 在清单里加一行 `"MEMORY": "memory"`；在 DDL 里加一列 `memory_enabled BOOLEAN NOT NULL DEFAULT 0`。原有成员与原有列的断言一条不少，只是承认新增的成员和列。
  - B. 不改这两个文件，接受〔基线比对〕里因此出现的新增失败。
  - C. 不新增枚举成员（记忆调用改用已有的类型）。这会改变 design 决策 18 与 AC-45 测试的口径。
- **建议**：A。
- **目前做法**：已按 A 修改并单独提交。如果不同意，回退这两处改动即可（`git revert` 对应提交），涉及文件只有这两个。

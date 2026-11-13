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

## P-02 两个任务未点名的既有测试文件需要随本功能更新（用户已于 2026-11-13 批准，已按 A 修改）

- **涉及**：T012、T014；goal-runbook §8"不修改任务点名以外的既有测试文件"。
- **问题**：两个既有测试文件钉住了本功能必须修改的对象，不改它们就会产生新增失败：
  - `test/dsh/test_telemetry.py::test_application_enum_preserves_existing_values` 断言 `ApplicationTypeEnum` 的成员集合恰好等于一张清单。T014 按 design 决策 18 要求新增 `MEMORY = "memory"`，这条断言因此失败。
  - `test/fixtures/table_definitions.py` 的 `TABLE_ASSISTANT` 是手写 DDL。T012 给 `assistant` 模型加了 `memory_enabled` 列，使用这份 DDL 的测试（如 `test/app_template/test_template_api.py`）插入助手时报"没有这一列"。
- **可选做法**：
  - A. 在清单里加一行 `"MEMORY": "memory"`；在 DDL 里加一列 `memory_enabled BOOLEAN NOT NULL DEFAULT 0`。原有成员与原有列的断言一条不少，只是承认新增的成员和列。
  - B. 不改这两个文件，接受〔基线比对〕里因此出现的新增失败。
  - C. 不新增枚举成员（记忆调用改用已有的类型）。这会改变 design 决策 18 与 AC-45 测试的口径。
- **建议**：A。
- **目前做法**：**用户已批准（2026-11-13）**，已应用 `proposed/p02-existing-tests.patch`。此前曾按 A 修改（提交 8dfd18db07），后按规程 §8 撤回，等待确认期间两个文件为基线内容。A 的改动保存在 `proposed/p02-existing-tests.patch`，你同意后执行 `git apply features/v3.0.0/132-long-term-memory/proposed/p02-existing-tests.patch` 即可。批准前〔基线比对〕因此有 3 个新增失败；批准并应用后见最终报告第 3 项。

## P-03 `/workbench/continue` 追问轮的提示与归因按任务消息合并显示（P-01 的延续）

- **涉及**：T068、T070、T086；AC-21、AC-87；P-01。来源：wave-notes/wave-11.md W11-1、wave-13.md U-13-02。
- **问题**：主路径一轮一条任务消息行，按 `message_id` 取提示与归因没有问题。`/continue` 追问轮与首轮共用同一条任务消息行，所以按 `message_id` 取到的是这条行上多轮合并的结果；`/linsight/new` 页上的多轮只有前端自造的轮次标识，这些轮不显示记忆提示。
- **可选做法**：
  - A. 维持现状：这条隐藏路径不保证逐轮区分。
  - B. 后端经 WS 记忆事件为每轮带 `turn_id`，前端按 `turn_id` 取。后果：要改深度研究的 WS 事件与前端 `useLinsightManager` 的轮次状态。
  - C. `/continue` 轮的概要行不写 `message_id`。后果：一天后被遗留记录清理删除，刷新后操作提示与撤销入口消失。
- **建议**：A，与 P-01 的建议一致（这条路径没有界面入口）。
- **目前做法**：按 A。改为 C 只需改 `linsight/domain/services/memory_turns.py` 的 `begin`；改为 B 涉及 `linsight/domain/services/memory_turns.py` 与 `client/src/components/Linsight/` 的轮次状态。

## P-04 单条删除不做二次确认

- **涉及**：T082、T083；AC-87、AC-89。来源：wave-notes/wave-13.md U-13-01。
- **问题**：AC-89 只要求"清空全部"二次确认。记忆管理页的单条删除和回答旁归因里的就地删除，目前点一下就删除；删错后只能在管理页重新新增（撤销只针对对话里的显式写入）。
- **可选做法**：A. 不确认（现状）；B. 单条删除也弹确认，代价是归因里连续删多条时多一步。
- **建议**：A。AC-87 写的是"就地删除"，单条误删代价小。
- **目前做法**：按 A。改为 B 涉及 `client/src/pages/settings/sections/MemoryPane.tsx` 与 `client/src/components/Chat/MemoryNotice.tsx`。

# Wave 11 记录：接入深度研究（T067–T075）

本 Wave 在独立 worktree 上完成 T067–T075，共 9 个任务，每个任务一次提交。落点以 R3、R8、R9 和 verification.md 的 V3、V7 为准。

## 自己定的决定

- T067｜本 worktree 建出来时基于 `main`（af1894a538），不含 Wave 0–7 的记忆模块｜用 `git switch -C worktree-wf_f7c3abc6-f5a-4 b6a036d4b4` 把本分支移到其他并行 Wave 共用的基线｜工作区当时干净，基线与兄弟分支一致，协调者合并时不会多出 `main` 上的无关提交。
- T067｜测试放在 `test/linsight/` 下，用不到 `test/memory/conftest.py` 的 fixture｜新建 `test/linsight/_memory_doubles.py`，复制最小的 SQLite 接缝、KV、索引、详情替身，测试模块按名字导入 fixture｜brief 要求复制而不是跨目录引用；文件名以 `_` 开头，pytest 不把它当测试收集，也不影响 `test/linsight` 下其他测试。
- T068｜日常对话进入任务模式时，新会话的 `chat_id` 在 `submit_user_question` 内部生成，入队也在 `submit_task_turn` 内部；Wave 8 在 `chat.py` 端点里登记时拿不到这个 `chat_id`｜给 `submit_task_turn` 加一个默认 `None` 的参数 `on_session_created`，在会话建好之后、入队之前调用；只有 `chat_service._task_mode_stream_completion` 传入登记回调｜登记必须早于 worker 开始本轮，否则首轮读不到登记行。开放 API 走 `task_mode_service` 直接调 `submit_task_turn`，不传回调；开放面的日常路由在 `open_api/domain/schemas/workstation.py:88` 把 `task_mode` 强制置为 False，所以 `_task_mode_stream_completion` 只能从登录态端点进入。`chat_service.py` 只改了 `:2699` 一处调用，与 Wave 8 的改动区域不重叠。
- T068｜轮次结束要让整理知道"本轮结果已最终"｜轮结束时把本轮概要行的 `ended` 列置为真（该列在模型里已有、此前未被使用），新增 `memory/domain/services/linsight_turns.py` 承载这条更新和"按任务消息行找未结束轮"的查询｜不改既有记忆文件；整理据此区分进行中、停在补充输入与已结束。
- T068｜`end_turn` 的 `last_message_id`｜取本轮任务消息行 id（按 svid 经 `get_task_feedback_by_version` 找到），找不到时传 `None`（当前最大）｜与 V7 的建议一致。
- T068｜部分既有测试用 `LinsightWorkflowTask.__new__` 构造执行器，不经过 `__init__`｜开始与结束都经 `_begin_memory_round` / `_end_memory_round`，内部用 `getattr` 兜底创建 `LinsightMemoryRound`｜既有测试不因缺少新属性而失败。
- T068｜三个登录态端点之外的 `/workbench/start-execute` 是否登记｜不登记｜spec 只点名提交、继续、补充输入三个；提交端点已在客户端调用 start-execute 之前完成登记。
- T070｜调研子代理能否用 `memory_search`｜两个记忆工具都加入 `_SUBAGENT_TOOL_DENY`，记忆文本也只挂在主图｜R3 写明"子 agent 不读写记忆"。
- T070｜"有归因"的口径｜只在本轮带入了非空常驻块、或检索取回了条目时为真；经验类带入不计入；常驻块为空时本轮概要行的 `resident_rev` 写 `None`｜`GET /turn` 的 `resident` 按快照返回常驻条目、不含经验条目；把经验类算作归因会出现"有归因标志但面板里没有内容"。`flags` 按 `resident_rev is not None` 判归因，所以空常驻必须写 `None`。
- T070｜记忆信号的下发时机｜在三处下发并按 `(turn_id, has_write, has_attribution)` 去重：显式写入成功的回调、记忆工具的结束帧（覆盖检索）、轮结束｜任务消息 WS 在 `FINAL_RESULT` 后关闭（`message_stream_handle.py:22-23`），只在轮结束下发会到不了前端。
- T070｜提示词与工具同步｜记忆文本＝工具说明＋常驻块＋经验块，在轮开始时生成一次；`create_linsight_agent` 只在工具列表里确有 `memory_` 工具时才挂记忆中间件｜遵守 linsight/AGENTS.md 的 prompt ⟺ tool 约束。
- T072｜`ExecStep.output` 是字符串字段｜`params` 换成 `{"redacted": true, "op", "item_ids"}` 字典，`output` 换成同一字典的 JSON 字符串；条目 id 优先从返回里取｜满足字段类型，两处内容一致。
- T072｜`WorkspaceBackend.write/awrite` 的拦截范围｜只拦 `large_tool_results/` 下、内容以记忆工具输出固定前缀开头的写入，返回 `WriteResult(error=...)`｜三条卸载路径写失败时都保留原消息（V3 已核实），其余写入不受影响。
- T072｜压缩生成的摘要文本（V3 落点 13）｜不处理｜R4 已把它记入 §8 已知限制。
- T074｜整理读取深度研究的入口｜在 linsight 侧新增 `read_round_for_memory(chat_id, message_id)`：按任务消息行取 svid，再取该版本的 `question`、`output_result.answer` 与是否终态；记忆模块只调这个函数｜满足"不直接查深度研究的表"。
- T074｜一轮的文本上限｜问题截到 2000 字，回答截到总量 24000 字｜沿用日常整理的 `MAX_MESSAGE_CHARS`、`MAX_TOTAL_CHARS`。
- T074｜几种异常轮的处理｜`ended` 但版本未到终态：等待；任务消息行或版本找不到：置位并记 `op='abandoned'`；会话已删除、记忆关闭或登记行换了主人：只置位不整理；超过 24 小时未结束：置位并记 `op='abandoned'`｜失败方向都是"少整理"。单轮失败不影响同一用户其他轮，失败由 `Consolidator` 计数，下次扫描重试。
- T074｜`consolidator.py` 是否要改｜不改；在 `factory.get_consolidator` 里通过已有的 `extra_steps` 参数接入 `LinsightRoundConsolidation`｜`Consolidator` 已预留 `extra_steps`，按 brief 只有本 Wave 改 `factory.py`。
- T075｜`test/memory/spike/` 目录｜只删除 `test_v3_linsight_paths.py`，目录留给协调者在合并后删除｜brief 的要求；本 worktree 里 Wave 9、10 的实验测试仍在。

## 需要用户确认

### W11-1 `/workbench/continue` 多轮共用一条任务消息行时，按 `message_id` 读取会合并多轮

- **涉及**：T068、T070；AC-21、AC-87；P-01。
- **问题**：按 brief 的约定，每一轮的概要行都写上本轮任务消息行的 id。主路径一轮一条任务消息行，没有问题。`/continue` 追问轮与首轮共用同一条任务消息行，所以 `GET /api/v1/memory/turn?message_id=` 与 `GET /flags` 会把这条行上所有轮的写入与检索合并成一份。
- **可选做法**：
  - A. 保持现状。`/continue` 页按 WS 记忆事件里的 `turn_id` 取本轮数据（V7 已建议这样做），刷新后该页本来就不显示历史轮。后果：按 `message_id` 看到的是多轮合并的提示与归因。
  - B. `/continue` 轮的概要行不写 `message_id`。后果：这些行没有消息 id，一天后被遗留记录清理删除，刷新后操作提示与撤销入口消失。
- **建议**：A。这条路径没有界面入口，且 P-01 尚未确认。
- **目前做法**：按 A。如改为 B，只需改 `linsight/domain/services/memory_turns.py` 的 `begin`（`follow_up=True` 时 `message_id` 传 `None`）。

## 实际偏差

- **基线**：本 worktree 起点是 `main`，已移到 `b6a036d4b4`（见第一条决定）。
- **T068 文件清单之外**：改了 `workstation/domain/services/task_submit_service.py`（新增 `on_session_created` 参数）与 `workstation/domain/services/chat_service.py`（`:2699` 一处传参）。新增 `linsight/domain/services/memory_turns.py`（登记、轮次、记忆中间件、脱敏函数、整理读取入口）与 `memory/domain/services/linsight_turns.py`。
- **T070**：任务清单写 `_generate_tools` 的三个调用点之后追加；按 R9 改为在 `_generate_tools` 内部追加一次。`agent_factory.create_linsight_agent` 新增关键字参数 `memory_prompt`。
- **T072**：按 R3 落在 `task_exec._handle_exec_step` 入口一处，没有改 `stream_event_mapper.py` 与 `utils.py`；另改了 `context_budget.py`（`BishengSummarizationMiddleware` 覆盖 `_offload_to_backend` / `_aoffload_to_backend`，`ToolResultBudgetMiddleware` 对 `memory_` 工具截断）与 `workspace_backend.py`（`write` / `awrite` 拒绝写入记忆输出）。
- **T074**：没有改 `consolidator.py`，改的是 `factory.py`。
- **既有记忆文件**：只改了 `memory/domain/services/factory.py`（`get_consolidator` 增加 `extra_steps`），其余记忆代码均为新增文件。
- **既有测试**：没有修改。T072 之后 `test/memory/spike/test_v3_linsight_paths.py` 的断言（"原文会进入各落点"）按设计不再成立，该文件在 T075 删除。
- **tasks.md 勾选**：按 brief 不改 `tasks.md`，由协调者勾选。
- **〔基线比对〕**：按 brief 留给协调者在合并后运行。本 Wave 另跑了 `test/linsight test/workstation test/open_api test/memory`，结果见下节。

## 验收输出

Wave 11 验收命令（工作目录 `src/backend`）：

```
env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy uv run --no-sync python -m pytest test/memory test/linsight/test_memory_turns.py test/linsight/test_memory_inject.py test/linsight/test_memory_redaction.py -q -p no:cacheprovider
278 passed, 27 warnings in 30.43s
```

ruff（本 Wave 改动的全部 Python 文件）：

```
src/backend/.venv/bin/ruff check --select F821,F401 <changed py files>
All checks passed!
```

〔架构检查〕（对本 Wave 改动的 12 个源文件逐个运行 `scripts/arch-guard.sh`，与基线比较的新增 VIOLATION 行数）：`0`。〔分层检查〕：`0`。

相关目录回归（`test/linsight test/workstation test/open_api test/memory`）：

```
60 failed, 3345 passed, 8 skipped, 44 warnings, 2 errors in 387.65s (0:06:27)
```

与 `baseline/backend.xml` 逐条比较后，相对基线新增的失败只有 1 条：`test/open_api/test_execution_snapshot.py::test_worker_context_is_restored_and_reset`（断言 `get_current_tenant_id() is None`，实际是 5）。这条测试单独运行通过；与 `test/workstation` 或与本 Wave 的 4 个新测试文件一起运行也通过；在去掉本 Wave 新测试文件、只跑 `test/linsight` 既有测试再跑它时同样失败。所以失败原因是 `test/linsight` 下既有的技能类测试把租户上下文变量留在了进程里（它们调用 `set_current_tenant_id`），与本 Wave 无关。基线按顶层目录分片运行，`linsight` 与 `open_api` 不在同一进程，所以基线里没有出现。协调者按 `shard_run.py` 的分片规则做〔基线比对〕时不会触发这条顺序依赖。其余 59 条失败与 2 条报错都已在基线里失败（无中间件）。

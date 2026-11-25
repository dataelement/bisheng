# Wave 8 记录：接入日常模式（T049–T052）

## 自己定的决定

- T049–T052｜本 worktree 建在 `main`（af1894a538），不含 Wave 0–7 的记忆模块｜开工前用 `git switch -C worktree-wf_f7c3abc6-f5a-1 b6a036d4b4` 把本分支指向 `feat/v3.0.0/132-long-term-memory` 的 Wave 7 验收提交，再开始实现｜任务说明写明基底含 Wave 0–7；工作区当时干净，只动本 worktree 自己的分支。合并方请以 b6a036d4b4 为本分支的基底。
- T050｜新会话的 `chat_id` 在 endpoint 层还不存在（`_agent_initialize_chat` 里才生成），endpoint 无法直接调 `MemoryGate.open`｜登录态 endpoint（`workstation/api/endpoints/chat.py`）构造一个调用 `MemoryGate.open` 的回调 `memory_register`，经 `stream_chat_completion` 传到 `_agent_initialize_chat`，在会话确定之后、本轮问题行插入之前调用｜与助手/工作流的 `memory_register` 做法一致（决策 6、R2）；在问题行之前登记，首轮问题不会落到水位之下（AC-40）；开放面入口不传回调，所以不登记。
- T050｜开放面调用一个曾被登录态登记过的会话时，按 `chat_id` 仍能查到登记行｜只有传了 `memory_register` 的一轮才调用 `MemoryGate.resolve`；没传时既不带入、不给工具，也不写本轮记录、不调 `end_turn`｜比"有登记行就启用"更严，满足 AC-10。
- T050｜日常入口发起的任务模式（`_task_mode_stream_completion`）也经同一个 endpoint｜已有会话在 `submit_task_turn` 入队前登记；新会话只能在 submit 之后拿到 `chat_id` 再登记｜design 决策 6 写明"从日常入口转入任务模式的情况已被上一条覆盖"；新会话存在 worker 先于登记解析的竞争，后果只是该轮不用记忆（保守方向）。
- T050｜记忆已启用时工具列表恒非空，直连分支走不到｜测试用"记忆工具构建失败"驱动直连分支，断言系统消息仍带常驻块｜两条分支都要测（design §4.4）。
- T050｜作者或用户配置的工具与记忆工具同名｜加记忆工具前调 `split_reserved_tools`，以记忆工具为准并记告警｜决策 10"同名工具"。
- T050/T052｜本轮概要行何时写｜在轮开始取常驻块时写（`add_summary`），回答落库后由 `bind_turn` 补 `message_id`｜中断路径只能同步，开头写好后中断路径只需 `bind_turn_sync`，不需要同步版 `add_summary`；不改记忆模块既有文件。
- T050/T052｜常驻块为空或带入失败时 `add_summary` 的 `resident_rev`、`resident_day` 传什么｜传 `None`｜`TurnRecordService._flags` 把 `resident_rev is not None` 当作"有归因"；传空块的 rev 会让 `/flags` 与流式信号不一致（契约：has_attribution = 带入了非空常驻块或有检索）。
- T052｜`memory` SSE 事件的 `type` 字段契约未定｜用 `"over"`，载荷只含 `{turn_id, has_write, has_attribution}`；最后一条带 `message_id`（答案行 id），排在 `agent_answer/end` 之前｜前端按 category 识别；带 `message_id` 便于前端把标志挂到气泡上。
- T052｜一轮内何时下发信号｜每次工具结束后若标志有变化就下发一次（写入后立刻可见，AC-21）；结束前再下发一次带 `message_id` 的最终标志；三项标志都为假时不下发｜只读常驻、只检索的轮次同样有归因信号（AC-87）。
- T052｜记忆工具的错误文本（如参数校验错误）可能回显入参｜记忆工具的 `error` 一律替换为固定文本"记忆操作失败"｜脱敏只看工具名，不放宽（决策 10）。
- T052｜内容安全替换输出的路径（`persist_safety_replacement`）也会落答案行｜同样 `bind_turn` + `end_turn` 并下发信号｜替换前的显式写入已经发生，用户需要能看到并撤销。
- T051｜测试里计算事件顺序时，`user_message` 事件没有 `category` 键导致 KeyError（测试写错）｜改用 `b.get('category')`，随 T052 提交｜断言含义不变。
- T049/T051｜测试替身放哪｜新建 `test/workstation/memory_support.py`，从 `test/memory/conftest.py` 精简复制 SQLite 接缝、KV、索引、详情替身，不导入、不修改该 conftest；流的外围按 `test_stream_interrupt_persist.py` 的做法打桩，模型是脚本化的假 agent，会真实调用传给它的工具｜按任务说明"复制所需内容"。

## 需要用户确认

无。

## 实际偏差

- design §4.4"日常模式：对话入口"写"在 endpoint 里调 `MemoryGate.open`"。实际是 endpoint 构造调用 `MemoryGate.open` 的回调，由服务在插入问题行前调用（原因见上）。资格判定仍只在登录态 endpoint 发生。
- tasks T052 写"一轮结束前写本轮概要行"。实际在轮开始写、结束时绑定 `message_id`；结束前下发的信号与落库的行内容一致。
- 记忆模块（`src/backend/bisheng/memory/`）的既有文件未改动；新增 `bisheng/workstation/domain/services/daily_memory.py` 承载日常模式的接入逻辑。
- 按任务说明，未勾选 `tasks.md`，未改 `progress.md`、`decisions-self.md`、`design.md`。
- 既有用例 `test/workstation/test_knowledge_space_tag_selection.py::test_repository_checks_tag_owner_type_and_space_file_links` 在只跑 `test/workstation` 目录时失败、单独跑通过；把 `chat_service.py`、`chat.py` 临时换回基底版本后同样失败，属于既有的顺序依赖，与本 Wave 无关。`test/open_api test/linsight` 两个目录对基线比对为 `NEW FAILURES: 0`。〔基线比对〕全量由合并方执行。

## 验收输出

Wave 验收命令（工作目录 `src/backend/`）：

```
env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy uv run --no-sync python -m pytest test/memory test/workstation/test_memory_config.py test/workstation/test_memory_inject.py test/workstation/test_memory_events.py -q -p no:cacheprovider
270 passed, 27 warnings in 42.04s
```

ruff（F821、F401，改动的全部 py 文件）：

```
All checks passed!
```

〔架构检查〕（对改动的 4 个源文件逐个检查，与基线比较的新增 VIOLATION 行数）：`0`；〔分层检查〕：`0`。

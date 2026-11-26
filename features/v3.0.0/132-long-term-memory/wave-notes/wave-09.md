# Wave 9 记录：接入助手（T053–T059）

## 自己定的决定

- T053–T059｜本 worktree 建在 `main`（af1894a538）上，不含 Wave 0–7｜用 `git switch -C worktree-wf_f7c3abc6-f5a-2 b6a036d4b4` 把本分支切到 `feat/v3.0.0/132-long-term-memory` 的 Wave 7 验收提交上再开工｜任务说明写明基线应含 Wave 0–7；工作树当时干净，没有丢失任何改动。
- T054｜记忆逻辑放在哪里｜新建 `api/services/assistant_memory.py`，`assistant_agent.py` 只加调用｜`assistant_agent.py` 的改动保持最小；新文件属于 Service 层，可以引用 `memory`。
- T054｜开关开启时记忆工具每轮都要带新的 `MemoryContext`（`turn_id` 每轮不同，工具描述里还有当天日期）｜开启的轮次每轮重建工具与 agent；关闭的轮次只在"上一轮是开启"时重建一次｜tasks 写"状态变化时重建"，每轮重建是它的超集，结果一致；`init_agent` 只做图的构建，代价小。
- T054｜开关关闭的轮次是否复制输入列表｜只有需要改动（插入常驻或替换回放的记忆结果）时才复制，否则原样返回同一个列表｜V5 证明客户端切片依赖列表别名，记忆关闭时与改动前行为完全一致。
- T054｜开关先读还是登记行先读｜先按主键读 `assistant.memory_enabled`，为关时不再调用 `MemoryGate.resolve`｜少一次查询，判定结果相同。
- T054｜作者配置了 `memory_` 前缀的工具、而助手记忆关闭时｜保留作者的工具；只在记忆开启的轮次用 `split_reserved_tools` 去掉并记告警｜记忆关闭时不改变现有行为。
- T054/T056｜本轮常驻文本为空时概要行的 `resident_rev`｜写 `None`｜`TurnRecordService._flags` 把 `resident_rev` 非空当作"有归因"；契约要求只有常驻块非空或有检索时才算有归因。
- T056｜WebSocket `memory` 消息的形状｜`{"category": "memory", "type": "memory", "message": {turn_id, has_write, has_attribution}, "chat_id", "flow_id", "message_id": null, ...}`，不经 `ChatResponse`（其 `type` 校验不允许 `memory`）｜契约写"message type `memory`"，`category` 与 `type` 都设为 `memory`，前端按任一字段判别都成立。
- T056｜何时下发信号｜显式写入成功时立即发一次（工具 `on_write`），`run()` 返回前若有写入或归因再发一次｜中断的轮次也能拿到写入提示；前端按 `turn_id` 去重即可。
- T056｜`on_tool_start` 的脱敏入参来源｜优先用回调的 `inputs` 字典（拿得到 `action` 作为 `op`），没有时用 `input_str`｜`input_str` 是 Python repr，不是 JSON，解析不出 `op`。
- T056｜工具出错路径的输出｜错误文本整体替换为 `{"redacted": true, "op", "item_ids": []}` 的 JSON｜错误文本可能引用条目原文（测试里构造了这种情况）。
- T056｜ReAct 结果里的 `AgentAction` 带原始参数｜在 `finalize_result` 里一并脱敏｜它不落库，但会进 `BISHENG_RECORD_HISTORY` 调试文件；脱敏代价为零。
- T058｜异常分支（不落回答）如何结束本轮｜`question_saved` 为真时调 `after_answer_persisted(None, False)`，`end_turn` 用会话当前最大消息 id｜R2 要求异常分支也结束本轮。
- T058｜登记回调或落库回调抛错｜`client.py` 里捕获并记日志，不影响对话｜记忆失败不得打断助手（AC-61 的同类原则）。
- T053/T055/T057｜测试要用 `test/memory/conftest.py` 的夹具，但不能改它｜测试文件用 `from test.memory.conftest import ... # noqa: F401` 引入夹具；共享的桩模型与工厂注入放在新文件 `test/assistant/memory_support.py`｜不新增 conftest，不影响 `test/assistant` 下其它测试。
- T054｜T053 的一条断言写错：ReAct 把问题包成 "Question: ..." 的消息｜改为断言问题文本包含在最后一条消息里、常驻消息位于它之前｜测试本身写错，判定没有放宽。
- T058｜T057 的两处测试写错：`update_assistant` 现有代码把未传的 `temperature` 写成 `None` 导致 `AssistantInfo` 校验失败；构造 `ChatClient` 时读到真实配置存储｜测试请求里带上 `temperature`；在测试夹具里替换 `client_module.settings` 与历史读取｜都是测试替身不完整，与功能无关。

## 需要用户确认

无。

## 实际偏差

- design 决策 11 写"状态变化时重建 agent"；实现为开启的轮次每轮重建（见上）。行为相同。
- tasks T054/T056 只点名 `assistant_agent.py`；实际新增 `api/services/assistant_memory.py` 承载记忆逻辑，`assistant_agent.py` 只调用它。
- `astream()` 只做了注入与结果处理，没有下发信号与本轮结束：它在 `client.py` 中没有调用方（V5 已确认）。
- 已知的既有测试污染（与本 Wave 无关）：`test/api/test_assistant_knowledge_auth_gate.py`、`test/api/test_assistant_runlog_frames.py`、`test/app_template/test_template_api.py` 与 `test/audit/test_audit_log_tenant_scope.py` 放在同一进程里跑时，审计测试 26 条失败；不含本 Wave 的测试文件时同样失败。〔基线比对〕按目录分片运行，不受影响。
- 未改 `memory/` 下任何既有文件，未改 `common/chat/manager.py`。

## 验收输出

Wave 9 验收命令（`src/backend/`）：`uv run --no-sync python -m pytest test/memory test/assistant/test_memory_turn.py test/assistant/test_memory_redaction.py test/assistant/test_memory_session.py -q -p no:cacheprovider -rs`

```
275 passed, 153 warnings in 35.47s
```

〔架构检查〕：`0`；〔分层检查〕：`0`。〔基线比对〕由协调者合并后运行。

ruff（`ruff check --select F821,F401` 本 Wave 改动的全部 Python 文件）：

```
All checks passed!
```

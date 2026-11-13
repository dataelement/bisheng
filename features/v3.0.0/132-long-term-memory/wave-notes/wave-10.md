# Wave 10 记录：接入工作流（T060–T066）

## 自己定的决定

- 环境｜worktree 分支创建时基于 main（af1894a538），不含 Wave 0–7 的记忆模块｜在本 worktree 内用 `git checkout -B` 把本分支移到 `feat/v3.0.0/132-long-term-memory` 的 b6a036d4b4 再开工｜任务说明写明基线应含 Wave 0–7；工作区当时没有改动，不影响其他 worktree。
- T061｜`SearchService.search` 只取回调用前已知 id 的详情，节点要的是"所有带详情的命中都用详情全文"｜新建 `memory/domain/services/workflow_retrieval.py`：先检索，再按 `detail_object_key(tenant, user, item_id)` 逐条读取详情；读取失败时保留短内容并计 `detail_read_failed`；成功的计入 `mark_detail_read`｜不改 `search.py`，避免与并行 Wave 冲突；详情对象键由同一个函数生成，与 `MinioDetailStore.put` 一致。
- T061｜输出项 metadata 是否带条目 id｜不带，只有 `type`、`recorded_at`、`event_time`、`source` 四个键｜按跨 Wave 契约原样实现；`event_time` 没有时为 `null`。
- T061｜`limit` 的合法取值｜接受 1–100 的 int、整数值的 float（如 30.0）与纯数字字符串；拒绝 bool、小数、非数字、越界值，均抛 12108；缺省为 20｜JSON 里 `30` 与 `30.0` 前端无法区分；bool 是 int 子类，单独排除。
- T061｜`limit` 在哪校验｜节点构造时调用 `parse_limit`；上线时在 `update_flow_status` 先于 `Workflow(...)` 显式校验｜构造时抛出会被上线流程包成 `WorkFlowInitError(10526)`，显式校验才能返回 12108。
- T061｜引用变量不是文字时怎么转｜dict / list / tuple 用 `json.dumps(ensure_ascii=False)`，None 转空串，其他用 `str()`；整个查询 strip 后为空则不检索｜默认的 `PromptTemplateParser.format` 对 dict 用 Python repr，不是可读文字。
- T061｜节点从同步上下文调用异步检索｜用 `bisheng.utils.async_utils.run_async_safe`，超时 60 秒｜与 `workflow/common/knowledge.py` 的知识空间检索做法一致。
- T061｜运行日志｜`parse_log` 只返回 `{id}.query` 与 `{id}.retrieved_count` 两项；节点内不打印条目内容｜AC-86。
- T061｜节点内的记忆模块导入｜在 `_run` 与上线校验函数里延迟导入｜`node_manage` 在导入期加载所有节点，延迟导入可以避免工作流包导入时拉起记忆模块。
- T063｜开关查询的位置｜按 R5 放在 `worker/workflow/tasks.py::_execute_workflow`（函数 `_online_memory_switch`）；`chat_id` 为空时不查；查询异常按关处理｜tasks.md T063 的文件清单没有列 tasks.py，以 R5 为准；评测与调试运行不读库。
- T063｜上线校验函数放在哪｜`workflow/nodes/memory_retriever/memory_retriever.py::check_memory_nodes_for_publish`，由 `api/services/workflow.py` 的 ONLINE 分支调用；先查开关（12109），再逐节点查 `limit`（12108）｜节点类型与参数结构属于工作流模块；读开关复用 `app_switch.start_node_memory_enabled`。
- T065｜一轮结束时 `enabled` 怎么判定｜`MemoryGate.resolve_sync(chat_id, SCENE_WORKFLOW, app_enabled=本次运行的开关) is not None`；续跑时开关取自 `_global_workflow` 里原对象的 `graph_state`；原对象已失效时按未启用处理｜续跑沿用首次取得的值（R5）；整个调用包在 try 里，失败不改变任务结果。
- T065｜登记回调的异常｜`WorkflowClient._register_memory_session` 捕获异常并写日志，支持同步或异步回调｜登记失败不能中断工作流；`common/` 下的客户端不导入记忆模块。
- T060/T062/T064｜工作流测试目录下的夹具｜新建 `test/workflow/memory_fixtures.py`，复用 `test/memory/conftest.py` 里的替身类，自建夹具；异步引擎用 `NullPool`｜节点在 `run_async_safe` 的桥接事件循环上检索，aiosqlite 连接不能跨事件循环复用。
- T062/T064｜导入真实的 `bisheng.worker.workflow.tasks`｜沿用 `test/workflow/test_workflow_tasks.py` 的做法：给被预先 mock 的 `bisheng.worker` 一个带包路径的模块｜仓库已有先例。
- T063→T066｜T063 提交后 `test/memory/spike/test_v4_graph_state.py` 的两个用例失败（它把 `GraphState` 替换成不接受参数的 lambda）｜按任务顺序由 T066 删除该实验测试｜T066 的任务内容就是删除它；T063–T065 三个提交之间这两个用例为红。

## 需要用户确认

无。

## 实际偏差

- `worker/workflow/tasks.py` 的开关查询在 T063 中完成（tasks.md 把 tasks.py 列在 T065），依据 design §9 R5。
- 新增文件 `memory/domain/services/workflow_retrieval.py`（tasks.md 未列），原因见上文"自己定的决定"。没有改动 `memory/` 下的既有文件。
- AC-70 中"只有编辑权限的用户能保存开关"沿用既有的版本保存接口（`FlowService.update_version_info` → `judge_flow_write_permission`），本 Wave 没有改动权限代码，只为它补了测试。
- AC-60、AC-28 用静态扫描测试：`bisheng/workflow/` 与 `bisheng/worker/workflow/` 下没有常驻记忆与写入能力的调用。
- 前端部分（节点模板、开始节点开关、保存时的 `limit` 校验）不在本 Wave。

## 验收输出

Wave 10 验收命令（cwd `src/backend`，不含〔基线比对〕）：

```
env -u ALL_PROXY ... uv run --no-sync python -m pytest test/memory test/workflow/test_memory_retriever_node.py test/workflow/test_memory_switch.py test/workflow/test_memory_session.py -q -p no:cacheprovider -rs
300 passed, 27 warnings in 44.04s
```

ruff（本 Wave 改动的 14 个 Python 文件）：

```
.venv/bin/ruff check --select F821,F401 <14 files>
All checks passed!
```

〔架构检查〕只对本 Wave 改动的文件逐个运行 arch-guard，与基线比较后新增 VIOLATION 行数为 `0`；〔分层检查〕输出 `0`。`test/workflow` 全目录有 5 个失败（test_docx_replace、test_docx_string ×2、test_retrieval_question ×2），在 `baseline/backend.xml` 里都已是失败。

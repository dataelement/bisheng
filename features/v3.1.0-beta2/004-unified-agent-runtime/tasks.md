# Tasks: 日常对话与深度研究统一（F004-unified-agent-runtime）

**关联规格**: [spec.md](./spec.md) · **设计**: [design.md](./design.md) · **QA 参考**: [test-cases.md](./test-cases.md)
**版本**: v3.1.0-beta2

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-11-18 用户确认，51 条 AC |
| design.md | ✅ 已评审 | 2026-11-18 用户确认，决策 1 至决策 12；接手时的第一入口 |
| tasks.md | ✅ 已拆解 | 2026-11-18 `/sdd-review tasks` 自审通过；任务编号 T001 至 T063，T063 排在 T044 之后 |
| 实现 | 🔨 进行中 | 9 / 63 完成（Wave 0 全部完成，2026-11-18，未提交）。偏差处理见 design.md 顶部调整原则 + `docs/SDD-Guide.md` §3-§4 |

---

## 开发模式

- **按 Wave 组织**：Wave 对应 design §4.6 的分期（P0 至 P4）。同一 Wave 内没有依赖关系的任务可以并行。每个 Wave 结束都能独立上线和回滚。
- **后端 Test-First**：测试任务排在配对的实现任务之前。测试用 `scripts/spike_unified_runtime/_scripted_model.py` 里的脚本化模型思路驱动 agent，不依赖真实模型；Redis 用 `fakeredis`（含 Lua 支持）。新测试放 `test/linsight/` 或 `test/workstation/`。
- **前端**：只涉及 Client（`src/frontend/client/`）。store 和事件归并逻辑写 jest 单测；界面任务附手动验证步骤，对照 [prototype/index.html](./prototype/index.html)。
- **Worker**：本特性不新增 Celery 任务。Linsight worker 的队列项沿用现有方式携带租户信息（`worker.py` 的 `process_one_item` 在执行前恢复租户上下文）；新增的队列项类型必须带同样的字段。
- **路径约定**：后端路径相对 `src/backend/`，前端路径相对 `src/frontend/client/src/`。
- **数据库**：本特性不新增表、不改列。新增信息都放进已有的 JSON 字段（`task_data.previous_name`、运行记录里的线程 id、回答行 `extra` 的运行 id 与排队标记），旧版本读到这些字段时忽略即可，所以回滚不需要数据操作。
- **跨特性影响**：F016（回答行 `files` 与审计下载）、F132（记忆接线）、引用编号表、开放 API（F073）、DSH 额度。涉及它们的任务（T030、T035、T055、T059、T028）都要求对方现有测试继续通过；写入行为的归属不变。
- **设计论证不在此重复**：每个任务只写做什么，为什么见 design 对应决策。

---

## Tasks

### Wave 0（P0）：前置验证、依赖升级、计划对齐修正

- [x] **T001**: 核实私有化部署的最低 Redis 版本
  **文件**: `features/v3.1.0-beta2/004-unified-agent-runtime/design.md`（回写 K8）
  **逻辑**: 查 `docker/` 下各部署形态的 Redis 镜像版本与部署文档写明的最低版本；确认 Stream（`XADD`/`XREAD`/`XTRIM`）可用。把结论和出处写进 design K8。若存在低于 5.0 的受支持环境，停下并按 design 决策 4 的“何时重新考虑”与用户确认。
  **依赖**: 无

- [x] **T002**: 取升级前的回归基线
  **文件**: `features/v3.1.0-beta2/004-unified-agent-runtime/baseline-before-upgrade.txt`
  **逻辑**: 在升级依赖之前，于 `src/backend/` 运行 `.venv/bin/python -m pytest test/linsight test/workstation test/open_api -q -p no:cacheprovider`，把每个用例的通过或失败结果保存到该文件，供 T004 做差分。
  **依赖**: 无

- [x] **T003**: 升级 deepagents、langchain、langchain-core
  **文件**: `pyproject.toml`、`uv.lock`
  **逻辑**: 把约束改为 `deepagents>=0.7.39,<0.8`、`langchain>=1.5,<2.0`、`langchain-core>=1.8.1,<2.0`。逐个包用 `uv lock --upgrade-package "pkg==ver"` 升级，不做整体升级。检查 `git diff --stat uv.lock`，把被连带移动的包列进提交说明。新引入的传递依赖先查许可证。
  **依赖**: T002

- [x] **T004**: 0.7 行为差异的回归测试
  **文件**: `test/linsight/test_deepagents_07_compat.py`
  **逻辑**: 用脚本化模型断言：① `planned` 构图后绑定的工具含 `write_todos`，且 `write_todos` 之后 `updates` 流里出现 `todos` 增量，结构为 `[{content, status}]`；② 解析 `read_file` 与空目录 `ls` 输出的现有代码在新格式（`@@ lines a-b of n @@`、`No files found`）下行为正确。再运行 T002 的同一选择集，与基线逐用例对比，新增失败必须在本任务或 T005 内解决。
  **测试**: `test_planned_graph_has_write_todos`、`test_todos_delta_shape`、`test_read_file_format_consumers`、`test_empty_ls_consumers`
  **覆盖 AC**: AC-07
  **依赖**: T003

- [x] **T005**: 适配 0.7：显式挂载计划能力与输出格式
  **文件**: `bisheng/linsight/domain/services/agent_factory.py`、`bisheng/linsight/domain/services/context_budget.py`
  **逻辑**: 从 `langchain.agents.middleware` 导入 `TodoListMiddleware`，在主图与子代理的中间件列表里显式传入（保持今天的行为）。全仓搜索依赖 `read_file` 行号格式与 `ls` 返回 `[]` 的代码和提示词示例并修正。替换已废弃的 `BASE_AGENT_PROMPT` 引用。
  **测试**: T004 全部通过；与 T002 基线差分无新增失败
  **覆盖 AC**: AC-07
  **依赖**: T004

- [x] **T006**: `_diff_todos` 对齐的单元测试
  **文件**: `test/linsight/test_stream_event_mapper.py`（追加）
  **逻辑**: 以三条计划为基准，分别做改写一条、末尾追加、中间插入、删除中间一条，断言未改动条目的 task id 不变、状态不变；被删除的条目产生 `terminated` 的结束事件；被改写的条目带上改写前的文字。
  **测试**: `test_diff_reword_keeps_ids`、`test_diff_append_keeps_ids`、`test_diff_insert_in_middle_keeps_ids`、`test_diff_delete_marks_terminated`、`test_diff_reword_carries_previous_content`
  **覆盖 AC**: AC-09, AC-10
  **依赖**: 无

- [x] **T007**: `_diff_todos` 改为两趟匹配
  **文件**: `bisheng/linsight/domain/services/stream_event_mapper.py`
  **逻辑**: 第一趟对全部新条目做精确内容匹配；第二趟对剩余新条目按位置匹配尚未被占用的旧条目；其余为新增。改写分支在投影里记录 `previous_content`。
  **测试**: T006 全部通过；`scripts/spike_unified_runtime/s3b_diff_todos_alignment.py` 四项均为 `aligned: true`
  **覆盖 AC**: AC-09, AC-10
  **依赖**: T006

- [x] **T008**: 核实两项未验证的假设
  **文件**: `features/v3.1.0-beta2/004-unified-agent-runtime/design.md`（回写 §4.4 与 §7）
  **逻辑**: ① 读代码确认服务端对 `task_mode=true` 是否已校验 `linsight_task_mode` 权限，记录文件与行号；② 对比日常对话的读图组件（`common/image_view`）与深度研究的读图处理，判断能否以中间件形式接入统一工厂，给出结论。两项结论回写 design。
  **依赖**: 无

- [x] **T009**: 真实模型的插话改计划成功率
  **文件**: `scripts/spike_unified_runtime/s3c_steer_real_model.py`、`scripts/spike_unified_runtime/README.md`
  **逻辑**: 在 114 上用后端虚拟环境运行（模型由 `LLMService` 按模型 id 取得，不在脚本里写密钥）。对工作台模型列表里的 3 个模型各跑 5 次：先让 agent 写出计划，再经收件箱注入“第 3 步改成做 PPT”，记录模型是否调用 `write_todos` 改写第 3 条。把成功次数表写进 README 和 design 决策 6。任一模型成功率低于 4/5 时停下，与用户确认是否按 design 决策 6 的备选处理。
  **依赖**: T005, T007

### Wave 1（P1）：统一内核、会话线程、事件通道、发送入口（用户不可见）

- [ ] **T010**: 新旧通道切换开关
  **文件**: `bisheng/core/config/settings.py`（或工作台配置所在文件，以现有 `daily_chat` 配置的位置为准）、`bisheng/workstation/domain/services/workstation_service.py`
  **逻辑**: 增加按租户生效的布尔项 `unified_runtime_enabled`，缺省 `false`。提供 `is_unified_runtime_enabled(tenant_id)` 读取函数。未知键在旧镜像上被忽略，不影响启动。
  **依赖**: 无

- [ ] **T011**: 事件流读写的单元测试
  **文件**: `test/linsight/test_run_event_stream.py`
  **逻辑**: 断言：写入返回递增的条目 id；从某个游标读只得到其后的事件；超过 `MAXLEN` 后最早的条目被裁掉；游标早于现存最早条目时读取端先得到一个 `resync` 事件，内容等于累计状态；逐字事件在 50 毫秒窗口内被合并成一条；运行结束后流在 1 小时后过期。
  **测试**: `test_append_and_read_from_cursor`、`test_maxlen_trims`、`test_stale_cursor_gets_resync`、`test_text_coalescing`、`test_stream_expires_after_run`
  **覆盖 AC**: AC-31
  **依赖**: T001

- [ ] **T012**: 事件流读写实现
  **文件**: `bisheng/linsight/domain/services/run_event_stream.py`
  **逻辑**: 提供 `append(conversation_id, event)`、`read(conversation_id, cursor)`（异步迭代）、`snapshot(conversation_id)`、`update_snapshot(...)`。键：`bisheng:run:events:{conversation_id}`（Stream）与 `bisheng:run:snapshot:{conversation_id}`（累计状态）。事件外形与类型见 design §4.3。
  **测试**: T011 全部通过
  **覆盖 AC**: AC-31
  **依赖**: T011

- [ ] **T013**: 运行租约与停止标记的单元测试
  **文件**: `test/workstation/test_run_lease.py`
  **逻辑**: 断言：占用租约后同一会话再次占用失败；续租延长过期时间；不续租则 30 秒后租约消失；设置停止标记后 `should_stop(run_id)` 在 1 秒内返回真；运行进入“等待用户回答”时租约释放且状态变为 `waiting`。
  **测试**: `test_acquire_is_exclusive`、`test_renew_extends`、`test_expires_without_renew`、`test_stop_flag_visible`、`test_park_releases_lease`
  **覆盖 AC**: AC-22, AC-29, AC-33
  **依赖**: 无

- [ ] **T014**: 运行租约与停止标记实现
  **文件**: `bisheng/workstation/domain/services/run_lease.py`
  **逻辑**: 会话状态键 `bisheng:run:state:{conversation_id}`（字段：`status` 取 `idle`/`running`/`waiting`，`run_id`，`profile`，`lease_until`）。提供 `acquire`、`renew`、`release`、`park`、`request_stop`、`should_stop`。所有状态只存 Redis，不存进程内存。
  **测试**: T013 全部通过
  **覆盖 AC**: AC-22, AC-29, AC-33
  **依赖**: T013

- [ ] **T015**: 发送入口原子判断的单元测试
  **文件**: `test/workstation/test_run_dispatch.py`
  **逻辑**: 断言四个分支：空闲时返回 `started` 并占用租约；运行中且租约有效时消息进收件箱并返回 `queued`；等待回答时消息作为回答、返回 `started`、不新建运行；运行中但租约过期时旧运行被标失败并发 `run_failed`，随后按空闲处理。并发断言：同一会话并发提交 20 条，恰好 1 条得到 `started`，其余 19 条进收件箱且顺序与提交顺序一致。结束断言：运行结束时收件箱非空则产生一次接力运行，档位取收件箱第一条消息携带的设置，接力运行被投进 worker 队列；收件箱为空则状态回到空闲。排队断言：`planned` 档没有空闲名额时返回的事件里有 `queued` 与位置。
  **测试**: `test_idle_starts_run`、`test_running_enqueues`、`test_waiting_treated_as_answer`、`test_expired_lease_fails_old_run`、`test_concurrent_send_single_run`、`test_finish_with_inbox_starts_relay`、`test_finish_empty_goes_idle`、`test_planned_queue_position`
  **覆盖 AC**: AC-16, AC-17, AC-20, AC-21, AC-33, AC-36
  **依赖**: T014

- [ ] **T016**: 发送入口原子判断实现
  **文件**: `bisheng/workstation/domain/services/run_dispatch.py`、`bisheng/workstation/domain/services/run_dispatch.lua`
  **逻辑**: 两段 Lua：`dispatch`（四分支）与 `finish`（置空闲并检查收件箱）。收件箱键 `bisheng:run:inbox:{conversation_id}`，每条是 JSON：`{message_id, text, task_mode, tools, skills, knowledge, files, user_id, tenant_id, ts}`。`submit(conversation_id, message) -> {run_id, disposition, message_id}`；`on_run_finished(conversation_id)` 负责接力。接力运行的队列项带 `tenant_id`。
  **测试**: T015 全部通过
  **覆盖 AC**: AC-16, AC-17, AC-20, AC-21, AC-33, AC-36
  **依赖**: T015

- [ ] **T017**: 统一事件映射的单元测试
  **文件**: `test/linsight/test_unified_event_mapping.py`
  **逻辑**: 用脚本化模型跑一次 `planned` 运行，断言映射器产出的事件序列包含 `run_started`、`plan`（完整条目列表，含 `id`/`content`/`status`，改写后带 `previous_content`，被去掉的条目状态为 `cancelled`）、`tool_call`、`text`、`run_finished`；`plan` 事件能算出“已完成条数 / 总条数”；模型调用抛错时产出 `run_failed`，`data` 含 `code`、`reason`、`detail`、`reference_id`；`interrupt` 产出 `ask_user`。
  **测试**: `test_planned_event_sequence`、`test_plan_event_full_snapshot`、`test_plan_progress_counts`、`test_cancelled_item_status`、`test_run_failed_fields`、`test_interrupt_maps_to_ask_user`
  **覆盖 AC**: AC-08, AC-10, AC-20, AC-32, AC-35
  **依赖**: T007

- [ ] **T018**: 统一事件映射实现
  **文件**: `bisheng/linsight/domain/services/stream_event_mapper.py`、`bisheng/linsight/domain/schemas/run_events.py`
  **逻辑**: 新增事件 schema（design §4.3 的类型与 `data` 字段）。映射器增加一个输出口，把现有内部事件转成统一事件并交给 `run_event_stream.append`；现有输出口保留，供旧通道使用。
  **测试**: T017 全部通过
  **覆盖 AC**: AC-08, AC-10, AC-20, AC-32, AC-35
  **依赖**: T012, T017

- [ ] **T019**: 统一内核工厂两个档位的单元测试
  **文件**: `test/linsight/test_agent_factory_profiles.py`
  **逻辑**: 断言：`direct` 档绑定的工具不含 `write_todos`，系统提示词不含计划指令；`planned` 档含 `write_todos`；两个档位在传入相同的工具、知识库、联网搜索、技能、代码执行、记忆设置时，绑定的业务工具集合相同；两个档位都绑定 `ask_user`；无人值守渠道下两个档位都不绑定 `ask_user`。
  **测试**: `test_direct_has_no_todos`、`test_planned_has_todos`、`test_same_business_tools_in_both_profiles`、`test_ask_user_in_both_profiles`、`test_unattended_has_no_ask_user`
  **覆盖 AC**: AC-02, AC-03, AC-05, AC-23, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48
  **依赖**: T005

- [ ] **T020**: 统一内核工厂实现
  **文件**: `bisheng/linsight/domain/services/agent_factory.py`、`bisheng/linsight/domain/services/base_prompt.py`
  **逻辑**: `create_linsight_agent` 增加 `profile: Literal["direct", "planned"]` 参数。`direct`：不传 `TodoListMiddleware`，使用精简提示词，状态定义保留 `todos` 通道。`planned`：现有行为。提示词由实际装配的工具列表生成（prompt 与 tool 保持一致）。
  **测试**: T019 全部通过
  **覆盖 AC**: AC-02, AC-03, AC-05, AC-23, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48
  **依赖**: T019

- [ ] **T021**: 工具装配合并的单元测试
  **文件**: `test/workstation/test_unified_tool_assembly.py`
  **逻辑**: 给定同一组请求参数（勾选的工具、知识库选择、联网开关、技能、记忆开关），断言统一装配函数返回的工具列表覆盖今天日常对话 `_prepare_tools` 与深度研究 `init_linsight_config_tools` 各自能返回的工具；知识库工具的可检索范围只含该用户有权限的知识库；单个工具初始化失败不影响其余工具，并产出一条可见的失败事件。
  **测试**: `test_assembly_superset_of_both_paths`、`test_kb_scope_limited_to_permitted`、`test_single_tool_failure_isolated`
  **覆盖 AC**: AC-05, AC-43, AC-44, AC-45
  **依赖**: 无

- [ ] **T022**: 工具装配合并实现
  **文件**: `bisheng/linsight/domain/services/tool_assembly.py`、`bisheng/workstation/domain/services/chat_service.py`、`bisheng/linsight/domain/services/workbench_impl.py`
  **逻辑**: 抽出一个装配函数供两个档位调用；`chat_service._prepare_tools` 与 `workbench_impl.init_linsight_config_tools` 改为调用它（两处都只是把函数体换成一次调用）。互不依赖的工具并行初始化。引用包装（`DailyChatCitationToolWrapper`）与读图包装保留在装配函数里。
  **测试**: T021 全部通过；`test/workstation/test_agent_tool_error_handling.py` 仍通过
  **覆盖 AC**: AC-05, AC-43, AC-44, AC-45
  **依赖**: T021

- [ ] **T023**: 工作区前缀泛化的单元测试
  **文件**: `test/linsight/test_workspace_prefix.py`
  **逻辑**: 断言：`WorkspaceBackend` 以任意前缀构造后，`ls`/`read`/`write` 都落在该前缀下；前缀到前缀的拷贝函数把 `output/` 与 `uploads/` 拷到目标前缀；以 `workspace/{svid}` 前缀构造时行为与今天一致。
  **测试**: `test_backend_scoped_to_prefix`、`test_copy_prefix_to_prefix`、`test_svid_prefix_backward_compatible`
  **覆盖 AC**: AC-26, AC-40
  **依赖**: 无

- [ ] **T024**: 工作区前缀泛化实现
  **文件**: `bisheng/linsight/domain/services/workspace_backend.py`、`bisheng/linsight/domain/task_exec.py`
  **逻辑**: `WorkspaceBackend` 的 `svid` 参数改为 `workspace_prefix`（保留 `svid` 关键字作为兼容入口）；`_seed_workspace_from_previous` 改为接受源前缀与目标前缀。`final_result/{svid}/` 交付快照的路径不变。
  **测试**: T023 全部通过；`test/linsight/test_workspace_original_sync.py` 仍通过
  **覆盖 AC**: AC-26, AC-40
  **依赖**: T023

- [ ] **T025**: 会话线程的单元测试
  **文件**: `test/linsight/test_conversation_thread.py`
  **逻辑**: 用内存 checkpointer 与脚本化模型断言：同一会话依次跑 `planned`、`direct`、`planned`，后一次运行的模型输入包含前面运行的消息；线程没有 checkpoint 时，运行从 `ChatMessage` 历史重建消息并从最近一个版本的工作区接入文件；旧运行记录没有保存线程 id 时，恢复使用 `session_version_id` 作为线程 id；运行被停止或失败后，下一次运行仍能读到此前的消息。
  **测试**: `test_profiles_alternate_on_one_thread`、`test_rebuild_when_no_checkpoint`、`test_legacy_run_resumes_on_svid_thread`、`test_next_run_after_stop_sees_history`
  **覆盖 AC**: AC-01, AC-04, AC-21, AC-26, AC-30, AC-40
  **依赖**: T020, T024

- [ ] **T026**: 会话线程实现
  **文件**: `bisheng/linsight/domain/task_exec.py`、`bisheng/linsight/domain/models/linsight_session_version.py`
  **逻辑**: 新通道下 `thread_id` 取会话 id，工作区前缀取 `workspace/{conversation_id}`。运行记录在已有的 JSON 字段里保存本次使用的线程 id（不改表结构）；读取时缺省为 `session_version_id`。无 checkpoint 时调用历史重建与工作区接入。
  **测试**: T025 全部通过
  **覆盖 AC**: AC-01, AC-04, AC-21, AC-26, AC-30, AC-40
  **依赖**: T025

- [ ] **T027**: `direct` 运行执行器的单元测试
  **文件**: `test/workstation/test_direct_run.py`
  **逻辑**: 用脚本化模型断言：执行器在后台协程里跑完一次 `direct` 运行，事件写入事件流；运行期间按间隔续租；检测到停止标记后在 5 秒内结束并发 `run_stopped`，已输出的文字保留在累计状态里；`interrupt` 时发 `ask_user`、释放租约、状态变 `waiting`；收到回答后用 `Command(resume=...)` 继续；一次运行只做一次额度准入；发出模型请求之前不创建工作区本地目录；运行结束调用 `on_run_finished`。
  **测试**: `test_run_writes_events`、`test_heartbeat_renews`、`test_stop_within_5s_keeps_output`、`test_interrupt_parks`、`test_resume_continues`、`test_single_admission_per_run`、`test_no_workspace_dir_before_model_call`、`test_finish_triggers_dispatch`
  **覆盖 AC**: AC-21, AC-22, AC-29, AC-34, AC-37
  **依赖**: T016, T018, T020, T026

- [ ] **T028**: `direct` 运行执行器实现
  **文件**: `bisheng/workstation/domain/services/direct_run.py`
  **逻辑**: `start_direct_run(run_ctx)` 用 `asyncio.create_task` 启动与请求无关的协程，并持有任务引用防止被回收。协程内：准入（`admit_round`）→ 构建 `direct` 档 agent → `astream` → 映射 → 事件流；并行一个续租与停止检查循环。异常路径发 `run_failed` 并调用 `on_run_finished`。同一函数也供 worker 执行接力运行时调用。
  **测试**: T027 全部通过
  **覆盖 AC**: AC-21, AC-22, AC-29, AC-34, AC-37
  **依赖**: T027

- [ ] **T029**: 两个落库投影器的单元测试
  **文件**: `test/workstation/test_run_projectors.py`
  **逻辑**: `direct` 投影器：运行结束后写出的回答行，`category`、`type`、`message` JSON 的 `{msg, events}` 结构、`files` 字段、引用记录与今天 `build_answer_row` 的结果一致；中途停止时保存已生成的部分；回答行 `extra` 里有运行 id。`planned` 投影器：计划条目写入 `linsight_execute_task`，改写后的行 `task_data` 含 `previous_name`，被去掉的条目为 `TERMINATED`；高频事件按节流落库（N 个事件触发的写库次数有上限）；重读数据库得到的计划与事件流最后一个 `plan` 事件一致。
  **测试**: `test_direct_answer_row_shape_unchanged`、`test_direct_partial_saved_on_stop`、`test_planned_previous_name_persisted`、`test_planned_cancelled_persisted`、`test_planned_write_throttled`、`test_plan_reload_matches_stream`
  **覆盖 AC**: AC-10, AC-11, AC-40, AC-41, AC-42
  **依赖**: T018

- [ ] **T030**: 两个落库投影器实现
  **文件**: `bisheng/workstation/domain/services/run_projector_direct.py`、`bisheng/linsight/domain/services/run_projector_planned.py`
  **逻辑**: 各自消费统一事件。`direct` 复用 `build_answer_row`、`save_message_citations`、`_promote_generated_files`。`planned` 复用 `task_exec._save_task_info` 的写法，改用 `update_fields_by_id`，不整行回读大字段。
  **测试**: T029 全部通过；`test/workstation/test_daily_generated_files.py` 仍通过
  **覆盖 AC**: AC-10, AC-11, AC-40, AC-41, AC-42
  **依赖**: T029

- [ ] **T031**: 订阅与发送接口的集成测试
  **文件**: `test/workstation/test_unified_run_api.py`
  **逻辑**: 订阅接口：会话本人得到 SSE 流；带 `Last-Event-ID` 时只收到其后的事件；非本人访问被拒绝。发送接口：带 `X-BS-Run-Protocol: 2` 时返回 JSON `{run_id, disposition, message_id}`；不带该头时返回与今天相同格式的流式响应；`task_mode=true` 且用户没有深度研究权限时被拒绝、不产生运行；同一请求体在开关关闭的租户上走旧链路；输入命中敏感词时被拦截且不进收件箱。
  **测试**: `test_subscribe_owner_only`、`test_subscribe_resume_from_cursor`、`test_send_negotiated_json`、`test_send_legacy_stream_shape`、`test_task_mode_requires_permission`、`test_flag_off_uses_legacy_path`、`test_sensitive_input_blocked_before_inbox`
  **覆盖 AC**: AC-01, AC-06, AC-28, AC-31, AC-38
  **依赖**: T016, T028

- [ ] **T032**: 订阅接口与发送接口改造
  **文件**: `bisheng/workstation/api/endpoints/chat.py`、`bisheng/workstation/domain/services/chat_service.py`
  **逻辑**: 新增 `GET /api/v1/workstation/conversations/{conversation_id}/events`（SSE，按会话归属校验）。`POST /chat/completions`：开关开启时先做输入检测与权限校验，再调用 `run_dispatch.submit`；按协商头返回 JSON，或订阅事件流并转成旧 SSE 格式返回。路径不含 `config`。
  **测试**: T031 全部通过；`test/api/test_route_path_naming.py` 仍通过
  **覆盖 AC**: AC-01, AC-06, AC-28, AC-31, AC-38
  **依赖**: T031

- [ ] **T033**: `planned` 运行接入新通道的单元测试
  **文件**: `test/linsight/test_planned_run_unified.py`
  **逻辑**: 断言：开关开启时 worker 执行的 `planned` 运行把统一事件写入事件流、按间隔续租、响应停止标记、结束时调用 `on_run_finished`；旧 WebSocket 的订阅者仍收到与今天相同类型的事件（由事件流转译）；worker 从队列取到 `direct` 档的接力项时调用 `direct_run`；队列项里的租户信息在执行前被恢复。
  **测试**: `test_planned_writes_unified_events`、`test_planned_renews_and_stops`、`test_legacy_ws_still_receives`、`test_worker_runs_direct_relay`、`test_queue_item_restores_tenant`
  **覆盖 AC**: AC-03, AC-29, AC-33, AC-39
  **依赖**: T018, T028

- [ ] **T034**: `planned` 运行接入新通道实现
  **文件**: `bisheng/linsight/domain/task_exec.py`、`bisheng/linsight/worker.py`
  **逻辑**: `task_exec` 在开关开启时使用会话级租约（取代 4 小时固定锁）、统一事件输出口、停止标记。`worker.process_one_item` 增加 `direct_relay` 队列项类型。旧 WebSocket 广播改为从事件流读取后按旧类型转译。
  **测试**: T033 全部通过
  **覆盖 AC**: AC-03, AC-29, AC-33, AC-39
  **依赖**: T033

- [ ] **T035**: 开放 API 契约的回归测试
  **文件**: `test/open_api/test_task_mode_contract_unchanged.py`
  **逻辑**: 在开关开启的租户上调用开放 API 的提交、查询、文件、终止四个接口，断言响应字段集合与状态取值和开关关闭时一致；无人值守运行里没有 `ask_user` 事件，也不读取收件箱。
  **测试**: `test_submit_response_shape`、`test_task_status_values`、`test_files_response_shape`、`test_terminate`、`test_unattended_never_asks`
  **覆盖 AC**: AC-23, AC-39
  **依赖**: T034

- [ ] **T036**: 附件读取进度事件的单元测试
  **文件**: `test/workstation/test_attachment_progress_event.py`
  **逻辑**: 断言：带附件的 `direct` 运行在开始解析附件之前就发出一条“正在读取附件”的 `tool_call` 类事件（距 `run_started` 不超过 2 秒，用假时钟），解析完成后发对应的结束事件；不带附件时不发。
  **测试**: `test_progress_event_before_parsing`、`test_no_event_without_attachment`
  **覆盖 AC**: AC-51
  **依赖**: T028

- [ ] **T037**: 附件读取进度事件实现
  **文件**: `bisheng/workstation/domain/services/direct_run.py`
  **逻辑**: 在调用 `_process_agent_files` 前后各发一个事件。只加事件，不改解析方式（解析方式在 T055 调整）。
  **测试**: T036 全部通过
  **覆盖 AC**: AC-51
  **依赖**: T036

- [ ] **T038**: 运行观测指标
  **文件**: `bisheng/workstation/domain/services/direct_run.py`、`bisheng/linsight/domain/task_exec.py`
  **逻辑**: 每次运行用现有 `BS_METRIC` 日志格式记录：`prep_ms`（收到请求到发出第一次模型请求）、`queue_ms`、`steer_wait_ms`（插话入箱到被读取）、`checkpoint_bytes`。字段名写进 design §7。
  **测试**: 在 T027 的测试文件里追加 `test_metric_line_emitted`，断言日志行包含四个字段
  **覆盖 AC**: AC-34
  **依赖**: T028, T034

- [ ] **T039**: P1 等价性验证（手动）
  **文件**: `features/v3.1.0-beta2/004-unified-agent-runtime/verification-p1.md`
  **逻辑**: 在 114 上对一个测试租户打开开关，用现有前端（未改）各跑一次直接回答（带工具）、带附件的直接回答、深度研究（含一次提问、一次停止）。逐项记录界面表现与开关关闭时是否一致。用 `s5_first_char_timing_from_logs.py` 取 `prep` 的中位数与 90 分位，与 AC-34 的阈值比较，结果写进该文件。部署前先查 114 上没有进行中的深度研究任务。
  **覆盖 AC**: AC-34
  **依赖**: T032, T034, T037, T038

### Wave 2（P2）：插话与改计划（用户可见）

- [ ] **T040**: 收件箱中间件的单元测试
  **文件**: `test/linsight/test_inbox_middleware.py`
  **逻辑**: 用脚本化模型与 `fakeredis` 断言：运行中进入收件箱的消息出现在下一次模型调用的输入里，位置在上一步工具结果之后；多条消息按入箱顺序注入，各出现一次；每条被读取后发一个 `steer_read` 事件，带 `message_id`；最后一次模型调用期间入箱的消息留在收件箱；中间件只挂在主图，子代理的中间件列表里没有它；无人值守渠道不挂；`direct` 档同样生效；注入的消息进入会话状态。
  **测试**: `test_injected_before_next_model_call`、`test_order_and_exactly_once`、`test_steer_read_event`、`test_late_message_stays_queued`、`test_not_in_subagents`、`test_not_in_unattended`、`test_works_in_direct_profile`、`test_injected_message_persisted_in_state`
  **覆盖 AC**: AC-14, AC-15, AC-16, AC-18, AC-19, AC-23
  **依赖**: T016, T020

- [ ] **T041**: 收件箱中间件实现
  **文件**: `bisheng/linsight/domain/services/inbox_middleware.py`、`bisheng/linsight/domain/services/agent_factory.py`
  **逻辑**: `InboxMiddleware(AgentMiddleware)`：`abefore_model` 取出该会话收件箱里的全部消息，转成 `HumanMessage`，发 `steer_read`，返回 `{"messages": [...]}`。在工厂里只对主图、且非无人值守渠道挂载。参考实现见 `scripts/spike_unified_runtime/s3_inbox_middleware.py`。
  **测试**: T040 全部通过
  **覆盖 AC**: AC-14, AC-15, AC-16, AC-18, AC-19, AC-23
  **依赖**: T040

- [ ] **T042**: 插话入箱事件与消息落库的单元测试
  **文件**: `test/workstation/test_steer_message_persist.py`
  **逻辑**: 断言：消息进收件箱时立即写一条提问行（与普通提问行同结构，`extra` 标明所属运行），并发 `steer_accepted` 事件；刷新后历史接口返回这条消息；被读取后历史里的这条消息不再带“排队”标记。
  **测试**: `test_steer_row_written_on_enqueue`、`test_steer_accepted_event`、`test_history_reflects_read_state`
  **覆盖 AC**: AC-13, AC-14
  **依赖**: T016

- [ ] **T043**: 插话入箱事件与消息落库实现
  **文件**: `bisheng/workstation/domain/services/run_dispatch.py`、`bisheng/workstation/domain/services/chat_service.py`
  **逻辑**: `submit` 的 `queued` 分支写提问行、发 `steer_accepted`。`steer_read` 时把该行 `extra` 的排队标记清掉（用 `update_fields_by_id`）。
  **测试**: T042 全部通过
  **覆盖 AC**: AC-13, AC-14
  **依赖**: T042

- [ ] **T044**: 规划提示词的单元测试
  **文件**: `test/linsight/test_planning_prompt.py`
  **逻辑**: 断言 `planned` 档的系统提示词：包含“用户在执行中发来新要求时，先调用 write_todos 更新计划，再继续”；不再包含“不改写已有文案”的无条件表述，改为“只有用户要求时才改写”；仍包含“不写固定数量示例”的现有约束。
  **测试**: `test_prompt_allows_rewrite_on_user_request`、`test_prompt_requires_plan_update_on_steer`、`test_prompt_keeps_no_fixed_count_rule`
  **覆盖 AC**: AC-18
  **依赖**: T020

- [ ] **T063**: 规划提示词改动
  **文件**: `bisheng/linsight/domain/services/agent_factory.py`
  **逻辑**: 修改 `agent_factory.py:199-243` 一带的规划提示词，使 T044 通过。指令位置遵循 `linsight/AGENTS.md` 的尾部指令规则，措辞只限定计划的改写，不影响其他约束。
  **测试**: T044 全部通过
  **覆盖 AC**: AC-18
  **依赖**: T044

- [ ] **T045**: 前端运行 store 的单测
  **文件**: `store/runStore.test.ts`
  **逻辑**: 断言事件归并：`text` 累加；`plan` 整体替换并保留条目顺序；`steer_accepted` 把对应消息标为排队中，`steer_read` 清除该标记；`resync` 整体替换当前运行；`run_started` 至 `run_finished` 之间 `isRunning` 为真；`ask_user` 设置待回答问题；`file` 追加且按 `file_id` 去重；`isRunning` 为真时 `canSend` 仍为真。
  **测试**: `merges text`、`replaces plan`、`steer queued then cleared`、`resync replaces run`、`running flags`、`pending question`、`file dedupe`、`can send while running`
  **覆盖 AC**: AC-08, AC-12, AC-13, AC-14
  **依赖**: T018

- [ ] **T046**: 前端运行 store 与依赖
  **文件**: `store/runStore.ts`、`../package.json`
  **逻辑**: 加入 `zustand` 依赖。store 按会话 id 保存：当前运行的文字与思考、计划、文件、待回答问题、消息的排队标记、运行状态。只提供纯归并函数与选择器，不发 HTTP（C7）。不与 Recoil `linsightMapState` 镜像同一份数据。
  **测试**: T045 全部通过
  **覆盖 AC**: AC-08, AC-12, AC-13, AC-14
  **依赖**: T045

- [ ] **T047**: 前端事件订阅
  **文件**: `hooks/useRunEvents.ts`、`api/chatApi.ts`
  **逻辑**: 用现有的 `sse.js` 订阅 `GET /api/v1/workstation/conversations/{id}/events`，断线重连时带 `Last-Event-ID`，把事件交给 `runStore`。发送改为带 `X-BS-Run-Protocol: 2`，按返回的 `disposition` 更新本地消息。类型定义放 `api/chatApi.ts`。
  **覆盖 AC**: AC-12, AC-31
  **手动验证**:
  - 打开 http://192.168.106.114:4001/workspace/ ，对开了开关的租户登录，发送一条消息，回答正常出字。
  - 运行中断开网络 10 秒再恢复，断开期间的内容补齐，没有重复文字。
  **依赖**: T032, T046

- [ ] **T048**: 会话页运行中可发送与排队标记
  **文件**: `components/Chat/AiChatInput.tsx`、`components/Chat/AiMessageBubble.tsx`
  **逻辑**: 去掉运行中禁用文本框与发送按钮的条件（`isStreaming`、`sendDisabled=taskRunning`），停止按钮与发送按钮并存。用户消息在排队时下方显示“已发送，排队处理中”，被读取后该文字消失。文案进三个语言文件（用 `/i18n-localizer`）。
  **覆盖 AC**: AC-12, AC-13, AC-14, AC-19
  **手动验证**:
  - 深度研究运行中输入并发送“第 3 步改成做 PPT”：消息立即出现，下方显示“已发送，排队处理中”；agent 读取后文字消失。
  - 直接回答执行代码期间重复上述操作，表现相同。
  - 对照原型场景 3。
  **依赖**: T043, T047

- [ ] **T049**: 计划面板读新 store
  **文件**: `components/Linsight/Execution/PinnedTaskPanel.tsx`、`components/Linsight/Execution/TaskPanel.tsx`
  **逻辑**: 会话页的计划面板改读 `runStore` 的计划。被改写的条目显示改写后的文字，并用删除线保留改写前的文字；条目上不显示修改来源。`cancelled` 状态显示为“已取消”。头部显示“已完成条数 / 总条数”。
  **覆盖 AC**: AC-08, AC-09, AC-10, AC-11
  **手动验证**:
  - 插话改写第 3 条后：第 3 条显示新文字与带删除线的旧文字，其余条目状态与位置不变。
  - 刷新页面，计划与刷新前一致。
  - 让 agent 去掉一条：该条显示“已取消”。
  **依赖**: T030, T047

- [ ] **T050**: 提问卡片与停止接入新通道
  **文件**: `components/Linsight/Execution/ClarifyCard.tsx`、`components/Chat/hooks/useTaskWorkspaceState.ts`
  **逻辑**: 提问卡片读 `runStore` 的待回答问题；点选项或在输入框输入都通过发送接口提交。停止调用现有终止接口并传运行 id；停止后计划面板显示“已停止”。等待回答时输入框占位文案为“点上面的选项，或者直接输入你的回答”。
  **覆盖 AC**: AC-20, AC-21, AC-29
  **手动验证**:
  - 触发一次提问，点选项后运行继续；再触发一次，改为在输入框输入文字，运行同样继续且没有新开运行。
  - 运行中点停止，5 秒内停下，已完成的条目、文件、文字都在；发“接着做”能继续。
  **依赖**: T047

- [ ] **T051**: P2 验证（手动）
  **文件**: `features/v3.1.0-beta2/004-unified-agent-runtime/verification-p2.md`
  **逻辑**: 在 114 上按 test-cases.md 的 TC-UAR-005 至 TC-UAR-012 逐条执行，记录结果。另开两个标签页验证 TC-UAR-020。
  **覆盖 AC**: AC-12, AC-16, AC-17, AC-18
  **依赖**: T041, T063, T048, T049, T050

### Wave 3（P3）：直接回答能力补齐、文件实时可见、提速

- [ ] **T052**: `direct` 档工作区与技能的单元测试
  **文件**: `test/workstation/test_direct_workspace_and_skills.py`
  **逻辑**: 断言：`direct` 运行里代码执行器的工作目录对应会话工作区，写到 `output/` 的文件进入 `workspace/{conversation_id}/output/`；勾选技能后技能被挂载且可被调用；不涉及文件操作的运行不创建本地缓存目录、不同步工作区；运行在另一节点恢复时（本地目录为空）先从对象存储取回 `output/` 与 `uploads/`。
  **测试**: `test_code_output_lands_in_conversation_workspace`、`test_skills_available_in_direct`、`test_lazy_workspace_creation`、`test_resume_on_other_node_restores_files`
  **覆盖 AC**: AC-25, AC-33, AC-45, AC-46
  **依赖**: T028

- [ ] **T053**: `direct` 档挂工作区与技能
  **文件**: `bisheng/workstation/domain/services/direct_run.py`、`bisheng/linsight/domain/services/tool_assembly.py`
  **逻辑**: `direct` 档使用 `WorkspaceBackend`；代码执行器按深度研究的方式绑定工作区前缀与本地缓存目录，目录在第一次文件工具调用时创建。去掉 `chat_service` 里对 `skills` 的强制清空（`:2907`）。跨节点恢复复用 `_sync_workspace_originals`。
  **测试**: T052 全部通过
  **覆盖 AC**: AC-25, AC-33, AC-45, AC-46
  **依赖**: T052

- [ ] **T054**: 文件事件与访问控制的单元测试
  **文件**: `test/linsight/test_file_events.py`
  **逻辑**: 断言：`WorkspaceBackend` 写入 `output/` 成功后发一个 `file` 事件，`data` 含 `file_id`、`name`、`path`、`size`、`source`；代码执行器产物同步到工作区后同样发事件；同一路径重复写只更新、不新增条目；写到 `scratch/` 不发事件；运行结束时的目录对账补发漏掉的文件；文件存放在主桶；预览与下载地址由非会话本人请求时被拒绝，审计接口可访问。
  **测试**: `test_file_event_on_output_write`、`test_file_event_from_executor_sync`、`test_same_path_updates`、`test_scratch_is_silent`、`test_reconcile_at_run_end`、`test_stored_in_main_bucket`、`test_non_owner_denied`、`test_audit_allowed`
  **覆盖 AC**: AC-24, AC-25, AC-27, AC-28
  **依赖**: T018, T024

- [ ] **T055**: 文件事件实现
  **文件**: `bisheng/linsight/domain/services/workspace_backend.py`、`bisheng/linsight/domain/services/run_projector_planned.py`
  **逻辑**: `WorkspaceBackend` 接受一个事件回调，在 `output/` 写入成功后调用。执行器同步路径（`sync_to_workspace`）复用同一回调。运行结束时用现有的目录扫描结果对账。运行结束时继续写回答行的 `files` 字段（F016）与 `output_result.final_files`。
  **测试**: T054 全部通过
  **覆盖 AC**: AC-24, AC-25, AC-27, AC-28
  **依赖**: T054

- [ ] **T056**: 附件按需读取的单元测试
  **文件**: `test/workstation/test_attachment_on_demand.py`
  **逻辑**: 断言：附件上传后进入会话工作区的 `uploads/`，解析在上传时开始；`direct` 运行开始时不等待解析完成即发出模型请求，模型输入里列出附件名与路径；字符数低于阈值且已解析完成的附件直接内联；agent 读取尚未解析完的附件时等待并发进度事件；二进制原件不以原扩展名暴露给 `read_file`。
  **测试**: `test_upload_starts_parsing`、`test_run_does_not_wait_for_parsing`、`test_small_parsed_file_inlined`、`test_read_waits_with_progress`、`test_binary_original_not_exposed`
  **覆盖 AC**: AC-26, AC-34, AC-51
  **依赖**: T053

- [ ] **T057**: 附件按需读取实现
  **文件**: `bisheng/workstation/domain/services/direct_run.py`、`bisheng/workstation/domain/services/chat_service.py`
  **逻辑**: `direct` 档改用深度研究的上传与解析状态机制（`upload-file` 与 `file-parsing-status` 背后的服务）。内联阈值做成配置项，初始值由本任务用 114 的日常附件实测后确定，并把测量结果写进 design 决策 12。
  **测试**: T056 全部通过
  **覆盖 AC**: AC-26, AC-34, AC-51
  **依赖**: T056

- [ ] **T058**: 引用、读图、记忆在统一工厂下的单元测试
  **文件**: `test/linsight/test_unified_citation_image_memory.py`
  **逻辑**: 断言：同一会话里先 `direct` 后 `planned`，两次运行产生的引用角标编号不重复，且都能解析到来源；知识库检索结果含图片且模型标记为支持读图时，两个档位的模型输入都包含图片内容，图片块位于整批工具消息之后；长期记忆开启时两个档位都绑定记忆工具并注入常驻记忆，统一前写入的记忆可被检索到；记忆接线只有一处实现。
  **测试**: `test_citation_handles_unique_across_profiles`、`test_citation_resolves_to_source`、`test_images_visible_in_both_profiles`、`test_image_blocks_after_tool_batch`、`test_memory_tools_in_both_profiles`、`test_existing_memories_searchable`
  **覆盖 AC**: AC-41, AC-48, AC-49, AC-50
  **依赖**: T020, T008

- [ ] **T059**: 引用、读图、记忆接入统一工厂
  **文件**: `bisheng/linsight/domain/services/agent_factory.py`、`bisheng/workstation/domain/services/daily_memory.py`
  **逻辑**: `direct` 档挂载引用中间件与共享编号表；按 T008 的结论接入读图组件；把 `daily_memory.py` 与 `linsight/.../memory_turns.py` 的接线合并为工厂里的一处，另一处改为调用它。
  **测试**: T058 全部通过；`test/memory/` 与 `test/citation/` 现有用例仍通过
  **覆盖 AC**: AC-41, AC-48, AC-49, AC-50
  **依赖**: T058

- [ ] **T060**: 工作区面板实时文件与工具结果展开
  **文件**: `components/Linsight/Artifacts/WorkspacePanel.tsx`、`components/Chat/Messages/ToolCallDisplay.tsx`
  **逻辑**: 会话页的工作区面板合并 `runStore` 的文件与历史文件，文件一出现就可预览下载；没有任何文件时不显示工作区入口提示。直接回答的通用工具调用行增加“查看代码和输出”的展开。文案进三个语言文件。
  **覆盖 AC**: AC-24, AC-25
  **手动验证**:
  - 深度研究生成两个文件的任务：第一个文件在运行结束前出现在工作区，可预览可下载。
  - 关闭「深度研究」，让 agent 用代码生成一个 Excel：回答下方与工作区都出现该文件；展开工具行能看到代码与输出。
  - 对照原型场景 1 与场景 5。
  **依赖**: T047, T055

### Wave 4（P4）：前端收尾与整体验收

- [ ] **T061**: 会话页移除旧通道
  **文件**: `hooks/useAiChat.ts`、`components/Chat/AiMessageBubble.tsx`
  **逻辑**: 会话页不再处理 `linsight_task_handoff`，不再为会话页建立任务 WebSocket；深度研究的回合与直接回答的回合用同一套时间线组件渲染（数据来自 `runStore` 与历史接口）。`/linsight/:id` 独立页保持用旧 WebSocket 与 Recoil，只做历史回看，输入框不显示。
  **覆盖 AC**: AC-01, AC-40
  **手动验证**:
  - 浏览器网络面板里，会话页没有 `task-message-stream` 的 WebSocket 连接。
  - 打开一个升级前的旧日常对话与一个旧深度研究任务：显示正常，能继续发消息。
  - 对照原型场景 2 与场景 4。
  **依赖**: T048, T049, T050, T060

- [ ] **T062**: 整体验收
  **文件**: `features/v3.1.0-beta2/004-unified-agent-runtime/verification-final.md`
  **逻辑**: ① 运行 `/e2e-test features/v3.1.0-beta2/004-unified-agent-runtime`；② 在两节点环境执行 test-cases.md 的 TC-UAR-022、TC-UAR-023；③ 在 DM8 环境执行 TC-UAR-033，并观察长运行期间会话页无 500；④ 用 `s5_first_char_timing_from_logs.py` 复测 `prep`，与 AC-34 阈值比较；⑤ 额度不足时两种方式都在运行开始前被拒绝。结果逐项写进该文件，未通过或未执行的项如实标注。
  **覆盖 AC**: AC-33, AC-34, AC-35, AC-36, AC-37, AC-42
  **依赖**: T039, T051, T057, T059, T061

---

## 实际偏差记录

> 只留一行指针，论证在 design.md。推翻已 ★ 确认的决策时，先停下与用户重新确认。

- **T003**：除任务写明的 3 个包，锁文件还连带移动 15 个包并新增 4 个包，全部是被强制的最低版本。见 design K3。
- **T005**：任务只写了“显式挂载计划能力与输出格式”。实际还要处理 4 处任务没有预见的行为变化：新增的 `delete` 工具、基础提示词不再追加、摘要失败与卸载的签名变化、超窗恢复不再无条件重试。`read_file` 与空 `ls` 的新格式没有任何代码需要修改。`BASE_AGENT_PROMPT` 的引用随中间件一起删除。见 design §5 坑 13 至坑 16。
- **T004**：测试断言了任务没写的一条：`delete` 不在绑定的工具里。
- **T007**：改写前的文字放在 `GenerateSubTask.subtask[].previous_name`（事件里），写进 `task_data` 留给 T041 一组。
- **T009**：114 的工作台只配了 2 个模型，实际跑了 2 个模型各 5 次（10/10 成功），不是 3 个模型。脚本在 114 的 deepagents 0.6.12 上运行。限制见 design 决策 6。
- **T008**：结论是工作台两个入口都没有校验深度研究权限。发送入口的实现任务要新加校验，这比原先“再校验一次”的表述多一项工作。

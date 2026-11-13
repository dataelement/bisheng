# Tasks: 日常会话代码执行生成文件的附件交付

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md) · [test-cases.md](./test-cases.md)
**版本**: v3.1.0-beta1

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-11-13 用户确认（单轮上限 50） |
| design.md | ✅ 已评审 | 2026-11-13 用户确认；接手时的第一入口 |
| test-cases.md | ✅ 已生成 | 23 条，格式已校验 |
| tasks.md | ✅ 已拆解 | `/sdd-review tasks` 第 2 轮 LGTM |
| 实现 | 🔲 未开始 | 0 / 12 完成 |

---

## 开发模式

- 按 Wave 组织：同一 Wave 内依赖已满足的任务可以并行。
- 后端每组任务先写测试、再写实现。
- 前端任务配 jest 单测，并附手动验证步骤。
- 共享工作区禁止整仓 git 写操作（见根 AGENTS.md §7）。
- 本功能不涉及 ORM、DDL 或错误码，所以没有基础设施任务。

**共享文件影响**：

| 文件 | 影响 |
|---|---|
| `base_executor.py` | 深度研究、工作流代码节点、助手共用。新增的收集开关默认关闭；对象名去掉双点会影响所有调用方，但只改临时桶里的对象名，没有调用方依赖旧格式（T001 回归覆盖）。 |
| `chat_session/domain/chat.py` | 本人附件接口的行为保持不变（T003 回归覆盖）。 |
| `Markdown.tsx` | 深度研究分支不变（T011 回归覆盖）。 |

---

## Tasks

### Wave 1（后端底座，两组可以并行）

- [ ] **T001**: 代码执行器交付物收集 — 测试
  **文件**: `src/backend/test/sandbox/test_generated_deliverables.py`（新建）
  **逻辑**: 用 `LocalExecutor(minio={...})`，把 `upload_minio` mock 成返回 `"http://h/tmp-dir/<name>?sig"`，`local_sync_path=None`，在临时目录里运行脚本。
  **测试**:
  - `test_collect_off_by_default` → AC-22
  - `test_only_output_files_collected`（同时写 `output/a.docx`、`scratch/t.csv`，目录中预置一个上传源文件并修改它）→ AC-02
  - `test_failed_run_collects_nothing` → AC-05
  - `test_object_name_has_single_dot` → AC-23
  - `test_parallel_runs_keep_all_entries`
  - `test_file_list_return_unchanged`（`file_list` 仍是字符串列表）→ AC-22
  **覆盖 AC**: AC-02, AC-05, AC-22, AC-23
  **依赖**: 无

- [ ] **T002**: 代码执行器交付物收集 — 实现
  **文件**: `src/backend/bisheng_langchain/gpts/tools/code_interpreter/base_executor.py`
  **逻辑**:
  - `__init__` 新增 `self.collect_deliverables = False`、`self.published_deliverables: list[dict] = []`、`self._deliverables_lock = threading.Lock()`。
  - `_publish_generated_files` 上传后，若开关打开且路径（统一用 `/` 分隔）以 `output/` 开头，就在锁内追加 `{"path": rel, "name": basename, "size": os.path.getsize, "url": url}`。
  - 对象名改为 `f"{uuid.uuid4().hex}{file_ext}"`。
  - 设计依据：决策 3，坑 1、2、7。
  **测试**: T001 全部通过，`test/sandbox`、`test/linsight/test_code_interpreter_*` 回归通过。
  **覆盖 AC**: AC-02, AC-05, AC-22, AC-23
  **依赖**: T001

- [ ] **T003**: 附件签名与审计接口 — 测试
  **文件**: `src/backend/test/chat_session/test_generated_file_url.py`（新建）
  **逻辑**: 先构造会话、提问行，以及带 `files=[{file_id, object_name, source:"code_interpreter"}]` 的回答行，再 mock `get_minio_storage().get_share_link` 和 `AuditLogService.assert_session_in_audit_scope`。
  **测试**:
  - `test_owner_can_sign_bot_row_attachment` → AC-11（会话本人能签回答行附件）
  - `test_non_owner_rejected` → AC-11
  - `test_audit_in_scope_signs` → AC-17
  - `test_audit_out_of_scope_rejected` → AC-18
  - `test_audit_rejects_user_upload` → AC-17
  - `test_missing_object_name_not_found`
  - `test_delete_session_removes_bot_row_objects`（`_remove_attachments` 会删除回答行的 `object_name`）→ AC-10
  **覆盖 AC**: AC-10, AC-11, AC-17, AC-18
  **依赖**: 无

- [ ] **T004**: 附件签名与审计接口 — 实现
  **文件**: `src/backend/bisheng/chat_session/domain/chat.py`、`src/backend/bisheng/chat_session/api/endpoints/session.py`
  **逻辑**:
  - 新增 `ChatSessionService._sign_attachment(chat_id, file_id, owner, *, only_source=None) -> str`。它承接 `resolve_attachment_url` 主人校验之后的那段逻辑；`only_source` 不为空时，`attachment.get("source")` 必须相等，否则返回不存在。`resolve_attachment_url` 改为先校验主人、再调用它。
  - 新增 `ChatSessionService.resolve_audit_attachment_url(chat_id, file_id)`：取 `MessageSessionDao.async_get_one(chat_id)` 作为 owner，再调用 `_sign_attachment(..., only_source="code_interpreter")`。
  - endpoint：新增 `@router.get("/chat/{chat_id}/files/{file_id}/url")`。先调用 `AuditLogService.assert_session_in_audit_scope(login_user, chat_id)`，`UnAuthorizedError` 时抛 `.http_exception()`；然后返回 `resp_200(data={"url": url})`。最终路径为 `/api/v1/session/chat/{chat_id}/files/{file_id}/url`。
  - 设计依据：决策 5。
  **测试**: T003 全部通过，`test/chat_session` 回归通过。
  **覆盖 AC**: AC-10, AC-11, AC-17, AC-18
  **依赖**: T003

### Wave 2（日常会话接线）

- [ ] **T005**: 日常会话挂载附件 — 测试
  **文件**: `src/backend/test/workstation/test_daily_generated_files.py`（新建）
  **逻辑**: 直接测试 T006 新增的纯函数和落库辅助函数，用假工具对象带 `executor.published_deliverables`，并 mock `promote_chat_attachments`。
  **测试**:
  - `test_enable_sets_flag_and_appends_hint` → AC-16
  - `test_collect_dedup_keeps_last` → AC-03
  - `test_collect_caps_last_50` → AC-07
  - `test_item_shape`（`file_id`、`file_name`、`path`、`type`、`size`、`source`、`filepath`）→ AC-01
  - `test_promote_partial_failure_keeps_others` → AC-06
  - `test_promoted_item_has_object_name` → AC-09
  - `test_answer_row_and_end_event_carry_files` → AC-01, AC-04
  - `test_safety_replacement_has_no_files` → AC-20
  - `test_stop_path_uses_sync_promotion` → AC-21
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-06, AC-07, AC-09, AC-16, AC-20, AC-21
  **依赖**: T002

- [ ] **T006**: 日常会话挂载附件 — 实现
  **文件**: `src/backend/bisheng/workstation/domain/services/chat_service.py`
  **逻辑**:
  - 新增 `_enable_deliverable_collection(tool)`：取 `getattr(tool, "tool_instance", tool).executor`；有 `collect_deliverables` 属性时置 True，并在内层和外层 `description` 末尾追加 design 决策 6 的英文说明。在约 1331 行 `init_by_tool_id` 返回后，对 `tool_key == CODE_INTERPRETER_TOOL_KEY` 的工具调用。
  - 新增 `_collect_generated_files(tools) -> list[dict]`：读取清单，按 `path` 去重保留最后一次，取最后 50 个，按 design §4.3 组装附件项。
  - `build_answer_row(db_content, files=None)`：有值时写 `files=json.dumps(files, ensure_ascii=False)`。
  - 约 2605 行（正常结束和出错落库）：先 `await promote_chat_attachments(files, user_id, storage_partition=…)`，再落库；`db_content` 发 SSE 时附加 `files`。分区与提问附件相同，即 `session_subject.storage_partition`。
  - 约 2009 行（停止）：调用 `promote_chat_attachments_sync(files, partition)`。
  - 约 1956 行（内容安全）：不挂附件。
  - 日志：`daily chat generated files chat_id={} count={} promoted={}`。
  - 设计依据：决策 1、2、6，坑 5。
  **测试**: T005 全部通过，`test/workstation` 回归通过。
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-06, AC-07, AC-09, AC-16, AC-20, AC-21
  **依赖**: T002, T005

### Wave 3（前端，client 与 platform 可以并行）

- [ ] **T007**: client — 流式结束带回 files，助手气泡渲染卡片
  **文件**: `src/frontend/client/src/hooks/useAiChatSSE.ts`、`src/frontend/client/src/components/Chat/AiMessageBubble.tsx`，以及消费 `onAgentUpdate` 并写回消息的调用处（一处）
  **逻辑**:
  - `AgentPatch` 增加 `files?: any[]`；`agent_answer` end 事件把 `message.files` 带进 `emitAgent`；调用处把它写到 `ChatMessage.files`。
  - 助手气泡在正文下方左对齐渲染附件列表，复用 `MessageImage` 和 `ChatHistoryFileRow`，并传入 `conversationId`。
  - 设计依据：坑 4。
  **测试**: jest 覆盖 end 事件的 `files` 能到达 patch，以及助手气泡在有 `files` 时渲染卡片。
  **覆盖 AC**: AC-01, AC-04
  **手动验证**: 在 `http://192.168.106.116:3001/workspace` 执行 TC-DCF-001、TC-DCF-003。
  **依赖**: T006

- [ ] **T008**: client — 打开附件前再签名
  **文件**: `src/frontend/client/src/components/Chat/attachments/ChatHistoryFileRow.tsx`、`src/frontend/client/src/components/Chat/hooks/useTaskWorkspaceState.ts`（打开文件的路径）
  **逻辑**:
  - 新增一个小的再签名函数：附件有 `object_name`、`file_id`，且上下文有 `conversationId` 时，先 `await getAttachmentUrl(conversationId, file_id)`。拿到地址就用它构造预览或下载；拿不到就回退到存储的 `filepath`。
  - 卡片的可点击判断仍依赖 `filepath`（保留不删）。
  - 用户上传的文档附件同样受益，回归时要覆盖。
  - 设计依据：坑 3、10、11。
  **测试**: jest 覆盖有 `object_name` 时调用 `getAttachmentUrl`、没有时用原地址、签名失败时回退。
  **覆盖 AC**: AC-08, AC-09, AC-12
  **手动验证**: 执行 TC-DCF-002、TC-DCF-008、TC-DCF-023。
  **依赖**: T007

- [ ] **T009**: client — 正文 output/ 链接规则
  **文件**: `src/frontend/client/src/components/Chat/Messages/Content/Markdown.tsx`，以及日常会话气泡传参处（`AiMessageBubble.tsx` 的主 `<Markdown>`）
  **逻辑**:
  - 日常会话气泡传入 `resolveFileLink(href)`。它先归一化 href：`decodeURIComponent` 容错，去掉 `./` 和前导 `/`；再与 `message.files[].path` 比对。
  - 命中时点击走 T008 的再签名下载。
  - 未命中且是 `output/` 或 `scratch/` 相对链接时，渲染为 `<span>`。
  - 其他链接不变。不传解析器的地方（深度研究）沿用现有 `resolveArtifactLink` 分支。
  - 设计依据：决策 4，坑 8、9。
  **测试**: jest 覆盖命中、URL 编码、`./` 前缀、未命中变文字、`https://` 不变、深度研究分支不变。
  **覆盖 AC**: AC-13, AC-14, AC-15, AC-22
  **手动验证**: 执行 TC-DCF-012、TC-DCF-013、TC-DCF-014、TC-DCF-021。
  **依赖**: T008

- [ ] **T010**: platform — 审计详情卡片与下载
  **文件**: `src/frontend/platform/src/controllers/API/log.ts`、`src/frontend/platform/src/pages/LogPage/useAppLog/dailyChatDetail.tsx`
  **逻辑**:
  - `log.ts` 新增 `getAuditChatFileUrlApi(chatId, fileId)`，调用 T004 的接口。
  - `dailyChatDetail` 的 `Message` 增加 `files`；对 `source === "code_interpreter"` 的项，在回答下渲染文件卡片（文件图标、文件名），点击时取地址后下载。
  - 新文案（如「下载失败」）补齐三语 i18n。
  **覆盖 AC**: AC-17, AC-18
  **手动验证**: 在 `http://192.168.106.116:3001/log/chatlog/<会话id>` 执行 TC-DCF-015、TC-DCF-016。
  **依赖**: T004, T006

- [ ] **T011**: platform — 审计正文 output/ 链接规则
  **文件**: `src/frontend/platform/src/pages/LogPage/useAppLog/DailyMessageContent.tsx`
  **逻辑**:
  - `ReactMarkdown` 增加 `components.a`，规则与 T009 相同：用本条消息的 `files` 匹配；命中时调用 T010 的取地址函数下载；`output/`、`scratch/` 未命中时渲染为文字；其他链接保持原样。
  - `MessageContent` 新增 `files` 和 `chatId` 两个 props，由 `dailyChatDetail` 传入。
  **覆盖 AC**: AC-19
  **手动验证**: 执行 TC-DCF-017。
  **依赖**: T010

### Wave 4（验收）

- [ ] **T012**: E2E 与 116 验收
  **逻辑**:
  - 运行 `/e2e-test features/v3.1.0-beta1/016-daily-chat-generated-files`。
  - 在 116 执行 test-cases.md 的全部 P0 和 P1 用例，并回填结果列。
  - 运行 `scripts/arch-guard.sh`。
  - 运行后端定向回归：`test/sandbox`、`test/linsight/test_code_interpreter_*`、`test/workstation`、`test/chat_session`、`test/audit`。
  - 运行两端前端 lint 和 jest。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23
  **依赖**: T009, T011

---

## 实际偏差记录

（暂无）

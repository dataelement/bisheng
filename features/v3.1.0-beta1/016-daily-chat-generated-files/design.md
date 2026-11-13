# Design: 日常会话代码执行生成文件的附件交付

> 现状快照（Why this How）。需求口径见 [spec.md](./spec.md)。

**关联**: [spec.md](./spec.md)
**版本**: v3.1.0-beta1
**状态**: 设计已确认（2026-11-13，与 spec 同时确认）
**最后更新**: 2026-11-13
**调研基线**: `feat/3.1.0-beta1`（工作区 HEAD，2026-11-13）

---

## 1. 目标与非目标

- **目标**：日常会话里代码执行器写到 `output/` 的文件，由系统确定性地挂到该轮回答上，长期保存、按需签名、会话页与审计页均可下载；下载不再取决于模型在正文里抄对了哪条地址。
- **非目标**：不改深度研究工作区与产物面板；不改代码执行器交给模型的返回结构；不补 E2B；不回填历史；不新增数据表、数据库列或错误码。

---

## 2. 关键约束

- 遵循 `docs/constitution.md` C1–C8。与本功能直接相关的是：C1（审计端点走 Service，不在 endpoint 里查 ORM）、C4（审计下载复用 F003 的会话审计范围判定，不另建权限判断）、C8（文件内容只以对象存储为准，消息行只存指针；执行器进程内的收集列表只是本轮的临时缓存）。
- 代码执行器（`bisheng_langchain/gpts/tools/code_interpreter/`）被日常会话、深度研究、工作流代码节点、助手共用。工具描述 `LOCAL_DESCRIPTION` 和返回结构 `{exitcode, log, file_list}` 是这些调用方共同依赖的契约，只能做向后兼容的增量。
- 日常会话每次请求都会通过 `ToolExecutor.init_by_tool_id` 新建工具和执行器实例（`chat_service.py` 约 1331 行），执行器上的状态天然按请求隔离。
- 临时桶 `tmp-dir` 的生命周期规则是 7 天过期（`minio_storage.tmp_object_lifecycle`），预签名地址也是 7 天。

---

## 3. 方案对比与选定

### 决策 1：附件存在哪里

- **备选**：
  - A. 写入回答行已有的 `ChatMessage.files` 列 — 不加表也不加列；历史接口（`_message_base_fields`）、审计接口（`WorkstationMessage.from_chat_message`）已经原样返回该列；`resolve_attachment_url` 和删除会话时的 `_remove_attachments` 都会扫描会话内所有带 `files` 的行（`WorkflowFileRepository.attachment_messages` 不区分用户还是助手）。
  - B. 新建「消息生成文件」表 — 结构清晰，但签名、删除、两个读取接口都要重新接一遍。
  - C. 不落库，读取时从 `events[].results` 里解析 `file_list` — 地址是会过期的临时预签名地址，也没有文件名。
- **选定**：A
- **原因**：现有附件的签名、删除、读取链路可以直接复用，改动最小，也天然满足 AC-09、AC-10、AC-11。
- **何时该重新考虑**：需要按生成文件单独检索或统计，或者单条消息附件多到 JSON 列不合适时。

### 决策 2：长期存储方式

- **备选**：
  - A. 回答落库时复用 `promote_chat_attachments`，把 `tmp-dir` 对象复制到主桶 `chat/<分区>/<uuid><扩展名>`，并写入 `object_name`。
  - B. 让执行器直接上传到主桶。
- **选定**：A
- **原因**：执行器位于 `bisheng_langchain`，不知道用户和存储分区；它还被深度研究和工作流共用，直接改上传目标会影响其他调用方。转正函数的输入恰好是 `{filepath, file_name}`，执行器给的 `tmp-dir` 预签名地址可以被 `temp_object_name_from_url` 解析。分区与提问附件保持一致（`session_subject.storage_partition`，缺省为 `user_id`）。
- **何时该重新考虑**：单个生成文件很大、复制耗时影响回答落库时，改为异步转正。

### 决策 3：系统怎么拿到生成文件清单（不经过模型）

- **备选**：
  - A. 执行器在实例上按需收集本次请求里发布到 `output/` 的文件（路径、文件名、大小、临时地址），日常会话在回答落库前从工具实例上读取。
  - B. 在工具返回里加 `generated_files` 字段，再从 `on_tool_end` 事件里解析。
  - C. 解析正文里的 `output/…` 链接，再去反查文件。
- **选定**：A，收集默认关闭，只在日常会话里通过 `collect_deliverables=True` 打开。
- **原因**：B 会把文件清单（含地址）再发给模型一遍，既占上下文，又会诱导模型继续把地址写进正文，而且改变了各调用方共同依赖的返回结构。C 正是本次要摆脱的依赖。A 不影响模型可见内容，深度研究和工作流的执行器默认不收集，也不会让长生命周期的执行器内存持续增长。
- **何时该重新考虑**：日常会话的执行器改为跨请求复用时（届时需要按轮次清空）。

### 决策 4：正文里的 `output/` 链接

- **备选**：
  - A. 渲染时把链接与同一条消息的 `files[].path` 比对：匹配上的点击即下载该附件，匹配不上的 `output/`、`scratch/` 相对链接改成不可点击的文字。
  - B. 后端落库时改写正文里的链接。
  - C. 不处理，只靠卡片。
- **选定**：A，会话页（client）和审计页（platform）各自实现。
- **原因**：B 改了模型原文，审计看到的不再是真实输出，历史消息也处理不了。C 会把 404 链接留在正文里。A 不修改存储内容，历史消息也能自然降级为不可点击。
- **何时该重新考虑**：链接规则需要在三处以上复用时，抽到 `packages/`。

### 决策 5：审计下载入口

- **备选**：
  - A. 新增 `GET /api/v1/session/chat/{chat_id}/files/{file_id}/url`：先调用 `AuditLogService.assert_session_in_audit_scope`，再由 `ChatSessionService` 共用的签名逻辑出地址，只允许签 `source == "code_interpreter"` 的附件。
  - B. 放宽现有 `/chat/{chat_id}/files/{file_id}/url`，允许审计管理员调用。
  - C. 审计接口返回消息时直接附带新签名的地址。
- **选定**：A
- **原因**：B 会把「本人会话」和「审计读取」两套判定混进一个接口。C 会给整段会话里的所有文件批量签名，地址可能在页面停留期间过期。A 与审计详情接口使用同一套范围判定（满足 AC-18），并按最小权限只放开本功能新增的附件类型；用户上传附件在审计页展示属于范围外。
- **何时该重新考虑**：审计页决定同时展示用户上传附件时，去掉 `source` 限制。

### 决策 6：模型提示

- **备选**：
  - A. 日常会话构造代码执行器后，在工具描述末尾追加一段日常会话专用说明（与 `_attach_kb_image_stage` 刷新描述的方式相同）。
  - B. 修改共用的 `LOCAL_DESCRIPTION`。
  - C. 写进日常会话系统提示词。
- **选定**：A
- **原因**：B 会影响深度研究，那里写 `output/` 链接是正确用法，会由 `resolveArtifactLink` 解析成产物。C 在未启用代码执行器时也会出现，且离工具太远，不如紧挨工具描述生效。说明文字为英文，与工具描述其余部分保持一致：`Files you save under output/ are attached to your reply automatically and shown to the user as download cards. Do not write download links, URLs or output/ paths in your reply; mention a file by its file name only.`
- **何时该重新考虑**：观察到模型仍频繁写链接时，在系统提示词中再强调一次。

---

## 4. 系统现状与改动后数据流（接手必读）

### 4.1 现状（问题成因）

`ToolExecutor.parse_preset_tool_params` 只给日常会话的执行器传 `minio` 配置，不传 `local_sync_path` 和 `workspace_prefix`。因此：

1. `LocalExecutor._run_blocks` 在 `TemporaryDirectory` 中运行脚本，运行结束后目录即被删除。
2. `BaseExecutor.run_with_dir` 对比运行前后的快照，再由 `_publish_generated_files` 对每个新建或修改的文件调用 `upload_minio`，上传到 `tmp-dir/<uuid>..<ext>`，返回 `sharepoint` 主机的 7 天预签名地址。
3. 工具返回 `{exitcode, log, file_list:[url…]}` 交给模型。日常会话没有任何代码读取 `file_list`。
4. 模型在正文里写链接：有时抄 `file_list` 的地址（能下载，但最多 7 天，且需要浏览器能直连 MinIO 端口），有时写自己写文件用的 `output/x.docx`（相对路径会被浏览器补全成 `/workspace/c/output/x.docx` 或 `/log/chatlog/output/x.docx`，结果 404）。
5. 客户端 `Markdown` 组件只有在深度研究传入 `resolveArtifactLink` 时才解析 `output/` 链接；日常会话和审计页都是普通 `<a>`。

### 4.2 改动后数据流

```
脚本写 output/x.docx
 → BaseExecutor._publish_generated_files：上传 tmp-dir（对象名修正为 <uuid>.docx）
   └ collect_deliverables=True 时，把 {path, name, size, url} 追加到 executor.published_deliverables（加锁）
 → 回答结束（正常结束 / 停止 / 出错落库）
 → chat_service：从本次请求的 langchain_tools 中找到代码执行器，读取清单
   → 按 path 去重保留最后一次 → 只保留 output/ → 取最后 50 个
   → 组装附件项 → promote_chat_attachments（停止路径用 _sync 版本），成功的写入 object_name
   → build_answer_row(files=…) 落库
   → agent_answer end 事件的 message 增加 files
 → client：AgentPatch.files → 助手气泡渲染文件卡片；点击时 getAttachmentUrl 取新地址
 → 刷新后：/workstation/messages/{id}/agent 返回 row.files → mapAgentResponseItem 已映射到 message.files
 → platform 审计：/session/chat/messages/{id} 返回 files → 卡片 → 新接口签名
```

| 步骤 | 文件 / 函数 |
|---|---|
| 收集清单 | `code_interpreter/base_executor.py`：`_publish_generated_files`、新属性 `collect_deliverables` / `published_deliverables` |
| 对象名修正 | 同上，`f"{uuid.uuid4().hex}{file_ext}"` |
| 打开收集、追加说明 | `workstation/domain/services/chat_service.py`：在 `_attach_kb_image_stage` 附近新增 `_enable_deliverable_collection(tool)` |
| 读取、转正、落库 | `chat_service.py`：`build_answer_row` 增加 `files` 参数；三个落库点（约 1956 行内容安全、约 2009 行停止/中断、约 2605 行正常结束）；新增 `_collect_generated_files(tools)` 与组装函数 |
| SSE | `chat_service.py` 约 2625 行的 `agent_answer`/`end` 事件 |
| 共用签名 | `chat_session/domain/chat.py`：从 `resolve_attachment_url` 中拆出不带主人校验的 `_sign_attachment(chat_id, file_id, *, only_source=None)` |
| 审计签名接口 | `chat_session/api/endpoints/session.py`：新增 `GET /chat/{chat_id}/files/{file_id}/url` |
| client 展示 | `components/Chat/AiMessageBubble.tsx`（助手气泡渲染附件列表）、`hooks/useAiChatSSE.ts`（`AgentPatch.files`）、`attachments/ChatHistoryFileRow.tsx`（有 `object_name`、`file_id` 和 `conversationId` 时，先用 `getAttachmentUrl` 取新地址，再交给 `toChatArtifact` / 预览 / 下载） |
| client 工作区面板 | `hooks/useTaskWorkspaceState.ts` 通过 `collectChatAttachments` 汇总全部消息的 `files`，生成文件会随之进入面板；打开时复用同一个再签名函数 |
| client 正文链接 | `components/Chat/Messages/Content/Markdown.tsx`：日常会话传入基于 `message.files` 的链接解析器；复用 `artifactUtils.isDeliverableLinkHref` 的路径归一化 |
| platform 审计 | `pages/LogPage/useAppLog/dailyChatDetail.tsx`（卡片）、`DailyMessageContent.tsx`（链接规则）、`controllers/API/log.ts`（新接口） |

### 4.3 关键数据结构

回答行 `ChatMessage.files` 中的生成文件附件项（JSON）：

| 字段 | 示例 | 说明 | 消费方 |
|---|---|---|---|
| `file_id` | `"9f…"`（uuid hex） | 后端生成，签名接口按它查找 | client 卡片、审计卡片、两个签名接口 |
| `file_name` | `"北京今日天气_20261113.docx"` | 取路径最后一段；`getChatAttachmentFileName` 已支持读取 | 卡片显示、下载文件名、转正时取扩展名 |
| `path` | `"output/北京今日天气_20261113.docx"` | 工作目录内的相对路径，用于正文链接匹配 | 两端链接解析 |
| `type` | `"application/vnd.openxmlformats-officedocument.wordprocessingml.document"` | `mimetypes.guess_type`，猜不出为空 | 图片和文档分流 |
| `size` | `12345` | 字节数 | 卡片（可选展示） |
| `source` | `"code_interpreter"` | 区分用户上传附件 | 审计签名白名单 |
| `object_name` | `"chat/12/ab…docx"` | 转正成功后才有 | 签名、删除会话时清理 |
| `filepath` | `tmp-dir` 预签名地址 | 始终保留：转正读取它；`toChatArtifact` 没有地址会返回 null，卡片会变成不可点击。转正成功后它只作为占位，打开时以再签名地址为准；转正失败时它是 7 天内的兜底 | 转正、`toChatArtifact`、卡片兜底 |

SSE：`agent_answer`/`end` 的 `message` 由 `{msg, events}` 变为 `{msg, events, files}`；没有生成文件时 `files` 为 `[]`。落库的 `message` 列仍是 `{msg, events}`，附件只存在 `files` 列。

新接口 `GET /api/v1/session/chat/{chat_id}/files/{file_id}/url` → `resp_200({"url": str})`。不在审计范围时返回 `UnAuthorizedError`（与详情接口相同）；附件不存在、不是 `code_interpreter` 来源或没有 `object_name` 时返回 `NotFoundError`。

### 4.4 模块职责

| 模块 | 职责 | 不做什么 |
|---|---|---|
| `BaseExecutor` | 发布文件，按开关收集清单 | 不知道会话、用户、存储分区；不改返回给模型的内容 |
| `chat_service`（workstation） | 打开收集、去重截断、转正、落库、推送 | 不签名 |
| `ChatSessionService` | 按会话已存附件签名 | 不判断审计范围 |
| `AuditLogService` | 判断审计范围 | 不碰对象存储 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | `os.path.splitext` 返回的扩展名已带点，现有代码又拼了一个点 | 对象名是 `<uuid>..docx`；转正时 `_safe_extension` 取到的扩展名正常，但临时地址难看，下载时也拿不到原文件名 | `_publish_generated_files` 修正（AC-23） |
| 2 | `touched` 里还包含 `scratch/` 文件，以及被修改过的上传源文件 | 卡片里混进中间文件和用户自己的源文件 | 收集时只保留路径以 `output/` 开头的文件（AC-02） |
| 3 | 非图片附件行 `ChatHistoryFileRow` 直接使用存下来的 `filepath`，只有图片会走 `getAttachmentUrl` 重新签名 | 卡片 7 天后失效；用户上传的文档附件目前也有这个问题 | 有 `file_id` 和 `conversationId` 时点击再签名；用户上传文档附件会顺带受益，回归时要覆盖 |
| 4 | `UploadedFileList` 只在用户气泡里渲染，而且右对齐 | 直接复用会把卡片排在助手气泡右侧 | 助手气泡使用左对齐版本 |
| 5 | 停止/中断路径（约 2009 行）运行在流关闭阶段，只能用同步 DAO | 在这里调用异步转正会失败或被取消 | 改用 `promote_chat_attachments_sync`，把分区作为它的 `user_id` 参数传入 |
| 6 | `resolve_attachment_url` 签出的地址默认 `clear_host=True`，是走 nginx `/bisheng` 代理的相对路径；执行器给的地址是 `sharepoint` 主机直连 | 兜底的 `filepath` 在浏览器访问不到 MinIO 端口的环境里打不开 | 只把它作为转正失败时的兜底；spec §3 已写明 |
| 7 | 同一请求中模型可能并行调用代码执行器，`LocalExecutor.run` 在线程中执行 | 清单追加时出现竞态 | `published_deliverables` 追加时加 `threading.Lock` |
| 8 | 正文链接会被 URL 编码（`%E5%8C%97…`），也可能带 `./` 或前导 `/` | 匹配不上，正确的附件被显示成不可点击文字 | 匹配前先 `decodeURIComponent`（容错），再去掉 `./` 和 `/` |
| 9 | 深度研究同样使用 `Markdown` 组件，也会传入 `resolveArtifactLink` | 日常会话的链接规则影响深度研究 | 只有日常会话气泡传入基于附件的解析器；深度研究的分支保持不变（AC-22） |
| 10 | `toChatArtifact` 在附件没有 `filepath` 等地址字段时返回 null；`ChatHistoryFileRow` 据此判断能否点击 | 转正后如果删掉 `filepath`，卡片会变灰、点不开 | 保留 `filepath`，点击时先再签名（§4.3） |
| 11 | `useTaskWorkspaceState` 会把会话里所有消息的 `files` 汇总进工作区文件面板，不区分用户还是助手 | 生成文件出现在面板里，面板直接使用存储的 `filepath`，7 天后打不开 | 面板打开文件时复用再签名函数；验收时一并检查面板 |

---

## 6. 对外契约与依赖

### 6.1 Outgoing

| 契约 | 形式 | 谁在用 |
|---|---|---|
| 回答行 `files` 中 `source=code_interpreter` 的附件项（§4.3） | 数据契约 | client 历史、审计详情、会话删除清理 |
| `agent_answer`/`end`.`message.files` | SSE | client `useAiChatSSE` |
| `GET /api/v1/session/chat/{chat_id}/files/{file_id}/url` | HTTP | platform 审计页 |
| `BaseExecutor.collect_deliverables` / `published_deliverables` | 内部 Python API | 日常会话 |

### 6.2 Incoming

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `promote_chat_attachments` 读取 `filepath` + `file_name` | 隐式数据契约 | 字段名变化会导致转正静默跳过 |
| `WorkflowFileRepository.attachment_messages` 扫描全部带 `files` 的行 | 查询契约 | 若改成只看提问行，签名和删除会漏掉生成文件 |
| `AuditLogService.assert_session_in_audit_scope` | F003 | 范围规则变化会直接影响下载权限 |
| 执行器只在无 `workspace_prefix` 时走 `upload_minio` | 执行器行为 | 若日常会话以后接入工作区，收集点要换到 `sync_to_workspace` |

错误码：沿用 `UnAuthorizedError`、`NotFoundError`，不新增。数据库：不新增表、列或迁移。

---

## 7. 测试与可观测

- **后端单测**（`test/workstation/`、`test/sandbox/`、`test/chat_session/`）：
  - 收集开关：开启时只收 `output/`，并按路径去重；关闭时为空。
  - 对象名不再有双点。
  - 三个落库点都写入 `files`；内容安全替换时为空。
  - 超过 50 个时截断。
  - 转正失败时保留 `filepath`，不报错。
  - 审计接口：在范围内能签名；不在范围内被拒；`source` 不是 `code_interpreter` 时返回不存在。
- **前端单测**：
  - `AgentPatch.files` 能更新到气泡。
  - 链接解析：匹配、URL 编码、`./` 前缀、找不到时显示为文字。
  - 历史消息（无 `files`）中的链接显示为文字。
  - 深度研究链接行为不变。
- **手动验证（116）**：
  - 日常会话启用代码执行器，输入「生成一个测试 docx 文件」。期望：回答下方出现卡片，可以下载；刷新后仍在；在 MinIO 主桶 `chat/<用户>/` 下能看到对象。
  - 审计页打开 `/log/chatlog/<会话id>`，看到相同卡片并能下载。
  - 换一个不在审计范围内的管理员，直接调用新接口应被拒。
- **日志**：转正失败沿用 `promote_chat_attachments` 的 `logger.exception`；新增一行 `daily chat generated files chat_id={} count={} promoted={}`，便于现场排查。

---

## 8. 后续改进 / 不打算做的事

- E2B 执行器需要先把 `output/` 文件复制出沙箱并上传，才能接入本功能；等出现实际需求再做。
- 管理员下载附件目前不记审计日志；如果合规要求「谁看过/下载过什么」，在新接口上补审计动作。
- 历史消息不回填：旧消息的临时对象可能已经过期，回填需要另写脚本，收益有限。
- 工具调用卡片里依然能看到原始 `file_list`（MinIO 直连地址），如果被认为属于信息暴露，另行处理。

---

## 9. Constitution Check（自查，待 `/sdd-review design` 复核）

| 条款 | 结论 |
|---|---|
| C1 | 新审计接口只调用 `AuditLogService` 和 `ChatSessionService`，不直接查 ORM |
| C2 | 不涉及 DDL |
| C3 | 不手写 `tenant_id` 条件；会话读取沿用现有带租户注入的查询 |
| C4 | 不新增资源权限判断；审计范围复用 F003 现有判定；会话本人校验沿用 `_own_conversation_or_raise` |
| C5 | 不新增错误码 |
| C6 | 无密钥 |
| C7 | client 和 platform 的新 HTTP 调用分别放在 `api/chatApi.ts`、`controllers/API/log.ts` |
| C8 | 文件内容的唯一来源是主桶对象，消息行存指针；执行器收集列表只在本次请求内有效，不承担持久化 |

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-11-13 | 初版 | 116 报障：日常会话生成文件下载 404 |

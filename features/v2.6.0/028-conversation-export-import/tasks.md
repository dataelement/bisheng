# Tasks: 工作台会话回答级导出与导入知识空间（F028）

**关联规格**: [spec.md](./spec.md)
**版本**: v2.6.0
**基线依赖**: F004（ReBAC core）+ F008（resource-rebac-adaptation）+ 现有 `workstation/` / `chat_session/` / `knowledge_space/` / `libreoffice_converter`

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 单轮 /sdd-review 通过；3 low MISSING（文件大小/敏感内容/取消按钮单独 AC）+ 2 ISSUE（INV-6 豁免说明 / 前后端 How 偏多）按方案 3 跳过；文件大小 + 敏感词二次确认后已在 spec §「本次明确排除」补充 |
| tasks.md | ✅ 已拆解 | 两轮 /sdd-review tasks 通过（4 medium 修后 LGTM；3 low 跳过：T013 测试实现合并、T015/T019 跨 3 文件、T001 Dockerfile 影响范围简述） |
| 实现 | 🔲 未开始 | 0 / 23 完成 |

---

## 开发模式

- **后端 Test-First**：service 取数、Markdown 中间表达、四种 renderer、同名追加、权限拦截全部先写测试再补实现；图片预处理用 fixture 桶 mock 而不依赖真实 MinIO。
- **前端 Test-Alongside（手动验证）**：Client 端无自动化测试基线，按 PRD 样式图 + AC 操作清单逐项过；H5 通过浏览器 device toolbar 模拟。
- **跨进程依赖前置**：T001 必须先在 docker 镜像里 smoke test `pandoc` / `soffice` / 中文字体可用；不通过则**先改 Dockerfile 再继续**，否则后端 service 无法跑通。
- **真实角标样本**：T002 必须从生产 / 测试库捞 5 条以上含 RAG 角标的 `ChatMessage.message` 真实样本，落档作为 `_strip_citation_marks` 正则集合的依据；spec 阶段未勘察，本期作为前置探查任务补齐。
- **自包含任务**：每个任务内联文件、逻辑、测试上下文、AC 覆盖，实现阶段不必反复回读 spec。

---

## 执行阶段计划

1. **前置探查（T001-T003）**：Docker 依赖 + 角标真实形态 + ChatMessageDao 现状盘点。结果落档于「实际偏差记录」，作为后续任务的硬约束。
2. **后端基础设施（T004-T006）**：错误码、DTO、reference docx 模板。
3. **后端 Service（T007-T013）**：导出方向取数 → 中间表达 → 四 renderer + 图片预处理 → 导入方向 → 可上传空间查询；每段严格 test-first 配对。
4. **后端 API（T014-T015）**：3 个 endpoint 测试 + 实现 + router 注册。
5. **前端 Client（T016-T021）**：API client → Recoil 选择态 → AddToKnowledgeModal 改造 → 选择 UI 组件套件 → Messages footer 接入 → i18n。
6. **集成验证（T022）**：/e2e-test 跑通 31 条 AC。

**总任务数**：23（T001-T017、T018a、T018b、T019-T022）

---

## Tasks

### 阶段 1：前置探查（无测试配对，结果落档）

- [ ] **T001**: Docker 镜像 pandoc / LibreOffice / 中文字体 smoke test（条件性补镜像）
  **文件**:
  - 探查脚本：`scripts/check_export_dependencies.sh`（新建，可丢弃）
  - 条件性修改：`docker/Dockerfile`（如缺）
  **逻辑**:
  - 进入 bisheng-backend 容器，跑：`which pandoc && pandoc --version`、`which soffice && soffice --version`、`fc-list :lang=zh | head -5`。
  - **pandoc 缺失** → `RUN apt-get install -y pandoc`（apt 源若缺需切换 contrib/non-free）。
  - **LibreOffice 缺失** → 不应缺失（知识库 PPT→PDF 已在用）；若真的缺则 `RUN apt-get install -y libreoffice-core libreoffice-writer`。
  - **中文字体缺失** → `RUN apt-get install -y fonts-noto-cjk fonts-wqy-microhei`。
  - 跑一次端到端 mini smoke：`echo "**测试** 中文" | pandoc -f markdown -t docx -o /tmp/t.docx && soffice --headless --convert-to pdf /tmp/t.docx --outdir /tmp && file /tmp/t.pdf` —— 验证三件套联动 OK。
  **结果落档**: 「实际偏差记录」§T001：`{pandoc: <version>, soffice: <version>, fonts: <count>, dockerfile_changed: bool}`
  **覆盖 AC**: —（spec §10 非功能 - 性能 / AD-01 / AD-02 前置条件）
  **依赖**: 无

- [ ] **T002**: RAG 角标真实形态勘察 + 落档
  **文件**:
  - 一次性 SQL/脚本：`scripts/dump_rag_citation_samples.py`（新建，可丢弃）
  - 输出：「实际偏差记录」§T002 内嵌样本
  **逻辑**:
  - 在测试库（最好生产快照）跑：`SELECT id, message FROM chat_message WHERE category IN ('answer', 'agent_answer') AND (message LIKE '%[1]%' OR message LIKE '%<sup%' OR message LIKE '%【%】%') LIMIT 50;`
  - 人工筛选 ≥5 条含真实 RAG 角标的样本，把原始 message 片段贴进偏差记录。
  - 对照 bisheng 后端 RAG 渲染代码（如 `bisheng/api/services/llm_callback.py` 或类似）确认角标生成规则。
  - **额外线索**：前端已有 `src/frontend/client/src/components/Chat/Messages/Content/citationUtils.ts`，封装了角标渲染 / 规范化逻辑；通过它能反推后端存储格式，是较快的入口。
  - 产出最终正则集合，写进 T010 的 `_strip_citation_marks` 实现里。**禁止仅凭"应该是这样"猜测**。
  **结果落档**: 「实际偏差记录」§T002
  **覆盖 AC**: AC-14 前置
  **依赖**: 无

- [ ] **T003**: ChatMessageDao 现状盘点
  **文件**: 只读 `src/backend/bisheng/chat_session/`（或 `database/models/message.py` 中现有 DAO）
  **逻辑**:
  - grep `ChatMessageDao` 的所有 classmethod，确认是否已有按 `id IN (...)` + `user_id` 过滤的方法。
  - 若已有等价方法（如 `aget_messages_by_ids`），T008 直接复用；若没有，T008 新增。
  - 同时确认 `extra` 字段读取约定（JSON string 还是 dict）、`message` 字段在不同 category 下的格式（PRD 已知有纯文本 + `{msg, events[]}` 两种）。
  **结果落档**: 「实际偏差记录」§T003：`{existing_dao_methods: [...], extra_field_format, message_field_formats: [...]}`
  **覆盖 AC**: —（影响 T007/T008 决策）
  **依赖**: 无

### 阶段 2：后端基础设施（无测试配对）

- [ ] **T004**: 工作台错误码扩展（12060-12069）
  **文件**: `src/backend/bisheng/common/errcode/workstation.py`
  **逻辑**: 沿用现有 12040-12045 的写法，追加 10 个错误类，全部继承 `BaseErrorCode`：

    | Code | Class | Msg |
    |------|-------|-----|
    | 12060 | `ConversationMessageNotFoundError` | 消息不存在或已删除，请刷新会话 |
    | 12061 | `ConversationMessageBatchTooLargeError` | 单次最多选中 200 条消息 |
    | 12062 | `ConversationMessageNotOwnedError` | 消息不存在或无访问权 |
    | 12063 | `ConversationExportFormatUnsupportedError` | 不支持的导出格式 |
    | 12064 | `ConversationExportRenderFailedError` | 文件生成失败，请稍后重试 |
    | 12065 | `ConversationImportSpaceNotFoundError` | 知识空间不存在或已删除 |
    | 12066 | `ConversationImportFolderNotFoundError` | 文件夹不存在或已删除 |
    | 12067 | `ConversationImportPermissionDeniedError` | 暂无权限导入到该知识空间 |
    | 12068 | `ConversationImportQuotaExceededError` | 知识空间配额已满 |
    | 12069 | `ConversationImportFailedError` | 导入失败，请稍后重试 |
  **依赖**: 无

- [ ] **T005**: Pydantic DTO schemas
  **文件**: `src/backend/bisheng/workstation/domain/schemas/conversation_export.py`（新建）
  **逻辑**: 定义 `ExportFormat`（Enum）/ `ExportMessagesRequest` / `ImportMessagesToKnowledgeRequest` / `ImportMessagesToKnowledgeResponse` / `UploadableSpaceItem` / `UploadableSpaceListResponse`（spec §5.2）。`message_ids` 加 `min_length=1, max_length=200` Field 约束（与 AC-08 配套，FastAPI 层即拦）。
  **依赖**: 无

- [ ] **T006**: 程序化生成 reference docx 模板
  **文件**:
  - 生成脚本（一次性）：`scripts/gen_conversation_export_template.py`（新建，入仓但不参与运行时）
  - 模板产物：`src/backend/bisheng/workstation/assets/conversation_export_template.docx`（新建）
  - 占位 init：`src/backend/bisheng/workstation/assets/__init__.py`
  **逻辑**:
  - 用 `python-docx` 构建 reference 模板：
    - A4 纵向、白底、上下左右 2.5cm 边距
    - Default `Normal` 段落字体：微软雅黑（中文）/ Calibri（西文），11pt，行距 1.5
    - `Heading 1`: 微软雅黑加粗 16pt
    - `Heading 2`: 微软雅黑加粗 14pt
    - `Heading 3`: 微软雅黑加粗 12pt
    - 自定义 character style「BoldLabel」用于标签段（用户名 / 模型名）：加粗 14pt
    - 代码块（`Source Code` style）：等宽字体 10pt + 浅灰背景
    - 表格默认带 1px 灰边框
  - 脚本支持 `python scripts/gen_conversation_export_template.py --out src/backend/bisheng/workstation/assets/conversation_export_template.docx` 一键再生。
  - 在 docstring 里说明：UX 后续可手工编辑 .docx 直接替换，重新跑脚本即覆盖。
  **测试**: 跑完脚本后用 `pypandoc.convert_text("**a**\n\n# h1\n\n表格 | b\n--- | ---\n1 | 2", "docx", reference_doc=<path>)` 生成测试 docx，肉眼检查 LibreOffice 打开样式接近 PRD 样式图。
  **依赖**: T001（确保 LibreOffice 可用以肉眼验证）

### 阶段 3：后端 Service（Test-First）

- [ ] **T007**: ConversationExportService 取数 / 配对 / turn 构建 单元测试
  **文件**: `src/backend/test/workstation/test_conversation_export_service.py`（新建）+ `src/backend/test/workstation/__init__.py`
  **逻辑**: 测试 `_load_and_validate_messages` + `_build_turns` 两个私有方法（也可通过 `export_messages` 入口间接测试，建议先单测私有方法）：

    | 测试 | 场景 | AC |
    |---|---|---|
    | `test_load_happy_path` | 同会话同用户 5 条 message，按 id 拉回 | AC-01 |
    | `test_load_cross_chat_rejected` | message_ids 跨两个 chat_id | AC-28 → 12062 |
    | `test_load_cross_user_rejected` | message_ids 属于其他 user | AC-25 → 12062 |
    | `test_load_partial_missing_rejected` | message_ids 中 1 个不存在 | AC-27 → 12060 |
    | `test_load_over_200_rejected` | 传 201 条 | AC-08 → 12061 |
    | `test_build_turns_daily_mode` | flow_type=15，取 `ChatMessage.sender` 作模型名 | AC-11 / spec §7.1 |
    | `test_build_turns_assistant` | flow_type=5，取 `MessageSession.flow_name` | AC-11 |
    | `test_build_turns_workflow_multi_answer` | 单 query 多 answer，全部保留 | AC-06 |
    | `test_build_turns_workflow_nontext_output` | events 含非 text 输出 → 占位 | AC-09 |
    | `test_build_turns_agent_answer_msg_only` | events[] 含 thinking/tool_call → 只取 msg | AC-15 |
    | `test_build_turns_strip_citations` | 多形态角标全部剥除（基于 T002 真实样本） | AC-14 |
    | `test_build_turns_parentMessageId_missing` | legacy 数据无 parentMessageId → 时间相邻兜底 | spec §3 |

  **基础设施**: `test/workstation/__init__.py` + 顶级 conftest（若不存在，本任务一并新建 fixtures：mock ChatMessageDao、mock MessageSession、mock UserPayload）。
  **覆盖 AC**: AC-01, AC-06, AC-08, AC-09, AC-11, AC-14, AC-15, AC-25, AC-27, AC-28
  **依赖**: T002（角标样本）、T003（DAO 现状）

- [ ] **T008**: ConversationExportService 取数 / 配对 / turn 构建 实现
  **文件**: `src/backend/bisheng/workstation/domain/services/conversation_export_service.py`（新建）
  **逻辑**: 实现 `_load_and_validate_messages` + `_build_turns` 两个方法（spec §7.1 表格中"取数 + 中间表达"部分）。SQL 过滤必须包含 `user_id` + `chat_id` + 隐式 `tenant_id`（SQLAlchemy 事件已注入）。若 T003 发现 DAO 没有现成方法，本任务一并加 `ChatMessageDao.aget_messages_by_ids(message_ids, user_id, chat_id)`。
  **测试**: T007 全部通过。
  **覆盖 AC**: AC-06, AC-08, AC-09, AC-11, AC-14, AC-15, AC-25, AC-26, AC-27, AC-28
  **依赖**: T004, T005, T007

- [ ] **T009**: 四种 renderer + 图片预处理 单元测试
  **文件**: `src/backend/test/workstation/test_conversation_export_renderers.py`（新建）
  **逻辑**:

    | 测试 | 场景 | AC |
    |---|---|---|
    | `test_render_markdown_structure` | 用户名加粗段 / `---` 分隔 / 多 turn 拼接顺序 | AC-12 |
    | `test_render_docx_via_pypandoc` | 调 pypandoc.convert_text，输出 bytes ≠ 0、能被 zipfile 识别 | AC-11 |
    | `test_render_pdf_via_libreoffice` | docx → pdf 链路，输出文件头是 `%PDF` | AC-11 |
    | `test_render_txt_strips_markdown` | 表格 Tab 化、图片 `[图片：<name>]` 占位、代码块保留缩进 | AC-13 |
    | `test_preprocess_images_minio` | mock MinioManager 返回 bytes，URL 被替换为本地 `file://` | AD-06 |
    | `test_preprocess_images_httpx_fail_fallback` | httpx 抛超时 → 替换为 `[图片加载失败：<url>]` | AC-29 |
    | `test_resolve_filename_truncate_and_sanitize` | 100 字标题被截到 80 字；`<>:"/\|?*` 全替换；末尾空格点删除 | AC-10 |
    | `test_resolve_filename_empty_title` | 标题为空 → `未命名会话_yyyyMMddHHmm.ext` | AC-10 |
    | `test_strip_citation_marks` | T002 收集的 5+ 角标样本全部清理干净 | AC-14 |
    | `test_export_render_timeout` | LibreOffice subprocess 抛 TimeoutExpired → 12064 | AC-30 |

  **覆盖 AC**: AC-10, AC-11, AC-12, AC-13, AC-14, AC-29, AC-30
  **依赖**: T002

- [ ] **T010**: 四种 renderer + 图片预处理 实现
  **文件**: `conversation_export_service.py`（追加）
  **逻辑**: 实现 `_render_markdown` / `_render_docx` / `_render_pdf` / `_render_txt` / `_preprocess_images` / `_resolve_filename` / `_strip_citation_marks` + 顶层 `export_messages` 编排（spec §7.1）。
  - `_render_docx` 使用 `pypandoc.convert_text(md, 'docx', format='markdown', extra_args=['--reference-doc=<template>'])`，模板路径用 `importlib.resources` 取仓内 asset。
  - `_render_pdf` 调用 `libreoffice_converter._convert_file_extension(docx_path, 'pdf', tempdir, except_file_ext='pdf')`；超时 30s（已是 converter 默认 180s，需在调用方再加 30s timeout 保护或调整 converter timeout 参数）。
  - `_preprocess_images` 用 `httpx.AsyncClient(timeout=5)` + 并发上限 8（`asyncio.Semaphore(8)`）；MinIO 走 `MinioManager.get_bytes`。
  - `_strip_citation_marks` 正则集合来源：T002 落档样本。
  - 所有临时文件用 `tempfile.TemporaryDirectory()` 上下文管理；FastAPI Response 发送完成后自动清理。
  - LibreOffice / pandoc subprocess 异常一律封装为 `ConversationExportRenderFailedError(reason=<engine_name>)`，不允许吞异常（CLAUDE.md backend §Error Handling）。
  **测试**: T009 全部通过。
  **覆盖 AC**: AC-10, AC-11, AC-12, AC-13, AC-14, AC-29, AC-30
  **依赖**: T006, T008, T009

- [ ] **T011**: 导入流程（同名追加 + add_file 集成）单元测试
  **文件**: `src/backend/test/workstation/test_conversation_export_import.py`（新建）
  **逻辑**:

    | 测试 | 场景 | AC |
    |---|---|---|
    | `test_import_happy_path` | 选 2 条 message，目标空间根目录 → 生成 .md → 调 add_file → 返 file_id + dup_renamed=false | AC-18 |
    | `test_import_dup_renamed_to_1` | 目标已有同名 → 落地 `xxx(1).md`，dup_renamed=true | AC-19 |
    | `test_import_dup_renamed_to_5` | 同名 (1)~(4) 都已存在 → 落地 (5) | AC-19 |
    | `test_import_dup_race_retry_once` | add_file 第一次报重名 → 重新扫描重命名后重试 1 次 → 成功 | spec §3 |
    | `test_import_dup_race_fail_after_retry` | 重试仍报重名 → 12069 | spec §3 |
    | `test_import_permission_denied_pre_check` | mock PermissionService.check 抛 → 12067 不调 add_file | AC-20 |
    | `test_import_space_not_found` | mock 空间查不到 → 12065 | AC-21 |
    | `test_import_folder_not_found` | mock 文件夹查不到 → 12066 | AC-22 |
    | `test_import_quota_exceeded` | mock add_file 抛配额异常 → 归一化为 12068 | AC-23 |
    | `test_import_add_file_failed` | mock add_file 抛其它异常 → 12069 | AC-19 |

  **覆盖 AC**: AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24
  **依赖**: T002, T003

- [ ] **T012**: 导入流程实现
  **文件**: `conversation_export_service.py`（追加 `_resolve_unique_filename` + `import_messages_to_knowledge`）
  **逻辑**:
  - 复用 T008 的 `_load_and_validate_messages` + `_build_turns`、T010 的 `_render_markdown`。
  - 先调 `PermissionService.check(<space|folder>, "upload_file")` 早返错（AC-20 早返语义）；不依赖 `add_file` 内部校验作为唯一防线。
  - `_resolve_unique_filename` 调 `KnowledgeSpaceFileDao.async_list_children(space_id, parent_id)` 拉本层级文件名列表 → set 内查重 → 追加 `(N)`。
  - 把 Markdown bytes 写到 `tempfile.NamedTemporaryFile(suffix='.md')` → 拿到 file_path → 调 `KnowledgeSpaceService.add_file(knowledge_id=space_id, file_path=[md_path], parent_id=parent_id)` → 拿 file_id。
  - 异常映射：`add_file` 内部抛的配额 / 重名 / 敏感等错误，分别映射到 12068 / 12069 / 透传（敏感错误按 AC-23 含义靠现有链路展示，不在本接口拦截）。
  **测试**: T011 全部通过。
  **覆盖 AC**: AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24
  **依赖**: T008, T010, T011

- [ ] **T013**: `KnowledgeSpaceService.list_uploadable_spaces` 单元测试 + 实现
  **文件**:
  - 测试：`src/backend/test/knowledge/test_uploadable_spaces.py`（新建）
  - 实现：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`（追加方法）
  **逻辑**:
  - 单元测试 3 条：
    | 测试 | 场景 | AC |
    |---|---|---|
    | `test_list_uploadable_filters_by_upload_file` | mock `PermissionService.list_resources(user, "upload_file", "knowledge_space")` 返 [42, 56] → 拉 KnowledgeSpace 元信息 → 返回 2 项 | AC-17 |
    | `test_list_uploadable_keyword_filter` | keyword="黄金" → 仅返回 name 含「黄金」的 | AC-17 |
    | `test_list_uploadable_empty` | list_resources 返空 → 返 `[]`，不抛 | AC-17 |
  - 实现按 spec §7.2 模板；按 `update_time DESC` 排序。**首版不分页**（与 INV-6 豁免论据：单用户可上传空间数量级 ≤100；spec §3 范围边界已说明本豁免，但未单独成 AC，本接口在 docstring 里再强调一次）。
  **覆盖 AC**: AC-17
  **测试 / 实现合并理由**: 单 service 方法 + 3 个测试用例，独立拆对工作量增益小；保留测试先写 / 实现紧跟的内部顺序。
  **依赖**: T004（导入需要的错误码已存在）

### 阶段 4：后端 API（Test-First）

- [ ] **T014**: 3 个 endpoint 集成测试
  **文件**: `src/backend/test/workstation/test_conversation_export_api.py`（新建）+ `src/backend/test/knowledge/test_uploadable_spaces_api.py`（新建）
  **逻辑**: 用 FastAPI `TestClient` 跑端到端：

    | 测试 | 接口 + 场景 | AC |
    |---|---|---|
    | `test_export_pdf_returns_file_stream` | POST /export, format=pdf, 选 4 条 message → 200 OK + `Content-Type: application/pdf` + `Content-Disposition` 含 RFC5987 编码文件名 | AC-02 |
    | `test_export_unauthorized` | 无 Cookie → 401（沿用现有认证拦截） | spec §10 安全 |
    | `test_export_format_unsupported` | format="xlsx" → 12063 | AC-31 |
    | `test_export_over_200` | 传 201 message_ids → FastAPI 422 或 12061（取决于 DTO max_length 拦截位置） | AC-08 |
    | `test_import_happy_path_via_api` | POST /import-to-knowledge, parent_id=null → 200 + file_id + target_filename | AC-18 |
    | `test_import_missing_space` | knowledge_space_id 不存在 → 12065 | AC-21 |
    | `test_uploadable_returns_filtered_list` | GET /uploadable?keyword=黄金 → 仅返关键词命中项 | AC-17 |
    | `test_uploadable_empty_for_user_without_permission` | mock list_resources 返空 → `data: []` | AC-17 |

  **覆盖 AC**: AC-02, AC-08, AC-17, AC-18, AC-21, AC-31
  **依赖**: T010, T012, T013

- [ ] **T015**: 3 个 endpoint 实现 + Router 注册
  **文件**:
  - 新建：`src/backend/bisheng/workstation/api/endpoints/conversation_export.py`（2 个 POST 端点）
  - 修改：`src/backend/bisheng/workstation/api/router.py`（注册）
  - 修改：`src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`（追加 `GET /uploadable`）
  **逻辑**:
  - 两个 POST 端点：
    - `POST /api/v1/chat/messages/export` → 接收 `ExportMessagesRequest`，委托 `ConversationExportService.export_messages` → 返回 `StreamingResponse(bytes_io, media_type=mimetype, headers={"Content-Disposition": <RFC5987 编码>})`。
    - `POST /api/v1/chat/messages/import-to-knowledge` → 接收 `ImportMessagesToKnowledgeRequest`，委托 service，用 `resp_200(data)` 返回。
  - 路由路径前缀：在 workstation 模块内注册，但路由路径以 `/api/v1/chat/messages/...` 出现（前端心智一致；router prefix 用 `/api/v1/chat` 或在 endpoint decorator 显式给路径）。
  - `GET /api/v1/knowledge/space/uploadable` → 注入 keyword query param → 委托 `KnowledgeSpaceService.list_uploadable_spaces`。
  - 所有 endpoint 注入 `user: UserPayload = Depends(UserPayload.get_login_user)`；委托给 service，endpoint 层禁止直接 import `database/models/*`（arch-guard RULE-3）。
  - 错误码统一通过 `XxxError.return_resp()` 返回，不要走 `resp_500(message=str(e))`（CLAUDE.md backend §Error Handling）。
  **测试**: T014 全部通过。
  **覆盖 AC**: 全部 endpoint 级 AC（AC-02, AC-17, AC-18, AC-21, AC-25-28, AC-31）
  **依赖**: T010, T012, T013, T014

### 阶段 5：前端 Client（手动验证）

- [ ] **T016**: messageExport API client + AddToKnowledgeModal 数据源开关
  **文件**:
  - 新建：`src/frontend/client/src/api/messageExport.ts`
  - 修改：`src/frontend/client/src/pages/Subscription/Article/AddToKnowledgeModal.tsx`
  **逻辑**:
  - `messageExport.ts` 三个函数：`exportMessagesApi`（`responseType: 'blob'`）/ `importMessagesToKnowledgeApi` / `listUploadableSpacesApi`（spec §8.1）。
  - AddToKnowledgeModal 加一个可选 prop `dataSourceApi?: (keyword?: string) => Promise<UploadableSpaceItem[]>`。在加载空间树时，**优先使用** `dataSourceApi`（如有传入），否则按现有 mode 分支调 `getManagedSpacesApi` / `getMineSpacesApi`。**原有调用方零改动**（向后兼容硬约束）。
  **覆盖 AC**: AC-02, AC-17, AC-18 客户端侧；不直接对应 UI AC，作为下游依赖
  **手动验证**:
  - 打开 article 页 / channel-sync 页测试现有调用流程不被破坏
  - 用浏览器 DevTools 验证 `dataSourceApi` 注入时调用的是 `/uploadable` 接口
  **依赖**: T015

- [ ] **T017**: Recoil 选择态 store + useMessageSelection hook
  **文件**:
  - 新建：`src/frontend/client/src/store/messageSelectionStore.ts`
  - 新建：`src/frontend/client/src/hooks/useMessageSelection.ts`
  **逻辑**:
  - atom：`messageSelectionAtom`（含 `active` / `chatId` / `selectedIds: Set<string>` / `anchorMessageId` / `globalSelectAllOn` / `selectAllBelowAnchor`）。
  - selector：`isMessageSelectedSelector` 派生单条消息是否被选中（综合 globalSelectAllOn / selectAllBelowAnchor / 显式 selectedIds）。
  - hook 暴露：`enterSelectionMode(initialMessageId)` / `exitSelectionMode()` / `toggleMessage(messageId)` / `selectAll()` / `selectAllBelow(anchorId)` / `getSelectedIds(currentMessages)` / `isOverLimit(currentMessages)`。
  - **配对联选**：`toggleMessage` 内部按 `extra.parentMessageId` 自动拉对应 query / answer；多 answer 全部联选（AC-06）；legacy 无 parentMessageId 时只选当前（spec §3 兜底）。
  - **切换会话**：监听全局 `currentChatId` 变化 → 自动调 `exitSelectionMode`（AC-25 / spec §3）。
  - **>200 拦截**：`getSelectedIds` 实例化具体 ID 集合时，若数量超 200，返回特殊 marker 让调用方阻断 + toast（AC-08）。
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-05, AC-06, AC-08
  **手动验证**:
  - 用 React DevTools / Recoil DevTools 观察 atom 在交互过程中的状态切换
  - 进入选择态 → 切换会话 → atom 应清空
  **依赖**: 无

- [ ] **T018a**: 选择态主组件 — Toolbar + Checkbox + barrel
  **文件**:
  - 新建：`src/frontend/client/src/components/Chat/MessageSelection/MessageSelectionToolbar.tsx`
  - 新建：`src/frontend/client/src/components/Chat/MessageSelection/MessageCheckbox.tsx`
  - 新建：`src/frontend/client/src/components/Chat/MessageSelection/index.ts`（barrel；导出本任务 + T018b 组件）
  **逻辑**:
  - `<MessageSelectionToolbar>`：根据视口宽度（`useIsMobile()` 或现有等价 hook）选 PC（横向 6 个按钮：全选 / 4 个格式 / 导入到知识空间 / 关闭）或 H5（3 按钮：全选 / 导出到本地 / 导入到知识空间 / 关闭）布局；按钮触发 → 调对应 API（`exportMessagesApi` 直下载 blob / 打开 `AddToKnowledgeModal` / 打开 `<ExportFormatSheet>`）。
  - `<MessageCheckbox>`：圆形 checkbox，受 `isMessageSelectedSelector` 控制；点击调 `toggleMessage`。
  - 下载：拿到 blob 后用 `<a download={filename}>` 触发；filename 从 response `Content-Disposition` 头部解码（RFC5987）。
  - barrel 文件统一导出本任务和 T018b 的四个组件，简化下游 import。
  **覆盖 AC**: AC-01, AC-02, AC-16
  **手动验证**:
  - PC chrome：模拟选择态注入 → toolbar 6 按钮可见 + 点 PDF 触发下载（HAR 抓包验证）
  - H5 模拟（device toolbar，iPhone 14）：toolbar 切到 3 按钮布局
  **依赖**: T016, T017

- [ ] **T018b**: 选择态辅助组件 — ExportFormatSheet + SelectAllBelowBanner
  **文件**:
  - 新建：`src/frontend/client/src/components/Chat/MessageSelection/ExportFormatSheet.tsx`（H5 底部弹层）
  - 新建：`src/frontend/client/src/components/Chat/MessageSelection/SelectAllBelowBanner.tsx`
  **逻辑**:
  - `<ExportFormatSheet>`：shadcn `Sheet` 组件，从底部弹出 4 个文件类型选项（Word / PDF / Markdown / TXT）；选完后调 `exportMessagesApi`。
  - `<SelectAllBelowBanner>`：渲染在选择态下、用户右键或长按某条消息时弹出（PRD 文案「点击全选以下消息」）；点击调 `selectAllBelow(anchorId)`。
  **覆盖 AC**: AC-05, AC-13
  **手动验证**:
  - H5 模拟：点「导出到本地」→ ExportFormatSheet 从底部弹起 → 选 Word → 触发下载
  - 选择态下右键/长按某条消息 → SelectAllBelowBanner 浮现 → 点后该锚点以下消息全勾上
  **依赖**: T017

- [ ] **T019**: 在 Messages footer 接入「导出」icon + 启用选择态
  **文件**:
  - 修改：`src/frontend/client/src/components/Chat/Messages/HoverButtons.tsx`（PC 端 footer icon 区，与"复制"icon 同层）
  - 修改：`src/frontend/client/src/components/Chat/Messages/MinimalHoverButtons.tsx`（H5 端 footer icon 区）
  - 修改：`src/frontend/client/src/components/Chat/ChatView.tsx`（主聊天页 layout，挂载 `<MessageSelectionToolbar>` + `<AddToKnowledgeModal>`）
  **逻辑**:
  - 在 `HoverButtons.tsx` / `MinimalHoverButtons.tsx` 的 footer icon 行追加「导出」icon（lucide-react `Download` 图标），点击调 `enterSelectionMode(currentMessageId)`。
  - **可见性条件**：完全复用现有「复制」icon 的可见性条件（grep `复制` / `Copy` 看现有 condition 是哪个 prop / hook，用 `&&` 拼上即可）—— 不要单独写新的"流式判断"。
  - 在 `ChatView.tsx`（或等价的会话主 layout）底部 fixed 挂 `<MessageSelectionToolbar>`，仅在 `messageSelectionAtom.active === true` 时挂载。
  - 在 `ChatView.tsx` 同处挂 `<AddToKnowledgeModal dataSourceApi={listUploadableSpacesApi} ... onSyncSelect={handleImport}>`。
  - `handleImport({knowledgeSpaceId, folderId})` → 调 `importMessagesToKnowledgeApi` → toast「导入成功，文件正在解析中」+ 含知识空间链接。
  - `<MessageCheckbox>` 的接入：可能在 `MessagesView.tsx` / `MultiMessage.tsx` 或单条 message 渲染组件中；具体接入点开发时确认（不超出本任务范围）。
  **覆盖 AC**: AC-01, AC-07, AC-14, AC-16
  **手动验证**:
  - 流式生成中的消息下面**没有** "导出" icon
  - 生成完成后 "导出" icon 出现
  - 点击 "导出" → 进入选择态 + 底部栏出现 + 该 answer 和对应 query 默认勾上
  - 在选择态下点「导入到知识空间」→ AddToKnowledgeModal 弹出，使用 `/uploadable` 数据源
  **依赖**: T018a, T018b

- [ ] **T020**: i18n 三语补齐 + 关键文案错误码映射
  **文件**:
  - 修改：`src/frontend/client/src/locales/zh-Hans/translation.json`（按 client 端单文件多 key 结构）
  - 修改：`src/frontend/client/src/locales/en-US/translation.json`
  - 修改：`src/frontend/client/src/locales/ja/translation.json`
  **逻辑**:
  - 追加 spec §8.1 列出的 14 个 key，三语全量。
  - 在调用 `exportMessagesApi` / `importMessagesToKnowledgeApi` 的失败分支，根据后端返的 `code`（12061-12069）映射到对应 i18n key，统一走 `showToast({ severity: 'error', message: localize(...) })`。
  **覆盖 AC**: AC-08, AC-19-23, AC-30
  **手动验证**:
  - 切换中 / 英 / 日 三种语言，触发权限不足 / 配额超限 / 文件生成失败三种错误，toast 文案均正确
  **依赖**: T019

- [ ] **T021**: 选择态视觉细节 + 边界场景手动巡检
  **文件**: 无新增；在 T019 基础上微调样式 / 行为
  **逻辑**:
  - 流式态：「导出」icon 不出现 → 同步验证
  - 切换会话 → 选择态自动退出
  - 刷新页面 → 选择态不持久化
  - 「全选以下消息」横条悬浮位置正确
  - 多 answer 联选：勾任一 answer 自动联动同 query 下所有 answer + 该 query
  - 上滑加载更多 + 已开「全选」→ 新加载的消息自动勾上（AC-04）
  - 文件下载文件名展示正确（包含中文 + 时间戳 + 扩展名）
  **覆盖 AC**: AC-03, AC-04, AC-05, AC-06, AC-07, spec §3 切换 / 刷新边界
  **手动验证**: 按 AC 表逐项过；遗漏的视觉问题落档「实际偏差记录」
  **依赖**: T019, T020

### 阶段 6：集成验证

- [ ] **T022**: /e2e-test 跑通全部 AC
  **文件**: 由 `/e2e-test 028-conversation-export-import` 自动生成 + `src/backend/test/e2e/test_conversation_export_e2e.py`（路径以 e2e-test skill 实际产出为准）
  **逻辑**:
  - 跑通全部 31 条 AC，重点：
    - AC-02 4 种格式同步生成 + 文件下载
    - AC-08 / AC-19 / AC-25 / AC-26 边界
    - AC-18 / AC-24 导入入队成功 + 异步解析
  - 后端 API 端到端测试 + 前端手动验证清单（spec.md §2 全量映射）
  - 配额 / 敏感内容 / 权限三类校验走真实 PermissionService + KnowledgeSpaceService 链路（不走 mock）
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31
  **依赖**: T015, T021

---

## 实际偏差记录

> 完成后，在此记录实现与 spec.md 的偏差，供后续参考。

### §T001 Docker 依赖盘点结果（2026-05-31）

**静态结论（仓内代码勘察）**：

| 组件 | 来源 | 状态 |
|---|---|---|
| `pandoc 3.6.4` | `src/backend/base.Dockerfile:22-27`（wget 解压到 /usr/bin/） | ✅ 已装 |
| `libreoffice` | `src/backend/base.Dockerfile:12`（apt install） | ✅ 已装 |
| `fonts-wqy-zenhei` (文泉驿正黑) | `src/backend/base.Dockerfile:13`（apt install） | ✅ 已装 |

**Dockerfile 是否需要改动**：不需要。三件套全部在 base.v8 镜像里。`pypandoc>=1.15` 在 pyproject.toml 也已声明。

**待容器内验证**：smoke test 脚本 `scripts/check_export_dependencies.sh` 已落仓。需要在镜像里跑一次端到端 md → docx → pdf：

```bash
docker exec -it bisheng-backend bash scripts/check_export_dependencies.sh
```

期望输出 `=== ALL CHECKS PASSED — F028 export toolchain is ready ===`。任何 `[FAIL]` 行需要补镜像层（pandoc / soffice / 中文字体）。

**字体能力补注**：`fonts-wqy-zenhei` 是中文黑体替代品，覆盖常规简繁汉字 + ASCII。PRD 写「微软雅黑或系统中文字体」—— wqy-zenhei 属于「系统中文字体」类别，视觉风格接近但不完全等同微软雅黑。本期接受这一替代；若 UX 后期要求精准雅黑风格，可考虑补 `fonts-noto-cjk`（apt 包，约 50MB），作为 nice-to-have。

### §T002 RAG 角标真实样本（2026-05-31）

**存储格式（与 spec 假设有偏差）**：bisheng 用**私有 Unicode 字符**包裹角标，不是 `[1]` / `<sup>` 之类的 Markdown / HTML：

```
 <citation_id>:<item_id>[<更多 ref>]* 
```

三个 marker 定义在：

- 后端：`src/backend/bisheng/citation/domain/services/citation_prompt_helper.py:18-22`
  - `CITATION_START_MARKER = ''`
  - `CITATION_SEPARATOR_MARKER = ''`
  - `CITATION_END_MARKER = ''`
  - 已有正则：`CITATION_KEY_PATTERN = re.compile(rf'{CITATION_START_MARKER}(.*?){CITATION_END_MARKER}', re.DOTALL)`
- 前端：`src/frontend/client/src/components/Chat/Messages/Content/citationUtils.ts:37-39`
  - 同字符常量，并有 `stripCitationMarkers()` / `normalizeCitationMarkers()` 现成函数

**生成位置**：`bisheng/citation/domain/services/citation_prompt_helper.py:108-136`（`annotate_rag_documents_with_citations` 注入到 LLM prompt），由 RAG 节点 `bisheng/workflow/nodes/rag/rag.py:95-96` 调用；持久化在 `chat_service.py:1617-1626`。

**两种 category 的差异**：

| Category | 角标位置 | 取数策略 |
|---|---|---|
| `answer`（legacy） | 直接嵌在纯文本 message 里 | 整段过一次正则即可 |
| `agent_answer`（现代） | 嵌在 JSON `{msg: "...", events: [...]}` 的 `msg` 字段里；events 内的 tool_call / thinking 我们本来就不导出（AC-15） | 先 `json.loads()` 取 msg，再过正则 |

**spec.md AC-14 用语偏差**：spec AC-14 写「`[1]`、`[2]`、`<sup>` 等所有现有形式被完全剥除」—— 实际不存在 `[1]` / `<sup>` 形式，仅一种私有 Unicode 形态。语义不影响（"剥除一切现有形式"成立），不回改 spec。

**最终 `_strip_citation_marks` 实现策略**（写到 T010 时按此实现，不必再多正则集合）：

```python
import re

_CITATION_PATTERN = re.compile(r'[\s\S]*?')

def _strip_citation_marks(text: str) -> str:
    if not text:
        return text
    # 剥配对的 start..end；附带处理流式截断遗留的孤立 /
    text = _CITATION_PATTERN.sub('', text)
    text = text.translate({0xe200: None, 0xe201: None, 0xe202: None})
    return text
```

**复用建议**：直接在 `bisheng/citation/domain/services/citation_prompt_helper.py` 里追加 `strip_citation_markers(text: str) -> str`（与前端 `stripCitationMarkers` 同名同语义），让 F028 的 service 从 citation 模块 import，而不是把正则散落在 workstation 内。

**对 T007 测试用例的影响**：T007 的 `test_build_turns_strip_citations` 测试样本就用私有 Unicode 字符构造（`"答案前ref1:1答案后"`），不必再依赖真实库快照。T002 已经把"真实形态"勘察清楚，可以直接合成测试 fixture。

### §T003 ChatMessageDao 现状（2026-05-31）

**ORM 与 DAO 位置**：

- `ChatMessage` ORM：`src/backend/bisheng/database/models/message.py:63`
- `ChatMessageDao` 类：同文件第 152 行
- `MessageSession` ORM：`src/backend/bisheng/database/models/session.py`（表名 `message_session`，第 50 行）

**关键字段**（与 spec 假设一致或微调）：

| 字段 | 类型 | 备注 |
|---|---|---|
| `ChatMessage.message` | `LargeText`（第 25 行） | category 不同格式不同（见下） |
| `ChatMessage.extra` | `LargeText`（第 26 行） | **裸字符串，不是 JsonType** —— 取 `parentMessageId` 时需 `json.loads(extra or "{}")` |
| `ChatMessage.category` | str | `question` / `answer` / `agent_answer` / `agent_tool_call` / `agent_thinking` |
| `ChatMessage.sender` | str | 日常模式取这个字段当模型名 |
| `MessageSession.flow_type` | int | 15=日常 / 5=助手 / 10=工作流（与 spec 一致） |
| `MessageSession.flow_name` | str | 应用会话取这个字段当应用名 |
| `MessageSession.name` | str | 会话标题（用于文件名） |
| `MessageSession.user_id` / `tenant_id` | int / str | 多租户事件自动注入 |

**message 字段三种格式**（按 category）：

| category | 格式 | 取最终文本的方法 |
|---|---|---|
| `question` | 纯文本 | 直接取 |
| `answer`（legacy） | 纯 Markdown 字符串 | 直接取 + 剥角标 |
| `agent_answer`（现代） | JSON `{"msg": "...", "events": [...]}` | `json.loads()` 后取 `msg` + 剥角标；events 丢弃（AC-15） |

写入路径参考（实现 T008 时回看）：

- `agent_answer` 写入：`chat_service.py:~528`
- query / legacy answer：`chat_service.py / chat_helpers.py:272-290`

**没有现成的批量 ID 查询方法**：

- 只有 `get_message_by_id` / `aget_message_by_id`（单条，第 340/345 行）
- 有 `get_latest_message_by_chat_ids` 但语义不同
- T008 必须**自己新增** `aget_messages_by_ids(message_ids, user_id, chat_id)` —— 这条加在 `ChatMessageDao` 上，签名建议：

  ```python
  @classmethod
  async def aget_messages_by_ids(
      cls,
      message_ids: list[int],
      user_id: int,
      chat_id: str,
  ) -> list[ChatMessage]:
      """按 ID 列表批量查，强制 user_id + chat_id 复合过滤防越权。"""
      stmt = select(ChatMessage).where(
          ChatMessage.id.in_(message_ids),
          ChatMessage.user_id == user_id,
          ChatMessage.chat_id == chat_id,
      ).order_by(ChatMessage.id.asc())
      ...
  ```

  顺便给 `MessageSession` 类似一个 `aget_by_chat_id(chat_id, user_id)`（如 DAO 没有同等能力），用于取 `name` / `flow_type` / `flow_name`。

**arch-guard 提醒**：endpoint 层不得 `import bisheng.database.models.*`（RULE-3 WARNING）。Service 层调 DAO 是允许的（DAO 就定义在 models 文件中，但 service → dao 是合法层级；endpoint → models 是越层）。本特性 service 直接 import `ChatMessageDao` / `MessageSessionDao` 是 OK 的。

**对 T008 任务的具体修订**：

- T008 文件清单从 1 个加到 2 个：`conversation_export_service.py` + `database/models/message.py`（追加 `aget_messages_by_ids`）+ `database/models/session.py`（如需追加 `aget_by_chat_id`）。这超出"任务 ≤ 2-3 文件"的软约束 1 个文件，可以接受（属于 DAO 增量、改动局部）。落档于此作记录。

### 后续偏差

- **偏差 N**: <实际开发中与 spec / tasks 不一致的地方 + 原因>

- **偏差 WF-1（2026-06-03）：工作流/助手会话导出答案为空**。
  - **现象**：工作流/助手会话导出，问题在、大模型答案整块空（测试反馈，repro chat `326fc42649812821399af6c777f1d040`）。
  - **根因**：F028 抽取逻辑按工作台 agent 格式（`answer` 纯文本 / `agent_answer` 的 `msg`+events）写死。实测工作流/助手答案落库 category 是 **`stream_msg`/`output_msg`**，文本在 JSON 的 `msg` 字段；QA 答案是 `{"content":...}`；工作流提问是 `is_bot=1` 的纯字符串。`_extract_answer_text` 对 `stream_msg` 返回空。
  - **改动**：`conversation_export_service.py:_extract_answer_text` 重写 —— 统一按"丢弃集（reasoning_answer/input/agent_thinking/agent_tool_call）→ 纯字符串 raw → `{"content"}` → `msg`+events" 处理，覆盖 stream_msg/output_msg/agent_answer/answer/QA 全部格式。
  - **验证**：测试机用 repro chat 实跑 `_extract_answer_text`，stream_msg 取到答案、input 丢弃、question 正常；热补丁 + 重启，health 200。
  - **落档**：design.md §5 #12 已加。

- **偏差 WF-2（2026-06-03）：工作流/助手"实时新会话导出整篇空"（缺提问 → 0 轮）**。
  - **现象**：刚聊完的工作流会话导出空。抓包 live 发 `message_ids:[430820,430821]`（两个答案，**缺提问 430819**）；刷新后发 `[430819,430820,430821]` 正常。
  - **根因**：工作流提问的前端实时 id 是 `'u-'+uuid`（`createSendMsg`），导出按 `parseInt` 转 int 时变 NaN 被过滤 → 只发答案。后端 `_build_turns` 按 `queries=[category==question]` 分组，无提问 → 0 轮 → 整篇空（孤儿答案在 `queries` 为空时被丢弃）。
  - **修复（后端兜底，方案B）**：`_load_and_validate_messages` 末尾新增 `_backfill_paired_questions`：选中答案若缺同组提问，按 chat_id 取该 chat 的 question 列表（复用 `ChatMessageDao.aget_messages_by_chat_id`，limit 500），为每条孤儿答案补回 id 最近的前置提问。chat 归属已校验，无 IDOR 风险；刷新后已带提问则 no-op。
  - **未修（症状3）**：工作流答案前端临时 id（`unique_id+output_key`，parseInt 截出开头数字如 `7`）在 `end` 未回传 message_id 时不回填真实 id → 12060。属前端 `useChatHelpers`/`skillMethod` 流式 id 回填，待前端构建修复。
  - **部署**：两处后端改动（WF-1 抽取 + WF-2 兜底）已热补丁到测试机 116（`.bak`/`.bak2` 备份在容器内），重启 health 200。持久化在本地分支。

- **偏差 WF-3（2026-06-03）：重复导入同一会话到知识空间，列表只剩一份、`(1)` 序号永不出现**。
  - **现象**：同一会话多次导入同空间，只看到一份；F028 的同名追加 `(1)` 没生效。
  - **根因（热补丁日志确认）**：平台 `KnowledgeService.process_one_file`（`knowledge_service.py:1259`）按 **内容 md5 / 文件名** 去重 —— 重导同一会话 markdown 一字不差 → md5 命中 → 把已存在文件标 `FAILED` 返回、**不新建**。F028 的 `_resolve_unique_filename`(`(N)`) 是文件名级，**绕不过内容 md5 去重**。日志显示第 2/3 次导入命中 `REUSE existing -> FAILED`，且全程无 `adelete_batch`（不是删除，是拒收不新增）。
  - **改动**：`process_one_file` 加 `skip_dedup` 参数，去重判定改 `if (content_repeat or name_repeat) and not skip_dedup`；`add_file` 加 `skip_dedup` 透传；F028 `_upload_and_add_file` 两处 add_file（含 retry）传 `skip_dedup=True`。F028 已保证文件名唯一，跳过平台去重安全。
  - **部署**：热补丁到测试机（涉及 `knowledge_service.py`/`knowledge_space_service.py`/`conversation_export_service.py`，`.ddbak` 备份在容器内），调试日志已撤（`.dbgbak` 还原），重启 health 200。持久化在本地分支。
  - **落档**：design.md §5 #13 已加。

- **偏差 WF-4（2026-06-03）：docx 导出图片不显示（txt/md 正常）**。
  - **现象**：工作流会话 docx 导出，答案里的图片不显示;txt/md 有图片链接内容。
  - **根因**：答案图片是 `/bisheng/knowledge/images/...` 根相对路径(前端 nginx 代理路径,后端无此代理)→ `_fetch_image_bytes` 旧逻辑当"不支持 scheme"丢弃；且 MinIO 返回 `application/octet-stream` → 扩展名猜成 `.bin` → pandoc 认不出图片嵌不进。txt/md 只输出链接文本,不抓图,故不受影响。
  - **改动**：`_fetch_image_bytes` 加 `minio_host` 参数,相对路径补 `get_minio_share_host()`(实测 `http://host:9000/bisheng/...` 直连可取 200);content-type 为泛型(`bin`)时用 URL 后缀兜底扩展名;`_preprocess_images` 先解析 host 传入;新增 `_resolve_minio_host`(best-effort)。
  - **部署**：热补丁到测试机(`.imgbak` 备份在容器内),重启 health 200。持久化在本地分支。
  - **落档**：design.md §5 #14 已加。

- **偏差 WF-5（2026-06-03）：docx/pdf 图片预处理函数是死代码，图片从未内嵌**。
  - **现象**：WF-4 修了图片抓取后 docx 仍无图。
  - **根因**：`_preprocess_images` 定义了但**全代码库无调用方**（dead code）——`_render_docx`(pandoc)和 `_render_pdf`(chromium)直接拿原始 markdown 渲染，相对路径图片渲不出。
  - **改动**：将 `_preprocess_images` 改写为 `_embed_images_as_data_uri`（下载图片→`data:` base64 内嵌，pandoc/chromium 均支持，免临时文件/`file://`/resource-path）；在导出 endpoint(`conversation_export.py`)渲染前对 **docx+pdf** 调用（md/txt 跳过）。
  - **验证**：容器内端到端跑 embed→`_render_docx`，docx 内出现 `word/media/rId20.jpg`（图片成功嵌入）。
  - **部署**：热补丁到测试机（`conversation_export_service.py` span 替换 + endpoint），重启 health 200。持久化在本地分支。WF-4 + WF-5 合起来才真正修好 docx 图片。
  - **落档**：design.md §5 #14（WF-4）+ 本条。

- **偏差 WF-6（2026-06-03）：导入到知识空间未校验单文件大小限制**。
  - **现象**：系统配置 `uploaded_files_maximum_size`（MB）只前端校验；F028 导入服务端生成文件绕过前端，后端 `add_file` 只查存储配额、不查单文件大小，导致超限文件也能导入。
  - **改动**：`import_messages_to_knowledge` 构建 markdown_bytes 后，读 `settings.aget_all_config()['env']['uploaded_files_maximum_size']`（MB→bytes）与文件大小比对，超限抛 `ConversationImportQuotaExceededError`(12068)，文案"导出文件大小超过上传限制（XMB）"。
  - **注意**：配置键路径是 `env.uploaded_files_maximum_size`（initdb_config.yaml，默认 50）；DB 配置有 ~100s Redis 缓存。
  - **部署**：热补丁到测试机，重启 health 200。持久化在本地分支。

- **偏差 PDF-1（2026-06-02）：PDF 渲染引擎 libreoffice → chromium/playwright**。
  - **现象**：实测真实数据下，libreoffice 解析 pandoc 生成的 docx 时表格 / 列表布局崩塌，排版不可用。
  - **改动**：pdf 路径从 `docx → libreoffice → pdf` 改为 `md → html → chromium(playwright) → pdf`，绕开 docx 中间产物；docx 路径不变（仍 pandoc + 模板）。
  - **依赖变化**：移除 pdf 路径对 libreoffice 的依赖；新增 `playwright` + chromium binary（镜像 `/root/.cache/ms-playwright/chromium-*`）+ `python-markdown`。
  - **连带新坑（已同步 design.md §5）**：① pandoc 默认要求 list 前空行，需加 `+lists_without_preceding_blankline`；② 部分来源把 PUA marker 字面化成 `` 6 字符串，strip 需兼容；③ 兜底 strip 的 `\s*` 不能吃换行，否则吃掉 ul 项分隔；④ WenQuanYi/Liberation 无 emoji 字形，docx 路径需预替换为 `●`。
  - **测试**：API + renderer 测试因 mock playwright 重写，单元/集成总数 94 → 80。
  - **落档**：design.md 决策 6 + §4.1/§4.3/§5/§6.2/§7/§8 已覆盖更新。

- **偏差 ID-1（2026-06-02）：导出请求携带前端临时 id，后端报 12060「消息不存在」**。
  - **现象**：测试环境（116）日志 `POST /chat/messages/export … 消息不存在或已删除: [9394]`、另一例 `[1, 71]`；DB 实测 id 段为 4022–430645，`9394` 不存在、`1/71` 远低于最小 id。用户复现：会话进行中导出 `message_ids:[430660]`（只发答案、漏提问 430659），刷新后再导出 `[430659, 430660]` 正确。
  - **根因**：实时会话中前端消息 id 是临时值，不是真实 DB 主键。导出按 `parseInt(messageId)` 取整 id：① daily 路径提问消息被 `useAiChat.onCreated` 用 `messageId: userMessageId` 钉死成临时 UUID（覆盖了 `created` 事件带回的真实 id）→ UUID 解析成 NaN 被丢 → 提问整轮丢失；② workflow 路径答案消息流 `end` 缺 `message_id` 时保留合成数字 id（`unique_id+output_key`）→ 发出去后端查无此 id → 12060。刷新后走历史接口才映射成真实 id，故"刷新后正确"。
  - **改动（仅 daily 路径）**：`src/frontend/client/src/hooks/useAiChat.ts` — `onCreated` 改为用 `created` 事件的真实 `messageId` 回填提问消息（不再覆盖回 UUID）；新增闭包变量 `realUserMessageId` 追踪提问真实 id，`onFinal` 按真实 id 匹配回提问消息。答案消息原本就在 `agent_answer/end` 回填真实 id，无需改。
  - **未修**：workflow/技能入口（appChat，`useChatHelpers`/`skillMethod`/`useWebsocket`）的合成数字 id 问题；流式关联逻辑更复杂，回归风险高，待单独处理。见 design.md §8 短板。
  - **落档**：design.md §5 #11 + §8 短板已更新。

- **补做 SELECT-BELOW-1（2026-06-02）：实现 spec AC-05「全选以下消息」悬浮按钮**（此前只建了组件外壳，从未接线）。
  - **交互（与产品确认）**：导出态下，一个 pill **常驻 sticky 在消息滚动区左上角**（左对齐底部全选卡片），pill 右侧一条虚线作选择范围校准线；点击时按**当前滚动位置**定位锚点（pill 正下方第一条消息），选中它及下方全部（上方滚走的不选 = 覆盖式）；锚点是答案时连带其上方关联问题。两个入口（daily + appChat）都生效。无图标。
  - **改动**：
    - `hooks/useMessageSelection.ts`：`selectAllBelow` 改覆盖式（清空旧 `selectedIds`）；`computeSelectedIds` 在锚点为答案时用 `buildPairGroup` 补回关联问题。
    - `components/Chat/MessageSelection/SelectAllBelowBanner.tsx`：重写为自包含 sticky pill + 校准线，接收 `scrollRef`，点击时查 `[data-message-id]` 找首个 `rect.top >= barBottom` 的消息为锚点。
    - `components/Chat/MessageSelection/MessageCheckbox.tsx`：checkbox 加 `data-message-id`（锚点定位锚）。
    - 接线：daily `components/Chat/AiChatMessages.tsx`（`isActiveForChat(conversationId)` 时渲染）；appChat `pages/appChat/ChatView.tsx` 传 `selectionActive` → `pages/appChat/ChatMessages.tsx` 渲染。
  - **锚点定位机制**：复用每条消息的选择 checkbox 上的 `data-message-id`，避免给两个入口的多分支消息行逐个加包裹。
  - **i18n**：复用既有 key `workstation.messageExport.selectAllBelow`（全选以下消息）。

---

## 关键复用清单（实现时回看）

| 复用对象 | 路径 | 用途 |
|---|---|---|
| ~~`libreoffice_converter._convert_file_extension`~~ | ~~docx → pdf~~ | **已废弃**：pdf 改走 chromium(playwright) md→html→pdf（见偏差 PDF-1） |
| `KnowledgeSpaceService.add_file` | `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:2659` | 导入到知识空间 |
| `KnowledgeSpaceFileDao.async_list_children` | `knowledge_space` 模块 DAO | 同名扫描 |
| `MinioManager` | `src/backend/bisheng/core/storage/minio/` | 拉内部图片 bytes |
| `PermissionService.check / list_resources` | `src/backend/bisheng/permission/domain/services/permission_service.py` | 权限校验 / 列可上传空间 |
| `AddToKnowledgeModal` | `src/frontend/client/src/pages/Subscription/Article/AddToKnowledgeModal.tsx` | 目标选择器 UI |
| `UserPayload` | `src/backend/bisheng/common/dependencies/user_deps.py` | 认证注入 |
| `BaseErrorCode` | `src/backend/bisheng/common/errcode/base.py` | 错误类基类 |
| `resp_200` | `src/backend/bisheng/common/schemas/api.py` | 统一成功响应 |

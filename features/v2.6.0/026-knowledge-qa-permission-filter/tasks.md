# Tasks: F026-knowledge-qa-permission-filter（知识空间 AI 问答 - 检索权限过滤）

**关联规格**: [spec.md](./spec.md)
**版本**: v2.6.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 经 `/sdd-review spec` 14 项检查 + 7 项修复 + citations/resolve 范围调整，2026-05-29 通过 |
| tasks.md | ✅ 已拆解 | 经 `/sdd-review tasks` 21 项检查，Round 1 修复 4 处 medium ISSUE（AC-21/22 覆盖、T003 dependencies.py、T010 拆分、AC 范围写法），Round 2 LGTM，2026-05-29 通过 |
| 实现 | ✅ 全部完成（代码） | 12 / 12 完成；E2E 报告模板待人工执行（[e2e-report.md](./e2e-report.md)）|

---

## 开发模式

**后端 Test-First（务实版）**：
- 理想流程：先写测试（红），再写实现（绿）
- 务实适配：项目测试基础已建好，新测试统一放在 `test/<module>/` 之下：
  - knowledge 相关 → `test/knowledge/`
  - workstation 相关 → `test/workstation/`（新建目录）
  - citation 相关 → `test/citation/`（新建目录）
- 复用 `conftest.py` 现有 fixtures（`mock_openfga`, `mock_redis`, `async_db_session`, `tenant_context` 等）；OpenFGA 通过 `mock_openfga` 桩；Milvus / ES 不在单元测试中真起，用 monkeypatch 替换 retriever 工具的最外层 `ainvoke` 返回固定 docs。

**前端 Test-Alongside（暂缓版）**：
- Platform 和 Client 前端当前无自动化测试框架；前端改动仅为 i18n key 增补 + 回归验证，以手动 / E2E 方式覆盖。

**自包含任务**：每个任务内联文件、逻辑、测试上下文，实现阶段不需要回读 spec.md。

---

## Tasks

### 基础设施（无测试配对）

- [x] **T001**: 配置常量 + release-contract 登记（commit `c2bf1e4ab`）
  **文件**:
  - `src/backend/bisheng/core/config/settings.py`（新增 `KnowledgeQAFilterConf` 配置块挂在 `Settings` 顶层为可选块）
  - `features/v2.6.0/release-contract.md`（① 表 1 追加 F026 行，标注"不引入新领域对象、仅读取/调用现有对象"；② 表 2 追加 INV-6 完整三列定义（spec §9 已给出）；③ 表 3 追加 F026 行，依赖列填 "—"；④ 变更历史登记本次新增）
  **逻辑**:
  - `KnowledgeQAFilterConf` 字段：`index_filter_threshold: int = 5000`、`retrieval_initial_multiplier: int = 3`、`retrieval_expansion_multiplier: int = 10`、`fine_grained_concurrency: int = 8`
  - 在 `Settings.knowledge_qa_filter_conf: Optional[KnowledgeQAFilterConf] = None` 字段中挂入；YAML 缺省时按默认值
  **测试**: 无（纯配置文件 + 文档）
  **覆盖 AC**: 间接支撑 AD-02 / AD-03 / AD-08（无 AC 直接断言）
  **依赖**: 无

### 后端 Domain Service — KnowledgeFileVisibilityService（Test-First 配对）

- [x] **T002**: KnowledgeFileVisibilityService 单元测试（commit `2f1bd6197`，12 tests，TDD red 阶段）
  **文件**: `src/backend/test/knowledge/test_knowledge_file_visibility_service.py`
  **逻辑**: 测试 3 个方法的全部分支，mock OpenFGA（`mock_openfga`）+ 用 `monkeypatch.setattr` 桩掉 `FineGrainedPermissionService.get_effective_permission_ids_async`：
  - `is_space_visible`：① 有 `view_space` → True；② 无 → False；③ admin 短路 → True
  - `build_index_prefilter`：① K=0 → strategy=empty（caller skip）；② K=10 → strategy=in，`milvus_expr="document_id in [..]"`、`es_filter` 含 `terms`；③ K=N-3（即 N-K=3 ≤ 5000）→ strategy=notin；④ K=10000 且 N-K=10000 → strategy=none；⑤ admin → strategy=none（不过滤）
  - `post_filter_visible_files`：① 给 30 个 file_id，10 个返回 view_file ∈ effective → 仅返回那 10 个；② admin → 返回全部输入；③ semaphore 限流不死锁（用 50 个并发 file_id 验证完成）
  **测试 → AC 映射**:
  - `test_is_space_visible_*` → AC-11
  - `test_build_index_prefilter_*` → AC-23 / AC-24 / AC-25（性能策略 / AD-02 三分支）
  - `test_post_filter_visible_files_*` → AC-02 / AC-06 / AC-16 / AC-17（双层过滤的结果层）
  - `test_retrieval_loop_cap_*`（在 T004/T006 中覆盖；本任务只验单个原语）
  **覆盖 AC**: AC-11, AC-23, AC-24, AC-25（部分）
  **基础设施**: `mock_openfga` 已在 conftest；`test/knowledge/` 目录已存在
  **依赖**: T001

- [x] **T003**: KnowledgeFileVisibilityService 实现 + FastAPI 依赖工厂（commit `98942f52c`，arch-guard 通过）
  **文件**:
  - `src/backend/bisheng/knowledge/domain/services/knowledge_file_visibility_service.py`（新建）
  - `src/backend/bisheng/knowledge/api/dependencies.py`（修改：新增 `get_knowledge_file_visibility_service(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user)) -> KnowledgeFileVisibilityService` 工厂函数，供 T005/T007/T009 endpoints 与下游 service 通过 Depends 拿实例）
  **逻辑**:
  - 构造函数注入 `request: Request, login_user: UserPayload`
  - `is_space_visible(space_id) -> bool`：non-throwing 版本，复用 `KnowledgeSpaceService._require_permission_id('knowledge_space', space_id, 'view_space')` 的判定逻辑，捕获 `SpacePermissionDeniedError` 返回 False
  - `build_index_prefilter(space_id, candidate_file_ids: Optional[List[int]]) -> IndexFilter`：
    1. `accessible_ids = await PermissionService.list_accessible_ids(user, 'can_read', 'knowledge_file', login_user)`（admin 返回 None → strategy=none）
    2. 拉 space 主版本 file_id 总数 N（一次 SQL count）
    3. 计算交集 K = `accessible_ids ∩ candidate (∩ space_files if candidate=None)`
    4. 按 AD-02 阈值选 strategy（`KnowledgeQAFilterConf.index_filter_threshold` 控制）；返回 `IndexFilter` dataclass：`{milvus_expr, es_filter, strategy, accessible_size}`
  - `post_filter_visible_files(space_id, file_ids: Set[int]) -> Set[int]`：
    1. admin → 返回输入集合（短路）
    2. 一次性 `_build_child_permission_context(space_id)` 拿 tuple_cache
    3. semaphore(`fine_grained_concurrency`=8) 并发跑 `FineGrainedPermissionService.get_effective_permission_ids_async` per file_id；保留 `view_file ∈ effective` 的 file_id
  **测试**: T002 全部通过
  **覆盖 AC**: AC-02, AC-06, AC-08, AC-11, AC-16, AC-17, AC-23, AC-24, AC-25
  **依赖**: T001, T002

### 后端 Domain Service — KnowledgeSpaceChatService 改造（Test-First 配对）

- [x] **T004**: chat_folder + chat_single_file + space_rag 集成测试（commit `f274a1fa0`，7 tests）
  **文件**: `src/backend/test/knowledge/test_knowledge_space_chat_service_visibility.py`（新建，与现有 `test_knowledge_space_chat_service_retrieve.py` 并列）
  **逻辑**: 使用 conftest 的 `async_db_session` + monkeypatch 桩掉 retriever 工具的 `KnowledgeRetrieverTool.ainvoke`，验证：
  - 整空间问答（folder_id=0）：① 无 view_space → 抛 `SpacePermissionDeniedError`（AC-01）；② 部分文件可见 → `source_documents` 仅含可见 file_id（AC-02）；③ 空可见集 → 空 `finally_docs` + 不报错（AC-03）；④ 模拟权限收回后第二轮调用走新权限（AC-04）
  - 文件夹问答：① 无 view_folder → AC-05；② 子树过滤正确（AC-06）；③ tag + 权限交集为空时空检索（AC-07）
  - 文件预览问答：① 无 view_file → AC-08；② 有 view_file → 沿用现状（AC-09）
  - 检索循环上限：模拟首轮 K×3 全部被精滤砍光、扩展一次到 K×10 拿到 N 条 → 验证最多 2 轮 Milvus 调用（AC-26）
  - 结构化日志：用 `caplog` 验证一次问答输出 `strategy=`, `accessible_ids_size=`, `prefilter_candidate_size=`, `retrieval_attempts=`, `post_filter_dropped_count=`（AC-27）
  **测试 → AC 映射**:
  - `test_chat_whole_space_no_view_space` → AC-01
  - `test_chat_whole_space_filtered_source_documents` → AC-02
  - `test_chat_whole_space_empty_visible_set` → AC-03
  - `test_chat_continue_uses_fresh_permissions` → AC-04
  - `test_chat_folder_no_view_folder` → AC-05
  - `test_chat_folder_subtree_filtered` → AC-06
  - `test_chat_folder_tag_intersection_empty` → AC-07
  - `test_chat_single_file_denied` → AC-08
  - `test_chat_single_file_passthrough` → AC-09
  - `test_retrieval_loop_cap_two_attempts` → AC-26
  - `test_permission_filter_structured_log` → AC-27
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-26, AC-27
  **依赖**: T003

- [x] **T005**: KnowledgeSpaceChatService 实现（commit `f274a1fa0`，`_retrieve_and_filter` + `_render_rag_response` + chat_folder 重接线）
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_chat_service.py`（修改）
  **逻辑**:
  - 拆分 `_build_folder_search_kwargs` → `_compute_candidate_file_ids(knowledge_id, folder_id, tags) -> Optional[List[int]]`（保留原 candidate 计算逻辑）
  - 新增 `_retrieve_with_post_filter(space, query, candidate, top_k, max_content) -> List[Document]`：按 spec §7.4 五步流程实现（调 `build_index_prefilter` → 首轮 ×3 → 抽 unique file_id → `post_filter_visible_files` → 截到 top_k → 不足则扩张到 ×10 一次 → 仍不足返回）；每轮结束写结构化日志（AC-27 字段）
  - `chat_folder`：替换原 `milvus_kwargs/es_kwargs` 构造为 `_retrieve_with_post_filter` 调用
  - `chat_single_file`：在 `space_rag` 之前增加防御性 `post_filter_visible_files({file_id})` 一次（已通过门禁的请求应必中；不中则记 WARN 并返回空，避免越权）
  - `space_rag`：将 `retriever_tool.ainvoke` 调用迁入 `_retrieve_with_post_filter`，移除原 retriever_tool 直接拼接逻辑（保留 prompt + LLM 调用）
  - 依赖注入：从 `request.app.state` 或 `KnowledgeFileVisibilityService` 工厂构造一次实例复用
  **测试**: T004 全部通过
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-26, AC-27
  **依赖**: T003, T004

### 后端 Domain Service — WorkStationService 改造（Test-First 配对）

- [x] **T006**: queryChunksFromDB 集成测试（commit `a924fab12`，8 tests）
  **文件**: `src/backend/test/workstation/test_query_chunks_visibility.py`（新建 `test/workstation/` 目录）
  **逻辑**: 用 `async_db_session` + monkeypatch 桩掉 `MultiRetriever` 与 `KnowledgeRetrieverTool.ainvoke`：
  - 单个 space_bucket KB 无 view_space → 该 KB 不进入 retriever 调用、不出现在 `kb_succeed`；INFO 日志含 `skipped_kb_id=X reason=no_view_space`（AC-11）
  - 单个 KB 有 view_space 但 0 view_file 文件 → Stage 2 / Stage 3 自然产出 0 docs、不进入 `finally_docs` / `kb_succeed`；日志含 `accessible_ids_size=0`（AC-12）
  - 多 KB 部分可见 → 每 KB 按可见集合过滤，跨 KB 合并按 `max_total_docs=100` 截断（AC-13）
  - `org_bucket`（构造一个 legacy `knowledge_library` ID）走老路径不被修改（AC-14）
  **测试 → AC 映射**:
  - `test_query_chunks_kb_no_view_space_skipped` → AC-11
  - `test_query_chunks_kb_no_visible_files_natural_skip` → AC-12
  - `test_query_chunks_multi_kb_partial_visibility` → AC-13
  - `test_query_chunks_org_bucket_untouched` → AC-14
  **覆盖 AC**: AC-11, AC-12, AC-13, AC-14
  **依赖**: T003

- [x] **T007**: WorkStationService.queryChunksFromDB 实现（commit `a924fab12`，Stage 1 + Stage 3）
  **文件**: `src/backend/bisheng/workstation/domain/services/workstation_service.py`（修改）
  **逻辑**: 按 spec §7.2b 表格逐项落地：
  - 进入循环前对 `space_bucket` 的每个 kb_id 调 `KnowledgeFileVisibilityService.is_space_visible(kb_id)`；不通过则 `continue` + INFO 日志（AC-11）
  - 构造 `MultiRetriever` 的 `search_kwargs` 注入 `build_index_prefilter(kb_id, None)` 的产物（与 chat_folder 路径一致）
  - `per_kb_tool.ainvoke` 返回后，对 `kb_docs` 调 `post_filter_visible_files(kb_id, unique_file_ids)`；过滤后空则不进入 `finally_docs` / 不计入 `kb_succeed`
  - 沿用 AD-03 检索循环上限（首轮 ×3 / 扩展 ×10），多 KB 间不互相补量
  - `org_bucket` 路径完全不改（不修改 legacy `knowledge_library` 那一支的代码）
  - `check_auth=False` 不动（与本特性正交）
  **测试**: T006 全部通过
  **覆盖 AC**: AC-11, AC-12, AC-13, AC-14
  **依赖**: T003, T006

### 后端 Domain Service — CitationResolveService 改造（Test-First 配对）

- [x] **T008**: CitationResolveService 单元测试（commit `d55bdfbb6`，9 tests）
  **文件**: `src/backend/test/citation/test_citation_resolve_visibility.py`（新建 `test/citation/` 目录）
  **逻辑**: 用 fixture 构造 `CitationRegistryItemSchema` 列表（混合 RAG + web 类型）+ monkeypatch `KnowledgeFileVisibilityService.post_filter_visible_files`：
  - 登录用户 + 所有 RAG citation 的 documentId 均通过精滤 → 所有 items 原样返回（含 URL/bbox）（AC-15）
  - 登录用户 + 部分 RAG citation documentId 不通过 → 响应 `items` 不含这些条目（含 web 类型不受影响）（AC-16）
  - 登录用户 + 所有 RAG citation 均不通过 → `items` 空数组（AC-17）
  - 单条 `resolve_citation` RAG 无权 → 抛 `NotFoundError`（AC-18）
  - 单条 `resolve_citation` web 类型 → 不走 `view_file` 精滤，正常返回（AC-19）
  - `login_user is None` → 跳过精滤，行为同改造前（AC-20）
  - admin → `post_filter_visible_files` 返回输入集合，不过滤（间接覆盖 admin 短路）
  **测试 → AC 映射**:
  - `test_resolve_all_visible` → AC-15
  - `test_resolve_partial_invisible_filtered_out` → AC-16
  - `test_resolve_all_invisible_empty_items` → AC-17
  - `test_resolve_single_rag_no_permission_raises_not_found` → AC-18
  - `test_resolve_web_citation_untouched` → AC-19
  - `test_resolve_anonymous_caller_preserves_legacy_behavior` → AC-20
  - `test_resolve_admin_skips_filter` → AC-15（admin 等同全可见）
  **覆盖 AC**: AC-15, AC-16, AC-17, AC-18, AC-19, AC-20
  **依赖**: T003

- [x] **T009**: CitationResolveService 实现（commit `d55bdfbb6`，删除 `_has_file_access`，新增 `_filter_visible_rag_items`；arch-guard RULE-8 VIOLATION 消除）
  **文件**:
  - `src/backend/bisheng/citation/domain/services/citation_resolve_service.py`（修改）
  - `src/backend/bisheng/citation/api/dependencies.py`（修改：构造时注入 `KnowledgeFileVisibilityService`）
  **逻辑**:
  - 删除 `_has_file_access` 静态方法（旧 RBAC `AccessType.KNOWLEDGE` 调用，arch-guard RULE-8 VIOLATION）
  - 删除对 `from bisheng.database.models.role_access import AccessType` 的导入
  - 新增 `_filter_visible_rag_items(items: List[CitationRegistryItemSchema], login_user: Optional[UserPayload]) -> List[CitationRegistryItemSchema]`：
    1. `login_user is None` → 直返（AC-20，匿名直通）
    2. 提取 RAG 类型 items 的 (knowledgeId, documentId) 对；按 knowledgeId 分组
    3. 对每个 knowledgeId 调 `KnowledgeFileVisibilityService.post_filter_visible_files(knowledgeId, file_ids)`
    4. 返回 items 中：① 非 RAG 类型直通（AC-19）；② RAG 且 documentId ∈ permitted 的
  - `resolve_citations`：先调 `_filter_visible_rag_items(items, login_user)` 过滤，再走原 `_enrich_item` 并发流程
  - `resolve_citation`（单条）：先精滤；不通过 → `raise NotFoundError()`（AC-18）；通过 → 走原 enrich 流程
  - `_enrich_rag_item` 内的 `has_access = login_user is None or ...` 整段删除（不再需要——精滤已经在上层完成，进入这里的 item 必然通过 view_file 或匿名）；URL/bbox 无条件填充
  **测试**: T008 全部通过
  **覆盖 AC**: AC-15, AC-16, AC-17, AC-18, AC-19, AC-20
  **依赖**: T003, T008

### 前端 Platform（手动验证）

- [x] **T010**: Platform i18n key 补齐 + "无可见内容" UI 联调（commit `83d346fab`，3 文件 zh/en/ja `qa.noVisibleContent`）
  **文件**:
  - `src/frontend/platform/public/locales/en-US/knowledge.json`
  - `src/frontend/platform/public/locales/zh-Hans/knowledge.json`
  - `src/frontend/platform/public/locales/ja/knowledge.json`
  **逻辑**: 仅当现状无对应"未找到相关内容"提示时新增 `knowledge.qa.noVisibleContent` 文案：
  - 中："未在你有权访问的内容中找到相关信息"
  - 英："No relevant content found in resources accessible to you"
  - 日："アクセス権限のあるリソースに該当する内容が見つかりませんでした"
  **覆盖 AC**: 间接支撑 AC-03 / AC-12 的 UX 表现（无 AC 直接断言）
  **手动验证**:
  - 打开 Platform 整空间问答页（http://localhost:3001/.../knowledge/space/{id}/chat）
  - 用对该空间全部文件均无 `view_file` 的测试账号触发问答
  - 切换 zh-Hans / en-US / ja 三语，确认文案显示且不出现 i18n key 字面量；不出现"已引用 0 篇"卡片
  **依赖**: T005

### 前端 Client（手动验证）

- [x] **T011**: Client i18n key 补齐 + 工作台联调（commit `83d346fab`，3 文件 `knowledge_qa_noVisibleContent`）
  **文件**:
  - `src/frontend/client/src/locales/en/translation.json`
  - `src/frontend/client/src/locales/zh-Hans/translation.json`
  - `src/frontend/client/src/locales/ja/translation.json`
  **逻辑**: 按 Client nested namespace 风格添加与 T010 同语义的 i18n key（推荐 `knowledge_qa.noVisibleContent`，具体命名遵循 `/i18n-localizer` skill 约定）；中/英/日三语文案与 T010 保持一致
  **覆盖 AC**: 间接支撑 AC-03 / AC-12 / AC-13 的工作台 UX 表现（无 AC 直接断言）
  **手动验证**:
  - 打开 Client 工作台（http://localhost:4001/workspace）
  - 选 3 个 KB 触发问答，验证三语文案在"全 KB 无可见文件"场景下正确显示
  **依赖**: T007

### E2E + 手动回归

- [x] **T012**: 全链路 E2E + 手动回归 + arch-guard 校验（代码侧：arch-guard 6 文件全部 rc=0；E2E 模板 [e2e-report.md](./e2e-report.md) 待人工执行 → 填回结果）
  **文件**: 无（验证型任务，仅产出 E2E 报告）
  **逻辑**:
  - **回归验证 KB 下拉框**（Platform + Client）：以 `view_space` 不全的测试账号登录，确认 `GET /api/v1/knowledge/space/{mine,managed,joined,department}` 仅返回有 `view_space` 的空间，前端 KB 选择器中无权空间不显示（覆盖 AC-10）
  - **整空间问答**：以对部分文件有 `view_file` 的账号触发问答，截图 `source_documents` 仅含可见 file_id 的 chunk（覆盖 AC-02 / AC-06）
  - **首页/工作台问答**：选 3 个 KB 其中 1 个无 view_space、1 个无任何可见 view_file、1 个有可见 file → 仅最后一个 KB 出现在回答 citation 列表（覆盖 AC-11 / AC-12 / AC-13）
  - **角标溯源**：构造一段历史会话，会话中引用 N 个文件；管理员收回测试账号对其中一半文件的 `view_file` 权限；测试账号重新打开会话，点击展开 citation 面板，确认无权文件 citation 整条不出现、其余可见 citation URL / 预览正常加载（覆盖 AC-15 / AC-16 / AC-17）
  - **单条 citation**：直接 `GET /api/v1/citations/{无权 citation_id}` 返回 `NotFoundError`（覆盖 AC-18）
  - **匿名调用**：通过 share link 公开访问触发 citation resolve，确认行为不变（覆盖 AC-20）
  - **实时失效**（关键场景，覆盖 AC-21 / AC-22）：
    1. 账号 A 对空间 S 内文件 F1 有 `view_file`，进行一次问答确认 F1 出现在 `source_documents`
    2. 管理员立刻调 `PermissionService.revoke`（通过权限管理后台 UI 或直接 SQL/REST 触发）
    3. 账号 A 在 10s 内追问 → 验证 F1 已不再出现（理想期望：`invalidate_user` 触发即时生效；最迟 10s 内必收敛）
    4. grep 后端日志确认 `accessible_ids_size` 在前后两轮间发生变化，证明 `list_accessible_ids` 已重新计算
  - **结构化日志**：grep 后端日志中 `permission_filter` 行，确认 `strategy`/`accessible_ids_size`/`prefilter_candidate_size`/`retrieval_attempts`/`post_filter_dropped_count` 字段齐全（覆盖 AC-27）
  - **性能 sanity**：单空间 5000+ 可见文件账号触发整空间问答，记录权限过滤耗时（warmup → ≤ 80ms；冷启动 ≤ 500ms）→ 录入 E2E 报告（覆盖 AC-23 / AC-24；10 万规模 AC-25 若环境不可达则在报告标注 "未验证 + 留待 staging 环境"）
  - **arch-guard 校验**：运行 `bash scripts/arch-guard.sh`，确认 `CitationResolveService` 的 RULE-8 VIOLATION 已消除
  **覆盖 AC**: AC-10, AC-21, AC-22, AC-23, AC-24, AC-25（条件性）, AC-27（端到端性能 / 可观测 / 实时失效）+ 全部其他 AC 的 UI 层串联验证
  **依赖**: T005, T007, T009, T010, T011

---

## 实际偏差记录

> 实现完成后，在此记录与 spec.md 的偏差，供后续参考。

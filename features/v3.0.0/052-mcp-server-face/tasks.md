# Tasks: MCP Server 工具面与统一检索门面（六类工具 + 文件级过滤门面 + `delegate` 入口拒绝）

**关联规格**: [spec.md](./spec.md)（47 条 AC，What 的唯一真相）· [design.md](./design.md)（How 的唯一真相，D1–D12 / 坑 1–18 / §4.2 契约）
**版本**: v3.0.0
**纵切**: 不在 [mvp-114-path.md](../mvp-114-path.md) §2 纵切上（表单问卷不需 MCP）；批次 A 顺序 F049 → **F052** → F051 → F053 → F050
**代码事实口径**: 本文所有 `文件:行号` 沿用 design.md（`3.0-vibe` HEAD `fe10f75ea`，2026-09-16 核实，并于同日 `/sdd-review design|tasks` 独立审查时逐条重 grep 订正；路径以 `src/backend/bisheng/` 为根，前端另注 `platform/` = `src/frontend/platform/src/`；`mcp` SDK 行号以**主检出**的 `/Users/lilu/Projects/bisheng/src/backend/.venv/lib/python3.11/site-packages/` 为准，worktree 里没有 `.venv`）。行号会漂移，符号名不会——落地前以符号名重定位。

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-08-17 定稿（47 AC，独立审查 17 条已修订；决议 1–12）；2026-08-28 AC-03 术语订正 |
| design.md | ✅ 已评审（全自动模式，★ 豁免） | 2026-09-16 初版 + 同日 `/sdd-review design` 独立审查就地修订（4 high / 6 medium / ~20 low，见 design 修订历史末行）；D1–D12 / 坑 1–23；接手时的第一入口 |
| tasks.md | ✅ 已拆解（2026-09-16，`/sdd-review tasks` 已过） | 本文；三条线（共享基础 / 门面 / MCP 面）+ 合流波；审查订正见文末「审查修订记录」 |
| 实现 | 🚧 代码面已齐，余 CI 中间件与 114（2026-09-16 合流波收尾） | **31 / 34 完成**（T205 为编号占位不计）。Line A（T001–T003 / T101–T103 / T105）与 Line B（T201–T212）全部落地；Wave C 的 T301a/T301/T304 落地，**两线合并后 T301a 的 10 条已实跑不再 skip**。**余三项**：T104 与 T302 的「样本播种后的集合相等」部分、T303（114 部署与手动验证，步骤已备在文末「114 验证记录」）。**前两项的阻塞点已从「播种 helper 不存在」变成「没有能跑的环境」**——wave 5 已写出 `test/e2e/helpers/retrieval_sample.py`（四种权限来源 + 未授权空间 + 服务账号/自然人双主体）与 `test/e2e/test_e2e_f052_retrieval_set_equality.py`（6 例，`@pytest.mark.e2e` + `F052_E2E=1` 默认跳过），跑起来需要 MySQL + Redis + OpenFGA + MinIO + Milvus/ES **外加在跑的 knowledge Celery worker**，逐条前提写在 T104 下；**未跑过，故两项都不勾**。T211 已结案为**不做**（前提随「延迟 import + `available()` 门控」消失）。|

---

## 开发模式

**三条线、文件不相交，可由两个 agent 并行**（design §4.3 模块表是文件归属的真相）：
- **Wave 0 · 共享基础**（T001–T003）：单一 owner 先落——错误码 263 段 + 三语、v2 handler 状态映射、门面契约 schema 文件。**两条线都依赖它，且它是两条线唯一共同触碰的文件集**；落完再分叉。
- **Line A · 统一检索门面**（T101–T105，owner「facade agent」）：只碰 `knowledge/domain/services/{retrieval_engine,retrieval_facade_service,knowledge_space_chat_service}.py`、`open_endpoints/api/endpoints/filelib.py`、`open_endpoints/domain/schemas/filelib.py`、`docs/api/filelib-retrieve.md`、`test/knowledge/test_retrieval_*.py`、`test/open_api/test_filelib_retrieve_facade.py`。
- **Line B · MCP Server**（T201–T212，owner「mcp agent」）：只碰 `open_api/mcp/**`、`open_api/api/{dependencies,middleware}.py`、`open_api/domain/scopes.py`、`main.py`、`dev_toolkit/api/endpoints/distribution.py`、`department/domain/services/org_directory_service.py`、`app_publish/domain/services/publish_status_service.py`、`app_runtime/domain/services/app_query_service.py`、`database/models/audit_log.py`、`platform/controllers/API/log.ts`、`platform/public/locales/*/bs.json`、`test/open_api/test_mcp_*.py`、`test/open_api/test_open_api_route_matrix.py`、`test/open_api/test_scope_issuability.py`、`test/open_api/test_scopes.py`。**Line B 内只有 T301（工具 ①②）依赖 Line A**；T301 之前 Line B 用 fake 门面（按 design §4.2 ③ 契约）自测。
- **Wave C · 合流**（T301–T305）：工具 ①②、注册表驱动矩阵与端到端、114 验证、对外文档与契约回写。

**后端 Test-First**：`a` 后缀 = 配对测试任务，物理排在实现任务前、先执行；`覆盖 AC` 逐条全写（禁 `AC-01~05` 范围写法）。基础设施任务（错误码 / schema / conftest / 注册表）无测试配对。单测放 `src/backend/test/open_api/` 与 `src/backend/test/knowledge/`（不放 `test/` 根），`asyncio_mode=auto`。本地无中间件（HARNESS.md）：集合相等 / fail-closed 端到端标 `@pytest.mark.e2e`，CI 中间件分组跑，本地默认跳过。跑法：`cd src/backend && env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy uv run pytest test/open_api test/knowledge -q -p no:cacheprovider`（清代理是必须的，否则缺 `socksio` 会整批误报；`| tail` 会吃掉退出码，直接读最后一行）。**在 worktree 里跑之前**：worktree 没有 `.venv`、也没有未跟踪的 `src/backend/bisheng/config.yaml`，先从主检出拷一份 `config.yaml` 进来（`src/backend/AGENTS.md:180`）。基线 = 主检出同选择跑一遍再 diff，**别用绝对失败数判回归**。

**前端**：本 Feature **无页面**。唯一前端改动 = 审计 action lockstep 三处（T204）；接入信息区界面归 F053 T046。

**自包含任务**：每个任务内联文件、逻辑、AC 覆盖；设计论证指向 design D-x / 坑 n，不复制。

**编号 ≠ 执行顺序**：Line A 与 Line B 并行；`依赖:` 是唯一顺序真相。

**跨 Feature 副作用登记**（release-contract 表 1 / 清单检查项 17）：
- **T001**（`docs/constitution.md` C5 登记表 + `features/v3.0.0/release-contract.md` 已分配模块编码表：新增 **263 = mcp_face**；同表 F052 行状态回写归 T305）
- **T002**（`open_api/api/exception_handlers.py:54-75 open_api_http_status` 加 `McpFaceError` 分支——只加分支、既有映射不动）
- **T101**（`knowledge_space_chat_service.py` 五个私有方法**搬出**到 `retrieval_engine.py`，`aretrieve_chunks` 改薄委托——平台内对话链行为不变，`test/knowledge` 既有用例是护栏；F029 / F030 owner 的检索链此后由引擎承载）
- **T103**（`open_endpoints/api/endpoints/filelib.py:687-735 retrieve_chunks` 改调门面；`RetrieveReq` / `RetrieveResp` 的**字段集**不改。**两处受控收紧，已在 design D6 定案，本任务负责落地与回写**：① **F066 `data_scope` 拒绝由 26044/403 折叠为 26321/404**——门面走批量判定，而批量检查对被窄化目标是「返回 False 不抛」（`permission_action_service.py:328-333`），且 AC-11 / AC-27 本就要求「存在但非我创建」与「不存在」同一响应；因此 **`test/open_api/test_data_scope_matrix.py:41` 的 `"raise"` 分类必须改成新增档 `"unreachable"`**，并补一条「窄化令牌检索非本人创建的库 → 404 / 26321 且与库不存在逐字相同」的断言；技能包文案 `open_api/skill_packs/knowledge-search/SKILL.md:85` 与 `references/api.md:78` 对 26044 的检索期指引同批订正。② **`RetrieveReq.max_content` 加 `le=60000`**（今天只有 `ge=1`、无上限；门面静默夹取会违反 spec §3「截断必须在响应中可见」而 `RetrieveResp` 没有承载字段））
- **T201**（`open_api/api/dependencies.py:64-163 open_api_access_context` 拆成 `admit_open_api_principal` + `open_api_execution_scope` 两段——**对外行为逐字不变**，`test/open_api` 全部 40 个测试文件是护栏；注意拆分会动到「租户 ContextVar 装配（`:76-80`）」与「PAT 租户策略读（`:86-98`）」的相对顺序，见 design D2 的风险段）
- **T203**（`main.py` 条件追加 Starlette `Route("/api/v2/mcp", …)`（**不是 `app.mount`**，design D1）+ lifespan 进 `session_manager.run()`；`open_api/api/middleware.py:22-27` 对 `/api/v2/mcp` 前缀短路；`test_open_api_route_matrix.py:36-41` 的 `test_every_real_v2_route_is_globally_key_protected_and_marked` 改遍历方式——同文件 `actual_v2_routes() :25-34` **已经**做了 isinstance 过滤，不要动）
- **T204**（`database/models/audit_log.py:198 _UI_VISIBLE_V2_ACTIONS` + `platform/controllers/API/log.ts:153 V2_ACTIONS` + `platform/public/locales/{zh-Hans,en-US,ja}/bs.json` 键 `openApiMcpToolCall`——审计对象归 F056 查询面、写入归本 Feature）
- **T206**（F053 的 `dev_toolkit/api/endpoints/distribution.py:56 get_dev_toolkit_versions` 返回体加 `mcp` 段 + `"model": None` 槽位；F051 落地时填 `model`，**不要重排既有键**）
- **T207**（`open_api/domain/scopes.py:154 identity:read issuable=True`；beta2 F053 的三处钉住测试同步）
- **T208**（F055 `publish_status_service.py:74/181 get_publish_status / _require_viewer` 与 F054 `app_query_service.py:64/246 get_instance / _load_visible` 加 `entry` 形参，缺省 `"detail"` 行为不变）
- **T209 → F054 回写请求**：`AppDataService` 需 `insert_row / delete_row`（manager `POST /v1/apps/{id}/db/tables/{t}/rows`、`DELETE …/rows/{key}`）——登记到 F054 tasks「跨 Feature 回写受理」表；F054 T086/T087 落地前 T209 阻塞。**注意 T209 只读不写 F054 的代码**：`AppDataService` 的 owner-only 已无条件内建（`_require_owner`），本 Feature **不给它加 `entry`、也不在工具层重复判 owner**
- **T210 → F051**：依赖其 `resolve_callable_names` 导出（design D10）；F051 tasks 须把该函数列为 Outgoing 契约

---

## Tasks

### Wave 0 · 共享基础（单一 owner，无测试配对，两条线分叉前落完）

- [x] **T001**: 错误码 263 段 + 三语 + C5 / release-contract 登记
  **证据**: 71f525d42 — `common/errcode/mcp_face.py`（11 个码，全部 `Code: int`）+ 三语 `packages/locales/src/api_errors/*.json` + 生成物重跑 + C5 段位表 / 「263 is assigned」段 / release-contract 编码表；`test/open_api/test_mcp_face_error_codes.py`（4 条，含「模块 docstring 里的示例不得被 check-i18n 的正则当成真码」）。
  **偏差**: `test_error_codes.py` 未动（既有两条断言只扫 260 段的 `OpenApiAuthError` 子类，与 263 无交集），新断言独立成文件而不是塞进去。
  **文件**: `src/backend/bisheng/common/errcode/mcp_face.py`（新）, `src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`（三语视为一组）, `docs/constitution.md`（C5：`:128` 那行「26x–27x」段位表加 `263 mcp_face`；在 `:135`「**261 is assigned**」段之后补一条「**263 is assigned** …」写清子段与 HTTP 状态约定；文件头 `:9` 的 “Last revised / registry re-derived to 40 modules” 改成 41 并注明本次新增）, `features/v3.0.0/release-contract.md`（「已分配模块编码（MMMEE）」表，`:96-104` 那张表里 260 行之后加 263 行）, `src/backend/test/open_api/test_error_codes.py`（追加 263 段契约断言）
  **逻辑**: 按 design §4.2 ④ 定义 `McpFaceError(BaseErrorCode)`（`Code=26300`、`http_status: int = 400`，构造签名仿 `common/errcode/open_api.py:6-22 OpenApiAuthError`）与十个子类：`26301 McpUnknownToolError(404)` / `26302 McpToolScopeMissingError(403, __init__(required))` / `26303 McpIdentityHeaderRefusedError(403)` / `26304 McpToolArgumentInvalidError(400)` / `26305 McpAppNotOwnedError(403)` / `26306 McpIdentityNotFoundError(404)` / `26320 RetrievalIdentityMissingError(403)` / `26321 KnowledgeUnreachableError(404, __init__(unreachable_ids))` / `26322 KnowledgeCapabilityRevokedError(409, __init__(knowledge_id))` / `26323 RetrievalScopeTooLargeError(400)`。模块 docstring 仿 `app_factory.py:1-28`：子段 26300–26319 传输 / 工具面、26320–26339 门面（四调用方共用）、26340+ 保留；写明「不占 260 段」。每个子类**必须**写成 `Code: int = 263xx`（`check-i18n.mjs:106` 的 `/Code:\s*int\s*=\s*(\d+)/g` 只认这一形，坑 18——`open_api.py` 整份用的是不带注解的 `Code = 26001`，别照抄它）。三语：每码 `"<code>"` 主文案（**只放主文案**，`next_step` 归 T202 后端表——design D4）；`test_error_codes.py` 新增 `test_mcp_face_codes_are_in_263_band_and_have_three_language_copy`（读三文件，断言 `mcp_face.py` 每个 `Code` 都在 26300–26339 且三文件都有该键）。**该文件既有的两条断言不会被误伤**：`test_only_designated_open_api_error_codes_are_implemented :39-46` 只扫 `bisheng.common.errcode.open_api` 模块里 `OpenApiAuthError` 的子类，`test_reserved_and_removed_codes_are_not_reused :49-52` 只检查 260 段的保留洞——新模块是独立文件、独立基类，与两者无交集；新增断言写成第三个函数即可，**不要**去扩 `EXPECTED_CODES`。
  **依赖**: 无
  **落地**: `64cc2c386` — `common/errcode/mcp_face.py` 十个码（子类一律 `Code: int = 263xx`）+ 三语文案 + C5 / release-contract 登记；`test_error_codes.py::test_mcp_face_codes_are_in_263_band_and_have_three_language_copy` 同时钉死波段、注解写法与三语齐全。

- [x] **T002**: v2 exception handler 对 `McpFaceError` 的真实 HTTP 状态映射
  **证据**: 71f525d42 — `exception_handlers.open_api_http_status` 在 `OpenApiAuthError` 分支后加 `McpFaceError` 分支；`test/open_api/test_http_status.py` 新增一条参数化用例（26320/403、26321/404、26322/409、26323/400 在 `/api/v2` 为真实状态，`/api/v1` 仍 200 信封）。
  **文件**: `src/backend/bisheng/open_api/api/exception_handlers.py`（`open_api_http_status :45-75`）, `src/backend/test/open_api/test_http_status.py`（追加）
  **逻辑**: 在 `OpenApiAuthError` 分支之后加 `if issubclass(error_type, McpFaceError): return getattr(exc, "http_status", error_type.http_status)`；其余分支不动。测试：26321 → 404、26322 → 409、26320 → 403、26323 → 400 在 `/api/v2/**` 上为真 HTTP 状态；`/api/v1` 路径不受影响（仍 200 信封）。
  **依赖**: T001
  **落地**: `64cc2c386` — `exception_handlers.open_api_http_status` 加 `McpFaceError` 分支；`test_http_status.py` 两条新用例（26320→403 / 26321→404 / 26322→409 / 26323→400，且 `/api/v1` 仍 200 信封）。

- [x] **T003**: 门面契约 schema（Line A / Line B 共同依赖的**唯一**共享文件）
  **落地**: 由 Line A 建立；Line B 在 `tools/knowledge.py` 函数体内延迟 import 消费，注册表 `available()` 用 `importlib.util.find_spec` 判定——两侧合并后门面已在树上，工具 ①② 正常进清单。
  **文件**: `src/backend/bisheng/knowledge/domain/schemas/retrieval_facade.py`（新）
  **逻辑**: 按 design §4.2 ③ 逐字落：`RetrievalIdentity`（frozen dataclass，`actor: PermissionActor`、`login_user: UserPayload`；两个构造 classmethod——`from_open_api_principal(principal)`：S 模式 `subject_type=principal.authorization_subject_type, subject_id=principal.authorization_subject_id`，D 模式 `("user", effective_user_id)`；`login_user = UserPayload(user_id=principal.effective_user_id or principal.actor_id, user_name=principal.actor_name, user_role=[], tenant_id=principal.tenant_id, is_global_super=False)`（坑 8：不调 `init_login_user`）；`from_user(user_id, tenant_id, *, data_scope=DATA_SCOPE_ALL)` 经 `resolve_permission_actor` 解析管理员事实后构造 actor）· `RetrievalRequest` · `RetrievalChunk` · `RetrievalFacadeResult` · `AccessibleKnowledge` · `ReachabilityReport` · 五个常量。**只放数据结构与常量，不放逻辑**（Line B 的 fake 门面据此写）。`PermissionActor` import 走 `bisheng.permission.domain.services.permission_action_service`（与 `dependencies.py:50` 同一路径）。
  **依赖**: 无
  **落地**: `64cc2c386` — `knowledge/domain/schemas/retrieval_facade.py`。**偏差**：`from_user` 落成 `async`（管理员事实必须经 `resolve_permission_actor` 解析，不能由调用方猜），`from_open_api_principal` 保持同步；已回写 design §4.2 ③。

### Line A · 统一检索门面（Test-First 配对）

- [x] **T101a**: 引擎搬迁等价测试
  **文件**: `src/backend/test/knowledge/test_retrieval_engine_extraction.py`（新）
  **逻辑**: 用 monkeypatch 替换 `KnowledgeRetrieverTool`、`KnowledgeDao.aquery_by_id`、`KnowledgeFileVisibilityService.build_index_prefilter / post_filter_retrievable_files`、`KnowledgeFileDao.aget_file_by_ids` 为可控 fake，断言：`test_chat_service_aretrieve_chunks_delegates_to_engine`（同输入 → `KnowledgeSpaceChatService.aretrieve_chunks` 与 `RetrievalEngine.retrieve_many` 返回逐项相等，含 `document_update_time` 水合）→ AC-20；`test_engine_constructs_without_request`（`RetrievalEngine(login_user)` 不需 `Request`，可见性服务以 `request=None` 构造仍完成双层过滤——坑 4 守卫）→ AC-19；`test_space_path_keeps_two_layer_filter`（prefilter 与 post_filter 各被调用一次、被 post_filter 丢弃的 `document_id` 不出现）→ AC-20；`test_library_path_requires_use_then_filters_files`（`ensure_knowledge_use_async` 被调、失败即 `UnAuthorizedError` 上抛）→ AC-20；`test_permission_unavailable_propagates_unchanged`（fake 抛 `PermissionServiceUnavailableError` → 原样冒出、无结果）→ AC-24；`test_chat_service_empty_ids_still_400`（平台内路径的 400 行为不变，决议-9）。
  **覆盖 AC**: AC-19, AC-20, AC-24
  **依赖**: T003
  **落地**: `291b1e405` — `test/knowledge/test_retrieval_engine_extraction.py` 14 例全绿。

- [x] **T101**: `RetrievalEngine` 搬出 + 聊天服务薄委托
  **文件**: `src/backend/bisheng/knowledge/domain/services/retrieval_engine.py`（新）, `src/backend/bisheng/knowledge/domain/services/knowledge_space_chat_service.py`（`aretrieve_chunks :726-770` 改委托；删除 `_attach_document_update_time :788` / `_aretrieve_chunks_for_kb :809` / `_aretrieve_chunks_dispatch :836` / `_aretrieve_chunks_for_knowledge_base :869` / `_resolve_kb_file_ids_by_tags :907`；`_retrieve_and_filter :393` 与 `_resolve_kb_target_file_ids :695` 若仍被对话链其它方法调用则**保留并改为委托引擎同名方法**，不复制）
  **逻辑**: design D5-B。`RetrievalEngine(login_user: UserPayload, *, version_repo=None)`：`retrieve_many(targets: list[Knowledge], *, query, tag_filters, max_content) -> list[tuple[int, Document]]`（`asyncio.gather` 逐库；接收**已加载的 Knowledge 行**而非 id——可及性由门面预判，引擎不再 `aquery_by_id`/抛 `NotFoundError`）、`retrieve_space(space, ...)`、`retrieve_library(kb, ...)`、`attach_document_update_time(results)`；内部 `KnowledgeFileVisibilityService(request=None, login_user)` + `svc.version_repo = version_repo`；`permission_filter | …` 结构化日志随方法搬入。`KnowledgeSpaceChatService.aretrieve_chunks` 保持签名与 400 / 10962 / 404 行为：先自行 `aquery_by_id` 逐个加载与类型分派（原 `_aretrieve_chunks_dispatch` 的判断留在聊天服务这一层，只把「取 docs」交给引擎），再 `flattened[:top_k]`。
  **测试**: T101a 全部通过；`test/knowledge` 既有用例（`grep -l aretrieve_chunks test/`）全绿。
  **覆盖 AC**: AC-19, AC-20, AC-24
  **依赖**: T101a
  **落地**: `291b1e405` — `retrieval_engine.py` 新建，聊天服务 946→752 行。**偏差**：`_aretrieve_chunks_dispatch` 未整体删除，而是收窄成 `_aretrieve_chunks_for_one`（存在性 / 类型裁定 + 空间级闸留在聊天服务这一层，design D5 正文即如此要求，只是文件清单行写了「删除」）；`_retrieve_and_filter` / `_resolve_kb_target_file_ids` 中前者保留为委托（文件夹对话在用）、后者随引擎搬走。**三个既有测试文件同批改**：`test_knowledge_space_chat_service_retrieve.py` / `test_knowledge_space_chat_service_visibility.py` / `test_openapi_retrieve_file_visibility.py` 里直接戳私有方法的用例改为对引擎断言——方法搬走了断言跟着搬，行为断言本身未放松。

- [x] **T102a**: `RetrievalFacadeService` 单元测试
  **文件**: `src/backend/test/knowledge/test_retrieval_facade.py`（新）, `src/backend/test/knowledge/conftest.py`（新：`fake_engine`（记录 `retrieve_many` 调用、按 fixture 表返回 Document）、`fake_visibility`（monkeypatch `batch_check_business_actions` 返回按 `{resource_type: {id: actions}}` 查表）、`fake_visible_objects`（monkeypatch `runtime.list_visible_objects`）、`knowledge_rows`（monkeypatch `KnowledgeDao.aget_list_by_ids`）；**autouse 清代理 env**（`ALL_PROXY` 等六个，HARNESS.md 陷阱））
  **逻辑**: `test_identity_none_rejected_26320` / `test_identity_without_subject_rejected_26320`（不调引擎）→ AC-23；`test_explicit_targets_all_reachable_calls_engine_with_rows` → AC-22；`test_any_unreachable_target_fails_whole_request_26321_same_response`（参数化：不存在 / 存在未授予 / type=1 QA / type=2 个人 → 同一码 + `data.unreachable_ids` 只列不可及 id、**不带原因字段**）→ AC-11, AC-27；`test_no_targets_no_whitelist_uses_all_accessible`（`list_visible_objects` 两种资源类型各一次 → 过滤 type∈{0,3}）→ AC-22；`test_scope_larger_than_200_rejected_26323`（不静默截断）；`test_admin_actor_scans_tenant_but_personal_scope_does_not`（坑 7）；`test_whitelist_intersects_visible_silently_when_not_targeted`（白名单内不可见库不出现、不报错）→ AC-21；`test_whitelist_outside_target_is_unreachable`（执行身份本人可见、且是租户管理员 actor，仍 26321）→ AC-21；`test_whitelist_entry_deleted_raises_26322_and_no_engine_call`（含 `data.knowledge_id`；显式指定同库且**无白名单**时 → 26321）→ AC-46；`test_top_k_and_max_content_clamped_visibly`（`truncated_params` 含被夹字段）；`test_permission_unavailable_never_returns_partial`（引擎中途抛 19002 → 异常冒出、无结果对象）→ AC-24；`test_chunks_carry_knowledge_name_and_type` → AC-19；`test_list_accessible_knowledge_excludes_unsupported_types`（QA / 个人库不出现；返回 `AccessibleKnowledge`）→ AC-27；`test_check_reachable_report_three_buckets`；`test_facade_installs_actor_contextvar_and_resets`（坑 5：调用前后 `get_current_permission_actor()` 恢复原值）；`test_data_scope_personal_inherited`（actor `data_scope=personal_only` 透传到 `batch_check_business_actions` 的 actor 解析——断言 fake 收到的 actor.data_scope）。
  **覆盖 AC**: AC-11, AC-19, AC-21, AC-22, AC-23, AC-24, AC-27, AC-46
  **依赖**: T001, T003, T101
  **落地**: `e82561fc5` — `test/knowledge/test_retrieval_facade.py` 33 例 + `test/knowledge/conftest.py` 四个可编程 fake。

- [x] **T102**: `RetrievalFacadeService` 实现
  **文件**: `src/backend/bisheng/knowledge/domain/services/retrieval_facade_service.py`（新）
  **逻辑**: design D5。`retrieve(identity, req)`：① `identity is None or identity.actor is None or not identity.actor.subject_id` → 26320；② `top_k = min(req.top_k, RETRIEVAL_TOP_K_MAX)`、`max_content = min(…)`，被夹的记入 `truncated_params`；③ 范围解析：`targets = req.knowledge_ids`；若 `req.whitelist is not None`：`whitelist == []` → 全部目标不可及（有目标 → 26321(targets)；无目标 → 空结果 `effective_scope=[]`，不报错——app 声明为空是 F055 的预检问题）；有目标 → `∉ whitelist` 的进 unreachable；无目标 → `targets = whitelist`；若 `whitelist is None and not targets` → `list_accessible_knowledge` 全集（> `RETRIEVAL_SCOPE_MAX` → 26323）；`len(targets) > RETRIEVAL_TARGETS_MAX` → 26323；④ `rows = KnowledgeDao.aget_list_by_ids(targets)`：白名单条目缺行 / `type ∉ SUPPORTED` → **26322**（取第一条，`data.knowledge_id`）；非白名单缺行 / 类型不支持 → unreachable；⑤ `token = set_current_permission_actor(identity.actor)` 后一次 `batch_check_business_actions(identity.login_user, resource_type="knowledge_space", ids, actions=("visible",))` + 一次 `resource_type="knowledge_library"（以 F048 registry 名为准）, actions=("use",)`；显式目标不可见 → unreachable；白名单（未显式）不可见 → 剔除；`unreachable` 非空 → 26321；⑥ `RetrievalEngine(identity.login_user).retrieve_many(可及 rows, ...)` → `[:top_k]` → `attach_document_update_time` → 组 `RetrievalChunk`（`knowledge_name / knowledge_type` 取自 rows）；`finally reset_current_permission_actor(token)`。异常一律不捕获权限族（19002 / 19201 / `PermissionCheckFailedError` 等原样上抛）。`list_accessible_knowledge(identity, *, name=None, limit=200)`：actor 管理员且 `data_scope == ALL` → 租户内 `Knowledge` 扫描（type∈{0,3}、`delete==0`；自动租户过滤）；否则 `runtime.list_visible_objects(actor, resource_type=…, max_results=RETRIEVAL_SCOPE_MAX)` 两类型 → `aget_list_by_ids` → 类型过滤 → `batch_check_business_actions` 二次确认（`visible` 是超集）；`name` 子串过滤在内存做。`check_reachable(identity, knowledge_ids, *, whitelist=None) -> ReachabilityReport`（复用 ③④⑤，不调引擎；F055 T060 预检用）。`is_supported_knowledge_type(t)` 纯函数。**不创建会话、不写消息、不 import 任何 `chat_session` / `message` 模块**（AC-08 / AC-19；T104 用 `test_facade_imports_no_session_modules` 静态守卫）。
  **测试**: T102a 全部通过
  **覆盖 AC**: AC-11, AC-19, AC-21, AC-22, AC-23, AC-24, AC-27, AC-46
  **依赖**: T102a
  **落地**: `e82561fc5` — `retrieval_facade_service.py`。**偏差**：`retrieve` 的 `version_repo` 走关键字传参而非门面内部取依赖工厂（领域服务调 FastAPI 依赖工厂 = 反向依赖入口层，C1）；`check_reachable` 只评估 `knowledge_ids` 点名的目标、`whitelist` 仅用于判定是否属声明范围与条目是否消失（不遍历未点名的白名单条目）。两条均已回写 design §4.2 ③。

- [x] **T103a**: v2 `POST /filelib/retrieve` 收敛测试
  **文件**: `src/backend/test/open_api/test_filelib_retrieve_facade.py`（新）, `src/backend/test/open_api/test_data_scope_matrix.py`（改分类 + 补一条用例，见下）
  **逻辑**: HTTP 客户端用本目录的既有形态 `AsyncClient(transport=ASGITransport(app=app), base_url="http://test")`（`test/open_api/conftest.py` 里**没有** `v2_client` fixture；`test_data_scope_matrix.py:129` / `test_dependencies.py:93` 是现成范式），配合 monkeypatch `RetrievalFacadeService.retrieve` 为 spy：`test_endpoint_builds_identity_from_principal_mode_s`（`RetrievalIdentity.actor.subject_type == "service_account"`）→ AC-25；`test_endpoint_mode_d_identity_is_target_user`（模式 D principal → `("user", effective_user_id)`）→ AC-43（能力交付，验收归 F050）；`test_response_shape_unchanged`（`RetrieveResp{chunks[{content,knowledge_id,document_id,document_name,chunk_index,document_update_time}],total}` 字段集与 HEAD 快照相等）→ AC-25；`test_unreachable_maps_to_26321_http_404`（旧 404 `NotFoundError` / 403 `SpacePermissionDeniedError` / 10962 三态不再出现）→ AC-11；`test_permission_unavailable_is_503_with_19002_not_26030`（D6：删包装）→ AC-24, AC-44；`test_empty_knowledge_base_ids_still_400`（`min_length=1` 保留，契约不变）→ AC-25；`test_no_bypass_of_facade_in_open_face`（静态：`grep` `open_endpoints/` 与 `open_api/` 下不存在对 `aretrieve_chunks` / `RetrievalEngine` 的直接调用，只允许 `RetrievalFacadeService`）→ AC-26；`test_max_content_above_cap_is_422_not_silently_clamped`（传 `max_content=100000` → pydantic 422，**不是** 200 + 静默夹取）→ AC-25。
  **同批改 `test_data_scope_matrix.py`（design D6 受控收紧 ①）**：`KNOWLEDGE_READ_CLASSIFICATION` 里 `("POST", "/api/v2/filelib/retrieve")` 由 `"raise"` 改为新增档 `"unreachable"`，并在文件顶部的分类注释（`:33-37`）补一行说明该档语义；新增 `test_narrowed_token_retrieve_is_unreachable_not_26044`（窄化 PAT 检索非本人创建的库 → HTTP 404 / `status_code == 26321`，且响应体与「库不存在」逐字相等）→ AC-11, AC-25。**理由必须写进用例 docstring**：批量检查对被窄化目标返回 `False` 而非抛（`permission_action_service.py:328-333`），且 AC-27「存在性不泄露」不允许 26044 与 26321 可区分。
  **覆盖 AC**: AC-11, AC-24, AC-25, AC-26, AC-43, AC-44
  **依赖**: T002, T102
  **落地**: `610551615` — `test/open_api/test_filelib_retrieve_facade.py` 14 例；`test_data_scope_matrix.py` 分类改 `"unreachable"` + 新增 `test_narrowed_token_retrieve_is_unreachable_not_26044`（5 例全绿）。`test_openapi_retrieve_file_visibility.py::test_v2_adapter_maps_permission_outage_to_503_without_chunks` 同批改断言（26030 包装已删，改断 19002 / 503）。

- [x] **T103**: v2 端点改调门面 + 文档订正
  **文件**: `src/backend/bisheng/open_endpoints/api/endpoints/filelib.py`（`retrieve_chunks :689-735`）, `src/backend/bisheng/open_endpoints/domain/schemas/filelib.py`（`RetrieveReq.max_content :48-52` 加 `le=60000`，其余字段一律不改；`RetrieveChunk` 不改）, `docs/api/filelib-retrieve.md`（`:181-186` 错误表加 26321 / 26322 / 26323 行、删 404「知识库不存在」与 403「默认操作员」两行、把 26044 行改注「清单类端点仍返回，retrieve 上已折叠进 26321」；`:287` 「default operator 是否对该 KB 有 view 权限」→「统一检索门面按执行身份做可及性判定（知识空间 `visible`、文档库 `use`）+ 文件级双层过滤」；补一句 `max_content` 上限 60000）, `src/backend/bisheng/open_api/skill_packs/knowledge-search/SKILL.md`（`:85` 26044 指引）与 `.../references/api.md`（`:78` 同）
  **逻辑**: design D6。端点体：`principal = get_current_open_api_principal()` → `identity = RetrievalIdentity.from_open_api_principal(principal)` → `result = await RetrievalFacadeService.retrieve(identity, RetrievalRequest(query=req.query, knowledge_ids=req.knowledge_base_ids, tag_filters=<由 req.filters 转>, top_k=req.top_k, max_content=req.max_content))` → 映射为 `RetrieveResp`（`knowledge_name / knowledge_type` **不**加进 v2 响应，契约不变）。删除 `:722` 的 `OpenApiAuthDependencyUnavailableError` 包装与 `:703` 的 `KnowledgeSpaceChatService` 构造（连同 `:700-702` 那段「per-user view_file/view_space filtering in aretrieve_chunks」注释，改为指向门面）；`version_repo` 依赖改传给门面（`RetrievalRequest` 不带 repo——门面构造引擎时从 `get_knowledge_document_version_repository()` 取，或端点经 `RetrievalFacadeService.retrieve(..., version_repo=)` 关键字传入，二选一并在 §4.2 ③ 回写）。`tag_match_mode != "ANY"` 的 400 保留在端点层（原 `retrieve_chunks` 体内对 `req.filters` 的校验行为，符号定位）。
  **测试**: T103a 全部通过；`test/open_api/test_data_scope_matrix.py` 按 T103a 改完后全绿（**不是「原样仍绿」**——retrieve 的分类必须改，理由见 design D6 受控收紧 ①）
  **覆盖 AC**: AC-11, AC-24, AC-25, AC-26, AC-43, AC-44
  **依赖**: T103a
  **落地**: `610551615` — 端点改调门面、`RetrieveReq.max_content` 加 `le=60000`、`docs/api/filelib-retrieve.md` 错误表与 §7.1 口径订正、技能包 `SKILL.md` / `references/api.md` 补 26321/26322/26323 并改写 26044 指引。**额外删除**：`open_endpoints/api/dependencies.py` 的 `get_knowledge_space_chat_service_for_openapi`——端点改走门面后零调用方，属死代码（顺带解掉该文件对 `knowledge/api/` 的跨模块 import）。

- [ ] **T104**: 集合相等 + fail-closed 集成用例（CI 中间件分组）——**部分落地，未完成**（勾选留空：`[x]` 会让本条在「哪些还没做」的检索里消失，而 AC-40 / AC-42 / AC-44 的存储层断言确实还没有）
  **文件**: `src/backend/test/knowledge/test_retrieval_facade_equality.py`（新，`@pytest.mark.e2e`）
  **逻辑**: 真 MySQL + Redis + OpenFGA + Milvus/ES（CI）；建样本：服务账号 SA1 授 空间 S1（文件 f1 可见、f2 单文件收权、f3 在未授权文件夹、f4 切自定义模式脱钩）+ 文档库 L1；未授予 空间 S2；自然人 U1 同样授权。断言：`test_sa_equals_expected_set`（门面结果文件集 == {f1 的 chunks} ∪ L1；S2 指定 → 26321）→ AC-40；`test_v2_and_facade_direct_equal`（同 key 经 v2 端点与直调门面集合相等）→ AC-41；`test_user_with_whitelist_equals_platform_search_in_scope`（`from_user(U1)` + `whitelist=[S1]` == U1 平台内限定 S1 的 `aretrieve_chunks`）→ AC-42（F055 承接运行期验收）；`test_mode_d_identity_equals_user_self`（`from_open_api_principal(模式 D principal → U1)` == U1 自检）→ AC-43（F050 承接）；`test_fga_down_three_callers_error_zero_results`（`fga_down` fixture → 门面 / v2 / MCP 工具 ① 三处 19002、无 chunks）→ AC-44；`test_facade_imports_no_session_modules`（静态 import 图）→ AC-08, AC-19。**测试降级**：本地无中间件时 skip；114 手动步骤见 design §7 ③。
  **覆盖 AC**: AC-08, AC-19, AC-40, AC-41, AC-42, AC-43, AC-44
  **依赖**: T103, T301（MCP 工具 ① 那一分支可 `importorskip`）
  **执行位置**: 编号属 Line A，但因依赖 T301 而**在 Wave C 执行**（「编号 ≠ 执行顺序」；Line A 的 owner 在 T103 之后即可转去 T105，T104 与 T302 一起在合流波跑）。
  **部分落地**: `610551615` — `test/knowledge/test_retrieval_facade_equality.py` 10 例全绿，覆盖**能在无中间件下证的那一层**：AC-41 / AC-43 的身份构造缝（v2 端点不得自建 actor / UserPayload；模式 D = 被代表用户且不带任何提权）、AC-08 / AC-19 会话解耦（静态 import 图 + 签名里没有 `Request` 的位置）、坑 23 无缓存红线守卫。**刻意不写 skip / NotImplementedError 占位用例**（看起来像覆盖、实际什么也没证）。
  **再落地（`005e5f470`，合流波）**: 同文件加到 18 例，把另外两条原本被整体推给中间件、实际由请求路径决定的断言补上——
  ① **AC-41 行为层** `test_the_two_open_doors_hand_the_facade_the_very_same_call`：同一 principal 下 v2 端点与 MCP 工具 ① 递给门面的 `RetrievalIdentity` 与 `RetrievalRequest` 逐字相等（含 `whitelist is None`）。原先只有 AST 静态守卫，证不到「两边传的参数也一样」；
  ② **AC-44 逐门面同一次故障注入** `test_a_permission_outage_returns_an_error_and_zero_chunks_at_every_door`（参数化 facade / v2 / mcp / hosted_runtime）：`batch_check_business_actions` 抛 `PermissionServiceUnavailableError` 时四处都上抛、且检索引擎一次都没被调用。「少给几条」与「授权本来就窄」不可区分，正是这条 AC 要挡的形状。**参数取自 spec AC-44 点名的三个门面**（MCP 检索工具 / v2 `POST /filelib/retrieve` / **托管运行期**）**再加门面本身**——本任务原文第 129 行把「三处」写成「门面 / v2 / MCP」，漏掉了托管运行期；而托管运行期是唯一一个不直连门面、经 `CapabilityBusService.retrieve` 且**带 `except BaseErrorCode` 包裹**的调用方（它要给 AC-55 能力台账补一行），正是「顺手改成记一笔再返回已有结果」最可能被写进去的位置。已按 spec 补齐。
  **播种 helper 与用例体已落地（wave 5，`wt/f052-e2e-scaffold`）；任务仍不勾——它们一次都还没跑过**。
  - **新增** `src/backend/test/e2e/helpers/retrieval_sample.py`：`seed_retrieval_sample()` 异步上下文管理器，按前缀 `e2e-f052-retrieval-` 播种并在退出时全部清掉。播的正是本任务写的那份样本，四种权限来源**逐条可区分**（原文「单文件收权」与「自定义模式脱钩」两条容易写成同一件事，helper 里分成了两个位置不同的脱钩）：f1 空间根 INHERIT（可达）；f2 空间根切 CUSTOM（把继承来的授权单文件收回）；f3 在切了 CUSTOM 的文件夹 D1 下；f4 在仍 INHERIT 的文件夹 D2 下、**文件自身**切 CUSTOM（父路径全部放行、停在文件上，最易回归的一条）；文档库 L1 走 `knowledge_library` 的 `use` 授权。外加谁都没授的空间 S2。服务账号与自然人（PAT）**两个主体授权完全相同**，都从各自真实的管理入口授（服务账号只能走账号详情页的 `resource-grants:mutate`，通用资源选择器会拒）。脱钩后 helper 自己复核名册里不再有这两个主体，播错时报「播种失败」而不是让断言背锅。
  - **新增** `src/backend/test/e2e/test_e2e_f052_retrieval_set_equality.py`（`@pytest.mark.e2e` + `F052_E2E=1` 双层跳过）：`test_a_service_account_reads_exactly_the_files_it_was_granted`（AC-40 集合相等，多给少给分别报「过度披露 / 披露不足」并带文件来源）、`test_naming_an_ungranted_space_is_refused_rather_than_quietly_dropped`（AC-40 的 26321）、`test_the_mcp_tool_and_v2_return_the_same_chunks_for_the_same_key`（AC-41，按 `(document_id, chunk_index)` 比，不是只比文件集）、`test_a_personal_token_sees_exactly_what_the_platform_shows_that_person`（AC-42）、`test_a_revoked_key_stops_working_inside_the_revocation_bound`（AC-05，真 Redis 计时）、`test_with_the_permission_engine_stopped_every_door_errors_and_returns_nothing`（AC-44，见下）。
  - **跑起来还需要什么**（一条都不能省，缺哪条就写在跳过理由里）：① 一套**部署起来的** BiSheng——MySQL + Redis + OpenFGA + MinIO + Milvus/ES，**外加一个在跑的 knowledge Celery worker**；没有 worker 样本永远进不了索引，三条集合相等会以「两边都空」的方式假绿，所以 helper 在摄取超时时直接报错而不是继续；② `E2E_API_BASE`（必要时 `E2E_ADMIN_PASSWORD`）；③ `F052_E2E_OWNER_USER_ID`；④ `F052_E2E_USER_ID` / `F052_E2E_USER_NAME` / `F052_E2E_USER_PASSWORD`——**非超管、非租户管理员**的普通账号（管理员在 `_identity_shortcut` 处先于动作校验被放行，管理员跑绿等于没跑）；⑤ 部署级 PAT 开关可用（helper 读原值、用完原样写回）。
  - **AC-42 的偏差**：原文写「== U1 平台内限定 S1 的 `aretrieve_chunks`」。平台内那条路只经 SSE 会话且要真模型，把身份断言绑到一次模型调用上不合适。改为与 U1 用自己会话**递归浏览** S1 得到的文件集比对——同一个权限判定、同一个粒度（四种来源都作用在文件/文件夹上），f2 / f3 / f4 必须两边都不在。
  - **AC-44 分两次跑**：停掉 OpenFGA 就播不了种，所以停机那一条单独用 `F052_E2E_FGA_DOWN=1` 跑，样本 id 与密钥经 `F052_E2E_SEEDED_SPACE_ID` / `F052_E2E_SEEDED_KEY` 从上一次已播种的运行传进来。
  - **文件位置偏差**：本任务原文把文件写在 `test/knowledge/test_retrieval_facade_equality.py`。那份是**无中间件**的缝层守卫（18 例常跑），把默认跳过的中间件用例混进去会让「这份文件到底证了什么」读不出来；且仓内活体 E2E 的房子规矩就是 `test/e2e/` + `test/e2e/helpers/`。故落在 `test/e2e/`，并把原文件末尾那段「播种 helper 尚不存在」的注释改写成指路（指向新 helper 与新用例，逐条写明哪条 AC 在哪儿）。
  - **评审回合逐条核对了 helper 用到的每个接口形状**（`b68c12286`），改掉三处会让首跑必挂、且挂得不像真原因的写法：① `cleanup_prefixed` 原来用 `GET /knowledge?type=3` 列知识空间，而该 handler 对 `type=3` 直接抛 `KnowledgeSpaceListNotSupportedError`，播种第一步就死——改走 `GET /knowledge/space/mine`（空间都是这个管理员建的）；② f1–f4 原本字节完全相同，而上传去重是**同一知识库内 md5 或文件名命中即拒**（`KnowledgeFileDao.get_file_by_condition` 的 `or_`），四份里只有一份会真建出来，且被拒的那份**回的是它撞上的那个文件的行**，形状与建成功一模一样——现在每份多带一行槽位标记保证 md5 互不相同，并在 `accept_created` 里按 `status=FAILED` 与 id 重复直接判「播种失败」；③ 摄取轮询原来不带 `parent_id`，而 `/children` 只列**直接子级**（无 `parent_id` 时即 `file_level_path == ''` 的空间根），`file_ids` 是在此之上再收窄而非改写作用域，D1/D2 里的 f3/f4 永远等不到 SUCCESS，只会以「摄取超时」收场、读起来却像「没起 Celery worker」——改成按父目录分组轮询。另把名册复核从「只比 id」改成比 `(subject_type, id)` 对（服务账号与用户各自编号，撞号会误报泄漏），并把 fixture 的管理员前置核验从只看 `role == "admin"` 扩到 `/user/info` 的 `is_global_super` / `is_child_admin` / `is_department_admin`——租户管理员不是 `role=="admin"`，原判据放得过去。**这些都是静态核对 + 假传输层走通控制流的结果，仍然不等于真跑过。**

- [x] **T105**: 门面对外契约文档回写
  **文件**: `features/v3.0.0/052-mcp-server-face/design.md`（§4.2 ③ 按实现定稿：`version_repo` 传法、`from_user` 签名）, `features/v3.0.0/055-app-publish-pipeline/tasks.md`（T057 / T060 的「依赖」行改指本契约，一行）, `features/v3.0.0/057-bisheng-sdk/spec.md` 不改（AC-11 已引 F052 AC-19）
  **逻辑**: 只回写契约，不写论证。
  **依赖**: T103
  **落地**: `610551615` — design §4.2 ③ 按实现定稿（`from_user` 为 async、`version_repo` 关键字传参、`check_reachable` 口径、`knowledge_type_label`）；`055-app-publish-pipeline/tasks.md` 的 T057 / T060 各补一行「依赖」指向该契约并写明调用形态。`057-bisheng-sdk/spec.md` 未改（AC-11 已引 F052 AC-19）。

### Line B · MCP Server（Test-First 配对；T301 前用 fake 门面）

- [x] **T201a**: `dependencies.py` 拆分回归测试
  **文件**: `src/backend/test/open_api/test_dependencies.py`（追加）
  **逻辑**: `test_admit_returns_principal_and_pat_scope`（服务账号 → `(principal, DATA_SCOPE_ALL)`；PAT + 租户策略 personal → `(principal, "personal_only")`；PAT 未开 → `PersonalTokenDisabledError`）；`test_execution_scope_installs_and_resets_four_contextvars`（进入后 `get_current_tenant_id / visible_tenant_ids / get_current_open_api_principal / get_current_permission_actor` 四者正确、退出后恢复）；**`test_pat_policy_read_happens_with_tenant_contextvar_installed`**（design D2 的风险点：今天的顺序是 `:76-80` 先装租户 ContextVar、`:86-98` 再读 `TenantSettingService.get_policy`，拆分会把它们倒过来；monkeypatch `get_policy` 在被调用的瞬间断言 `get_current_tenant_id() == principal.tenant_id`，倒序即红）；`test_open_api_access_context_behaviour_unchanged`（沿用本文件既有用例集全绿即可，不新写）。
  **覆盖 AC**: AC-02, AC-03
  **依赖**: 无
  **证据**: 71f525d42 — `test/open_api/test_dependencies.py` 追加 6 条，含 `test_pat_policy_read_happens_with_tenant_contextvar_installed`（design D2 点名的唯一风险点： `get_policy` 虽显式收租户 id，其 DAO 仍在自动租户过滤之下，顺序颠倒只在真库上才炸）与 `test_execution_scope_without_prepare_never_resolves_delegation`（MCP 面不传 `prepare`， 身份头是拒绝而不是解析）。

- [x] **T201**: 拆分 `open_api_access_context`（行为不变）
  **文件**: `src/backend/bisheng/open_api/api/dependencies.py`（`:64-163`）
  **逻辑**: design D2。新增导出 `async def admit_open_api_principal(conn) -> tuple[OpenApiPrincipal, str]`（`:70-98` 内容：`validate_bearer` + PAT 策略；`OpenApiAuthError` 经 `_raise_for_connection`）与 `@asynccontextmanager async def open_api_execution_scope(conn, principal, *, data_scope)`（`:76-83` 的 tenant / visible / scope 写入 + `:129-153` 的 admin 事实与 `PermissionActor` + 四个 set，`finally` 四个 reset）。`open_api_access_context` 改为：`principal, data_scope = await admit_open_api_principal(conn)` → marker / delegate / scope / 身份头 / `resolve_request_identity` / 模式判定（`:100-127` 原样）→ `async with open_api_execution_scope(conn, principal, data_scope=data_scope) as p: yield p`。`__all__` 加两名。
  **测试**: T201a 通过；`test/open_api` 全部文件与主检出基线无新增失败
  **覆盖 AC**: AC-02, AC-03
  **依赖**: T201a
  **证据**: 71f525d42 — 拆出 `admit_open_api_principal` / `open_api_execution_scope` 并导出；`open_api_access_context` 组合二者，对外行为逐字不变（`test/open_api` 425 passed，与拆分前一致）。
  **偏差（与 design D2 相比更保守）**: `open_api_execution_scope` 多收一个可选 `prepare` 回调。原因是 `resolve_request_identity` 要在租户 ContextVar 已装、actor 未构造之间跑——它读库（`OwnerRepository`），而委托解析会改变 actor 是谁。把这段放在调用方会把顺序拆散，`prepare` 让「一处实现」继续成立；MCP 面不传它。

- [x] **T202**: 错误层 + 工具注册表（无测试配对，T203a 覆盖）
  **文件**: `src/backend/bisheng/open_api/mcp/__init__.py`（新）, `src/backend/bisheng/open_api/mcp/errors.py`（新）, `src/backend/bisheng/open_api/mcp/registry.py`（新）
  **逻辑**: `errors.py`：`class McpToolError(mcp.server.fastmcp.exceptions.ToolError)` 持 `code / category / reason / next_step / data`，`__str__` = `json.dumps({...}, ensure_ascii=False)`；`ERROR_CATEGORY_MAP`（design D4 列表）；`to_tool_error(exc: BaseException, *, lang) -> McpToolError`：`McpFaceError` / `OpenApiAuthError` / `BaseErrorCode` 按码查表，未映射 → `internal`（`reason=exc.Msg`、`next_step=NEXT_STEP_COPY[26300][lang]`「稍后重试或联系管理员」），**任何分支不把 `str(exc)` 原文放进 `reason`**（可能含路径 / SQL）；`next_step` 取自同文件 `NEXT_STEP_COPY: dict[int, dict[str, str]]`（design D4：后端自有三语表，键 = 错误码，值 = `{"zh-Hans", "en", "ja"}`；`lang` 由闸从 `Accept-Language` 解析后放 ContextVar，缺省 `zh-Hans`；**不**读 `packages/locales`——后端进程没有那份 JSON，坑 18）；`ERROR_CATEGORY_MAP` 与 `NEXT_STEP_COPY` 键集必须相等（T203a 断言）。`registry.py`：`@dataclass(frozen=True) McpToolSpec(name, category, scope, requires_app_runtime, handler, input_model, description, available: Callable[[], bool] = lambda: True)`；`TOOL_REGISTRY` 按 design D3 表（工具 ③ 的 `available` = F051 函数可导入；⑤ 的 `available` = `AppDataService` 可导入）；`visible_tools(principal) -> list[McpToolSpec]`（`spec.scope in principal.scopes ∧ (not requires_app_runtime ∨ settings.app_runtime.enabled) ∧ available()`）；`require_tool(principal, name)`：不在表或 `not available()` → 26301；缺位 → 26302(required)；`requires_app_runtime ∧ ¬enabled` → `AppPublishRuntimeLayerDisabledError`（16207，`common/errcode/app_publish.py:109`）。
  **依赖**: T001
  **证据**: 1b359102a — `open_api/mcp/{__init__,errors,registry}.py`。`ERROR_CATEGORY_MAP` 与 `NEXT_STEP_COPY` 键集相等（T203a 断言），`to_tool_error` 任何分支都不把 `str(exc)` 放进 `reason`。
  **偏差**: 映射表比 design D4 列的多四个码——16164 / 16165 / 16166 / 16167（表不存在 / 行不存在 /入参非法 / 库忙）。它们是「这个应用确实是你的」的真实业务态，和 16163 同理不能折进 26305，否则等于告诉开发者自己的应用不是自己的。

- [x] **T203a**: 闸 + 服务器 + 挂载 测试
  **文件**: `src/backend/test/open_api/test_mcp_server.py`（新）, `src/backend/test/open_api/conftest.py`（追加 `mcp_client` fixture：`httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")` → `mcp.client.streamable_http.streamable_http_client("http://testserver/api/v2/mcp", http_client=client)`（`mcp/client/streamable_http.py:601-604`，1.27.1 支持注入 `http_client`）→ `ClientSession(read, write)`；参数 `headers`；`open_platform_enabled` monkeypatch **必须在 app 构造前**——坑 13：conftest 用 `importlib.reload(bisheng.main)` 或直接构造 `McpAccessGate(StreamableHTTPASGIApp(server.session_manager))` 做单元级装配，二选一记录）
  **逻辑**: `test_no_credential_401_26001_and_no_tools`（`initialize` 即失败）→ AC-02；`test_invalid_revoked_expired_401_26002`（建号发钥仿 `test_credential_validator.py:18 seed_service_account` + `CredentialService` 签发；撤销后立即被拒；`fake_redis` 清键）→ AC-02, AC-05；`test_every_mapped_code_has_three_language_next_step`（`ERROR_CATEGORY_MAP` 键集 == `NEXT_STEP_COPY` 键集，且每项含 zh-Hans / en / ja 非空）→ AC-09；`test_accept_language_selects_next_step_default_zh`（`Accept-Language: en` → 英文；缺省 → 中文）→ AC-09；`test_query_param_token_rejected`（`?token=` / `?authorization=` 不认）→ AC-02；`test_delegate_key_403_26051_at_initialize_and_lists_nothing` → AC-28, AC-29；`test_identity_headers_403_26303`（参数化 `X-On-Behalf-Of` / `X-End-User` / `X-Foo-On-Behalf-Of` / `x-end-user`）→ AC-30；`test_delegate_key_never_falls_back_to_mode_s`（持 delegate + 无身份头 → 仍 26051，不是 26016）→ AC-29；`test_list_tools_filtered_by_scopes`（仅 `knowledge:read` → 恰两工具；PAT 主体同）→ AC-04；`test_empty_scopes_handshake_ok_tools_empty` → AC-04；`test_call_unlisted_tool_26302_names_scope`（仅 knowledge:read 调 `bisheng_org_tree` → `isError`、JSON `code=26302,data.required="identity:read"`，非「未知工具」）→ AC-04, AC-09；`test_unknown_tool_26301` → AC-09；`test_scope_edit_effective_next_call`（编辑权限位 → `invalidate_cache` → 下一次 `tools/list` 即新集合，同一客户端不重连）→ AC-06；`test_app_tools_hidden_when_runtime_disabled_and_direct_call_16207` → AC-17, AC-38；`test_route_absent_when_open_platform_disabled_404` → AC-37；`test_dns_rebinding_protection_disabled_real_host_accepted`（`Host: 192.168.106.114:4101`）→ 坑 1；**`test_bare_path_is_not_redirected`**（`POST /api/v2/mcp` 直接 200/JSON-RPC，**不得**是 307；用 `follow_redirects=False` 的裸 httpx 请求断言，这是 D1 用 `Route` 不用 `Mount` 的唯一可测证据，坑 12 的同源问题）→ AC-01；**`test_tool_error_text_is_parseable_json`**（任取一个被拒的工具调用，把 `content[0].text` 真的 `json.loads()` 一遍并断言含 `code/category/reason/next_step` 四键——只断言 `isError=True` 会漏掉 `Tool.run` 的前缀重包，坑 19）→ AC-09；**`test_successful_call_has_structured_content_and_no_output_validation_error`**（每个已注册工具各一次成功调用：`structuredContent` 非空、文本里不含 `Output validation error`，坑 20）→ AC-10, AC-12；`test_no_key_material_in_any_response`（所有响应体 / 错误体不含 `bs-sak-` / `bs-pat-`）→ AC-47；`test_no_session_or_message_dao_touched`（monkeypatch `MessageSessionDao` / `ChatMessageDao` 任一方法为 `raise`，全流程不触发）→ AC-08；`test_tenant_contextvar_installed_for_handler`（handler 内 `get_current_tenant_id()==密钥租户`、`visible=={1,tenant}`）→ AC-03。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-08, AC-09, AC-10, AC-12, AC-17, AC-28, AC-29, AC-30, AC-37, AC-38, AC-47
  **依赖**: T201, T202
  **证据**: 1b359102a + 后续 — `test/open_api/test_mcp_server.py` 30 条，全部经真 `ClientSession`；`conftest.py` 加 `mcp_http` / `mcp_session` 两个**同步工厂**夹具。
  **评审修订（2026-09-16）**: 补 `test_a_personal_token_holder_is_a_first_class_subject_on_this_face`。design K4 把自然人（PAT）与服务账号并列为模式 S 的两类主体，本任务原文也写了「PAT 主体同」，但全部用例用的都是 `actor_kind="service_account"` 的 principal——自然人那条路（`admit_open_api_principal` 读租户 PAT 策略 → `open_api_execution_scope` 解析管理员事实）在本面上一次都没跑过。新用例桩掉这三处远程读，断言 PAT 主体能握手、清单里绝不出现身份 / 应用两族、直调 `bisheng_org_tree` 得 26302。**AC-05「撤销 5 秒内生效」本地仍无用例**：全部用例都桩掉 `validate_bearer`；它成立的依据是 `test_scope_edit_takes_effect_on_the_next_call_without_reconnecting` 证明的「每次请求都重新过一遍 `validate_bearer`」＋该函数自身在 `test_credential_validator.py` 的既有覆盖，真正的端到端验收归 T302 / T303。
  **偏差（比 design D12 的写法关键）**: 夹具**不能**是 async generator fixture——`session_manager.run()` 开的是 anyio 任务组，任务组必须在开它的那个 task 里关闭，而 pytest-asyncio 在另一个 task 里做 teardown，直接报 `Attempted to exit cancel scope in a different task`。改成返回 async CM、由测试体自己 `async with`，两端就在同一个 task 里。每次调用新建一个 server 实例（`new_mcp_server()`），因为 `run()` 每实例只能进一次。

- [x] **T203**: `McpAccessGate` + `BishengMcpServer` + `main.py` 路由注册 / lifespan + 中间件短路 + 路由矩阵测试适配
  **文件**: `src/backend/bisheng/open_api/mcp/gate.py`（新）, `src/backend/bisheng/open_api/mcp/server.py`（新）, `src/backend/bisheng/main.py`（`create_app :159` 内 `if settings.open_platform.enabled: app.router.routes.append(build_mcp_route())`；`lifespan :104` 内同一开关下 `async with mcp_session_manager_run():`）, `src/backend/bisheng/open_api/api/middleware.py`（`:22-27` 加 `or path.startswith("/api/v2/mcp")` 短路）, `src/backend/test/open_api/test_open_api_route_matrix.py`（**只改** `test_every_real_v2_route_is_globally_key_protected_and_marked :36-41`，加 `isinstance(route, (APIRoute, APIWebSocketRoute))` 过滤；`actual_v2_routes :25-34` 已有该过滤、**不要动**；新增 `test_mcp_route_present_iff_open_platform_enabled`）
  **逻辑**: design D1 / D2 / D3。`server.py`：`class BishengMcpServer(FastMCP)`：`__init__` 传 `name="bisheng"`, `stateless_http=True`, `json_response=True`, `streamable_http_path="/"`, `transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)`（**不要传 `host`**——显式给了 `transport_security` 后它对本面无意义）；遍历 `TOOL_REGISTRY` `self.add_tool(spec.handler, name=spec.name, description=spec.description)`（`add_tool` 签名见 `fastmcp/server.py:397-407`）；覆盖 `list_tools()`：`principal = get_current_open_api_principal()`（None → 空列表，闸失败时到不了这里）→ `visible_tools` → 按父类 `:315-329` 同一形状组装 `MCPTool(name, title, description, inputSchema=info.parameters, outputSchema=info.output_schema, annotations, icons, _meta)`（**别漏 `outputSchema`**）；覆盖 `call_tool(name, arguments)`：`require_tool(principal, name)` → `started = perf_counter()` → `try: result = await super().call_tool(name, arguments)` → `audit_tool_call(... outcome="success")` → **`except ToolError as e:`（坑 19：`fastmcp/tools/base.py:116-117` 把 handler 的任何异常重包成 `ToolError(f"Error executing tool …: {e}")`，照原样冒出去 JSON 会被加前缀）`err = e.__cause__ if isinstance(e.__cause__, McpToolError) else to_tool_error(e)`；`audit(denied/error)`；`raise err`** → `except pydantic.ValidationError as e: raise to_tool_error(McpToolArgumentInvalidError(errors=e.errors()))` → `except BaseException as e: audit(...); raise to_tool_error(e)`。**装配顺序（坑 2）**：`build_mcp_route()` 内先 `server.streamable_http_app()`（返回值丢弃，只为懒建 session manager——在此之前读 `server.session_manager` 会 RuntimeError），再 `return Route("/api/v2/mcp", endpoint=McpAccessGate(StreamableHTTPASGIApp(server.session_manager)), methods=["GET", "POST", "DELETE"])`；`mcp_session_manager_run()` 返回 `server.session_manager.run()`（每进程只进一次）。`gate.py`：`McpAccessGate.__call__(scope, receive, send)`：非 http → 直通；构造 `Request(scope, receive)`；`principal, data_scope = await admit_open_api_principal(request)`（异常 → 信封响应 + `audit_transport_refusal`）；`principal.has_scope("delegate")` → 26051；`assert_no_removed_identity_headers` 之外再对 `X-On-Behalf-Of` / `X-End-User` 精确名与 `-on-behalf-of` / `-end-user` 后缀一律 26303；解析 `Accept-Language`（只认 `zh-Hans` / `en` / `ja` 三值，其余 → `zh-Hans`）写入 `open_api/mcp/errors.py` 的 `current_mcp_lang` ContextVar（供 `to_tool_error` 选 `next_step` 语言）；`async with open_api_execution_scope(request, principal, data_scope=data_scope): await self.app(scope, receive, send)`。信封：`JSONResponse(status_code=exc.http_status, content=exc.to_dict())`（`McpFaceError` 与 `OpenApiAuthError` 都带 `http_status`）。
  **测试**: T203a 全部通过；`test_open_api_route_matrix.py` / `test_openapi_schema_contract.py` 全绿
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-08, AC-09, AC-10, AC-12, AC-17, AC-28, AC-29, AC-30, AC-37, AC-38, AC-47
  **依赖**: T203a
  **证据**: 1b359102a — `open_api/mcp/{gate,server}.py` + `main.py` 条件 `Route` 与 lifespan + `middleware.py` 前缀短路 + `test_open_api_route_matrix.py` 只改那一个断言的遍历方式。
  **评审修订（2026-09-16）**: `test_open_api_route_matrix.py` 补 `test_the_mcp_route_is_registered_exactly_when_the_open_capability_layer_is_on`——本地 `config.yaml` 的 `open_platform.enabled` 为 false，`test_mcp_route_is_gated_or_absent` 读的是 import 期就建好的 `bisheng.main.app`，于是它**永远只走「不存在」那一支**，`create_app()` 里那段条件注册（AC-01 的正面、AC-37 的反面）实际零覆盖。新用例把两种开关各建一次 app，并断言：恰好一条 `/api/v2/mcp`、不是 `APIRoute`、endpoint 是 `McpAccessGate`、`GET/POST/DELETE` 齐全、不进 `app.openapi()`。
  **偏差 / 补强**: ① 路由矩阵除了加 isinstance 过滤，另加 `test_mcp_route_is_gated_or_absent`——只加过滤等于给「以后任何人往 app 上挂一条无鉴权 Starlette 路由」开了永久豁免；新用例断言`/api/v2` 下的非 APIRoute 恰好只有 MCP 那条且 endpoint 是 `McpAccessGate`。② 闸内用 `AsyncExitStack` 显式进 execution scope，区分「装配执行身份失败」（回 v2 信封）与「传输层自己出错」（交给 MCP 层，响应多半已开始，再发一个就是协议错误）。③ `lifespan` 拆出 `_platform_lifespan`，让 session manager 的 `run()` 包在最外层且只在开关开时进。

- [x] **T204a**: MCP 审计测试
  **文件**: `src/backend/test/open_api/test_mcp_audit.py`（新）
  **逻辑**: 用 `audit_events` fixture（`conftest.py:97`）：`test_tool_call_success_row_shape`（`action="open_api.mcp.tool_call"`, `target_type="mcp_tool"`, `target_id="bisheng_knowledge_list"`, metadata 含 `credential_id / actor_kind / actor_id / resource_owner_user_id / tool / category / target / outcome="success" / latency_ms / trace_id`）→ AC-07；`test_denied_row_outcome_code`（缺位 → `outcome="denied:26302"`）→ AC-07；`test_transport_refusal_row_target_dash`（26051 → `target_id="-"`）→ AC-07；`test_no_query_text_no_chunks_no_key_in_metadata`（检索调用后 metadata 序列化不含 query 字串、不含 `content`、不含 `bs-sak-`）→ AC-07, AC-47；`test_middleware_does_not_double_write_for_mcp_path`（`open_api.call` 行数为 0）；`test_action_registered_in_lockstep`（`_UI_VISIBLE_V2_ACTIONS` ∋ action；`platform/controllers/API/log.ts` 与三语 `bs.json` 含派生键 `openApiMcpToolCall`——仿 `test/app_runtime/test_audit_action_registry_lockstep.py` 的读文件断言）。
  **覆盖 AC**: AC-07, AC-47
  **依赖**: T203
  **证据**: 1b359102a + 后续 — `test/open_api/test_mcp_audit.py` 7 条。中间件短路那条**参数化成两个 path**（`/api/v2/mcp` 记 0 行、`/api/v2/filelib/retrieve` 记 1 行）——按前缀短路不能顺手把 `/api/v2` 其余部分也静音了。

- [x] **T204**: MCP 逐调用审计 + lockstep 登记
  **文件**: `src/backend/bisheng/open_api/mcp/audit.py`（新）, `src/backend/bisheng/database/models/audit_log.py`（`_UI_VISIBLE_V2_ACTIONS :198` 加 `"open_api.mcp.tool_call"`）, `src/frontend/platform/src/controllers/API/log.ts`（`V2_ACTIONS :153` 加同名）, `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json`（`log.eventTypeEnum.openApiMcpToolCall` 三语——键路径与派生规则以 `check-i18n.mjs:113-123 foldActionKey` / `controllers/API/log.ts actionToI18nKey` 为准；`pnpm check-i18n` 的 lockstep 检查会解析 `_UI_VISIBLE_V2_ACTIONS` 与 `V2_ACTIONS` 两个字面量块，**不要改它们的声明形状**）
  **逻辑**: design D7。`audit_tool_call(principal, *, tool, target: dict, outcome, latency_ms)` 与 `audit_transport_refusal(principal_or_none, *, code, ip)` 都经 `open_api_call_audit_service.enqueue(AuditLog(...))`（`operator_id / operator_name` 取法同 `middleware.py:135-152`）；`target` 只允许 `{knowledge_ids, app_id, table, dept_id, user_id}` 白名单键。
  **测试**: T204a 全部通过；`pnpm --filter bisheng typecheck` 通过
  **覆盖 AC**: AC-07, AC-47
  **依赖**: T204a
  **证据**: 1b359102a — `open_api/mcp/audit.py`；三处 lockstep（`audit_log.py` / `platform/controllers/API/log.ts` / 三语 `bs.json` 的 `openApiMcpToolCall`）。`platform` vitest `logActions.test.ts` 6 passed；`pnpm check-i18n` OK。
  **评审修订（2026-09-16）**: 中间件短路原写成 `path.startswith("/api/v2/mcp")`，会顺手把**任何以这串字符开头的兄弟路径**（将来的 `/api/v2/mcp-registry` 之类）一并静音——一个不写审计行的端点是看代码看不出来的洞。改为 `path == "/api/v2/mcp" or path.startswith("/api/v2/mcp/")`（`middleware._is_mcp_face`，常量随之更名 `MCP_FACE_PREFIX` → `MCP_FACE_PATH`），`test_mcp_audit.py` 的参数化补 `/api/v2/mcp-registry` → 仍记 1 行。

- [x] **T205**: （编号占位）开关消费 + MCP 地址字段——已**合并进 T203（挂载）与 T206（地址）**，本条不执行、不计入完成数。

- [x] **T206a**: 接入地址测试
  **文件**: `src/backend/test/dev_toolkit/test_distribution_versions_mcp.py`（新）
  **逻辑**: `test_versions_carries_mcp_url_from_public_base_url`（`open_api.public_base_url="https://kb.example.com"` → `mcp.url=="https://kb.example.com/api/v2/mcp"`, `transport=="streamable-http"`, `auth=="bearer"`）→ AC-39；`test_versions_mcp_url_derived_from_forwarded_headers`（无配置 → `X-Forwarded-Proto/Host`）→ AC-39；`test_versions_has_model_slot_none` → F051 槽位；`test_router_absent_when_open_platform_disabled`（既有 F053 用例若已覆盖则引用不重写）→ AC-37；`test_payload_contains_no_credential_material` → AC-39。
  **覆盖 AC**: AC-37, AC-39
  **依赖**: T203
  **证据**: `test/dev_toolkit/test_distribution_versions_mcp.py` 5 条（配置优先、`X-Forwarded-*` 兜底、`model` 槽位为 null、返回体零凭据、地址随路由条件挂载而非分支）。

- [x] **T206**: `GET /api/v1/dev-toolkit/versions` 加 `mcp` 段
  **文件**: `src/backend/bisheng/dev_toolkit/api/endpoints/distribution.py`（`get_dev_toolkit_versions :56` 签名加 `request: Request`，返回体加 `"mcp": {"url": f"{resolve_public_base_url(request)}/api/v2/mcp", "transport": "streamable-http", "auth": "bearer"}` 与 `"model": None`）
  **逻辑**: design D11。F053 T046 前端读 `mcp.url`；`resolve_public_base_url` 见 `open_api/api/public_base_url.py:77`。
  **测试**: T206a 全部通过
  **覆盖 AC**: AC-37, AC-39
  **依赖**: T206a
  **证据**: `dev_toolkit/api/endpoints/distribution.py` 的 `versions` 增 `mcp` 段与 `model: None` 槽位。
  **偏差（RULE-5）**: design D11 让 dev_toolkit 直接 import `open_api/api/public_base_url.py`，但那是**跨模块 API 层互相导入**，arch-guard RULE-5 当场拦下。把该模块整体移到`open_api/domain/services/public_base_url.py`（领域层，谁都可以依赖），同批改三处 import 与一处测试 import。函数体一字未改。

- [x] **T207a**: 身份 / 组织工具测试
  **文件**: `src/backend/test/open_api/test_mcp_tools_identity.py`（新）
  **逻辑**: 用 `open_api_db`（内存 aiosqlite，`conftest.py:29`）造两租户：T1 有部门 A/B（B 是 A 子）、用户 u1∈A、u2∈B、u3 disabled；T2 有 u9。`test_org_tree_full_tenant_no_scope_narrowing`（服务账号无任何管理身份仍得完整树）→ AC-31；`test_org_tree_excludes_other_tenant` → AC-32；`test_get_user_cross_tenant_same_as_missing`（u9 与 99999 → 同一 26306 响应体）→ AC-32；`test_get_user_fields_whitelist_no_credentials`（响应键集 == `{user_id,user_name,status,departments,roles}`；`password/token_version/external_id` 不出现）→ AC-14；`test_service_accounts_never_appear`（组织成员与点查都拿不到服务账号 id）→ AC-14；`test_dept_members_paginated` → AC-14；`test_missing_identity_scope_26302`（仅 `knowledge:read`）→ AC-33；`test_identity_read_is_issuable_when_open_platform_on`（`CredentialService.validate_scopes(["identity:read"])` 通过；关开关 → 26023）→ AC-33 前置；同步改 `test_scope_issuability.py:66-68`（参数化只剩 `model:invoke`）/ `:176`（集合断言改 `identity:read` 在、`model:invoke` 不在）与 `test_scopes.py:49`。
  **覆盖 AC**: AC-14, AC-31, AC-32, AC-33
  **依赖**: T203
  **证据**: `test/open_api/test_mcp_tools_identity.py` 12 条，跑在内存 aiosqlite 上造两租户 / 两级树 /归档部门 / 停用用户 / 角色。`userrole` 用手写 DDL 建表——它声明了自增 `id` 又是复合主键，SQLite 拒绝编译，不为了迁就测试引擎去改生产模型。

- [x] **T207**: `OrgDirectoryService` + 工具 ④ + `identity:read` 可签发
  **文件**: `src/backend/bisheng/department/domain/services/org_directory_service.py`（新）, `src/backend/bisheng/open_api/mcp/tools/identity.py`（新）, `src/backend/bisheng/open_api/domain/scopes.py`（`:154 issuable=False` → `True`，注释改「F052 MCP face」）
  **逻辑**: design D8。`OrgDirectoryService.atree() -> list[dict]`（`Department` 全量 by 当前租户 ContextVar 自动过滤，`status=="active"`，按 `path` 组树）、`amembers(dept_id, *, page, size, keyword)`（`UserDepartment ⋈ User`，`delete==0`；租户经 `UserTenant`）、`aget_user(user_id) -> dict | None`（`UserDao.aget_user` + `UserTenantDao.aget_active_user_tenant` 租户 == 当前，否则 `None`；水合部门与角色名）。工具 handler：pydantic 入参模型（`user_id: int` / `dept_id: str` / `page,size(≤200),keyword`）；`None` → 26306。**不**调用 `DepartmentService.aget_tree(login_user)`（坑：按可管范围）。
  **测试**: T207a 全部通过
  **覆盖 AC**: AC-14, AC-31, AC-32, AC-33
  **依赖**: T207a
  **证据**: `department/domain/services/org_directory_service.py` + `open_api/mcp/tools/identity.py` + `scopes.py` 翻 `identity:read` 可签发；`test_scope_issuability.py` / `test_scopes.py` 三处钉住集合同步。
  **偏差 1**: `identity:read` 没有任何 `endpoints` 条目——它门控的是 MCP 工具，不是 REST 路由。`test_scopes.py` 里「每个可签发的位都有端点」的断言随之把它与 `delegate` 一并排除，并写明理由。
  **偏差 2**: 停用用户（`delete=1`）**返回 `status: "disabled"` 而不是当作不存在**。藏起来会读成「没这个人」，把人支去查一个完全正确的 id 里的错别字；而且那样 `status` 这个字段永远只会是 `active`，等于白给。
  **偏差 3**: `amembers` 的状态改为按页批量取用户（`aget_user_by_ids`），不是逐行查——一页 200 人不该换来 200 次往返。

- [x] **T208a**: 应用状态 / 日志工具测试
  **文件**: `src/backend/test/open_api/test_mcp_tools_apps.py`（新）, `src/backend/test/app_publish/test_publish_status_service.py`（追加 owner-only entry 用例）, `src/backend/test/app_runtime/test_app_query_service_entry.py`（新）
  **逻辑**: 用 `test/app_runtime/conftest.py` 的 `fake_orchestrator` + 内存库造 app A（owner=归属人 R）、app B（owner=X，同租户）、app C（他租户）、租户管理员 M 名下服务账号 SA_M：`test_status_owner_app_returns_instance_and_publish_fields`（键集按 design §4.2 ②）→ AC-16；`test_status_includes_reject_reason_full_text` → AC-16；`test_logs_via_entry_mcp_lines_app_state_pending_reason` → AC-16；`test_non_owner_app_26305_same_as_missing_no_owner_name`（B / C / 不存在 三者响应体逐字相等）→ AC-34；`test_tenant_admin_service_account_key_still_refused`（SA_M 查 B → 26305）→ AC-35；`test_owner_change_takes_effect_next_call`（改 SA 的 `resource_owner_user_id` → A 不可及、X 的应用可及；app owner 未变）→ AC-36；`test_publish_status_entry_mcp_refuses_admin_detail_still_allows`（服务层：`entry="mcp"` 管理员拒、缺省放行）→ AC-35；`test_get_instance_entry_mcp_same_rule` → AC-35；`test_runtime_disabled_16207` → AC-17；`test_same_source_as_detail_page`（`entry="detail"` 与 `entry="mcp"` 对 owner 返回体相等）→ AC-18。
  **覆盖 AC**: AC-16, AC-17, AC-18, AC-34, AC-35, AC-36
  **依赖**: T203
  **证据**: `test/open_api/test_mcp_tools_apps.py` 16 条 + `test/app_runtime/test_app_query_service_entry.py` 6 条 + `test/app_publish/test_publish_status_service.py` 追加 5 条。
  **实测发现**: 服务层「陌生人」与「应用不存在」的 `details.reason` 本来就不同（`not_visible` vs `not_found`），这在平台面是有用的（告诉负责人「应用已删除」）。存在性不泄露的要求落在**工具出口**：工具重建一个只带 `app_id` 的 `McpAppNotOwnedError`，`details` 一概不透传——逐字相等的断言因此写在`test_mcp_tools_apps.py` 而不是服务层测试里。

- [x] **T208**: 工具 ⑥ + 服务层 `entry` owner-only
  **文件**: `src/backend/bisheng/open_api/mcp/tools/apps.py`（新；⑤ 的 handler 也在此文件，T209 补）, `src/backend/bisheng/app_publish/domain/services/publish_status_service.py`（`get_publish_status :74` 加 `entry: str = "detail"`；`_require_viewer :181` 加 `entry`：`entry in {"cli","mcp"}` 时仅 owner，否则原逻辑）, `src/backend/bisheng/app_runtime/domain/services/app_query_service.py`（`get_instance :64` 加 `entry`；`_load_visible :246` 加 `entry`：owner-only 入口先比租户再比 owner、不放行管理员——与 `_require_log_access :263-290` 同一判据，抽公共 `_owner_only_gate(app, actor)` 复用）
  **逻辑**: design D9。actor 构造同 `app_publish/api/endpoints/deploy.py:206-211`（`UserPayload(user_id=resource_owner_of(principal), user_name=…, user_role=[], tenant_id=principal.tenant_id)`——**不传任何会抬高权限的字段**）。`bisheng_app_status(app_id)`：`instance = get_instance(app_id, actor=actor, entry="mcp")` + `publish = get_publish_status(app_id, actor=actor, entry="mcp")` → 合并；`bisheng_app_logs(app_id, tail, since, keyword)` → `get_logs(..., entry=LOG_ENTRY_MCP)`。异常折叠：`AppNotFoundError(16101) / AppLogForbiddenError(16161) / AppPublishOwnerOnlyError(16254) / 16205` → `McpAppNotOwnedError`（26305，`data` 只含 `app_id`；三者响应体必须逐字相同，不带 owner 名）。
  **测试**: T208a 全部通过；`test/app_runtime test/app_publish` 与基线无新增失败
  **覆盖 AC**: AC-16, AC-17, AC-18, AC-34, AC-35, AC-36
  **依赖**: T208a
  **证据**: `publish_status_service.get_publish_status/_require_viewer` 与 `app_query_service.get_instance/_load_visible` 加 `entry`，缺省 `detail` 行为不变；`open_api/mcp/tools/apps.py` 工具 ⑥。
  **评审修订（2026-09-16）**: ① `_actor()` 原来在 `try` **之外**调用，于是 `resource_owner_of` 对无归属人密钥抛的 **16205 不会被折成 26305**——直接落到 `to_tool_error`，答的是原码 + 该异常自己的 `details` / `hints`，与其它四种「不是你的应用」形状不一。`test_every_not_yours_reason_gives_one_identical_answer` 把 `AppNotOwnedBySubjectError` 注入成 `get_instance` 的返回，走的是 try 内那条路，所以看不出来。已把 `_actor()` 移进 `bisheng_app_status` / `bisheng_app_logs` 的 try，并补 `test_a_key_with_no_resource_owner_gets_the_same_one_answer`（status 与 logs 响应体逐字相等、`data` 只含 `app_id`、不含 `resource_owner_missing`）。② `test_personal_tokens_cannot_hold_the_scope_these_tools_need` 原断言 `requires_open_platform is True`，那是「这套层部署了没有」，证明不了「PAT 拿不到 `app:manage`」；改为断言真正的机关 `personal_token_service.PERSONAL_TOKEN_SCOPE == "knowledge:read"`。
  **偏差**: 「哪些入口算凭据门」抽成 `app_query_service.OWNER_ONLY_ENTRIES` 公共常量，由 app_publish 复用，不在两个模块各写一份 `{"cli", "mcp"}`。`_load_visible` 的凭据门两种失败都答`AppNotFoundError`（而不是拆成 16101 / 16161）——这个方法本来就这么说话，且工具层无论哪个码都折成同一个 26305。

- [x] **T209**: 工具 ⑤ 应用数据（**阻塞于 F054 T086/T087 `AppDataService`**——HEAD `fe10f75ea` 树上不存在；本波次 data-plane 切片**已实现但尚未合并**，合流时以合并后的文件为准）
  **文件**: `src/backend/bisheng/open_api/mcp/tools/apps.py`（增量）, `src/backend/test/open_api/test_mcp_tools_app_data.py`（新）
  **逻辑**: design D9。**服务端签名已核实**（只读来源：worktree `/Users/lilu/Projects/bisheng/.claude/worktrees/wf_f464b35c-e86-3` 的 `bisheng/app_runtime/domain/services/app_data_service.py:56+`，合并后路径相同）：
  - `AppDataService.list_tables(app_id, *, actor)` → `bisheng_app_db_tables`
  - `AppDataService.get_table_schema(app_id, table, *, actor)` → `bisheng_app_db_schema`（**方法名不是 `get_schema`**）
  - `AppDataService.get_rows(app_id, table, *, actor, page=None, size=None, order=None)` → `bisheng_app_db_rows`（**不是 `read_rows`**；`DEFAULT_PAGE_SIZE=50` / `MAX_PAGE_SIZE=200`）
  - `AppDataService.update_row(app_id, table, key, values, *, actor)` → `bisheng_app_db_row_update`（行键形参叫 **`key`** 不是 `pk`）
  - `export_table` **不接线**（MCP 不传文件）；`insert_row / delete_row` **今天不存在**，待 F054 回写受理后接线（未落地时两工具 `available()=False` → 不进清单）
  **没有 `entry` 形参**：`_require_owner` 已把 owner-only 无条件内建（明确不看 `is_global_super` / 租户管理员），所以本任务 **不给 F054 的服务加参数、也不在工具层重复判 owner**（两处判定必漂）。返回体原样透传；写操作审计由 F054 侧 `app.data_row_edit`（`app_runtime/domain/constants.py:107`）带 before/after 记，本工具**不**另记数据审计，只记 `open_api.mcp.tool_call`。异常折叠：`AppNotFoundError(16101)` / `AppDataForbiddenError(16162)` → 26305（`not_your_app`，同一响应体）；「应用尚未建库」16163 保留原码、`category="unreachable"`、`next_step` 指「先让应用写一次数据」。
  **测试**: owner-only（含租户管理员名下 SA 查他人应用 → 26305）→ AC-34, AC-35；不存在 / 他租户 / 非 owner 三者响应体逐字相等 → AC-34；写调用透传到 `AppDataService.update_row`（spy）且 F054 审计被触发 → AC-15；无 DDL 入口（注册表里没有 `create/alter/drop` 类工具名）→ AC-15；运行时层关 → 16207 → AC-17；`test_mcp_face_reuses_same_service_method`（对应 F054 T087a 同名用例：`tools/apps.py` **不 import** `orchestrator_client`）→ AC-15；`test_16163_app_has_no_tables_yet_is_not_folded_into_26305`（建库前的空表态不能被说成「不是你的应用」）→ AC-15。
  **测试降级**：F054 未合并前本任务整体 `[ ]`，注册表 `available()` 由 `importlib.util.find_spec("bisheng.app_runtime.domain.services.app_data_service")` 判定；合并后若签名与上面不符，只改本文件的适配层并把差异写进「实际偏差记录」。
  **覆盖 AC**: AC-15, AC-17, AC-34, AC-35
  **依赖**: T208, **F054 T087**
  **状态变更**: **不再阻塞**——F054 `AppDataService` 本波次已合入 3.0-vibe（`app_runtime/domain/services/app_data_service.py`），签名与 design D9 核实的一致（`get_table_schema` / `get_rows` / `key` / 无 `entry`、owner-only 内建）。
  **证据**: 四个数据工具在 `tools/apps.py` 纯透传，未加 `entry`、未在工具层重复判 owner；`test_mcp_tools_apps.py` 覆盖透传、无 DDL 工具名、不 import `orchestrator_client`、16163「还没建库」不被说成「不是你的应用」。
  **未做**: `bisheng_app_db_row_insert` / `_row_delete` 仍不存在——manager 侧只有 `PATCH …/rows/{key}`，F054 需补 `insert_row` / `delete_row`。已登记到 F054 tasks 的「跨 Feature 回写受理」表。**注册表里也没有这两个占位工具**：一个 `available()` 恒假的空壳不如没有。

- [x] **T210**: 工具 ③ 模型清单（**阻塞于 F051 名称解析**）
  **文件**: `src/backend/bisheng/open_api/mcp/tools/models.py`（新）, `src/backend/test/open_api/test_mcp_tools_models.py`（新）
  **逻辑**: design D10。`from bisheng.llm.domain.services.model_name_resolver import resolve_callable_names`（F051 定名，落地后以其 tasks 为准改 import）；`resolve_callable_names(tenant_id)` → 过滤 `is_chat` 不限（AC-13 要标注是否对话类，故全部返回并带 `is_chat`）→ 出参 §4.2 ②。测试：`test_names_match_f051_resolver_verbatim`（三处同源：工具输出 == 解析函数输出）→ AC-13, AC-18；`test_ambiguous_models_expose_qualified_name_only` → AC-13；`test_tenant_level_not_per_user`（两把不同 SA 的 key 同租户 → 相同清单）→ AC-13；`test_missing_model_invoke_scope_26302` → AC-45 一格。**测试降级**：F051 未合入时工具 `available()=False`、本任务 `[ ]`。
  **覆盖 AC**: AC-13, AC-18
  **依赖**: T203, **F051 名称解析交付**
  **状态**: 实现已落、**保持不可用**。`open_api/mcp/tools/models.py` 按 design D10 只经 F051 的 `resolve_callable_names` 取名，本分支上该函数不存在 → `available()` 为假 → 工具不进清单、直调 26301。
  **偏差**: design D10 把模块名写作 `model_name_resolver`，而 F051 切片的提交把它落在 `model_catalog`。`RESOLVER_MODULES` 两个名字都探，哪个先合入都能亮；都没有就保持熄灭。合并后请核对真实符号名并收敛成一个。
  **证据**: `test/open_api/test_mcp_tools_models.py`——2 条无依赖的（不自造命名规则、「未落地即缺席」）常绿，3 条依赖解析器的 skip。

- [x] **T211（结案：不做）**: fake 门面（Line B 自测用，随 T301 删除）
  **文件**: `src/backend/test/open_api/fakes/fake_retrieval_facade.py`（新；T301 合流后删除并改 import 真门面）
  **逻辑**: 按 T003 契约实现 `retrieve / list_accessible_knowledge / check_reachable` 的可编程 fake（按 fixture 表返回或抛 26321 / 26322 / 19002）。
  **依赖**: T003
  **不做，理由**：T211 的 fake 门面是为「Line B 先于 Line A 落地时自测 ①②」准备的。Line B 改用「延迟 import + `available()` 门控」后，①② 在门面缺席时根本不进清单，没有可自测的对象；多造一个 fake 只会多一份要跟着契约漂的代码。
  **前提已永久消失（合流波复核）**：两线均已在 `3.0-vibe` 上，`knowledge_tools.facade_available()` 为真，`test_mcp_tools_knowledge.py` 的 10 条已实跑（不再整份 skip），同文件的 `test_the_registry_hides_both_tools_when_the_facade_is_absent` 继续守住「工具悄悄消失」不能冒充「门面还没来」。**勾选为 `[x]` 是结案不是交付**——本条不再是待办，才不该留在「哪些还没做」的检索结果里。

- [x] **T212**: MCP 注册表驱动的逐位矩阵（Line B 内可先跑，T301 后补 ①②）
  **文件**: `src/backend/test/open_api/test_mcp_scope_matrix.py`（新）
  **逻辑**: 参数化 `TOOL_REGISTRY × {仅 knowledge:read, 仅 model:invoke, 仅 identity:read, 仅 app:manage, 空}`：持位 → 在清单且可调（handler monkeypatch 为 stub）；不持位 → 不在清单且直调 26302 指明缺位。**基准取 `[s for s in TOOL_REGISTRY if s.available()]`**（不是整张表）——③ 与 ⑤ 的后两个工具在 F051 / F054 落地前 `available()=False`，用整表做分母会在分批上线期间恒红；另加一条 `test_every_registry_entry_is_covered_by_this_matrix`（断言参数化用例数 == 可用工具数 × 5，新增工具漏进表即红）。
  **覆盖 AC**: AC-04, AC-45
  **依赖**: T203, T207, T208
  **证据**: `test/open_api/test_mcp_scope_matrix.py`——`installed_tools() × {四个单位, 空}` 参数化，48 条常绿；另有「每个注册项都被矩阵覆盖」「每个工具恰好映射到清单里的一个位」两条守卫。
  **实现说明**: 持位那一格**不 stub handler**，让调用真的落到 handler——这才证明清单里的名字可被分发；本地无中间件时 handler 自己会失败，用例只要求「失败的不是 26302」。

### Wave C · 合流（两条线都落地后）

- [x] **T301a**: 工具 ①② 测试
  **文件**: `src/backend/test/open_api/test_mcp_tools_knowledge.py`（新）
  **逻辑**: monkeypatch 真 `RetrievalFacadeService` 的 `retrieve / list_accessible_knowledge` 为 spy（T211 fake 删除）：`test_search_passes_service_account_identity_and_no_whitelist`（`identity.actor.subject_type=="service_account"`, `req.whitelist is None`）→ AC-10, AC-22；`test_search_output_fields`（§4.2 ② 键集，含 `effective_scope / truncated_params`）→ AC-10；`test_search_unreachable_26321_isError_json_lists_ids` → AC-11；`test_search_omitted_ids_means_all_granted` → AC-22；`test_search_capability_revoked_not_raised_without_whitelist`（显式指定已删库 → 26321 而非 26322）→ AC-46；`test_list_returns_only_supported_types_with_ids_and_names` → AC-12；`test_list_equals_subject_grant_page_set`（spy `list_accessible_knowledge` 的入参 identity 与 v2 `GET /filelib/` 同主体 → 同 actor）→ AC-12, AC-18；`test_search_permission_unavailable_category`（19002 → `category="permission_unavailable"`、无 chunks）→ AC-24；`test_pat_holder_sees_search_and_list_only` → AC-04。
  **覆盖 AC**: AC-04, AC-10, AC-11, AC-12, AC-18, AC-22, AC-24, AC-46
  **依赖**: T102, T203, T212
  **证据**: `test/open_api/test_mcp_tools_knowledge.py` 10 条，整份 `skipif` 于门面是否在树上；文件末尾的 `test_the_registry_hides_both_tools_when_the_facade_is_absent` 断言「跳过的前提确实成立」，让「工具悄悄消失」无法冒充「门面还没来」。本分支上全部 skip。

- [x] **T301**: 工具 ①② 实现
  **文件**: `src/backend/bisheng/open_api/mcp/tools/knowledge.py`（新）, `src/backend/test/open_api/fakes/fake_retrieval_facade.py`（删除）
  **逻辑**: `bisheng_knowledge_search(query, knowledge_ids=None, top_k=10, max_content=15000, tags=None)`：`identity = RetrievalIdentity.from_open_api_principal(get_current_open_api_principal())` → `RetrievalFacadeService.retrieve(identity, RetrievalRequest(...))` → §4.2 ② 出参；`bisheng_knowledge_list(name=None, limit=200)` → `list_accessible_knowledge` → `{items:[{knowledge_id,name,type:"library"|"space",description}],total}`。错误经 `to_tool_error`。
  **测试**: T301a 全部通过
  **覆盖 AC**: AC-04, AC-10, AC-11, AC-12, AC-18, AC-22, AC-24, AC-46
  **依赖**: T301a
  **证据**: `open_api/mcp/tools/knowledge.py` 已按 design §4.2 ③ 契约实现（`RetrievalIdentity.from_open_api_principal` + `RetrievalRequest(whitelist=None)` → 出参整形），门面模块经函数体内延迟 import；`available()` 未满足前 ①② 不进清单。
  **阻塞**: 需 Line A 的 `knowledge/domain/schemas/retrieval_facade.py` 与 `knowledge/domain/services/retrieval_facade_service.py` 合入后才能真正跑通并解除 skip。

- [ ] **T302**: 端到端（真 MCP 客户端 + CI 中间件）
  **文件**: `src/backend/test/open_api/test_mcp_e2e.py`（新，`@pytest.mark.e2e`）
  **逻辑**: 用 `mcp_client` 对真 app：`test_standard_client_zero_change_handshake_list_call`（`initialize` → `list_tools` → `call_tool("bisheng_knowledge_list")`）→ AC-01；`test_revoke_then_denied_within_5s`（真 Redis：撤销 → 采样 ≤ 3s 内首次拒绝）→ AC-05；`test_matrix_over_real_app`（复跑 T212 矩阵不 stub handler）→ AC-45；`test_search_set_equality_with_v2`（同 key、同 query、同 ids：MCP 与 v2 chunk 集相等；样本同 T104）→ AC-40, AC-41；`test_fga_down_mcp_search_error_zero_results` → AC-44。**测试降级**：本地 skip；114 手动步骤 design §7。
  **覆盖 AC**: AC-01, AC-05, AC-40, AC-41, AC-44, AC-45
  **依赖**: T301, T104
  **部分落地**: `005e5f470` — 新建 `test/open_api/test_mcp_e2e.py`，4 例全绿、**不带 `e2e` 标记**（它们不需要中间件）。原任务把两类断言混在一处，这次按「由谁决定」拆开：
  - **只由请求路径决定、已落地**：AC-01 `test_a_standard_client_connects_lists_and_calls_with_nothing_but_an_address_and_a_key`（真 `ClientSession` 走进程内 ASGI：握手 → `tools/list` → `tools/call("bisheng_knowledge_list")` 拿到 `structuredContent`，除地址与 Bearer 外无任何本地件）；AC-05 三条——`test_a_live_session_is_not_a_grant_the_credential_is_reread_every_call`（逐次数 `validate_bearer`，证不存在会话级凭据记忆）、`test_a_revoked_credential_is_refused_on_the_very_next_call`（会话中途撤销 → 下一次请求被传输层 401 拒）、`test_the_credential_cache_can_never_outlive_the_revocation_bound`（`OpenApiConf.cap_credential_cache_ttl` 把 300 钳成 5——INV-28 的唯一防线，此前仓内只有 F055 侧断言）。
  - **AC-45 不在本文件重复**：`test_mcp_scope_matrix.py` 已在同一个进程内 app 上按注册表逐位跑过且**不 stub handler**。
  **播种 helper 与用例体已落地（wave 5，`wt/f052-e2e-scaffold`）；任务仍不勾——它们一次都还没跑过**。AC-40 / AC-41 的「同样本同 query 下 MCP 与 v2 chunk 集合相等」、AC-44 的真停 OpenFGA、AC-05 的真 Redis TTL 计时，与 T104 是同一份样本，现在都写在 `src/backend/test/e2e/test_e2e_f052_retrieval_set_equality.py` 里（`@pytest.mark.e2e` + `F052_E2E=1`），样本由 `src/backend/test/e2e/helpers/retrieval_sample.py` 播种。MCP 那一侧用真 `mcp` 客户端（`streamablehttp_client` + `ClientSession`）对**部署好的**地址握手后调 `bisheng_knowledge_search`，与同一把密钥的 `POST /api/v2/filelib/retrieve` 比 `(document_id, chunk_index)` 集合。**运行前提、AC-42 的偏差、AC-44 的两次跑法、以及文件为何落在 `test/e2e/` 而不是任务原文写的路径，逐条记在 T104 下**，不在此重复。
  **实现说明（踩到过）**：`identity:read` 那条用例必须在 `OrgDirectoryService` 服务边界打桩。让 handler 真去够数据库，在无中间件环境下会把 SQLAlchemy engine 留在坏状态，**几个文件之后**的 `test_route_error_contract.py::test_child_tenant_key_is_not_mistaken_for_missing_account` 才报错——与 `test_mcp_scope_matrix.py` 里 `quiet_services` 注释记的是同一个坑，已实测复现并修掉。

- [ ] **T303**: 114 部署与手动验证（design §7 ①–⑤）
  **文件**: `features/v3.0.0/052-mcp-server-face/tasks.md`（本节下方「114 验证记录」）
  **逻辑**: `bash /opt/bisheng-ops/deploy.sh`（先查 `linsight_session_version` IN_PROGRESS 与 `free -m`）→ 114 `config.yaml` 已有 `open_platform.enabled: true`（HARNESS.md remote_114）→ 步骤 ①–⑤，用非管理员 `shuiwu` 名下服务账号（**不用 admin**）；同时用 Claude Code 与一个纯 `mcp` python 客户端各接一次（AC-01「任何标准客户端」）；记录 `journalctl -u bisheng-api` 中 `open_api.mcp` 行与 `audit_log` 行。
  **覆盖 AC**: AC-01, AC-05, AC-40
  **依赖**: T302
  **未做（需 114 机器，本切片无法执行）**：逐条命令已按当前实现核对并写在文末「114 验证记录」，照抄即可跑。`T302` 的依赖不再是阻塞——它能在本地证的那部分已落地，剩下的那部分与本任务要的是同一批真实数据。

- [x] **T304**: 对外文档
  **文件**: `docs/api/mcp-server.md`（新：地址 / 鉴权 / 六类工具入参出参（引 design §4.2 ②）/ 错误三要素与类别表 / Claude Code · Cursor · 纯 python 客户端配置示例 / 「PAT 只见两工具」/ 未部署时 404）, `docs/api/filelib-retrieve.md`（T103 已改，此处只核对交叉引用）
  **依赖**: T301
  **证据**: `docs/api/mcp-server.md`（地址 / 鉴权与身份边界 / 六类工具表与入出参 / 三要素错误与 category 表 / 传输层拒绝的真实状态 / 审计口径 / Claude Code 与纯 python 客户端示例）。
  **评审修订（2026-09-16）**: 应用数据工具那一行原写「数据面服务返回体原样透传」，实际出参是 `{result: …}`（`AppDataResult` 信封）——照文档写客户端会取错一层。已改为写明信封。

- [x] **T305**: 契约回写与状态
  **文件**: `features/v3.0.0/release-contract.md`（表 3 F052 行状态；错误码表 263 行由 T001 已加，此处核对）, `features/v3.0.0/README.md`（F052 行状态）, `features/v3.0.0/054-app-domain-runtime/tasks.md`（「跨 Feature 回写受理」表登记 T209 的 insert / delete 请求）, `features/v3.0.0/051-model-protocol-gateway/spec.md` 不改（design 未写；在其 design 编写时引用本文 D10）
  **依赖**: T303
  **证据**: 表 3 F052 行与 README F052 行都改成**按实现侧取证**的口径（不写「已交付」，写清哪几项未验），两处都点名 T104 / T302 / T303 三个未完项。**核对结果**：① 错误码表 263 行 T001 已加，两张表（`:100` 已分配模块编码、`:106` 段位说明）内容一致、无需改；② F054 tasks 的「跨 Feature 回写受理」表里 T209 的 `insert_row` / `delete_row` 请求**已登记且状态为 🔲 未交付**，本次只复核未改。
  **偏差**: 原写「依赖 T303」。T303 需要 114 机器，但本任务要回写的是「哪些已落地、哪些还没验」这件事本身——押在 114 之后只会让契约表长期停在「Spec 定稿」，与实现侧严重不符。故先按当前取证回写，并把 T303 未做写进状态里；114 跑完后只需把「未验」几项改掉。
  **反向口径**：交付与否不能读 `features/` 目录，本次回写的每一句都对着实现侧 grep 过（`open_api/mcp/` 十一个文件、`common/errcode/mcp_face.py` 十一个 `Code: int = 263xx` 且三语 `api_errors` 各 11 个键、`audit_log.py` 与 `platform/controllers/API/log.ts` 的 `open_api.mcp.tool_call` 与三份 `bs.json` 的 `openApiMcpToolCall`、`distribution.py:94` 的 `mcp` 段）。

---

## 估算（小时）

| 波 / 线 | 任务 | 估算 |
|---|---|---|
| Wave 0 | T001–T003 | 6 |
| Line A | T101a/T101 10 · T102a/T102 14 · T103a/T103 6 · T104 8 · T105 1 | 39 |
| Line B | T201a/T201 4 · T202 4 · T203a/T203 16 · T204a/T204 4 · T206a/T206 2 · T207a/T207 8 · T208a/T208 8 · T209 6（阻塞）· T210 4（阻塞）· T211 1 · T212 3 | 60 |
| Wave C | T301a/T301 6 · T302 8 · T303 4 · T304 3 · T305 1 | 22 |
| **合计** | | **≈127h**（不含 F051 / F054 前置） |

---

## AC 追溯表（47 / 47）

> **两条 AC 的覆盖任务被上游阻塞，本 Feature 单独交付时它们不可验收**（spec「依赖」段已写明，这里复述以免漏判）：**AC-13** 只挂 T210（阻塞于 F051 的 `resolve_callable_names`）、**AC-15** 只挂 T209（阻塞于 F054 的 `AppDataService`）。两个工具在依赖落地前 `available()=False`、不进工具清单，其余 45 条 AC 不受影响——所以「F052 已交付」的口径是「45 / 47，AC-13 与 AC-15 随 F051 / F054 启用后补验」，不得笼统写成全绿。
>
> **2026-09-16 Line B 交付后的实际口径**（比上面这段更细，以此为准）：
> - **AC-15 已解除阻塞**：F054 `AppDataService` 本波次已在 3.0-vibe 上，四个数据工具已接线并有测试。**但 `insert_row` / `delete_row` 仍不存在**，所以 AC-15 里「行级增删改」的**增与删两项仍未交付**，只有读与改成立。
> - **AC-13 仍不可验收**：F051 名称解析未在本分支出现，工具 ③ `available()=False`。
> - **门面侧的 AC 由 Line A 承接，Line B 只做了工具面接线**：AC-10 / AC-11 / AC-19～AC-27 / AC-40～AC-44 / AC-46 的实质实现在门面，本切片对应的 T301a 全份 skip。「MCP 面可用」≠「检索工具可用」。
> - **AC-01 / AC-05 的 114 端到端验证（T302 / T303）未做**：本地无中间件，且需要真实密钥与真实 MCP 客户端。
>
> **2026-09-16 合流波收尾后的增量**（最新，覆盖上一条的后两项）：
> - **T301a 不再 skip**：两线已在同一棵树上，`facade_available()` 为真，10 条实跑通过——上一条写的「全份 skip」已过期。
> - **AC-01 / AC-05 已有本地用例**（`test/open_api/test_mcp_e2e.py`）：真 `ClientSession` 走完握手 → 清单 → 调用，撤销后下一次调用被 401 拒，凭据缓存 TTL 被 5s 钳住。**但「≤5 秒」的计时本身没测**——本地用例证的是「每次都重新校验 + 缓存上界存在」，真实计时归 T303 ④。
> - **AC-41 / AC-44 各交付了一半**：两个门面递给统一门面的调用逐字相等（AC-41 的构造层）、权限引擎故障注入下 **spec AC-44 点名的三个门面（MCP 工具 / v2 / 托管运行期）加门面本身共四处**都 fail-closed 且引擎零调用（AC-44 的判断层）。**仍欠**：AC-40 / AC-42 的样本集合相等、AC-41 的存储层集合相等、AC-44 的真停 OpenFGA——都卡在同一个「四种权限来源的样本播种 helper」上。
> - **一句话口径**：F052 现在是「45 / 47 的代码面已齐，其中 AC-40 / AC-41 / AC-42 / AC-44 只完成了可在无中间件下证的那一层」，加上 AC-13（F051）与 AC-15 的增删两项（F054）待上游。**不得写成「已交付」**。

| AC | 任务 | AC | 任务 | AC | 任务 |
|---|---|---|---|---|---|
| AC-01 | T203a/T203, T302, T303 | AC-17 | T203a/T203, T208a/T208, T209 | AC-33 | T207a/T207 |
| AC-02 | T201a/T201, T203a/T203 | AC-18 | T208a/T208, T210, T301a/T301 | AC-34 | T208a/T208, T209 |
| AC-03 | T201a/T201, T203a/T203 | AC-19 | T101a/T101, T102a/T102, T104 | AC-35 | T208a/T208, T209 |
| AC-04 | T203a/T203, T212, T301a/T301 | AC-20 | T101a/T101 | AC-36 | T208a/T208 |
| AC-05 | T203a/T203, T302, T303 | AC-21 | T102a/T102 | AC-37 | T203a/T203, T206a/T206 |
| AC-06 | T203a/T203 | AC-22 | T102a/T102, T301a/T301 | AC-38 | T203a/T203 |
| AC-07 | T204a/T204 | AC-23 | T102a/T102 | AC-39 | T206a/T206 |
| AC-08 | T203a/T203, T104 | AC-24 | T101a/T101, T102a/T102, T103a/T103, T301a/T301 | AC-40 | T104, T302, T303 |
| AC-09 | T203a/T203 | AC-25 | T103a/T103 | AC-41 | T104, T302 |
| AC-10 | T203a/T203, T301a/T301 | AC-26 | T103a/T103 | AC-42 | T104（F055 承接运行期） |
| AC-11 | T102a/T102, T103a/T103, T301a/T301 | AC-27 | T102a/T102 | AC-43 | T103a/T103, T104（F050 承接） |
| AC-12 | T203a/T203, T301a/T301 | AC-28 | T203a/T203 | AC-44 | T103a/T103, T104, T302 |
| AC-13 | T210（阻塞 F051） | AC-29 | T203a/T203 | AC-45 | T212, T302 |
| AC-14 | T207a/T207 | AC-30 | T203a/T203 | AC-46 | T102a/T102, T301a/T301 |
| AC-15 | T209（阻塞 F054） | AC-31 | T207a/T207 | AC-47 | T203a/T203, T204a/T204 |
| AC-16 | T208a/T208 | AC-32 | T207a/T207 | | |

---

## 实际偏差记录

> **只留一行指针**，论证在 design.md（决策 / 坑），这里不重复（见 `docs/SDD-Guide.md` §4）。
> 推翻已定案的决策时，先停下与用户重新确认（本轮 ★ 已豁免，但 D1 传输形态 / D5 抽出引擎 / D6 契约收紧 / D9 owner-only 四条属「产品可见」决策，翻案仍须确认）。

- **（已落地 `610551615`）两处对外可见的受控收紧**，design D6 已定案：① v2 `POST /filelib/retrieve` 对被 F066 `data_scope` 窄化的目标由 26044/403 改答 26321/404；② `RetrieveReq.max_content` 由无上限改为 `le=60000`。**实际影响核查**：仓内对 retrieve 的 26044 指引只有技能包两处文案（`SKILL.md:85` / `references/api.md:78`），已同批订正；`test_data_scope_matrix.py` 的分类已由 `"raise"` 改为新增档 `"unreachable"` 并补了「与库不存在逐字相同」的断言；`max_content` **仓内**无传值 > 60000 的调用点（`grep -rn max_content src/backend/bisheng src/frontend/*/src docs`：全部走默认 15000 或内部路径，`workstation_service.py:1394` 的 `max_content=max_token` 不经 `RetrieveReq`、不受本次上限影响）。**仓外集成方无从核实**——`le=60000` 对它们是可能命中的破坏性变更，回滚条件见 design D6 ②（改为门面对 v2 不夹取 + `RetrieveResp` 加可选 `truncated_params`，走 v2 版本化）。
- **（T003）`RetrievalIdentity.from_user` 落成 `async`**：design 原文按同步写。管理员事实必须经 `resolve_permission_actor` 解析（可能一次 FGA 往返），由调用方猜就会在托管运行期给出错误的可见范围。`from_open_api_principal` 仍同步——闸已解析过。
- **（T102）`version_repo` 走关键字传参**，不由门面内部调 `get_knowledge_document_version_repository()`：领域服务调 FastAPI 依赖工厂是反向依赖入口层（C1），且 F055 / F057 未必有 `Request`。design §4.2 ③ 原文留了「二选一」，此处定案。
- **（T102）`check_reachable` 只评估 `knowledge_ids` 点名的目标**，`whitelist` 仅用于判定是否属声明范围与条目是否已消失，不遍历未点名的白名单条目。F055 预检把声明列表同时传两个参数即可逐条得结论。
- **（T101）`_aretrieve_chunks_dispatch` 未整体删除而是收窄为 `_aretrieve_chunks_for_one`**：design D5 正文要求「存在性 / 类型裁定留在聊天服务这一层」，与 T101 文件清单行的「删除」字面冲突，按正文办。
- **（T101）三个既有测试文件同批改**：`test_knowledge_space_chat_service_retrieve.py` / `test_knowledge_space_chat_service_visibility.py` / `test_openapi_retrieve_file_visibility.py` 里直接戳私有方法的用例改为对 `RetrievalEngine` 断言。tasks.md 原文要求「既有用例全绿」，但被断言的私有方法本身是这次搬迁的对象——方法搬走断言跟着搬，行为断言未放松，等价性另由 `test_retrieval_engine_extraction.py` 守。
- **（T103）删除 `get_knowledge_space_chat_service_for_openapi`**：端点改走门面后零调用方（`grep` 全仓确认），死代码按项目口径删除而非保留。
- **（T003 · 复核修正）`RetrievalIdentity.from_open_api_principal` 改为沿用闸已装的 actor**（仅当它描述的正是本 principal 的授权主体：`subject_type` / `subject_id` / `tenant_id` 三者相等，否则退回按 principal 现构）。原实现每次新建一个 `PermissionActor(data_scope=DATA_SCOPE_ALL)`，而门面随后又把它装进 ContextVar 盖掉闸装的那个——后果是**被 F066 `data_scope` 窄化的个人令牌在检索面拿回全量范围**（窄化判定完全由 `actor.data_scope` 驱动，`permission_action_service.py` 的 `_data_scope_denied_map` / `list_visible_objects`），是一处线上放权；同时管理员事实被抹成 `False`，管理员持有的个人令牌经门面看到的比平台内少（AC-41 / AC-43 的静默反向破坏）。design 坑 8 原文即写「管理员事实取自已装 actor」。守卫：`test_retrieval_facade_equality.py::test_identity_keeps_the_gates_data_scope_narrowing` / `::test_identity_keeps_the_gates_administrator_facts` / `::test_identity_never_adopts_an_actor_for_a_different_subject`。
- **（T003 · 复核修正）`RetrievalIdentity.from_user` 解析 actor 前先把 ContextVar 清空**。`resolve_permission_actor` 有 ContextVar 短路（design 坑 5），而 F055 托管运行期是**带着应用自己的凭据 actor** 调这个构造器的——不清空就会把访问用户的身份悄悄换成应用的可见范围，正是 AC-42 要挡的放大。守卫：`::test_from_user_does_not_inherit_the_ambient_actor`。
- **（T103 · 复核修正）端点层两条参数校验补回**：`tag_match_mode="ALL"` → 400、过滤器引用不在 `knowledge_base_ids` 里的库 → 400。两条原本在 `aretrieve_chunks` 体内，端点改走门面时随调用一起丢了；`"ALL"` 未实现，按 `"ANY"` 当作等价处理会**返回比调用方要求更宽的集合**且响应里无从察觉，与 `docs/api/filelib-retrieve.md` §5.1 的对外承诺相反。T103 文件清单本来就写了「`tag_match_mode != "ANY"` 的 400 保留在端点层」。守卫：`test_filelib_retrieve_facade.py::test_tag_match_mode_all_is_still_400` / `::test_filter_for_an_untargeted_knowledge_base_is_400`。
- **（T103 · 复核修正）文档口径**：`max_content` 超限写成「422」不成立——`/api/v2` 的 `RequestValidationError` 由 `open_api_validation_exception_handler` 统一回 **HTTP 400**。`docs/api/filelib-retrieve.md` 已按实际行为订正（§3.3 与 §5.1）。
- **（记录，非本切片引入）`open_endpoints/api/endpoints/filelib.py` 的 arch-guard RULE-5 告警是存量**：`from bisheng.knowledge.api.dependencies import get_knowledge_document_version_repository` 在 `3.0-vibe` 原文件上同样触发（已用 `git show 3.0-vibe:` 取原文复跑确认），本次未新增跨模块 `api/` import。
- **（预登记，随 T103 落地）两处对外可见的受控收紧**，design D6 已定案、理由与回滚条件在那里：① v2 `POST /filelib/retrieve` 对被 F066 `data_scope` 窄化的目标由 26044/403 改答 26321/404（AC-11 / AC-27 的存在性不泄露要求；`test_data_scope_matrix.py` 分类同批改）；② `RetrieveReq.max_content` 由无上限改为 `le=60000`（避免静默夹取）。两条都偏离 AC-25 字面的「对外契约保持兼容」，落地时把实际影响（有无存量调用方命中）补在本条下面。
- **（Line B 落地）`resolve_public_base_url` 从 `open_api/api/` 移到 `open_api/domain/services/`**。design D11 让 `dev_toolkit` 直接 import 前者，那是跨模块 API 层互相导入，arch-guard RULE-5 当场拦下（C1）。函数体一字未改，改的只是落点与四处 import（`skill_pack.py` / `personal_token_self.py` / `distribution.py` / `test_public_base_url.py`）。**F051 若也要在 whoami 加 `model_base_url`，合并时把那处 import 一并改到新路径**。
- **（Line B 落地）`open_api_execution_scope` 多一个可选 `prepare` 回调**，design D2 未写。`resolve_request_identity` 必须在租户 ContextVar 已装（它读库）且 actor 未构造（委托会改变 actor 是谁）之间跑；把这段推给调用方就等于把顺序拆散。MCP 面不传 `prepare`。
- **（Line B 落地）`identity:read` 没有 `endpoints` 条目**。它门控的是 MCP 工具而不是 REST 路由，所以 `test_scopes.py` 里「每个可签发的位都有端点」的断言把它与 `delegate` 一并排除，并在用例里写明理由。
- **（Line B 落地）停用用户按 `status: "disabled"` 返回，不当作不存在**。spec AC-14 的字段清单里有 `status`，藏起来会让这个字段永远只能是 `active`，并把查询者支去排查一个完全正确的 id。跨租户与不存在仍然同一响应（AC-32 未动）。
- **（Line B 落地）`ERROR_CATEGORY_MAP` 比 design D4 多映射 16164 / 16165 / 16166 / 16167**。它们和 16163 同类——是「这个应用确实是你的」的真实业务态，折进 26305 等于告诉开发者自己的应用不是自己的。
- **（Line B 未做）T211 fake 门面**。改用「延迟 import + `available()` 门控」后，①② 在门面缺席时根本不进清单，没有可自测的对象；真门面合入后 T301a 直接 spy 真类。多一个 fake 只多一份要跟着契约漂的代码。**合流波结案**：两线已合并、T301a 实跑，前提永久消失，T211 改勾 `[x]` 并在标题标「结案：不做」——它不该再出现在「哪些还没做」的检索里。
- **（合流波 `005e5f470`）T302 / T104 按「由谁决定」重新切分，而不是整块推给 CI 中间件**。原文把「标准客户端能不能接上」「撤销是否立刻生效」「两个门面是否递了同一份调用」「权限引擎挂了会不会降级返回」与「样本播种后集合是否相等」混在一起标 `@pytest.mark.e2e`。前四条完全由请求路径决定，本地可证且已证（`test/open_api/test_mcp_e2e.py` 4 条 + `test_retrieval_facade_equality.py` 加到 19 条）；只有最后一条真的需要 MySQL / Redis / OpenFGA / Milvus 同时在位。**新增文件不带 `e2e` 标记**——标了就默认被跳过，等于白写。
- **（合流波复核补齐）AC-44 的第三个门面「托管运行期」原先漏在参数化之外**。本任务第 129 行把 AC-44 的三处写成「门面 / v2 / MCP 工具 ①」，而 spec AC-44 点名的是「MCP 检索工具、v2 `POST /filelib/retrieve`、**托管运行期检索**」——门面是共用实现，不是门。漏掉的恰恰是唯一一个不直连门面的调用方：`CapabilityBusService.retrieve` 为了给 AC-55 能力台账补一行，**用 `except BaseErrorCode` 包住了门面调用**，「记一笔然后把已有结果返回去」只可能写在那里。参数化已补 `hosted_runtime`（真门面 + 真 `from_user`，只替掉声明读取与台账写入两个要库的协作者），该门面的台账行为本身由 `test/app_publish/test_capability_audit.py` 承接，此处不重复断言。
- **（合流波复核补齐）`test_mcp_e2e.py` 的 `REVOCATION_BOUND_SECONDS` 改为从 `app_credential_service` import**，不再本地重写 `= 5`。AC-05 与 F055 INV-28 是同一个 5 秒；抄一份会在真正的界限挪动后继续断言旧数字。
- **（合流波）T305 不再等 T303**。原「依赖: T303」会把契约表长期钉在「Spec 定稿」而实现侧已经有十一个文件、十一个错误码和三处审计 lockstep。改为先按当前取证回写，并把「T104 / T302 的集合相等」「T303 的 114 验证」作为未完项写进两张表；114 跑完只需改掉「未验」几项。
- **（合流波）`test/open_api/test_mcp_e2e.py` 里 `identity:read` 用例必须在服务边界打桩**。第一版让 `bisheng_org_tree` 真去够数据库，本地无中间件时 SQLAlchemy engine 被留在坏状态，**三个文件之后**的 `test_route_error_contract.py::test_child_tenant_key_is_not_mistaken_for_missing_account` 才炸（`Could not refresh instance '<ServiceAccount …>'`）。与 `test_mcp_scope_matrix.py` 的 `quiet_services` 注释记的是同一个坑，实测复现后改桩。**判回归必须跑整个 `test/open_api` 选择，单跑新文件是绿的。**

## 114 验证记录

- **（未执行）** 本切片在本地 worktree 内完成，没有 114 机器。下面是**照当前实现逐条核对过**的可执行清单（T303 的交付物就是把每条的实际输出填回本节）。**不要把这份清单当成验证结果**——一条都还没跑。

**前置**（`reference_remote_dev`）：先看 `linsight_session_version` 有没有 IN_PROGRESS、`free -m` 余量够不够，再 `bash /opt/bisheng-ops/deploy.sh`（默认 `BRANCH=3.0-vibe`）。114 的 `config.yaml` 已有 `open_platform.enabled: true`。**`health` 200 会骗人**：deploy 后先确认 `journalctl -u bisheng-api --since "2 min ago" | grep -i "alembic\|Traceback"` 干净，迁移失败会被 deploy.sh 掩盖。

| # | 验证 | 命令 | 期望 | AC |
|---|---|---|---|---|
| ① | 无凭据即拒 | `curl -s -o /dev/null -w '%{http_code}\n' -X POST http://192.168.106.114:4101/api/v2/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'` | `401`（不是 404、不是 307——裸路径不许重定向，design D1） | AC-02 |
| ①b | 裸路径不重定向 | 同上加 `-w '%{http_code} %{redirect_url}\n'` | 无 `redirect_url` | AC-01 |
| ② | 标准客户端接入 | `claude mcp add --transport http bisheng http://192.168.106.114:4101/api/v2/mcp --header "Authorization: Bearer <bs-sak-…>"` 然后在 Claude Code 里 `/mcp` | 工具清单与该密钥权限位一致；**再用纯 `mcp` python 客户端连一次**（`docs/api/mcp-server.md` 的示例），两者看到同一份清单 = AC-01 的「任何标准客户端」 | AC-01 |
| ③ | 检索不越权 | 用**非管理员 `shuiwu`** 名下的服务账号（只授 1 个知识空间、其中 1 个文件单独收权）调 `bisheng_knowledge_search` | 被收权的那个文件的片段**不出现**；指定一个未授予的空间 → `26321` 且与「库不存在」逐字相同 | AC-40, AC-11 |
| ③b | 两个门面同集合 | 同一把密钥、同 query 同 `knowledge_ids`，分别走 MCP 工具与 `POST /api/v2/filelib/retrieve` | 两边 chunk 集合相等（按 `document_id` + `chunk_index` 比） | AC-41 |
| ④ | 撤销 5 秒内生效 | 在管理界面撤销该密钥，**立刻**开始每秒调一次工具并记时间戳 | 首次拒绝距撤销 ≤ 5s（凭据缓存 TTL 上界，`OpenApiConf.cap_credential_cache_ttl`）；已建会话不得继续可用 | AC-05 |
| ⑤ | 运行时层未部署 | 在 `app_runtime.enabled: false` 的环境上 `/mcp` 看清单、并直调 `bisheng_app_status` | 两类应用工具不在清单；直调得 `16207`；其余四类不受影响 | AC-17, AC-38 |
| ⑥ | 审计落行 | `journalctl -u bisheng-api --since "10 min ago" \| grep open_api.mcp`；`select action,target_type,target_id,create_time from auditlog where action='open_api.mcp.tool_call' order by id desc limit 10;` | 每次 `tools/call` 一行，`target_type='mcp_tool'`；审计页事件名显示「MCP 工具调用」；**行内不得出现密钥明文或检索片段正文** | AC-07, AC-47 |

**必须用非管理员账号**：`super_admin` 短路 ReBAC，管理员跑 ③ 会全绿而权限运行时可能是坏的。**空列表也是 200**，③ 的判据是「该出现的出现了且该消失的消失了」，不是「有没有报错」。

## 跨 Feature 回写受理

> 别的 Feature 请求本 Feature 交付的增量，逐条记「谁请求 / 请求什么 / 交付没交付 / 在哪」。只追加。

| 请求方 | 请求内容 | 状态 | 交付物 |
|---|---|---|---|
| **F053**（接入信息区 T046） | MCP 接入地址 | ✅ 已交付 | `GET /api/v1/dev-toolkit/versions` 的 `mcp: {url, transport, auth}`；同批留了 `model: null` 槽位给 F051 |
| **F056**（审计查询面） | MCP 调用的审计行 | ✅ 已交付 | `action="open_api.mcp.tool_call"` / `target_type="mcp_tool"`，三处 lockstep 已登记，审计页事件名「MCP 工具调用」 |
| **F055**（发布面）/ **F054**（详情页） | `get_publish_status` / `get_instance` 加 `entry` 形参 | ✅ 已交付 | 两处均为可选形参、缺省 `"detail"`，既有调用方行为逐字不变 |

---

## 审查修订记录（`/sdd-review`，2026-09-16）

> 对 design.md 跑 design 审查（24 条清单 + Constitution Check）、对本文跑 tasks 审查（21 条清单），全部 `文件:行号` / 符号名重新 grep 核实。design 侧的改动明细见 design.md 修订历史末行；下面只记**改到本文**的。

| # | 严重度 | 问题 | 修订 |
|---|---|---|---|
| 1 | high | T103 / T103a 写「`test_data_scope_matrix` 必须仍绿」——**不可能**：门面改走批量判定后，被 `data_scope` 窄化的目标由「抛 26044」变成「返回 False → 26321」（`permission_action_service.py:328-333` 的批量语义），而 AC-11 / AC-27 又要求它与「库不存在」同一响应 | 改成「分类必须从 `"raise"` 改为 `"unreachable"` 并补断言」，并把这条登记进「实际偏差记录」的预登记项 |
| 2 | high | T209 按**假设**签名接线 F054 `AppDataService`（`get_schema` / `read_rows` / `pk` / `entry`），与 data-plane 切片**已实现**的真实签名（`get_table_schema` / `get_rows` / `key` / 无 `entry`、owner-only 内建、16162 / 16163）不符 | 按只读核实的真实签名重写 T209，写清来源 worktree 与「不给 F054 加 `entry`、不在工具层重复判 owner」 |
| 3 | high | T203 用 `app.mount`——`Mount` 的路径正则要求尾斜杠，裸 `/api/v2/mcp` 会被 `redirect_slashes` 回 307 | 改为精确 `Route` + 三步装配顺序；T203a 加 `test_bare_path_is_not_redirected` |
| 4 | high | T203a 只断言 `isError`，漏掉 `Tool.run` 把三要素 JSON 重包成 `Error executing tool …: {…}`（坑 19） | 加 `test_tool_error_text_is_parseable_json`；T203 逻辑里写死 `except ToolError` 的 `__cause__` 解包 |
| 5 | medium | `max_content` 无上限，门面夹取对 v2 是静默收窄（违反 spec §3「截断必须可见」而 `RetrieveResp` 无承载字段） | T103 加 `le=60000`，T103a 加 422 用例 |
| 6 | medium | T103a 用了不存在的 `v2_client` fixture（`test/open_api/conftest.py` 只有 `open_api_db` / `fake_redis` / `audit_events`） | 改指本目录既有的 `AsyncClient(transport=ASGITransport(app=app))` 范式并给出参照文件 |
| 7 | medium | T201a 没覆盖拆分带来的**顺序**变化（租户 ContextVar 与 PAT 策略读） | 加 `test_pat_policy_read_happens_with_tenant_contextvar_installed` |
| 8 | medium | T212 用 `len(TOOL_REGISTRY) × 5` 做分母，工具分批上线期间恒红 | 分母改 `available()` 过滤后的集合，另加一条「每个注册项都被矩阵覆盖」 |
| 9 | medium | T001 没说清动 `docs/constitution.md` 的哪几处、也没说新断言会不会撞 `test_error_codes.py` 既有两条 | 两处都写明（C5 `:128` 段位表 + `:135` 后补「263 is assigned」+ 文件头模块计数；既有断言只覆盖 260 段，新增写成第三个函数） |
| 10 | medium | AC-13 / AC-15 的唯一覆盖任务被上游阻塞，追溯表看不出来 | AC 追溯表顶部加「45 / 47，两条随 F051 / F054 补验」的口径说明 |
| 11 | low | T104 编号在 Line A、依赖却指向 Wave C 的 T301 | 补「执行位置」一行 |
| 12 | low | T203 的路由矩阵改法写成「`:37-41` 与 `actual_v2_routes :25-35` 都改」——后者本来就有 isinstance 过滤 | 改为只动 `test_every_real_v2_route_is_globally_key_protected_and_marked :36-41` |
| 13 | low | 若干行号 / 符号名（`check-i18n.mjs:106`、`deploy.py:206-211`、`add_tool` 签名、`streamable_http_client` 的 `http_client` 参数等） | 逐条订正 |

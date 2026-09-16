# Tasks: 模型协议直连面（OpenAI 兼容子集 + `model:invoke` + 逐条调用审计）

**关联规格**: [spec.md](./spec.md)（36 条 AC，What 的唯一真相）· [design.md](./design.md)（How 的唯一真相，K1–K13 / D1–D14 / 坑 1–18 / §4.2 契约）
**版本**: v3.0.0
**纵切**: 不在 [mvp-114-path.md](../mvp-114-path.md) 上；Wave 1–5 可在本地全部完成，Wave 6 依赖 F055 / F054，Wave 7 需 114
**代码事实口径**: 本文所有 `文件:行号` 沿用 design.md（`3.0-vibe` HEAD `fe10f75ea`，2026-09-16 核实，路径以 `src/backend/bisheng/` 为根；`locales/` = `src/frontend/packages/locales/src/`）。行号会漂移，符号名不会——落地前以符号名重定位。

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-08-17 定稿（决议 1–8 全自动模式定案，同日审查 16 条修订） |
| design.md | ✅ 已评审（2026-09-16，`/sdd-review design` 两轮） | 用户豁免 ★，D1–D14 标「全自动模式定案」；接手时的第一入口。二轮发现 AC-27 底座缺口 → 新增 26205 / 坑 18 |
| tasks.md | ✅ 已拆解并评审（2026-09-16，`/sdd-review tasks`） | 本文 |
| 实现 | 🚧 进行中 | **24 / 30 完成**（2026-09-16：Wave 1–5 全部落地 T001–T021；**Wave 6 的 T022 / T023 / T024 于同日解除阻塞并落地**——F055 T055 / T056 与 F054 `verify_obo_token` 均已合入 `3.0-vibe`，三者由 `app_publish/composition.py:register()` 一并注册；余下 T025 与 Wave 7 T026–T029 全部需要 114）。同日复核并修正 6 处（见「实际偏差记录」8–13），Wave 6 的核实见 15–18。本地用例 131 → **`test/open_api` 739 → 760 passed / 3 skipped**（新增 `test_model_gateway_hosted_app.py` 21 条；739 为主检出 `3.0-vibe` 同选择基线）、**`test/app_publish` 655 → 660 passed**（同样对主检出基线）。本地证据：`ruff check` / `ruff format --check` 对本切片文件零输出，`arch-guard.sh` 零输出。偏差处理见 design.md 顶部调整原则 + `docs/SDD-Guide.md` §3-§4 |

---

## 开发模式

**按 Wave 组织任务**：Wave 1 基础设施（无测试配对）→ Wave 2 目录与解析（`llm` 域）→ Wave 3 协议面（路由 / 错误体 / 流式）→ Wave 4 逐条记录 → Wave 5 base URL 契约与官方客户端契约测试 → **Wave 6 托管应用路径（阻塞于 F055 T055 / T056、F054 OBO 验签）** → Wave 7 114 E2E 与引擎适配。每个任务标 `依赖:`，无依赖的可并行。

**后端 Test-First**：测试任务先于配对实现任务；`覆盖 AC` 逐条写全 id（禁范围写法）。单测放 `src/backend/test/open_api/` 与 `src/backend/test/llm/`（不放 `test/` 根），`asyncio_mode=auto`。fake `BishengLLM` 与 fake catalog 在 T005 一次建好，其后测试不再各造。集成用例连 CI 中间件；DM8 用例在 105 回归。

**HTTP 状态断言口径**（design K2 / D4）：本面路径断言**真 HTTP 状态 + OpenAI 错误体** `{"error":{...,"bisheng_code":N}}`；其它 `/api/v2` 路径仍断言信封（T012 含一条"邻居不受影响"用例）。

**前端**：本 Feature 无界面任务；三语 `api_errors` 文案（K13）与 `whoami` 字段是唯一前端侧改动。

**自包含任务**：每个任务内联文件、逻辑、AC 覆盖；设计论证指向 design §X 不复制。

**执行顺序 ≠ 编号**：T005（fake 夹具）应在 T006 / T007 之前跑通；T009（catalog 实现）会同时改 `llm.py` 与 `llm_server.py`，与 T006（typed 异常，同在 `llm/domain/utils.py`）合成一个 PR 提交以减少 `llm` 域两次 review。

**工时口径**：括号内为估算人时；合计 ≈ 101h / 30 个任务（其中 Wave 6 ≈ 12h 要等上游；Wave 7 ≈ 8h 需 114）。

**跨 Feature 副作用登记**（release-contract 表 1 / 检查项 17）：
- **T006**（`llm/domain/utils.py:126/136` 裸 `Exception` → `LlmProviderDailyLimitExceededError(Exception)`；`common/constants/enums/telemetry.py` `ApplicationTypeEnum` 加 `MODEL_GATEWAY`）—— `llm` 域共享 util 与遥测枚举；同基类同 message，既有 `except Exception` 与统计页零感知；统计页按类型筛选会多出一项。
- **T009**（`llm/domain/services/llm.py:419-453` 抽 `acollect_visible_server_ids`；`llm/domain/models/llm_server.py:492` `aget_shared_server_ids_for_leaf(raise_on_error=False)`）—— `get_all_llm` 行为不变（T008 含回归断言）；新 kw 默认值保持旧行为。
- **T007**（`open_api/domain/scopes.py:139-147` `model:invoke` 翻 issuable + 端点登记）—— 签发表单在 `open_platform.enabled` 下开始展示该位（F049 AC-13 语义），**位本身的三语文案已存在、不必补**；**六条**既有测试同批改（design D12 清单，其中 `test_scopes.py:44-51` 连函数名一起改、`test_scopes.py:35-41` 刻意不动）。
- **T004**（`open_api/domain/services/call_audit_service.py` 重构为 `BatchedRecordWriter` 子类；`main.py:108/154` lifespan 增一对起停）—— 公开名 / 常量 / 行为不变，`test/open_api/test_call_audit*.py` 既有用例必须原样通过。
- **T013**（`open_api/api/exception_handlers.py` 增本面前缀分支两处；`api/router.py:149-166` 条件挂载）—— 其它 v2 路径体形状不变（T012 断言）。
- **T001**（`docs/constitution.md` C5 表 + `release-contract.md` 已分配模块编码）—— 登记 262。
- **T005**（`test/open_api/conftest.py` 收编 `open_platform_enabled` / `open_platform_disabled`；`test/open_api/test_scope_issuability.py:36-42` 删本地定义）—— 共享测试夹具，既有用例零改动（fixture 名不变，只换供给位置）。
- **T023**（`bisheng/app_runtime/domain/services/obo_token.py` 新建、`entry_authz_service.py:379-426` 抽常量与签发逻辑）—— **改的是 F054 领域对象**：`OBO_AUDIENCE`（`entry_authz_service.py:78`）已是模块级常量，抽取必须保持签发侧字节级等价（app-proxy 已发出的 OBO 令牌要继续验得过），实现 PR 由 F054 出或本 Feature 代出后由 F054 review。
- **T020**（回写 F054 `contracts-runtime-manager.md §5`、F053 design §6.2 表、F055 design D13 环境变量名）—— 只加名不改既有名。
- **依赖上游任务 ID**：F055 **T055**（`hosted_app` 主体解析器 + CHECK 放宽迁移，**✅ 2026-09-16 已落地**）· **T056**（注册 `HostedAppDeclarationPort`、凭据 `scopes` 含 `model:invoke`、`BISHENG_APP_TOKEN`，**✅ 已落地**）· F054（OBO 验签实现 + runtime-manager 注入三名，无任务号，见 F054 tasks 追加项；**✅ 验签已落地**，入口侧 fail-open 仍在 F054 手上，见偏差 18）· F056（查询面接线）· F052 / F055 T060（消费 `model_catalog`）。

---

## Tasks

### Wave 1 · 基础设施（无测试配对，排最前）

- [x] **T001**: 错误码 262 段 + C5 / release-contract 登记 + 三语文案（3h）
  **文件**: `src/backend/bisheng/common/errcode/model_face.py`（新）, `docs/constitution.md`（C5 表 `26x–27x` 行加 `262 model_face`，并加一段「262 is assigned」子段说明，同 260 段体例）, `features/v3.0.0/release-contract.md`（「已分配模块编码」加 262 行，Owner F051）, `src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`（三语视为一组）
  **逻辑**: 按 design D11 定义 `ModelFaceError(OpenApiAuthError)`（类属性 `http_status / openai_type / openai_code`，**`Code: int = 262xx` 写法**，K13）与本期码：26201 / 26202 / 26203 / 26204 / **26205**（`ModelFaceIdentityHeaderRefusedError`，403，坑 18）· 26211 / 26212 / 26213 / 26214（`candidates` kwarg）/ 26215 / 26216 / 26217 · 26231 / 26232（实例级 `http_status`）/ 26233 / 26234。三语 message 面向 agent 可读（26202 原文「本版仅提供 OpenAI 兼容面」；26214 提示「请使用限定名 服务商名/模型名」；26205 提示「本面不承载委托，请去掉 X-End-User / X-On-Behalf-Of 头」）。文件名是 `en.json` 不是 `en-US.json`（那是 `platform/public/locales/` 的目录命名）。跑 `pnpm check-i18n`（`src/frontend/`）确认新码全部有文案、生成物不手改。
  **依赖**: 无
  **完成证据**: `common/errcode/model_face.py`（`ModelFaceError` + 16 个码，一律 `Code: int =` 写法，故 `check-i18n` 真的能看到）；三语文案落 `packages/locales/src/api_errors/{zh-Hans,en,ja}.json` 并跑 `node scripts/build.mjs` 重生成产物；`docs/constitution.md` C5 表 + 「262 is assigned」段、`release-contract.md` 已分配模块编码表各加一行。

- [x] **T002**: 请求 / 响应 schemas（3h）
  **文件**: `src/backend/bisheng/open_api/domain/schemas/model_gateway.py`（新）
  **逻辑**: pydantic v2：`ChatCompletionRequest`（design D8 字段清单，`extra="allow"`，`messages` `min_length=1`，`n` 只允许 1，`stream_options.include_usage`）/ `ChatCompletionMessage` / `ToolCall` / `ChatCompletionChoice` / `Usage` / `ChatCompletionResponse(object="chat.completion")` / `ChatCompletionChunk(object="chat.completion.chunk")` / `ModelObject(id, object="model", created, owned_by, bisheng_model_type, bisheng_qualified_name)` / `ModelList(object="list", data)` / `OpenAIErrorBody(error: {message,type,code,param,bisheng_code, candidates?})`。响应模型序列化用 `exclude_none=False`（OpenAI 客户端接受 null 字段），`reasoning_content` 为 `None` 时**不输出**（单独 `exclude_none` 的字段级处理）。
  **依赖**: 无
  **完成证据**: `open_api/domain/schemas/model_gateway.py`；`ChatCompletionRequest.forwarded_kwargs()` 把枚举字段与 `model_extra` 一起透传，`test_openai_codec.py::test_enumerated_and_unknown_request_fields_are_both_forwarded` 守住。

- [x] **T003**: `model_call_record` ORM + Repository（4h）
  **文件**: `src/backend/bisheng/open_api/domain/models/model_call_record.py`（新）, `src/backend/bisheng/open_api/domain/models/__init__.py`（**必改**）, `src/backend/bisheng/open_api/domain/repositories/model_call_record_repository.py`（新）
  **逻辑**: 表按 design §4.2 ④（`SQLModelSerializable`，`BigInteger` 主键，`VARCHAR` 不用 `CHAR`，`create_time` 用 `sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))`——**不用 `func.now()`**，与 `api_credential.py:82` 一致、双 DB 已验证；三条索引 D9）。**`__init__.py` 必须加 `from ... import ModelCallRecord` 与 `__all__` 条目**（坑 17：`_TENANT_AWARE_MODEL_MODULES` 登记的是**包名** `"bisheng.open_api.domain.models"`，`core/database/tenant_filter.py:107`，发现全靠包 `__init__` 的显式 import 链——漏了就是 `create_all` 不建表 + 租户过滤不覆盖，两个都静默）；加一条 `test_database_contract.py` 风格断言 `"model_call_record" in SQLModel.metadata.tables`。Repository：`ainsert_batch(rows)`（一个 session `add_all` + 单次 commit；行显式带 `tenant_id`）/ `alist(tenant_id, *, credential_id, app_id, time_from, time_to, cursor, limit)`（排序 `(create_time DESC, id DESC)`，游标 `(create_time, id)` 编码为 base64 字符串）/ `aiter_export(...)`（同条件按游标翻页的 async 生成器）。**禁**批量 UPDATE / DELETE。
  **回滚**: 新表无 Alembic；回滚 = 删表（本 Feature 前无数据）。
  **依赖**: 无
  **完成证据**: `open_api/domain/models/model_call_record.py` + `models/__init__.py` 已加 import/`__all__`（坑 17）；`repositories/model_call_record_repository.py` 提供 `ainsert_batch / alist / aiter_export`，排序 `(create_time DESC, id DESC)`、游标含 id；`test_model_call_record.py::test_paging_is_stable_when_rows_share_a_second` 用 20 行同秒数据断言两页拼接 == 全序。

- [x] **T004**: `BatchedRecordWriter` 泛化 + `ModelCallRecordWriter` + lifespan（4h）
  **文件**: `src/backend/bisheng/open_api/domain/services/batched_writer.py`（新：`BatchedRecordWriter[T]`，构造参数 `max_queue_size / batch_size / flush_interval_seconds / name / write_batch: Callable[[list[T]], Awaitable[None]]`，方法 `enqueue / start / stop / flush_now`，逻辑逐行搬自 `call_audit_service.py:18-108`）, `src/backend/bisheng/open_api/domain/services/call_audit_service.py`（改为子类；`AUDIT_*` 常量与 `open_api_call_audit_service` 单例名不变）, `src/backend/bisheng/open_api/domain/services/model_call_record_writer.py`（新：队列 5000 / 批 200 / 1s，`write_batch=ModelCallRecordRepository.ainsert_batch`；失败 `logger.error("open_api.model_call_record.write_failed | reason=…")` + `emit_metric("model_call_record", status="dropped", …)`）, `src/backend/bisheng/main.py`（`:108` 旁 `model_call_record_writer.start()`，`:154` 旁 `await model_call_record_writer.stop()`）
  **逻辑**: design D9。既有 `test/open_api/` 中审计写入器用例必须原样通过（重构不改行为）。
  **依赖**: T003
  **完成证据**: `open_api/domain/services/batched_writer.py`（泛型基类，逻辑逐行搬自审计写入器）；`call_audit_service.py` 改为子类、公开名与常量不变，既有 `test_call_audit.py` 原样通过；`model_call_record_writer.py` 队列 5000 / 批 200 / 1s，掩码批内水合；`main.py` lifespan 起停。

- [x] **T005**: 测试夹具：fake `BishengLLM` / fake catalog / ASGI `openai` 客户端（4h）
  **文件**: `src/backend/test/open_api/model_gateway_fixtures.py`（新）, `src/backend/test/open_api/conftest.py`（追加 fixture 引用；顶层不 import 尚未存在的实现模块，fixture 体内惰性 import）
  **逻辑**: `fake_llm_factory(script)`：返回对象，`astream` 按脚本 yield `AIMessageChunk`（支持 content / `reasoning_content` / `tool_call_chunks(index=None)` / 末块 `usage_metadata` / 中途抛异常 / 抛 `LlmProviderDailyLimitExceededError`），`ainvoke` 返回 `AIMessage`，`bind` 记录 `tools / tool_choice` 并返回自身；`monkeypatch LLMService.get_bisheng_llm`。`catalog_rows`：构造 `LLMServer` / `LLMModel` 行（含跨服务商同名、下线、embedding 类型、他租户、服务器已删）写入 `open_api_db`（沿用 `conftest.py:28`）。`credential_with_scopes(scopes)`：经 `CredentialService.issue` 签发返回明文。`openai_client(app, api_key)`：`openai.AsyncOpenAI(base_url="http://test/api/v2/model/v1", api_key=..., http_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app)))`。**`open_platform_enabled` / `open_platform_disabled` 今天是 `test/open_api/test_scope_issuability.py:36-42` 的模块内 fixture，本任务把这两个 fixture 原样搬到 `test/open_api/conftest.py`**（原文件删掉定义、靠 conftest 注入，既有用例零改动），供本面各测试与 D3 的开关用例复用。代理 env 清理沿用既有 autouse。
  **依赖**: 无
  **完成证据**: `test/open_api/model_gateway_fixtures.py`（fake `BishengLLM` / catalog 行 / 独立 app 工厂 / 记录捕获 / chunk 构造器）；`open_platform_enabled` / `open_platform_disabled` 已从 `test_scope_issuability.py` 提升到 `test/open_api/conftest.py`，原文件删定义、既有用例零改动。

- [x] **T006**: typed 日上限异常 + `ApplicationTypeEnum.MODEL_GATEWAY`（1h）
  **文件**: `src/backend/bisheng/llm/domain/utils.py`（`:126 / :136`：`raise LlmProviderDailyLimitExceededError(f"...")`，新类定义于同文件顶部、继承 `Exception`）, `src/backend/bisheng/common/constants/enums/telemetry.py`（`ApplicationTypeEnum.MODEL_GATEWAY = "model_gateway"`）
  **逻辑**: design D13 / 坑 4。`grep -rn "Quota used up" src/backend` 确认无字符串匹配的调用方。
  **依赖**: 无
  **完成证据**: `llm/domain/utils.py` 两处裸 `Exception` 改 `LlmProviderDailyLimitExceededError`（同基类同 message，既有 `except Exception` 零感知）；`ApplicationTypeEnum.MODEL_GATEWAY` 已加；`test_model_gateway_stream.py::test_the_daily_provider_limit_is_a_real_429_not_half_a_stream` 断言它映射成 26217。

- [x] **T007**: `model:invoke` 翻 issuable + 端点登记 + 既有测试同批改（2h）
  **文件**: `src/backend/bisheng/open_api/domain/scopes.py`（`:139-147`：`endpoints` 填 `("POST", "/api/v2/model/v1/chat/completions")`、`("GET", "/api/v2/model/v1/models")`、五个方法 × `"/api/v2/model/v1/{rest}"`；删 `issuable=False` 行，**`requires_open_platform=True` 保留**）, `src/backend/test/open_api/test_scope_issuability.py`, `src/backend/test/open_api/test_scopes.py`, `src/backend/test/open_api/test_open_api_route_matrix.py`
  **逻辑**: design D12 的**六条受影响测试清单**，逐条落实：① `test_scope_issuability.py:66-69` 参数化只留 `identity:read`，新增 `test_model_invoke_issuable_once_open_platform_on`；② 同文件 `:176` 改 `assert "identity:read" not in codes and "model:invoke" in codes`；③ 同文件 `:4` 模块 docstring 去掉 `model:invoke`；④ `test_scopes.py:44-51` **函数改名**为 `test_app_manage_and_model_invoke_become_issuable_with_open_platform`，`:49` 与 `:50`（`codes == ALWAYS_ISSUABLE_OPEN_API_SCOPE_CODES | {"app:manage"}`）**两条断言都要改**；⑤ `test_scopes.py:35-41`（开关关闭态）**不要动**——`requires_open_platform=True` 仍把它挡在 `issuable_scopes()` 外（`scopes.py:201`）；⑥ `test_open_api_route_matrix.py` 按 D3 末段改为「开关为假时从**期望集合**剔除 `MODEL_GATEWAY_PATH_PREFIX` 前缀下的操作」，不要试图 `monkeypatch` 开关（坑 13：`api/router.py:140` 在 import 时求值，`from bisheng.main import app` 拿到的是进程启动时的挂载结果）。
  **不需要做的**：`openApiManagement.scopes.model_invoke.{label,desc}` 三语文案**已存在**于 `platform/public/locales/{zh-Hans,en-US,ja}/bs.json`（已核实），翻 issuable 后签发表单直接有文案，本任务不碰 i18n。
  路由矩阵测试在本任务会因路由尚不存在而红——**允许**，T013 落地后转绿（本任务 PR 与 T013 同批合入，或先标 `xfail(strict=True)`）。
  **依赖**: T005
  **完成证据**: `scopes.py` 的 `model:invoke` 删 `issuable=False` 并登记七条端点（两条承诺面 + catch-all 五方法）；design D12 六条受影响测试逐条落实（`test_scope_issuability.py` 参数化/断言/docstring、`test_scopes.py` 函数改名 + 两条断言 + `issuable_scopes()` 分组列表、`test_open_api_route_matrix.py` 期望集合按开关剔除）；`test_scopes.py:35-41` 按设计刻意未动。

### Wave 2 · 目录与名称解析（`llm` 域，Test-First）

- [x] **T008**: `model_catalog` 单元测试（4h）
  **文件**: `src/backend/test/llm/test_model_catalog.py`（新）
  **逻辑**: `test_list_callable_only_llm_and_online`（embedding / rerank / 下线不出现）→ AC-09；`test_root_shared_server_visible_to_child`（子租户目录含 FGA `shared_with` 的 Root 服务器模型；Root 租户只见自有）→ AC-09；`test_other_tenant_model_invisible` → AC-13；`test_exact_name_unique_resolves` / `test_exact_name_with_slash_prefers_bare_match`（`model_name` 本身含 `/`）→ AC-11；`test_ambiguous_bare_name_26214_lists_qualified`（跨服务商同名 → `candidates == {"A/x","B/x"}`）→ AC-12；`test_qualified_name_resolves_when_unique_and_when_ambiguous` → AC-12；`test_offline_26212_vs_missing_26211_vs_provider_deleted_26213` → AC-13；`test_non_llm_type_is_26211`（不透露类型）→ AC-13；`test_list_ids_qualified_only_for_ambiguous_rows` → AC-10 / AC-12；`test_cache_ttl_bounded_60s`（`monkeypatch settings.open_api.model_catalog_ttl_seconds=61` → 校验器夹到 60；缓存命中后下线模型仍可解析、`ttl` 过后 26212）→ AC-14；`test_fga_failure_raises_26216_not_narrower_set`（`monkeypatch get_permission_relation_api` 抛 → 26216；断言**未**返回仅自有服务器的集合）→ AC-35；`test_get_all_llm_unchanged_after_helper_extraction`（同一数据下 `get_all_llm` 返回集合与抽取前快照一致）→ 回归；`test_hosted_range_intersection`（`range=ModelRange(declared={"x"})` 时 `y` → 26215、`x` 下线 → 26212）→ AC-34。
  **覆盖 AC**: AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-34, AC-35
  **依赖**: T001, T005, T006
  **完成证据**: `test/llm/test_model_catalog.py` 18 passed（复核后：假 DAO 改为按 `server_ids` 过滤，「服务商已删」一条拆成三条真实用例，偏差 8）。

- [x] **T009**: `model_catalog` 实现 + `get_all_llm` helper 抽取 + fail-closed 参数（6h）
  **文件**: `src/backend/bisheng/llm/domain/services/model_catalog.py`（新：`CallableModel` / `ModelRange(kind: Literal["tenant","declared"], declared: frozenset[str] | None)` / `ResolvedModel(model_id, server_id, model_name, server_name, server_type, qualified_name)` / `list_callable_chat_models(tenant_id)` / `resolve_model_name(tenant_id, requested, *, range=None)` / `invalidate_catalog(tenant_id)`；进程内 `TTLCache(maxsize=256, ttl=settings.open_api.model_catalog_ttl_seconds)`，只缓存成功；`emit_metric("model_catalog", status=hit|miss|unavailable)`）, `src/backend/bisheng/llm/domain/services/llm.py`（`:419-449` 抽 `acollect_visible_server_ids(tenant_id, *, raise_on_error=False) -> list[int]`；`get_all_llm` 改调、行为不变）, `src/backend/bisheng/llm/domain/models/llm_server.py`（`:492` `aget_shared_server_ids_for_leaf(leaf_id, *, raise_on_error: bool = False)`，`True` 时重抛）, `src/backend/bisheng/core/config/open_platform.py`（`OpenApiConf.model_catalog_ttl_seconds: int = 30`，校验器夹到 `[1, 60]`）
  **逻辑**: design D5 解析四步 + D6 集合与缓存；`range.kind == "declared"` 时先按租户集合解析（得到唯一模型）再判 `qualified_name ∈ declared or model_name ∈ declared`，否则 26215——保证「已收回」与「未声明」的判序：下线先于未声明（spec §3 末段）。
  **测试**: T008 全部通过
  **覆盖 AC**: AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-34, AC-35
  **依赖**: T008
  **完成证据**: `llm/domain/services/model_catalog.py`（`CallableModel` / `ModelRange` / `ResolvedModel` / `list_callable_chat_models` / `resolve_model_name` / `invalidate_catalog`，进程内按租户 TTL 缓存、只缓存成功）；`llm.py` 抽出 `acollect_visible_servers` / `acollect_visible_server_ids`，`get_all_llm` 改调、行为不变；`llm_server.py` 的 `aget_shared_server_ids_for_leaf` 增 keyword-only `raise_on_error`（默认 False 保持旧行为）；`OpenApiConf.model_catalog_ttl_seconds` 默认 30、校验器夹到 60。

- [x] **T010**: `ModelRangePolicy` + 两个 Port 单元测试（2h）
  **文件**: `src/backend/test/open_api/test_model_range_policy.py`（新）
  **逻辑**: `test_service_account_tenant_range_subject_self` → AC-04 / AC-09；`test_service_account_with_access_token_header_26204`（头存在即拒，值任意）→ AC-22；`test_end_user_header_refused_26205_for_every_actor_kind`（服务账号与 hosted_app 各一例，值合法，断言在读任何 Port 之前就抛——坑 18）→ AC-27；`test_identity_header_check_precedes_access_token_check`（同时带 `X-End-User` 与坏的 `X-BiSheng-Access-Token` → 得 26205 而非 26204，锁住判定序）→ AC-27；`test_natural_person_tenant_range`（结构上可达即可，PAT 无 `model:invoke` 由 T012 覆盖）；`test_hosted_app_without_declaration_port_26216`（默认 Port fail-closed）→ AC-35；`test_hosted_app_declared_range_and_subject_user_when_token_valid`（fake 两个 Port）→ AC-21 / AC-34；`test_hosted_app_no_token_subject_app_self` → AC-21；`test_hosted_app_invalid_token_26204` → AC-21；`test_registration_replaces_default_port`。hosted_app 用例以 `OpenApiPrincipal.model_construct(actor_kind="hosted_app", …)` 绕过 Literal（F055 T055 落地后改为正常构造，见 T022）。
  **覆盖 AC**: AC-04, AC-09, AC-21, AC-22, AC-27, AC-34, AC-35
  **依赖**: T005
  **完成证据**: `test/open_api/test_model_range_policy.py` 14 passed（复核补 `test_a_forged_token_is_refused_even_when_the_declaration_is_unreadable`，偏差 9）。

- [x] **T011**: `ModelRangePolicy` + Port 定义与默认实现（3h）
  **文件**: `src/backend/bisheng/open_api/domain/services/model_range_policy.py`（新：`HostedAppDeclarationPort` / `AccessSubjectVerifierPort` Protocol、`AccessSubject`、`ResolvedSubject(subject_kind, subject_id)`、`register_hosted_app_declaration_port` / `register_access_subject_verifier`、`resolve_range_and_subject(principal, headers) -> tuple[ModelRange, ResolvedSubject]`；常量 `ACCESS_TOKEN_HEADER = "X-BiSheng-Access-Token"`）
  **逻辑**: design D7 的**四步判定序**，顺序不可换：① `headers.get("X-End-User") is not None` → `ModelFaceIdentityHeaderRefusedError`（26205，全部 `actor_kind` 一视同仁，坑 18）；② 访问凭据头判定（服务账号存在即 26204 / 托管应用验签失败即 26204）；③ 范围确立（Port 不可用 → 26216）；④ 交给 `model_catalog` 解析。默认 Port：声明读取抛 → 26216；验签恒 `None`。
  **测试**: T010 全部通过
  **覆盖 AC**: AC-04, AC-09, AC-21, AC-22, AC-27, AC-34, AC-35
  **依赖**: T010, T009
  **完成证据**: `open_api/domain/services/model_range_policy.py`，四步判定序按 design D7 固定，`test_identity_header_is_judged_before_the_access_token` 锁住顺序；两个 Port 默认实现 fail-closed。

### Wave 3 · 协议面：路由、错误体、开关、流式（Test-First）

- [x] **T012**: 鉴权穿透 / 错误体 / 承诺面外 / 开关 集成测试（5h）
  **文件**: `src/backend/test/open_api/test_model_gateway_auth.py`（新）, `src/backend/test/open_api/test_model_gateway_errors.py`（新）, `src/backend/test/open_api/test_model_gateway_switch.py`（新）
  **逻辑**: **auth**：无凭据 → 401 `error.type=="authentication_error"` `bisheng_code==26001`；改一位 → 401 26002；只持 `chat:invoke` → 403 26003 且 `message` 含 `model:invoke`（`/models` 与 `/chat/completions` 都断）→ AC-06；持 `model:invoke` 的密钥打 `/api/v2/workstation/chat/completions` → 403 26003（互不蕴含反向）→ AC-06；编辑密钥补位后同一明文立即通过 → AC-07；撤销后 ≤ 3s 401 且 `/models` 无数据 → AC-05；持 `delegate` → 403 26051 `code=="delegate_only_credential"`（承诺面与 catch-all 都断，坑 7）→ AC-26；**身份头四例逐一断言（坑 18，本面最容易漏的一组）**：`X-On-Behalf-Of: 9`（密钥无 `delegate`）→ 403 26004；`X-End-User: abc`（**合法值、单独出现**）→ 403 **26205** `code=="identity_header_not_accepted"`（若不加本面拒绝，底座会 200 放行并把 `end_user_id` 记成 `abc`）；两头同时出现 → 26010；`x-foo-on-behalf-of` 旧式头 / body 里 `user_id` → 26019；**四例都断言 fake LLM 的 `astream` / `ainvoke` 零调用**且 `model_call_record` 零行 → AC-27；PAT（`knowledge:read`）→ 403 26003。**errors**：`RequestValidationError`（`messages=[]`）→ 400 26203 `param=="messages"`；`n=2` → 26203；`/embeddings` POST / `/responses` / `/images/generations` / `/audio/speech` / `/files` GET → 404 26201 `code=="endpoint_not_supported"` → AC-02；`/messages` POST → 404 26202 → AC-03 / AC-32；上述均无凭据时先 401 → AC-05；**邻居不变**：`/api/v2/auth/whoami` 无凭据仍返回信封 `{status_code:26001,...}`；被拒路径 `audit_log` 有 `open_api.call` 行、`model_call_record` 无行 → AC-20。**switch**：`open_platform.enabled=False` 下用独立 app 工厂 / `importlib.reload(bisheng.api.router)` 构建 → `/api/v2/model/v1/models` 与 `/chat/completions` 均 404 `{"detail":"Not Found"}`（有无凭据同）→ AC-28；`True` 下不依赖任何 runtime-manager / app-proxy 配置即可 200 → AC-29。
  **覆盖 AC**: AC-02, AC-03, AC-05, AC-06, AC-07, AC-08, AC-20, AC-26, AC-27, AC-28, AC-29, AC-32
  **依赖**: T005, T007, T001
  **完成证据**: `test_model_gateway_auth.py` 14 passed · `test_model_gateway_errors.py` 18 passed · `test_model_gateway_switch.py` 4 passed（复核补 AC-06 反向蕴含与 Anthropic `v1/messages` 拼法，偏差 11 / 13）。

- [x] **T013**: 路由 / catch-all / 条件挂载 / OpenAI 错误体分支（5h）
  **文件**: `src/backend/bisheng/open_api/api/endpoints/model_gateway.py`（新：`router = APIRouter(prefix="/model/v1", tags=["OpenAPI","Model"])`；`POST /chat/completions`、`GET /models`、`api_route("/{rest:path}", methods=[...])` 三者均 `@open_api_scope("model:invoke", modes=("S",))` + `Depends(get_open_api_execution)`；`/models` 与 `/chat/completions` 挂 `response_model`），`src/backend/bisheng/open_api/api/router.py`（新 `model_gateway_router` 导出）, `src/backend/bisheng/api/router.py`（`:166` 后 `if settings.open_platform.enabled: router_rpc.include_router(model_gateway_router)`）, `src/backend/bisheng/open_api/api/exception_handlers.py`（新 `MODEL_GATEWAY_PATH_PREFIX = "/api/v2/model/v1"`、`_is_model_gateway_path(conn)`、`render_openai_error(exc) -> JSONResponse`（D4 映射表：`ModelFaceError` 直接读 `openai_type/openai_code`；`OpenApiAuthError` 其它码与权限族按表；`RequestValidationError` → 26203）；在 `_register_v2_handler.dispatch` 与 `open_api_auth_exception_handler` **两处**前置该判断，坑 8）
  **逻辑**: design D3 / D4。catch-all 端点体只做 `rest == "messages"` 判断后 raise。`chat_completions` 端点本任务先返回 26231 占位（T015b 填实）。
  **测试**: T012 auth / errors / switch 通过（`chat/completions` 成功路径留 T014）
  **覆盖 AC**: AC-02, AC-03, AC-05, AC-06, AC-07, AC-08, AC-26, AC-27, AC-28, AC-29, AC-32
  **依赖**: T012, T011
  **完成证据**: `open_api/api/endpoints/model_gateway.py` 三条路由（catch-all 同样带 `model:invoke` marker，坑 7）；`api/router.py` 条件挂载；`exception_handlers.py` 增 `MODEL_GATEWAY_PATH_PREFIX` / `render_openai_error` 并在 `dispatch` 与 `open_api_auth_exception_handler` 两处前置判断（坑 8）。

- [x] **T014**: 对话补全翻译与流式 单元测试（6h）
  **文件**: `src/backend/test/open_api/test_model_gateway_stream.py`（新）, `src/backend/test/open_api/test_openai_codec.py`（新）
  **逻辑**: **codec**：`messages` 含 system / user / assistant(tool_calls) / tool(tool_call_id) / 多模态数组 → `convert_to_messages` 结果类型与字段逐一断言 → AC-18；`tools` / `tool_choice` 原样进 `bind`、采样参数原样进 `kwargs`、未知字段（`extra`）透传 → AC-17 / AC-18；非流式响应形状（`chat.completion`、`tool_calls` 的 `arguments` 为 JSON 字符串、`finish_reason=="tool_calls"`、`usage` 三数）；流式 chunk 序列（首块 `role`、文本 delta、`reasoning_content` 只在非空时出现、`tool_calls` 的 `index` 在 fake 给 `None` 时被按顺序分配且同一调用稳定——双工具夹具，坑 6、`finish_reason` 独立 chunk、`include_usage` 为真时 `choices=[]` 的 usage chunk、`[DONE]`）→ AC-16 / AC-18；usage 未知（末块无 `usage_metadata`）→ 非流式 `usage` 三 null、流式不发 usage chunk → AC-23。**stream 端点**：SSE 头 `text/event-stream` + `X-Accel-Buffering: no`；中途异常 → `data: {"error":{...26234/26231}}` 后 `[DONE]` 且连接关闭（`httpx` 读到结尾不超时）→ AC-16；预取首块阶段抛 `LlmProviderDailyLimitExceededError` → **非 SSE** 429 26217 → AC-15；首块阶段上游 `APIStatusError(400/413/422)` → 同状态 26232 `message` 含上游原文、上游 429 → 26233、连接错 → 502 26231 → AC-08 / AC-18；不建会话（`message_session` 表零新增行）、不写消息表 → AC-17 / AC-19；`BishengLLM` 实例化参数断言（`app_type==MODEL_GATEWAY`、`user_id==resource_owner_user_id`、`streaming==req.stream`）→ AC-23 前提；客户端中途断开 → 记录 `result=="client_disconnected"`（与 T017 合并断言）。
  **覆盖 AC**: AC-08, AC-15, AC-16, AC-17, AC-18, AC-19, AC-23
  **依赖**: T005, T002, T006
  **完成证据**: `test_openai_codec.py` 17 passed · `test_model_gateway_stream.py` 18 passed（复核补 `_LLM_ERROR_TRANSLATION` 五条映射与 `client_disconnected`，偏差 8 / 13）。

- [x] **T015a**: `openai_codec` 纯翻译层实现（无 I/O）（5h）
  **文件**: `src/backend/bisheng/open_api/domain/services/openai_codec.py`（新）
  **逻辑**: design D8。导出 `to_langchain_messages(messages)`（经 `langchain_core.messages.utils.convert_to_messages`，多模态 content 数组原样保留）、`build_completion(ai_message, model, request_id) -> ChatCompletionResponse`（`tool_calls` 的 `arguments` 序列化成 JSON 字符串、`finish_reason` 取 `response_metadata.finish_reason` 兜底 `stop` / `tool_calls`）、`ChunkAssembler`（状态 `request_id / created / model / tool_index_map / last_chunk / sent_role`；方法 `first(chunk) / next(chunk) / finish(finish_reason) / usage(last_chunk, include_usage) / error(exc)` 各返回一行 SSE 文本；**`tool_index_map` 按 tool_call 首次出现顺序分配 index 并缓存**——坑 6：qwen / zhipu 的 `tool_call_chunks.index` 是 `None`、`id` 只在首块出现）、`usage_from(result) -> Usage | None`（经 `llm/domain/utils.py` 的 `parse_token_usage`，**全零 → `None`**，坑 5）、`classify_upstream_error(exc) -> ModelFaceError`（`openai.APIStatusError` 的 `status_code` → 26232 / 26233；连接类 → 26231；无法识别 → 26231 且 message 取 `str(exc)` 前 500 字）、`redact_secrets(text)`（正则抹 `sk-…` / `bs-sak-…` / `Bearer …`）。本模块**不 import** 任何 repository / DAO / Settings。
  **测试**: T014 的 `test_openai_codec.py` 全部通过
  **覆盖 AC**: AC-08, AC-16, AC-17, AC-18, AC-23
  **依赖**: T014, T002
  **完成证据**: `open_api/domain/services/openai_codec.py`（`to_langchain_messages` / `build_completion` / `ChunkAssembler` / `usage_from` / `classify_upstream_error` / `classify_stream_error` / `redact_secrets`），零 I/O；`tool_index_map` 按首次出现顺序分配 index（坑 6），双工具夹具守住。

- [x] **T015b**: `ModelGatewayService` 编排 + 端点接线（6h）
  **文件**: `src/backend/bisheng/open_api/domain/services/model_gateway_service.py`（新：`complete(principal, request, req)`：范围 → 解析 → `get_bisheng_llm` → `bind` → 非流式 `ainvoke` / 流式预取首块（坑 3）→ 返回 `ChatCompletionResponse` 或 `StreamingResponse`；`list_models(principal, headers)`；每条路径末尾调 `ModelCallRecordWriter.enqueue`（字段由 T018 填全）+ `logger.bind(event="model_gateway.call")`）, `src/backend/bisheng/open_api/api/endpoints/model_gateway.py`（`chat_completions` 从 T013 的 26231 占位改接 service；`StreamingResponse(..., headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})`）
  **逻辑**: design D8 / D13 / D14。**流式必须预取首块**（坑 3：服务商日上限的异常在 `astream` 第一次迭代时才抛，`StreamingResponse` 一旦构造就已发 200 头）——先 `agen = llm.astream(...)`、`first = await anext(agen)`，此步的异常以普通 JSON 错误体 + 真状态返回，成功后才构造 `StreamingResponse` 并先 yield 已预取的 `first`；**不要**在外面再调一次 `bisheng_model_limit_check`（包装器内已 `INCR`，会计两次）。`request.is_disconnected()` 在每块 yield 前查一次；`asyncio.CancelledError` 记 `client_disconnected` 后重抛。`BishengLLM` 错误族映射：10009 / 10010 → 26213，10012 → 26212，10011 → 26211，10013 → 26231（K6）。
  **测试**: T014 的 `test_model_gateway_stream.py` 全部通过；T012 全部通过
  **覆盖 AC**: AC-08, AC-15, AC-16, AC-17, AC-18, AC-19, AC-23
  **依赖**: T015a, T013
  **完成证据**: `open_api/domain/services/model_gateway_service.py`；流式按坑 3 预取首块——日上限与上游 4xx 因此是真状态码而不是半截 200 流；`BishengLLM` 错误族 10009/10010→26213、10012→26212、10011→26211、10013→26231。

- [x] **T016**: 路由矩阵 / OpenAPI 契约再生成 / 契约文档补章（2h）
  **文件**: `features/v3.0.0-beta1/053-openapi-auth-and-identity/openapi-v2-key-auth-api.json`（跑 `python features/v3.0.0-beta1/053-openapi-auth-and-identity/generate_openapi_contract.py` 再生成）, 同目录 `openapi-v2-key-auth-api.md` / `openapi-v2-key-auth-api-by-category.md`（补「模型协议面」章：三条操作、错误体、base URL）, `src/backend/test/open_api/test_open_api_route_matrix.py`（T007 的 xfail 去掉）, `src/backend/bisheng/open_api/api/openapi_schema.py`（如需：本面 `StreamingResponse` 的 `text/event-stream` 描述）
  **逻辑**: design D12 / 坑 11。断言 `test_openapi_schema_contract.py` 三条全绿。
  **依赖**: T013, T015b
  **完成证据**: `generate_openapi_contract.py` 在 import app 前强制打开 `open_platform.enabled`（契约文档完整面，不依赖跑脚本的人手上的 YAML），重跑后 `openapi-v2-key-auth-api.json` 含本面两条承诺面操作（catch-all `include_in_schema=False`，不进契约）；`test_openapi_schema_contract.py` 与 `test_open_api_route_matrix.py` 在开关关闭的进程里按前缀剔除期望集合。
  **未做的一半（2026-09-16 复核记录，偏差 8）**: 同目录两份**手写**客户文档 `openapi-v2-key-auth-api.md` / `openapi-v2-key-auth-api-by-category.md` **没有**补「模型协议面」章。它们是 beta1 冻结的四分类（知识库 / 日常模式会话 / 工作流 / 助手）交付物，抬头写死「HTTP 接口：42 条」「分类顺序：知识库 → 日常模式会话 → 工作流 → 助手」，而同目录 json 现在是 **48 条**——差额里 F055 的 `/api/v2/apps/**` 四条同样不在 md 里。也就是说这两份 md 的滞后是先于本 Feature 的、且范围比本 Feature 大；只补模型面一章会让计数与分类总览更不自洽。模型面的对外文档改由 **T029**（`docs/api/` 新增「模型协议面」页）承接，见该任务。

### Wave 4 · 逐条调用记录（Test-First）

- [x] **T017**: ModelCallRecord 写入与查询 单元 + 集成测试（4h）
  **文件**: `src/backend/test/open_api/test_model_call_record.py`（新）
  **逻辑**: `test_success_row_fields`（成功调用 → 一行：`credential_id / credential_mask` 掩码格式、`actor_kind/actor_id/actor_name`、`resource_owner_user_id`、`subject_kind=="service_account"`、`requested_model / model_id / server_id / model_name / server_name / server_type`、`is_stream`、三 token 数与 `parse_token_usage(last_chunk)` 相等、`result=="success"`、`latency_ms>0`、`ttft_ms` 非空（流式）、`request_id` 与响应 `id` 相等、`trace_id`）→ AC-20 / AC-23；`test_unknown_usage_is_null_not_zero` → AC-23；`test_upstream_failure_row`（`result=="upstream_failed"`、`error_code==26231`、tokens NULL）→ AC-20；`test_model_unavailable_row`（26211 / 26212 / 26214 各一行 `result=="model_unavailable"`、`model_id` 空、`requested_model` 保留）→ AC-20；`test_limit_exceeded_row` → AC-15 / AC-20；`test_rejected_before_resolution_writes_no_row_but_audit_row`（401 / 403 / 26051：本表零行、`audit_log.open_api.call` 一行含 `credential_id` 与 `error_code`）→ AC-20；`test_models_endpoint_writes_no_row`；`test_no_message_body_no_secret_in_row_or_logs`（行内任何列与 `caplog` 均不含 `Authorization` 明文、`bs-sak-` 全串、`messages` 文本、`LLMServer.config` 值）→ AC-36；`test_batch_writer_flushes_within_interval_and_on_stop`；`test_queue_full_logs_error_and_metric`（C8 不静默）；`test_alist_filters_and_cursor_order`（按 `credential_id` / `app_id` / 时间范围筛；同秒 20 行两页拼接 == 全序，坑 9）→ AC-24；`test_tenant_isolation_on_list`（子租户查不到 Root 行）→ AC-24；**`test_no_aggregation_or_quota_surface`**（反向断言 AC-25：`app.routes` 中 `/api/v2/model/v1` 前缀下只有 design §4.2 ① 登记的三条路由，没有任何 usage / billing / quota 路径；`ModelCallRecordRepository` 的公开方法只有 `ainsert_batch / alist / aiter_export`，没有任何 `asum_*` / `aggregate_*`；`OpenApiConf` 未新增任何 `*_limit` / `*_quota` 键——把「本版只逐条计量、不做聚合与上限」钉成可回归的事实，否则它只是 design §8 里一句无人执行的话）→ AC-25；`test_telemetry_event_same_tokens`（`monkeypatch telemetry_service.log_event_sync` 捕获 `ModelInvokeEventData`，`app_type=="model_gateway"`、三 token 数与本表相等）→ AC-23。
  **覆盖 AC**: AC-15, AC-20, AC-23, AC-24, AC-25, AC-36
  **依赖**: T003, T004, T005, T015b
  **完成证据**: `test/open_api/test_model_call_record.py` 13 passed（含 `test_no_aggregation_or_quota_surface_exists` 反向断言 AC-25；复核把满队列用例改为断言 `emit_metric(status="dropped")` 真的发出，偏差 13）。

- [x] **T018**: 记录接线 + token 同源 + 脱敏（4h）
  **文件**: `src/backend/bisheng/open_api/domain/services/model_gateway_service.py`（`_start_record(principal, subject, req)` / `_finish_record(record, result, error, usage, ttft)`；`credential_mask` **不在请求路径查**（`OpenApiPrincipal` 无掩码字段、不动 beta2 契约）：行入队时 `credential_mask=None`，由 `ModelCallRecordWriter` 在 `write_batch` 前按 `credential_id` 批量水合 `ApiCredential.key_mask`（一次 `IN` 查询 / 批，design D14））, `src/backend/bisheng/open_api/domain/services/model_call_record_writer.py`（批内水合）, `src/backend/bisheng/open_api/domain/services/openai_codec.py`（`redact_secrets` 接入所有 message 出口）
  **逻辑**: design D9 / D10 / D14；坑 5（0 → NULL）。中途错误同时 `conn.scope["open_api_error_code"] = code`（坑 10）。
  **测试**: T017 全部通过
  **覆盖 AC**: AC-15, AC-20, AC-23, AC-24, AC-25, AC-36
  **依赖**: T017
  **完成证据**: `model_gateway_service._start_record / _attach_model / _finish_record` + 结构化日志 `model_gateway.call`；掩码在 `ModelCallRecordWriter` 批内一次 `IN` 查询水合（`test_the_credential_mask_is_hydrated_per_batch_not_per_call`）；流式中途错误同时 `mark_open_api_error`（坑 10）。

### Wave 5 · base URL 契约与官方客户端契约测试

- [x] **T019**: 官方 `openai` 客户端 ASGI 契约测试（3h）
  **文件**: `src/backend/test/open_api/test_model_gateway_openai_sdk.py`（新）
  **逻辑**: 用 T005 `openai_client`：`client.models.list()` 能解析且 `id` 集合符合 D5（歧义只有限定名）→ AC-01 / AC-10；`client.chat.completions.create(model=..., messages=..., stream=False)` 得 `ChatCompletion` 且 `usage` 可读 → AC-01；`stream=True` 迭代 `ChatCompletionChunk`，含 `tool_calls` 增量可被 SDK 累加、`stream_options={"include_usage":True}` 末块 `usage` → AC-16 / AC-18；错误：401 → `openai.AuthenticationError`、403 → `openai.PermissionDeniedError`（`body["error"]["bisheng_code"]` 可读）、404 模型 → `openai.NotFoundError`、429 → `openai.RateLimitError`、400 歧义 → `openai.BadRequestError` 且 `body.error.candidates` 列出限定名 → AC-08 / AC-12；`client.embeddings.create(...)` → `NotFoundError` 26201 → AC-02；限定名 `A/x` 调用成功 → AC-12。
  **覆盖 AC**: AC-01, AC-02, AC-08, AC-10, AC-12, AC-16, AC-18
  **依赖**: T015b, T016
  **完成证据**: `test/open_api/test_model_gateway_openai_sdk.py` 9 passed——官方 `openai.AsyncOpenAI` 经 ASGITransport 直打，能解析成功体、按 index 累加双工具调用的 arguments、并把 401/403/404/400/429 抛成自己的异常类（`body` 里读得到 `bisheng_code` 与 `candidates`）。

- [x] **T020**: base URL helper + `whoami.model_base_url` + 环境变量名回写三处（3h）
  **文件**: `src/backend/bisheng/open_api/api/public_base_url.py`（`model_gateway_base_url(request) -> str` = `resolve_public_base_url(request) + "/api/v2/model/v1"`；`_warn_once` 文案泛化，坑 14）, `src/backend/bisheng/open_api/domain/schemas/credential.py`（`WhoamiResponse.model_base_url: str`）, `src/backend/bisheng/open_api/api/endpoints/auth.py`（`whoami` 填值；`open_platform.enabled=False` 时为空串）, `src/backend/test/open_api/test_model_gateway_base_url.py`（新：配置 `public_base_url` / `X-Forwarded-*` / Host 三来源各一例；两把不同密钥、两个租户得到同一 base → AC-30；关开关时空串）, `features/v3.0.0/054-app-domain-runtime/contracts-runtime-manager.md`（§5 清单追加 `OPENAI_BASE_URL` · `OPENAI_API_KEY` · `BISHENG_MODEL_BASE_URL`，来源标 F051 design D2）, `features/v3.0.0/053-dev-cli-skills/design.md`（§6.2 表末行同步）, `features/v3.0.0/055-app-publish-pipeline/design.md`（D13「模型注入」段：`BISHENG_PLATFORM_API_BASE` → 改引 `OPENAI_BASE_URL` / `BISHENG_MODEL_BASE_URL`；凭据仍 `BISHENG_APP_TOKEN`，且同时以 `OPENAI_API_KEY` 注入）
  **逻辑**: design D2。三处回写只加名不改既有名。
  **覆盖 AC**: AC-30, AC-33
  **依赖**: T013
  **完成证据**: `public_base_url.py` 增 `MODEL_GATEWAY_BASE_PATH` / `model_gateway_base_url`，`_warn_once` 文案泛化（坑 14）；`WhoamiResponse.model_base_url` + `auth.py` 填值（开关关时空串）；`test_model_gateway_base_url.py` 6 passed（三来源各一例 + 两租户两把密钥同一地址）；三处回写：F054 `contracts-runtime-manager.md` §5、F053 design §6.2 表、F055 design D13。

- [x] **T021**: 技能包 / 文档配合项登记（1h）
  **文件**: `features/v3.0.0/053-dev-cli-skills/tasks.md`（追加一行「平台能力接线包·模型一节按 F051 §4.2 ①③ 与 D5 限定名规则编写；附 `X-BiSheng-Access-Token` 转发说明」，指向本文）, `features/v3.0.0/057-bisheng-sdk/spec.md` 或 tasks（如存在：登记「SDK 不封 chat；示例用 `openai` 客户端读 `OPENAI_BASE_URL`；应用侧转发访问凭据头」）
  **逻辑**: design §6.1 / 坑 16。本 Feature 不写技能包正文。
  **覆盖 AC**: AC-31, AC-33
  **依赖**: T020
  **完成证据**: F053 tasks.md 追加 **T038a**（模型章改写 + `X-BiSheng-Access-Token` 转发说明）；F057 tasks.md 追加 **T035a**（模型章两条回归断言改口径，`test_no_sdk_wrapper_for_model_or_appdb` 不动）。

### Wave 6 · 托管应用运行期路径（~~依赖 F055 T055 / T056、F054 OBO 验签~~ **上游已落地，2026-09-16 解除**）

> ~~在上游落地前，本 Wave 的测试用 fake Port + `model_construct` 构造 `hosted_app` principal 通过（T010 已含），代码可先合；下列任务是**接线与真实断言**，须待上游。~~
>
> **2026-09-16**：三项上游全部在 `3.0-vibe` 上：`resolve_hosted_app`（F055 T055）、`HostedAppDeclarationAdapter` + `derive_scopes` + `runtime_capability_env`（F055 T056）、`verify_obo_token` + `AccessSubjectVerifier`（F054）。两个 Port 由 **F055 的组合根 `app_publish/composition.py:register()` 一并注册**（两者必须同进同退，理由见该文件注释），组合根本身由 `main.py` 与 `worker/main.py` 各调一次。本面**代码零改动**即接通——这正是 D7 的 Port 设计要换来的结果；T022–T024 落的是真实断言。

- [x] **T022**: `hosted_app` principal 正式构造 + 范围收窄真实断言（3h）~~**依赖 F055 T055**~~
  **文件**: `src/backend/test/open_api/test_model_gateway_hosted_app.py`（新）, `src/backend/bisheng/open_api/domain/services/model_range_policy.py`（若 F055 把 `actor_kind` Literal 扩为含 `"hosted_app"`，去掉 `model_construct` 变通；T055 的解析器返回的 principal 字段（`actor_id = app 内部 id`、`actor_name = slug`、`resource_owner_user_id = owner`）按 F055 实际回填本文 §4.2 ④ 的 `actor_*` 语义）
  **逻辑**: 经真实 `CredentialService.issue(subject_kind="hosted_app", ...)` 签发 → `/models` 只返回 `declared ∩ C` → AC-34；`declared` 外模型 → 26215；`declared` 内已下线 → 26212 → AC-13 / AC-34；声明 Port 未注册 → 26216 → AC-35。
  **覆盖 AC**: AC-13, AC-34, AC-35
  **依赖**: T011, T015b, F055 T055
  **完成证据**（2026-09-16）：
  - `src/backend/test/open_api/test_model_gateway_hosted_app.py`（新，21 条，与 T023 共用）——范围半：`/models` 只回 `declared ∩ C`（声明里有、租户没有的 `claude-3` 与租户有、没声明的 `qwen-max` 都不出现）、未声明 → 26215、已下线 → 26212、租户没有 → 26211、缓存窗口内被摘 → **26213（不是 26215）**、声明为空 → 26215 而非 26216、Port 未注册 / 声明读不到 / 他租户声明 → 26216 且**绝不回退租户范围**。声明侧用的是 F055 的真 `HostedAppDeclarationAdapter`（只桩 `load_effective_declaration`），`None` ⟷ 空集的区分因此是真代码在判。
  - `src/backend/test/app_publish/test_capability_model.py`（+3 条端到端）——走**真实** `AppRuntimeCredentialService.issue` 签发 `bs-app-` 明文 → 真实 `validate_bearer` → `resolve_hosted_app` → 本面：声明内可调、租户其它模型 26215、声明内模型下线 26212 且声明本身不变。夹具 `published_app_client` 只把模型目录换成 F051 套件的**同一个** `install_catalog` 假件（模型管理的表不在 `test/app_publish` 的 schema 里），两侧对「租户有什么」的认知因此不可能分叉。
  - `model_construct` 变通已删：`test/open_api/model_gateway_fixtures.py:hosted_app_principal` 改为完整校验构造（`OpenApiPrincipal.actor_kind` Literal 已含 `hosted_app`）。
  - §4.2 ④ 的 `actor_*` 语义按 `resolve_hosted_app` 实际回填进 design.md（`actor_id = hosted_app_subject.id` / `actor_name = app.name` 显示名 / 应用机器标识只有 `subject_ref = app.id` 一个来源）。

- [x] **T023**: 访问凭据验签 Port 接线（F054 提供实现）+ subject 落记录（3h）~~**依赖 F054 OBO 验签**~~
  **文件**: `src/backend/bisheng/app_runtime/domain/services/obo_token.py`（**F054 归属**：从 `entry_authz_service.py:379-426` 抽 `OBO_AUDIENCE` / secret 读取 / `issue` 与新 `verify_obo_token(token, *, app_id, tenant_id) -> AccessSubject | None`；本任务只登记需求，实现 PR 由 F054 出或本 Feature 代出后由 F054 review）, `src/backend/bisheng/main.py`（lifespan 注册 `register_access_subject_verifier(verify_obo_token)`——**放 `app_runtime` 组合根**，不在 `open_api` 内 import `app_runtime`）, `src/backend/test/open_api/test_model_gateway_hosted_app.py`（增：有效头 → 行 `subject_kind=="user"`、`subject_id==user`；无头 → `app_self`；过期 / 错 `app_id` / 错签名 → 26204；任何情况下范围不随 subject 变）
  **逻辑**: design D7；spec 决议-5。`app_id` 维度：行 `app_id = principal.actor_name`（slug）或 F055 定义的应用标识——以 T055 回填为准。
  **覆盖 AC**: AC-21, AC-22, AC-34
  **依赖**: T022, T018
  **完成证据**（2026-09-16）：
  - **实现已由上游提供，本任务不新写代码**：`verify_obo_token(token, *, app_id, tenant_id) -> int | None` 与其适配器 `AccessSubjectVerifier` 落在 `bisheng/app_runtime/domain/services/entry_authz_service.py`（F054 归属，非本 Feature 代出），注册点是 `bisheng/app_publish/composition.py:register()` 里的 `register_access_subject_verifier(AccessSubjectVerifier())` —— 与 T023 原计划的「放 `app_runtime` 组合根、在 `main.py` lifespan 注册」等价且更严：**两个 Port 在同一个函数里同进同退**，不会出现「声明读得到、令牌验不了 → 全部记成应用自身却照常服务」这种半接线。`main.py` 与 `worker/main.py` 各调一次组合根。
  - `test/open_api/test_model_gateway_hosted_app.py` 的 subject 半（用**真** `_issue_obo_token` 签 + 真 `AccessSubjectVerifier` 验，非 fake）：有效令牌 → 行 `subject_kind == "user"` / `subject_id == 77` / `app_id == app.id`；无令牌 → `app_self` + `subject_id is None`，同时 `resource_owner_user_id` 照记（归属人与「谁发起的调用」是两列两义）；**五种坏令牌**（他应用、他租户、非 JWT、已过期、错签名）参数化 → 一律 26204、不降级成 `app_self`、且在摸模型之前就拒（`records == []`）；范围不随 subject 变（带/不带令牌的 `/models` 响应逐字节相同）；判定序 ②→③（声明读不到 + 坏令牌 → 26204 而不是 26216）。
  - 注册本身也有守卫：`test_the_composition_root_installs_both_ports`（调真组合根后两个 Port 的类型断言）与 `test_both_process_entry_points_call_the_composition_root`（AST 断言 `main.py` / `worker/main.py` 都 import 了组合根）。
  - `app_id` 维度的悬而未决项按 T055 实际回填：**是 `principal.subject_ref`（`app.id` uuid），不是 `actor_name`（slug/显示名）**；design §4.2 ④ 与 D7 已同步。

- [x] **T024**: F055 声明 Port 注册验证 + 能力收回错误对齐（2h）~~**依赖 F055 T056 / T058**~~
  **文件**: `src/backend/test/app_publish/test_capability_model.py`（F055 归属，增：经本面 26215 / 26212 / 26213 与 F055 `16273` / `16274` 的对应关系——本面**不**改码，F055 在发布面读接口按 `declared ∖ 当前可解析` 计算「已失效」）, `features/v3.0.0/055-app-publish-pipeline/design.md`（D13 与错误码表 16270–16289 段各补一句：**模型能力的运行期判定一律走 262 段**——「已收回」= 26212 / 26213、「未声明」= 26215；F055 的 `16273`（能力已被收回）/ `16274`（未在能力声明中的能力）**只用于知识库等非模型能力**）
  **逻辑**: 消除两个错误码族对同一事件的重复——**两边各有一对码**（16273 ⟷ 26212/26213、16274 ⟷ 26215），只登记 16273 一半会留下同样的歧义。F055 AC-53 在模型面的表现 = 26212 / 26213（spec AC-13）、AC-51 的表现 = 26215（spec AC-34）。
  **覆盖 AC**: AC-13, AC-34
  **依赖**: T022
  **完成证据**（2026-09-16）：
  - **本面不改码**（任务原文即如此）。F055 侧两处文档补齐：`055/design.md` 错误码表 16270–16289 行加了「两码只用于知识库等非模型能力」的限定，「一码一义」清单加了第四条，写全**双向**对应（16273 ⟷ 26212/26213、16274 ⟷ 26215）并点名只登记一半会留下同样的歧义；D13 原有的那句保持不变（已正确）。
  - `test/app_publish/test_capability_model.py::test_this_features_capability_codes_are_never_raised_for_a_model` —— AST 遍历 `capability_bus_service`，断言每一处 `AppCapabilityRevokedError` / `AppCapabilityNotDeclaredError` 都显式带 `kind=CAPABILITY_KIND_KNOWLEDGE`；哪天有人给模型路径加一处 162 段的 raise，这条会点名文件行号。比散文声明强的地方就在这里。
  - `test_the_model_face_and_the_publish_surface_read_the_same_resolution` —— 同一份声明（`gpt-4o` 在线 / `retired` 下线）下，发布面的 `model_capability_status` 标记与本面的拒绝同源（都出自 `resolve_model_name`），避免「发布面说健康、面上拒」或反过来。
  - 本面 26213 的托管应用侧也补了用例（见 T022 证据行），因为 16273「已收回」对应的是 26212 **和** 26213 两个码。

- [ ] **T025**: 114 托管应用端到端（2h）**依赖 F055 T056 部署到 114**
  **文件**: 本文「114 部署记录」小节
  **逻辑**: 发布一个声明了模型 `x` 的示例应用 → 容器内 `env | grep OPENAI_` 三名齐 → 应用内 `openai` 客户端调 `x` 成功、调 `y` 26215 → 管理员下线 `x` → ≤ 60s 26212、发布面标「已失效」→ `model_call_record` 行 `app_id` 与 `subject_kind` 正确（浏览器访问 → `user`，`curl` 容器内后台调用 → `app_self`）。
  **覆盖 AC**: AC-21, AC-33, AC-34
  **依赖**: T023, T024
  **⚠️ 部署前置（2026-09-16 复核补入，不做这一步「浏览器访问 → `user`」永远跑不出来）**: 114 的 `config.yaml` 必须配 `app_runtime.obo_secret`（`openssl rand -hex 32`，且**不等于** `jwt_secret`）。出厂默认是空串（`core/config/app_runtime.py:88`），`docker/bisheng/config/config.yaml:216` 也是注释掉的；空串时 `_issue_obo_token` **不签令牌、只按进程记一条 error 日志**，入口照常放行 —— 于是所有托管应用调用都落 `subject_kind=app_self`，与「应用没转发令牌」在本面完全不可区分，T025 的 subject 那一半会「通过得毫无破绽」却什么都没验到。核对方式：改完重启后端 → 浏览器进一次应用 → 后端日志无 `obo_secret is not configured` → 再跑本任务。



### Wave 7 · 114 E2E 与引擎适配（需 114）

- [ ] **T026**: 114 部署 + `/e2e-test` 脚本（pytest + httpx 打 114）（3h）
  **文件**: `src/backend/test/e2e/test_model_gateway_114.py`（新，`-m e2e`，读 `BISHENG_E2E_BASE / BISHENG_E2E_SAK` 环境变量）, 本文「114 部署记录」小节
  **逻辑**: 部署顺序：`bash /opt/bisheng-ops/deploy.sh`（`create_all` 建 `model_call_record`）→ `config.yaml` 确认 `open_platform.enabled: true`、`open_api.public_base_url`（114 用 `http://192.168.106.114:3001`）→ 重启 8 unit → 平台签一把 `model:invoke` 密钥。脚本覆盖：AC-01 / AC-05 / AC-06 / AC-12 / AC-13 / AC-14（下线 → 轮询 ≤ 60s；在途流式在下线后仍完整读到 `[DONE]`）/ AC-16（经 nginx 首字延迟 < 3s 且分块到达，证明 `X-Accel-Buffering` 生效）/ AC-18（tools 往返）/ AC-26 / AC-28（可选：改开关重启一次）。
  **覆盖 AC**: AC-01, AC-05, AC-06, AC-12, AC-13, AC-14, AC-16, AC-18, AC-26, AC-28
  **依赖**: T016, T018, T020

- [ ] **T027**: 本地引擎手动验证（Qwen Code / Codex CLI 对话补全模式 / Kimi Code / Claude Code 反例）（3h）
  **文件**: 本文「114 部署记录」小节（记录每个引擎的配置片段与结果；配置里密钥用占位符）
  **逻辑**: `export OPENAI_BASE_URL=http://192.168.106.114:3001/api/v2/model/v1 OPENAI_API_KEY=bs-sak-…`：Qwen Code 跑一个需要 `read_file` 工具调用的任务 → 流式 + 工具往返成功 → AC-31；Codex CLI 切 chat completions provider → 成功；Kimi Code 同；Claude Code `ANTHROPIC_BASE_URL` 指向 base → 得到 26202 可读提示 → AC-32；`/api/v1/env` 关开关后（AC-28）Qwen Code 报 404。任一引擎失败 → 记入「实际偏差记录」并回 design 坑表。
  **覆盖 AC**: AC-03, AC-31, AC-32, AC-33
  **依赖**: T026

- [ ] **T028**: 审计与账本核对（1h）
  **文件**: 本文「114 部署记录」小节
  **逻辑**: 114 MySQL：`SELECT credential_mask, model_name, server_name, prompt_tokens, completion_tokens, result FROM model_call_record ORDER BY id DESC LIMIT 10`；`audit_log` 中 `action='open_api.call' AND target_id LIKE 'POST /api/v2/model/v1/%'` 行数 ≥ 本表行数（含被拒）；ES 遥测 `MODEL_INVOKE` 事件 `app_type=model_gateway` 的 token 数与本表同一 `trace_id` 行一致 → AC-23；grep 后端日志无 `bs-sak-` 全串与 `Authorization` → AC-36。
  **覆盖 AC**: AC-20, AC-23, AC-24, AC-36
  **依赖**: T026

- [x] **T029**: 发布说明 + docs 补章（1h）
  **文件**: `docs/api/`（如有 v2 文档目录：新增「模型协议面」页，内容 = design §4.2 ①②③ + 引擎配置片段）, `features/v3.0.0/release-contract.md`（变更历史加一行：F051 design / tasks 定稿、262 登记、`model:invoke` 可签发）
  **并入本任务（从 T016 移来，2026-09-16）**: 模型面的对外客户文档写在这里，不再往 beta1 那两份手写 md 里塞——理由见 T016「未做的一半」。写这一页时顺带确认 `openapi-v2-key-auth-api.json` 是最新的（catch-all 不进契约是有意的），以及 `whoami.model_base_url` 是文中唯一的 base URL 出处。
  **覆盖 AC**: AC-30
  **依赖**: T027, T028
  **完成证据（2026-09-16，切片 `wt/f057-tail`）**: 新增 `docs/api/model-gateway.md`（照 `docs/api/mcp-server.md` 的房式，七节：接入 / 模型名解析四步 / 承诺参数 / OpenAI 错误体与码表 / 身份与边界 / 引擎配置片段 / 调用记录）；`features/v3.0.0/release-contract.md` 变更历史加「2026-09-16（F051 收口）」一行。**逐条对着实现侧核过**：`model_gateway.py`（两条端点 + catch-all、`ANTHROPIC_MESSAGES_PATHS` 两种拼法）、`schemas/model_gateway.py`（承诺字段表、`extra="allow"` 原样转发、`reasoning_content` 非空才出现）、`model_gateway_service.py:148`（`n != 1` → 26203）、`common/errcode/model_face.py`（26201–26205 / 26211–26217 / 26231–26234 逐个）、`credential.py:136` 的 `model_base_url`。
  **顺带核对的两处，结论都是不改**: ① `features/v3.0.0-beta1/053-openapi-auth-and-identity/openapi-v2-key-auth-api.json` 已含 `/api/v2/model/v1/chat/completions` 与 `/models`（全表 48 条操作），是最新的、catch-all 如设计不进契约；② release-contract 错误码表 262 行（`:105`）早已登记且与 `model_face.py` 一致，未动。
  **偏差**: 「发布说明」在本仓没有独立的 release note 文件（`docs/blog/` 只有两篇长文，无版本发布说明），故按本任务文件清单落在 release-contract 变更历史；若后续建立版本发布说明文件，本行内容可原样搬过去。

---

## AC 追溯表（36 / 36 全覆盖，2026-09-16 `/sdd-review tasks` 复核：每条 AC 至少一个带「覆盖 AC」标注的任务）

| AC | 任务 | 阶段 |
|---|---|---|
| AC-01 | T019, T026 | 本地 / 114 |
| AC-02 | T012, T013, T019 | 本地 |
| AC-03 | T012, T013, T027 | 本地 / 114 |
| AC-04 | T010, T011 | 本地 |
| AC-05 | T012, T013, T026 | 本地 / 114 |
| AC-06 | T012, T013, T026 | 本地 / 114 |
| AC-07 | T012, T013 | 本地 |
| AC-08 | T012, T013, T014, T015a, T015b, T019 | 本地 |
| AC-09 | T008, T009, T010, T011 | 本地 |
| AC-10 | T008, T009, T019 | 本地 |
| AC-11 | T008, T009 | 本地 |
| AC-12 | T008, T009, T019, T026 | 本地 / 114 |
| AC-13 | T008, T009, T022, T024, T026 | 本地 / [后] |
| AC-14 | T008, T009, T026 | 本地 / 114 |
| AC-15 | T014, T015b, T017, T018 | 本地 |
| AC-16 | T014, T015a, T015b, T019, T026 | 本地 / 114 |
| AC-17 | T014, T015a, T015b | 本地 |
| AC-18 | T014, T015a, T015b, T019, T026 | 本地 / 114 |
| AC-19 | T014, T015b | 本地 |
| AC-20 | T012, T017, T018, T028 | 本地 / 114 |
| AC-21 | T010, T011, T023, T025 | [后] |
| AC-22 | T010, T011, T023 | 本地 / [后] |
| AC-23 | T014, T015a, T015b, T017, T018, T028 | 本地 / 114 |
| AC-24 | T017, T018, T028 | 本地 / 114（查询面 UI 归 F056） |
| AC-25 | T017, T018（`test_no_aggregation_or_quota_surface` 反向断言，必做；design §8 同步登记「不做」） | 本地 |
| AC-26 | T012, T013, T026 | 本地 / 114 |
| AC-27 | T010, T011, T012, T013 | 本地 |
| AC-28 | T012, T013, T026 | 本地 / 114 |
| AC-29 | T012, T013 | 本地 |
| AC-30 | T020, T029 | 本地 |
| AC-31 | T021, T027 | 114 |
| AC-32 | T012, T013, T027 | 本地 / 114 |
| AC-33 | T020, T021, T025, T027 | 114 / [后] |
| AC-34 | T008, T009, T010, T011, T022, T023, T024, T025 | 本地 / [后] |
| AC-35 | T008, T009, T010, T011, T022 | 本地 / [后] |
| AC-36 | T017, T018, T028 | 本地 / 114 |

~~`[后]` = 依赖 F055 T055 / T056 或 F054 OBO 验签，上游未落地前只有 fake Port 用例通过。~~
**2026-09-16 起 `[后]` 全部解除**：上游三项已在 `3.0-vibe` 上，T022 / T023 / T024 已按真实实现断言（fake Port 的单元用例 T010 保留——它守的是判定序与 Port 契约本身，与真实现的用例互补而非重复）。AC-13 / AC-21 / AC-22 / AC-34 / AC-35 的本地覆盖因此不再打折；标 `[后]` 的行里只剩 T025 需要 114。

---

## 114 部署记录

> 未开工。T026 起在此追加：部署命令 / 配置片段（密钥占位）/ 每个引擎的结果 / SQL 核对结果。

---

## 实际偏差记录

> **只留一行指针**，论证在 design.md（决策 / 坑），这里不重复（见 `docs/SDD-Guide.md` §4）。
> 推翻已定案的决策时，先停下与用户重新确认（§3 第四个 ★），再记录。

**2026-09-16 Wave 1–5 实施（T001–T021）**

1. **`acollect_visible_server_ids` 实际抽成了两个函数** —— design D6 只写了 id 版；catalog 还要服务商的 `name` / `type` 才能算限定名与 `owned_by`，只给 id 会逼出第二次 `aget_server_by_ids`。落地为 `acollect_visible_servers(leaf_id, *, strict)` 返回行，`acollect_visible_server_ids` 是它的薄封装（签名与 design 一致，供只要 id 的调用方）。`get_all_llm` 改调前者，行为不变。
2. **开关关闭时本面返回的是 v2 信封 404（`{"status_code":404,"status_message":"Not Found"}`），不是 design D3 写的 Starlette 裸 `{"detail":"Not Found"}`** —— 路径落在 `/api/v2` 前缀下，既有的 `open_api_http_exception_handler` 会把任何 404 统一渲染成信封，这在本面之前就是全部不存在的 v2 路径的行为。AC-28 要的是「与不存在的路径无差别」，这一条仍然成立且更强：`test_model_gateway_switch.py::test_the_face_is_indistinguishable_from_nothing_when_not_deployed` 直接断言本面路径与一个从来不存在的 `/api/v2/no-such-surface/models` **响应体逐字节相同**，而不是断言某个固定的 JSON 形状。
3. **契约生成脚本自己打开开关，而不是要求运行者改 config.yaml** —— design D3 末段说「契约 json 用 `open_platform.enabled: true` 的 config 生成」。实际落地是在 `generate_openapi_contract.py` 里 import app **之前**把开关置 true 并留注释。理由：客户契约文档描述的是完整承诺面，不该取决于跑脚本的人手上那份 YAML；而 `test_openapi_schema_contract.py` 已按前缀剔除期望集合，两态都对得上。
4. **范围策略阶段的拒绝（26205 / 26204 / 26216）不写 ModelCallRecord** —— design D9 写「解析失败（26211–26216）也 enqueue」，但 26216 有两个来源：能力声明读不到（范围确立阶段，尚未到模型解析）与目录读不到（解析阶段）。按 AC-20 的措辞「到达模型解析阶段」取前者不写、后者写。被拒调用仍由中间件的 `open_api.call` 审计行承接，`test_a_call_refused_before_model_resolution_gets_no_usage_row` 守住。
5. **`ChunkAssembler` 的 `finish_reason` 优先采信上游 `response_metadata.finish_reason`，`tool_calls` 只是兜底** —— design D8 的措辞容易读成「有 tool_call 就写 tool_calls」。上游是权威的（`length` / `content_filter` 必须原样传出），所以顺序是先读上游、读不到才按有无 tool_call 推断。
6. **`_explain_miss` 的两次补查也走 `strict=True`** —— 失败路径再遇到权限后端故障时，答案应当是 26216 而不是把它误判成 26211「不存在」。
7. **Wave 6（T022–T025）与 Wave 7（T026–T029）未做**：前者阻塞于 F055 T055（`hosted_app` 主体解析器 + `OpenApiPrincipal.actor_kind` Literal 扩容）/ F055 T056（注册 `HostedAppDeclarationPort`）与 F054 的 OBO 验签实现；本面的 hosted_app 分支已按契约写完并以 fake Port 测通（T010 / T011），上游落地后只需注册实现、不改本面代码。后者需要 114。
   —— **2026-09-16 更新**：阻塞解除，T022 / T023 / T024 已落地（见下方 15–18）；「上游落地后只需注册实现、不改本面代码」这句话被证实了，本面一行没改。T025 与 Wave 7 仍未做，全部需要 114。

**2026-09-16 复核（Wave 1–5 实施后的审查与修正）**

8. **26213「已收回」在解析阶段不可达，改由实例化阶段承担** —— design D5 第 4 步写「服务器被删（模型行残留、`server_id` 无对应）→ 26213」，但 `LLMDao.adelete_server_by_id` 删服务商时**一并删掉它的模型行**，而 `aget_model_by_server_ids` 又只查可见服务商下的模型：两条一叠，「服务商已删、模型行残留」这个状态数据库根本产生不了，`_explain_miss` 里那个分支是死代码。原 `test_offline_missing_and_provider_deleted_are_distinguishable` 之所以绿，是因为 T005 的 `install_catalog` 假 DAO **忽略了 `server_ids` 过滤**，凭空造出一行数据库给不出的数据。修正：① 假 DAO 改为真的按 `server_ids` 过滤（假件与真 DAO 契约一致，否则测试守的是想象中的代码）；② 删掉 `_explain_miss` 的死分支，并在函数 docstring 写明 26213 的真实来源；③ 测试拆成「下线 vs 不存在可区分」「他租户模型读作不存在」「服务商删干净后只能答不存在」三条，另在 `test_model_gateway_stream.py` 补 `test_a_model_withdrawn_inside_the_cache_window_is_reported_as_such` —— 参数化断言 `_LLM_ERROR_TRANSLATION` 五条映射（10009 / 10010 → 26213、10012 → 26212、10011 → 26211、10013 → 26231），这条链路此前**一条测试都没有**。对 AC-13 的净效果：目录缓存窗口内（≤60s）「已收回」仍可区分，窗口过后与「不存在」合并——后者本就是 AC-13 要求的不透露存在性的答案。
9. **D7 判定序在 hosted_app 分支被写反（②③ 对调），已改回** —— 原实现先读能力声明 Port、再验访问凭据，于是「伪造/过期令牌 + 声明读不到」会答 26216（「暂时判不了，重试」）而不是 26204。令牌永久无效的调用方会被这句话送进一个永远成功不了的重试循环。已把验签移到声明读取之前，并补 `test_a_forged_token_is_refused_even_when_the_declaration_is_unreadable`。
10. **`model_catalog` 的 `tenant_id` 参数此前不是权威的** —— `acollect_visible_servers(leaf_id)` 只拿 `leaf_id` 做 FGA / 继承查询，自有行那一条走的是 `strict_tenant_filter()` + 租户 ContextVar；而本模块**按 `tenant_id` 缓存**。两者一旦不一致（后台任务、或 F052 / F055 在别的租户上下文里带 tenant_id 调用），就是把甲租户的行缓存到乙租户键下、有效期 60 秒的跨租户泄漏。新增 `_as_tenant(tenant_id)` 上下文管理器，在目录加载与 `_explain_miss` 期间把 `current_tenant_id` / admin-scope 覆盖 / `visible_tenant_ids` 一起绑到参数上，使公开签名名副其实。本面自身行为不变（`verify_open_api_access` 本就设了同样的三项）。
11. **Anthropic 路径只认了 `messages`，认不出真实客户端发的 `v1/messages`** —— Anthropic 客户端拿到的是 origin、自己补 `/v1/messages`；把 `ANTHROPIC_BASE_URL` 指到我们公布的地址（已以 `/v1` 结尾）就会打到 `…/model/v1/v1/messages`，原实现答 26201「没这个端点」而不是 AC-03 / AC-32 承诺的协议提示。已改为两种拼法都答 26202，测试参数化。
12. **`_instantiate` 失败一律记 `model_unavailable`，与 D9 的 result 词表不符** —— 10013（provider 客户端初始化失败）映射到 26231 上游失败，却在账本里记成「模型不可用」。已按错误族分流：26211 / 26212 / 26213 记 `model_unavailable`，其余记 `upstream_failed`。
13. **三处测试补强** —— ① `client_disconnected` 分支此前无任何用例（T014 / T017 都写了要断言），补 `test_a_client_that_walks_away_mid_stream_is_recorded_as_such`；② `test_a_full_queue_is_reported_rather_than_silently_dropped` 原本只断言 `enqueue` 返回 `False`，`caplog` 拿到手却没断言（loguru 不进 `caplog`，断了也是空转），改为断言 `emit_metric("model_call_record", status="dropped")` 真的发出——「不静默」这半句这才有人守；③ AC-06 的反向蕴含（持 `model:invoke` 不能调 `/api/v2/workstation/chat/completions`）T012 写了但没落地，补 `test_model_invoke_does_not_open_the_daily_chat_data_plane`。
14. **仍未覆盖、且本地覆盖不了的一条（Wave 1–5 口径）**：T017 列的 `test_telemetry_event_same_tokens`（AC-23「与平台既有 token 账本同源」的端到端断言）没有落地，也不打算在单测里造——本面的用例把 `BishengLLM` 整个替换成假件，遥测那一段根本不会跑，造一个假遥测只会守住假件自己。今天的证据是 `test_the_model_is_built_for_this_face_and_charged_to_the_resource_owner`（`app_type == MODEL_GATEWAY`、`user_id == resource_owner_user_id`）+ `usage_from` 与遥测取同一个最终结果对象；真正的同源核对是 T028 在 114 上按 `trace_id` 比对 ES 事件与 `model_call_record`。

**2026-09-16 Wave 6 实施（T022–T024，上游解除阻塞后）**

15. **T023 计划的注册落点改了，而且比原计划严** —— 任务原文写「新建 `app_runtime/domain/services/obo_token.py`、在 `main.py` lifespan 调 `register_access_subject_verifier`」。实际上游已经把 `verify_obo_token` 留在 `entry_authz_service.py`（与 `_issue_obo_token` 同文件，签发与验签的常量共享因此是编译期保证的，不是约定），适配器 `AccessSubjectVerifier` 也在那里；**注册点是 F055 的组合根 `app_publish/composition.py:register()`，两个 Port 同一个函数装**。没有另建模块、没有在 `open_api` 里 import `app_runtime`（依赖方向仍是 F055 → F054 → 无），并且避免了「只注册一个」的半接线。按「上游已给出更好的实现就不重复造」处理，本任务不新写实现代码。
16. **T022 要求的「经真实 `CredentialService.issue` 签发」落在 `test/app_publish/`，不在 `test/open_api/`** —— 真实签发要 `app` / `hosted_app_subject` / `api_credential` 三张表加凭据缓存，这套 SQLite 夹具只有 `test/app_publish/conftest.py` 有（`publish_db` / `app_factory` / `credential_redis` / `hosted_app_resolver`），在 `test/open_api/` 里重建一份等于把 F055 的 schema 抄第二遍。落法：端到端三条进 `test/app_publish/test_capability_model.py`（该文件本就是 T024 指定的 F055 归属落点），面行为的 21 条进 `test/open_api/test_model_gateway_hosted_app.py`（T022 指定的文件名，用 `hosted_app_principal()` + 真 Port）。两边共用 `test/open_api/model_gateway_fixtures.py` 的 `install_catalog`，所以「租户有哪些模型」不会两处分叉。
17. **`hosted_app_resolver` 夹具从 `test_app_credential.py` 移进 `test/app_publish/conftest.py`** —— 它要拆五个进程级注册表，第二份拷贝迟早漂移。`test_app_credential.py` 的 40 条用例逐字未改，仍全绿。
18. **T023 顺手核实到一条 F054 归属的 fail-open，未在本 Feature 修** —— `_issue_obo_token` 在 `obo_secret` 缺失、或与 `jwt_secret` 相同时**不签令牌、只记一条进程级日志**（`entry_authz_service.py:_warn_once`），入口照常放行。该函数的注释自己写了「等 OBO 有了第一个消费方就必须改 fail-closed」——本 Feature 就是那个消费方，但收紧的是**入口放行判据**（F054 的 AC-34 领域），不是本面的行为：本面这侧的表现是所有调用落 `app_self`，与「应用没转发令牌」无法区分，符合 spec 决议-5 允许的降级。已写进 design.md §6.2 的 F054 依赖行，留给 F054 处置。

**2026-09-16 Wave 6 复审（reviewer 复核 T022–T024 后补记）**

19. **「组合根被两个进程都调到」这条守卫原先只断言了 import** —— `test_both_process_entry_points_call_the_composition_root` 遍历 AST 找 `ImportFrom`，但 `main.py` / `worker/main.py` 都是在 `_register_app_publish_composition()` 里 `from ... import register as register_app_publish` 再调用；**删掉调用、留下 import**，原断言照样绿，而那个进程里两个 Port 全停在 fail-closed 默认值上——正是这条用例声称要拦的事。已改为先取 `register` 的本地别名、再断言存在对该别名的 `ast.Call`（用把 `register_app_publish()` 换成 `pass` 的变异验证过：改前通过、改后失败）。
20. **已知未覆盖的一个角落：声明写裸名、事后变歧义** —— 范围判定是 `ModelRange.allows` 的**名称集合成员测试**（`model_catalog.py:80-84`：`model.model_name in declared or model.qualified_name in declared`），不是「按 D5 重新解析一次」。声明写 `gpt-4o`、发布后管理员又接入第二个同样提供 `gpt-4o` 的服务商时：发布面 `model_capability_status` 走 `resolve_model_name(tenant, "gpt-4o")` 得 26214 → 标 `REASON_AMBIGUOUS` / 「已失效」，本面却仍然放行**限定名**请求（`azure-openai/gpt-4o` 与 `other/gpt-4o` 都过），等于应用拿到了一个它从未声明过的服务商。两侧因此并不同源，`test_the_model_face_and_the_publish_surface_read_the_same_resolution` 只覆盖了在线 / 下线 / 不存在三档（该用例 docstring 已写明边界）。**本轮不改语义**：AC-34 原文就是「声明中的模型 ∩ 租户已启用」的集合口径，而 D7 那句「按 D5 规则解析后与 C 求交」指向另一种口径，先由 F051 / F055 裁定该角落答 26214（与发布面一致）还是维持现状，再动 Wave 1–5 的 `allows`。触发条件窄（必须发布之后才出现同名服务商，此时再发布会被 F055 预检 16224 拦下），不阻塞交付。

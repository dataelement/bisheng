# Tasks: 开放 API 鉴权底座（默认拒绝 + 服务账号密钥 + 资源归属人）

**关联规格**: [spec.md](./spec.md)（65 条 AC，What 的唯一真相）· [design.md](./design.md)（How 的唯一真相，D1–D13 / 坑 1–27 / §4.2 契约）
**版本**: v3.0.0
**纵切**: [mvp-114-path.md](../mvp-114-path.md) §2 F049 行——Wave 1–2 全部为 `[MVP-114]` 任务，其后 Wave 为 release 必做
**代码事实口径**: 本文所有 `文件:行号` 沿用 design.md（`3.0-vibe` HEAD `b63a320f2`，2026-08-17 核实，路径以 `src/backend/bisheng/` 为根；前端另注 `platform/` = `src/frontend/platform/src/`、`client/` = `src/frontend/client/src/`）。行号会漂移，符号名不会——落地前以符号名重定位。

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-08-17 ★ 已过（决议-6 f/g/h/i 拍板，65 AC 定稿） |
| design.md | ✅ 已评审 | 本轮（2026-08-17 初版 + 同日 `/sdd-review design` 两轮 26 条修订）；接手时的第一入口 |
| tasks.md | ✅ 已拆解（2026-08-17） | 本文；同日 `/sdd-review tasks` 一轮 21 条修订（1 high / 8 medium / 12 low）已就地吸收 |
| 实现 | 🚧 进行中 | 26 / 76 完成（Wave 1 T001–T019 + Wave 2 后端 T020–T026）。偏差处理见 design.md 顶部调整原则 + `docs/SDD-Guide.md` §3-§4 |

---

## 开发模式

**按 Wave 组织任务**：Wave 1–2 = `[MVP-114]` 纵切首波（design D13 / K10：建号 → 签发 → `whoami` → `app:manage` 判定 + 三处结构性封口），部署 114 后即可支撑 F053 `login` / F055 复用 `Depends`；Wave 3–6 = 既有 v2 面收口与 release 必做项（INV-27 要求发版前全做，**F049 不得脱离 F050 单独对外发版**，K11）。每个任务标 `依赖:`，无依赖的可并行。

**后端 Test-First**：测试任务先于配对实现任务，`覆盖 AC` 逐条列举（禁范围写法）。基础设施任务（Alembic / ORM / 错误码 / Settings / conftest / 注册表）无测试配对、排最前。单测放 `src/backend/test/open_api/` 等 `test/<module>/`（不放 `test/` 根），`asyncio_mode=auto`。集成测试连 test 中间件（MySQL / Redis / OpenFGA），在 CI 跑；DM8 用例在 105 回归。

**HTTP 状态断言口径**（design K4 / D2 / §4.2）：`/api/v2/**` 断言**真 HTTP 状态**（401 / 403 / 404 / 503）；`/api/v1/service-accounts/**` 等管理端点断言**信封 `status_code`**（HTTP 仍 200）。

**前端**：Platform 任务附「手动验证」步骤（Playwright 未落地）；本 Feature **含 Client 任务**（design D8：两个免登录分享页真身在 client `pages/standaloneChat/`，platform 旧页已随 `36beaa00f` 删除——原「本 Feature 无 Client」的假设已被 design 推翻）。platform `react-query` 已冻结（坑 24），新页面用 `useTable` / `useState + useEffect`；新增 i18n key 三语同 PR。

**自包含任务**：每个任务内联文件、逻辑、AC 覆盖；设计论证指向 design §X 不复制。

**编号 ≠ 执行顺序**（评审修订）：Wave 1 内 validator 测试需要真实服务账号主体，故实际执行顺序为 T009 → T010 → T013 → T014 → T011 → T012（`依赖:` 已登记，编号保留不重排）；T047（`share_link.share_scope` Alembic）是无依赖的基础设施任务，实际与 T001 同批执行（Wave 1），编号保留在 Wave 4 只为与 share-token 通道叙事相邻。

**跨 Feature 副作用登记**（release-contract 表 1 / 检查项 17）：T001（`User` 表加列，ServiceAccount 对象归 F049 但 `User` 表本身不归）· T016 / T019 / T058 / T059 / T064（改 `user` DAO 默认过滤、`grant_subject_service` / `canonical_source` / F048 runtime / `permission.application`——PermissionGrant 归 F048，本 Feature 只增显式参数与新来源值）· T024（`MANAGEMENT_API_PREFIXES` 加项 = F019 元组扩展）· T040（`open_endpoints` router 挂全局依赖 + 删 `chat.py`）· T042（`worker/workflow/redis_callback.py set_workflow_status` 状态载荷加 `owner_user_id / tenant_id`——workflow worker 写 / `stop` 端点读的共享载荷，加键不删键、老读者无感）· T047 / T049（ShareLink 写增量，表 1 已登记归 F049）· T050（`bisheng/api/router.py` 新增 `app_shares_router` 直接挂接）· T069（`tenant_reconcile` / `quota_service` 加类型条件）。

---

## Tasks

### Wave 1 · `[MVP-114]` 基础设施（无测试配对，排最前）

- [x] **T001**: `[MVP-114]` Alembic：`user.user_type` 列
  **文件**: `src/backend/bisheng/core/database/alembic/versions/v3_0_0_f049_user_user_type.py`（新，模板 `v2_5_1_f012_user_token_version.py`）, `src/backend/bisheng/user/domain/models/user.py`（`User` 模型加 `user_type: str = Field(default='human', max_length=16, index=True)`）
  **逻辑**: `upgrade()`：`ALTER TABLE user ADD COLUMN user_type VARCHAR(16) NOT NULL DEFAULT 'human'` + `ix_user_user_type` 索引；`VARCHAR` 不用 `CHAR`（K5 DM8）；`server_default` 是 revision 允许的唯一数据效果（AC-51 零迁移：不 UPDATE 任何存量行、存量全部按缺省 `human`）。
  **回滚**: `downgrade()` 删索引 + 删列；服务账号行（`user_type='service'`）在 downgrade 后退化为普通用户行——因此 downgrade 前须先删全部服务账号（T014 delete）或接受其变为可见普通用户；说明写在 revision docstring。
  **跨 Feature**: `User` 表加列，自然人侧行为不变（缺省 `human`）；影响面 = 全部 `User` 查询无感、`_filter_users_statement` 默认过滤在 T016 才生效。
  **依赖**: 无

- [x] **T002**: `[MVP-114]` ORM `api_credential` / `service_account` 模型 + DAO + 租户感知注册
  **文件**: `src/backend/bisheng/open_api/domain/models/api_credential.py`（新）, `src/backend/bisheng/open_api/domain/models/service_account.py`（新）, `src/backend/bisheng/core/database/tenant_filter.py`（`_TENANT_AWARE_MODEL_MODULES` 登记 `bisheng.open_api.domain.models`）
  **逻辑**: 按 design §4.2 建两表（继承 `SQLModelSerializable`，含 `tenant_id / create_time / update_time`）：`api_credential`（`subject_kind VARCHAR(32)` / `subject_id VARCHAR(64)` / `key_prefix VARCHAR(16)` / `last4 VARCHAR(4)` / `token_hash VARCHAR(64) unique` / `scopes JsonType` / `expires_at` / `revoked_at` / `last_used_at` / `revoke_reason VARCHAR(32)` / `created_by`；**无 status 枚举列**，K3）；`service_account`（`user_id` PK FK user / `tenant_id` / `resource_owner_user_id` / `description` / `created_by` / `disabled_at` / `deleted_at`）。DAO 只提供**单行 ORM**读写：`ApiCredentialDao.aget_by_hash(session)`（调用方负责 `bypass_tenant_filter()`）/ `alist_by_subject` / `aupdate_row`；`ServiceAccountDao.acreate_with_user(session, ...)`（接受外部 session、不在 DAO 内开会话，D1 建号事务）/ `aget` / `alist_page` / `aset_timestamps`。**禁**批量 UPDATE / DELETE 与 `text()`（K6）。新表靠 `create_all(checkfirst=True)`（K5）。
  **回滚**: 新表无 Alembic；回滚 = 删两表（本 Feature 之前无数据、无外部依赖）；`api_credential` 撤销记录是审计资产，删表前 dump。
  **依赖**: T001

- [x] **T003**: `[MVP-114]` 错误码 260 段 + C5 登记 + 三语
  **文件**: `src/backend/bisheng/common/errcode/open_api.py`（新）, `docs/constitution.md`（C5 登记表 260 段由 reserved 改 implemented）, `src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`（三语视为一组）
  **逻辑**: 按 design D10 定义 `OpenApiAuthError(BaseErrorCode)` 基类（携带 `http_status`）与本期启用码：`26001`(401) / `26002`(401) / `26003`(403，`data.required` 指明缺哪位) / `26004`(403) / `26012`(403) / `26020`–`26031`（含 `26030` 503、`26031` 500）。`26013 / 26014` 不复用；`26005–26007 / 26010 / 26016` 留 F050。三语文案落 `packages/locales`（K12：缺任一语 CI `check-i18n` 失败）；生成物 `platform/public/locales/*/api_errors.json` / `client/src/locales/*/api_errors.gen.json` 由脚本生成、不手改。
  **依赖**: 无

- [x] **T004**: `[MVP-114]` 开放能力层开关三段式（后端两段）+ `open_api` Settings
  **文件**: `src/backend/bisheng/core/config/open_platform.py`（新：`OpenPlatformConf(enabled: bool = False)`）, `src/backend/bisheng/core/config/settings.py`（`:782` `multi_tenant` 旁加 `open_platform: OpenPlatformConf` 与 `open_api: OpenApiConf(service_account_idle_days=90, credential_cache_ttl_seconds=3 上限 5)`）, `src/backend/bisheng/api/v1/endpoints.py`（`get_env :60-108` 增 `open_platform_enabled`）
  **逻辑**: 进程级 config.yaml、非 DB 热配置（K8 / D9 S2，先例 `multi_tenant.enabled`）。**部署顺序坑 22**：`load_settings_from_yaml` 对未知顶层键拒启 → 先发代码再加 yaml 键（写进 T033）。
  **依赖**: 无

- [x] **T005**: `[MVP-114]` `OPEN_API_SCOPES` 注册表 + `@open_api_scope` 标记 + ContextVar
  **文件**: `src/backend/bisheng/open_api/domain/scopes.py`（新）, `src/backend/bisheng/open_api/domain/context.py`（新）
  **逻辑**: `OPEN_API_SCOPES`：每位 `code / group / label_key / desc_key / endpoints[] / requires_open_platform / pending_note_key`（D9）——基础位 `workflow:invoke/read`、`knowledge:read/write`、`assistant:invoke/read`、`chat:invoke`（`endpoints=()` + `pending_note_key`「端点随后续版本开放」）+ 三扩展位 `model:invoke / identity:read / app:manage`（`group='local_dev_toolkit'`，`requires_open_platform=True`）；**不登记 `delegate`**（AC-14）。端点映射表按 D3（38 个：`workflow:invoke` 3 / `workflow:read` 1 / `assistant:invoke` 4 / `assistant:read` 2 / `knowledge:read` 7 / `knowledge:write` 21）。`@open_api_scope(scope: str | None, allow_share_token=False)` 纯标记装饰器（只设函数属性、无 FastAPI 依赖，v2 端点文件 import 它不触 RULE-5）；`visible_scopes(open_platform_enabled)` 供 `/scopes` 端点与签发校验。`context.py`：`current_open_api_principal: ContextVar[OpenApiPrincipal | None]`（`credential_id / subject_kind / subject_user_id / resource_owner_user_id / share_link_id / scopes`，§4.2 `UserPayload.open_api_principal` 形状）。
  **依赖**: 无

- [x] **T006**: `[MVP-114]` 请求 / 响应 schemas
  **文件**: `src/backend/bisheng/open_api/domain/schemas/service_account.py`（新）, `src/backend/bisheng/open_api/domain/schemas/credential.py`（新）
  **逻辑**: pydantic：`ServiceAccountCreate(name, description, resource_owner_user_id)` / `ServiceAccountUpdate` / `ServiceAccountItem`（列表列：名称 / 状态 / 有效密钥数 / 归属人（含 `owner_disabled`）/ 最后调用 / 创建人 / 创建时间；分页 `PageData` + meta `idle_days`）；`KeyIssueRequest(name, scopes, expires_at?)` / `KeyUpdateRequest` / `KeyItem`（掩码 = `bs-sak-********` + 末四位）/ `KeyIssuedResponse`（唯一含 `plaintext` 的模型）/ `WhoamiResponse`（`subject_kind / service_account{id,name} / tenant_id / scopes / key_mask / expires_at`）。
  **依赖**: T005

- [x] **T007**: `[MVP-114]` 审计动作后端 lockstep 登记
  **文件**: `src/backend/bisheng/database/models/audit_log.py`（`_UI_VISIBLE_V2_ACTIONS :178-201` + `_V2_NAMESPACE_TO_ACTION_PREFIX :207-211` 加 `open_api.`）
  **逻辑**: 登记 D11 全部 action：`open_api.service_account.{create,update,enable,disable,delete}`、`open_api.api_key.{issue,update,revoke,revoke_all,expire,invalidate_by_subject}`、`open_api.grant.{add,update,remove,remove_all}`、`open_api.share_link.{revoke,expire}`、`open_api.ws.connect`（后三族 Wave 4–5 才产生事件，登记一次到位避免二次改同一处）。前端两处 lockstep 见 T032。
  **依赖**: 无

- [x] **T008**: `[MVP-114]` `test/open_api/conftest.py` 测试基础设施
  **文件**: `src/backend/test/open_api/conftest.py`（新）, `src/backend/test/open_api/__init__.py`（新）
  **逻辑**: fixtures：`tenant_admin_payload`（非超管的租户管理员 `UserPayload`，避免 admin 短路）/ `human_user`（本租户已启用自然人，作归属人）/ `service_account_factory`（经 T014 `ServiceAccountService.create` 建号——**fixture 体内惰性 `import`**，conftest 顶层不 import T010 / T014 模块，T009 阶段整包收集不因模块缺失而失败）/ `credential_factory`（经 T010 签发，返回明文 + 行；同样惰性 import）/ `redis_client`（真 Redis，`oapi:*` 键用后清理）/ `v2_client`（`TestClient(app, raise_server_exceptions=False)`，断言真 HTTP 状态）/ `sub_tenant`（多租户子租户 + 其管理员，用于跨租户断言）/ `fga_down`（monkeypatch 让 F048 判定抛 `PermissionServiceUnavailableError`）。SOCKS 代理清理：`test/conftest.py` **无**任何 proxy / socks 处理（原锚点已失效），仓内先例只有 `test/linsight/test_e2e_llm_resilience.py`（清 `HTTP(S)_PROXY / ALL_PROXY` env）——本 conftest 自带 `autouse` fixture 清代理 env（memory：缺 `socksio` 整批误报 ERROR）。
  **依赖**: T002

### Wave 1 · `[MVP-114]` 后端 Domain（Test-First）

- [x] **T009**: `[MVP-114]` `CredentialService` 单元测试
  **文件**: `src/backend/test/open_api/test_credential_service.py`（新）
  **逻辑**: `test_issue_returns_plaintext_once_and_stores_hash_only`（明文以 `bs-sak-` 起、43 位 urlsafe、DB 只有 sha256、`key_prefix / last4` 正确、掩码格式 `bs-sak-********xxxx`）→ AC-02；`test_default_scopes_empty_and_unknown_scope_rejected_26025` → AC-06；`test_issue_hosted_app_kind_accepted`（`subject_kind='hosted_app'` 可存可撤，D2「主体解析器」承诺）；`test_validity_predicate`（撤销 / 过期 / 边界时刻 `expires_at == now`）→ AC-05；`test_revoke_soft_keeps_row_and_history`（`revoked_at` 置位、行与归属保留、`revoke_reason='manual'`）→ AC-11；`test_revoke_deletes_cache_key`（撤销后 `oapi:cred:{hash}` 不存在，主动失效不靠 TTL）→ AC-03；`test_update_scopes_name_expires_invalidates_cache_immediately` → AC-08；`test_revoke_by_subject_batch`（名下全部 `revoked_at`、`revoke_reason='batch'`、逐键 `adelete`）→ AC-09；`test_touch_last_used_throttled_60s`（`SET NX EX 60` 闸内只写一次单行 UPDATE）→ AC-10；`test_expire_lazy_marks_reason_once`（过期首次校验拒绝时 `revoke_reason='expired'`、`revoked_at` 仍 NULL、并发两次只一次 `rowcount==1`）→ AC-05 / AC-12；`test_audit_events_never_contain_plaintext`（issue / update / revoke / revoke_all / expire 五事件的 `metadata` 只含掩码）→ AC-12。
  **覆盖 AC**: AC-02, AC-03, AC-05, AC-06, AC-08, AC-09, AC-10, AC-11, AC-12
  **依赖**: T002, T003, T005, T008

- [x] **T010**: `[MVP-114]` `CredentialService` 实现
  **文件**: `src/backend/bisheng/open_api/domain/services/credential_service.py`（新）
  **逻辑**: `issue(subject_kind, subject_id, tenant_id, name, scopes, expires_at, created_by)`：`secrets.token_urlsafe(32)`（坑 17：不用 `generate_short_high_entropy_string`）→ 明文 `'bs-sak-' + 43 位` → `sha256` → 单行写 → 审计 `open_api.api_key.issue`（`AuditLogDao.ainsert_v2`，`metadata` 只掩码）→ 返回明文（唯一出口）。`update / revoke(reason) / revoke_by_subject(reason) / list_by_subject / touch_last_used`；每次写后 `invalidate_cache(hashes)`（按 DB 清单逐个 `adelete('oapi:cred:{hash}')`，不 `SCAN`，K1 / K7；每次调用累加 `open_api.cache.invalidate` 计数 / 结构化日志，D11 指标由此产生）；`touch_last_used`：`asetNx('oapi:cred:lastused:{id}', 1, ex=60)` 成功才做带主键单行 UPDATE（坑 20 DM8 写放大）；`mark_expired_lazy(id)`：`UPDATE ... SET revoke_reason='expired' WHERE id=:id AND revoke_reason IS NULL`，`rowcount==1` 才审计 `open_api.api_key.expire`（`operator_id=0` → `system`）。scopes 校验：`∉ OPEN_API_SCOPES` → 26025；含 `delegate` → 26024；三扩展位而 `settings.open_platform.enabled` 为 False → 26023。
  **测试**: T009 全部通过
  **覆盖 AC**: AC-02, AC-03, AC-05, AC-06, AC-08, AC-09, AC-10, AC-11, AC-12
  **依赖**: T009

- [x] **T011**: `[MVP-114]` `credential_validator` 单元 + 集成测试
  **文件**: `src/backend/test/open_api/test_credential_validator.py`（新）
  **逻辑**: `test_missing_or_malformed_bearer_26001` / `test_unknown_hash_26002_constant_time`（`hmac.compare_digest`）→ AC-01；`test_revoked_rejected_within_5s`（撤销后立即校验被拒；采样多次 ≤ 3s）→ AC-03；`test_expired_rejected_even_when_cache_hit`（缓存命中路径每请求比对 `expires_at`）→ AC-05；`test_subject_disabled_or_deleted_rejected_26027`（伴生表两时间戳任一非空 → 拒）→ AC-21 / AC-47；`test_subject_tenant_mismatch_rejected`（主体活跃租户 ≠ 密钥租户 → 26002；spec §3 跨租户组合一律拒绝）；`test_sets_tenant_context_and_visible_tenants`（校验通过后 `get_current_tenant_id()==密钥租户`；子租户密钥 `visible == {leaf, 1}`、Root `{1}`；坑 2 / D2「可见租户」）→ AC-32；`test_user_payload_constructed_directly`（`is_global_super=False`、`user_role=[]`、`open_api_principal` 填充、**不调 `init_login_user`**）→ AC-32；`test_hosted_app_without_resolver_26002`（`SUBJECT_RESOLVERS` 只注册 `service_account`）；`test_redis_down_fail_closed_26030` / `test_db_down_fail_closed_26030`（monkeypatch `get_redis_client` / session 抛错 → 拒绝而非放行，K2）→ AC-34；`test_disabled_tenant_blacklist_rejects`（`DISABLED_TENANT_KEY` 命中 → 拒）；`test_cache_payload_minimal_not_pickled_userpayload`。
  **覆盖 AC**: AC-01, AC-03, AC-05, AC-21, AC-32, AC-34, AC-47
  **依赖**: T010, T014, T008（`service_account_factory` 需 T014 建号 Service，见「编号 ≠ 执行顺序」）

- [x] **T012**: `[MVP-114]` `credential_validator` 实现
  **文件**: `src/backend/bisheng/open_api/domain/services/credential_validator.py`（新）, `src/backend/bisheng/user/domain/services/auth.py`（`LoginUser :196` 加可选字段 `open_api_principal: 'OpenApiPrincipal | None' = None`——`UserPayload(LoginUser)`（`common/dependencies/user_deps.py:8`）自动继承、该文件不改；类型经 `TYPE_CHECKING` 前向引用或把 `OpenApiPrincipal` 定义为不 import `user` 域的独立 pydantic 模型（`open_api/domain/context.py`，T005），避免 `user ↔ open_api` 循环 import）
  **逻辑**: 纯 domain 函数 `validate_bearer(token: str) -> OpenApiPrincipal + UserPayload`，校验顺序固定为 D2：提取 Bearer → `bypass_tenant_filter()` 下 `aget_by_hash(sha256)`（K6）→ 恒时比较（先例 `sso_sync/domain/services/hmac_auth.py:103`）→ 未撤销 → 未过期（过期则 `mark_expired_lazy` + 拒 26002）→ 按 `subject_kind` 分派 `SUBJECT_RESOLVERS`（F049 只注册 `service_account`：`user_type=='service'` ∧ 伴生表两时间戳皆空 ∧ `UserTenant.status=='active' ∧ is_active==1` 且 == 密钥租户；`hosted_app` 无解析器 → 26002）→ 回填 Redis `oapi:cred:{sha256}`（最小载荷、TTL = `settings.open_api.credential_cache_ttl_seconds`）→ **每请求（含命中）**：`expires_at` 比对 + `DISABLED_TENANT_KEY` 黑名单（`tenant/domain/services/tenant_service.py:44`）→ `set_current_tenant_id(密钥租户)`（K9 无条件覆盖）+ `set_visible_tenant_ids`（复刻 `http_middleware.py:210-231 _compute_visible_tenant_ids`）→ 直接构造 `UserPayload(user_id, user_name, user_role=[], tenant_id, token_version=0, is_global_super=False, open_api_principal=...)`（坑 4：不调 `init_login_user` / `init_login_user_sync`）→ 写 `current_open_api_principal`。任何 Redis / DB 异常 → `26030`（503，K2 fail-closed）。`open_api_principal` 字段位置见上文文件清单（`LoginUser :196`，缺省 `None`）。
  **测试**: T011 全部通过
  **覆盖 AC**: AC-01, AC-03, AC-05, AC-21, AC-32, AC-34, AC-47
  **依赖**: T011

- [x] **T013**: `[MVP-114]` `ServiceAccountService` 单元测试
  **文件**: `src/backend/test/open_api/test_service_account_service.py`（新）
  **逻辑**: `test_create_single_transaction`（一个 session 内 `User(user_type='service', source='service_account', external_id=None, password=哨兵)` → flush → `ServiceAccount` → `UserTenant(status='active', is_active=1)` → 单次 commit；模拟中途异常 → 三表皆无残行）→ AC-19；`test_create_requires_owner_human_active_same_tenant`（缺归属人 / 归属人是服务账号 / 已禁用 / 他租户 → 26021）→ AC-23；`test_tenant_taken_from_admin_context_not_from_body`（请求体带 `tenant_id` 被忽略；`admin-scope` 下取当前作用域租户）→ AC-23；`test_created_account_is_grantable_immediately`（`aget_active_user_tenant` 有行、`is_active==1`，坑 8）→ AC-19；`test_disable_invalidates_keys_within_5s`（`disabled_at` 置位 → 名下缓存键全删 → 校验拒 26027；`revoke_reason` 不改、密钥行不动）→ AC-21 / AC-47；`test_enable_restores`（清 `disabled_at` → 校验恢复、授权与配置未动）→ AC-47；`test_delete_wave1_shape`（撤销全部密钥 `revoke_reason='subject_deleted'` + `deleted_at` + `user.delete=1` 投影 + 审计；Wave 5 T065 升级为反查 REMOVE 前置步）→ AC-21 / AC-48；`test_change_owner_not_retroactive`（换归属人只改伴生表列，历史 creator 列不动——断言 Service 不发起任何对 `knowledge` 等业务表的写）→ AC-27；`test_owner_disabled_does_not_cascade`（禁用归属人 → 服务账号与密钥仍有效；列表行 `owner_disabled=True`）→ AC-28；`test_audit_account_family_events`（create / update / enable / disable / delete 五事件 + 密钥失效 `invalidate_by_subject` 带触发原因）→ AC-12。
  **覆盖 AC**: AC-12, AC-19, AC-21, AC-23, AC-27, AC-28, AC-47, AC-48
  **依赖**: T010, T008

- [x] **T014**: `[MVP-114]` `ServiceAccountService` 实现
  **文件**: `src/backend/bisheng/open_api/domain/services/service_account_service.py`（新）
  **逻辑**: `create(admin, name, description, resource_owner_user_id)`（D1 建号事务：`async with get_async_db_session()` 内三 add + 一次 commit；**不复用** `UserDao.create_user` / `aactivate_user_tenant` / `user_register` / `add_user_and_default_role`（坑 6：后者会把它塞进 guest 部门）；`external_id=NULL` 固定，坑 5）；`update(name/description/owner)`（归属人校验同 create）；`enable / disable`（写伴生表时间戳 + 同事务写穿 `user.delete` 投影 + `CredentialService.invalidate_cache(名下全部)` + 审计）；`delete`（Wave 1 形态：`revoke_by_subject('subject_deleted')` → `deleted_at` → 投影 → 审计；T065 前插反查 REMOVE）；`list_page(tenant, q, page)`（伴生表自动租户过滤兜住 AC-07；水合：`user_name` 走 `aget_user_by_ids`、有效密钥数、归属人名 + `owner_disabled`、`last_used_at = max(名下密钥)`、`idle_days` 阈值随 meta）；`get(id)`；读侧状态只读伴生表两列不读 `user.delete`（D1「读侧口径统一」）。归属人校验：`aget_user` 存在 ∧ `delete==0` ∧ `user_type=='human'` ∧ 活跃租户 == 当前租户，否则 26021。
  **测试**: T013 全部通过
  **覆盖 AC**: AC-12, AC-19, AC-21, AC-23, AC-27, AC-28, AC-47, AC-48
  **依赖**: T013

- [x] **T015**: `[MVP-114]` 登录守卫 / `assert_natural_persons` / DAO 排除 测试
  **文件**: `src/backend/test/user/test_service_account_login_guard.py`（新）
  **逻辑**: **登录守卫矩阵**（集成）：本地登录 `/user/login`（`user/domain/services/user.py:460`）、旧 SSO `/user/sso`（`user/api/user.py:97`，按用户名匹配，坑 5）、login-sync HMAC（`sso_sync/domain/services/login_sync_service.py:221`）、切租户（`tenant/domain/services/tenant_service.py:662`）四入口对服务账号一律 **`raise` 26012**（断言不是被压成「无菜单」的 `UserNoWebMenuForLoginError`，坑 3）；`test_guard_runs_before_admin_role_shortcut`（给服务账号误挂 AdminRole 仍 26012；守卫在 `:388 bypass` 与 `:394 AdminRole return` 之前）→ AC-15；`test_login_candidates_exclude_service`（`aget_login_candidates_by_account` 第二道锁）→ AC-15。**测试降级（AC-15 其余入口）**：Java 网关登录同步 / SSO 网关回调 / 商业版 license 登录等入口只能在 109 联调环境手动验证（网关不在本仓、无 TestClient 可达）——理由：这些入口最终都汇入上述四条守卫路径之一（design 坑 3「公共守卫 4 个调用点」），自动化四条 + 手动其余；手动步骤写进 T075。**DAO 排除**：`_filter_users_statement` 默认 `user_type='human'`、显式 `user_type=None` 才含；`/user/list` 超管与非超管两分支均不含服务账号；`aget_user_by_ids` **仍能**取到（名称水合不过滤）→ AC-16。**管理接口**：`assert_natural_persons([sa_id])` 抛 26022；`/user/update` 对服务账号（含只翻 `delete` 位）→ 26022；`/user/reset_password` → 26022 → AC-20；`/user/role_add`（任意角色含管理员角色）→ 26022；`grant_tenant_admin` → 26022 → AC-22。
  **覆盖 AC**: AC-15, AC-16, AC-20, AC-22
  **依赖**: T014, T008

- [x] **T016**: `[MVP-114]` 用户域守卫与 DAO 排除实现
  **文件**: `src/backend/bisheng/user/domain/services/user.py`（`_reject_login_if_user_has_no_usable_access :373`：**最前**（`:388 bypass` 之前）`if user.user_type == 'service': raise ServiceAccountLoginForbiddenError()`（26012）；新增 **同步** `assert_natural_persons(user_ids: list[int]) -> None`（`UserDao.get_user_by_ids`，供同步调用方 T071 `role_group_service` 三方法）与 **异步** `aassert_natural_persons(user_ids)`（`aget_user_by_ids`，供 async 端点 / Service：T017 `/user/update` `:664` 等三端点均 `async def`、`grant_tenant_admin :37` async、T071 `aadd_members :1749` / `aset_admins :1986` async）；两者语义相同：任一目标 `user_type=='service'` → 26022）, `src/backend/bisheng/user/domain/models/user.py`（`_filter_users_statement :259-264` 增 `user_type: str | None = 'human'` 默认参数并透传到 `filter_users :267` / `afilter_users :279`；`aget_login_candidates_by_account :212-223` 加 `User.user_type == 'human'` 第二道锁）
  **逻辑**: 见 D7 / 坑 3 / 坑 5 / 坑 10（`get_all_users / search_user_by_name / get_user_with_group_role / get_user_by_ids / aget_user_by_ids / get_unique_user_by_name / aget_users_by_username / aget_by_source` 旁路**逐个判定不动**：名称水合保持不过滤）。`raise` 而非 `return`（`tenant_service.py:663-665` / `login_sync_service.py:228-230` 会把非 `UserNoRoleForLoginError` 返回值压成「无菜单」）。
  **跨 Feature**: `_filter_users_statement` 是 `/user/list` 全部 8 处 platform 消费点的共同底座（E2 §1.3）——默认排除即全部生效；影响面 = 用户管理 / 审批人 / 部门加成员 / 用户组加成员 / 创建租户选管理员等选人框不再显示服务账号（AC-16 预期行为）。
  **测试**: T015 守卫 / DAO / `assert_natural_persons` 部分通过
  **覆盖 AC**: AC-15, AC-16, AC-20, AC-22
  **依赖**: T015

- [x] **T017**: `[MVP-114]` 管理接口拒绝（用户 API + 租户管理员）
  **文件**: `src/backend/bisheng/user/api/user.py`（`/user/update :663-724`（含 `:709` 直写 `delete` 位）、`/user/reset_password :1032-1066`、`/user/role_add :874-965` 入口调 `assert_natural_persons`）, `src/backend/bisheng/tenant/domain/services/tenant_admin_service.py`（`grant_tenant_admin :37-58` 入口调 `assert_natural_persons`）
  **逻辑**: 三个用户 API 与租户管理员授予（均 async）在做任何写之前调 `aassert_natural_persons` 断言目标为自然人，否则 26022（AC-20 / AC-22 的「管理员身份 / 角色」部分；部门 / 用户组其余矩阵项 Wave 6 T071）。`/user/change_password :1067`（改自己）与 `change_password_public :1095`（按 `external_id`）对服务账号结构性不可达，不加。
  **测试**: T015 管理接口部分通过
  **覆盖 AC**: AC-20, AC-22
  **依赖**: T016

- [x] **T018**: `[MVP-114]` 授权候选过滤 + 授权主体校验拒绝 测试
  **文件**: `src/backend/test/permission/test_service_account_subject_exclusion.py`（新）
  **逻辑**: `test_list_candidate_users_excludes_service`（`grant_subject_service.list_candidate_users`——两个资源侧授权弹窗的独立查询，不走 `/user/list`）→ AC-16；`test_display_names_still_resolves_service_account`（`f048_permission_subject.display_names :110` 走 `aget_user_by_ids`，已授权对象列表可显示）→ AC-16；`test_canonical_source_rejects_service_account_subject_26029`（资源侧 `POST /api/v1/permissions/resources/{t}/{id}/grants:mutate` 授服务账号 → 26029）；`test_canonical_source_allows_when_explicit_flag`（`allow_service_account_subject=True` 上下文放行——主体侧端点 T065 用）→ INV-29 结构性保证（AC-16 失败方向 = 看不到 / 授不进）。
  **覆盖 AC**: AC-16
  **依赖**: T014, T008

- [x] **T019**: `[MVP-114]` 授权候选过滤 + `canonical_source` 拒绝 实现
  **文件**: `src/backend/bisheng/permission/domain/services/grant_subject_service.py`（`list_candidate_users :70-121`，条件 `:90` 加 `User.user_type == 'human'`）, `src/backend/bisheng/tenant/domain/services/f048_permission_subject.py`（`canonical_source :53-71` 对 `user` 主体查到 `user_type=='service'` → 26029，除非 `allow_service_account_subject=True`）, `src/backend/bisheng/permission/application/resource_api.py`（`PermissionSubjectDirectoryPort.canonical_source :45` 协议签名加 keyword-only `allow_service_account_subject: bool = False`；`mutate_grants :288` 加同名 kw（缺省 False）并在 `:308` 调用处透传）
  **逻辑**: D7 三处结构性封口的后两处（第一处在 T016）。`allow_service_account_subject` 经 application 层显式参数传入（D6 W2）：`resource_api.mutate_grants(allow_service_account_subject=...)` → Port → `canonical_source`；资源侧端点永不设置，主体侧端点 T065 传 True。`channel/domain/services/f048_channel_permission.py:292` 也有同名 `canonical_source` 但签名不同（带 `actor`、无 `tenant_id / userset_relation`，非该 Port 的实现）——落地时核实：若它被当作 `PermissionSubjectDirectoryPort` 注入则同步加缺省参数，否则不动。
  **跨 Feature**: 改 F048 主体校验层（PermissionGrant 归 F048）——只加拒绝条件与显式放行参数，不改判定链；资源侧授权弹窗与 `grants:mutate` 对自然人行为不变。
  **测试**: T018 全部通过
  **覆盖 AC**: AC-16
  **依赖**: T018

### Wave 2 · `[MVP-114]` 后端 API 层（Test-First）

- [x] **T020**: `[MVP-114]` 鉴权依赖 + 专属 handler + `whoami` 集成测试
  **文件**: `src/backend/test/open_api/test_open_api_auth_api.py`（新）
  **逻辑**: 对 `GET /api/v2/auth/whoami` 断言**真 HTTP 状态**：无头 → 401 `26001`、改一位 → 401 `26002`（信封 `{status_code,status_message,data}` 形状不变）→ AC-01；`test_scope_none_marker_skips_scope_check`（`whoami` 标 `@open_api_scope(None)`，无位也通过）；`test_unregistered_endpoint_26031`（临时挂一个无标记路由到带依赖的 router → 500 `26031`，结构性 fail-closed）；`test_missing_scope_403_with_required`（临时挂 `@open_api_scope('assistant:read')` 路由，密钥无该位 → 403 `26003` `data.required=='assistant:read'`）→ AC-04；`test_app_manage_scope_check_via_factory`（`Depends(open_api_subject('app:manage'))` 工厂：有位通过 / 无位 403——F053 / F055 复用面）→ AC-04 / AC-13；`test_extension_scope_issue_rejected_when_platform_off`（`open_platform.enabled=False` 下签发含 `app:manage` → 26023；开后放行且 `whoami.scopes` 含之）→ AC-13；`test_identity_headers_rejected_26004`（`X-Bisheng-On-Behalf-Of` / `X-Bisheng-End-User` 任一存在 → 403 `26004`，且业务未执行）→ AC-33；`test_no_header_runs_as_key_subject`（`whoami.service_account.id == 主体`、`tenant_id == 密钥租户`）→ AC-32；`test_only_two_outcomes_no_silent_downgrade`（同一端点：无头 = 模式 S 结果；有头 = 26004；不存在返回空集 / 公开子集的第三种响应）→ AC-35；`test_fga_unavailable_503`（`fga_down` fixture + 临时路由内调 `require_business_action` → HTTP 503，无业务数据）与 `test_redis_down_503_26030` → AC-34；`test_v1_envelope_unchanged`（`/api/v1` 任一错误仍 HTTP 200 + 信封，K4 只对 v2 真实化）。
  **覆盖 AC**: AC-01, AC-04, AC-13, AC-32, AC-33, AC-34, AC-35
  **依赖**: T012, T008

- [x] **T021**: `[MVP-114]` `open_api/api/dependencies.py` + `whoami` 端点
  **文件**: `src/backend/bisheng/open_api/api/dependencies.py`（新）, `src/backend/bisheng/open_api/api/endpoints/auth.py`（新：`GET /auth/whoami`，`@open_api_scope(None)`）
  **逻辑**: `verify_open_api_access(conn: HTTPConnection)`（router 级依赖，HTTP + WS 同一函数；`isinstance(conn, WebSocket)` 分流——WS 分支的 share-token 解析随 T052 填入，本任务 WS 只走密钥分支）：调 `credential_validator.validate_bearer` → 读 `conn.scope['endpoint']` 上的 `@open_api_scope` 标记：**无标记 → 26031**；`scope=None` → 跳过位判定；有位 → `scope ∉ principal.scopes` → 26003（`data.required`）→ 身份传递头存在 → 26004（AC-33）→ `CredentialService.touch_last_used`。**可观测（design D11 / §7）**：依赖出口统一写一条结构化日志 `open_api.call`（`credential_id / subject_kind / subject_user_id / tenant_id / path / scope / outcome(ok|错误码) / latency_ms`，`logger.bind(event=...)`，成功与拒绝都写、不写明文）；拒绝路径累加计数 `open_api.auth.reject{code}`（沿用仓内既有 metrics 出口，若无则先只落结构化日志、指标名保留）；`open_api.cache.invalidate` 计数由 T010 `invalidate_cache` 内累加（本任务不重复）。`open_api_subject(scope: str | None) -> Depends` 工厂（供 F053 / F055 新 router：等价于「router 级依赖 + 端点级位判定」一体化）；`get_service_account_admin`（管理端点依赖：内部调 `UserPayload.get_tenant_admin_user`（`common/dependencies/user_deps.py:50-75`），把它抛出的 `LLMModelSharedReadonlyError`（19801）**改抛 `UnAuthorizedError`**（信封 403，§4.2）。`whoami` 返回 `WhoamiResponse`。
  **测试**: T020 通过（与 T022 合并验证）
  **覆盖 AC**: AC-01, AC-04, AC-13, AC-32, AC-33, AC-34, AC-35
  **依赖**: T020

- [x] **T022**: `[MVP-114]` 专属异常 handler + 路由注册
  **文件**: `src/backend/bisheng/main.py`（仿 `:165-167` 注册 `OpenApiAuthError` handler：路径以 `/api/v2` 开头 → `JSONResponse(status_code=http_status, content=信封)`；同 handler 把 `PermissionServiceUnavailableError`（19002）/ `PermissionBackendUnavailableError`（19201）在 `/api/v2` 上映射 HTTP 503；**不改** `handle_http_exception :22-36` 全局语义）, `src/backend/bisheng/open_api/api/router.py`（新：`/service-accounts` 子 router 挂 `/api/v1`；`/auth` 子 router **自带** `dependencies=[Depends(verify_open_api_access)]` 挂 `/api/v2`）, `src/backend/bisheng/api/router.py`（`include_router` 两处；`router_rpc :94` **本任务不改**）
  **逻辑**: **顺序说明（不改 design 口径，只定挂接时点）**：design D2 的挂接点是 `router_rpc :94`；MVP-114 阶段先把依赖挂在 `open_api` 自己的 v2 子 router 上（`whoami` 立即受保护、`Depends` 工厂立即可用），全局 `router_rpc` 的挂接与 38 端点标记在同一任务 T040 落地——否则 Wave 2 部署 114 后既有 v2 端点全部 26031、guest 分享页白屏（design §7 步 4 亦标「Wave 2 后」）。
  **测试**: T020 全部通过
  **覆盖 AC**: AC-01, AC-04, AC-13, AC-32, AC-33, AC-34, AC-35
  **依赖**: T021

- [x] **T023**: `[MVP-114]` 服务账号管理端点集成测试
  **文件**: `src/backend/test/open_api/test_service_account_api.py`（新）
  **逻辑**: 以 `tenant_admin_payload` 调 `/api/v1/service-accounts/**`（断言**信封码**）：`test_non_admin_403_envelope_not_19801`（普通用户 GET / POST → 信封 `status_code==403`，非 LLM 只读文案）→ AC-41 / AC-59；`test_create_requires_name_and_human_owner`（缺归属人 / 非自然人 → 26021；成功响应含 `id`）→ AC-23；`test_create_tenant_from_admin_scope`（多租户下超管经 admin-scope 头给子租户建号落子租户；未加前缀前 ScopeBar 无效——断言 `MANAGEMENT_API_PREFIXES` 含 `/api/v1/service-accounts`，坑 23）→ AC-23；`test_list_tenant_isolated`（子租户管理员只见本租户；跨租户 `GET /{id}` → 26020）→ AC-07；`test_list_columns`（名称 / 状态 / 有效密钥数（0 → 前端高亮的字段）/ 归属人 + `owner_disabled` / 最后调用 / 创建人 / 创建时间；meta `idle_days==90`）→ AC-42；`test_owner_disabled_flag_and_keys_still_valid` → AC-28；`test_created_account_grantable`（`aget_active_user_tenant` 有活跃行）→ AC-19；`test_human_user_endpoints_reject_service_account`（`/user/update` / `/user/reset_password` 对该 id → 26022）→ AC-20；`test_disable_enable_keeps_config`（disable → 密钥 401；enable → 恢复；`PATCH` 名称 / 归属人不受影响）→ AC-47；`test_delete_second_confirm_payload_and_effect`（`DELETE /{id}` 成功、密钥失效、`GET /{id}` → 26020；Wave 1 授权清单为空列表——T063 补反查断言）→ AC-48；`test_module_always_on_when_platform_off`（`open_platform.enabled=False` 下全部**账号**管理端点照常；`GET /scopes` 的三位断言归 T025 `test_scopes_endpoint_reflects_platform_switch`——该端点 T026 才实现）→ AC-49。
  **覆盖 AC**: AC-07, AC-19, AC-20, AC-23, AC-28, AC-41, AC-42, AC-47, AC-48, AC-49, AC-59
  **依赖**: T014, T021, T022, T017

- [x] **T024**: `[MVP-114]` 服务账号管理端点实现 + admin-scope 前缀
  **文件**: `src/backend/bisheng/open_api/api/endpoints/service_account.py`（新：`GET /` 分页 · `POST /` · `GET /{id}` · `PATCH /{id}` · `POST /{id}/enable` · `POST /{id}/disable` · `DELETE /{id}`，全部 `Depends(get_service_account_admin)`，`resp_200` / `PageData` 包装）, `src/backend/bisheng/common/middleware/admin_scope.py`（`MANAGEMENT_API_PREFIXES :63-71` 加 `/api/v1/service-accounts`）
  **逻辑**: 端点只做参数校验 + 委托 `ServiceAccountService`；`DELETE` 响应 `data` 含被删账号当前授权清单（Wave 1 恒空，T065 起反查填充）供前端二次确认（AC-48）。
  **跨 Feature**: `MANAGEMENT_API_PREFIXES` 是 F019 元组，加项 = 可审计扩展（坑 23）；影响面 = 该前缀下超管 ScopeBar 切租户生效。
  **测试**: T023 全部通过
  **覆盖 AC**: AC-07, AC-19, AC-20, AC-23, AC-28, AC-41, AC-42, AC-47, AC-48, AC-49, AC-59
  **依赖**: T023

- [x] **T025**: `[MVP-114]` 密钥管理端点 + `scopes` 端点集成测试
  **文件**: `src/backend/test/open_api/test_service_account_keys_api.py`（新）
  **逻辑**: `test_issue_plaintext_only_in_create_response`（`POST /{id}/keys` 响应含 `plaintext`；`GET /{id}/keys` / `GET /{id}` / 审计 metadata 只有 `bs-sak-********xxxx`）→ AC-02；`test_issue_default_no_scopes_and_unknown_26025` → AC-06；`test_issue_and_list_tenant_isolated`（子租户管理员操作 Root 账号密钥 → 26020 / 26026）→ AC-07；`test_patch_name_scopes_expires_effective_immediately`（改位后同一把明文对 `whoami` 立即按新位；不换密钥）→ AC-08；`test_revoke_all_within_5s`（`POST /{id}/keys/revoke-all` → 名下全部 401，采样 ≤ 3s）→ AC-09 / AC-46；`test_revoke_single_requires_belongs_to_account`（他账号 key_id → 26026）→ AC-46；`test_scopes_route_not_shadowed_by_id`（`GET /api/v1/service-accounts/scopes` 返回 200 信封而非 422 / 26020——防被 T024 `GET /{id}` 遮蔽）；`test_scopes_endpoint_reflects_platform_switch`（`GET /scopes`：关 → 无三位；开 → 三位在 `local_dev_toolkit` 组、含 `desc_key` / `identity:read` 醒目提示 key / `app:manage` 部署提示 key / `chat:invoke` 带 `pending_note_key`）→ AC-13 / AC-49；`test_issue_extension_scope_when_platform_off_26023` → AC-13；`test_issue_or_patch_with_delegate_26024` → AC-14；`test_key_list_columns`（名称 / 掩码 / 权限位 / 最后使用 / 过期 / 状态（按 `revoked_at` / `expires_at` 现算））→ AC-44；`test_key_lifecycle_audit_events`（issue / update / revoke / revoke_all 四事件、操作者 = 管理员、掩码、所属账号）→ AC-12。
  **覆盖 AC**: AC-02, AC-06, AC-07, AC-08, AC-09, AC-12, AC-13, AC-14, AC-44, AC-46, AC-49
  **依赖**: T024

- [x] **T026**: `[MVP-114]` 密钥管理端点 + `scopes` 端点实现
  **文件**: `src/backend/bisheng/open_api/api/endpoints/service_account_keys.py`（新：`GET /{id}/keys` · `POST /{id}/keys`（唯一返回明文处）· `PATCH /{id}/keys/{key_id}` · `POST /{id}/keys/{key_id}/revoke` · `POST /{id}/keys/revoke-all` · `GET /scopes`）, `src/backend/bisheng/open_api/api/router.py`（T022 建的 `/service-accounts` 子 router 追加 include：**`GET /scopes` 所在 router 必须先于 T024 的 `service_account.py` router 注册**——FastAPI 按注册顺序匹配，否则 `/service-accounts/scopes` 被 `GET /{id}` 吃掉、`"scopes"` 解析 int 失败返回 422；实现上把 `GET /scopes` 单独放 `scopes_router` 并第一个 include，keys router 其次，`service_account.py` router 最后）
  **逻辑**: 委托 `CredentialService`；`key_id` 不属该账号 → 26026；账号已停用 / 删除时签发 → 26027；`GET /scopes` 返回 `visible_scopes(settings.open_platform.enabled)`（含 `group / label_key / desc_key / endpoints / pending_note_key`，供签发表单悬停与分组）。
  **测试**: T025 全部通过
  **覆盖 AC**: AC-02, AC-06, AC-07, AC-08, AC-09, AC-12, AC-13, AC-14, AC-44, AC-46, AC-49
  **依赖**: T025

### Wave 2 · `[MVP-114]` 前端 Platform（手动验证）

- [ ] **T027**: `[MVP-114]` platform API 封装 + 类型
  **文件**: `src/frontend/platform/src/controllers/API/serviceAccount.ts`（新）, `src/frontend/platform/src/types/api/serviceAccount.ts`（新）
  **逻辑**: 经既有 `request` 封装（C7，不 `import axios`）封 §4.2 全部管理端点：`getServiceAccountsApi / createServiceAccountApi / getServiceAccountApi / updateServiceAccountApi / enable / disable / deleteServiceAccountApi / getServiceAccountKeysApi / issueKeyApi / updateKeyApi / revokeKeyApi / revokeAllKeysApi / getOpenApiScopesApi`（grants 三个随 T066 追加同文件）。类型：`ServiceAccountItem / ServiceAccountDetail / ApiKeyItem / KeyIssuedResponse / OpenApiScope`。
  **覆盖 AC**: AC-41, AC-44
  **手动验证**: 无 UI；`pnpm typecheck` 通过。
  **依赖**: T024, T026

- [ ] **T028**: `[MVP-114]` i18n 命名空间 + `appConfig.openPlatformEnabled`
  **文件**: `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/serviceAccount.json`（新，三语视为一组；目录名实为 `en-US` 非 `en`，`i18n.js:48 fallbackLng: 'en-US'`；`dev/` 目录不放正式文案）, `src/frontend/platform/src/i18n.js`（`:45` `ns` 数组加 `'serviceAccount'`）, `src/frontend/platform/src/contexts/locationContext.tsx`（`:75-94` `appConfig` 增 `openPlatformEnabled`，取 `GET /api/v1/env.open_platform_enabled`）
  **逻辑**: 本任务只建命名空间与 Wave 2 首批 key；**后续每个新增文案的前端任务（T029–T031 / T054 / T066 / T067）自行把 `serviceAccount.json` 三语列进文件清单、同 PR 补 key**（规则「新增 key 三语同 PR」）。首批 key 覆盖列表列 / 表单 / 三扩展位说明（`identity:read` 醒目常驻文案「勾选即本租户组织架构全量可读、无法收窄到部分部门」、`app:manage`「部署应用需勾选」、软提示「转交个人使用的 key 建议仅配本地开发工具包权限位」、`chat:invoke`「端点随后续版本开放」）/ 归属人说明句 / 开放能力层下归属人附加提示 / 一次性展示提示 / 撤销确认（含开放能力层下「MCP / 模型协议 / CLI 三面同时被拒绝」）/ 空态（零授权时一切 v2 调用失败是正确行为，坑 21）。
  **覆盖 AC**: AC-13, AC-23, AC-45, AC-46, AC-49
  **手动验证**: 切三语无缺 key 警告；`pnpm check-i18n` 通过。
  **依赖**: T004

- [ ] **T029**: `[MVP-114]` 「服务账号」tab：列表 + 新建弹窗
  **文件**: `src/frontend/platform/src/pages/SystemPage/index.tsx`（新 tab，可见性 `isSuperAdmin ∪ isChildAdmin`，不含部门管理员；不新增 web_menu）, `src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/ServiceAccountList.tsx`（新）, `src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/CreateServiceAccountDialog.tsx`（新）, `src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/ServiceAccountPanel.tsx`（新：tab 内容容器，持有 `view: 'list' | 'detail'` / `detailId` / `detailInitialTab: 'overview' | 'keys' | 'grants'` / `autoOpenIssue: boolean` 四个 `useState`——**SystemPage 各 tab 是 `<TabsContent>` 内部状态、无子路由**（`SystemPage/index.tsx:54-83`），详情不走路由，列表 ↔ 详情在容器内切换；`CreateServiceAccountDialog` 成功回调 `onCreated(id)` → 容器 `setView('detail'); setDetailInitialTab('keys'); setAutoOpenIssue(true)`；`ServiceAccountDetail` 通过 props `initialTab / autoOpenIssue / onBack` 接收，T030 / T031 据此实现）, `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/serviceAccount.json`（本任务新增 key 三语）
  **逻辑**: 列表用 `useTable`（不用 react-query，坑 24）：列 = 名称 / 状态 / 有效密钥数（0 高亮）/ 资源归属人（`owner_disabled` 高亮）/ 最后调用时间（空或超 `idle_days` 提示可考虑停用）/ 创建人 / 创建时间；行点击进详情（T030）。新建弹窗：名称 · 描述 · 资源归属人（`DepartmentUsersSelect multiple={false}`——其两条查询路径均已在 T016 / T071 排除服务账号）+ 一句话说明「该集成创建出的知识库等资源将归属此人、由其在平台内管理」+ `appConfig.openPlatformEnabled` 时附「首发部署应用以此人为 owner…」提示；租户不可选（取当前作用域）；创建成功 → **直接跳详情 · API 密钥 tab 并打开签发弹窗**（AC-43）。模块恒在，不受 `openPlatformEnabled` 影响（AC-49）。
  **覆盖 AC**: AC-23, AC-41, AC-42, AC-43, AC-49
  **手动验证**: 以**租户管理员**（非 admin）登录 114 platform → 系统管理 → 「服务账号」tab 可见；普通用户不可见；新建（缺归属人被拦；选人框搜不到任何服务账号）→ 成功后停在详情 · API 密钥 tab 且签发弹窗已打开；返回列表：有效密钥数 0 高亮；把 `open_platform.enabled` 关掉重启后 tab 仍在。
  **依赖**: T027, T028

- [ ] **T030**: `[MVP-114]` 详情页壳 + 概览 tab
  **文件**: `src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/ServiceAccountDetail.tsx`（新：三 tab 壳——概览 / API 密钥 / 资源授权（占位，T066 填）; 接入信息区不做，归 F053）, `src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/OverviewTab.tsx`（新）, `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/serviceAccount.json`（本任务新增 key 三语）
  **逻辑**: 详情壳 props 契约见 T029 `ServiceAccountPanel`（`initialTab` 决定默认激活 tab、`autoOpenIssue` 透传给 `ApiKeysTab` 首帧打开签发弹窗、`onBack` 回列表并触发列表刷新）。概览：名称 / 描述 / 租户 / 创建人 / 创建时间 / 资源归属人（可编辑：`PATCH`）；停用 / 启用按钮（`bsConfirm` 二次确认，文案说明「停用后 5 秒内密钥被拒、授权与配置保留」）；删除按钮：`bsConfirm` 列出 `DELETE` 预检返回的授权清单（Wave 1 恒空，T067 升级文案）+「依赖它的集成将立即失败」，确认即删、不阻断，删后回列表。
  **覆盖 AC**: AC-41, AC-47, AC-48
  **手动验证**: 停用 → 3 秒内 `curl whoami` 401；启用 → 恢复且归属人 / 密钥配置原样；删除 → 二次确认 → 列表消失、密钥 401。
  **依赖**: T029

- [ ] **T031**: `[MVP-114]` API 密钥 tab：签发 / 一次性展示 / 编辑 / 撤销 / 批量撤销
  **文件**: `src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/ApiKeysTab.tsx`（新：列表 + 顶部「撤销该账号全部密钥」）, `src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/KeyIssueDialog.tsx`（新：签发 / 编辑共用）, `src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/KeyRevealDialog.tsx`（新）, `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/serviceAccount.json`（本任务新增 key 三语）
  **逻辑**: `ApiKeysTab` 接收 `autoOpenIssue` prop（T029 契约），为 true 时挂载后即打开 `KeyIssueDialog`（AC-43）。列表列 = 名称 / 掩码 / 权限位 / 最后使用 / 过期 / 状态；签发表单：名称（必填）· 过期时间（可空 = 长期）· 权限位按 `GET /scopes` 分组 `checkBox`（**默认全不勾**；悬停 `tooltip` 显示覆盖端点；`chat:invoke` 附「端点随后续版本开放」；`appConfig.openPlatformEnabled` 时出现「本地开发工具包」组三位 + `identity:read` 醒目常驻提示 + `app:manage` 说明；勾任一开放 API 端点位时显示不阻断软提示）；**无 `delegate` 位、无委托配置区**（AC-14）。`KeyRevealDialog`：明文 + `copyText` + 「关闭后不可再查看」+ 「我已保存」勾选后才可关闭。撤销单把：`bsConfirm`（开放能力层下补三面文案）；顶部批量撤销：`bsConfirm`。编辑复用签发弹窗（名称 / 权限位 / 过期）。
  **覆盖 AC**: AC-02, AC-06, AC-13, AC-14, AC-44, AC-45, AC-46
  **手动验证**: 114 步 2（design §7）：签发勾 `app:manage`（组可见）→ 复制 → 未勾「我已保存」关不掉 → 关闭后列表只见掩码；编辑权限位 → 同一明文 `whoami.scopes` 立即变化；撤销单把 / 全部 → 3 秒内 401；`open_platform.enabled=false` 时三位不出现、表单无 `delegate`。
  **依赖**: T029

- [ ] **T032**: `[MVP-114]` 审计页 lockstep（前端两处）
  **文件**: `src/frontend/platform/src/controllers/API/log.ts`（`actions :53-108` + `getModulesApi :35-51` 加 `open_api` 模块与 D11 全部 action）, `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json`（`log.systemIdEnum` / `log.eventTypeEnum` 三语）
  **逻辑**: 与 T007 后端登记一一对应（E1 §5.2 四处 lockstep）。
  **覆盖 AC**: AC-12
  **手动验证**: 系统操作日志页可筛选「开放 API」模块，能看到 T031 产生的 issue / revoke 事件，metadata 只见掩码。
  **依赖**: T007, T028

- [ ] **T033**: `[MVP-114]` 114 部署步骤 + 首波手动验证清单
  **文件**: `features/v3.0.0/049-openapi-auth-baseline/tasks.md`（本文「实际偏差记录」上方追加「114 部署记录」小节）
  **逻辑**: 部署顺序（坑 22）：① `bash /opt/bisheng-ops/deploy.sh`（代码 + Alembic upgrade + create_all）→ ② `config.yaml` 加 `open_platform: {enabled: true}`（可选 `open_api: {service_account_idle_days: 90}`）→ ③ 重启后端 → `curl -s /api/v1/env | jq .open_platform_enabled` == `true`。手动验证 = design §7 步 1–3 与步 5（用普通用户看用户管理 / 审批人 / 部门加成员 / 资源授权弹窗搜不到服务账号；服务账号密码登录 → 26012；F048 验证用非 admin）。
  **依赖**: T022, T024, T026, T029, T030, T031, T032

### Wave 3 · 既有 v2 面接入（38 端点标记 + 6 端点关闭 + 缺陷修复 + 配置移除）

- [ ] **T034**: v2 路由完整性 + 全端点鉴权矩阵测试
  **文件**: `src/backend/test/open_api/test_v2_route_integrity.py`（新）
  **逻辑**: `test_every_v2_route_has_scope_marker`（枚举 `app.routes` 下 `/api/v2/**` 含 `APIWebSocketRoute`，每条带 `@open_api_scope`；位 ∈ `OPEN_API_SCOPES` 或 `None`，`None` 只允许白名单 `{'/api/v2/auth/whoami'}`；注册表可含无端点的位 `chat:invoke`）→ AC-29；`test_scope_endpoint_mapping_matches_registry`（38 端点归位与 `OPEN_API_SCOPES.endpoints` 一致）→ AC-04；`test_six_chat_routes_absent_404`（`GET /chat/history`、`POST /chat/gen_title`、`/chat/liked`、`/chat/solved`、`/chat/comment`、`POST /chat/sync/messages` → 404 `{"detail":"Not Found"}`，无业务副作用）→ AC-30；`test_all_http_endpoints_401_without_key`（参数化 36 个 HTTP 端点：无头 → 401 `26001`，不执行业务——对写端点断言 DB 无新行）→ AC-01 / AC-50；`test_all_endpoints_403_missing_scope_with_required`（有效密钥无位 → 403 `26003` `data.required` = 该端点位）→ AC-04；`test_two_layer_errors_distinguishable`（持 `knowledge:read` 但主体对该知识库无授权 → 业务既有资源权限错误码，≠ 26003）→ AC-36；`test_no_config_switch_can_reopen`（`initdb_config` / Settings 中不存在任何键能让无头请求通过：grep 代码无 `enable_guest_access` / `default_operator` 消费者 + 运行时断言）→ AC-50；`test_no_third_path_across_endpoints`（抽样 5 端点：无头 = 模式 S 结果集；有身份头 = 26004；无「返回公开资源 / 空集」响应）→ AC-35。
  **覆盖 AC**: AC-01, AC-04, AC-29, AC-30, AC-35, AC-36, AC-50
  **依赖**: T022, T008

- [ ] **T035**: `resolve_operator` 收紧 + `get_open_api_login_user` 测试
  **文件**: `src/backend/test/open_api/test_resolve_operator.py`（新）
  **逻辑**: `test_get_open_api_login_user_reads_contextvar`（无 ContextVar → 抛 26001 而非兜底身份）；`resolve_operator(user_id)`：空 → 返回密钥主体 → AC-35；目标 `delete==1` 或不存在 → 403（不构造可用身份）→ AC-39；目标活跃租户 ≠ 密钥租户 → 403（坑 25 跨租户取数）→ AC-39；`test_get_default_operator_symbols_removed`（`open_endpoints.domain.utils` 无 `get_default_operator` / `get_default_operator_async`；`open_endpoints.api.dependencies` 无 `get_knowledge_space_chat_service_for_openapi`）。
  **覆盖 AC**: AC-35, AC-39
  **依赖**: T012, T008

- [ ] **T036**: `open_endpoints/domain/utils.py` 重写 + 死函数删除
  **文件**: `src/backend/bisheng/open_endpoints/domain/utils.py`（删 `get_default_operator :26` / `get_default_operator_async :53`（AC-52 读取点）；新增 `get_open_api_login_user() -> UserPayload`（读 `current_open_api_principal` 对应 `UserPayload`，供 `Depends`）；`resolve_operator :77` 收紧：读 ContextVar 主体 → `user_id` 空即返回主体；非空 → `aget_user` + `delete==0` + 目标活跃租户 == 密钥租户 → 否则 403）, `src/backend/bisheng/open_endpoints/api/dependencies.py`（删 `:61-70 get_knowledge_space_chat_service_for_openapi` 死函数——`endpoints/knowledge.py:11` 仍 import 该模块，删函数不删 import 处即模块导入失败，随 T037 一并改）
  **逻辑**: D3；`utils.py` 不 import `open_api/api/*`（RULE-5），只 import `bisheng.open_api.domain.context`。
  **测试**: T035 全部通过
  **覆盖 AC**: AC-35, AC-39
  **依赖**: T035

- [ ] **T037**: 标记接入：`knowledge.py` + `citation.py` + `llm.py`
  **文件**: `src/backend/bisheng/open_endpoints/api/endpoints/knowledge.py`（8 个 `*metadata*` 端点 `@open_api_scope('knowledge:write')`；`Depends(get_default_operator_async)` ×8（`:21/42/65/90/111/136/162/188`）→ `Depends(get_open_api_login_user)`；`:11` 对 `dependencies` 的 import 按 T036 调整）, `src/backend/bisheng/open_endpoints/api/endpoints/citation.py`（`GET /citation/{id}` `knowledge:read`；`:23` 依赖替换）, `src/backend/bisheng/open_endpoints/api/endpoints/llm.py`（`/llm/workbench/asr` / `tts` `assistant:invoke`；`:13/:21` 内联调用替换）
  **逻辑**: 只 import `bisheng.open_api.domain.scopes`（domain 常量，RULE-5 不触发）；端点体逻辑不动。
  **测试**: T034 相关端点通过（`pytest -k "knowledge or citation or llm"`）
  **覆盖 AC**: AC-04, AC-29
  **依赖**: T036

- [ ] **T038**: 标记接入：`filelib.py`（19 端点：6 读 + 13 写；`knowledge:write` 位总数 21 = 本文件 13 + `knowledge.py` 8）
  **文件**: `src/backend/bisheng/open_endpoints/api/endpoints/filelib.py`
  **逻辑**: 按 D3 映射：`knowledge:read` = `GET /filelib/`（`:157`）、`file/list`（`:362`）、`retrieve`（`:623`）、`download_statistic`（`:496`）、`detail_qa` / `query_qa`（`:614` / `:676` 之读端点，以函数名核）；其余 13 个写端点 + `chunks` / `chunks_string` 等 = `knowledge:write`。全部 `get_default_operator*` 内联调用（`:88/132/211/241/301/349/357/444/475/515/539/557/590/618/680`）→ `get_open_api_login_user()`；`resolve_operator(user_id)` 三处（`:176/381/640`）保留（K11，F050 移除）。`POST /filelib/retrieve` 只加鉴权、过滤强度维持现状（spec §3；文件级双层过滤归 F052）。
  **测试**: T034 相关端点通过（`pytest -k filelib`）
  **覆盖 AC**: AC-04, AC-29
  **依赖**: T036

- [ ] **T039**: 标记接入：`workflow.py` + `flow.py` + `assistant.py`（HTTP + WS 标记）
  **文件**: `src/backend/bisheng/open_endpoints/api/endpoints/workflow.py`（`invoke :31` / `stop :144` `workflow:invoke`；WS `:157` `@open_api_scope('workflow:invoke', allow_share_token=True)`；`:41/149/167` 身份改 `get_open_api_login_user()`；WS 端点内旧的 `close(1011) before accept` 身份分支删除——身份已在依赖里判定，坑 16）, `src/backend/bisheng/open_endpoints/api/endpoints/flow.py`（`GET /flows/{id}` `workflow:read`；`:8` 从 `endpoints.assistant` 转导入 `get_default_operator` 删除、`:21-23` guest 开关读取删除）, `src/backend/bisheng/open_endpoints/api/endpoints/assistant.py`（`chat/completions :30` `assistant:invoke`，**端点体 `:48` 内联 `get_default_operator()` 一并改为 `get_open_api_login_user()`**；`list :256` / `info :271` `assistant:read`（`:262-286` `enable_guest_access` 读取删除）；WS `:298` `assistant:invoke` + `allow_share_token=True`，`:304 get_default_operator()` 删除；`:24` 的 `get_default_operator` import 删除——共 4 处调用 `:48/:266/:286/:304`，漏一处即 T036 删函数后模块 import 失败）
  **逻辑**: WS 端点体保留 `accept` 后的 `dispatch_client` 逻辑；share-token 分支与 watchdog 由 T052 / T053 接入（本任务后 WS 只接受密钥）。
  **测试**: T034 相关端点通过（`pytest -k "workflow or flow or assistant"`）
  **覆盖 AC**: AC-04, AC-29
  **依赖**: T036

- [ ] **T040**: `chat.py` 删除 + 全局 `router_rpc` 挂依赖
  **文件**: `src/backend/bisheng/open_endpoints/api/endpoints/chat.py`（**删除**，含 `:7-9` 无用 `a = WSGIMiddleware`）, `src/backend/bisheng/open_endpoints/api/router.py`（去 `chat_router_rpc` import / `__all__`）, `src/backend/bisheng/api/router.py`（`:94` `router_rpc = APIRouter(prefix='/api/v2', dependencies=[Depends(verify_open_api_access)])`；`include_router(chat_router_rpc)` 删除；`open_api` v2 子 router 的自带依赖去重（避免同一请求跑两次校验））
  **逻辑**: D4 真 404、不留 410 桩；与 T037–T039 同 wave 落地（顺序：T037–T039 先、本任务最后合并），保证挂全局依赖那一刻不存在未标记端点。
  **跨 Feature**: `open_endpoints` 全部路由从此经同一凭据路径（INV-27）；`docs/api` 与发布说明（T045 / T074）同步 6 端点清单。
  **测试**: T034 全部通过（含 `test_every_v2_route_has_scope_marker` / `test_six_chat_routes_absent_404`）
  **覆盖 AC**: AC-01, AC-29, AC-30, AC-50
  **依赖**: T037, T038, T039

- [ ] **T041**: 三处既有缺陷测试（AC-37 / 38 / 40）
  **文件**: `src/backend/test/open_api/test_v2_known_defects.py`（新）
  **逻辑**: `test_invoke_offline_workflow_13010`（`status != ONLINE` → `WorkflowOfflineError` 业务错误、不进 `RedisCallback`）→ AC-37；`test_stop_session_not_owned_403`（他主体的 `unique_id` 会话 → 403；本主体 → 200；`set_workflow_status` 载荷含 `owner_user_id / tenant_id`）→ AC-38；`test_download_statistic_rejects_paths`（`file_path` 参数不再接受；`file_name` 含 `..` / 绝对路径 / 子目录 / 非 `.log` → 400；`realpath` 不在 `STATISTIC_DIR` 内 → 404；合法 → 只返回该目录内文件；无 `knowledge:read` → 403）→ AC-40。
  **覆盖 AC**: AC-37, AC-38, AC-40
  **依赖**: T040, T039, T038, T008（T040 之前全局 `router_rpc` 依赖未挂，v2 端点全部 26001，本测试的有效密钥请求打不到业务逻辑）

- [ ] **T042**: `invoke` 上线守卫 + `stop` 归属校验
  **文件**: `src/backend/bisheng/open_endpoints/api/endpoints/workflow.py`（`invoke_workflow :43-49` 取到 `workflow_info` 后、构造 `RedisCallback` 前 `if workflow_info.status != FlowStatus.ONLINE.value: raise WorkflowOfflineError.http_exception()`（`common/errcode/chat.py:29` 13010，已有三语）；`stop :144` 读 `RedisCallback` 状态载荷 `owner_user_id / tenant_id`，≠ 当前主体 → 403）, `src/backend/bisheng/worker/workflow/redis_callback.py`（`set_workflow_status :118-123` 状态载荷加 `owner_user_id / tenant_id`）
  **逻辑**: `/workflow/stop` **不加**上线守卫（停未上线流的会话是幂等空操作）。
  **跨 Feature**: `set_workflow_status` 状态载荷是 workflow worker（写）与 `stop` 端点（读）的共享结构——只加 `owner_user_id / tenant_id` 两键、不删不改既有键，worker 侧其它读者无感（已登记顶部跨 Feature 表）。
  **测试**: T041 前两项通过
  **覆盖 AC**: AC-37, AC-38
  **依赖**: T041, T040

- [ ] **T043**: `download_statistic` 收口
  **文件**: `src/backend/bisheng/open_endpoints/api/endpoints/filelib.py`（`download_statistic_file :496-507`：入参 `file_path` → `file_name`；`os.path.basename(file_name) == file_name` 且不含 `..` 否则 400 `ServerError`；`STATISTIC_DIR = <data_dir>/statistic`（既有配置根，不新增 Settings 键）；`os.path.realpath(join)` 须以 `realpath(STATISTIC_DIR) + os.sep` 开头否则 404）
  **逻辑**: D3「AC-40 收口」；契约变化（`file_path → file_name`）进 T045 文档与 T074 发布说明。
  **测试**: T041 第三项通过
  **覆盖 AC**: AC-40
  **依赖**: T041

- [ ] **T044**: 升级零迁移 + 配置移除 + 文档断言测试
  **文件**: `src/backend/test/open_api/test_upgrade_zero_migration.py`（新）
  **逻辑**: `test_alembic_f049_revisions_touch_only_new_columns`（F049 两个 revision 的 upgrade 只 ADD COLUMN / 索引；对种子用户 / 知识库 / 权限行 upgrade 前后逐行相等；`default_operator` 指向的用户仍是普通用户、其名下资源归属零变化）→ AC-51；`test_default_operator_config_has_no_effect`（DB `config` 表残留 `default_operator.user=<超管>` 时：无头调用仍 401，且代码库无 `get_default_operator` 符号）→ AC-52；`test_enable_guest_access_has_no_effect`（残留 `enable_guest_access: true` 时 `GET /assistant/info` / `/flows/{id}` 无头 401、有头有位 200）→ AC-53；`test_initdb_config_keys_removed`（`initdb_config.yaml` 无 `default_operator` / `enable_guest_access` 键）→ AC-54。**降级**：`docs/api/*.md` 与 `platform/.../ApiAccess.tsx` 的禁词 / 前缀断言**不进 pytest**（跨树脆弱断言，spec AC-54 未要求自动化）——改为 T045 / T046 完成标准里的一条 `grep` 审阅命令：`grep -rnE "由网络层负责访问控制|默认操作员配置为超级管理员|default_operator|转为服务账号|会被降权" docs/api src/frontend/platform/src/components/bs-comp/apiComponent/` 应为空，且 `grep -lE "\bbs-sak-[A-Za-z0-9_-]{43}\b" docs/api/*.md` 非空。
  **覆盖 AC**: AC-51, AC-52, AC-53, AC-54
  **依赖**: T040, T001, T047（「F049 两个 revision」含 T047 的 `share_link.share_scope`）

- [ ] **T045**: `initdb_config.yaml` 删键 + `docs/api` 修订与前缀模式公开
  **文件**: `src/backend/bisheng/initdb_config.yaml`（`:35-38` `default_operator` 块含 `enable_guest_access` 删除）, `docs/api/filelib-retrieve.md`（`:25-28` / `:297-298` 两处错误引导改为「持 `bs-sak-` 密钥 + `knowledge:read`，租户取密钥所属租户」；说明「知识资源级一次校验 + fail-closed，文件级过滤随 F052」）, `docs/api/开放 API 接口方案.md`（新增「凭据格式与前缀模式」小节：`Authorization: Bearer bs-sak-<43>`、正则 `\bbs-sak-[A-Za-z0-9_-]{43}\b`、掩码格式；`download_statistic` 入参 `file_path → file_name`；6 个 `/chat/*` 不再提供；**订正 `:1594-1596`**「该用户会被转为服务账号并降权 / 升级后该身份会被降权」两句——与 AC-51 / AC-52 零迁移决议相悖，改为「原默认操作员用户**不做任何变更**（仍是普通用户、名下资源归属与权限原样），只是不再被任何 v2 调用当作兜底身份；请新建服务账号并授权」；同表 `:1592` 裸 `user_id` 行注明随 F050 移除、`delegate` 位随 F050）
  **逻辑**: D12；存量 DB `config` 残留键无害、不写清理脚本（AC-51）；测试注释 `test/e2e/test_e2e_knowledge_resource_unified.py:4` 顺带改。
  **测试**: T044 全部通过 + T044 登记的 `grep` 审阅命令为空 / 非空（含「转为服务账号」「会被降权」两词）
  **覆盖 AC**: AC-52, AC-53, AC-54
  **依赖**: T044

- [ ] **T046**: platform 接入文档页示例修订 + `ApiAccessFlow` i18n 偿债
  **文件**: `src/frontend/platform/src/components/bs-comp/apiComponent/ApiAccess.tsx`（`:57-58` 示例 `api_key="empty"` → `bs-sak-…` 占位 + 说明「密钥经 Authorization 头传递」）, `src/frontend/platform/src/components/bs-comp/apiComponent/ApiAccessFlow.tsx`（同类示例修订；该文件冻结 188 条中文，触碰即整文件 `/i18n-localizer` 提取（坑 24），三语 key 落 `flow.json`）
  **逻辑**: AC-54 前端面；`ChatLink.tsx` 与 `noLoginLinkDescription` 文案随 T054 一并改（同文件不二次动）。
  **覆盖 AC**: AC-54
  **手动验证**: 接入文档页示例含 `bs-sak-` 占位；`pnpm lint` 通过且 `eslint-suppressions.json` 经 `pnpm lint:prune` 只减不增。
  **依赖**: T045

### Wave 4 · WebSocket 双凭据 + share-token 通道（后端 + Platform + Client）

> **前置 ★**：design D8 登记了两处需回写 spec 的口径（决议-1「实际受影响面只有两个 WS」的核实基础已过时——guest 页另打 4 个 v2 HTTP，改由 3 个 `/api/v1/share-link/{token}/*` 端点承接；AC-55「单一资源」在 history 端点上按「资源 = flow」解释）。这两处**不改 AC 文字**，但开工 T047 前须经用户确认并回写 spec 决议-1（design 修订历史「需回写上游」）。

- [ ] **T047**: Alembic：`share_link.share_scope` 列 + 模型
  **文件**: `src/backend/bisheng/core/database/alembic/versions/v3_0_0_f049_share_link_share_scope.py`（新）, `src/backend/bisheng/share_link/domain/models/share_link.py`（`ShareLink` 加 `share_scope: str = Field(default='session', max_length=16)`；`resource_type` `SQLEnum` **不加枚举值**（K5）；`expire_time` 注释改为「自 `create_time` 起相对秒，0 = 永不」）
  **逻辑**: `ALTER TABLE share_link ADD COLUMN share_scope VARCHAR(16) NOT NULL DEFAULT 'session'`；`app` = 应用级分享（`resource_id` = flow / assistant id）。现状 6 个会话级消费点与 2 个 flow 级消费点逻辑不改（D8「资源类型表达」）。
  **回滚**: `downgrade()` 删列；`app` 行 downgrade 后会被 flow 级消费点按兜底分支读、被会话级消费点当会话 id 读——因此 downgrade 前先经 T050 revoke 全部 `app` 行（写在 docstring）。
  **跨 Feature**: ShareLink 写增量已在 release-contract 表 1 登记归 F049。
  **排位**: 基础设施任务、无依赖——**实际执行提前到 Wave 1 与 T001 同批**（一次 Alembic 升级两个 revision；T044 依赖它），编号保留在此只为与 share-token 通道叙事相邻（见「编号 ≠ 执行顺序」）。
  **依赖**: 无

- [ ] **T048**: share-link 服务 + 匿名作用域端点 + `/app-shares` 管理端点测试
  **文件**: `src/backend/test/share_link/test_share_link_app_scope.py`（新）
  **逻辑**: `test_expire_time_enforced_relative_seconds`（`expire_time>0` 且 `create_time + expire_time < now` → `get_share_link_by_token` 拒；`0` 永不过期；`session` 行兼容）→ AC-56 / AC-57；`test_generate_app_scope_requires_positive_expire`（`share_scope='app'` 且 `expire_time<=0` → 拒；service 内显式 `tenant_id = login_user.tenant_id`）→ AC-57；`test_revoke_endpoint_writes_inactive_and_immediate`（`POST /api/v1/app-shares/{id}/revoke`：创建者或管理员可撤；撤后 `status=INACTIVE`、匿名端点立即 26028）→ AC-56 / AC-57；`test_app_shares_list_tenant_isolated_and_requires_login`（`GET /api/v1/app-shares?resource_type&resource_id` 只返回本租户 `share_scope=app`；未登录拒；**路径不在 `TENANT_CHECK_EXEMPT_PATHS` 前缀下**——断言方式：枚举 `app.routes` 取两个端点的**最终挂接路径**恰为 `/api/v1/app-shares` / `/api/v1/app-shares/{id}/revoke`，且对 `TENANT_CHECK_EXEMPT_PATHS` 每一项 `startswith` 均为 False（只查豁免列表抓不到「被挂在 `/api/v1/share-link` 前缀下」的错挂）；再以 `token_version` 已 bump 的旧登录态调 `GET /api/v1/app-shares` → 被拒（证明 token_version / 租户状态检查生效，坑 26））；`test_share_link_expire_audit_once`（过期 share-link 首次被 `get_share_link_by_token` 拒绝 → 单行 `status=INACTIVE` + 恰一条 `open_api.share_link.expire` 审计（`operator=system`），并发两次只一条）→ AC-56；匿名端点：`GET /api/v1/share-link/{token}/resource`（按 `resource_type` 返回工作流 / 助手信息、只放行 `share.resource_id`）、`GET .../chat/history?chat_id=`（`session.flow_id == share.resource_id` 才返回，他 flow 的 chat_id → 26028）、`POST .../chat/gen_title`；坏 token / 过期 / INACTIVE → 26028；创建者已禁用或已删除 → 拒（fail-closed）→ AC-55；`test_v2_http_face_does_not_accept_share_token`（`share-token` 头打任一 v2 HTTP → 401 `26001`）→ AC-55。
  **覆盖 AC**: AC-55, AC-56, AC-57
  **依赖**: T047, T008

- [ ] **T049**: `ShareLinkService` 增量实现
  **文件**: `src/backend/bisheng/share_link/domain/services/share_link_service.py`（`get_share_link_by_token :52-58`：删「有效期刻意不生效」注释、统一强制相对秒过期；过期首次命中时惰性 `UPDATE share_link SET status=INACTIVE WHERE id=:id AND status=ACTIVE`，`rowcount==1` 才写审计 `open_api.share_link.expire`（`operator_id=0` → `system`）——T007 登记的该动作由此产生事件（同 T010 密钥惰性到期的幂等闸），不另起 Beat；新增 `revoke(share_id, actor)`（创建者或管理员，写 `status=INACTIVE` + 审计 `open_api.share_link.revoke`）/ `list_app_shares(resource_type, resource_id)` / `generate` 支持 `share_scope`（`app` 必填 `expire_time>0`，`resource_id` = flow / assistant id）/ `resolve_guest_principal(token, expected_resource_type, expected_resource_id) -> UserPayload`（以创建者**直接构造** `UserPayload(is_global_super=False, user_role=[], open_api_principal(subject_kind='share_link', share_link_id))` + `set_current_tenant_id(share.tenant_id)`；创建者禁用 / 删除 / 租户不活跃 → 26028））
  **逻辑**: D8；`share_link` 继续用 `generate_short_high_entropy_string`（坑 17 只影响密钥）；`access_count` 不动。
  **测试**: T048 service 部分通过
  **覆盖 AC**: AC-55, AC-56, AC-57
  **依赖**: T048

- [ ] **T050**: share-link 匿名作用域端点 + `/app-shares` 管理端点
  **文件**: `src/backend/bisheng/share_link/api/endpoints/share_link.py`（新增 3 个匿名端点 `GET /{token}/resource` · `GET /{token}/chat/history` · `POST /{token}/chat/gen_title`，复用 `api/dependencies.py:30-48 header_share_token_parser`；留在豁免前缀 `/api/v1/share-link` 下——匿名端点正需要 bypass）, `src/backend/bisheng/share_link/api/endpoints/share_link_manage.py`（新：`app_shares_router = APIRouter(prefix='/app-shares', tags=['ShareLink'])`：`GET /` · `POST /{id}/revoke`，`Depends(get_login_user)`，**非豁免前缀**，租户自动过滤 + token_version + 租户状态检查全部生效）, `src/backend/bisheng/share_link/api/router.py`（现有 `router = APIRouter(prefix='/share-link')` `:4` 只 include 3 个匿名端点；`app_shares_router` **不得** include 进它——否则最终路径变成 `/api/v1/share-link/app-shares`，`startswith` 命中 `TENANT_CHECK_EXEMPT_PATHS`（`utils/http_middleware.py:39`，匹配在 `:311`），正是坑 26 要规避的 bypass + 跳过 token_version；此文件只 `export` `app_shares_router`）, `src/backend/bisheng/api/router.py`（`:76` `include_router(share_link_router)` 旁**独立** `router.include_router(app_shares_router)`，直接挂 `/api/v1`）
  **逻辑**: 坑 26：撤销 / 列表绝不能落 `share-link*` 前缀——最终路径必须恰为 `/api/v1/app-shares*`（T048 以 `app.routes` 最终路径断言）；既有 `generate_share_link :12-17` 的豁免暴露只登记不搬。history / gen_title 端点内部复用 chat_session 既有 Service，以创建者身份 + `flow_id == share.resource_id` 收窄。
  **测试**: T048 全部通过
  **覆盖 AC**: AC-55, AC-56, AC-57
  **依赖**: T049

- [ ] **T051**: WS 双凭据 + watchdog + 审计 集成测试
  **文件**: `src/backend/test/open_api/test_ws_dual_credentials.py`（新）
  **逻辑**: 对 `/api/v2/workflow/chat/{id}` 与 `/api/v2/assistant/chat/{id}`（TestClient `websocket_connect`）：`test_no_credential_handshake_rejected_gracefully`（无头无 `share_token` → 握手被拒（1008 / HTTP 403），进程无未捕获异常、无 HTTP 200 denial（坑 16））→ AC-31；`test_bad_key_rejected` / `test_key_without_invoke_scope_rejected` → AC-29 / AC-31；`test_share_token_valid_app_scope_accepts`（有效 `?share_token=` 且 `share_scope=='app'` 且路径 id == `resource_id` → accept；执行主体 = 分享创建者、`get_current_tenant_id()==share.tenant_id`、`open_api_principal.subject_kind=='share_link'`）→ AC-55 / AC-58；`test_share_token_wrong_resource_rejected`（路径 id ≠ `resource_id` 或 `session` 行 → 26028）→ AC-55；`test_key_and_share_token_both_present_key_wins`；`test_query_param_key_not_accepted`（`?token=bs-sak-…` 不被当密钥）；`test_ws_connect_audit_written`（每次建连一条 `open_api.ws.connect`：凭据种类、密钥 id 或 `share_link_id`、执行主体、资源）→ AC-58；**watchdog 5 秒矩阵**：建连后撤销密钥 / 批量撤销 / 停用账号 / share-link revoke / share-link 到期 → 连接在 ≤ 5s 内 `close(1008)` → AC-03 / AC-09 / AC-21 / AC-47 / AC-56。
  **覆盖 AC**: AC-03, AC-09, AC-21, AC-29, AC-31, AC-47, AC-55, AC-56, AC-58
  **依赖**: T050, T039, T008

- [ ] **T052**: `verify_open_api_access` WS 分支 + watchdog
  **文件**: `src/backend/bisheng/open_api/api/dependencies.py`（WS 分支：`Authorization` 头（密钥）或 `?share_token=` 二选一（同时给以密钥为准、share_token 忽略并记日志）；share-token 分支要求端点标记 `allow_share_token=True`，调 `ShareLinkService.resolve_guest_principal(token, 资源类型, 路径 id)`；任何失败一律 `raise WebSocketException(code=1008, reason=str(错误码))`——**禁止** `HTTPException` / `BaseErrorCode.http_exception`（坑 16）；成功后写 ContextVar 主体）, `src/backend/bisheng/open_api/domain/services/ws_watchdog.py`（新：`start_watchdog(ws, principal) -> asyncio.Task`，每 3 秒复查同一 Redis 键 `oapi:cred:{hash}` 或 share_link 状态（revoke / 过期 / 主体停用），失败即 `close(1008)`；连接关闭时取消 task）
  **逻辑**: D2「WS 连接期失效」；不动 `common/chat/manager.py dispatch_client` 的按消息校验（F048 `use` 校验仍以执行主体为 actor）。
  **测试**: T051 握手 / 双凭据部分通过
  **覆盖 AC**: AC-03, AC-09, AC-21, AC-29, AC-31, AC-47, AC-55, AC-56, AC-58
  **依赖**: T051

- [ ] **T053**: 两个 WS 端点接 watchdog + 建连审计
  **文件**: `src/backend/bisheng/open_endpoints/api/endpoints/workflow.py`（WS `:157`：`accept` 后 `start_watchdog` + 审计 `open_api.ws.connect`；`finally` 取消 watchdog）, `src/backend/bisheng/open_endpoints/api/endpoints/assistant.py`（WS `:298` 同上；`:305` 原 `try` 内不再有身份解析）
  **逻辑**: 端点体只做 `accept → 审计 → watchdog → dispatch_client`；身份全部来自依赖。
  **测试**: T051 全部通过
  **覆盖 AC**: AC-31, AC-56, AC-58
  **依赖**: T052

- [ ] **T054**: platform 免登录链接改走 share-token + 撤销入口
  **文件**: `src/frontend/platform/src/components/bs-comp/apiComponent/ChatLink.tsx`（`:77-81` 免登录 URL 改为 `${origin}${BASE_URL}/workspace/chat/{flow|assistant}/{id}?share_token=…`（生成 `share_scope='app'`、`expire_time` 默认 30 天可改）；`:106-108` `enable_guest_access` 文案删除；增「已生成分享」列表 + 撤销按钮）, `src/frontend/platform/src/controllers/API/shareLink.ts`（新：`generateAppShareLinkApi / listAppSharesApi / revokeAppShareApi`）, `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json`（`api.noLoginLinkDescription` 三语改为「分享链接带有效期、可随时撤销」口径）
  **逻辑**: D8 前端；存量裸分享链接升级后失效、须重新分享（发布说明 T074）。
  **覆盖 AC**: AC-55, AC-57
  **手动验证**: 工作流 / 助手接入页生成免登录链接 → 新开无痕窗口打开可对话（步 T056 完成后）；撤销 → 已开页面 ≤ 5s 断连、刷新被拒；到期同理；旧格式链接（无 `share_token`）打开被拒。
  **依赖**: T050

- [ ] **T055**: client guest 页：share-token 读取 + WS URL
  **文件**: `src/frontend/client/src/utils/shareToken.ts`（新：从 URL query 取 `share_token`、会话内保存）, `src/frontend/client/src/pages/appChat/useChatHelpers.ts`（`:23-40` 拼 WS URL 时 guest 模式带 `?share_token=`；`:35-36` 两个 WS 路径不变）
  **逻辑**: 密钥不经查询参数、share-token 例外（spec §3）。
  **覆盖 AC**: AC-55
  **手动验证**: 带 `share_token` 打开 guest 页 → WS 建连成功；去掉参数 → 建连被拒并显示无权限态。
  **依赖**: T053

- [ ] **T056**: client guest 页：HTTP 改打 share-link 作用域端点
  **文件**: `src/frontend/client/src/api/apps.ts`（`:39` `GET /flows/{id}`、`:64` `GET /assistant/info/{id}`、`:133` `GET /chat/history` 在 guest 模式改打 `/api/v1/share-link/{token}/resource` / `.../chat/history`）, `src/frontend/client/src/api/chat/api-endpoints.ts`（`:51` `gen_title` guest 模式改打 `/api/v1/share-link/{token}/chat/gen_title`）, `src/frontend/client/src/pages/standaloneChat/StandaloneChatPage.tsx`（`:82` guest → 注入 share-token 上下文；**不再打任何 `/api/v2` HTTP**）
  **逻辑**: D8 备选 C；`useWebsocket.ts:82` 处 gen_title 调用经 `api-endpoints.ts` 已覆盖。
  **覆盖 AC**: AC-30, AC-55
  **手动验证**: guest 页全程 Network 面板无 `/api/v2/*` HTTP 请求；信息 / 历史 / 标题正常；撤销后刷新被拒。
  **依赖**: T055

### Wave 5 · 主体侧授权页 + 资源归属人回授（D5 / D6）

- [ ] **T057**: F048 runtime 回授分支 + 新来源值 单元测试
  **文件**: `src/backend/test/permission/test_service_account_autogrant.py`（新）
  **逻辑**: `test_authorize_created_with_autogrant_adds_non_protected_row`（`autogrant_user_id == actor.user_id != owner_user_id` → 创建计划含 `subject=user:{sa}`、`source_type=SERVICE_ACCOUNT_AUTOGRANT`、`protected=False`、档位 = 该类型含 `edit` 动作的最低档（经 Catalog 解析）；同一 plan / prepare / execute / finalize；幂等键不变）→ AC-24；`test_autogrant_structural_constraints`（`autogrant_user_id != actor` 或 `== owner` → 拒；`INHERIT` 起始类型（`folder / knowledge_file`）→ 忽略回授、记 debug、不报错）→ AC-24；`test_source_type_registered_everywhere`（`SOURCE_TYPES` / `_validate_source_subject`（允许 `user`）/ `_source_locator` 均识别新值；`f048_mode_mapper` / `control_state` 按普通源处理 → 可 `mutate REMOVE`）→ AC-63；`test_owner_projection_context_extra_grants_not_copy_grants`（`extra_grants` 不触发 `_validate_copy :236-239` 的 `PermissionInvalidResourceError`）；`test_no_creator_row_for_service_account`（CREATOR 行在 owner（归属人），服务账号名下无 CREATOR）→ AC-61。
  **覆盖 AC**: AC-24, AC-61, AC-63
  **依赖**: T014, T008

- [ ] **T058**: `grant_source_service` 新来源值 + `OwnerProjectionContext.extra_grants`
  **文件**: `src/backend/bisheng/permission/domain/services/grant_source_service.py`（`SOURCE_TYPES :16-26` 加 `SERVICE_ACCOUNT_AUTOGRANT`；`_validate_source_subject :178` 允许 `user`；`_source_locator :193`）, `src/backend/bisheng/permission/domain/services/owner_service.py`（`OwnerProjectionContext :38-53` 加 `extra_grants / extra_deltas`；`project_created :113-166` 把 extra deltas 与 owner protected deltas 一起进 `build_create_plan(protected_deltas=...)`；**不复用** `copy_grants / copy_deltas`（坑 27））
  **跨 Feature**: PermissionGrant 归 F048——只增来源值与显式上下文字段，不改既有来源语义；`sync_business_source_model` 白名单（`runtime.py:647-649`）与之无关。
  **测试**: T057 来源值 / context 部分通过
  **覆盖 AC**: AC-24, AC-63
  **依赖**: T057

- [ ] **T059**: `runtime.authorize_created` `autogrant_user_id` + `control_state` 落账本
  **文件**: `src/backend/bisheng/permission/application/runtime.py`（`authorize_created :206-260` 新增显式 kwarg `autogrant_user_id: int | None = None`：校验 `== actor.user_id ∧ != owner_user_id ∧ 资源版本 0`；目标起始 `INHERIT` → 忽略并 debug；否则组回授 delta 进 `OwnerProjectionContext.extra_grants`；`:216-223` 对 owner 行的硬拒不变）, `src/backend/bisheng/permission/application/control_state.py`（`_owner_projection_grants :956-963` 与 `_state.prepare / finalize` 把 extra grant 的 assignee 行一并落账本；`:355 protected_only` 逻辑不动）
  **逻辑**: D5 输入契约：`PermissionActor` / `resolve_permission_actor` **不改、不读 `user_type`**（C4）；回授行进创建计划而非事后 `mutate`（失败即整个创建 `FAILED_CLOSED`）。
  **跨 Feature**: F048 runtime 公共入口加可选 kwarg，缺省行为零变化。
  **测试**: T057 全部通过
  **覆盖 AC**: AC-24, AC-61, AC-63
  **依赖**: T058

- [ ] **T060**: 资源归属人三条创建路径集成测试
  **文件**: `src/backend/test/open_api/test_resource_owner_paths.py`（新）
  **逻辑**: 以服务账号密钥（持 `knowledge:write`、被授予父库可编辑档）。**前置授权途径**：主体侧端点 T065 排在本任务之后、资源侧 `grants:mutate` 已被 T019 拒绝——本文件的授权 fixture **直接调 `resource_api.mutate_grants(..., allow_service_account_subject=True)`**（T019 加的显式参数，actor 用 `tenant_admin_payload` 解析的 `PermissionActor`），不经任何 HTTP 端点；T063 再经 `POST /{id}/grants:mutate` 端点验一遍同一路径。`test_owner_permission_change_does_not_affect_key` 里对归属人的加入 / 移出走普通资源侧 `grants:mutate`（自然人主体，不受 T019 影响）。用例：`test_create_knowledge_base_owner_and_autogrant`（`POST /filelib/` type≠3 → `knowledge.user_id == 归属人`、CREATOR 行主体 = 归属人、服务账号只有一条 `SERVICE_ACCOUNT_AUTOGRANT` 行且可继续写入）→ AC-24 / AC-61；`test_create_knowledge_space_same`（type=3 走 `KnowledgeSpaceService`）→ AC-24 / AC-61；`test_upload_file_owner_no_autogrant`（`POST /filelib/file/{kid}` / `chunks`：`KnowledgeFile.user_id == 归属人`、`updater_id == 服务账号`、文件 / 文件夹上服务账号**零行**且仍能再上传）→ AC-24 / AC-61；`test_owner_sees_resource_as_own`（归属人 `GET /api/v1/knowledge` 列表含之、可管理）→ AC-24；`test_session_stays_with_service_account`（v2 `chat/completions` 产生的 `MessageSession.user_id == 服务账号`，归属人会话列表不含）→ AC-25；`test_owner_permission_change_does_not_affect_key`（把归属人加入 / 移出另一知识库授权 → 服务账号对该库的 v2 读写结果不变）→ AC-26；`test_change_owner_not_retroactive`（换归属人 → 旧库 creator 不变、新建库归新归属人）→ AC-27。
  **覆盖 AC**: AC-24, AC-25, AC-26, AC-27, AC-61
  **依赖**: T059, T040, T008

- [ ] **T061**: `knowledge_service.py` 三处硬写参数化 + 回授字段
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_service.py`（`acreate_knowledge_base :795-799` / `create_knowledge_base :741-749`：`login_user.open_api_principal` 存在且 `subject_kind=='service_account'` → `db_knowledge.user_id = principal.resource_owner_user_id`；`_new_library_permission_record :194-208` 带 `creator_autogrant_user_id = login_user.user_id`（经 `_project_library_created :212-223` 透传）；`process_one_file :1483-1544` `KnowledgeFile.user_id` 同规则改归属人、`updater_id` 保持服务账号；`_new_library_file_permission_record :242-254` 不带回授（INHERIT））
  **逻辑**: D5 路径 1 与 3；`create_knowledge :674` 只是上层入口不改。
  **测试**: T060 知识库 / 文件用例通过
  **覆盖 AC**: AC-24, AC-25, AC-26, AC-27
  **依赖**: T060

- [ ] **T062**: `knowledge_space_service.py` + adapter 透传
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`（`create_knowledge_space :1100` `user_id` 同规则参数化；`:1110-1117 authorize_created(owner_user_id=…)` 记录带 `autogrant_user_id`）, `src/backend/bisheng/knowledge/domain/services/knowledge_permission_service.py`（`:995-1000` adapter 把记录上的 `creator_autogrant_user_id` 透传为 `authorize_created(autogrant_user_id=…)`）
  **逻辑**: D5 路径 2；QA 问答对与 `knowledge/*metadata*` 不是 F048 资源、不经接缝。
  **测试**: T060 全部通过
  **覆盖 AC**: AC-24, AC-61
  **依赖**: T061

- [ ] **T063**: 主体反查 + 授权端点 + 删除反查 集成测试
  **文件**: `src/backend/test/open_api/test_service_account_grants_api.py`（新）
  **逻辑**: `test_grants_endpoints_admin_only_403_envelope`（非管理员 GET / mutate / revoke-all → 信封 403）→ AC-59；`test_grant_add_via_subject_side_and_key_can_access`（`POST /{id}/grants:mutate` ADD 某知识库档位 → `GET /{id}/grants` 一条 `source_label='管理员授予'`（`DIRECT`）→ 持 `knowledge:read` 密钥可读该库）→ AC-19 / AC-60；`test_resource_side_still_rejects_26029`（资源侧端点授同一服务账号 → 26029；已授权对象列表仍显示该服务账号）→ AC-16 / AC-59；`test_list_is_single_list_with_source_and_bijective`（管理员授予 + 回授两类同列表；集合与 `permission_grant_assignee` 有效行一一对应；无 CREATOR 行；异常来源标「异常来源」并进日志）→ AC-61；`test_remove_then_key_gets_resource_error_then_restore`（REMOVE → v2 读该库返回业务资源权限错误（≠ 26003）；重新 ADD → 恢复）→ AC-62；`test_revoke_all_excludes_autogrant`（`POST /{id}/grants:revoke-all` 只删 `DIRECT`；回授行仍在；单条 REMOVE 回授行 → 集成写入失败；重新授予 → 恢复）→ AC-63；`test_page_header_keys_and_scope_gap_hint`（`GET /{id}/grants` meta 含名下密钥数与各自权限位、以及「已授权但无密钥持对应位」的资源 id 列表）→ AC-64；`test_grant_audit_events`（add / update / remove / remove_all：操作管理员、目标账号、资源类型与 id、前后档位、时间）→ AC-65；`test_delete_lists_grants_and_removes_all_including_autogrant`（`DELETE /{id}` 预检响应列全部授权含回授项；执行后逐资源 REMOVE、密钥失效、`deleted_at`；被授权资源与归属人不受影响）→ AC-48；`test_reverse_lookup_single_select_tenant_filtered`（子租户管理员反查 Root 服务账号 → 26020；SQL 无 UNION / `text()`（坑 14））。
  **覆盖 AC**: AC-16, AC-19, AC-48, AC-59, AC-60, AC-61, AC-62, AC-63, AC-64, AC-65
  **依赖**: T059, T024, T008

- [ ] **T064**: `permission.application.subject_api.list_subject_grants`
  **文件**: `src/backend/bisheng/permission/application/subject_api.py`（新：`list_subject_grants(subject_type='user', subject_id, tenant_id, resource_type=None, cursor=None)`：单条 `select` + join `permission_grant_assignee a JOIN permission_grant g WHERE a.subject_type='user' AND a.subject_id=:sa AND a.state='ACTIVE'`（命中 `ix_perm_assignee_subject_state`，`tenant_id` 由自动过滤注入）；资源名水合走 registry 白名单 `api/services/f048_permission_runtime.py:171-195`（不照抄前端 union）；返回行形状 = `PermissionGrantAssignee` + `source_type`）
  **逻辑**: D6 备选 C；只读 API，不改 F048 写路径。
  **跨 Feature**: `permission.application` 新增只读入口，供 F050 授权页「delegate 提示」复用。
  **测试**: T063 反查用例通过
  **覆盖 AC**: AC-61, AC-64
  **依赖**: T063

- [ ] **T065**: 授权端点 + 删除流程升级
  **文件**: `src/backend/bisheng/open_api/api/endpoints/service_account_grants.py`（新：`GET /{id}/grants`（分页、按 `resource_type` 筛、`source_label` 映射：`DIRECT`→管理员授予 / `SERVICE_ACCOUNT_AUTOGRANT`→创建时自动回授 / 其它→异常来源+日志；meta 含名下密钥位与 AC-64 缺口列表）· `POST /{id}/grants:mutate`（`{changes:[{resource_type,resource_id,op,model_key,expected_assignee_version?}]}`：校验管理员 + 账号存在 → 逐资源取 context → 调同一 `resource_api.mutate_grants` / runtime，携带 `allow_service_account_subject=True`；N 次 mutate 逐条结果、不做事务；审计 `open_api.grant.*` 含前后档位）· `POST /{id}/grants:revoke-all`（反查后过滤掉 `SERVICE_ACCOUNT_AUTOGRANT` 再逐条 REMOVE）), `src/backend/bisheng/open_api/domain/services/service_account_service.py`（`delete` 升级：反查 → 逐资源 REMOVE（含回授）→ `revoke_by_subject('subject_deleted')` → `deleted_at` → 审计；`DELETE` 预检返回授权清单）
  **逻辑**: D6 W2；管理员对目标资源无需另持权限（`_system_authorized`，`runtime.py:1077-1083`）；assignee 外键 `ondelete=RESTRICT` 指向 grant 非主体（`grant.py:137`），故必须显式 REMOVE。
  **测试**: T063 全部通过
  **覆盖 AC**: AC-16, AC-19, AC-48, AC-59, AC-60, AC-61, AC-62, AC-63, AC-64, AC-65
  **依赖**: T064

- [ ] **T066**: platform 「资源授权」tab
  **文件**: `src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/ServiceAccountGrantsTab.tsx`（新）, `src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/GrantResourceDialog.tsx`（新：选资源类型 / 资源 + 档位（`getGrantablePermissionModelsApi`，本页不自定义档位））, `src/frontend/platform/src/controllers/API/serviceAccount.ts`（追加 `getServiceAccountGrantsApi / mutateServiceAccountGrantsApi / revokeAllServiceAccountGrantsApi`）, `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/serviceAccount.json`（资源授权 tab 全部文案：来源标签 / 缺口提示 / 回授撤销确认 / 全部撤销说明 / 空态，三语同 PR）
  **逻辑**: 顶部：名下密钥数与各自权限位 + 「已授权但无密钥持对应位」提示（AC-64）；单一列表 + 来源列（`SourceBadge` 复用）+ 单条撤销（回授项 `bsConfirm`「撤销后该集成将无法再写入这个资源」）+ 「全部撤销」（文案明示不含回授项）+ 授予按钮；空态文案说明「零授权时该账号的一切开放 API 调用都会失败」（坑 21）；不复用 `PermissionDialog` 整体。
  **覆盖 AC**: AC-59, AC-60, AC-61, AC-62, AC-63, AC-64
  **手动验证**: 授予知识库可读 → 密钥可 `GET /filelib/`；撤销 → 资源权限错误；「全部撤销」后回授行仍在；无 `knowledge:read` 密钥时顶部出现缺口提示；非管理员直接访问 tab 路由不可见、直调端点 403。
  **依赖**: T065, T030

- [ ] **T067**: platform 删除弹窗升级 + 回授撤销确认
  **文件**: `src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/DeleteServiceAccountDialog.tsx`（新：列出 `DELETE` 预检返回的全部授权（含回授项）+ 「删除后这些授权一并失效、依赖它的集成将立即失败」，确认即删、不阻断）, `src/frontend/platform/src/pages/SystemPage/components/ServiceAccount/OverviewTab.tsx`（删除按钮改用该弹窗）, `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/serviceAccount.json`（删除弹窗清单 / 「一并失效」文案三语）
  **覆盖 AC**: AC-48, AC-63
  **手动验证**: 有授权的账号点删除 → 清单含管理员授予与回授两类 → 确认 → 删除成功、被授权知识库与归属人无变化。
  **依赖**: T066

### Wave 6 · 对账豁免 / 配额 / 管理接口矩阵 / 到期 Beat / 发布说明 / E2E

- [ ] **T068**: 对账豁免 + 配额排除测试
  **文件**: `src/backend/test/tenant/test_service_account_reconcile_exempt.py`（新）
  **逻辑**: `test_reconcile_skips_service_account_structurally`（子租户服务账号（无部门）跑 `reconcile_user_tenant_assignments` → 归属不变、`token_version` 不 bump、`tenant#member` 不重写；`alist_users_after_id` 结果不含服务账号；`sync_user` 直接传入服务账号 id → 入口守卫跳过）→ AC-17；`test_unmount_and_delete_tenant_paths_do_not_touch`（`tenant_mount_service :487-600` / `tenant_service.py:355-397` 路径不产生悬空）→ AC-17；`test_quota_user_count_excludes_service`（`_count_user_count` 与 `acount_users_by_tenant_subtree` 两处口径一致均不计，坑 11）→ AC-18。
  **覆盖 AC**: AC-17, AC-18
  **依赖**: T014, T008

- [ ] **T069**: 对账 / 配额 实现
  **文件**: `src/backend/bisheng/user/domain/models/user.py`（`alist_users_after_id :541-556` 加 `User.user_type == 'human'`）, `src/backend/bisheng/tenant/domain/services/user_tenant_sync_service.py`（`sync_user :76` 入口：目标 `user_type=='service'` → return，日志 debug）, `src/backend/bisheng/role/domain/services/quota_service.py`（`_count_user_count :622-651` 加类型条件）
  **逻辑**: 坑 7 / 坑 11；不改 `TenantResolver`、不改 guest 兜底三条路径（坑 6）。
  **跨 Feature**: `worker/tenant_reconcile/tasks.py:68` 经 `alist_users_after_id` 自动生效；自然人对账行为不变。
  **测试**: T068 全部通过
  **覆盖 AC**: AC-17, AC-18
  **依赖**: T068

- [ ] **T070**: AC-22 管理接口矩阵其余项 + 全局成员搜索测试
  **文件**: `src/backend/test/user/test_service_account_admin_ops_reject.py`（新）
  **逻辑**: 部门加成员 `aadd_members`、部门管理员 `aset_admins`、用户组 `replace_user_groups / set_group_admin / set_group_members` 五入口对服务账号 → 26022 → AC-22；`test_department_global_member_search_excludes`（`department_service :2255-2330` 全局成员搜索不含服务账号，即使被误塞 guest 部门也不含）→ AC-16；`test_guest_backfill_paths_do_not_hit`（`_backfill_guest_department_membership` / `_reconcile_guest_membership` / `_ensure_user_guest_department_membership` 三路径跑过后服务账号无 `user_department` 行——以测试断言固化，不改路径，坑 6）→ AC-22。
  **覆盖 AC**: AC-16, AC-22
  **依赖**: T017, T008

- [ ] **T071**: 部门 / 用户组管理接口拒绝 + 全局搜索纵深
  **文件**: `src/backend/bisheng/department/domain/services/department_service.py`（`aadd_members :1749` / `aset_admins :1986` 调 `assert_natural_persons`；全局成员搜索 `:2255-2330` 加 `User.user_type=='human'`）, `src/backend/bisheng/api/services/role_group_service.py`（`replace_user_groups :175` / `set_group_admin :238` / `set_group_members :271` 均为**同步**方法 → 调同步版 `assert_natural_persons`（T016 提供双版本）；department 两处 async → `aassert_natural_persons`）
  **测试**: T070 全部通过
  **覆盖 AC**: AC-16, AC-22
  **依赖**: T070

- [ ] **T072**: 到期兜底 Beat 任务测试
  **文件**: `src/backend/test/open_api/test_expire_credentials_task.py`（新）
  **逻辑**: `test_task_marks_never_called_expired_keys`（跨两租户造过期且从未再被调用的密钥 → 任务后 `revoke_reason='expired'`、`revoked_at` 仍 NULL、每把恰一条 `open_api.api_key.expire` 审计、`operator_name=='system'`）→ AC-05 / AC-12；`test_idempotent_with_lazy_channel`（先经校验惰性标记再跑任务 → 不重复审计）→ AC-12；`test_tenant_context_per_row`（写入时 `get_current_tenant_id() == row.tenant_id`；枚举在 `bypass_tenant_filter()` 内）。
  **覆盖 AC**: AC-05, AC-12
  **依赖**: T010, T008

- [ ] **T073**: Worker `expire_credentials` Beat 任务
  **文件**: `src/backend/bisheng/worker/open_api/tasks.py`（新，含 `__init__.py`：`expire_credentials`，默认队列、每小时）, `src/backend/bisheng/core/config/settings.py`（`celery_task.beat_schedule :167-189` 缺省注入 `open_api_expire_credentials`）
  **约束（tenant_id 传递）**: Beat 触发无租户上下文——任务体在 `bypass_tenant_filter()` 下枚举 `expires_at <= now AND revoke_reason IS NULL`，**逐行 `set_current_tenant_id(row.tenant_id)`** 后调 `CredentialService.mark_expired_lazy(row.id)`（同一条单行 UPDATE + 审计幂等闸）；写法同 `worker/tenant_reconcile/tasks.py:55-80`（backend AGENTS.md「Beat × 多租户」陷阱）。不删缓存（到期靠每请求比对）。114 若未起 Beat，惰性通道仍保证被拒时有记录。
  **测试**: T072 全部通过
  **覆盖 AC**: AC-05, AC-12
  **依赖**: T072

- [ ] **T074**: 发布说明「升级前必读」章节
  **文件**: `docs/api/开放 API 升级前必读（v3.0.0）.md`（新）
  **逻辑**: 四项（AC-50）：① 升级前三步（创建服务账号并指定归属人、在其详情页「资源授权」授权 → 签发密钥 → 调用方加 `Authorization: Bearer bs-sak-…` 头）；② 「升级完成到配好密钥之间存在接入空窗」，无兼容窗口 / 鉴权开关；③ 存量裸分享链接升级后失效、须在接入页重新生成（带有效期、可撤销）；④ 不再提供的 6 个 `/chat/*` 端点清单；另附：`default_operator` / `enable_guest_access` 配置移除说明（残留键无害）、`download_statistic` 入参 `file_path → file_name`、密钥前缀模式、`GET /api/v2/auth/whoami` 自检方法、`F049 + F050 合并发版`（裸 `user_id` 参数随 F050 移除）。
  **测试降级**: 文档交付物，无自动化断言——手动审阅四项齐全（AC-50 的 401 行为由 T034 自动化覆盖）。
  **覆盖 AC**: AC-50, AC-54
  **依赖**: T045

- [ ] **T075**: E2E（`/e2e-test`）+ 页面手动清单
  **文件**: `src/backend/test/e2e/test_e2e_openapi_auth_baseline.py`（新，由 `/e2e-test features/v3.0.0/049-openapi-auth-baseline` 生成）, `features/v3.0.0/049-openapi-auth-baseline/tasks.md`（本文追加「页面手动验证清单」结果）
  **逻辑**: API 层 E2E 走 design §7 步 3–5 剧本（真 HTTP 状态；非 admin 账号）；页面手动清单覆盖 AC-41–49 / 59–65 的界面路径，尤其 **AC-43**（创建成功直达签发入口，前端行为）与 **AC-45**（一次性展示：复制 + 「关闭后不可再查看」+ 「我已保存」才可关闭）——两者为纯前端行为、无后端可断言点，Playwright 未落地故只能在此覆盖。DM8 / SSO / 网关外部环境验证拆到 T075a。
  **测试降级**: 前端交互（AC-43 / AC-45）= 手动验证——理由：Playwright 未落地。
  **覆盖 AC**: AC-41, AC-42, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48, AC-49, AC-59, AC-60, AC-61, AC-62, AC-63, AC-64, AC-65
  **依赖**: T033, T046, T056, T067, T071, T073, T074

- [ ] **T075a**: 外部环境回归：DM8 105 + SSO / 网关 109（AC-15 手动部分）
  **文件**: `features/v3.0.0/049-openapi-auth-baseline/tasks.md`（本文「114 部署记录」下追加「105 / 109 回归记录」结果）
  **逻辑**: **DM8 105 回归**（CICD：push → Drone 打镜像 → 105 pull && up，tag 可变须先 pull）：建 ≥ 2 个服务账号（`(source='service_account', external_id=NULL)` 多行唯一性，D1 风险）+ 5 秒失效矩阵抽样（撤销 / 停用 / 到期）+ `JsonType` scopes 读回 + T001 / T047 两 revision 在 DM8 上 upgrade / downgrade 各一次；**AC-15 手动部分**：109 联调环境（入口 120:3003 → 3001 → 8098 Gateway → 7860）用服务账号用户名走 Java 网关登录同步 / SSO 网关回调 → 均 26012（不是「无菜单」）。
  **测试降级**: SSO / 网关入口（AC-15 部分）= 手动验证——理由：网关不在本仓、无 TestClient 可达；DM8 无本地实例。
  **覆盖 AC**: AC-15, AC-19, AC-47
  **依赖**: T075

---

## AC → 任务追溯表（核对用）

> 每条 AC 至少出现在一个**测试任务**的「覆盖 AC」里；标 † 的仅由 E2E / 手动清单（T075）覆盖，理由见该任务。

| AC | 测试任务 | AC | 测试任务 | AC | 测试任务 |
|---|---|---|---|---|---|
| AC-01 | T011, T020, T034 | AC-23 | T013, T023 | AC-45 † | T075 |
| AC-02 | T009, T025 | AC-24 | T057, T060 | AC-46 | T025, T075 |
| AC-03 | T009, T011, T051 | AC-25 | T060 | AC-47 | T011, T013, T023, T051, T075, T075a |
| AC-04 | T020, T034 | AC-26 | T060 | AC-48 | T013, T023, T063, T075 |
| AC-05 | T009, T011, T072 | AC-27 | T013, T060 | AC-49 | T023, T025, T075 |
| AC-06 | T009, T025 | AC-28 | T013, T023 | AC-50 | T034（401 无回落）, T074（发布说明·手动） |
| AC-07 | T023, T025 | AC-29 | T034, T051 | AC-51 | T044 |
| AC-08 | T009, T025 | AC-30 | T034 | AC-52 | T044 |
| AC-09 | T009, T025, T051 | AC-31 | T051 | AC-53 | T044 |
| AC-10 | T009 | AC-32 | T011, T020 | AC-54 | T044, T074 |
| AC-11 | T009 | AC-33 | T020 | AC-55 | T048, T051 |
| AC-12 | T009, T013, T025, T072 | AC-34 | T011, T020 | AC-56 | T048, T051 |
| AC-13 | T020, T025 | AC-35 | T020, T034, T035 | AC-57 | T048 |
| AC-14 | T025 | AC-36 | T034 | AC-58 | T051 |
| AC-15 | T015（四入口自动化）, T075a（SSO / 网关手动） | AC-37 | T041 | AC-59 | T023, T063, T075 |
| AC-16 | T015, T018, T063, T070 | AC-38 | T041 | AC-60 | T063, T075 |
| AC-17 | T068 | AC-39 | T035 | AC-61 | T057, T060, T063, T075 |
| AC-18 | T068 | AC-40 | T041 | AC-62 | T063, T075 |
| AC-19 | T013, T023, T063, T075a（DM8） | AC-41 | T023, T075 | AC-63 | T057, T063, T075 |
| AC-20 | T015, T023 | AC-42 | T023, T075 | AC-64 | T063, T075 |
| AC-21 | T011, T013, T051 | AC-43 † | T075 | AC-65 | T063, T075 |
| AC-22 | T015, T070 | AC-44 | T025, T075 | | |

**未被任何测试任务覆盖的 AC：无。**

**汇总**：任务 76 个（T001–T075 + T075a）；Wave 6 个；`[MVP-114]` 任务 33 个（T001–T033，Wave 1–2 全部）；测试任务 22 个（T009 / T011 / T013 / T015 / T018 / T020 / T023 / T025 / T034 / T035 / T041 / T044 / T048 / T051 / T057 / T060 / T063 / T068 / T070 / T072 / T075 / T075a）；数据库变更 3 个（T001 / T002 / T047，均含回滚方案；T047 实际与 T001 同批执行）；Client 任务 2 个（T055 / T056）。

---

## 114 部署记录

> T033 执行时填写：部署时间 / commit / `open_platform` 键写入时间 / 手动验证结果。

（未开始）

### 105 / 109 回归记录

> T075a 执行时填写：DM8 镜像 tag / 两 revision upgrade-downgrade 结果 / 5 秒失效矩阵抽样 / 109 网关与 SSO 入口 26012 截图或日志。

（未开始）

---

## 实际偏差记录

> **只留一行指针**，论证在 design.md（决策 / 坑），这里不重复（见 `docs/SDD-Guide.md` §4）。
> 推翻已 ★ 确认的决策时，先停下与用户重新确认（§3 第四个 ★），再记录。

| 任务 | 偏差 | 回写到 design | 原因（一句话） |
|---|---|---|---|
| T024 | 管理面读写显式带 `tenant_id` 条件（`ServiceAccountService.get_row/get_detail/list_page` + `ServiceAccountDao.alist_page(tenant_id=)`），不只靠自动租户过滤 | design §4.3「open_api/」行 + 坑 14 旁注 | 子租户管理员的 `visible_tenant_ids` 是 `{leaf, Root}` IN-list，只靠自动过滤会让他看到 Root 的服务账号，违反 AC-07 |
| T021 | `open_api_subject(scope)` 返回**依赖可调用对象**（用法 `Depends(open_api_subject(...))`），不是 `Depends` 实例 | design §4.3「`open_api_subject(scope=…)` `Depends` 工厂」措辞 | tasks T020 的验收写法即 `Depends(open_api_subject('app:manage'))`；返回 `Depends` 会变成 `Depends(Depends(...))` |
| T022 | handler 函数定义在 `open_api/api/exception_handlers.py`，`main.py` 只调 `register_open_api_exception_handlers(app)` | design §4.3「main.py」行 | 让测试能在同一函数上验证 handler，且 `main.py` 不再堆 open_api 细节；注册点仍是 `main.create_app` |
| T021 | 依赖出口不再重复调 `CredentialService.touch_last_used`（T012 已在 `validate_bearer` 内做） | 无（D2 顺序不变，只是落点在 validator） | 重复调用只会多一次同样被 60s 闸拦下的写，无额外信息 |

（实现期每条偏差一行，design 同步覆盖为「今天的状态」。）

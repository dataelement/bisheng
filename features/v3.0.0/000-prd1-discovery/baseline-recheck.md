# F049 基线核实速查（3.0-vibe / feat/3.0.0-beta1，含 F048）

> 2026-08-06 三路并行代码核实的浓缩结论，供 F049 design 与 F050 spec 直接引用。
> 上一轮 `research/` 11 份是在 **main（pre-F048）** 上做的，与本基线相差 242 个后端文件；
> 本文件覆盖其中与 F049/F050 相关的三块，**冲突时以本文件为准**。
> 全部为代码核实；标「推断」的除外。行号对应 3.0-vibe rebase 前的 `584f2c253`，rebase 后内容未变。

---

## 一、v2 开放 API 端点盘点（改造工作量基数）

**44 个端点**（不是 45/50+），8 个路由文件，全部零鉴权。`router_rpc`（`api/router.py:94-102`）构造时**没有 `dependencies=`**，8 次 `include_router` 也没带 —— 加 router 级依赖技术可行、零冲突。挂载点 `main.py:285`。

按身份来源分类（这是逐端点改造的真实基数）：

| 身份来源 | 数量 | 改造性质 |
|---|---|---|
| `Depends(get_default_operator_async)` | 9 | 最轻，换依赖即可（knowledge.py 全部 8 个 + citation.py:23） |
| 函数体内联 `get_default_operator*()` | 25 | 中等，需改函数体；其中 4 个结果被丢弃、仅用于播种租户上下文 |
| `resolve_operator(裸 user_id)` 代用户 | 3 | 重，需接受限委托准入（filelib.py:157/362/623） |
| 裸 user_id 直写 | 1 | 重（chat.py:80 `/sync/messages`，连用户存在性都不查） |
| **完全无身份** | **6** | 重，函数体内无任何调用者信息可用 |

**6 个无身份端点**：`chat.py:23/31/48/60/74`（gen_title / history / liked / solved / comment —— 任何人可改任意会话）+ `filelib.py:496`（`download_statistic`，见下）。

`filelib.py:496-506` 的 `download_statistic_file(file_path: str)`：只校验后缀为 `.log` 且路径以 `/app/data` 开头（含一个 `.` 字符检查），随后 `FileResponse(file_path)` —— **调用方可指定路径取走服务器上任意 `.log`**，无身份无归属校验。

**三个身份解析函数**（`open_endpoints/domain/utils.py`）：`get_default_operator` :26-50 / `get_default_operator_async` :53-74 / `resolve_operator` :77-104，三者末尾各自 `set_current_tenant_id`（:49/:73/:103）。`resolve_operator` 的租户种子来自**调用方指定的目标用户**（:96-97）。全仓 `open_endpoints/` 之外零调用者 → **这是唯一入口，是最省工的改造点**。

**两层改造方案（推断，需实测）**：① router 级 `dependencies=[Depends(verify_credential)]` 保证「无凭据 401」对 44 个端点无死角；② 新依赖把解析出的 UserPayload 写进 ContextVar，再改上述三个函数「先读 ContextVar，读不到才按开关决定回落或 401」→ **34 个端点零改动**完成身份切换，真正要单独动刀的只剩 10 个（2 个 WS + 6 个无身份 + 3 个代用户，有重叠）。

**易漏点**：`flow.py:8` 是从 `endpoints.assistant` 转导入 `get_default_operator`，不是从 `domain/utils` 直取；`api/dependencies.py:61-77` 的 `get_knowledge_space_chat_service_for_openapi` **全仓无调用者**（死代码，只能当样板）。

**前端 v2 依赖面**：`ApiAccess.tsx:38/57/111`、`ApiAccessFlow.tsx:53/78/82`、`client/src/api/chat/api-endpoints.ts:51`。另 `chatShare.tsx:25` 引用的 `/api/v2/chat/ws/{flowId}` **后端不存在**（前端死路径）。

### ⚠️ 两个 WS 端点同时是平台免登录分享页的通道

- `workflow.py:157` `/api/v2/workflow/chat/{workflow_id}`：JWT 校验被注释在 :165-166，docstring :162 写 "Use Exempt Login Link" ← `chatShare.tsx:16` 在连
- `assistant.py:298` `/api/v2/assistant/chat/{assistant_id}`：无鉴权，且 `get_default_operator()` 在 :304 位于 try(:305) **之外** → 配置缺失时握手裸崩 ← `chatAssitantShare.tsx:11` 在连
- 路由注册：`platform/src/routes/index.tsx:24-25`

浏览器原生 WebSocket **无法设置请求头** → 分享页不可能携带密钥。强制鉴权 = 已发布分享链接全部失效。这是 spec §4 待澄清-1 的事实基础。

WS 握手读 Authorization 的可行性：FastAPI 的 `WebSocket` 对象自带 `.headers`，新依赖直接读即可，**不需要改中间件、不需要改 AuthJwt**。WS 中间件（`http_middleware.py:396-412`）已在读 `scope["headers"]`，只是当前只取 cookie。

---

## 二、身份体系与 User 表（凭据鉴权的接入面）

- **JWT**：`AuthJwt`（`auth.py:129-193`），HS256，cookie 名 `access_token_cookie`，`path=/`、`domain=None`、`httponly=True`、`secure=False`、`samesite=None`（`settings.py:487-499`）。payload 只有 `sub`/`exp`/`iss`，**无 jti/iat/typ**。
- **v1 端点只认 cookie**：`get_subject` 的 `auth_from="headers"` 分支存在（`auth.py:178-180`）但**全仓零调用方**，且有 NPE 缺陷（缺 header 时 `.split()` 于 None）。→ **凭据鉴权必须新写依赖，不能复用它。**
- **中间件会先看到 Bearer 头**：`_extract_http_access_token`（`http_middleware.py:60-73`）cookie 优先、其次 Bearer，会尝试当 JWT 解码；`bs-sak-` 解不开返回 None，不 500，但**也不会注入租户上下文** → 凭据依赖必须自己 `set_current_tenant_id`。
- **`/api/v2/*` 不在中间件豁免清单**，但因无 JWT，token_version 校验/禁用检查/租户状态检查全部跳过。
- **身份构造**：`init_login_user`（`auth.py:531-565`，async，**推荐入口**）≈ 1 次 DB（user_role）+ 1 次 Redis（is_super）；支持 `role_ids=` 注入省掉 DB。⚠️ `LoginUser.__init__`（:219-232）在未传 `user_role` 时有**同步 DB 副作用**，async 上下文会阻塞事件循环 —— 别直接 `LoginUser(user_id=...)`。
- ⚠️ **`init_login_user_sync`（:567-589）不计算 `is_global_super`（恒 False）**，而 F048 的 `resolve_permission_actor` 正是读这个字段判超管短路。当前多数 v2 端点走 sync 路径 → 同一个 default_operator 在 sync/async 两条路径下的 F048 判定结果不同。统一走 async 会**放宽**这些端点的现有权限（spec §4 待澄清-2）。同类隐患：`tool/domain/services/executor.py:96-105` 自造 UserPayload 也不带该字段。
- **User 表无 `user_type`**（全仓 grep 零命中）→ 服务账号主体需 Alembic 加列（既有表加列必须走 revision）。
- **不可登录性半免费**：`UserDao.aget_login_candidates_by_account`（`user.py:211-223`）是 `/user/login` 唯一候选查询，条件只有 `delete == 0 AND external_id == acc` —— **user_name 根本不参与匹配** → `external_id IS NULL` 的服务账号结构性进不了密码登录。（附带：`user.py:425` 注释「支持用户名或 external_id」与实现不符，是过期注释。）
- **`/user/list` 有统一过滤入口**：`UserDao._filter_users_statement`（`user.py:259-264`），被 `filter_users`/`afilter_users` 共用 → 加一个默认 `user_type == human` 条件即可覆盖两个消费点。**不经过它**的查询需单独处理：`get_all_users`(:400)、`search_user_by_name`(:295)、`get_user_with_group_role`(:411)、`get_user_by_ids/aget_user_by_ids`(:177/:183)、`get_unique_user_by_name`(:289)。
- **禁用传导挂接点仍可用**：`UserService.ainvalidate_jwt_after_account_disabled`（`user.py:70-90`）是唯一收敛点，6 个调用点；但 `user_tenant_sync_service.py:117` 与 `wecom_gateway_absent_reconcile.py:117` **绕过漏斗直连 DAO**。
- **撤销 ≤5s 该抄的范式**：`UserDao.aincrement_token_version`（`user.py:512-538`）—— 原子 UPDATE + **主动 `aset` 覆盖缓存**（非 DEL），TTL 300s 只是兜底。把 TTL 降到 5s 即满足要求，形状可一比一复制。「按主体批量吊销」可借鉴 `PermissionCache` 的双前缀 SCAN+DEL（`permission_cache.py:112-140`），key 设计成 `cred:{owner_id}:{key_id}` 便于扫。
- ⚠️ **失败语义分歧（须在 spec/design 显式声明）**：中间件 token_version 校验是 **fail-open**（`http_middleware.py:140-141`，注释「don't lock users out on cache/DB hiccup」）；凭据校验属鉴权，必须 **fail-closed**。这是刻意的不一致。

---

## 三、F048 权限运行时（pre-F048 结论全部作废）

- **唯一业务入口**：`check_business_action` / `require_business_action` / `batch_check_business_actions`（`permission/application/business_authorization.py:27/46/62`）。`PermissionService` 已降格为身份/LLM 兼容桥，对 F048 业务资源类型直接 raise。
- **短路只剩两个 allow-all**：super_admin、当前租户的租户管理员（`permission_action_service.py:379-384`）。**Root 租户（id=1）没有租户管理员这一档**（`identity.py:30-37`）。
- **委托红线该用的谓词**：`resolve_permission_actor(login_user)` → `actor.super_admin` / `actor.tenant_admin_tenant_ids`；仓内已有等价实现 `F048PermissionRuntime._system_authorized`（`runtime.py:1074-1081`）。**不要用 legacy `login_user.is_admin()`**（那是 RBAC AdminRole 位，与 F048 super_admin 不是一回事）。
- **fail-closed 已是现状**：FGA 异常 → `PermissionFGAUnavailableError`；Catalog 未就绪 → `PermissionPublishNotReadyError`；资源镜像非 CURRENT（含 FAILED_CLOSED）→ 同上；动作未分级 → `InvalidCatalogActionError`；模型 checksum 不符 → 进程标 migration_required、**全站 503**。**无任何 owner/creator 兜底**。
  - 唯一还带 fail-open 味道的：`_check_is_global_super`（`http_middleware.py:181-197`）在 FGA 异常时回落 legacy AdminRole 判定 → 故障时反而可能把人判成超管并命中 allow-all。**这是 D6 残留项的具体锚点。**
- **列表过滤范式**：SQL 出业务候选 → `batch_check_business_actions`（每 100 一批）；ListObjects 生产装配 `DenyListObjectsPolicy`（`sql_runtime.py:638-648`），**无生产调用方**。
- **性能**：F048 路径**完全无缓存**，每次 check ≈ 3 次 SQL + 1~3 次 Redis + 1 次 FGA Check，批量路径每个 target 重复前 3 次 SQL（N+1，推断为风险）。MCP/应用运行时高频检索会放大。
- **新增资源类型（如 app）要改 12 处后端 + 3 处前端**：
  1. `authorization_model_f048.py:32` `MIGRATED_RESOURCE_TYPES`；2. `:55` `RESOURCE_ACTION_SCOPES`；3. `:80` `PARENT_TYPES`（若有父层级）；4. `:93` `SYSTEM_SHARED_ACTION_TYPES`（若要 user:* 共享）；5. `catalog_policy.py:31` `MIGRATED_RESOURCE_TYPES`（**必须与 1 同步**）；6. `:45` `ACTION_RESOURCE_SCOPES`；7. `:16` `REGISTERED_ACTION_CODES`（若新增动作）；8. `resource_lifecycle_policy.py:14-26` `FLEXIBLE_MODE_TYPES`/`FIXED_CUSTOM_TYPES`（否则 `default_permission_mode` 抛错）；9. `owner_service.py:34` allowlist（若 system-owned）；10. 新建 adapter（照抄 `api/services/f048_application_permission.py:122-225`）；11. `f048_permission_runtime.py:166-195` 注册进 registry（**这是 resource_type 的实际白名单**）；12. `f048_source_inventory.py:16/30`。
  前端：`platform/controllers/API/permission.ts:5-15`、`platform/components/bs-comp/permission/types.ts:3-13`（**两处重复定义**）、`client/src/api/permission.ts:3-13`。
- ⚠️ **存量环境生效缺口（真实、可落地到 spec）**：授权模型本身有 checksum + 503 闸门（比 pre-F048 好），但 **Catalog 的「动作↔资源类型范围表」只在首次迁移与草稿发布时写入**，且 `CatalogChangeType` 枚举**没有「改资源范围」这一种**，迁移脚本又因 checksum 不符无法重跑 → 给存量环境加资源类型**必须新写运维脚本或扩展变更类型**（推断为唯一出路）。
- **创建即 owner 的现行契约**：adapter 的 `authorize_created`（非 `PermissionService.authorize`）→ protected owner grant + 投影账本（prepare → SQL 预写 → 投影 OpenFGA → finalize）。失败 → 置 `FAILED_CLOSED` → **该资源任何权限判定都 fail closed（资源变砖）**，且**业务行不回滚**（`api/v1/workflow.py:312-318` 先落库再 hook）。人工恢复走 `scripts/reconcile_f048_projection_operations.py`。
- **存量隐患**：前端三处类型都含 `linsight_skill`，但后端 registry 未注册 → 对它调通用授权 API 直接报 `PermissionInvalidResourceError`。

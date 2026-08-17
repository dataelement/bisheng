# Design: 开放 API 鉴权底座（默认拒绝 + 服务账号密钥 + 资源归属人）

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**（65 条 AC、边界、决议）
> - `design.md`（本文）回答 **为什么这么实现**：关键决策（含被否决的备选）、运行时不直观的事实、对外契约
> - `tasks.md` 是 **流水账**：拆了哪些任务、做了什么改动
>
> 调整原则（详见 `docs/SDD-Guide.md` §3-§4）：实现变化 → 覆盖更新本文档、只留"今天的状态"；但每个决策保留"为什么 + 被否方案"和坑。推翻已 ★ 确认的决策 → 停下与用户重新确认；纯实现细节 → 直接改 design。
>
> **代码事实口径**：本文所有 `文件:行号` 均按 `3.0-vibe`（HEAD `b63a320f2`，含 F048）在 2026-08-17 核实，路径以 `src/backend/bisheng/` 为根（前端另注 `platform/` = `src/frontend/platform/src/`、`client/` = `src/frontend/client/src/`）。行号会漂移，符号名不会——落地前以符号名重定位。凡文档锚点已在代码中消失的，标「已失效」。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)（待写）· [release-contract.md](../release-contract.md)（表 1 ApiCredential / ServiceAccount / ShareLink，INV-27~31）· [mvp-114-path.md](../mvp-114-path.md) · [baseline-recheck.md](../000-prd1-discovery/baseline-recheck.md)
**版本**: v3.0.0
**最后更新**: 2026-08-17（初版 + 同日审查修订；尚未开工，本文是"要建成的样子"，实现后按现状覆盖）

---

## 1. 目标与非目标

- **目标**：给 `/api/v2/**` 装上唯一一条凭据校验路径——服务账号密钥 `bs-sak-`（只存哈希、软撤销、5 秒内失效、按位授权），让每个外部调用都能定位到"哪个集成、哪个租户、哪些权限位"，并把匿名超管通道彻底关掉。为此交付三块地基：服务账号主体（不可登录、不进选人、必填资源归属人）、管理界面（列表 / 新建 / 详情三 tab，含主体侧唯一授权入口）、开放能力层开关与三扩展位登记（F051–F053 复用）。两个免登录分享页同步改走 share-token 通道。
- **非目标**（详见 spec 范围边界，此处防扩范围）：身份传递（模式 D / OBO / End-User 头 / `delegate` 位 / 审计双归属）→ F050；三扩展位的运行期消费与入口拒绝 → F051 / F052 / F053；接入信息区 → F053；应用运行期凭据编排 → F055；Responses 契约 → F058；文件级检索过滤 → F052；限流 / 配额 / IP 白名单 / 幂等 → P2；个人 key（`bs-pat-`）整条废除；平台侧任何存量迁移。

---

## 2. 关键约束

> 全局铁律（DDD 分层 / 双 DB / 多租户自动注入 / 权限唯一入口 / 错误码 / 无硬编码密钥 / 前端 store 不直连 HTTP）一律遵循 [`docs/constitution.md`](../../../docs/constitution.md) **C1–C7**，本节不重抄。以下只写本 Feature 特有的硬约束。

| # | 约束 | 出处 / 后果 |
|---|---|---|
| K1 | **撤销 / 停用 / 删除 / 编辑 → 5 秒内生效**，且靠**主动失效**（撤销时删缓存），不靠 TTL 自然过期兜底 | INV-28 / AC-03、08、09、21、47、56。任何"进程内 dict 缓存"都被 K7 否决 |
| K2 | **哈希恒时比较 + fail-closed**：Redis 或 DB 抖动时**拒绝**（与平台既有会话续期 `_validate_token_version` 的 fail-open `utils/http_middleware.py:139-141` 刻意相反） | spec §3 已声明是刻意差异；INV-30 |
| K3 | **有效性判据唯一** = `revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now)`；密钥表**不设** status 枚举列 | INV-28；反例 `share_link.status` INACTIVE 全仓无写入端点（`share_link/domain/models/share_link.py:62`） |
| K4 | **HTTP 状态语义必须真实**：AC-01/04/33/34 要求真 401 / 403 / 5xx，但平台 `handle_http_exception`（`main.py:22-36`）把 `HTTPException` 与 `BaseErrorCode` 统一压成 **HTTP 200 + 信封**。本 Feature 的鉴权层错误必须走**专属 exception handler**（先例 `main.py:165-167` `AuthJWTException → JSONResponse(401)`） | E1 已用最小 FastAPI 复现验证 |
| K5 | **DM8 双库对新表 / 改表的影响**：新表靠 `create_all(checkfirst=True)`；给 `user` 加 `user_type` 必须 Alembic revision（模板 `core/database/alembic/versions/v2_5_1_f012_user_token_version.py`）；哈希 / 前缀列用 `VARCHAR` 不用 `CHAR`（DM8 CHAR 去尾空格补丁 `dialect_helpers.py:117-141` 是历史包袱）；权限位列用 `JsonType`（DM8 落 CLOB → **不能在 SQL 里按位过滤**，只能取回后 Python 判）；不给 `share_link.resource_type`（`SQLEnum`，MySQL 原生 ENUM）加枚举值 | C2；E1 §6.3 |
| K6 | **密钥表 / 服务账号表禁批量 UPDATE / DELETE 与 `text()`**：租户自动过滤只拦 SELECT（`core/database/tenant_filter.py:164`），批量写路径无租户注入。撤销 = 单行 ORM 更新；最后使用时间 = 带主键单行 UPDATE；按哈希查凭据必须在 `bypass_tenant_filter()` 下（此时尚无租户上下文） | C3 + backend AGENTS.md 已知陷阱；PRD 附录 E.1 |
| K7 | **所有改动默认多节点**：进程内缓存只能当性能加速、不能承载正确性；失效只能靠 Redis | memory `feedback_multinode_default_assumption` |
| K8 | **开放能力层开关三段式**：进程级 Settings（`config.yaml`，需重启）→ `GET /api/v1/env` → 前端 `appConfig`；**不是** DB 热配置（100s Redis TTL、语义是租户偏好而非部署形态）。服务账号模块恒在，开关只 gate 三扩展位与接入信息区（AC-49） | 先例 `multi_tenant.enabled`（E1 §3） |
| K9 | **凭据校验先于租户上下文，且必须无条件覆盖 ContextVar**：`http_middleware.py:60-73 → _set_tenant_context :87-122` 对解不开的 Bearer **预种租户 1**（不是"不注入"）；依赖忘了 `set_current_tenant_id(密钥租户)` 时多租户下**静默按 Root 查**而非报错 | E1 §0-2；C3 |
| K10 | **MVP-114 首波边界**（`mvp-114-path.md` §2 F049 行）：先交付凭据底座 + 服务账号主体 + 权限位清单 / 开关 + 管理界面（列表 / 新建 / 概览 / API 密钥 tab）+ 供 F053 / F055 复用的 `Depends` + `app:manage` 判定；36 端点接入 / WS / share-token / 资源授权 tab / 缺陷修复 / 配置移除 / 审计全覆盖排第二波（见 D13） | 纵切裁剪只改顺序不改口径 |
| K11 | **F049 不得脱离 F050 单独对外发版**（裸 `user_id` 须随 v3.0.0 移除）；开发期内 `resolve_operator` 保留、只补状态与同租户校验 | spec 范围边界 / AC-35、39 |
| K12 | **错误码 260 段**：C5 登记表写"reserved / not yet implemented"，落码同一改动回写；新增 260xx 不补三语 `packages/locales/src/api_errors/*.json` 即 CI 失败（`src/frontend/scripts/check-i18n.mjs:97-101/141-147`，仓库根 `scripts/` 下无此文件） | C5；E1 §5.1 |

**Constitution Check（自查）**：C1 新模块 `open_api/` 按 `api/ + domain/` 分层，v2 端点不跨模块导入 `open_api/api/*`（RULE-5，见 D3）；C2 见 K5；C3 见 K6 / K9；C4 授权写路径只经 F048 runtime（D5 / D6）、无 OpenFGA 直连、反查走 SQL 投影账本；C5 见 K12 / D10；C6 密钥明文不落盘不进日志；C7 前端只经 `controllers/API/`。

---

## 3. 方案对比与选定

> 每条 3 段：备选 / 选定 / 原因 + 何时该重新考虑。这里是"想当然会走但被否决"的路的登记处。

### 决策 1（D1）：服务账号主体形态 = 复用 `User` 表 + `user_type` 列 + 伴生属性表 `service_account`

- **备选**：
  - A. **独立 `service_account` 主体表**，与 `user` 平行 — 优点：干净、不污染用户表；缺点：F048 授权主体类型是 `user`（`tenant/domain/services/f048_permission_subject.py:53-91 canonical_source`、OpenFGA 模型 `directly_related_user_types`、投影 `owner_service.py`）——新主体类型要改授权模型 / 主体校验 / 投影 / 前端 roster 全链路，且会话 `MessageSession.user_id`、审计 `operator_id`、创建人列全部按 `user_id` 建模
  - B. **复用 `User` 表**：`user.user_type`（`human` / `service`，索引，Alembic 加列）+ `source='service_account'` + `external_id=NULL` + 密码哨兵；SA 专属属性（资源归属人 / 描述 / 创建人 / 停用 / 删除时间）放伴生表 `service_account`（PK = `user_id`，物理带 `tenant_id`） — 优点：F048 零改动、会话 / 审计 / 创建人语义直接成立；缺点：三处成本（租户归属直写 + 对账豁免、登录入口封堵、选人场景排除）与 `uk_user_source_external_id(source, external_id)` 多行 `(service_account, NULL)` 的 DM8 风险
  - C. B 但 SA 属性全塞 `user` 表新列 — 缺点：`user` 是热表、多列 Alembic、`user` 无 `tenant_id` 无法靠自动过滤做 AC-07
- **选定**：**B**
- **原因**：PRD §4.5 D4 已定复用；E2 核实 F048 `runtime.authorize_created`（`permission/application/runtime.py:206-247`）`owner_user_id` 与 `actor` 本就是两个入参、按主体反查索引 `ix_perm_assignee_subject_state`（`permission/domain/models/grant.py:118`）已现成——主体类型仍是 `user` 才能白吃这些。伴生表让"服务账号列表按租户过滤"（AC-07）直接由 `_TENANT_AWARE_MODEL_MODULES` 自动过滤兜住。`external_id=NULL` 使 `aget_login_candidates_by_account`（`user/domain/models/user.py:212-223`）、login-sync 匹配（`sso_sync/domain/services/login_sync_service.py:263-266`）、公开改密（`user/api/user.py:1103`）三条路径**结构性不命中**（AC-15 的零代码防线）。DM8 部分 NULL 唯一性：仓内同构先例 `uk_user_active(user_id, is_active)`（`database/models/tenant.py:185`）已在 105 DM8 跑过多条同 `user_id` 的 NULL 行（E2 §1.1）——作旁证，但**建 ≥2 个服务账号的 DM8 用例列入 §7 必测**。
- **停用 / 删除表达**：`service_account.disabled_at` / `deleted_at`（可空时间戳）是**唯一状态源**；`user.delete` 只是它的**同事务写穿投影**（任一时间戳非空 → `user.delete=1`，为空 → `0`），作用仅是让全部面向人的 `delete==0` 过滤自然隐藏它。**读侧口径统一**：凭据校验、服务账号列表「状态」列、详情启停按钮、`GET /{id}` 全部只读伴生表两列，不读 `user.delete`；名称水合走 `aget_user_by_ids`（`user/domain/models/user.py:184`，**不过滤 `delete`**，E2 已核）故停用 / 已删账号在授权列表仍能显名。`user.delete` 可被 SSO / `/user/update`（`user/api/user.py:709`）单独翻转的风险由 D7 `assert_natural_persons` 守（对服务账号 → 26022）；即便被翻，凭据校验与状态列不受影响，只可能出现"人向过滤下重新可见"这一种偏差，且下一次启停操作会把投影重写一致。这与 K3「不引入可独立漂移的状态」一致：漂移的只是投影，不是真相。
- **建号事务**：`ServiceAccountService.create` 在**一个** `async with get_async_db_session()` 内依次 `session.add(User)` → `flush()` 取 `user_id` → `add(ServiceAccount)` → `add(UserTenant(status='active', is_active=1))` → 单次 `commit()`；**不复用** `UserDao.create_user`（`user/domain/models/user.py:302-307`，sync、独立会话、独立提交）与 `aactivate_user_tenant`（`database/models/tenant.py:867`，独立 async 会话；其"先降级既有活跃行"一步对全新用户也无意义）——三者各自提交无法构成事务，中途失败会留下"有 user 行无伴生行 / 无租户行"的孤儿（凭据校验按 D2 的"主体存在且伴生表可读且活跃租户 == 密钥租户"三连判会拒绝它，但列表看不到、`/user/list` DAO 过滤又不显示 → 只能进 DB 清）。单事务下失败即全无、无需恢复语义；审计 `open_api.service_account.create` 在 commit 后写、失败只记日志不回滚建号。新写 `ServiceAccountDao.acreate_with_user(session, ...)` 一类"接受外部 session"的方法，不在 DAO 内开会话。
- **何时该重新考虑**：DM8 用例证明 `(source, NULL)` 多行冲突 → 退化为 `external_id='sa:{uuid}'`（登录免疫退化为纯靠守卫，测试矩阵不变）；或 F050 之后出现第二类非人主体（如托管应用要成为授权主体）→ 那时再评估独立主体表。

### 决策 2（D2）：凭据校验位置与形态 = router 级 v2 依赖（HTTP + WS 同一函数）+ 专属异常处理器 + Redis 短缓存 + 主动失效

- **备选**：
  - A. **中间件**（仿 `utils/http_middleware.py`）— 优点：一处覆盖；缺点：中间件对所有路径生效、要靠 path 前缀判断；拿不到 FastAPI 依赖链与路由元数据（权限位）；WS 与 HTTP 在中间件层分叉（`WebSocketLoggingMiddleware :385`）；异常只能手写 `JSONResponse`
  - B. **router 级 `dependencies=[Depends(verify_open_api_access)]`** 挂在 `api/router.py:94` `APIRouter(prefix='/api/v2')` 构造处；依赖签名 `conn: HTTPConnection`，`isinstance(conn, WebSocket)` 分流 — FastAPI 0.121 `include_router` 把 router 级依赖同样合并到 `APIWebSocketRoute`（`fastapi/routing.py:1425-1434`，E1/E4 已核）
  - C. 逐端点手写 `Depends`（36+2 处）— 缺点：漏一处即匿名端点，靠 review 保证
  - **缓存**：C1 无缓存每请求查库（5 秒上界零成本满足）vs C2 Redis 正缓存 TTL ≤ 5s + 撤销主动删 vs C3 进程内 LRU（K7 否决）
- **选定**：**B + C2**。缓存 key `oapi:cred:{sha256}`（值 = 最小载荷：`credential_id / tenant_id / subject_user_id / subject_kind / scopes / expires_at / resource_owner_user_id / subject_disabled`，**不 pickle `UserPayload`**）、TTL **3 秒**（AC 上界 5 秒的一半，多节点时钟差留余量）；撤销 / 编辑 / 停用 / 删除后按该主体名下密钥哈希**逐个 `adelete`**（DB 里有清单，不需要 `SCAN`）；`get_redis_client()` / `aget` / DB 任一异常 → **拒绝**（K2）。校验顺序固定为 PRD 附录 E.1：提取 Bearer → `bypass_tenant_filter()` 下按 `sha256(明文)` 查行 → 恒时比较（`hmac.compare_digest`，先例 `sso_sync/domain/services/hmac_auth.py:103`）→ 未撤销 → 未过期 → **按 `subject_kind` 分派主体解析器**（见下「主体解析器」）：`service_account` → 主体存在且 `user_type=='service'` 且伴生表 `disabled_at IS NULL ∧ deleted_at IS NULL` → 主体活跃租户（`UserTenant.status=='active' ∧ is_active==1`）== 密钥租户 → 回填缓存 → **每请求（含缓存命中）再做两项**：`expires_at` 与 `now` 比对（AC-05 在 TTL 窗口内到期也要拒）+ 租户禁用 / 归档黑名单 `DISABLED_TENANT_KEY`（`tenant/domain/services/tenant_service.py:44`，`aupdate_tenant_status :268-303` 对 `disabled` / `archived` 都写、恢复时删；Redis 异常按 K2 拒绝）→ **`set_current_tenant_id(密钥租户)`**（K9）+ `set_visible_tenant_ids(...)`（见下「可见租户」）→ **直接构造 `UserPayload(user_id, user_name, user_role=[], tenant_id, token_version=0, is_global_super=False)`**（`LoginUser` 是 pydantic 模型 `user/domain/services/auth.py:196`；**不调 `init_login_user`**——它无条件跑 `_check_is_global_super`（`auth.py:542-543 → utils/http_middleware.py:145-207`：Redis `user:{id}:is_super` + FGA `super_admin` Check + AdminRole 回落），既让每个 v2 请求多 1 次 Redis / 未命中时多 1 次 FGA，又把服务账号"永不超管"从结构性事实变成依赖 FGA tuple / AdminRole 数据状态；`role_ids=[]` 只能关掉 AdminRole 回落、关不掉 FGA Check。也不用 `init_login_user_sync :558-580`）→ 写 ContextVar `current_open_api_principal` → 权限位判定（见 D3）→ 身份传递头存在则 403（AC-33）→ 最后使用时间节流写（`SET NX EX 60` 闸 + 单行 UPDATE）。**残余的一次 FGA**：`resolve_permission_actor`（`permission/application/identity.py:19-38`）对非 Root 租户主体会调 `is_tenant_admin`（`relation_api.py:368-376`）——服务账号在子租户每次进 F048 判定多 1 次 FGA Check；能否成"租户管理员"由 D7 守 `grant_tenant_admin`（26022）保证，不改 `PermissionActor`（C4：permission 模块不认识业务主体）。
- **主体解析器（`subject_kind` 扩展点）**：`credential_validator` 内部维护 `SUBJECT_RESOLVERS: dict[str, SubjectResolver]`，F049 **只注册 `service_account`**；`hosted_app` 凭据（F055 签发）在 F049 期出现在 `/api/v2` 上时**因无解析器而按 `26002` 拒绝**——它的执行身份 / 租户 / `UserPayload` / `open_api_principal.subject_user_id` 取谁**随 F055 定义并注册**（候选：托管应用的 owner 自然人或应用专属服务账号，本文不预判）。F049 对 `hosted_app` 承诺的只有：`CredentialService.issue / revoke / update` 接受该 kind、`api_credential.subject_kind/subject_id` 能存、`open_api_subject(...)` 工厂在解析器注册后无需改动。
- **HTTP 错误形态**（K4）：新异常基类 `OpenApiAuthError(BaseErrorCode)` 携带 `http_status`；`main.py` 注册专属 handler：请求路径以 `/api/v2` 开头时 → `JSONResponse(status_code=http_status, content={status_code, status_message, data})`（信封形状不变，只把 HTTP 状态真实化）。**WS 分支**：`raise WebSocketException(code=1008, reason=str(错误码))`（Starlette `ExceptionMiddleware.websocket_exception` 在 accept 前 `close()` → uvicorn 403 拒握手，AC-31「优雅关闭」）；**禁止**在依赖里对 WS 抛 `HTTPException` / `BaseErrorCode.http_exception`（那正是今天助手 WS 裸崩的形态：HTTP 200 的 denial response，E1 §0-4）。**503 映射清单**（AC-34，统一用正名）：`PermissionServiceUnavailableError`（19002，`common/errcode/permission.py:15-17`；`PermissionFGAUnavailableError :21` 只是它的兼容别名，本文不再使用该名）与 `PermissionBackendUnavailableError`（19201，`common/errcode/tenant_fga.py:8`）两族在 `/api/v2` 上经同一 handler 返回 HTTP 503；本 Feature 自己的 `26030`（凭据校验依赖不可用）同样 503。
- **可见租户**：**复刻** JWT 用户的规则 `_compute_visible_tenant_ids`（`http_middleware.py:210-231`）：密钥租户 == 1 → `set_visible_tenant_ids({1})`；子租户 → `{leaf, 1}`（docstring `:216-222`："own leaf plus Root for shared resource visibility"——是子租户成员看 Root 下发共享资源的语义，与"在父租户导航"无关）。**必须由依赖自己 set**：`/api/v2` 上携带 `bs-sak-` 时中间件 `_apply_token_version_and_visible`（`:233-249`）因 subject 解不开直接 `return None`、不 set，`tenant_filter.py:172-197` 在 visible 为 None 时退回严格 `tenant_id == current` → 子租户服务账号将看不到 Root 共享的模型 / 知识库，而同租户自然人能看到，违反 AC-32「可见范围等于该主体的权限边界」。写路径与计数仍按既有 `strict_tenant_filter()` 约定；`super_admin` 结构性 False 故永不走 `None`（无过滤）分支。
- **WS 连接期失效**：握手校验 + 连接期 **watchdog**（端点内 `asyncio.create_task`，每 3 秒复查同一 Redis 键 / share_link 状态，失败即 `close(1008)`）——这样"后续调用 5 秒内被拒绝"对长连接同样成立，且不动 `common/chat/manager.py dispatch_client` 的按消息校验。
- **原因**：B 是唯一"零死角 + 拿得到路由元数据 + HTTP/WS 一份代码"的落点；A 已被 E1 证明拿不到 WS 依赖语义、C 靠人。缓存：F051 模型面 / F052 MCP 面是高频调用（每次校验若走 DB 是 4 次 SQL：凭据 / user / service_account / user_tenant），5 秒上界与 3 秒 TTL 兼容；命中路径的固定开销 = 1 次 Redis `GET`（凭据载荷）+ 1 次 Redis `GET`（租户黑名单），无 FGA。**K1「主动失效」的覆盖面如实划清**：撤销 / 编辑 / 停用 / 删除 / 批量撤销 / 主体删除 → 主动 `adelete` 缓存键；密钥**到期** → 不需主动失效（`expires_at` 在载荷内、每请求比对）；**租户禁用 / 归档** → 靠 `DISABLED_TENANT_KEY` 黑名单每请求查（租户模块已有的主动写入），不靠 TTL；TTL 只兜"多节点 Redis 删键与请求交错"的窗口。恒时比较与 fail-closed 姿势抄 `hmac_auth.py:58-109`，但**HTTP 状态语义别抄**（它抛 `HTTPException(19301)` 也被压成 200）。
- **何时该重新考虑**：Redis 可用性低于 DB（那时无缓存反而更稳，5 秒上界不受影响）；F051 压测显示 3 秒 TTL 命中率不足 → 提高 TTL 必须同时把主动删除的覆盖面（编辑 / 停用 / 删除 / 过期）重新审一遍；Starlette 升级改变 `WebSocketException` 处理路径。

### 决策 3（D3）：端点接入策略 = 两层：router 级依赖（凭据 + 租户 + 权限位）+ 端点级**权限位标记**（domain 级装饰器），不是逐端点 `Depends`

- **备选**：
  - A. baseline-recheck「两层改造」原案：router 级依赖只管"无凭据 401"，把解析出的身份写 ContextVar，再让 `open_endpoints/domain/utils.py` 三个函数改读 ContextVar → 34 端点零改动 — 缺点：`get_default_operator*` 随 AC-52 整体作废，"零改动"实际是"保留一个名不副实的函数"；权限位（AC-04 需指明缺哪一位）无处声明
  - B. 每个端点加 `login_user = Depends(require_scope("workflow:invoke"))` — 优点：显式；缺点：`open_endpoints/api/endpoints/*.py` 要 import `open_api/api/dependencies.py` → **RULE-5 违规**（API 层跨模块导入）；漏写一处即"有凭据但不判位"，只能靠测试兜
  - C. **端点级标记 + router 级统一判定**：`open_api/domain/scopes.py` 提供纯标记装饰器 `@open_api_scope("workflow:invoke", allow_share_token=False)`（写在端点函数上，只设属性、无 FastAPI 依赖）；router 级依赖读 `conn.scope["endpoint"]`（Starlette `Route.matches` 设置，`starlette/routing.py:263/348`）上的标记：**没有标记 → 拒绝（500 级 `26031` 未登记端点）**，有标记 → 按位判定；端点体里的身份取 `Depends(get_open_api_login_user)`（`open_endpoints/domain/utils.py` 内新函数，读 ContextVar；替换 **10 处** `Depends(get_default_operator_async)`——端点内 9 处（`citation.py:23` + `knowledge.py:21/42/65/90/111/136/162/188`）加 `open_endpoints/api/dependencies.py:63 get_knowledge_space_chat_service_for_openapi`（全仓无调用方 = 死代码，但该模块被 `endpoints/knowledge.py:11` import，删函数不删这处则**模块导入即失败**——随 AC-52 一并删除该死函数）——与 25 处内联调用）
- **选定**：**C**
- **原因**：C 对"漏标记"是**结构性 fail-closed**（router 依赖拒绝未登记端点），B 是漏一处即静默放宽；C 的标记留在端点旁、review 可见，且能承载 F050 的 `modes=("S","D")`；C 只让 v2 端点文件 import `bisheng.open_api.domain.scopes`（domain 级常量），RULE-5 不触发（它只拦 `bisheng.<mod>.api.` 导入）；router 级依赖的挂接点在 `bisheng/api/router.py:94`（全局路由文件，RULE-5 显式排除 `bisheng.api.`）。A 的三个函数中 `get_default_operator` / `get_default_operator_async` **删除**（AC-52），`resolve_operator(user_id)` 保留到 F050、改为：读 ContextVar 主体 → `user_id` 为空即返回主体；非空则 `aget_user` + `delete==0`（AC-39）+ 目标活跃租户 == 密钥租户（spec §3 跨租户组合一律拒绝）→ 否则 403。**注意 `flow.py:8` 从 `endpoints.assistant` 转导入 `get_default_operator`**（E1 §1.2）——删函数时一起改。
- **权限位 ↔ 端点映射**（38 个，B.1 口径；`OPEN_API_SCOPES` 常量同时给签发表单的悬停提示 AC-44 供数）：`workflow:invoke` = invoke / stop / WS chat（3）；`workflow:read` = `GET /flows/{id}`（1）；`assistant:invoke` = chat/completions / WS / `llm/workbench/asr` / `tts`（4）；`assistant:read` = list / info（2）；`knowledge:read` = `GET /filelib/`、`file/list`、`retrieve`、`download_statistic`、`detail_qa`、`query_qa`、`citation/{id}`（7）；`knowledge:write` = filelib 其余 13 个写端点 + `knowledge/*metadata*` 8 个（21）。合计 3+1+4+2+7+21 = **38** ✓。另加 `GET /api/v2/auth/whoami`（**新增**，只验密钥不判位，供 F053 `login` 与 114 手动验证；见 §6.1）——它**同样必须带标记**，写作 `@open_api_scope(None)`：router 级依赖的规则是「无标记 → 26031；标记 `scope=None` → 跳过位判定；标记有位 → 判位」，"无位"与"漏标"在结构上可区分。
- **完整性守卫**：单测枚举 `app.routes` 下所有 `/api/v2/**` 路由，断言每个都带标记，且标记的位 ∈ `OPEN_API_SCOPES` **或为 `None`**（`None` 只允许出现在显式白名单 `{"/api/v2/auth/whoami"}`，白名单增项要改测试）（AC-29 的机器化）。
- **随接入一并落地的两处既有缺陷（AC-37 / AC-40，此前只出现在测试清单）**：
  - **AC-37 未上线工作流 invoke 拒绝**：`open_endpoints/api/endpoints/workflow.py:43-49 invoke_workflow` 取到 `workflow_info` 后、构造 `RedisCallback` 之前加 `if workflow_info.status != FlowStatus.ONLINE.value: raise WorkflowOfflineError.http_exception()`（复用 `common/errcode/chat.py:29` 13010，已有三语；同一判据在 `common/chat/clients/workflow_client.py:98` 与 `workstation/api/endpoints/apps.py:161` 各有一份，v2 invoke 是唯一漏掉的入口）。`/workflow/stop` 不加（停一个未上线流的会话是幂等空操作）。
  - **AC-40 `download_statistic` 收口**：`filelib.py:496-507` 现状是接受调用方任意 `file_path`、只靠"后缀 `.log` + 目录名不含 `.` + 前缀 `/app/data`"三条字符串守卫读服务器文件，且**全仓无产出该类统计文件的代码**（grep `download_statistic` / `statistic` 只命中 ES 统计连接，无写盘方）——它事实上是"读 `/app/data` 下任意 `.log`"。改为：入参 `file_path` → `file_name`（`os.path.basename(file_name) == file_name` 且不含 `..`，否则 400 `ServerError`）；固定目录常量 `STATISTIC_DIR = <data_dir>/statistic`（`data_dir` 取既有配置根，不新增 Settings 键）；`os.path.realpath(join)` 必须以 `realpath(STATISTIC_DIR) + os.sep` 开头，否则 404；仍需 `knowledge:read`。契约变化（`file_path` → `file_name`）进发布说明与 `docs/api`（AC-54 同批）。
- **何时该重新考虑**：FastAPI / Starlette 不再在 scope 里暴露 `endpoint`（则退回 B 并补完整性测试）；F050 引入委托后如果"允许模式"需要按请求动态判定而非静态标记。

### 决策 4（D4）：6 个 `/chat/*` 端点的关闭方式 = **从 router 移除**（真 404），不留 410 桩

- **备选**：
  - A. 移除路由（不 `include_router(chat.py)`，删文件）→ Starlette 默认 404 `{"detail":"Not Found"}`（E1 已验证）
  - B. 保留路由、返回 410 + 发布说明链接（先例 `tenant/api/endpoints/tenant_users.py:57-73`，故意不挂鉴权依赖）
  - C. 保留路由、挂鉴权后返回 404
- **选定**：**A**
- **原因**：AC-30「端点不存在类响应、不执行任何业务逻辑」A 天然满足；B 需要在 `/api/v2` 下保留**不挂凭据依赖的路由**——与 AC-29「不存在绕过该路径的端点」相悖、且 D3 完整性测试要为它开例外；6 端点从未进过对外文档（PRD §4.6），发布说明逐个列出即可（AC-50）。`chat.py:7-9` 那行无用的 `a = WSGIMiddleware` 随文件删除。
- **何时该重新考虑**：升级后客户大量反馈"404 看不出为什么"→ 加 410 桩，但必须挂在凭据依赖**之后**（无凭据仍 401），并把它加进 D3 的标记完整性例外表。

### 决策 5（D5）：资源归属人落地 = 业务 Service 传 `owner_user_id`（创建关系落归属人）+ F048 runtime `authorize_created` 计划内追加**非 protected 回授行**（新 `source_type`）

- **备选**：
  - A. 只在 F048 adapter / runtime 层做（检测 actor 是服务账号 → owner 换成归属人 + 回授）— 缺点：业务行 creator 列（`knowledge.user_id`）仍硬写 `login_user.user_id`（`knowledge/domain/services/knowledge_service.py acreate_knowledge_base :795-799`、同步版 `create_knowledge_base :741-749`——**不是** `create_knowledge :674`，后者只是它们的上层入口），归属人的"我创建的"列表与创建人显示都不对；且 C4 禁止 permission 模块查 `user_type`，runtime 根本拿不到"actor 是服务账号"这个事实
  - B. 只在 v2 API 层做（端点里把 `login_user` 换成归属人再调 Service）— 缺点：**同时打破 AC-25 与定义 6 边界 c**——会话 / 审计 / 权限基准全变成归属人的（E2 §6 明确警告）
  - C. **业务 Service 加 `owner_user_id` 覆盖参数 + runtime 计划内回授（业务侧显式下令，runtime 不判主体类型）**：`login_user` / `actor` 仍是服务账号；业务 Service 判 `login_user.open_api_principal is not None and .subject_kind == 'service_account'` → 业务行 creator 列写 `principal.resource_owner_user_id`，并在权限记录上置 `creator_autogrant_user_id = login_user.user_id`；runtime `authorize_created`（`runtime.py:206-260`）**新增显式 kwarg `autogrant_user_id: int | None = None`**：非空时要求 `autogrant_user_id == actor.user_id ∧ != owner_user_id`（结构约束：只能"创建者把自己回授进来"，不能借此给第三方授权），把一条 `subject=user:{autogrant_user_id}`、`source_type=SERVICE_ACCOUNT_AUTOGRANT`、`protected=False`、档位 = 该资源类型可授档位中包含 `edit` 动作的最低档（经 Catalog 解析，不硬编码 `model_key`）的 assignee 行并入**同一份创建计划**
- **选定**：**C**
- **输入契约与进入点（把"runtime 怎么知道"写死）**：
  - `PermissionActor`（`permission/domain/services/permission_action_service.py:27-31`：只有 `user_id / current_tenant_id / super_admin / tenant_admin_tenant_ids`）与 `resolve_permission_actor`（`permission/application/identity.py:19-38`）**都不改、不读 `user_type`**（C4）。"是否回授、回授给谁"由业务层通过 record → adapter → runtime 的**显式参数**传入；runtime 只校验结构约束（同 actor、异 owner、资源版本 0）。
  - 进入点 = `authorize_created` 本身（不新开 `owner_grant` / `build_create_plan` 的旁路）：现状硬拒 `source_type != 'CREATOR' or not protected`（`:216-223`）保持不变——那两个参数描述的是 owner 行；回授行走新字段。`OwnerProjectionContext`（`permission/domain/services/owner_service.py:38-53`）加 `extra_grants / extra_deltas`（**不复用** `copy_grants / copy_deltas`：`_validate_copy :236-239` 对 `RESOURCE_CREATE` 见到 copy_* 即抛 `PermissionInvalidResourceError`，且 INHERIT 下拒绝），`project_created :113-166` 把 extra deltas 与 owner 的 protected deltas 一起进 `build_create_plan(protected_deltas=...)`（`resource_lifecycle_policy.py:93`，同一 plan / prepare / execute / finalize），`control_state._owner_projection_grants :956-963` 与 `_state.prepare / finalize` 把 extra grant 的 assignee 行一并落账本。幂等键不变（同资源同 owner 的重放得到同一计划）。
  - **只对 CUSTOM 起始模式的类型回授**：`knowledge_library / knowledge_space` 等 `FIXED_CUSTOM_TYPES` 起始 CUSTOM，回授行有效；`folder / knowledge_file`（`FLEXIBLE_MODE_TYPES`，`resource_lifecycle_policy.py:14`）起始 **INHERIT**，INHERIT 下非 protected 本地行被忽略 / 丢弃（`control_state.py:355 protected_only=normalized_mode=="INHERIT"`、`mode_service.py:72-76`）——服务账号对文件 / 文件夹的写权限**来自父库上的回授行或 DIRECT 行**（正是允许它上传的那条权限），因此文件 / 文件夹**只落 owner=归属人、不加回授行**；`authorize_created` 收到 `autogrant_user_id` 且目标起始模式为 INHERIT 时**忽略回授**（不报错，记 debug 日志），避免业务层逐类型判断。
- **v2 面创建 F048 资源的全部路径（必须全部经过接缝，漏一条即 AC-61 / AC-24 失守）**：
  1. `POST /filelib/` **type≠3** → `KnowledgeService.acreate_knowledge_base :795`（`db_knowledge.user_id = login_user.user_id :799`）→ `_project_library_created :212-223` → `_new_library_permission_record :194-208 owner_user_id=int(knowledge.user_id)`；同步版 `create_knowledge_base :741-749` 同改（`create_knowledge :674` 是其上层）。
  2. `POST /filelib/` **type=3（知识空间）** → `filelib.py:99-101` 走 `KnowledgeSpaceService.create_knowledge_space`（`knowledge/domain/services/knowledge_space_service.py:1100 user_id=self.login_user.user_id` → `:1110-1117 authorize_created(owner_user_id=int(knowledge_space.user_id))`）——**不经路径 1**，单独参数化。
  3. `POST /filelib/file/{knowledge_id}`（`filelib.py:338 aprocess_knowledge_file :1346`）与 `POST /filelib/chunks` / `chunks_string`（`:459 sync_process_knowledge_file :1375`）都进 `process_one_file :1483` → `KnowledgeFile(user_id=login_user.user_id :1544)` → `_project_library_file_created :257-268` → `_new_library_file_permission_record :242-254 owner_user_id=int(file.user_id)` → `knowledge_permission_service.py:995-1000 authorize_created(mode='INHERIT', protected=True)`；资源类型 `knowledge_file` / `folder` 均在 F048 registry（`api/services/f048_permission_runtime.py:171-195`）。此处 `KnowledgeFile.user_id` 写归属人（`updater_id` 保持服务账号），**不回授**（INHERIT，见上）。
  4. QA 问答对（`add_qa` 等）与 `knowledge/*metadata*` 不是 F048 资源，不经接缝。
  §4.3 模块表相应扩到 `knowledge_space_service.py` 与 `process_one_file`。
- **原因**：runtime 已把 `owner_user_id` 与 `actor` 分离（E2 §0），业务侧只差把硬写处参数化；回授行必须**非 protected**（受保护源不可经 `mutate` 移除，`grant_service.py:308/326`，与 AC-63「可单条撤销」冲突）且必须有**可识别的新 `source_type`**（复用 `DIRECT` 则「全部撤销」分不出回授，AC-63 失效；`OTHER` 不校验 subject 类型且语义模糊）。新增来源值要同步 `SOURCE_TYPES`（`permission/domain/services/grant_source_service.py:16-26`）、`_validate_source_subject`（`:178`，允许 `user`）、`_source_locator`（`:193`）；`f048_mode_mapper.py:80` 与 `control_state.py:379` 对非 `CREATOR/SYSTEM` 源按普通源处理，与"可单条撤销"一致。回授行进创建计划而非事后 `mutate`：失败即整个创建 `FAILED_CLOSED`（`permission/domain/models/grant.py:26-31`）而不是"资源建成但集成写不进"的半成品。（原句"v2 面本期能创建的 F048 资源只有知识库"**已订正**：知识空间与文件 / 文件夹两条投影路径同样存在，见上「全部路径」清单。）
- **何时该重新考虑**：F050 模式 D 上线（"一次调用两者并存以被代表用户为准"，AC-46 归 F050，同一接缝加分支）；F054 `app` 类型注册后若 CLI `deploy` 走同一 runtime 创建 → 复用本接缝（`app` owner = 归属人，PRD-1 DEV-01 ④）。

### 决策 6（D6）：主体侧授权页反查 = SQL 反查 `permission_grant_assignee`（`permission.application` 新只读 API）+ 来源列取值映射；写路径复用 runtime 但**不复用资源侧 HTTP 端点**

- **备选**：
  - A. OpenFGA ListObjects — 被 `DenyListObjectsPolicy`（`permission/application/sql_runtime.py:638`，装配 `runtime.py:1113`）显式禁用
  - B. 服务账号模块自建"授权镜像表" — 双份真相
  - C. **`permission.application` 增只读 `subject_api.list_subject_grants(subject_type='user', subject_id, tenant_id, resource_type?, cursor)`**：`SELECT ... FROM permission_grant_assignee a JOIN permission_grant g WHERE a.subject_type='user' AND a.subject_id=:sa AND a.state='ACTIVE'`（命中 `ix_perm_assignee_subject_state`，`tenant_id` 由自动过滤注入），资源名水合走 registry 白名单（`api/services/f048_permission_runtime.py:171-195`，**不照抄前端 union**——它含未注册的 `linsight_skill`）；来源列：`DIRECT` → 「管理员授予」、`SERVICE_ACCOUNT_AUTOGRANT` → 「创建时自动回授」、其它（`CREATOR` / `DEPARTMENT` / …）→ 标「异常来源」并进日志（AC-61：出现即缺陷）
  - **写路径**：W1 前端直接调既有 `POST /api/v1/permissions/resources/{t}/{id}/grants:mutate`（PRD 附录 E.4 原案）vs W2 **服务账号模块新端点 `POST /api/v1/service-accounts/{id}/grants:mutate`**（校验管理员 + 服务账号存在 → 逐资源取 context → 调同一 `resource_api.mutate_grants` / runtime，携带 `allow_service_account_subject=True`）
- **选定**：**C + W2**
- **原因**：C4 要求 Grant 变更只经 F048 runtime 且先落账本——W2 仍经同一 runtime，只是 HTTP 入口不同；选 W2 是因为 D7 要在 `canonical_source`（`f048_permission_subject.py:68-71`）拒绝服务账号主体以硬保证 INV-29「授权只走主体侧」（否则绕开界面直接 POST 资源侧端点仍能把服务账号授进去，E2 §1.4）——那么资源侧端点必须拒绝、主体侧端点必须放行，靠一个 application 层显式参数区分。N 个资源 = N 次 mutate、逐条反馈、不做事务（PRD E.4）；管理员对目标资源无需另持权限（`_system_authorized`，`runtime.py:1077-1083`）。「全部撤销」= 反查后过滤掉 `SERVICE_ACCOUNT_AUTOGRANT` 再逐条 REMOVE（AC-63）；单条撤销回授项需前端二次确认文案。删除服务账号 = 先反查、逐资源 REMOVE、再撤销密钥、再置 `deleted_at`（assignee 外键 `ondelete=RESTRICT` 指向 grant 而非主体，删用户行不会级联，`grant.py:137`）。
- **何时该重新考虑**：F048 引入按主体的 ListObjects 或专门的主体侧 API；资源类型超过两位数导致名称水合退化为 N 次查询（那时在反查 SQL 里 join 各业务表或加缓存）。

### 决策 7（D7）：服务账号选人排除 = DAO 默认参数（fail-safe 方向）+ 授权候选查询同步过滤 + 授权主体校验层拒绝

- **备选**：
  - A. 接口层 opt-in 参数（`/user/list?exclude_service=true`）— 漏传即泄漏，方向反了
  - B. 只在前端过滤 — 直接调接口即泄漏
  - C. **数据访问层默认排除**：`UserDao._filter_users_statement`（`user/domain/models/user.py:259-264`）增 `user_type: str | None = "human"` 默认参数（覆盖 `filter_users :267` / `afilter_users :279` → `/user/list` 全部 8 处 platform 消费点，E2 §1.3）；`grant_subject_service.list_candidate_users`（`permission/domain/services/grant_subject_service.py:70-121`，条件在 `:90`）同步加 `User.user_type=='human'`（两个前端资源侧授权弹窗的独立查询，**不走 `/user/list`**）；`department_service` 全局成员搜索（`department/domain/services/department_service.py:2255-2330`，JOIN 主部门、SA 结构性不命中）也显式加条件作纵深；`f048_permission_subject.canonical_source`（`:68-71`）对 `user` 主体查到 `user_type=='service'` 时**拒绝**，除非 mutate 上下文带 `allow_service_account_subject=True`（D6 W2）；`aget_user_by_ids`（`:184`，已授权对象名称水合）**保持不过滤**（AC-16 可显示不可选）
- **选定**：**C**
- **原因**：PRD §4.5 成本 3「漏传的后果是看不到而非泄漏」；E2 已核实两条查询路径都只查 `delete==0`；`display_names`（`f048_permission_subject.py:110`）走 `aget_user_by_ids` 不经统一过滤，AC-16「可显示」天然满足。管理接口层拒绝（AC-22）另加共享断言 `assert_natural_persons(user_ids)`（放 `user/domain/services/`），在 `/user/role_add`（`user/api/user.py:874-965`）、部门加成员 `aadd_members`（`department_service.py:1749`）、部门管理员 `aset_admins`（`:1986`）、用户组 `replace_user_groups` / `set_group_admin` / `set_group_members`（`api/services/role_group_service.py:175/238/271`）、租户管理员 `grant_tenant_admin`（`tenant/domain/services/tenant_admin_service.py:37-58`）、`/user/update`（`user/api/user.py:663-724`，含 `:709` 直写 `delete` 位）、**管理员改密 `/user/reset_password`**（`user/api/user.py:1032-1066`，按 `user_id` 直改密码——AC-20「改密」在 D10 26022 清单里，此前漏列入口）入口调用——这些是"主动加入 / 主动改写"，DAO 过滤兜不住直接 POST。`/user/change_password`（`:1067`，改自己）与 `change_password_public`（`:1095`，按 `external_id`）对服务账号结构性不可达（不能登录 / `external_id=NULL`），不加断言。
- **何时该重新考虑**：出现合法的"要看到服务账号"的人向场景（目前无；审计筛选 `search_user_by_name :296` 按名筛会话日志属另一路径、不受影响）。

### 决策 8（D8）：share-token 通道 = 分享创建者为执行主体 + WS 双凭据并存 + `share_link` 加 `share_scope` 列 + 三个 share-link 作用域 HTTP 端点 + 撤销 / 有效期

- **事实修正（★ 需回写 spec 决议-1——已在修订历史「需回写上游」登记，tasks 前须与用户确认；不改 AC 文字，但改其解释基础）**：spec 决议-1「实际受影响面只有两个 WS」的核实基础已过时；本设计新增 3 个 `/api/v1/share-link/{token}/*` 端点、`share_scope` 列与"应用级分享必填有效期"，AC-55–58 只写了 WS，应补一句"guest 页的信息 / 历史 / 标题读取经 share-link 作用域端点"。另 AC-55「仅限该分享所指向的单一资源」在 history 端点上按「资源 = flow」解释（同 flow 下任意 chat_id 可读，与今日 v2 history 完全匿名相比已是收窄；逐访客绑定等 F050 分区键）——此口径也随本项一并回写。两个免登录分享页**已不在 platform**（`chatShare.tsx` / `chatAssitantShare.tsx` / `platform/routes/index.tsx:24-25` 随 `36beaa00f` 删除，**已失效**），真身是 client `pages/standaloneChat/StandaloneChatPage.tsx`（guest → `apiVersion='v2'` `:82`；路由 `client/routes/index.tsx:264-265`，AuthLayout 之外）；它除 2 个 WS（`pages/appChat/useChatHelpers.ts:35-36`）外还打 4 个 v2 HTTP：`GET /flows/{id}`（`client/api/apps.ts:39`）、`GET /assistant/info/{id}`（`:64`）、**`GET /chat/history`**（`:133`）、**`POST /chat/gen_title`**（`api/chat/api-endpoints.ts:51` / `useWebsocket.ts:82`）——后两个在 AC-30 关闭清单里。
- **备选**：
  - A. share-token 通行 v2 上述 4 个 HTTP 端点（保留 history / gen_title 的 share-token 版）— 与 AC-30 / INV-27「靠关闭解决」冲突，且 v2 HTTP 面出现第二种凭据
  - B. guest 页改打 v1 同名端点（已接受 `share-token` 头：`api/v1/flows.py:20-24`、`api/v1/assistant.py:71-74`、`chat_session/api/endpoints/chat.py:53`）并把它们的 `Depends(get_login_user)` 放宽成"登录或有效 share-token" — 给 v1 三个端点新增匿名模式，扩大前端面攻击面
  - C. **share-token 只在两处出现**：① 两个 WS（查询参数 `?share_token=`，spec §3 明示允许）；② `share_link` 模块自己的**匿名**作用域端点（前缀在 `TENANT_CHECK_EXEMPT_PATHS`，`http_middleware.py:39`——匿名端点正需要它）：`GET /api/v1/share-link/{token}/resource`（按 `resource_type` 返回工作流或助手信息）、`GET /api/v1/share-link/{token}/chat/history?chat_id=`、`POST /api/v1/share-link/{token}/chat/gen_title` — v2 HTTP 面保持"只有 `bs-sak-`"
  - **登录态管理端点的落点**（撤销 / 列表）：`TENANT_CHECK_EXEMPT_PATHS` 是 `startswith` 前缀匹配（`http_middleware.py:311`），命中后**整条调用链 `_bypass_tenant_filter=True`、跳过 token_version 校验、跳过租户禁用检查**（`:322-343`）——任何以 `/api/v1/share-link` 开头的路径（含 `/share-links`、`/share-link-admin`）都会被豁免。因此撤销 / 列表**不能**放在该前缀下（列表会在 bypass 下跨租户可见），改挂**新的非豁免前缀 `/api/v1/app-shares`**：`GET /api/v1/app-shares?resource_type&resource_id`、`POST /api/v1/app-shares/{id}/revoke`（`share_link/api/endpoints/share_link_manage.py`，`Depends(get_login_user)`，租户自动过滤 + token_version + 租户状态检查全部生效）。既有 `POST /api/v1/share-link/generate_share_link`（`share_link.py:12-17`，登录态）**本就**落在豁免前缀下运行于 bypass、无 token_version 校验——属既有暴露，F049 不搬它（生成 `share_scope='app'` 仍复用它，service 内显式 `tenant_id = login_user.tenant_id`），登记为坑 26。
  - **资源类型表达**：R1 给 `ResourceTypeEnum` 加 `workflow_app / assistant_app`（`SQLEnum` → MySQL 原生 ENUM 要 Alembic ALTER，K5 反例）vs R2 **加列 `share_scope VARCHAR(16) server_default 'session'`**（`app` = 本 Feature 的应用级分享，`resource_id` = flow id）。**现状如实**：`ShareChat.tsx:59` 生成的 `workflow` / `assistant` 行 `resource_id` 是会话 id，**6 个**消费点按 `resource_id == session/chat id` 校验（`workstation/api/endpoints/chat.py:57,81`、`chat_session/api/endpoints/chat.py:59`、`linsight/api/endpoints/linsight.py:152,554,620`）；但另有 **2 个 flow 级消费点**已承认"`resource_id` 即 flow id"这一形状（`api/services/flow.py:236-246`、`api/services/assistant.py:293-303`：`meta_data.flowId` 优先、否则 `resource_id` 当 flow id，注释明写 direct flow shares）。所以"语义已被占用"只对 6 个会话级消费点成立，R2 加列的理由是**同一行同时被两种口径读**、必须有一列把它们分开，而不是"不能复用"。D8 落地后这 2 处 flow 级消费点**逻辑不改**（`app` 行 `resource_id` 即 flow id，与其兜底分支天然一致），只在注释登记 `share_scope` 语义；6 个会话级消费点也不改（`session` 行行为不变）。
- **选定**：**C + R2**。执行主体（AC-58）：以创建者构造 `UserPayload`（同 D2，直接构造、`is_global_super=False`、`user_role=[]`，**不**调 `init_login_user`——分享创建者若是超管，guest 会话也不应继承超管短路），创建者已禁用 / 已删除或租户不活跃 → 拒绝（fail-closed）；`set_current_tenant_id(share.tenant_id)`；WS 路径参数 `workflow_id` / `assistant_id` 必须 == `share.resource_id` 且 `share_scope=='app'`（AC-55 单一资源）；`ContextVar` 主体标记 `subject_kind='share_link'` + `share_link_id`；F048 `use` 校验仍以创建者为 actor（`common/chat/manager.py:195-208` 每条消息的既有校验保留）。撤销：`POST /api/v1/app-shares/{id}/revoke`（登录 + 创建者或管理员；非豁免前缀，见备选段）写 `status=INACTIVE`（读侧 `get_share_link_by_token :57-58` 已按 `status != ACTIVE` 拒绝，写入端点从此存在、枚举不再"死"）；有效期：`expire_time` 语义**定为"自 `create_time` 起的相对秒数，0 = 永不"**，`get_share_link_by_token` 统一强制（`:52-56` 注释删除），应用级分享生成时 `expire_time` **必填 > 0**（platform `NoLoginLink` 默认 30 天），会话级分享保持 0 兼容；`access_count` 不动。撤销 / 过期对**新建连接**立即生效（无缓存），对已建立的 WS 靠 D2 watchdog（≤ 5 秒）。前端：platform `ChatLink.tsx:77-81` 的免登录 URL 改为 `${origin}${BASE_URL}/workspace/chat/{flow|assistant}/{id}?share_token=…`（新增 platform `controllers/API/shareLink.ts`：生成 / 列表 / 撤销）；client guest 页从 query 取 token，`useChatHelpers.ts:23-40` 拼 WS URL 时带 `share_token`，`api/apps.ts` 三处与 `api-endpoints.ts:51` 改打 share-link 作用域端点。
- **原因**：C 让"v2 HTTP = 密钥、WS = 密钥 ∪ share-token、share-link 模块 = share-token"三个面各自单一；A 违反 INV-27；B 改 v1 语义。R2 比 R1 便宜且双库安全（加列 + `server_default` 是 revision 允许的唯一数据效果）。执行主体取创建者与「分享 = 分享者把自己的应用开放给匿名访客」一致（spec 决议-6 i），且比现状（固定配置身份）收窄。
- **已知代价（如实登记）**：guest 会话的 `MessageSession.user_id` = 分享创建者 → **会出现在创建者的工作台会话列表**（`workstation/api/endpoints/apps.py:196-202` 按 `user_ids=[login_user.user_id]`）；现状是落在 `default_operator` 名下（同样"串"，只是串给了别人）。缓解：本期 `MessageSession` 不加列（F050 才加分区键 `external_user_id`、只写不读，memory 已定），F050 / F058 落地时用 `share_link_id` 作分区值把 guest 会话从创建者列表里摘出——列入 §8。history 端点只校验 `session.flow_id == share.resource_id`（chat_id 是 128 位随机、当前 v2 history 本就完全匿名），逐访客绑定同样等分区键。
- **何时该重新考虑**：F050 分区键落地（则 history 按 `share_link_id` 收窄、会话列表摘除）；产品决定分享页需要登录（则整条通道退役）；出现服务端集成用 WS 的证据（E1 §7 未找到 WS 出现在 platform API 接入文档中）——不影响双凭据并存，只影响文档。

### 决策 9（D9）：权限位清单 = 代码常量注册表；开放能力层开关 = 进程级 Settings 三段式；`chat:invoke` 登记为「端点待开放」位、`delegate` 本期不登记

- **备选**：
  - A. 权限位存表（可运营配置）— 运行期消费者（F051–F053）按常量判位，表只会漂移
  - B. **`open_api/domain/scopes.py` `OPEN_API_SCOPES`**：每位 = `code / group / label_key / desc_key / endpoints[] / requires_open_platform`；三扩展位 `model:invoke` / `identity:read` / `app:manage` `requires_open_platform=True`、组 `local_dev_toolkit`
  - 开关：S1 DB 热配置（`initdb_config`，100s TTL）vs S2 **`core/config/open_platform.py OpenPlatformConf(enabled: bool = False)` → `Settings.open_platform`（`core/config/settings.py:782` `multi_tenant` 旁）→ `config.yaml` `open_platform: enabled:` → `api/v1/endpoints.py:60-108 get_env` 增 `open_platform_enabled` → platform `contexts/locationContext.tsx:75-94` 增 `appConfig.openPlatformEnabled`**；后端签发 / 编辑校验直接读 `settings.open_platform.enabled`，未部署时三位入参 → `26023`；F054 的「工场运行时层开关」是同形态兄弟键、不合并
  - `chat:invoke`：**按 spec「本次纳入」口径登记**（spec 范围边界明写权限位清单含 `chat:invoke`，「开放前签发表单对该位以说明标注『端点随后续版本开放』、其余行为同普通位」；决议-6 f 只裁决了 `delegate`，未推及 `chat:invoke`——本文初版把它踢出注册表属未经再确认的推翻，**已撤回**）：`OPEN_API_SCOPES` 中 `code='chat:invoke'`、`group='assistant'`、`endpoints=()`、`pending_note_key`（三语「端点随后续版本开放」）；签发 / 编辑可勾、持久化、`whoami` 原样返回；D3 完整性测试对该位的约束是"允许注册表里有位而无端点"（反向：端点标了注册表没有的位才失败）；F058 落端点时只需给端点加标记 + 清 `pending_note_key`。
  - `delegate`（F050）：本期**不进注册表、不进表单**（AC-14；入参 → `26024`「委托能力尚未启用」）——决议-6 f 判据："管理员能勾一个什么都不做的位"是负资产；`chat:invoke` 不适用该判据，因为 spec 已把它定为「有说明的待开放位」而非「什么都不做」。
- **选定**：**B + S2 + `chat:invoke` 登记 / `delegate` 不登记**
- **原因**：先例 `multi_tenant.enabled` 就是这条三段式（E1 §3）；开关是部署形态不是租户偏好；`load_settings_from_yaml`（`common/services/config_service.py:91-107`）对未知顶层键 `KeyError` 拒启 → **先发代码再加 yaml 键**（114 部署顺序坑，§5）。
- **何时该重新考虑**：F058 落端点 → 给端点加标记并清 `pending_note_key`（常量已在）；产品要求运营期按租户开关能力 → 那是另一层（租户级配额 / 能力总线），不动本开关。

### 决策 10（D10）：错误码 = 260 段落码 `common/errcode/open_api.py` + constitution C5 同改动回写；开放面 / 管理面分号段

- **备选**：全部塞 26001–26016 vs **开放面用附录 C 编号、管理面另起 26020+**（同一模块 260，`EE` 到 99）
- **选定**：后者。本期启用：`26001` 缺少 / 格式非法（401）、`26002` 无效 / 已撤销 / 已过期（401）、`26003` 缺权限位（403，`data.required` 指明缺哪位）、`26004` 身份传递能力尚未启用（403；本期任何 `X-Bisheng-On-Behalf-Of` / `X-Bisheng-End-User` 头一律触发，F050 收窄其语义为"未授予委托 / 不在范围"）、`26012` 服务账号禁止登录（403；登录守卫用。**落地形态必须是 `raise`，不能是 `return` 一个 26012 响应**：`_reject_login_if_user_has_no_usable_access` 是"返回响应对象"式守卫（`user/domain/services/user.py:373-379`），其调用方 `tenant_service.py:663-665` / `login_sync_service.py:228-230` 的映射是 `if guard.status_code == UserNoRoleForLoginError.Code: raise UserNoRoleForLoginError() else: raise UserNoWebMenuForLoginError()`——即 `UserNoRoleForLoginError` 原样透传、**其它任何返回码（含 26012）都被压成「无菜单」**。所以服务账号分支不走返回值通道，直接 `raise`，四个入口的异常路径都原样透传）；管理面草案：`26020` 服务账号不存在、`26021` 资源归属人须为本租户已启用自然人、`26022` 对服务账号禁止的操作（改密 / 启停登录 / 授角色 / 加组 / 加部门 / 租户管理员）、`26023` 扩展位未部署、`26024` 委托能力尚未启用、`26025` 未知权限位、`26026` 密钥不存在或不属于该账号、`26027` 服务账号已停用 / 已删除、`26028` 分享链接无效 / 已撤销 / 已过期（WS 与 share-link 端点）、`26029` 服务账号不能作为资源侧授权主体、`26030` 凭据校验依赖不可用（503，Redis / DB 抖动 fail-closed）、`26031` 端点未登记权限位（500，D3 完整性兜底）。`26013 / 26014` 不复用；`26005–26007 / 26010 / 26016` 随 F050。**信封形状**：`{status_code, status_message, data}`（与平台一致），差别只在 v2 面 HTTP 状态真实（D2）。
- **原因**：C5；E1 重跑登记命令确认 260 空；三语文案只落 `packages/locales/src/api_errors/{zh-Hans,en,ja}.json`（K12）。
- **何时该重新考虑**：F050 / F058 落码时若与草案号冲突以先落码者为准并回写此表。

### 决策 11（D11）：审计 = `AuditLogDao.ainsert_v2` + `open_api.*` 命名空间 + 四处 lockstep；HTTP 逐调用审计不进本期

- **备选**：新建独立审计表 vs **复用审计 v2 结构化字段**（`database/models/audit_log.py:117-158`：`action` String(64) / `target_type` / `target_id` / `metadata`）
- **选定**：复用。事件（AC-12 / 65 / 58）：`open_api.service_account.{create,update,enable,disable,delete}`、`open_api.api_key.{issue,update,revoke,revoke_all,expire,invalidate_by_subject}`（`metadata` 含掩码 / 权限位 / 触发原因；**明文永不出现**）、`open_api.grant.{add,update,remove,remove_all}`（含前后档位）、`open_api.share_link.{revoke,expire}`、`open_api.ws.connect`（每次 WS 建连一条：凭据种类、密钥 id 或 share_link id、执行主体、资源；AC-58 的"审计记录 share-token 标识与分享创建者"落此）。`operator_id=0` 时 DAO 自动 `operator_name='system'`（`:387-402`）——到期 / 主体停用触发的失效事件用它。**到期事件的触发者（AC-12「到期自动失效」；过期在 D2 是被动判据，需要有人写 `revoke_reason='expired'` 与审计）——双通道、同一幂等闸**：① **惰性**：凭据校验判到 `expires_at <= now` 拒绝时，附带一条单行 `UPDATE api_credential SET revoke_reason='expired' WHERE id=:id AND revoke_reason IS NULL`（`revoked_at` **保持 NULL**，让"到期"与"人工撤销"在列上可区分；K3 有效性判据不受影响），`rowcount==1` 才写审计 `open_api.api_key.expire`（多节点并发下只有一个赢，天然去重）；② **兜底**：Celery Beat 任务 `bisheng.worker.open_api.tasks.expire_credentials`（默认队列，每小时；`Settings.celery_task.beat_schedule` 缺省注入，先例 `core/config/settings.py:176-189`）在 `bypass_tenant_filter()` 下枚举 `expires_at <= now AND revoke_reason IS NULL`，逐行 `set_current_tenant_id(row.tenant_id)` 后做同一条单行 UPDATE + 审计（backend AGENTS.md「Beat × 多租户」陷阱：跨租户枚举查询在 bypass 内、写入按行切租户；同 `worker/tenant_reconcile/tasks.py:55-80` 写法）——覆盖"到期后再没人调用"的密钥。114 若未起 Beat（memory：默认 worker / Beat 曾缺）惰性通道仍保证被拒时有记录；列表页「已过期」状态按 `expires_at` 现算，不等审计。**四处 lockstep**（E1 §5.2）：后端 `_UI_VISIBLE_V2_ACTIONS`（`audit_log.py:178-201`）+ `_V2_NAMESPACE_TO_ACTION_PREFIX`（`:207-211`，加 `open_api.`）；前端 `platform/controllers/API/log.ts` `actions :53-108` 与 `getModulesApi :35-51`；i18n `bs.json` `log.systemIdEnum` / `log.eventTypeEnum` 三语。**HTTP 逐调用审计**（PRD §4.8.1 R7）本期只落结构化日志行 `open_api.call`（key_id / subject / endpoint / status / latency），审计表化随 F050 双归属一并做。
- **何时该重新考虑**：F050 落审计双归属时统一升级为表记录；审计量级让 `audit_log` 单表承压（那时按月分区或专表）。

### 决策 12（D12）：`default_operator` / `enable_guest_access` 移除与 6 端点删除的对外表现

- **备选**：A. 保留键但 no-op + 启动告警；B. 发现残留键即拒绝启动；C. **删 yaml 键（`initdb_config.yaml:35-38`）+ 删全部读取点（后端 `open_endpoints/domain/utils.py:36/59`、`assistant.py:264/284`、`flow.py:21`、`chat.py:87` 随文件删；前端 i18n `api.noLoginLinkDescription` 三语 + `ChatLink.tsx:106-108`；`docs/api/filelib-retrieve.md:25-28/297-298` 两处错误引导；`ApiAccess.tsx:57-58` 示例 `api_key="empty"` → `bs-sak-…`；测试注释 `test/e2e/test_e2e_knowledge_resource_unified.py:4`）**
- **选定**：**C**。对外表现：存量 DB `config` 表里残留键**无害**（`get_from_db` 缺消费者、`merge_old_config :301-313` 只合并新键），不写清理脚本（AC-51 零迁移）；`GET /assistant/info`、`/assistant/list`、`GET /flows/{id}` 从"guest 开关 + 固定身份"变为"密钥 + `assistant:read` / `workflow:read`"，guest 分享页改走 D8；6 端点真 404；无密钥调用一律 401（AC-50）。发布说明四项由 tasks 交付。
- **原因**：A 正是 PRD §4.9 否决的"死配置误导运维"；B 拿 DB 键做启动闸没有意义（它不是 Settings 顶层键，`load_settings_from_yaml` 根本不看它）。
- **何时该重新考虑**：只有 PRD §4.9「平台侧零迁移 / 无兼容窗口」决议本身被产品推翻（INV-27 改写）时；否则不变。

### 决策 13（D13）：MVP-114 首波边界 = "建号 → 签发 → whoami → `app:manage` 判定"纵切 + 结构性封口；既有 v2 面收口整体排第二波（tasks 里以 `[MVP-114]` 排最前）

- **备选**：
  - A. 按模块顺序（先做完全部 v2 端点接入再做管理界面）— 纵切剧本步 1–2（`mvp-114-path.md`）在 v2 接入完成前无法演示，且 F053 / F055 首波拿不到 `Depends` 工厂
  - B. 只做能演示的最小面、其余"以后再说" — 首波部署到 114 后存在"服务账号可被资源侧授权 / 可被选人"的空窗，INV-29 在开发环境就先破
  - C. **纵切 + 结构性封口先行**：首波交付纵切所需件 + 所有"不做就会在 114 留下漏洞"的结构性拒绝（选人 DAO 排除、资源侧授权主体拒绝、登录守卫），把"既有 v2 面 36+2 端点收口"整体推到第二波
- **选定**：**C**
- **首波（Wave 1）**：`open_api` 模块骨架 + `api_credential` / `service_account` 表 + `user.user_type` 迁移 + 凭据服务（生成 / 哈希 / 掩码 / 有效性 / 软撤销 / 批量撤销 / 缓存与主动失效 / 最后使用节流 / 到期惰性记录）+ **router 级依赖与 `Depends` 工厂**（可挂在 F053 / F055 新 router 上）+ `OPEN_API_SCOPES`（含三扩展位与 `chat:invoke` 待开放位）+ `open_platform` 开关三段式 + `GET /api/v2/auth/whoami` + 服务账号 CRUD / 启停 / 删除 + 登录公共守卫 + **三处结构性封口**：`/user/list` DAO 排除、`grant_subject_service.list_candidate_users` 过滤、`canonical_source` 拒绝服务账号主体（D7 前三项）——有它们在，Wave 1 期间服务账号名下**结构性不可能**出现任何授权行（主体侧入口未建、资源侧被拒、D5 接缝未开），因此 **Wave 1 的删除 = 撤销全部密钥 + 置 `deleted_at` + 审计，无需反查 REMOVE**；`26012 / 2600x` 错误码与三语 + platform 「服务账号」tab（列表 / 新建 / 详情概览 / API 密钥 tab：签发 / 编辑 / 撤销 / 批量撤销 / 一次性展示）+ 审计事件（账号 / 密钥两族）。
- **第二波（Wave 2，release 必做）**：38 端点标记接入 + 6 端点删除 + `get_default_operator*` 删除 + `resolve_operator` 收紧 + WS 双凭据 + watchdog + share-link 撤销 / 有效期 / `share_scope` / 三个作用域端点 + `/app-shares` 管理端点 + platform `ChatLink` 与 client guest 页改造 + 「资源授权」tab（`subject_api.list_subject_grants` 反查 / 授予 / 撤销 / 全部撤销 / AC-64 提示）+ **删除流程升级为"反查 → 逐资源 REMOVE → 撤销密钥 → 置 `deleted_at`"且删除弹窗按 AC-48 列全部授权（含回授项）** + D5 回授接缝（三条创建路径）+ AC-37 / 38 / 39 / 40 四处缺陷修复 + `default_operator` / `enable_guest_access` 移除与文档 + 对账豁免与配额排除 + 管理接口拒绝（AC-22 矩阵其余项）+ 到期 Beat 兜底任务 + 授权页 / share-link / WS 审计事件 + 前端 `ApiAccessFlow.tsx` i18n 偿债。
- **原因**：纵切剧本步 1–2 只需要"建号 → 签发 → CLI 用密钥 login（`whoami`）→ `app:manage` 判定"；三处封口成本极低（各一行条件 + 一个显式参数）却让 Wave 1 的删除语义自洽、INV-29 在 114 上不留空窗；Wave 2 全部是既有 v2 面的收口，与纵切正交但 INV-27 要求发版前必做。
- **何时该重新考虑**：F053 / F055 首波提前需要 `resource_owner_user_id`（deploy 的 owner）→ 已在 Wave 1（伴生表字段随建号即有）；不需要调整。

---

## 4. 系统现状（接手必读；实现后按现状覆盖）

### 4.1 数据流

**A. 管理面（platform，`/api/v1`，JWT cookie）**

`租户管理员进 /sys「服务账号」tab → POST /api/v1/service-accounts（名称 / 描述 / 资源归属人）→ ServiceAccountService.create：校验归属人为本租户已启用自然人（26021）→ 单个 async session 内 add(user: user_type='service', source='service_account', external_id=NULL, password=哨兵) → flush 取 user_id → add(service_account: tenant_id 取管理员当前租户 / admin-scope) → add(user_tenant: status='active' ∧ is_active=1) → 一次 commit（D1「建号事务」；不调 UserDao.create_user / aactivate_user_tenant）→ commit 后审计 open_api.service_account.create → 前端直达详情·API 密钥并打开签发表单（AC-43）→ POST /api/v1/service-accounts/{id}/keys（名称 / 权限位 / 过期）→ CredentialService.issue：secrets.token_urlsafe(32) → 明文 = 'bs-sak-' + 43 字符 → sha256 → 写 api_credential（tenant_id / subject_kind='service_account' / subject_id / key_prefix / last4 / token_hash / scopes / expires_at）→ 响应一次性返回明文 → 审计 open_api.api_key.issue → 前端 KeyRevealDialog（复制 + 「我已保存」）`

**B. 开放面（`/api/v2`，Bearer）**

`调用方 Authorization: Bearer bs-sak-… → HTTP 中间件（读 Bearer、JWT 解不开、预种租户 1、放行）→ router 级 verify_open_api_access（open_api/api/dependencies.py，挂在 api/router.py:94）：Redis oapi:cred:{sha256} 命中？否 → bypass_tenant_filter 下查 api_credential + 主体 + 租户 → 恒时比较 / 未撤销 / 未过期 / 主体活跃 / 租户一致 → 回填缓存 TTL 3s → 每请求：expires_at 比对 + DISABLED_TENANT_KEY 黑名单 → set_current_tenant_id(密钥租户) + set_visible_tenant_ids({leaf,1} / {1}) → 直接构造 UserPayload（is_global_super=False, user_role=[]）→ ContextVar 主体 → 读 conn.scope['endpoint'] 上的 @open_api_scope 标记 → 缺位 26003 / 无标记 26031 → 身份头存在 26004 → 最后使用节流写 → 端点体 Depends(get_open_api_login_user) 取身份 → 业务 Service → F048 require/check_business_action（资源级，失败回业务既有错误码，与 26003 可区分 AC-36；FGA 不可用 → 503 AC-34）→ 创建类端点经 D5 接缝（owner=归属人 + 回授）→ 响应`

**C. WS 分支**（`/api/v2/workflow/chat/{id}`、`/api/v2/assistant/chat/{id}`）

`握手 → 同一依赖，isinstance(conn, WebSocket)：Authorization 头（服务端集成）或 ?share_token=（guest 页）二选一（同时给以密钥为准、share_token 忽略并记日志）→ 密钥分支同 B（位 = workflow:invoke / assistant:invoke）；share-token 分支：ShareLinkService.get_share_link_by_token（bypass 查、status ACTIVE、未过期）→ share_scope=='app' ∧ resource_id == 路径 id → 以创建者直接构造 UserPayload + set_current_tenant_id(share.tenant_id) → 失败一律 WebSocketException(1008, reason=码) → 成功 accept → 审计 open_api.ws.connect → watchdog 每 3s 复查（撤销 / 过期 / 停用 → close(1008)）→ dispatch_client（common/chat/manager.py 既有逐消息 use 校验保留）`

**D. share-link 作用域 HTTP**（guest 页信息 / 历史 / 标题）

`GET /api/v1/share-link/{token}/resource | /chat/history | POST /chat/gen_title → header/查询 token → 同上校验 → 创建者身份 + 租户 → 只放行 share.resource_id 对应资源 / 该 flow_id 下的会话 → 响应`

**E. 撤销 / 停用 / 删除的失效链**

`管理端点单行 ORM 更新（revoked_at / disabled_at / deleted_at）→ 同一请求内按 DB 清单 adelete 每个 oapi:cred:{hash} → 审计 → 最坏 3s 内所有节点新请求被拒；已建 WS 由 watchdog ≤ 3s 断开`

### 4.2 关键数据结构 / 字段约定（对外可见契约）

| 字段 / 结构 | 类型 / 格式 | 说明 | 谁会消费 |
|---|---|---|---|
| `Authorization: Bearer bs-sak-<43 位 urlsafe-b64>` | HTTP / WS 握手请求头 | 唯一密钥传递方式；查询参数**不接受**密钥（会进访问日志） | 全部 `/api/v2/**`、F051–F053 三面、F055 应用运行期凭据 |
| `?share_token=<32 位>`（WS）/ `share-token` 头或路径段（HTTP） | 查询参数 / 请求头 | 仅两个 WS 与 `/api/v1/share-link/{token}/*` 接受 | client guest 页 |
| 密钥前缀 / 掩码 | `bs-sak-`；掩码 = `bs-sak-********` + 末四位（8 个 `*`） | AC-02 / 54：前缀模式公开给 secret scanning 与 F055 扫描规则集：`\bbs-sak-[A-Za-z0-9_-]{43}\b` | 列表 / 详情 / 审计 metadata / F055 |
| `api_credential` 行（对外只经 API 暴露掩码字段） | `id` int PK · `tenant_id` · `subject_kind` VARCHAR(32)（`service_account` / `hosted_app`）· `subject_id` VARCHAR(64) · `name` · `key_prefix` VARCHAR(16) · `last4` VARCHAR(4) · `token_hash` VARCHAR(64) unique · `scopes` JsonType(list[str]) · `expires_at` / `revoked_at` / `last_used_at` DateTime nullable · `revoke_reason` VARCHAR(32)（`manual` / `batch` / `subject_disabled` / `subject_deleted` / `expired`）· `created_by` · `create_time` / `update_time` | 有效 = `revoked_at IS NULL ∧ (expires_at IS NULL ∨ expires_at>now)`（K3）；注册进 `_TENANT_AWARE_MODEL_MODULES` | CredentialService / F055（`subject_kind='hosted_app'`）|
| `service_account` 行 | `user_id` PK(FK user) · `tenant_id` · `resource_owner_user_id` · `description` · `created_by` · `disabled_at` / `deleted_at` nullable · `create_time` / `update_time` | 名称 = `user.user_name`；启用 = 两时间戳皆空 | 管理端点 / 凭据校验 / F053 / F055（取归属人）|
| `user` 新增列 | `user_type` VARCHAR(16) NOT NULL server_default `'human'`，索引 | Alembic revision；`service` = 服务账号 | DAO 过滤 / 登录守卫 / 对账 / 配额 |
| 权限位标识 | `workflow:invoke` `workflow:read` `knowledge:read` `knowledge:write` `assistant:invoke` `assistant:read` + 扩展位 `model:invoke` `identity:read` `app:manage`（组 `local_dev_toolkit`，仅 `open_platform.enabled`）| 字符串常量，`OPEN_API_SCOPES` 唯一来源；`GET /api/v1/service-accounts/scopes` 返回当前部署可见清单（含分组 / 说明 key / 覆盖端点） | 签发 / 编辑表单、F051–F053 判位 |
| `UserPayload.open_api_principal` | `{credential_id, subject_kind: 'service_account'|'share_link', subject_user_id, resource_owner_user_id, share_link_id, scopes}`，普通登录用户为 `None` | 业务 Service 据此取归属人（D5）；会话 / 审计仍用 `user_id` | 知识库创建、F053 deploy owner、审计 |
| `GET /api/v1/env` | 新增 `open_platform_enabled: bool` | 三扩展位显隐（AC-13 / 49） | platform `appConfig.openPlatformEnabled`、client（备用）|
| Settings | `open_platform.enabled`（默认 false）；`open_api.service_account_idle_days`（默认 90，AC-42）；`open_api.credential_cache_ttl_seconds`（默认 3，上限 5） | 进程级 config.yaml | 后端 |
| 管理端点（`/api/v1/service-accounts`，依赖 `open_api/api/dependencies.py get_service_account_admin`：内部调 `UserPayload.get_tenant_admin_user`（`common/dependencies/user_deps.py:50-75`，超管 ∪ 当前租户 Child Admin 的唯一既有判定）并把它抛出的 `LLMModelSharedReadonlyError`（**19801，文案「Root-shared LLM server/model is read-only…」，`common/errcode/llm_tenant.py:9-13`**——直接复用会让 AC-41 / AC-59 的拒绝在前端显示 LLM 只读文案）**改抛 `UnAuthorizedError`（`common/errcode/http_error.py:4`，信封 `status_code=403`）**；platform 拦截器 `controllers/request.ts:160` 对信封 403 统一处理，业务代码不再加分支。**AC-59「返回 403」的满足口径 = 信封 `status_code=403`，HTTP 状态仍为 200**（`/api/v1` 全局 `handle_http_exception` 语义不改，K4 只对 `/api/v2` 真实化）——E2E 断言信封码而非 HTTP 状态） | `GET /`（分页 `PageData`，列：名称 / 状态 / 有效密钥数 / 归属人（含禁用标记）/ 最后调用 / 创建人 / 创建时间；`idle_days` 阈值随响应 meta）· `POST /` · `GET /{id}` · `PATCH /{id}`（名称 / 描述 / 归属人）· `POST /{id}/enable` · `POST /{id}/disable` · `DELETE /{id}` · `GET /{id}/keys` · `POST /{id}/keys`（唯一返回明文处）· `PATCH /{id}/keys/{key_id}`（名称 / 权限位 / 过期）· `POST /{id}/keys/{key_id}/revoke` · `POST /{id}/keys/revoke-all` · `GET /{id}/grants`（分页、按 `resource_type` 筛，行形状 = `PermissionGrantAssignee` 前端既有类型 + `source_label`）· `POST /{id}/grants:mutate`（`{changes:[{resource_type,resource_id,op:ADD|MOVE|REMOVE,model_key,expected_assignee_version?}]}` 逐条结果）· `POST /{id}/grants:revoke-all`（排除回授）· `GET /scopes` | 路径加入 `MANAGEMENT_API_PREFIXES`（`common/middleware/admin_scope.py:63-71`）以让超管 ScopeBar 生效（AC-23 "租户取当前管理员所在租户"在多租户下唯一入口）——这是 F019 元组的一次可审计扩展 | platform `controllers/API/serviceAccount.ts` |
| share-link 增量 | 匿名（豁免前缀下）：`GET /api/v1/share-link/{token}/resource`、`GET /api/v1/share-link/{token}/chat/history?chat_id=`、`POST /api/v1/share-link/{token}/chat/gen_title`；登录态（**非豁免前缀** `/api/v1/app-shares`）：`GET /api/v1/app-shares?resource_type&resource_id`（列表，只返回 `share_scope=app`）、`POST /api/v1/app-shares/{id}/revoke`；生成请求新增 `share_scope`（默认 `session`）；`expire_time` = 相对秒、`app` 必填 > 0 | 既有 `generate_share_link` / `GET /{token}` 不变 | platform `ChatLink`、client |
| `GET /api/v2/auth/whoami` | 返回 `{subject_kind, service_account:{id,name}, tenant_id, scopes, key_mask, expires_at}` | 标记 `@open_api_scope(None)`（不判位，但必须带标记）；F053 `login` 校验点 | F053 CLI、114 手动验证 |
| 审计 action | `open_api.service_account.*` / `open_api.api_key.*` / `open_api.grant.*` / `open_api.share_link.*` / `open_api.ws.connect` | `metadata` 永不含明文 | 系统操作日志页 |
| 错误码 | 见 D10；`/api/v2` 上 HTTP 状态真实（401 / 403 / 404 / 503），`/api/v1` 管理端点仍 HTTP 200 + 信封（AC-59 的「403」= 信封码 403） | 信封 `{status_code, status_message, data}` | 调用方 / 前端 |

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| **`open_api/`（新模块）** `api/router.py`（`/service-accounts` 挂 `/api/v1`；`/auth/whoami` 挂 `router_rpc`）· `api/endpoints/service_account.py` · `api/endpoints/service_account_keys.py` · `api/endpoints/service_account_grants.py` · `api/dependencies.py`（`verify_open_api_access` router 级依赖 + `open_api_subject(scope=…)` `Depends` 工厂供 F053 / F055 新 router）· `domain/models/{api_credential,service_account}.py` · `domain/services/{credential_service,credential_validator,service_account_service}.py` · `domain/scopes.py`（`OPEN_API_SCOPES` + `@open_api_scope` 标记）· `domain/context.py`（ContextVar）· `domain/schemas/` | 凭据全生命周期、服务账号 CRUD、权限位判定、主体侧授权页读端点与 mutate 编排、审计事件 | 不写 OpenFGA、不自建授权镜像、不判具体资源权限（交 F048）、不含 UI 文案 |
| `open_endpoints/`（既有 v2 业务端点） | 8 个路由文件加 `@open_api_scope` 标记、身份改 `Depends(get_open_api_login_user)`；`chat.py` 删除；`domain/utils.py` 只剩 `get_open_api_login_user` + 收紧后的 `resolve_operator`；`api/dependencies.py:61-70 get_knowledge_space_chat_service_for_openapi` 死函数删除；`endpoints/workflow.py invoke_workflow` 加 `FlowStatus.ONLINE` 守卫（AC-37）；`endpoints/filelib.py download_statistic_file` 改 `file_name` + 固定目录 realpath 校验（AC-40） | 不再解析任何身份、不读配置身份、不 import `open_api/api/*` |
| `bisheng/api/router.py:94` | `router_rpc = APIRouter(prefix='/api/v2', dependencies=[Depends(verify_open_api_access)])`；注册 `open_api` v1 router | — |
| `main.py` | 注册 `OpenApiAuthError` 与 v2 上 `PermissionServiceUnavailableError`（19002）/ `PermissionBackendUnavailableError`（19201）→ 503 的专属 handler | 不改 `handle_http_exception` 全局语义 |
| `common/errcode/open_api.py` | 260xx 定义 | — |
| `core/config/open_platform.py` + `settings.py` + `api/v1/endpoints.py get_env` | 开关三段式后端两段 | — |
| `user/domain/models/user.py`（`_filter_users_statement` 默认参数、`alist_users_after_id` 加类型条件、`aget_login_candidates_by_account` 第二道锁）· `user/domain/services/user.py`（`_reject_login_if_user_has_no_usable_access` **最前**拒绝 SA → 26012；`assert_natural_persons`）· `user/api/user.py:663`（`/user/update` 拒绝 SA） | 服务账号的登录 / 选人 / 对账免疫 | 不改 `TenantResolver`、不改 guest 兜底三条路径 |
| `permission/`（`grant_source_service.py` 新 `SERVICE_ACCOUNT_AUTOGRANT`；`runtime.authorize_created` 回授分支；`application/subject_api.py` 主体反查；`f048_permission_subject.canonical_source` 拒 SA 主体除非显式允许；`grant_subject_service.list_candidate_users` 过滤） | 授权真相 | 不认识"服务账号"业务对象，只认 `user_type` 与显式参数 |
| `knowledge/domain/services/knowledge_service.py`（`acreate_knowledge_base :795-799` / `create_knowledge_base :741-749` 的 `user_id` 硬写处参数化；`process_one_file :1483-1544` `KnowledgeFile.user_id` 改归属人；`_new_library_permission_record :194-208` 带 `creator_autogrant_user_id`）· `knowledge/domain/services/knowledge_space_service.py`（`create_knowledge_space :1100` `user_id` 参数化 + `:1110-1117` 记录带回授字段）· `knowledge_permission_service.py:995-1000`（adapter 透传 `autogrant_user_id`） | 创建关系落归属人（D5 三条路径） | 不判归属人权限；文件 / 文件夹不回授（INHERIT） |
| `share_link/`（模型加 `share_scope`；service 强制过期 + revoke；新增 3 个匿名作用域端点（豁免前缀下）；新增 `api/endpoints/share_link_manage.py` 挂 `/api/v1/app-shares`（登录态，非豁免前缀）；`api/dependencies.py:30-48 header_share_token_parser` 复用） | share-token 通道 | 不出现在 v2 HTTP 面；登录态端点不落豁免前缀 |
| `worker/tenant_reconcile/tasks.py:68` ← `alist_users_after_id`；`tenant/domain/services/user_tenant_sync_service.py:76 sync_user` 入口守卫；`role/domain/services/quota_service.py:622-651 _count_user_count` 加类型条件 | 对账豁免 / 配额排除 | — |
| `worker/workflow/redis_callback.py:118-123 set_workflow_status` | 状态载荷加 `owner_user_id` / `tenant_id`（供 `/workflow/stop` 归属校验，AC-38） | — |
| `worker/open_api/tasks.py expire_credentials`（新，Beat 每小时，默认队列） | 到期密钥 `revoke_reason='expired'` 兜底写入 + 审计（D11） | 不改有效性判据、不删缓存（到期不需要） |
| `database/models/audit_log.py` + `platform/controllers/API/log.ts` + `bs.json` | 审计四处 lockstep | — |
| **platform** `pages/SystemPage/index.tsx`（新 tab，`isSuperAdmin ∪ isChildAdmin`，不含部门管理员）· `pages/SystemPage/components/ServiceAccount/`（列表 / `CreateServiceAccountDialog`（归属人 = `DepartmentUsersSelect multiple={false}`）/ 详情三子 tab / `KeyIssueDialog` / `KeyRevealDialog` / `ServiceAccountGrantsTab`）· `controllers/API/serviceAccount.ts` · `controllers/API/shareLink.ts` · `types/api/serviceAccount.ts` · `public/locales/*/serviceAccount.json` ×3（加进 `i18n.js:45` ns）· `contexts/locationContext.tsx` `openPlatformEnabled` · `components/bs-comp/apiComponent/{ChatLink,ApiAccess,ApiAccessFlow}.tsx` | 管理界面 | 不用 `react-query`（冻结）；不复用 `PermissionDialog` 整体（只复用 `getGrantablePermissionModelsApi` / `SourceBadge` / `PermissionGrantAssignee` 类型）；不新增 web_menu |
| **client** `pages/standaloneChat/StandaloneChatPage.tsx` · `pages/appChat/useChatHelpers.ts` · `api/apps.ts` · `api/chat/api-endpoints.ts` · `utils/shareToken.ts` | guest 页带 share-token | 不再打任何 `/api/v2` HTTP |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | **平台把 `HTTPException` / `BaseErrorCode` 一律压成 HTTP 200 + 信封**（`main.py:22-36 handle_http_exception`，`_EXCEPTION_HANDLERS :46-51`）；路由里 `raise HTTPException(403)` 客户端收到 200 | AC-01/04/33/34 的真 401/403/5xx 全部不成立，E2E 全红且调用方按 HTTP 状态判错的 SDK 全坏 | `open_api` 专属 handler（`main.py` 仿 `:165-167`）；WS 用 `WebSocketException`（D2） |
| 2 | **中间件对解不开的 Bearer 预种租户 1**（`http_middleware.py:60-73 → _set_tenant_context :87-122 → :101-106`），基线写的"不注入"不准确 | 依赖漏 `set_current_tenant_id` 时多租户**静默按 Root 查**、不报 `NoTenantContextError`，跨租户串数据无任何症状 | `verify_open_api_access` 校验通过后无条件 `set_current_tenant_id(密钥租户)`；集成测试断言子租户密钥查不到 Root 数据 |
| 3 | 平台"登录入口"是 10 个，但守卫只有 1 处公共 + 3 处单独：公共 = `_reject_login_if_user_has_no_usable_access`（`user/domain/services/user.py:373`）4 个调用点（本地 `:460` / 旧 SSO `user/api/user.py:97` / login-sync `login_sync_service.py:221` / 切租户 `tenant_service.py:662`）；单独 3 处 = PRD 附录 E.2 所列的 `resolve_operator`（`open_endpoints/domain/utils.py:77`，F050 前保留）、`get_default_operator*`（`:36/:59`，随 AC-52 删除）、`/user/update`（`user/api/user.py:663`，D7 断言）。**公共守卫第一段就是 `AdminRole → return`（`:394`）**，且它是"返回响应对象"式守卫 | 守卫放在 bypass 之后 → 被误授 AdminRole 的服务账号直接放行；用 `return` 通道返回 26012 → 被 `tenant_service.py:663-665` / `login_sync_service.py:228-230` 的 `else: raise UserNoWebMenuForLoginError()` 压成"无菜单"（**只有 `UserNoRoleForLoginError` 会原样透传**） | 守卫放 `:388 with bypass_tenant_filter()` 之前，**`raise`** `26012`（D10） |
| 4 | **`is_global_super` 不对称**：`init_login_user`（`auth.py:522-556`）**无条件**调 `_check_is_global_super`（`:542-543`），`init_login_user_sync`（`:558-580`）恒 False；`_check_is_global_super`（`http_middleware.py:145-207`）= Redis `user:{id}:is_super` → FGA `super_admin` Check → legacy AdminRole 回落（`:187-198`），`role_ids=[]` 只关得掉最后一段 | 走 `init_login_user` → 每个 v2 请求多 1 次 Redis / 未命中多 1 次 FGA，且服务账号"永不超管"退化成数据状态（有人写了 FGA tuple 就短路）；走 sync 版 → 与其它路径不对称 | D2 **直接构造 `UserPayload(is_global_super=False, user_role=[])`**，两版都不调；D7 `assert_natural_persons` 守 `/user/role_add`（`user/api/user.py:874-965`）与 `grant_tenant_admin` 是纵深不是唯一防线 |
| 5 | **`external_id=NULL` 是隐式防线**：登录候选 `aget_login_candidates_by_account`（`user.py:212-223`）、公开改密（`user/api/user.py:1103`）、login-sync 匹配（`login_sync_service.py:263-266`）都只按 `external_id`；`user_name` 不参与；旧 SSO `/user/sso`（`user/api/user.py:67`）**按用户名**匹配 | 给服务账号写了 `external_id`（哪怕为了"看起来完整"）→ 三条免疫全失；旧 SSO 同名账号可被匹配到、只剩守卫 | 创建路径固定 `external_id=NULL`；`aget_login_candidates_by_account` 加 `user_type=='human'` 第二道锁；测试断言 |
| 6 | **guest 部门自动兜底有三条路径**：启动 `_backfill_guest_department_membership`（`common/init_data.py:439-481`，判据是 `user_department` 全表任意一行 `:458-461`，整表为空时全用户入 guest）、SSO/网关推送 `_reconcile_guest_membership`（`login_sync_service.py:409`，`:202` / `sso_sync/api/endpoints/gateway_wecom_org_sync.py:123`）、自助注册 `_ensure_user_guest_department_membership`（`user.py:293/300`） | 服务账号被塞进 guest 部门 → 全局成员搜索能搜到、"无部门"前提破产；创建路径若复用 `user_register` / `add_user_and_default_role` 同时违反 AC-22 | 不改三条路径（PRD E.2 决议）；创建路径**新写纯插入**（`UserDao.create_user` 或新方法）；`department_service` 全局搜索加类型条件；测试断言 |
| 7 | **对账会把子租户的服务账号搬回 Root**：`worker/tenant_reconcile/tasks.py:68` 经 `alist_users_after_id`（`user.py:541-556`，只查 `delete==0`）→ 无主部门 expected=ROOT（`user_tenant_reconcile_service.py:63-64`）→ `sync_user` 搬家 + bump token_version + 重写 tenant#member | 6 小时后子租户服务账号"消失"、密钥校验租户不一致全部 401；卸载子租户（`tenant_mount_service.py:487-600`）/ 删租户（`tenant_service.py:355-397` → `adelete_by_tenant`）留下悬空主体 | `alist_users_after_id` 收口 + `sync_user :76` 入口守卫；凭据校验把"主体活跃租户存在且 status=active"纳入 fail-closed |
| 8 | **`aadd_user_to_tenant`（`database/models/tenant.py:614-628`）不写 `is_active`**，而授权主体校验（`f048_permission_subject.py:70`）与 `_count_user_count` / `aget_active_user_tenant` 都要 `is_active==1` | 建号成功、授权页整页不可用、密钥校验取不到活跃租户 | 创建用 `aactivate_user_tenant`（`:867`）语义 |
| 9 | **`/user/list` 8 处消费点 + `grant_subject_service.list_candidate_users` 独立查询**（`grant_subject_service.py:70-121`，条件 `:90`）——DAO 改一处覆盖不到资源侧选人框；`canonical_source`（`f048_permission_subject.py:68-71`）不看类型 | 资源侧弹窗仍能选到服务账号；直接 POST `grants:mutate` 仍能从资源侧授权 → INV-29 破 | D7 三处 |
| 10 | **`_filter_users_statement` 之外还有旁路**：`get_all_users :401`、`search_user_by_name :296`、`get_user_with_group_role :412`、`get_user_by_ids/aget_user_by_ids :178/:184`、`get_unique_user_by_name :290`、`aget_users_by_username :204`、`aget_by_source :557` | 以为改一处就全覆盖 | 逐个判定：名称水合**保持不过滤**（AC-16 可显示）；筛选类不动；`get_unique_user_by_name` 只服务旧 SSO 靠守卫 |
| 11 | **`_count_user_count`（`quota_service.py:622-651`）会计入服务账号，但 `aget_quota` / 租户列表用户数走部门子树**（`tenant_service.py:184/223/362/410` → `acount_users_by_tenant_subtree`）结构性不含；`user_count` 配额无任何创建期强制 | 两处口径不一致、以为"配额已排除"其实只排了一半 | `_count_user_count` 加类型条件；测试两处都断言 |
| 12 | **回授不能用 `protected=True` 表达**（`grant_service.py:308/326` 禁止 mutate 触碰受保护源），也不能复用 `DIRECT`（分不出回授）；`SOURCE_TYPES` 是 frozenset（`grant_source_service.py:16-26`），新值须同步 `_validate_source_subject :178` 与 `_source_locator :193`；`sync_business_source_model` 白名单（`runtime.py:647-649`）与之无关 | 回授行不可撤销（AC-63 失效）或「全部撤销」把回授一起删（切断集成写入） | D5 新 `SERVICE_ACCOUNT_AUTOGRANT` |
| 13 | **Catalog「动作↔资源类型范围表」只写一次**：`_ensure_catalog`（`permission/migration/f048_runtime_storage.py:834-912`）只写 INITIAL release 且 checksum 不符即抛；草稿发布 `_replace_children`（`catalog_api.py:769-823`）不引入新类型 | F049 本身不加资源类型故不触雷；但若把 `app:manage` 判定做成"F048 资源动作"就会撞上——F054 才处理 | `app:manage` 在 F049 只是权限位常量判定，不进 Catalog |
| 14 | **UNION / 子查询绕过租户过滤**：租户监听器只对顶层 SELECT 注入（`tenant_filter.py:164`）；反查 SQL 若写成 UNION 或 `text()`，子查询不带 `tenant_id`；密钥表批量 UPDATE/DELETE 同样无注入 | 跨租户看到别人的授权 / 撤销别人的密钥 | 反查用单条 select + join；密钥写路径单行 ORM（K6） |
| 15 | **WS 查询参数鉴权是坏的**：`AuthJwt.get_subject` websocket 分支无条件用 cookie 覆盖传入 token（`auth.py:175-177`），`t` 参数是死路径；`headers` 分支（`:178-180`）零调用且缺头 NPE | 复用 `AuthJwt` 做密钥鉴权必崩 | 新写依赖，不碰 `AuthJwt` |
| 16 | **助手 WS 裸崩机制**：`assistant.py:304 get_default_operator()` 在 `try(:305)` 之外 → `HTTPException(500)` → 全局 handler 在 WS scope 上以 HTTP 200 denial 拒握手；工作流 WS（`workflow.py:163-174`）`close(1011)` before accept → 403 但 reason 丢 | 修成"移进 try"仍是 200 denial；在依赖里 raise `HTTPException` 也一样 | D2：身份解析全部进依赖 + `WebSocketException(1008)` |
| 17 | **`generate_short_high_entropy_string`（`common/utils/util.py:28-54`）上限约 43 字符**（sha256 → b64 截断），`length` 传更大值静默变短 | 以为签出 64 位密钥其实 43 位（仍够强，但文档口径错） | 用 `secrets.token_urlsafe(32)`（43 字符，同等强度）；share_link 继续用原函数 |
| 18 | **`share_link` 语义今天是"会话级"**：`ShareChat.tsx:59` 传 `resource_id=chatId`，`workflow`/`assistant` 类型的 `resource_id` 是会话 id；5 个后端消费点按 `resource_id == chat_id` 校验；`expire_time` 单位 / 绝对相对未定；`status` INACTIVE 无写入端点；`share_token` 存 CHAR(36) 实写 32 位（DM8 靠去空格补丁） | 直接复用两枚举值做应用级分享 → 与既有会话分享冲突；改 `SQLEnum` 撞 MySQL ENUM ALTER | D8 `share_scope` 列 + 相对秒语义 + revoke 端点 |
| 19 | **`withdraw_instance` 无终态守卫**（`approval/domain/services/approval_center_service.py:418-489`，`:427-431` 只查存在与申请人）与**租户配额整体覆盖写**（`tenant_service.py:419-435 aset_quota`；前端 `TenantQuotaDialog.tsx:57-61` 只序列化 `storage_gb`）——都在 F049 探查中被核实但**不属本 Feature** | 顺手去修 → 越界；不知道 → F055 撤回 / 租户配额页踩雷 | 登记给 F055（契约表 3）与 discovery §5 已知缺陷；F049 不碰 |
| 20 | **DM8 写放大**：`api_credential.last_used_at` 若每请求 UPDATE，DM8 undo 会被高频调用撑爆（同灵思 -7120 事故形态） | 生产 DM8 环境高频集成把库写死 | 60 秒 `SET NX` 闸 + 单行 UPDATE（AC-10 允许 60 秒合并） |
| 21 | **F048 `check` 曾被刻意从硬 fail-closed 改成兜底**的只剩 `_check_is_global_super`（`http_middleware.py:187-198`）一处，判定链本身无 owner/creator 兜底（`permission_action_service.py:125-166`） | 以为"资源没授权也能兜底看到"→ 服务账号零授权时一切 v2 调用都失败是**正确行为**（授权页空态文案要说清） | 授权页空态 + AC-64 提示 |
| 22 | **`config.yaml` 顶层未知键拒绝启动**（`config_service.py:104-106`） | 114 先加 `open_platform:` 键再发代码 → 后端起不来 | 部署顺序：先发代码、再加键、再重启（tasks 部署步骤） |
| 23 | **admin-scope 只对 `MANAGEMENT_API_PREFIXES` 生效**（`admin_scope.py:63-71`）；超管默认在 Root、无租户管理员档，多租户下超管给子租户建号只有 ScopeBar 一条路 | 不加前缀 → ScopeBar 切换无效、创建落 Root；加了 → 是 F019 元组的扩展（审计项） | 把 `/api/v1/service-accounts` 加进元组并在 tasks 登记 |
| 24 | **platform `react-query` 已冻结**（`eslint.config.mjs:45,51`），`ApiAccessFlow.tsx` 冻结 188 条中文（`eslint-suppressions.json`），改它就要整文件 i18n | 新页面照抄旧页 import 即 lint 失败；改示例文本被 CI 拦 | 新页用 `useTable` / `useState+useEffect`；`ApiAccessFlow.tsx` 改动单列 i18n 工时 |
| 25 | **`resolve_operator` 的租户种子来自调用方指定的目标用户**（`open_endpoints/domain/utils.py:96-97`） | F049 期保留该函数若不加"目标活跃租户 == 密钥租户"，一把密钥可跨租户取数 | D3 收紧 |
| 26 | **`TENANT_CHECK_EXEMPT_PATHS` 是 `startswith` 前缀**（`http_middleware.py:311`）且命中即整链 `_bypass_tenant_filter=True` + 跳过 token_version + 跳过租户禁用检查（`:322-343`）；`/api/v1/share-link` 在列（`:39`），既有登录态 `generate_share_link`（`share_link/api/endpoints/share_link.py:12-17`）已在此暴露面下运行 | 把撤销 / 列表放在任何 `share-link*` 前缀下 → 列表在 bypass 下跨租户可见、撤销不受 token_version 保护 | D8：登录态端点挂新的非豁免前缀 `/api/v1/app-shares`；匿名作用域端点留在豁免前缀（它们需要 bypass）；`generate_share_link` 既有暴露只登记不搬 |
| 27 | **INHERIT 起始模式的资源上非 protected 本地行是无效的**：`control_state.py:355 protected_only=normalized_mode=="INHERIT"`、`mode_service.py:72-76`；`folder / knowledge_file` 起始 INHERIT（`resource_lifecycle_policy.py:14,29-33`）；`_validate_copy`（`owner_service.py:236-239`）对 `RESOURCE_CREATE` 见 `copy_grants` 即抛 | 给服务账号上传的文件也写回授行 → 行落账本却不生效（或被 `_validate_copy` 拒创建）；复用 `copy_grants` 携带回授 → 创建直接 `PermissionInvalidResourceError` | D5：新 `extra_grants` 字段、INHERIT 目标忽略回授、文件写权限来自父库授权 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `Authorization: Bearer bs-sak-…` 凭据格式、前缀模式 `\bbs-sak-[A-Za-z0-9_-]{43}\b`、掩码格式 | 对外接口文档 + secret scanning 规则 | 调用方、F055 发布前扫描 |
| `/api/v1/service-accounts/**` 管理端点（§4.2） | HTTP API（JWT，租户管理员及以上） | platform 服务账号页 |
| `GET /api/v2/auth/whoami` | HTTP API（Bearer） | F053 CLI `login`、114 验证 |
| `verify_open_api_access`（router 级）与 `open_api_subject(scope: str | None, modes=…)`（`Depends` 工厂）、`@open_api_scope(...)` 标记、`get_open_api_login_user` | 内部 Python API（`bisheng.open_api.api.dependencies` / `bisheng.open_api.domain.scopes`） | F050（加 delegate 分支）、F051 模型面、F052 MCP 面、F053 CLI 端点、F055 部署管线端点（`subject_kind='hosted_app'`）、F058 |
| `CredentialService.issue / revoke / revoke_by_subject / update`（接受 `subject_kind='hosted_app'` 存储 / 签发 / 回收）+ `credential_validator.SUBJECT_RESOLVERS` 注册点 | 内部 Python API | F055 应用运行期凭据自动签发 / 回收；**F055 须自行注册 `hosted_app` 解析器**（执行身份 / 租户 / `subject_user_id` 取谁由 F055 定义），未注册前该 kind 在 `/api/v2` 上按 `26002` 拒绝（D2「主体解析器」） |
| `OPEN_API_SCOPES` 常量与三扩展位标识 | 常量 | F051–F053 判位；签发表单 |
| `settings.open_platform.enabled` / `GET /api/v1/env.open_platform_enabled` / `appConfig.openPlatformEnabled` | 配置三段式 | F051 / F052 / F053 显隐与拒绝 |
| `UserPayload.open_api_principal`（含 `resource_owner_user_id`） | 内部数据契约 | 知识库创建、F053 / F055 deploy owner |
| `SERVICE_ACCOUNT_AUTOGRANT` 来源值、`subject_api.list_subject_grants` | 内部 Python API（permission.application） | 主体侧授权页；F050 授权页「delegate 提示」 |
| share-link 增量：`share_scope`、`POST /app-shares/{id}/revoke` / `GET /app-shares`、`/share-link/{token}/{resource|chat/history|chat/gen_title}`、WS `?share_token=` | HTTP / WS 契约 | client guest 页、platform `ChatLink` |
| 审计 action 命名空间 `open_api.*` | 数据契约 | 审计页 |
| 错误码 260xx | 数据契约（三语） | 前端 / 调用方 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `user` 表 + `UserDao`（`_filter_users_statement :259`、`aget_login_candidates_by_account :212`、`alist_users_after_id :541`、`aget_user_by_ids :184`）与 `LoginUser` pydantic 模型（`auth.py:196`，直接构造，不经 `init_login_user`） | ORM / 内部 API | `LoginUser` 字段增删（`is_global_super` / `user_role` 默认值）；建号不复用 `create_user`（D1 单事务） |
| `user_tenant`（`aactivate_user_tenant :867`、`uk_user_active :185`、`aget_active_user_tenant`） | ORM | 对账 / 挂载 / 卸载路径新增调用点未过守卫 → 服务账号被搬家 |
| F048 权限运行时：`authorize_created`（`runtime.py:206-260`，本 Feature 加 `autogrant_user_id` kwarg 与 `OwnerProjectionContext.extra_grants`）、`mutate_grants :603-623`、`resource_api.mutate_grants`、`canonical_source`、`grant_source_service`、`ix_perm_assignee_subject_state`、`check/require_business_action`（`business_authorization.py:27/48/64`）、`grantable_models` | 内部 Python API + 表结构 | 索引被删 → 反查全表扫；`SOURCE_TYPES` 校验收紧漏掉新值 → 回授失败即创建 `FAILED_CLOSED`（资源变砖）；ListObjects 策略变化不影响我 |
| `share_link` 模型 / `ShareLinkService.get_share_link_by_token`（bypass 先例）/ `header_share_token_parser` | ORM / 内部 API | 别人把 `expire_time` 语义改成绝对时间戳 → 我的强制过期算错 |
| Redis（`core/cache/redis_manager.get_redis_client`，`aset` pickle + `setex`、`asetNx`、`adelete`） | 基础设施 | Redis 不可用 = 开放面整体 503（K2 刻意）；`akeys` 用 `KEYS`（`redis_conn.py:196-203`）不可用于批量、我不依赖它 |
| MySQL / DM8（Alembic 加列；新表 create_all；`JsonType`） | 基础设施 | DM8 部分 NULL 唯一（D1）；DM8 CLOB 不能按位过滤 |
| `AuditLogDao.ainsert_v2`（`audit_log.py:366-430`） | 内部 API | 签名变更；`_UI_VISIBLE_V2_ACTIONS` 未同步则页面不显示 |
| `Settings` / `config_service.load_settings_from_yaml`（未知键拒启）、`get_env` | 配置 | 部署顺序（坑 22） |
| FastAPI 0.121 / Starlette 0.49.3（router 级依赖传播到 WS 路由；`scope["endpoint"]`；`WebSocketException`）、uvicorn 0.38 | 框架 | 升级改变任一 → D2/D3 需复核（单测枚举路由可及早发现） |
| `common/middleware/admin_scope.py MANAGEMENT_API_PREFIXES` | 常量 | 我加一项；F019 审计口径 |
| platform：`bs-ui`（dialog / table / tabs / checkBox / alert / tooltip / calendar）、`DepartmentUsersSelect`、`useTable`、`bsConfirm`、`copyText`、`getGrantablePermissionModelsApi` / `mutateResourceGrantsApi` 类型、`SourceBadge`、`appConfig` | 组件 / API 封装 | `PermissionGrantAssignee` 类型变化 → 授权 tab 行形状漂移；`DepartmentUsersSelect` 走 `/user/list` 或全局成员搜索两条路径都必须已排除服务账号 |
| client：`StandaloneChatPage` guest 模式、`useChatHelpers`、`api/apps.ts` | 页面 | guest 页若被别的改动重新指回 `/api/v2` HTTP → 升级后白屏 |
| `docs/api/filelib-retrieve.md`、`ApiAccess.tsx` 示例 | 文档 | AC-54 |

---

## 7. 测试与可观测

**分层策略**（不重复 tasks 清单）：

- **单元**（`test/open_api/`）：凭据生成 / 哈希 / 掩码 / 有效性判据（撤销 · 过期 · 边界时刻）；`OPEN_API_SCOPES` 与三扩展位可见性随 `open_platform.enabled`；**路由完整性**——枚举 `app.routes` 下 `/api/v2/**`，每条都带 `@open_api_scope`，位在注册表内或为 `None`（`None` 只允许 `/api/v2/auth/whoami` 白名单）、注册表可含无端点的位（`chat:invoke`）、6 个 `/chat/*` 路径不存在；`download_statistic` 的 `file_name` 校验（`../`、绝对路径、子目录、非 `.log` 全拒）；`_filter_users_statement` 默认排除 / 显式 `user_type=None` 才含；`assert_natural_persons`；`resolve_operator` 收紧；错误码三语对账（复用 `check-i18n`）。
- **集成**（pytest + httpx，连 test 中间件 MySQL / Redis / OpenFGA，`asyncio_mode=auto`）：TestClient 断言 **真 HTTP 状态**（无头 401 / 坏头 401 / 缺位 403 含 `data.required` / 身份头 403 / FGA 不可用 503）；WS：无凭据握手被拒（1008/403）、坏 share-token 被拒、有效 share-token 但路径资源不符被拒、密钥与 share-token 同传以密钥为准；**5 秒失效矩阵**：撤销 / 编辑权限位 / 停用 / 删除 / 批量撤销 / share-link 撤销与过期 → 下一次请求即拒（多次采样 ≤ 3s）；Redis 拔掉 → 503（不是放行）；**登录守卫矩阵**：本地登录 / `/user/sso` / login-sync（HMAC）/ 切租户 四入口对服务账号返回 26012；**对账豁免**：子租户服务账号跑 `reconcile_user_tenant_assignments` 后归属不变；`_count_user_count` 不计；**选人排除**：`/user/list`（超管与非超管两分支）、`grant-subjects/users`、全局成员搜索均不含服务账号，已授权列表 `display_names` 仍能显示；直接 POST 资源侧 `grants:mutate` 授服务账号 → 26029、主体侧端点 → 成功；**归属人**：v2 建知识库 → `knowledge.user_id` = 归属人、CREATOR 行在归属人、服务账号只有 `SERVICE_ACCOUNT_AUTOGRANT` 行且可 REMOVE、「全部撤销」不动它；换归属人不追溯；会话仍归服务账号；**四缺陷**：未上线工作流 invoke → 13010、停别人会话 403、`download_statistic` 传路径 / 越界文件名被拒、助手 WS 无凭据不产生未捕获异常；**到期**：过期密钥首次被拒后 `revoke_reason='expired'` 且恰一条 `open_api.api_key.expire` 审计（并发两请求只产生一条）、Beat 任务对从未再被调用的过期密钥补写；**归属人三路径**：v2 建知识库 / 建知识空间 / 上传文件 → creator 列与 CREATOR 行均在归属人、库 / 空间上服务账号只有 `SERVICE_ACCOUNT_AUTOGRANT` 行、文件 / 文件夹上服务账号**零行**且仍可继续上传；**可见租户**：子租户密钥能列出 Root 共享模型 / 知识库（AC-32）；**AC-59**：非管理员调 `/api/v1/service-accounts/**` → 信封 403（非 19801）；**多租户**：子租户密钥查不到 Root 数据（坑 2）；**DM8**（105 回归）：建 ≥ 2 个服务账号 + 上述矩阵抽样。
- **E2E**（`/e2e-test`，spec AC 全覆盖 + 页面手动清单）：AC-41–49、59–65 的页面路径；非管理员进 tab 不可见、直调管理端点 403。

**114 手动验证（对应 `mvp-114-path.md` §1 步 1–2；Wave 1 即可）**：
1. `bash /opt/bisheng-ops/deploy.sh` 部署（先代码后 `config.yaml` 加 `open_platform: enabled: true`，再重启后端）；`curl -s https://114/api/v1/env | jq .open_platform_enabled` → `true`。
2. 以**租户管理员**（非 admin，避免超管短路）登录 platform → 系统管理 → 服务账号 → 新建（归属人 = 开发者本人）→ 直达签发 → 勾 `app:manage`（「本地开发工具包」组可见）→ 复制明文 → 勾「我已保存」关闭；再打开列表：只见 `bs-sak-********xxxx`。
3. `curl -H "Authorization: Bearer bs-sak-…" https://114/api/v2/auth/whoami` → 200 含 `scopes:["app:manage"]`；去掉头 → **HTTP 401** `26001`；改一位 → 401 `26002`；用 `platform` 撤销 → 3 秒内再 curl → 401 `26002`；停用账号 → 同上；启用 → 恢复。
4. （Wave 2 后）`curl -H … https://114/api/v2/assistant/list` 未勾 `assistant:read` → **HTTP 403** `26003 data.required=assistant:read`；加 `X-Bisheng-On-Behalf-Of: 1` → 403 `26004`；`GET /api/v2/chat/history` → 404。
5. 用普通用户账号看用户管理 / 审批人 / 部门加成员 / 资源授权弹窗：搜不到该服务账号；服务账号密码登录 → 26012。

**关键日志 / 指标**：`open_api.call`（结构化行：`credential_id / subject / endpoint / scope / status_code / latency_ms / cache_hit`）；`open_api.auth.reject`（原因码）；`open_api.cache.invalidate`（键数）；watchdog 断连原因；审计页 `open_api.*`。Redis 键：`oapi:cred:{sha256}`、`oapi:cred:lastused:{id}`。

---

## 8. 后续改进 / 不打算做的事

- **P1（随后续 Feature）**：HTTP 逐调用审计表化 + 双归属（F050）；`delegate` 位、委托配置区、`26005–26007/26010/26016`（F050）；guest 会话从分享创建者会话列表摘出 + history 逐访客绑定（等 F050 `MessageSession` 分区键）；`chat:invoke` 端点标记与清 `pending_note_key`（F058）；`hosted_app` 主体解析器（F055）；文件级检索过滤（F052，本期 `POST /filelib/retrieve` 只加鉴权，过滤强度维持知识资源级 + fail-closed）；接入信息区（F053）；应用运行期凭据编排（F055，本底座只保证 `subject_kind='hosted_app'` 可用）；WS 吊销事件驱动断连（F054 app-proxy 的 connection 索引方案，本期用 3s 轮询 watchdog 够用）。
- **P2（PRD R8）**：限流 / 配额 / IP 白名单 / 幂等键——平台无 HTTP 限流基础设施，最近原语 fail-open（PRD 附录 E.5），不可按"接现成库"估。
- **不做**：兼容窗口 / 鉴权开关 / 迁移期放行（INV-27）；密钥级资源白名单（PRD D3）；个人 key；平台侧存量迁移或转型脚本；`share_link.status` 改成时间戳（既有读路径按枚举判，本期只补写入端点）；给 `share_link.resource_type` 加枚举值；把 `default_operator` 残留 DB 键清理成脚本；密钥经查询参数传递；F018 归属转移接口。
- **重写 / 拆分触发条件**：F051–F053 上线后凭据校验 QPS 使 Redis 成瓶颈 → 评估本地 LRU 只作"正缓存 + 版本号校验"的两级方案（仍靠 Redis 版本号保证 5 秒）；服务账号数量或授权条目达到万级 → 反查与名称水合改批量 join。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-08-17 | 初版（D1–D13 决策 + 25 条坑 + 契约 + 测试策略）；登记两处需回写上游：spec 决议-1「实际受影响面只有两个 WS」的核实基础已过时（D8）、`GET /api/v2/auth/whoami` 与 26020+ 管理面错误码需回写伴生 PRD 附录 B.1 / C | F049 design 编写（四份探查笔记 E1–E4 + spec 65 AC） |
| 2026-08-17 | **审查修订：处理 26 条**（1 high / 12 medium / 13 low）。要点：D5 接缝扩到知识空间与文件 / 文件夹三条创建路径并写死输入契约（`autogrant_user_id` kwarg + `extra_grants`，INHERIT 不回授）；D2 身份改直接构造 `UserPayload`（不经 `init_login_user`）、复刻 `{leaf,1}` 可见租户、每请求比对 `expires_at` + 租户黑名单、`hosted_app` 解析器注册点、503 码清单统一正名；D1 建号单事务 + 状态源口径；D3 补 AC-37 / AC-40 落点、`dependencies.py:63` 入删除清单、whoami `scope=None`；D8 管理端点改挂非豁免前缀 `/app-shares`、消费点计数订正为 6+2、★ 回写 spec 决议-1 项显式化；D9 `chat:invoke` 按 spec 登记为待开放位（撤回初版推翻）；D10 26012 必须 `raise` 的论据订正；D11 到期事件双通道（惰性 + Beat）；D13 补备选并消解 Wave 1 删除矛盾；D7 补 `/user/reset_password`；坑 3 / 4 / 6 / 13 订正，新增坑 26 / 27；§1 目标改 3 句。**需回写上游新增**：spec 决议-1 + AC-55「资源 = flow」口径（tasks 前 ★）；spec / 伴生 PRD 附录 B.1 登记 `/api/v1/app-shares` 与 `download_statistic` 入参 `file_path → file_name` 契约变化 | `/sdd-review design` 审查发现（两轮） |

<!-- self-check: design-checklist 24 项自检：1-23 满足；第 24 项（反映 tasks.md 实际偏差）暂不适用——tasks.md 尚未编写，实现后回填；第 12 项「与 spec §5-§7 实际实现一致」以"要建成的样子"口径写、实现后须按现状覆盖。 -->

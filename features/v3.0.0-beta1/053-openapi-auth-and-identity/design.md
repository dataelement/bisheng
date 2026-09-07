# Design: 开放 API 鉴权与身份传递（P0 底座 · P1 身份传递 / 个人访问令牌 / 日常模式会话）

> **本文档定位 — 总体设计 + 分工边界（Why this How）**
>
> - 需求的 **What** 以上游 PRD（`docs/product/3.0 开放 API 鉴权与身份传递 PRD.md` v2.4）为基础；本文按 2026-09-04 的范围裁定覆盖其中已变更部分：R8 / P2 不做、现有分享链接链路不改、服务账号不进入 `user` 表、日常模式复用既有 v1 能力但收窄对外请求字段、免登录发布接口迁至 v3。
> - 本文回答 **怎么做、为什么这么做、谁做哪块、接口在哪对齐**。6 个工作流（WS-A～F）通过 §6 的共享契约协作。
> - `reference/vibe-049-design.md` 只作为凭据生命周期、管理界面和端点标记的实现参考；其“服务账号复用 User”“新增分享凭据通道”“P2 运营能力”均不继承。
> - `文件:行号` 会漂移，落地前以符号名和路由清单重新定位。

**关联**: [discovery.md](../000-openapi-auth-discovery/discovery.md) · [spec.md](./spec.md) · [tasks.md](./tasks.md) · [release-contract.md](../release-contract.md) · [reference/](./reference/README.md)
**版本**: v3.0.0-beta1 · **Feature 编号**: F053 · **最后更新**: 2026-09-04（按范围新裁定重写，待 ★ 用户确认）

---

## 0. 阅读路径（按角色）

| 你是 | 先读 | 再读 |
|---|---|---|
| 把控者 / 评审 | §1 目标范围 · §3 总体架构 · §6.2 路由分面 | §7 迁移 · §10 发布 |
| WS-A 底座与权限主体 | §3.1～§3.3 · §5.A | §6.1 Principal · §6.4 数据 |
| WS-B 管理界面（platform） | §4 · §5.B · §6.2 管理 API | 当前设计规范与 landed 组件总览 |
| WS-C 身份传递与审计 | §3.2 · §5.C | §6.1 · §6.3 · §6.4 |
| WS-D 个人访问令牌 | §5.D · PRD §4.10 | §6 · §8 |
| WS-E 日常模式会话 | §5.E · §6.2 | 既有五个 v1 端点实现 |
| WS-F 免登录发布面 v3 | §3.1 · §5.F · §6.2 | client guest 页与网关路由 |

---

## 1. 目标与范围

**目标**：建立彼此独立、不可互相兜底的三种访问面：

1. `/api/v1/**` 继续服务站内前端：登录/管理接口沿用既有登录鉴权，现有分享与其它免登录接口也保持原语义；
2. `/api/v2/**` 作为密钥开放面，只接受平台签发的 `bs-sak-` / `bs-pat-`，不接受登录态代替密钥，也不回落默认操作员；
3. `/api/v3/**` 只承接工作流和知识助手对外发布所需的既有免登录接口，不做密钥鉴权。

在 v2 密钥面交付独立服务账号主体、自然人个人访问令牌、两种身份模式、逐调用审计，以及复用既有 v1 能力的日常模式会话接口。

### 1.1 本期范围

| PRD / 裁定 | 需求 | 归属工作流 |
|---|---|---|
| R1 | 凭据体系：签发、哈希存储、撤销、过期、权限位、最后使用时间 | WS-A |
| R4 | 服务账号独立主体表、资源归属人、F048 `service_account:{id}` 授权主体 | WS-A |
| R5 | v2 存量开放端点接入密钥鉴权；发布类端点拆出 v3 免登录面 | WS-A / WS-F |
| R6 | 服务账号、密钥、资源授权、PAT 管理界面 | WS-B / WS-D |
| R9 | v2 移除默认操作员回落；默认操作员和 `enable_guest_access` 仅保留给 v3 发布面 | WS-A / WS-F |
| R2 / R3 / R7 | 自身身份 / 代表他人、外部用户标识、五道准入、审计双归属、裸 `user_id` 收口、检索文件级过滤 | WS-C |
| R10 | 个人访问令牌：自助签发、级联失效、治理开关、技能包 | WS-D |
| §4.6.3 新裁定 | 以五个既有 v1 接口为契约，在相同子路径增加 v2 密钥接口 | WS-E |

### 1.2 明确移出本期

- **R8 与全部 P2 需求不做**：不设计、不建表、不留运行时代码，包括 IP 白名单、限流、日配额和幂等。
- **现有分享链接链路原样保留**：不改 `share_link` 表，不增加 `share_link.share_scope`，不改分享链接接口、前端参数或鉴权方式。
- **不改 `user` 表承载服务账号**：不增加 `user.user_type`，不为服务账号创建 `user` / `user_tenant` 行。
- 不建设 MCP / 模型协议面 / CLI；三扩展权限位默认不展示、不签发。
- 任务模式（灵思）和异步执行不开放；v2 日常对话只允许日常模式的现有同步 SSE 链路。

### 1.3 发版约束

- WS-A 与 WS-C 必须同版发布：裸 `user_id` 与默认操作员回落必须在 v2 同时消失。
- WS-A 的 F048 服务账号主体支持必须先于任何服务账号密钥启用。
- WS-F 后端 v3 路由必须先上线，再把 client guest 页、platform 发布文档和商业网关从 v2 切到 v3，避免免登录发布页中断。

---

## 2. 关键约束

> DDD 分层、双 DB、多租户、权限唯一入口、错误码、安全和前端 HTTP 边界遵循 `docs/constitution.md` C1–C7。

| # | 约束 | 后果 |
|---|---|---|
| K13 | **登录鉴权、密钥鉴权、免登录发布是三条不同通道** | v1 JWT、v2 API Key、v3 guest policy 不得共用“缺失则回落”的依赖 |
| K14 | **v2 只有一条固定管线**：凭据 → 租户 → PAT 开关 → 权限位 → 身份模式 → 授权主体 → 业务 | 任一 v2 端点漏标记均 fail-closed；端点体不得另行解析身份 |
| K15 | **服务账号是独立主体** | F048 actor 必须能表达 `service_account:{id}`；禁止用资源归属人的 `UserPayload` 冒充授权主体 |
| K16 | **模式 D 是纯替换** | 授权主体、会话归属与资源归属均换成被代表用户，服务账号自身授权不参与 |
| K17 | **PAT 动态继承自然人权限** | PAT 主体直接查 `User` + 活跃租户；因服务账号不在 `User`，无需 `user_type` 区分 |
| K18 | **授权主体与业务归属人必须分开** | 模式 S 服务账号以 SA 做 F048 Check，但业务资源的 owner / creator 仍写其 `resource_owner_user_id` |
| K19 | **审计复用现有 `audit_log`** | 不建 `open_api_call_log`；调用字段写入 `audit_log.metadata`，公共列只承载可稳定索引的字段 |
| K20 | **请求头不携带产品品牌** | 只使用 `X-On-Behalf-Of` 与 `X-End-User`；旧品牌头不作为别名继续接受 |
| K21 | **日常模式不造第二套业务实现** | v2 五个接口复用 v1 路径、业务服务、信封与 SSE；chat/completions 的对外 schema 以 v1 为底稿，但删除 `use_knowledge_base`、`task_mode` |
| K22 | **v3 是显式 allowlist** | 仅 §5.F 列出的发布接口存在于 v3；知识库、日常模式、管理接口不得挂入 v3 |
| K23 | **静默降级零容忍** | v2 日常接口收到已删除的 `task_mode` / `use_knowledge_base`、异步字段、旧品牌身份头或裸 `user_id` 时明确拒绝；不能静默忽略调用方字段 |
| K24 | **异步边界必须显式传递身份** | v2 工作流进入 Celery 时携带不可变执行快照；worker 不得从 `user_id`、默认操作员或缺失的请求 ContextVar 重建授权主体 |

**Constitution Check（自查）**：C1 `open_api/` 与 `public_endpoints/` 分层，v2/v3 API 层共享 domain service 而不互相 import；C2 只做 §7 所列 DDL，JSON 使用 `JsonType`；C3 `service_account`、`api_credential`、委托范围与会话来源字段均带租户约束，凭据校验后显式设置 ContextVar；C4 F048 扩展统一 actor，不在业务模块旁路授权；C5 260 段错误码统一登记；C6 明文密钥、请求体和敏感头不入审计；C7 前端只经各自 request wrapper。

### 2.1 与 vibe-049 参考实现的差异

| vibe-049 写法 | 本方案处置 |
|---|---|
| 服务账号复用 `User` + `user_type` | 作废；改为独立 `service_account` + F048 新主体类型 |
| 服务账号构造假的 `UserPayload` | 作废；改为 `OpenApiPrincipal` + 通用 `PermissionActor`，业务归属人单独传递 |
| 删除 `default_operator` / `enable_guest_access` | 只从 v2 移除；v3 发布面继续使用并统一加 guest policy |
| 两个 WS 并入密钥或分享凭据管线 | v2 WS 走密钥；另建相同能力的 v3 免登录 WS，二者路由隔离 |
| 新增分享凭据链路和分享表字段 | 全部不采纳；现有分享链接链路不动 |
| 新建逐调用日志表 | 作废；写现有 `audit_log.metadata` |
| IP / 限流 / 配额 / 幂等 | 全部不采纳 |
| 日常模式新造 `/workbench/chat` 三端点 | 作废；按 §5.E 复用五个既有 v1 契约 |
| 品牌化身份请求头 | 改为 `X-On-Behalf-Of` / `X-End-User` |
| PAT 主体判断依赖 `user_type='human'` | 删除；存在且启用的 `User` + 活跃 `UserTenant` 即自然人主体 |

---

## 3. 总体架构

### 3.1 三种访问面

| 访问面 | 调用方 | 身份来源 | 缺少该面凭据时 | 默认操作员 |
|---|---|---|---|---|
| `/api/v1` 既有面 | platform / client 与现有分享链路 | 各端点现有 JWT / cookie / 免登录语义 | 保持现状，不接收 v2 API Key 作为登录态替代 | 按现状 |
| `/api/v2` 密钥面 | 系统集成、个人 Agent | `Authorization: Bearer bs-sak-… / bs-pat-…` | HTTP 401 `26001`；登录 JWT 不能替代 | **禁止回落** |
| `/api/v3` 发布面 | 工作流 / 知识助手免登录访问者 | 无登录、无 API Key；由发布开关 + 资源状态准入 | 按 guest policy 返回 403 / 404 | **仅此面使用** |

路由层必须物理分开：`router_rpc(prefix='/api/v2', dependencies=[verify_open_api_access])` 与 `router_public(prefix='/api/v3', dependencies=[verify_public_access])` 分别注册，不通过 path if/else 在同一个依赖里分流。

### 3.2 v2 密钥请求处理管线（HTTP / WebSocket 共用）

```text
Authorization: Bearer bs-sak-… / bs-pat-…
        │
        ├─ ① 提取凭据：无头、JWT、格式非法 → 401 26001
        │
        ├─ ② 校验 api_credential：sha256 + 恒时比较 + 未撤销 + 未过期
        │      service_account → service_account 行存在、tenant 一致、未停用/删除
        │      natural_person  → User 存在、delete=0、活跃 UserTenant 与凭据 tenant 一致
        │      Redis / DB 异常 → 503 26030（fail-closed）
        │
        ├─ ③ 写租户上下文：tenant 黑名单 → current_tenant_id + visible_tenant_ids
        │
        ├─ ④ PAT 部署级 / 租户级开关：任一关闭 → 403 26040
        │
        ├─ ⑤ 读取 @open_api_scope(scope, modes, session)
        │      无标记 → 500 26031；缺权限位 → 403 26003
        │
        ├─ ⑥ 解析 X-On-Behalf-Of / X-End-User
        │      冲突、非法、强制委托漏头、端点模式不匹配 → 对应 260xx
        │
        ├─ ⑦ 构造 OpenApiPrincipal 与 PermissionActor
        │      SA 模式 S → service_account:{id}
        │      PAT 模式 S / 模式 D → user:{user_id}
        │
        ├─ ⑧ 最后使用时间节流更新
        │
        ▼
业务 Service → F048 require_business_action（读取统一 PermissionActor）
        │
        ▼
响应 / 断连后 → audit_log(action='open_api.call', metadata={actor, subject, endpoint, result…})
```

v2 WebSocket 的密钥从 `Authorization` 头读取，不接受 query 参数密钥。握手失败使用 `WebSocketException(1008)`；连接建立后每 3 秒复查凭据状态，撤销、过期、账号停用或租户停用后 5 秒内关闭。

### 3.3 独立服务账号与既有业务模型的衔接

```text
                         F048 授权主体              业务 owner / creator
SA · 自身身份        service_account:{sa_id}   resource_owner_user_id
SA · 代表他人        user:{target_user_id}      target_user_id
PAT · 自身身份       user:{holder_user_id}      holder_user_id
```

- `PermissionActor` 从只含 `user_id` 扩为 `subject_type + subject_id + tenant_id + admin facts`。用户 actor 的行为不变；服务账号 actor 的 `super_admin=False`、`tenant_admin_tenant_ids=∅`。
- OpenFGA 模型新增 `service_account` type，并把它加入业务资源直接授权关系允许的主体类型。`permission_grant_assignee.subject_type/subject_id` 已是通用列，不新增授权表。
- `canonical_source` / display name / grant mutation 支持 `service_account`，但通用“选用户/部门/用户组”接口仍不返回服务账号；服务账号授权只能从服务账号详情页发起。
- 权限运行时使用通用 `current_permission_actor` ContextVar。v2 适配器设置它；v1 JWT 未设置时仍由 `resolve_permission_actor(login_user)` 构造用户 actor。permission 模块不反向 import `open_api`。
- 模式 S 创建资源时，业务行的自然人 creator 写 `resource_owner_user_id`；同一 F048 创建计划追加一条 `subject_type='service_account'` 的可撤销回授。模式 D 不回授服务账号。
- 需要 `UserPayload` 的遗留 Service 由 v2 adapter 使用资源归属人构造兼容 payload，但权限判定只能读取 `current_permission_actor`；必须用反向测试证明归属人有权而服务账号无权时仍拒绝。
- 会话表增加 API 来源主体字段。SA 模式 S 的 `message_session.user_id` 为资源归属人（兼容既有非空列），同时写 `api_subject_type='service_account' / api_subject_id=sa_id`；v1 会话列表排除这类行，v2 列表按 API 来源主体读取，避免会话泄漏给资源归属人。模式 D / PAT 仍以自然人 `user_id` 归属，可在 v1 工作台看见。
- v2 工作流 `invoke / continue` 跨 Celery 边界时序列化 `OpenApiExecutionSnapshot`，至少包含 tenant、actor、authorization subject、业务归属人、identity mode、credential id 与 trace id，**不包含明文密钥**。worker 在任务入口设置 tenant / permission actor ContextVar，并在 `finally` 中 reset；不能只沿用现有 `user_id` 参数。v3 发布任务继续传默认操作员用户身份，但同样使用明确的 `channel='public_v3'` 快照，避免与 v2 密钥主体混淆。

### 3.4 模块图

```text
bisheng/open_api/
├─ api/
│  ├─ dependencies.py        verify_open_api_access / get_open_api_execution
│  ├─ exception_handlers.py  v2 真 HTTP 状态；WS 1008
│  ├─ middleware.py          v2 调用审计采集
│  ├─ router.py              v1 管理端点 + /api/v2/auth/whoami
│  └─ endpoints/             服务账号、密钥、授权、PAT、技能包
├─ domain/
│  ├─ scopes.py              OPEN_API_SCOPES + @open_api_scope(scope,modes,session)
│  ├─ context.py             OpenApiPrincipal
│  ├─ models/                api_credential / service_account / delegate_scope / tenant_setting
│  └─ services/              credential / service_account / identity / audit / PAT
└─ skill_packs/

bisheng/permission/           PermissionActor 与 F048 支持 service_account subject
bisheng/open_endpoints/       v2 密钥适配器；不再读取 default_operator
bisheng/public_endpoints/     v3 免登录发布适配器；只含 allowlist
bisheng/workstation/          日常模式共享 domain service
bisheng/chat_session/         会话列表 / 详情共享 domain service
bisheng/knowledge/            临时文件上传共享 domain service

platform: ServiceAccount / PersonalToken 管理页；发布 API 示例切 v3
client: PersonalTokenDialog；guest 页面 apiVersion 切 v3
```

### 3.5 关键模块职责

| 模块 | 做什么 | 不做什么 |
|---|---|---|
| `open_api/api/dependencies.py` | v2 管线唯一入口，设置 principal、tenant 与 permission actor | 不处理 v1 JWT；不允许默认操作员回落 |
| `public_endpoints/api/dependencies.py` | v3 guest 开关、资源发布状态与默认操作员解析 | 不解析 API Key / 身份传递头；不挂到 v2 |
| `credential_validator.py` | 凭据校验、主体分派、短缓存 | 不认识具体业务资源 |
| `identity_service.py` | 无品牌身份头、委托准入、执行主体构造 | 不直接查业务资源权限 |
| `call_audit_service.py` | 组装 `AuditLog` 并批量写现有表 | 不建新表；不写请求体 / 密钥 / 敏感头 |
| `permission/application/identity.py` | 为 user / service_account 生成统一 PermissionActor | 不读取服务账号业务表以外的信息来赋管理员能力 |
| v1 / v2 / v3 endpoint adapter | 校验本面的 schema，调用共享 domain service，渲染既有响应 | 不跨模块 import 别的 API 层；不内部 HTTP 转调 |

---

## 4. 工作流拆分与分工

| WS | 名称 | 交付物 | 前置 / 对接 |
|---|---|---|---|
| A | 底座 + 独立服务账号 + v2 接入 | 凭据表、独立 SA 表、F048 新主体、v2 统一依赖、端点标记、资源归属/回授、到期兜底 | 为 B/C/D/E 提供 Principal、scopes、管理 API |
| B | 管理界面（platform） | SA 列表/详情/密钥/资源授权、委托配置、PAT 台账；移除网络配置组；发布 API 示例切 v3 | 依赖 A/C/D/F 契约 |
| C | 身份传递 + 审计 | 新请求头、五道准入、委托范围、文件级过滤、裸参数收口、会话来源字段、复用 `audit_log` | 依赖 A；供 E 使用会话隔离 |
| D | 个人访问令牌 | natural_person resolver、自助/管理端点、两层开关、级联失效、技能包、client 入口 | 依赖 A/C 文件级过滤 |
| E | 日常模式 v2 | 五个 v2 端点、共享 service 提取、会话归属校验、模型/工具过滤、对外文档 | 依赖 A/C |
| F | 免登录发布面 v3 | v3 allowlist、共享 service 提取、guest policy、client/platform/gateway 路由切换 | 后端先发，前端后切 |

**关键路径**：A 的凭据 + PermissionActor → A/C 的 v2 端点接入 → E 日常模式；F 可与 C/D/E 并行，但必须按“后端 v3 先发、调用方后切”集成。

**集成里程碑**：

- M1：独立服务账号可签发密钥，`GET /api/v2/auth/whoami` 可用，数据库没有对应 `user` 行。
- M2：存量 v2 全部密钥化，模式 D 与审计可用。
- M3：v3 发布面上线并完成 guest 页面 / 发布文档 / 网关切换。
- M4：PAT 与五个日常模式 v2 端点完成。

---

## 5. 各工作流设计

### 5.A 底座、权限主体与存量 v2 接入

**A1：选择性复用 vibe-049，不整体 cherry-pick。** 可复用密钥生成、hash、掩码、撤销、短缓存、最后使用时间节流、scope 标记与大部分测试；必须排除 `user.user_type`、服务账号 User/UserTenant 建号、登录守卫、分享链路、逐调用新表和 P2 代码。采用“按目录/提交拆取后逐文件对照”的方式，避免先搬入错误数据模型再反向删除。

**A2：服务账号独立建模。** `service_account` 自己持有 `id / tenant_id / name / description / resource_owner_user_id / created_by / disabled_at / deleted_at / create_time / update_time`。创建只插这一张表；归属人必须是同租户、有效的自然人。停用 / 删除的唯一状态源是本表时间戳，随后撤销或使其名下密钥失效。`api_credential(subject_kind='service_account', subject_id=service_account.id)` 逻辑关联，不在 `user` 中造影子行。

**A3：F048 新主体。** OpenFGA authorization model 增加 `service_account`；权限 Check 使用 `service_account:{id}`。授权投影、反查、显示名和 mutation 支持该 subject type。服务账号不能成为资源 owner、租户管理员或超级管理员，只能获得资源直接授权 / 创建回授。旧 user actor 的 tuple、授权结果和 API 不变。

**A4：v2 统一依赖与端点清单。** `router_rpc` 统一挂 `verify_open_api_access`；每个路由必须有 `@open_api_scope`。`GET /api/v2/auth/whoami` 显式标 `scope=None`。现有 `/chat/{history,gen_title,liked,solved,comment,sync/messages}` 不作为密钥开放能力继续暴露；其中发布页需要的 history / gen_title 仅进入 v3。完整性测试枚举实际 `app.routes`，禁止依赖手写数量。

**A5：资源归属与回授。** 模式 S 的知识库、知识空间和文件创建路径显式接收 `resource_owner_user_id` 与 `PermissionActor`：业务 creator 写自然人归属人，F048 回授给 SA；INHERIT 型文件/文件夹不重复落本地回授，沿用父资源授权。模式 D creator=目标用户且不回授 SA。

**A6：异步身份传递。** 改造 `execute_workflow / continue_workflow` 的任务载荷，使 v2 传 `OpenApiExecutionSnapshot` 而不是把资源归属人的 `user_id` 当作调用身份。任务入队前完成密钥和资源权限检查，worker 仍用快照恢复租户与 F048 actor，并对实际读取/执行动作再次授权；快照里的 `credential_id` 仅用于审计关联，不允许 worker 凭此绕过主体状态或权限检查。

### 5.B 管理界面（platform）

**B1：页面结构。** 系统管理提供“服务账号”和“个人访问令牌”两个同级入口。服务账号详情含概览、API 密钥、资源授权；PAT 台账与开关不放进某个服务账号详情。实现前以 `src/frontend/packages/ui/docs/` 当前规范和 landed 组件为准；platform 沿用自己的 Zustand、request wrapper 与 bs-ui，不混用 client 技术栈。

**B2：密钥表单只有三组。** 基本信息、权限位、委托配置。原“网络”组及 IP 白名单 / 限流 / 日配额字段全部删除。委托范围为空不能保存；`delegate` 与未部署的扩展位保持互斥。

**B3：资源授权。** 服务账号详情页调用主体侧授权接口，mutation 固定写 `subject_type='service_account' / subject_id=sa_id`；通用用户选择器不增加服务账号。来源列区分管理员授予与创建回授，“全部撤销”不删除保障当前集成继续访问父资源所需的回授行。

**B4：发布文档。** `ApiAccess.tsx`、`ApiAccessFlow.tsx` 等“对外发布、无需密钥”的示例统一改 `/api/v3`。密钥开放 API 文档继续使用 `/api/v2`，示例必须携带 `Authorization: Bearer <key>`，两者不得出现在同一个无鉴权示例里。

### 5.C 身份传递、文件过滤与审计

**C1：请求头与模式分流。** 管线只读取 `X-On-Behalf-Of` 与 `X-End-User`。旧品牌头即使单独出现也返回 400，错误信息指向新头，不做兼容别名，避免迁移期同一请求出现两个真相。OBO 值只接受用户 ID；End-User ≤128 字节且为可打印 ASCII。

**C2：委托范围。** 使用独立表 `api_credential_delegate_scope`，支持 user / department 条目。编辑密钥去掉 `delegate` 时同事务清空范围。user 条目只需验证目标存在于 `User`、`delete=0` 且同租户活跃；服务账号不存在于 User，因此无需 `user_type` 判断。department 子树在调用期按物化路径展开。

**C3：五道准入。** 依次检查：①凭据有 `delegate`；②目标 User 存在、启用、同租户；③目标不是超级管理员 / 租户管理员；④目标命中委托范围；⑤端点允许 D。失败分别落 `26004 / 26005 / 26007 / 26004 / 26006`。全部通过后，授权主体直接改为 `user:{target_id}`。PAT 携带 OBO 在检查 ① 前拒绝。

**C4：裸参数收口与检索过滤。** 原 v2 `filelib` 的裸 `user_id` 和 `/assistant/list` 死参数一律拒绝并指向 `X-On-Behalf-Of`。`POST /filelib/retrieve` 两个召回分支都执行文件级 prefilter + post-filter；权限服务异常向上返回 503，不能降级成全量结果。

**C5：逐调用审计复用 `audit_log`。** ASGI 中间件只包 v2 密钥面，响应或 WS 终止后向进程内有界队列写标准 `AuditLog` 对象；flusher 调用现有 `AuditLogDao.ainsert_audit_logs` 批量写现有表。映射如下：

- `action='open_api.call'`；`target_type='api_endpoint'`；`target_id` 使用路由模板（如 `POST /api/v2/filelib/retrieve`）；
- `tenant_id / operator_tenant_id` 均为密钥租户；PAT 的 `operator_id=holder_user_id`，SA 的 `operator_id=0`、`operator_name=service_account.name`；
- Python 字段 `audit_metadata`（数据库 JSON 列 `metadata`）保存 `credential_id / actor_kind / actor_id / identity_mode / authorization_subject_type / authorization_subject_id / on_behalf_of_user_id / end_user_id / scope / http_status / error_code / latency_ms / trace_id`；
- `ip_address` 使用现有列；不写 Authorization、原始请求体、文件内容或其它请求头；
- `open_api.call` 不加入旧“系统操作”页面白名单，避免高频调用淹没管理操作；需要查询时走结构化 action 查询；
- 不新增独立清理任务，保留期跟随项目统一审计数据策略。队列满或批量写失败时记录 `open_api.audit.write_failed` 结构化日志，不影响业务响应。

依赖同时把 principal 写入 ContextVar 与 `conn.scope['open_api_principal']`，外层 ASGI 中间件从 scope 读取，规避 ContextVar 子任务回传问题。

**C6：会话来源与隔离。** `message_session` 增加 `api_subject_type / api_subject_id / external_user_id`。模式 S 的 SA 会话按 `(tenant_id, service_account, sa_id, end_user_id)` 隔离；未传 End-User 时按 SA 粒度并记录 WARN。模式 D / PAT 以自然人归属。`chat/list`、`chat/info`、续聊和附件归属校验使用同一规则，不只比较兼容字段 `user_id`。

### 5.D 个人访问令牌

**D1：主体与校验。** `subject_kind='natural_person'`、前缀 `bs-pat-`，`subject_id=user_id`。resolver 校验 User 存在、`delete=0`、活跃租户与凭据 tenant 一致，再加载角色与管理员事实；不读取 `user_type`。可见租户集合始终按密钥租户限制，不因持有人是超管而放开跨租户过滤。

**D2：一人一把与权限白名单。** 获取新 PAT 时撤销旧 PAT；员工删除、管理员吊销、用户禁用/删除/换租户均主动失效。权限位本期固定 `knowledge:read`，不支持 delegate。管理员持有人按既有 PRD 规则警示并收紧 TTL。

**D3：两层开关。** 部署级 `open_api.pat_enabled=false` 与租户级 `open_api_tenant_setting.pat_enabled=false` 均默认关闭；关闭只让校验拒绝，不改撤销位，重新开启可恢复未过期令牌。

**D4：端点与技能包。** 员工面 `/api/v1/me/api-token`（状态 / 获取或重签 / 删除 / install-prompt）走 JWT；管理员面 `/api/v1/personal-tokens` 走管理员鉴权；技能包下载端点沿用匿名分发。技能包文档使用新身份头名称，API Key 环境变量仍可沿用 `BISHENG_API_KEY`，因为本裁定只去除 HTTP 请求头中的品牌字样。

### 5.E 日常模式会话开放

**E1：按 v1 原路径增加五个 v2 端点。** 不再设计 `/workbench/chat`、`/workbench/turns`、`/workbench/files`，也不发明另一套事件格式。

| v2 端点 | 复用来源 | scope | v2 行为差异 |
|---|---|---|---|
| `POST /api/v2/workstation/chat/completions` | `/api/v1/workstation/chat/completions` | `chat:invoke` | 只允许日常模式；对外请求以 `APIChatCompletion` 为底稿删除 `use_knowledge_base`、`task_mode`，保留 `files`，返回原 SSE |
| `GET /api/v2/workstation/config` | `/api/v1/workstation/config` | `chat:invoke` | 只返回 `models[]`、`tools[]`，工具按密钥执行主体权限过滤 |
| `GET /api/v2/chat/list` | `/api/v1/chat/list` | `chat:invoke` | 按 §5.C.6 的 API 会话主体列举 |
| `POST /api/v2/knowledge/upload` | `/api/v1/knowledge/upload` | `chat:invoke` | 复用 multipart 限制与 `UploadFileResponse`，文件绑定当前调用主体 |
| `GET /api/v2/chat/info?chat_id=` | `/api/v1/chat/info?chat_id=` | `chat:invoke` | 校验 chat_id 归属后返回同形状信封 |

**E2：只替换认证适配，不改 v1。** 五个 v1 端点的当前登录/匿名语义原样保留；五个 v2 端点不声明 `Depends(UserPayload.get_login_user)`，也不读 cookie/JWT，只消费 `get_open_api_execution`。即使调用方已登录，缺少 `bs-*` 密钥仍返回 401；有密钥但没有 JWT 可以正常调用。

**E3：共享业务实现。** 将端点内编排下沉或复用已有 domain service：聊天调用 `workstation.domain.services.chat_service.stream_chat_completion`，配置调用 `WorkStationService`，会话调用 `ChatSessionService`，上传调用 `KnowledgeService` / storage helper。v2 adapter 把对外请求转换成内部 `APIChatCompletion` 时固定写入 `task_mode=False`、`use_knowledge_base=None`；`files` 原样保留并继续使用 `/api/v2/knowledge/upload` 返回的文件引用。v2 adapter 禁止 import `bisheng.workstation.api.*`、`bisheng.chat_session.api.*` 或 `bisheng.knowledge.api.*`，也禁止内部 HTTP 转调 v1。

**E4：对外请求收窄。** 新建 `OpenDailyChatCompletionReq` 作为 v2 请求模型，其字段等于当前 `APIChatCompletion` 去掉 `use_knowledge_base`、`task_mode` 后的集合；`files` 仍在对外模型中，日常对话继续支持临时文件附件，但不支持选择个人知识库、组织知识库或知识空间。对外 schema 使用 `extra='forbid'`：调用方传 `use_knowledge_base` 返回 400；传任何 `task_mode` 值均返回 400，要求任务模式时使用 `26017`。端点内部不读取调用方的运行模式，调用共享服务前无条件补 `task_mode=False`，所以外部请求无法切入灵思任务分支。

**E5：返回与其它拒绝规则。** chat/completions 的 SSE 顺序和持久化结果与 v1 保持一致。若调用方传入已知异步意图字段则返回 `26015`，其它契约外字段 400，不能静默忽略。配置端点不得透出 `linsightConfig`、邀请码、部署专属字段等非开放信息。

### 5.F 工作流 / 知识助手免登录发布面 v3

**F1：v3 allowlist。** 以下路由从当前 v2 免登录实现迁移为 v3；相同业务能力的 v2 路由保留为密钥鉴权版本。除下表外不注册其它 v3 路由。

| v3 免登录端点 | 用途 | 对应 v2 密钥端点 |
|---|---|---|
| `POST /api/v3/workflow/invoke` | 发布工作流执行 | `/api/v2/workflow/invoke` |
| `POST /api/v3/workflow/stop` | 停止本发布会话 | `/api/v2/workflow/stop` |
| `WS /api/v3/workflow/chat/{workflow_id}` | 发布工作流对话 | `/api/v2/workflow/chat/{workflow_id}` |
| `POST /api/v3/assistant/chat/completions` | 发布知识助手 Chat Completions | `/api/v2/assistant/chat/completions` |
| `GET /api/v3/assistant/info/{assistant_id}` | 发布页助手详情 | `/api/v2/assistant/info/{assistant_id}` |
| `WS /api/v3/assistant/chat/{assistant_id}` | 发布知识助手对话 | `/api/v2/assistant/chat/{assistant_id}` |
| `GET /api/v3/flows/{flow_id}` | 发布页工作流详情 | `/api/v2/flows/{flow_id}` |
| `GET /api/v3/chat/history` | 发布页当前会话历史 | v2 不开放此端点 |
| `POST /api/v3/chat/gen_title` | 发布页会话标题 | v2 不开放此端点 |

`GET /assistant/list` 不是单个已发布资源所需能力，不进入 v3；它只保留 v2 密钥版本。

**F2：guest policy。** v3 不校验 JWT 和 API Key，统一校验 `default_operator.enable_guest_access=true`、默认操作员存在且启用、目标工作流/助手处于可发布状态。初次定位资源允许在受控 bypass 中按 ID 查询，随后必须设置资源所属 tenant ContextVar 再进入业务 Service。任一 `X-On-Behalf-Of` / `X-End-User` 头均拒绝，防止匿名调用方伪造身份。

**F3：会话绑定。** v3 创建的会话标记 `api_subject_type='public_v3'`，并绑定资源 ID / 默认操作员；history、gen_title、stop、续聊都校验该来源与资源匹配。不得仅凭随机 chat_id 读取或停止其它 v1/v2 会话。

**F4：代码复用和切换。** v2/v3 endpoint 只做各自鉴权和 schema 适配，工作流/助手执行逻辑下沉到共享 domain service。client guest 模式 `apiVersion` 类型扩为 `v1 | v2 | v3` 且取 `v3`；platform 两个发布 API 页面改 v3；商业网关中显式代理/拦截的 assistant、workflow、chat 路径同步增加 v3。现有分享链接代码、URL 参数与 header 不在此工作流修改。

---

## 6. 共享契约

### 6.1 `OpenApiPrincipal`

```python
class OpenApiPrincipal(BaseModel, frozen=True):
    credential_id: int
    actor_kind: Literal["service_account", "natural_person"]
    actor_id: int                         # SA id 或 PAT holder user_id
    actor_name: str
    tenant_id: int
    resource_owner_user_id: int | None   # 仅 SA
    scopes: frozenset[str]
    mode: Literal["S", "D"] = "S"
    authorization_subject_type: Literal["service_account", "user"]
    authorization_subject_id: int
    effective_user_id: int | None         # SA 模式 S 为 None；PAT / D 为自然人 id
    on_behalf_of_user_id: int | None = None
    end_user_id: str | None = None
```

`verify_open_api_access` 同时写 `current_open_api_principal`、`conn.scope['open_api_principal']` 与 permission 层的 `current_permission_actor`。业务代码不得从 `resource_owner_user_id` 反推授权主体。

跨进程任务使用 `OpenApiExecutionSnapshot`，它是 `OpenApiPrincipal` 的最小可序列化投影：保留 `tenant_id / actor_kind / actor_id / authorization_subject_type / authorization_subject_id / resource_owner_user_id / effective_user_id / mode / credential_id / trace_id / channel`，去掉 scopes 以外的凭据材料。`channel` 仅允许 `open_api_v2 | public_v3`；worker 根据 channel 恢复对应执行上下文，不能执行 HTTP 层的 JWT、API Key 或 guest fallback。

### 6.2 路由与鉴权契约

| 面 | 端点 | 鉴权 |
|---|---|---|
| v2 密钥面 | 现有 knowledge / filelib / citation / llm / flow / assistant / workflow 开放端点（排除旧 chat 六端点） | API Key + scope + S/D |
| | `GET /api/v2/auth/whoami` | API Key，`scope=None` |
| | §5.E 五个日常模式端点 | API Key + `chat:invoke` + S/D |
| v3 发布面 | §5.F 九个 allowlist 端点 | 无 JWT / 无 API Key；guest policy |
| v1 管理面 | `/service-accounts/**`、`/personal-tokens/**` | JWT + 租户管理员及以上 |
| v1 员工面 | `/me/api-token/**` | JWT |
| v1 站内与分享 | 所有既有接口 | **保持现状** |

v2 请求头只有：`Authorization: Bearer <key>`、`X-On-Behalf-Of: <user_id>`、`X-End-User: <≤128 可打印 ASCII>`。本期没有 `Idempotency-Key` 或限流响应头契约。

### 6.3 错误码分配（模块 260）

| 段 | 码 | 含义 | HTTP |
|---|---|---|---|
| v2 凭据 | 26001 缺少/非法密钥 · 26002 无效/撤销/过期 · 26003 缺权限位 · 26030 依赖不可用 · 26031 端点未登记 | 401 / 401 / 403 / 503 / 500 |
| 身份传递 | 26004 未授予委托/不在范围 · 26005 委托目标无效 · 26006 端点不支持代表模式 · 26007 目标为特权主体 · 26010 身份头冲突 · 26016 持 delegate 漏头 · 26018 End-User 非法 · 26019 裸 `user_id` 或旧品牌头已移除 | 403 / 403 / 403 / 403 / 400 / 400 / 400 / 400 |
| 日常模式 | 26015 异步未开放 · 26017 任务模式未开放 | 400 / 400 |
| PAT | 26040 能力未开启 · 26041 权限位不在白名单 · 26042 有效期超上限 · 26043 持有人失效 | 403 / 400 / 400 / 401 |
| 管理面 | 26020 账号不存在 · 26021 归属人/委托目标无效 · 26022 禁止操作 · 26023 扩展位未部署 · 26024 委托配置无效 · 26025 未知权限位 · 26026 密钥不存在 · 26027 账号停用 · 26029 服务账号不能作为资源 owner | v1 信封 |
| 预留 | 26008 / 26009 / 26011 / 26012 / 26013 / 26014 / 26028、26032～26039、26044～26049 | 不在本期复用 |

三语文案只落 `src/frontend/packages/locales/src/api_errors/*.json`，生成物由脚本产生。

### 6.4 数据契约

| 对象 | 字段 / 变化 |
|---|---|
| `service_account` | `id · tenant_id · name · description · resource_owner_user_id · created_by · disabled_at · deleted_at · create_time · update_time`；不关联 User |
| `api_credential` | 凭据 hash / prefix / mask / subject_kind / subject_id / scopes / expires / revoked / last_used 等底座字段；`subject_kind∈{service_account,natural_person}`；无 P2 字段 |
| `api_credential_delegate_scope` | `id · tenant_id · credential_id · subject_type(user|department) · subject_id · create_time`；唯一键覆盖 credential/type/id |
| `open_api_tenant_setting` | `tenant_id PK · pat_enabled · pat_ttl_days · update_time` |
| `message_session` 增列 | `api_subject_type VARCHAR(32) NULL · api_subject_id BIGINT NULL · external_user_id VARCHAR(128) NULL`；索引 `(tenant_id, api_subject_type, api_subject_id, update_time)` |
| `audit_log` | **无 DDL**；逐调用数据按 §5.C.5 写现有公共列 + `metadata JsonType` |
| Settings | `open_platform.enabled`、`open_api.credential_cache_ttl_seconds`、`open_api.service_account_idle_days`、`open_api.pat_enabled`、`open_api.pat_admin_ttl_days`；保留现有 `default_operator.enable_guest_access` 给 v3 |
| Redis | `oapi:cred:{sha256}` · `oapi:cred:lastused:{id}` · `oapi:tenant:{tid}:pat`；无 rate/quota/idempotency key |
| 审计 action | `open_api.call`、`open_api.service_account.*`、`open_api.api_key.*`、`open_api.grant.*`、`open_api.pat.*` |

### 6.5 外部依赖与风险点

| 依赖 | 谁用 | 风险 |
|---|---|---|
| OpenFGA F048 authorization model + grant projection | A | 漏加某资源关系的 `service_account` 允许类型会导致 SA 已授权但恒拒；需模型契约测试覆盖全部 registry 类型 |
| `current_permission_actor` | A/C/E | 清理不当会在连接复用中串身份；请求 / WS 生命周期必须 token reset |
| Celery 工作流任务载荷 | A/F | 现状只传 `user_id`，无法表达 SA 主体；改为执行快照并在 worker `finally` reset tenant / actor ContextVar |
| `AuditLogDao` 与 `audit_log.metadata JsonType` | C | 批量 API 必须兼容 MySQL / DM8；不能用 JSON SQL 表达式做核心鉴权 |
| `KnowledgeFileVisibilityService` | C/D | 异常若被吞会扩大检索结果，必须反向测试 fail-closed |
| `WorkStationService` / `stream_chat_completion` | E | v1 活跃功能，抽共享 service 后必须保证 v1 SSE 零变化 |
| `ChatSessionService` / `MessageSessionDao` | C/E/F | 只按 `user_id` 校验会把 SA 或 public_v3 会话误归属给默认/归属用户 |
| `default_operator` 配置 | F | 只允许 v3 使用；静态检查禁止 v2 endpoint import `get_default_operator*` |
| client guest `apiVersion` 与 platform 发布示例 | F | 后端未先发 v3 即切前端会导致发布页白屏 |
| 商业网关路由 | F | 仍只代理 v2 时 v3 WS/HTTP 在商业版 404 或被登录网关拦截 |

---

## 7. 数据模型与权限模型变更

### 7.1 Alembic

| revision（命名） | DDL | WS |
|---|---|---|
| `v3_0_0b1_f053_api_credential_tables` | 建 `api_credential`、独立 `service_account`；不改 `user` / `user_tenant` | A |
| `v3_0_0b1_f053_delegate_scope_and_session_subject` | 建委托范围表；`message_session` 加 API 来源主体与外部用户标识列/索引 | C |
| `v3_0_0b1_f053_pat_tenant_setting` | 建 `open_api_tenant_setting` | D |

明确不存在以下 revision：`user_user_type`、`open_api_call_log`、credential P2 columns、`share_link` scope。

全部 revision 只做 DDL、不做数据回填；`VARCHAR` 不用 `CHAR`；JSON 用 `JsonType`；新租户表注册到 tenant-aware model 模块。当前功能尚未落表，因此没有服务账号 User 行的迁移/清理任务。

### 7.2 OpenFGA 模型

新增 `service_account` type，并将其加入各业务资源可直接授权关系的 `directly_related_user_types`。发布模型前运行 schema contract：registry 中每个支持直接授权的资源类型都允许 `service_account`，owner / tenant admin / super admin 关系均不允许。模型升级是向后兼容添加，不重写既有 user / department / group tuple。

---

## 8. 已知坑 / 反直觉事实

| # | 事实 | 处理 |
|---|---|---|
| 1 | 同一路径能力会同时存在 v2 密钥版与 v3 免登录版 | 物理分 router；路由枚举测试同时断言 auth dependency |
| 2 | 登录 JWT 与 API Key 都可能占用 Authorization Bearer | v2 只接受 `bs-sak-` / `bs-pat-` 前缀；JWT 一律 26001 |
| 3 | 服务账号 id 与 user_id 都是整数，数值可能碰撞 | 所有授权、缓存、审计和会话键都使用 `(subject_type, subject_id)`，不得裸用 id |
| 4 | 资源归属人有真实 UserPayload，但不是 SA 的授权身份 | permission actor ContextVar 优先；反向测试“owner 有权、SA 无权”必须拒绝 |
| 5 | `User` 中不再有服务账号 | 自然人判断不需要 `user_type`；任何服务账号筛选/登录守卫代码都是错误移植 |
| 6 | v1 会话列表按 `user_id`，SA 会话兼容写资源归属人 | v1 列表排除 `api_subject_type='service_account'`；v2 按来源主体查 |
| 7 | ASGI 外层读不到依赖子任务写回的 ContextVar | principal 同时写 `conn.scope`，审计从 scope 取 |
| 8 | `/api/v1/workstation/config` 含部署配置，不全是模型/工具 | v2 明确投影只返回 `models` / `tools` |
| 9 | `clientTimestamp` 是 v1 schema 的历史必填字段 | v2 既然复用契约就保持一致；不得另造字段映射或悄悄补值 |
| 10 | v3 无 JWT 时中间件不会自动建立租户 ContextVar | guest resolver 受控查询资源后显式设置 tenant，再进入业务查询 |
| 11 | v3 history / gen_title 当前只靠 chat_id 容易越界 | 增加 `public_v3` 会话来源校验并绑定资源 |
| 12 | client guest 页面除 WS 外还会请求 flow/info/history/title | v3 allowlist 必须覆盖完整调用图，端到端验证浏览器 Network |
| 13 | commercial gateway 目前显式写有 v2 assistant/chat 规则 | v3 HTTP + WS 路由必须同步调整并做商业版回归 |
| 14 | 平台全局 HTTP handler 会把部分异常压成 200 信封 | v2 新异常继承 `OpenApiAuthError` 并返回真实 401/403/500/503；v3 沿用发布面既有形状 |

---

## 9. 测试策略与验收映射

**分层**：单元测试 `test/open_api/`；HTTP / WS 集成测试；MySQL + Redis + OpenFGA CI；DM8 105 回归；最后运行 `/e2e-test`。重点不是手写端点数，而是从 `app.routes` 生成实际清单。

| 范围 | 关键用例 |
|---|---|
| 三面隔离 | v1 JWT 正常；v2 已登录但无 key 仍 401；v2 只有 key 可调用；v3 无 JWT/key 可访问已发布资源；v3 不接受身份传递头 |
| 独立 SA | 创建 SA 后 User/UserTenant 行数不变；两 SA id 与 user id 碰撞不串权；SA 无 admin shortcut；停用/删除 5 秒内失效 |
| F048 | direct grant / revoke / create autogrant；owner 有权而 SA 无权仍拒；模式 D 不使用 SA grant |
| 异步身份 | v2 SA / PAT / D 三类快照往返后 actor、tenant 不变；队列载荷无明文 key；worker 串行处理两个 tenant 后 ContextVar 不串；v3 快照不能进入 v2 分支 |
| 身份传递 | 五道准入逐条；新头有效；旧品牌头拒绝；裸 user_id 拒绝；文件级过滤异常 503 且无数据 |
| 审计 | `audit_log.action='open_api.call'`；metadata actor/subject 双归属完整；无密钥/请求体；SA operator_id=0；DM8 可批量写 |
| PAT | 一人一把、两层开关、级联失效、只 knowledge:read、超管不跨 tenant、OBO 拒绝 |
| 日常模式 | 五个 v2 端点复用 v1 业务/信封/SSE；请求 schema 删除 `use_knowledge_base`、`task_mode` 但保留 `files`；内部固定 `task_mode=False`；config 只有 models/tools；SA/PAT/D 会话归属矩阵；跨主体 chat/file 统一 404 |
| v3 发布面 | 九路由 allowlist；未发布/开关关拒绝；两个 WS 正常；history/title/stop 不能跨资源；`/api/v3/assistant/list` 真 404 |
| 前端/网关 | guest 页面所有 v3 HTTP/WS 无 v2 遗留；发布示例为 v3；密钥文档为 v2；商业网关可转发 v3 WS |

**手动验证**（`$BASE` 为实例地址）：

```bash
# v2：登录态不能替代密钥；服务账号密钥可用
curl -s -o /dev/null -w '%{http_code}\n' "$BASE/api/v2/auth/whoami"                    # 401
curl -s -H "Authorization: Bearer $SAK" "$BASE/api/v2/auth/whoami"                    # 200

# 新身份头
curl -s -H "Authorization: Bearer $SAK" -H "X-On-Behalf-Of: $USER_ID" \
  "$BASE/api/v2/filelib/"                                                               # 按委托规则
# 旧品牌身份头或裸 user_id → 400 26019

# 日常模式：五个 v2 端点只需密钥，不需 JWT
curl -s -H "Authorization: Bearer $SAK_CHAT" "$BASE/api/v2/workstation/config"         # data 仅 models/tools
curl -N -H "Authorization: Bearer $SAK_CHAT" -H 'Content-Type: application/json' \
  -d '{"clientTimestamp":"2026-09-04T00:00:00Z","model":"<id>","text":"你好"}' \
  "$BASE/api/v2/workstation/chat/completions"                                            # 与 v1 同形 SSE
curl -s -H "Authorization: Bearer $SAK_CHAT" "$BASE/api/v2/chat/list?page=1&limit=10"

# v3：发布面无 key；v2 同能力仍要求 key
curl -s "$BASE/api/v3/assistant/info/$ASSISTANT_ID"                                       # 已发布且 guest 开关开 → 200
curl -s -o /dev/null -w '%{http_code}\n' "$BASE/api/v2/assistant/info/$ASSISTANT_ID"     # 401

# 审计写现有表
# SELECT action, operator_id, metadata FROM audit_log WHERE action='open_api.call' ORDER BY create_time DESC;
```

**可观测**：`open_api.call` 结构化日志、`open_api.auth.reject{code}`、`open_api.audit.write_failed`、`public_api.reject{reason}`、WS 关闭原因。不再定义 P2 相关指标。

---

## 10. 发布与升级

1. 执行 §7 三个 Alembic revision；无需 `user`、审计表或分享表备份/变更。
2. 先发布向后兼容的 OpenFGA `service_account` 模型，再部署后端；在模型就绪前保持服务账号签发入口关闭。
3. 先上线 v3 后端九个路由并验证 HTTP / WS，再切 client guest、platform 发布示例和商业网关；旧 v2 发布 URL 在同一版本移除免登录语义，不能继续匿名调用。
4. v2 发布后不再读取 `default_operator`；v3 继续依赖 `default_operator.enable_guest_access`。升级说明必须把两者写成不同通道。
5. 对客文档分别成章：v2 密钥开放 API（含新身份头）与 v3 免登录发布 API。不得宣称“所有 `/api/v2/**` 都可匿名”，也不得要求 v3 携带 API Key。
6. 最小可发版集为 A + C + F；B 缺失时不建议对外启用服务账号，E/D 可在同版后续里程碑启用。

---

## 11. 后续 / 不做

- R8 / P2 的 IP 白名单、限流、配额、幂等均不做，也不预埋字段、Redis key 或错误处理分支。
- 现有分享链接实现和数据模型不改；其后续治理单独立项，不与 v2/v3 分面绑定。
- 任务模式、异步作业、按轮结果新契约不做；日常模式只复用现有同步链路。
- 密钥级资源白名单、OAuth 授权服务器、Webhook 回调鉴权、企业网关签发令牌不做。
- 日常模式反馈、消息回填等未列入 §5.E 的接口不开放。
- 日常对话支持临时文件附件，但不开放 `use_knowledge_base`，不能从请求中选择个人知识库、组织知识库或知识空间；`task_mode` 也不是对外字段，内部恒为 `False`。
- 与 `3.0-vibe` 合并时以 §2.1 为差异清单，禁止把 User 影子账号、分享凭据或 P2 代码重新带入。

---

## 修订历史

| 日期 | 改动 | 触发 |
|---|---|---|
| 2026-08-31 | 初版：P0 + P1 + P2、7 工作流 | 初始总体设计 |
| 2026-08-31 | `/sdd-review design` 自查修订 | 初版评审 |
| 2026-09-04 | 重写：移除 R8/P2 与分享链路改造；请求头去品牌；审计改复用 `audit_log.metadata`；服务账号改独立主体且不写 User；日常模式改为五个 v1 同路径 v2 接口；工作流/知识助手免登录发布接口迁至 v3，与 v2 密钥面彻底分离 | 用户新范围裁定 |
| 2026-09-04 | 收窄日常对话请求：对外删除 `use_knowledge_base`、`task_mode`，内部固定 `task_mode=False`；`files` 与临时文件上传能力保持不变 | 用户补充裁定 |

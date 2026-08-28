# 设计说明：可复用角色「平台管理员」（运营岗，非超管）

跨仓（毕昇写模型 + 门户消费）。需求已确认后再实现；本文是实现权威。

## 1. 目标、非目标、取舍

### 目标

新增可复用 RBAC 角色，显示名固定为 **`平台管理员`**。持有该角色的用户：

- 前台当普通登录用户使用；
- 拥有门户管理端下列 **11 项**模块的入口与写权限（见下表）；迁移为全库；
- 不能进门户管理整组、课程、审批、系统管理，也不能从毕昇管理后台直进看板/标签/审查；
- 积分规则/调账/字典等写接口放行，但 **`is_admin()` 仍为 false**（不是超管）。

真超管（RBAC `AdminRole=1` / `is_global_super`）行为不变。

### 平台管理员拥有的管理端模块（11 项）

这 11 项是允许名单的完整集合：菜单要显示，对应接口要放行。不在此列的管理端模块一律不能进（入口隐藏 + 403）。

1. **数据看板**（`platformDashboard`）— 门户 iframe `/platform/standalone/dashboard`
2. **积分管理**（`points`）— 改规则、调账、扣分、运营查询；不含专家问答违规删除
3. **问答配置**（`qa`）
4. **写作模板**（`qaTemplates`）
5. **应用配置**（`agentConfig`）
6. **知识分类**（`documentTypes`）
7. **水印设置**（`watermark`）
8. **字典配置**（`dictConfig`）
9. **内容与安全审查**（`platformContentSecurity`）— 门户 iframe `/platform/standalone/content-security`
10. **标签管理**（`platformTagLibrary`）— 门户 iframe `/platform/standalone/knowledge-tag-library`
11. **迁移记录 / 新建迁移** — Header 入口 + 路由 `/knowledge-migrations`；全库；不是 `NAV_GROUPS` 的 nav key，资格用 `canViewMigrations`

不在这 11 项内、平台管理员不能进的管理端模块：首页导航/分区/轮播/展示/搜索/知识推荐策略、课程管理、业务域映射绑定、自动发布、科室知识库绑定、审批管理、系统管理（站点/数据源/集成/统一认证/审计/系统配置）、回收站、毕昇管理后台外链、公开发现开关、用户/角色、专家问答违规删除。

### 非目标（本期不做）

- 不新建门户角色表、不新增 `role` 列、不做 Alembic 插角色种子（超管在角色管理创建一条即可）。
- 不把「平台管理员」加入现有整页白名单 `{管理员, 系统管理员, admin}`。
- 不给该角色毕昇管理端 WEB_MENU；不开放 `LoginUser.get_admin_user()` / `get_tenant_admin_user()` 给该角色。
- 不改公开发现开关、回收站、专家问答违规删除、用户/角色管理、全库知识空间管理。
- 不做按知识库收窄的迁移范围（已拍板：与超管一样全库）。
- 不引入 OpenFGA 新 relation；不改多租户注入。

### 关键决策

| 决策 | 选定 | 否决 | 原因 | 何时可推翻 |
|---|---|---|---|---|
| 身份载体 | 毕昇 `role.role_name` 精确等于 `平台管理员` | 账号白名单；把人设成 `AdminRole`；门户独立角色表 | 需求是可复用角色；`is_admin()` 会打开全部超管能力 | 要稳定 ID 不随改名失效时，再加 `role_type`/`code` 列（需 DDL） |
| 鉴权形状 | 入口隐藏 + 对应接口 403 | 只藏菜单 | 用户已选 B | 无 |
| 门户 `/admin` | 模块级允许名单，与整页 `isPortalAdmin` 拆开 | 把该名塞进 `ADMIN_ROLES` | 塞进去会打开门户管理/课程/审批/系统管理 | 无 |
| 内嵌三页 | 只放行 `/standalone/{dashboard,knowledge-tag-library,content-security}` | 给管理端 WEB_MENU；放行全部 `/standalone/*` | 只要门户 iframe；`/standalone/approval` 与 `/standalone/sys` 必须进不去 | 产品允许从毕昇后台进这三页时 |
| 配置写路径 | 门户文档（问答/模板/应用/分类/水印）在 **BFF 按 path 鉴权**，下游仍用服务账号调毕昇 `get_admin_user` | 把 `get_admin_user` 扩成运营身份 | 扩了之后用户可直打毕昇 `PUT /shougang-portal/config` 改首页导航等 | BFF 不再用服务账号写配置时必须重做 |
| 积分/迁移/字典/看板/标签/敏感词 | 毕昇服务认「超管 ∪ 平台管理员」 | 继续只认 `is_admin()` | 这些接口走用户 Cookie（`/workspace/api`），不经过 BFF 整页闸门 | 无 |
| 角色名唯一 | 同一租户内该保留名全局唯一（跨 `role_type`/`department_id`）；禁止改名/删除该名角色 | 只靠现有 scope 唯一约束 | 现网唯一键是 `(tenant_id, role_type, role_name, department_scope_key)`，部门范围下可再插同名 | 产品允许同名部门角色时 |

---

## 2. 术语对照（中文名 ≠ 超管）

| 产品称呼 | 代码身份 | 判定 |
|---|---|---|
| 系统超管 / 真超管 | RBAC `AdminRole`（`role.id=1`）或 FGA `is_global_super` | `LoginUser.is_admin()` 或 `is_global_super`。`/user/info.role` 为 `admin` |
| 门户整页管理员 | 角色名 `管理员` / `系统管理员`，或账号 `admin` | 门户 `isPortalAdmin` / BFF `require_admin_session`。**不包含**「平台管理员」 |
| 系统管理员（迁移 Header 旧逻辑） | `role ∈ {系统管理员, admin}` | 现 `isSystemAdministrator`。本期改为：超管 ∪ 平台管理员 可进迁移 |
| **平台管理员（运营岗）** | `role.role_name == "平台管理员"` | 下文 `has_platform_operator_role`。`is_admin()` 必须仍为 false |
| 运营写资格 | 超管 ∪ 平台管理员 | `can_platform_operate`。只用于允许名单内的模块，不用于审批/系统管理 |

常量（唯一事实源，两仓拷贝同一字面量）：

```text
PLATFORM_OPERATOR_ROLE_NAME = "平台管理员"
```

匹配：去首尾空白后 **全等**。大小写敏感（中文无 case）。不得用 `includes("管理员")`。

---

## 3. 持久化

无 DDL、无字段增删改、不做迁移。不涉及对象存储新桶。

### 3.1 身份（毕昇）

| 表 | 角色 | 关键已有字段 | 结构 |
|---|---|---|---|
| `role` | 读；超管创建/绑菜单时写 | `id`, `role_name`, `role_type`, `department_id`, `tenant_id`, `remark` | 无变更 |
| `userrole` | 读；超管给人绑角色时写 | `user_id`, `role_id`, `tenant_id` | 无变更 |
| `roleaccess` | 旁路：保存该角色 WEB_MENU 时读/写并 **剥离管理端 key** | `role_id`, `third_id`, `type`（WEB_MENU=99） | 无变更 |
| `user` | 旁路读（会话） | `user_id`, `user_name` | 无变更 |

运营资格 **不** 写入 JWT。每次请求 `init_login_user` 已装 `role_names`（现网已有），用列表判定即可。改名/解绑下一请求生效。

保留名规则（服务层，非新唯一索引）：

- 创建或改名目标为 `平台管理员`：该 `tenant_id` 下已有任一行同名 → `RoleNameDuplicateError`（24002）。
- 已有 `role_name=平台管理员` 的行：禁止改名、禁止删除（复用 `RoleBuiltinProtectedError` 24004 或同语义新码，见契约）。可改 remark、可改 WEB_MENU（保存时剥离管理端）、可继续绑人。

超管操作：在角色管理 **创建一条** 该名角色，给账号绑定；账号同时保留「普通用户」(`DefaultRole=2`) 以便前台/工作台。本期不自动 insert。

### 3.2 业务写（沿用现表，资格放宽）

| 表 | 角色 | 关键字段 | 结构 |
|---|---|---|---|
| `user_point_account` / `user_point_log` / `point_rule` / `point_copy` / `point_rank_snapshot` / `point_favorite_tier_award` / `point_pending_deduct` / `point_sync_outbox` | 积分管理读写，与现超管相同 | 现有规则/调账/流水列 | 无变更 |
| `knowledge_migration_batch` / `knowledge_migration_unit` / `knowledge_migration_file` / `knowledge_migration_attempt` | 迁移全库读写，与现超管相同 | 批次/单元/状态 | 无变更 |
| `system_dictionary` | 字典配置写 | 现有字典列 | 无变更 |
| `dashboard` / `dashboard_component` / `dashboard_default` | 数据看板 iframe 内与超管同等列表/写 | 现有看板列 | 无变更 |
| `sensitive_word_policy` | 内容审查策略读写 | 现有策略列 | 无变更 |
| 标签库相关现表（tag console 已用） | 标签管理 iframe 读写 | 现有标签列 | 无变更 |
| `config`（`key=shougang_portal_config` 或 `shougang_portal_config:t:{tenant_id}`） | 问答/模板/应用配置/知识分类/水印：BFF 合并写；运营身份 **不能** 直打毕昇 PUT 全量 | JSON 聚合 | 无变更 |

门户 BFF 无独立角色表。`RemotePortalAdminConfigStore` 仍代理到毕昇 `config`。

### 3.3 零落库面

菜单显隐、Header、iframe 白名单、`userContext` 对 standalone 的放行：纯鉴权/前端，不落库。

---

## 4. 对外契约

### 4.1 身份下发（一份源：`GET /api/v1/user/info`）

现网 `_user_info_role_label`：超管 → `admin`；否则若 `role_names` 命中 `{管理员, 系统管理员, admin}` 则下发该名；否则下发 `str(role_ids)`。自定义「平台管理员」今天会变成 `"[3]"`，门户认不到。

改后优先级：

1. `AdminRole` → `role="admin"`（不变）。
2. 否则 `role_names` 含精确 `平台管理员` → `role="平台管理员"`。
3. 否则原门户整页名逻辑。
4. 否则保持现网。

同时在 `UserRead` **增加** `role_names: list[str]`（已有列的回显，不是新表字段）。门户会话同时存 `role` 与 `role_names`。判定运营岗：`role === "平台管理员"` **或** `role_names` 含该名。

持有超管 + 平台管理员：仍下发 `admin`，走超管全量。持有 `管理员` + `平台管理员`：走整页管理员（不降级）。

### 4.2 毕昇：单一资格函数

模块：`user`（`LoginUser` / 小 helper）。`common/` 不引用 domain。

```text
has_platform_operator_role(user) :=
  PLATFORM_OPERATOR_ROLE_NAME in user.role_names   # 精确

can_platform_operate(user) :=
  user.is_admin() OR user.is_global_super OR has_platform_operator_role(user)
```

禁止把 `has_platform_operator_role` 写进 `is_admin()`。

**扩资格（`can_platform_operate`）的现网闸门：**

| 现网闸门 | 模块 | 失败码 |
|---|---|---|
| `points_auth.require_platform_admin`（今日 = 超管） | 全部 `/api/v1/points/admin/*` 读/写 | 18201 `无积分管理权限` |
| `require_system_admin` | `/api/v1/knowledge/migrations/*` | 继续 HTTP 403，detail 不泄露无权正文 |
| `DictionaryService._ensure_admin` | `/api/v1/dictoption` 写 | 19102 |
| `DashboardService` 中 `is_admin()` 列表/实时数据集写 | `/api/v1/dashboard*` | 现网未授权错误 |
| `TagConsoleService._ensure_can_manage_tags` | `/api/v1/.../tag-console*` | 10712 |
| `UserPayload.get_tenant_admin_user` 用在敏感词策略 | `GET/PUT /api/v1/sensitive-word-policies/{business_type}` | 改为 `get_login_user` + `can_platform_operate`，失败用现网未授权，**不**扩大 `get_tenant_admin_user` |

**明确不扩：**

- `LoginUser.get_admin_user` / `get_admin_user_from_ws`（含 `PUT /api/v1/shougang-portal/config`）。
- `get_tenant_admin_user` 的通用语义（LLM 等）。
- 专家问答违规删除：仍 `is_platform_super_admin`（超管）。积分管理页内的调账/扣分走扩后的 `require_platform_admin`。
- Client 公开发现开关、知识空间超管 API、审批、系统配置、用户角色。

积分函数建议拆名以免误导：`is_platform_super_admin` 保持超管；写积分管理改调 `can_platform_operate`。对外错误码 18201 不变。

### 4.3 门户 BFF 模块 ACL

现网 `require_admin_session` = `is_portal_admin_role(role) OR account==admin`。**不要**把「平台管理员」加入 `ADMIN_ROLES`。

新增：

```text
is_platform_operator(session) := role 或 role_names 精确匹配「平台管理员」
can_enter_admin_shell := is_portal_admin OR is_platform_operator
```

按 path 鉴权（router 级整组 `Depends(require_admin_session)` 拆掉）：

| 资格 | 路径（均在 `/api/v1/admin/config` 下除非注明） |
|---|---|
| 仅整页管理员 | `GET/POST ""`（全量聚合）、`/domains`、`/sections`、`/category-cards`、`/banners`、`/display`、`/search*`、`/recommendation`、`/apps`（若仅门户管理用则仅超管；应用配置走 `/agent-config`）、`/auto-publish-rules`、`/dept-knowledge-binding*`、`/site`、`/bisheng`、`/integrations`、`/unified-auth`、`/rest-auth`、`/space-options`、`/spaces/*`（业务域绑库用） |
| 整页管理员 ∪ 平台管理员 | `/qa`、`/qa/model-options`、`/agent-config`、`/agent-config/workflow-options`、`/document-types`、`/watermark` |
| 仅整页管理员（其它路由） | `course.py` 写接口、`knowledge_recycle.py` 全部 |
| 上传 | `admin_upload`：运营岗需要水印等素材，允许上传；真正改配置仍受上面 POST 限制 |

`GET /api/v1/admin/config`（全量）：运营岗 **403**（现 `AdminPage.loadConfig` 会拉全量 + `/bisheng` + `/rest-auth`，后两者含密钥）。前端改为：运营岗只拉允许的分文档；整页管理员保持现网。BFF 即使被直打全量也 403。

失败：HTTP 403，`detail` 固定「无权限访问知识管理后台」，不回配置正文。

课程/回收站/站点：保持 `require_admin_session`。

### 4.4 门户前端入口

| 入口 | 超管 / 整页管理员 | 平台管理员 | 普通用户 |
|---|---|---|---|
| Header「知识管理后台」→ `/admin` | 开 | 开 | 关 |
| `/admin` 壳 | 开 | 开（仅上表 11 项） | 登录去登录页；已登录无权限页 |
| 上表第 1–10 项菜单 | 开 | 开 | — |
| 门户管理 / 课程 / 业务域 / 自动发布 / 科室绑定 / 审批 / 系统管理 | 开 | **不渲染**；`?section=` 直链无权限页，不发对应 API | — |
| 上表第 11 项：Header 迁移记录、`/knowledge-migrations`、页内新建迁移 | 开（现仅系统管理员） | **开（全库）** | 关 |
| Header 回收站 | 开 | **关** | 关 |
| 外链「毕昇管理后台」 | 开 | **关** | 关 |
| 专家问答违规删除 | 仅超管 | 关 | 关 |

第 1–10 项 nav key 与 `AdminPage.NAV_GROUPS` 一致。第 11 项迁移不是 nav key，走 `canViewMigrations := isSystemAdministrator OR isPlatformOperator`。完整列表以 §「平台管理员拥有的管理端模块（11 项）」为准。

无权限文案：区分「仅管理员…」与「无权限访问该模块」，不要写「请用超管账号」。

### 4.5 iframe / standalone

嵌入 URL（不变）：

- `/platform/standalone/dashboard`
- `/platform/standalone/knowledge-tag-library`
- `/platform/standalone/content-security`

Platform `userContext` 现网：无管理端 WEB_MENU 则 **整站**（含 standalone）踢到 workspace。路由注释说 standalone 不按 `web_menu` 滤，但 context 未排除。

改后：

1. 路径属于 **运营白名单** 三条（含其子路径如 `/standalone/dashboard/:id` 仅当从看板进入的编辑态；**不包括** `/standalone/approval`、`/standalone/sys`、`/standalone/log`）：跳过 `canAccessPlatform` 踢走；仍要求已登录。
2. 其它 `/platform/*`（含 `/admin`、`/dashboard` 有壳、`/sys`）：平台管理员仍踢到 workspace（或 403），满足「不许从管理后台直进」。
3. 白名单外的 `/standalone/approval`、`/standalone/sys`、`/standalone/log`：前端进 403 页，不加载审批/系统页；后端审批/系统 API 保持超管闸门（不扩 `can_platform_operate`）。

iframe 内接口走用户毕昇 Cookie（与现超管嵌页相同）。本地联调依赖现有 `/platform` 代理与 Cookie 域，不另开 SSO。

### 4.6 角色管理契约

创建/更新角色名：保留名冲突 → 24002。删除或改掉「平台管理员」这一行 → 24004（或等价）。保存 WEB_MENU：若 `role_name` 为保留名，服务端丢掉管理端 key（至少：`admin`,`backend`,`board`,`model`,`log`,`knowledge`,`build`,`evaluation`,`system_config`,`mark_task`,`sys` 及现网 `adminMenuKeys` 同类），只保留工作台类。超管误勾管理端菜单也不能从 Platform 进后台。

---

## 5. 流程与状态

无新状态机。资格是请求时计算，不是资源状态。

### 主路径

1. 超管创建角色 `平台管理员`（可空菜单或仅工作台）→ 写 `role`。
2. 超管把用户绑上该角色（保留普通用户）→ 写 `userrole`。
3. 用户登录门户 → BFF 调 `/user/info` → 会话 `role=平台管理员`。
4. Header 出现后台与迁移；`/admin` 只渲染允许名单。
5. 点积分/问答等：门户或 `/workspace/api` 调对应写接口 → `can_platform_operate` 或 BFF 模块 ACL 通过 → 写第 3 节表。
6. 点数据看板/标签/审查：iframe 白名单 standalone → 页内 API 同样 `can_platform_operate`。
7. 登出 / 被解绑：下一请求无该 `role_name`，入口与接口同时失效。

### 失败

| 场景 | 系统停在 | 脏数据 |
|---|---|---|
| 未绑角色打 `/admin` | 无权限页；BFF 403 | 无 |
| 运营岗直链 `?section=site` 或 POST `/admin/config/domains` | UI 无权限 + 403；`config` 行不变 | 无 |
| 运营岗打 `PUT /api/v1/shougang-portal/config`（用户 Cookie） | `get_admin_user` 403 | 无 |
| 运营岗改 iframe 为 `/standalone/approval` | 前端 403；审批 API 仍超管拒绝 | 无 |
| 运营岗打积分/迁移（未扩资格的旧代码） | 18201 / HTTP 403 | 无（验收必须扩） |
| 并发创建第二条「平台管理员」 | 24002 或 DB unique | 无第二行（同 scope）；跨 scope 由服务层拦截 |
| 超管改名该角色 | 24004，名称仍在 | 资格不会静默消失 |
| 只藏菜单未拦 BFF | 视为实现失败 | 配置可能被改 — 验收必须打禁止 path |

积分/迁移写路径与现超管相同（账本行锁、批次状态机）。运营岗不引入新并发语义。内存 SQLite 测不到的 FOR UPDATE 仍在 171 MySQL 流转测。

### 权限矩阵（AC 可测）

| 身份 | `/admin` 允许名单 | 禁止模块 API | 积分写 | 迁移全库 | 三 iframe | `/standalone/sys` | 回收站 | 专家问答违规删 | `is_admin()` |
|---|---|---|---|---|---|---|---|---|---|
| 未登录 | 去登录 | 401 | 401 | 401 | 登录 | 登录 | 登录 | — | — |
| 普通用户 | 无权限页 | 403 | 18201 | 403 | 踢走/403 | 403 | 403 | 关 | false |
| 平台管理员 | 开 | 403 | 200 且落库 | 200 且落库 | 开且接口 200 | 403 | 403 | 关 | **false** |
| 整页「管理员」 | 全开 | 200 | 视其是否超管 | 视 Header 旧规则；本期不收窄真超管 | 开 | 开 | 开 | 否（非超管） | false |
| 超管 `admin` | 全开 | 200 | 200 | 200 | 开 | 开 | 开 | 开 | true |

---

## 6. 模块所有权

| 规则 | 所有者 | 只调用方 |
|---|---|---|
| 角色名是否为运营岗 | 毕昇 `user`/`role` | 积分、迁移、字典、看板、tag console、敏感词、门户 BFF（经 `/user/info`） |
| 门户模块 path ACL | 门户 `backend/app/api/dependencies.py` + `admin_config` 分路 | 前端只展示 |
| WEB_MENU 剥离 | 毕昇 `RoleService` | Platform 侧栏 |
| standalone 白名单 | Platform `userContext` + `routes/standalone` | 门户 iframe src |
| 门户配置聚合写 | 毕昇 `ShougangPortalConfigService`（仍仅 `get_admin_user`） | 门户 BFF 服务账号 |

调用链不跳层：毕昇 Router → Endpoint → Service → Repository；门户 routes → services → clients。

禁止：前端用 `role` 字符串当唯一鉴权；禁止积分模块自己 parse 角色名（调统一 helper）。

---

## 7. 跨边界影响（blast radius）

**不变量：** 仅当用户持有精确角色名「平台管理员」或超管时，才获得运营写资格；该资格 **不等于** `is_admin()`，也不能打开禁止模块。

**波及面：**

- 门户 `/admin` 菜单与 `loadConfig`（全量配置 + 数据源密钥）。
- BFF `/api/v1/admin/config/*`、课程、回收站、上传。
- Header 后台/迁移/回收站/外链。
- 毕昇 `/user/info` 的 `role` 语义（自定义角色不再只有 id 列表）。
- 积分管理全部 admin API；迁移全部 API（全库列表与写）。
- 字典写；看板列表/写；tag console；敏感词策略。
- Platform 登录后跳转（standalone 例外）。
- 角色创建/改名/删除/WEB_MENU。

**例外：** 真超管、现网「管理员/系统管理员」整页能力不收窄。前台知识/问答/积分查看不变。未登录首页不变。

**可行性：** 能改干净。无 DDL。依赖现网 `role_names` 已在 `LoginUser` 上。工作量：跨两仓中等（鉴权点多，业务逻辑少）。

**风险：高。** 漏改一处 `is_admin()` 则入口开、接口 403；误扩 `get_admin_user` 或 `ADMIN_ROLES` 则首页配置/审批可被改；`GET` 全量配置给运营岗会泄露数据源密码。回滚 = 回代码，库中角色行可留着（无资格函数即失效）。

**建议验证：** 用非超管账号只绑「平台管理员」：允许名单写穿并查表；禁止 path 403 且 `config`/课程表不变；三 iframe 能开；改 URL 进 approval/sys 失败；`is_admin()` 为 false；超管回归全开。

**建议延后：** 角色稳定 `code` 列；自动种子角色；把门户 ACL 做成可配置表。

---

## 8. 迁移、坑、后续

- 存量：无角色则无人获得新资格。上线后超管创建并绑人。
- 回滚代码后，已创建的「平台管理员」行仍在，只是门户又进不去、写接口又 403。
- 坑 1：`AdminPage.loadConfig` 并行拉 `/admin/config`、`/bisheng`、`/rest-auth`。运营岗必须跳过后两路，且全量 GET 403。
- 坑 2：积分、迁移走 `/workspace/api`，**不**走门户 `require_admin_session`。只改门户菜单不够。
- 坑 3：`require_platform_admin` 今日名字像运营岗，实际是超管。必须拆，避免专家问答违规删除被一起放开。
- 坑 4：`「平台管理员」` 以「管理员」结尾，但现网是 Set 全等，不会误判；禁止改成 substring。
- 坑 5：standalone 路由不过 web_menu，但 `userContext` 会踢人；只改路由表不够。
- 坑 6：BFF 写门户配置用服务账号，毕昇侧仍是超管写 `config`。BFF 漏 ACL = 运营岗可改禁止文档。
- 短板：身份绑显示名，超管若绕过 API 直接改库 `role_name`，资格会漂。保留名只拦正规 API。
- 这版不做种子行：避免多环境插出第二条。

---

## 9. AC 可追溯

| AC | 存储 | 契约 | 流程 |
|---|---|---|---|
| 角色名叫「平台管理员」，租户内不重复、不与整页管理员名冲突 | `role.role_name` | 创建/改名 24002；精确匹配 | 超管创建一条 |
| 不能改名/删除该保留名角色 | `role` | 24004 | 改名失败，资格仍在 |
| 不是超管（无超管入口） | 不写 AdminRole | `is_admin()` false；`get_admin_user` 403 | 管理后台有壳页踢走 |
| 能进 11 项 + 迁移全库 | 积分/迁移/字典/`config` 分文档 | 模块 ACL + `can_platform_operate` | 写穿查表 |
| 不能进门户管理/课程/审批/系统管理 | `config` 禁止文档不变 | 403 | 直链+POST |
| 入口隐藏 + 接口 403 | — | BFF/毕昇 | 菜单不渲染且 API 拒 |
| 三 iframe 能开 | dashboard/tag/sensitive 表 | standalone 白名单 + 各 API | 嵌页可读写 |
| approval/sys standalone 进不去 | — | 前端 403 + 后端不扩资格 | 改 URL |
| 积分/迁移认运营身份 | 积分表、迁移表 | 扩 `require_*`，不扩 `is_admin()` | 调账/建批次落库 |
| 超管不变 | 同现网 | `role=admin` | 全模块仍开 |
| 解绑后失效 | `userrole` 删除 | 下一请求无 role_name | 403 |

方案未确认前不拆 tasks、不写业务代码。确认后先出验收用例，再实现。

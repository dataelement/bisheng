# quota-tenant-roles

## summary
配额/租户管理/角色权限三条线的现状基础设施都已存在且可直接承载 GOV-03/GOV-07 的大部分需求：租户配额存 tenant.quota_config JSON（白名单校验 + 三级配额引擎 QuotaService），租户管理页配额弹窗 quotaFields 是按多字段设计的数组（当前仅 storage_gb 一项）；admin-scope 切换（F019）是 Redis + 中间件按 API 前缀注入的管理视图机制；角色菜单权限走 roleaccess 表 type=99 (WEB_MENU) 且后端不校验菜单键白名单，新增「应用工场」菜单与「新建应用」权限点近似零后端 schema 改动（有 create_app 子开关先例）；部署级可选层可照抄 multi_tenant.enabled / BISHENG_PRO 的 settings→/env→appConfig 三段式。真正要新建的是：资源档位表 + 系统管理页新 tab、应用实例计数源（依赖应用实例表）、待上线状态机与终检通知、工场运行时层部署 flag。最大隐患是 tenant quota 的整体覆盖写语义（弹窗保存会清掉 quotaFields 之外的已存 key）与终检的 check-then-act 竞态。

## current_state
【存储配额 storage_gb】配额值不落独立表：租户级存 `tenant.quota_config` JSON 列（src/backend/bisheng/database/models/tenant.py:95），角色级存 `role.quota_config` JSON（src/backend/bisheng/database/models/role.py:26）。核心引擎 = `QuotaService`（src/backend/bisheng/role/domain/services/quota_service.py）：三级计算（超管短路 -1 → 角色级多角色聚合 `_compute_role_quotas` → 租户链硬顶 `_apply_tenant_chain_cap`，Root 用量聚合 `_aggregate_root_usage` 含全部 active 子租户 INV-T9）；合法 key 白名单 `VALID_QUOTA_KEYS` = DEFAULT_ROLE_QUOTA(9 项) + `_TENANT_ONLY_QUOTA_KEYS` {storage_gb, user_count, model_tokens_monthly} + 菜单模式元数据 keys，`validate_quota_config` 拒绝未知 key（24005）。用量统计走 `_RESOURCE_COUNT_TEMPLATES` 原生 SQL 字典（storage_gb = knowledgefile.file_size SUM，file_source IN ('channel','space_upload')）。语义：缺 key / -1 = 不限——与 PRD「未设置=不限」天然一致。
【quota endpoints】用户视角 `GET /api/v1/quota/effective` 与 `/quota/usage`（src/backend/bisheng/role/api/endpoints/quota.py，F005 产物，client 端额度条曾复用，见冻结分支记忆）；管理视角 `GET/PUT /api/v1/tenants/{id}/quota` + `GET /api/v1/tenants/quota/tree`（src/backend/bisheng/tenant/api/endpoints/tenant_crud.py:129-167，`UserPayload.get_admin_user` 依赖），落到 `TenantService.aget_quota/aset_quota/aget_quota_tree`（src/backend/bisheng/tenant/domain/services/tenant_service.py:363-430）。⚠️已核实：`aset_quota` 是整体替换写（line 392 `aupdate_tenant(tenant_id, quota_config=data.quota_config)`）。
【执行点】两类：① 创建类 endpoint 装饰器 `require_quota(QuotaResourceType.X)`（quota_service.py:826）——knowledge.py:101、knowledge_space.py:52、assistant.py:84、workflow.py:185、tool/api/tool.py:31；内部走 `check_quota`（先租户链 blocker → 19401/19403，再角色级 → 19402，错误码在 common/errcode/tenant_quota.py）。② 存储字节级前置额度计算 `get_knowledge_space_upload_limit_bytes` + `get_tenant_storage_remaining_bytes`，调用点：knowledge_space_service.py:3176/3384/3603、workstation/api/endpoints/knowledge.py:30、open_endpoints/api/endpoints/filelib.py:334/454/481（v2 开放 API 也在执行）。
【租户管理页配额弹窗】platform 前端 `TenantPage/index.tsx`（路由 routes/index.tsx:116，permission:'sys'）列表展示 storage_used_gb/storage_quota_gb（后端批量 `QuotaService.get_storage_used_gb_batch` quota_service.py:730）；弹窗 `TenantPage/components/TenantQuotaDialog.tsx`——`quotaFields` 是数组（line 56-61，当前仅 `{key:'storage_gb'}` 一行），输入校验镜像后端 GB float 规则，保存时**只序列化 quotaFields 中的 key 并整体覆盖**（line 77-98）。给 PRD「实例配额与存储配额同弹窗并列」加一行即可，但两入口写同 JSON 的覆盖语义要先修。
【admin-scope 租户管理视图】F019 三件套：服务 `TenantScopeService`（src/backend/bisheng/admin/domain/services/tenant_scope.py）——Redis key `admin_scope:{user_id}`、TTL=settings.multi_tenant.admin_scope_ttl_seconds（默认 14400s 滑动）、非 JWT、审计 admin.scope_switch、logout/token-bump 清除钩子；endpoint `POST/GET /api/v1/admin/tenant-scope`（admin/api/endpoints/tenant_scope.py，仅全局超管）；中间件 `AdminScopeMiddleware`（src/backend/bisheng/common/middleware/admin_scope.py）只对 `MANAGEMENT_API_PREFIXES`（/api/v1/llm、/workstation、/linsight、/tool、/knowledge、/chat/online、/admin）把 scope 注入 ContextVar `_admin_scope_tenant_id`（core/context/tenant.py:65，get_current_tenant_id 优先返回它），每请求重验 `_check_is_global_super`，fail-open。前端：hook `useAdminScope`（platform/src/hooks/useAdminScope.ts）+ UI 仅存在于模型管理页 `pages/ModelPage/manage/ScopeBar.tsx`（v2.5.1 产品评审后从全局 header 收缩为页面级切换器），且 `manage/index.tsx:198` 要求 `appConfig.multiTenantEnabled` 才渲染。
【角色权限配置】存储：`roleaccess` 表（database/models/role_access.py，RoleAccess: role_id+third_id+type），type 枚举 `AccessType`（资源读写 1-12 + `WEB_MENU=99`）；菜单键"注册表" = `WebMenuResource` enum（同文件 line 42-72）：一级 workstation/admin，管理侧 build/knowledge/model/tool/mcp/channel/…，工作台侧 home/linsight_task_mode/apps，且已有**功能权限点子开关先例**：`CREATE_APP='create_app'`（BUILD 下「新建应用/管理应用模板」入口开关）与 CREATE_KNOWLEDGE。写路径：`RoleService.create_role_with_menu/update_role_with_menu`（role/domain/services/role_service.py:132/431）→ `_normalize_menu_ids`（line 766：只去重+剔除 system_config，**不做枚举白名单校验**）→ `_replace_menu_access_in_session`（line 778：删旧插新 type=99 行）。读路径：登录信息 `user/api/user.py:187` → `get_roles_web_menu`（user/domain/services/auth.py:668，多角色 union）返回 `web_menu` 列表；后端有菜单权限断言先例 `assert_effective_web_menu_contains(user_id,'model')`（auth.py:647）。菜单模式 flags `menu_approval_mode_workbench/_admin`（workbench/admin scope split）存 role.quota_config（quota_service.py `_MENU_APPROVAL_MODE_KEYS`）。前端配置面：`SystemPage/components/EditRole.tsx`——admin 菜单 MENU_LIST + 工作台菜单 `WORKBENCH_MENU_LIST`（line 80-82，'workbenchMenu' 独立面板 line 368），保存时合并 `[...menuPermissionsToSave, ...form.useWorkbenchMenu]`（line 563）一起提交。菜单 gating：platform `layout/MainLayout.tsx` `isMenu()`/`showAdminNav()`（line 93-113，超管/子租户管理员全放行、审批模式显示可申请菜单占位）；client `layouts/MainLayout.tsx`（web_menu 映射为 plugins，line 105；`showWorkbenchItem('home'/'apps')` line 131-132 控 tab；menu_approval_mode_workbench 控 /menu-unavailable 占位）。
【多租户 vs 单租户 & 部署 flag 模式】后端开关 `settings.multi_tenant.enabled`（core/config/multi_tenant.py MultiTenantConf，default False；settings.py:748）；经 `GET /api/v1/env` 暴露 `multi_tenant_enabled`（api/v1/endpoints.py:94）与 `pro`（line 90，BISHENG_PRO）；前端 `contexts/locationContext.tsx:91` 收进 `appConfig.multiTenantEnabled` 后各处 gating：租户管理菜单仅 `isSuperAdmin && appConfig.multiTenantEnabled`（platform MainLayout.tsx:249）、TenantPage:135 单租户降级、ScopeBar、Departments 挂租户操作、ModelPage 权限函数 canManageModelSettings。系统管理页 tab 框架：`SystemPage/index.tsx`——按 isSuperAdmin/isDeptAdmin/isChildAdmin 布尔条件挂 TabsTrigger（组织/角色/orgSync/系统配置），新增「资源档位」tab 照此模式加即可。

## key_files
- src/backend/bisheng/role/domain/services/quota_service.py — 配额核心引擎：VALID_QUOTA_KEYS 白名单、三级计算、租户链硬顶、_RESOURCE_COUNT_TEMPLATES 用量 SQL、require_quota 装饰器、validate_quota_config——实例数配额的预检/终检直接扩展此处
- src/backend/bisheng/tenant/api/endpoints/tenant_crud.py — GET/PUT /tenants/{id}/quota + /tenants/quota/tree（get_admin_user 依赖），line 129-167
- src/backend/bisheng/tenant/domain/services/tenant_service.py — aget_quota/aset_quota(line 363-395，⚠️quota_config 整体替换写)/aget_quota_tree
- src/backend/bisheng/database/models/tenant.py — tenant.quota_config JSON 列（line 95）——租户实例数配额的自然落点
- src/frontend/platform/src/pages/TenantPage/components/TenantQuotaDialog.tsx — 租户配额弹窗；quotaFields 数组（line 56-61）加一行即得「实例数与存储同弹窗并列」；⚠️handleSave 只序列化 quotaFields 内的 key 后整体覆盖
- src/frontend/platform/src/pages/TenantPage/index.tsx — 租户管理页；multiTenantEnabled gating（line 62/135）、配额弹窗入口、storage 用量条展示
- src/backend/bisheng/admin/domain/services/tenant_scope.py — F019 admin-scope：Redis 4h 滑动、审计、清除钩子
- src/backend/bisheng/common/middleware/admin_scope.py — MANAGEMENT_API_PREFIXES 列表（line 63-71）——工场管理 API 若需超管切租户视图须加前缀于此
- src/frontend/platform/src/pages/ModelPage/manage/ScopeBar.tsx — 页面级 admin-scope 切换器 UI 先例（仅超管+多租户渲染），可复制到工场管理面
- src/backend/bisheng/database/models/role_access.py — RoleAccess 表 + AccessType(WEB_MENU=99) + WebMenuResource 菜单键枚举（含 create_app 权限点子开关先例）
- src/backend/bisheng/role/domain/services/role_service.py — 角色菜单写路径 _normalize_menu_ids（不校验白名单，line 766）+ _replace_menu_access_in_session（line 778）
- src/backend/bisheng/user/domain/services/auth.py — get_roles_web_menu(line 668，多角色 union) + assert_effective_web_menu_contains(line 647，后端菜单权限断言先例)
- src/frontend/platform/src/pages/SystemPage/components/EditRole.tsx — 角色权限配置面：MENU_LIST + WORKBENCH_MENU_LIST（line 73-82）双面板；「应用工场」菜单/「新建应用」权限点在此加条目
- src/frontend/platform/src/pages/SystemPage/index.tsx — 系统管理页 tab 框架（按管理员身份布尔挂 TabsTrigger）——「资源档位」新 tab 照此模式
- src/frontend/platform/src/layout/MainLayout.tsx — platform 菜单 gating：isMenu/showAdminNav（line 93-113）；租户管理入口 isSuperAdmin && multiTenantEnabled（line 249）
- src/frontend/client/src/layouts/MainLayout.tsx — client 工作台菜单 gating：web_menu→plugins、showWorkbenchItem('home'/'apps')、menu-unavailable 占位——「应用工场」工作台入口照此
- src/backend/bisheng/api/v1/endpoints.py — /api/v1/env 暴露 multi_tenant_enabled(line 94)/pro(line 90)——部署级可选层 flag 的现成暴露通道
- src/backend/bisheng/core/config/multi_tenant.py — MultiTenantConf——新增部署 flag（工场运行时层/开放能力层）的 settings section 范本
- src/frontend/platform/src/contexts/locationContext.tsx — appConfig.multiTenantEnabled 注入点（line 91）——前端消费部署 flag 的单一入口
- src/backend/bisheng/common/errcode/tenant_quota.py — 19401/19402/19403 配额错误码——实例配额超限错误码在同模块续号

## reuse
- 租户实例数配额存储：直接复用 tenant.quota_config JSON（database/models/tenant.py:95）加新 key（如 app_instance_count），VALID_QUOTA_KEYS + validate_quota_config（quota_service.py:57/790）加白名单即可，无需新表、无迁移（JSON 列）；「未设置=不限」语义（缺 key/-1=unlimited）与 PRD 一致（verified）
- 配额弹窗并列展示：TenantQuotaDialog.quotaFields 本就是数组（line 56-61），加 {key:'app_instance_count'} 一行 + i18n label 即得「与既有存储配额同弹窗并列」；输入校验模式（镜像后端规则）可照抄（verified）
- 预检+终检执行模式：复用 QuotaService.check_quota / _apply_tenant_chain_cap 的租户链检查骨架与 194xx 错误码族（common/errcode/tenant_quota.py）；提交发布预检可仿 require_quota 装饰器（quota_service.py:826，5 个资源 endpoint 在用），上线终检在服务层显式调 check（channel_service.py:1423 有服务层直调先例）（verified）
- 「应用工场」菜单 + 「新建应用」权限点：完全复用 roleaccess 表 type=99 机制——WebMenuResource 加枚举成员（文档性质，后端 _normalize_menu_ids 不校验白名单故零 schema 改动，role_service.py:766）；CREATE_APP='create_app' 已是「菜单+功能点子开关」的完整先例（role_access.py:50）；前端 EditRole.tsx WORKBENCH_MENU_LIST/MENU_LIST 加条目；后端拦截复用 assert_effective_web_menu_contains 先例（auth.py:647）；变更审计走既有角色保存路径（verified）
- 默认值策略（菜单默认仅租户管理员开）：platform MainLayout isMenu() 已对 isSuperAdmin/isChildAdmin 全放行（MainLayout.tsx:99），普通角色缺 key 即不可见——与 PRD「默认关闭、管理员勾选开通」的灰度模型天然一致（verified）
- 部署级可选层开关：照抄 multi_tenant.enabled / BISHENG_PRO 三段式——settings 新 section（core/config/ 下仿 MultiTenantConf）→ /api/v1/env 加字段（api/v1/endpoints.py:90-94）→ locationContext appConfig → 前端 gating（TenantPage:135 有「关闭时降级页」先例）；「未部署时资源档位 tab 不出现」即 SystemPage/index.tsx 的布尔挂 tab 模式（verified）
- 平台超管切租户上下文：F019 admin-scope 全套可复用——工场管理 API 前缀加入 MANAGEMENT_API_PREFIXES（admin_scope.py:63）后 get_current_tenant_id 自动生效，页面复制 ScopeBar 组件模式（verified；注意该机制当前 UI 仅模型管理页一处）
- 本租户配额视图（GOV-09 用量条）：GET /api/v1/quota/effective + /usage（role/api/endpoints/quota.py）与 client useEffectiveQuota 先例（记忆：知识空间额度条冻结分支 feature/knowledge-space-quota-display 已实现同类 UI，单位已 GB）可参考复用
- 单租户部署写配额：tenant 表在单租户模式也始终有 ROOT 行（ROOT_TENANT_ID=1，tenant quota endpoints 本身无 multi_tenant gating，只有前端菜单 gating）——单租户时实例配额仍可写 Root 行 quota_config，由「资源档位」tab 内的实例配额区调用同一 PUT /tenants/1/quota（推断，端点无模式限制已核实，产品动线需确认）

## gaps
- 资源档位（Tier）实体：全仓无任何服务器资源档位/CPU/内存规格概念——需新表（名称/CPU/内存/适用说明/启用状态，平台级无 tenant_id）+ CRUD service/endpoints + 「使用中应用数」统计（依赖应用实例表 join）+ 档位停用只拦新选择的规则层
- 系统管理页「资源档位」tab：SystemPage/index.tsx 新 TabsTrigger + 新组件（超管可见 && 工场运行时层已部署双条件）；单租户形态下 tab 内还要嵌「实例配额区」子块（多租户走 TenantQuotaDialog，单租户此处）——同一配额两个写入口需统一写语义
- 应用实例数计数源：_RESOURCE_COUNT_TEMPLATES 需新条目，但被计数的应用实例表本身属 PRD-1 其它调研线的新建物；计数 SQL 须排除审批期临时预览实例（RT-03 不计入）与已停用实例——状态字段设计要预留
- 「待上线（配额不足）」状态机分支 + 终检失败通知：审批单保持通过、应用转待上线态、站内消息提示 owner 与租户管理员（可复用 notification/ 站内信模块与 approval outbox 模式，但接线是新活）；配额释放后 owner 手动上线免重新审批的路径
- 工场运行时层/开放能力层两个部署 flag：settings 新 section + /env 字段 + 前端 appConfig gating + 未部署时统一引导页（RT-01）+ API key 管理入口整体隐藏（GOV-08 联动）——flag 本身是新建，模式可抄
- CLI 首发 deploy 的「新建应用」权限点校验：v2 开放 API（SAK 鉴权，见开放 API PRD）此前无 web_menu 校验先例——需要把 SAK 解析出的用户身份接到角色 web_menu 检查（assert_effective_web_menu_contains 的 v2 变体），且区分首发 deploy（校验）与迭代 deploy（放行）
- 档位规格「部署配置项提供初始默认值」的 seed 机制：三档默认规格如何初始化进 DB（启动 seed / initdb_config / 配置链 YAML→env→DB）需设计——现状无档位类 seed 先例
- 配额下调至低于存量的提示文案与「存量不受影响」语义：现有 check_quota 是 remaining=max(limit-used,0)=0 即拦——天然满足「只拦新增」，但管理 UI 下调时的影响提示是新前端交互

## risks
- 【已核实的覆盖写缺陷】TenantQuotaDialog.handleSave（line 77-98）只从 quotaFields 构建 config 后整体 PUT，后端 aset_quota（tenant_service.py:392）整体替换 quota_config——只要实例配额与存储配额有任一入口不含对方字段（如单租户的资源档位 tab 实例配额区 vs 多租户弹窗），保存即互相清掉对方 key。设计必须改成后端合并（PATCH 语义）或强制所有入口全量读改写（本仓已有同类事故先例：workstation 模型配置整体覆盖抹 models）
- 终检竞态：check_quota 是 check-then-act 无锁，两个应用并发上线可同时通过终检导致超限 1 个——存量配额体系同样非原子（可作先例接受），但 PRD 终检语义更严肃，design 阶段需显式声明或加 Redis 锁/DB 行锁
- admin-scope 前缀误伤：MANAGEMENT_API_PREFIXES 含宽前缀 /api/v1/knowledge、/tool——工场新 API 路由命名若落在这些前缀下会意外被超管 scope 改写租户上下文；反之若工场管理面需要 scope 又忘加前缀则切换失效。前缀取名是隐性架构决策
- C3 多租户：资源档位表是平台级（无 tenant_id），DAO 查询若在租户上下文中执行需注意 bypass_tenant_filter 惯例；若应用实例表含 tenant_id，须注册 _TENANT_AWARE_MODEL_MODULES（记忆中的既有约束），且实例计数是聚合 SQL——租户过滤监听器只拦 SELECT ORM 查询、raw text() 无注入，须手写 tenant_id 条件（已有两次泄漏教训）
- C2 双库：档位表/实例表 DDL 与计数 SQL 须 DM8 兼容（quota_service 已有 user_count/model_tokens_monthly 因 DM8 保留字与日期函数单独处理的先例，照抄其模式）
- _normalize_menu_ids 不校验菜单键白名单：加「应用工场」「新建应用」零后端改动是便利，但拼写错误 key 会静默入库且永不生效——建议在 design 中评估是否补枚举校验（会影响存量脏数据）
- 菜单默认值迁移：PRD 要求存量环境升级后「应用工场」菜单默认仅租户管理员角色开启——现状 isMenu() 对 child admin/超管代码级放行已覆盖管理员，但若「租户管理员」是普通角色（非 is_child_admin 标记）则需数据迁移给角色补 WEB_MENU 行；升级默认值语义需核实租户管理员的实现形态
- 单租户部署差异面广：TenantPage/ScopeBar/挂租户等均以 appConfig.multiTenantEnabled gating——工场配额 UI 要在两种形态下分别验收（PRD 明确两条动线），E2E 需双模式覆盖；另注意 /api/v1/env 的 version 字段硬编码不可靠（记忆），新 flag 不要依赖 version 判断

## open_questions
- 实例配额存储形态：进 tenant.quota_config JSON（复用最大化，但需先修整体覆盖写语义）还是随资源档位建独立表？两个写入口（多租户弹窗 / 单租户资源档位 tab）如何共享同一后端接口避免互踩？
- 「租户实例数」的计数对象定义：仅『运行中』实例？含「待上线（配额不足）」？停用后重新启用要终检——状态机哪些态占额度需要产品拍板（直接决定计数 SQL 的状态过滤条件）
- 工场运行时层部署 flag 的检测方式与命名：纯 settings 静态 flag（如 app_factory.enabled，PRD 倾向）还是运行时探测运行时层健康？与开放能力层 flag（GOV-08 API key 入口隐藏）是一个 section 两个键还是两个 section？
- 「新建应用」权限点在 CLI/SAK 路径的检查时点：SAK（bs-sak-，服务账号密钥，见开放 API PRD）解析出的操作者身份是否总能映射到有角色的平台用户？受限委托模式下按被代表者还是密钥归属者的角色判「新建应用」？
- 档位三档默认规格的 seed 与调整持久化：部署配置项提供初始默认值、平台超管可调——调整后写 DB 覆盖配置文件？重新部署时配置文件默认值是否回灌？（config 链 YAML→env→DB→Redis 的优先级如何应用于档位）
- 「租户管理员」在权限默认值语境下的确切实现形态：is_child_admin 标记（代码级放行）还是具名角色（需迁移补 WEB_MENU 行）？决定存量升级是否需要数据迁移脚本
- 工场管理 API 是否需要超管 admin-scope 切换视图（PRD 未明说）：若需要，加 MANAGEMENT_API_PREFIXES + 页面 ScopeBar；若不需要（超管在租户管理页直接设各租户配额已够），可省一层复杂度
- 本租户配额视图（应用管理 tab 用量条）走既有 /quota/effective 扩展还是工场自己的接口？（effective 接口按 DEFAULT_ROLE_QUOTA 枚举资源类型，实例配额是租户级无角色维度，塞进去语义略歪）

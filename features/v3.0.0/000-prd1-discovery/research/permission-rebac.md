# permission-rebac

## summary
权限体系已具备 PRD GOV-01/RT-02 所需的全部积木：PermissionService 七级检查链（超管短路→缓存→租户门→子租户管理员短路→OpenFGA→创建者兜底→降级回退）、通用授权 API（/api/v1/permissions/resources/{type}/{id}/authorize，按用户/部门/用户组）、platform 端通用授权弹窗 PermissionDialog、以及 ListObjects∪绑定表 的列表预过滤模式，均已在 workflow/assistant 上跑通。核心缺口是「app」作为新资源类型的全链路注册：OpenFGA 静态模型文件、VALID_RESOURCE_TYPES、permission_service 内约 7 处 per-type dispatch 分支、细粒度权限模板、两个前端的 ResourceType 联合类型；最大风险是 FGA 授权模型只在「store 无模型」时写入，存量环境新增类型必须运维介入（force_write_model），无自动升级通道。

## current_state
【入口与检查链（已核实）】核心引擎是 src/backend/bisheng/permission/domain/services/permission_service.py 的 PermissionService（全 @classmethod 无状态）。check()（L82-215）实际是七级链（文件头 docstring 明示）：L1 超管短路——login_user.is_admin() 直接 return True（is_admin 定义在 src/backend/bisheng/user/domain/services/auth.py:270，判 user_role 含 AdminRole，即 super_admin，这是第一个 allow-all 短路）；L3/L4 租户门 _evaluate_tenant_gate()（L999-1036）——先 _resolve_resource_tenant()（L1743，仅 workflow/assistant/knowledge_space/knowledge_library 四类解析 tenant_id，其余返回 None 跳过门）比对 login_user.get_visible_tenants()，不可见且非 shared_to 即拒绝（tenant mismatch 拒绝级）；同函数内做子租户管理员短路——has_tenant_admin(resource_tenant_id) 为真直接返回 PermissionLevel.owner（第二个 allow-all 短路，Root 租户按 INV-T3 无 tenant#admin 元组故不吃此短路）；L2 Redis 缓存（10s，UNCACHEABLE_RELATIONS 绕过，刻意放在租户门之后防止陈旧 allow 绕门）；L5 OpenFGA fga.check()；L6 DB creator 兜底 _get_implicit_permission_level_after_gate()（L1039，require_no_active_owner=True 时仅当无其它 owner 元组才把 creator 当 owner，knowledge_space 例外为永久 owner）；L7 FGAConnectionError 时不再硬 fail-closed，而是回退 owner/implicit 档位（L194-212 注释说明三条 FGA 不可用路径已对齐）。RBAC 菜单权限是独立平行体系：role_access 表 AccessType.WEB_MENU=99（src/backend/bisheng/database/models/role_access.py:89），配置面在 src/backend/bisheng/role/domain/services/role_service.py（:541/:784），并由 permission/domain/services/legacy_rbac_sync_service.py 的 LegacyRBACSyncService 把 role_access 行同步成 FGA 元组。
【OpenFGA 模型（已核实）】DSL 以 Python 静态 dict 形式放在 src/backend/bisheng/core/openfga/authorization_model.py：MODEL_VERSION='v2.0.2'，16 个类型 = user/system/tenant/department/user_group 基础类型 + 11 个资源类型（knowledge_space、knowledge_library、folder、knowledge_file、channel、workflow、assistant、tool、dashboard、llm_server、llm_model）。资源类型由 _standard_resource_type() 工厂生成：owner>manager>editor>viewer 金字塔 + can_manage/can_edit/can_read computed + can_delete + shared_with:[tenant]（F013 跨租户共享）。授权主体三源固定为 user / department#member / user_group#member(+admin)（_user_types()）。模型写入在 core/openfga/manager.py::_async_initialize（L60-75）：仅当 store 无既有模型或配置 force_write_model=true（core/config/openfga.py:16）时才 POST 新模型，否则复用最新既有模型——即改了静态文件存量环境不会自动生效；另有 F013 遗留的 dual_model_mode/legacy_model_id 双模型灰度配置。llm_server/llm_model 当年就是「静态文件预分配+发版时写新模型」的先例。
【资源创建授权与补偿（已核实）】创建资源写 owner 元组的契约是 permission/domain/services/owner_service.py::OwnerService.write_owner_tuple（L44，默认 best-effort，enforce_fga_success 可选强制）。PermissionService.authorize()（L314-408）：_expand_subject 展开主体（部门 include_children 展开整棵子树为多条 department:{id}#member）、write-over-delete 去重、交给 batch_write_tuples()（L413，每批 100，FGAWriteError 时回退逐条写并容忍幂等错误 _is_idempotent_tuple_error），失败落 FailedTuple 表（database/models/failed_tuple.py），并按 affected_user_ids 逐用户失效 PermissionCache。补偿重试是 Celery beat 任务 worker/permission/retry_failed_tuples.py：每 30s、Redis 分布式锁、批量→逐条回退、最多 3 次后 mark_dead + logger.critical。
【通用授权 API 与细粒度模板（已核实）】前端弹窗对接 permission/api/endpoints/resource_permission.py：POST /api/v1/permissions/resources/{resource_type}/{resource_id}/authorize（:1457 authorize_resource，入口先校验 VALID_RESOURCE_TYPES），配套 grant-subjects/users、departments/children（懒加载部门树）、模板端点（:2161-:2205 按类型各一个）。resource_type→细粒度权限 id 的映射由各 *_permission_template.py 提供（application_permission_template.py 定义 workflow/assistant 共用的 view_app/use_app/edit_app/delete_app/publish_app/share_app/manage_app_* 及 relation 默认档位），dispatch 在 resource_permission.py::_default_permission_ids_for_relation（:562，硬编码 if-chain）。自定义关系模型（F048）与绑定表以 JSON 存 Config 表（_save_relation_models/_save_bindings，ConfigDao），带版本化进程内缓存 relation_roster_cache。permission/api/endpoints/permission_check.py 提供前端自查端点 POST /permissions/check（支持 permission_id 细粒度）与 GET /permissions/objects（admin 返回 null=不过滤）。
【前端通用授权弹窗（已核实）】platform（管理端）：src/frontend/platform/src/components/bs-comp/permission/PermissionDialog.tsx——Tabs 按用户/部门/用户组（SUBJECT_TABS），PermissionListTab（已授权列表）+ PermissionGrantTab（新增授权，支持关系模型选择 getGrantableRelationModelsApi、部门含子部门 include_children）。使用方：构建页 BuildPage/apps.tsx:476（workflow/assistant 卡片授权，即 PRD 说的「像其他平台资源一样授权」的现成交互）、flow/Header.tsx:532、assistant/editAssistant/Header.tsx:113、tools/index.tsx:232、KnowledgePage/KnowledgeFile.tsx:727、KnowledgeQa.tsx:594、Dashboard/DashboardSidebar.tsx:248。resourceType 联合类型在 bs-comp/permission/types.ts（9 类，无 app）。client（工作台）：src/frontend/client/src/components/permission/PermissionDialog.tsx 只是 KnowledgeSpaceShareDialog 的薄壳（知识空间成员管理走它），频道另有 pages/Subscription/ChannelPermissionDialog.tsx；client 的 ResourceType 联合类型在 client/src/api/permission.ts:3。
【列表可见性过滤模式（已核实）】构建页与工作台应用列表共用 GET /api/v1/workflow/list（client/src/api/apps.ts:391 也调它）。后端 api/services/workflow.py::get_all_flows_envelope（:565，F027 游标）：is_admin_bypass = user.is_admin() 且非 scoped_super_admin（:612-613）→ 整页不过滤；普通用户走两段式——先 _app_type_ids_for_permission（:699）做 ID 预过滤 = PermissionService.list_accessible_ids（FGA ListObjects，带 Redis 缓存）∪ ApplicationPermissionService.get_bound_app_type_ids_async（绑定表推导，该方法 docstring 自述是对「list_objects 在元组缺失/不稳时返回空」的兜底），再用预过滤 ID 集做 DB keyset 扫描；行级细粒度（can_share/writeable）再经 get_app_permission_map_async 逐行求有效权限集（并发 20 semaphore + 请求级 ApplicationPermissionContext 复用）。list_accessible_ids（permission_service.py:218）对 admin 返回 None（调用方免过滤），普通用户 = FGA ids + creator 自建 ids + 子租户管理员 scope ids（_resource_ids_child_tenant_admin_scope :1347）再过租户门 _filter_ids_by_tenant_gate。

## key_files
- src/backend/bisheng/permission/domain/services/permission_service.py — PermissionService 核心：check() 七级链、list_accessible_ids()、authorize()、batch_write_tuples()、_evaluate_tenant_gate/_resolve_resource_tenant/_get_resource_creator 等 per-type dispatch（新增 app 类型的主要改造面）
- src/backend/bisheng/core/openfga/authorization_model.py — OpenFGA 授权模型 DSL（静态 Python dict，MODEL_VERSION v2.0.2，16 类型）；新增 app = _standard_resource_type('app') + 版本号
- src/backend/bisheng/core/openfga/manager.py — 模型写入仅在 store 无模型或 force_write_model=true 时发生（存量环境升级卡点）；dual_model_mode 灰度配置
- src/backend/bisheng/permission/domain/schemas/permission_schema.py — VALID_RESOURCE_TYPES（9 类，无 app）——/check、/objects、/authorize 的入口白名单
- src/backend/bisheng/permission/api/endpoints/resource_permission.py — 通用授权 API：authorize_resource(:1457)、grant-subjects 搜索、模板端点、_default_permission_ids_for_relation(:562) 类型 dispatch、关系模型/绑定 JSON 存 Config 表
- src/backend/bisheng/permission/domain/application_permission_template.py — workflow/assistant 细粒度权限模板（view/use/edit/delete/publish/share/manage_*）——app 类型模板的样板
- src/backend/bisheng/permission/domain/services/owner_service.py — OwnerService.write_owner_tuple——资源创建写 owner 元组的 F008 契约（INV-2）
- src/backend/bisheng/worker/permission/retry_failed_tuples.py — FailedTuple 补偿：Celery beat 每 30s，Redis 锁，3 次后 dead + critical 告警
- src/backend/bisheng/database/models/failed_tuple.py — 失败元组补偿队列表
- src/backend/bisheng/api/services/workflow.py — get_all_flows_envelope(:565)/_app_type_ids_for_permission(:699)——列表可见性过滤范式（admin bypass + ListObjects∪绑定预过滤 + 行级细粒度），RT-02 广场过滤直接复用
- src/backend/bisheng/permission/domain/services/application_permission_service.py — 应用细粒度权限求值 + get_bound_app_type_ids_async（ListObjects 不稳兜底）；_FLOW_TYPE_TO_OBJECT_TYPE 仅 WORKFLOW/ASSISTANT
- src/backend/bisheng/permission/api/endpoints/permission_check.py — 前端自查端点 /permissions/check + /permissions/objects
- src/backend/bisheng/database/models/role_access.py — AccessType.WEB_MENU=99——RBAC 菜单权限（GOV-07 应用工场菜单/新建权限的接入点）
- src/backend/bisheng/permission/domain/services/legacy_rbac_sync_service.py — role_access(RBAC)→FGA 元组同步
- src/frontend/platform/src/components/bs-comp/permission/PermissionDialog.tsx — platform 通用授权弹窗（按用户/部门/用户组三 Tab + 关系模型），GOV-01 复用目标
- src/frontend/platform/src/components/bs-comp/permission/types.ts — platform 端 ResourceType 联合类型（需加 app）
- src/frontend/client/src/components/permission/PermissionDialog.tsx — client 端「通用」弹窗实为 KnowledgeSpaceShareDialog 薄壳——若发布面在工作台需真正通用化
- src/frontend/client/src/api/permission.ts — client 端 ResourceType 联合类型与授权 API 封装
- src/frontend/platform/src/pages/BuildPage/apps.tsx — :476 构建页应用卡片挂 PermissionDialog——「应用像其他资源一样授权」的现成交互样板

## reuse
- GOV-01 通用授权交互（按用户/部门/用户组）可整体复用：后端 POST /api/v1/permissions/resources/{type}/{id}/authorize（resource_permission.py:1457）+ platform PermissionDialog.tsx（BuildPage/apps.tsx:476 已在应用卡片上用同款弹窗），新 app 类型只需进白名单与类型联合
- GOV-01「授权变更自下一次请求起生效」已由现有机制保证：authorize() 按 affected_user_ids 逐用户失效 PermissionCache（permission_service.py:403-408），部门/用户组授权经 _affected_user_ids_for_subject 展开；检查链 L2 缓存也仅 10s TTL
- RT-02 广场按可见范围过滤可直接套用现有列表范式：get_all_flows_envelope 的「admin bypass + ListObjects∪绑定表预过滤 + DB keyset + 行级细粒度」（api/services/workflow.py:565-740），client 应用广场本就走同一 /api/v1/workflow/list
- GOV-01 租户管理员代 owner 调整：_evaluate_tenant_gate 的子租户管理员 owner 级短路（permission_service.py:1026-1034）使租户管理员天然能打开/修改本租户任意资源的授权关系，无需新权限逻辑
- 应用创建即 owner：OwnerService.write_owner_tuple（owner_service.py:44）是现成的创建契约，含 enforce_fga_success 强一致选项与 FailedTuple 补偿（worker/permission/retry_failed_tuples.py 30s 重试）
- 细粒度动作权限（发布/下线/分享等）可仿 application_permission_template.py 建 app 模板并接入 _default_permission_ids_for_relation dispatch，F048 关系模型/绑定存储（Config 表 JSON + relation_roster_cache）零改动复用
- GOV-07 应用工场菜单与「新建应用」角色配置可复用 RBAC 菜单体系：AccessType.WEB_MENU（role_access.py:89）+ role_service.py 配置面 + LegacyRBACSyncService 同步
- NFR-1.3/入口访问检查可复用 /permissions/check 端点（permission_check.py:24，支持 relation 或 permission_id 细粒度）

## gaps
- OpenFGA 模型新增 app 类型：core/openfga/authorization_model.py 加 _standard_resource_type('app') + MODEL_VERSION 升版；且必须配套存量环境模型升级手段——manager.py 仅在 store 无模型或 force_write_model=true 时写模型，目前没有『版本比对自动升级』机制（llm_server/llm_model 当年靠发版前预分配绕过了这个问题）
- permission_service.py 内约 7 处 per-type dispatch 需加 app 分支：VALID_RESOURCE_TYPES、_resolve_resource_tenant（租户门）、_get_resource_creator（creator 兜底）、_TENANT_GATED_RESOURCE_TYPES、_resource_ids_by_creator_user_ids、_resource_ids_in_tenants/_resource_tenant_map（列表租户过滤）、必要时 _IMPLICIT_SCOPE_RESOURCE_TYPES
- app 细粒度权限模板：新建 permission/domain/app_permission_template.py（可含 use/view/manage 等）+ resource_permission.py 的 _default_permission_ids_for_relation dispatch + 模板端点；application_permission_service.py 的 _FLOW_TYPE_TO_OBJECT_TYPE 仅覆盖 WORKFLOW/ASSISTANT，app 若不入 flow 表需新的求值路径
- 两个前端的 ResourceType 联合类型均需加 'app'（platform bs-comp/permission/types.ts、client api/permission.ts）；若发布面/应用管理在 client 工作台，client 的『通用弹窗』需真正通用化（现为 KnowledgeSpaceShareDialog 薄壳，platform 版才是完整三 Tab + 关系模型实现）
- RT-02 广场对 app 的列表接入：现有过滤范式绑定 FlowType 枚举与 flow 表（get_all_flows_envelope / TagDao ResourceTypeEnum），app 作为新资产需要新增 FlowType 值或独立列表通道，标签体系 TagDao 也需扩 ResourceTypeEnum
- GOV-01 授权变更计审计：未发现 authorize_resource 接审计中心的证据（仅见 _dispatch_authorize_notifications_in_background 站内通知）——『owner 调可见范围计审计、租户管理员代调计审计』需新建审计埋点（未逐行核实 authorize_resource 全文，此条为待确认缺口）
- GOV-09 租户管理员『应用管理列表行上打开同款授权弹窗』的管理面页面与入口为新建（platform 侧现无应用工场管理页）

## risks
- 【存量环境模型升级是硬风险】FGA 模型只写一次的机制意味着 app 类型上线必须有运维介入（force_write_model 或等价 runbook）；参考 F048 迁移在存量环境被拦的教训（memory），需要把『模型升版+重启顺序+灰度（dual_model_mode 尚在）』写进发布方案，否则新类型的 check 全部 fail 向兜底路径
- 【fail-closed 语义与现状有出入】PRD NFR-1.4 要求『权限评估失败即报错，绝不回退』，但现有 check() 在 FGA 不可用时刻意回退 owner/implicit（permission_service.py:194-212 注释），list 回退 creator+租户管理员 scope——回退是收窄而非放行，但『报错 vs 收窄放行 owner』的口径需要与 PRD 对齐，app 运行时链路若要更严必须显式传参或新增严格模式
- 【allow-all 短路与受限委托红线】super_admin（is_admin L1）与子租户管理员（tenant gate owner 短路）是仅有的两个 allow-all 短路；开放 API PRD 已判定禁止代表这两类身份做委托——app 运行时以用户身份评估权限时必须继承该六道准入约束（memory：v2 openapi auth D2 改判）
- 【ListObjects 可靠性】代码自述 list_objects 在元组缺失/不稳时会返回空（application_permission_service.py:108-114 docstring），现网靠绑定表并集兜底；app 可见性若只依赖 FGA ListObjects 会复现同类空窗，建议沿用双源并集模式
- 【C4/C3 宪法】新 app 类型的一切检查必须走 PermissionService→OpenFGA（C4），新表须注册租户感知模块并注意租户过滤只拦 SELECT 的坑（C3；批量 UPDATE/DELETE 手写 tenant 条件）
- 【多处硬编码类型映射易漏】FlowType↔object_type 映射散落（application_permission_service._FLOW_TYPE_TO_OBJECT_TYPE、workflow.py object_type_for_flow_type、TagDao ResourceTypeEnum、legacy_rbac_sync_service._fga_object_types）——加 app 时漏一处即静默失效
- 【缓存一致性】PermissionCache 10s TTL + relation_roster_cache 版本缓存 + F037 浏览缓存方向——GOV-01『即时生效』依赖 invalidate_user 全覆盖，若 app 授权引入新主体展开路径需保证 affected_user_ids 计算完整（部门子树展开已有实现可复用）

## open_questions
- app 的『可见范围』映射到哪个 relation？最小方案 = viewer（can_read 即入口+广场可见），但 PRD 还有 use（使用）语义——是 viewer 一档搞定还是仿 application 模板拆 view_app/use_app 细粒度？决定模板设计与授权弹窗档位下拉
- app 资产落库形态：复用 flow 表新增 FlowType（列表/标签/广场全链路自动继承，但 per-type dispatch 走 workflow 同构路径）还是独立新表（更干净但 7 处 dispatch + 列表通道 + TagDao 全要新做）？直接决定权限接入工作量
- 发布面（owner 打开授权弹窗的地方）在哪个前端？若在 client 工作台，需要把 platform 的完整 PermissionDialog 移植/通用化到 client（Recoil/shadcn 技术栈不同，不能直接复制）；若在 platform 构建页则近乎零成本
- FGA 模型升级的部署策略要拍板：一次性 force_write_model 运维步骤、还是新增『MODEL_VERSION 比对自动写新模型』机制（后者是平台级改进，超出本 PRD 但一劳永逸）；以及是否启用 dual_model_mode 灰度
- GOV-01 审计的实现口径：授权变更事件接现有 audit 模块（api/v1/audit）还是审批中心事件流？租户管理员代调的『操作人以本人计』需要审计记录结构支持 actor≠owner
- 租户管理员在『应用管理列表』代 owner 调整时，是否允许其看到 owner-only 动作（删除/回滚）置灰而非隐藏（PRD §矩阵注明确 owner-only 不可代行，但 UI 呈现方式未定）
